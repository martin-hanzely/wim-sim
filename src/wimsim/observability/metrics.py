"""The metric registry.

Buildspec section 9 lists twenty-six metrics by name. Dashboards refer to them by string, so a name
that exists in one place and not the other is a panel that renders an empty graph and says nothing
about why. ``REGISTRY`` is therefore the single declaration of the set, and every emission goes
through it: an unknown name raises, the wrong instrument kind raises, and a metric declared to carry
a label raises if the label is missing. All of that fails at the call site during a test run rather
than as a missing series a month later.

Three design decisions worth stating.

**The default is a no-op.** No collector, no exporter, no background thread, no dependency on
OpenTelemetry being importable at all. The edge is meant to run on a station whose link goes down
(scenario S5) and the test suite is meant to run without docker; neither can require a collector.
``build_metrics`` reads the standard ``OTEL_EXPORTER_OTLP_ENDPOINT`` and ``OTEL_SDK_DISABLED``
environment variables rather than inventing a config surface, so the usual OTel knobs work.

**Validation happens on the null path too.** A registry that only checked names when a collector was
attached would move every typo into production. ``Metrics`` validates first and dispatches second.

**Truth metrics are refused unless the caller says it is the truth exporter.** ``test_truth_isolation``
enforces principle 1 across imports, but a metric named ``wim_mass_true`` published by the edge would
put ground truth into the same Prometheus a controller could query -- the leak would be through the
network rather than the import graph. So the permission is explicit, defaults to off, and the truth
exporter in ``wimsim.experiments`` is the only caller that turns it on.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import Literal, Protocol

__all__ = [
    "REGISTRY",
    "MetricDef",
    "MetricKind",
    "MetricRecord",
    "Metrics",
    "NullSink",
    "OtelSink",
    "RecordingSink",
    "build_metrics",
]

MetricKind = Literal["counter", "gauge", "histogram"]
MetricGroup = Literal["flow", "calibration", "quality", "truth"]


@dataclass(frozen=True, slots=True)
class MetricDef:
    """One metric, declared once."""

    name: str
    kind: MetricKind
    unit: str
    description: str
    group: MetricGroup
    required_attributes: tuple[str, ...] = ()


def _defs(*rows: MetricDef) -> dict[str, MetricDef]:
    return {row.name: row for row in rows}


# ----------------------------------------------------------------------------------------------
# The set. Grouped and ordered as the buildspec lists them, so the two can be diffed by eye.
# ----------------------------------------------------------------------------------------------

REGISTRY: dict[str, MetricDef] = _defs(
    # -- flow ----------------------------------------------------------------------------------
    MetricDef(
        "wim_samples_acquired_total",
        "counter",
        "1",
        "Samples pulled from the source adapter.",
        "flow",
    ),
    MetricDef(
        "wim_sample_gaps_total",
        "counter",
        "1",
        "Discontinuities in the sample clock, in samples missing.",
        "flow",
    ),
    MetricDef(
        "wim_events_detected_total",
        "counter",
        "1",
        "Vehicle passes the detector accepted.",
        "flow",
    ),
    MetricDef(
        "wim_publish_latency_ms",
        "histogram",
        "ms",
        "Enqueue to broker acknowledgement.",
        "flow",
    ),
    MetricDef(
        "wim_buffer_depth",
        "gauge",
        "1",
        "Payloads spooled and not yet acknowledged.",
        "flow",
    ),
    MetricDef(
        "wim_publish_failures_total",
        "counter",
        "1",
        "Publish attempts that did not acknowledge.",
        "flow",
    ),
    MetricDef(
        "wim_dlq_total",
        "counter",
        "1",
        "Payloads dead-lettered at ingest, by rejection reason.",
        "flow",
        required_attributes=("reason",),
    ),
    MetricDef(
        "wim_ingest_lag_ms",
        "histogram",
        "ms",
        "Station timestamp to ingest wall clock. Includes clock skew, deliberately.",
        "flow",
    ),
    MetricDef(
        "wim_db_write_latency_ms",
        "histogram",
        "ms",
        "Duration of one upsert batch.",
        "flow",
    ),
    # -- calibration loop ----------------------------------------------------------------------
    # The estimate and the truth overlay are both *sensor-side* -- sensor units per kg, and sensor
    # units -- so the calibration dashboard draws them on one axis with neither side inverting. The
    # convention was settled in calibration/base.py; the estimator fits in the prediction direction
    # and reports through EstimatorState.sensor_gain/sensor_bias. A truth gain of 2e-4 drawn against
    # a prediction gain of 5000 is a panel that looks broken rather than wrong, which is the kind of
    # mistake that survives review.
    MetricDef(
        "wim_cal_gain_estimate",
        "gauge",
        "{sensor}/kg",
        "Estimated gain, sensor-side: sensor units per kg. Comparable with wim_cal_gain_true.",
        "calibration",
    ),
    MetricDef(
        "wim_cal_bias_estimate",
        "gauge",
        "{sensor}",
        "Estimated zero line, sensor units. Comparable with wim_cal_bias_true.",
        "calibration",
    ),
    MetricDef(
        "wim_cal_temp_coeff_estimate",
        "gauge",
        "1/Cel",
        "Estimated relative temperature coefficient.",
        "calibration",
    ),
    MetricDef(
        "wim_cal_covariance_trace",
        "gauge",
        "1",
        "Trace of the estimator state covariance; convergence made visible.",
        "calibration",
    ),
    MetricDef(
        "wim_cal_update_count",
        "gauge",
        "1",
        "Observations folded into the current state. A gauge, not a counter: it resets when a "
        "profile is replaced, and a counter that goes backwards is a lie.",
        "calibration",
    ),
    MetricDef(
        "wim_cal_residual",
        "gauge",
        "kg",
        "Most recent prediction residual, signed.",
        "calibration",
    ),
    MetricDef(
        "wim_drift_statistic",
        "gauge",
        "1",
        "Current detector statistic, one series per detector.",
        "calibration",
        required_attributes=("detector",),
    ),
    MetricDef(
        "wim_recalibration_triggered_total",
        "counter",
        "1",
        "Recalibrations the controller decided to perform.",
        "calibration",
        required_attributes=("reason",),
    ),
    MetricDef(
        "wim_cal_state",
        "gauge",
        "1",
        "One-hot over the MAPE-K controller states; 1 for the active one.",
        "calibration",
        required_attributes=("state",),
    ),
    MetricDef(
        "wim_cal_profile_version",
        "gauge",
        "1",
        "Monotonic version of the active calibration profile.",
        "calibration",
    ),
    # -- quality -------------------------------------------------------------------------------
    #
    # Absolute error, relative error and coverage all need a reference mass, so they are emitted
    # by the scoring layer and not by the edge. Interval width does not, and is emitted by the
    # edge. That split is a consequence of principle 1 rather than a choice.
    MetricDef(
        "wim_mass_abs_error",
        "histogram",
        "kg",
        "Absolute error against a reference mass. Scoring layer only.",
        "quality",
    ),
    MetricDef(
        "wim_mass_rel_error",
        "histogram",
        "1",
        "Relative error against a reference mass. Scoring layer only.",
        "quality",
    ),
    MetricDef(
        "wim_interval_width",
        "histogram",
        "kg",
        "Width of the reported confidence interval. Needs no reference.",
        "quality",
    ),
    MetricDef(
        "wim_coverage_rolling",
        "gauge",
        "1",
        "Rolling fraction of intervals containing the reference mass.",
        "quality",
    ),
    # -- truth overlay (synthetic only) --------------------------------------------------------
    MetricDef(
        "wim_cal_gain_true",
        "gauge",
        "{sensor}/kg",
        "Plant gain k, from the truth log. Never emitted by the estimator path.",
        "truth",
    ),
    MetricDef(
        "wim_cal_bias_true",
        "gauge",
        "{sensor}",
        "Plant zero line q, from the truth log. Never emitted by the estimator path.",
        "truth",
    ),
    MetricDef(
        "wim_temperature_true",
        "gauge",
        "Cel",
        "True sensor temperature, distinct from the probe reading.",
        "truth",
    ),
    MetricDef(
        "wim_mass_true",
        "gauge",
        "kg",
        "True vehicle mass, from the truth log.",
        "truth",
    ),
)


# ----------------------------------------------------------------------------------------------
# Sinks
# ----------------------------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class MetricRecord:
    name: str
    kind: MetricKind
    value: float
    attributes: dict[str, str]


class MetricSink(Protocol):
    """Where a validated measurement goes. Deliberately narrow."""

    def emit(self, record: MetricRecord) -> None: ...


@dataclass
class NullSink:
    """Discards. The default, and the entire offline story.

    It counts, because "are we emitting anything at all" is a question worth being able to answer
    without a collector, and a single integer is cheap enough to leave switched on.
    """

    count: int = 0

    def emit(self, record: MetricRecord) -> None:
        self.count += 1


@dataclass
class RecordingSink:
    """Keeps everything, in order. For tests, and for the offline experiment runner."""

    records: list[MetricRecord] = field(default_factory=list)

    def emit(self, record: MetricRecord) -> None:
        self.records.append(record)

    @property
    def count(self) -> int:
        return len(self.records)

    def values(self, name: str) -> list[float]:
        return [r.value for r in self.records if r.name == name]


class OtelSink:
    """Bridges to an OpenTelemetry meter.

    Instruments are created lazily and cached, because the OTel API creates a new instrument object
    on every call and duplicate instrument registration is a warning on some SDK versions and a
    silent second series on others.
    """

    def __init__(self, meter) -> None:
        self._meter = meter
        self._instruments: dict[str, object] = {}

    def _instrument(self, mdef: MetricDef):
        inst = self._instruments.get(mdef.name)
        if inst is not None:
            return inst
        if mdef.kind == "counter":
            inst = self._meter.create_counter(
                mdef.name, unit=mdef.unit, description=mdef.description
            )
        elif mdef.kind == "gauge":
            inst = self._meter.create_gauge(mdef.name, unit=mdef.unit, description=mdef.description)
        else:
            inst = self._meter.create_histogram(
                mdef.name, unit=mdef.unit, description=mdef.description
            )
        self._instruments[mdef.name] = inst
        return inst

    def emit(self, record: MetricRecord) -> None:
        mdef = REGISTRY[record.name]
        inst = self._instrument(mdef)
        if mdef.kind == "counter":
            inst.add(record.value, record.attributes)
        elif mdef.kind == "gauge":
            inst.set(record.value, record.attributes)
        else:
            inst.record(record.value, record.attributes)


# ----------------------------------------------------------------------------------------------
# The facade
# ----------------------------------------------------------------------------------------------

_TRUTH_LABEL = {"source": "truth"}


class Metrics:
    """Validate, then dispatch. The only way a metric leaves this process."""

    def __init__(
        self,
        sink: MetricSink,
        *,
        truth_allowed: bool = False,
        attributes: dict[str, str] | None = None,
    ) -> None:
        self.sink = sink
        self.truth_allowed = truth_allowed
        self._attributes = dict(attributes or {})

    @property
    def enabled(self) -> bool:
        """False when nothing is being exported. Callers may skip expensive derivations."""
        return not isinstance(self.sink, NullSink)

    def bind(self, **attributes: str) -> Metrics:
        """A child carrying extra attributes on every emission. The parent is untouched."""
        return Metrics(
            self.sink,
            truth_allowed=self.truth_allowed,
            attributes={**self._attributes, **{k: str(v) for k, v in attributes.items()}},
        )

    # -- the three verbs ---------------------------------------------------------------------

    def add(self, name: str, value: float, **attributes: str) -> None:
        """Increment a counter."""
        mdef = self._check(name, "counter", attributes)
        if value < 0:
            raise ValueError(f"{name} is a counter and must be monotonic; got {value}")
        self._emit(mdef, value, attributes)

    def set(self, name: str, value: float, **attributes: str) -> None:
        """Record the current value of a gauge."""
        mdef = self._check(name, "gauge", attributes)
        self._emit(mdef, value, attributes)

    def observe(self, name: str, value: float, **attributes: str) -> None:
        """Record one observation into a histogram."""
        mdef = self._check(name, "histogram", attributes)
        self._emit(mdef, value, attributes)

    # -- internals ---------------------------------------------------------------------------

    def _check(self, name: str, kind: MetricKind, attributes: dict[str, str]) -> MetricDef:
        try:
            mdef = REGISTRY[name]
        except KeyError:
            raise KeyError(
                f"{name!r} is not a declared metric. The set is fixed by buildspec section 9; "
                "add it to REGISTRY and to the dashboard that needs it, in that order."
            ) from None

        if mdef.kind != kind:
            verb = {"counter": "add", "gauge": "set", "histogram": "observe"}[mdef.kind]
            raise TypeError(f"{name} is a {mdef.kind}, not a {kind}; use {verb}()")

        if mdef.group == "truth":
            if not self.truth_allowed:
                raise PermissionError(
                    f"{name} carries ground truth and this registry is on the estimator path. "
                    "Only the truth exporter in wimsim.experiments may emit it (principle 1)."
                )
            if "source" in attributes or "source" in self._attributes:
                raise ValueError(
                    f"{name} is stamped source=truth by the registry; overriding the label would "
                    "put a truth series where dashboards expect an estimate."
                )

        missing = [a for a in mdef.required_attributes if a not in attributes]
        if missing:
            raise ValueError(
                f"{name} requires the attribute(s) {missing}; without them the series collide"
            )
        return mdef

    def _emit(self, mdef: MetricDef, value: float, attributes: dict[str, str]) -> None:
        merged = {**self._attributes, **{k: str(v) for k, v in attributes.items()}}
        if mdef.group == "truth":
            merged.update(_TRUTH_LABEL)
        self.sink.emit(MetricRecord(mdef.name, mdef.kind, float(value), merged))


# ----------------------------------------------------------------------------------------------
# Construction
# ----------------------------------------------------------------------------------------------


def _otlp_endpoint() -> str | None:
    if os.environ.get("OTEL_SDK_DISABLED", "").strip().lower() == "true":
        return None
    endpoint = os.environ.get("OTEL_EXPORTER_OTLP_ENDPOINT", "").strip()
    return endpoint or None


def build_metrics(
    *,
    station_id: str,
    run_id: str | None = None,
    truth_allowed: bool = False,
    endpoint: str | None = None,
    export_interval_ms: int = 5000,
) -> Metrics:
    """A ``Metrics`` wired to a collector if one is configured, and to nothing if not.

    ``endpoint`` overrides the environment. Passing it explicitly is how the CLI honours a
    ``--otlp-endpoint`` flag without mutating ``os.environ``.
    """
    target = endpoint if endpoint is not None else _otlp_endpoint()
    attributes = {"station_id": station_id}
    if run_id:
        attributes["run_id"] = run_id

    if not target:
        return Metrics(NullSink(), truth_allowed=truth_allowed, attributes=attributes)

    sink = _otel_sink(target, station_id=station_id, run_id=run_id, interval_ms=export_interval_ms)
    return Metrics(sink, truth_allowed=truth_allowed, attributes=attributes)


def _otel_sink(
    endpoint: str, *, station_id: str, run_id: str | None, interval_ms: int
) -> MetricSink:
    """Build the OTel meter provider. Imported here so the SDK is optional at import time."""
    from opentelemetry.exporter.otlp.proto.grpc.metric_exporter import OTLPMetricExporter
    from opentelemetry.sdk.metrics import MeterProvider
    from opentelemetry.sdk.metrics.export import PeriodicExportingMetricReader

    from wimsim.observability.resource import build_resource

    reader = PeriodicExportingMetricReader(
        OTLPMetricExporter(endpoint=endpoint, insecure=True),
        export_interval_millis=interval_ms,
    )
    provider = MeterProvider(
        resource=build_resource(station_id=station_id, run_id=run_id),
        metric_readers=[reader],
    )
    return OtelSink(provider.get_meter("wimsim"))
