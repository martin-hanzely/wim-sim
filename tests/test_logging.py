"""Structured logging: one JSON object per line, and the five fields that make it joinable.

Buildspec section 9 is specific -- "every line carries ``event_id``, ``trace_id``, ``station_id``,
``profile_id``, ``run_id``". The point of that list is joins: a Loki query filtered by ``trace_id``
next to a Tempo trace with the same id, or every line about one pass pulled up by ``event_id``. A
field that is *sometimes* present cannot be filtered on with any confidence, so the rule enforced
here is stronger than "present when known": the keys are always there, null when unset.

The other thing worth protecting is that logging never becomes a source of failure. A value that
will not serialise, a station with no collector, a second call to ``configure_logging`` -- none of
those may raise, and none may silently double every line.
"""

from __future__ import annotations

import json
import logging

import pytest

from wimsim.observability.logging import (
    LOG_FIELDS,
    JsonFormatter,
    bind,
    configure_logging,
    get_logger,
    log_context,
    reset_context,
)


@pytest.fixture
def captured(caplog: pytest.LogCaptureFixture):
    """Emit through the real formatter, return the parsed JSON lines."""
    formatter = JsonFormatter()

    def lines() -> list[dict]:
        return [json.loads(formatter.format(r)) for r in caplog.records]

    caplog.set_level(logging.DEBUG, logger="wimsim")
    return lines


# ------------------------------------------------------------------------------------------
# the required fields
# ------------------------------------------------------------------------------------------


def test_log_fields_are_the_buildspec_five() -> None:
    assert LOG_FIELDS == ("event_id", "trace_id", "station_id", "profile_id", "run_id")


def test_every_line_carries_every_field_even_when_unset(captured) -> None:
    """Null beats absent: a Loki filter on a key that is only sometimes emitted silently drops the
    lines that would have told you why."""
    get_logger("wimsim.test").info("hello")
    (line,) = captured()
    for field in LOG_FIELDS:
        assert field in line
        assert line[field] is None


def test_bound_fields_appear_on_the_line(captured) -> None:
    with bind(station_id="ST-1", run_id="r-9", event_id="e-1", profile_id="p-1"):
        get_logger("wimsim.test").info("weighed")
    (line,) = captured()
    assert line["station_id"] == "ST-1"
    assert line["run_id"] == "r-9"
    assert line["event_id"] == "e-1"
    assert line["profile_id"] == "p-1"


def test_binding_nests_and_unwinds(captured) -> None:
    log = get_logger("wimsim.test")
    with bind(station_id="ST-1"):
        log.info("outer")
        with bind(event_id="e-1"):
            log.info("inner")
        log.info("after")
    log.info("outside")

    outer, inner, after, outside = captured()
    assert outer["event_id"] is None and outer["station_id"] == "ST-1"
    assert inner["event_id"] == "e-1" and inner["station_id"] == "ST-1"
    assert after["event_id"] is None and after["station_id"] == "ST-1"
    assert outside["station_id"] is None


def test_binding_unwinds_through_an_exception(captured) -> None:
    """A pass that raised is exactly when the next line's context matters most."""
    with pytest.raises(ValueError):
        with bind(event_id="e-1"):
            raise ValueError("boom")
    get_logger("wimsim.test").info("recovered")
    (line,) = captured()
    assert line["event_id"] is None


def test_an_unknown_bind_key_is_refused() -> None:
    """The five are a contract with the dashboards. Anything else is per-line `extra`."""
    with pytest.raises(KeyError, match="sensor_id"):
        with bind(sensor_id="S1"):
            pass


def test_log_context_reads_what_is_currently_bound() -> None:
    assert log_context() == dict.fromkeys(LOG_FIELDS)
    with bind(station_id="ST-1"):
        assert log_context()["station_id"] == "ST-1"


# ------------------------------------------------------------------------------------------
# the line itself
# ------------------------------------------------------------------------------------------


def test_the_line_is_one_json_object_with_the_usual_envelope(captured) -> None:
    get_logger("wimsim.test").warning("degraded")
    (line,) = captured()
    assert line["level"] == "WARNING"
    assert line["message"] == "degraded"
    assert line["logger"] == "wimsim.test"
    assert line["ts"].endswith("Z")


def test_extras_land_at_the_top_level(captured) -> None:
    """`mass_kg=7350` should be a queryable field, not prose inside the message."""
    get_logger("wimsim.test").info("weighed", extra={"mass_kg": 7350.0, "axle_count": 2})
    (line,) = captured()
    assert line["mass_kg"] == 7350.0
    assert line["axle_count"] == 2


def test_an_unserialisable_extra_does_not_take_the_line_down(captured) -> None:
    get_logger("wimsim.test").info("odd", extra={"thing": object()})
    (line,) = captured()
    assert line["thing"].startswith("<object object at")


def test_an_exception_is_recorded_as_a_field(captured) -> None:
    log = get_logger("wimsim.test")
    try:
        raise ZeroDivisionError("boom")
    except ZeroDivisionError:
        log.exception("estimation failed")
    (line,) = captured()
    assert "ZeroDivisionError: boom" in line["exception"]
    assert line["message"] == "estimation failed"


def test_an_extra_cannot_overwrite_the_envelope(captured) -> None:
    """Otherwise a stray `level` in a debug call rewrites what the alerting rules read."""
    get_logger("wimsim.test").info("x", extra={"level": "CRITICAL"})
    (line,) = captured()
    assert line["level"] == "INFO"


# ------------------------------------------------------------------------------------------
# trace correlation
# ------------------------------------------------------------------------------------------


def test_trace_id_is_filled_from_the_active_span(captured) -> None:
    """The join that makes a trace and its logs one view. Requiring every call site to pass the
    trace id by hand would mean most of them eventually do not."""
    trace_sdk = pytest.importorskip("opentelemetry.sdk.trace")
    from wimsim.observability.tracing import Tracing

    tracing = Tracing(trace_sdk.TracerProvider().get_tracer("wimsim"))
    with tracing.span("detect") as span:
        get_logger("wimsim.test").info("detected")
        expected = format(span.get_span_context().trace_id, "032x")
    (line,) = captured()
    assert line["trace_id"] == expected


def test_an_explicitly_bound_trace_id_wins(captured) -> None:
    """Ingest replaying a stored payload knows the trace the pass belongs to even when it is not
    the trace it is currently in."""
    with bind(trace_id="a" * 32):
        get_logger("wimsim.test").info("replayed")
    (line,) = captured()
    assert line["trace_id"] == "a" * 32


# ------------------------------------------------------------------------------------------
# configuration
# ------------------------------------------------------------------------------------------


def test_configure_is_idempotent() -> None:
    """Double handlers mean double lines, and a duplicated error is a different incident count."""
    logger = logging.getLogger("wimsim")
    before = list(logger.handlers)
    try:
        logger.handlers.clear()
        configure_logging(station_id="ST-1")
        configure_logging(station_id="ST-1")
        assert len(logger.handlers) == 1
    finally:
        logger.handlers[:] = before


def test_configure_without_an_endpoint_ships_nothing(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("OTEL_EXPORTER_OTLP_ENDPOINT", raising=False)
    logger = logging.getLogger("wimsim")
    before = list(logger.handlers)
    try:
        logger.handlers.clear()
        configure_logging(station_id="ST-1")
        assert [type(h).__name__ for h in logger.handlers] == ["StreamHandler"]
    finally:
        logger.handlers[:] = before


def test_configure_binds_the_station_and_run_for_the_process(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """station_id and run_id are the same for every line a process ever emits; making each call
    site pass them would be noise that eventually goes wrong."""
    monkeypatch.delenv("OTEL_EXPORTER_OTLP_ENDPOINT", raising=False)
    logger = logging.getLogger("wimsim")
    before = list(logger.handlers)
    try:
        logger.handlers.clear()
        configure_logging(station_id="ST-1", run_id="r-9")
        ctx = log_context()
        assert ctx["station_id"] == "ST-1"
        assert ctx["run_id"] == "r-9"
    finally:
        logger.handlers[:] = before
        reset_context()


def test_configure_with_an_endpoint_adds_the_otlp_handler_once() -> None:
    """Push to the collector, as metrics and traces do -- a station behind a link that goes down
    cannot be scraped (the reason recorded in docker/prometheus/prometheus.yml)."""
    pytest.importorskip("opentelemetry.sdk._logs")
    logger = logging.getLogger("wimsim")
    before = list(logger.handlers)
    try:
        logger.handlers.clear()
        configure_logging(station_id="ST-1", endpoint="http://localhost:4317")
        configure_logging(station_id="ST-1", endpoint="http://localhost:4317")
        assert [type(h).__name__ for h in logger.handlers] == ["StreamHandler", "LoggingHandler"]
    finally:
        logger.handlers[:] = before
        reset_context()


def test_the_shipped_body_is_the_same_json_as_the_stream(monkeypatch: pytest.MonkeyPatch) -> None:
    """Loki and the console must not show different things; a discrepancy there is the sort of
    thing that is only discovered while debugging something else."""
    pytest.importorskip("opentelemetry.sdk._logs")
    logger = logging.getLogger("wimsim")
    before = list(logger.handlers)
    try:
        logger.handlers.clear()
        configure_logging(station_id="ST-1", endpoint="http://localhost:4317")
        stream, otlp = logger.handlers
        assert isinstance(otlp.formatter, JsonFormatter)
        assert type(otlp.formatter) is type(stream.formatter)
    finally:
        logger.handlers[:] = before
        reset_context()
