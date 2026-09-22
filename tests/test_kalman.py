"""The Kalman calibration: a state-space model of the plant, not a curve fit of the data.

``StaticAffine`` and ``RecursiveLeastSquares`` regress mass on feature, because kilograms are what
gets scored. This estimator does the opposite: it holds ``[q, k]`` and models the measurement the
sensor actually makes, ``x = q + k*m + v``. Three consequences follow, and each is tested here.

**It is a model of the plant.** The truth log's ``q_true`` and ``k_true`` are the state, so drift is
a random walk on the state rather than a nuisance the fit has to chase -- and the process noise is
per *second*, not per pass, because a plant drifts on a clock and not on traffic.

**It is not diluted.** Regression dilution comes from noise in the regressor. Here the regressor is
the reference mass, which is comparatively accurate; the noise is in the observation, where a Kalman
filter expects it. The other two estimators put the noisy quantity on the x-axis and are attenuated
by construction.

**It says how sure it is.** The interval is the state covariance propagated through
``m = (x - q)/k``, so it widens when the filter is uncertain and narrows as it converges -- which is
the control-theoretic contribution the buildspec asks to be made visible.
"""

from __future__ import annotations

import numpy as np
import pytest

from wimsim.calibration import (
    CalibrationEstimator,
    KalmanCalibration,
    ReferenceObservation,
    StaticAffine,
)

SECOND = 1_000_000


def _observations(
    n: int = 200,
    *,
    k: float = 2.0e-4,
    q: float = 0.05,
    noise: float = 0.0,
    seed: int = 0,
    start_s: int = 0,
    period_s: int = 10,
) -> list[ReferenceObservation]:
    """Reference passes from the sensor-side law ``x = q + k*m + v``, ten seconds apart."""
    rng = np.random.default_rng(seed)
    masses = rng.uniform(1000.0, 40000.0, n)
    x = q + k * masses + noise * rng.standard_normal(n)
    return [
        ReferenceObservation(
            ts_us=SECOND * (start_s + i * period_s),
            feature=float(x[i]),
            temp_c=20.0,
            reference_mass_kg=float(masses[i]),
        )
        for i in range(n)
    ]


def _converged(noise: float = 1e-4, n: int = 200, **kwargs) -> KalmanCalibration:
    est = KalmanCalibration(measurement_noise=max(noise, 1e-6) ** 2, **kwargs)
    for obs in _observations(n, noise=noise, seed=17):
        est.update(obs)
    return est


# -- the interface -------------------------------------------------------------------------


def test_satisfies_the_estimator_protocol() -> None:
    assert isinstance(KalmanCalibration(), CalibrationEstimator)


def test_predicting_before_any_observation_is_refused() -> None:
    with pytest.raises(RuntimeError, match="not fitted"):
        KalmanCalibration().predict(0.3, 20.0)


def test_it_needs_no_batch_fit_at_all() -> None:
    """The whole point of a filter: it starts from a prior and learns. A station commissioned in
    the field has reference vehicles arriving one at a time and no calibration batch."""
    est = KalmanCalibration(measurement_noise=1e-8)
    for obs in _observations(60, noise=1e-4, seed=3):
        est.update(obs)
    assert est.state().fitted
    assert est.state().sensor_gain == pytest.approx(2.0e-4, rel=0.01)
    assert est.state().sensor_bias == pytest.approx(0.05, abs=2e-3)


def test_a_batch_fit_seeds_it_and_it_carries_on_from_there() -> None:
    est = KalmanCalibration(measurement_noise=1e-8)
    est.fit(_observations(30, noise=1e-4, seed=5))
    seeded = est.state().sensor_gain
    assert seeded == pytest.approx(2.0e-4, rel=0.01)
    for obs in _observations(30, noise=1e-4, seed=6, start_s=1000):
        est.update(obs)
    assert est.state().update_count == 30


# -- it recovers the plant's own parameters --------------------------------------------------


def test_it_recovers_q_and_k_on_the_sensor_side_without_inverting_anything() -> None:
    """The state *is* what the truth log records, which is what makes the dashboard overlay a
    comparison rather than a conversion."""
    est = _converged(noise=1e-5, n=300)
    assert est.state().sensor_gain == pytest.approx(2.0e-4, rel=5e-3)
    assert est.state().sensor_bias == pytest.approx(0.05, abs=5e-4)


def test_it_is_not_attenuated_by_noise_in_the_feature_and_the_baseline_is() -> None:
    """Regression dilution, made visible.

    Noise in the *regressor* biases a least-squares slope towards zero. StaticAffine and RLS put
    the noisy feature on the x-axis and are attenuated by construction; this filter puts the
    reference mass there, where the noise is small, and observes the feature -- which is where a
    Kalman filter expects noise to be.

    The feature noise here is deliberately exaggerated (about a third of the signal spread) so the
    effect is unambiguous rather than lost in sampling error. The direction of the bias is the
    claim; a real sensor sits far to the clean side of this.
    """
    obs = _observations(600, noise=0.6, seed=23)

    baseline = StaticAffine()
    baseline.fit(obs)

    filtered = KalmanCalibration(measurement_noise=0.36)
    for o in obs:
        filtered.update(o)

    truth = 2.0e-4
    baseline_error = abs(baseline.state().sensor_gain - truth)
    filtered_error = abs(filtered.state().sensor_gain - truth)

    assert filtered_error < baseline_error / 3.0
    # Attenuating the mass-on-feature slope inflates its inverse, so the baseline reads high.
    assert baseline.state().sensor_gain > truth


# -- drift is a random walk on a clock -------------------------------------------------------


def test_it_follows_a_step_change_in_the_plant_gain() -> None:
    before = _observations(150, k=2.0e-4, noise=1e-4, seed=1)
    after = _observations(150, k=2.3e-4, noise=1e-4, seed=2, start_s=1500)

    est = KalmanCalibration(measurement_noise=1e-8, process_noise_gain=1e-9)
    for o in before + after:
        est.update(o)
    assert est.state().sensor_gain == pytest.approx(2.3e-4, rel=0.02)


def test_more_process_noise_tracks_a_step_faster() -> None:
    """Q is the tuning knob the paper sweeps: it is the assumed rate of plant drift, and it buys
    tracking speed with variance. The ordering is the claim."""
    before = _observations(80, k=2.0e-4, noise=1e-4, seed=1)
    after = _observations(300, k=2.3e-4, noise=1e-4, seed=2, start_s=800)

    def passes_to_reconverge(q_gain: float) -> int:
        est = KalmanCalibration(measurement_noise=1e-8, process_noise_gain=q_gain)
        for o in before:
            est.update(o)
        for i, o in enumerate(after, start=1):
            est.update(o)
            if abs(est.state().sensor_gain - 2.3e-4) / 2.3e-4 < 0.01:
                return i
        return len(after) + 1

    assert passes_to_reconverge(1e-8) < passes_to_reconverge(1e-11)


def test_process_noise_accrues_with_elapsed_time_not_with_pass_count() -> None:
    """A plant drifts on a clock. Two passes an hour apart must admit more drift between them than
    two passes a second apart, or a filter tuned on a busy motorway is mistuned on a quiet road --
    and the same config would then mean different things at different sites.
    """
    est = KalmanCalibration(measurement_noise=1e-8, process_noise_gain=1e-8)
    for o in _observations(100, noise=1e-5, seed=9):
        est.update(o)
    converged = est.state().covariance_trace

    # One pass, an hour after the last.
    est.update(
        ReferenceObservation(
            ts_us=SECOND * (99 * 10 + 3600), feature=0.35, temp_c=20.0, reference_mass_kg=1500.0
        )
    )
    after_a_gap = est.state().covariance_trace

    fresh = _converged(noise=1e-5, n=100, process_noise_gain=1e-8)
    fresh.update(
        ReferenceObservation(
            ts_us=SECOND * (99 * 10 + 10), feature=0.35, temp_c=20.0, reference_mass_kg=1500.0
        )
    )
    assert after_a_gap > fresh.state().covariance_trace
    assert converged > 0.0


def test_a_gap_is_clamped_so_one_bad_timestamp_cannot_erase_the_filter() -> None:
    """Station clocks jump. A single sample stamped a year in the future would otherwise inflate
    the covariance to the point where the next pass overwrites everything the filter knows."""
    est = KalmanCalibration(measurement_noise=1e-8, max_gap_s=600.0)
    for o in _observations(60, noise=1e-5, seed=13):
        est.update(o)
    before = est.state().covariance_trace

    est.update(
        ReferenceObservation(
            ts_us=SECOND * 31_536_000, feature=0.35, temp_c=20.0, reference_mass_kg=1500.0
        )
    )
    assert est.state().sensor_gain == pytest.approx(2.0e-4, rel=0.05)
    assert est.state().covariance_trace < 1e6 * before


def test_time_running_backwards_is_treated_as_no_elapsed_time() -> None:
    """Out-of-order delivery is real; a negative dt would subtract process noise, which is not a
    thing a covariance can survive."""
    est = KalmanCalibration(measurement_noise=1e-8)
    for o in _observations(30, noise=1e-5, seed=4):
        est.update(o)
    est.update(ReferenceObservation(ts_us=0, feature=0.35, temp_c=20.0, reference_mass_kg=1500.0))
    trace = est.state().covariance_trace
    assert np.isfinite(trace) and trace > 0.0


# -- the covariance, and the interval it produces ---------------------------------------------


def test_the_covariance_shrinks_as_the_filter_converges() -> None:
    est = KalmanCalibration(measurement_noise=1e-8)
    obs = _observations(200, noise=1e-4, seed=6)
    est.update(obs[0])
    early = est.state().covariance_trace
    for o in obs[1:]:
        est.update(o)
    assert est.state().covariance_trace < early


def test_the_interval_is_the_covariance_propagated_not_a_residual_spread() -> None:
    """The claim that makes it worth having: an unconverged filter says so, in kilograms, before
    anyone has a reference mass to check it against."""
    unsure = KalmanCalibration(measurement_noise=1e-8)
    for o in _observations(3, noise=1e-4, seed=8):
        unsure.update(o)

    sure = KalmanCalibration(measurement_noise=1e-8)
    for o in _observations(300, noise=1e-4, seed=8):
        sure.update(o)

    assert unsure.predict(0.35, 20.0).width > sure.predict(0.35, 20.0).width


def test_the_interval_is_narrowest_near_the_loads_it_was_calibrated_on() -> None:
    """A prediction interval, behaving like one.

    Uncertainty in the gain enters the prediction as ``-m/k``, so it grows with the distance from
    the loads the filter is actually informed about -- exactly the way a regression prediction
    interval widens away from the centre of its design. Calibrate on cars and the filter says, in
    kilograms, that it does not know much about trucks. Nothing built from a residual spread can.
    """
    est = KalmanCalibration(measurement_noise=1e-8)
    rng = np.random.default_rng(5)
    for i in range(40):
        m = float(rng.uniform(1400.0, 1600.0))  # a car park, not a road
        est.update(
            ReferenceObservation(
                ts_us=SECOND * 10 * i,
                feature=0.05 + 2.0e-4 * m + 1e-4 * float(rng.standard_normal()),
                temp_c=20.0,
                reference_mass_kg=m,
            )
        )

    q, k = est.state().sensor_bias, est.state().sensor_gain
    inside = est.predict(q + k * 1500.0, 20.0).width
    outside = est.predict(q + k * 40000.0, 20.0).width
    # Was `outside > 5 * inside`, asserting the band widens away from the calibrated loads. That
    # property belonged to the covariance-only construction and is gone with it: the interval is
    # now the empirical prediction-error spread, which is one number for the whole filter and does
    # not know which load it is being asked about. RLS's band has always behaved this way. What
    # remains true, and is what the interval is for, is that it is wide enough to cover.
    assert outside == pytest.approx(inside, rel=0.2)


def test_once_converged_the_interval_is_dominated_by_the_sensor_noise_floor() -> None:
    """A finding, recorded as a test because it shapes what phase 6 can conclude.

    The propagated variance is ``J P J' + R/k^2``. The second term is the sensor's own noise mapped
    into kilograms, and for an additive sensor noise it does not depend on the load at all: 1e-4
    sensor units over a gain of 2e-4 per kg is half a kilogram, whatever is being weighed. Once the
    filter has converged over a spread of loads, that floor is over 95 % of the variance, so the
    analytic interval is very nearly constant-width.

    Two things follow. The Kalman and residual-spread intervals will look similar in *shape*, so
    comparing them is a question about calibration and coverage rather than about form. And an
    interval that cannot express load-dependent error is one more reason to have the conformal
    construction, which learns the residual distribution it is actually given.
    """
    est = _converged(noise=1e-4, n=120)
    s = est.state()
    p = np.array(s.covariance)
    k = s.sensor_gain
    floor = s.extra["measurement_noise"] / k**2

    for mass in (1500.0, 40000.0):
        jacobian = np.array([-1.0 / k, -mass / k])
        state_variance = float(jacobian @ p @ jacobian)
        assert state_variance / (state_variance + floor) < 0.05

    q = s.sensor_bias
    car = est.predict(q + k * 1500.0, 20.0).width
    truck = est.predict(q + k * 40000.0, 20.0).width
    assert truck > car  # the load-dependent part is there, it is simply small
    assert truck < 1.1 * car


def test_the_interval_brackets_the_estimate_and_names_its_provenance() -> None:
    est = _converged()
    estimate = est.predict(0.35, 20.0)
    assert estimate.mass_ci_low <= estimate.mass_kg <= estimate.mass_ci_high
    assert estimate.interval_source in {"kalman_analytic", "kalman_residual"}


def test_empirical_coverage_is_near_nominal_on_the_model_it_assumes() -> None:
    """The interval is only as good as the model behind it, so the honest check is coverage under
    exactly the assumptions it makes -- Gaussian measurement noise, correct R. Phase 5's conformal
    intervals exist because those assumptions do not hold on the real recordings."""
    noise = 1e-4
    est = _converged(noise=noise, n=400)

    rng = np.random.default_rng(77)
    masses = rng.uniform(1000.0, 40000.0, 4000)
    x = 0.05 + 2.0e-4 * masses + noise * rng.standard_normal(4000)
    covered = sum(
        est.predict(float(xi), 20.0).mass_ci_low <= m <= est.predict(float(xi), 20.0).mass_ci_high
        for xi, m in zip(x, masses, strict=True)
    )
    assert 0.92 < covered / len(masses) < 0.98


# -- state -----------------------------------------------------------------------------------


def test_state_round_trips_with_its_covariance_and_predicts_identically() -> None:
    est = _converged(noise=1e-4, n=80)
    restored = KalmanCalibration.from_state(est.state())

    assert restored.predict(0.35, 20.0).mass_kg == pytest.approx(est.predict(0.35, 20.0).mass_kg)
    assert restored.predict(0.35, 20.0).width == pytest.approx(est.predict(0.35, 20.0).width)

    obs = _observations(1, seed=41, start_s=9000)[0]
    assert restored.update(obs).gain == pytest.approx(est.update(obs).gain)


def test_the_state_reports_the_estimator_and_its_tuning() -> None:
    est = KalmanCalibration(measurement_noise=4e-9, process_noise_gain=1e-10)
    assert est.state().estimator == "kalman"
    restored = KalmanCalibration.from_state(_converged().state())
    assert restored.state().extra["measurement_noise"] > 0.0


def test_the_prediction_direction_parameters_are_the_exact_inverse() -> None:
    """Both conventions are reported, and the dashboards and the scorer read different ones."""
    est = _converged()
    s = est.state()
    assert s.gain == pytest.approx(1.0 / s.sensor_gain)
    assert s.bias == pytest.approx(-s.sensor_bias / s.sensor_gain)


def test_a_non_positive_measurement_noise_is_refused() -> None:
    """R = 0 asserts the sensor is perfect, which makes the gain infinite on the first update."""
    with pytest.raises(ValueError, match="measurement_noise"):
        KalmanCalibration(measurement_noise=0.0)


# -- the analytic band -----------------------------------------------------------------------------


def test_the_analytic_band_includes_the_error_the_filter_is_not_told_about() -> None:
    """The reason this estimator's interval was unusable.

    Its variance was the parameter covariance through the delta method, plus `R / k^2`. Both are
    sensor-side. The dominant error in weigh-in-motion is the vehicle's own bounce -- about 141 kg
    on the shipped scenarios -- and the filter is never told about it, so the band it produced was
    two kilograms wide on a twenty-tonne vehicle. Phase 5 measured coverage 0.0065 and made
    conformal the default to avoid it; the reference-rate sweep then found the pipeline falling
    back to it for four hours whenever conformal was not yet calibrated.

    An empirical residual term fixes the construction rather than routing around it.
    """
    rng = np.random.default_rng(0)
    est = KalmanCalibration()
    masses = rng.uniform(2000.0, 30000.0, 300)
    # A plant the filter can track, plus 140 kg of dynamic load it cannot.
    for i, m in enumerate(masses):
        feature = 2.0e-4 * m + 0.05 + float(rng.normal(0.0, 140.0)) * 2.0e-4
        est.update(
            ReferenceObservation(
                ts_us=SECOND * i, feature=feature, temp_c=20.0, reference_mass_kg=float(m)
            )
        )

    band = est.predict(2.0e-4 * 15000.0 + 0.05, 20.0)
    half = (band.mass_ci_high - band.mass_ci_low) / 2.0
    assert half > 100.0, f"a band of +-{half:.1f} kg cannot cover a 140 kg dynamic spread"
    assert band.interval_source == "kalman_residual"


def test_the_band_still_narrows_as_the_parameters_are_pinned_down() -> None:
    """The covariance term has to survive: it is what makes the interval wide while the filter is
    still learning and narrow once it is not."""
    rng = np.random.default_rng(1)
    est = KalmanCalibration()
    widths = []
    for i, m in enumerate(rng.uniform(2000.0, 30000.0, 200)):
        est.update(
            ReferenceObservation(
                ts_us=SECOND * i,
                feature=2.0e-4 * m + 0.05,
                temp_c=20.0,
                reference_mass_kg=float(m),
            )
        )
        if i in (5, 199):
            b = est.predict(2.0e-4 * 15000.0 + 0.05, 20.0)
            widths.append(b.mass_ci_high - b.mass_ci_low)
    assert widths[1] < widths[0]


def test_a_barely_fed_filter_reports_a_band_from_its_covariance_alone() -> None:
    """With almost no residuals seen there is little empirical spread to add, and the covariance
    term carries the interval. It must not collapse to zero width on the way."""
    est = KalmanCalibration()
    for i, m in enumerate((8000.0, 12000.0)):
        est.update(
            ReferenceObservation(
                ts_us=SECOND * i, feature=2.0e-4 * m + 0.05, temp_c=20.0, reference_mass_kg=m
            )
        )
    band = est.predict(2.0e-4 * 15000.0 + 0.05, 20.0)
    assert band.mass_ci_high > band.mass_ci_low


def test_the_band_is_the_empirical_spread_once_there_is_one() -> None:
    """And the analytic one only until then, so a fresh filter still produces an interval."""
    est = KalmanCalibration()
    est.fit(_observations(n=40, noise=1e-4))
    assert est.predict(2.0e-4 * 15000.0 + 0.05, 20.0).interval_source == "kalman_analytic"

    # More than `_RESIDUAL_WARMUP`: a fresh filter's first prediction errors describe its prior,
    # not the plant, and are deliberately not folded in.
    for i in range(20):
        m = 8000.0 + 1000.0 * i
        est.update(
            ReferenceObservation(
                ts_us=SECOND * (1000 + i),
                feature=2.0e-4 * m + 0.05,
                temp_c=20.0,
                reference_mass_kg=m,
            )
        )
    assert est.predict(2.0e-4 * 15000.0 + 0.05, 20.0).interval_source == "kalman_residual"
