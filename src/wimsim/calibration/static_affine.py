"""``StaticAffine`` -- the baseline everything else must beat.

``mass = gain * feature + bias``, fitted once by ordinary least squares from a set of reference
passes and then **frozen**. ``update`` counts the observation and changes nothing else. That is not
an omission: the whole claim of the project is that closing the loop beats calibrating once, and
that claim is only measurable against an estimator that genuinely never adapts.

Deliberate design notes:

* **Fitted in the prediction direction.** ``mass`` is regressed on ``feature``, minimising error in
  kilograms, because kilograms are what the experiment scores. The sensor-side parameters reported
  for the dashboard are the exact algebraic inverse of the fitted ones -- which is *not* the same as
  what regressing the other way would give, whenever the feature carries noise. Stated here because
  a reader comparing ``sensor_gain`` against ``k_true`` deserves to know it is a derived quantity.
* **No temperature term in the fit.** Compensation happens upstream in the preprocessor, using the
  active profile's coefficient, so by the time a feature reaches this estimator its thermal
  dependence has already been removed. The coefficient is carried in the state so an emitted event
  can say what was assumed, and applying it a second time here would double-correct.
* **The interval is analytic and provisional.** It is the residual standard deviation of the fit,
  scaled by a normal quantile: honest under Gaussian residuals, and no more than that. Split
  conformal prediction, which needs no such assumption, arrives in phase 5, and the two are then
  compared. ``interval_source`` records which one produced any given number.
"""

from __future__ import annotations

import math
from collections.abc import Iterable, Sequence

import numpy as np

from wimsim.calibration.base import (
    EstimatorState,
    MassEstimate,
    ReferenceObservation,
)

__all__ = ["StaticAffine"]

#: Free parameters in the fit: slope and intercept.
_N_PARAMS = 2


def _normal_quantile(p: float) -> float:
    """Two-sided normal quantile for a coverage target.

    ``p = 0.95`` -> 1.959964. ``z`` such that ``P(-z < Z < z) = p``, i.e. ``sqrt(2)*erfinv(p)``.
    Written out rather than taken from ``scipy.stats.norm.ppf`` because scipy is not available to
    this package (principle 6) and pulling it in for one scalar would not be a good trade.
    """
    if not 0.0 < p < 1.0:
        raise ValueError(f"coverage_target must lie in (0, 1), got {p}")
    return math.sqrt(2.0) * _erfinv(p)


def _erfinv(y: float) -> float:
    """Inverse error function: Winitzki's approximation refined by Newton against ``math.erf``.

    numpy has no ``erfinv`` and scipy is off-limits here. Accuracy after three Newton steps is
    better than 1e-13 across the range coverage targets use -- orders of magnitude tighter than the
    Gaussian-residual assumption the interval itself rests on.
    """
    if not -1.0 < y < 1.0:
        raise ValueError(f"erfinv domain is (-1, 1), got {y}")
    if y == 0.0:
        return 0.0
    # Winitzki's approximation as a starting point
    a = 0.147
    ln1my2 = math.log(1.0 - y * y)
    term = 2.0 / (math.pi * a) + ln1my2 / 2.0
    x = math.copysign(math.sqrt(math.sqrt(term * term - ln1my2 / a) - term), y)
    # two Newton steps against erf, which the stdlib does provide
    for _ in range(3):
        err = math.erf(x) - y
        deriv = 2.0 / math.sqrt(math.pi) * math.exp(-x * x)
        x -= err / deriv
    return x


class StaticAffine:
    """Fit once, predict forever."""

    estimator_name = "static_affine"

    def __init__(
        self,
        *,
        temp_coeff: float = 0.0,
        t_ref_c: float = 20.0,
        coverage_target: float = 0.95,
    ) -> None:
        self._gain = 0.0
        self._bias = 0.0
        self._temp_coeff = float(temp_coeff)
        self._t_ref_c = float(t_ref_c)
        self._coverage_target = float(coverage_target)
        self._residual_sd: float | None = None
        self._fitted = False
        self._n_fit = 0
        self._update_count = 0
        self._z = _normal_quantile(self._coverage_target)

    # -- fitting ---------------------------------------------------------------------------

    def fit(self, observations: Iterable[ReferenceObservation]) -> EstimatorState:
        """Ordinary least squares of reference mass on feature.

        Weighted by ``1/sigma_kg**2`` where a reference uncertainty is supplied, because a
        weighbridge reading and a nominal placard value do not deserve equal say.
        """
        obs: Sequence[ReferenceObservation] = list(observations)
        if len(obs) < _N_PARAMS:
            raise ValueError(
                f"a two-parameter fit needs at least {_N_PARAMS} reference observations, got "
                f"{len(obs)}"
            )

        x = np.array([o.feature for o in obs], dtype=np.float64)
        m = np.array([o.reference_mass_kg for o in obs], dtype=np.float64)

        spread = float(x.max() - x.min())
        if not np.isfinite(spread) or spread <= 0.0 or float(np.std(x)) <= 0.0:
            raise ValueError(
                "degenerate reference set: all features are identical, so the slope is "
                "unidentifiable. Calibration passes must span a range of loads."
            )

        sigmas = np.array([o.sigma_kg if o.sigma_kg else np.nan for o in obs], dtype=np.float64)
        if np.isfinite(sigmas).all() and (sigmas > 0).all():
            w = 1.0 / sigmas**2
        else:
            w = np.ones_like(x)

        design = np.column_stack([x, np.ones_like(x)])
        sw = np.sqrt(w)
        coeffs, *_ = np.linalg.lstsq(design * sw[:, None], m * sw, rcond=None)
        self._gain, self._bias = float(coeffs[0]), float(coeffs[1])

        residuals = m - (self._gain * x + self._bias)
        dof = max(len(obs) - _N_PARAMS, 1)
        self._residual_sd = float(np.sqrt(float(residuals @ residuals) / dof))
        self._fitted = True
        self._n_fit = len(obs)
        return self.state()

    @classmethod
    def from_state(cls, state: EstimatorState) -> StaticAffine:
        est = cls(
            temp_coeff=state.temp_coeff,
            t_ref_c=state.t_ref_c,
            coverage_target=state.coverage_target,
        )
        est._gain = state.gain
        est._bias = state.bias
        est._residual_sd = state.residual_sd
        est._fitted = state.fitted
        est._n_fit = state.n_fit
        est._update_count = state.update_count
        return est

    # -- the interface ----------------------------------------------------------------------

    def predict(self, x_comp: float, temp_c: float) -> MassEstimate:
        """Mass from a compensated feature.

        ``temp_c`` is accepted because the interface requires it and later estimators use it, but is
        deliberately unused: the thermal correction was applied by the preprocessor. Applying it
        again here would double-correct, and the resulting error would be small, systematic, and
        very hard to find.
        """
        if not self._fitted:
            raise RuntimeError(
                "StaticAffine is not fitted; call fit() with reference observations, or restore a "
                "profile with from_state()"
            )
        del temp_c  # see docstring
        mass = self._gain * float(x_comp) + self._bias
        half = self._z * (self._residual_sd or 0.0)
        return MassEstimate(
            mass_kg=mass,
            mass_ci_low=mass - half,
            mass_ci_high=mass + half,
            coverage_target=self._coverage_target,
            interval_source="residual_sd",
        )

    def update(self, observation: ReferenceObservation) -> EstimatorState:
        """Count the observation and change nothing else.

        The baseline does not adapt. Observations are still counted so that a dashboard can show
        how many reference passes an adaptive estimator had available over the same window.
        """
        del observation
        self._update_count += 1
        return self.state()

    def state(self) -> EstimatorState:
        return EstimatorState(
            estimator=self.estimator_name,
            gain=self._gain,
            bias=self._bias,
            temp_coeff=self._temp_coeff,
            t_ref_c=self._t_ref_c,
            residual_sd=self._residual_sd,
            coverage_target=self._coverage_target,
            update_count=self._update_count,
            fitted=self._fitted,
            n_fit=self._n_fit,
        )
