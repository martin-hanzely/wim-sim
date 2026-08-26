"""Analog-to-digital conversion.

Mid-tread uniform quantisation with hard clipping at both rails. Two things are deliberately
modelled rather than idealised away:

* **Saturation is reported, not silently clipped.** A saturated sample is flagged, because an
  overloaded channel is a fault condition the pipeline must be able to see and the estimator must
  be able to refuse.
* **Counts are the primary quantity.** ``raw_value`` is derived from ``raw_counts``, not the other
  way round, so the reported analog value lands exactly on the quantisation lattice -- the same way
  it does when the value comes off a real converter, and the same way it will when real recordings
  arrive as integer counts.
"""

from __future__ import annotations

import numpy as np

from wimsim.core.config import AdcConfig

__all__ = ["Quantizer"]


class Quantizer:
    __slots__ = ("cfg", "lsb", "max_count")

    def __init__(self, cfg: AdcConfig) -> None:
        self.cfg = cfg
        self.lsb = cfg.lsb
        self.max_count = cfg.levels - 1

    @property
    def min_count(self) -> int:
        return 0

    def to_counts(self, x: np.ndarray | float) -> np.ndarray:
        raw = np.rint((np.asarray(x, dtype=np.float64) - self.cfg.range_min) / self.lsb)
        return np.clip(raw, 0, self.max_count).astype(np.int64)

    def to_value(self, counts: np.ndarray | int) -> np.ndarray:
        return self.cfg.range_min + np.asarray(counts, dtype=np.float64) * self.lsb

    def quantize(self, x: np.ndarray) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
        """(counts, value, saturated). ``saturated`` marks samples that hit a rail."""
        ideal = (np.asarray(x, dtype=np.float64) - self.cfg.range_min) / self.lsb
        counts = np.clip(np.rint(ideal), 0, self.max_count).astype(np.int64)
        saturated = (ideal < -0.5) | (ideal > self.max_count + 0.5)
        return counts, self.to_value(counts), saturated
