"""Watching two channels against each other, with no reference vehicle at all.

Every other detector in this package watches the *residual* -- the gap between a predicted mass and
a known one -- so every one of them needs reference vehicles, and the reference-rate sweep measured
what happens when those are scarce: past one reference in ten the discrete loop fires rarely and
catches little.

A two-channel installation has a signal that costs nothing. The gauges at ST-CINTRON-1 sit at a
fixed amplitude ratio -- measured 2.98 +/- 0.37 on the Citroen and 2.78 +/- 0.34 on the Fabia, which
is one ratio within the noise -- because they are two views of the same load. Nothing about that
needs to know what the vehicle weighed. If the ratio moves, something in the instrument moved.

**It detects, it does not diagnose.** A ratio that rises means Tenzo2 gained sensitivity or Tenzo1
lost it, and nothing here can say which: two channels give one equation. Naming the faulty channel
needs a third signal or a reference vehicle, and claiming otherwise from a ratio would be arithmetic
dressed as a conclusion.

**What it can resolve is set by the crossing-to-crossing scatter, which is large.** The measured
ratio spread is 12 % of its own value, so at the shipped three sigmas a single-channel change has to
reach roughly 36 % before three consecutive crossings fall outside the band. This finds gross faults
-- a gauge half dead, a bond failing, a channel unplugged -- and will not find a 10 % drift. Lowering
the threshold does not help: the scatter is the floor, and more confirmations buy latency rather than
resolution.

**It is blind to anything common to both channels.** A platform that loses stiffness, a temperature
that moves both gauges, an amplifier supply that feeds both -- all leave the ratio exactly where it
was. This is a complement to the residual detectors and not a substitute: it sees the faults they
are worst at, which are the single-channel ones, and misses the ones they see best.
"""

from __future__ import annotations

import math
from collections import deque
from typing import Any

import numpy as np

__all__ = ["ChannelRatioMonitor"]

#: MAD -> sigma for normally distributed data. The same constant the rest of the package uses.
_MAD_TO_SIGMA = 1.4826


class ChannelRatioMonitor:
    """Latching alarm on the amplitude ratio between two channels.

    The baseline is a median and a MAD over the last ``window`` healthy crossings, so a single
    unusual vehicle cannot move it and a slow common-mode drift is followed rather than flagged.
    """

    def __init__(
        self,
        *,
        threshold_sigma: float = 3.0,
        window: int = 40,
        warmup: int = 12,
        confirm: int = 3,
        min_peak: float = 0.0,
    ) -> None:
        if warmup < 3:
            raise ValueError("warmup must be at least 3: a MAD over two points is not a spread")
        self.threshold_sigma = float(threshold_sigma)
        self.window = int(window)
        self.warmup = int(warmup)
        #: Consecutive crossings outside the band before the alarm latches. A MAD over forty points
        #: carries about a tenth of its own value in uncertainty, so the effective threshold
        #: wanders and a single crossing will eventually fall outside a 4-sigma band by itself --
        #: measured: a healthy pair tripped inside 400 crossings without this. A genuine
        #: single-channel fault puts *every* subsequent crossing outside, so requiring a run of
        #: them costs two crossings of latency and removes the false alarms.
        self.confirm = max(int(confirm), 1)
        self.min_peak = float(min_peak)
        self._ratios: deque[float] = deque(maxlen=self.window)
        self._alarmed = False
        self._n_seen = 0
        self._last_z = 0.0
        self._consecutive = 0

    @property
    def ready(self) -> bool:
        return len(self._ratios) >= self.warmup

    @property
    def alarmed(self) -> bool:
        return self._alarmed

    @property
    def last_z(self) -> float:
        """How far the most recent ratio sat from the baseline, in robust sigmas."""
        return self._last_z

    def baseline(self) -> tuple[float, float]:
        """Median ratio and its robust sigma. ``(nan, nan)`` before warm-up."""
        if not self.ready:
            return float("nan"), float("nan")
        sample = np.asarray(self._ratios, dtype=np.float64)
        median = float(np.median(sample))
        sigma = float(np.median(np.abs(sample - median))) * _MAD_TO_SIGMA
        return median, sigma

    def observe(self, peak_a: float, peak_b: float) -> bool:
        """Fold one crossing in. Returns whether the monitor is alarmed.

        ``peak_a`` is the reference channel and ``peak_b`` the one compared against it; the ratio
        is ``|b| / |a|``. A crossing too small to have a reliable ratio is ignored rather than
        folded in, because dividing two near-zero peaks produces a number with no information and
        enormous variance.
        """
        a, b = abs(float(peak_a)), abs(float(peak_b))
        if a <= self.min_peak or b <= self.min_peak or a == 0.0:
            return self._alarmed
        if not math.isfinite(a) or not math.isfinite(b):
            return self._alarmed

        ratio = b / a
        self._n_seen += 1

        if not self.ready:
            self._ratios.append(ratio)
            return self._alarmed

        median, sigma = self.baseline()
        self._last_z = abs(ratio - median) / sigma if sigma > 0 else 0.0

        if sigma > 0 and self._last_z > self.threshold_sigma:
            # Outside the band. NOT folded into the baseline, whether or not it goes on to confirm:
            # a monitor that learns the fault it just found stops being able to see it, and a
            # marginal fault that drags the baseline a little at a time is exactly how a drift
            # detector ends up reporting that everything is fine. Measured without this: a 50 %
            # sensitivity loss walked the baseline from 2.96 to 1.42 and the alarm never latched.
            self._consecutive += 1
            if self._consecutive >= self.confirm:
                self._alarmed = True
            return self._alarmed

        self._consecutive = 0
        self._ratios.append(ratio)
        return self._alarmed

    def reset(self) -> None:
        """Clear the alarm and the baseline, after the fault has been dealt with."""
        self._ratios.clear()
        self._alarmed = False
        self._last_z = 0.0
        self._consecutive = 0

    def to_dict(self) -> dict[str, Any]:
        median, sigma = self.baseline()
        return {
            "ready": self.ready,
            "alarmed": self._alarmed,
            "n_seen": self._n_seen,
            "baseline_ratio": median,
            "baseline_sigma": sigma,
            "last_z": self._last_z,
            "consecutive_outside": self._consecutive,
        }
