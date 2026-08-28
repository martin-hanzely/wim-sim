"""The database schema, as SQLAlchemy Core metadata.

Core rather than the ORM: everything here is a bulk upsert or an analytical query, and an identity
map buys nothing for either. Alembic owns the migrations; this module is the single description both
the migration and the writer read, so they cannot drift.

**Two schemas, and the separation is load-bearing.** ``wim`` holds what was *measured*. ``truth``
holds what the simulator *knows*, and is joined only by the scoring layer (buildspec section 8). In
replay mode ``truth`` is empty and any dashboard panel reading it goes blank -- which is correct,
because a real recording has no true gain, and a panel that invented one would be lying.

**Hypertable partitioning keys are in every primary key**, because TimescaleDB requires it. That
constrains ``measurement_event``: its natural key is ``event_id`` alone, but the primary key must
include ``ts_start``. This is safe rather than a compromise -- ``event_id`` is a UUIDv5 *of*
``ts_start`` (with station and sensor), so two rows sharing an ``event_id`` and differing in
``ts_start`` cannot exist. The uniqueness the upsert relies on is preserved.
"""

from __future__ import annotations

from sqlalchemy import (
    BigInteger,
    Boolean,
    Column,
    Float,
    Index,
    Integer,
    MetaData,
    String,
    Table,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB, TIMESTAMP

__all__ = [
    "HYPERTABLES",
    "METADATA",
    "calibration_profile",
    "calibration_state",
    "dlq",
    "incident_log",
    "measurement_event",
    "run_manifest",
    "sensor_sample",
    "station",
    "system_metric",
    "truth_pass",
    "truth_timeseries",
]

METADATA = MetaData()


def _ts(name: str = "ts") -> Column:
    """A timestamptz partition column. Stored as an instant, never as a naive local time."""
    return Column(name, TIMESTAMP(timezone=True), nullable=False)


# -- measured ---------------------------------------------------------------------------------

measurement_event = Table(
    "measurement_event",
    METADATA,
    _ts("ts_start"),
    Column("event_id", String(64), nullable=False),
    Column("station_id", String(64), nullable=False),
    Column("sensor_id", String(64), nullable=False),
    Column("schema_version", String(16), nullable=False),
    _ts("ts_peak"),
    _ts("ts_end"),
    Column("raw_peak", Float),
    Column("raw_area", Float),
    Column("compensated_peak", Float),
    Column("compensated_area", Float),
    Column("temperature_c", Float),
    Column("speed_mps", Float),
    Column("axle_count", Integer),
    Column("mass_kg", Float, nullable=False),
    Column("mass_ci_low", Float),
    Column("mass_ci_high", Float),
    Column("coverage_target", Float),
    # Calibration, flattened: these are what the dashboard plots against truth, and a JSONB probe
    # per point would make the centrepiece panel unusable.
    Column("profile_id", String(64)),
    Column("estimator", String(32)),
    Column("cal_gain", Float),
    Column("cal_bias", Float),
    Column("cal_temp_coeff", Float),
    Column("cal_state_hash", String(64)),
    Column("cal_update_count", Integer),
    Column("cal_covariance_trace", Float),
    Column("quality_flag", String(16), nullable=False, server_default="ok"),
    Column("trace_id", String(64)),
    # Provenance and preprocessing are carried whole. They are read when auditing one event, never
    # aggregated, so a JSONB column is exactly right and adding twelve more columns is not.
    Column("preprocessing", JSONB),
    Column("provenance", JSONB, nullable=False),
    Column("ingested_at", TIMESTAMP(timezone=True), server_default="now()"),
    UniqueConstraint("event_id", "ts_start", name="measurement_event_pkey"),
    Index("measurement_event_station_time", "station_id", "ts_start"),
    Index("measurement_event_profile", "profile_id"),
    schema="wim",
)

sensor_sample = Table(
    "sensor_sample",
    METADATA,
    _ts(),
    Column("station_id", String(64), nullable=False),
    Column("sensor_id", String(64), nullable=False),
    Column("raw_value", Float, nullable=False),
    Column("raw_counts", BigInteger),
    Column("temperature_c", Float),
    Column("valid", Boolean, nullable=False, server_default="true"),
    Column("saturated", Boolean, nullable=False, server_default="false"),
    Index("sensor_sample_station_time", "station_id", "sensor_id", "ts"),
    schema="wim",
)

calibration_state = Table(
    "calibration_state",
    METADATA,
    _ts(),
    Column("station_id", String(64), nullable=False),
    Column("sensor_id", String(64), nullable=False),
    Column("profile_id", String(64), nullable=False),
    Column("estimator", String(32), nullable=False),
    Column("gain", Float, nullable=False),
    Column("bias", Float, nullable=False),
    Column("temp_coeff", Float),
    Column("state_hash", String(64), nullable=False),
    Column("update_count", Integer),
    Column("covariance_trace", Float),
    Column("residual", Float),
    Column("controller_state", String(24)),
    Index("calibration_state_station_time", "station_id", "sensor_id", "ts"),
    schema="wim",
)

system_metric = Table(
    "system_metric",
    METADATA,
    _ts(),
    Column("station_id", String(64), nullable=False),
    Column("name", String(96), nullable=False),
    Column("value", Float, nullable=False),
    Column("labels", JSONB),
    Index("system_metric_name_time", "name", "ts"),
    schema="wim",
)

incident_log = Table(
    "incident_log",
    METADATA,
    _ts(),
    Column("station_id", String(64), nullable=False),
    Column("sensor_id", String(64)),
    Column("severity", String(16), nullable=False),
    Column("kind", String(48), nullable=False),
    Column("message", Text, nullable=False),
    Column("detail", JSONB),
    Index("incident_log_station_time", "station_id", "ts"),
    schema="wim",
)

# -- reference tables (not hypertables) ---------------------------------------------------------

station = Table(
    "station",
    METADATA,
    Column("station_id", String(64), primary_key=True),
    Column("description", Text),
    Column("sample_rate_hz", Float),
    Column("unit", String(16)),
    Column("metadata", JSONB),
    schema="wim",
)

calibration_profile = Table(
    "calibration_profile",
    METADATA,
    Column("profile_id", String(64), primary_key=True),
    Column("station_id", String(64), nullable=False),
    Column("sensor_id", String(64), nullable=False),
    Column("estimator", String(32), nullable=False),
    Column("activated_at", TIMESTAMP(timezone=True), nullable=False),
    # Append-only: superseding a profile sets this on the OLD row and inserts a new one. Nothing is
    # ever edited in place, so an event can always name the calibration that produced it, even
    # after that calibration has been replaced.
    Column("superseded_by", String(64)),
    Column("reason", String(32)),
    Column("state", JSONB, nullable=False),
    Column("provenance", JSONB),
    Index("calibration_profile_station", "station_id", "sensor_id", "activated_at"),
    schema="wim",
)

run_manifest = Table(
    "run_manifest",
    METADATA,
    Column("run_id", String(96), primary_key=True),
    Column("scenario", String(64)),
    Column("station_id", String(64)),
    Column("config_hash", String(64), nullable=False),
    Column("output_hash", String(64)),
    Column("seed", BigInteger),
    Column("mode", String(16)),
    Column("created_at", TIMESTAMP(timezone=True)),
    Column("manifest", JSONB, nullable=False),
    schema="wim",
)

dlq = Table(
    "dlq",
    METADATA,
    Column("id", BigInteger, primary_key=True, autoincrement=True),
    Column("received_at", TIMESTAMP(timezone=True), nullable=False, server_default="now()"),
    Column("topic", String(128), nullable=False),
    Column("reason_code", String(48), nullable=False),
    Column("detail", Text),
    # The payload is kept verbatim, as bytes, exactly as it arrived. Anything else -- parsing it,
    # normalising it, storing what we think it meant -- destroys the evidence needed to work out
    # why it was rejected.
    Column("payload", Text, nullable=False),
    Index("dlq_reason_time", "reason_code", "received_at"),
    schema="wim",
)

# -- truth -------------------------------------------------------------------------------------

truth_pass = Table(
    "truth_pass",
    METADATA,
    _ts("ts_peak"),
    Column("pass_id", String(64), nullable=False),
    Column("run_id", String(96), nullable=False),
    Column("station_id", String(64), nullable=False),
    Column("pass_index", Integer),
    Column("vehicle_class", String(32)),
    Column("true_mass_kg", Float, nullable=False),
    Column("applied_mass_kg", Float),
    Column("speed_mps", Float),
    Column("axle_count", Integer),
    Column("peak_load_kg", Float),
    Column("area_load_kg_s", Float),
    Column("k_at_peak", Float),
    Column("q_at_peak", Float),
    Column("t_sensor_at_peak", Float),
    UniqueConstraint("run_id", "pass_id", "ts_peak", name="truth_pass_pkey"),
    Index("truth_pass_run_time", "run_id", "ts_peak"),
    schema="truth",
)

truth_timeseries = Table(
    "truth_timeseries",
    METADATA,
    _ts(),
    Column("run_id", String(96), nullable=False),
    Column("station_id", String(64), nullable=False),
    Column("q_true", Float),
    Column("k_true", Float),
    Column("alpha_true", Float),
    Column("t_sensor_true", Float),
    Column("t_ambient_true", Float),
    Column("clock_offset_s", Float),
    Column("active_faults", Text),
    Index("truth_timeseries_run_time", "run_id", "ts"),
    schema="truth",
)

#: (table, partition column, chunk interval). Applied by the migration, not by the writer -- a
#: writer that created its own tables would work on an empty database and diverge from the
#: migration forever after.
HYPERTABLES: tuple[tuple[Table, str, str], ...] = (
    (measurement_event, "ts_start", "7 days"),
    (sensor_sample, "ts", "1 hour"),
    (calibration_state, "ts", "7 days"),
    (system_metric, "ts", "1 day"),
    (incident_log, "ts", "30 days"),
    (truth_pass, "ts_peak", "7 days"),
    (truth_timeseries, "ts", "1 day"),
)
