"""Stage 1 of the edge pipeline: pulling samples and noticing what is missing.

Thin, and deliberately so -- it adds no signal processing. What it adds is *observation*: how many
samples actually arrived, at what rate, and where the stream has holes.

Gaps are the point. A dropped acquisition block does not announce itself; it looks like a slightly
shorter recording. But every window that spans a gap has a truncated integral and a displaced peak,
so an event computed across one is wrong in a way nothing downstream can detect. Counting gaps here
is what lets the ingest layer and the dashboards mark those events instead of trusting them.

The ring buffer the buildspec asks for is not needed offline -- the source is already a
materialised stream -- so it arrives with the streaming publisher in phase 3, where back-pressure
makes it meaningful.
"""

from __future__ import annotations

from collections.abc import Iterator
from typing import TYPE_CHECKING

import numpy as np

from wimsim.core.types import SampleBlock

if TYPE_CHECKING:  # pragma: no cover
    # Type-only: importing wimsim.source at runtime would execute its package __init__, which pulls
    # in the generator -- and edge/ is quarantined from wimsim.signal (principle 1).
    from wimsim.source.base import SourceAdapter

__all__ = ["AcquisitionAgent"]


class AcquisitionAgent:
    """Pulls blocks from a source and measures the stream while it does."""

    def __init__(self, source: SourceAdapter, *, sample_rate_hz: float | None = None) -> None:
        self.source = source
        self.sample_rate_hz = (
            float(sample_rate_hz)
            if sample_rate_hz is not None
            else float(source.metadata.sample_rate_hz)
        )
        #: a gap is a jump of more than this many nominal intervals between consecutive samples
        self.gap_tolerance = 1.5

        self.samples_acquired = 0
        self.blocks_acquired = 0
        self.gaps = 0
        self.missing_samples = 0
        self.first_ts_us: int | None = None
        self.last_ts_us: int | None = None

    @property
    def observed_rate_hz(self) -> float:
        """Rate implied by the timestamps actually seen. Diverges from nominal when samples go
        missing, which is precisely when someone needs to know."""
        if self.first_ts_us is None or self.last_ts_us is None or self.samples_acquired < 2:
            return float("nan")
        span_s = (self.last_ts_us - self.first_ts_us) / 1e6
        if span_s <= 0:
            return float("nan")
        return (self.samples_acquired - 1) / span_s

    def stream(self) -> Iterator[SampleBlock]:
        nominal_us = 1e6 / self.sample_rate_hz
        prev_last: int | None = None

        for block in self.source.stream_blocks():
            if block.n == 0:
                continue
            ts = block.ts_us
            if self.first_ts_us is None:
                self.first_ts_us = int(ts[0])

            deltas = np.diff(ts)
            if prev_last is not None:
                deltas = np.concatenate([[int(ts[0]) - prev_last], deltas])
            offending = deltas > self.gap_tolerance * nominal_us
            if offending.any():
                self.gaps += int(offending.sum())
                self.missing_samples += int(np.round(deltas[offending] / nominal_us - 1.0).sum())

            prev_last = int(ts[-1])
            self.last_ts_us = prev_last
            self.samples_acquired += block.n
            self.blocks_acquired += 1
            yield block

    def stats(self) -> dict[str, float]:
        return {
            "samples_acquired": self.samples_acquired,
            "blocks_acquired": self.blocks_acquired,
            "gaps": self.gaps,
            "missing_samples": self.missing_samples,
            "observed_rate_hz": self.observed_rate_hz,
        }
