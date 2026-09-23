"""The three-parameter map, so that dropping it can be a result rather than an omission.

Section III-B specifies `m = theta0 + theta1*s + theta2*(s*dT)`. No estimator fitted such a term,
so the claim was withdrawn; `AffineTemp` exists to turn it into a tested hypothesis. These tests
are about the ways it could pass its own experiment without deserving to:

* fitting a third parameter on data that cannot identify it, and reporting the resulting number;
* being wired into the factory but not into the config, so the experiment measures nothing;
* quietly adapting, which would confound "a third parameter helps" with "a third adaptive
  mechanism helps" -- two different claims, one of which the paper is not making.
"""

from __future__ import annotations

import numpy as np
import pytest

from wimsim.calibration.affine_temp import AffineTemp
from wimsim.calibration.base import ReferenceObservation

#: The plant these observations come from: mass -> feature at gain K, with a thermal sensitivity
#: ALPHA, i.e. s = m * K * (1 + ALPHA*dT). Recovering ALPHA from the fitted parameters is the whole
#: claim of section III-B.
_K = 2.0e-4
_ALPHA = -2.0e-4
_T_REF = 20.0


def _observations(
    *, alpha: float = _ALPHA, temps=(5.0, 12.0, 20.0, 28.0, 35.0), n: int = 60
) -> list[ReferenceObservation]:
    """A reference set spanning loads and temperatures, which is what identifies three parameters."""
    rng = np.random.default_rng(7)
    out = []
    for i in range(n):
        mass = float(rng.uniform(600.0, 9000.0))
        temp = float(temps[i % len(temps)])
        feature = mass * _K * (1.0 + alpha * (temp - _T_REF))
        out.append(
            ReferenceObservation(
                ts_us=1_000_000 * i, feature=feature, temp_c=temp, reference_mass_kg=mass
            )
        )
    return out


def test_the_planted_thermal_sensitivity_is_recovered() -> None:
    """The claim section III-B makes, stated as an experiment: with the interaction present in the
    data and the preprocessor's own compensation switched off, `-theta2/theta1` is the plant's
    alpha."""
    est = AffineTemp(temp_coeff=0.0, t_ref_c=_T_REF)
    est.fit(_observations())

    assert est.residual_alpha == pytest.approx(_ALPHA, rel=1e-3)
    # The map goes feature -> mass, so theta1 is the reciprocal of the plant's gain, not the gain.
    assert est.state().gain == pytest.approx(1.0 / _K, rel=1e-3)


def test_the_residual_and_the_total_are_different_numbers_and_both_are_available() -> None:
    """The double-correction hazard. The preprocessor has already divided the feature by
    `1 + alpha_profile*dT`, so what the third parameter fits is the *residual* sensitivity. Reading
    it as the sensor's coefficient, without adding the profile's, is a small systematic error that
    would be very hard to find in a results table.
    """
    profile_alpha = -1.5e-4
    est = AffineTemp(temp_coeff=profile_alpha, t_ref_c=_T_REF)
    est.fit(_observations())

    assert est.total_alpha == pytest.approx(est.residual_alpha + profile_alpha)
    assert est.total_alpha != est.residual_alpha


def test_a_single_temperature_reference_set_is_refused_rather_than_fitted() -> None:
    """With dT constant the interaction column is a multiple of the feature column, so the fit has
    three parameters and two directions. Least squares still returns numbers, and they would be
    reported as a measured thermal sensitivity.
    """
    with pytest.raises(ValueError, match="same temperature"):
        AffineTemp().fit(_observations(temps=(20.0,)))


def test_a_reference_set_with_no_load_spread_is_refused() -> None:
    obs = _observations()
    flat = [
        ReferenceObservation(
            ts_us=o.ts_us, feature=1.0e-3, temp_c=o.temp_c, reference_mass_kg=5000.0
        )
        for o in obs
    ]
    with pytest.raises(ValueError, match="unidentifiable"):
        AffineTemp().fit(flat)


def test_a_non_positive_gain_is_refused_because_it_is_not_a_calibration() -> None:
    """A negative gain reports heavier vehicles as lighter. It is always a fit failure and never a
    sensor, and `StaticAffine` learned the same lesson at -8.03e+06."""
    obs = [
        ReferenceObservation(
            ts_us=1_000_000 * i,
            feature=float(f),
            temp_c=float(t),
            reference_mass_kg=float(m),
        )
        for i, (f, t, m) in enumerate(
            [(1.0e-3, 5.0, 9000.0), (2.0e-3, 20.0, 6000.0), (3.0e-3, 35.0, 3000.0)]
        )
    ]
    with pytest.raises(ValueError, match="not positive"):
        AffineTemp().fit(obs)


def test_too_few_observations_are_refused_rather_than_fitted_exactly() -> None:
    """Three points fit three parameters with zero residual, which would be reported as a perfect
    calibration with no uncertainty."""
    with pytest.raises(ValueError, match="at least 3"):
        AffineTemp().fit(_observations(n=2))


def test_an_update_is_counted_and_changes_nothing() -> None:
    """Batch-only has to mean "ignores updates", not "refuses them".

    The point of this estimator is a controlled comparison against `static_affine` inside the closed
    loop, and the loop hands every reference observation to `update`. Raising there made the
    comparison impossible to run: `theta2`'s first attempt failed every `affine_temp` cell with
    NotImplementedError and measured nothing at all. `StaticAffine` counts and returns, and this
    class's own docstring already said "like StaticAffine".

    What must NOT happen is adaptation. The parameters after an update are the parameters from the
    batch fit, or the experiment would be comparing a third parameter *and* a third adaptive
    mechanism and could attribute a difference to neither.
    """
    est = AffineTemp()
    est.fit(_observations())
    fitted = est.state()

    state = est.update(_observations()[0])

    assert state.gain == fitted.gain, "a batch estimator does not move"
    assert state.bias == fitted.bias
    assert state.extra["interaction"] == fitted.extra["interaction"]
    assert state.update_count == 1, "but it counts what it was offered"


def test_the_config_accepts_the_three_parameter_map_as_an_estimator() -> None:
    """Registering an estimator in the factory is half the wiring. `estimate.estimator` is a
    Literal, so a name the factory knows and the config does not fails at load time with a
    validation error and never reaches the estimator -- which is how `theta2` spent its first
    attempt producing ValidationErrors instead of an answer.
    """
    from wimsim.core.config import EstimateConfig

    assert EstimateConfig(estimator="affine_temp").estimator == "affine_temp"


def test_the_runner_builds_the_three_parameter_map_from_that_config() -> None:
    """The other half: the config value has to reach `build_estimator` and come back as the right
    class, rather than falling through a branch chain to the default."""
    from wimsim.core.config import EdgeConfig, EstimateConfig
    from wimsim.experiments.closed_loop import _estimator_for

    cfg = EdgeConfig(name="t", estimate=EstimateConfig(estimator="affine_temp"))
    assert type(_estimator_for(cfg)).__name__ == "AffineTemp"
