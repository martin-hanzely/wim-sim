"""A Kalman filter on the plant's own parameters. The control-theoretic contribution.

The other two estimators regress mass on feature, because kilograms are what gets scored. This one
turns the problem around and holds the state the plant actually has:

```
state       s = [q, k]                       zero line and gain, sensor-side
process     s(t+dt) = s(t) + w,   w ~ N(0, Q*dt)     a random walk, on a clock
measurement x = [1, m] @ s + v,   v ~ N(0, R)        what the sensor reports for a known mass
prediction  m_hat = (x - q) / k
```

Three things follow from that choice, and each is worth the reader's attention because each is a
difference from the baselines rather than a refinement of them.

**The state is what the truth log records.** ``q_true`` and ``k_true`` *are* the state, so the
calibration dashboard's overlay is a comparison and not a conversion, and a modelled drift is a
random walk on the state rather than a moving target the fit has to chase.

**It is not attenuated.** Regression dilution comes from noise in the regressor. Here the regressor
is the reference mass -- comparatively accurate, since it came from a weighbridge -- and the noise
sits in the observation, which is where a Kalman filter expects it and where it belongs physically.
StaticAffine and RLS put the noisy feature on the x-axis and are biased towards zero slope by
construction; the effect is measured in ``tests/test_kalman.py``. The honest caveat is that this
does not make it unbiased in general, only unbiased with respect to *feature* noise: a reference
mass that is itself uncertain dilutes this filter in exactly the same way. ``sigma_kg`` on the
observation exists so that a poor reference can at least be down-weighted.

**Process noise accrues with elapsed time, not with pass count.** A plant drifts on a clock, so two
passes an hour apart must admit more drift between them than two a second apart. Without that, a
filter tuned on a motorway is mistuned on a quiet road and the same config file means different
things at different sites. Gaps are clamped, because station clocks jump and a single sample stamped
a year into the future would otherwise inflate the covariance until the next pass overwrote
everything the filter knew.

**The interval is the covariance propagated, not a residual spread.** ``m = (x - q)/k`` is nonlinear
in the state, so the variance goes through a first-order (delta method) propagation:

```
dm/dq = -1/k      dm/dk = -m/k      dm/dx = 1/k
var(m) = J P J' + R/k^2
```

That is what makes an unconverged filter *say* it is unconverged, in kilograms, before anyone has a
reference mass to check it against -- and it scales with the load, because gain uncertainty is
multiplicative and a 1 % error in ``k`` is 15 kg on a car and 400 kg on a truck. A residual spread
cannot express either. It is still only as good as the model behind it, which is why phase 5 also
ships conformal intervals and compares the two.

**The third state is deliberately absent for now.** The buildspec offers ``[q, k, alpha]``. The
obstacle is not the algebra, it is a loop: the preprocessor already applies thermal compensation
using the *active profile's* coefficient, so an estimator that fits its own coefficient changes the
features it is fitted on, and the offline runner's single pass over the stream stops being valid
(see ``experiments/offline.py``). Adding the state without the two-pass structure would produce a
number that looks like a temperature coefficient and is not one.
"""

from __future__ import annotations

import math
from collections.abc import Iterable

import numpy as np

from wimsim.calibration.base import (
    EstimatorState,
    MassEstimate,
    ReferenceObservation,
)
from wimsim.calibration.static_affine import _normal_quantile

__all__ = ["KalmanCalibration"]

_N_STATES = 2  # [q, k]

#: Prior, as standard deviations on ``[q, k]``. Genuinely weak: a station's zero line is of order
#: 0.05 sensor units and its gain of order 2e-4 per kg, so these put the truth within a small
#: fraction of one prior standard deviation and let the first observations decide.
#:
#: An earlier version used (1e-2, 1e-6), which reads as "wide" until you notice it places the true
#: gain two hundred prior standard deviations from the prior mean. With a precise sensor the
#: measurements overwhelm it in a few updates and nothing looks wrong; with a noisy one the prior
#: wins and the gain is shrunk most of the way to zero. The dilution test in tests/test_kalman.py
#: is what caught it, because that test is the one that deliberately uses a very noisy feature.
_DEFAULT_P0 = (1.0, 1.0e-2)

#: Assumed drift, as standard deviation per second. Defaults are deliberately small -- a plant that
#: is genuinely stationary should not have its calibration wander -- and are what the phase-6 sweep
#: varies.
_DEFAULT_Q_BIAS = 1.0e-7
_DEFAULT_Q_GAIN = 1.0e-11

#: Longest gap that may accrue process noise, in seconds. A day of genuine downtime and a clock
#: that jumped are indistinguishable from inside the filter, so the larger is treated as the
#: smaller: the filter becomes uncertain, not amnesiac.
_DEFAULT_MAX_GAP_S = 3600.0


class KalmanCalibration:
    """Two states, one measurement, and a covariance that means something."""

    estimator_name = "kalman"

    def __init__(
        self,
        *,
        measurement_noise: float = 1.0e-8,
        process_noise_bias: float = _DEFAULT_Q_BIAS,
        process_noise_gain: float = _DEFAULT_Q_GAIN,
        temp_coeff: float = 0.0,
        t_ref_c: float = 20.0,
        coverage_target: float = 0.95,
        initial_state: tuple[float, float] = (0.0, 0.0),
        initial_covariance: tuple[float, float] = _DEFAULT_P0,
        max_gap_s: float = _DEFAULT_MAX_GAP_S,
    ) -> None:
        if measurement_noise <= 0.0:
            raise ValueError(
                f"measurement_noise (R) must be positive; got {measurement_noise}. R = 0 asserts a "
                "perfect sensor, which makes the Kalman gain infinite on the first update."
            )
        if process_noise_bias < 0.0 or process_noise_gain < 0.0:
            raise ValueError("process noise must be non-negative")

        self.measurement_noise = float(measurement_noise)
        #: Variance per second, one per state. Squared here so the constructor takes standard
        #: deviations, which is the only form anyone can reason about.
        self._q_rate = np.array(
            [float(process_noise_bias) ** 2, float(process_noise_gain) ** 2], dtype=np.float64
        )
        self.max_gap_s = float(max_gap_s)

        self._s = np.array(initial_state, dtype=np.float64)  # [q, k]
        self._p = np.diag(np.array(initial_covariance, dtype=np.float64) ** 2)

        self._temp_coeff = float(temp_coeff)
        self._t_ref_c = float(t_ref_c)
        self._coverage_target = float(coverage_target)
        self._z = _normal_quantile(self._coverage_target)

        self._last_ts_us: int | None = None
        self._fitted = False
        self._n_fit = 0
        self._update_count = 0

    # -- fitting ---------------------------------------------------------------------------

    def fit(self, observations: Iterable[ReferenceObservation]) -> EstimatorState:
        """Seed the state by least squares of feature on mass, then carry on filtering.

        Optional -- the filter starts perfectly well from its prior -- but a station that *has* a
        calibration batch should not spend its first hundred passes rediscovering it. Note the
        regression direction: feature on mass, the same way round as the measurement model, so the
        seed is not diluted either.
        """
        obs = list(observations)
        if len(obs) < _N_STATES:
            raise ValueError(
                f"seeding a two-state filter needs at least {_N_STATES} observations, got "
                f"{len(obs)}"
            )

        m = np.array([o.reference_mass_kg for o in obs], dtype=np.float64)
        x = np.array([o.feature for o in obs], dtype=np.float64)
        if float(np.std(m)) <= 0.0:
            raise ValueError(
                "degenerate reference set: all reference masses are identical, so the gain is "
                "unidentifiable. Calibration passes must span a range of loads."
            )

        design = np.column_stack([np.ones_like(m), m])
        gram = design.T @ design
        self._s = np.linalg.solve(gram, design.T @ x)

        residuals = x - design @ self._s
        dof = max(len(obs) - _N_STATES, 1)
        variance = float(residuals @ residuals) / dof
        self._p = np.linalg.inv(gram) * max(variance, np.finfo(float).tiny)

        self._last_ts_us = int(obs[-1].ts_us)
        self._fitted = True
        self._n_fit = len(obs)
        return self.state()

    @classmethod
    def from_state(cls, state: EstimatorState) -> KalmanCalibration:
        """Restore the filter, covariance and clock included.

        All three are state. A station that restarts and comes back with a fresh prior has
        forgotten how confident it was and will over-react to the first vehicle it sees; one that
        comes back without its clock will accrue an arbitrary amount of process noise on the next
        pass.
        """
        extra = state.extra or {}
        est = cls(
            measurement_noise=float(extra.get("measurement_noise", 1.0e-8)),
            process_noise_bias=float(extra.get("process_noise_bias", _DEFAULT_Q_BIAS)),
            process_noise_gain=float(extra.get("process_noise_gain", _DEFAULT_Q_GAIN)),
            temp_coeff=state.temp_coeff,
            t_ref_c=state.t_ref_c,
            coverage_target=state.coverage_target,
            max_gap_s=float(extra.get("max_gap_s", _DEFAULT_MAX_GAP_S)),
        )
        est._s = np.array([state.sensor_bias, state.sensor_gain], dtype=np.float64)
        if state.covariance is not None:
            est._p = np.array(state.covariance, dtype=np.float64)
        last = extra.get("last_ts_us")
        est._last_ts_us = None if last is None else int(last)
        est._fitted = state.fitted
        est._n_fit = state.n_fit
        est._update_count = state.update_count
        return est

    # -- the interface ----------------------------------------------------------------------

    def predict(self, x_comp: float, temp_c: float) -> MassEstimate:
        """Invert the measurement model, and propagate the state covariance through the inversion.

        ``temp_c`` is unused for the same reason as in the other estimators: the preprocessor has
        already applied the thermal correction, and applying it twice would double-correct.
        """
        if not self._fitted:
            raise RuntimeError(
                "KalmanCalibration is not fitted; feed it reference observations through update(), "
                "seed it with fit(), or restore a profile with from_state()"
            )
        del temp_c  # see docstring

        q, k = float(self._s[0]), float(self._s[1])
        if k == 0.0 or not math.isfinite(k):
            raise RuntimeError(
                "the filter's gain estimate is zero or not finite, so the measurement model cannot "
                "be inverted. This means the filter has diverged; a profile that produced it "
                "should not be trusted to weigh anything."
            )

        x = float(x_comp)
        mass = (x - q) / k

        # Delta method: J = [dm/dq, dm/dk], plus the measurement noise itself through dm/dx.
        jacobian = np.array([-1.0 / k, -mass / k], dtype=np.float64)
        variance = float(jacobian @ self._p @ jacobian) + self.measurement_noise / (k * k)
        half = self._z * math.sqrt(max(variance, 0.0))

        return MassEstimate(
            mass_kg=mass,
            mass_ci_low=mass - half,
            mass_ci_high=mass + half,
            coverage_target=self._coverage_target,
            interval_source="kalman_analytic",
        )

    def update(self, observation: ReferenceObservation) -> EstimatorState:
        """One predict-correct cycle against a known mass."""
        self._advance_to(int(observation.ts_us))

        m = float(observation.reference_mass_kg)
        h = np.array([1.0, m], dtype=np.float64)  # d(measurement)/d(state)
        z = float(observation.feature)

        # A reference that carries its own uncertainty adds to the measurement noise: a placard
        # value and a weighbridge reading must not have equal say. sigma_kg is in kg, so it enters
        # through the gain -- an uncertain mass makes an uncertain prediction of the feature.
        r = self.measurement_noise
        if observation.sigma_kg:
            r += (float(observation.sigma_kg) * float(self._s[1])) ** 2

        innovation = z - float(h @ self._s)
        p_h = self._p @ h
        s = float(h @ p_h) + r
        gain = p_h / s

        self._s = self._s + gain * innovation
        # Joseph form: stays positive semi-definite under rounding, which the short form does not,
        # and this filter runs for a very long time between restarts.
        i_kh = np.eye(_N_STATES) - np.outer(gain, h)
        self._p = i_kh @ self._p @ i_kh.T + np.outer(gain, gain) * r
        self._p = 0.5 * (self._p + self._p.T)

        self._update_count += 1
        self._fitted = True
        return self.state()

    def state(self) -> EstimatorState:
        q, k = float(self._s[0]), float(self._s[1])
        # Reported in the prediction direction, like every other estimator, so the scorer and the
        # event schema do not have to know which estimator produced them. sensor_gain/sensor_bias
        # invert it back, exactly.
        gain = math.inf if k == 0.0 else 1.0 / k
        bias = math.nan if k == 0.0 else -q / k
        return EstimatorState(
            estimator=self.estimator_name,
            gain=gain,
            bias=bias,
            temp_coeff=self._temp_coeff,
            t_ref_c=self._t_ref_c,
            residual_sd=None,  # the interval comes from the covariance, not from a residual spread
            coverage_target=self._coverage_target,
            update_count=self._update_count,
            fitted=self._fitted,
            n_fit=self._n_fit,
            covariance=tuple(tuple(float(v) for v in row) for row in self._p),
            extra={
                "measurement_noise": self.measurement_noise,
                "process_noise_bias": float(np.sqrt(self._q_rate[0])),
                "process_noise_gain": float(np.sqrt(self._q_rate[1])),
                "max_gap_s": self.max_gap_s,
                "last_ts_us": self._last_ts_us,
            },
        )

    # -- internals ---------------------------------------------------------------------------

    def _advance_to(self, ts_us: int) -> None:
        """Add the process noise that accrued since the last observation.

        The state transition is the identity -- a random walk does not move its own mean -- so only
        the covariance grows. Backwards time contributes nothing rather than subtracting:
        out-of-order delivery is real, and a negative dt would make the covariance indefinite.
        """
        previous = self._last_ts_us
        self._last_ts_us = ts_us
        if previous is None:
            return
        dt_s = max((ts_us - previous) / 1e6, 0.0)
        dt_s = min(dt_s, self.max_gap_s)
        if dt_s > 0.0:
            self._p = self._p + np.diag(self._q_rate * dt_s)
