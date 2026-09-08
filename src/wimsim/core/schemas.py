"""Event schemas -- the wire contract.

These payloads are what the edge publishes, what ingest validates, what the database stores and
what a paper eventually cites. Everything downstream of the pipeline is written against them, so
they are versioned (``schema_version``, semantic) and exported as JSON Schema for consumers that
are not Python.

Four rules the models enforce rather than document:

1. **``event_id`` is derived, never accepted.** It is a UUIDv5 of station, sensor and ``ts_start``
   -- and of nothing else. Two runs that detect the same crossing agree on the id even if they
   estimate different masses, which is exactly what makes the phase-3 upsert idempotent and what
   lets ``recompute --from <ts> --profile <id>`` update history in place instead of duplicating it.
2. **Provenance is mandatory on anything carrying a number a paper might quote.** A
   ``measurement.event`` will not validate without its config hash, seed and schema version, so an
   unreproducible event cannot be emitted (principle 3).
3. **Unknown fields are rejected.** A producer that has drifted from the contract fails loudly at
   the boundary instead of quietly dropping a field that a consumer needed.
4. **Fields added after 1.0.0 are optional.** Otherwise every schema bump makes existing data
   unreadable, and buildspec section 11 asks for old payloads to keep validating.

Timestamps are integer microseconds since the Unix epoch, UTC, everywhere. Never floats: a float64
holding seconds-since-epoch cannot represent present-day microseconds exactly, and an ``event_id``
derived from a timestamp that drifts in the last digit is not an id at all.
"""

from __future__ import annotations

import uuid
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from wimsim import SCHEMA_VERSION

__all__ = [
    "EVENT_NAMESPACE",
    "TOPIC_MODELS",
    "CalibrationBlock",
    "CalibrationDriftDetected",
    "CalibrationState",
    "ControllerState",
    "MeasurementEvent",
    "MeasurementSample",
    "PreprocessingBlock",
    "ProfileActivated",
    "ProvenanceBlock",
    "QualityFlag",
    "SystemIncident",
    "SystemMetric",
    "event_id_for",
    "exported_json_schemas",
]

#: Fixed for the lifetime of the project. Changing it renumbers every event ever emitted.
EVENT_NAMESPACE = uuid.UUID("1c9d8e7f-3a2b-5c4d-8e6f-0a1b2c3d4e5f")

SEMVER = r"^\d+\.\d+\.\d+$"

#: W3C Trace Context, version 00: ``00-<32 hex trace id>-<16 hex span id>-<2 hex flags>``.
#: The specification also declares all-zero ids invalid, which is checked in a validator rather
#: than here: pydantic-core's regex engine has no look-ahead.
TRACEPARENT = r"^00-[0-9a-f]{32}-[0-9a-f]{16}-[0-9a-f]{2}$"

QualityFlag = Literal["ok", "degraded", "suspect"]

#: The MAPE-K controller's states (buildspec section 6). Declared here rather than in
#: ``calibration/`` so that a consumer can interpret a ``calibration.state`` payload without
#: importing the estimator package.
ControllerState = Literal["MONITORING", "DRIFT_SUSPECTED", "RECALIBRATING", "VERIFYING", "DEGRADED"]


def event_id_for(station_id: str, sensor_id: str, ts_start_us: int) -> str:
    """Deterministic event id.

    Depends on the identity of the crossing and nothing else -- not on the mass, not on the
    calibration profile, not on when it was processed. Re-deriving an event under a different
    profile therefore produces the same id, which is what makes replay idempotent.
    """
    return str(uuid.uuid5(EVENT_NAMESPACE, f"{station_id}|{sensor_id}|{int(ts_start_us)}"))


class _Payload(BaseModel):
    """Common envelope. Every topic carries a schema version, a station and a timestamp."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: str = Field(
        SCHEMA_VERSION,
        pattern=SEMVER,
        description="Semantic version of this payload's shape. Older values are accepted.",
    )
    station_id: str
    trace_id: str | None = Field(
        None,
        description="OpenTelemetry trace id, propagated inside the payload because MQTT has no "
        "header mechanism to rely on (buildspec section 9). This is the queryable form: a database "
        "column, a Grafana data link, a field on every log line.",
    )
    traceparent: str | None = Field(
        None,
        pattern=TRACEPARENT,
        description="The full W3C trace context. Redundant with trace_id and stamped alongside it, "
        "because a trace id alone cannot re-parent a span -- a child needs its parent's span id "
        "too, and without it the ingest span floats as a second root in the same trace.",
    )

    @field_validator("traceparent")
    @classmethod
    def _reject_all_zero_ids(cls, value: str | None) -> str | None:
        """W3C declares an all-zero trace or span id invalid. Refuse it here rather than store a
        payload claiming a context that cannot be followed."""
        if value is None:
            return None
        _, trace_id, span_id, _ = value.split("-")
        if trace_id == "0" * 32 or span_id == "0" * 16:
            raise ValueError(f"traceparent carries an all-zero id, which W3C forbids: {value}")
        return value


# --------------------------------------------------------------------------------------------
# Reusable blocks
# --------------------------------------------------------------------------------------------


class ProvenanceBlock(BaseModel):
    """Principle 3, in a form that travels with the number."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    config_hash: str = Field(..., description="SHA-256 of the canonical resolved run config.")
    seed: int
    mode: Literal["synthetic", "replay", "serial"] = "synthetic"
    git_commit: str | None = Field(None, description="None when not run from a git checkout.")
    git_dirty: bool = Field(
        True,
        description="True means the commit does not identify the code that ran. Treat such events "
        "as non-citable.",
    )
    run_id: str | None = None


class CalibrationBlock(BaseModel):
    """The estimator state that produced a mass, at the moment it produced it."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    profile_id: str
    estimator: str = Field(..., description="e.g. static_affine, rls, kalman.")
    gain: float = Field(..., description="Sensor units per kg.")
    bias: float = Field(..., description="Zero line, sensor units.")
    temp_coeff: float = Field(0.0, description="Relative temperature coefficient, 1/degC.")
    state_hash: str = Field(..., description="Hash of the full serialised estimator state.")
    update_count: int = Field(0, ge=0)
    covariance_trace: float | None = Field(
        None,
        description="Trace of the state covariance. Present only for estimators that have one, "
        "which is why it is optional rather than zero.",
    )


class PreprocessingBlock(BaseModel):
    """What was done to the signal before the feature was taken."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    filter: str = Field(..., description="e.g. none, moving_average, butterworth, median.")
    cutoff_hz: float | None = None
    order: int | None = None
    zero_window_s: float | None = None


# --------------------------------------------------------------------------------------------
# measurement.*
# --------------------------------------------------------------------------------------------


class MeasurementSample(_Payload):
    """One reading. High volume; published only when sample streaming is enabled."""

    topic: Literal["measurement.sample"] = "measurement.sample"
    sensor_id: str
    ts: int = Field(..., description="Station-clock microseconds since epoch, UTC.")
    raw_value: float
    raw_counts: int
    temperature_c: float | None = None
    valid: bool = True
    saturated: bool = False


class MeasurementEvent(_Payload):
    """One vehicle pass, as measured. The payload the whole system exists to produce."""

    topic: Literal["measurement.event"] = "measurement.event"
    event_id: str = Field(
        "",
        description="Derived from station, sensor and ts_start. Any supplied value is overwritten.",
    )
    sensor_id: str

    ts_start: int
    ts_peak: int
    ts_end: int

    raw_peak: float
    raw_area: float = Field(
        ...,
        description="Integral above the zero line, sensor-units*seconds. Proportional to "
        "mass/speed, not to mass -- see docs/signal-model.md.",
    )
    compensated_peak: float
    compensated_area: float | None = None
    temperature_c: float | None = None
    speed_mps: float | None = None
    axle_count: int | None = None

    mass_kg: float
    mass_ci_low: float
    mass_ci_high: float
    coverage_target: float = Field(0.95, gt=0.0, lt=1.0)
    interval_source: str | None = Field(
        None,
        description="How the interval was derived: residual_sd, rls_residual_sd, kalman_analytic, "
        "conformal_absolute, conformal_relative. Phase 5 compares them, and a number whose "
        "provenance is unknown cannot be compared with one whose is.",
    )

    calibration: CalibrationBlock
    preprocessing: PreprocessingBlock
    provenance: ProvenanceBlock
    quality_flag: QualityFlag = "ok"

    @model_validator(mode="after")
    def _derive_and_check(self) -> MeasurementEvent:
        if not (self.ts_start <= self.ts_peak <= self.ts_end):
            raise ValueError(
                f"ts_start <= ts_peak <= ts_end violated: "
                f"{self.ts_start} / {self.ts_peak} / {self.ts_end}"
            )
        if not (self.mass_ci_low <= self.mass_kg <= self.mass_ci_high):
            raise ValueError(
                f"mass_ci_low <= mass_kg <= mass_ci_high violated: "
                f"{self.mass_ci_low} / {self.mass_kg} / {self.mass_ci_high}"
            )
        derived = event_id_for(self.station_id, self.sensor_id, self.ts_start)
        if self.event_id != derived:
            # frozen model: rebuild the field rather than mutate
            object.__setattr__(self, "event_id", derived)
        return self


# --------------------------------------------------------------------------------------------
# calibration.*
# --------------------------------------------------------------------------------------------


class CalibrationState(_Payload):
    """The calibration loop's own state, exported as a time series.

    Principle 5: convergence has to be *visible* in Grafana, not inferred from logs. That is the
    entire reason this is an event type rather than a log line.
    """

    topic: Literal["calibration.state"] = "calibration.state"
    sensor_id: str
    ts: int
    profile_id: str
    estimator: str
    gain: float
    bias: float
    temp_coeff: float = 0.0
    state_hash: str
    update_count: int = Field(0, ge=0)
    covariance_trace: float | None = None
    residual: float | None = Field(None, description="Most recent prediction residual, kg.")
    controller_state: ControllerState = "MONITORING"


class CalibrationDriftDetected(_Payload):
    """A detector fired. Carries the statistic, not just the alarm, so thresholds can be tuned
    after the fact from recorded data rather than by re-running the experiment."""

    topic: Literal["calibration.drift_detected"] = "calibration.drift_detected"
    sensor_id: str
    ts: int
    detector: str = Field(..., description="cusum, page_hinkley, adwin, ks.")
    statistic: float
    threshold: float
    profile_id: str
    window_start_ts: int | None = None
    n_observations: int | None = None


class ProfileActivated(_Payload):
    """A new calibration profile took effect. Append-only history."""

    topic: Literal["calibration.profile_activated"] = "calibration.profile_activated"
    sensor_id: str
    ts: int
    profile_id: str
    supersedes: str | None = None
    estimator: str
    reason: str = Field(..., description="bootstrap, recalibration, manual, rollback.")
    n_reference_observations: int | None = None
    provenance: ProvenanceBlock


# --------------------------------------------------------------------------------------------
# system.*
# --------------------------------------------------------------------------------------------


class SystemMetric(_Payload):
    topic: Literal["system.metric"] = "system.metric"
    ts: int
    name: str = Field(..., description="Prometheus metric name, e.g. wim_buffer_depth.")
    value: float
    labels: dict[str, str] = Field(default_factory=dict)


class SystemIncident(_Payload):
    topic: Literal["system.incident"] = "system.incident"
    ts: int
    severity: Literal["info", "warning", "error", "critical"]
    kind: str = Field(..., description="publish_failure, dlq_reject, heartbeat_loss, ...")
    message: str
    sensor_id: str | None = None
    detail: dict[str, Any] = Field(default_factory=dict)


#: Topic string -> model. Used by ingest to dispatch and by the JSON Schema export.
TOPIC_MODELS: dict[str, type[_Payload]] = {
    "measurement.sample": MeasurementSample,
    "measurement.event": MeasurementEvent,
    "calibration.state": CalibrationState,
    "calibration.drift_detected": CalibrationDriftDetected,
    "calibration.profile_activated": ProfileActivated,
    "system.metric": SystemMetric,
    "system.incident": SystemIncident,
}


def exported_json_schemas() -> dict[str, dict[str, Any]]:
    """JSON Schema per topic, for consumers that are not Python.

    Written to ``docs/schemas/`` by ``wimsim export-schemas`` so the contract is reviewable in a
    diff rather than only readable by importing this module.
    """
    return {topic: model.model_json_schema() for topic, model in TOPIC_MODELS.items()}
