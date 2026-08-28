"""Phase 3, end to end: generator -> pipeline -> publisher -> broker -> ingest -> TimescaleDB.

Every stage has its own tests. This is the one that checks they compose, which is a different
question and historically the one that catches things -- a timestamp convention that each side
implements consistently and differently, a field that validates on the way out and not on the way
in, an id that is not as unique as everybody assumed.

Skips when the stack is down, with instructions.
"""

from __future__ import annotations

import socket
import time
import uuid

import pytest
from sqlalchemy import text

from wimsim.core.config import load_edge_config, load_run_config
from wimsim.experiments.offline import run_offline
from wimsim.ingest import IngestConsumer
from wimsim.signal.writer import write_run
from wimsim.storage import EventWriter, database_url
from wimsim.storage.schema import dlq, measurement_event
from wimsim.transport import PersistentQueue, Publisher
from wimsim.transport.mqtt import MqttTransport

MQTT_HOST, MQTT_PORT = "localhost", 1883


def _reachable(host: str, port: int) -> bool:
    try:
        with socket.create_connection((host, port), timeout=1.0):
            return True
    except OSError:
        return False


def _database_up() -> bool:
    try:
        writer = EventWriter()
        with writer.engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        writer.dispose()
        return True
    except Exception:
        return False


pytestmark = pytest.mark.skipif(
    not (_reachable(MQTT_HOST, MQTT_PORT) and _database_up()),
    reason=(
        "phase-3 stack not reachable -- `docker compose --profile core up -d` "
        f"then `alembic upgrade head` (database: {database_url()})"
    ),
)


@pytest.fixture(scope="module")
def writer():
    w = EventWriter()
    yield w
    w.dispose()


@pytest.fixture
def events(tmp_path_factory):
    """A short synthetic run, taken all the way through the phase-2 pipeline."""
    cfg = load_run_config(
        "S1_nominal",
        overrides=["scenario.duration_s=300.0", "scenario.output.samples=none"],
    )
    out = write_run(cfg, tmp_path_factory.mktemp("e2e"))
    import pandas as pd

    truth = pd.read_parquet(out.out_dir / "truth_passes.parquet")
    result = run_offline(cfg, truth, load_edge_config("default"), calibration_passes=5)
    assert len(result.events) > 5
    return result.events


def _count_for(writer: EventWriter, station: str) -> int:
    with writer.engine.connect() as conn:
        return int(
            conn.execute(
                text("SELECT count(*) FROM wim.measurement_event WHERE station_id = :s"),
                {"s": station},
            ).scalar_one()
        )


def test_events_travel_from_the_generator_to_the_database(tmp_path, writer, events) -> None:
    station = f"ST-E2E-{uuid.uuid4().hex[:8]}"
    consumer = IngestConsumer(writer, host=MQTT_HOST, port=MQTT_PORT, station_filter=station)
    consumer.start()

    transport = MqttTransport(host=MQTT_HOST, port=MQTT_PORT, station_id=station)
    transport.connect()
    publisher = Publisher(
        transport, queue=PersistentQueue(tmp_path / "spool.db"), station_id=station
    )

    try:
        for event in events:
            payload = event.model_dump(mode="json")
            payload["station_id"] = station  # route this run to its own station id
            publisher.publish("measurement.event", payload)
        assert publisher.flush(timeout_s=20.0)

        deadline = time.monotonic() + 20.0
        while _count_for(writer, station) < len(events) and time.monotonic() < deadline:
            consumer.flush()
            time.sleep(0.1)
        consumer.flush()

        assert _count_for(writer, station) == len(events)
        assert consumer.stats.rejected == 0
    finally:
        consumer.stop()
        publisher.close()
        transport.disconnect()


def test_redelivery_updates_in_place_rather_than_duplicating(tmp_path, writer, events) -> None:
    """QoS 1 is at-least-once, a drained backlog can resend, and phase 5's recompute re-derives
    history on purpose. All three must converge on one row per event."""
    station = f"ST-IDEM-{uuid.uuid4().hex[:8]}"
    payloads = []
    for event in events[:10]:
        payload = event.model_dump(mode="json")
        payload["station_id"] = station
        payloads.append(payload)

    writer.write_events(payloads)
    first = _count_for(writer, station)
    assert first == len(payloads)

    writer.write_events(payloads)
    assert _count_for(writer, station) == first, "a redelivery must not insert a second row"

    # ...and a recompute under a new profile updates the existing row
    for payload in payloads:
        payload["mass_kg"] = payload["mass_kg"] + 100.0
        payload["calibration"]["profile_id"] = "p-recomputed"
    writer.write_events(payloads)
    assert _count_for(writer, station) == first

    with writer.engine.connect() as conn:
        profiles = (
            conn.execute(
                text("SELECT DISTINCT profile_id FROM wim.measurement_event WHERE station_id = :s"),
                {"s": station},
            )
            .scalars()
            .all()
        )
    assert profiles == ["p-recomputed"], "the row was updated, not shadowed by a second one"


def test_a_malformed_payload_lands_in_the_dlq_not_the_events_table(tmp_path, writer) -> None:
    station = f"ST-DLQ-{uuid.uuid4().hex[:8]}"
    consumer = IngestConsumer(writer, host=MQTT_HOST, port=MQTT_PORT, station_filter=station)
    consumer.start()

    transport = MqttTransport(host=MQTT_HOST, port=MQTT_PORT, station_id=station)
    transport.connect()

    before = writer.count(dlq)
    try:
        transport.publish(f"edge/{station}/event", b'{"topic": "measurement.event", "broken":')
        deadline = time.monotonic() + 15.0
        while writer.count(dlq) <= before and time.monotonic() < deadline:
            time.sleep(0.1)

        assert writer.count(dlq) == before + 1
        assert _count_for(writer, station) == 0
        with writer.engine.connect() as conn:
            reason = conn.execute(
                text("SELECT reason_code FROM wim.dlq ORDER BY id DESC LIMIT 1")
            ).scalar_one()
        assert reason == "invalid_json"
    finally:
        consumer.stop()
        transport.disconnect()


def test_the_stored_event_keeps_its_provenance(tmp_path, writer, events) -> None:
    """Principle 3, checked at the far end: a row nobody can trace back is not evidence."""
    station = f"ST-PROV-{uuid.uuid4().hex[:8]}"
    payload = events[0].model_dump(mode="json")
    payload["station_id"] = station
    writer.write_events([payload])

    with writer.engine.connect() as conn:
        row = (
            conn.execute(
                text(
                    "SELECT provenance, preprocessing, cal_state_hash, quality_flag "
                    "FROM wim.measurement_event WHERE station_id = :s"
                ),
                {"s": station},
            )
            .mappings()
            .one()
        )

    assert row["provenance"]["config_hash"] == payload["provenance"]["config_hash"]
    assert row["provenance"]["seed"] == payload["provenance"]["seed"]
    assert row["preprocessing"]["filter"] == payload["preprocessing"]["filter"]
    assert row["cal_state_hash"] == payload["calibration"]["state_hash"]
    assert row["quality_flag"] == payload["quality_flag"]


def test_timestamps_survive_the_round_trip_to_the_microsecond(tmp_path, writer, events) -> None:
    """Integer microseconds on the wire, timestamptz in the database. The conversion happens in
    exactly one place, and this is the test that says it is lossless."""
    station = f"ST-TIME-{uuid.uuid4().hex[:8]}"
    payload = events[0].model_dump(mode="json")
    payload["station_id"] = station
    writer.write_events([payload])

    with writer.engine.connect() as conn:
        stored = conn.execute(
            text(
                "SELECT (EXTRACT(EPOCH FROM ts_start) * 1000000)::bigint AS us "
                "FROM wim.measurement_event WHERE station_id = :s"
            ),
            {"s": station},
        ).scalar_one()
    assert int(stored) == payload["ts_start"]


def test_the_hypertable_is_actually_partitioned(writer, events) -> None:
    """A hypertable that was never converted still works and silently loses every benefit."""
    station = f"ST-CHUNK-{uuid.uuid4().hex[:8]}"
    payloads = []
    for event in events[:5]:
        payload = event.model_dump(mode="json")
        payload["station_id"] = station
        payloads.append(payload)
    writer.write_events(payloads)

    with writer.engine.connect() as conn:
        chunks = conn.execute(
            text(
                "SELECT count(*) FROM timescaledb_information.chunks "
                "WHERE hypertable_schema = 'wim' AND hypertable_name = 'measurement_event'"
            )
        ).scalar_one()
    assert int(chunks) >= 1
    assert writer.count(measurement_event) >= 5
