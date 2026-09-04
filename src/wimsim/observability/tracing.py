"""Spans across the seven stages of a pass, and the trace context that crosses the broker.

Buildspec section 9 asks for one thing that is easy to state and easy to get subtly wrong: select a
vehicle pass in Tempo and see ``acquire -> preprocess -> detect -> estimate -> publish -> ingest ->
persist`` as a single trace with per-stage latency. Within the edge process that is ordinary nested
spans. Across the broker it is not, because MQTT 3.1.1 has no headers, so the context travels inside
the payload -- as the buildspec says, "there is no header mechanism to rely on".

**Two fields, one context.** The payload carries both ``trace_id`` (32 hex characters) and
``traceparent`` (the W3C string). They are redundant on purpose and stamped together so they cannot
disagree. ``trace_id`` is the queryable one: it is a database column, it is what a Grafana data link
puts in a URL, and it is what every log line carries. ``traceparent`` is the functional one: a trace
id alone cannot re-parent a span, because a child needs its parent's *span* id too, and without it
the ingest span would float as a second root in the same trace.

**A malformed context is never fatal.** The measurement is worth more than its trace. Anything that
does not parse is dropped and the stage starts a fresh root span.

**Nothing here is required.** With no collector configured the tracer is ``None``, ``span()`` yields
an object that accepts the same calls and discards them, and the cost is one attribute lookup per
stage. Stage names are still validated, so a typo fails in the test suite rather than becoming a
span nobody ever queries for.
"""

from __future__ import annotations

import os
from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any

__all__ = [
    "STAGES",
    "Tracing",
    "build_tracing",
    "format_traceparent",
    "parse_traceparent",
    "trace_id_of",
]

STAGES: tuple[str, ...] = (
    "acquire",
    "preprocess",
    "detect",
    "estimate",
    "publish",
    "ingest",
    "persist",
)

_TRACEPARENT_VERSION = "00"
_INVALID_TRACE_ID = "0" * 32
_INVALID_SPAN_ID = "0" * 16


# ----------------------------------------------------------------------------------------------
# W3C traceparent, by hand
# ----------------------------------------------------------------------------------------------
#
# Written out rather than taken from the propagators API because it is six lines, because the
# validity rules (all-zero ids are invalid) are the part that matters and are easy to check here,
# and because it keeps this module importable with no OpenTelemetry installed.


def format_traceparent(trace_id: int, span_id: int, flags: int) -> str:
    return f"{_TRACEPARENT_VERSION}-{trace_id:032x}-{span_id:016x}-{flags:02x}"


def parse_traceparent(value: str | None) -> tuple[str, str, int] | None:
    """``(trace_id, span_id, flags)`` as hex strings, or None if the header is unusable."""
    if not value:
        return None
    parts = value.strip().split("-")
    if len(parts) != 4:
        return None
    version, trace_id, span_id, flags = parts
    if version != _TRACEPARENT_VERSION or len(trace_id) != 32 or len(span_id) != 16:
        return None
    if trace_id == _INVALID_TRACE_ID or span_id == _INVALID_SPAN_ID:
        return None
    try:
        return trace_id.lower(), span_id.lower(), int(flags, 16)
    except ValueError:
        return None


def trace_id_of(payload: Any) -> str | None:
    """The trace id off a payload dict or a pydantic model, whichever the caller happens to hold."""
    if payload is None:
        return None
    if isinstance(payload, dict):
        return payload.get("trace_id")
    return getattr(payload, "trace_id", None)


# ----------------------------------------------------------------------------------------------
# The disabled span
# ----------------------------------------------------------------------------------------------


class _NullSpan:
    """Accepts what a span accepts, keeps none of it.

    Its whole reason for existing is that call sites can write ``span.set_attribute(...)``
    unconditionally. The alternative -- yielding None -- puts an ``if span is not None`` at every
    instrumentation point, and those are exactly the lines nobody keeps correct.
    """

    __slots__ = ()

    def set_attribute(self, key: str, value: Any) -> None: ...
    def set_attributes(self, attributes: dict[str, Any]) -> None: ...
    def add_event(self, name: str, attributes: dict[str, Any] | None = None) -> None: ...
    def record_exception(self, exc: BaseException) -> None: ...
    def set_status(self, *args: Any, **kwargs: Any) -> None: ...
    def is_recording(self) -> bool:
        return False

    def get_span_context(self) -> None:
        return None


_NULL_SPAN = _NullSpan()


# ----------------------------------------------------------------------------------------------
# Tracing
# ----------------------------------------------------------------------------------------------


class Tracing:
    """A tracer, or the absence of one, behind a single interface."""

    def __init__(self, tracer: Any | None) -> None:
        self._tracer = tracer

    @property
    def enabled(self) -> bool:
        return self._tracer is not None

    # -- spans -------------------------------------------------------------------------------

    @contextmanager
    def span(self, stage: str, **attributes: Any) -> Iterator[Any]:
        """Open one stage span, nested under whatever is already active."""
        self._check(stage)
        if self._tracer is None:
            yield _NULL_SPAN
            return
        with self._tracer.start_as_current_span(stage) as span:
            for key, value in attributes.items():
                if value is not None:
                    span.set_attribute(key, value)
            yield span

    @contextmanager
    def continue_from(self, payload: Any, stage: str, **attributes: Any) -> Iterator[Any]:
        """Open a stage span parented to the context carried in ``payload``.

        An absent or malformed ``traceparent`` yields a root span rather than an error: a pass whose
        trace was lost is still a pass.
        """
        self._check(stage)
        if self._tracer is None:
            yield _NULL_SPAN
            return

        context = self._context_from(payload)
        with self._tracer.start_as_current_span(stage, context=context) as span:
            for key, value in attributes.items():
                if value is not None:
                    span.set_attribute(key, value)
            yield span

    # -- context out -------------------------------------------------------------------------

    def current_trace_id(self) -> str | None:
        """32 hex characters, or None when nothing is being traced."""
        ctx = self._current_span_context()
        return None if ctx is None else format(ctx.trace_id, "032x")

    def current_traceparent(self) -> str | None:
        ctx = self._current_span_context()
        if ctx is None:
            return None
        return format_traceparent(ctx.trace_id, ctx.span_id, int(ctx.trace_flags))

    def stamp(self, payload: dict) -> dict:
        """A copy of ``payload`` carrying the active context. Unchanged when nothing is active."""
        traceparent = self.current_traceparent()
        if traceparent is None:
            return payload
        return {**payload, "trace_id": self.current_trace_id(), "traceparent": traceparent}

    # -- internals ---------------------------------------------------------------------------

    @staticmethod
    def _check(stage: str) -> None:
        if stage not in STAGES:
            raise KeyError(
                f"{stage!r} is not one of the pass lifecycle stages {STAGES}. Dashboards and Tempo "
                "queries name them literally; add it here first if a stage is genuinely new."
            )

    def _current_span_context(self):
        if self._tracer is None:
            return None
        from opentelemetry import trace

        ctx = trace.get_current_span().get_span_context()
        return ctx if ctx.is_valid else None

    def _context_from(self, payload: Any):
        """A parent context from the payload's traceparent, or None for a fresh root."""
        raw = payload.get("traceparent") if isinstance(payload, dict) else None
        if raw is None:
            raw = getattr(payload, "traceparent", None)
        parsed = parse_traceparent(raw)
        if parsed is None:
            return None

        from opentelemetry import trace

        trace_id, span_id, flags = parsed
        span_context = trace.SpanContext(
            trace_id=int(trace_id, 16),
            span_id=int(span_id, 16),
            is_remote=True,
            trace_flags=trace.TraceFlags(flags),
        )
        return trace.set_span_in_context(trace.NonRecordingSpan(span_context))


# ----------------------------------------------------------------------------------------------
# Construction
# ----------------------------------------------------------------------------------------------


def _otlp_endpoint() -> str | None:
    if os.environ.get("OTEL_SDK_DISABLED", "").strip().lower() == "true":
        return None
    return os.environ.get("OTEL_EXPORTER_OTLP_ENDPOINT", "").strip() or None


def build_tracing(
    *,
    station_id: str,
    run_id: str | None = None,
    service_name: str | None = None,
    endpoint: str | None = None,
) -> Tracing:
    """A ``Tracing`` wired to a collector if one is configured, and to nothing if not."""
    target = endpoint if endpoint is not None else _otlp_endpoint()
    if not target:
        return Tracing(None)

    from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter
    from opentelemetry.sdk.trace import TracerProvider
    from opentelemetry.sdk.trace.export import BatchSpanProcessor

    from wimsim.observability.resource import SERVICE_NAME, build_resource

    provider = TracerProvider(
        resource=build_resource(
            station_id=station_id, run_id=run_id, service_name=service_name or SERVICE_NAME
        )
    )
    provider.add_span_processor(
        BatchSpanProcessor(OTLPSpanExporter(endpoint=target, insecure=True))
    )
    return Tracing(provider.get_tracer("wimsim"))
