"""The phase-5 checkpoint: ``S4_step_fault`` shows detection, recalibration and reconvergence.

Buildspec: *"Checkpoint: ``S4_step_fault`` shows detection, recalibration, and reconvergence on the
calibration dashboard."* Stated as something you can see, so this asserts it as something that
happened -- and, more importantly, measures it against the arm where the controller is switched off.
Same scenario, same seed, same pipeline, byte-identical sample stream; the controller is the only
difference, which is what makes the comparison mean anything.

A shortened S4 with the fault brought forward, so the whole thing runs in a test suite rather than
in three minutes. The full 16-hour result is in ``docs/controller.md``.
"""

from __future__ import annotations

import pytest

from wimsim.core.config import RunConfig, load_edge_config, load_run_config
from wimsim.experiments.closed_loop import run_closed_loop
from wimsim.experiments.offline import load_run

pytestmark = pytest.mark.slow

STEP_AT_S = 3600.0
DURATION_S = 14400.0


@pytest.fixture(scope="module")
def step_fault_run(tmp_path_factory):
    """Four hours of S4, with the sensitivity step at one hour.

    Long enough that the loop can detect, recalibrate *and* reconverge inside the scored window --
    at ninety minutes it could not, and the bias reduction measured 21 % rather than the 66 % the
    full-length run gives. A checkpoint that cannot reach its own conclusion is not one.
    """
    from wimsim.signal.writer import write_run

    # Loaded at its shipped length first: the config refuses a fault scheduled after the run ends,
    # which is a good validator and means the duration and the fault time have to move together.
    # `--set` deliberately cannot index into the fault list -- a dotted path that created list
    # entries would turn a typo into a new fault -- so the edit is made on the dumped dict and
    # re-validated, which exercises that validator rather than bypassing it.
    tree = load_run_config("S4_step_fault").model_dump(mode="python")
    tree["scenario"]["duration_s"] = DURATION_S
    tree["scenario"]["block_seconds"] = 60.0
    tree["scenario"]["output"]["samples"] = "none"
    # One sensitivity step, brought forward. The second fault is dropped rather than moved: one
    # step is what this checkpoint is about.
    step = dict(tree["scenario"]["faults"][0])
    step["t_start_s"] = STEP_AT_S
    tree["scenario"]["faults"] = [step]
    cfg = RunConfig.model_validate(tree)

    out = write_run(cfg, tmp_path_factory.mktemp("s4")).out_dir
    return load_run(out)


def _edge(control: bool):
    return load_edge_config(
        "default",
        overrides=[
            f"edge.control.enabled={'true' if control else 'false'}",
            "edge.control.reference_every_n=2",
            "edge.control.cooldown_s=0.0",
            "edge.control.confirmation_passes=30",
            "edge.control.verification_passes=30",
            "edge.control.min_reference_observations=40",
            "edge.drift.warmup=60",
        ],
    )


@pytest.fixture(scope="module")
def arms(step_fault_run):
    cfg, truth, _ = step_fault_run
    return {
        "off": run_closed_loop(cfg, truth, _edge(False), calibration_passes=60),
        "on": run_closed_loop(cfg, truth, _edge(True), calibration_passes=60),
    }


# -- the checkpoint, as the buildspec words it ----------------------------------------------------


def test_the_drift_is_detected(arms) -> None:
    assert arms["on"].alarms >= 1, "no detector raised an alarm on an injected sensitivity step"


def test_the_detectors_were_ready_before_the_fault_arrived(arms) -> None:
    """The check that makes the previous assertion meaningful.

    A detector's warm-up is counted in residuals and residuals arrive only on reference passes, so
    readiness costs ``warmup * reference_every_n`` passes. On the full-length S4 at the old
    defaults that was 33,144 s of a 57,600 s run -- past both faults, which the detector had by
    then learned as normal, reporting zero alarms and looking perfectly healthy. A run that could
    not have detected anything is not evidence that detection works.
    """
    result = arms["on"]
    assert result.detectors_ready_after_references is not None
    assert result.detectors_ready_after_references < result.n_references / 2


def test_it_recalibrates_and_activates_the_new_profile(arms) -> None:
    result = arms["on"]
    assert result.recalibrations >= 1
    assert len(result.profiles) >= 2, "a recalibration that activates no profile changes nothing"

    named = {e.calibration.profile_id for e in result.events}
    assert named <= {p.profile_id for p in result.profiles}
    assert len(named) >= 2, "every event still names the bootstrap profile"


def test_it_reconverges_rather_than_ending_degraded(arms) -> None:
    """Recalibrating is easy; recalibrating *correctly* is the claim. Ending in MONITORING means
    the verification window found the residuals back where they belong."""
    result = arms["on"]
    assert result.to_dict()["final_state"] == "MONITORING"


def test_the_profile_ids_are_distinct_per_activation(arms) -> None:
    """A refit can legitimately reproduce an earlier parameter set -- it means the reference buffer
    did not yet hold the post-fault evidence. That activation is still its own record, so the id
    carries an ordinal as well as the state hash. Keying on the hash alone took a run down."""
    ids = [p.profile_id for p in arms["on"].profiles]
    assert len(ids) == len(set(ids))


# -- against the arm with the controller switched off ---------------------------------------------


def test_the_controller_removes_most_of_the_bias_the_step_introduced(arms) -> None:
    """The headline number, and the reason bias rather than MAE is the one to quote.

    A sensitivity step makes the scale systematically wrong, so it moves the *bias*. MAE moves too
    but is dominated by the dynamic floor -- the error the vehicle brought with it, which no
    calibration can remove -- so it understates what the controller did.

    Measured on this four-hour window: -200.5 kg with the controller off, -17.8 kg with it on, a
    91 % reduction. Two fixes got it there from an initial 29 %: refitting only from references
    that postdate the drift, and a confirmation window long enough to confirm a 0.74-sigma step.
    """
    off, on = arms["off"], arms["on"]
    assert abs(on.score.bias_kg) < abs(off.score.bias_kg) * 0.25


def test_the_controller_does_not_make_the_accuracy_worse(arms) -> None:
    off, on = arms["off"], arms["on"]
    assert on.score.mae_kg <= off.score.mae_kg


def test_the_arm_with_the_controller_off_recalibrates_nothing(arms) -> None:
    """The control arm has to be genuinely passive, or it is not a control arm."""
    off = arms["off"]
    assert off.recalibrations == 0
    assert off.alarms == 0
    assert len(off.profiles) == 1


def test_both_arms_saw_the_identical_sample_stream(arms) -> None:
    """Same seed and same config mean a byte-identical stream (principle 4), so the two arms
    detected the same passes and the comparison is paired rather than merely similar."""
    off, on = arms["off"], arms["on"]
    assert off.n_detected == on.n_detected
    assert [e.event_id for e in off.events] == [e.event_id for e in on.events]
    assert [e.raw_peak for e in off.events] == [e.raw_peak for e in on.events]


def test_the_dynamic_floor_bounds_what_any_controller_could_achieve(arms) -> None:
    """Worth asserting so no future result can quietly claim to have beaten physics: the mean
    |applied - static| load is the error the vehicle's own bounce contributed, and no calibration
    removes it."""
    on = arms["on"]
    assert on.score.dynamic_floor_kg > 0.0
    assert on.score.mae_kg > on.score.dynamic_floor_kg


# -- the dashboard half of the checkpoint ----------------------------------------------------------


def test_every_phase_five_dashboard_panel_has_a_producer(step_fault_run) -> None:
    """The other half of "shows ... on the calibration dashboard", checked without a stack.

    ``tests/test_dashboards.py`` already asserts every panel queries a metric the registry
    declares, which catches a typo. It cannot catch the opposite gap: a declared metric that
    nothing ever emits, which renders exactly the same empty graph. This closes it from the
    producer side by running the loop and collecting what actually came out.

    The remaining unverified link is the live scrape, and that is what
    ``scripts/check_dashboards.py`` is for.
    """
    import json
    import pathlib
    import re

    from wimsim.observability.metrics import Metrics, RecordingSink

    cfg, truth, _ = step_fault_run
    sink = RecordingSink()
    result = run_closed_loop(cfg, truth, _edge(True), calibration_passes=60, metrics=Metrics(sink))
    assert result.recalibrations >= 1, "no recalibration, so the recalibration metric cannot fire"

    emitted = {record.name for record in sink.records}

    board = json.loads(
        (
            pathlib.Path(__file__).resolve().parents[1] / "dashboards" / "calibration-loop.json"
        ).read_text(encoding="utf-8")
    )
    queried: set[str] = set()
    for panel in board["panels"]:
        for target in panel.get("targets") or []:
            for token in re.findall(r"\bwim_[a-z0-9_]+\b", target.get("expr") or ""):
                for suffix in ("_bucket", "_sum", "_count"):
                    token = token.removesuffix(suffix)
                queried.add(token)

    #: Emitted by the truth exporter in experiments/, never by the estimator path (principle 1).
    truth_side = {"wim_cal_gain_true", "wim_cal_bias_true", "wim_temperature_true", "wim_mass_true"}
    #: StaticAffine carries no covariance; the Kalman filter does, and is covered separately.
    estimator_specific = {"wim_cal_covariance_trace"}

    missing = queried - emitted - truth_side - estimator_specific
    assert not missing, (
        f"the calibration dashboard queries metrics nothing emits: {sorted(missing)}"
    )


def test_the_kalman_arm_supplies_the_covariance_panel(step_fault_run) -> None:
    """The one panel the static baseline cannot fill, and the reason it looked broken in phase 4.

    ``wim_cal_covariance_trace`` is the convergence panel. StaticAffine has no covariance to
    report -- correctly, since it never updates -- so the panel was empty for a reason that had
    nothing to do with the dashboard. An adaptive estimator fills it.
    """
    from wimsim.core.config import load_edge_config
    from wimsim.observability.metrics import Metrics, RecordingSink

    cfg, truth, _ = step_fault_run
    sink = RecordingSink()
    run_closed_loop(
        cfg,
        truth,
        load_edge_config(
            "default",
            overrides=[
                "edge.estimate.estimator=kalman",
                "edge.control.enabled=true",
                "edge.control.reference_every_n=2",
            ],
        ),
        calibration_passes=60,
        metrics=Metrics(sink),
    )
    traces = sink.values("wim_cal_covariance_trace")
    assert traces, "the Kalman arm reported no covariance trace"
    assert all(t > 0.0 for t in traces)
