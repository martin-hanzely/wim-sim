"""Structured logging: one JSON object per line, joinable to everything else.

Buildspec section 9 names five fields that must appear on every line -- ``event_id``, ``trace_id``,
``station_id``, ``profile_id``, ``run_id`` -- and the reason is joins. A Loki query filtered by
``trace_id`` sits next to the Tempo trace with the same id; ``event_id`` pulls up every line about
one pass; ``run_id`` separates two runs of the same station in the same window. A field that is only
*sometimes* emitted cannot be filtered on with any confidence, because the filter silently drops the
lines that would have explained the problem. So the keys are always present and null when unset.

Three things follow from "logging must never be the thing that fails".

**Context is ambient, not threaded through call signatures.** ``station_id`` and ``run_id`` are the
same for every line a process emits and ``event_id`` is the same for every line about one pass;
passing them explicitly at each call site is noise that eventually goes wrong. A ``ContextVar``
holds them, ``bind()`` layers a scope on top, and the scope unwinds through exceptions -- which is
exactly when the next line's context matters most.

**``trace_id`` fills itself from the active span.** Requiring every call site to pass it by hand
would mean most of them eventually do not, and a log line with no trace id is a line that cannot be
joined to the pass it describes. An explicitly bound value still wins, because ingest replaying a
stored payload knows which trace the pass belongs to even when that is not the trace it is in.

**Nothing here can raise.** An unserialisable extra becomes its ``repr``, a second
``configure_logging`` does not double the handlers, and with no collector configured the lines still
come out on the stream -- structured, just not shipped.
"""

from __future__ import annotations

import json
import logging
import os
from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from datetime import UTC, datetime
from typing import IO, Any

__all__ = [
    "LOG_FIELDS",
    "JsonFormatter",
    "bind",
    "configure_logging",
    "get_logger",
    "log_context",
    "reset_context",
]

#: Buildspec section 9. Every line carries all of them, null when unknown.
LOG_FIELDS: tuple[str, ...] = ("event_id", "trace_id", "station_id", "profile_id", "run_id")

ROOT_LOGGER = "wimsim"

#: The envelope. An ``extra`` may not overwrite these -- a stray ``level`` in a debug call would
#: rewrite what the alerting rules read.
_ENVELOPE = frozenset({"ts", "level", "logger", "message", "exception", *LOG_FIELDS})

_CONTEXT: ContextVar[dict[str, str | None]] = ContextVar("wimsim_log_context")


def log_context() -> dict[str, str | None]:
    """What is currently bound, with every field present."""
    current = _CONTEXT.get(None) or {}
    return {field: current.get(field) for field in LOG_FIELDS}


def reset_context() -> None:
    """Clear the process-wide binding. Used between runs, and by tests."""
    _CONTEXT.set(dict.fromkeys(LOG_FIELDS))


@contextmanager
def bind(**fields: str | None) -> Iterator[None]:
    """Layer fields onto the log context for the duration of the block."""
    unknown = [key for key in fields if key not in LOG_FIELDS]
    if unknown:
        raise KeyError(
            f"{unknown} are not log context fields. The five in LOG_FIELDS are a contract with the "
            "dashboards; anything else belongs in a per-line `extra`."
        )
    token = _CONTEXT.set({**log_context(), **fields})
    try:
        yield
    finally:
        _CONTEXT.reset(token)


def _bind_process(**fields: str | None) -> None:
    """Set fields for the rest of the process, with no scope to unwind."""
    _CONTEXT.set({**log_context(), **fields})


# ----------------------------------------------------------------------------------------------
# The formatter
# ----------------------------------------------------------------------------------------------

#: Everything ``logging`` puts on a record itself. Anything else came from an ``extra``.
_RESERVED = frozenset(logging.LogRecord("", 0, "", 0, "", None, None).__dict__) | {
    "message",
    "asctime",
    "taskName",
}


def _stringify(value: Any) -> Any:
    """JSON if it can be, ``repr`` if it cannot. A log line is not worth an exception."""
    if value is None or isinstance(value, bool | int | float | str):
        return value
    try:
        json.dumps(value)
    except (TypeError, ValueError):
        return repr(value)
    return value


class JsonFormatter(logging.Formatter):
    """One JSON object per line."""

    def format(self, record: logging.LogRecord) -> str:
        line: dict[str, Any] = {
            "ts": datetime.fromtimestamp(record.created, tz=UTC)
            .isoformat(timespec="microseconds")
            .replace("+00:00", "Z"),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }

        # Read off the *record*, not off the contextvar. The context is snapshotted when the record
        # is created (see ``_ContextLogger``) because formatting happens later -- in another thread
        # for a batching handler -- and by then the scope the line belongs to has usually unwound.
        line.update({field: getattr(record, field, None) for field in LOG_FIELDS})

        for key, value in record.__dict__.items():
            if key in _RESERVED or key in _ENVELOPE or key.startswith("_"):
                continue
            line[key] = _stringify(value)

        if record.exc_info:
            line["exception"] = self.formatException(record.exc_info)

        return json.dumps(line, default=repr)


def _active_trace_id() -> str | None:
    from wimsim.observability.tracing import active_trace_id

    return active_trace_id()


# ----------------------------------------------------------------------------------------------
# Wiring
# ----------------------------------------------------------------------------------------------


class _ContextLogger(logging.LoggerAdapter):
    """Stamps the current log context onto every record as it is created.

    An adapter rather than a ``Filter`` because a filter installed on the ``wimsim`` logger would
    not see records from ``wimsim.edge.detect`` -- during propagation only *handlers* run, not the
    ancestors' filters -- and installing one per child logger is the kind of bookkeeping that is
    eventually forgotten for exactly one module.
    """

    def process(self, msg, kwargs):
        context = log_context()
        if context["trace_id"] is None:
            context["trace_id"] = _active_trace_id()
        # Caller extras first: a bound context field is the more specific statement about which
        # pass a line belongs to, and must not be overwritten by a stale value passed by hand.
        kwargs["extra"] = {**kwargs.get("extra", {}), **context}
        return msg, kwargs


def get_logger(name: str) -> _ContextLogger:
    """A logger under the ``wimsim`` root, so one configuration reaches all of them."""
    if not name.startswith(ROOT_LOGGER):
        name = f"{ROOT_LOGGER}.{name}"
    return _ContextLogger(logging.getLogger(name), {})


def _otlp_endpoint() -> str | None:
    if os.environ.get("OTEL_SDK_DISABLED", "").strip().lower() == "true":
        return None
    return os.environ.get("OTEL_EXPORTER_OTLP_ENDPOINT", "").strip() or None


def configure_logging(
    *,
    station_id: str,
    run_id: str | None = None,
    level: int = logging.INFO,
    stream: IO[str] | None = None,
    endpoint: str | None = None,
) -> logging.Logger:
    """Configure the ``wimsim`` logger tree. Safe to call more than once.

    The stream handler is always installed: a station with no link still has to produce readable
    lines, and they are structured whether or not anything is collecting them. The OTLP handler is
    added only when a collector is configured, and ships to the same collector as traces and
    metrics -- push rather than scrape, for the reason recorded in ``docker/prometheus``.
    """
    logger = logging.getLogger(ROOT_LOGGER)
    logger.setLevel(level)
    #: A station's logs are its own; letting them also reach the root logger's handlers would
    #: duplicate every line under pytest and under any host application.
    logger.propagate = False

    _bind_process(station_id=station_id, run_id=run_id)

    if not any(getattr(h, "_wimsim", False) for h in logger.handlers):
        handler = logging.StreamHandler(stream)
        handler.setFormatter(JsonFormatter())
        handler._wimsim = True  # type: ignore[attr-defined]
        logger.addHandler(handler)

    target = endpoint if endpoint is not None else _otlp_endpoint()
    if target and not any(getattr(h, "_wimsim_otlp", False) for h in logger.handlers):
        logger.addHandler(_otlp_handler(target, station_id=station_id, run_id=run_id, level=level))

    return logger


def _otlp_handler(endpoint: str, *, station_id: str, run_id: str | None, level: int):
    """The OTel logging bridge. Imported here so the SDK is optional.

    ``LoggingHandler`` is deprecated in favour of ``opentelemetry-instrumentation-logging``, which
    is a new dependency for a handler that does the same job. Not worth it while the SDK one still
    works; revisit if it is removed rather than merely deprecated.
    """
    from opentelemetry.exporter.otlp.proto.grpc._log_exporter import OTLPLogExporter
    from opentelemetry.sdk._logs import LoggerProvider, LoggingHandler
    from opentelemetry.sdk._logs.export import BatchLogRecordProcessor

    from wimsim.observability.resource import build_resource

    provider = LoggerProvider(resource=build_resource(station_id=station_id, run_id=run_id))
    provider.add_log_record_processor(
        BatchLogRecordProcessor(OTLPLogExporter(endpoint=endpoint, insecure=True))
    )
    handler = LoggingHandler(level=level, logger_provider=provider)
    handler.setFormatter(JsonFormatter())
    handler._wimsim_otlp = True  # type: ignore[attr-defined]
    return handler
