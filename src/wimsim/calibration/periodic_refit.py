"""``PeriodicRefit`` -- the recalibration schedule a practitioner would actually run.

The adaptive estimators update on every reference; the frozen baseline never does. Neither is what
a station operator does in practice, which is to repeat the commissioning calibration on a fixed
schedule and leave the scale alone in between. This is that, and nothing more:

* between refits it is :class:`StaticAffine` exactly -- same fit, same direction, same interval;
* every ``refit_every`` reference observations it refits on the most recent ``refit_window`` of
  them (the commissioning batch included, while it is still inside the window) and freezes again.

Its memory is therefore a hard window rather than RLS's geometric discount, and it adapts in steps.
It exists for revision item 1.3, as the baseline that "adapt versus freeze" has to beat before the
comparison can be called a choice of adaptation rather than a choice of memory length.

A refit that ``StaticAffine`` refuses -- a degenerate window, a non-positive gain -- is skipped and
the previous calibration kept, which is what an operator rejecting a bad calibration run does.
"""

from __future__ import annotations

from collections import deque
from collections.abc import Iterable

from wimsim.calibration.base import EstimatorState, MassEstimate, ReferenceObservation
from wimsim.calibration.static_affine import StaticAffine

__all__ = ["PeriodicRefit"]

_DEFAULT_EVERY = 60
_DEFAULT_WINDOW = 60


def _to_row(obs: ReferenceObservation) -> list:
    return [obs.ts_us, obs.feature, obs.temp_c, obs.reference_mass_kg, obs.sigma_kg]


def _from_row(row) -> ReferenceObservation:
    ts_us, feature, temp_c, mass, sigma = row
    return ReferenceObservation(
        ts_us=int(ts_us),
        feature=float(feature),
        temp_c=float(temp_c),
        reference_mass_kg=float(mass),
        sigma_kg=None if sigma is None else float(sigma),
    )


class PeriodicRefit:
    """Fit, freeze, and fit again on a schedule."""

    estimator_name = "periodic_refit"

    def __init__(
        self,
        *,
        refit_every: int = _DEFAULT_EVERY,
        refit_window: int = _DEFAULT_WINDOW,
        temp_coeff: float = 0.0,
        t_ref_c: float = 20.0,
        coverage_target: float = 0.95,
    ) -> None:
        if refit_every < 1:
            raise ValueError(f"refit_every must be at least 1 reference; got {refit_every}")
        if refit_window < 2:
            raise ValueError(
                f"refit_window must hold at least 2 references for a two-parameter fit; "
                f"got {refit_window}"
            )
        self.refit_every = int(refit_every)
        self.refit_window = int(refit_window)
        self._static = StaticAffine(
            temp_coeff=temp_coeff, t_ref_c=t_ref_c, coverage_target=coverage_target
        )
        self._window: deque[ReferenceObservation] = deque(maxlen=self.refit_window)
        self._since_refit = 0
        self._update_count = 0
        self._n_refits = 0

    # -- fitting ---------------------------------------------------------------------------

    def fit(self, observations: Iterable[ReferenceObservation]) -> EstimatorState:
        obs = list(observations)
        self._static.fit(obs)
        self._window.clear()
        self._window.extend(obs)
        self._since_refit = 0
        return self.state()

    @classmethod
    def from_state(cls, state: EstimatorState) -> PeriodicRefit:
        extra = state.extra or {}
        est = cls(
            refit_every=int(extra.get("refit_every", _DEFAULT_EVERY)),
            refit_window=int(extra.get("refit_window", _DEFAULT_WINDOW)),
            temp_coeff=state.temp_coeff,
            t_ref_c=state.t_ref_c,
            coverage_target=state.coverage_target,
        )
        est._static = StaticAffine.from_state(
            EstimatorState(
                estimator=StaticAffine.estimator_name,
                gain=state.gain,
                bias=state.bias,
                temp_coeff=state.temp_coeff,
                t_ref_c=state.t_ref_c,
                residual_sd=state.residual_sd,
                coverage_target=state.coverage_target,
                fitted=state.fitted,
                n_fit=state.n_fit,
            )
        )
        est._window.extend(_from_row(r) for r in extra.get("window", []))
        est._since_refit = int(extra.get("since_refit", 0))
        est._n_refits = int(extra.get("n_refits", 0))
        est._update_count = state.update_count
        return est

    # -- the interface ----------------------------------------------------------------------

    def predict(self, x_comp: float, temp_c: float) -> MassEstimate:
        if not self._static.state().fitted:
            raise RuntimeError(
                "PeriodicRefit is not fitted; call fit() with reference observations, or restore "
                "a profile with from_state()"
            )
        return self._static.predict(x_comp, temp_c)

    def update(self, observation: ReferenceObservation) -> EstimatorState:
        self._window.append(observation)
        self._update_count += 1
        self._since_refit += 1
        if self._since_refit >= self.refit_every:
            self._since_refit = 0
            try:
                self._static.fit(list(self._window))
                self._n_refits += 1
            except ValueError:
                pass  # a calibration the baseline refuses is rejected; keep the previous one
        return self.state()

    def state(self) -> EstimatorState:
        s = self._static.state()
        return EstimatorState(
            estimator=self.estimator_name,
            gain=s.gain,
            bias=s.bias,
            temp_coeff=s.temp_coeff,
            t_ref_c=s.t_ref_c,
            residual_sd=s.residual_sd,
            coverage_target=s.coverage_target,
            update_count=self._update_count,
            fitted=s.fitted,
            n_fit=s.n_fit,
            extra={
                "refit_every": self.refit_every,
                "refit_window": self.refit_window,
                "since_refit": self._since_refit,
                "n_refits": self._n_refits,
                "window": [_to_row(o) for o in self._window],
            },
        )
