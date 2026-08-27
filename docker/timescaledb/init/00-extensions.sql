-- Runs once, on an empty data volume. Extensions and schemas only.
--
-- TABLES ARE NOT CREATED HERE. Alembic owns them, so that the schema has a version, a migration
-- path and a diff. An init script that creates tables works exactly once -- on a fresh volume --
-- and then silently diverges from the code for the rest of the project's life.

CREATE EXTENSION IF NOT EXISTS timescaledb;
CREATE EXTENSION IF NOT EXISTS pg_stat_statements;

-- Measurements, metrics and calibration state.
CREATE SCHEMA IF NOT EXISTS wim;

-- Ground truth lives in its OWN schema (buildspec section 8), joined only by the scoring layer.
-- In replay mode it is empty and the dashboards that reference it degrade to blank panels, which
-- is correct: there is no true gain to draw for a real recording, and a dashboard that invented
-- one would be lying.
CREATE SCHEMA IF NOT EXISTS truth;

COMMENT ON SCHEMA wim IS 'Measured data: events, samples, calibration state, metrics, incidents.';
COMMENT ON SCHEMA truth IS
  'Simulator ground truth. Never read by the edge or the estimator; joined only when scoring. '
  'Empty for replayed real recordings.';
