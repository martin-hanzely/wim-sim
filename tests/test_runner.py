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

import pytest

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
