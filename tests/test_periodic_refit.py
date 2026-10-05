"""Periodic batch refit: the baseline a practitioner would actually run (revision item 1.3).

Between refits it is ``StaticAffine`` exactly -- frozen. Every ``refit_every`` reference
observations it repeats the commissioning calibration on the most recent ``refit_window`` of them,
and freezes again. So it adapts in steps rather than continuously, and its memory is the window.
"""

from __future__ import annotations

import numpy as np
import pytest

from wimsim.calibration import CalibrationEstimator, ReferenceObservation, StaticAffine
from wimsim.calibration.periodic_refit import PeriodicRefit
from wimsim.calibration.registry import build_estimator, estimator_from_state


def _observations(
    n: int, *, k: float = 2.0e-4, q: float = 0.0, noise: float = 0.0, seed: int = 0, start: int = 0
) -> list[ReferenceObservation]:
    rng = np.random.default_rng(seed)
    masses = rng.uniform(1000.0, 40000.0, n)
    x = q + k * masses + noise * rng.standard_normal(n)
    return [
        ReferenceObservation(
            ts_us=1_000_000 * (start + i),
            feature=float(x[i]),
            temp_c=20.0,
            reference_mass_kg=float(masses[i]),
        )
        for i in range(n)
    ]


def test_satisfies_the_estimator_protocol() -> None:
    assert isinstance(PeriodicRefit(), CalibrationEstimator)


def test_registered_under_its_own_name() -> None:
    est = build_estimator("periodic_refit", refit_every=10, refit_window=20)
    assert isinstance(est, PeriodicRefit)
    assert est.state().estimator == "periodic_refit"


def test_fit_matches_static_affine() -> None:
    cal = _observations(60, noise=1e-3, seed=1)
    a, b = PeriodicRefit().fit(cal), StaticAffine().fit(cal)
    assert a.gain == pytest.approx(b.gain)
    assert a.bias == pytest.approx(b.bias)


def test_frozen_between_refits() -> None:
    est = PeriodicRefit(refit_every=10, refit_window=10)
    before = est.fit(_observations(60, seed=1))
    # nine observations of a sensor whose gain has halved: below the interval, nothing moves
    for obs in _observations(9, k=1.0e-4, seed=2, start=100):
        after = est.update(obs)
    assert after.gain == before.gain
    assert after.bias == before.bias
    assert after.update_count == 9


def test_refits_on_the_recent_window_at_the_interval() -> None:
    est = PeriodicRefit(refit_every=10, refit_window=10)
    est.fit(_observations(60, k=2.0e-4, seed=1))
    for obs in _observations(10, k=1.0e-4, seed=2, start=100):
        state = est.update(obs)
    # noise-free, and the window holds only post-change observations: the new gain exactly
    assert state.gain == pytest.approx(1.0 / 1.0e-4, rel=1e-9)
    assert state.n_fit == 10


def test_window_longer_than_interval_mixes_old_and_new() -> None:
    est = PeriodicRefit(refit_every=10, refit_window=20)
    est.fit(_observations(60, k=2.0e-4, seed=1))
    for obs in _observations(10, k=1.0e-4, seed=2, start=100):
        state = est.update(obs)
    # ten old and ten new observations: the fit is neither calibration (OLS with an intercept over
    # a mixture of two lines is not bounded by their slopes, so nothing stronger holds)
    assert state.gain != pytest.approx(1.0 / 2.0e-4, rel=1e-3)
    assert state.gain != pytest.approx(1.0 / 1.0e-4, rel=1e-3)
    assert state.n_fit == 20


def test_window_never_reaches_past_what_it_has_seen() -> None:
    est = PeriodicRefit(refit_every=5, refit_window=1000)
    est.fit(_observations(60, seed=1))
    for obs in _observations(5, seed=2, start=100):
        state = est.update(obs)
    assert state.n_fit == 65  # the calibration batch plus five, not 1000


def test_state_round_trips_including_the_window() -> None:
    est = PeriodicRefit(refit_every=10, refit_window=10)
    est.fit(_observations(60, seed=1))
    for obs in _observations(7, k=1.0e-4, seed=2, start=100):
        est.update(obs)
    restored = estimator_from_state(est.state())
    original_next = restored_next = None
    for obs in _observations(3, k=1.0e-4, seed=3, start=200):
        original_next = est.update(obs)
        restored_next = restored.update(obs)
    assert restored_next.gain == pytest.approx(original_next.gain)
    assert restored_next.bias == pytest.approx(original_next.bias)


@pytest.mark.parametrize(("every", "window"), [(0, 10), (10, 1), (-1, 10)])
def test_refuses_meaningless_settings(every: int, window: int) -> None:
    with pytest.raises(ValueError):
        PeriodicRefit(refit_every=every, refit_window=window)


def test_predict_before_fit_refuses() -> None:
    with pytest.raises(RuntimeError):
        PeriodicRefit().predict(0.5, 20.0)
