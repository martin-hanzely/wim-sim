"""The source abstraction -- principle 2's load-bearing interface.

Everything downstream of a :class:`SourceAdapter` is identical whether samples come from the
generator, from a replayed recording of real passes, or eventually from a serial port on a Jetson.
When the real drives arrive, only a config line changes.

Two methods, because two granularities are genuinely needed:

``stream()``
    One :class:`~wimsim.core.types.Sample` at a time. This is the interface real acquisition
    hardware presents, and the one the protocol in the buildspec specifies. Use it for
    hardware-in-the-loop and for tests that need per-sample control.
``stream_blocks()``
    :class:`~wimsim.core.types.SampleBlock` at a time, as numpy arrays. This is the fast path and
    what every pipeline stage should prefer -- iterating two thousand Python objects per second of
    simulated time costs more than the entire rest of the chain.

``stream()`` has a default implementation in terms of ``stream_blocks()``, so an adapter only has
to provide the block form.

What is deliberately *not* on this interface: anything that would let a downstream stage learn the
truth. No true mass, no true gain, no "am I being fed a known reference vehicle". A stage can read
``metadata.mode`` for labelling, and that is all.
"""

from __future__ import annotations

from collections.abc import Iterator
from typing import Protocol, runtime_checkable

from wimsim.core.types import Sample, SampleBlock, SourceMetadata

__all__ = ["BaseSource", "SourceAdapter"]


@runtime_checkable
class SourceAdapter(Protocol):
    def stream(self) -> Iterator[Sample]: ...

    def stream_blocks(self) -> Iterator[SampleBlock]: ...

    @property
    def metadata(self) -> SourceMetadata: ...


class BaseSource:
    """Mixin supplying ``stream()`` for adapters that implement ``stream_blocks()``."""

    def stream_blocks(self) -> Iterator[SampleBlock]:  # pragma: no cover - overridden
        raise NotImplementedError

    def stream(self) -> Iterator[Sample]:
        for block in self.stream_blocks():
            yield from block

    @property
    def metadata(self) -> SourceMetadata:  # pragma: no cover - overridden
        raise NotImplementedError
