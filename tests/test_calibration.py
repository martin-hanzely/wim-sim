"""The calibration interface and the StaticAffine baseline.

StaticAffine is the floor every later estimator has to beat, so its job is to be *correct and
boring*: fitted once by least squares, never updated afterwards, no hidden adaptation. If it turns
out to be hard to beat on a scenario, that is a result about the scenario.

Two conventions are pinned here because getting them wrong would be invisible until a dashboard
looked wrong months later:

* the estimator's own parameters are in the **prediction direction** (kg per sensor unit), because
  that is the error being minimised and scored;
* ``sensor_gain`` / ``sensor_bias`` are the **sensor-side** equivalents (sensor units per kg), which
  is the convention the truth log uses, so the calibration dashboard can overlay estimate on truth
  without either side silently inverting.
"""

from __future__ import annotations

import json

import numpy as np
import pytest

from wimsim.calibration import (
    CalibrationEstimator,
    CalibrationProfile,
    EstimatorState,
    MassEstimate,
    ReferenceObservation,
    StaticAffine,
)


def _observations(
    n: int = 200,
    *,
    k: float = 2.0e-4,
    q: float = 0.05,
    noise: float = 0.0,
    seed: int = 0,
    temp_c: float = 20.0,
) -> list[ReferenceObservation]:
    """Reference passes generated from a known sensor-side law x = q + k*m."""
    rng = np.random.default_rng(seed)
    masses = rng.uniform(1000.0, 40000.0, n)
    x = q + k * masses + noise * rng.standard_normal(n)
    return [
        ReferenceObservation(
            ts_us=1_000_000 * i,
            feature=float(x[i]),
            temp_c=temp_c,
            reference_mass_kg=float(masses[i]),
        )
        for i in range(n)
    ]


# -- the interface -------------------------------------------------------------------------


def test_static_affine_satisfies_the_protocol() -> None:
    est = StaticAffine()
    assert isinstance(est, CalibrationEstimator)


def test_predict_before_fitting_is_refused_rather_than_guessed() -> None:
    """An unfitted estimator returning 0 kg would look like a very light vehicle, not an error."""
    est = StaticAffine()
    assert not est.state().fitted
    with pytest.raises(RuntimeError, match="not fitted"):
        est.predict(1.5, 20.0)


# -- fitting -------------------------------------------------------------------------------


def test_recovers_the_generating_law_exactly_without_noise() -> None:
    est = StaticAffine()
    est.fit(_observations(noise=0.0))
    st = est.state()
    assert st.fitted
    assert st.sensor_gain == pytest.approx(2.0e-4, rel=1e-9)
    assert st.sensor_bias == pytest.approx(0.05, rel=1e-9)


def test_predicts_mass_to_machine_precision_without_noise() -> None:
    obs = _observations(noise=0.0)
    est = StaticAffine()
    est.fit(obs)
    for o in obs[:20]:
        got = est.predict(o.feature, o.temp_c)
        assert got.mass_kg == pytest.approx(o.reference_mass_kg, rel=1e-9)


def test_prediction_direction_parameters_are_the_inverse_of_the_sensor_side_ones() -> None:
    est = StaticAffine()
    est.fit(_observations(noise=0.0))
    st = est.state()
    x = 1.5
    assert st.gain * x + st.bias == pytest.approx((x - st.sensor_bias) / st.sensor_gain)


def test_fitting_needs_more_observations_than_free_parameters() -> None:
    est = StaticAffine()
    with pytest.raises(ValueError, match="at least"):
        est.fit(_observations(n=1))


def test_degenerate_observations_are_refused() -> None:
    """All-identical features carry no information about the slope; fitting would divide by zero."""
    obs = [
        ReferenceObservation(ts_us=i, feature=1.0, temp_c=20.0, reference_mass_kg=1000.0 + i)
        for i in range(10)
    ]
    est = StaticAffine()
    with pytest.raises(ValueError, match="degenerate"):
        est.fit(obs)


def test_noise_degrades_the_estimate_gracefully() -> None:
    est = StaticAffine()
    est.fit(_observations(n=500, noise=2.0e-4, seed=1))
    st = est.state()
    assert st.sensor_gain == pytest.approx(2.0e-4, rel=0.02)
    assert st.sensor_bias == pytest.approx(0.05, abs=5e-4)


# -- the baseline is static ------------------------------------------------------------------


def test_update_does_not_move_the_parameters() -> None:
    """StaticAffine is the *baseline*: fitted once, then frozen. Adaptation is what beats it."""
    est = StaticAffine()
    est.fit(_observations(noise=0.0))
    before = est.state()
    est.update(ReferenceObservation(ts_us=99, feature=10.0, temp_c=20.0, reference_mass_kg=1.0))
    after = est.state()
    assert after.gain == before.gain
    assert after.bias == before.bias
    assert after.update_count == before.update_count + 1, "observations are still counted"


# -- prediction intervals --------------------------------------------------------------------


def test_interval_brackets_the_estimate_and_widens_with_residual_noise() -> None:
    tight = StaticAffine()
    tight.fit(_observations(n=500, noise=5.0e-5, seed=2))
    loose = StaticAffine()
    loose.fit(_observations(n=500, noise=5.0e-4, seed=2))

    a = tight.predict(1.5, 20.0)
    b = loose.predict(1.5, 20.0)
    assert a.mass_ci_low <= a.mass_kg <= a.mass_ci_high
    assert (b.mass_ci_high - b.mass_ci_low) > 5 * (a.mass_ci_high - a.mass_ci_low)


def test_noise_free_fit_yields_a_degenerate_but_valid_interval() -> None:
    est = StaticAffine()
    est.fit(_observations(noise=0.0))
    got = est.predict(1.5, 20.0)
    assert got.mass_ci_low <= got.mass_kg <= got.mass_ci_high
    assert got.interval_source == "residual_sd"


def test_coverage_target_is_configurable_and_wider_targets_give_wider_intervals() -> None:
    obs = _observations(n=500, noise=2.0e-4, seed=3)
    narrow = StaticAffine(coverage_target=0.80)
    wide = StaticAffine(coverage_target=0.99)
    narrow.fit(obs)
    wide.fit(obs)
    n = narrow.predict(1.5, 20.0)
    w = wide.predict(1.5, 20.0)
    assert (w.mass_ci_high - w.mass_ci_low) > (n.mass_ci_high - n.mass_ci_low)


def test_empirical_coverage_is_near_nominal_on_gaussian_residuals() -> None:
    """Not a conformal guarantee -- that is phase 5 -- but the analytic interval should not be
    grossly miscalibrated when its own assumptions hold."""
    obs = _observations(n=4000, noise=2.0e-4, seed=4)
    est = StaticAffine(coverage_target=0.95)
    est.fit(obs)
    covered = sum(
        est.predict(o.feature, o.temp_c).mass_ci_low
        <= o.reference_mass_kg
        <= est.predict(o.feature, o.temp_c).mass_ci_high
        for o in obs
    )
    assert 0.92 <= covered / len(obs) <= 0.98


# -- temperature ------------------------------------------------------------------------------


def test_temp_coeff_is_carried_but_not_applied_twice() -> None:
    """Compensation happens in the preprocessor. The estimator records the coefficient it assumed
    so an event can say what was done, but must not apply it a second time."""
    est = StaticAffine(temp_coeff=-2.0e-4, t_ref_c=20.0)
    est.fit(_observations(noise=0.0, temp_c=20.0))
    at_ref = est.predict(1.5, 20.0).mass_kg
    at_thirty = est.predict(1.5, 30.0).mass_kg
    assert at_ref == pytest.approx(at_thirty)
    assert est.state().temp_coeff == -2.0e-4


# -- state ------------------------------------------------------------------------------------


def test_state_is_serialisable_and_the_hash_is_stable() -> None:
    est = StaticAffine()
    est.fit(_observations(noise=0.0))
    st = est.state()

    payload = st.to_dict()
    json.dumps(payload)  # must not raise: numpy scalars are not JSON-serialisable
    assert EstimatorState.from_dict(payload) == st
    assert EstimatorState.from_dict(payload).state_hash == st.state_hash


def test_state_hash_ignores_the_update_count_but_tracks_the_parameters() -> None:
    """The hash identifies *what the estimator computes*, so two estimators that predict
    identically hash identically even if one has seen more observations."""
    a = StaticAffine()
    a.fit(_observations(noise=0.0))
    b = StaticAffine()
    b.fit(_observations(noise=0.0))
    b.update(ReferenceObservation(ts_us=1, feature=1.0, temp_c=20.0, reference_mass_kg=5000.0))
    assert a.state().state_hash == b.state().state_hash

    c = StaticAffine()
    c.fit(_observations(noise=0.0, k=3.0e-4))
    assert c.state().state_hash != a.state().state_hash


def test_state_round_trips_through_a_profile() -> None:
    est = StaticAffine()
    est.fit(_observations(noise=0.0))
    profile = CalibrationProfile.from_state(
        est.state(), profile_id="p-0001", activated_ts_us=1748736000000000
    )
    restored = StaticAffine.from_state(profile.state)
    assert restored.predict(1.5, 20.0).mass_kg == pytest.approx(est.predict(1.5, 20.0).mass_kg)
    assert profile.state.state_hash == est.state().state_hash


def test_profile_serialises_to_plain_json() -> None:
    est = StaticAffine()
    est.fit(_observations(noise=0.0))
    profile = CalibrationProfile.from_state(
        est.state(), profile_id="p-0001", activated_ts_us=1748736000000000
    )
    text = json.dumps(profile.to_dict(), sort_keys=True)
    assert CalibrationProfile.from_dict(json.loads(text)) == profile


def test_mass_estimate_rejects_an_interval_that_does_not_bracket_the_estimate() -> None:
    with pytest.raises(ValueError, match="bracket"):
        MassEstimate(mass_kg=100.0, mass_ci_low=200.0, mass_ci_high=300.0, coverage_target=0.95)
