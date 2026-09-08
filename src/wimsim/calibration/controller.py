"""The MAPE-K recalibration controller: when to act on a drift alarm, and when not to.

``MONITORING -> DRIFT_SUSPECTED -> RECALIBRATING -> VERIFYING -> MONITORING``, with ``DEGRADED``
whenever the loop cannot close. Buildspec section 6 asks for the machine to be explicit and
configurable because it is the control contribution; what follows is the reasoning behind each
transition, since the transitions are the contribution and the code is short.

**Monitor** takes a residual per pass and feeds the detectors. **Analyse** asks whether any of them
is alarming. **Plan** decides whether an alarm is worth acting on -- has it persisted, are there
reference vehicles to recalibrate against, has the cool-down elapsed, is this station allowed to
decide for itself. **Execute** refits and hands the new state back. **Knowledge** is the profile
store, which the caller owns; this class holds no persistence and does no IO, because
``calibration/`` has to cross-deploy to a Pi (principle 6).

Four decisions worth defending.

**Confirmation is a second opinion, not just a wait.** The detectors are deliberately tuned to allow
a couple of false alarms per thirty stationary runs, because tightening them further costs detection
delay. The confirmation window is what makes that trade affordable: after an alarm the controller
collects ``confirmation_passes`` more residuals and asks whether their mean is *still* displaced from
the level it was monitoring. A blip is not, drift is. Waiting alone would confirm both.

**``DEGRADED`` is the point of the machine, not an error path.** A confirmed drift with no reference
vehicle to recalibrate against is the normal case on a real road, and the honest response is to say
so and keep saying so. A controller without this state either recalibrates on nothing or pretends
the alarm never happened; both leave a scale weighing while it knows it is wrong, and only one of
them tells anyone. Verification failing lands here too, and that is the most dangerous outcome of
all, because the station has just announced that it fixed itself.

**The cool-down is on the station clock.** Recalibration consumes reference vehicles and briefly
makes the calibration worse, so doing it twice in a minute is a real cost. An hour is an hour whether
forty vehicles crossed in it or four.

**The loop has a hard sensitivity floor, and it is not in this file.** CUSUM's slack makes it a
drift detector rather than an outlier detector, which means deviations smaller than ``slack`` sigmas
never accumulate at all -- invisible permanently, not merely slowly. Measured against a 50 kg
residual spread over twenty runs of five hundred passes: 0/20 at half a sigma, 3/20 at 0.6, 12/20 at
one sigma, 19/20 at two. No tuning here can lift that floor, so the honest statement of this
system's sensitivity is "about two sigma of the residual spread", and every detection claim has to
quote the spread alongside it. ``tests/test_controller.py`` re-measures the curve.

**Arbitration is a switch because it is a deployment question.** A systematic error across twenty
stations is a fleet problem, and twenty stations independently recalibrating away from it destroys
the evidence that it was systematic. Whether a station may decide for itself therefore depends on
what it is part of, and the two modes are worth comparing rather than choosing between in advance.
"""

from __future__ import annotations

import math
from collections import deque
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from typing import Any, Literal

import numpy as np

from wimsim.calibration.base import EstimatorState, ReferenceObservation
from wimsim.calibration.drift import DriftDetector

__all__ = [
    "ARBITRATION_MODES",
    "ControllerConfig",
    "ControllerEvent",
    "RecalibrationController",
]

ARBITRATION_MODES = ("local", "cloud")

#: ``sqrt(pi/2)``. The standard error of a median is this much larger than that of a mean, for
#: normally distributed data. Paid deliberately: see ``_displaced``.
_MEDIAN_EFFICIENCY = 1.2533141373155003

State = Literal["MONITORING", "DRIFT_SUSPECTED", "RECALIBRATING", "VERIFYING", "DEGRADED"]
#: Kept here as well as in ``core.schemas`` because this package may not import pydantic
#: (principle 6). ``tests/test_controller.py`` asserts the two agree.
STATES: tuple[str, ...] = (
    "MONITORING",
    "DRIFT_SUSPECTED",
    "RECALIBRATING",
    "VERIFYING",
    "DEGRADED",
)


@dataclass(frozen=True, slots=True)
class ControllerConfig:
    """Every knob buildspec section 6 asks to be configurable."""

    confirmation_passes: int = 30
    """Residuals collected after an alarm before deciding whether it was real."""

    confirm_sigma: float = 3.0
    """How far the median of those residuals must still sit from the monitored level, in standard
    errors, for the suspicion to be confirmed.

    Three, not one. This is the second of two gates -- the detector alarmed first -- and its job is
    to reject the false alarms the detector was deliberately tuned to allow. At one sigma it
    rejects almost nothing: a 32 % false-confirmation rate by construction, which makes the gate
    decorative. At three it is 0.3 %, and it still confirms any drift larger than
    ``3 * 1.2533 * scale / sqrt(n)`` -- with thirty passes and a 50 kg residual spread that is
    34 kg, well under one residual. Both properties at once, which is why the standard error and
    not the raw spread is the yardstick.
    """

    min_reference_observations: int = 10
    """Fewer than this and there is nothing to recalibrate against, so the answer is DEGRADED."""

    cooldown_s: float = 3600.0
    verification_passes: int = 50
    """Residuals gathered after a new profile goes live, to check that it actually helped."""

    max_references: int = 200
    arbitration: str = "local"

    def __post_init__(self) -> None:
        if self.arbitration not in ARBITRATION_MODES:
            raise ValueError(
                f"arbitration must be one of {ARBITRATION_MODES}; got {self.arbitration!r}"
            )
        if self.confirmation_passes < 1 or self.verification_passes < 1:
            raise ValueError("confirmation_passes and verification_passes must be at least 1")
        if self.min_reference_observations < 2:
            raise ValueError("a two-parameter fit needs at least 2 reference observations")


@dataclass(frozen=True, slots=True)
class ControllerEvent:
    """Something the edge should publish. The controller itself does no IO."""

    kind: str
    """drift_detected | recalibrated | profile_activated | degraded | recovered"""
    ts_us: int
    state: str
    reason: str
    detector: str | None = None
    statistic: float | None = None
    estimator_state: EstimatorState | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "kind": self.kind,
            "ts_us": int(self.ts_us),
            "state": self.state,
            "reason": self.reason,
            "detector": self.detector,
            "statistic": None if self.statistic is None else float(self.statistic),
        }


@dataclass
class _Suspicion:
    """What is known between the first alarm and the decision about it."""

    started_ts_us: int
    detector: str
    statistic: float
    baseline_centre: float
    baseline_scale: float
    residuals: list[float] = field(default_factory=list)


class RecalibrationController:
    """One station's control loop."""

    def __init__(
        self,
        config: ControllerConfig,
        *,
        detectors: Sequence[DriftDetector],
        recalibrate: Callable[[list[ReferenceObservation]], EstimatorState],
        baseline_window: int = 200,
    ) -> None:
        if not detectors:
            raise ValueError("a controller with no detectors can never leave MONITORING")
        self.config = config
        self.detectors = list(detectors)
        self._recalibrate = recalibrate

        self._state: str = "MONITORING"
        self._events: list[ControllerEvent] = []
        self._references: deque[ReferenceObservation] = deque(maxlen=config.max_references)

        #: Recent residuals while healthy: the level a suspicion is measured against.
        self._baseline: deque[float] = deque(maxlen=baseline_window)
        self._suspicion: _Suspicion | None = None
        self._verification: list[float] = []
        self._verify_reference: tuple[float, float] | None = None

        self._arbitration: str | None = None  # None | "granted" | "denied"
        #: How many references had been seen when the last attempt was made. DEGRADED only retries
        #: once that number has grown -- see ``_retry``.
        self._references_at_last_attempt = -1
        self.recalibration_count = 0
        self.last_recalibration_ts_us: int | None = None
        self.active_state: EstimatorState | None = None

    # -- properties -------------------------------------------------------------------------

    @property
    def state(self) -> str:
        return self._state

    @property
    def n_references(self) -> int:
        return len(self._references)

    @property
    def awaiting_arbitration(self) -> bool:
        return (
            self.config.arbitration == "cloud"
            and self._state == "DRIFT_SUSPECTED"
            and self._suspicion is not None
            and self._arbitration is None
            and len(self._suspicion.residuals) >= self.config.confirmation_passes
        )

    def state_one_hot(self) -> dict[str, int]:
        """For ``wim_cal_state{state=...}``, which is drawn as a stack. Exactly one is 1."""
        return {name: int(name == self._state) for name in STATES}

    # -- inputs ------------------------------------------------------------------------------

    def offer_reference(self, observation: ReferenceObservation) -> None:
        """A vehicle of known mass has crossed. Buffered until a recalibration needs it."""
        self._references.append(observation)

    def grant_arbitration(self) -> None:
        self._arbitration = "granted"

    def deny_arbitration(self, reason: str = "denied") -> None:
        self._arbitration = "denied"
        self._denial_reason = reason

    def observe(self, ts_us: int, residual_kg: float) -> list[ControllerEvent]:
        """One pass. Returns the events it produced, which the edge publishes."""
        before = len(self._events)
        residual = float(residual_kg)

        for detector in self.detectors:
            detector.update(residual)

        if self._state == "MONITORING":
            self._monitor(ts_us, residual)
        elif self._state == "DRIFT_SUSPECTED":
            self._analyse(ts_us, residual)
        elif self._state == "VERIFYING":
            self._verify(ts_us, residual)
        elif self._state == "DEGRADED":
            self._retry(ts_us, residual)

        return self._events[before:]

    def drain_events(self) -> list[ControllerEvent]:
        """Take the accumulated events. Once, so nothing is published twice."""
        events, self._events = self._events, []
        return events

    # -- the machine ---------------------------------------------------------------------------

    def _monitor(self, ts_us: int, residual: float) -> None:
        self._baseline.append(residual)
        alarming = next((d for d in self.detectors if d.alarm), None)
        if alarming is None:
            return

        centre, scale = self._baseline_stats()
        self._suspicion = _Suspicion(
            started_ts_us=int(ts_us),
            detector=alarming.name,
            statistic=float(alarming.statistic),
            baseline_centre=centre,
            baseline_scale=scale,
        )
        self._arbitration = None
        self._transition(
            "DRIFT_SUSPECTED",
            ts_us,
            kind="drift_detected",
            reason=f"{alarming.name} raised an alarm at {alarming.statistic:.2f}",
            detector=alarming.name,
            statistic=float(alarming.statistic),
        )

    def _analyse(self, ts_us: int, residual: float) -> None:
        assert self._suspicion is not None
        self._suspicion.residuals.append(residual)
        if len(self._suspicion.residuals) < self.config.confirmation_passes:
            return

        if not self._confirmed():
            # A blip. Clear the latch, or it re-triggers on the very next pass and forever after.
            self._clear_detectors()
            self._suspicion = None
            self._transition(
                "MONITORING",
                ts_us,
                kind="recovered",
                reason="the alarm did not persist through the confirmation window",
            )
            return

        self._plan(ts_us)

    def _plan(self, ts_us: int) -> None:
        """Everything between "drift is real" and "act on it"."""
        if self.config.arbitration == "cloud":
            if self._arbitration is None:
                return  # awaiting_arbitration; the caller will grant or deny
            if self._arbitration == "denied":
                self._degrade(ts_us, getattr(self, "_denial_reason", "arbitration denied"))
                return

        if not self._cooled_down(ts_us):
            return

        if self.n_references < self.config.min_reference_observations:
            self._degrade(
                ts_us,
                f"drift confirmed but only {self.n_references} reference observations are "
                f"available; {self.config.min_reference_observations} are needed to refit",
            )
            return

        self._execute(ts_us)

    def _execute(self, ts_us: int) -> None:
        self._state = "RECALIBRATING"
        self._references_at_last_attempt = self.n_references
        try:
            new_state = self._recalibrate(list(self._references))
        except Exception as exc:  # a failed fit must not take the station down with it
            self._degrade(ts_us, f"recalibration failed: {exc}")
            return

        self.active_state = new_state
        self.recalibration_count += 1
        self.last_recalibration_ts_us = int(ts_us)
        self._append(
            "recalibrated",
            ts_us,
            "RECALIBRATING",
            f"refitted from {self.n_references} reference observations",
        )
        self._append(
            "profile_activated",
            ts_us,
            "RECALIBRATING",
            f"state hash {new_state.state_hash}",
            estimator_state=new_state,
        )

        self._clear_detectors()
        self._suspicion = None
        self._arbitration = None
        self._verification = []
        self._verify_reference = self._baseline_stats()
        self._transition(
            "VERIFYING",
            ts_us,
            kind="recovered",
            reason=f"verifying the new profile over {self.config.verification_passes} passes",
        )

    def _verify(self, ts_us: int, residual: float) -> None:
        self._verification.append(residual)
        if len(self._verification) < self.config.verification_passes:
            return

        centre, scale = self._verify_reference or (0.0, 0.0)
        displaced = self._displaced(self._verification, centre, scale)
        if displaced:
            self._degrade(
                ts_us,
                "the recalibration did not help: residuals are still displaced after "
                f"{self.config.verification_passes} passes",
            )
            return

        # The new normal is whatever the verification window saw.
        self._baseline.clear()
        self._baseline.extend(self._verification)
        self._verification = []
        self._transition(
            "MONITORING",
            ts_us,
            kind="recovered",
            reason="the new profile verified; back to monitoring",
        )

    def _retry(self, ts_us: int, residual: float) -> None:
        """DEGRADED is not a dead end: a reference vehicle may yet arrive.

        **Only new evidence gets a retry.** A refit from the same observations is deterministic, so
        an attempt that failed will fail identically -- and with a short cool-down the controller
        would sit in a loop recalibrating on every pass, each time announcing that it had fixed
        itself. So the gate is that the reference buffer has actually grown since the last attempt,
        not merely that it is large enough.
        """
        self._baseline.append(residual)
        if self.n_references < self.config.min_reference_observations:
            return
        if self.n_references <= self._references_at_last_attempt:
            return
        if not self._cooled_down(ts_us):
            return
        if self.config.arbitration == "cloud" and self._arbitration != "granted":
            return
        self._execute(ts_us)

    # -- helpers -------------------------------------------------------------------------------

    def _confirmed(self) -> bool:
        assert self._suspicion is not None
        return self._displaced(
            self._suspicion.residuals,
            self._suspicion.baseline_centre,
            self._suspicion.baseline_scale,
        )

    def _displaced(self, values: list[float], centre: float, scale: float) -> bool:
        """Has the *level* moved away from where the controller was monitoring?

        Two choices here, and both were wrong in the first version.

        **The median, not the mean.** A confirmation window that spans the alarm contains the few
        bad passes that caused it, and the mean cannot tell five potholes in forty passes from a
        step. With a 16-sigma blip and a forty-pass window the mean lands at 2 sigma and confirms
        a drift that is not there -- so the controller recalibrates on the potholes, which is
        exactly the failure the confirmation window exists to prevent. The median of the same
        window is unmoved by a handful of outliers and tracks a genuine step exactly.

        **Scaled by the standard error, not by the raw spread.** The question is whether the level
        moved, so the yardstick has to shrink with the evidence: after thirty passes a shift much
        smaller than one residual is already decisive, and comparing against the raw spread would
        make the controller blind to every slow drift. The 1.2533 is the median's own efficiency
        penalty -- ``sqrt(pi/2)`` -- which is the price of the robustness above.
        """
        if not values:
            return False
        sample = np.asarray(values, dtype=np.float64)
        statistic = float(np.median(sample))
        if scale <= 0.0:
            return not math.isclose(statistic, centre, abs_tol=1e-12)
        standard_error = _MEDIAN_EFFICIENCY * scale / math.sqrt(sample.size)
        return abs(statistic - centre) > self.config.confirm_sigma * standard_error

    def _baseline_stats(self) -> tuple[float, float]:
        """Median and robust sigma of the healthy residuals seen so far."""
        if not self._baseline:
            return 0.0, 0.0
        sample = np.asarray(self._baseline, dtype=np.float64)
        centre = float(np.median(sample))
        return centre, float(np.median(np.abs(sample - centre))) * 1.4826

    def _cooled_down(self, ts_us: int) -> bool:
        if self.last_recalibration_ts_us is None:
            return True
        elapsed_s = (int(ts_us) - self.last_recalibration_ts_us) / 1e6
        return elapsed_s >= self.config.cooldown_s

    def _clear_detectors(self) -> None:
        for detector in self.detectors:
            detector.reset()

    def _degrade(self, ts_us: int, reason: str) -> None:
        self._clear_detectors()
        self._suspicion = None
        self._transition("DEGRADED", ts_us, kind="degraded", reason=reason)

    def _transition(self, state: str, ts_us: int, *, kind: str, reason: str, **extra) -> None:
        self._state = state
        self._append(kind, ts_us, state, reason, **extra)

    def _append(self, kind: str, ts_us: int, state: str, reason: str, **extra) -> None:
        self._events.append(
            ControllerEvent(kind=kind, ts_us=int(ts_us), state=state, reason=reason, **extra)
        )

    # -- serialisation ---------------------------------------------------------------------------

    def to_dict(self) -> dict[str, Any]:
        return {
            "state": self._state,
            "recalibration_count": self.recalibration_count,
            "last_recalibration_ts_us": self.last_recalibration_ts_us,
            "n_references": self.n_references,
            "awaiting_arbitration": self.awaiting_arbitration,
            "detectors": {d.name: float(d.statistic) for d in self.detectors},
        }
