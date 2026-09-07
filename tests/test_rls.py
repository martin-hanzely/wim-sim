"""Recursive least squares: the same fit as the baseline, but never finished.

``StaticAffine`` fits once and freezes; RLS keeps the same model and the same objective and folds
each new reference observation into it. That single difference is the point of the ladder -- it
isolates *adaptivity*, changing nothing else -- so most of these tests are comparisons against the
baseline rather than absolute claims.

The forgetting factor is what makes it a controller rather than a bookkeeper. With ``lam = 1`` it is
exactly recursive OLS and converges to the batch answer; below 1 it discounts the past
geometrically, which is what lets it follow a plant whose gain has stepped -- and what makes it
vulnerable to covariance windup when nothing is exciting it, which is why the trace is bounded.
"""

from __future__ import annotations

import numpy as np
import pytest

from wimsim.calibration import (
    CalibrationEstimator,
    RecursiveLeastSquares,
    ReferenceObservation,
    StaticAffine,
)


def _observations(
    n: int = 200,
    *,
    k: float = 2.0e-4,
    q: float = 0.0,
    noise: float = 0.0,
    seed: int = 0,
    start: int = 0,
) -> list[ReferenceObservation]:
    """Reference passes from a known sensor-side law ``x = q + k*m``."""
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


def _fitted(lam: float = 1.0, **kwargs) -> RecursiveLeastSquares:
    est = RecursiveLeastSquares(forgetting=lam, **kwargs)
    est.fit(_observations(20, noise=1e-3, seed=99))
    return est


# -- the interface -------------------------------------------------------------------------


def test_satisfies_the_estimator_protocol() -> None:
    assert isinstance(RecursiveLeastSquares(), CalibrationEstimator)


def test_predicting_before_anything_is_known_is_refused() -> None:
    with pytest.raises(RuntimeError, match="not fitted"):
        RecursiveLeastSquares().predict(0.3, 20.0)


def test_it_can_start_from_updates_alone_with_no_batch_fit() -> None:
    """A station commissioned in the field has no calibration batch; it has reference vehicles
    arriving one at a time. The recursion is the whole point, so a batch fit must be optional."""
    est = RecursiveLeastSquares()
    for obs in _observations(40, noise=1e-4, seed=3):
        est.update(obs)
    assert est.state().fitted
    assert est.state().sensor_gain == pytest.approx(2.0e-4, rel=0.02)


# -- lambda = 1 is recursive OLS ------------------------------------------------------------


def test_with_no_forgetting_it_converges_on_the_batch_least_squares_answer() -> None:
    """The property that makes it a *credible* baseline rather than a new model: with lam = 1 the
    recursion and the batch fit are the same estimator, so any difference in the results is
    adaptivity and not a different objective."""
    obs = _observations(300, noise=2e-4, seed=7)

    batch = StaticAffine()
    batch.fit(obs)

    online = RecursiveLeastSquares(forgetting=1.0)
    for o in obs:
        online.update(o)

    assert online.state().gain == pytest.approx(batch.state().gain, rel=1e-6)
    # A milligram, on a scale that weighs forty-tonne trucks. What is left is the prior, below.
    assert online.state().bias == pytest.approx(batch.state().bias, abs=1e-3)


def test_the_only_gap_to_batch_least_squares_is_the_prior_and_it_scales_as_one_over_p0() -> None:
    """Recursive OLS from a finite prior is ridge regression with penalty ``1/P0``, so it does not
    reach batch OLS exactly -- it approaches it as the prior weakens.

    Worth pinning rather than absorbing into a loose tolerance, because the alternative explanation
    for a small mismatch is catastrophic cancellation in the covariance update, which is a real and
    well-known RLS failure and would get *worse* with more data rather than better. This shows the
    opposite on both counts: the error is proportional to ``1/P0`` and shrinks as observations
    accumulate.
    """
    obs = _observations(300, noise=2e-4, seed=7)
    batch = StaticAffine()
    batch.fit(obs)

    errors = []
    for p0 in (1e4, 1e6, 1e8):
        online = RecursiveLeastSquares(forgetting=1.0, initial_covariance=p0)
        for o in obs:
            online.update(o)
        errors.append(abs(online.state().bias - batch.state().bias))

    # Each hundredfold weakening of the prior buys two orders of magnitude.
    assert errors[0] / errors[1] == pytest.approx(100.0, rel=0.1)
    assert errors[1] / errors[2] == pytest.approx(100.0, rel=0.1)

    long_run = RecursiveLeastSquares(forgetting=1.0, initial_covariance=1e6)
    for o in _observations(3000, noise=2e-4, seed=7):
        long_run.update(o)
    long_batch = StaticAffine()
    long_batch.fit(_observations(3000, noise=2e-4, seed=7))
    assert abs(long_run.state().bias - long_batch.state().bias) < errors[1]


def test_the_order_of_observations_does_not_matter_without_forgetting() -> None:
    """Recursive OLS is order-invariant; anything that is not is carrying hidden state."""
    obs = _observations(120, noise=2e-4, seed=11)

    forwards = RecursiveLeastSquares(forgetting=1.0)
    for o in obs:
        forwards.update(o)
    backwards = RecursiveLeastSquares(forgetting=1.0)
    for o in reversed(obs):
        backwards.update(o)

    assert forwards.state().gain == pytest.approx(backwards.state().gain, rel=1e-8)


# -- forgetting is what makes it follow a step ----------------------------------------------


def test_it_follows_a_step_change_in_the_plant_and_the_baseline_does_not() -> None:
    """S4_step_fault in miniature, and the headline claim of the whole project: a scale whose gain
    has stepped is wrong forever if it was calibrated once."""
    before = _observations(120, k=2.0e-4, noise=1e-4, seed=1)
    after = _observations(120, k=2.3e-4, noise=1e-4, seed=2, start=120)

    baseline = StaticAffine()
    baseline.fit(before)

    adaptive = RecursiveLeastSquares(forgetting=0.97)
    adaptive.fit(before)
    for o in after:
        adaptive.update(o)

    assert adaptive.state().sensor_gain == pytest.approx(2.3e-4, rel=0.02)
    assert baseline.state().sensor_gain == pytest.approx(2.0e-4, rel=0.02)


def test_a_smaller_forgetting_factor_reconverges_sooner() -> None:
    """The trade the sweep exists to explore: fast forgetting tracks a step quickly and pays for it
    in variance. The ordering is the claim, not the individual numbers."""
    before = _observations(80, k=2.0e-4, noise=1e-4, seed=1)
    after = _observations(200, k=2.3e-4, noise=1e-4, seed=2, start=80)

    def passes_to_reconverge(lam: float) -> int:
        est = RecursiveLeastSquares(forgetting=lam)
        est.fit(before)
        for i, o in enumerate(after, start=1):
            est.update(o)
            if abs(est.state().sensor_gain - 2.3e-4) / 2.3e-4 < 0.01:
                return i
        return len(after) + 1

    assert passes_to_reconverge(0.95) < passes_to_reconverge(0.995)


def test_the_forgetting_factor_is_bounded_to_a_sane_range() -> None:
    for bad in (0.0, -0.5, 1.5):
        with pytest.raises(ValueError, match="forgetting"):
            RecursiveLeastSquares(forgetting=bad)


# -- covariance, and the windup that comes with forgetting ----------------------------------


def test_the_covariance_shrinks_as_evidence_accumulates() -> None:
    """The number the calibration dashboard draws: convergence made visible rather than argued."""
    est = RecursiveLeastSquares(forgetting=1.0)
    est.update(_observations(1, seed=5)[0])
    early = est.state().covariance_trace

    for o in _observations(200, noise=1e-4, seed=6):
        est.update(o)
    assert est.state().covariance_trace < early


def test_covariance_windup_is_bounded_when_nothing_is_exciting_the_fit() -> None:
    """The failure mode forgetting brings with it, and the reason for the trace bound.

    A fleet that is 95 % identical cars gives the recursion almost no new information about the
    slope, but a forgetting factor below 1 keeps discounting the old information anyway -- so P
    grows without limit and the estimator eventually swings wildly on a single pass. Real WiM
    traffic looks exactly like that at night.
    """
    est = RecursiveLeastSquares(forgetting=0.95, max_covariance_trace=1e12)
    est.fit(_observations(20, noise=1e-4, seed=8))

    identical = ReferenceObservation(ts_us=0, feature=0.30, temp_c=20.0, reference_mass_kg=1500.0)
    for _ in range(2000):
        est.update(identical)

    trace = est.state().covariance_trace
    assert np.isfinite(trace)
    assert trace <= 1e12 * (1.0 + 1e-9)


def test_an_unbounded_run_of_identical_passes_still_predicts_sanely() -> None:
    est = RecursiveLeastSquares(forgetting=0.95)
    est.fit(_observations(20, noise=1e-4, seed=8))
    for _ in range(500):
        est.update(
            ReferenceObservation(ts_us=0, feature=0.30, temp_c=20.0, reference_mass_kg=1500.0)
        )
    estimate = est.predict(0.30, 20.0)
    assert estimate.mass_kg == pytest.approx(1500.0, rel=0.05)


# -- intervals ------------------------------------------------------------------------------


def test_the_interval_brackets_the_estimate_and_reflects_the_residual_spread() -> None:
    quiet = _fitted()
    for o in _observations(200, noise=1e-5, seed=21):
        quiet.update(o)
    noisy = _fitted()
    for o in _observations(200, noise=1e-3, seed=21):
        noisy.update(o)

    a = quiet.predict(0.3, 20.0)
    b = noisy.predict(0.3, 20.0)
    assert a.mass_ci_low <= a.mass_kg <= a.mass_ci_high
    assert b.width > a.width


def test_the_interval_names_its_own_provenance() -> None:
    """Phase 5 compares three interval constructions; a number whose provenance is unknown cannot
    be compared with one whose is."""
    est = _fitted()
    assert est.predict(0.3, 20.0).interval_source == "rls_residual_sd"


# -- state ----------------------------------------------------------------------------------


def test_state_round_trips_and_predicts_identically() -> None:
    """A profile restored on a restarted station has to be the same estimator, covariance and all --
    otherwise every restart silently resets the loop's confidence."""
    est = _fitted(lam=0.98)
    for o in _observations(50, noise=1e-4, seed=31):
        est.update(o)

    restored = RecursiveLeastSquares.from_state(est.state())
    assert restored.predict(0.31, 20.0).mass_kg == pytest.approx(est.predict(0.31, 20.0).mass_kg)
    assert restored.state().covariance_trace == pytest.approx(est.state().covariance_trace)

    obs = _observations(1, seed=41)[0]
    assert restored.update(obs).gain == pytest.approx(est.update(obs).gain)


def test_the_state_reports_the_estimator_by_name() -> None:
    assert _fitted().state().estimator == "rls"


def test_the_update_count_tracks_the_observations_folded_in() -> None:
    est = RecursiveLeastSquares()
    for o in _observations(17, noise=1e-4, seed=2):
        est.update(o)
    assert est.state().update_count == 17


def test_the_forgetting_factor_survives_serialisation() -> None:
    """It is a parameter of the estimator, not of the run: a profile restored without it would
    adapt at a different rate than the one that was evaluated."""
    est = _fitted(lam=0.93)
    assert RecursiveLeastSquares.from_state(est.state()).forgetting == pytest.approx(0.93)
