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
from wimsim.observability.metrics import Metrics, NullSink
from wimsim.observability.tracing import Tracing
from wimsim.storage.writer import EventWriter
from wimsim.transport.topics import wildcard_for

__all__ = ["IngestConsumer", "IngestStats"]

#: Where a queued row remembers the ``ingest`` span that accepted it, so the ``persist`` span
#: emitted at flush time can be its child rather than its sibling. Underscored and popped before
#: the row reaches the writer: it is bookkeeping, not payload.
_PERSIST_PARENT = "_persist_parent"


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
        metrics: Metrics | None = None,
        tracing: Tracing | None = None,
    ) -> None:
        self.metrics = metrics or Metrics(NullSink())
        self.tracing = tracing or Tracing(None)
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
            self.metrics.add("wim_dlq_total", 1, reason=outcome.reason)
            self.writer.write_dlq(mqtt_topic, raw, outcome.reason, outcome.detail)
            return

        assert isinstance(outcome, RoutedPayload)
        with self.tracing.continue_from(
            outcome.payload, "ingest", schema_topic=outcome.schema_topic
        ):
            self._observe_lag(outcome.payload)
            # Captured inside the span, used at flush time. A batch writes many rows, so `persist`
            # cannot be opened inside any one message's span -- but parenting it to the *publish*
            # context instead would draw it as a sibling of `ingest`, which reads as two concurrent
            # operations when one follows the other.
            persist_parent = self.tracing.current_traceparent()

            if outcome.schema_topic not in self._WRITERS:
                # A valid payload of a type nothing persists yet -- calibration.profile_activated
                # and calibration.drift_detected arrive in phase 5. Counted, not dead-lettered: it
                # is not malformed, we simply have nowhere to put it.
                self.stats.accepted += 1
                return

            self.stats.accepted += 1
            if persist_parent is not None:
                outcome.payload[_PERSIST_PARENT] = persist_parent
            with self._lock:
                self._pending[outcome.schema_topic].append(outcome.payload)
                due = sum(len(v) for v in self._pending.values()) >= self.batch_size
        if due:
            self.flush()

    def _observe_lag(self, payload: dict) -> None:
        """Station clock to ingest wall clock.

        Clock skew is inside this number deliberately. A station whose clock is wrong produces data
        that lands in the wrong bucket on every dashboard, and that has to be visible somewhere
        rather than quietly corrected here.
        """
        for key in ("ts_start", "ts"):
            value = payload.get(key)
            if isinstance(value, int):
                self.metrics.observe("wim_ingest_lag_ms", (time.time() - value / 1e6) * 1000.0)
                return

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

        parents = {
            schema_topic: [row.pop(_PERSIST_PARENT, None) for row in rows]
            for schema_topic, rows in batches.items()
        }

        written = 0
        failed: dict[str, list[dict]] = {}
        for schema_topic, rows in batches.items():
            method = getattr(self.writer, self._WRITERS[schema_topic])
            started_ns = time.time_ns()
            try:
                written += method(rows)
            except Exception:
                # Put them back rather than losing them. A database that is briefly unavailable
                # must not undo the guarantee the station's spool just provided.
                self.stats.flush_failures += 1
                failed[schema_topic] = rows
                continue
            finished_ns = time.time_ns()
            self.metrics.observe(
                "wim_db_write_latency_ms", (finished_ns - started_ns) / 1e6, table=schema_topic
            )
            self._record_persist_spans(parents[schema_topic], len(rows), started_ns, finished_ns)

        if failed:
            with self._lock:
                for schema_topic, rows in failed.items():
                    self._pending[schema_topic] = rows + self._pending[schema_topic]

        self.stats.written += written
        self.stats.flushes += 1
        self._last_flush = time.monotonic()
        return written

    def _record_persist_spans(
        self, parents: list[str | None], batch_size: int, started_ns: int, finished_ns: int
    ) -> None:
        """One ``persist`` span per row, over the batch's real interval.

        A flush writes many passes at once, so a single span could only belong to one of their
        traces and the rest would end at ``ingest`` with no visible database write. Each row
        therefore gets its own span over the interval the batch actually took, labelled with how
        many rows it shared that interval with -- which is the honest statement of what happened,
        rather than a fabricated per-row duration.
        """
        if not self.tracing.enabled:
            return
        for parent in parents:
            if parent is None:
                continue
            self.tracing.record(
                "persist",
                start_time_ns=started_ns,
                end_time_ns=finished_ns,
                payload={"traceparent": parent},
                batch_size=batch_size,
            )

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
