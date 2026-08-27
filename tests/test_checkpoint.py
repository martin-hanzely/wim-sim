"""The phase-2 checkpoint, as a test.

> Phase 2 -- edge pipeline offline. [...] *Checkpoint: MAE on S1_nominal.*

Slow (it generates and processes a whole run), and worth it: this is the only test that exercises
generator, preprocessor, detector, estimator and scoring together against ground truth. Everything
else checks a part in isolation, and a chain of individually correct parts can still be wrong at the
seams.

The thresholds are regression guards, not targets. They sit a factor of a few above what the
pipeline currently achieves, so ordinary numerical drift does not fail the build but a real
regression -- the despiker eating pulse peaks, say, which cost 80x -- does.
"""

from __future__ import annotations

import pytest

from wimsim.core.config import load_edge_config, load_run_config
from wimsim.experiments.offline import run_offline
from wimsim.signal.writer import write_run


@pytest.fixture(scope="module")
def s1_run(tmp_path_factory):
    """S1_nominal at its shipped length, generated once for the whole module."""
    cfg = load_run_config("S1_nominal", overrides=["scenario.output.samples=none"])
    result = write_run(cfg, tmp_path_factory.mktemp("s1"))
    import pandas as pd

    truth = pd.read_parquet(result.out_dir / "truth_passes.parquet")
    return cfg, truth


def test_checkpoint_mae_on_s1_nominal(s1_run) -> None:
    """Clean conditions, no drift, no faults: the pipeline should be limited only by sampling."""
    cfg, truth = s1_run
    result = run_offline(cfg, truth, load_edge_config("default"), calibration_passes=15)
    score = result.score

    assert score.recall == 1.0, f"missed {score.n_missed} of {score.n_truth} passes"
    assert score.n_false_positive == 0
    assert score.axle_count_accuracy == 1.0

    assert score.mae_kg < 10.0, f"MAE {score.mae_kg:.2f} kg"
    assert score.mape < 0.005, f"MAPE {100 * score.mape:.3f} %"
    assert abs(score.bias_kg) < 5.0, f"bias {score.bias_kg:+.2f} kg"


def test_a_filter_whose_cutoff_clears_the_pulse_band_does_no_harm(s1_run) -> None:
    """Regression guard on the measured cutoff.

    A 4th-order Butterworth at 500 Hz passes the narrowest pulse in the fleet intact. At 120 Hz it
    does not, and the damage is width-dependent -- which converts the speed-invariant peak feature
    into a speed-dependent one rather than merely adding noise.
    """
    cfg, truth = s1_run
    wide = run_offline(cfg, truth, load_edge_config("filtered"), calibration_passes=15)
    narrow = run_offline(
        cfg,
        truth,
        load_edge_config("filtered", overrides=["edge.preprocess.cutoff_hz=120.0"]),
        calibration_passes=15,
    )
    assert wide.score.mae_kg < 10.0, f"MAE {wide.score.mae_kg:.2f} kg at 500 Hz"
    assert narrow.score.mae_kg > 5.0 * wide.score.mae_kg


def test_despiking_does_not_cost_accuracy(s1_run) -> None:
    """Regression: the despiker used to eat 19.8 % of a car's peak and cost 80x in MAE."""
    cfg, truth = s1_run
    plain = run_offline(cfg, truth, load_edge_config("default"), calibration_passes=15)
    despiked = run_offline(
        cfg,
        truth,
        load_edge_config("default", overrides=["edge.preprocess.despike=true"]),
        calibration_passes=15,
    )
    assert despiked.score.mae_kg < 3.0 * plain.score.mae_kg


def test_the_area_feature_loses_to_peak_when_speed_varies(s1_run) -> None:
    """Not a defect -- the expected consequence of a single sensor being unable to measure speed.

    Area is proportional to load/speed. With speeds spanning 75-128 km/h and no way to observe
    them, that variation lands directly in the mass estimate. Pinned as a test because it is the
    phase-2 answer to the question the buildspec left open, and a future change that appears to
    "fix" it is far more likely to have broken the peak path.
    """
    cfg, truth = s1_run
    peak = run_offline(cfg, truth, load_edge_config("default"), calibration_passes=15)
    area = run_offline(cfg, truth, load_edge_config("area"), calibration_passes=15)
    assert area.score.mae_kg > 20.0 * peak.score.mae_kg
    assert area.score.recall == peak.score.recall, "both must still detect every vehicle"


def test_the_analytic_interval_is_optimistic_when_residuals_are_not_gaussian(s1_run) -> None:
    """Why phase 5 needs conformal prediction, measured rather than asserted.

    The peak path's residuals are near-Gaussian and its coverage lands near nominal. The area path's
    are speed-driven and heteroscedastic, and its coverage falls far short -- from an interval that
    is nonetheless far wider. An interval whose width is honest but whose coverage is not is the
    worst of both.
    """
    cfg, truth = s1_run
    peak = run_offline(cfg, truth, load_edge_config("default"), calibration_passes=15)
    area = run_offline(cfg, truth, load_edge_config("area"), calibration_passes=15)
    assert peak.score.coverage > 0.85
    assert area.score.coverage < peak.score.coverage
    assert area.score.mean_interval_width_kg > peak.score.mean_interval_width_kg


def test_mains_interference_hurts_more_than_its_power_and_breaks_coverage(s1_run) -> None:
    """Measured from the first real recording: mains dominates the in-band noise (+54 dB).

    It is *coherent*, so unlike white noise it does not average down over a 5 ms pulse -- the window
    sees a near-constant offset whose value depends on where in the mains cycle the axle arrived.
    Two consequences, both pinned here: accuracy falls several-fold, and empirical coverage falls
    well below nominal because the error is structured rather than Gaussian and the analytic
    interval misprices it.

    S1_nominal is the one scenario that keeps mains switched off, so that a non-zero error there can
    only mean a bug in the pipeline.
    """
    cfg, truth = s1_run
    edge = load_edge_config("default")
    clean = run_offline(cfg, truth, edge, calibration_passes=15)

    noisy_cfg = load_run_config(
        "S1_nominal",
        overrides=["scenario.output.samples=none", "scenario.noise.mains.enabled=true"],
    )
    noisy = run_offline(noisy_cfg, truth, edge, calibration_passes=15)

    assert noisy.score.mae_kg > 3.0 * clean.score.mae_kg
    assert noisy.score.coverage < clean.score.coverage
    assert noisy.score.recall == 1.0, "mains must not cost detections, only accuracy"


def test_no_pass_is_both_training_and_test_data(s1_run) -> None:
    cfg, truth = s1_run
    result = run_offline(cfg, truth, load_edge_config("default"), calibration_passes=15)
    assert result.score.n_truth == len(truth) - 15
    assert result.profile.provenance["n_reference_observations"] <= 15
