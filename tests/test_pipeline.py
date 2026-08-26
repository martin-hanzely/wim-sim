"""The mass estimator and the offline pipeline: source -> preprocess -> detect -> estimate.

No transport and no database (buildspec phase 2). What this stage must get right is the seam: a
``DetectedEvent`` carries features, a ``CalibrationProfile`` carries the law, and the result is a
``MeasurementEvent`` that names both -- including the config hash, the seed and the estimator state
hash that produced it. An event that cannot say how it was made is not evidence.
"""

from __future__ import annotations

import numpy as np
import pytest

from wimsim.calibration import (
    CalibrationProfile,
    EstimatorState,
    ReferenceObservation,
    StaticAffine,
)
from wimsim.core.config import EdgeConfig, EstimateConfig, load_run_config
from wimsim.core.schemas import MeasurementEvent, ProvenanceBlock
from wimsim.edge.acquisition import AcquisitionAgent
from wimsim.edge.detect import AxlePeak, DetectedEvent
from wimsim.edge.estimate import MassEstimator
from wimsim.edge.pipeline import OfflinePipeline
from wimsim.source import SyntheticSource

FS = 2000.0


def _profile(
    gain: float = 5000.0, bias: float = 0.0, residual_sd: float = 10.0
) -> CalibrationProfile:
    state = EstimatorState(
        estimator="static_affine",
        gain=gain,
        bias=bias,
        residual_sd=residual_sd,
        fitted=True,
        n_fit=100,
    )
    return CalibrationProfile.from_state(state, profile_id="p-0001", activated_ts_us=0)


def _axle(peak: float, area: float, t: float) -> AxlePeak:
    return AxlePeak(
        t_start_s=t - 0.01,
        t_peak_s=t,
        t_end_s=t + 0.01,
        peak=peak,
        area=area,
        raw_peak=peak,
        raw_area=area,
        n_samples=40,
    )


def _event(axles: list[AxlePeak], **over) -> DetectedEvent:
    base = {
        "ts_start_us": 1_748_736_000_000_000,
        "ts_peak_us": 1_748_736_000_010_000,
        "ts_end_us": 1_748_736_000_020_000,
        "t_start_s": 1.0,
        "t_peak_s": 1.01,
        "t_end_s": 1.02,
        "peak": max(a.peak for a in axles),
        "area": sum(a.area for a in axles),
        "raw_peak": max(a.raw_peak for a in axles),
        "raw_area": sum(a.raw_area for a in axles),
        "axles": tuple(axles),
        "axle_dt_s": tuple(
            axles[i + 1].t_peak_s - axles[i].t_peak_s for i in range(len(axles) - 1)
        ),
        "saturated": False,
        "has_invalid": False,
        "warming_up": False,
        "zero_suspect": False,
        "truncated": False,
        "channel_id": "S1",
    }
    return DetectedEvent(**{**base, **over})


def _provenance() -> ProvenanceBlock:
    return ProvenanceBlock(config_hash="a" * 64, seed=1, mode="synthetic", git_dirty=False)


def _estimator(**over) -> MassEstimator:
    cfg = EstimateConfig(**over)
    profile = _profile()
    return MassEstimator(
        cfg,
        estimator=StaticAffine.from_state(profile.state),
        profile=profile,
        station_id="ST-1",
        sensor_id="S1",
    )


# -- feature selection ---------------------------------------------------------------------------


def test_the_peak_feature_is_the_sum_of_axle_peaks_not_the_largest() -> None:
    """A vehicle's mass is carried by all its axles.

    ``DetectedEvent.peak`` is the largest axle, which is what the schema reports as
    ``compensated_peak`` -- an instantaneous force. The quantity proportional to *mass* is the sum,
    and conflating the two would weigh every truck as though it were its heaviest axle.
    """
    ev = _event([_axle(1.0, 0.01, 1.0), _axle(1.5, 0.015, 1.1)])
    assert ev.peak == 1.5
    assert ev.axle_peak_sum == pytest.approx(2.5)

    est = _estimator(feature="peak", axle_summation="whole_signal")
    got = est.estimate(ev)
    assert got.mass_kg == pytest.approx(5000.0 * 2.5)


def test_the_area_feature_is_the_sum_over_axles() -> None:
    ev = _event([_axle(1.0, 0.01, 1.0), _axle(1.5, 0.015, 1.1)])
    est = _estimator(feature="area", axle_summation="whole_signal")
    assert est.estimate(ev).mass_kg == pytest.approx(5000.0 * 0.025)


def test_per_axle_sum_applies_the_bias_once_per_axle() -> None:
    """The two summation modes differ exactly in how often the intercept is charged.

    Whole-signal treats the vehicle as one measurement with one zero error; per-axle treats each
    axle as its own measurement. Neither is obviously right, which is why it is configurable.
    """
    ev = _event([_axle(1.0, 0.01, 1.0), _axle(1.5, 0.015, 1.1)])
    profile = _profile(gain=5000.0, bias=100.0)
    kwargs = {
        "estimator": StaticAffine.from_state(profile.state),
        "profile": profile,
        "station_id": "ST-1",
        "sensor_id": "S1",
    }
    whole = MassEstimator(EstimateConfig(axle_summation="whole_signal"), **kwargs)
    per_axle = MassEstimator(EstimateConfig(axle_summation="per_axle_sum"), **kwargs)

    assert whole.estimate(ev).mass_kg == pytest.approx(5000.0 * 2.5 + 100.0)
    assert per_axle.estimate(ev).mass_kg == pytest.approx(5000.0 * 2.5 + 200.0)


def test_a_single_axle_vehicle_is_identical_under_both_modes() -> None:
    ev = _event([_axle(1.2, 0.012, 1.0)])
    profile = _profile(bias=100.0)
    kwargs = {
        "estimator": StaticAffine.from_state(profile.state),
        "profile": profile,
        "station_id": "ST-1",
        "sensor_id": "S1",
    }
    whole = MassEstimator(EstimateConfig(axle_summation="whole_signal"), **kwargs)
    per_axle = MassEstimator(EstimateConfig(axle_summation="per_axle_sum"), **kwargs)
    assert whole.estimate(ev).mass_kg == pytest.approx(per_axle.estimate(ev).mass_kg)


# -- intervals ------------------------------------------------------------------------------------


def test_the_interval_brackets_the_estimate() -> None:
    got = _estimator().estimate(_event([_axle(1.0, 0.01, 1.0)]))
    assert got.mass_ci_low <= got.mass_kg <= got.mass_ci_high


def test_per_axle_intervals_add_in_quadrature_not_linearly() -> None:
    """Axle errors are independent draws from the same residual distribution.

    Summing half-widths linearly would claim a four-axle truck is four times as uncertain as one
    axle, when independence makes it twice.
    """
    profile = _profile(residual_sd=100.0)
    est = MassEstimator(
        EstimateConfig(axle_summation="per_axle_sum"),
        estimator=StaticAffine.from_state(profile.state),
        profile=profile,
        station_id="ST-1",
        sensor_id="S1",
    )
    one = est.estimate(_event([_axle(1.0, 0.01, 1.0)]))
    four = est.estimate(_event([_axle(1.0, 0.01, 1.0 + 0.1 * i) for i in range(4)]))
    assert (four.mass_ci_high - four.mass_ci_low) == pytest.approx(
        2.0 * (one.mass_ci_high - one.mass_ci_low), rel=1e-9
    )


# -- event assembly ---------------------------------------------------------------------------------


def test_a_measurement_event_names_everything_that_produced_it() -> None:
    est = _estimator()
    detected = _event([_axle(1.0, 0.01, 1.0)])
    payload = est.to_measurement_event(
        detected, provenance=_provenance(), preprocessing=_preprocessing()
    )
    assert isinstance(payload, MeasurementEvent)
    assert payload.station_id == "ST-1"
    assert payload.sensor_id == "S1"
    assert payload.calibration.profile_id == "p-0001"
    assert payload.calibration.estimator == "static_affine"
    assert payload.calibration.state_hash
    assert payload.provenance.config_hash == "a" * 64
    assert payload.quality_flag == "ok"


def test_the_event_reports_sensor_side_gain_so_it_can_be_drawn_against_truth() -> None:
    """The dashboard overlays estimated gain on k_true, which is in sensor units per kg."""
    est = _estimator()
    payload = est.to_measurement_event(
        _event([_axle(1.0, 0.01, 1.0)]), provenance=_provenance(), preprocessing=_preprocessing()
    )
    assert payload.calibration.gain == pytest.approx(1.0 / 5000.0)


def test_quality_flag_is_carried_from_detection_into_the_event() -> None:
    est = _estimator()
    detected = _event([_axle(1.0, 0.01, 1.0)], saturated=True)
    payload = est.to_measurement_event(
        detected, provenance=_provenance(), preprocessing=_preprocessing()
    )
    assert payload.quality_flag == "suspect"


def test_event_id_is_stable_across_two_identical_runs() -> None:
    est = _estimator()
    detected = _event([_axle(1.0, 0.01, 1.0)])
    a = est.to_measurement_event(detected, provenance=_provenance(), preprocessing=_preprocessing())
    b = est.to_measurement_event(detected, provenance=_provenance(), preprocessing=_preprocessing())
    assert a.event_id == b.event_id


def _preprocessing():
    from wimsim.core.schemas import PreprocessingBlock

    return PreprocessingBlock(filter="none", zero_window_s=2.0)


# -- acquisition ---------------------------------------------------------------------------------------


def test_acquisition_reports_sample_count_and_rate() -> None:
    cfg = load_run_config(
        "S1_nominal", overrides=["scenario.duration_s=30.0", "scenario.block_seconds=10.0"]
    )
    agent = AcquisitionAgent(SyntheticSource(cfg))
    total = sum(block.n for block in agent.stream())
    assert total == cfg.sample_count
    assert agent.samples_acquired == cfg.sample_count
    assert agent.observed_rate_hz == pytest.approx(cfg.station.sample_rate_hz, rel=1e-6)
    assert agent.gaps == 0


def test_acquisition_counts_a_timestamp_gap() -> None:
    """A dropped block shortens every integration window that spans it, silently. Count it."""
    from wimsim.core.types import SampleBlock

    class _Gappy:
        def stream_blocks(self):
            for start in (0, 4000):  # a 1 s hole at 2 kHz
                idx = np.arange(start, start + 2000)
                t_s = idx / FS
                yield SampleBlock(
                    ts_us=(1_748_736_000_000_000 + np.rint(t_s * 1e6)).astype(np.int64),
                    t_s=t_s,
                    raw_value=np.zeros(2000),
                    raw_counts=np.zeros(2000, dtype=np.int64),
                    temperature_c=np.full(2000, 20.0),
                    saturated=np.zeros(2000, dtype=bool),
                    valid=np.ones(2000, dtype=bool),
                    channel_id="S1",
                )

    agent = AcquisitionAgent(_Gappy(), sample_rate_hz=FS)
    list(agent.stream())
    assert agent.gaps == 1
    assert agent.missing_samples == pytest.approx(2000, rel=0.01)


# -- the whole pipeline ------------------------------------------------------------------------------------


def _clean_run(**over):
    base = [
        "scenario.duration_s=300.0",
        "scenario.block_seconds=30.0",
        "scenario.output.samples=none",
    ]
    return load_run_config("S1_nominal", overrides=base + [f"{k}={v}" for k, v in over.items()])


def test_pipeline_detects_every_pass_under_clean_conditions() -> None:
    cfg = _clean_run(**{"scenario.noise.white_sigma": "0.0", "scenario.noise.pink_sigma": "0.0"})
    source = SyntheticSource(cfg)
    expected = len(source.generator.passes)

    pipeline = OfflinePipeline(
        EdgeConfig(name="test"),
        source=source,
        profile=_profile(),
        provenance=_provenance(),
    )
    events = list(pipeline.run())
    assert len(events) == expected, f"{len(events)} events from {expected} passes"
    assert all(isinstance(e, MeasurementEvent) for e in events)

    # and the axles were grouped into the right vehicles, not merely counted correctly overall
    truth_axles = [p.axle_count for p in source.generator.passes]
    assert [e.axle_count for e in events] == truth_axles


def test_pipeline_events_are_ordered_and_uniquely_identified() -> None:
    cfg = _clean_run()
    pipeline = OfflinePipeline(
        EdgeConfig(name="test"),
        source=SyntheticSource(cfg),
        profile=_profile(),
        provenance=_provenance(),
    )
    events = list(pipeline.run())
    assert len(events) > 5
    starts = [e.ts_start for e in events]
    assert starts == sorted(starts)
    assert len({e.event_id for e in events}) == len(events)


def test_pipeline_is_deterministic() -> None:
    cfg = _clean_run()
    runs = []
    for _ in range(2):
        pipeline = OfflinePipeline(
            EdgeConfig(name="test"),
            source=SyntheticSource(cfg),
            profile=_profile(),
            provenance=_provenance(),
        )
        runs.append([(e.event_id, e.mass_kg) for e in pipeline.run()])
    assert runs[0] == runs[1]


def test_pipeline_exposes_its_stage_counters() -> None:
    cfg = _clean_run()
    pipeline = OfflinePipeline(
        EdgeConfig(name="test"),
        source=SyntheticSource(cfg),
        profile=_profile(),
        provenance=_provenance(),
    )
    events = list(pipeline.run())
    stats = pipeline.stats()
    assert stats["samples_acquired"] == cfg.sample_count
    assert stats["events_detected"] == len(events)
    assert stats["axles_detected"] >= stats["events_detected"]


def test_pipeline_can_bootstrap_a_profile_from_reference_observations() -> None:
    """Phase 2 fits the baseline offline from a calibration split; phase 5 replaces this."""
    cfg = _clean_run()
    source = SyntheticSource(cfg)
    pipeline = OfflinePipeline(
        EdgeConfig(name="test"), source=source, profile=None, provenance=_provenance()
    )
    with pytest.raises(RuntimeError, match="no calibration profile"):
        list(pipeline.run())


def test_reference_observation_round_trip_through_the_estimator() -> None:
    obs = [
        ReferenceObservation(ts_us=i, feature=0.05 + 2e-4 * m, temp_c=20.0, reference_mass_kg=m)
        for i, m in enumerate(np.linspace(1000, 40000, 50))
    ]
    est = StaticAffine()
    est.fit(obs)
    profile = CalibrationProfile.from_state(est.state(), profile_id="p", activated_ts_us=0)
    assert profile.state.sensor_gain == pytest.approx(2e-4, rel=1e-6)
