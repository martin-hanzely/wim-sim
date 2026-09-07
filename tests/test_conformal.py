"""Split conformal prediction: an interval that does not need the residuals to be Gaussian.

The buildspec calls empirical coverage "the single most persuasive number for a small-real-data
paper", and the analytic intervals shipped so far only earn it when their assumptions hold. Phase 2
already measured 0.906 against a nominal 0.95 on clean synthetic data, and the real recordings are
worse: mains hum makes the residual structured rather than Gaussian, and phase 4 measured coverage
falling to 0.750 with it enabled.

Conformal makes no distributional assumption at all. Under exchangeability its coverage is
guaranteed in *finite samples*, not asymptotically -- which is the property being bought, and which
the tests below check on deliberately non-Gaussian residuals where the analytic interval fails.

Two nonconformity scores ship. The absolute one gives a constant-width band; the relative one
normalises by the prediction, so the band widens with the load. The second exists because phase 4
found the Kalman analytic interval to be over 95 % sensor-noise floor once converged, and therefore
almost constant-width -- which is the wrong shape for a scale whose error is proportional to what it
is weighing.
"""

from __future__ import annotations

import numpy as np
import pytest

from wimsim.calibration import ConformalInterval, MassEstimate


def _fit(scores: np.ndarray, **kwargs) -> ConformalInterval:
    conformal = ConformalInterval(**kwargs)
    conformal.calibrate(
        [(1000.0, 1000.0 + float(s)) for s in scores]
        if kwargs.get("score") != "relative"
        else [(1000.0, 1000.0 * (1.0 + float(s))) for s in scores]
    )
    return conformal


def _coverage(conformal: ConformalInterval, predictions, truths) -> float:
    hits = 0
    for prediction, truth in zip(predictions, truths, strict=True):
        interval = conformal.interval(float(prediction))
        hits += interval.mass_ci_low <= truth <= interval.mass_ci_high
    return hits / len(truths)


# -- the finite-sample guarantee ---------------------------------------------------------------


def test_coverage_reaches_the_target_on_gaussian_residuals() -> None:
    rng = np.random.default_rng(0)
    conformal = ConformalInterval(coverage_target=0.95)
    conformal.calibrate([(1000.0, 1000.0 + float(e)) for e in rng.normal(0, 50, 500)])

    truths = 1000.0 + rng.normal(0, 50, 4000)
    assert _coverage(conformal, np.full(4000, 1000.0), truths) == pytest.approx(0.95, abs=0.02)


#: Three residual shapes no Gaussian interval can describe, with fixed seeds. The earlier version
#: seeded from ``hash(name)``, which Python randomises per process -- so the test passed or failed
#: depending on the interpreter's startup salt.
SHAPES = {
    "student_t_df3": lambda r, n: r.standard_t(3, n) * 30.0,
    "lognormal_skew": lambda r, n: np.exp(r.normal(0, 1, n)) * 20.0 - 33.0,
    "bimodal": lambda r, n: r.choice([-120.0, 120.0], n) + r.normal(0, 10, n),
    "laplace": lambda r, n: r.laplace(0, 40, n),
}


def test_the_quantile_is_exactly_the_conformal_order_statistic() -> None:
    """The guarantee is an identity about an index, so it can be checked as one rather than
    inferred from a coverage estimate. n = 199 puts the index at ceil(200 * 0.95) = 190."""
    rng = np.random.default_rng(0)
    residuals = rng.standard_normal(199)
    conformal = ConformalInterval(coverage_target=0.95)
    conformal.calibrate([(0.0, float(e)) for e in residuals])
    assert conformal.quantile == pytest.approx(float(np.sort(np.abs(residuals))[189]), abs=1e-12)


@pytest.mark.parametrize("name", sorted(SHAPES))
def test_coverage_holds_on_residuals_no_gaussian_interval_could_describe(name: str) -> None:
    """The whole reason conformal is here: the shape of the residual distribution does not enter.

    Averaged over sixty independent calibration draws, because the *conditional* coverage given one
    calibration set is a random variable -- Beta distributed, and strongly left-skewed for a heavy
    tail. A single draw on a lognormal can land at 0.90 and say nothing. What the theory guarantees
    is the mean, ``index/(n+1)``, and that is what is asserted.
    """
    draw = SHAPES[name]
    coverages = []
    for seed in range(60):
        rng = np.random.default_rng(4000 + seed)
        conformal = ConformalInterval(coverage_target=0.95)
        conformal.calibrate([(1000.0, 1000.0 + float(e)) for e in draw(rng, 199)])
        truths = 1000.0 + draw(rng, 2000)
        coverages.append(_coverage(conformal, np.full(2000, 1000.0), truths))

    assert float(np.mean(coverages)) == pytest.approx(190 / 200, abs=0.01)


def test_the_gaussian_interval_is_unreliable_across_shapes_and_conformal_is_not() -> None:
    """Measured, and narrower than the textbook claim -- because the textbook claim is not true.

    "A Gaussian interval under-covers on non-Gaussian residuals" is wrong as a general statement.
    Over sixty calibration draws per shape it lands within 0.001 of nominal on Student-t(3) and
    within 0.006 on a lognormal, essentially by luck: the standard deviation is inflated by the same
    tail that makes the extreme residuals, and the two errors happen to cancel. On a Laplace it
    under-covers at 0.936, and on a bimodal stream it covers *everything* -- a standard deviation
    inflated by the hole in the middle produces a band so wide it can no longer distinguish an
    overloaded truck from a legal one, which is not the safe failure that over-covering sounds like.

    So the honest claim is about reliability rather than direction: the Gaussian interval's accuracy
    depends on a distribution shape nobody measured, and its worst case across these four is an
    order of magnitude off. Conformal's worst case is the sampling error of the estimate.
    """
    conformal_misses, gaussian_misses = {}, {}
    for name, draw in SHAPES.items():
        conformal_runs, gaussian_runs = [], []
        for seed in range(60):
            rng = np.random.default_rng(4000 + seed)
            calibration = draw(rng, 199)
            conformal = ConformalInterval(coverage_target=0.95)
            conformal.calibrate([(1000.0, 1000.0 + float(e)) for e in calibration])

            truths = draw(rng, 2000)
            conformal_runs.append(float(np.mean(np.abs(truths) <= conformal.quantile)))
            gaussian_runs.append(
                float(np.mean(np.abs(truths) <= 1.959964 * float(np.std(calibration))))
            )
        conformal_misses[name] = abs(float(np.mean(conformal_runs)) - 0.95)
        gaussian_misses[name] = abs(float(np.mean(gaussian_runs)) - 0.95)

    assert max(conformal_misses.values()) < 0.01, conformal_misses
    assert max(gaussian_misses.values()) > 0.04, gaussian_misses
    assert max(gaussian_misses.values()) > 10 * max(conformal_misses.values())

    # The two it gets right, it gets right by coincidence rather than by construction.
    assert gaussian_misses["student_t_df3"] < conformal_misses["student_t_df3"]
    assert gaussian_misses["bimodal"] > 0.04
    assert gaussian_misses["laplace"] > 0.01


def test_the_quantile_carries_the_finite_sample_correction() -> None:
    """``ceil((n+1)(1-alpha))/n``, not the plain empirical quantile.

    With twenty calibration points and a 95 % target the correction picks the *largest* score,
    where the naive quantile would pick the nineteenth. The difference is exactly what turns an
    asymptotic statement into a guarantee, and it only shows up at small n -- which is the regime a
    station with a handful of reference vehicles is permanently in.
    """
    scores = np.arange(1.0, 21.0)  # 20 residuals, 1 .. 20
    conformal = ConformalInterval(coverage_target=0.95)
    conformal.calibrate([(0.0, float(s)) for s in scores])
    assert conformal.quantile == pytest.approx(20.0)

    naive = float(np.quantile(scores, 0.95))
    assert naive < conformal.quantile


def test_too_few_calibration_points_is_refused_rather_than_approximated() -> None:
    """At n < 1/alpha - 1 there is no score high enough to give the guarantee, so any interval
    returned would be a smaller claim wearing the same name."""
    conformal = ConformalInterval(coverage_target=0.95)
    with pytest.raises(ValueError, match="at least 19"):
        conformal.calibrate([(0.0, float(s)) for s in range(10)])


def test_a_stricter_target_needs_more_points_and_gives_a_wider_interval() -> None:
    rng = np.random.default_rng(3)
    residuals = rng.normal(0, 50, 800)

    widths = {}
    for target in (0.80, 0.95, 0.99):
        conformal = ConformalInterval(coverage_target=target)
        conformal.calibrate([(1000.0, 1000.0 + float(e)) for e in residuals])
        widths[target] = conformal.interval(1000.0).width
    assert widths[0.80] < widths[0.95] < widths[0.99]

    with pytest.raises(ValueError, match="at least 99"):
        ConformalInterval(coverage_target=0.99).calibrate([(0.0, float(s)) for s in range(50)])


# -- what the interval looks like ----------------------------------------------------------------


def test_the_absolute_score_gives_a_constant_width_band() -> None:
    rng = np.random.default_rng(4)
    conformal = ConformalInterval(score="absolute")
    conformal.calibrate([(1000.0, 1000.0 + float(e)) for e in rng.normal(0, 50, 400)])
    assert conformal.interval(1500.0).width == pytest.approx(conformal.interval(40000.0).width)


def test_the_relative_score_gives_a_band_proportional_to_the_load() -> None:
    """The shape phase 4 found missing.

    A scale's error is largely proportional to what it is weighing, so a 40-tonne truck deserves a
    wider band than a 1.5-tonne car. The Kalman analytic interval cannot say that -- once converged
    it is over 95 % sensor-noise floor and therefore nearly constant-width -- and neither can a
    residual standard deviation. Normalising the nonconformity score by the prediction does.
    """
    rng = np.random.default_rng(5)
    conformal = ConformalInterval(score="relative")
    conformal.calibrate(
        [
            (float(m), float(m) * (1.0 + float(e)))
            for m, e in zip(rng.uniform(1000, 40000, 600), rng.normal(0, 0.02, 600), strict=True)
        ]
    )
    car = conformal.interval(1500.0)
    truck = conformal.interval(40000.0)
    assert truck.width == pytest.approx(car.width * 40000.0 / 1500.0, rel=1e-9)


def test_the_relative_score_still_covers_when_the_error_scales_with_load() -> None:
    """Coverage is the point; the shape is only worth having if it does not cost coverage.

    Here the truth is that error is proportional to mass, so the constant-width band over-covers
    small vehicles and under-covers large ones while averaging out to nominal. The relative score
    is calibrated at every load, which is a stronger statement than the marginal one.
    """
    rng = np.random.default_rng(6)
    masses = rng.uniform(1000, 40000, 3000)
    predictions = masses * (1.0 + rng.normal(0, 0.02, 3000))

    conformal = ConformalInterval(score="relative")
    conformal.calibrate(list(zip(masses[:1000], predictions[:1000], strict=True)))

    heavy = masses[1000:] > 30000
    covered = np.array(
        [
            conformal.interval(float(p)).mass_ci_low
            <= t
            <= conformal.interval(float(p)).mass_ci_high
            for t, p in zip(masses[1000:], predictions[1000:], strict=True)
        ]
    )
    assert covered.mean() >= 0.93
    assert covered[heavy].mean() >= 0.90, "the heaviest vehicles were not covered"


def test_the_interval_brackets_the_prediction_and_names_its_provenance() -> None:
    rng = np.random.default_rng(7)
    conformal = ConformalInterval()
    conformal.calibrate([(1000.0, 1000.0 + float(e)) for e in rng.normal(0, 50, 300)])
    interval = conformal.interval(1234.0)
    assert isinstance(interval, MassEstimate)
    assert interval.mass_ci_low <= 1234.0 <= interval.mass_ci_high
    assert interval.interval_source == "conformal_absolute"
    assert ConformalInterval(score="relative").score == "relative"


def test_asking_for_an_interval_before_calibrating_is_refused() -> None:
    with pytest.raises(RuntimeError, match="not calibrated"):
        ConformalInterval().interval(1000.0)


# -- staying calibrated over time ------------------------------------------------------------------


def test_the_calibration_set_is_bounded_and_keeps_the_most_recent_scores() -> None:
    """A station runs for months. An unbounded calibration set is both a leak and a claim that a
    residual from March still describes September."""
    conformal = ConformalInterval(max_calibration=100)
    conformal.calibrate([(1000.0, 1000.0 + float(e)) for e in np.arange(500.0)])
    assert conformal.n_calibration == 100

    # Only the last hundred survive, so the scores are 400..499 and the conformal index is
    # ceil(101 * 0.95) = 96 -- the 96th smallest, which is 495. Not the largest: the correction
    # buys the guarantee at small n, it does not simply take the maximum.
    assert conformal.quantile == pytest.approx(495.0)


def test_new_residuals_can_be_folded_in_one_at_a_time() -> None:
    """Reference vehicles arrive one at a time in the field, not in batches."""
    conformal = ConformalInterval()
    for e in np.linspace(-50.0, 50.0, 200):
        conformal.observe(1000.0, 1000.0 + float(e))
    assert conformal.n_calibration == 200
    assert conformal.quantile == pytest.approx(50.0, rel=0.05)


def test_it_re_widens_after_the_residuals_get_worse() -> None:
    """Exchangeability is what the guarantee rests on, and drift breaks it -- so the honest design
    is a sliding window that forgets, and an interval that grows when the scale gets worse rather
    than a guarantee that quietly stops being true."""
    conformal = ConformalInterval(max_calibration=200)
    rng = np.random.default_rng(8)
    for e in rng.normal(0, 20, 400):
        conformal.observe(1000.0, 1000.0 + float(e))
    tight = conformal.interval(1000.0).width

    for e in rng.normal(0, 200, 400):
        conformal.observe(1000.0, 1000.0 + float(e))
    assert conformal.interval(1000.0).width > 5.0 * tight


def test_reset_clears_the_calibration_set() -> None:
    """After a recalibration the old residuals describe an estimator that no longer exists."""
    conformal = ConformalInterval()
    conformal.calibrate([(1000.0, 1000.0 + float(e)) for e in np.arange(100.0)])
    conformal.reset()
    assert conformal.n_calibration == 0
    with pytest.raises(RuntimeError, match="not calibrated"):
        conformal.interval(1000.0)


# -- serialisation ----------------------------------------------------------------------------------


def test_state_round_trips_so_a_restart_does_not_lose_the_calibration() -> None:
    conformal = ConformalInterval(coverage_target=0.9, score="relative", max_calibration=64)
    rng = np.random.default_rng(9)
    for m, e in zip(rng.uniform(1000, 40000, 300), rng.normal(0, 0.02, 300), strict=True):
        conformal.observe(float(m), float(m) * (1.0 + float(e)))

    restored = ConformalInterval.from_dict(conformal.to_dict())
    assert restored.quantile == pytest.approx(conformal.quantile)
    assert restored.interval(2000.0).width == pytest.approx(conformal.interval(2000.0).width)
    assert restored.score == "relative"
    assert restored.n_calibration == conformal.n_calibration


def test_the_state_is_plain_json() -> None:
    import json

    conformal = ConformalInterval()
    conformal.calibrate([(1000.0, 1000.0 + float(e)) for e in np.arange(50.0)])
    assert json.loads(json.dumps(conformal.to_dict()))["score"] == "absolute"


def test_an_unknown_score_is_refused() -> None:
    with pytest.raises(ValueError, match="score"):
        ConformalInterval(score="quadratic")
