"""The loop closed: estimator, detectors, controller, conformal and the profile store together.

Every component has its own tests. This is the one that checks they compose, which is a different
question -- and historically the one that catches things a unit test cannot see, like a controller
that recalibrates correctly and then hands the pipeline a profile it never activates.

The load-bearing structural claim is where the truth enters. The controller needs residuals and a
residual needs a reference mass; that mass is read *here*, in ``experiments/``, and reaches
``calibration/`` only as a ``ReferenceObservation``. The last test in this file is the structural
half of that argument.
"""

from __future__ import annotations

import pytest

from wimsim.calibration import ProfileStore
from wimsim.core.config import load_edge_config
from wimsim.experiments.closed_loop import ClosedLoopResult, run_closed_loop
from wimsim.experiments.offline import load_run
from wimsim.observability.metrics import Metrics, RecordingSink


@pytest.fixture(scope="module")
def short_run_dir(tmp_path_factory):
    """A full-length S1. Long enough that split conformal reaches its nineteen-score minimum,
    which a shorter run cannot -- and a conformal arm that never activates tests nothing."""
    from wimsim.core.config import load_run_config
    from wimsim.signal.writer import write_run

    cfg = load_run_config(
        "S1_nominal",
        overrides=[
            "scenario.duration_s=900.0",
            "scenario.block_seconds=30.0",
            "scenario.output.samples=none",
        ],
    )
    return write_run(cfg, tmp_path_factory.mktemp("closed")).out_dir


@pytest.fixture
def loaded(short_run_dir):
    return load_run(short_run_dir)


def _edge(**overrides):
    """The default pipeline with dotted overrides. `edge.` prefix: see load_edge_config."""
    sets = [f"edge.{k}={v}" for k, v in overrides.items()]
    return load_edge_config("default", overrides=sets)


# -- it runs at all, and the numbers are the same when the controller is off ---------------------


def test_with_the_controller_off_it_matches_the_offline_runner(loaded) -> None:
    """The control arm of every experiment. If closing the loop changed the answer even with the
    controller disabled, no comparison between the two would mean anything."""
    from wimsim.experiments.offline import run_offline

    cfg, truth, _ = loaded
    edge_cfg = _edge(**{"control.enabled": "false"})

    offline = run_offline(cfg, truth, edge_cfg, calibration_passes=5)
    closed = run_closed_loop(cfg, truth, edge_cfg, calibration_passes=5)

    assert closed.score.n_matched == offline.score.n_matched
    assert closed.score.mae_kg == pytest.approx(offline.score.mae_kg, rel=1e-9)
    assert closed.recalibrations == 0
    assert closed.controller_events == []


def test_it_reports_what_it_did(loaded) -> None:
    cfg, truth, _ = loaded
    result = run_closed_loop(cfg, truth, _edge(), calibration_passes=5)
    assert isinstance(result, ClosedLoopResult)
    assert result.n_detected > 5
    assert len(result.events) == result.n_detected
    assert result.score is not None

    payload = result.to_dict()
    assert payload["estimator"] == "static_affine"
    assert payload["n_detected"] == result.n_detected
    assert payload["profiles"]


# -- the reference supply ----------------------------------------------------------------------


def test_only_one_pass_in_n_is_treated_as_a_reference(loaded) -> None:
    """The supply rate of known masses, which is the factor that decides whether
    self-calibration is possible at a site at all."""
    cfg, truth, _ = loaded
    dense = run_closed_loop(
        cfg,
        truth,
        _edge(**{"control.enabled": "true", "control.reference_every_n": "1"}),
        calibration_passes=5,
    )
    sparse = run_closed_loop(
        cfg,
        truth,
        _edge(**{"control.enabled": "true", "control.reference_every_n": "10"}),
        calibration_passes=5,
    )
    assert dense.n_references > sparse.n_references
    assert sparse.n_references >= 1


def test_no_reference_supply_means_no_residuals_and_no_control(loaded) -> None:
    """S7_sparse_reference in miniature. With nothing to compare against, the loop cannot close --
    and it must say so by doing nothing rather than by inventing a residual."""
    cfg, truth, _ = loaded
    result = run_closed_loop(
        cfg,
        truth,
        _edge(**{"control.enabled": "true", "control.reference_every_n": "100000"}),
        calibration_passes=5,
    )
    assert result.n_references <= 1
    assert result.recalibrations == 0


# -- the estimators ------------------------------------------------------------------------------


@pytest.mark.parametrize("estimator", ["static_affine", "rls", "kalman"])
def test_every_estimator_runs_through_the_closed_loop(loaded, estimator: str) -> None:
    """The ladder, end to end. Each produces masses, an interval that brackets them, and a
    profile that names itself."""
    cfg, truth, _ = loaded
    result = run_closed_loop(
        cfg,
        truth,
        _edge(**{"estimate.estimator": estimator, "control.enabled": "true"}),
        calibration_passes=8,
    )
    assert result.score.n_matched > 0
    assert result.profiles[0].state.estimator == estimator
    for event in result.events:
        assert event.mass_ci_low <= event.mass_kg <= event.mass_ci_high
        assert event.calibration.estimator == estimator


def test_the_adaptive_estimators_fold_in_every_reference_observation(loaded) -> None:
    """The difference between the rungs. StaticAffine counts observations and changes nothing;
    RLS and the Kalman filter move with each one."""
    cfg, truth, _ = loaded
    states = {}
    for estimator in ("static_affine", "rls"):
        result = run_closed_loop(
            cfg,
            truth,
            _edge(**{"estimate.estimator": estimator, "control.reference_every_n": "1"}),
            calibration_passes=8,
        )
        gains = [e.calibration.gain for e in result.events]
        states[estimator] = len({round(g, 12) for g in gains})

    assert states["static_affine"] == 1, "the baseline must not adapt; that is what makes it one"
    assert states["rls"] > 1, "RLS should have moved as references arrived"


# -- uncertainty ---------------------------------------------------------------------------------


def test_the_analytic_arm_reports_the_estimator_own_interval(loaded) -> None:
    cfg, truth, _ = loaded
    result = run_closed_loop(
        cfg, truth, _edge(**{"uncertainty.method": "analytic"}), calibration_passes=5
    )
    assert {e.interval_source for e in result.events} == {"residual_sd"}


def test_the_conformal_arm_takes_over_once_it_has_enough_scores(loaded) -> None:
    """Split conformal needs nineteen scores at 0.95 before it can say anything, so the first
    passes of any run necessarily carry the analytic band. The switch has to be visible in the
    event rather than assumed, which is what `interval_source` is for."""
    cfg, truth, _ = loaded
    result = run_closed_loop(
        cfg,
        truth,
        _edge(
            **{
                "uncertainty.method": "conformal",
                "uncertainty.conformal_score": "relative",
                "control.reference_every_n": "1",
            }
        ),
        calibration_passes=5,
    )
    sources = [e.interval_source for e in result.events]
    assert sources[0] == "residual_sd"
    assert "conformal_relative" in sources


def test_the_conformal_band_never_replaces_the_mass_only_the_interval(loaded) -> None:
    """The override exists to change how sure the station says it is, not what it says."""
    cfg, truth, _ = loaded
    analytic = run_closed_loop(
        cfg,
        truth,
        # Explicit: conformal is now the shipped default, so the arms have to be named.
        _edge(**{"uncertainty.method": "analytic", "control.reference_every_n": "1"}),
        calibration_passes=5,
    )
    conformal = run_closed_loop(
        cfg,
        truth,
        _edge(**{"uncertainty.method": "conformal", "control.reference_every_n": "1"}),
        calibration_passes=5,
    )
    assert [e.mass_kg for e in conformal.events] == pytest.approx(
        [e.mass_kg for e in analytic.events]
    )
    widths_differ = any(
        (c.mass_ci_high - c.mass_ci_low) != pytest.approx(a.mass_ci_high - a.mass_ci_low)
        for a, c in zip(analytic.events, conformal.events, strict=True)
    )
    assert widths_differ, "the conformal arm produced the analytic interval throughout"


# -- the controller in the loop --------------------------------------------------------------------


def test_the_controller_state_is_recorded_as_a_timeline(loaded) -> None:
    """`wim_cal_state` is drawn as a timeline on the calibration dashboard, so the run has to
    produce one rather than only a final state."""
    cfg, truth, _ = loaded
    result = run_closed_loop(
        cfg,
        truth,
        _edge(**{"control.enabled": "true", "control.reference_every_n": "1"}),
        calibration_passes=5,
    )
    assert result.state_timeline
    assert all(
        state in {"MONITORING", "DRIFT_SUSPECTED", "RECALIBRATING", "VERIFYING", "DEGRADED"}
        for _ts, state in result.state_timeline
    )
    assert [ts for ts, _ in result.state_timeline] == sorted(ts for ts, _ in result.state_timeline)


def test_the_controller_metrics_reach_the_registry(loaded) -> None:
    """Everything the calibration dashboard's phase-5 panels query."""
    cfg, truth, _ = loaded
    sink = RecordingSink()
    run_closed_loop(
        cfg,
        truth,
        _edge(**{"control.enabled": "true", "control.reference_every_n": "1"}),
        calibration_passes=5,
        metrics=Metrics(sink),
    )
    names = {record.name for record in sink.records}
    assert "wim_cal_residual" in names
    assert "wim_drift_statistic" in names
    assert "wim_cal_state" in names

    detectors = {r.attributes["detector"] for r in sink.records if r.name == "wim_drift_statistic"}
    assert detectors == {"cusum", "page_hinkley"}

    states = {r.attributes["state"] for r in sink.records if r.name == "wim_cal_state"}
    assert len(states) == 5, "the one-hot must cover every state, not only the active one"


def test_an_activated_profile_reaches_the_store_and_the_pipeline(loaded) -> None:
    """The gap a unit test cannot see: a controller can recalibrate correctly and hand back a
    profile that nothing ever activates, and every later mass would then still use the old one."""
    cfg, truth, _ = loaded
    result = run_closed_loop(
        cfg,
        truth,
        _edge(**{"control.enabled": "true", "control.reference_every_n": "1"}),
        calibration_passes=5,
    )
    named = {e.calibration.profile_id for e in result.events}
    assert named <= {p.profile_id for p in result.profiles}


def test_the_profile_store_records_the_history_when_one_is_supplied(loaded, tmp_path) -> None:
    cfg, truth, _ = loaded
    store = ProfileStore(tmp_path / "profiles.jsonl")
    result = run_closed_loop(
        cfg,
        truth,
        _edge(**{"control.enabled": "true", "control.reference_every_n": "1"}),
        calibration_passes=5,
        profile_store=store,
    )
    assert [p.profile_id for p in store] == [p.profile_id for p in result.profiles]
    assert store.active_at(result.events[-1].ts_peak) is not None


# -- errors ---------------------------------------------------------------------------------------


def test_too_few_detections_to_calibrate_is_a_clear_error(loaded) -> None:
    cfg, truth, _ = loaded
    with pytest.raises(ValueError, match="reserved for the initial calibration"):
        run_closed_loop(cfg, truth, _edge(), calibration_passes=100_000)


def test_a_duplicate_detector_is_refused_by_the_config(loaded) -> None:
    """`wim_drift_statistic` is labelled by detector name, so two of the same would collide."""
    from pydantic import ValidationError

    with pytest.raises(ValidationError, match="duplicate detectors"):
        _edge(**{"drift.detectors": '["cusum","cusum"]'})


# -- principle 1 -----------------------------------------------------------------------------------


def test_the_only_truth_reader_in_the_loop_is_the_reference_supply() -> None:
    """The structural half of the argument, asked precisely.

    The controller needs residuals, a residual needs a reference mass, and that mass comes from the
    truth log. What keeps principle 1 intact is *where*: this module reads it and hands a
    ``ReferenceObservation`` across, and nothing in ``calibration/`` or ``edge/`` ever reaches for
    one. ``test_truth_isolation.py`` proves the import graph; this pins the read sites.

    Asked as an AST question about ``truth[...]`` subscripts rather than by searching for column
    names as text -- the text version matched ``detection.ts_peak_us``, an attribute on a detection
    object, and reported a violation that was not there.
    """
    import ast
    import pathlib

    path = (
        pathlib.Path(__file__).resolve().parents[1]
        / "src"
        / "wimsim"
        / "experiments"
        / "closed_loop.py"
    )
    tree = ast.parse(path.read_text(encoding="utf-8"))

    #: function name -> the truth columns it subscripts
    reads: dict[str, set[str]] = {}
    for scope in ast.walk(tree):
        if not isinstance(scope, ast.FunctionDef):
            continue
        for node in ast.walk(scope):
            if not isinstance(node, ast.Subscript):
                continue
            base = node.value
            if not (isinstance(base, ast.Name) and base.id == "truth"):
                continue
            if isinstance(node.slice, ast.Constant) and isinstance(node.slice.value, str):
                reads.setdefault(scope.name, set()).add(node.slice.value)

    masses = {"true_mass_kg", "applied_mass_kg", "peak_load_kg", "area_load_kg_s"}
    for function, columns in reads.items():
        leaked = columns & masses
        assert not leaked or function == "__init__", (
            f"{function}() reads the truth mass columns {sorted(leaked)}. Only _TruthReferences "
            "may do that, so the boundary stays one greppable object."
        )

    # The remaining reads are timestamps, used to locate the calibration split -- a time, not a
    # mass. Listed rather than merely allowed, so that adding one is a deliberate act.
    assert reads.keys() <= {"__init__", "run_closed_loop", "_cutoff_s"}, sorted(reads)
    assert reads.get("run_closed_loop", set()) == {"t_entry_s"}


@pytest.mark.parametrize("blocking", [True, False])
def test_control_blocking_reaches_the_controller(blocking):
    """The Stage C1 arms differ in this flag alone, so a flag that did not arrive would make the
    two arms identical and the experiment would report a null it had not measured."""
    from wimsim.experiments.closed_loop import _controller_for

    edge_cfg = load_edge_config(
        "default",
        overrides=["edge.control.enabled=true", f"edge.control.blocking={str(blocking).lower()}"],
    )
    assert edge_cfg.control.blocking is blocking

    controller = _controller_for(edge_cfg, estimator=None, references=None)
    assert controller.config.blocking is blocking


def test_control_blocking_defaults_to_the_behaviour_every_earlier_sweep_ran():
    assert load_edge_config("default").control.blocking is True


@pytest.mark.parametrize("cap", [None, 900.0])
def test_confirmation_max_s_reaches_the_controller(cap):
    """Stage D's arms differ in this value, so a dropped flag would make them identical."""
    from wimsim.experiments.closed_loop import _controller_for

    overrides = ["edge.control.enabled=true"]
    if cap is not None:
        overrides.append(f"edge.control.confirmation_max_s={cap}")
    edge_cfg = load_edge_config("default", overrides=overrides)
    assert edge_cfg.control.confirmation_max_s == cap

    controller = _controller_for(edge_cfg, estimator=None, references=None)
    assert controller.config.confirmation_max_s == cap


def test_confirmation_window_is_uncapped_by_default():
    assert load_edge_config("default").control.confirmation_max_s is None
