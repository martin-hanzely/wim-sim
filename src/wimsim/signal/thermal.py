"""Temperature: ambient weather, the sensor body's thermal lag, and what the probe reports.

Three distinct temperatures exist and conflating them is the classic mistake:

``T_ambient``
    Air temperature. A daily sinusoid plus a slow trend plus correlated weather noise
    (Ornstein-Uhlenbeck, so it is smooth rather than white).
``T_sensor``
    The sensor body, which is what actually changes ``k``. Ambient passed through a first-order
    lag with time constant ``tau_thermal`` (tens of minutes for a steel-and-concrete installation).
    **This lag is the control-theoretic heart of the plant**: it puts a phase shift between the
    temperature a compensator can measure and the sensitivity error it is trying to cancel, which
    is exactly why instantaneous feed-forward compensation leaves a residual and a closed loop
    does not.
``T_probe``
    What the station reports: ``T_sensor`` behind a further small lag, plus offset, noise and
    quantisation. The only temperature any estimator is allowed to see.

Everything is generated block-wise with carried filter state, so output does not depend on the
block size.
"""

from __future__ import annotations

import numpy as np
from scipy import signal as sps

from wimsim.core.config import StationConfig, TemperatureConfig
from wimsim.core.rng import RngStreams
from wimsim.core.types import US_PER_S

__all__ = ["ThermalBlock", "ThermalModel"]

_SECONDS_PER_DAY = 86400.0


class ThermalBlock:
    """Per-block temperatures. Plain attribute holder; arrays are parallel to the sample grid."""

    __slots__ = ("ambient_c", "probe_c", "sensor_c")

    def __init__(self, ambient_c: np.ndarray, sensor_c: np.ndarray, probe_c: np.ndarray) -> None:
        self.ambient_c = ambient_c
        self.sensor_c = sensor_c
        self.probe_c = probe_c


def _alpha(dt: float, tau: float) -> float:
    """Pole of the discrete first-order lag. Exact (matched-exponential), not Euler."""
    return float(np.exp(-dt / tau)) if tau > 0 else 0.0


class ThermalModel:
    """Stateful, block-wise temperature generator.

    Parameters
    ----------
    cfg, station
        Scenario temperature settings and the station's thermal constants.
    dt
        Sample interval, s. Must be constant for the whole run.
    start_time_us
        Wall-clock time of ``t = 0``; fixes where in the daily cycle the run begins.
    rngs
        Named streams. Weather noise and probe noise draw from *separate* streams: if they shared
        one, the interleaving of draws would depend on the block size and output would stop being
        block-size invariant.
    """

    def __init__(
        self,
        cfg: TemperatureConfig,
        station: StationConfig,
        *,
        dt: float,
        start_time_us: int,
        rngs: RngStreams,
    ) -> None:
        self.cfg = cfg
        self.station = station
        self.dt = float(dt)
        self._rng_weather = rngs.get("temperature.weather")
        self._rng_probe = rngs.get("temperature.probe")
        # seconds-of-day at t=0, so the daily cycle lines up with the run's wall clock
        self._t0_of_day = (start_time_us / US_PER_S) % _SECONDS_PER_DAY

        # OU weather noise: x[n] = a*x[n-1] + s*eps[n], stationary sd == noise_sigma_c
        self._ou_a = _alpha(self.dt, cfg.noise_tau_s)
        self._ou_s = cfg.noise_sigma_c * np.sqrt(max(1.0 - self._ou_a**2, 0.0))
        self._ou_zi = np.zeros(1)

        # sensor body lag
        self._body_a = _alpha(self.dt, station.thermal.tau_thermal_s)
        init = station.thermal.t_sensor_init_c
        if init is None:
            init = self._ambient_deterministic(np.zeros(1))[0]
        # lfilter initial condition for y[n] = a*y[n-1] + (1-a)*x[n]
        self._body_zi = np.array([self._body_a * float(init)])

        probe = station.temperature_probe
        self._probe_a = _alpha(self.dt, probe.lag_s) if probe.lag_s > 0 else 0.0
        self._probe_zi = np.array([self._probe_a * float(init)])

    # -- ambient -------------------------------------------------------------------------

    def _ambient_deterministic(self, t_s: np.ndarray) -> np.ndarray:
        c = self.cfg
        phase = 2.0 * np.pi * ((self._t0_of_day + t_s) / _SECONDS_PER_DAY - c.peak_hour_utc / 24.0)
        daily = c.daily_amplitude_c * np.cos(phase)
        trend = c.trend_c_per_day * (t_s / _SECONDS_PER_DAY)
        return c.mean_c + daily + trend

    # -- stepping ------------------------------------------------------------------------

    def advance(self, t_s: np.ndarray) -> ThermalBlock:
        """Generate temperatures for the next contiguous block of sample times."""
        n = t_s.shape[0]
        ambient = self._ambient_deterministic(t_s)

        if self._ou_s > 0.0:
            eps = self._rng_weather.standard_normal(n)
            weather, self._ou_zi = sps.lfilter(
                [self._ou_s], [1.0, -self._ou_a], eps, zi=self._ou_zi
            )
            ambient = ambient + weather

        body, self._body_zi = sps.lfilter(
            [1.0 - self._body_a], [1.0, -self._body_a], ambient, zi=self._body_zi
        )

        probe_cfg = self.station.temperature_probe
        if not probe_cfg.enabled:
            probe = np.full(n, np.nan)
        else:
            if self._probe_a > 0.0:
                probe, self._probe_zi = sps.lfilter(
                    [1.0 - self._probe_a], [1.0, -self._probe_a], body, zi=self._probe_zi
                )
            else:
                probe = body.copy()
            probe = probe + probe_cfg.offset_c
            if probe_cfg.noise_sigma_c > 0:
                probe = probe + probe_cfg.noise_sigma_c * self._rng_probe.standard_normal(n)
            if probe_cfg.resolution_c > 0:
                probe = np.round(probe / probe_cfg.resolution_c) * probe_cfg.resolution_c

        return ThermalBlock(ambient_c=ambient, sensor_c=body, probe_c=probe)
