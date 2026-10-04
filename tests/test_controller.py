"""The MAPE-K recalibration controller.

``MONITORING -> DRIFT_SUSPECTED -> RECALIBRATING -> VERIFYING -> MONITORING``, with ``DEGRADED``
when recalibration fails or reference data is not available. Buildspec section 6 asks for it to be
explicit and configurable because it is the control contribution; these tests exist because a state
machine that is only exercised by the happy path is a state machine with untested edges, and its
edges are where a scale silently keeps weighing while knowing it is wrong.

The states that matter most are the ones nobody demos. ``DEGRADED`` is the honest answer to "the
scale has detected that it is wrong and cannot fix itself", which on a real road happens whenever
drift is confirmed and no reference vehicle has passed. A controller without it either recalibrates
on nothing or pretends the alarm never happened, and both are worse than saying so.
"""

from __future__ import annotations

import numpy as np
import pytest

from wimsim.calibration import (
    ControllerConfig,
    RecalibrationController,
    ReferenceObservation,
    StaticAffine,
    build_detector,
)

SECOND = 1_000_000


def _controller(*, recalibrate=None, **overrides) -> RecalibrationController:
    defaults = {
        "confirmation_passes": 20,
        "min_reference_observations": 5,
        "cooldown_s": 0.0,
        "verification_passes": 20,
    }
    cfg = ControllerConfig(**{**defaults, **overrides})
    return RecalibrationController(
        cfg,
        detectors=[build_detector("cusum", warmup=60)],
        recalibrate=recalibrate or _fit_from,
    )


def _fit_from(observations):
    estimator = StaticAffine()
    estimator.fit(observations)
    return estimator.state()


def _references(n: int = 10, *, k: float = 2.0e-4, start_s: int = 0, seed: int = 0):
    rng = np.random.default_rng(seed)
    masses = rng.uniform(1000.0, 40000.0, n)
    return [
        ReferenceObservation(
            ts_us=SECOND * (start_s + i),
            feature=float(k * m),
            temp_c=20.0,
            reference_mass_kg=float(m),
        )
        for i, m in enumerate(masses)
    ]


def _run(controller, values, *, start_s: int = 0, step_s: int = 1):
    events = []
    for i, value in enumerate(values):
        events += controller.observe(SECOND * (start_s + i * step_s), float(value))
    return events


def _noise(n: int, *, shift: float = 0.0, seed: int = 0) -> np.ndarray:
    return shift + np.random.default_rng(seed).standard_normal(n) * 50.0


class _Plant:
    """Residuals that respond to a recalibration, which is the whole point of the loop.

    Feeding a fixed offset forever is a test of the *failure* path -- it says the refit did not
    help, and the controller is right to degrade. To exercise the cycle the offset has to clear
    when the estimator is refitted, exactly as it would on a station where the new profile
    cancels the drift.
    """

    def __init__(
        self, controller, *, seed: int = 0, scale: float = 50.0, responds: bool = True
    ) -> None:
        self.controller = controller
        self.rng = np.random.default_rng(seed)
        self.scale = scale
        self.offset = 0.0
        self.ts_s = 0
        #: Whether a refit actually fixes anything. False is the plant whose drift the new profile
        #: fails to correct -- a broken sensor rather than a mis-calibrated one -- which is the
        #: situation the verification window exists to catch.
        self.responds = responds
        self._seen_recalibrations = controller.recalibration_count

    def fault(self, offset: float) -> None:
        self.offset = float(offset)

    def run(self, n: int, *, step_s: int = 1, reference_every: int = 0) -> list:
        events = []
        for _ in range(n):
            if self.controller.recalibration_count != self._seen_recalibrations:
                self._seen_recalibrations = self.controller.recalibration_count
                if self.responds:
                    self.offset = 0.0  # the refit absorbed it
            residual = self.offset + float(self.rng.standard_normal()) * self.scale
            events += self.controller.observe(SECOND * self.ts_s, residual)
            if reference_every and self.ts_s % reference_every == 0:
                # Seeded from the timestamp so the masses span a range. Identical reference masses
                # make the slope unidentifiable and every refit raises, which is a real failure
                # mode but not the one these tests are about.
                self.controller.offer_reference(
                    _references(1, start_s=self.ts_s, seed=self.ts_s)[0]
                )
            self.ts_s += step_s
        return events


def _supply(controller, plant, n: int = 12, *, k: float = 2.0e-4) -> None:
    """Drop a batch of reference vehicles in at the plant's current time.

    Stamped *now* rather than at second zero, because a refit only uses references postdating the
    drift: a batch from before it describes a plant that no longer exists, and the controller is
    right to decline it.
    """
    for obs in _references(n, k=k, start_s=plant.ts_s, seed=plant.ts_s + n):
        controller.offer_reference(obs)


# -- the happy path ----------------------------------------------------------------------------


def test_it_starts_monitoring_and_stays_there_on_a_healthy_stream() -> None:
    controller = _controller()
    assert controller.state == "MONITORING"
    _run(controller, _noise(600, seed=1))
    assert controller.state == "MONITORING"
    assert controller.recalibration_count == 0


def test_a_confirmed_drift_walks_the_whole_cycle_and_comes_back_to_monitoring() -> None:
    """The cycle the buildspec names, end to end, against a plant that responds to the refit."""
    controller = _controller()
    plant = _Plant(controller, seed=2)

    plant.run(300, reference_every=4)
    assert controller.state == "MONITORING"

    plant.fault(400.0)
    plant.run(60, reference_every=2)
    assert controller.recalibration_count == 1
    assert plant.offset == 0.0, "the plant should have been corrected by the refit"

    # Deliberately no assertion on VERIFYING here: how long it lasts is a config value, and a test
    # that pins the state at an exact pass count is a test that breaks when that value changes
    # without anything being wrong. What matters is where the cycle *ends*.
    plant.run(60, reference_every=4)
    assert controller.state == "MONITORING"
    assert [e.kind for e in controller.drain_events()][:1] == ["drift_detected"]


def test_every_transition_is_announced_as_an_event() -> None:
    """The dashboard draws recalibrations as annotations and the controller state as a timeline;
    a transition that happened without an event is a timeline with a gap in it."""
    controller = _controller()
    plant = _Plant(controller, seed=6)
    plant.run(300, reference_every=4)
    plant.fault(400.0)
    plant.run(120, reference_every=2)
    plant.run(120, reference_every=4)
    events = controller.drain_events()

    kinds = [e.kind for e in events]
    assert "drift_detected" in kinds
    assert "recalibrated" in kinds
    assert "profile_activated" in kinds
    for event in events:
        assert event.ts_us > 0
        assert event.state in {
            "MONITORING",
            "DRIFT_SUSPECTED",
            "RECALIBRATING",
            "VERIFYING",
            "DEGRADED",
        }
        assert event.reason


def test_the_new_state_is_handed_back_so_the_edge_can_activate_it() -> None:
    controller = _controller()
    plant = _Plant(controller, seed=9)
    plant.run(300, reference_every=4)
    plant.fault(400.0)
    plant.run(120, reference_every=2)

    activated = [e for e in controller.drain_events() if e.kind == "profile_activated"]
    assert controller.active_state is not None
    assert controller.active_state.fitted
    assert activated == [] or activated[0].estimator_state is not None


# -- confirmation ------------------------------------------------------------------------------


def test_a_transient_alarm_is_not_confirmed_and_falls_back_to_monitoring() -> None:
    """The confirmation window is what separates drift from a bad afternoon. Without it the
    controller recalibrates on every detector alarm, and the detectors are tuned to allow a couple
    of false alarms per thirty runs precisely because this exists to catch them.
    """
    controller = _controller(confirmation_passes=40)
    for obs in _references(10):
        controller.offer_reference(obs)

    _run(controller, _noise(300, seed=11))
    _run(controller, _noise(5, shift=800.0, seed=12), start_s=300)
    assert controller.state == "DRIFT_SUSPECTED"

    _run(controller, _noise(60, seed=13), start_s=305)
    assert controller.state == "MONITORING"
    assert controller.recalibration_count == 0


def test_a_suspicion_that_persists_is_confirmed() -> None:
    controller = _controller(confirmation_passes=40)
    plant = _Plant(controller, seed=14)
    plant.run(300, reference_every=4)
    plant.fault(500.0)
    plant.run(140, reference_every=2)
    assert controller.recalibration_count == 1


def test_the_detectors_are_reset_when_the_suspicion_clears() -> None:
    """A latched alarm that survives an unconfirmed suspicion would re-trigger on the next pass,
    forever."""
    controller = _controller(confirmation_passes=30)
    _run(controller, _noise(300, seed=16))
    _run(controller, _noise(3, shift=900.0, seed=17), start_s=300)
    _run(controller, _noise(50, seed=18), start_s=303)
    assert controller.state == "MONITORING"
    assert not any(d.alarm for d in controller.detectors)


# -- degraded, which is the state that matters -------------------------------------------------


def test_confirmed_drift_with_no_reference_vehicles_degrades_rather_than_guessing() -> None:
    """The real-road case. The scale knows it is wrong and has nothing to fix itself with; the only
    honest answers are to say so and to keep saying so."""
    controller = _controller()  # no references offered
    _run(controller, _noise(300, seed=19))
    _run(controller, _noise(200, shift=500.0, seed=20), start_s=300)

    assert controller.state == "DEGRADED"
    assert controller.recalibration_count == 0
    assert any(e.kind == "degraded" for e in controller.drain_events())


def test_it_recovers_from_degraded_once_reference_vehicles_arrive() -> None:
    controller = _controller()
    _run(controller, _noise(300, seed=21))
    _run(controller, _noise(200, shift=500.0, seed=22), start_s=300)
    assert controller.state == "DEGRADED"

    for obs in _references(10, start_s=500):
        controller.offer_reference(obs)
    _run(controller, _noise(10, shift=500.0, seed=23), start_s=520)
    assert controller.recalibration_count == 1


def test_a_recalibration_that_raises_degrades_rather_than_propagating() -> None:
    """A fit can fail for reasons the controller cannot anticipate -- degenerate references, a
    singular design. Taking the station down with it is the wrong response to a scale that is
    merely uncalibrated."""

    def explode(_observations):
        raise ValueError("degenerate reference set")

    controller = _controller(recalibrate=explode)
    plant = _Plant(controller, seed=24)
    plant.run(300, reference_every=4)
    plant.fault(500.0)
    plant.run(140, reference_every=2)

    assert controller.state == "DEGRADED"
    reasons = [e.reason for e in controller.drain_events() if e.kind == "degraded"]
    assert any("degenerate reference set" in r for r in reasons)


def test_verification_that_fails_degrades_rather_than_declaring_success() -> None:
    """A recalibration that did not help is the most dangerous outcome of all, because the station
    has just told everyone it fixed itself."""
    controller = _controller(verification_passes=30)
    # responds=False: a sensor that is broken rather than mis-calibrated, so no refit helps. That
    # is what the verification window is for, and the only honest way to test it -- re-injecting
    # the fault afterwards would instead be testing a *second* drift cycle.
    plant = _Plant(controller, seed=26, responds=False)
    plant.run(300, reference_every=4)
    plant.fault(500.0)
    plant.run(400, reference_every=2)

    assert controller.recalibration_count >= 1
    assert controller.state == "DEGRADED"


# -- cool-down and rate limiting -----------------------------------------------------------------


def test_a_cooldown_prevents_a_second_recalibration_too_soon() -> None:
    """Recalibration consumes reference vehicles and briefly makes the calibration worse. A
    controller that can do it twice in a minute will, on a noisy afternoon."""
    controller = _controller(cooldown_s=3600.0, verification_passes=5)
    plant = _Plant(controller, seed=29)
    plant.run(300, reference_every=4)
    plant.fault(500.0)
    plant.run(140, reference_every=2)
    assert controller.recalibration_count == 1
    first_at = controller.last_recalibration_ts_us

    plant.fault(1500.0)
    plant.run(200, reference_every=2)
    assert controller.recalibration_count == 1, "recalibrated again inside the cool-down"
    assert controller.last_recalibration_ts_us == first_at


def test_the_cooldown_is_measured_on_the_station_clock_not_on_pass_count() -> None:
    """An hour is an hour whether forty vehicles crossed in it or four.

    Two identical drifts, the same number of passes apart. The first pair are one second apart and
    the cool-down blocks the second recalibration; the second pair are an hour apart and it does
    not. A pass-counting cool-down could not tell the two situations apart, and the same config
    file would then mean different things on a motorway and on a farm track.
    """
    controller = _controller(cooldown_s=3600.0, verification_passes=10)
    plant = _Plant(controller, seed=32)
    plant.run(300, reference_every=5)

    plant.fault(500.0)
    plant.run(60, reference_every=5)
    assert controller.recalibration_count == 1
    first_at = controller.last_recalibration_ts_us

    # A second drift, seconds later. Blocked.
    plant.fault(900.0)
    plant.run(120, reference_every=5)
    assert controller.recalibration_count == 1, "recalibrated again inside the cool-down"
    assert controller.last_recalibration_ts_us == first_at

    # The same drift, still unaddressed, but now the clock has moved on. One long step to cross
    # the cool-down, then ordinary passes -- running 120 passes an hour apart would cross it a
    # hundred times over and measure nothing.
    plant.ts_s += 7200
    plant.run(80, reference_every=2)
    assert controller.recalibration_count == 2


# -- arbitration, which is a paper section ----------------------------------------------------------


def test_local_arbitration_acts_without_asking() -> None:
    controller = _controller(arbitration="local")
    plant = _Plant(controller, seed=35)
    plant.run(300, reference_every=4)
    plant.fault(500.0)
    plant.run(140, reference_every=2)
    assert controller.recalibration_count == 1


def test_cloud_arbitration_waits_for_a_grant_and_says_it_is_waiting() -> None:
    """A fleet operator may not want each station deciding for itself: a systematic error across
    twenty stations is a fleet problem, and twenty stations independently recalibrating away from
    it destroys the evidence. Which of the two applies is a deployment question, so it is a switch."""
    controller = _controller(arbitration="cloud")
    plant = _Plant(controller, seed=37)
    plant.run(300, reference_every=4)
    plant.fault(500.0)
    plant.run(140, reference_every=2)

    assert controller.state == "DRIFT_SUSPECTED"
    assert controller.awaiting_arbitration
    assert controller.recalibration_count == 0

    controller.grant_arbitration()
    plant.run(5, reference_every=2)
    assert controller.recalibration_count == 1
    assert not controller.awaiting_arbitration


def test_a_denied_arbitration_degrades_rather_than_waiting_forever() -> None:
    controller = _controller(arbitration="cloud")
    plant = _Plant(controller, seed=40)
    plant.run(300, reference_every=4)
    plant.fault(500.0)
    plant.run(140, reference_every=2)

    controller.deny_arbitration("fleet-wide error under investigation")
    plant.run(5, reference_every=2)
    assert controller.state == "DEGRADED"
    assert controller.recalibration_count == 0


# -- references --------------------------------------------------------------------------------


def test_too_few_references_is_not_enough_to_recalibrate() -> None:
    controller = _controller(min_reference_observations=8)
    plant = _Plant(controller, seed=43)
    plant.run(300)
    plant.fault(500.0)
    plant.run(140, reference_every=60)  # a trickle: never eight inside the window
    assert controller.state == "DEGRADED"


def test_the_reference_buffer_is_bounded_and_keeps_the_most_recent() -> None:
    """A month-old reference vehicle describes a scale that has drifted since."""
    controller = _controller(max_references=10)
    for obs in _references(50):
        controller.offer_reference(obs)
    assert controller.n_references == 10


# -- state, for the dashboard and the profile store -------------------------------------------------


def test_the_state_is_one_hot_over_the_declared_controller_states() -> None:
    """`wim_cal_state{state=...}` is drawn as a stacked one-hot; two states at once would render as
    a controller in two places."""
    from typing import get_args

    from wimsim.core.schemas import ControllerState

    controller = _controller()
    one_hot = controller.state_one_hot()
    assert set(one_hot) == set(get_args(ControllerState))
    assert sum(one_hot.values()) == 1
    assert one_hot[controller.state] == 1


def test_it_serialises_to_plain_json_and_restores() -> None:
    import json

    controller = _controller()
    for obs in _references(6):
        controller.offer_reference(obs)
    _run(controller, _noise(300, seed=45))
    _run(controller, _noise(100, shift=500.0, seed=46), start_s=300)

    payload = controller.to_dict()
    assert json.loads(json.dumps(payload))["state"] == controller.state
    assert payload["recalibration_count"] == controller.recalibration_count


def test_draining_events_returns_them_once() -> None:
    """The edge publishes them; publishing the same drift twice would double-count every alarm on
    the data-integrity dashboard."""
    controller = _controller()
    _run(controller, _noise(300, seed=47))
    _run(controller, _noise(200, shift=500.0, seed=48), start_s=300)
    first = controller.drain_events()
    assert first
    assert controller.drain_events() == []


def test_an_unknown_arbitration_mode_is_refused() -> None:
    with pytest.raises(ValueError, match="arbitration"):
        ControllerConfig(arbitration="committee")


# -- the confirmation gate, measured ------------------------------------------------------------


@pytest.mark.slow
def test_the_confirmation_gate_rejects_blips() -> None:
    """``confirm_sigma`` went from 1.0 to 3.0 on the strength of arithmetic, so here is the
    measurement: four very bad passes in an otherwise healthy stream, thirty times over.

    At one sigma this gate was decorative -- a 32 % false-confirmation rate by construction -- and
    the controller would have recalibrated on potholes, consuming reference vehicles to correct a
    drift that was never there.
    """
    confirmed = 0
    for seed in range(30):
        controller = _controller()
        plant = _Plant(controller, seed=seed)
        plant.run(300, reference_every=4)
        plant.fault(900.0)
        plant.run(4, reference_every=2)  # a handful of very bad passes
        plant.fault(0.0)
        plant.run(80, reference_every=2)
        confirmed += controller.recalibration_count

    assert confirmed <= 3, f"{confirmed}/30 blips were confirmed as drift"


@pytest.mark.slow
def test_the_detection_floor_is_set_by_the_detector_slack_not_by_the_controller() -> None:
    """How small a drift this loop can see at all, measured -- and the answer is a limitation.

    CUSUM's slack is what makes it a drift detector rather than an outlier detector: deviations
    smaller than ``slack`` sigmas never accumulate, so they are invisible *permanently*, not merely
    slowly. With the shipped ``slack=0.5`` that puts a hard floor under the whole control loop, and
    no amount of tuning in the controller can lift it. Measured over twenty runs of five hundred
    passes each, against a 50 kg residual spread:

    | drift | as sigma | detected |
    |---|---|---|
    | 25 kg | 0.5 | 0/20 |
    | 30 kg | 0.6 | 3/20 |
    | 50 kg | 1.0 | 12/20 |
    | 100 kg | 2.0 | 19/20 |

    So the honest statement of this system's sensitivity is about two sigma of the residual spread
    for reliable detection, and half a sigma for none at all. That is a number the paper has to
    quote rather than a threshold anyone can tune away, and it is the argument for reporting the
    residual spread alongside every detection claim.
    """

    def detected(shift: float, seeds: int = 20) -> int:
        hits = 0
        for seed in range(seeds):
            controller = _controller()
            plant = _Plant(controller, seed=200 + seed)
            plant.run(300, reference_every=4)
            plant.fault(shift)
            plant.run(500, reference_every=2)
            hits += controller.recalibration_count > 0
        return hits

    assert detected(25.0) == 0, "a drift at the slack should be structurally invisible"
    assert detected(100.0) >= 17, "two sigma should be caught almost every time"
    assert detected(25.0) < detected(50.0) < detected(100.0)


# -- which references a recalibration is allowed to use -------------------------------------------


def test_a_recalibration_uses_only_references_from_after_the_drift_began() -> None:
    """Measured on S4 and worth the change it forced.

    The first version refitted from the whole reference buffer, which spans both sides of the
    fault -- so the new profile was a compromise between the old regime and the new one, and the
    bias it was meant to remove only fell by about a third even after the loop had declared itself
    reconverged. References from before the drift describe a plant that no longer exists.

    Filtering from the moment the suspicion started is right for a ramp as well as a step: for a
    ramp it keeps the recent observations, which is what a drifting plant means.
    """
    seen: list[list[ReferenceObservation]] = []

    def capture(observations):
        seen.append(list(observations))
        return _fit_from(observations)

    controller = _controller(recalibrate=capture, min_reference_observations=5)
    plant = _Plant(controller, seed=71)

    # References from the healthy regime, then a fault, then references from the new one.
    for obs in _references(20, k=2.0e-4, start_s=0, seed=1):
        controller.offer_reference(obs)
    plant.run(300)

    plant.fault(600.0)
    plant.ts_s = 400
    for obs in _references(20, k=2.3e-4, start_s=400, seed=2):
        controller.offer_reference(obs)
    plant.run(60)

    assert seen, "the controller never recalibrated"
    used = seen[0]
    assert used, "refitted from nothing"
    assert all(o.ts_us >= 400 * SECOND for o in used), (
        "the refit used references from before the drift began, which describe the old plant"
    )


def test_it_waits_rather_than_refitting_on_a_mixture() -> None:
    """If there are not yet enough post-drift references, refitting on the pre-drift ones is worse
    than waiting: it produces a profile that is confidently wrong and then passes verification
    often enough to hide the problem."""
    attempts: list[int] = []

    def capture(observations):
        attempts.append(len(observations))
        return _fit_from(observations)

    controller = _controller(recalibrate=capture, min_reference_observations=10)
    for obs in _references(30, start_s=0):
        controller.offer_reference(obs)  # all from before the drift
    plant = _Plant(controller, seed=73)
    plant.run(300)
    plant.fault(600.0)
    plant.run(80)

    assert attempts == [], "refitted despite having no post-drift references"
    assert controller.state in {"DRIFT_SUSPECTED", "DEGRADED"}


@pytest.mark.slow
def test_the_confirmable_floor_follows_the_window_length_as_predicted() -> None:
    """The second sensitivity floor, and the arithmetic behind it.

        minimum confirmable shift = confirm_sigma * 1.2533 * sigma / sqrt(confirmation_passes)

    At the shipped ``confirm_sigma = 3`` that is 0.841 residual standard deviations with a
    twenty-pass window and 0.485 with a sixty-pass one. Worth pinning because it is the *binding*
    constraint at default settings -- tighter than the detector slack -- and because getting it
    wrong is silent: on S4_step_fault a twenty-pass window detected the injected step twice,
    confirmed it never, and finished in MONITORING with the bias entirely uncorrected.

    Measured at 0.8 sigma, which is chosen so the two floors do not confound each other: the
    detector alarms 11 times in 12 at *both* window lengths, so detection is not what changes.
    Only confirmation does, and it flips from 1/12 to 9/12 as the window crosses the shift. An
    earlier version of this test used 0.6 sigma and failed, because at 0.6 the detector is the
    binding floor and the window length barely matters.
    """
    import math

    def confirms(shift_sigma: float, passes: int, seeds: int = 12) -> tuple[int, int]:
        alarms = confirmed = 0
        for seed in range(seeds):
            controller = _controller(confirmation_passes=passes, min_reference_observations=5)
            plant = _Plant(controller, seed=500 + seed)
            plant.run(300, reference_every=4)
            plant.fault(shift_sigma * plant.scale)
            plant.run(500, reference_every=2)
            alarms += any(e.kind == "drift_detected" for e in controller.drain_events())
            confirmed += controller.recalibration_count > 0
        return alarms, confirmed

    def floor(passes: int) -> float:
        return 3.0 * 1.2533141373155003 / math.sqrt(passes)

    assert floor(20) == pytest.approx(0.841, abs=0.002)
    assert floor(60) == pytest.approx(0.485, abs=0.002)

    tight_alarms, tight_confirmed = confirms(0.8, passes=20)  # floor 0.841 > 0.8
    wide_alarms, wide_confirmed = confirms(0.8, passes=60)  # floor 0.485 < 0.8

    assert tight_alarms >= 9 and wide_alarms >= 9, "detection should not be what differs here"
    assert tight_confirmed <= 3, "a shift below the confirmable floor was confirmed anyway"
    assert wide_confirmed >= 7, "a shift above the confirmable floor was not confirmed"


# -- the blocking arm, for Stage C1 ------------------------------------------------------------
#
# `_monitor` is the only emitter of `drift_detected`, and `observe` dispatches to it only while the
# state is MONITORING. So an alarm raised while the controller is confirming, recalibrating,
# verifying or degraded is swallowed -- and `experiments/runner._control_row` scores detection
# recall from exactly those events. At one reference in ten on S4 the confirmation window alone is
# 9,818 s against an 1,800 s fault horizon, so a fault arriving during it cannot be recalled at all.
#
# `blocking=False` is the counterfactual arm: the alarm is reported from whatever state the machine
# is in. It deliberately does NOT change the state machine -- the question is whether suppression
# of the event causes the sensitivity inversion, and an arm that also reorganised the transitions
# would not answer it.


def _blocked_controller(**overrides):
    """A controller parked in DRIFT_SUSPECTED with a fresh alarm waiting behind it."""
    controller = _controller(confirmation_passes=1000, **overrides)
    plant = _Plant(controller, seed=7)
    plant.run(200, reference_every=2)
    plant.fault(6.0 * plant.scale)
    plant.run(40, reference_every=1)
    return controller, plant


def test_an_alarm_outside_monitoring_is_swallowed_by_default():
    controller, plant = _blocked_controller()
    assert controller.state == "DRIFT_SUSPECTED"
    controller.drain_events()

    plant.fault(12.0 * plant.scale)  # a second, larger excursion while the loop is busy
    plant.run(60, reference_every=1)

    emitted = [e for e in controller.drain_events() if e.kind == "drift_detected"]
    assert emitted == [], "default behaviour must keep blocking, or C1 has no control arm"
    assert controller.state == "DRIFT_SUSPECTED"


def test_non_blocking_reports_an_alarm_raised_outside_monitoring():
    controller, plant = _blocked_controller(blocking=False)
    assert controller.state == "DRIFT_SUSPECTED"
    controller.drain_events()

    plant.fault(12.0 * plant.scale)
    plant.run(60, reference_every=1)

    emitted = [e for e in controller.drain_events() if e.kind == "drift_detected"]
    assert emitted, "non-blocking must report the alarm the blocking arm swallows"
    assert controller.state == "DRIFT_SUSPECTED", (
        "the non-blocking arm reports the alarm; it must not also rearrange the state machine, "
        "or the comparison confounds two changes"
    )


def test_non_blocking_does_not_re_report_the_same_latched_alarm():
    """The detectors latch until reset, so a naive implementation emits on every later pass."""
    controller, plant = _blocked_controller(blocking=False)
    controller.drain_events()

    plant.fault(12.0 * plant.scale)
    plant.run(120, reference_every=1)

    emitted = [e for e in controller.drain_events() if e.kind == "drift_detected"]
    assert len(emitted) <= 3, (
        f"one excursion produced {len(emitted)} drift_detected events; a latched alarm must be "
        "acknowledged, or the false-alarm rate is an artefact of the pass count"
    )


def test_blocking_defaults_to_true_so_existing_results_keep_their_meaning():
    assert ControllerConfig().blocking is True


# -- the confirmation window's duration, for Stage D1 --------------------------------------------
#
# `confirmation_passes` counts RESIDUALS, and a residual exists only when a reference vehicle
# crosses. So the window's duration is confirmation_passes * reference_every_n / traffic_rate --
# it scales with the reference rate, which is the swept factor of the reference-rate experiment.
# The controller's own time constant therefore moved with the independent variable, which is the
# defect D1 fixes.
#
# The fix is a count WITH A TIME CAP: the window closes at whichever of the two comes first.
# `confirmation_max_s=None` is the old behaviour and stays the default, so no stored result
# changes meaning.
#
# Nothing extra is needed to keep the decision honest, because `_displaced` already scales the
# bar by 1/sqrt(n): a window truncated to a third of its residuals automatically demands a
# displacement sqrt(3) larger. The cap trades detection power for timeliness, and the gate
# charges for the trade rather than hiding it.


def _suspicious(**overrides):
    """A controller in DRIFT_SUSPECTED, with the clock under the test's control."""
    controller = _controller(confirmation_passes=1000, **overrides)
    plant = _Plant(controller, seed=11)
    plant.run(200, reference_every=2)
    plant.fault(6.0 * plant.scale)
    plant.run(10, reference_every=1)
    assert controller.state == "DRIFT_SUSPECTED"
    return controller, plant


def test_confirmation_window_is_unbounded_in_time_by_default():
    controller, plant = _suspicious()
    plant.run(400, reference_every=1)
    assert controller.state == "DRIFT_SUSPECTED", (
        "default must stay count-only, or every stored controller result changes meaning"
    )


def test_confirmation_max_s_closes_the_window_on_time():
    controller, plant = _suspicious(confirmation_max_s=30.0)
    plant.run(400, reference_every=1)
    assert controller.state != "DRIFT_SUSPECTED", (
        "the time cap did not close a window that 1000 residuals never would have"
    )


def test_confirmation_max_s_defaults_to_none():
    assert ControllerConfig().confirmation_max_s is None


def test_a_truncated_window_still_decides_on_the_residuals_it_has():
    """A real, large step must still confirm when the cap fires early."""
    controller, plant = _suspicious(confirmation_max_s=30.0, min_reference_observations=5)
    plant.run(400, reference_every=1)
    assert controller.recalibration_count >= 1, (
        "a six-sigma step inside a truncated window was not confirmed; the cap must shorten the "
        "window, not disable the gate"
    )


def test_a_truncated_window_with_too_few_residuals_does_not_confirm():
    """Below two residuals there is no median worth testing, so the honest answer is to stop."""
    controller = _controller(confirmation_passes=1000, confirmation_max_s=1e-9)
    plant = _Plant(controller, seed=12)
    plant.run(200, reference_every=2)
    plant.fault(20.0 * plant.scale)
    plant.run(100, reference_every=1)
    assert controller.recalibration_count == 0, (
        "confirmed a drift on fewer than two residuals, which is the decorative gate the "
        "confirm_sigma analysis exists to prevent"
    )
