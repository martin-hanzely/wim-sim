"""The event detector: dual-threshold hysteresis, and the features it hands downstream.

The detector is where a continuous signal becomes a countable thing, so its failure modes are the
expensive kind: a missed axle is a missing vehicle, a spurious one is a phantom, and a merged pair
is a truck that weighs twice what it should.

Both **peak** and **area** are emitted. Which one estimates mass better under noise is an
experimental question the buildspec explicitly refuses to pre-decide, so the detector's job is to
produce both honestly rather than to pick.
"""

from __future__ import annotations

import numpy as np
import pytest

from wimsim.core.config import DetectConfig
from wimsim.edge.detect import EventDetector
from wimsim.edge.preprocess import PreprocessedBlock

FS = 2000.0


def _pre(
    compensated: np.ndarray,
    *,
    start_index: int = 0,
    valid: np.ndarray | None = None,
    saturated: np.ndarray | None = None,
    warming_up: np.ndarray | None = None,
    zero_suspect: np.ndarray | None = None,
) -> PreprocessedBlock:
    n = compensated.size
    idx = np.arange(start_index, start_index + n)
    t_s = idx / FS
    zeros = np.zeros(n, dtype=bool)
    zero_line = np.full(n, 0.05)
    return PreprocessedBlock(
        ts_us=(1_748_736_000_000_000 + np.rint(t_s * 1e6)).astype(np.int64),
        t_s=t_s,
        raw_value=compensated + zero_line,
        filtered_value=compensated + zero_line,
        zero_estimate=zero_line,
        compensated_value=compensated,
        temperature_c=np.full(n, 20.0),
        valid=np.ones(n, dtype=bool) if valid is None else valid,
        saturated=zeros if saturated is None else saturated,
        despiked=zeros,
        warming_up=zeros if warming_up is None else warming_up,
        zero_suspect=zeros if zero_suspect is None else zero_suspect,
        temp_missing=zeros,
        channel_id="S1",
    )


def _gauss(n: int, *, at: float, fwhm_s: float, amplitude: float) -> np.ndarray:
    t = np.arange(n) / FS
    sigma = fwhm_s / 2.3548200450309493
    return amplitude * np.exp(-0.5 * ((t - at) / sigma) ** 2)


def _cfg(**over) -> DetectConfig:
    """Axle-level by default.

    ``merge_gap_s`` is 0 here even though the shipped default groups axles into vehicles: most of
    this file is about what one threshold excursion does, and grouping would hide it. The tests
    that care about grouping set it explicitly.
    """
    base = {
        "start_threshold": 0.1,
        "end_threshold": 0.03,
        "min_duration_s": 0.001,
        "max_duration_s": 2.0,
        "merge_gap_s": 0.0,
    }
    return DetectConfig(**{**base, **over})


def _run(detector: EventDetector, blocks: list[PreprocessedBlock]) -> list:
    out = []
    for b in blocks:
        out.extend(detector.process(b))
    out.extend(detector.flush())
    return out


# -- basic detection ---------------------------------------------------------------------------


def test_a_single_pulse_produces_a_single_event() -> None:
    det = EventDetector(_cfg(), sample_rate_hz=FS)
    x = _gauss(4000, at=1.0, fwhm_s=0.01, amplitude=1.5)
    events = _run(det, [_pre(x)])
    assert len(events) == 1
    ev = events[0]
    assert ev.t_start_s < 1.0 < ev.t_end_s
    assert ev.t_peak_s == pytest.approx(1.0, abs=1 / FS)
    assert ev.axle_count == 1


def test_quiet_signal_produces_nothing() -> None:
    det = EventDetector(_cfg(), sample_rate_hz=FS)
    rng = np.random.default_rng(0)
    assert _run(det, [_pre(2e-4 * rng.standard_normal(20_000))]) == []


def test_a_pulse_below_the_start_threshold_is_ignored() -> None:
    det = EventDetector(_cfg(start_threshold=1.0, end_threshold=0.5), sample_rate_hz=FS)
    assert _run(det, [_pre(_gauss(4000, at=1.0, fwhm_s=0.01, amplitude=0.5))]) == []


def _hovering(n: int = 8000, *, seed: int = 1) -> np.ndarray:
    """An excursion that sits right on the start threshold, so a single-threshold detector chatters."""
    rng = np.random.default_rng(seed)
    x = np.zeros(n)
    x[2000:6000] = 0.1 + 0.02 * rng.standard_normal(4000)
    return x


def test_hysteresis_beats_a_single_threshold_by_orders_of_magnitude() -> None:
    """A signal hovering at the start threshold crosses it on half of all samples.

    With the two thresholds collapsed together, that is thousands of phantom axles from one
    excursion. The gap between them is what makes the detector usable at all.
    """
    narrow = EventDetector(
        _cfg(start_threshold=0.1, end_threshold=0.0999, end_hold_s=0.0), sample_rate_hz=FS
    )
    wide = EventDetector(
        _cfg(start_threshold=0.1, end_threshold=0.03, end_hold_s=0.0), sample_rate_hz=FS
    )
    assert len(_run(narrow, [_pre(_hovering())])) > 100
    assert len(_run(wide, [_pre(_hovering())])) < 5


def test_the_end_hold_debounce_closes_the_remaining_gap() -> None:
    """Hysteresis makes a spurious split rare; it does not make it impossible.

    At a 3.5-sigma gap a single sample still dips past the lower threshold every few thousand
    samples, splitting one axle into two -- and a split axle is a vehicle counted twice. Requiring
    the signal to stay below for a couple of milliseconds removes it.
    """
    without = EventDetector(
        _cfg(start_threshold=0.1, end_threshold=0.03, end_hold_s=0.0), sample_rate_hz=FS
    )
    with_hold = EventDetector(
        _cfg(start_threshold=0.1, end_threshold=0.03, end_hold_s=0.002), sample_rate_hz=FS
    )
    assert len(_run(without, [_pre(_hovering())])) > 1
    assert len(_run(with_hold, [_pre(_hovering())])) == 1


def test_minimum_duration_rejects_a_blip() -> None:
    det = EventDetector(_cfg(min_duration_s=0.005), sample_rate_hz=FS)
    x = np.zeros(4000)
    x[2000:2002] = 1.0  # 1 ms
    assert _run(det, [_pre(x)]) == []


def test_maximum_duration_rejects_a_stuck_channel() -> None:
    """A channel stuck high is not a vehicle that took four seconds to cross."""
    det = EventDetector(_cfg(max_duration_s=0.5), sample_rate_hz=FS)
    x = np.zeros(20_000)
    x[2000:18000] = 1.0  # 8 s
    events = _run(det, [_pre(x)])
    assert events == []
    assert det.rejected_too_long == 1


def test_refractory_suppresses_a_retrigger() -> None:
    det = EventDetector(_cfg(refractory_s=0.5), sample_rate_hz=FS)
    x = _gauss(8000, at=1.0, fwhm_s=0.01, amplitude=1.5) + _gauss(
        8000, at=1.2, fwhm_s=0.01, amplitude=1.5
    )
    events = _run(det, [_pre(x)])
    assert len(events) == 1


# -- features -----------------------------------------------------------------------------------


def test_peak_is_recovered_to_better_than_a_tenth_of_a_percent_with_interpolation() -> None:
    """Phase 1 measured that discrete peak-picking cannot reach 0.1 % at 2 kHz. This is the fix."""
    amplitude = 1.5
    worst = 0.0
    for offset in np.linspace(0.0, 1.0, 11):  # slide the peak between two samples
        det = EventDetector(_cfg(subsample_peak=True), sample_rate_hz=FS)
        x = _gauss(4000, at=1.0 + offset / FS, fwhm_s=0.005, amplitude=amplitude)
        ev = _run(det, [_pre(x)])[0]
        worst = max(worst, abs(ev.peak - amplitude) / amplitude)
    assert worst < 1e-3, f"worst interpolated peak error {worst:.3%}"


def test_without_interpolation_the_peak_is_systematically_low() -> None:
    amplitude = 1.5
    det = EventDetector(_cfg(subsample_peak=False), sample_rate_hz=FS)
    x = _gauss(4000, at=1.0 + 0.5 / FS, fwhm_s=0.005, amplitude=amplitude)
    ev = _run(det, [_pre(x)])[0]
    assert ev.peak < amplitude
    assert (amplitude - ev.peak) / amplitude > 1e-3


def test_peak_time_is_interpolated_too() -> None:
    det = EventDetector(_cfg(subsample_peak=True), sample_rate_hz=FS)
    true_t = 1.0 + 0.5 / FS
    ev = _run(det, [_pre(_gauss(4000, at=true_t, fwhm_s=0.005, amplitude=1.5))])[0]
    assert ev.t_peak_s == pytest.approx(true_t, abs=0.2 / FS)


def test_area_is_close_to_the_analytic_integral() -> None:
    """A unit-peak Gaussian integrates to sigma*sqrt(2*pi) = 1.0645 * FWHM."""
    amplitude, fwhm = 1.5, 0.02
    det = EventDetector(_cfg(area_pad_widths=1.0), sample_rate_hz=FS)
    ev = _run(det, [_pre(_gauss(8000, at=1.0, fwhm_s=fwhm, amplitude=amplitude))])[0]
    analytic = amplitude * fwhm * np.sqrt(2 * np.pi) / 2.3548200450309493
    assert ev.area == pytest.approx(analytic, rel=0.05)


def test_area_scales_with_pulse_width_and_peak_does_not() -> None:
    """The whole peak-versus-area question in one test: peak is speed-invariant, area is not."""
    amplitude = 1.5
    peaks, areas = [], []
    for fwhm in (0.01, 0.02):
        det = EventDetector(_cfg(area_pad_widths=1.0), sample_rate_hz=FS)
        ev = _run(det, [_pre(_gauss(8000, at=1.0, fwhm_s=fwhm, amplitude=amplitude))])[0]
        peaks.append(ev.peak)
        areas.append(ev.area)
    assert peaks[0] == pytest.approx(peaks[1], rel=2e-3)
    assert areas[1] == pytest.approx(2 * areas[0], rel=0.05)


def test_raw_features_are_baseline_removed_but_not_temperature_compensated() -> None:
    det = EventDetector(_cfg(), sample_rate_hz=FS)
    x = _gauss(4000, at=1.0, fwhm_s=0.01, amplitude=1.5)
    ev = _run(det, [_pre(x)])[0]
    # the fixture's compensated == filtered - zero, so the two must agree here
    assert ev.raw_peak == pytest.approx(ev.peak, rel=1e-9)
    assert ev.raw_area == pytest.approx(ev.area, rel=1e-9)


# -- multi-axle ------------------------------------------------------------------------------------


def test_two_close_axles_merge_into_one_vehicle() -> None:
    det = EventDetector(_cfg(merge_gap_s=0.3), sample_rate_hz=FS)
    x = _gauss(8000, at=1.0, fwhm_s=0.01, amplitude=1.2) + _gauss(
        8000, at=1.15, fwhm_s=0.01, amplitude=1.4
    )
    events = _run(det, [_pre(x)])
    assert len(events) == 1
    ev = events[0]
    assert ev.axle_count == 2
    assert ev.peak == pytest.approx(1.4, rel=2e-3), "vehicle peak is the largest axle"
    assert [a.peak for a in ev.axles] == pytest.approx([1.2, 1.4], rel=2e-3)
    assert ev.axle_dt_s[0] == pytest.approx(0.15, abs=2 / FS)


def test_distant_axles_stay_separate_vehicles() -> None:
    det = EventDetector(_cfg(merge_gap_s=0.3), sample_rate_hz=FS)
    x = _gauss(16000, at=1.0, fwhm_s=0.01, amplitude=1.2) + _gauss(
        16000, at=5.0, fwhm_s=0.01, amplitude=1.4
    )
    events = _run(det, [_pre(x)])
    assert len(events) == 2
    assert all(e.axle_count == 1 for e in events)


def test_vehicle_area_is_the_sum_over_its_axles() -> None:
    det = EventDetector(_cfg(merge_gap_s=0.3, area_pad_widths=0.5), sample_rate_hz=FS)
    x = _gauss(8000, at=1.0, fwhm_s=0.01, amplitude=1.2) + _gauss(
        8000, at=1.15, fwhm_s=0.01, amplitude=1.4
    )
    ev = _run(det, [_pre(x)])[0]
    assert ev.area == pytest.approx(sum(a.area for a in ev.axles), rel=1e-9)


def test_merging_is_not_confused_by_a_block_boundary() -> None:
    det = EventDetector(_cfg(merge_gap_s=0.3), sample_rate_hz=FS)
    x = _gauss(8000, at=1.0, fwhm_s=0.01, amplitude=1.2) + _gauss(
        8000, at=1.15, fwhm_s=0.01, amplitude=1.4
    )
    # split right between the two axles
    blocks = [_pre(x[:2200]), _pre(x[2200:], start_index=2200)]
    events = _run(det, blocks)
    assert len(events) == 1
    assert events[0].axle_count == 2


# -- block boundaries --------------------------------------------------------------------------------


@pytest.mark.parametrize("split", [1900, 2000, 2050, 2100])
def test_a_pulse_straddling_a_block_boundary_is_detected_once(split: int) -> None:
    x = _gauss(4000, at=1.0, fwhm_s=0.01, amplitude=1.5)
    whole = _run(EventDetector(_cfg(), sample_rate_hz=FS), [_pre(x)])
    chunked = _run(
        EventDetector(_cfg(), sample_rate_hz=FS),
        [_pre(x[:split]), _pre(x[split:], start_index=split)],
    )
    assert len(chunked) == 1
    assert chunked[0].t_peak_s == pytest.approx(whole[0].t_peak_s, abs=1e-9)
    assert chunked[0].peak == pytest.approx(whole[0].peak, rel=1e-9)
    assert chunked[0].area == pytest.approx(whole[0].area, rel=1e-6)


def test_results_do_not_depend_on_block_size() -> None:
    rng = np.random.default_rng(2)
    x = 5e-4 * rng.standard_normal(40_000)
    for at in (2.0, 5.0, 11.0, 17.5):
        x += _gauss(40_000, at=at, fwhm_s=0.01, amplitude=1.0 + at / 10)

    reference = _run(EventDetector(_cfg(), sample_rate_hz=FS), [_pre(x)])
    for size in (1000, 4096, 20_000):
        det = EventDetector(_cfg(), sample_rate_hz=FS)
        blocks = [_pre(x[i : i + size], start_index=i) for i in range(0, x.size, size)]
        got = _run(det, blocks)
        assert len(got) == len(reference)
        for a, b in zip(got, reference, strict=True):
            assert a.t_peak_s == pytest.approx(b.t_peak_s, abs=1e-9)
            assert a.peak == pytest.approx(b.peak, rel=1e-9)
            assert a.area == pytest.approx(b.area, rel=1e-6)


def test_an_open_window_at_end_of_stream_is_flushed_not_lost() -> None:
    det = EventDetector(_cfg(), sample_rate_hz=FS)
    # the stream ends at t = 1.1 s, right on the peak, so the window is still open
    x = _gauss(2200, at=1.1, fwhm_s=0.01, amplitude=1.5)
    events = _run(det, [_pre(x)])
    assert len(events) == 1
    assert events[0].truncated
    assert events[0].quality_flag == "suspect"


def test_flush_is_idempotent() -> None:
    det = EventDetector(_cfg(), sample_rate_hz=FS)
    during = det.process(_pre(_gauss(4000, at=1.0, fwhm_s=0.01, amplitude=1.5)))
    first = det.flush()
    assert det.flush() == []
    assert len(during) + len(first) == 1, "the event must be emitted exactly once, somewhere"


# -- quality ------------------------------------------------------------------------------------------


def test_saturation_inside_a_window_is_reported() -> None:
    det = EventDetector(_cfg(), sample_rate_hz=FS)
    x = _gauss(4000, at=1.0, fwhm_s=0.01, amplitude=1.5)
    sat = np.zeros(4000, dtype=bool)
    sat[1995:2005] = True
    ev = _run(det, [_pre(x, saturated=sat)])[0]
    assert ev.saturated
    assert ev.quality_flag == "suspect"


def test_invalid_samples_inside_a_window_are_reported() -> None:
    det = EventDetector(_cfg(), sample_rate_hz=FS)
    x = _gauss(4000, at=1.0, fwhm_s=0.01, amplitude=1.5)
    valid = np.ones(4000, dtype=bool)
    valid[1995:2005] = False
    ev = _run(det, [_pre(x, valid=valid)])[0]
    assert ev.has_invalid
    assert ev.quality_flag == "suspect"


def test_a_warming_up_zero_line_degrades_rather_than_invalidates() -> None:
    det = EventDetector(_cfg(), sample_rate_hz=FS)
    x = _gauss(4000, at=1.0, fwhm_s=0.01, amplitude=1.5)
    warming = np.ones(4000, dtype=bool)
    ev = _run(det, [_pre(x, warming_up=warming)])[0]
    assert ev.quality_flag == "degraded"


def test_a_clean_event_is_flagged_ok() -> None:
    det = EventDetector(_cfg(), sample_rate_hz=FS)
    ev = _run(det, [_pre(_gauss(4000, at=1.0, fwhm_s=0.01, amplitude=1.5))])[0]
    assert ev.quality_flag == "ok"
    assert not ev.truncated


# -- counters ------------------------------------------------------------------------------------------


def test_detector_counts_what_it_rejected() -> None:
    """Rejections are metrics, not silence: buildspec section 9 wants them on a dashboard."""
    det = EventDetector(_cfg(min_duration_s=0.005, max_duration_s=0.5), sample_rate_hz=FS)
    x = np.zeros(20_000)
    x[2000:2002] = 1.0
    x[6000:16000] = 1.0
    _run(det, [_pre(x)])
    assert det.rejected_too_short == 1
    assert det.rejected_too_long == 1
    assert det.detected == 0


def test_the_detection_carries_the_temperature_at_its_peak() -> None:
    """Without it the estimator's temperature coefficient can never be applied.

    ``MassEstimator.estimate`` takes a ``temp_c`` and defaults it to 0.0, and nothing was passing
    one: every stored event had a null temperature and every compensation was computed at 0 degC.
    Harmless for ``StaticAffine``, whose coefficient is fixed at zero, and silently wrong for the
    temperature-compensating estimators phase 5 adds -- so the detection carries it now.
    """
    n = int(2.0 * FS)
    signal = _gauss(n, at=1.0, fwhm_s=0.01, amplitude=1.0)
    block = _pre(signal)
    # A temperature that varies, so reading the wrong sample gives a visibly wrong answer.
    object.__setattr__(block, "temperature_c", 10.0 + 10.0 * block.t_s)

    events = list(detector_over(block))
    (event,) = events
    assert event.temp_c == pytest.approx(20.0, abs=0.5)  # t = 1.0 s -> 10 + 10*1.0


def detector_over(block: PreprocessedBlock):
    detector = EventDetector(_cfg(), sample_rate_hz=FS)
    yield from detector.process(block)
    yield from detector.flush()
