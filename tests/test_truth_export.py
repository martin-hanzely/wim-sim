"""The truth overlay exporter.

Buildspec section 9: ``wim_cal_gain_true``, ``wim_cal_bias_true``, ``wim_temperature_true`` and
``wim_mass_true``, carrying ``source="truth"``, "emitted by a separate exporter that reads the truth
log -- **never** by the estimator path".

Two things are being pinned.

**Where it lives.** ``observability/`` is quarantined from ``wimsim.signal`` by
``test_truth_isolation.py``, and must stay that way, because the edge imports it. So the exporter
lives in ``experiments/`` -- already the designated truth-joining layer, and already outside the
quarantine -- while ``observability/`` holds only the registry that refuses to emit these metrics
unless the caller declares itself the exporter.

**That the overlay is on the same axes as the estimate.** A truth gain of 2e-4 plotted against a
prediction gain of 5000 is a panel that looks broken rather than one that looks wrong, and it is the
sort of thing that survives review. ``calibration/base.py`` already fixed the convention: the
dashboard draws sensor-side, ``k_true`` and ``q_true`` directly, with the estimator inverting via
``sensor_gain``/``sensor_bias``. The test below is what keeps that true.
"""

from __future__ import annotations

import pandas as pd
import pytest

from wimsim.calibration import EstimatorState
from wimsim.experiments.truth_export import TruthExporter, build_truth_metrics
from wimsim.observability.metrics import Metrics, NullSink, RecordingSink


@pytest.fixture
def timeseries() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "t_s": [0.0, 1.0, 2.0],
            "ts_us": [1_748_736_000_000_000, 1_748_736_001_000_000, 1_748_736_002_000_000],
            "q_true": [0.050, 0.051, 0.052],
            "k_true": [2.0e-4, 2.1e-4, 2.2e-4],
            "alpha_true": [-2.0e-4] * 3,
            "t_sensor_true": [20.0, 21.0, 22.0],
            "t_ambient_true": [20.0, 20.5, 21.0],
            "clock_offset_s": [0.0] * 3,
            "active_faults": ["", "", ""],
        }
    )


@pytest.fixture
def passes() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "pass_id": ["p-1", "p-2"],
            "pass_index": [0, 1],
            "vehicle_class": ["car", "truck"],
            "t_entry_s": [0.5, 1.5],
            "t_exit_s": [0.7, 1.7],
            "t_peak_s": [0.6, 1.6],
            "ts_peak_us": [1_748_736_000_600_000, 1_748_736_001_600_000],
            "true_mass_kg": [1500.0, 18000.0],
            "applied_mass_kg": [1505.0, 18100.0],
            "axle_count": [2, 3],
            "speed_mps": [20.0, 22.0],
        }
    )


def _exporter(sink=None) -> tuple[TruthExporter, RecordingSink]:
    sink = sink or RecordingSink()
    metrics = Metrics(sink, truth_allowed=True).bind(station_id="ST-1", run_id="r-1")
    return TruthExporter(metrics), sink


# ------------------------------------------------------------------------------------------
# the four truth metrics
# ------------------------------------------------------------------------------------------


def test_the_plant_state_is_exported_as_a_time_series(timeseries) -> None:
    exporter, sink = _exporter()
    assert exporter.export_timeseries(timeseries) == 3

    assert sink.values("wim_cal_gain_true") == [2.0e-4, 2.1e-4, 2.2e-4]
    assert sink.values("wim_cal_bias_true") == [0.050, 0.051, 0.052]
    assert sink.values("wim_temperature_true") == [20.0, 21.0, 22.0]


def test_true_masses_are_exported_per_pass(passes) -> None:
    exporter, sink = _exporter()
    assert exporter.export_passes(passes) == 2
    assert sink.values("wim_mass_true") == [1500.0, 18000.0]


def test_every_truth_point_is_labelled_source_truth(timeseries, passes) -> None:
    """The label is how a dashboard tells the overlay from the estimate, and how a reviewer can
    satisfy themselves that no truth series reached Prometheus by another route."""
    exporter, sink = _exporter()
    exporter.export_timeseries(timeseries)
    exporter.export_passes(passes)
    assert all(r.attributes["source"] == "truth" for r in sink.records)


def test_the_vehicle_class_travels_with_the_mass(passes) -> None:
    """Per-class accuracy is a headline result; a mass with no class cannot contribute to it."""
    exporter, sink = _exporter()
    exporter.export_passes(passes)
    classes = [r.attributes["vehicle_class"] for r in sink.records if r.name == "wim_mass_true"]
    assert classes == ["car", "truck"]


# ------------------------------------------------------------------------------------------
# principle 1
# ------------------------------------------------------------------------------------------


def test_the_exporter_refuses_a_registry_that_is_not_allowed_truth(timeseries) -> None:
    """Constructing it with an estimator-path registry is a programming error, and one worth
    catching at construction rather than at the first data point."""
    with pytest.raises(PermissionError, match="truth"):
        TruthExporter(Metrics(RecordingSink()))


def test_build_truth_metrics_is_the_only_thing_that_turns_the_permission_on() -> None:
    metrics = build_truth_metrics(station_id="ST-1", run_id="r-1", endpoint=None)
    assert metrics.truth_allowed
    assert isinstance(metrics.sink, NullSink)  # no collector configured in the test environment


def test_the_exporter_is_not_importable_from_the_edge() -> None:
    """The structural half of the argument: experiments/ may read the truth log because nothing on
    the measurement path imports it. If that ever stops being true, this fails."""
    import ast
    import pathlib

    root = pathlib.Path(__file__).resolve().parents[1] / "src" / "wimsim"
    offenders = []
    for path in list((root / "edge").rglob("*.py")) + list((root / "calibration").rglob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and (node.module or "").startswith(
                "wimsim.experiments"
            ):
                offenders.append(path.name)
            if isinstance(node, ast.Import):
                offenders += [
                    path.name for a in node.names if a.name.startswith("wimsim.experiments")
                ]
    assert offenders == []


# ------------------------------------------------------------------------------------------
# the overlay has to be on the estimate's axes
# ------------------------------------------------------------------------------------------


def test_the_truth_overlay_and_the_estimate_use_the_same_convention() -> None:
    """A truth gain of 2e-4 drawn against a prediction gain of 5000 is a panel that looks broken
    rather than wrong, and that kind of mistake survives review.

    calibration/base.py already settled it: the dashboard is sensor-side, so `k_true` and `q_true`
    go out untouched and the estimator inverts.
    """
    from wimsim.experiments.truth_export import estimate_metrics

    # A plant with k = 2e-4 sensor units per kg and q = 0.05. An estimator that has learned it
    # exactly holds the inverse.
    state = EstimatorState(
        estimator="static_affine",
        gain=1.0 / 2.0e-4,
        bias=-0.05 / 2.0e-4,
        fitted=True,
    )
    sink = RecordingSink()
    estimate_metrics(Metrics(sink), state)

    assert sink.values("wim_cal_gain_estimate") == pytest.approx([2.0e-4])
    assert sink.values("wim_cal_bias_estimate") == pytest.approx([0.05])


def test_the_estimate_metrics_do_not_need_the_truth_permission() -> None:
    """They are emitted by the edge, every time a profile is activated."""
    sink = RecordingSink()
    estimate_metrics_fn = __import__(
        "wimsim.experiments.truth_export", fromlist=["estimate_metrics"]
    ).estimate_metrics
    estimate_metrics_fn(
        Metrics(sink), EstimatorState(estimator="static_affine", gain=2.0, bias=1.0)
    )
    assert sink.values("wim_cal_update_count") == [0.0]


# ------------------------------------------------------------------------------------------
# quality metrics, which need truth and so live here too
# ------------------------------------------------------------------------------------------


class _Event:
    def __init__(self, event_id, ts_start, ts_peak, ts_end, mass, low, high):
        self.event_id = event_id
        self.ts_start, self.ts_peak, self.ts_end = ts_start, ts_peak, ts_end
        self.mass_kg, self.mass_ci_low, self.mass_ci_high = mass, low, high
        self.axle_count = 2
        self.quality_flag = "ok"


def _events() -> list[_Event]:
    return [
        _Event(
            "e-1",
            1_748_736_000_500_000,
            1_748_736_000_600_000,
            1_748_736_000_700_000,
            1650.0,
            1400.0,
            1900.0,
        ),
        _Event(
            "e-2",
            1_748_736_001_500_000,
            1_748_736_001_600_000,
            1_748_736_001_700_000,
            18000.0,
            17000.0,
            19000.0,
        ),
    ]


def test_absolute_and_relative_error_are_exported_per_matched_pass(passes) -> None:
    exporter, sink = _exporter()
    assert exporter.export_quality(_events(), passes) == 2

    assert sink.values("wim_mass_abs_error") == pytest.approx([150.0, 0.0])
    assert sink.values("wim_mass_rel_error") == pytest.approx([0.1, 0.0])


def test_rolling_coverage_is_exported_and_is_a_running_fraction(passes) -> None:
    """The 1500 kg pass is estimated at 1650 with an interval of [1400, 1900] -- covered. Both are,
    so the fraction is 1.0 after each."""
    exporter, sink = _exporter()
    exporter.export_quality(_events(), passes)
    assert sink.values("wim_coverage_rolling") == pytest.approx([1.0, 1.0])


def test_a_missed_interval_pulls_the_rolling_coverage_down(passes) -> None:
    events = _events()
    events[0].mass_ci_low, events[0].mass_ci_high = 1640.0, 1660.0  # excludes the true 1500
    exporter, sink = _exporter()
    exporter.export_quality(events, passes)
    assert sink.values("wim_coverage_rolling") == pytest.approx([0.0, 0.5])


def test_an_unmatched_event_contributes_no_error(passes) -> None:
    """A false positive has no reference mass. Scoring it against the nearest pass would invent an
    error; it is counted as a false positive elsewhere and left out of the histogram here."""
    events = _events()
    events.append(
        _Event(
            "e-3",
            1_748_736_050_000_000,
            1_748_736_050_100_000,
            1_748_736_050_200_000,
            9000.0,
            8000.0,
            10000.0,
        )
    )
    exporter, sink = _exporter()
    assert exporter.export_quality(events, passes) == 2
    assert len(sink.values("wim_mass_abs_error")) == 2


def test_quality_export_needs_no_truth_permission_but_gets_one_anyway(passes) -> None:
    """Absolute error is not itself a truth value, but computing it requires reading the truth log,
    so it is emitted from here and nowhere else. Documented by the test rather than by a comment
    that could drift."""
    metrics = Metrics(RecordingSink())  # truth_allowed False
    exporter = TruthExporter(metrics, require_truth_permission=False)
    assert exporter.export_quality(_events(), passes) == 2
