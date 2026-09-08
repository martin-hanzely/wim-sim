"""The metric registry: the complete buildspec set, and the rules about who may emit what.

Three things are being protected here.

**The set is complete and named exactly as the buildspec names it.** ``BUILDSPEC_METRICS`` below is
a transcription of section 9, kept as a literal so that a metric renamed in code and not in the spec
(or the reverse) fails a test rather than silently breaking a dashboard query. Grafana panels refer
to these by string; nothing else would catch a typo.

**Truth metrics cannot be emitted from the estimator path.** Principle 1 is enforced for imports by
``test_truth_isolation.py``; the same rule has an observability-shaped hole in it, because a metric
named ``wim_mass_true`` emitted by the edge would leak truth into the same Prometheus the controller
could read. So the registry itself refuses.

**Nothing requires a collector.** The default is a no-op, because the edge has to run on a station
with no link and the test suite has to run with no docker.
"""

from __future__ import annotations

import pytest

from wimsim.observability.metrics import (
    REGISTRY,
    Metrics,
    NullSink,
    RecordingSink,
    build_metrics,
)

# Section 9 of the buildspec, transcribed. Flow, calibration loop, quality, truth overlay.
BUILDSPEC_METRICS = {
    # flow
    "wim_samples_acquired_total",
    "wim_sample_gaps_total",
    "wim_events_detected_total",
    "wim_publish_latency_ms",
    "wim_buffer_depth",
    "wim_publish_failures_total",
    "wim_dlq_total",
    "wim_ingest_lag_ms",
    "wim_db_write_latency_ms",
    # calibration loop
    "wim_cal_gain_estimate",
    "wim_cal_bias_estimate",
    "wim_cal_temp_coeff_estimate",
    "wim_cal_covariance_trace",
    "wim_cal_update_count",
    "wim_cal_residual",
    "wim_drift_statistic",
    "wim_recalibration_triggered_total",
    "wim_cal_state",
    "wim_cal_profile_version",
    # quality
    "wim_mass_abs_error",
    "wim_mass_rel_error",
    "wim_interval_width",
    "wim_coverage_rolling",
    # truth overlay
    "wim_cal_gain_true",
    "wim_cal_bias_true",
    "wim_temperature_true",
    "wim_mass_true",
}


def test_registry_is_exactly_the_buildspec_set() -> None:
    assert set(REGISTRY) == BUILDSPEC_METRICS


def test_every_definition_is_complete() -> None:
    for name, mdef in REGISTRY.items():
        assert mdef.name == name
        assert mdef.kind in {"counter", "gauge", "histogram"}
        assert mdef.unit, f"{name} has no unit"
        assert mdef.description.endswith("."), f"{name}: description should be a sentence"


def test_counters_are_named_total_and_nothing_else_is() -> None:
    """Prometheus convention, and the dashboards rely on it when choosing rate() vs raw."""
    for name, mdef in REGISTRY.items():
        assert (mdef.kind == "counter") == name.endswith("_total"), name


# ------------------------------------------------------------------------------------------
# recording and validation
# ------------------------------------------------------------------------------------------


def test_records_name_kind_value_and_attributes_in_order() -> None:
    sink = RecordingSink()
    m = Metrics(sink)
    m.add("wim_samples_acquired_total", 500)
    m.set("wim_buffer_depth", 3)
    m.observe("wim_publish_latency_ms", 12.5, station_id="ST-1")

    assert [(r.name, r.kind, r.value) for r in sink.records] == [
        ("wim_samples_acquired_total", "counter", 500.0),
        ("wim_buffer_depth", "gauge", 3.0),
        ("wim_publish_latency_ms", "histogram", 12.5),
    ]
    assert sink.records[-1].attributes == {"station_id": "ST-1"}


def test_unknown_metric_is_refused() -> None:
    m = Metrics(RecordingSink())
    with pytest.raises(KeyError, match="wim_samples_aquired_total"):
        m.add("wim_samples_aquired_total", 1)


def test_wrong_instrument_kind_is_refused() -> None:
    """A gauge recorded through add() would be summed by Prometheus. Silent, and wrong."""
    m = Metrics(RecordingSink())
    with pytest.raises(TypeError, match="gauge"):
        m.add("wim_buffer_depth", 1)
    with pytest.raises(TypeError, match="counter"):
        m.set("wim_dlq_total", 1)


def test_counters_reject_negative_deltas() -> None:
    m = Metrics(RecordingSink())
    with pytest.raises(ValueError, match="monotonic"):
        m.add("wim_dlq_total", -1, reason="invalid_json")


# ------------------------------------------------------------------------------------------
# required attributes
# ------------------------------------------------------------------------------------------


def test_labelled_metrics_require_their_label() -> None:
    """`wim_drift_statistic{detector=...}` is meaningless unlabelled: four detectors would collide
    into one series and their alarms would be indistinguishable."""
    m = Metrics(RecordingSink())
    with pytest.raises(ValueError, match="detector"):
        m.set("wim_drift_statistic", 0.4)
    m.set("wim_drift_statistic", 0.4, detector="cusum")

    with pytest.raises(ValueError, match="state"):
        m.set("wim_cal_state", 1)
    m.set("wim_cal_state", 1, state="monitoring")

    # Same argument for the dead-letter queue: "12 rejections" is an alert, "12 rejections, all
    # schema_validation_failed" is a diagnosis, and only the second is actionable at 3am.
    with pytest.raises(ValueError, match="reason"):
        m.add("wim_dlq_total", 1)
    m.add("wim_dlq_total", 1, reason="schema_validation_failed")


# ------------------------------------------------------------------------------------------
# principle 1, at the observability layer
# ------------------------------------------------------------------------------------------


TRUTH_METRICS = ["wim_cal_gain_true", "wim_cal_bias_true", "wim_temperature_true", "wim_mass_true"]


@pytest.mark.parametrize("name", TRUTH_METRICS)
def test_truth_metrics_are_refused_on_the_estimator_path(name: str) -> None:
    m = Metrics(RecordingSink())  # truth_allowed defaults to False
    with pytest.raises(PermissionError, match="truth"):
        m.set(name, 1.0)


@pytest.mark.parametrize("name", TRUTH_METRICS)
def test_truth_metrics_are_allowed_to_the_truth_exporter(name: str) -> None:
    sink = RecordingSink()
    m = Metrics(sink, truth_allowed=True)
    m.set(name, 1.0)
    assert sink.records[-1].name == name
    assert sink.records[-1].attributes["source"] == "truth"


def test_truth_registry_stamps_source_truth_and_refuses_a_conflicting_label() -> None:
    """The label is what dashboards filter on; letting a caller set it to anything else would
    put a truth series where an estimate series is expected."""
    m = Metrics(RecordingSink(), truth_allowed=True)
    with pytest.raises(ValueError, match="source"):
        m.set("wim_mass_true", 1.0, source="estimate")


def test_non_truth_metrics_are_not_stamped() -> None:
    sink = RecordingSink()
    Metrics(sink, truth_allowed=True).set("wim_buffer_depth", 2)
    assert "source" not in sink.records[-1].attributes


# ------------------------------------------------------------------------------------------
# the no-op path
# ------------------------------------------------------------------------------------------


def test_no_endpoint_configured_gives_a_null_sink(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("OTEL_EXPORTER_OTLP_ENDPOINT", raising=False)
    m = build_metrics(station_id="ST-1")
    assert isinstance(m.sink, NullSink)
    assert not m.enabled


def test_sdk_disabled_wins_over_a_configured_endpoint(monkeypatch: pytest.MonkeyPatch) -> None:
    """The standard OTel kill switch. Useful in tests and on a station being debugged."""
    monkeypatch.setenv("OTEL_EXPORTER_OTLP_ENDPOINT", "http://localhost:4317")
    monkeypatch.setenv("OTEL_SDK_DISABLED", "true")
    assert isinstance(build_metrics(station_id="ST-1").sink, NullSink)


def test_the_null_path_still_validates(monkeypatch: pytest.MonkeyPatch) -> None:
    """Otherwise a typo would only surface in production, which is exactly backwards."""
    monkeypatch.delenv("OTEL_EXPORTER_OTLP_ENDPOINT", raising=False)
    m = build_metrics(station_id="ST-1")
    m.add("wim_samples_acquired_total", 1)  # fine
    with pytest.raises(KeyError):
        m.add("wim_nonsense_total", 1)


def test_null_sink_records_nothing_and_costs_nothing() -> None:
    m = Metrics(NullSink())
    for _ in range(1000):
        m.add("wim_samples_acquired_total", 1)
    assert m.sink.count == 1000  # counted, not stored


def test_bound_attributes_are_merged_into_every_record() -> None:
    sink = RecordingSink()
    m = Metrics(sink).bind(station_id="ST-1", run_id="r-9")
    m.add("wim_events_detected_total", 1, sensor_id="S1")
    assert sink.records[-1].attributes == {
        "station_id": "ST-1",
        "run_id": "r-9",
        "sensor_id": "S1",
    }


def test_bind_does_not_mutate_the_parent() -> None:
    sink = RecordingSink()
    parent = Metrics(sink)
    parent.bind(station_id="ST-1")
    parent.add("wim_events_detected_total", 1)
    assert sink.records[-1].attributes == {}


def test_bind_preserves_the_truth_permission() -> None:
    m = Metrics(RecordingSink(), truth_allowed=True).bind(station_id="ST-1")
    m.set("wim_mass_true", 1.0)  # must not raise

    m2 = Metrics(RecordingSink()).bind(station_id="ST-1")
    with pytest.raises(PermissionError):
        m2.set("wim_mass_true", 1.0)


# ------------------------------------------------------------------------------------------
# the OTel path
# ------------------------------------------------------------------------------------------


def test_otel_sink_produces_the_declared_instruments() -> None:
    """The SDK's own reader, no collector.

    Worth a test rather than trusting the API: `create_gauge` is recent, the three instrument
    types take *different* method names for recording a value, and getting one wrong would fail
    only in a deployment where nobody is watching the collector's own error log.
    """
    sdk_metrics = pytest.importorskip("opentelemetry.sdk.metrics")
    export = pytest.importorskip("opentelemetry.sdk.metrics.export")

    from wimsim.observability.metrics import OtelSink

    reader = export.InMemoryMetricReader()
    provider = sdk_metrics.MeterProvider(metric_readers=[reader])
    m = Metrics(OtelSink(provider.get_meter("wimsim")))

    m.add("wim_samples_acquired_total", 7)
    m.set("wim_buffer_depth", 3)
    m.observe("wim_publish_latency_ms", 11.0)
    m.observe("wim_publish_latency_ms", 13.0)

    data = reader.get_metrics_data()
    points = {}
    for rm in data.resource_metrics:
        for sm in rm.scope_metrics:
            for metric in sm.metrics:
                points[metric.name] = next(iter(metric.data.data_points))

    assert points["wim_samples_acquired_total"].value == 7
    assert points["wim_buffer_depth"].value == 3
    assert points["wim_publish_latency_ms"].count == 2
    assert points["wim_publish_latency_ms"].sum == 24.0


def test_otel_sink_reuses_one_instrument_per_name() -> None:
    """Creating an instrument per call would register duplicate series."""
    sdk_metrics = pytest.importorskip("opentelemetry.sdk.metrics")
    export = pytest.importorskip("opentelemetry.sdk.metrics.export")

    from wimsim.observability.metrics import OtelSink

    provider = sdk_metrics.MeterProvider(metric_readers=[export.InMemoryMetricReader()])
    sink = OtelSink(provider.get_meter("wimsim"))
    m = Metrics(sink)
    for _ in range(5):
        m.add("wim_samples_acquired_total", 1)
    assert len(sink._instruments) == 1


def test_resource_attributes_carry_station_and_version() -> None:
    from wimsim import __version__
    from wimsim.observability.resource import resource_attributes

    attrs = resource_attributes(station_id="ST-1", run_id="r-1")
    assert attrs["station_id"] == "ST-1"
    assert attrs["run_id"] == "r-1"
    assert attrs["service.version"] == __version__


# ------------------------------------------------------------------------------------------
# flushing before exit
# ------------------------------------------------------------------------------------------


def test_flush_and_shutdown_are_no_ops_on_the_null_path() -> None:
    """Every CLI command calls them, and most runs have no collector."""
    m = Metrics(NullSink())
    assert m.flush() is False
    m.shutdown()  # must not raise


def test_flush_exports_the_current_interval_rather_than_waiting_for_the_timer() -> None:
    """The bug this exists for: the periodic reader exports on a five-second timer, so a command
    that finishes and exits loses whatever is pending -- the tail of a long run, and *all* of a
    short one, with the process reporting success either way.

    Found while verifying the phase-5 dashboard: the controller's panels read empty immediately
    after a run and had data a couple of minutes later. Nothing was broken except that nobody had
    told the exporter the run was over.
    """
    sdk_metrics = pytest.importorskip("opentelemetry.sdk.metrics")
    export = pytest.importorskip("opentelemetry.sdk.metrics.export")

    from wimsim.observability.metrics import OtelSink

    exported: list = []

    class _Capturing(export.MetricExporter):
        def __init__(self) -> None:
            super().__init__()

        def export(self, metrics_data, timeout_millis=10_000, **kwargs):
            exported.append(metrics_data)
            return export.MetricExportResult.SUCCESS

        def force_flush(self, timeout_millis=10_000):
            return True

        def shutdown(self, timeout_millis=30_000, **kwargs):
            return None

    # An interval far longer than the test, so only an explicit flush can produce an export.
    reader = export.PeriodicExportingMetricReader(_Capturing(), export_interval_millis=600_000)
    provider = sdk_metrics.MeterProvider(metric_readers=[reader])
    m = Metrics(OtelSink(provider.get_meter("wimsim"), provider))

    m.add("wim_events_detected_total", 3)
    assert exported == [], "the timer should not have fired yet"

    assert m.flush() is True
    assert exported, "flush produced no export"
    m.shutdown()


def test_a_bound_child_flushes_the_same_sink() -> None:
    """`bind` returns a new facade over the *same* sink, so a caller holding the child can still
    flush -- which is what the CLI does, since it binds station and run before use."""
    sdk_metrics = pytest.importorskip("opentelemetry.sdk.metrics")
    export = pytest.importorskip("opentelemetry.sdk.metrics.export")

    from wimsim.observability.metrics import OtelSink

    provider = sdk_metrics.MeterProvider(metric_readers=[export.InMemoryMetricReader()])
    parent = Metrics(OtelSink(provider.get_meter("wimsim"), provider))
    child = parent.bind(station_id="ST-1")
    assert child.sink is parent.sink
    assert child.flush() is True
    child.shutdown()
