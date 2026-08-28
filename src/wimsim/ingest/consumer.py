"""The ingest consumer: broker to database, with a dead-letter queue in between.

Subscribes at QoS 1, validates, batches by type, and upserts. Everything it cannot accept goes to
the DLQ with a reason code and its original bytes.

**Batching is by type, not by arrival.** Ten events and three metrics arriving interleaved become
two statements, not thirteen. At a few hundred events an hour that is irrelevant; when a station
that has been offline for six hours drains its backlog in one burst, it is the difference between
keeping up and falling further behind.

**A flush that fails does not lose the batch.** The rows go back on the pending list and are retried
with the next flush, because the alternative -- dropping a batch because the database was briefly
unavailable -- would defeat the persistent spool that got the data this far.
"""

from __future__ import annotations

import threading
import time
from collections import defaultdict
from typing import Any, ClassVar

import paho.mqtt.client as mqtt

from wimsim.ingest.router import Rejection, RoutedPayload, Router
from wimsim.storage.writer import EventWriter
from wimsim.transport.topics import wildcard_for

__all__ = ["IngestConsumer", "IngestStats"]


class IngestStats:
    __slots__ = ("accepted", "by_reason", "flush_failures", "flushes", "rejected", "written")

    def __init__(self) -> None:
        self.accepted = 0
        self.rejected = 0
        self.written = 0
        self.flushes = 0
        self.flush_failures = 0
        self.by_reason: dict[str, int] = defaultdict(int)

    def as_dict(self) -> dict[str, Any]:
        return {
            "accepted": self.accepted,
            "rejected": self.rejected,
            "written": self.written,
            "flushes": self.flushes,
            "flush_failures": self.flush_failures,
            "by_reason": dict(self.by_reason),
        }


class IngestConsumer:
    """One subscriber, one writer, one dead-letter queue."""

    #: schema topic -> the writer method that persists it
    _WRITERS: ClassVar[dict[str, str]] = {
        "measurement.event": "write_events",
        "measurement.sample": "write_samples",
        "calibration.state": "write_calibration_states",
        "system.metric": "write_metrics",
        "system.incident": "write_incidents",
    }

    def __init__(
        self,
        writer: EventWriter,
        *,
        host: str = "localhost",
        port: int = 1883,
        station_filter: str = "+",
        batch_size: int = 500,
        flush_interval_s: float = 1.0,
        router: Router | None = None,
        client_id: str = "wimsim-ingest",
    ) -> None:
        self.writer = writer
        self.host = host
        self.port = port
        self.topic = wildcard_for(station_filter)
        self.batch_size = batch_size
        self.flush_interval_s = flush_interval_s
        self.router = router or Router()
        self.stats = IngestStats()

        self._pending: dict[str, list[dict]] = defaultdict(list)
        self._lock = threading.Lock()
        self._last_flush = time.monotonic()
        self._subscribed = threading.Event()

        self._client = mqtt.Client(
            mqtt.CallbackAPIVersion.VERSION2, client_id=client_id, protocol=mqtt.MQTTv5
        )
        self._client.on_message = self._on_message
        self._client.on_subscribe = lambda *_a, **_k: self._subscribed.set()

    # -- message handling -------------------------------------------------------------------------

    def handle(self, mqtt_topic: str, raw: bytes) -> None:
        """Route one payload. Public so the whole path is testable without a broker."""
        outcome = self.router.route(mqtt_topic, raw)
        if isinstance(outcome, Rejection):
            self.stats.rejected += 1
            self.stats.by_reason[outcome.reason] += 1
            self.writer.write_dlq(mqtt_topic, raw, outcome.reason, outcome.detail)
            return

        assert isinstance(outcome, RoutedPayload)
        if outcome.schema_topic not in self._WRITERS:
            # A valid payload of a type nothing persists yet -- calibration.profile_activated and
            # calibration.drift_detected arrive in phase 5. Counted, not dead-lettered: it is not
            # malformed, we simply have nowhere to put it.
            self.stats.accepted += 1
            return

        self.stats.accepted += 1
        with self._lock:
            self._pending[outcome.schema_topic].append(outcome.payload)
            due = sum(len(v) for v in self._pending.values()) >= self.batch_size
        if due:
            self.flush()

    def _on_message(self, _client, _userdata, message) -> None:
        try:
            self.handle(message.topic, message.payload)
        except Exception as exc:  # a bad message must never kill the subscriber thread
            self.stats.rejected += 1
            self.stats.by_reason["handler_error"] += 1
            try:
                self.writer.write_dlq(message.topic, message.payload, "handler_error", str(exc))
            except Exception:
                pass

    # -- flushing ---------------------------------------------------------------------------------

    def flush(self) -> int:
        with self._lock:
            batches = {topic: rows for topic, rows in self._pending.items() if rows}
            self._pending = defaultdict(list)
        if not batches:
            return 0

        written = 0
        failed: dict[str, list[dict]] = {}
        for schema_topic, rows in batches.items():
            method = getattr(self.writer, self._WRITERS[schema_topic])
            try:
                written += method(rows)
            except Exception:
                # Put them back rather than losing them. A database that is briefly unavailable
                # must not undo the guarantee the station's spool just provided.
                self.stats.flush_failures += 1
                failed[schema_topic] = rows

        if failed:
            with self._lock:
                for schema_topic, rows in failed.items():
                    self._pending[schema_topic] = rows + self._pending[schema_topic]

        self.stats.written += written
        self.stats.flushes += 1
        self._last_flush = time.monotonic()
        return written

    @property
    def pending_count(self) -> int:
        with self._lock:
            return sum(len(v) for v in self._pending.values())

    # -- lifecycle ---------------------------------------------------------------------------------

    def start(self, *, timeout_s: float = 10.0) -> None:
        self._client.connect(self.host, self.port, keepalive=30)
        self._client.loop_start()
        self._client.subscribe(self.topic, qos=1)
        if not self._subscribed.wait(timeout_s):
            raise RuntimeError(f"subscription to {self.topic} was not acknowledged")

    def poll(self) -> int:
        """Flush if the interval has elapsed. Call from the owning loop."""
        if time.monotonic() - self._last_flush >= self.flush_interval_s:
            return self.flush()
        return 0

    def stop(self) -> None:
        self._client.loop_stop()
        self._client.disconnect()
        self.flush()

    def __enter__(self) -> IngestConsumer:
        self.start()
        return self

    def __exit__(self, *exc: object) -> None:
        self.stop()
