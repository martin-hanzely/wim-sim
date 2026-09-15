"""The preprocessor: filter chain, zero-line tracking, temperature compensation.

Three properties are load-bearing and tested hardest:

* **Raw is never discarded.** Every stage keeps ``raw_value`` alongside what it derived, because a
  filtering decision made in phase 2 must not be able to destroy evidence needed in phase 6.
* **Filtering is causal.** A real station cannot look into the future, so no ``filtfilt``, no
  centred windows. That costs group delay, which is measured and reported rather than ignored.
* **Compensation uses the active profile's coefficient and the probe's reading** -- not the true
  sensor temperature, which the preprocessor cannot see and must not be able to.
"""

from __future__ import annotations

import numpy as np
import pytest

from wimsim.calibration import CalibrationProfile, EstimatorState
from wimsim.core.config import PreprocessConfig
from wimsim.core.types import SampleBlock
from wimsim.edge.preprocess import Preprocessor

FS = 2000.0


def _block(
    values: np.ndarray,
    *,
    start_index: int = 0,
    temp_c: float | np.ndarray = 20.0,
    valid: np.ndarray | None = None,
) -> SampleBlock:
    n = values.size
    idx = np.arange(start_index, start_index + n)
    t_s = idx / FS
    temps = np.full(n, temp_c) if np.isscalar(temp_c) else np.asarray(temp_c)
    return SampleBlock(
        ts_us=(1_748_736_000_000_000 + np.rint(t_s * 1e6)).astype(np.int64),
        t_s=t_s,
        raw_value=values.astype(np.float64),
        raw_counts=np.rint(values * 1e4).astype(np.int64),
        temperature_c=temps.astype(np.float64),
        saturated=np.zeros(n, dtype=bool),
        valid=np.ones(n, dtype=bool) if valid is None else valid,
        channel_id="S1",
    )


def _profile(temp_coeff: float = 0.0, t_ref_c: float = 20.0) -> CalibrationProfile:
    state = EstimatorState(
        estimator="static_affine",
        gain=5000.0,
        bias=0.0,
        temp_coeff=temp_coeff,
        t_ref_c=t_ref_c,
        fitted=True,
    )
    return CalibrationProfile.from_state(state, profile_id="p-test", activated_ts_us=0)


def _quiet(n: int, *, level: float = 0.05, noise: float = 0.0, seed: int = 0) -> np.ndarray:
    rng = np.random.default_rng(seed)
    return level + noise * rng.standard_normal(n)


def _with_pulse(
    n: int, *, at: int, width: int = 20, amplitude: float = 1.0, level: float = 0.05
) -> np.ndarray:
    x = np.full(n, level)
    t = np.arange(n)
    x += amplitude * np.exp(-0.5 * ((t - at) / (width / 2.355)) ** 2)
    return x


# -- raw is sacred ----------------------------------------------------------------------------


def test_raw_value_passes_through_untouched() -> None:
    cfg = PreprocessConfig(filter="butterworth", cutoff_hz=100.0, order=4)
    pre = Preprocessor(cfg, sample_rate_hz=FS, profile=_profile())
    values = _with_pulse(4000, at=2000)
    out = pre.process(_block(values))
    np.testing.assert_array_equal(out.raw_value, values)
    assert not np.array_equal(out.filtered_value, values), "the filter should have done something"


def test_timestamps_and_flags_pass_through() -> None:
    pre = Preprocessor(PreprocessConfig(), sample_rate_hz=FS, profile=_profile())
    valid = np.ones(1000, dtype=bool)
    valid[400:500] = False
    block = _block(_quiet(1000), valid=valid)
    out = pre.process(block)
    np.testing.assert_array_equal(out.ts_us, block.ts_us)
    np.testing.assert_array_equal(out.valid, block.valid)
    assert out.n == 1000


# -- causality --------------------------------------------------------------------------------


def test_filtering_is_causal() -> None:
    """A step at sample k must not move any output before k. A real station has no future."""
    cfg = PreprocessConfig(filter="butterworth", cutoff_hz=80.0, order=4)
    pre = Preprocessor(cfg, sample_rate_hz=FS, profile=_profile())
    x = np.zeros(2000)
    x[1000:] = 1.0
    out = pre.process(_block(x))
    assert np.abs(out.filtered_value[:1000]).max() < 1e-12


def test_group_delay_is_reported_and_nonzero_for_a_real_filter() -> None:
    none_cfg = Preprocessor(PreprocessConfig(filter="none"), sample_rate_hz=FS, profile=_profile())
    assert none_cfg.group_delay_s == 0.0

    ma = Preprocessor(
        PreprocessConfig(filter="moving_average", window=21), sample_rate_hz=FS, profile=_profile()
    )
    # a boxcar of N samples delays by exactly (N-1)/2 samples
    assert ma.group_delay_s == pytest.approx(10.0 / FS)

    bw = Preprocessor(
        PreprocessConfig(filter="butterworth", cutoff_hz=100.0, order=4),
        sample_rate_hz=FS,
        profile=_profile(),
    )
    assert bw.group_delay_s > 0.0


def test_group_delay_compensation_corrects_the_time_axis_not_the_samples() -> None:
    """Compensation relabels time; it does not move samples.

    Shifting sample *values* earlier would mean the output at time t depended on the input at
    t + delay, which no station can do. What a station can do is emit a filtered sample stamped with
    the time the underlying event actually happened, at the cost of `delay` seconds of latency. So
    the corrected quantity is ``t_s``, and the filtered array stays exactly where the filter put it.
    """
    values = _with_pulse(4000, at=2000, width=40)
    true_peak_t = 2000 / FS

    cfg = PreprocessConfig(filter="moving_average", window=21, compensate_group_delay=True)
    out = Preprocessor(cfg, sample_rate_hz=FS, profile=_profile()).process(_block(values))
    # the filtered peak still sits ten samples late in the array...
    assert int(np.argmax(out.compensated_value)) - 2000 == pytest.approx(10, abs=1)
    # ...but the time stamped on it is the time the axle really crossed
    assert out.t_s[int(np.argmax(out.compensated_value))] == pytest.approx(true_peak_t, abs=1 / FS)

    uncomp = PreprocessConfig(filter="moving_average", window=21, compensate_group_delay=False)
    late = Preprocessor(uncomp, sample_rate_hz=FS, profile=_profile()).process(_block(values))
    assert late.t_s[int(np.argmax(late.compensated_value))] == pytest.approx(
        true_peak_t + 10 / FS, abs=1 / FS
    )


def test_time_shift_is_applied_to_microsecond_stamps_too() -> None:
    cfg = PreprocessConfig(filter="moving_average", window=21, compensate_group_delay=True)
    pre = Preprocessor(cfg, sample_rate_hz=FS, profile=_profile())
    block = _block(_quiet(1000))
    out = pre.process(block)
    shift_us = round(pre.group_delay_s * 1e6)
    np.testing.assert_array_equal(out.ts_us, block.ts_us - shift_us)


# -- block-boundary continuity -----------------------------------------------------------------


@pytest.mark.parametrize(
    "cfg",
    [
        PreprocessConfig(filter="moving_average", window=21),
        PreprocessConfig(filter="butterworth", cutoff_hz=100.0, order=4),
    ],
)
def test_filter_state_is_carried_across_blocks(cfg: PreprocessConfig) -> None:
    """Splitting the stream must not put a discontinuity in the filtered signal."""
    values = _with_pulse(4000, at=2500, width=40)

    whole = Preprocessor(cfg, sample_rate_hz=FS, profile=_profile()).process(_block(values))
    chunked = Preprocessor(cfg, sample_rate_hz=FS, profile=_profile())
    parts = [
        chunked.process(_block(values[i : i + 500], start_index=i)) for i in range(0, 4000, 500)
    ]
    joined = np.concatenate([p.filtered_value for p in parts])
    np.testing.assert_allclose(joined, whole.filtered_value, rtol=0, atol=1e-12)


def test_zero_line_is_continuous_across_blocks() -> None:
    values = _quiet(8000, level=0.05, noise=2e-4, seed=1)
    cfg = PreprocessConfig(zero_window_s=1.0, zero_update_s=0.1)

    whole = Preprocessor(cfg, sample_rate_hz=FS, profile=_profile()).process(_block(values))
    chunked = Preprocessor(cfg, sample_rate_hz=FS, profile=_profile())
    joined = np.concatenate(
        [
            chunked.process(_block(values[i : i + 1000], start_index=i)).zero_estimate
            for i in range(0, 8000, 1000)
        ]
    )
    np.testing.assert_allclose(joined, whole.zero_estimate, rtol=0, atol=1e-12)


# -- zero-line tracking -------------------------------------------------------------------------


def test_zero_line_finds_a_constant_baseline() -> None:
    cfg = PreprocessConfig(zero_window_s=0.5, zero_update_s=0.1)
    pre = Preprocessor(cfg, sample_rate_hz=FS, profile=_profile())
    out = pre.process(_block(_quiet(8000, level=0.07, noise=1e-4, seed=2)))
    settled = out.zero_estimate[~out.warming_up]
    assert settled.size > 0
    np.testing.assert_allclose(settled, 0.07, atol=2e-5)


def test_zero_line_tracks_a_drifting_baseline_with_the_expected_lag() -> None:
    cfg = PreprocessConfig(zero_window_s=0.5, zero_update_s=0.05)
    pre = Preprocessor(cfg, sample_rate_hz=FS, profile=_profile())
    n = 20000
    drift = 0.05 + np.linspace(0.0, 0.02, n)  # 0.02 units over 10 s
    out = pre.process(_block(drift))
    settled = ~out.warming_up
    err = out.zero_estimate[settled] - drift[settled]
    # a trailing median lags a ramp by about half the window
    assert np.median(err) < 0.0
    assert abs(np.median(err)) < 0.02 / (n / FS) * cfg.zero_window_s


def test_a_pass_does_not_drag_the_zero_line_up() -> None:
    """The median is robust while vehicles occupy less than half the window -- the whole reason
    a median is used rather than a mean."""
    cfg = PreprocessConfig(zero_window_s=1.0, zero_update_s=0.05)
    pre = Preprocessor(cfg, sample_rate_hz=FS, profile=_profile())
    values = _with_pulse(8000, at=4000, width=20, amplitude=2.0, level=0.05)
    out = pre.process(_block(values))
    settled = out.zero_estimate[~out.warming_up]
    assert settled.max() < 0.0505, "a 2.0-unit pulse moved the baseline"


def test_dense_traffic_is_flagged_rather_than_silently_biasing_the_zero() -> None:
    """If vehicles occupy most of the window the median stops being the baseline. Say so."""
    cfg = PreprocessConfig(zero_window_s=0.2, zero_update_s=0.05)
    pre = Preprocessor(cfg, sample_rate_hz=FS, profile=_profile())
    x = np.full(8000, 0.05)
    x[::2] = 2.0  # pathological: half the samples are 'vehicle'
    out = pre.process(_block(x))
    assert out.zero_suspect.any()


def test_warming_up_is_flagged_until_the_window_is_full() -> None:
    cfg = PreprocessConfig(zero_window_s=1.0, zero_update_s=0.05)
    pre = Preprocessor(cfg, sample_rate_hz=FS, profile=_profile())
    out = pre.process(_block(_quiet(6000)))
    assert out.warming_up[0]
    assert not out.warming_up[-1]
    assert out.warming_up.sum() == pytest.approx(int(1.0 * FS), rel=0.05)


def test_invalid_samples_are_excluded_from_the_zero_estimate() -> None:
    """A stuck channel reports a constant; letting it into the baseline would move the baseline."""
    cfg = PreprocessConfig(zero_window_s=0.5, zero_update_s=0.05)
    values = _quiet(8000, level=0.05, noise=1e-5, seed=3)
    values[3000:5000] = 2.5  # a stuck-high dropout
    valid = np.ones(8000, dtype=bool)
    valid[3000:5000] = False

    pre = Preprocessor(cfg, sample_rate_hz=FS, profile=_profile())
    out = pre.process(_block(values, valid=valid))
    settled = out.zero_estimate[~out.warming_up]
    np.testing.assert_allclose(settled, 0.05, atol=1e-4)


# -- temperature compensation -------------------------------------------------------------------


def test_compensation_removes_a_known_thermal_gain_error() -> None:
    """A pass measured at 30 degC on a sensor with -2e-4/degC must compensate back to its 20 degC
    value."""
    alpha, t_ref = -2.0e-4, 20.0
    cfg = PreprocessConfig(filter="none", zero_window_s=0.2, zero_update_s=0.05)
    pre = Preprocessor(cfg, sample_rate_hz=FS, profile=_profile(temp_coeff=alpha, t_ref_c=t_ref))

    true_amplitude = 1.0
    thermal = 1.0 + alpha * (30.0 - t_ref)
    values = _with_pulse(8000, at=6000, width=20, amplitude=true_amplitude * thermal, level=0.05)
    out = pre.process(_block(values, temp_c=30.0))
    assert out.compensated_value.max() == pytest.approx(true_amplitude, rel=2e-3)


def test_no_compensation_when_the_profile_has_no_coefficient() -> None:
    cfg = PreprocessConfig(filter="none", zero_window_s=0.2, zero_update_s=0.05)
    pre = Preprocessor(cfg, sample_rate_hz=FS, profile=_profile(temp_coeff=0.0))
    values = _with_pulse(8000, at=6000, width=20, amplitude=1.0, level=0.05)
    out = pre.process(_block(values, temp_c=35.0))
    assert out.compensated_value.max() == pytest.approx(1.0, rel=2e-3)


def test_a_missing_probe_reading_disables_compensation_and_is_flagged() -> None:
    cfg = PreprocessConfig(filter="none", zero_window_s=0.2, zero_update_s=0.05)
    pre = Preprocessor(cfg, sample_rate_hz=FS, profile=_profile(temp_coeff=-2.0e-4))
    values = _with_pulse(8000, at=6000, width=20, amplitude=1.0, level=0.05)
    out = pre.process(_block(values, temp_c=np.full(8000, np.nan)))
    assert out.compensated_value.max() == pytest.approx(1.0, rel=2e-3)
    assert out.temp_missing.all()


def test_without_a_profile_the_preprocessor_still_runs_but_cannot_compensate() -> None:
    """Bootstrapping: the first pass of a run happens before any profile exists."""
    cfg = PreprocessConfig(filter="none", zero_window_s=0.2, zero_update_s=0.05)
    pre = Preprocessor(cfg, sample_rate_hz=FS, profile=None)
    out = pre.process(_block(_with_pulse(8000, at=6000, amplitude=1.0), temp_c=30.0))
    assert out.compensated_value.max() == pytest.approx(1.0, rel=2e-3)
    assert pre.describe().filter == "none"


def test_the_active_profile_can_be_swapped_mid_stream() -> None:
    """Phase 5 recalibration activates a new profile while the stream keeps running."""
    cfg = PreprocessConfig(filter="none", zero_window_s=0.2, zero_update_s=0.05)
    pre = Preprocessor(cfg, sample_rate_hz=FS, profile=_profile(temp_coeff=0.0))
    values = _with_pulse(8000, at=6000, width=20, amplitude=1.0, level=0.05)
    before = pre.process(_block(values, temp_c=30.0)).compensated_value.max()

    pre.set_profile(_profile(temp_coeff=-2.0e-4))
    after = pre.process(_block(values, start_index=8000, temp_c=30.0)).compensated_value.max()
    assert after != pytest.approx(before)
    assert pre.profile_id == "p-test"


# -- despiking ------------------------------------------------------------------------------------


def test_despike_removes_an_isolated_outlier() -> None:
    cfg = PreprocessConfig(despike=True, despike_window=11, despike_threshold=6.0, filter="none")
    pre = Preprocessor(cfg, sample_rate_hz=FS, profile=_profile())
    values = _quiet(4000, level=0.05, noise=1e-4, seed=5)
    values[2000] = 3.0
    out = pre.process(_block(values))
    assert out.filtered_value[2000] < 0.06
    assert out.raw_value[2000] == 3.0, "raw must still show what really arrived"
    assert out.despiked.sum() == 1


def test_despike_does_not_fire_on_clean_gaussian_noise() -> None:
    """Regression: the scale must come from a long window, not from the 11-sample median window.

    An 11-sample MAD has enough sampling variance that a six-deviation threshold flags roughly one
    quiet sample in three hundred -- thousands of phantom spikes an hour on a perfectly healthy
    channel. Estimating the scale over a second of signal removes that.
    """
    cfg = PreprocessConfig(despike=True, despike_window=11, despike_threshold=6.0, filter="none")
    pre = Preprocessor(cfg, sample_rate_hz=FS, profile=_profile())
    out = pre.process(_block(_quiet(40_000, level=0.05, noise=1e-4, seed=11)))
    assert out.despiked.sum() == 0


@pytest.mark.parametrize("width_samples", [8, 11, 14, 21, 42])
def test_despike_does_not_clip_a_pulse_comparable_to_its_own_window(width_samples: int) -> None:
    """Regression: the run-length guard has to be tight, not merely present.

    A centred median only tracks a pulse while the pulse is much wider than the window. At
    comparable widths the median sits near half maximum, the peak trips the outlier test, and the
    despiker replaces the top of the vehicle with the middle of it. With the guard set to half the
    window this went unnoticed -- exactly five samples were flagged and exactly five were allowed --
    and cost 19.8 % of a car's peak while costing a truck 0.6 %, which turns the speed-invariant
    peak feature into a speed-dependent one. It showed up as a 114 kg MAE on S1_nominal against
    1.4 kg without despiking.
    """
    cfg = PreprocessConfig(despike=True, despike_window=11, despike_threshold=6.0, filter="none")
    pre = Preprocessor(cfg, sample_rate_hz=FS, profile=_profile())
    rng = np.random.default_rng(width_samples)
    # noise is not decoration here: with a perfectly noiseless signal the scale estimate is zero and
    # despiking switches itself off, so the assertion below would hold vacuously
    values = _with_pulse(8000, at=4000, width=width_samples, amplitude=1.5, level=0.05)
    values += 2e-4 * rng.standard_normal(8000)
    out = pre.process(_block(values))

    clean = _with_pulse(8000, at=4000, width=width_samples, amplitude=1.5, level=0.05)
    lost = 1.0 - (out.filtered_value.max() - 0.05) / (clean.max() - 0.05)
    assert lost < 0.01, f"{100 * lost:.1f} % of the peak was eaten at width {width_samples}"


def test_despike_removes_a_spike_between_vehicles() -> None:
    """The case the despiker exists for: an EMI hit on an otherwise quiet baseline."""
    cfg = PreprocessConfig(despike=True, despike_window=11, despike_threshold=6.0, filter="none")
    pre = Preprocessor(cfg, sample_rate_hz=FS, profile=_profile())
    rng = np.random.default_rng(21)
    values = _with_pulse(8000, at=4000, width=21, amplitude=1.5, level=0.05)
    values += 1e-4 * rng.standard_normal(8000)
    values[6000] += 3.0
    out = pre.process(_block(values))
    assert out.despiked[6000]
    assert out.despiked.sum() == 1
    assert out.filtered_value[6000] < 0.06
    assert out.filtered_value.max() == pytest.approx(values[3995:4005].max(), rel=1e-6)


def test_a_spike_on_a_steep_flank_is_deliberately_left_alone() -> None:
    """A documented limitation, pinned so it stays a decision rather than becoming a surprise.

    A Hampel filter cannot separate "outlier" from "curvature": over an 11-sample window the flank
    of a real pulse already departs from its own median by far more than six noise deviations, so
    the flank is flagged too, and the run-length guard then releases the whole run -- spike
    included. The alternative is to trust the flags and eat the pulse. For a weighing instrument
    that trade is not close: a missed spike degrades one event, an eaten peak biases every event and
    does so more for fast vehicles than slow ones.
    """
    cfg = PreprocessConfig(despike=True, despike_window=11, despike_threshold=6.0, filter="none")
    pre = Preprocessor(cfg, sample_rate_hz=FS, profile=_profile())
    rng = np.random.default_rng(21)
    values = _with_pulse(8000, at=4000, width=21, amplitude=1.5, level=0.05)
    values += 1e-4 * rng.standard_normal(8000)
    values[4010] += 3.0  # on the falling flank
    out = pre.process(_block(values))
    assert not out.despiked[4010], "if this starts passing, check the peak is still intact"
    assert out.filtered_value[3995:4005].max() == pytest.approx(
        values[3995:4005].max(), rel=1e-6
    ), "whatever else happens, the peak must survive"


def test_a_noiseless_channel_disables_despiking_rather_than_flagging_everything() -> None:
    """With no measurable noise there is no scale to threshold against.

    Every deviation would then be infinitely many sigmas and every pulse would be "a spike". Doing
    nothing is the only safe answer, and it is reachable in practice: a stuck ADC reports a constant.
    """
    cfg = PreprocessConfig(despike=True, filter="none")
    pre = Preprocessor(cfg, sample_rate_hz=FS, profile=_profile())
    out = pre.process(_block(_with_pulse(8000, at=4000, width=21, amplitude=1.5, level=0.05)))
    assert out.despiked.sum() == 0
    assert out.filtered_value.max() == pytest.approx(1.55, rel=1e-6)


def test_despike_does_not_clip_a_real_pulse() -> None:
    """A median filter wide enough to despike would flatten a 5 ms axle pulse. Only outliers are
    replaced, which is why this is despiking and not median filtering."""
    cfg = PreprocessConfig(despike=True, despike_window=11, despike_threshold=6.0, filter="none")
    pre = Preprocessor(cfg, sample_rate_hz=FS, profile=_profile())
    values = _with_pulse(4000, at=2000, width=20, amplitude=1.5, level=0.05)
    out = pre.process(_block(values))
    assert out.filtered_value.max() == pytest.approx(values.max(), rel=1e-6)
    assert out.despiked.sum() == 0


# -- provenance -------------------------------------------------------------------------------------


def test_describe_matches_the_event_schema_block() -> None:
    from wimsim.core.schemas import PreprocessingBlock

    cfg = PreprocessConfig(filter="butterworth", cutoff_hz=120.0, order=4, zero_window_s=0.5)
    pre = Preprocessor(cfg, sample_rate_hz=FS, profile=_profile())
    block = pre.describe()
    assert isinstance(block, PreprocessingBlock)
    assert block.filter == "butterworth"
    assert block.cutoff_hz == 120.0
    assert block.order == 4
    assert block.zero_window_s == 0.5


def test_cutoff_above_nyquist_is_rejected() -> None:
    with pytest.raises(ValueError, match="Nyquist"):
        Preprocessor(
            PreprocessConfig(filter="butterworth", cutoff_hz=1500.0, order=4),
            sample_rate_hz=FS,
            profile=_profile(),
        )


def test_a_negative_going_sensor_can_be_inverted_in_the_preprocessor() -> None:
    """Which way a crossing goes is a property of the wiring -- which leg of the bridge, which way
    the gauge is bonded -- not of the algorithm.

    Measured on `20260209_cintron1/Tenzo1`: the vehicle at t=15.2 s pulls the compensated signal
    *down* by 7.1 microstrain. The detector opens on a rise above the zero line, by design and
    correctly: a detector needs one definition of "above". So with the recording as exported it
    finds nothing, at any threshold, with any filter. Inverted, it finds the crossing.
    """
    from wimsim.core.config import PreprocessConfig
    from wimsim.edge.preprocess import Preprocessor

    n = 4000
    block = _block(np.full(n, 0.5) - 0.2 * np.exp(-0.5 * ((np.arange(n) - 3000) / 60.0) ** 2))

    upright = Preprocessor(PreprocessConfig(), sample_rate_hz=FS).process(block)
    inverted = Preprocessor(PreprocessConfig(invert=True), sample_rate_hz=FS).process(block)

    assert upright.compensated_value.min() < -0.1, "the test signal does not dip"
    assert inverted.compensated_value.max() > 0.1
    assert inverted.compensated_value == pytest.approx(-upright.compensated_value)


def test_inversion_leaves_the_raw_value_alone() -> None:
    """`raw_value` is what the station reported and is carried for provenance. Flipping it would
    make the stored sample disagree with the recording it came from."""
    from wimsim.core.config import PreprocessConfig
    from wimsim.edge.preprocess import Preprocessor

    block = _block(np.full(2000, 0.5))
    out = Preprocessor(PreprocessConfig(invert=True), sample_rate_hz=FS).process(block)
    assert out.raw_value == pytest.approx(block.raw_value)
