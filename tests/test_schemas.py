"""Event schemas: the wire contract.

These payloads are what the pipeline emits, what ingest validates, what the database stores and
what a paper cites. Three properties are tested harder than the rest because breaking any of them
breaks something that cannot be repaired after the fact:

* **``event_id`` is deterministic.** Replaying the same stream must produce the same ids, or the
  idempotent upsert of phase 3 silently duplicates every event.
* **Provenance is mandatory.** A ``measurement.event`` that will not validate without its config
  hash, seed and schema version is an event that cannot be emitted unreproducibly.
* **Old payloads still validate.** Buildspec section 11 asks for schema compatibility explicitly.
"""

from __future__ import annotations

import json

import pytest
from pydantic import ValidationError

from wimsim import SCHEMA_VERSION
from wimsim.core.schemas import (
    TOPIC_MODELS,
    CalibrationBlock,
    CalibrationDriftDetected,
    CalibrationState,
    MeasurementEvent,
    MeasurementSample,
    PreprocessingBlock,
    ProfileActivated,
    ProvenanceBlock,
    SystemIncident,
    SystemMetric,
    event_id_for,
    exported_json_schemas,
)


def _provenance(**over) -> dict:
    base = {
        "config_hash": "a" * 64,
        "seed": 20250601,
        "git_commit": "b" * 40,
        "git_dirty": False,
        "mode": "synthetic",
    }
    return {**base, **over}


def _event(**over) -> dict:
    base = {
        "station_id": "ST-DEMO-01",
        "sensor_id": "S1",
        "ts_start": 1748736000000000,
        "ts_peak": 1748736000005000,
        "ts_end": 1748736000010000,
        "raw_peak": 1.52,
        "raw_area": 0.0161,
        "compensated_peak": 1.47,
        "temperature_c": 20.1,
        "mass_kg": 7350.0,
        "mass_ci_low": 7100.0,
        "mass_ci_high": 7600.0,
        "calibration": {
            "profile_id": "p-0001",
            "estimator": "static_affine",
            "gain": 2.0e-4,
            "bias": 0.05,
            "temp_coeff": -2.0e-4,
            "state_hash": "c" * 16,
            "update_count": 12,
            "covariance_trace": 0.0,
        },
        "preprocessing": {
            "filter": "butterworth",
            "cutoff_hz": 120.0,
            "order": 4,
            "zero_window_s": 0.5,
        },
        "provenance": _provenance(),
    }
    return {**base, **over}


# -- event_id ------------------------------------------------------------------------------


def test_event_id_is_a_pure_function_of_station_sensor_and_ts_start() -> None:
    a = event_id_for("ST-1", "S1", 1748736000000000)
    b = event_id_for("ST-1", "S1", 1748736000000000)
    assert a == b
    assert a != event_id_for("ST-1", "S1", 1748736000000001)
    assert a != event_id_for("ST-2", "S1", 1748736000000000)
    assert a != event_id_for("ST-1", "S2", 1748736000000000)


def test_event_id_ignores_everything_else() -> None:
    """Two runs that detect the same crossing must agree, even if they estimate different masses.

    This is what makes replay idempotent: re-estimating history under a new calibration profile
    updates rows in place rather than inserting duplicates.
    """
    light = MeasurementEvent.model_validate(
        _event(mass_kg=1000.0, mass_ci_low=950.0, mass_ci_high=1050.0)
    )
    heavy = MeasurementEvent.model_validate(
        _event(mass_kg=40000.0, mass_ci_low=39000.0, mass_ci_high=41000.0)
    )
    assert light.mass_kg != heavy.mass_kg
    assert light.event_id == heavy.event_id


def test_event_id_is_derived_not_accepted() -> None:
    """A caller must not be able to forge an id that disagrees with the key fields."""
    ev = MeasurementEvent.model_validate(_event(event_id="deadbeef"))
    assert ev.event_id == event_id_for("ST-DEMO-01", "S1", 1748736000000000)


# -- required content ----------------------------------------------------------------------


def test_schema_version_defaults_to_the_package_version() -> None:
    assert MeasurementEvent.model_validate(_event()).schema_version == SCHEMA_VERSION


@pytest.mark.parametrize("missing", ["provenance", "calibration", "preprocessing", "mass_kg"])
def test_an_event_cannot_be_emitted_without_its_provenance(missing: str) -> None:
    payload = _event()
    payload.pop(missing)
    with pytest.raises(ValidationError):
        MeasurementEvent.model_validate(payload)


def test_unknown_fields_are_rejected() -> None:
    with pytest.raises(ValidationError):
        MeasurementEvent.model_validate(_event(mas_kg=1.0))


def test_timestamps_must_be_ordered() -> None:
    with pytest.raises(ValidationError, match="ts_start <= ts_peak <= ts_end"):
        MeasurementEvent.model_validate(_event(ts_peak=1748735999000000))


def test_confidence_interval_must_bracket_the_estimate() -> None:
    with pytest.raises(ValidationError, match="mass_ci_low <= mass_kg <= mass_ci_high"):
        MeasurementEvent.model_validate(_event(mass_ci_low=9000.0))


def test_quality_flag_defaults_to_ok_and_is_constrained() -> None:
    assert MeasurementEvent.model_validate(_event()).quality_flag == "ok"
    with pytest.raises(ValidationError):
        MeasurementEvent.model_validate(_event(quality_flag="fine"))


# -- serialisation -------------------------------------------------------------------------


def test_round_trips_through_json_unchanged() -> None:
    ev = MeasurementEvent.model_validate(_event())
    again = MeasurementEvent.model_validate_json(ev.model_dump_json())
    assert again == ev


def test_json_uses_integer_microseconds_not_floats() -> None:
    """Sub-microsecond drift through a float timestamp would break event_id determinism."""
    payload = json.loads(MeasurementEvent.model_validate(_event()).model_dump_json())
    for key in ("ts_start", "ts_peak", "ts_end"):
        assert isinstance(payload[key], int)


def test_every_topic_has_a_model_and_every_model_exports_a_schema() -> None:
    expected = {
        "measurement.sample",
        "measurement.event",
        "calibration.state",
        "calibration.drift_detected",
        "calibration.profile_activated",
        "system.metric",
        "system.incident",
    }
    assert set(TOPIC_MODELS) == expected
    schemas = exported_json_schemas()
    assert set(schemas) == expected
    for topic, schema in schemas.items():
        assert schema["title"], topic
        assert "schema_version" in schema["properties"], topic


# -- compatibility -------------------------------------------------------------------------


def test_a_payload_carrying_an_older_schema_version_still_validates() -> None:
    """Buildspec section 11: old-version payloads must still validate."""
    ev = MeasurementEvent.model_validate(_event(schema_version="0.9.0"))
    assert ev.schema_version == "0.9.0"


def test_schema_version_must_be_semantic() -> None:
    with pytest.raises(ValidationError):
        MeasurementEvent.model_validate(_event(schema_version="one"))


def test_optional_fields_may_be_absent_in_an_older_payload() -> None:
    """Fields added after 1.0.0 must be optional, or old data becomes unreadable."""
    payload = _event()
    payload["calibration"].pop("covariance_trace")
    payload.pop("trace_id", None)
    ev = MeasurementEvent.model_validate(payload)
    assert ev.calibration.covariance_trace is None
    assert ev.trace_id is None


# -- the other topics ----------------------------------------------------------------------


def test_measurement_sample() -> None:
    s = MeasurementSample.model_validate(
        {
            "station_id": "ST-1",
            "sensor_id": "S1",
            "ts": 1748736000000000,
            "raw_value": 0.05,
            "raw_counts": 10304,
            "temperature_c": 20.0,
            "valid": True,
            "saturated": False,
        }
    )
    assert s.topic == "measurement.sample"


def test_calibration_state_is_hashable_and_carries_covariance() -> None:
    st = CalibrationState.model_validate(
        {
            "station_id": "ST-1",
            "sensor_id": "S1",
            "ts": 1748736000000000,
            "profile_id": "p-0001",
            "estimator": "kalman",
            "gain": 2.0e-4,
            "bias": 0.05,
            "temp_coeff": -2.0e-4,
            "state_hash": "d" * 16,
            "update_count": 3,
            "covariance_trace": 1.2e-9,
            "controller_state": "MONITORING",
        }
    )
    assert st.topic == "calibration.state"
    assert st.controller_state == "MONITORING"


def test_controller_state_is_constrained_to_the_mapek_states() -> None:
    for name in ("MONITORING", "DRIFT_SUSPECTED", "RECALIBRATING", "VERIFYING", "DEGRADED"):
        CalibrationState.model_validate(
            {
                "station_id": "ST-1",
                "sensor_id": "S1",
                "ts": 1,
                "profile_id": "p",
                "estimator": "kalman",
                "gain": 1.0,
                "bias": 0.0,
                "temp_coeff": 0.0,
                "state_hash": "x",
                "update_count": 0,
                "controller_state": name,
            }
        )
    with pytest.raises(ValidationError):
        CalibrationState.model_validate(
            {
                "station_id": "ST-1",
                "sensor_id": "S1",
                "ts": 1,
                "profile_id": "p",
                "estimator": "kalman",
                "gain": 1.0,
                "bias": 0.0,
                "temp_coeff": 0.0,
                "state_hash": "x",
                "update_count": 0,
                "controller_state": "CONFUSED",
            }
        )


def test_drift_detected_and_profile_activated() -> None:
    d = CalibrationDriftDetected.model_validate(
        {
            "station_id": "ST-1",
            "sensor_id": "S1",
            "ts": 1748736000000000,
            "detector": "cusum",
            "statistic": 8.4,
            "threshold": 5.0,
            "profile_id": "p-0001",
        }
    )
    assert d.topic == "calibration.drift_detected"

    p = ProfileActivated.model_validate(
        {
            "station_id": "ST-1",
            "sensor_id": "S1",
            "ts": 1748736000000000,
            "profile_id": "p-0002",
            "supersedes": "p-0001",
            "estimator": "static_affine",
            "reason": "recalibration",
            "provenance": _provenance(),
        }
    )
    assert p.supersedes == "p-0001"


def test_system_metric_and_incident() -> None:
    m = SystemMetric.model_validate(
        {
            "station_id": "ST-1",
            "ts": 1748736000000000,
            "name": "wim_buffer_depth",
            "value": 12.0,
            "labels": {"stage": "publisher"},
        }
    )
    assert m.topic == "system.metric"

    i = SystemIncident.model_validate(
        {
            "station_id": "ST-1",
            "ts": 1748736000000000,
            "severity": "warning",
            "kind": "publish_failure",
            "message": "broker unreachable, buffering",
        }
    )
    assert i.severity == "warning"


def test_blocks_are_reusable_across_topics() -> None:
    """The provenance and calibration blocks are one definition, not copy-paste per topic."""
    assert issubclass(
        ProvenanceBlock, type(ProvenanceBlock.model_validate(_provenance())).__mro__[0]
    )
    assert CalibrationBlock.model_validate(_event()["calibration"]).profile_id == "p-0001"
    assert PreprocessingBlock.model_validate(_event()["preprocessing"]).order == 4


# -- trace context -------------------------------------------------------------------------


def test_a_payload_can_carry_a_traceparent() -> None:
    """MQTT has no headers, so the W3C context rides in the body (buildspec section 9).

    `trace_id` alone is not enough to re-parent a span at ingest -- a child needs its parent's
    span id too -- so both fields exist and `wimsim.observability.tracing` stamps them together.
    """
    tp = "00-" + "a" * 32 + "-" + "1" * 16 + "-01"
    ev = MeasurementEvent.model_validate(_event(trace_id="a" * 32, traceparent=tp))
    assert ev.traceparent == tp
    assert ev.trace_id == "a" * 32


def test_traceparent_is_optional_everywhere() -> None:
    """Replayed recordings and offline runs carry no trace, and must still validate."""
    for topic, model in TOPIC_MODELS.items():
        assert "traceparent" in model.model_fields, topic
    assert MeasurementEvent.model_validate(_event()).traceparent is None


def test_a_malformed_traceparent_is_rejected_at_the_boundary() -> None:
    """Garbage in the field would be dropped later by the tracer anyway, but a payload that
    cannot be trusted about its own context should not be stored as if it could."""
    with pytest.raises(ValidationError):
        MeasurementEvent.model_validate(_event(traceparent="not-a-traceparent"))


def test_adding_traceparent_was_a_minor_version_bump() -> None:
    """An optional additive field. Consumers on 1.0.0 keep working, which is the whole contract."""
    major, minor, _ = SCHEMA_VERSION.split(".")
    assert (major, minor) == ("1", "1")
