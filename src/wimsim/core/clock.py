"""Clocks.

Two exist and they are not the same clock:

* **simulation time** -- seconds since run start, exact by construction.
* **station wall clock** -- what the device stamps on a sample. Equals simulation time mapped onto
  ``start_time`` *plus* whatever the clock-skew fault is doing. Downstream code only ever sees
  this one, which is the point: clock skew must be discoverable from the data, not from the config.

A :class:`Pacer` is also provided so ``SyntheticSource`` can run in real time when a demo needs to
look like a demo, and as fast as the CPU allows when an experiment needs throughput.
"""

from __future__ import annotations

import time
from dataclasses import dataclass

import numpy as np

from wimsim.core.types import US_PER_S

__all__ = ["ClockModel", "Pacer"]


@dataclass(frozen=True, slots=True)
class ClockModel:
    """Maps simulation time to station wall-clock microseconds.

    ``offset(t) = 0`` before ``t_start_s``; afterwards ``offset_s + drift_ppm*1e-6*(t - t_start_s)``.
    """

    start_time_us: int
    t_start_s: float = float("inf")
    offset_s: float = 0.0
    drift_ppm: float = 0.0

    def offset_at(self, t_s: np.ndarray | float) -> np.ndarray | float:
        t = np.asarray(t_s, dtype=np.float64)
        elapsed = np.maximum(t - self.t_start_s, 0.0)
        active = t >= self.t_start_s
        off = np.where(active, self.offset_s + self.drift_ppm * 1e-6 * elapsed, 0.0)
        return off if isinstance(t_s, np.ndarray) else float(off)

    def to_epoch_us(self, t_s: np.ndarray) -> np.ndarray:
        """Vectorised simulation-time -> station-clock microseconds.

        Rounding is half-away-from-zero via ``np.rint`` on a value that is already integral in the
        common (no-skew) case, so the mapping is exactly reproducible.
        """
        skewed = np.asarray(t_s, dtype=np.float64) + np.asarray(self.offset_at(t_s))
        return self.start_time_us + np.rint(skewed * US_PER_S).astype(np.int64)


class Pacer:
    """Throttles a generator loop to wall-clock speed.

    ``rate`` is a speed multiplier: 1.0 is real time, 60.0 is a minute per second, ``None`` (the
    default) is as fast as possible and never sleeps.
    """

    __slots__ = ("_sim0", "_t0", "rate")

    def __init__(self, rate: float | None = None) -> None:
        self.rate = rate
        self._t0: float | None = None
        self._sim0: float = 0.0

    def wait_until(self, sim_t_s: float) -> None:
        if self.rate is None:
            return
        now = time.perf_counter()
        if self._t0 is None:
            self._t0, self._sim0 = now, sim_t_s
            return
        target = self._t0 + (sim_t_s - self._sim0) / self.rate
        delay = target - now
        if delay > 0:
            time.sleep(delay)
