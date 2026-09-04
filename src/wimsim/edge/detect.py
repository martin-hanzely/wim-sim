"""Stage 3 of the edge pipeline: where a continuous signal becomes countable things.

Dual-threshold hysteresis on the compensated signal. A window opens when the signal rises above
``start_threshold`` and closes when it has stayed below ``end_threshold`` for ``end_hold_s``. The
gap between the thresholds is the hysteresis, and the hold is the debounce; both are needed.
Hysteresis alone reduces chatter from thousands of phantom axles to a handful, but a single noise
sample dipping past the lower threshold still splits one axle in two, and a split axle is a vehicle
counted twice. Minimum and maximum duration then reject blips and stuck channels, and both
rejections are *counted*, because a detector that silently discards things cannot be debugged from a
dashboard.

The detector works on a **rolling buffer**, not on one block at a time. That is not an
optimisation: a window can open in one block and close three blocks later, the walk-back to the
start of an excursion can cross a boundary, and the padded area integral needs samples from before
the window opened. Per-block arrays cannot supply any of those, so results would depend on where
the stream happened to be chopped -- and ``test_results_do_not_depend_on_block_size`` says they must
not.

Two levels of grouping exist, because a vehicle is not an axle:

``AxlePeak``
    One threshold excursion. On a bogie these are milliseconds apart.
``DetectedEvent``
    Axles separated by less than ``merge_gap_s`` merged into one vehicle. Merging costs latency --
    the detector cannot know an axle was the last until ``merge_gap_s`` of quiet has passed -- which
    is real and which a field device also pays.

**Both peak and area are emitted.** Which estimates mass better under noise is the experimental
question the buildspec refuses to pre-decide, so the detector's job is to produce both honestly.
Peak uses parabolic sub-sample interpolation, because phase 1 measured that the largest *sample*
undershoots a 5 ms pulse at 2 kHz by a systematic few tenths of a percent.

**What this stage cannot do: measure speed.** One sensor gives no baseline against which to time a
vehicle, so ``speed_mps`` stays ``None`` and the area feature cannot be speed-normalised. Axle time
differences are exposed instead: combined with an assumed axle spacing they imply a speed, which is
how a real single-sensor installation does it and which phase 6 can explore. This is a limitation of
the instrument, not of the code, and it is one reason the peak-versus-area comparison is worth
running rather than reasoning about.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from wimsim.core.config import DetectConfig
from wimsim.core.schemas import QualityFlag
from wimsim.edge.preprocess import PreprocessedBlock

__all__ = ["AxlePeak", "DetectedEvent", "EventDetector"]

_BUFFER_FIELDS = (
    "t_s",
    "ts_us",
    "comp",
    "raw",
    "temp",
    "saturated",
    "invalid",
    "warming_up",
    "zero_suspect",
)


@dataclass(frozen=True, slots=True)
class AxlePeak:
    """One threshold excursion."""

    t_start_s: float
    t_peak_s: float
    t_end_s: float
    peak: float
    area: float
    raw_peak: float
    raw_area: float
    n_samples: int


@dataclass(frozen=True, slots=True)
class DetectedEvent:
    """One vehicle: a group of axles close enough together to share a body."""

    ts_start_us: int
    ts_peak_us: int
    ts_end_us: int
    t_start_s: float
    t_peak_s: float
    t_end_s: float

    peak: float
    """Largest axle peak, compensated units. Not the sum: a peak is an instantaneous force."""
    area: float
    """Sum of axle areas, compensated units * seconds."""
    raw_peak: float
    raw_area: float
    """As above but before temperature compensation. The zero line is removed from both -- a peak
    measured from an arbitrary baseline is not a measurement."""

    axles: tuple[AxlePeak, ...]
    axle_dt_s: tuple[float, ...]
    """Gaps between consecutive axle peaks. With an assumed axle spacing these imply a speed."""

    saturated: bool
    has_invalid: bool
    warming_up: bool
    zero_suspect: bool
    truncated: bool
    """True when the stream ended before the window closed, so the features are incomplete."""

    temp_c: float | None = None
    """Probe reading at the peak sample, degC. The estimator's temperature coefficient is applied
    at this temperature, so a detection that does not carry one compensates at 0 degC -- which is
    what silently happened until phase 4 noticed the stored column was always null. Optional
    because a source need not have a temperature channel, not because it is unimportant."""

    channel_id: str = "ch0"

    @property
    def axle_count(self) -> int:
        return len(self.axles)

    @property
    def axle_peak_sum(self) -> float:
        """Sum of the axle peaks -- the quantity proportional to *mass*.

        ``peak`` is the largest axle, which is what the event schema reports as
        ``compensated_peak``: an instantaneous force, and the right thing to compare against an
        overload threshold. It is not a mass proxy. A vehicle's mass is carried by all of its axles,
        so conflating the two would weigh every truck as though it were its heaviest axle.
        """
        return float(sum(a.peak for a in self.axles))

    @property
    def raw_axle_peak_sum(self) -> float:
        return float(sum(a.raw_peak for a in self.axles))

    @property
    def duration_s(self) -> float:
        return self.t_end_s - self.t_start_s

    @property
    def quality_flag(self) -> QualityFlag:
        """Saturation, invalid samples or truncation make a measurement untrustworthy; a warming-up
        or suspect zero line makes it merely worse."""
        if self.saturated or self.has_invalid or self.truncated:
            return "suspect"
        if self.warming_up or self.zero_suspect:
            return "degraded"
        return "ok"


def _parabolic_vertex(y0: float, y1: float, y2: float) -> tuple[float, float]:
    """Vertex of the parabola through three equally spaced points, ``y1`` the middle.

    Returns ``(offset_in_samples, value)``. ``offset`` lies in [-0.5, 0.5] for a genuine maximum.
    """
    denom = y0 - 2.0 * y1 + y2
    if denom == 0.0:
        return 0.0, y1
    shift = 0.5 * (y0 - y2) / denom
    return shift, y1 - 0.25 * (y0 - y2) * shift


class EventDetector:
    """Stateful across blocks. A window, and a vehicle, may span any number of them."""

    def __init__(self, cfg: DetectConfig, *, sample_rate_hz: float) -> None:
        self.cfg = cfg
        self.fs = float(sample_rate_hz)
        self.dt = 1.0 / self.fs

        self._hold = max(int(round(cfg.end_hold_s * self.fs)), 1)
        #: enough history for the walk-back and for the padded area integral
        self._context = (
            int(np.ceil(cfg.max_duration_s * (1.0 + 2.0 * cfg.area_pad_widths) * self.fs))
            + self._hold
            + 8
        )

        self._buf: dict[str, np.ndarray] = {
            name: np.zeros(0, dtype=np.float64) for name in _BUFFER_FIELDS
        }
        self._buf["ts_us"] = np.zeros(0, dtype=np.int64)
        for flag in ("saturated", "invalid", "warming_up", "zero_suspect"):
            self._buf[flag] = np.zeros(0, dtype=bool)

        self._base = 0  # absolute index of self._buf[...][0]
        self._pos = 0  # absolute index of the next sample to examine
        self._open_start: int | None = None  # absolute index

        self._pending: list[AxlePeak] = []
        self._pending_flags = self._blank_flags()
        self._channel_id = "ch0"
        self._refractory_until = -np.inf
        self._last_close_t = -np.inf

        self.detected = 0
        self.rejected_too_short = 0
        self.rejected_too_long = 0

    # -- buffer ------------------------------------------------------------------------------

    @staticmethod
    def _blank_flags() -> dict[str, bool]:
        return {
            "saturated": False,
            "has_invalid": False,
            "warming_up": False,
            "zero_suspect": False,
            "truncated": False,
        }

    def _append(self, block: PreprocessedBlock) -> None:
        self._channel_id = block.channel_id
        incoming = {
            "t_s": block.t_s,
            "ts_us": block.ts_us,
            "comp": block.compensated_value,
            "raw": block.filtered_value - block.zero_estimate,
            "temp": block.temperature_c,
            "saturated": block.saturated,
            "invalid": ~block.valid,
            "warming_up": block.warming_up,
            "zero_suspect": block.zero_suspect,
        }
        for name, values in incoming.items():
            self._buf[name] = np.concatenate([self._buf[name], values])

    def _trim(self) -> None:
        """Drop history that can no longer be needed."""
        keep_from = self._pos if self._open_start is None else min(self._pos, self._open_start)
        cut = max(keep_from - self._context - self._base, 0)
        if cut <= 0:
            return
        for name in _BUFFER_FIELDS:
            self._buf[name] = self._buf[name][cut:]
        self._base += cut

    @property
    def _end(self) -> int:
        return self._base + self._buf["t_s"].size

    def _slice(self, name: str, lo: int, hi: int) -> np.ndarray:
        return self._buf[name][lo - self._base : hi - self._base]

    # -- feature extraction -------------------------------------------------------------------

    def _axle(self, start: int, stop: int) -> AxlePeak | None:
        """Build an axle from the absolute index range ``[start, stop)``."""
        t_s = self._slice("t_s", start, stop)
        comp = self._slice("comp", start, stop)
        raw = self._slice("raw", start, stop)
        if comp.size == 0:
            return None

        duration = float(t_s[-1] - t_s[0]) + self.dt
        if duration < self.cfg.min_duration_s:
            self.rejected_too_short += 1
            return None
        if duration > self.cfg.max_duration_s:
            self.rejected_too_long += 1
            return None

        i = int(np.argmax(comp))
        peak_t, peak_v = float(t_s[i]), float(comp[i])
        if self.cfg.subsample_peak and 0 < i < comp.size - 1:
            shift, value = _parabolic_vertex(float(comp[i - 1]), float(comp[i]), float(comp[i + 1]))
            if abs(shift) <= 1.0:
                peak_t, peak_v = peak_t + shift * self.dt, value

        return AxlePeak(
            t_start_s=float(t_s[0]),
            t_peak_s=peak_t,
            t_end_s=float(t_s[-1]),
            peak=peak_v,
            area=self._integrate(start, stop, "comp"),
            raw_peak=float(raw.max()),
            raw_area=self._integrate(start, stop, "raw"),
            n_samples=comp.size,
        )

    def _integrate(self, start: int, stop: int, field: str) -> float:
        """Trapezoidal integral, padded by ``area_pad_widths`` of the window's own duration.

        Padding matters: integrating only between the threshold crossings truncates the pulse tails,
        and by an amount that grows as the peak approaches the threshold -- so a light vehicle loses
        proportionally more area than a heavy one, and the bias becomes a function of load rather
        than a constant the fitted gain could absorb.
        """
        pad = int(round(self.cfg.area_pad_widths * (stop - start)))
        lo = max(start - pad, self._base)
        hi = min(stop + pad, self._end)
        if hi - lo < 2:
            return 0.0
        return float(np.trapezoid(self._slice(field, lo, hi), self._slice("t_s", lo, hi)))

    # -- vehicle assembly ----------------------------------------------------------------------

    def _emit_pending(self) -> list[DetectedEvent]:
        if not self._pending:
            return []
        axles = tuple(self._pending)
        flags = self._pending_flags
        self._pending = []
        self._pending_flags = self._blank_flags()

        biggest = max(axles, key=lambda a: a.peak)
        offset = self._epoch_offset()
        return [
            DetectedEvent(
                ts_start_us=int(round(axles[0].t_start_s * 1e6)) + offset,
                ts_peak_us=int(round(biggest.t_peak_s * 1e6)) + offset,
                ts_end_us=int(round(axles[-1].t_end_s * 1e6)) + offset,
                t_start_s=axles[0].t_start_s,
                t_peak_s=biggest.t_peak_s,
                t_end_s=axles[-1].t_end_s,
                peak=biggest.peak,
                area=float(sum(a.area for a in axles)),
                raw_peak=max(a.raw_peak for a in axles),
                raw_area=float(sum(a.raw_area for a in axles)),
                temp_c=self._temp_at(biggest.t_peak_s),
                axles=axles,
                axle_dt_s=tuple(
                    axles[i + 1].t_peak_s - axles[i].t_peak_s for i in range(len(axles) - 1)
                ),
                saturated=flags["saturated"],
                has_invalid=flags["has_invalid"],
                warming_up=flags["warming_up"],
                zero_suspect=flags["zero_suspect"],
                truncated=flags["truncated"],
                channel_id=self._channel_id,
            )
        ]

    def _temp_at(self, t_peak_s: float) -> float | None:
        """The probe reading at the sample nearest the peak.

        Nearest rather than an average over the window: the coefficient corrects a gain, and the
        gain that produced the peak is the one in force at the peak.
        """
        t_s = self._buf["t_s"]
        if t_s.size == 0:
            return None
        i = int(np.abs(t_s - t_peak_s).argmin())
        value = float(self._buf["temp"][i])
        return None if np.isnan(value) else value

    def _epoch_offset(self) -> int:
        """Microseconds between ``t_s = 0`` and the epoch, read off the buffer's own stamps."""
        if self._buf["t_s"].size == 0:
            return 0
        return int(self._buf["ts_us"][0]) - int(round(float(self._buf["t_s"][0]) * 1e6))

    def _record(self, axle: AxlePeak, start: int, stop: int) -> list[DetectedEvent]:
        events: list[DetectedEvent] = []
        if self._pending and (axle.t_start_s - self._last_close_t) > self.cfg.merge_gap_s:
            events.extend(self._emit_pending())

        self._pending.append(axle)
        self._pending_flags["saturated"] |= bool(self._slice("saturated", start, stop).any())
        self._pending_flags["has_invalid"] |= bool(self._slice("invalid", start, stop).any())
        self._pending_flags["warming_up"] |= bool(self._slice("warming_up", start, stop).any())
        self._pending_flags["zero_suspect"] |= bool(self._slice("zero_suspect", start, stop).any())
        self._last_close_t = axle.t_end_s
        self.detected += 1
        return events

    # -- the state machine ----------------------------------------------------------------------

    def _scan(self) -> list[DetectedEvent]:
        cfg = self.cfg
        comp = self._buf["comp"]
        t_s = self._buf["t_s"]
        above_start = comp >= cfg.start_threshold
        above_end = comp > cfg.end_threshold
        below = ~above_end
        events: list[DetectedEvent] = []

        while self._pos < self._end:
            local = self._pos - self._base
            if self._open_start is None:
                rel = np.flatnonzero(above_start[local:])
                if rel.size == 0:
                    self._pos = self._end
                    break
                idx = local + int(rel[0])
                if t_s[idx] < self._refractory_until:
                    resume = int(np.searchsorted(t_s, self._refractory_until, side="left"))
                    self._pos = self._base + max(resume, idx + 1)
                    continue
                # walk back to where the excursion actually began, i.e. the first sample of the
                # contiguous run above the *end* threshold containing this crossing
                back = idx
                while back > 0 and above_end[back - 1]:
                    back -= 1
                self._open_start = self._base + back
                self._pos = self._base + idx
                continue

            # close only once the signal has stayed below end_threshold for the hold time
            if below.size - local < self._hold:
                self._pos = self._end
                break
            runs = np.convolve(
                below[local:].astype(np.int32), np.ones(self._hold, np.int32), "valid"
            )
            rel = np.flatnonzero(runs == self._hold)
            if rel.size == 0:
                self._pos = self._end - self._hold + 1
                break

            close_local = local + int(rel[0])
            start, stop = self._open_start, self._base + close_local
            self._open_start = None
            self._pos = self._base + close_local + 1

            axle = self._axle(start, stop)
            if axle is not None:
                events.extend(self._record(axle, start, stop))
                if cfg.refractory_s > 0:
                    self._refractory_until = float(t_s[close_local]) + cfg.refractory_s
        return events

    def _guard_runaway(self) -> None:
        """Refuse to buffer without bound when the signal never comes back down."""
        if self._open_start is None:
            return
        if (self._end - self._open_start) * self.dt > self.cfg.max_duration_s:
            self.rejected_too_long += 1
            self._refractory_until = float(self._buf["t_s"][-1])
            self._open_start = None
            self._pos = self._end

    def _maybe_emit(self) -> list[DetectedEvent]:
        """Emit a buffered vehicle once enough quiet has passed for it to be complete."""
        if not self._pending or self._open_start is not None or self._buf["t_s"].size == 0:
            return []
        if float(self._buf["t_s"][-1]) - self._last_close_t <= self.cfg.merge_gap_s:
            return []
        return self._emit_pending()

    # -- entry points -----------------------------------------------------------------------------

    def process(self, block: PreprocessedBlock) -> list[DetectedEvent]:
        self._append(block)
        events = self._scan()
        self._guard_runaway()
        events.extend(self._maybe_emit())
        self._trim()
        return events

    def flush(self) -> list[DetectedEvent]:
        """End of stream: emit whatever is buffered rather than losing it.

        An open window is emitted with ``truncated=True``. Its features are incomplete by
        construction, so it is marked ``suspect`` rather than quietly counted as a healthy vehicle.
        """
        if self._open_start is not None:
            start, stop = self._open_start, self._end
            self._open_start = None
            self._pos = self._end
            axle = self._axle(start, stop)
            if axle is not None:
                self._record(axle, start, stop)
                self._pending_flags["truncated"] = True
        return self._emit_pending()
