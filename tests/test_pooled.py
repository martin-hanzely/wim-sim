"""Leave-one-recording-out over the real corpus.

`score-real` fits and scores inside one 60-second recording, which on this corpus proves nothing:
the calibration and the test come from the same minute of the same drive-over, and two recordings
cannot be scored at all because every crossing is needed to fit.

The tests here are about the construction rather than the arithmetic, because the construction is
where a cross-validation goes wrong:

* a whole *recording* is held out, not random crossings -- crossings within a recording share a
  vehicle, a driver, a line across the platform and a minute of thermal state, and splitting them
  randomly leaks all of it across the fold boundary;
* a fold never sees its own observations in the calibration set;
* a fold that cannot be fitted is reported, not dropped.
"""

from __future__ import annotations

import math

import pytest

from wimsim.calibration import ReferenceObservation
from wimsim.core.config import load_edge_config
from wimsim.experiments.pooled import PooledResult, run_pooled


def _obs(masses, *, gain=3.0e-8, bias=0.0, noise=0.0, seed=0):
    import numpy as np

    rng = np.random.default_rng(seed)
    return [
        ReferenceObservation(
            ts_us=1_000_000 * i,
            feature=gain * m + bias + float(rng.normal(0.0, noise)),
            temp_c=20.0,
            reference_mass_kg=float(m),
        )
        for i, m in enumerate(masses)
    ]


def _patched(monkeypatch, corpus: dict[str, list[ReferenceObservation]]):
    """Stand in for detection, so these tests are about the fold structure and not about parquet."""
    from wimsim.experiments import pooled

    monkeypatch.setattr(
        pooled,
        "collect_observations",
        lambda run_dir, edge_cfg, **kw: corpus[str(run_dir)],
    )


def test_a_fold_never_sees_its_own_observations(monkeypatch) -> None:
    """The whole point. If the held-out recording is in the calibration set the number reported is
    a fit statistic wearing a cross-validation's name."""
    corpus = {
        "a": _obs([300.0, 460.0]),
        "b": _obs([320.0, 450.0]),
        "c": _obs([330.0, 470.0]),
    }
    _patched(monkeypatch, corpus)
    result = run_pooled(list(corpus), load_edge_config("default"))

    assert [f.run_id for f in result.folds] == ["a", "b", "c"]
    for fold in result.folds:
        assert fold.n_calibration == result.n_observations - fold.n_scored


def test_whole_recordings_are_held_out_not_individual_crossings(monkeypatch) -> None:
    """A random split over crossings would leak the vehicle, the driver, the line across the
    platform and the thermal state across the fold boundary, and report a number the site will not
    give."""
    corpus = {"a": _obs([300.0, 460.0, 330.0]), "b": _obs([320.0, 450.0])}
    _patched(monkeypatch, corpus)
    result = run_pooled(list(corpus), load_edge_config("default"))

    assert {f.n_scored for f in result.folds} == {3, 2}
    assert {f.n_calibration for f in result.folds} == {2, 3}


def test_a_clean_corpus_recovers_the_gain_it_was_built_with(monkeypatch) -> None:
    corpus = {
        "a": _obs([300.0, 500.0], gain=3.0e-8),
        "b": _obs([350.0, 550.0], gain=3.0e-8),
        "c": _obs([400.0, 600.0], gain=3.0e-8),
    }
    _patched(monkeypatch, corpus)
    result = run_pooled(list(corpus), load_edge_config("default"))

    assert result.mae_kg == pytest.approx(0.0, abs=1e-6)
    for fold in result.folds:
        # `EstimatorState.gain` is kg per feature unit, the direction the estimator predicts in --
        # the inverse of the sensor's strain per kg that the corpus was built with.
        assert fold.fitted_gain == pytest.approx(1.0 / 3.0e-8, rel=1e-6)
    assert result.gain_spread == pytest.approx(0.0, abs=1e-9)


def test_the_gain_spread_reports_how_much_the_calibration_moves(monkeypatch) -> None:
    """The number leave-one-out exists to produce. A calibration that changes materially depending
    on which recording it was fitted on has not transferred, whatever its MAE says."""
    corpus = {
        "a": _obs([300.0, 500.0], gain=3.0e-8),
        "b": _obs([300.0, 500.0], gain=3.0e-8),
        "c": _obs([300.0, 500.0], gain=6.0e-8),  # a recording from a different-looking sensor
    }
    _patched(monkeypatch, corpus)
    result = run_pooled(list(corpus), load_edge_config("default"))
    assert result.gain_spread > 0.2


def test_a_fold_that_cannot_be_fitted_is_reported_rather_than_dropped(monkeypatch) -> None:
    """Dropping it would let a corpus that half fails report the half that worked."""
    corpus = {
        "a": _obs([400.0, 400.0]),  # degenerate on its own, but it is never the calibration alone
        "b": _obs([400.0, 400.0]),
        "c": _obs([400.0, 400.0]),
    }
    _patched(monkeypatch, corpus)
    result = run_pooled(list(corpus), load_edge_config("default"))

    assert len(result.folds) == 3
    assert all(f.error for f in result.folds)
    assert all(math.isnan(f.mae_kg) for f in result.folds)


def test_a_corpus_of_one_recording_cannot_be_cross_validated(monkeypatch) -> None:
    """There is nothing to hold out against, and saying so beats reporting a fit as a test."""
    corpus = {"a": _obs([300.0, 460.0])}
    _patched(monkeypatch, corpus)
    result = run_pooled(list(corpus), load_edge_config("default"))

    assert result.folds == []
    assert result.n_recordings == 1
    assert math.isnan(result.mae_kg)


def test_the_corpus_figures_are_over_held_out_predictions_only(monkeypatch) -> None:
    """Every scored observation was predicted by a calibration that had not seen it."""
    corpus = {"a": _obs([300.0, 500.0]), "b": _obs([350.0, 550.0]), "c": _obs([400.0, 600.0])}
    _patched(monkeypatch, corpus)
    result = run_pooled(list(corpus), load_edge_config("default"))

    assert result.n_observations == 6
    assert sum(f.n_scored for f in result.folds) == 6


def test_it_serialises_flat_enough_to_write_down(monkeypatch) -> None:
    corpus = {"a": _obs([300.0, 500.0]), "b": _obs([350.0, 550.0])}
    _patched(monkeypatch, corpus)
    payload = run_pooled(list(corpus), load_edge_config("default")).to_dict()

    assert payload["n_recordings"] == 2
    assert isinstance(payload["folds"], list)
    assert {"run_id", "mae_kg", "fitted_gain"} <= set(payload["folds"][0])


def test_an_empty_corpus_is_not_a_crash() -> None:
    assert isinstance(run_pooled([], load_edge_config("default")), PooledResult)
