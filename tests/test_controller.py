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

    def __init__(self, controller, *, seed: int = 0, scale: float = 50.0) -> None:
        self.controller = controller
        self.rng = np.random.default_rng(seed)
        self.scale = scale
        self.offset = 0.0
        self.ts_s = 0
        self._seen_recalibrations = controller.recalibration_count

    def fault(self, offset: float) -> None:
        self.offset = float(offset)

    def run(self, n: int, *, step_s: int = 1, reference_every: int = 0) -> list:
        events = []
        for _ in range(n):
            if self.controller.recalibration_count != self._seen_recalibrations:
                self._seen_recalibrations = self.controller.recalibration_count
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
    for obs in _references(10):
        controller.offer_reference(obs)
    plant = _Plant(controller, seed=2)

    plant.run(300)
    assert controller.state == "MONITORING"

    plant.fault(400.0)
    plant.run(30)
    assert controller.recalibration_count == 1
    assert controller.state == "VERIFYING"

    plant.run(40)
    assert controller.state == "MONITORING"
    assert plant.offset == 0.0, "the plant should have been corrected by the refit"


def test_every_transition_is_announced_as_an_event() -> None:
    """The dashboard draws recalibrations as annotations and the controller state as a timeline;
    a transition that happened without an event is a timeline with a gap in it."""
    controller = _controller()
    for obs in _references(10):
        controller.offer_reference(obs)

    events = _run(controller, _noise(300, seed=6))
    events += _run(controller, _noise(300, shift=400.0, seed=7), start_s=300)
    events += _run(controller, _noise(40, seed=8), start_s=600)

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
    for obs in _references(10):
        controller.offer_reference(obs)
    _run(controller, _noise(300, seed=9))
    _run(controller, _noise(300, shift=400.0, seed=10), start_s=300)

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
    for obs in _references(10):
        controller.offer_reference(obs)
    _run(controller, _noise(300, seed=14))
    _run(controller, _noise(80, shift=500.0, seed=15), start_s=300)
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
    for obs in _references(10):
        controller.offer_reference(obs)
    _run(controller, _noise(300, seed=24))
    _run(controller, _noise(200, shift=500.0, seed=25), start_s=300)

    assert controller.state == "DEGRADED"
    reasons = [e.reason for e in controller.drain_events() if e.kind == "degraded"]
    assert any("degenerate reference set" in r for r in reasons)


def test_verification_that_fails_degrades_rather_than_declaring_success() -> None:
    """A recalibration that did not help is the most dangerous outcome of all, because the station
    has just told everyone it fixed itself."""
    controller = _controller(verification_passes=30)
    for obs in _references(10):
        controller.offer_reference(obs)
    _run(controller, _noise(300, seed=26))
    _run(controller, _noise(200, shift=500.0, seed=27), start_s=300)
    assert controller.recalibration_count == 1

    # The residuals are still displaced after the new profile went live.
    _run(controller, _noise(60, shift=500.0, seed=28), start_s=500)
    assert controller.state == "DEGRADED"


# -- cool-down and rate limiting -----------------------------------------------------------------


def test_a_cooldown_prevents_a_second_recalibration_too_soon() -> None:
    """Recalibration consumes reference vehicles and briefly makes the calibration worse. A
    controller that can do it twice in a minute will, on a noisy afternoon."""
    controller = _controller(cooldown_s=3600.0, verification_passes=5)
    for obs in _references(30):
        controller.offer_reference(obs)

    _run(controller, _noise(300, seed=29))
    _run(controller, _noise(200, shift=500.0, seed=30), start_s=300)
    assert controller.recalibration_count == 1
    first_at = controller.last_recalibration_ts_us

    _run(controller, _noise(300, shift=1500.0, seed=31), start_s=520)
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

    # The same drift, still unaddressed, but now the clock has moved on.
    plant.run(120, step_s=3600, reference_every=5)
    assert controller.recalibration_count == 2


# -- arbitration, which is a paper section ----------------------------------------------------------


def test_local_arbitration_acts_without_asking() -> None:
    controller = _controller(arbitration="local")
    for obs in _references(10):
        controller.offer_reference(obs)
    _run(controller, _noise(300, seed=35))
    _run(controller, _noise(200, shift=500.0, seed=36), start_s=300)
    assert controller.recalibration_count == 1


def test_cloud_arbitration_waits_for_a_grant_and_says_it_is_waiting() -> None:
    """A fleet operator may not want each station deciding for itself: a systematic error across
    twenty stations is a fleet problem, and twenty stations independently recalibrating away from
    it destroys the evidence. Which of the two applies is a deployment question, so it is a switch."""
    controller = _controller(arbitration="cloud")
    for obs in _references(10):
        controller.offer_reference(obs)
    _run(controller, _noise(300, seed=37))
    _run(controller, _noise(200, shift=500.0, seed=38), start_s=300)

    assert controller.state == "DRIFT_SUSPECTED"
    assert controller.awaiting_arbitration
    assert controller.recalibration_count == 0

    controller.grant_arbitration()
    _run(controller, _noise(5, shift=500.0, seed=39), start_s=500)
    assert controller.recalibration_count == 1
    assert not controller.awaiting_arbitration


def test_a_denied_arbitration_degrades_rather_than_waiting_forever() -> None:
    controller = _controller(arbitration="cloud")
    for obs in _references(10):
        controller.offer_reference(obs)
    _run(controller, _noise(300, seed=40))
    _run(controller, _noise(200, shift=500.0, seed=41), start_s=300)

    controller.deny_arbitration("fleet-wide error under investigation")
    _run(controller, _noise(5, shift=500.0, seed=42), start_s=500)
    assert controller.state == "DEGRADED"
    assert controller.recalibration_count == 0


# -- references --------------------------------------------------------------------------------


def test_too_few_references_is_not_enough_to_recalibrate() -> None:
    controller = _controller(min_reference_observations=8)
    for obs in _references(3):
        controller.offer_reference(obs)
    _run(controller, _noise(300, seed=43))
    _run(controller, _noise(200, shift=500.0, seed=44), start_s=300)
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
        for obs in _references(10):
            controller.offer_reference(obs)
        plant = _Plant(controller, seed=seed)
        plant.run(300)
        plant.fault(900.0)
        plant.run(4)  # a handful of very bad passes
        plant.fault(0.0)
        plant.run(80)
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
            for obs in _references(10):
                controller.offer_reference(obs)
            plant = _Plant(controller, seed=200 + seed)
            plant.run(300)
            plant.fault(shift)
            plant.run(500)
            hits += controller.recalibration_count > 0
        return hits

    assert detected(25.0) == 0, "a drift at the slack should be structurally invisible"
    assert detected(100.0) >= 17, "two sigma should be caught almost every time"
    assert detected(25.0) < detected(50.0) < detected(100.0)
