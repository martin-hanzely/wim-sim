"""Stage 5 of the edge pipeline: getting events off the station without losing any.

The contract, from buildspec section 5: serialise to the event schema, write to a persistent local
queue, publish, mark acknowledged. On outage keep buffering, expose ``buffer_depth``, retry with
backoff, replay in timestamp order on reconnect.

The ordering of those verbs is the design. **Enqueue happens before publish, and acknowledgement
happens after.** Anything else has a window in which an event exists only in memory, and the whole
point of the component is that no such window exists.

``publish()`` never blocks on the network and never raises on a delivery failure -- it appends to the
spool and opportunistically drains. The pipeline that calls it is processing a sample stream in real
time; making it wait on a socket would turn a network problem into dropped samples, which is a
strictly worse failure than a growing backlog.
"""

from __future__ import annotations

import json
import time
from typing import Any

from wimsim.transport.base import Transport, TransportError
from wimsim.transport.queue import PersistentQueue
from wimsim.transport.topics import topic_for

__all__ = ["Publisher"]


def _timestamp_of(payload: dict[str, Any]) -> int:
    """Measurement time, for replay ordering.

    ``ts_start`` for an event, ``ts`` for everything else. An event's *start* rather than its peak
    or end so that a vehicle's ordering matches when it arrived at the sensor.
    """
    for key in ("ts_start", "ts"):
        value = payload.get(key)
        if isinstance(value, int):
            return value
    return 0


class Publisher:
    def __init__(
        self,
        transport: Transport,
        *,
        queue: PersistentQueue,
        station_id: str,
        batch_size: int = 200,
        max_queue_depth: int = 500_000,
        backoff_initial_s: float = 0.5,
        backoff_max_s: float = 30.0,
        backoff_factor: float = 2.0,
    ) -> None:
        self.transport = transport
        self.queue = queue
        self.station_id = station_id
        self.batch_size = batch_size
        self.max_queue_depth = max_queue_depth

        self._backoff_initial = backoff_initial_s
        self._backoff_max = backoff_max_s
        self._backoff_factor = backoff_factor
        self.current_backoff_s = backoff_initial_s
        self._retry_after = 0.0

        self._was_connected = True
        self.reconnect_count = 0
        self.published_count = 0
        self.failure_count = 0
        self.dropped_count = 0

    # -- accepting work -------------------------------------------------------------------------

    def publish(self, schema_topic: str, payload: dict[str, Any], *, qos: int = 1) -> None:
        """Spool an event and try to send. Never blocks on the network, never raises on failure."""
        blob = json.dumps(payload, separators=(",", ":"), sort_keys=True).encode("utf-8")
        self.queue.append(
            topic_for(self.station_id, schema_topic),
            blob,
            ts_us=_timestamp_of(payload),
            qos=qos,
        )
        dropped = self.queue.trim_to(self.max_queue_depth)
        if dropped:
            self.dropped_count += dropped
        self.drain()

    def publish_model(self, model: Any, *, qos: int = 1) -> None:
        """Spool a pydantic event model. The schema topic comes from the payload's own ``topic``."""
        payload = model.model_dump(mode="json")
        self.publish(payload["topic"], payload, qos=qos)

    # -- draining -------------------------------------------------------------------------------

    def drain(self, *, now: float | None = None, force: bool = False) -> int:
        """Send as much of the backlog as the link will take. Returns how many got through.

        The backoff gate rate-limits *automatic* retries: without it, a publisher in a loop hammers
        a dead broker as fast as the CPU allows. Two things bypass it, because in both cases the
        caller knows something the timer does not:

        * ``force=True`` -- a reconnect handler, or a shutdown flush, asking to try right now.
        * the transport reporting a fresh connection. A link that has just come back is the one
          moment when waiting out a thirty-second backoff is exactly wrong.
        """
        clock = time.monotonic() if now is None else now
        if self._note_connection_state():
            force = True
        if not force and clock < self._retry_after:
            return 0

        batch = self.queue.peek(self.batch_size)
        if not batch:
            return 0

        sent: list[int] = []
        for message in batch:
            try:
                self.transport.publish(message.topic, message.payload, qos=message.qos)
            except TransportError:
                self.failure_count += 1
                break
            sent.append(message.row_id)

        if sent:
            self.queue.ack(sent)
            self.published_count += len(sent)

        if len(sent) == len(batch):
            self._on_success()
        else:
            self._on_failure(clock)
        return len(sent)

    def _note_connection_state(self) -> bool:
        """True when the transport has just come back. Resets the backoff as a side effect."""
        try:
            connected = bool(self.transport.is_connected)
        except Exception:  # a transport that cannot answer is not a reason to stop publishing
            return False
        reconnected = connected and not self._was_connected
        self._was_connected = connected
        if reconnected:
            self.reconnect_count += 1
            self.current_backoff_s = self._backoff_initial
            self._retry_after = 0.0
        return reconnected

    def _on_success(self) -> None:
        self.current_backoff_s = self._backoff_initial
        self._retry_after = 0.0

    def _on_failure(self, clock: float) -> None:
        self._retry_after = clock + self.current_backoff_s
        self.current_backoff_s = min(
            self.current_backoff_s * self._backoff_factor, self._backoff_max
        )

    def flush(self, *, timeout_s: float = 30.0, poll_s: float = 0.05) -> bool:
        """Block until the backlog is empty or the timeout expires. For shutdown, not for the loop."""
        deadline = time.monotonic() + timeout_s
        while self.buffer_depth and time.monotonic() < deadline:
            before = self.buffer_depth
            self.drain(force=True)
            if self.buffer_depth == before:
                time.sleep(poll_s)
        return self.buffer_depth == 0

    # -- observability ---------------------------------------------------------------------------

    @property
    def buffer_depth(self) -> int:
        return self.queue.depth()

    @property
    def oldest_queued_age_s(self) -> float | None:
        """How stale the head of the backlog is, in seconds of *measurement* time.

        More useful on a dashboard than depth alone: a thousand queued events from ten seconds ago
        is a busy road, and a hundred from six hours ago is a station nobody noticed had fallen off.
        """
        oldest = self.queue.oldest_ts_us()
        if oldest is None:
            return None
        return max(time.time() - oldest / 1e6, 0.0)

    def stats(self) -> dict[str, float]:
        return {
            "published": self.published_count,
            "failures": self.failure_count,
            "dropped": self.dropped_count,
            "buffer_depth": self.buffer_depth,
            "backoff_s": self.current_backoff_s,
            "reconnects": self.reconnect_count,
        }

    def close(self) -> None:
        self.queue.close()
