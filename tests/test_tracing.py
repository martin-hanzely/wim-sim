"""Tracing: seven stages, one trace, carried across a broker that has no headers.

The buildspec's requirement is concrete -- "select any single vehicle pass in Tempo and see its
complete lifecycle" -- and it has one hard part. The edge and the ingest are different processes
joined by MQTT, and MQTT 3.1.1 has no header mechanism, so the trace context has to travel *inside*
the payload. These tests pin that round trip: a span opened at ingest from a stamped payload must
land in the same trace as the publish span that stamped it, with the publish span as its parent.

Everything here runs against the SDK's in-memory exporter. No collector, no docker.
"""

from __future__ import annotations

import pytest

from wimsim.observability.tracing import (
    SPAN_NAMES,
    STAGES,
    Tracing,
    build_tracing,
    parse_traceparent,
    trace_id_of,
)


def _sdk_tracing() -> tuple[Tracing, object]:
    """A Tracing backed by a real SDK tracer and an in-memory exporter."""
    trace_sdk = pytest.importorskip("opentelemetry.sdk.trace")
    export = pytest.importorskip("opentelemetry.sdk.trace.export")
    memory = pytest.importorskip("opentelemetry.sdk.trace.export.in_memory_span_exporter")

    exporter = memory.InMemorySpanExporter()
    provider = trace_sdk.TracerProvider()
    provider.add_span_processor(export.SimpleSpanProcessor(exporter))
    return Tracing(provider.get_tracer("wimsim")), exporter


# ------------------------------------------------------------------------------------------
# the stage set
# ------------------------------------------------------------------------------------------


def test_stages_are_the_buildspec_lifecycle_in_order() -> None:
    assert STAGES == (
        "acquire",
        "preprocess",
        "detect",
        "estimate",
        "publish",
        "ingest",
        "persist",
    )


def test_the_block_root_is_allowed_but_is_not_a_stage() -> None:
    """The seven stages need a common parent to be siblings under, and per-stage latency is the
    whole point -- making `acquire` the parent would report it as taking as long as everything it
    contains. `block` is that parent, and it is structural rather than a stage of the measurement.
    """
    assert "block" not in STAGES
    assert "block" in SPAN_NAMES
    tracing, exporter = _sdk_tracing()
    with tracing.span("block"):
        pass
    assert exporter.get_finished_spans()[0].name == "block"


def test_an_undeclared_stage_is_refused() -> None:
    """Same discipline as the metric registry: a typo becomes a span nobody queries for."""
    tracing, _ = _sdk_tracing()
    with pytest.raises(KeyError, match="preproces"):
        with tracing.span("preproces"):
            pass


# ------------------------------------------------------------------------------------------
# the disabled path
# ------------------------------------------------------------------------------------------


def test_no_endpoint_configured_means_no_tracing(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("OTEL_EXPORTER_OTLP_ENDPOINT", raising=False)
    tracing = build_tracing(station_id="ST-1")
    assert not tracing.enabled


def test_the_disabled_path_still_yields_a_usable_span() -> None:
    """Call sites set attributes unconditionally; a None here would put an `if` at every one."""
    tracing = Tracing(None)
    with tracing.span("detect") as span:
        span.set_attribute("axle_count", 2)
        span.add_event("threshold_crossed")
    assert tracing.current_trace_id() is None


def test_the_disabled_path_still_validates_the_stage_name() -> None:
    tracing = Tracing(None)
    with pytest.raises(KeyError):
        with tracing.span("nonsense"):
            pass


def test_stamping_a_payload_while_disabled_leaves_it_alone() -> None:
    tracing = Tracing(None)
    payload = {"topic": "measurement.event", "station_id": "ST-1"}
    assert tracing.stamp(payload) == payload


def test_sdk_disabled_wins_over_a_configured_endpoint(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("OTEL_EXPORTER_OTLP_ENDPOINT", "http://localhost:4317")
    monkeypatch.setenv("OTEL_SDK_DISABLED", "true")
    assert not build_tracing(station_id="ST-1").enabled


# ------------------------------------------------------------------------------------------
# spans
# ------------------------------------------------------------------------------------------


def test_nested_stages_share_one_trace_and_chain_their_parents() -> None:
    tracing, exporter = _sdk_tracing()
    with tracing.span("acquire"):
        with tracing.span("preprocess"):
            with tracing.span("detect"):
                pass

    spans = {s.name: s for s in exporter.get_finished_spans()}
    assert set(spans) == {"acquire", "preprocess", "detect"}
    trace_ids = {s.context.trace_id for s in spans.values()}
    assert len(trace_ids) == 1
    assert spans["detect"].parent.span_id == spans["preprocess"].context.span_id
    assert spans["preprocess"].parent.span_id == spans["acquire"].context.span_id
    assert spans["acquire"].parent is None


def test_attributes_are_recorded() -> None:
    tracing, exporter = _sdk_tracing()
    with tracing.span("detect", axle_count=2, station_id="ST-1") as span:
        span.set_attribute("event_id", "e-1")
    (recorded,) = exporter.get_finished_spans()
    assert recorded.attributes["axle_count"] == 2
    assert recorded.attributes["station_id"] == "ST-1"
    assert recorded.attributes["event_id"] == "e-1"


def test_an_exception_marks_the_span_and_still_propagates() -> None:
    """A stage that died has to be visible as a red span, and the error still has to reach the
    caller -- an observability layer that swallows exceptions is worse than none."""
    from opentelemetry.trace import StatusCode

    tracing, exporter = _sdk_tracing()
    with pytest.raises(ZeroDivisionError):
        with tracing.span("estimate"):
            raise ZeroDivisionError("boom")

    (recorded,) = exporter.get_finished_spans()
    assert recorded.status.status_code is StatusCode.ERROR
    assert recorded.events[0].name == "exception"


# ------------------------------------------------------------------------------------------
# the round trip through a payload -- the whole point
# ------------------------------------------------------------------------------------------


def test_stamp_writes_both_trace_id_and_traceparent_and_they_agree() -> None:
    """`trace_id` is what the database column and every Grafana link use; `traceparent` is what
    actually re-parents a span. Two fields, one context, and they must not disagree."""
    tracing, _ = _sdk_tracing()
    with tracing.span("publish"):
        payload = tracing.stamp({"topic": "measurement.event"})

    assert parse_traceparent(payload["traceparent"])[0] == payload["trace_id"]
    assert len(payload["trace_id"]) == 32


def test_stamp_does_not_mutate_the_payload_it_was_given() -> None:
    tracing, _ = _sdk_tracing()
    original = {"topic": "measurement.event"}
    with tracing.span("publish"):
        tracing.stamp(original)
    assert original == {"topic": "measurement.event"}


def test_ingest_continues_the_trace_the_publisher_started() -> None:
    """The buildspec requirement, end to end: one pass, one trace, across the broker."""
    edge, edge_exporter = _sdk_tracing()
    with edge.span("publish") as publish_span:
        payload = edge.stamp({"topic": "measurement.event"})
        publish_trace = publish_span.get_span_context().trace_id
        publish_span_id = publish_span.get_span_context().span_id

    # ... over the wire, into a different process with its own provider ...
    server, server_exporter = _sdk_tracing()
    with server.continue_from(payload, "ingest"):
        with server.span("persist"):
            pass

    ingest, persist = server_exporter.get_finished_spans()[::-1]
    assert ingest.name == "ingest" and persist.name == "persist"
    assert ingest.context.trace_id == publish_trace
    assert ingest.parent.span_id == publish_span_id
    assert persist.context.trace_id == publish_trace
    assert len(edge_exporter.get_finished_spans()) == 1


def test_an_unstamped_payload_starts_a_fresh_trace_rather_than_failing() -> None:
    """Replayed recordings and hand-injected test payloads carry no context. Ingest must still
    produce a span, just an unparented one."""
    server, exporter = _sdk_tracing()
    with server.continue_from({"topic": "measurement.event"}, "ingest"):
        pass
    (span,) = exporter.get_finished_spans()
    assert span.parent is None


@pytest.mark.parametrize(
    "bad",
    [
        "",
        "not-a-traceparent",
        "00-abc-def-01",
        "00-" + "0" * 32 + "-" + "1" * 16 + "-01",  # all-zero trace id is invalid per W3C
        "00-" + "a" * 32 + "-" + "0" * 16 + "-01",  # all-zero span id likewise
        "99-" + "a" * 32 + "-" + "1" * 16 + "-01",  # unknown version
    ],
)
def test_a_malformed_traceparent_is_ignored_not_fatal(bad: str) -> None:
    """A broken header from anywhere must not take the ingest down; the pass is worth more than
    its trace."""
    assert parse_traceparent(bad) is None
    server, exporter = _sdk_tracing()
    with server.continue_from({"traceparent": bad}, "ingest"):
        pass
    (span,) = exporter.get_finished_spans()
    assert span.parent is None


def test_trace_id_of_reads_the_field_off_a_payload_or_model() -> None:
    """Log lines need the trace id and are handed whatever the caller had -- dict or model."""
    from wimsim.core.schemas import MeasurementSample

    assert trace_id_of({"trace_id": "abc"}) == "abc"
    assert trace_id_of({}) is None
    sample = MeasurementSample(
        station_id="ST-1", sensor_id="S1", ts=1, raw_value=0.1, raw_counts=10, trace_id="def"
    )
    assert trace_id_of(sample) == "def"


def test_current_trace_id_is_the_hex_of_the_active_span() -> None:
    tracing, _ = _sdk_tracing()
    assert tracing.current_trace_id() is None
    with tracing.span("acquire") as span:
        assert tracing.current_trace_id() == format(span.get_span_context().trace_id, "032x")
    assert tracing.current_trace_id() is None
