"""A source that hands blocks over no faster than the clock allows.

A synthetic run generates a fifteen-minute stream in a couple of seconds, which is exactly what you
want for scoring and exactly wrong for watching a dashboard: every point lands in one Prometheus
scrape, every trace shares a millisecond, and the buffer-depth gauge never leaves zero because the
publisher drains as fast as the pipeline fills it. None of the phase-4 panels can be judged from
that.

Pacing belongs here rather than in the pipeline because it is a property of the *stream*, not of the
processing -- and because a decorator over ``SourceAdapter`` keeps principle 2 intact: the pipeline
still cannot tell what it is reading from.

``speed`` is a multiplier on real time. ``1.0`` replays a 900-second run in 900 seconds; ``60.0``
does it in fifteen. The sleep is computed against the *stream's own* timestamps and a fixed start
instant rather than per block, so a slow block does not push every later one later -- the schedule
is absolute, and falling behind is visible as a lag rather than hidden as drift.
"""

from __future__ import annotations

import time
from collections.abc import Iterator

from wimsim.core.types import SampleBlock, SourceMetadata
from wimsim.source.base import BaseSource, SourceAdapter

__all__ = ["PacedSource"]


class PacedSource(BaseSource):
    """Wraps another source and releases its blocks on a wall clock."""

    def __init__(self, inner: SourceAdapter, *, speed: float = 1.0) -> None:
        if speed <= 0:
            raise ValueError(f"speed must be positive; got {speed}")
        self.inner = inner
        self.speed = float(speed)
        #: How far behind the schedule the slowest block fell, in seconds. Zero means the machine
        #: kept up, which is the only condition under which the latency panels mean anything.
        self.max_lag_s = 0.0

    @property
    def metadata(self) -> SourceMetadata:
        return self.inner.metadata

    def stream_blocks(self) -> Iterator[SampleBlock]:
        origin_us: int | None = None
        started = time.monotonic()

        for block in self.inner.stream_blocks():
            if block.n == 0:
                yield block
                continue
            if origin_us is None:
                origin_us = int(block.ts_us[0])

            due = started + (int(block.ts_us[-1]) - origin_us) / 1e6 / self.speed
            delay = due - time.monotonic()
            if delay > 0:
                time.sleep(delay)
            else:
                self.max_lag_s = max(self.max_lag_s, -delay)
            yield block
