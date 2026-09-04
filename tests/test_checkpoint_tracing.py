"""The phase-4 checkpoint: one pass, one trace, acquire to persist.

Buildspec section 9 states it as a thing you can do rather than a thing that is implemented --
"select any single vehicle pass in Tempo and see its complete lifecycle with per-stage latency" --
so this test does exactly that, against the running stack, and fails if any of the seven stages is
missing from the trace.

The hard part is not instrumentation, it is that two processes joined by MQTT have to agree on a
trace, and MQTT 3.1.1 has no headers. The context rides in the payload; ``tests/test_tracing.py``
checks that round trip in isolation, and this checks it survives a real broker, a real collector and
a real Tempo.

Skips when the stack is down, with instructions.
"""

from __future__ import annotations

import json
import socket
import time
import urllib.error
import urllib.request
import uuid

import pytest

from wimsim.core.config import load_edge_config, load_run_config
from wimsim.observability.tracing import STAGES, build_tracing
from wimsim.transport import PersistentQueue, Publisher
from wimsim.transport.mqtt import MqttTransport

MQTT_HOST, MQTT_PORT = "localhost", 1883
OTLP = "http://localhost:4317"
TEMPO = "http://localhost:3200"


def _reachable(host: str, port: int) -> bool:
    try:
        with socket.create_connection((host, port), timeout=1.0):
            return True
    except OSError:
        return False


def _tempo_up() -> bool:
    try:
        with urllib.request.urlopen(f"{TEMPO}/ready", timeout=2.0):
            return True
    except Exception:
        return False


pytestmark = pytest.mark.skipif(
    not (_reachable(MQTT_HOST, MQTT_PORT) and _reachable("localhost", 4317) and _tempo_up()),
    reason=(
        "phase-4 stack not reachable -- `docker compose --profile core --profile observability "
        "up -d` (needs mosquitto, otel-collector and tempo)"
    ),
)


class _CapturingWriter:
    """Stands in for the database. This checkpoint is about the trace, not about persistence --
    that is tested by test_end_to_end.py -- and a real writer would make the test depend on
    migrations having been run as well."""

    def __init__(self) -> None:
        self.rows: list[dict] = []

    def write_events(self, rows) -> int:
        self.rows.extend(rows)
        return len(rows)

    def write_dlq(self, *_args) -> int:  # pragma: no cover - nothing should be rejected
        raise AssertionError("the checkpoint published a payload the router refused")


def _fetch_trace(trace_id: str, *, timeout_s: float = 30.0) -> dict:
    """Tempo, after the collector's batch processor has got round to it."""
    deadline = time.monotonic() + timeout_s
    last: Exception | None = None
    while time.monotonic() < deadline:
        try:
            with urllib.request.urlopen(f"{TEMPO}/api/traces/{trace_id}", timeout=5.0) as response:
                body = json.load(response)
            if body.get("batches"):
                return body
        except urllib.error.HTTPError as exc:  # 404 until the batch arrives
            last = exc
        except Exception as exc:  # pragma: no cover - network flake
            last = exc
        time.sleep(1.0)
    raise AssertionError(f"trace {trace_id} never arrived in Tempo ({last})")


def _spans(trace: dict) -> list[tuple[str, str, str, str]]:
    """``(service, name, span_id, parent_id)`` for every span in the trace."""
    out = []
    for batch in trace["batches"]:
        service = next(
            (
                a["value"].get("stringValue")
                for a in batch["resource"]["attributes"]
                if a["key"] == "service.name"
            ),
            "?",
        )
        for scope in batch["scopeSpans"]:
            for span in scope["spans"]:
                out.append((service, span["name"], span["spanId"], span.get("parentSpanId", "")))
    return out


@pytest.fixture(scope="module")
def one_pass(tmp_path_factory):
    """Push a short run through a fully traced edge, and return one pass's trace id.

    A module fixture because the collector batches on a two-second timer and Tempo takes a moment
    to index; doing this once and asserting several things about the result is much faster than
    running it per test, and every assertion below is about the same trace anyway.
    """
    from wimsim.experiments.live import run_live
    from wimsim.ingest import IngestConsumer
    from wimsim.signal.writer import write_run

    station = f"ST-TRACE-{uuid.uuid4().hex[:8]}"
    cfg = load_run_config(
        "S1_nominal",
        overrides=[
            "scenario.duration_s=180.0",
            "scenario.output.samples=none",
            f"station.station_id={station}",
        ],
    )
    out = write_run(cfg, tmp_path_factory.mktemp("trace"))

    import pandas as pd

    truth = pd.read_parquet(out.out_dir / "truth_passes.parquet")

    edge_tracing = build_tracing(station_id=station, endpoint=OTLP)
    ingest_tracing = build_tracing(station_id=station, service_name="wimsim-ingest", endpoint=OTLP)
    assert edge_tracing.enabled and ingest_tracing.enabled

    writer = _CapturingWriter()
    consumer = IngestConsumer(
        writer,
        host=MQTT_HOST,
        port=MQTT_PORT,
        station_filter=station,
        tracing=ingest_tracing,
    )
    consumer.start()

    transport = MqttTransport(host=MQTT_HOST, port=MQTT_PORT, station_id=station)
    transport.connect()
    publisher = Publisher(
        transport,
        queue=PersistentQueue(tmp_path_factory.mktemp("spool") / "spool.db"),
        station_id=station,
        tracing=edge_tracing,
    )

    try:
        result = run_live(
            cfg,
            truth,
            load_edge_config("default"),
            publisher=publisher,
            tracing=edge_tracing,
            calibration_passes=3,
        )
        assert result.published > 0

        deadline = time.monotonic() + 20.0
        while len(writer.rows) < result.published and time.monotonic() < deadline:
            consumer.flush()
            time.sleep(0.2)
        consumer.flush()
        assert len(writer.rows) == result.published
    finally:
        consumer.stop()
        publisher.close()
        transport.disconnect()

    trace_ids = [row["trace_id"] for row in writer.rows if row.get("trace_id")]
    assert len(trace_ids) == len(writer.rows), "every stored event must name its trace"
    return _fetch_trace(trace_ids[len(trace_ids) // 2])


def test_one_pass_is_traceable_from_acquire_to_persist(one_pass) -> None:
    """The checkpoint, stated as the buildspec states it."""
    names = {name for _service, name, _sid, _pid in _spans(one_pass)}
    assert set(STAGES) <= names, f"missing stages: {sorted(set(STAGES) - names)}"


def test_the_trace_crosses_the_process_boundary(one_pass) -> None:
    """Edge and ingest are separate processes with separate tracer providers. The context got there
    inside the payload, because MQTT has no header to put it in."""
    services = {service for service, _n, _s, _p in _spans(one_pass)}
    assert services == {"wimsim-edge", "wimsim-ingest"}


def test_the_spans_form_one_connected_tree(one_pass) -> None:
    """A trace with orphans looks complete in a list and is useless in a waterfall: the whole
    reason `traceparent` is carried alongside `trace_id` is that a trace id alone cannot re-parent
    anything."""
    spans = _spans(one_pass)
    ids = {span_id for _s, _n, span_id, _p in spans}
    roots = [name for _s, name, _sid, parent in spans if not parent]
    orphans = [name for _s, name, _sid, parent in spans if parent and parent not in ids]

    assert roots == ["block"], f"expected one block root, got {roots}"
    assert not orphans, f"spans with a parent that is not in the trace: {orphans}"


def test_ingest_hangs_off_publish_and_persist_off_ingest(one_pass) -> None:
    spans = _spans(one_pass)
    by_id = {span_id: (service, name) for service, name, span_id, _p in spans}
    parents = {
        name: by_id.get(parent, ("?", None))[1]
        for _s, name, _sid, parent in spans
        if name in {"publish", "ingest", "persist"}
    }
    assert parents["publish"] == "estimate"
    assert parents["ingest"] == "publish"
    assert parents["persist"] == "ingest", (
        "persist parented to publish would draw it as a sibling of ingest, which reads as two "
        "concurrent operations rather than one following the other"
    )
