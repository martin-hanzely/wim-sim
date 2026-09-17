"""Scoring the loop rather than the masses.

``scoring.py`` answers "how wrong were the kilograms". These are the questions buildspec section 10
names for a control paper: time to reconverge after an injected drift event -- called out as *the*
headline control metric -- the drift detector's false-alarm and missed-detection rates, and what an
estimator update costs in microseconds and in bytes of state.

All of it needs the fault times, which are truth-side, so all of it lives in ``experiments/`` and
none of it is reachable from ``calibration/``.

**The definitions are the contribution here, not the arithmetic.** Each of these is easy to define
in a way that flatters the system, so each one is defined to be hard to game:

* **Reconvergence requires the error to come back and stay back.** A rolling median over a window,
  not a single pass: one lucky pass in the middle of a fault must not read as recovery.
* **The statistic is the SIGNED median, not the median of the absolute error.** A calibration fault
  is a systematic shift, and ``|error|`` barely moves when a wide symmetric distribution slides
  sideways -- so an absolute statistic is blind to exactly the thing being measured. Measured on
  ``S7_sparse_reference``, the old definition reported static_affine reconverging in 187-327 s
  while it carried -96.7 kg of bias on a 158 kg spread. It had not recovered at all.
* **The threshold is the controller's own.** Recovery means the signed median has come back inside
  ``tolerance_sigma`` standard errors of its pre-fault value -- the same test
  ``RecalibrationController._displaced`` applies when deciding drift has *occurred*. The metric and
  the loop therefore agree on what "moved" means instead of each carrying a private definition, and
  the number stays comparable across sites whose residual spreads differ by an order of magnitude.
* **A detection has to happen after the fault.** Crediting an alarm that fired beforehand would let
  a detector that alarms constantly score perfectly.
* **Recovery requires a departure first.** If the error never left its pre-fault band there was
  nothing to recover from, and reporting a fast recovery would be worse than reporting none.
  ``S7_sparse_reference`` ramps its fault over two hours; measured from the fault's start time, the
  first window is trivially still at baseline, and the metric used to call that recovery in 187 s.
* **"Never reconverged", "never departed" and "could not be measured" are three different
  outcomes**, and all are reportable. Collapsing any of them into a missing value would let a
  system that never recovers disappear from a mean instead of dragging it down.
"""

from __future__ import annotations

import json
import math
import time
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any

import numpy as np

#: ``sqrt(pi/2)``. The standard error of a median is this much larger than that of a mean, for
#: normally distributed data -- the same constant, for the same reason, as in
#: ``calibration.controller``, which is the point: the loop and this metric must agree on what
#: counts as a displaced median.
_MEDIAN_EFFICIENCY = 1.2533141373155003

#: MAD -> sigma, for normally distributed data.
_MAD_TO_SIGMA = 1.4826


def _robust_sigma(sample: np.ndarray) -> float:
    """Spread of the healthy residuals, via the MAD, so one outlier cannot set the threshold."""
    if sample.size == 0:
        return 0.0
    return float(np.median(np.abs(sample - np.median(sample)))) * _MAD_TO_SIGMA


__all__ = [
    "ControlScore",
    "DetectorRates",
    "EstimatorCost",
    "Reconvergence",
    "detector_rates",
    "estimator_cost",
    "time_to_reconverge",
]


@dataclass(frozen=True, slots=True)
class Reconvergence:
    """How long the loop took to get the error back to where it started."""

    measurable: bool
    """False when the run ended before a verdict was possible -- distinct from never recovering."""
    departed: bool
    """Whether the error ever left its pre-fault band. False means there was nothing to recover
    from, which is a different finding from recovering quickly and must not be averaged with it."""
    reconverged: bool
    seconds: float | None
    passes: int | None
    reconverged_at_ts_us: int | None
    baseline_error: float
    """Signed median error over the window before the fault. Near zero for a healthy estimator,
    however wide its residual spread -- large symmetric errors are not a bias."""
    final_error: float
    """Signed median error over the last window of the run."""

    def to_dict(self) -> dict[str, Any]:
        return {
            "reconverge_measurable": self.measurable,
            "reconverge_departed": self.departed,
            "reconverged": self.reconverged,
            "reconverge_s": self.seconds,
            "reconverge_passes": self.passes,
            "baseline_error_kg": self.baseline_error,
            "final_error_kg": self.final_error,
        }


def time_to_reconverge(
    errors: Sequence[tuple[int, float]],
    *,
    fault_ts_us: int,
    window: int = 40,
    tolerance_sigma: float = 3.0,
    hold: int | None = None,
) -> Reconvergence:
    """Time from an injected fault until the calibration returns to where it started, and stays.

    ``errors`` is ``(timestamp_us, signed error in kg)`` per scored pass, in time order.

    The statistic is a rolling **signed** median over ``window`` passes. Signed because a
    calibration fault is a systematic shift and that is what has to come back; a median of
    ``|error|`` hardly moves when a wide symmetric distribution slides sideways, and the first
    version of this function was blind to exactly the failures it existed to catch. Median rather
    than mean because a fault window contains outliers by construction, and rolling because a
    single pass that happens to land near zero is not a recovery.

    Recovery means the rolling median has come back within ``tolerance_sigma`` standard errors of
    its pre-fault value, where the standard error is ``1.2533 * sigma / sqrt(window)`` for a
    robustly estimated pre-fault ``sigma``. That is the same test
    :meth:`~wimsim.calibration.controller.RecalibrationController._displaced` uses to decide that
    drift has occurred, and the default matches its ``confirm_sigma``: the loop and the metric
    agree on what "moved" means. It also keeps the number comparable across sites, since a noisy
    site is permitted a proportionally larger residual bias rather than being unable to reconverge
    at all.

    Recovery must then *hold* for ``hold`` further windows (default: ``window``). An earlier
    version required it to hold for the rest of the run, which sounds stricter and is simply wrong:
    the median of forty draws has enough sampling variation that one later window drifts over the
    line by chance, and a genuine recovery at pass 300 was reported at pass 466. Requiring a stated
    horizon measures recovery; requiring the rest of the run measures how long the run happened to
    be.
    """
    rows = sorted(errors, key=lambda row: row[0])
    if not rows:
        return Reconvergence(False, False, False, None, None, None, 0.0, 0.0)

    times = np.array([row[0] for row in rows], dtype=np.int64)
    signed = np.array([row[1] for row in rows], dtype=np.float64)

    before = signed[times < fault_ts_us]
    after_mask = times >= fault_ts_us
    after = signed[after_mask]
    after_times = times[after_mask]

    baseline = float(np.median(before[-window:])) if before.size else 0.0
    final = float(np.median(after[-window:])) if after.size else 0.0

    # Not enough post-fault passes to fill even one window: the run ended too soon to say.
    if after.size < window:
        return Reconvergence(False, False, False, None, None, None, baseline, final)

    sample = before[-window:] if before.size else np.zeros(0)
    standard_error = _MEDIAN_EFFICIENCY * _robust_sigma(sample) / math.sqrt(window)
    # A noiseless baseline admits no slack, but floating point still needs a hair of it.
    threshold = max(tolerance_sigma * standard_error, 1e-9)

    rolling = np.array(
        [float(np.median(after[i - window + 1 : i + 1])) for i in range(window - 1, after.size)]
    )
    within = np.abs(rolling - baseline) <= threshold

    horizon = window if hold is None else int(hold)

    # Recovery is only meaningful after a departure. A fault that ramps over hours has not moved
    # the error at all in its first window, so without this the metric reports an instant recovery
    # from a disturbance that has not arrived -- which is how `S7_sparse_reference` came to be
    # scored at 187 s while carrying a bias that was still growing.
    #
    # A departure has to be sustained for the same reason a recovery does, and by the same number
    # of windows. A rolling median crosses a three-sigma band by chance somewhere in a few hundred
    # overlapping windows, so "went outside once" is a property of the run's length rather than of
    # the plant.
    left = np.array(
        [bool((~within[i : i + horizon + 1]).all()) for i in range(within.size)], dtype=bool
    )
    departures = np.flatnonzero(left)
    if departures.size == 0:
        return Reconvergence(True, False, False, None, None, None, baseline, final)
    first_departure = int(departures[0])

    # "Held": within tolerance here and for the next `hold` windows, and after the departure.
    held = np.array(
        [
            bool(i > first_departure and within[i : i + horizon + 1].all())
            for i in range(within.size)
        ],
        dtype=bool,
    )
    hits = np.flatnonzero(held)
    if hits.size == 0:
        return Reconvergence(True, True, False, None, None, None, baseline, final)

    index = int(hits[0]) + window - 1
    at_us = int(after_times[index])
    return Reconvergence(
        measurable=True,
        departed=True,
        reconverged=True,
        seconds=(at_us - int(fault_ts_us)) / 1e6,
        passes=index + 1,
        reconverged_at_ts_us=at_us,
        baseline_error=baseline,
        final_error=final,
    )


@dataclass(frozen=True, slots=True)
class DetectorRates:
    """What the drift detectors got right and wrong, against the injected faults."""

    detected: int
    missed: int
    false_alarms: int
    duration_s: float
    detection_delay_s: list[float]

    @property
    def recall(self) -> float | None:
        """None on a scenario with no faults -- undefined, not perfect."""
        total = self.detected + self.missed
        return self.detected / total if total else None

    @property
    def false_alarms_per_hour(self) -> float:
        """The denominator an operator recognises. "Twelve false alarms" means nothing without
        knowing whether that was over a day or over a year."""
        hours = self.duration_s / 3600.0
        return self.false_alarms / hours if hours > 0 else 0.0

    @property
    def mean_detection_delay_s(self) -> float | None:
        return float(np.mean(self.detection_delay_s)) if self.detection_delay_s else None

    def to_dict(self) -> dict[str, Any]:
        return {
            "detected": self.detected,
            "missed": self.missed,
            "false_alarms": self.false_alarms,
            "recall": self.recall,
            "false_alarms_per_hour": self.false_alarms_per_hour,
            "mean_detection_delay_s": self.mean_detection_delay_s,
        }


def detector_rates(
    *,
    fault_ts_us: Sequence[int],
    alarm_ts_us: Sequence[int],
    horizon_s: float,
    duration_s: float,
) -> DetectorRates:
    """Match alarms to injected faults, greedily and in time order.

    An alarm answers a fault when it lands in ``[fault, fault + horizon]``. Each alarm answers at
    most one fault and each fault is answered at most once, so a detector that fires five times for
    one fault scores one detection and four false alarms -- which is right, because an operator has
    to triage every one of them.
    """
    faults = sorted(int(t) for t in fault_ts_us)
    alarms = sorted(int(t) for t in alarm_ts_us)
    horizon_us = int(horizon_s * 1e6)

    unclaimed = set(range(len(alarms)))
    delays: list[float] = []
    detected = 0

    for fault in faults:
        answer = next(
            (i for i in sorted(unclaimed) if fault <= alarms[i] <= fault + horizon_us),
            None,
        )
        if answer is None:
            continue
        unclaimed.discard(answer)
        detected += 1
        delays.append((alarms[answer] - fault) / 1e6)

    return DetectorRates(
        detected=detected,
        missed=len(faults) - detected,
        false_alarms=len(unclaimed),
        duration_s=float(duration_s),
        detection_delay_s=delays,
    )


@dataclass(frozen=True, slots=True)
class EstimatorCost:
    """What one update costs, on the hardware this is meant to deploy to."""

    update_us: float
    state_bytes: int
    n_updates: int

    def to_dict(self) -> dict[str, Any]:
        return {
            "update_us": self.update_us,
            "state_bytes": self.state_bytes,
        }


def estimator_cost(estimator: Any, observations: Sequence[Any]) -> EstimatorCost:
    """Mean microseconds per ``update``, and the serialised size of the state it carries.

    Both, because they are different deployment failures. This runs on a Pi beside a road: an
    update that takes a millisecond starves the sample loop, and a state that will not fit in flash
    cannot survive a restart -- and neither shows up as an inaccurate mass.

    The state is measured as the JSON the profile store would write, because that is the form that
    actually has to be persisted, rather than the in-memory footprint which nobody has to budget
    for.
    """
    if not observations:
        raise ValueError("costing an estimator needs at least one observation")

    started = time.perf_counter_ns()
    for observation in observations:
        estimator.update(observation)
    elapsed_ns = time.perf_counter_ns() - started

    state = estimator.state()
    blob = json.dumps(state.to_dict(), sort_keys=True, separators=(",", ":"))
    return EstimatorCost(
        update_us=elapsed_ns / 1e3 / len(observations),
        state_bytes=len(blob.encode("utf-8")),
        n_updates=len(observations),
    )


@dataclass(frozen=True, slots=True)
class ControlScore:
    """The control-loop half of a run's result row."""

    reconvergence: Reconvergence | None = None
    rates: DetectorRates | None = None
    cost: EstimatorCost | None = None

    def to_dict(self) -> dict[str, Any]:
        """Flat, because this goes to parquet and then to a comparison table. Nesting would have to
        be undone by every consumer instead of once here."""
        row: dict[str, Any] = {}
        for part in (self.reconvergence, self.rates, self.cost):
            if part is not None:
                row.update(part.to_dict())
        return row
