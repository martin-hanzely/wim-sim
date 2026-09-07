"""Recursive least squares with exponential forgetting.

The second rung of the ladder, and it is deliberately a *small* step up from ``StaticAffine``: same
model, same objective, same prediction direction. The only difference is that the fit is never
finished. That isolation is the point -- when RLS beats the baseline on ``S4_step_fault``, the
result is attributable to adaptivity and to nothing else.

The recursion, per observation, with ``phi = [feature, 1]`` and ``y`` the reference mass:

```
e = y - phi @ theta                      a priori residual: the error before this pass was seen
g = P @ phi / (lam + phi @ P @ phi)      gain, in the direction the data is informative
theta <- theta + g * e
P <- (P - outer(g, phi @ P)) / lam
```

With ``lam = 1`` this is exactly recursive OLS: it converges on the batch least-squares answer, is
order-invariant, and ``P`` is the usual ``(X'X)^-1``. Below 1 the past is discounted geometrically
with a memory of roughly ``1/(1-lam)`` observations, which is what lets it follow a plant whose gain
has stepped.

**Forgetting brings covariance windup with it, and this is where WiM traffic makes it real.** A
fleet that is 95 % identical cars tells the recursion almost nothing new about the slope, but
``lam < 1`` keeps discounting what it already knew -- so ``P`` grows without bound and the estimator
eventually swings wildly on one unusual pass. That is not a hypothetical: it is what a rural site
looks like at 3am. The remedy here is the simplest defensible one, a bound on ``trace(P)``, applied
by scaling the whole matrix so the *shape* of the uncertainty (which direction is poorly known) is
preserved while the size is capped. Directional forgetting would be better and is a phase-6
question; a bound is honest, one line, and cannot itself go wrong.

**The dilution is inherited, not introduced.** Fitting mass on feature with a noisy feature biases
the slope towards zero (regression dilution). ``StaticAffine`` has the same bias, by construction,
because the two share an objective -- which is exactly why the comparison between them is fair.
``KalmanCalibration`` fits in the other direction and does not have it, and that is one of the
things the phase-6 experiment is for.
"""

from __future__ import annotations

from collections.abc import Iterable

import numpy as np

from wimsim.calibration.base import (
    EstimatorState,
    MassEstimate,
    ReferenceObservation,
)
from wimsim.calibration.static_affine import _normal_quantile

__all__ = ["RecursiveLeastSquares"]

#: Free parameters: slope and intercept.
_N_PARAMS = 2

#: Prior covariance when the recursion starts cold. Large enough that the first few observations
#: dominate it completely, which is what "no prior opinion" means in this formulation.
_DEFAULT_P0 = 1.0e6

#: Default ceiling on trace(P). Chosen well above anything a converged fit produces -- so it never
#: interferes with normal operation -- and well below the point at which the recursion goes numeric
#: nonsense. It exists to stop windup, not to regularise.
_DEFAULT_MAX_TRACE = 1.0e10


class RecursiveLeastSquares:
    """Least squares that never stops fitting."""

    estimator_name = "rls"

    def __init__(
        self,
        *,
        forgetting: float = 0.99,
        temp_coeff: float = 0.0,
        t_ref_c: float = 20.0,
        coverage_target: float = 0.95,
        initial_covariance: float = _DEFAULT_P0,
        max_covariance_trace: float = _DEFAULT_MAX_TRACE,
        residual_memory: float = 0.98,
    ) -> None:
        if not 0.0 < forgetting <= 1.0:
            raise ValueError(
                f"forgetting must lie in (0, 1]; got {forgetting}. 1.0 is recursive OLS, and the "
                "literature sweeps 0.90-0.999."
            )
        if not 0.0 < residual_memory < 1.0:
            raise ValueError(f"residual_memory must lie in (0, 1); got {residual_memory}")

        self.forgetting = float(forgetting)
        self.max_covariance_trace = float(max_covariance_trace)
        self._residual_memory = float(residual_memory)

        self._theta = np.zeros(_N_PARAMS, dtype=np.float64)  # [gain, bias]
        self._p = np.eye(_N_PARAMS, dtype=np.float64) * float(initial_covariance)

        self._temp_coeff = float(temp_coeff)
        self._t_ref_c = float(t_ref_c)
        self._coverage_target = float(coverage_target)
        self._z = _normal_quantile(self._coverage_target)

        #: Exponentially weighted mean square of the a priori residual. Weighted rather than
        #: cumulative because the interval should describe how wrong the estimator is *now*: after
        #: a step fault a cumulative statistic stays inflated long after the fit has recovered.
        self._residual_ms: float | None = None
        self._fitted = False
        self._n_fit = 0
        self._update_count = 0

    # -- fitting ---------------------------------------------------------------------------

    def fit(self, observations: Iterable[ReferenceObservation]) -> EstimatorState:
        """Seed the recursion from a batch, then carry on.

        Equivalent to feeding the batch through ``update`` one at a time with ``lam = 1``, but done
        in closed form so that a cold start is not sensitive to the order the calibration passes
        happened to arrive in.
        """
        obs = list(observations)
        if len(obs) < _N_PARAMS:
            raise ValueError(
                f"a two-parameter fit needs at least {_N_PARAMS} reference observations, got "
                f"{len(obs)}"
            )

        x = np.array([o.feature for o in obs], dtype=np.float64)
        y = np.array([o.reference_mass_kg for o in obs], dtype=np.float64)
        if float(np.std(x)) <= 0.0:
            raise ValueError(
                "degenerate reference set: all features are identical, so the slope is "
                "unidentifiable. Calibration passes must span a range of loads."
            )

        design = np.column_stack([x, np.ones_like(x)])
        gram = design.T @ design
        self._theta = np.linalg.solve(gram, design.T @ y)
        self._p = np.linalg.inv(gram)

        residuals = y - design @ self._theta
        dof = max(len(obs) - _N_PARAMS, 1)
        self._residual_ms = float(residuals @ residuals) / dof
        self._fitted = True
        self._n_fit = len(obs)
        return self.state()

    @classmethod
    def from_state(cls, state: EstimatorState) -> RecursiveLeastSquares:
        """Restore an estimator, covariance included.

        The covariance is part of the state and not a derived convenience: a station that restarts
        and comes back with a fresh prior has silently forgotten how confident it was, and would
        then over-react to the first vehicle it sees.
        """
        extra = state.extra or {}
        est = cls(
            forgetting=float(extra.get("forgetting", 0.99)),
            temp_coeff=state.temp_coeff,
            t_ref_c=state.t_ref_c,
            coverage_target=state.coverage_target,
            max_covariance_trace=float(extra.get("max_covariance_trace", _DEFAULT_MAX_TRACE)),
            residual_memory=float(extra.get("residual_memory", 0.98)),
        )
        est._theta = np.array([state.gain, state.bias], dtype=np.float64)
        if state.covariance is not None:
            est._p = np.array(state.covariance, dtype=np.float64)
        est._residual_ms = None if state.residual_sd is None else float(state.residual_sd) ** 2
        est._fitted = state.fitted
        est._n_fit = state.n_fit
        est._update_count = state.update_count
        return est

    # -- the interface ----------------------------------------------------------------------

    def predict(self, x_comp: float, temp_c: float) -> MassEstimate:
        """Mass from a compensated feature.

        ``temp_c`` is unused for the same reason as in ``StaticAffine``: the preprocessor already
        applied the thermal correction, and applying it again would double-correct.
        """
        if not self._fitted:
            raise RuntimeError(
                "RecursiveLeastSquares is not fitted; call fit(), feed it reference observations "
                "through update(), or restore a profile with from_state()"
            )
        del temp_c  # see docstring
        mass = float(self._theta[0] * float(x_comp) + self._theta[1])
        half = self._z * self._residual_sd()
        return MassEstimate(
            mass_kg=mass,
            mass_ci_low=mass - half,
            mass_ci_high=mass + half,
            coverage_target=self._coverage_target,
            interval_source="rls_residual_sd",
        )

    def update(self, observation: ReferenceObservation) -> EstimatorState:
        """Fold one reference observation into the fit."""
        phi = np.array([float(observation.feature), 1.0], dtype=np.float64)
        y = float(observation.reference_mass_kg)

        # A priori: the error this estimator would have made *before* seeing the answer. That is
        # the quantity the drift detectors consume, so it must never be computed after the update.
        error = y - float(phi @ self._theta)

        p_phi = self._p @ phi
        denominator = self.forgetting + float(phi @ p_phi)
        gain = p_phi / denominator

        self._theta = self._theta + gain * error
        self._p = (self._p - np.outer(gain, p_phi)) / self.forgetting
        self._p = 0.5 * (self._p + self._p.T)  # symmetry is lost to rounding; restore it
        self._bound_covariance()

        weight = self._residual_memory
        square = error * error
        self._residual_ms = (
            square
            if self._residual_ms is None
            else (weight * self._residual_ms + (1.0 - weight) * square)
        )

        self._update_count += 1
        self._fitted = True
        return self.state()

    def state(self) -> EstimatorState:
        return EstimatorState(
            estimator=self.estimator_name,
            gain=float(self._theta[0]),
            bias=float(self._theta[1]),
            temp_coeff=self._temp_coeff,
            t_ref_c=self._t_ref_c,
            residual_sd=self._residual_sd() if self._residual_ms is not None else None,
            coverage_target=self._coverage_target,
            update_count=self._update_count,
            fitted=self._fitted,
            n_fit=self._n_fit,
            covariance=tuple(tuple(float(v) for v in row) for row in self._p),
            extra={
                "forgetting": self.forgetting,
                "max_covariance_trace": self.max_covariance_trace,
                "residual_memory": self._residual_memory,
            },
        )

    # -- internals ---------------------------------------------------------------------------

    def _residual_sd(self) -> float:
        return 0.0 if self._residual_ms is None else float(np.sqrt(max(self._residual_ms, 0.0)))

    def _bound_covariance(self) -> None:
        """Cap ``trace(P)`` by scaling, so windup cannot run away.

        Scaling rather than clipping the diagonal, because the *shape* of P says which direction
        the fit is poorly informed about, and that is the useful part; only its size needs a
        ceiling. A run of identical vehicles inflates the slope direction and leaves the intercept
        direction alone, and after scaling it still does.
        """
        trace = float(np.trace(self._p))
        if not np.isfinite(trace):
            # The recursion has gone numerically bad. Reset to a weak prior rather than emitting
            # NaN masses: an estimator that says "I know nothing" is recoverable, one that says
            # NaN is not.
            self._p = np.eye(_N_PARAMS) * _DEFAULT_P0
            return
        if trace > self.max_covariance_trace:
            self._p *= self.max_covariance_trace / trace
