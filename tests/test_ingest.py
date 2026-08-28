"""Ingest: validation, dead-lettering, and batching.

The router is pure -- bytes in, a validated payload or a rejection out -- so every malformed-input
case is checked here without a broker or a database.

The rule these tests exist to protect: **nothing reaches the database unvalidated, and nothing is
silently discarded.** A pipeline that quietly drops what it cannot parse is indistinguishable, from
the outside, from one that is working.
"""

from __future__ import annotations

import json

import pytest

from wimsim.ingest.consumer import IngestConsumer
from wimsim.ingest.router import Rejection, RoutedPayload, Router


def _event(**over) -> dict:
    base = {
        "topic": "measurement.event",
        "schema_version": "1.0.0",
        "station_id": "ST-1",
        "sensor_id": "S1",
        "ts_start": 1_748_736_000_000_000,
        "ts_peak": 1_748_736_000_005_000,
        "ts_end": 1_748_736_000_010_000,
        "raw_peak": 1.5,
        "raw_area": 0.016,
        "compensated_peak": 1.47,
        "mass_kg": 7350.0,
        "mass_ci_low": 7100.0,
        "mass_ci_high": 7600.0,
        "calibration": {
            "profile_id": "p-1",
            "estimator": "static_affine",
            "gain": 2e-4,
            "bias": 0.05,
            "state_hash": "abc",
            "update_count": 1,
        },
        "preprocessing": {"filter": "none", "zero_window_s": 2.0},
        "provenance": {"config_hash": "a" * 64, "seed": 1, "mode": "synthetic", "git_dirty": False},
    }
    base.update(over)
    return base


def _blob(payload: dict) -> bytes:
    return json.dumps(payload).encode("utf-8")


class _FakeWriter:
    """Records what it was asked to persist, and can be told to fail."""

    def __init__(self) -> None:
        self.events: list[dict] = []
        self.metrics: list[dict] = []
        self.dead: list[tuple[str, str, str]] = []
        self.fail_events = False

    def write_events(self, rows):
        if self.fail_events:
            raise RuntimeError("database unavailable")
        self.events.extend(rows)
        return len(rows)

    def write_metrics(self, rows):
        self.metrics.extend(rows)
        return len(rows)

    def write_samples(self, rows):
        return len(rows)

    def write_calibration_states(self, rows):
        return len(rows)

    def write_incidents(self, rows):
        return len(rows)

    def write_dlq(self, topic, payload, reason, detail=""):
        blob = payload.decode("utf-8", "replace") if isinstance(payload, bytes) else payload
        self.dead.append((topic, reason, blob))


def _consumer(writer: _FakeWriter, **kw) -> IngestConsumer:
    return IngestConsumer(writer, **kw)


# -- the router ---------------------------------------------------------------------------------


def test_a_valid_event_routes_to_its_schema_topic() -> None:
    out = Router().route("edge/ST-1/event", _blob(_event()))
    assert isinstance(out, RoutedPayload)
    assert out.schema_topic == "measurement.event"
    assert out.payload["mass_kg"] == 7350.0
    assert out.payload["event_id"], "the derived id must survive validation"


@pytest.mark.parametrize(
    ("raw", "reason"),
    [
        (b"\xff\xfe not utf8", "invalid_utf8"),
        (b"{not json", "invalid_json"),
        (b"[1, 2, 3]", "not_an_object"),
        (b'{"mass_kg": 1}', "missing_topic"),
        (b'{"topic": "measurement.telepathy"}', "unknown_topic"),
    ],
)
def test_malformed_payloads_are_rejected_with_a_specific_reason(raw: bytes, reason: str) -> None:
    out = Router().route("edge/ST-1/event", raw)
    assert isinstance(out, Rejection)
    assert out.reason == reason
    assert out.detail, "a reason code without detail cannot be debugged"


def test_a_payload_failing_schema_validation_says_which_field() -> None:
    out = Router().route("edge/ST-1/event", _blob(_event(mass_ci_low=9999.0)))
    assert isinstance(out, Rejection)
    assert out.reason == "schema_validation_failed"
    assert "mass_ci_low" in out.detail


def test_a_missing_required_field_is_rejected() -> None:
    payload = _event()
    del payload["provenance"]
    out = Router().route("edge/ST-1/event", _blob(payload))
    assert isinstance(out, Rejection)
    assert out.reason == "schema_validation_failed"
    assert "provenance" in out.detail


def test_a_payload_on_the_wrong_mqtt_topic_is_rejected() -> None:
    """The MQTT topic is a routing convenience; a producer can publish anything anywhere. A
    disagreement between it and the payload's own type is itself a defect."""
    out = Router().route("edge/ST-1/metric", _blob(_event()))
    assert isinstance(out, Rejection)
    assert out.reason == "topic_mismatch"


def test_topic_checking_can_be_relaxed_for_a_foreign_bridge() -> None:
    out = Router(strict_topic=False).route("some/other/path", _blob(_event()))
    assert isinstance(out, RoutedPayload)


# -- the consumer -------------------------------------------------------------------------------


def test_accepted_events_are_batched_and_written(_=None) -> None:
    writer = _FakeWriter()
    consumer = _consumer(writer, batch_size=1000)
    for i in range(5):
        consumer.handle("edge/ST-1/event", _blob(_event(ts_start=1_748_736_000_000_000 + i * 1000)))

    assert writer.events == [], "nothing written before the flush"
    assert consumer.pending_count == 5
    assert consumer.flush() == 5
    assert len(writer.events) == 5
    assert consumer.stats.accepted == 5


def test_a_full_batch_flushes_itself() -> None:
    writer = _FakeWriter()
    consumer = _consumer(writer, batch_size=3)
    for i in range(3):
        consumer.handle("edge/ST-1/event", _blob(_event(ts_start=1_748_736_000_000_000 + i * 1000)))
    assert len(writer.events) == 3
    assert consumer.pending_count == 0


def test_batching_groups_by_type_not_by_arrival() -> None:
    writer = _FakeWriter()
    consumer = _consumer(writer, batch_size=1000)
    for i in range(4):
        consumer.handle("edge/ST-1/event", _blob(_event(ts_start=1_748_736_000_000_000 + i * 1000)))
        consumer.handle(
            "edge/ST-1/metric",
            _blob(
                {
                    "topic": "system.metric",
                    "station_id": "ST-1",
                    "ts": 1_748_736_000_000_000 + i,
                    "name": "wim_buffer_depth",
                    "value": float(i),
                }
            ),
        )
    consumer.flush()
    assert len(writer.events) == 4
    assert len(writer.metrics) == 4


def test_rejected_payloads_go_to_the_dlq_with_their_bytes_intact() -> None:
    writer = _FakeWriter()
    consumer = _consumer(writer)
    consumer.handle("edge/ST-1/event", b"{not json")

    assert writer.events == []
    assert len(writer.dead) == 1
    topic, reason, blob = writer.dead[0]
    assert topic == "edge/ST-1/event"
    assert reason == "invalid_json"
    assert blob == "{not json", "the payload must be kept verbatim, or it cannot be diagnosed"
    assert consumer.stats.rejected == 1
    assert consumer.stats.by_reason["invalid_json"] == 1


def test_a_failed_flush_keeps_the_rows_for_the_next_attempt() -> None:
    """A database that is briefly unavailable must not undo the guarantee the station's spool
    just provided."""
    writer = _FakeWriter()
    consumer = _consumer(writer, batch_size=1000)
    for i in range(3):
        consumer.handle("edge/ST-1/event", _blob(_event(ts_start=1_748_736_000_000_000 + i * 1000)))

    writer.fail_events = True
    assert consumer.flush() == 0
    assert consumer.pending_count == 3, "the batch must not have been dropped"
    assert consumer.stats.flush_failures == 1

    writer.fail_events = False
    assert consumer.flush() == 3
    assert len(writer.events) == 3
    assert consumer.pending_count == 0


def test_a_valid_but_not_yet_persisted_type_is_counted_not_dead_lettered() -> None:
    """calibration.drift_detected arrives in phase 5. It is not malformed; there is simply nowhere
    to put it yet, and dead-lettering valid data would make the DLQ meaningless."""
    writer = _FakeWriter()
    consumer = _consumer(writer)
    consumer.handle(
        "edge/ST-1/calibration",
        _blob(
            {
                "topic": "calibration.drift_detected",
                "station_id": "ST-1",
                "sensor_id": "S1",
                "ts": 1_748_736_000_000_000,
                "detector": "cusum",
                "statistic": 8.4,
                "threshold": 5.0,
                "profile_id": "p-1",
            }
        ),
    )
    assert consumer.stats.accepted == 1
    assert writer.dead == []


def test_an_exception_in_the_handler_does_not_kill_the_subscriber() -> None:
    class _Exploding(_FakeWriter):
        def write_dlq(self, *a, **k):
            super().write_dlq(*a, **k)

    writer = _Exploding()
    consumer = _consumer(writer)

    class _Msg:
        topic = "edge/ST-1/event"
        payload = b"{not json"

    consumer._on_message(None, None, _Msg())
    assert consumer.stats.rejected == 1


def test_stats_are_reportable() -> None:
    writer = _FakeWriter()
    consumer = _consumer(writer, batch_size=1000)
    consumer.handle("edge/ST-1/event", _blob(_event()))
    consumer.handle("edge/ST-1/event", b"garbage")
    consumer.flush()
    stats = consumer.stats.as_dict()
    assert stats["accepted"] == 1
    assert stats["rejected"] == 1
    assert stats["written"] == 1
    assert stats["by_reason"]["invalid_json"] == 1
