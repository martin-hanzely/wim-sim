"""The three-parameter map, so that dropping it can be a result rather than an omission.

The manuscript's section III-B specifies ``m = theta0 + theta1*s + theta2*(s*dT)``, with the temperature interaction
identified *online* and thermal sensitivity recoverable as ``alpha = -theta2/theta1``. No estimator in this
package fitted such a term: the map is two-parameter and temperature is compensated upstream in the
preprocessor from a coefficient carried on the active profile and never estimated.

This is that estimator, added so the difference can be measured instead of asserted either way.
On `S2_thermal_cycle` — 72 hours of daily thermal cycling, the scenario the term exists for — the
two-parameter map already sits within 2 % of the dynamic load floor, which is the error no
calibration can remove. If the third parameter cannot beat that, the honest report is a negative
result, and section III-B becomes a tested hypothesis rather than a withdrawn claim.

**What dT is here.** The temperature the *probe* reports, minus the reference temperature on the
profile. Not the true sensor temperature, which the edge cannot see — a real probe sits near the
sensor rather than inside it, and carries its own lag, offset and noise. That is the whole reason
perfect thermal compensation is unavailable even in simulation.

**The double-correction hazard.** The preprocessor has *already* divided the feature by
``1 + alpha(T_probe - T_ref)`` before this estimator sees it. A third parameter fitted on top of that
compensated feature is therefore estimating the **residual** thermal sensitivity the profile's fixed
``alpha`` failed to remove, and ``alpha_total = alpha_profile + alpha_residual``. Reading ``-theta2/theta1`` as the sensor's
thermal coefficient without adding the profile's own is wrong, and the error is small, systematic
and very hard to find. :meth:`residual_alpha` returns the residual; :meth:`total_alpha` adds the
profile's.
"""

from __future__ import annotations

import math
from collections.abc import Iterable, Sequence

import numpy as np

from wimsim.calibration.base import EstimatorState, MassEstimate, ReferenceObservation

__all__ = ["AffineTemp"]

_N_PARAMS = 3


def _normal_quantile(coverage: float) -> float:
    """Two-sided normal quantile. Duplicated from `static_affine` rather than imported, to keep the
    estimator core free of cross-module coupling for one line of arithmetic."""
    return float(math.sqrt(2.0) * _erfinv(coverage))


def _erfinv(x: float) -> float:
    # Newton on erf, which is in the stdlib. Converges in a handful of steps over (0, 1).
    lo, hi = 0.0, 6.0
    for _ in range(200):
        mid = 0.5 * (lo + hi)
        if math.erf(mid) < x:
            lo = mid
        else:
            hi = mid
    return 0.5 * (lo + hi)


class AffineTemp:
    """``m = theta0 + theta1*s + theta2*(s*dT)``, fitted in one batch least squares.

    Same shape as :class:`~wimsim.calibration.static_affine.StaticAffine` in every other respect, so
    a comparison between them isolates the interaction term and nothing else.
    """

    estimator_name = "affine_temp"

    def __init__(
        self,
        *,
        temp_coeff: float = 0.0,
        t_ref_c: float = 20.0,
        coverage_target: float = 0.95,
    ) -> None:
        self._theta = np.zeros(_N_PARAMS, dtype=np.float64)  # [bias, gain, interaction]
        self._temp_coeff = float(temp_coeff)
        self._t_ref_c = float(t_ref_c)
        self._coverage_target = float(coverage_target)
        self._residual_sd: float | None = None
        self._fitted = False
        self._n_fit = 0
        self._update_count = 0
        self._z = _normal_quantile(self._coverage_target)

    # -- fitting -------------------------------------------------------------------------------

    def fit(self, observations: Iterable[ReferenceObservation]) -> EstimatorState:
        obs: Sequence[ReferenceObservation] = list(observations)
        if len(obs) < _N_PARAMS:
            raise ValueError(
                f"a three-parameter fit needs at least {_N_PARAMS} reference observations, got "
                f"{len(obs)}"
            )

        x = np.array([o.feature for o in obs], dtype=np.float64)
        m = np.array([o.reference_mass_kg for o in obs], dtype=np.float64)
        dt = np.array([o.temp_c - self._t_ref_c for o in obs], dtype=np.float64)

        if float(np.std(x)) <= 0.0:
            raise ValueError(
                "degenerate reference set: all features are identical, so the slope is "
                "unidentifiable. Calibration passes must span a range of loads."
            )
        if float(np.std(dt)) <= 0.0:
            # The whole point of the third parameter is the temperature range it is fitted over.
            # Without one the interaction column is collinear with the feature column and the fit
            # is a two-parameter fit wearing three coefficients -- which would look like it worked.
            raise ValueError(
                "degenerate reference set: all reference observations are at the same temperature, "
                f"so the interaction term is collinear with the feature. Observed spread "
                f"{float(np.ptp(dt)):.3g} degC."
            )

        design = np.column_stack([np.ones_like(x), x, x * dt])
        sigmas = np.array([o.sigma_kg if o.sigma_kg else np.nan for o in obs], dtype=np.float64)
        w = 1.0 / sigmas**2 if np.isfinite(sigmas).all() and (sigmas > 0).all() else np.ones_like(x)
        sw = np.sqrt(w)

        coeffs, *_ = np.linalg.lstsq(design * sw[:, None], m * sw, rcond=None)
        theta = np.asarray(coeffs, dtype=np.float64)

        if not np.isfinite(theta).all() or theta[1] <= 0.0:
            raise ValueError(
                f"fitted sensor gain {theta[1]:.4g} is not positive, so this is not a calibration: "
                "a negative gain reports heavier vehicles as lighter."
            )

        self._theta = theta
        residuals = m - design @ theta
        dof = max(len(obs) - _N_PARAMS, 1)
        self._residual_sd = float(np.sqrt(float(residuals @ residuals) / dof))
        self._fitted = True
        self._n_fit = len(obs)
        return self.state()

    # -- the interface -------------------------------------------------------------------------

    def predict(self, x_comp: float, temp_c: float) -> MassEstimate:
        """Mass from a compensated feature and the probe's temperature.

        Unlike the two-parameter estimators, ``temp_c`` is *used*: it is the whole point.
        """
        if not self._fitted:
            raise RuntimeError(
                "AffineTemp is not fitted; call fit() with reference observations, or restore a "
                "profile with from_state()"
            )
        x = float(x_comp)
        dt = float(temp_c) - self._t_ref_c
        mass = float(self._theta[0] + self._theta[1] * x + self._theta[2] * x * dt)
        half = self._z * (self._residual_sd or 0.0)
        return MassEstimate(
            mass_kg=mass,
            mass_ci_low=mass - half,
            mass_ci_high=mass + half,
            coverage_target=self._coverage_target,
            interval_source="affine_temp_residual_sd",
        )

    def update(self, observation: ReferenceObservation) -> EstimatorState:
        """Not supported. This estimator exists to test whether the third *parameter* helps, not to
        add a third adaptive mechanism; making it recursive would confound the two questions."""
        del observation
        raise NotImplementedError(
            "AffineTemp is a batch estimator, like StaticAffine. Use rls or kalman for recursive "
            "tracking; this exists to isolate the effect of the interaction term."
        )

    # -- thermal sensitivity --------------------------------------------------------------------

    @property
    def residual_alpha(self) -> float:
        """``-theta2/theta1``: the thermal sensitivity the *profile's* fixed coefficient failed to remove.

        Not the sensor's thermal coefficient. The feature reaching this estimator has already been
        divided by ``1 + alpha_profile*dT``, so what is left to fit is the residual.
        """
        if not self._fitted or self._theta[1] == 0.0:
            return float("nan")
        return float(-self._theta[2] / self._theta[1])

    @property
    def total_alpha(self) -> float:
        """The sensor's thermal coefficient: the profile's fixed part plus the fitted residual."""
        return self._temp_coeff + self.residual_alpha

    # -- state ------------------------------------------------------------------------------------

    def state(self) -> EstimatorState:
        return EstimatorState(
            estimator=self.estimator_name,
            gain=float(self._theta[1]),
            bias=float(self._theta[0]),
            temp_coeff=self._temp_coeff,
            t_ref_c=self._t_ref_c,
            coverage_target=self._coverage_target,
            residual_sd=self._residual_sd,
            fitted=self._fitted,
            n_fit=self._n_fit,
            update_count=self._update_count,
            extra={
                "interaction": float(self._theta[2]),
                "residual_alpha": self.residual_alpha,
                "total_alpha": self.total_alpha,
            },
        )

    @classmethod
    def from_state(cls, state: EstimatorState) -> AffineTemp:
        est = cls(
            temp_coeff=state.temp_coeff,
            t_ref_c=state.t_ref_c,
            coverage_target=state.coverage_target,
        )
        est._theta = np.array(
            [state.bias, state.gain, float((state.extra or {}).get("interaction", 0.0))],
            dtype=np.float64,
        )
        est._residual_sd = state.residual_sd
        est._fitted = state.fitted
        est._n_fit = state.n_fit
        est._update_count = state.update_count
        return est
