"""Stage 2 of the edge pipeline: conditioning the signal without destroying it.

Order of operations, and the reason for each:

1. **Despike.** Isolated outliers -- a single corrupted sample, an EMI hit -- are replaced by the
   local median. *Only* samples exceeding a robust deviation threshold are touched, and only when
   the excursion is short enough to be a spike rather than an axle. This is deliberately not a
   median filter: a median wide enough to remove a spike is also wide enough to flatten a 5 ms axle
   pulse, and the pulse is the measurement.
2. **Filter.** A causal moving average or Butterworth low-pass, whichever the config names. Causal
   because a station cannot look into the future; ``filtfilt`` is not available to a real edge
   device and pretending otherwise would flatter every latency and timestamp figure in the paper.

   The price is group delay. Compensating it by shifting sample *values* earlier would reintroduce
   exactly the clairvoyance that was just refused -- the output at *t* would depend on the input at
   *t + delay*. So what gets corrected is the **time axis**: the filtered sample is stamped with the
   time the underlying event actually happened, and the station pays for that with ``delay`` seconds
   of latency, which is what a real one does. ``group_delay_s`` is reported either way.
3. **Zero line.** A trailing median over ``zero_window_s``, recomputed every ``zero_update_s`` and
   held constant in between. The median is unbiased for symmetric noise and completely immune to
   vehicles while they occupy less than half the window -- which, with 10 ms pulses in a 2 s window,
   they overwhelmingly do. When they do not, the estimate is flagged rather than quietly biased.
4. **Temperature compensation.** Divide out the thermal gain factor implied by the *active
   calibration profile* and the *probe's* reading. Not the true sensor temperature: the preprocessor
   cannot see it and must not be able to.

``raw_value`` survives all four untouched. Buildspec section 5: "never discards raw". A filtering
decision made in phase 2 must not be able to destroy evidence phase 6 needs.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
from scipy import signal as sps

from wimsim.calibration import CalibrationProfile
from wimsim.core.config import PreprocessConfig
from wimsim.core.schemas import PreprocessingBlock
from wimsim.core.types import SampleBlock

__all__ = ["PreprocessedBlock", "Preprocessor"]

#: q25 - q05 of a standard normal. Converts that spread into a sigma estimate.
_IQ_SPREAD_TO_SIGMA = 1.0 / 0.9704


def _lerp(a: float, b: float, t: float) -> float:
    """``numpy.lib._function_base_impl._lerp``, reproduced exactly, branch included.

    The branch is not cosmetic. Above t = 0.5 numpy interpolates down from ``b`` instead of up
    from ``a``, and the two orders differ in the last bit. This function exists so the quantiles
    below are *bit-identical* to ``np.quantile`` rather than merely equal to within rounding --
    every sweep in this project is compared against sweeps run before this code existed, and a
    one-ulp difference in a zero-line estimate propagates into a different mass.
    """
    diff = b - a
    out = a + t * diff
    if t >= 0.5:
        out = b - diff * (1.0 - t)
    return out


def _low_quantiles_and_median(window: np.ndarray) -> tuple[float, float, float, float]:
    """``q05, q10, q25, median`` from ONE partition of the window.

    Written out rather than left to ``np.median`` plus ``np.quantile`` because this is the hot
    path of the whole project: the zero tracker recomputes it every ``zero_stride`` samples, which
    on a sixteen-hour scenario is 230,000 times per run, and profiling put 61 % of a sweep run
    inside it. Two separate numpy calls partition the same 15,000-sample window twice and then
    spend more time in ``np.quantile``'s Python wrapper -- ``_get_indexes``, ``_lerp``,
    ``_ureduce``, ``issubdtype`` -- than in the partition itself, because the wrapper's cost is
    per *call* and the quantile array has three elements.

    Measured on a representative window: 451 us for the two-call version against 216 us for this
    one, and 1.44x on a whole sweep run. Verified bit-identical to ``np.median`` and
    ``np.quantile`` over 4,000 windows spanning constant arrays, heavy ties, both parities of
    length, and the degenerate zero-scale case -- see ``tests/test_preprocess.py``.
    """
    n = window.size
    virtual = [q * (n - 1) for q in (0.05, 0.10, 0.25)]
    lower = [int(np.floor(v)) for v in virtual]
    # One partition serving every index either computation needs, the median's pair included.
    kth = sorted({*lower, *(min(i + 1, n - 1) for i in lower), (n - 1) // 2, n // 2})
    part = np.partition(window, kth)
    q05, q10, q25 = (
        _lerp(float(part[i]), float(part[min(i + 1, n - 1)]), v - i)
        for v, i in zip(virtual, lower, strict=True)
    )
    # np.median's own definition: the mean of the middle pair, which for odd n is one element
    # counted twice and therefore itself.
    median = float(np.mean(part[[(n - 1) // 2, n // 2]]))
    return q05, q10, q25, median


def _robust_sigma(window: np.ndarray) -> float:
    """Noise scale from low quantiles, immune to positive-going vehicles.

    A plain MAD would be inflated by every pass in the window. ``q25 - q05`` sits entirely inside
    the quiet floor while vehicles occupy less than three quarters of the window, which they always
    do, and is a consistent estimator of sigma for Gaussian noise.
    """
    if window.size < 32:
        return 0.0
    q05, q25 = np.quantile(window, [0.05, 0.25])
    return float(q25 - q05) * _IQ_SPREAD_TO_SIGMA


def _occupancy_from(q05: float, q10: float, q25: float, window: np.ndarray) -> float:
    """The occupancy fraction, given quantiles already computed from this window.

    ``count_nonzero`` rather than ``np.mean`` over the comparison: both sum the same boolean
    array, and a count below 2**53 divides to exactly the same float64.
    """
    scale = q25 - q05
    threshold = q10 if scale <= 0.0 else q10 + 8.0 * scale
    return float(np.count_nonzero(window > threshold)) / window.size


def _occupancy(window: np.ndarray) -> float:
    """Fraction of a window sitting well above its own uncontaminated floor.

    The median is the baseline only while vehicles occupy less than half the window. Detecting when
    that stops being true cannot itself use the median -- it would already be contaminated -- so the
    reference comes from low quantiles, which survive up to 75 % contamination, and the scale comes
    from the spread *within* the quiet floor.
    """
    if window.size < 8:
        return 0.0
    q05, q10, q25, _median = _low_quantiles_and_median(window)
    return _occupancy_from(q05, q10, q25, window)


def _release_long_runs(flags: np.ndarray, max_len: int) -> np.ndarray:
    """Clear any run of consecutive ``True`` longer than ``max_len``.

    Encodes "a spike is isolated" explicitly rather than hoping the median window implies it.
    """
    if not flags.any():
        return flags
    out = flags.copy()
    edges = np.flatnonzero(np.diff(np.concatenate([[False], flags, [False]]).astype(np.int8)))
    for start, stop in zip(edges[::2], edges[1::2], strict=True):
        if stop - start > max_len:
            out[start:stop] = False
    return out


@dataclass(frozen=True, slots=True)
class PreprocessedBlock:
    """Parallel arrays over one block. ``raw_value`` is the untouched input."""

    ts_us: np.ndarray
    t_s: np.ndarray
    raw_value: np.ndarray
    filtered_value: np.ndarray
    zero_estimate: np.ndarray
    compensated_value: np.ndarray
    temperature_c: np.ndarray
    valid: np.ndarray
    saturated: np.ndarray
    despiked: np.ndarray
    warming_up: np.ndarray
    """True until the zero-line window has filled. Events here deserve quality_flag=degraded."""
    zero_suspect: np.ndarray
    """True where too much of the zero window sat above the baseline for a median to mean anything."""
    temp_missing: np.ndarray
    channel_id: str = "ch0"

    @property
    def n(self) -> int:
        return int(self.ts_us.shape[0])


class Preprocessor:
    """Stateful, block-wise. Filter state and the zero-line history carry across blocks."""

    def __init__(
        self,
        cfg: PreprocessConfig,
        *,
        sample_rate_hz: float,
        profile: CalibrationProfile | None = None,
    ) -> None:
        self.cfg = cfg
        self.fs = float(sample_rate_hz)
        self._profile = profile

        self._b, self._a = self._design()
        self._zi: np.ndarray | None = None
        self.group_delay_s = self._group_delay()
        self._shift_s = self.group_delay_s if cfg.compensate_group_delay else 0.0
        self._shift_us = round(self._shift_s * 1e6)

        self._zero_window = max(int(round(cfg.zero_window_s * self.fs)), 1)
        self._zero_stride = max(int(round(cfg.zero_update_s * self.fs)), 1)
        #: trailing history, NaN where a sample was invalid. Holds exactly one window.
        self._history = np.full(self._zero_window, np.nan, dtype=np.float64)
        self._zero_level = float("nan")
        self._zero_is_suspect = False
        self._valid_seen = 0
        self._global_index = 0

        self._despike_pad = np.zeros(0, dtype=np.float64)
        self._scale_window = max(int(round(cfg.despike_scale_window_s * self.fs)), 64)
        self._scale_history = np.zeros(0, dtype=np.float64)
        self._noise_scale = 0.0

    # -- setup ------------------------------------------------------------------------------

    def _design(self) -> tuple[np.ndarray, np.ndarray]:
        cfg = self.cfg
        if cfg.filter == "none":
            return np.array([1.0]), np.array([1.0])
        if cfg.filter == "moving_average":
            return np.full(cfg.window, 1.0 / cfg.window), np.array([1.0])
        nyquist = 0.5 * self.fs
        if cfg.cutoff_hz is None or cfg.cutoff_hz >= nyquist:
            raise ValueError(
                f"cutoff_hz ({cfg.cutoff_hz}) must be below the Nyquist frequency ({nyquist} Hz)"
            )
        b, a = sps.butter(cfg.order, cfg.cutoff_hz / nyquist, btype="low")
        return np.asarray(b), np.asarray(a)

    def _group_delay(self) -> float:
        """DC group delay of the configured chain, seconds.

        Exact for a boxcar: ``(N-1)/2`` samples. For a rational filter the DC group delay also has
        a closed form, ``sum(n*b)/sum(b) - sum(n*a)/sum(a)``, which is what is used here. The true
        delay is frequency-dependent, so compensating by the DC value realigns the pulse
        approximately rather than exactly -- but DC is where the pulse energy is. Reported either
        way, so a consumer can decide whether it matters.

        ``scipy.signal.group_delay`` was used before and is worse in two ways at the cutoff-to-rate
        ratios this project now runs at. It samples the phase on a grid and reads the first bin,
        which at 5 Hz on 25 kHz is not close enough to DC; and its denominator is near-singular
        there, so it emits a page of warnings on every construction. Measured against the
        impulse-response centroid, which needs no phase unwrapping:

            order 4, 5 Hz at 25 kHz    scipy 2078.105   closed 2078.363   centroid 2078.364
            order 4, 2 Hz at 25 kHz    scipy 5250.823   closed 5240.821   centroid 5240.957

        So the closed form is the more accurate of the two where they disagree, not merely the
        quieter one.
        """
        if self.cfg.filter == "none":
            return 0.0
        if self.cfg.filter == "moving_average":
            return (self.cfg.window - 1) / 2.0 / self.fs
        n_b = np.arange(self._b.size)
        n_a = np.arange(self._a.size)
        delay = float((n_b @ self._b) / self._b.sum() - (n_a @ self._a) / self._a.sum())
        return delay / self.fs

    # -- profile ----------------------------------------------------------------------------

    def set_profile(self, profile: CalibrationProfile | None) -> None:
        """Activate a calibration profile mid-stream, as phase-5 recalibration will."""
        self._profile = profile

    @property
    def profile_id(self) -> str | None:
        return None if self._profile is None else self._profile.profile_id

    def describe(self) -> PreprocessingBlock:
        """What was done, in the form the event schema carries."""
        return PreprocessingBlock(
            filter=self.cfg.filter,
            cutoff_hz=self.cfg.cutoff_hz,
            order=self.cfg.order if self.cfg.filter == "butterworth" else None,
            zero_window_s=self.cfg.zero_window_s,
        )

    # -- stages -----------------------------------------------------------------------------

    def _despike(self, x: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
        """Replace isolated outliers with the local median.

        The window is **centred**, not trailing. A trailing window cannot tell the leading edge of a
        real axle pulse from a spike -- both are a sudden jump above a quiet history -- and would
        chew the front off every vehicle. A centred window can: at the peak of a 20-sample pulse the
        11-sample median is the pulse itself, so nothing is flagged, whereas at a one-sample spike
        the median is still the baseline.

        That costs ``despike_window // 2`` samples of look-ahead: 2.5 ms at 2 kHz, which a real edge
        device buys with a small input buffer. The previous block's tail supplies the left padding
        exactly; the right padding at the very end of a block is edge-replicated, so at most
        ``despike_window // 2`` samples per block are judged with a slightly asymmetric window.

        The comparison uses a **short median** and a **long noise scale**, and the split matters. An
        11-sample MAD has enormous sampling variance: thresholding against it at six deviations
        flags roughly one quiet Gaussian sample in three hundred, so a clean channel would come out
        "despiked" thousands of times an hour. The scale therefore comes from a one-second trailing
        window via low quantiles, which is stable to a couple of per cent and immune to vehicles.

        A run-length guard makes the "isolated" part explicit: a flagged run longer than
        ``despike_max_run`` is an excursion, not a spike, and is released. That bound has to be
        *small*. A centred median only tracks a pulse while the pulse is much wider than the window;
        at comparable widths the median sits near half-maximum, the peak trips the outlier test, and
        the despiker replaces the top of the vehicle with the middle of it. Measured, an 11-sample
        window took 19.8 % off a 10.6-sample car pulse and 0.6 % off a 42-sample truck pulse -- which
        does not merely add error, it makes the peak feature speed-dependent, destroying the one
        property that made it worth using.
        """
        cfg = self.cfg
        if not cfg.despike:
            return x, np.zeros(x.size, dtype=bool)

        half = cfg.despike_window // 2
        left = self._despike_pad if self._despike_pad.size == half else np.full(half, x[0])
        padded = np.concatenate([left, x, np.full(half, x[-1])])
        self._despike_pad = x[-half:].copy() if x.size >= half else x.copy()

        view = np.lib.stride_tricks.sliding_window_view(padded, cfg.despike_window)
        med = np.median(view, axis=1)

        scale = self._update_noise_scale(x)
        outlier = (
            np.abs(x - med) > cfg.despike_threshold * scale
            if scale > 0.0
            else np.zeros(x.size, dtype=bool)
        )
        kept = _release_long_runs(outlier, cfg.despike_max_run)
        return np.where(kept, med, x), kept

    def _update_noise_scale(self, x: np.ndarray) -> float:
        """Running robust noise scale over a trailing window, carried across blocks.

        One value per block rather than per sample: the channel's noise level does not change
        meaningfully inside a thirty-second block, and a per-sample estimate would cost far more
        than it could possibly buy.
        """
        buf = np.concatenate([self._scale_history, x])
        self._scale_history = buf[-self._scale_window :]
        estimate = _robust_sigma(self._scale_history)
        if estimate > 0.0:
            self._noise_scale = estimate
        return self._noise_scale

    def _filter(self, x: np.ndarray) -> np.ndarray:
        if self.cfg.filter == "none":
            return x.copy()
        if self._zi is None:
            # start from steady state at the first sample, so the filter does not ring in from zero
            self._zi = sps.lfilter_zi(self._b, self._a) * x[0]
        y, self._zi = sps.lfilter(self._b, self._a, x, zi=self._zi)
        return y

    def _track_zero(
        self, x: np.ndarray, valid: np.ndarray
    ) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
        """Trailing-median baseline, recomputed on a stride and held constant in between.

        Only *valid* samples enter the history. A stuck channel reports a constant, and letting that
        into the baseline would drag the baseline to wherever the channel got stuck -- so invalid
        samples are entered as NaN and skipped by ``nanmedian`` rather than dropped, which keeps the
        history aligned in time.

        Update points are chosen on the **global** sample index, so where they fall does not depend
        on how the stream happens to be blocked.
        """
        n = x.size
        window, stride = self._zero_window, self._zero_stride

        entries = np.where(valid, x, np.nan)
        buf = np.concatenate([self._history, entries])
        base = self._global_index - self._history.size  # global index of buf[0]

        # global indices in this block at which the estimate is recomputed
        first = -(-self._global_index // stride) * stride
        updates = np.arange(first, self._global_index + n, stride, dtype=np.int64)

        zero = np.full(n, self._zero_level, dtype=np.float64)
        suspect = np.full(n, self._zero_is_suspect, dtype=bool)

        for g in updates.tolist():
            end = g - base + 1  # buf slice end, inclusive of the update sample
            chunk = buf[max(end - window, 0) : end]
            # The filter allocates a copy of the whole window. On a channel with no dropout --
            # which is every sample of most runs -- the copy is the original, so the test is
            # cheaper than the copy it avoids and the result is the same array either way.
            if not np.isfinite(chunk).all():
                chunk = chunk[np.isfinite(chunk)]
            if chunk.size == 0:
                continue
            if chunk.size < 8:
                # _occupancy's own floor: too short for the quantiles to mean anything.
                self._zero_level = float(np.median(chunk))
                self._zero_is_suspect = 0.0 > self.cfg.zero_occupancy_warn
            else:
                q05, q10, q25, median = _low_quantiles_and_median(chunk)
                self._zero_level = median
                self._zero_is_suspect = (
                    _occupancy_from(q05, q10, q25, chunk) > self.cfg.zero_occupancy_warn
                )
            local = g - self._global_index
            zero[local:] = self._zero_level
            suspect[local:] = self._zero_is_suspect

        if not np.isfinite(self._zero_level):
            zero = np.where(np.isfinite(zero), zero, x)

        valid_before = self._valid_seen
        self._valid_seen += int(valid.sum())
        cumulative = valid_before + np.cumsum(valid.astype(np.int64))
        warming = cumulative < window

        self._history = buf[-window:] if buf.size >= window else buf
        self._global_index += n
        return zero, suspect, warming

    def _thermal_factor(self, temp_c: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
        """``1 + alpha*(T_probe - T_ref)`` from the active profile, and a missing-probe mask."""
        missing = ~np.isfinite(temp_c)
        if self._profile is None:
            return np.ones(temp_c.size), missing
        state = self._profile.state
        if state.temp_coeff == 0.0:
            return np.ones(temp_c.size), missing
        safe = np.where(missing, state.t_ref_c, temp_c)
        factor = 1.0 + state.temp_coeff * (safe - state.t_ref_c)
        # a factor at or below zero would invert the signal; refuse rather than produce nonsense
        return np.where(factor > 1e-6, factor, 1.0), missing

    # -- entry point -------------------------------------------------------------------------

    def process(self, block: SampleBlock) -> PreprocessedBlock:
        raw = np.asarray(block.raw_value, dtype=np.float64)
        despiked_values, despiked_mask = self._despike(raw)
        filtered = self._filter(despiked_values)
        zero, suspect, warming = self._track_zero(filtered, np.asarray(block.valid, dtype=bool))
        factor, temp_missing = self._thermal_factor(
            np.asarray(block.temperature_c, dtype=np.float64)
        )
        compensated = (filtered - zero) / factor
        if self.cfg.invert:
            # After the zero line is removed, not before: the zero-line tracker's median is
            # invariant to the flip, but `raw_value` is what the station reported and is
            # carried for provenance, so it stays as recorded.
            compensated = -compensated

        return PreprocessedBlock(
            ts_us=block.ts_us - self._shift_us,
            t_s=block.t_s - self._shift_s,
            raw_value=raw,
            filtered_value=filtered,
            zero_estimate=zero,
            compensated_value=compensated,
            temperature_c=block.temperature_c,
            valid=block.valid,
            saturated=block.saturated,
            despiked=despiked_mask,
            warming_up=warming,
            zero_suspect=suspect,
            temp_missing=temp_missing,
            channel_id=block.channel_id,
        )
