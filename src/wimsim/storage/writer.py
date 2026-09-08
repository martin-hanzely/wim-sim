"""Writing measured data to TimescaleDB, idempotently.

**Idempotent because delivery is at-least-once.** QoS 1 means the broker may hand the same message
over twice, a station replaying a backlog after a restart may resend what it already sent, and
``recompute --from <ts> --profile <id>`` (phase 5) deliberately re-derives history. All three must
converge on the same rows, so every write is an upsert keyed on the event's own identity -- never an
insert that assumes it is the first.

For ``measurement_event`` that key is ``(event_id, ts_start)``, and re-running a recompute updates
the mass and the calibration block *in place* rather than inserting a second opinion.

**Timestamps arrive as integer microseconds and are stored as ``timestamptz``.** The conversion
happens here and only here. Postgres stores an instant; the microsecond integer is the wire format.
Both are unambiguous, which is the property that matters -- unlike a naive local time, which is
neither.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import Engine, Table, create_engine, func, select
from sqlalchemy.dialects.postgresql import insert

from wimsim.storage.schema import (
    calibration_state,
    dlq,
    incident_log,
    measurement_event,
    sensor_sample,
    system_metric,
    truth_pass,
    truth_timeseries,
)
from wimsim.storage.url import database_url

__all__ = ["EventWriter", "datetime_to_us", "us_to_datetime"]


def us_to_datetime(value: int | None) -> datetime | None:
    """Microseconds since the epoch to an aware UTC datetime."""
    return None if value is None else datetime.fromtimestamp(value / 1e6, tz=UTC)


def datetime_to_us(value: datetime | None) -> int | None:
    """The exact inverse of :func:`us_to_datetime`, and it has to stay exact.

    ``event_id`` is a UUIDv5 of ``ts_start``, so a round trip that lost a microsecond would give a
    recomputed event a different id and the upsert would insert it alongside the original rather
    than replacing it. Rounded rather than truncated so a value that arrives as x.999999 does not
    come back a microsecond early.
    """
    return None if value is None else int(round(value.timestamp() * 1e6))


class EventWriter:
    """Bulk, idempotent writes. One connection, reused; batches in a single statement."""

    def __init__(self, url: str | None = None, *, engine: Engine | None = None) -> None:
        self.engine = engine or create_engine(
            database_url(url),
            pool_pre_ping=True,  # a station reconnecting after an outage finds a stale pool
            future=True,
        )

    # -- generic upsert --------------------------------------------------------------------------

    def _upsert(self, table: Table, rows: Sequence[dict[str, Any]], conflict: Sequence[str]) -> int:
        if not rows:
            return 0
        statement = insert(table).values(list(rows))
        updatable = {
            column.name: statement.excluded[column.name]
            for column in table.columns
            if column.name not in conflict and column.name != "ingested_at"
        }
        statement = statement.on_conflict_do_update(index_elements=list(conflict), set_=updatable)
        with self.engine.begin() as conn:
            conn.execute(statement)
        return len(rows)

    def _insert(self, table: Table, rows: Sequence[dict[str, Any]]) -> int:
        """For append-only streams with no natural key -- samples, metrics, incidents.

        These have no identity to deduplicate on, so a redelivery genuinely does produce a second
        row. That is the correct trade for a stream whose value is aggregate rather than individual;
        events, which a paper cites one at a time, get a key and an upsert.
        """
        if not rows:
            return 0
        with self.engine.begin() as conn:
            conn.execute(insert(table), list(rows))
        return len(rows)

    # -- measurement events -----------------------------------------------------------------------

    @staticmethod
    def _event_row(payload: dict[str, Any]) -> dict[str, Any]:
        cal = payload.get("calibration") or {}
        return {
            "ts_start": us_to_datetime(payload["ts_start"]),
            "ts_peak": us_to_datetime(payload["ts_peak"]),
            "ts_end": us_to_datetime(payload["ts_end"]),
            "event_id": payload["event_id"],
            "station_id": payload["station_id"],
            "sensor_id": payload["sensor_id"],
            "schema_version": payload["schema_version"],
            "raw_peak": payload.get("raw_peak"),
            "raw_area": payload.get("raw_area"),
            "compensated_peak": payload.get("compensated_peak"),
            "compensated_area": payload.get("compensated_area"),
            "temperature_c": payload.get("temperature_c"),
            "speed_mps": payload.get("speed_mps"),
            "axle_count": payload.get("axle_count"),
            "mass_kg": payload["mass_kg"],
            "mass_ci_low": payload.get("mass_ci_low"),
            "mass_ci_high": payload.get("mass_ci_high"),
            "coverage_target": payload.get("coverage_target"),
            "profile_id": cal.get("profile_id"),
            "estimator": cal.get("estimator"),
            "cal_gain": cal.get("gain"),
            "cal_bias": cal.get("bias"),
            "cal_temp_coeff": cal.get("temp_coeff"),
            "cal_state_hash": cal.get("state_hash"),
            "cal_update_count": cal.get("update_count"),
            "cal_covariance_trace": cal.get("covariance_trace"),
            "quality_flag": payload.get("quality_flag", "ok"),
            "trace_id": payload.get("trace_id"),
            "preprocessing": payload.get("preprocessing"),
            "provenance": payload["provenance"],
        }

    def write_events(self, payloads: Iterable[dict[str, Any]]) -> int:
        rows = [self._event_row(p) for p in payloads]
        return self._upsert(measurement_event, rows, conflict=("event_id", "ts_start"))

    def write_calibration_states(self, payloads: Iterable[dict[str, Any]]) -> int:
        rows = [
            {
                "ts": us_to_datetime(p["ts"]),
                "station_id": p["station_id"],
                "sensor_id": p["sensor_id"],
                "profile_id": p["profile_id"],
                "estimator": p["estimator"],
                "gain": p["gain"],
                "bias": p["bias"],
                "temp_coeff": p.get("temp_coeff"),
                "state_hash": p["state_hash"],
                "update_count": p.get("update_count"),
                "covariance_trace": p.get("covariance_trace"),
                "residual": p.get("residual"),
                "controller_state": p.get("controller_state"),
            }
            for p in payloads
        ]
        return self._insert(calibration_state, rows)

    def write_samples(self, payloads: Iterable[dict[str, Any]]) -> int:
        rows = [
            {
                "ts": us_to_datetime(p["ts"]),
                "station_id": p["station_id"],
                "sensor_id": p["sensor_id"],
                "raw_value": p["raw_value"],
                "raw_counts": p.get("raw_counts"),
                "temperature_c": p.get("temperature_c"),
                "valid": p.get("valid", True),
                "saturated": p.get("saturated", False),
            }
            for p in payloads
        ]
        return self._insert(sensor_sample, rows)

    def write_metrics(self, payloads: Iterable[dict[str, Any]]) -> int:
        rows = [
            {
                "ts": us_to_datetime(p["ts"]),
                "station_id": p["station_id"],
                "name": p["name"],
                "value": p["value"],
                "labels": p.get("labels") or {},
            }
            for p in payloads
        ]
        return self._insert(system_metric, rows)

    def write_incidents(self, payloads: Iterable[dict[str, Any]]) -> int:
        rows = [
            {
                "ts": us_to_datetime(p["ts"]),
                "station_id": p["station_id"],
                "sensor_id": p.get("sensor_id"),
                "severity": p["severity"],
                "kind": p["kind"],
                "message": p["message"],
                "detail": p.get("detail") or {},
            }
            for p in payloads
        ]
        return self._insert(incident_log, rows)

    # -- dead letters ------------------------------------------------------------------------------

    def write_dlq(self, topic: str, payload: bytes | str, reason: str, detail: str = "") -> None:
        """Record a payload that could not be accepted, verbatim.

        Verbatim matters: parsing it, normalising it or storing what we think it meant destroys the
        evidence needed to work out why it was rejected -- which is the only reason to keep it.
        """
        blob = payload.decode("utf-8", errors="replace") if isinstance(payload, bytes) else payload
        with self.engine.begin() as conn:
            conn.execute(
                insert(dlq).values(
                    topic=topic, reason_code=reason, detail=detail[:2000], payload=blob
                )
            )

    # -- truth ---------------------------------------------------------------------------------------

    def write_truth_passes(self, run_id: str, station_id: str, rows: Iterable[dict]) -> int:
        prepared = [
            {
                "ts_peak": us_to_datetime(int(r["ts_peak_us"])),
                "pass_id": r["pass_id"],
                "run_id": run_id,
                "station_id": station_id,
                "pass_index": int(r["pass_index"]),
                "vehicle_class": r.get("vehicle_class"),
                "true_mass_kg": float(r["true_mass_kg"]),
                "applied_mass_kg": float(r.get("applied_mass_kg", r["true_mass_kg"])),
                "speed_mps": r.get("speed_mps"),
                "axle_count": int(r.get("axle_count", 0)) or None,
                "peak_load_kg": r.get("peak_load_kg"),
                "area_load_kg_s": r.get("area_load_kg_s"),
                "k_at_peak": r.get("k_at_peak"),
                "q_at_peak": r.get("q_at_peak"),
                "t_sensor_at_peak": r.get("t_sensor_at_peak"),
            }
            for r in rows
        ]
        return self._upsert(truth_pass, prepared, conflict=("run_id", "pass_id", "ts_peak"))

    def write_truth_timeseries(self, run_id: str, station_id: str, rows: Iterable[dict]) -> int:
        prepared = [
            {
                "ts": us_to_datetime(int(r["ts_us"])),
                "run_id": run_id,
                "station_id": station_id,
                "q_true": r.get("q_true"),
                "k_true": r.get("k_true"),
                "alpha_true": r.get("alpha_true"),
                "t_sensor_true": r.get("t_sensor_true"),
                "t_ambient_true": r.get("t_ambient_true"),
                "clock_offset_s": r.get("clock_offset_s"),
                "active_faults": r.get("active_faults") or "",
            }
            for r in rows
        ]
        return self._insert(truth_timeseries, prepared)

    # -- reading back --------------------------------------------------------------------------------

    def read_events(
        self,
        *,
        station_id: str | None = None,
        from_ts_us: int | None = None,
        to_ts_us: int | None = None,
        limit: int | None = None,
    ) -> list[dict[str, Any]]:
        """Measurement events, in the same shape ``write_events`` accepts.

        Timestamps come back as integer microseconds, inverting exactly the conversion the writer
        applies on the way in. That symmetry is load-bearing rather than tidy: ``event_id`` is
        derived from ``ts_start``, so a recomputed row written under a timestamp that had drifted
        by a microsecond would get a *new* id and be inserted alongside the original instead of
        replacing it.

        Ordered by time and bounded by ``limit``, because a station that has been running for a
        year holds more events than a recompute should pull into memory at once.
        """
        statement = select(measurement_event)
        if station_id is not None:
            statement = statement.where(measurement_event.c.station_id == station_id)
        if from_ts_us is not None:
            statement = statement.where(measurement_event.c.ts_start >= us_to_datetime(from_ts_us))
        if to_ts_us is not None:
            statement = statement.where(measurement_event.c.ts_start <= us_to_datetime(to_ts_us))
        statement = statement.order_by(measurement_event.c.ts_start)
        if limit is not None:
            statement = statement.limit(int(limit))

        with self.engine.connect() as conn:
            rows = [dict(row) for row in conn.execute(statement).mappings()]

        for row in rows:
            for column in ("ts_start", "ts_peak", "ts_end"):
                row[column] = datetime_to_us(row[column])
            row.pop("ingested_at", None)
        return rows

    def count(self, table: Table) -> int:
        with self.engine.connect() as conn:
            return int(conn.execute(select(func.count()).select_from(table)).scalar_one())

    def refresh_aggregate(
        self, view: str, start: datetime | None = None, end: datetime | None = None
    ) -> None:
        """Materialise a continuous aggregate now, rather than waiting for its policy.

        TimescaleDB refuses ``refresh_continuous_aggregate`` inside a transaction block, and
        SQLAlchemy opens one by default -- so this needs an explicitly autocommitting connection.
        Needed after a bulk backfill, when the scheduled policy would otherwise leave the dashboard
        blank for a minute over data that is already there.
        """
        from sqlalchemy import text

        with self.engine.connect().execution_options(isolation_level="AUTOCOMMIT") as conn:
            # The casts are required, not decorative: Postgres cannot infer a type for a NULL
            # parameter, and a NULL window ("refresh everything") is the common case here.
            # CAST(...) rather than `::` -- SQLAlchemy's text() parser reads `:view::regclass` as
            # a bind parameter named `view` followed by a stray colon.
            conn.execute(
                text(
                    "CALL refresh_continuous_aggregate("
                    "  CAST(:view AS regclass),"
                    "  CAST(:start AS timestamptz),"
                    "  CAST(:end AS timestamptz))"
                ),
                {"view": view, "start": start, "end": end},
            )

    def dispose(self) -> None:
        self.engine.dispose()
