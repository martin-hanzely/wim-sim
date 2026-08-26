"""The plant: everything slow that stands between axle load and reported value.

This is the system the controller has to track. Its state at time ``t`` is

    q(t)      zero line, sensor units
    alpha(t)  relative temperature coefficient of sensitivity, 1/degC
    k(t)      sensitivity, sensor units per kg

with

    k(t) = k0 * (1 + alpha(t) * (T_sensor(t) - T_ref)) * g_fault(t)
    q(t) = q0 + W(t) + c*t + sum_i d_i*H(t - t_i) + beta*(T_sensor(t) - T_ref) + q_fault(t)

Each term of ``q`` is independently configurable and independently logged, so an experiment can ask
"which drift mechanism does the estimator actually fail on" instead of "does it drift".

``alpha`` itself is a random walk when ``alpha_walk_sigma_per_sqrt_s > 0``. That matters: with a
fixed ``alpha`` the plant is a static nonlinearity in a measured variable and feed-forward
compensation is in principle sufficient. Let ``alpha`` wander and no fixed compensation can be
correct, which is the situation a self-calibrating system is supposed to exist for.

Everything here runs on the **plant grid** (``scenario.plant_rate_hz``, default 50 Hz), not the
acquisition grid. None of these processes carries content near 2 kHz, and integrating them there
would multiply the cost of a long run for no change in the result.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from wimsim.core.config import RunConfig
from wimsim.core.rng import RngStreams
from wimsim.signal.faults import FaultSet
from wimsim.signal.noise import PinkNoise
from wimsim.signal.thermal import ThermalModel

__all__ = ["PlantBlock", "PlantModel"]


@dataclass(frozen=True, slots=True)
class PlantBlock:
    """Plant state over one contiguous stretch of the plant grid. All arrays are parallel.

    ``q`` and ``k`` here are **fault-free**. Faults are applied afterwards on the finer sample
    grid, by :meth:`PlantModel.effective`, so that a step fault stays a step instead of being
    smeared across one plant interval by interpolation.
    """

    t_s: np.ndarray
    q: np.ndarray
    k: np.ndarray
    alpha: np.ndarray
    t_sensor_c: np.ndarray
    t_ambient_c: np.ndarray
    t_probe_c: np.ndarray
    pink: np.ndarray
    fault_mask: np.ndarray


class PlantModel:
    """Stateful, block-wise generator of the slow plant state."""

    def __init__(self, cfg: RunConfig, rngs: RngStreams, faults: FaultSet) -> None:
        self.cfg = cfg
        self.faults = faults
        sc = cfg.scenario
        self.dt = 1.0 / sc.plant_rate_hz

        self.thermal = ThermalModel(
            sc.temperature,
            cfg.station,
            dt=self.dt,
            start_time_us=int(sc.start_time.timestamp() * 1_000_000),
            rngs=rngs,
        )
        self.pink = PinkNoise(
            sc.noise.pink_sigma,
            dt=self.dt,
            f_min_hz=sc.noise.pink_f_min_hz,
            f_max_hz=sc.noise.pink_f_max_hz,
            rngs=rngs,
        )

        d = sc.zero_drift
        self._rw_sigma = d.random_walk_sigma_per_sqrt_s * np.sqrt(self.dt)
        self._rng_rw = rngs.get("drift.random_walk")
        self._rw_level = 0.0

        s = cfg.station.sensor
        self._alpha_sigma = s.alpha_walk_sigma_per_sqrt_s * np.sqrt(self.dt)
        self._rng_alpha = rngs.get("gain.alpha_walk")
        self._alpha_level = 0.0

        self._step_times, self._step_cum = self._compile_steps(rngs)

    # -- setup ---------------------------------------------------------------------------

    def _compile_steps(self, rngs: RngStreams) -> tuple[np.ndarray, np.ndarray]:
        """All settling steps, resolved up front so the result cannot depend on block layout."""
        d = self.cfg.scenario.zero_drift
        times = [e.t_s for e in d.steps]
        deltas = [e.delta for e in d.steps]

        if d.step_rate_per_hour > 0.0:
            rng = rngs.get("drift.steps")
            duration = self.cfg.scenario.duration_s
            expected = d.step_rate_per_hour * duration / 3600.0
            count = int(rng.poisson(expected))
            if count:
                times.extend(np.sort(rng.uniform(0.0, duration, count)).tolist())
                deltas.extend((d.step_magnitude_sigma * rng.standard_normal(count)).tolist())

        if not times:
            return np.empty(0), np.empty(0)
        order = np.argsort(np.asarray(times, dtype=np.float64), kind="stable")
        t_sorted = np.asarray(times, dtype=np.float64)[order]
        return t_sorted, np.cumsum(np.asarray(deltas, dtype=np.float64)[order])

    def _step_level(self, t_s: np.ndarray) -> np.ndarray:
        if self._step_times.size == 0:
            return np.zeros_like(t_s)
        idx = np.searchsorted(self._step_times, t_s, side="right")
        padded = np.concatenate(([0.0], self._step_cum))
        return padded[idx]

    @property
    def step_events(self) -> list[tuple[float, float]]:
        """(time, cumulative level) for the truth log and for dashboard annotations."""
        return list(zip(self._step_times.tolist(), self._step_cum.tolist(), strict=True))

    # -- stepping ------------------------------------------------------------------------

    def advance(self, t_s: np.ndarray) -> PlantBlock:
        n = t_s.shape[0]
        temps = self.thermal.advance(t_s)
        pink = self.pink.advance(n)

        d = self.cfg.scenario.zero_drift
        s = self.cfg.station.sensor

        if self._rw_sigma > 0.0:
            walk = self._rw_level + np.cumsum(self._rw_sigma * self._rng_rw.standard_normal(n))
            self._rw_level = float(walk[-1])
        else:
            walk = np.zeros(n)

        if self._alpha_sigma > 0.0:
            awalk = self._alpha_level + np.cumsum(
                self._alpha_sigma * self._rng_alpha.standard_normal(n)
            )
            self._alpha_level = float(awalk[-1])
        else:
            awalk = np.zeros(n)

        dtemp = temps.sensor_c - s.t_ref_c
        alpha = s.alpha0_per_c + awalk

        q = (
            d.q0
            + walk
            + d.linear_slope_per_hour * (t_s / 3600.0)
            + self._step_level(t_s)
            + d.temp_coupling_per_c * dtemp
        )
        k = s.k0 * (1.0 + alpha * dtemp)

        return PlantBlock(
            t_s=t_s,
            q=q,
            k=k,
            alpha=alpha,
            t_sensor_c=temps.sensor_c,
            t_ambient_c=temps.ambient_c,
            t_probe_c=temps.probe_c,
            pink=pink,
            fault_mask=self.faults.active_mask(t_s),
        )

    def effective(
        self, t_s: np.ndarray, q_base: np.ndarray, k_base: np.ndarray
    ) -> tuple[np.ndarray, np.ndarray]:
        """Apply fault effects to fault-free plant state, on whatever grid ``t_s`` is.

        Called on the sample grid by the generator and on the truth grid by the truth writer, so
        both see the same discontinuities in the same places.
        """
        return (
            q_base + self.faults.zero_offset(t_s),
            k_base * self.faults.gain_multiplier(t_s),
        )
