"""The transport seam, and the fake that makes it testable.

``Publisher`` talks to a ``Transport``, never to paho directly. That is not indirection for its own
sake: the properties that matter here -- nothing lost across an outage, replay in timestamp order,
a backlog that survives a restart -- are all about what happens when delivery *fails*, and a test
that cannot make delivery fail on demand cannot check any of them.

``InMemoryTransport`` can be switched off, made to fail after N messages, or made to fail
intermittently, deterministically and in microseconds. The MQTT integration test then checks the
one thing the fake cannot: that a real broker accepts what we send.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

__all__ = ["InMemoryTransport", "Transport", "TransportError"]


class TransportError(RuntimeError):
    """Delivery failed. The message stays queued; the caller must not acknowledge it."""


@runtime_checkable
class Transport(Protocol):
    def connect(self) -> None: ...

    def disconnect(self) -> None: ...

    @property
    def is_connected(self) -> bool: ...

    def publish(self, topic: str, payload: bytes, *, qos: int = 1) -> None:
        """Deliver, or raise :class:`TransportError`.

        Returning a success flag instead would make "did this work" optional to check, and the one
        call site that forgot would silently drop data.
        """
        ...


class InMemoryTransport:
    """A transport that records what it was given and fails exactly when told to."""

    def __init__(self, *, down: bool = False, fail_after: int | None = None) -> None:
        self.published: list[tuple[str, bytes, int]] = []
        self.down = down
        #: succeed for this many messages in total, then fail. ``None`` means never.
        self.fail_after = fail_after
        self.connect_calls = 0

    def connect(self) -> None:
        self.connect_calls += 1
        if self.down:
            raise TransportError("in-memory transport is down")

    def disconnect(self) -> None:
        return None

    @property
    def is_connected(self) -> bool:
        return not self.down

    def publish(self, topic: str, payload: bytes, *, qos: int = 1) -> None:
        if self.down:
            raise TransportError("in-memory transport is down")
        if self.fail_after is not None and len(self.published) >= self.fail_after:
            raise TransportError(f"in-memory transport fails after {self.fail_after} messages")
        self.published.append((topic, bytes(payload), qos))
