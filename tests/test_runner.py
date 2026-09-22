"""The experiment runner: a declarative grid, one results table, every artifact stamped.

Buildspec section 10: "Declarative experiment YAML: scenario set x estimator set x seeds -> runs ->
results Parquet in ``data/results/<experiment_id>/``", every artifact stamped with config hash and
git commit.

The two properties that make results trustworthy rather than merely produced:

* **A run that fails does not take the sweep down, and does not disappear either.** Twenty runs
  where one raised is nineteen results and one recorded failure -- not nineteen results, because
  that silently changes what the table is a mean over.
* **Every row carries its own provenance.** A results table whose rows cannot each name the config
  and commit that produced them is a table nobody can rebuild.
"""

from __future__ import annotations

import json

import pandas as pd
import pytest

from wimsim.core.config import load_run_config
from wimsim.experiments.runner import (
    ExperimentSpec,
    load_experiment,
    run_experiment,
)


@pytest.fixture(scope="module")
def tiny_spec(tmp_path_factory) -> ExperimentSpec:
    """Two estimators over one very short scenario. Small enough to run in a test."""
    return ExperimentSpec(
        experiment_id="test-tiny",
        description="two estimators, one seed, one short scenario",
        scenarios=["S1_nominal"],
        estimators=["static_affine", "rls"],
        seeds=[1],
        overrides=[
            "scenario.duration_s=240.0",
            "scenario.block_seconds=60.0",
            "scenario.output.samples=none",
        ],
        edge_overrides=[
            "edge.control.enabled=true",
            "edge.control.reference_every_n=2",
            "edge.estimate.bootstrap_passes=10",
        ],
        calibration_passes=10,
    )


# -- the spec ------------------------------------------------------------------------------------


def test_a_spec_expands_to_the_full_grid(tiny_spec) -> None:
    runs = list(tiny_spec.grid())
    assert len(runs) == 2  # 1 scenario x 2 estimators x 1 seed
    assert {r.estimator for r in runs} == {"static_affine", "rls"}
    assert all(r.scenario == "S1_nominal" for r in runs)


def test_the_grid_is_the_product_of_all_three_axes() -> None:
    spec = ExperimentSpec(
        experiment_id="grid",
        scenarios=["S1_nominal", "S4_step_fault"],
        estimators=["static_affine", "rls", "kalman"],
        seeds=[1, 2],
    )
    runs = list(spec.grid())
    assert len(runs) == 12
    assert len({(r.scenario, r.estimator, r.seed) for r in runs}) == 12


def test_every_run_has_a_stable_identifier(tiny_spec) -> None:
    """Results are keyed by it, and a re-run has to land on the same key or a comparison across
    two invocations compares nothing."""
    first = [r.run_id for r in tiny_spec.grid()]
    second = [r.run_id for r in tiny_spec.grid()]
    assert first == second
    assert len(set(first)) == len(first)


def test_a_spec_round_trips_through_yaml(tmp_path) -> None:
    import yaml

    path = tmp_path / "sweep.yaml"
    path.write_text(
        yaml.safe_dump(
            {
                "experiment_id": "round-trip",
                "description": "a sweep",
                "scenarios": ["S1_nominal"],
                "estimators": ["static_affine"],
                "seeds": [7],
                "overrides": ["scenario.duration_s=120.0"],
            }
        ),
        encoding="utf-8",
    )
    spec = load_experiment(path)
    assert spec.experiment_id == "round-trip"
    assert spec.seeds == [7]
    assert spec.overrides == ["scenario.duration_s=120.0"]


def test_an_unknown_estimator_is_refused_before_anything_runs(tmp_path) -> None:
    """A sweep is expensive. Discovering a typo after the first hour is a waste, so the grid is
    validated up front."""
    with pytest.raises(ValueError, match="kalmen"):
        ExperimentSpec(
            experiment_id="bad", scenarios=["S1_nominal"], estimators=["kalmen"], seeds=[1]
        )


def test_an_empty_axis_is_refused() -> None:
    with pytest.raises(ValueError, match="scenarios"):
        ExperimentSpec(experiment_id="bad", scenarios=[], estimators=["rls"], seeds=[1])


# -- running -------------------------------------------------------------------------------------


@pytest.mark.slow
def test_a_sweep_produces_one_row_per_run(tiny_spec, tmp_path) -> None:
    import pandas as pd

    result = run_experiment(tiny_spec, out_dir=tmp_path / "results")
    assert result.n_runs == 2
    assert result.n_failed == 0

    frame = pd.read_parquet(result.results_path)
    assert len(frame) == 2
    assert set(frame["estimator"]) == {"static_affine", "rls"}
    assert frame["mae_kg"].notna().all()


@pytest.mark.slow
def test_every_row_carries_its_own_provenance(tiny_spec, tmp_path) -> None:
    """A results table whose rows cannot each name the config and commit that produced them is a
    table nobody can rebuild."""
    import pandas as pd

    result = run_experiment(tiny_spec, out_dir=tmp_path / "results")
    frame = pd.read_parquet(result.results_path)

    for column in ("config_hash", "edge_config_hash", "git_commit", "git_dirty", "wimsim_version"):
        assert column in frame.columns, column
        assert frame[column].notna().all()
    assert frame["config_hash"].str.len().eq(64).all()


@pytest.mark.slow
def test_a_manifest_records_the_sweep_itself(tiny_spec, tmp_path) -> None:
    result = run_experiment(tiny_spec, out_dir=tmp_path / "results")
    manifest = json.loads((result.out_dir / "manifest.json").read_text(encoding="utf-8"))

    assert manifest["experiment_id"] == "test-tiny"
    assert manifest["n_runs"] == 2
    assert manifest["spec"]["estimators"] == ["static_affine", "rls"]
    assert manifest["git_commit"]
    assert manifest["started_at"] and manifest["finished_at"]


@pytest.mark.slow
def test_a_failing_run_is_recorded_rather_than_swallowed_or_fatal(tmp_path) -> None:
    """Nineteen results and one failure, not nineteen results. Dropping the failure silently
    changes what every mean in the table is a mean over."""
    import pandas as pd

    spec = ExperimentSpec(
        experiment_id="one-bad",
        scenarios=["S1_nominal"],
        estimators=["static_affine"],
        seeds=[1, 2],
        overrides=["scenario.duration_s=240.0", "scenario.output.samples=none"],
        # Impossible: more calibration passes than the run can ever detect.
        calibration_passes=100_000,
    )
    result = run_experiment(spec, out_dir=tmp_path / "results")

    assert result.n_runs == 2
    assert result.n_failed == 2
    frame = pd.read_parquet(result.results_path)
    assert len(frame) == 2
    assert frame["failed"].all()
    assert frame["error"].str.contains("calibration").all()
    assert frame["mae_kg"].isna().all()


@pytest.mark.slow
def test_the_seed_actually_changes_the_run(tmp_path) -> None:
    """Otherwise a sweep over seeds is a sweep over nothing, and every error bar in the paper is
    an artefact."""
    import pandas as pd

    spec = ExperimentSpec(
        experiment_id="seeds",
        scenarios=["S1_nominal"],
        estimators=["static_affine"],
        seeds=[1, 2, 3],
        overrides=["scenario.duration_s=240.0", "scenario.output.samples=none"],
        calibration_passes=10,
    )
    result = run_experiment(spec, out_dir=tmp_path / "results")
    frame = pd.read_parquet(result.results_path)
    assert frame["config_hash"].nunique() == 3
    assert frame["mae_kg"].nunique() == 3


# -- the table -----------------------------------------------------------------------------------


@pytest.mark.slow
def test_a_markdown_table_is_written_next_to_the_parquet(tiny_spec, tmp_path) -> None:
    """The checkpoint is "a results table comparing all estimators across all scenarios", so the
    table is an artifact rather than something a reader has to produce from the parquet."""
    result = run_experiment(tiny_spec, out_dir=tmp_path / "results")
    table = (result.out_dir / "results.md").read_text(encoding="utf-8")

    assert "S1_nominal" in table
    assert "static_affine" in table and "rls" in table
    assert "MAE" in table
    assert "test-tiny" in table, "the table should name the experiment that produced it"
    assert result.git_commit[:8] in table, "and the commit, so it can be rebuilt"


@pytest.mark.slow
def test_the_table_says_when_a_run_failed(tmp_path) -> None:
    spec = ExperimentSpec(
        experiment_id="bad-table",
        scenarios=["S1_nominal"],
        estimators=["static_affine"],
        seeds=[1],
        overrides=["scenario.duration_s=240.0", "scenario.output.samples=none"],
        calibration_passes=100_000,
    )
    result = run_experiment(spec, out_dir=tmp_path / "results")
    table = (result.out_dir / "results.md").read_text(encoding="utf-8")
    assert "failed" in table.lower()


@pytest.mark.slow
def test_the_results_schema_does_not_depend_on_how_many_runs_succeeded(tmp_path) -> None:
    """A sweep where everything failed produced a parquet with no `mae_kg` column at all, because
    the score keys were only added on the success path. That makes the *shape* of the output depend
    on the luck of the runs, which breaks every consumer at exactly the moment they most need to
    look -- and turns "did this column go missing, or was it all null?" into an unanswerable
    question."""
    import pandas as pd

    def sweep(calibration_passes: int, name: str):
        spec = ExperimentSpec(
            experiment_id=name,
            scenarios=["S1_nominal"],
            estimators=["static_affine"],
            seeds=[1],
            overrides=["scenario.duration_s=240.0", "scenario.output.samples=none"],
            calibration_passes=calibration_passes,
        )
        return pd.read_parquet(run_experiment(spec, out_dir=tmp_path / name).results_path)

    good = sweep(10, "all-good")
    bad = sweep(100_000, "all-bad")

    assert list(good.columns) == list(bad.columns)
    assert bad["mae_kg"].isna().all()
    assert good["mae_kg"].notna().all()


def test_a_scenario_can_be_given_overrides_of_its_own() -> None:
    """Scenarios in one sweep differ in length by three hundred times -- S1 ships at 15 minutes and
    S2 at 72 hours -- so a single global `overrides` list cannot give both a sensible duration.

    Without this, `ladder` scored S1 on two passes: 62 crossings, 60 of them spent on the
    calibration window. A row built on two passes sits in the table looking exactly like a row
    built on four thousand.
    """
    spec = ExperimentSpec(
        experiment_id="t",
        scenarios=["S1_nominal", "S2_thermal_cycle"],
        estimators=["static_affine"],
        seeds=[1],
        overrides=["scenario.output.samples=none"],
        scenario_overrides={"S1_nominal": ["scenario.duration_s=7200"]},
    )
    cells = {c.scenario: c for c in spec.grid()}

    assert spec.overrides_for("S1_nominal") == [
        "scenario.output.samples=none",
        "scenario.duration_s=7200",
    ], "the scenario's own overrides must come last, so they win"
    assert spec.overrides_for("S2_thermal_cycle") == ["scenario.output.samples=none"]
    assert set(cells) == {"S1_nominal", "S2_thermal_cycle"}


def test_overrides_for_a_scenario_that_is_not_in_the_sweep_are_refused() -> None:
    """A typo here is a setting that silently does nothing, which is the same failure the unknown-
    key check on the YAML exists to prevent."""
    with pytest.raises(ValueError, match="not in this sweep"):
        ExperimentSpec(
            experiment_id="t",
            scenarios=["S1_nominal"],
            estimators=["static_affine"],
            seeds=[1],
            scenario_overrides={"S9_typo": ["scenario.duration_s=7200"]},
        )


def test_the_table_says_how_many_passes_each_row_is_a_mean_over() -> None:
    """A row scored on two passes and a row scored on four thousand are the same width in a
    markdown table, and every summary statistic in them -- MAE, bias, coverage -- reads the same.
    `ladder` produced exactly that: S1 ships at 15 minutes, so 60 of its 62 crossings went to the
    calibration window and the remaining two set the coverage to 0.5000.

    Without the count in the table there is nothing on the page to distrust it by.
    """
    from wimsim.experiments.table import markdown_table

    frame = pd.DataFrame(
        [
            {
                "scenario": "S1_nominal",
                "estimator": "static_affine",
                "seed": 1,
                "n_matched": 2,
                "mae_kg": 1.09,
                "coverage": 0.5,
                "failed": False,
            },
            {
                "scenario": "S6_combined",
                "estimator": "static_affine",
                "seed": 1,
                "n_matched": 4210,
                "mae_kg": 180.4,
                "coverage": 0.94,
                "failed": False,
            },
        ]
    )
    table = markdown_table(frame, experiment_id="t", git_commit="0" * 40)
    assert "| 2 |" in table
    assert "| 4210 |" in table


def test_a_sweep_writes_its_figures_beside_its_table(tiny_spec, tmp_path) -> None:
    """Buildspec section 10 asks for the table *and* matplotlib figures in the same place. A
    results directory a reader has to post-process is a results directory nobody looks at."""
    result = run_experiment(tiny_spec, out_dir=tmp_path / "results")
    figures = result.out_dir / "figures"
    assert figures.is_dir()
    assert (figures / "README.md").is_file(), "the captions travel with the figures"


def test_only_faults_that_move_the_calibration_are_scored_as_detections() -> None:
    """A connectivity loss does not make the scale wrong, so a drift detector that stays quiet
    through one is correct rather than blind.

    Regression, and a bad one: `_fault_times_us` said exactly this in its docstring and then
    counted every fault that had a start time. `S5_outage`'s three faults are a connectivity loss,
    a publish delay and a 45-second ADC dropout -- none of them touches the sensor's gain -- so the
    first `ladder` sweep reported `recall 0.000, missed 3` on all nine S5 runs. Read off the table
    that says "the drift detectors caught nothing", when what actually happened is that they were
    scored against three events they are not built to see and should not fire on.
    """
    from wimsim.experiments.runner import CALIBRATION_FAULTS, _fault_times_us

    assert CALIBRATION_FAULTS == frozenset({"gain_instability", "sensor_displacement"})

    truth = pd.DataFrame({"ts_peak_us": [1_000_000_000], "t_peak_s": [0.0]})
    cfg = load_run_config("S5_outage")
    assert cfg.scenario.faults, "S5 should still carry its transport faults"
    assert _fault_times_us(cfg, truth) == []


def test_a_sensitivity_fault_is_still_scored() -> None:
    """The counterpart: filtering must not empty the column it was meant to fix."""
    from wimsim.experiments.runner import _fault_times_us

    truth = pd.DataFrame({"ts_peak_us": [0], "t_peak_s": [0.0]})
    cfg = load_run_config("S4_step_fault")
    times = _fault_times_us(cfg, truth)
    assert len(times) == 2, "S4 injects two sensitivity steps"
    assert times == sorted(times)


def test_a_scenario_mixing_both_counts_only_the_calibration_half() -> None:
    """`S6_combined` overlaps six fault mechanisms, of which two move the calibration. Scoring the
    detector against all six made its recall look six times worse than it is."""
    from wimsim.experiments.runner import _fault_times_us

    truth = pd.DataFrame({"ts_peak_us": [0], "t_peak_s": [0.0]})
    cfg = load_run_config("S6_combined")
    assert len(cfg.scenario.faults) == 6
    assert len(_fault_times_us(cfg, truth)) == 2


# -- the reference rate as an axis ---------------------------------------------------------------


def test_the_reference_rate_can_be_swept() -> None:
    """The ladder asked a question it could not answer: at one reference vehicle in ten the
    discrete MAPE-K loop is a backstop -- Kalman recalibrated zero times on S4 and was still the
    most accurate arm -- while phase 5 at one-in-two showed the loop clearly earning its keep.

    The crossover is the central claim of the product and it was unmeasurable, because the
    reference rate was a scalar setting rather than an axis.
    """
    spec = ExperimentSpec(
        experiment_id="t",
        scenarios=["S4_step_fault"],
        estimators=["kalman"],
        seeds=[1],
        reference_rates=[2, 10, 50],
    )
    cells = list(spec.grid())
    assert [c.reference_every_n for c in cells] == [2, 10, 50]
    assert len({c.run_id for c in cells}) == 3, "each cell needs its own id"
    assert all("ref" in c.run_id for c in cells)


def test_a_sweep_that_does_not_vary_the_rate_keeps_its_run_ids() -> None:
    """`ladder` names a single rate. Its ids should not grow a suffix that distinguishes nothing --
    a run id names what separates a cell from its neighbours."""
    spec = ExperimentSpec(
        experiment_id="t",
        scenarios=["S4_step_fault"],
        estimators=["kalman"],
        seeds=[1, 2],
        reference_every_n=10,
    )
    cells = list(spec.grid())
    assert [c.run_id for c in cells] == [
        "S4_step_fault__kalman__seed1",
        "S4_step_fault__kalman__seed2",
    ]
    assert all(c.reference_every_n == 10 for c in cells)


def test_the_scalar_still_works_when_no_axis_is_given() -> None:
    spec = ExperimentSpec(
        experiment_id="t", scenarios=["S1_nominal"], estimators=["rls"], seeds=[1]
    )
    assert [c.reference_every_n for c in spec.grid()] == [None]


def test_naming_both_the_axis_and_the_scalar_is_refused() -> None:
    """Two settings for one thing, one of them silently ignored, is the failure the unknown-key
    check exists to prevent -- it just arrives by a different route."""
    with pytest.raises(ValueError, match="reference_every_n"):
        ExperimentSpec(
            experiment_id="t",
            scenarios=["S1_nominal"],
            estimators=["rls"],
            seeds=[1],
            reference_every_n=10,
            reference_rates=[2, 10],
        )


def test_a_reference_rate_must_be_a_positive_integer() -> None:
    with pytest.raises(ValueError, match="reference_rates"):
        ExperimentSpec(
            experiment_id="t",
            scenarios=["S1_nominal"],
            estimators=["rls"],
            seeds=[1],
            reference_rates=[10, 0],
        )


def test_each_cell_runs_at_its_own_rate() -> None:
    """The axis is worthless if the rate does not reach the pipeline. This is the wiring that the
    phase-5 bug -- an adaptive estimator rebuilt from state, so `update()` never reached the
    emitted events -- is the reason to test rather than assume."""
    from wimsim.experiments.runner import _edge_for

    spec = ExperimentSpec(
        experiment_id="t",
        scenarios=["S4_step_fault"],
        estimators=["kalman"],
        seeds=[1],
        reference_rates=[2, 25],
    )
    rates = [_edge_for(spec, cell).control.reference_every_n for cell in spec.grid()]
    assert rates == [2, 25]


def test_the_controller_can_be_swept_against_its_own_counterfactual() -> None:
    """ "Does the loop earn its keep at this reference rate" is a two-arm question, and the arm is
    the identical stream with the controller off. The README calls that "the arm every claim about
    the controller has to be measured against"; phase 5 measured S4 both ways by hand.

    Without it the rate sweep shows how accuracy varies with reference rate but not how much of
    that accuracy came from the loop -- which is the thing being asked.
    """
    spec = ExperimentSpec(
        experiment_id="t",
        scenarios=["S4_step_fault"],
        estimators=["static_affine"],
        seeds=[1],
        reference_rates=[2, 10],
        control_arms=[True, False],
    )
    cells = list(spec.grid())
    assert len(cells) == 4
    assert [(c.reference_every_n, c.control) for c in cells] == [
        (2, True),
        (2, False),
        (10, True),
        (10, False),
    ]
    assert {c.run_id for c in cells} == {
        "S4_step_fault__static_affine__seed1__ref2__control",
        "S4_step_fault__static_affine__seed1__ref2__open",
        "S4_step_fault__static_affine__seed1__ref10__control",
        "S4_step_fault__static_affine__seed1__ref10__open",
    }


def test_a_single_arm_sweep_keeps_its_run_ids() -> None:
    spec = ExperimentSpec(
        experiment_id="t", scenarios=["S1_nominal"], estimators=["rls"], seeds=[1]
    )
    cells = list(spec.grid())
    assert [c.run_id for c in cells] == ["S1_nominal__rls__seed1"]
    assert cells[0].control is None, "None leaves the edge config's own setting alone"


def test_each_arm_reaches_the_pipeline() -> None:
    from wimsim.experiments.runner import _edge_for

    spec = ExperimentSpec(
        experiment_id="t",
        scenarios=["S4_step_fault"],
        estimators=["rls"],
        seeds=[1],
        control_arms=[True, False],
    )
    assert [_edge_for(spec, c).control.enabled for c in spec.grid()] == [True, False]


def test_a_sweep_records_each_cell_as_it_finishes(tiny_spec, tmp_path) -> None:
    """A 180-run sweep that writes nothing until the last cell loses everything if it is
    interrupted -- which is not hypothetical: the first reference-rate run was killed at cell 30
    of 180 after 99 minutes and left an empty directory.

    Each row is appended as it completes, so an interrupted sweep can be inspected and its
    remaining cells re-run rather than the whole thing repeated.
    """
    result = run_experiment(tiny_spec, out_dir=tmp_path / "results")
    assert (result.out_dir / "results.parquet").is_file()
    assert not (result.out_dir / "rows.partial.jsonl").exists(), (
        "a finished sweep must not leave a partial log behind -- its presence is the signal that "
        "a sweep did NOT finish, and a stale one would be a lie"
    )


def test_the_partial_log_survives_an_interrupted_sweep(tmp_path) -> None:
    """The point of the log is the case where the sweep never reaches its own writer."""
    import json

    from wimsim.experiments.runner import _append_partial

    out = tmp_path / "results"
    out.mkdir()
    _append_partial(out, {"run_id": "a", "mae_kg": 1.0})
    _append_partial(out, {"run_id": "b", "mae_kg": 2.0})

    lines = (out / "rows.partial.jsonl").read_text(encoding="utf-8").strip().splitlines()
    assert [json.loads(line)["run_id"] for line in lines] == ["a", "b"]


def test_the_partial_log_tolerates_a_row_that_will_not_serialise(tmp_path) -> None:
    """A crash inside the progress log would take down a sweep that was otherwise fine, which is
    the opposite of what it is for."""
    from wimsim.experiments.runner import _append_partial

    out = tmp_path / "results"
    out.mkdir()
    _append_partial(out, {"run_id": "a", "when": object()})
    assert (out / "rows.partial.jsonl").is_file()


def test_every_column_the_template_declares_is_actually_filled(tiny_spec, tmp_path) -> None:
    """`_ROW_TEMPLATE` lists the columns and the row builders list them again, with nothing tying
    the two together. That duplication drifts: `coverage_expected` and `n_interval_fallback` were
    added to the template and not to `_score_row`, so a 180-run sweep produced both columns full of
    NaN and the evidence for the finding they were added for was missing from it.

    A column that is always null is worse than a missing one -- it looks measured.
    """
    result = run_experiment(tiny_spec, out_dir=tmp_path / "results")
    frame = result.frame

    # Columns that are genuinely null for a successful run: the error text, and the control metrics
    # for a scenario carrying no calibration faults.
    expected_null = {
        "error",
        "reconverge_s",
        "reconverge_passes",
        "reconverged",
        "reconverge_departed",
        "reconverge_measurable",
        "baseline_error_kg",
        "final_error_kg",
        "mean_detection_delay_s",
        "recall",
        # Undefined when the configured interval construction never produced one, which is
        # exactly what happens on a run this short: conformal needs 19 scored references
        # and `tiny_spec` never gets there, so every interval is a fallback. That is the
        # same finding the reference-rate sweep made, at small scale.
        "coverage_expected",
    }
    always_null = {c for c in frame.columns if frame[c].isna().all()} - expected_null
    assert not always_null, (
        f"these columns are declared and never filled: {sorted(always_null)}. Either a row builder "
        "is missing them or the template should not declare them."
    )


def test_a_sweep_can_name_the_station_it_runs_on() -> None:
    """Every sweep before this ran on whichever station the scenario named, which is `default` --
    the contact-force model. The hardware the real recordings came from is an influence-line strain
    platform, so no synthetic result corresponded to it and the sim-to-real chain was broken
    structurally: the simulator was validated against recordings from an instrument it was not
    modelling.

    Without a station axis that cannot be fixed, because the station is an argument to
    `load_run_config` and the runner was never passing one.
    """
    spec = ExperimentSpec(
        experiment_id="t",
        scenarios=["S1_nominal"],
        estimators=["static_affine"],
        seeds=[1],
        station="cintron_sim",
    )
    assert spec.station == "cintron_sim"
    assert spec.to_dict()["station"] == "cintron_sim"


def test_the_station_reaches_the_generated_config() -> None:
    """The axis is worthless if it does not change the instrument -- `cintron_sim` carries a k0 four
    orders of magnitude from the default's, so a wrong station is not subtle."""
    from wimsim.core.config import load_run_config

    spec = ExperimentSpec(
        experiment_id="t",
        scenarios=["S1_nominal"],
        estimators=["static_affine"],
        seeds=[1],
        station="cintron_sim",
    )
    cell = next(iter(spec.grid()))
    cfg = load_run_config(cell.scenario, spec.station, overrides=spec.overrides_for(cell.scenario))
    assert cfg.station.station_id == "ST-CINTRON-1-SIM"
    assert cfg.station.sensor.k0 != load_run_config(cell.scenario).station.sensor.k0


def test_no_station_named_keeps_the_scenario_default() -> None:
    spec = ExperimentSpec(
        experiment_id="t", scenarios=["S1_nominal"], estimators=["rls"], seeds=[1]
    )
    assert spec.station is None


def test_the_edge_config_can_be_swept() -> None:
    """Two things need it and neither can be done otherwise: comparing detectors, which live in the
    edge config, and sweeping recalibration frequency, which is driven by `confirm_sigma`.

    The per-detector table the manuscript's section IV-G assumes exists cannot be produced without
    this -- only two of the four detectors are enabled in the shipped config, so every detection
    number reported so far is the behaviour of that pair.
    """
    spec = ExperimentSpec(
        experiment_id="t",
        scenarios=["S4_step_fault"],
        estimators=["rls"],
        seeds=[1],
        edge_configs=["detect_cusum", "detect_all4"],
    )
    cells = list(spec.grid())
    assert [c.edge_config for c in cells] == ["detect_cusum", "detect_all4"]
    assert {c.run_id for c in cells} == {
        "S4_step_fault__rls__seed1__detect_cusum",
        "S4_step_fault__rls__seed1__detect_all4",
    }


def test_a_single_edge_config_keeps_its_run_ids_and_the_scalar_still_works() -> None:
    spec = ExperimentSpec(
        experiment_id="t",
        scenarios=["S1_nominal"],
        estimators=["rls"],
        seeds=[1],
        edge_config="filtered",
    )
    cells = list(spec.grid())
    assert [c.run_id for c in cells] == ["S1_nominal__rls__seed1"]
    assert cells[0].edge_config == "filtered"


def test_naming_both_the_edge_axis_and_the_scalar_is_refused() -> None:
    with pytest.raises(ValueError, match="edge_config"):
        ExperimentSpec(
            experiment_id="t",
            scenarios=["S1_nominal"],
            estimators=["rls"],
            seeds=[1],
            edge_config="filtered",
            edge_configs=["default", "filtered"],
        )
