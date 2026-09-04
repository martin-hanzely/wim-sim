"""Streaming a run to the broker: pacing, publishing inside the trace, and truth kept separate.

``run_live`` is what makes the phase-4 checkpoint runnable -- a pass published through it can be
selected in Tempo and followed from ``acquire`` to ``persist``. No broker is needed here; the
publisher is handed a transport that keeps what it is given.
"""

from __future__ import annotations

import json

import pytest

from wimsim.core.config import load_edge_config
from wimsim.observability.metrics import Metrics, RecordingSink
from wimsim.observability.tracing import Tracing
from wimsim.source import PacedSource
from wimsim.transport.base import Transport
from wimsim.transport.queue import PersistentQueue

# ==========================================================================================
# PacedSource
# ==========================================================================================


class _Blocks:
    """A source of pre-made blocks, so pacing can be tested without generating a signal."""

    def __init__(self, blocks, metadata) -> None:
        self._blocks = blocks
        self._metadata = metadata

    @property
    def metadata(self):
        return self._metadata

    def stream_blocks(self):
        yield from self._blocks


@pytest.fixture
def two_blocks(short_cfg):
    from wimsim.source import SyntheticSource

    source = SyntheticSource(short_cfg)
    blocks = []
    for block in source.stream_blocks():
        blocks.append(block)
        if len(blocks) == 2:
            break
    return _Blocks(blocks, source.metadata)


def test_pacing_takes_about_the_stream_duration_divided_by_speed(two_blocks) -> None:
    import time

    span_s = (int(two_blocks._blocks[-1].ts_us[-1]) - int(two_blocks._blocks[0].ts_us[0])) / 1e6
    paced = PacedSource(two_blocks, speed=span_s / 0.2)  # aim for ~0.2 s of wall clock

    t0 = time.monotonic()
    assert len(list(paced.stream_blocks())) == 2
    elapsed = time.monotonic() - t0
    assert 0.1 < elapsed < 1.0


def test_an_unpaced_source_is_not_wrapped_at_all(short_cfg) -> None:
    """`--speed` omitted has to mean *no* sleeping, not sleeping zero: the offline path runs a
    fifteen-minute scenario in seconds and must keep doing so."""
    from wimsim.experiments.live import run_live  # noqa: F401  (import cost only)
    from wimsim.source import SyntheticSource

    source = SyntheticSource(short_cfg)
    assert not isinstance(source, PacedSource)


def test_a_non_positive_speed_is_refused(two_blocks) -> None:
    with pytest.raises(ValueError, match="positive"):
        PacedSource(two_blocks, speed=0.0)


def test_the_schedule_is_absolute_so_a_slow_block_does_not_shift_the_rest(two_blocks) -> None:
    """Per-block sleeps accumulate: a run that stalls once would stay late for the rest of the
    replay, and the lag would be invisible. Against a fixed origin it shows up in max_lag_s."""
    import time

    paced = PacedSource(two_blocks, speed=1e9)  # every block is already overdue
    list(paced.stream_blocks())
    assert paced.max_lag_s > 0.0

    slow = PacedSource(two_blocks, speed=1e9)
    time.sleep(0.01)
    list(slow.stream_blocks())


def test_pacing_does_not_alter_the_samples(two_blocks) -> None:
    """It is a SourceAdapter; the pipeline must not be able to tell (principle 2)."""
    import numpy as np

    paced = list(PacedSource(two_blocks, speed=1e9).stream_blocks())
    for original, delivered in zip(two_blocks._blocks, paced, strict=True):
        assert np.array_equal(original.raw_value, delivered.raw_value)
        assert np.array_equal(original.ts_us, delivered.ts_us)


def test_metadata_passes_straight_through(two_blocks) -> None:
    paced = PacedSource(two_blocks, speed=1.0)
    assert paced.metadata is two_blocks.metadata


# ==========================================================================================
# run_live
# ==========================================================================================


class _KeepingTransport(Transport):
    def __init__(self) -> None:
        self.sent: list[tuple[str, bytes]] = []

    @property
    def is_connected(self) -> bool:
        return True

    def connect(self) -> None: ...
    def disconnect(self) -> None: ...

    def publish(self, topic: str, payload: bytes, *, qos: int = 1) -> None:
        self.sent.append((topic, payload))


@pytest.fixture
def live(short_run, tmp_path):
    from wimsim.experiments.offline import load_run
    from wimsim.transport.publisher import Publisher

    cfg, truth, _ = load_run(short_run.out_dir)
    transport = _KeepingTransport()
    sink = RecordingSink()
    metrics = Metrics(sink).bind(station_id=cfg.station.station_id)
    publisher = Publisher(
        transport,
        queue=PersistentQueue(tmp_path / "spool.db"),
        station_id=cfg.station.station_id,
        metrics=metrics,
    )
    return cfg, truth, transport, publisher, metrics, sink


def test_every_measured_pass_reaches_the_transport(live) -> None:
    from wimsim.experiments.live import run_live

    cfg, truth, transport, publisher, metrics, _sink = live
    result = run_live(
        cfg,
        truth,
        load_edge_config("default"),
        publisher=publisher,
        metrics=metrics,
        calibration_passes=2,
    )
    assert result.published == len(result.events) > 0
    assert len(transport.sent) == result.published
    assert result.buffered == 0
    publisher.close()


def test_what_is_published_is_a_valid_measurement_event(live) -> None:
    from wimsim.core.schemas import MeasurementEvent
    from wimsim.experiments.live import run_live

    cfg, truth, transport, publisher, metrics, _sink = live
    run_live(
        cfg,
        truth,
        load_edge_config("default"),
        publisher=publisher,
        metrics=metrics,
        calibration_passes=2,
    )
    topic, blob = transport.sent[0]
    assert topic.endswith("/event")
    MeasurementEvent.model_validate(json.loads(blob))
    publisher.close()


def test_publishing_happens_inside_the_pass_trace(live) -> None:
    """The checkpoint's requirement. If `publish` were a root span the pass would appear in Tempo
    as two unrelated traces, which looks fine in a list and is useless in a waterfall."""
    trace_sdk = pytest.importorskip("opentelemetry.sdk.trace")
    export = pytest.importorskip("opentelemetry.sdk.trace.export")
    memory = pytest.importorskip("opentelemetry.sdk.trace.export.in_memory_span_exporter")
    from wimsim.experiments.live import run_live

    exporter = memory.InMemorySpanExporter()
    provider = trace_sdk.TracerProvider()
    provider.add_span_processor(export.SimpleSpanProcessor(exporter))
    tracing = Tracing(provider.get_tracer("wimsim"))

    cfg, truth, _transport, publisher, metrics, _sink = live
    publisher.tracing = tracing
    run_live(
        cfg,
        truth,
        load_edge_config("default"),
        publisher=publisher,
        metrics=metrics,
        tracing=tracing,
        calibration_passes=2,
    )

    spans = exporter.get_finished_spans()
    by_id = {s.context.span_id: s for s in spans}
    publishes = [s for s in spans if s.name == "publish"]
    assert publishes

    for pub in publishes:
        estimate = by_id[pub.parent.span_id]
        assert estimate.name == "estimate"
        block = by_id[estimate.parent.span_id]
        assert block.name in {"block", "detect"}
        # acquire, preprocess and detect all live in the same trace as the publish
        siblings = {s.name for s in spans if s.context.trace_id == pub.context.trace_id}
        assert {"acquire", "preprocess", "detect", "estimate", "publish"} <= siblings
    publisher.close()


def test_the_published_payload_carries_the_context_for_the_ingest_side(live) -> None:
    trace_sdk = pytest.importorskip("opentelemetry.sdk.trace")
    from wimsim.experiments.live import run_live

    tracing = Tracing(trace_sdk.TracerProvider().get_tracer("wimsim"))
    cfg, truth, transport, publisher, metrics, _sink = live
    publisher.tracing = tracing
    run_live(
        cfg,
        truth,
        load_edge_config("default"),
        publisher=publisher,
        metrics=metrics,
        tracing=tracing,
        calibration_passes=2,
    )
    payload = json.loads(transport.sent[0][1])
    assert payload["traceparent"].startswith("00-" + payload["trace_id"])
    publisher.close()


def test_the_live_run_reports_the_same_metrics_as_the_offline_one(live) -> None:
    from wimsim.experiments.live import run_live

    cfg, truth, _transport, publisher, metrics, sink = live
    result = run_live(
        cfg,
        truth,
        load_edge_config("default"),
        publisher=publisher,
        metrics=metrics,
        calibration_passes=2,
    )
    assert sum(sink.values("wim_events_detected_total")) == len(result.events)
    assert len(sink.values("wim_interval_width")) == len(result.events)
    assert len(sink.values("wim_publish_latency_ms")) == result.published
    publisher.close()


def test_the_calibration_is_fitted_before_anything_is_published(live) -> None:
    """A mass emitted through an unfitted bootstrap profile is a number nobody should keep, so the
    fitting pass runs first and publishes nothing."""
    from wimsim.experiments.live import run_live

    cfg, truth, transport, publisher, metrics, _sink = live
    result = run_live(
        cfg,
        truth,
        load_edge_config("default"),
        publisher=publisher,
        metrics=metrics,
        calibration_passes=2,
    )
    assert result.profile_id.startswith("p-")
    for _topic, blob in transport.sent:
        assert json.loads(blob)["calibration"]["profile_id"] == result.profile_id
    publisher.close()


def test_too_few_passes_to_calibrate_is_a_clear_error(live) -> None:
    from wimsim.experiments.live import run_live

    cfg, truth, _transport, publisher, metrics, _sink = live
    with pytest.raises(ValueError, match="reserved for calibration"):
        run_live(
            cfg,
            truth,
            load_edge_config("default"),
            publisher=publisher,
            metrics=metrics,
            calibration_passes=500,
        )
    publisher.close()
