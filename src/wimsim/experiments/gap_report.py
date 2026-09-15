"""The sim-to-real gap report: where the simulator and the sensor disagree, measured.

Buildspec, phase 6: "sim-to-real gap report (compares noise PSD, drift rate, pulse shape between
synthetic and real; fits simulator parameters to the real passes)".

``docs/sim-to-real.md`` already contains this analysis, done by hand in phase 3. That is exactly the
problem it needs solving: a hand-run analysis is a claim about one afternoon. The recordings will be
re-imported, the model will change, and nobody will redo it. Making it a command is what turns those
paragraphs into something that can be re-run, and disagreed with.

**It is a comparison, not a verdict.** There is no pass mark, because a simulator that matched a
real sensor on every statistic would be suspicious rather than reassuring -- it would mean the
statistics were not discriminating. What is useful is a list of where the two differ and by how
much, and a set of ``--set`` lines that move the model towards the recording without anybody
retyping a number out of a report.

Three things are compared, and each was chosen because getting it wrong in phase 3 cost something:

* **Noise, in bands rather than as one number.** A single standard deviation over a real recording
  counts mains hum as noise. That is how the model came to ship with mains switched off and a white
  sigma that had quietly absorbed it -- and mains is *coherent*, so unlike white noise it does not
  average down over a pulse. Measured on ``S1_nominal``, enabling it at the real amplitude moved MAE
  from 1.13 to 6.42 kg and coverage from 0.906 to 0.750.
* **Drift, as a spectral slope with an explicit resolution caveat.** The real slope is -1.96 to
  -2.65, i.e. Brownian rather than flicker. Sixty seconds of recording gives about a decade and a
  half of low-frequency resolution and cannot separate a random walk from a slow trend, so the
  report says how many decades it actually resolved instead of leaving a reader to assume.
* **Pulse shape, by fitting rather than by eye.** Four candidates against a real crossing, ranked by
  residual. Phase 3 found the parabola won on five of six events at 5.2 % -- and that the residual
  5 % is real structure rather than noise, which is why the shape is a defensible primitive and not
  a claim of exactness.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any

import numpy as np

__all__ = [
    "CrossingFit",
    "DriftEstimate",
    "GapReport",
    "NoiseComparison",
    "NoiseFit",
    "PulseComparison",
    "compare_noise",
    "compare_pulse_shape",
    "estimate_drift_rate",
    "find_pulse_window",
    "fit_crossing",
    "fit_noise_parameters",
]

#: Frequency bands the model has knobs for. A full periodogram is not a finding; these are.
BANDS: dict[str, tuple[float, float]] = {
    "drift": (0.0, 1.0),
    "low": (1.0, 10.0),
    "mains": (45.0, 55.0),
    "pulse": (100.0, 1000.0),
    "high": (1000.0, np.inf),
}

MAINS_HZ = 50.0
#: Where the "local floor" beside mains is measured, for the excess-over-floor figure.
_MAINS_SIDEBAND = (30.0, 45.0, 55.0, 70.0)

_MIN_SAMPLES = 4096


def _welch(signal: np.ndarray, fs: float, segment: int = 8192) -> tuple[np.ndarray, np.ndarray]:
    """Welch PSD with a Hann window and 50 % overlap.

    Written out rather than taken from ``scipy.signal.welch`` because it is fifteen lines and
    because ``experiments/`` should not acquire a scipy dependency for one estimator that the
    project can state exactly.
    """
    x = np.asarray(signal, dtype=np.float64)
    x = x - x.mean()
    segment = min(segment, x.size)
    step = segment // 2
    window = np.hanning(segment)
    scale = 1.0 / (fs * (window**2).sum())

    starts = range(0, x.size - segment + 1, step)
    accumulated = np.zeros(segment // 2 + 1)
    count = 0
    for start in starts:
        chunk = x[start : start + segment] * window
        spectrum = np.abs(np.fft.rfft(chunk)) ** 2
        accumulated += spectrum
        count += 1
    psd = accumulated / max(count, 1) * scale
    psd[1:-1] *= 2.0  # one-sided
    return np.fft.rfftfreq(segment, 1.0 / fs), psd


def _band_power(freqs: np.ndarray, psd: np.ndarray, low: float, high: float) -> float:
    mask = (freqs >= low) & (freqs < high)
    if not mask.any():
        return 0.0
    return float(np.trapezoid(psd[mask], freqs[mask]))


def _mains_amplitude(freqs: np.ndarray, psd: np.ndarray) -> tuple[float, float]:
    """Amplitude of the 50 Hz line, and how far it stands above the floor beside it, in dB.

    Amplitude rather than power because that is the unit the config takes, and excess-over-floor
    rather than absolute power because "50 Hz is present" says nothing -- every mains-powered
    instrument has some. What matters is whether it dominates.
    """
    line = (freqs >= MAINS_HZ - 2.0) & (freqs <= MAINS_HZ + 2.0)
    if not line.any():
        return 0.0, 0.0
    resolution = float(freqs[1] - freqs[0])
    line_power = float(psd[line].sum() * resolution)

    lo1, hi1, lo2, hi2 = _MAINS_SIDEBAND
    floor_mask = ((freqs >= lo1) & (freqs < hi1)) | ((freqs > lo2) & (freqs <= hi2))
    floor = float(np.median(psd[floor_mask])) if floor_mask.any() else 0.0

    # A sinusoid of amplitude A has total power A^2/2 in its line.
    amplitude = math.sqrt(max(2.0 * line_power, 0.0))
    peak = float(psd[line].max())
    excess_db = 10.0 * math.log10(peak / floor) if floor > 0 and peak > 0 else 0.0
    return amplitude, excess_db


@dataclass(frozen=True, slots=True)
class NoiseComparison:
    """Reference (synthetic) against candidate (real), band by band."""

    reference_sigma: float
    candidate_sigma: float
    reference_mains_amplitude: float
    candidate_mains_amplitude: float
    reference_mains_db: float
    candidate_mains_db: float
    reference_band_power: dict[str, float]
    candidate_band_power: dict[str, float]

    @property
    def sigma_ratio(self) -> float:
        return self.candidate_sigma / self.reference_sigma if self.reference_sigma else math.inf

    def to_dict(self) -> dict[str, Any]:
        return {
            "reference_sigma": self.reference_sigma,
            "candidate_sigma": self.candidate_sigma,
            "sigma_ratio": self.sigma_ratio,
            "reference_mains_amplitude": self.reference_mains_amplitude,
            "candidate_mains_amplitude": self.candidate_mains_amplitude,
            "candidate_mains_db": self.candidate_mains_db,
        }


def _white_sigma(freqs: np.ndarray, psd: np.ndarray, fs: float) -> float:
    """The broadband floor, measured where mains and its harmonics are not.

    The median of the PSD above the harmonics, times the bandwidth. A plain standard deviation
    over the signal would count the hum, which is precisely the mistake that put a mains-inflated
    sigma into the shipped config.
    """
    mask = freqs > 300.0
    for harmonic in range(1, 7):
        centre = MAINS_HZ * harmonic
        mask &= ~((freqs > centre - 3.0) & (freqs < centre + 3.0))
    if not mask.any():
        mask = freqs > 0.0
    density = float(np.median(psd[mask]))
    return math.sqrt(max(density * fs / 2.0, 0.0))


def compare_noise(reference: np.ndarray, candidate: np.ndarray, *, fs: float) -> NoiseComparison:
    """Compare two streams' noise, in bands the model has knobs for."""
    for name, signal in (("reference", reference), ("candidate", candidate)):
        if np.asarray(signal).size < _MIN_SAMPLES:
            raise ValueError(
                f"{name} is too short: {np.asarray(signal).size} samples, at least {_MIN_SAMPLES} "
                "are needed to resolve the bands this report is about"
            )

    ref_f, ref_psd = _welch(reference, fs)
    can_f, can_psd = _welch(candidate, fs)

    ref_amp, ref_db = _mains_amplitude(ref_f, ref_psd)
    can_amp, can_db = _mains_amplitude(can_f, can_psd)

    return NoiseComparison(
        reference_sigma=_white_sigma(ref_f, ref_psd, fs),
        candidate_sigma=_white_sigma(can_f, can_psd, fs),
        reference_mains_amplitude=ref_amp,
        candidate_mains_amplitude=can_amp,
        reference_mains_db=ref_db,
        candidate_mains_db=can_db,
        reference_band_power={
            k: _band_power(ref_f, ref_psd, lo, hi) for k, (lo, hi) in BANDS.items()
        },
        candidate_band_power={
            k: _band_power(can_f, can_psd, lo, hi) for k, (lo, hi) in BANDS.items()
        },
    )


@dataclass(frozen=True, slots=True)
class NoiseFit:
    """Simulator parameters fitted to a real recording."""

    white_sigma: float
    mains_amplitude: float
    baseline: float

    def as_overrides(self) -> list[str]:
        """``--set`` lines. The point of fitting is that the answer is usable without retyping.

        The paths are the real ones and ``tests/test_gap_report.py`` loads a config through them,
        because ``--set`` refuses a key that does not already exist: a path that is merely
        plausible fails at the terminal, after the fit has been run and thrown away.

        ``mains.enabled`` is set alongside the amplitude because S1 ships with mains off. Handing
        back an amplitude and leaving the switch alone would produce a config that ignores the
        number just measured, which is worse than an error -- it looks applied.
        """
        return [
            f"scenario.noise.white_sigma={self.white_sigma:.4g}",
            "scenario.noise.mains.enabled=true",
            f"scenario.noise.mains.amplitude={self.mains_amplitude:.4g}",
            f"scenario.zero_drift.q0={self.baseline:.4g}",
        ]

    def to_dict(self) -> dict[str, Any]:
        return {
            "white_sigma": self.white_sigma,
            "mains_amplitude": self.mains_amplitude,
            "baseline": self.baseline,
        }


def fit_noise_parameters(signal: np.ndarray, *, fs: float) -> NoiseFit:
    """Estimate the model's noise parameters from a recording."""
    x = np.asarray(signal, dtype=np.float64)
    if x.size < _MIN_SAMPLES:
        raise ValueError(f"too short to fit: {x.size} samples, {_MIN_SAMPLES} needed")
    freqs, psd = _welch(x, fs)
    amplitude, _db = _mains_amplitude(freqs, psd)
    return NoiseFit(
        white_sigma=_white_sigma(freqs, psd, fs),
        mains_amplitude=amplitude,
        baseline=float(np.median(x)),
    )


@dataclass(frozen=True, slots=True)
class DriftEstimate:
    """The low-frequency slope, and how much of it the recording could actually see."""

    slope: float
    character: str
    """white | flicker | brownian -- the nearest of the three, by slope."""
    decades_resolved: float
    caveat: str | None

    def to_dict(self) -> dict[str, Any]:
        return {
            "slope": self.slope,
            "character": self.character,
            "decades_resolved": self.decades_resolved,
            "caveat": self.caveat,
        }


def estimate_drift_rate(signal: np.ndarray, *, fs: float, f_max: float = 5.0) -> DriftEstimate:
    """Fit ``log PSD = a + slope * log f`` over the low-frequency band.

    Slope near 0 is white, -1 is flicker, -2 is Brownian. The real recordings measure -1.96 to
    -2.65, which is why the model's random walk is doing the work and its pink term is not.
    """
    x = np.asarray(signal, dtype=np.float64)
    if x.size < _MIN_SAMPLES:
        raise ValueError(f"too short: {x.size} samples, {_MIN_SAMPLES} needed")

    # A long segment, because low-frequency resolution is exactly what is being measured.
    freqs, psd = _welch(x, fs, segment=min(x.size, 1 << 17))
    mask = (freqs > 0.0) & (freqs <= f_max) & (psd > 0.0)
    if mask.sum() < 4:
        raise ValueError("not enough low-frequency bins to fit a slope")

    slope, _intercept = np.polyfit(np.log10(freqs[mask]), np.log10(psd[mask]), 1)
    slope = float(slope)

    character = min(
        (("white", 0.0), ("flicker", -1.0), ("brownian", -2.0)),
        key=lambda pair: abs(slope - pair[1]),
    )[0]

    lowest = float(freqs[mask][0])
    decades = math.log10(f_max / lowest) if lowest > 0 else 0.0
    caveat = None
    if decades < 2.0:
        caveat = (
            f"only {decades:.1f} decades of low-frequency resolution ({x.size / fs:.0f} s of "
            "data): this cannot separate a random walk from a slow trend, so the slope is "
            "indicative and re-deriving the drift model from it would be over-fitting one minute"
        )
    return DriftEstimate(slope=slope, character=character, decades_resolved=decades, caveat=caveat)


@dataclass(frozen=True, slots=True)
class PulseComparison:
    """Which shipped pulse shape a real crossing actually looks like."""

    best_shape: str
    residuals: dict[str, float]
    fwhm_s: float

    def to_dict(self) -> dict[str, Any]:
        return {
            "best_shape": self.best_shape,
            "fwhm_s": self.fwhm_s,
            **{f"residual_{k}": v for k, v in self.residuals.items()},
        }


def _candidate_shapes(u: np.ndarray) -> dict[str, np.ndarray]:
    """Unit-peak shapes on a normalised axis where +-1 is the half-width at half maximum."""
    return {
        "gaussian": np.exp(-0.5 * (u / 0.8493218) ** 2),  # HWHM at u = 1
        "parabola": np.clip(1.0 - (u / math.sqrt(2.0)) ** 2, 0.0, None),
        "raised_cosine": np.where(np.abs(u) <= 2.0, 0.5 * (1.0 + np.cos(np.pi * u / 2.0)), 0.0),
        "triangle": np.clip(1.0 - np.abs(u) / 2.0, 0.0, None),
    }


def _edge_baseline(y: np.ndarray, edge_fraction: float = 0.1) -> float:
    """The zero line, taken from the *edges* of the window rather than from all of it.

    The obvious choice is the median of the whole window, and it is wrong for exactly the reason a
    phase-3 bug in the real-data validator was wrong: on a window that is mostly pulse, the median
    *is* part of the pulse. Subtracting it pulled a Gaussian down by 0.15, and after renormalising
    to unit peak the shape was distorted enough that a raised cosine fitted it better than a
    Gaussian did -- a fitter that could not identify the shape it was handed.

    The edges are the part of a crossing window that is reliably baseline, so that is where the
    baseline is measured.
    """
    n = max(int(round(y.size * edge_fraction)), 1)
    edges = np.concatenate([y[:n], y[-n:]])
    return float(np.median(edges))


def _smooth(y: np.ndarray, fraction: float = 0.01) -> np.ndarray:
    """Centred moving average over a small fraction of the window.

    High-frequency noise is not shape, and it has to come off before a shape is fitted -- for a
    reason measured on ``20260209_cintron1`` rather than assumed. That crossing is 1.7 s wide with
    a peak near 4 microstrain and per-sample noise of 0.46, so its largest *sample* stands 77 %
    above the pulse. Normalising by it scaled the real shape down to 0.57 of unit height and every
    candidate then fitted equally badly: residuals 0.346 to 0.370, a ranking carrying no
    information.

    One percent of the window is short against any pulse worth fitting (30 ms on that recording,
    against a 1.7 s crossing) and long enough to average the sample noise down by an order of
    magnitude.
    """
    width = int(y.size * fraction)
    if width < 3:
        return y
    kernel = np.ones(width) / width
    # `edge` padding rather than zero: a zero-padded convolution pulls the ends of the window
    # towards zero, which is precisely where the baseline is measured.
    padded = np.pad(y, (width // 2, width - width // 2 - 1), mode="edge")
    return np.convolve(padded, kernel, mode="valid")


#: How much of a window's total excursion its outer edges may span before the window is judged to
#: contain part of a pulse rather than a whole one.
_MAX_EDGE_SPAN = 0.25


def _refuse_if_clipped(y: np.ndarray, edge_fraction: float = 0.1) -> None:
    """Refuse a window that does not contain the whole pulse.

    Regression: two of the sixteen real channel-runs came back with an FWHM of exactly 3000.0 ms on
    a 3000 ms window. That is not a 3 s crossing, it is a crossing the window cut, and the shape
    ranked from it is a ranking of whichever part happened to fit -- a number that looks like a
    measurement of a vehicle but is a measurement of the window.

    The obvious test, "is the signal still above half its peak at the edge", does not work here,
    because :func:`_edge_baseline` has already subtracted the edge level: a clipped pulse arrives
    looking like a small narrow one sitting on a high baseline. What actually separates the two
    cases is whether the window contains *baseline at all*. In a well-formed window the outer
    tenths are flat to within the noise; in a clipped one the signal is still climbing through
    them, so they span a large fraction of the whole excursion.
    """
    n = max(int(round(y.size * edge_fraction)), 1)
    edges = np.concatenate([y[:n], y[-n:]])
    total = float(np.max(y) - np.min(y))
    if total <= 0.0:
        return  # flat; `compare_pulse_shape` reports that more precisely a few lines later
    if float(np.max(edges) - np.min(edges)) / total > _MAX_EDGE_SPAN:
        raise ValueError(
            "pulse is clipped by the window: its edges are still on the slope rather than at "
            "baseline, so the width measured here would be the window's own -- widen the window"
        )


def compare_pulse_shape(pulse: np.ndarray, *, dt_s: float) -> PulseComparison:
    """Rank the shipped pulse shapes against one real crossing, by normalised RMS residual.

    The window is normalised to unit peak and to its own half-width, so the comparison is about
    *shape* and not about amplitude or duration -- both of which the model already fits from speed
    and load.
    """
    y = _smooth(np.asarray(pulse, dtype=np.float64))
    _refuse_if_clipped(y)
    y = y - _edge_baseline(y)
    peak = float(np.max(np.abs(y)))
    if peak <= 0.0 or not np.isfinite(peak):
        raise ValueError("no pulse in this window: it is flat, so there is no shape to fit")
    y = y / peak * np.sign(y[int(np.argmax(np.abs(y)))])

    above = np.flatnonzero(y >= 0.5)
    if above.size < 3:
        raise ValueError("no pulse in this window: nothing rises above half of its own peak")
    hwhm_samples = (above[-1] - above[0]) / 2.0
    if hwhm_samples <= 0:
        raise ValueError("no pulse in this window: it has no measurable width")

    centre = float(np.argmax(np.abs(y)))
    u = (np.arange(y.size) - centre) / hwhm_samples

    residuals: dict[str, float] = {}
    for name, shape in _candidate_shapes(u).items():
        residual = y - shape
        residuals[name] = float(np.sqrt(np.mean(residual**2)))

    return PulseComparison(
        best_shape=min(residuals, key=residuals.get),
        residuals=residuals,
        fwhm_s=2.0 * hwhm_samples * dt_s,
    )


def find_pulse_window(
    signal: np.ndarray,
    *,
    fs: float,
    half_width_s: float = 1.5,
    min_snr: float = 8.0,
) -> np.ndarray | None:
    """Cut a window around the largest crossing in a recording, or return ``None`` if there is none.

    :func:`compare_pulse_shape` needs a window containing one pulse. On a real recording nobody has
    labelled the crossings, so the report has to find one first.

    The scale is the median absolute *successive difference*, not a standard deviation. A standard
    deviation grows with the pulse it is being used to detect, so a large enough crossing raises its
    own threshold out of reach -- the phase-3 bug in the real-data validator, which is why the same
    mistake is worth naming here. A successive difference sees only sample-to-sample noise, and a
    pulse spanning a few hundred samples of a few hundred thousand cannot move its median.

    Returning ``None`` matters as much as returning a window: a minute of empty road is a valid
    recording, and fitting a shape to its largest noise excursion would produce a confident answer
    about nothing.
    """
    x = np.asarray(signal, dtype=np.float64)
    if x.size < 64:
        return None

    step = max(x.size // 200_000, 1)
    sigma = float(np.median(np.abs(np.diff(x[::step])))) * 1.4826 / math.sqrt(2.0)
    if not (sigma > 0.0) or not np.isfinite(sigma):
        return None

    deviation = np.abs(x - float(np.median(x)))
    peak = int(np.argmax(deviation))
    if deviation[peak] < min_snr * sigma:
        return None

    half = max(int(round(half_width_s * fs)), 2)
    return x[max(peak - half, 0) : min(peak + half, x.size)]


#: Half-widths tried, in seconds. Spans a highway crossing (tens of milliseconds) through the
#: low-speed drive-overs the project has recordings of (about a second).
_HALF_WIDTHS: tuple[float, ...] = (0.25, 0.5, 0.75, 1.0, 1.5, 2.0, 3.0)

#: How far two windows' FWHM may differ and still count as the same measurement.
_FWHM_AGREEMENT = 0.15


@dataclass(frozen=True, slots=True)
class CrossingFit:
    """The pulse comparison, plus the evidence that its width is a property of the vehicle."""

    comparison: PulseComparison | None
    half_width_s: float | None
    agreeing: int
    """How many window widths independently returned this FWHM."""
    tried: int
    spread: float
    """Fractional range of the agreeing FWHMs. 0 means every width returned the same number."""
    note: str

    def to_dict(self) -> dict[str, Any]:
        base: dict[str, Any] = {
            "half_width_s": self.half_width_s,
            "agreeing_widths": self.agreeing,
            "tried_widths": self.tried,
            "fwhm_spread": self.spread,
            "note": self.note,
        }
        if self.comparison is not None:
            base.update(self.comparison.to_dict())
        return base


def fit_crossing(
    signal: np.ndarray,
    *,
    fs: float,
    half_widths: tuple[float, ...] = _HALF_WIDTHS,
) -> CrossingFit:
    """Find the largest crossing in a recording and fit a shape to it, at several window widths.

    Nobody tells the report how wide the crossing is, and the window width decides the answer in
    both directions: too narrow and the fit measures the window rather than the vehicle, too wide
    and the drifting baseline dominates it. Measured on ``20260209_cintron1/Tenzo1``, a half-width
    of 0.75 s clips the pulse and 4 s lets the Brownian drift trip the baseline-flatness check --
    while every width in between returns 890 to 942 ms.

    That agreement is the point. A width that holds at one window and nowhere else is a property
    of the window, so this reports a number only when at least two widths independently find it,
    and says how far apart they were. It is the one check here that a wrong answer cannot pass by
    being confident.
    """
    fits: list[tuple[float, PulseComparison]] = []
    reasons: list[str] = []
    for half_width in half_widths:
        window = find_pulse_window(signal, fs=fs, half_width_s=half_width)
        if window is None:
            reasons.append("no excursion")
            continue
        try:
            fits.append((half_width, compare_pulse_shape(window, dt_s=1.0 / fs)))
        except ValueError as exc:
            reasons.append(str(exc).split(":")[0])

    tried = len(half_widths)
    if not fits:
        summary = ", ".join(sorted(set(reasons))) or "no window could be cut"
        return CrossingFit(
            comparison=None,
            half_width_s=None,
            agreeing=0,
            tried=tried,
            spread=math.inf,
            note=f"No shape fitted at any of {tried} window widths: {summary}.",
        )

    widths = np.array([c.fwhm_s for _hw, c in fits])
    reference = float(np.median(widths))
    agreeing = [
        (hw, c)
        for (hw, c), w in zip(fits, widths, strict=True)
        if abs(w - reference) <= _FWHM_AGREEMENT * reference
    ]
    if len(agreeing) < 2:
        return CrossingFit(
            comparison=None,
            half_width_s=None,
            agreeing=len(agreeing),
            tried=tried,
            spread=math.inf,
            note=(
                f"{len(fits)} of {tried} window widths produced a shape but no two agreed on a "
                "width, so the number would be a property of whichever window was chosen."
            ),
        )

    agreed = np.array([c.fwhm_s for _hw, c in agreeing])
    spread = float(agreed.max() / agreed.min() - 1.0)
    half_width, best = min(agreeing, key=lambda pair: pair[1].residuals[pair[1].best_shape])
    return CrossingFit(
        comparison=best,
        half_width_s=half_width,
        agreeing=len(agreeing),
        tried=tried,
        spread=spread,
        note=(
            f"{len(agreeing)} of {tried} window widths agree on {best.fwhm_s * 1e3:.0f} ms to "
            f"within {spread:.1%}; the fit shown is from the +-{half_width:g} s window, which "
            "resolved it best."
        ),
    )


@dataclass
class GapReport:
    """Everything the comparison found, and the overrides that would close it."""

    real_run: str
    scenario: str
    noise: NoiseComparison
    drift: DriftEstimate
    fit: NoiseFit
    pulse: PulseComparison | None = None
    notes: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "real_run": self.real_run,
            "scenario": self.scenario,
            "noise": self.noise.to_dict(),
            "drift": self.drift.to_dict(),
            "fit": self.fit.to_dict(),
            "pulse": None if self.pulse is None else self.pulse.to_dict(),
            "overrides": self.fit.as_overrides(),
        }

    def to_markdown(self) -> str:
        n, d = self.noise, self.drift
        lines = [
            f"# Sim-to-real gap: {self.real_run} against {self.scenario}",
            "",
            "A comparison, not a verdict. There is no pass mark here: a simulator that matched a "
            "real sensor on every statistic would mean the statistics were not discriminating. "
            "What follows is where the two differ and by how much.",
            "",
            "## Noise",
            "",
            "| | synthetic | real | ratio |",
            "|---|---|---|---|",
            f"| white sigma | {n.reference_sigma:.3e} | {n.candidate_sigma:.3e} | "
            f"{n.sigma_ratio:.2f}x |",
            f"| 50 Hz amplitude | {n.reference_mains_amplitude:.3e} | "
            f"{n.candidate_mains_amplitude:.3e} | |",
            f"| 50 Hz above floor | {n.reference_mains_db:.1f} dB | {n.candidate_mains_db:.1f} dB "
            "| |",
            "",
            "Mains is measured separately from the white floor on purpose. A single standard "
            "deviation counts the hum as noise, and mains is *coherent* -- unlike white noise it "
            "does not average down over a pulse, so folding the two together hides the term that "
            "actually moves the mass.",
            "",
            "## Drift",
            "",
            f"Low-frequency slope **{d.slope:.2f}** ({d.character}); 0 is white, -1 flicker, "
            "-2 Brownian.",
        ]
        if d.caveat:
            lines += ["", f"> {d.caveat}"]

        if self.pulse is not None:
            lines += [
                "",
                "## Pulse shape",
                "",
                f"Best fit: **{self.pulse.best_shape}**, FWHM {self.pulse.fwhm_s * 1e3:.1f} ms.",
                "",
                "| shape | normalised RMS residual |",
                "|---|---|",
            ]
            for name, value in sorted(self.pulse.residuals.items(), key=lambda kv: kv[1]):
                lines.append(f"| {name} | {value:.3f} |")

        lines += [
            "",
            "## Fitted parameters",
            "",
            "Apply these to move the model towards this recording:",
            "",
            "```bash",
            "wimsim generate <scenario> --out <dir> \\",
        ]
        overrides = self.fit.as_overrides()
        for i, override in enumerate(overrides):
            tail = " \\" if i < len(overrides) - 1 else ""
            lines.append(f"  --set {override}{tail}")
        lines.append("```")

        if self.notes:
            lines += ["", "## Notes", ""]
            lines += [f"- {note}" for note in self.notes]
        return "\n".join(lines) + "\n"
