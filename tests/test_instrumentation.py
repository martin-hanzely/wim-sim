"""What the stages report about themselves.

Principle 5 says observability is data, not decoration, and these tests are what stops it becoming
decoration: each one asserts that a *specific* operational question has an answer in the metric
stream. How many samples arrived. How many holes were in them. How long an event waited between
being spooled and being acknowledged. Why something was dead-lettered.

The instrumentation sits at the pipeline and transport seams rather than inside the individual
stages. Those seams already know where one stage ends and the next begins, so nothing in
``preprocess.py`` or ``detect.py`` has to learn about OpenTelemetry to be measured.

Everything defaults to off. A pipeline built without a ``Metrics`` is exactly the pipeline phase 2
shipped, which is why the phase-2 numbers stay comparable.
"""

from __future__ import annotations

import json

import pytest

from wimsim.core.config import load_edge_config
from wimsim.observability.metrics import Metrics, RecordingSink
from wimsim.observability.tracing import Tracing
from wimsim.transport.base import Transport, TransportError
from wimsim.transport.queue import PersistentQueue


def _sdk_tracing():
    trace_sdk = pytest.importorskip("opentelemetry.sdk.trace")
    export = pytest.importorskip("opentelemetry.sdk.trace.export")
    memory = pytest.importorskip("opentelemetry.sdk.trace.export.in_memory_span_exporter")
    exporter = memory.InMemorySpanExporter()
    provider = trace_sdk.TracerProvider()
    provider.add_span_processor(export.SimpleSpanProcessor(exporter))
    return Tracing(provider.get_tracer("wimsim")), exporter


# ==========================================================================================
# The pipeline
# ==========================================================================================


@pytest.fixture
def instrumented_pipeline(short_cfg):
    """A real pipeline over a short S1 run, with a recording sink attached."""
    from wimsim.edge.pipeline import OfflinePipeline
    from wimsim.experiments.offline import _bootstrap_profile, _provenance_for
    from wimsim.source import SyntheticSource

    edge_cfg = load_edge_config("default")
    sink = RecordingSink()
    pipeline = OfflinePipeline(
        edge_cfg,
        source=SyntheticSource(short_cfg),
        profile=_bootstrap_profile(edge_cfg),
        provenance=_provenance_for(short_cfg),
        metrics=Metrics(sink).bind(station_id=short_cfg.station.station_id),
    )
    return pipeline, sink


def test_a_pipeline_with_no_metrics_is_the_phase_two_pipeline(short_cfg) -> None:
    """Instrumentation is opt-in, so the offline numbers stay comparable across phases."""
    from wimsim.edge.pipeline import OfflinePipeline
    from wimsim.experiments.offline import _bootstrap_profile, _provenance_for
    from wimsim.source import SyntheticSource

    edge_cfg = load_edge_config("default")
    pipeline = OfflinePipeline(
        edge_cfg,
        source=SyntheticSource(short_cfg),
        profile=_bootstrap_profile(edge_cfg),
        provenance=_provenance_for(short_cfg),
    )
    assert not pipeline.metrics.enabled
    assert not pipeline.tracing.enabled
    for _ in pipeline.detect_only():
        pass
    assert pipeline.acquisition.samples_acquired > 0


def test_samples_acquired_is_reported_and_agrees_with_the_agent(instrumented_pipeline) -> None:
    pipeline, sink = instrumented_pipeline
    for _ in pipeline.detect_only():
        pass
    assert sum(sink.values("wim_samples_acquired_total")) == pipeline.acquisition.samples_acquired


def test_samples_are_reported_per_block_not_once_at_the_end(instrumented_pipeline) -> None:
    """A counter that only moves when a run finishes tells a dashboard nothing during the run,
    which is the only time anybody is looking at it."""
    pipeline, sink = instrumented_pipeline
    for _ in pipeline.detect_only():
        pass
    assert len(sink.values("wim_samples_acquired_total")) == pipeline.acquisition.blocks_acquired


def test_gaps_are_reported_as_increments(instrumented_pipeline) -> None:
    """S1 is a clean stream, so the honest assertion is that nothing is invented."""
    pipeline, sink = instrumented_pipeline
    for _ in pipeline.detect_only():
        pass
    assert sum(sink.values("wim_sample_gaps_total")) == pipeline.acquisition.missing_samples


def test_detected_events_are_counted(instrumented_pipeline) -> None:
    pipeline, sink = instrumented_pipeline
    detected = list(pipeline.detect_only())
    assert detected
    assert sum(sink.values("wim_events_detected_total")) == len(detected)


def test_interval_width_is_reported_for_every_emitted_event(short_run) -> None:
    """The one quality metric the edge can compute alone: it needs no reference mass, so it is not
    a truth leak (see the note on the quality group in observability/metrics.py)."""
    from wimsim.experiments.offline import load_run, run_offline

    cfg, truth, _ = load_run(short_run.out_dir)
    sink = RecordingSink()
    result = run_offline(
        cfg, truth, load_edge_config("default"), calibration_passes=2, metrics=Metrics(sink)
    )

    widths = sink.values("wim_interval_width")
    assert len(widths) == len(result.events)
    assert all(w > 0 for w in widths)


def test_the_stage_spans_nest_under_one_block_span(instrumented_pipeline) -> None:
    """Per-stage latency in Tempo needs the stages to be siblings under a common parent; making
    `acquire` the parent would report it as taking as long as the whole block."""
    pipeline, _ = instrumented_pipeline
    tracing, exporter = _sdk_tracing()
    pipeline.tracing = tracing

    for _ in pipeline.detect_only():
        break

    spans = exporter.get_finished_spans()
    by_name = {s.name: s for s in spans}
    assert {"acquire", "preprocess", "detect", "block"} <= set(by_name)
    block = by_name["block"]
    for stage in ("acquire", "preprocess", "detect"):
        assert by_name[stage].parent.span_id == block.context.span_id


# ==========================================================================================
# The publisher
# ==========================================================================================


class _FakeTransport(Transport):
    """Accepts everything, or refuses everything, on command."""

    def __init__(self) -> None:
        self.sent: list[tuple[str, bytes]] = []
        self.up = True

    @property
    def is_connected(self) -> bool:
        return self.up

    def connect(self) -> None: ...
    def disconnect(self) -> None: ...

    def publish(self, topic: str, payload: bytes, *, qos: int = 1) -> None:
        if not self.up:
            raise TransportError("link down")
        self.sent.append((topic, payload))


def _publisher(tmp_path, transport, **kwargs):
    from wimsim.transport.publisher import Publisher

    return Publisher(
        transport,
        queue=PersistentQueue(tmp_path / "spool.db"),
        station_id="ST-1",
        **kwargs,
    )


def _sample_payload(ts: int = 1_748_736_000_000_000) -> dict:
    return {
        "topic": "measurement.sample",
        "schema_version": "1.1.0",
        "station_id": "ST-1",
        "sensor_id": "S1",
        "ts": ts,
        "raw_value": 0.1,
        "raw_counts": 10,
    }


def test_buffer_depth_is_reported_after_every_publish(tmp_path) -> None:
    """Depth is the number an operator watches during an outage; a stale one is worse than none."""
    sink = RecordingSink()
    transport = _FakeTransport()
    pub = _publisher(tmp_path, transport, metrics=Metrics(sink))

    transport.up = False
    for i in range(3):
        pub.publish("measurement.sample", _sample_payload(1_748_736_000_000_000 + i))
    assert sink.values("wim_buffer_depth")[-1] == 3

    transport.up = True
    pub.drain(force=True)
    assert sink.values("wim_buffer_depth")[-1] == 0
    pub.close()


def test_publish_failures_are_counted(tmp_path) -> None:
    sink = RecordingSink()
    transport = _FakeTransport()
    transport.up = False
    pub = _publisher(tmp_path, transport, metrics=Metrics(sink))
    pub.publish("measurement.sample", _sample_payload())
    assert sum(sink.values("wim_publish_failures_total")) == 1
    pub.close()


def test_publish_latency_is_measured_from_enqueue_to_acknowledgement(tmp_path) -> None:
    sink = RecordingSink()
    transport = _FakeTransport()
    pub = _publisher(tmp_path, transport, metrics=Metrics(sink))
    pub.publish("measurement.sample", _sample_payload())
    latencies = sink.values("wim_publish_latency_ms")
    assert len(latencies) == 1
    assert 0.0 <= latencies[0] < 1000.0
    pub.close()


def test_a_message_spooled_by_a_previous_process_reports_no_latency(tmp_path) -> None:
    """Its enqueue time died with that process. A wall-clock difference across a restart is not a
    latency, and inventing one would put a six-hour outage into the publish histogram."""
    sink = RecordingSink()
    transport = _FakeTransport()
    transport.up = False
    first = _publisher(tmp_path, transport, metrics=Metrics(RecordingSink()))
    first.publish("measurement.sample", _sample_payload())
    first.close()

    transport.up = True
    second = _publisher(tmp_path, transport, metrics=Metrics(sink))
    assert second.drain(force=True) == 1
    assert sink.values("wim_publish_latency_ms") == []
    second.close()


def test_the_publisher_stamps_the_trace_context_onto_the_payload(tmp_path) -> None:
    """The buildspec's requirement, at the point it has to happen: the last moment the edge holds
    both the payload and its span."""
    transport = _FakeTransport()
    tracing, exporter = _sdk_tracing()
    pub = _publisher(tmp_path, transport, tracing=tracing)
    pub.publish("measurement.sample", _sample_payload())

    (_topic, blob) = transport.sent[0]
    payload = json.loads(blob)
    (span,) = exporter.get_finished_spans()
    assert span.name == "publish"
    assert payload["trace_id"] == format(span.context.trace_id, "032x")
    assert payload["traceparent"].startswith("00-" + payload["trace_id"])
    pub.close()


def test_an_untraced_publisher_leaves_the_payload_untouched(tmp_path) -> None:
    transport = _FakeTransport()
    pub = _publisher(tmp_path, transport)
    pub.publish("measurement.sample", _sample_payload())
    payload = json.loads(transport.sent[0][1])
    assert "traceparent" not in payload
    pub.close()


def test_the_stamped_payload_still_validates(tmp_path) -> None:
    """It is about to cross a broker into a validator that forbids unknown fields."""
    from wimsim.core.schemas import MeasurementSample

    transport = _FakeTransport()
    tracing, _ = _sdk_tracing()
    pub = _publisher(tmp_path, transport, tracing=tracing)
    pub.publish("measurement.sample", _sample_payload())
    MeasurementSample.model_validate(json.loads(transport.sent[0][1]))
    pub.close()


# ==========================================================================================
# Ingest
# ==========================================================================================


class _FakeWriter:
    def __init__(self) -> None:
        self.rows: list[dict] = []
        self.dlq: list[tuple] = []

    def write_events(self, rows) -> int:
        self.rows.extend(rows)
        return len(rows)

    def write_samples(self, rows) -> int:
        self.rows.extend(rows)
        return len(rows)

    def write_dlq(self, topic, raw, reason, detail) -> int:
        self.dlq.append((topic, raw, reason, detail))
        return 1


def _consumer(writer, **kwargs):
    from wimsim.ingest.consumer import IngestConsumer

    return IngestConsumer(writer, **kwargs)


def test_dead_letters_are_counted_by_reason() -> None:
    """`wim_dlq_total` without the reason label is an alert; with it, it is a diagnosis."""
    sink = RecordingSink()
    writer = _FakeWriter()
    consumer = _consumer(writer, metrics=Metrics(sink))

    consumer.handle("edge/ST-1/sample", b"\xff\xfe not utf-8")
    consumer.handle("edge/ST-1/sample", b"{not json")

    reasons = [r.attributes["reason"] for r in sink.records if r.name == "wim_dlq_total"]
    assert reasons == ["invalid_utf8", "invalid_json"]


def test_ingest_lag_is_measured_against_the_station_clock() -> None:
    """Clock skew is deliberately inside this number: a station whose clock is wrong produces data
    that lands in the wrong bucket, and that has to be visible somewhere."""
    import time

    sink = RecordingSink()
    consumer = _consumer(_FakeWriter(), metrics=Metrics(sink))
    ts = int((time.time() - 2.0) * 1e6)
    consumer.handle("edge/ST-1/sample", json.dumps(_sample_payload(ts)).encode())

    (lag,) = sink.values("wim_ingest_lag_ms")
    assert 1500.0 < lag < 5000.0


def test_write_latency_is_reported_per_flush() -> None:
    sink = RecordingSink()
    consumer = _consumer(_FakeWriter(), metrics=Metrics(sink))
    for i in range(3):
        consumer.handle(
            "edge/ST-1/sample", json.dumps(_sample_payload(1_748_736_000_000_000 + i)).encode()
        )
    consumer.flush()
    assert len(sink.values("wim_db_write_latency_ms")) == 1


def test_ingest_continues_the_trace_carried_in_the_payload() -> None:
    """Publisher to database in one trace, across a broker with no headers."""
    tracing, exporter = _sdk_tracing()
    consumer = _consumer(_FakeWriter(), tracing=tracing)

    trace_id = "a" * 32
    payload = _sample_payload() | {
        "trace_id": trace_id,
        "traceparent": f"00-{trace_id}-{'1' * 16}-01",
    }
    consumer.handle("edge/ST-1/sample", json.dumps(payload).encode())
    consumer.flush()

    spans = {s.name: s for s in exporter.get_finished_spans()}
    assert format(spans["ingest"].context.trace_id, "032x") == trace_id
    assert format(spans["persist"].context.trace_id, "032x") == trace_id


def test_persist_spans_are_one_per_row_and_carry_the_batch_size() -> None:
    """One flush writes many passes, so a single persist span could only belong to one trace. Each
    row gets its own, over the batch's real interval, labelled with how many it shared it with --
    which is the honest statement of what happened."""
    tracing, exporter = _sdk_tracing()
    consumer = _consumer(_FakeWriter(), tracing=tracing)

    for i in range(3):
        trace_id = f"{i + 1:032x}"
        payload = _sample_payload(1_748_736_000_000_000 + i) | {
            "trace_id": trace_id,
            "traceparent": f"00-{trace_id}-{'1' * 16}-01",
        }
        consumer.handle("edge/ST-1/sample", json.dumps(payload).encode())
    consumer.flush()

    persists = [s for s in exporter.get_finished_spans() if s.name == "persist"]
    assert len(persists) == 3
    assert {format(s.context.trace_id, "032x") for s in persists} == {
        f"{i + 1:032x}" for i in range(3)
    }
    assert all(s.attributes["batch_size"] == 3 for s in persists)


def test_an_untraced_ingest_still_works() -> None:
    consumer = _consumer(_FakeWriter())
    consumer.handle("edge/ST-1/sample", json.dumps(_sample_payload()).encode())
    assert consumer.flush() == 1


def test_activating_a_profile_reports_the_calibration_it_activated(instrumented_pipeline) -> None:
    """The calibration dashboard's centrepiece is the estimate drawn on the truth; that needs the
    estimate to be in the metric stream at all, from the moment a profile becomes active."""
    from wimsim.calibration import CalibrationProfile, EstimatorState

    pipeline, sink = instrumented_pipeline
    sink.records.clear()
    state = EstimatorState(estimator="static_affine", gain=1.0 / 2.0e-4, bias=0.0, fitted=True)
    pipeline.set_profile(
        CalibrationProfile.from_state(state, profile_id="p-1", activated_ts_us=0, reason="test")
    )

    assert sink.values("wim_cal_gain_estimate") == pytest.approx([2.0e-4])
    assert sink.values("wim_cal_bias_estimate") == pytest.approx([0.0])


def test_the_profile_version_steps_on_each_activation(instrumented_pipeline) -> None:
    """A step function is what an annotation can be drawn against. A profile_id label would open a
    new series per recalibration and hide the step it exists to show."""
    from wimsim.calibration import CalibrationProfile, EstimatorState

    pipeline, sink = instrumented_pipeline
    state = EstimatorState(estimator="static_affine", gain=1.0, bias=0.0, fitted=True)
    for i in range(2):
        pipeline.set_profile(
            CalibrationProfile.from_state(
                state, profile_id=f"p-{i}", activated_ts_us=0, reason="test"
            )
        )
    # One for the bootstrap profile the fixture constructs with, then two more.
    assert sink.values("wim_cal_profile_version") == [1.0, 2.0, 3.0]
    assert all(
        "profile_id" not in r.attributes
        for r in sink.records
        if r.name == "wim_cal_profile_version"
    )
