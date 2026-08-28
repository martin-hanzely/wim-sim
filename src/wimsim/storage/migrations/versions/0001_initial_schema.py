"""Initial schema: measured tables, truth tables, hypertables and continuous aggregates.

Revision ID: 0001
Revises:
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

from wimsim.storage.schema import HYPERTABLES, METADATA

revision: str = "0001"
down_revision: str | None = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    # The compose init script creates these on a fresh volume; creating them here too means the
    # migration also works against a database someone else provisioned.
    op.execute("CREATE SCHEMA IF NOT EXISTS wim")
    op.execute("CREATE SCHEMA IF NOT EXISTS truth")
    op.execute("CREATE EXTENSION IF NOT EXISTS timescaledb")

    for table in METADATA.sorted_tables:
        table.create(op.get_bind(), checkfirst=True)

    # Hypertables must be converted before any rows exist. `migrate_data => TRUE` would move
    # existing rows, which is slow and, on a table this wide, memorable; refusing is better than
    # silently doing it.
    for table, column, interval in HYPERTABLES:
        op.execute(
            sa.text(
                "SELECT create_hypertable("
                f"  '{table.schema}.{table.name}', '{column}',"
                f"  chunk_time_interval => INTERVAL '{interval}',"
                "   if_not_exists => TRUE, migrate_data => FALSE)"
            )
        )

    # Continuous aggregates, for dashboard performance (buildspec section 8). A panel showing a
    # week of throughput must not scan a week of raw events every time someone opens it.
    op.execute("""
        CREATE MATERIALIZED VIEW IF NOT EXISTS wim.event_rate_1m
        WITH (timescaledb.continuous) AS
        SELECT
            time_bucket(INTERVAL '1 minute', ts_start) AS bucket,
            station_id,
            sensor_id,
            count(*)                                   AS events,
            avg(mass_kg)                               AS mean_mass_kg,
            sum(axle_count)                            AS axles,
            count(*) FILTER (WHERE quality_flag <> 'ok') AS not_ok
        FROM wim.measurement_event
        GROUP BY bucket, station_id, sensor_id
        WITH NO DATA
    """)
    op.execute("""
        SELECT add_continuous_aggregate_policy('wim.event_rate_1m',
            start_offset => INTERVAL '3 hours',
            end_offset   => INTERVAL '1 minute',
            schedule_interval => INTERVAL '1 minute',
            if_not_exists => TRUE)
    """)

    # The calibration dashboard's centrepiece reads this: estimated gain over time, per profile.
    op.execute("""
        CREATE MATERIALIZED VIEW IF NOT EXISTS wim.calibration_1m
        WITH (timescaledb.continuous) AS
        SELECT
            time_bucket(INTERVAL '1 minute', ts) AS bucket,
            station_id,
            sensor_id,
            last(gain, ts)             AS gain,
            last(bias, ts)             AS bias,
            last(covariance_trace, ts) AS covariance_trace,
            last(profile_id, ts)       AS profile_id,
            last(controller_state, ts) AS controller_state,
            avg(residual)              AS mean_residual
        FROM wim.calibration_state
        GROUP BY bucket, station_id, sensor_id
        WITH NO DATA
    """)
    op.execute("""
        SELECT add_continuous_aggregate_policy('wim.calibration_1m',
            start_offset => INTERVAL '3 hours',
            end_offset   => INTERVAL '1 minute',
            schedule_interval => INTERVAL '1 minute',
            if_not_exists => TRUE)
    """)

    # Samples are the one stream large enough to need a retention policy by default: at 2 kHz a
    # single station produces 170 million rows a day. Events, which are what a paper cites, are
    # kept forever.
    op.execute(
        "SELECT add_retention_policy('wim.sensor_sample', INTERVAL '7 days', if_not_exists => TRUE)"
    )


def downgrade() -> None:
    op.execute("DROP MATERIALIZED VIEW IF EXISTS wim.calibration_1m CASCADE")
    op.execute("DROP MATERIALIZED VIEW IF EXISTS wim.event_rate_1m CASCADE")
    for table in reversed(METADATA.sorted_tables):
        table.drop(op.get_bind(), checkfirst=True)
