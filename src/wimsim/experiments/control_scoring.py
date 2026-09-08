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
  not a single pass: one lucky pass in the middle of a fault must not read as recovery. And "came
  back to twice the pre-fault error" is not recovery either -- the tolerance is relative to the
  pre-fault level, which also makes the number comparable across sites whose residual spreads
  differ by an order of magnitude.
* **A detection has to happen after the fault.** Crediting an alarm that fired beforehand would let
  a detector that alarms constantly score perfectly.
* **"Never reconverged" and "could not be measured" are different outcomes**, and both are
  reportable. Collapsing either into a missing value would let a system that never recovers
  disappear from a mean instead of dragging it down.
"""

from __future__ import annotations

import json
import time
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any

import numpy as np

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
    reconverged: bool
    seconds: float | None
    passes: int | None
    reconverged_at_ts_us: int | None
    baseline_abs_error: float
    final_abs_error: float

    def to_dict(self) -> dict[str, Any]:
        return {
            "reconverge_measurable": self.measurable,
            "reconverged": self.reconverged,
            "reconverge_s": self.seconds,
            "reconverge_passes": self.passes,
            "baseline_abs_error_kg": self.baseline_abs_error,
            "final_abs_error_kg": self.final_abs_error,
        }


def time_to_reconverge(
    errors: Sequence[tuple[int, float]],
    *,
    fault_ts_us: int,
    window: int = 40,
    tolerance: float = 1.5,
    hold: int | None = None,
) -> Reconvergence:
    """Time from an injected fault until the error returns to its pre-fault level and stays there.

    ``errors`` is ``(timestamp_us, signed error in kg)`` per scored pass, in time order.

    The statistic is a rolling **median** of the absolute error over ``window`` passes, compared
    against the same statistic over the window immediately before the fault. Median rather than
    mean because a fault window contains outliers by construction, and rolling because a single
    pass that happens to land near zero is not a recovery.

    Recovery must then *hold* for ``hold`` further windows (default: ``window``). An earlier version
    required it to hold for the rest of the run, which sounds stricter and is simply wrong: the
    median of forty draws has enough sampling variation that at a 1.5x tolerance one later window
    drifts over the line by chance, and a genuine recovery at pass 300 was reported at pass 466.
    Requiring a stated horizon measures recovery; requiring the rest of the run measures how long
    the run happened to be.
    """
    rows = sorted(errors, key=lambda row: row[0])
    if not rows:
        return Reconvergence(False, False, None, None, None, 0.0, 0.0)

    times = np.array([row[0] for row in rows], dtype=np.int64)
    absolute = np.abs(np.array([row[1] for row in rows], dtype=np.float64))

    before = absolute[times < fault_ts_us]
    after_mask = times >= fault_ts_us
    after = absolute[after_mask]
    after_times = times[after_mask]

    baseline = float(np.median(before[-window:])) if before.size else 0.0
    final = float(np.median(after[-window:])) if after.size else 0.0

    # Not enough post-fault passes to fill even one window: the run ended too soon to say.
    if after.size < window:
        return Reconvergence(False, False, None, None, None, baseline, final)

    threshold = tolerance * baseline
    rolling = np.array(
        [float(np.median(after[i - window + 1 : i + 1])) for i in range(window - 1, after.size)]
    )
    within = rolling <= threshold

    # "Held": within tolerance here and for the next `hold` windows.
    horizon = window if hold is None else int(hold)
    held = np.array(
        [bool(within[i : i + horizon + 1].all()) for i in range(within.size)], dtype=bool
    )
    hits = np.flatnonzero(held)
    if hits.size == 0:
        return Reconvergence(True, False, None, None, None, baseline, final)

    index = int(hits[0]) + window - 1
    at_us = int(after_times[index])
    return Reconvergence(
        measurable=True,
        reconverged=True,
        seconds=(at_us - int(fault_ts_us)) / 1e6,
        passes=index + 1,
        reconverged_at_ts_us=at_us,
        baseline_abs_error=baseline,
        final_abs_error=final,
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
