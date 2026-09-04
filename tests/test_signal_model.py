"""Unit tests for the generative model's parts.

Each test pins one claim made in ``docs/signal-model.md``. If the docs and the code disagree, one of
them is wrong and this file is where that shows up.
"""

from __future__ import annotations

import numpy as np
import pytest

from wimsim.core.config import (
    AdcConfig,
    NoiseConfig,
    PulseConfig,
    StationConfig,
    TemperatureConfig,
)
from wimsim.core.rng import streams
from wimsim.signal.adc import Quantizer
from wimsim.signal.noise import MainsInterference, PinkNoise, WhiteNoise
from wimsim.signal.pulses import FWHM_TO_SIGMA, fwhm_for, pulse_area_factor, pulse_waveform
from wimsim.signal.thermal import ThermalModel

# -- pulses ------------------------------------------------------------------------------


@pytest.mark.parametrize("shape", ["gaussian", "emg", "ringing"])
def test_every_shape_has_unit_peak(shape: str) -> None:
    """Unit-peak normalisation is the modelling choice that makes peak speed-invariant."""
    cfg = PulseConfig(shape=shape)
    fwhm = 0.009
    t = np.linspace(-8 * fwhm, 8 * fwhm, 200_001)
    y = pulse_waveform(t, fwhm, cfg)
    assert y.max() == pytest.approx(1.0, abs=2e-4)


def test_gaussian_fwhm_is_the_configured_width() -> None:
    cfg = PulseConfig(shape="gaussian")
    fwhm = 0.01
    t = np.linspace(-4 * fwhm, 4 * fwhm, 400_001)
    y = pulse_waveform(t, fwhm, cfg)
    above = t[y >= 0.5]
    assert (above.max() - above.min()) == pytest.approx(fwhm, rel=1e-3)


def test_gaussian_area_matches_the_analytic_value() -> None:
    cfg = PulseConfig(shape="gaussian")
    fwhm = 0.01
    expected = fwhm * FWHM_TO_SIGMA * np.sqrt(2.0 * np.pi)
    assert pulse_area_factor(fwhm, cfg) == pytest.approx(expected, rel=1e-4)


def _emg_skew(tau_ratio: float, fwhm: float = 0.01) -> float:
    """Area after the peak divided by area before it. 1.0 for a symmetric shape."""
    cfg = PulseConfig(shape="emg", emg_tau_ratio=tau_ratio)
    t = np.linspace(-8 * fwhm, 8 * fwhm, 100_001)
    y = pulse_waveform(t, fwhm, cfg)
    peak_t = t[int(np.argmax(y))]
    before = np.trapezoid(y[t < peak_t], t[t < peak_t])
    after = np.trapezoid(y[t > peak_t], t[t > peak_t])
    return float(after / before)


def test_emg_is_right_skewed_and_more_so_with_a_longer_tail() -> None:
    """The trailing tail is what distinguishes a real pad response from a Gaussian."""
    assert _emg_skew(0.6) > 1.3
    assert _emg_skew(1.2) > _emg_skew(0.6) > _emg_skew(0.2) > 1.0
    # a Gaussian, for contrast, is symmetric to within the integration error
    cfg = PulseConfig(shape="gaussian")
    t = np.linspace(-8 * 0.01, 8 * 0.01, 100_001)
    y = pulse_waveform(t, 0.01, cfg)
    mid = t[int(np.argmax(y))]
    left = np.trapezoid(y[t < mid], t[t < mid])
    right = np.trapezoid(y[t > mid], t[t > mid])
    assert right / left == pytest.approx(1.0, abs=0.01)


def test_emg_carries_more_area_than_a_gaussian_of_the_same_peak() -> None:
    fwhm = 0.01
    g = pulse_area_factor(fwhm, PulseConfig(shape="gaussian"))
    e = pulse_area_factor(fwhm, PulseConfig(shape="emg", emg_tau_ratio=0.6))
    assert e > g


def test_ringing_oscillates_only_after_the_impact() -> None:
    """The structural mode is excited by the axle; it cannot precede it."""
    cfg = PulseConfig(shape="ringing", ring_freq_hz=200.0, ring_amplitude=0.4, ring_damping=0.05)
    fwhm = 0.01
    t = np.linspace(-8 * fwhm, 8 * fwhm, 200_001)
    y = pulse_waveform(t, fwhm, cfg)
    # a decaying sinusoid crosses back below zero after the pulse; nothing of the sort before it
    assert (y[t < -2 * fwhm] >= 0).all()
    assert (y[t > 0] < -1e-3).any()


def test_influence_line_is_parabolic_with_compact_support() -> None:
    """The shape the real sensor actually produces.

    Chosen by fitting six real crossings, not by eye: a clipped parabola gives a 5.2 % normalised
    RMS residual against 6.9 % for a raised cosine, 8.7 % for a Gaussian and 10.2 % for the textbook
    triangular influence line.
    """
    cfg = PulseConfig(shape="influence_line")
    fwhm = 0.5
    t = np.linspace(-fwhm, fwhm, 200_001)
    y = pulse_waveform(t, fwhm, cfg)

    assert y.max() == pytest.approx(1.0, abs=1e-6)
    above = t[y >= 0.5]
    assert (above.max() - above.min()) == pytest.approx(fwhm, rel=1e-3)

    half_support = fwhm / np.sqrt(2.0)
    assert (
        pulse_waveform(np.array([-1.01 * half_support, 1.01 * half_support]), fwhm, cfg).max()
        == 0.0
    )
    # a parabola, not a Gaussian: check the curve away from the peak
    assert pulse_waveform(np.array([half_support / 2]), fwhm, cfg)[0] == pytest.approx(0.75)


def test_influence_line_is_symmetric() -> None:
    cfg = PulseConfig(shape="influence_line")
    t = np.linspace(-0.4, 0.4, 8001)
    y = pulse_waveform(t, 0.5, cfg)
    np.testing.assert_allclose(y, y[::-1], atol=1e-12)


def test_influence_line_is_wider_than_a_contact_pulse_of_the_same_fwhm_setting() -> None:
    """Not about the shape but about what sets the width.

    A contact-force sensor's pulse width comes from the tyre footprint -- centimetres. A structural
    sensor's comes from the influence length of the member -- metres. At the same speed that is two
    orders of magnitude, which is why width_source exists as a switch rather than a tuning knob.
    """
    patch, influence = 0.22, 1.0
    speed = 10.0
    assert fwhm_for(speed, influence) == pytest.approx(4.5 * fwhm_for(speed, patch), rel=0.02)


def test_pulse_is_zero_outside_its_support() -> None:
    cfg = PulseConfig(shape="gaussian", support_widths=4.0)
    fwhm = 0.01
    t = np.array([-4.1 * fwhm, 4.1 * fwhm])
    assert (pulse_waveform(t, fwhm, cfg) == 0.0).all()


def test_width_is_inversely_proportional_to_speed() -> None:
    patch = 0.22
    assert fwhm_for(20.0, patch) == pytest.approx(2 * fwhm_for(40.0, patch))
    with pytest.raises(ValueError):
        fwhm_for(0.0, patch)


# -- thermal -----------------------------------------------------------------------------


def _thermal(tau: float, dt: float = 0.02, **probe) -> ThermalModel:
    station = StationConfig.model_validate(
        {
            "thermal": {"tau_thermal_s": tau, "t_sensor_init_c": 0.0},
            "temperature_probe": {
                "enabled": True,
                "lag_s": 0.0,
                "noise_sigma_c": 0.0,
                "resolution_c": 0.0,
                **probe,
            },
        }
    )
    cfg = TemperatureConfig(
        mean_c=10.0, daily_amplitude_c=0.0, trend_c_per_day=0.0, noise_sigma_c=0.0
    )
    return ThermalModel(cfg, station, dt=dt, start_time_us=0, rngs=streams(1))


def test_thermal_lag_reaches_63_percent_after_one_time_constant() -> None:
    """The textbook signature of a first-order lag, which is what the model claims to be."""
    tau, dt = 100.0, 0.02
    model = _thermal(tau, dt)
    n = int(round(tau / dt))
    block = model.advance(np.arange(n + 1) * dt)
    # step from 0 degC to a 10 degC ambient
    assert block.sensor_c[-1] == pytest.approx(10.0 * (1 - np.exp(-1.0)), rel=2e-3)


def test_sensor_lags_ambient_on_a_daily_cycle() -> None:
    """The phase shift is the whole reason instantaneous compensation underperforms."""
    station = StationConfig.model_validate(
        {"sample_rate_hz": 50.0, "thermal": {"tau_thermal_s": 1800.0}}
    )
    cfg = TemperatureConfig(
        mean_c=15.0, daily_amplitude_c=10.0, peak_hour_utc=12.0, noise_sigma_c=0.0
    )
    dt = 10.0
    model = ThermalModel(cfg, station, dt=dt, start_time_us=0, rngs=streams(2))
    t = np.arange(0.0, 3 * 86400.0, dt)
    b = model.advance(t)
    day3 = t >= 2 * 86400.0
    amb_peak = t[day3][int(np.argmax(b.ambient_c[day3]))]
    sens_peak = t[day3][int(np.argmax(b.sensor_c[day3]))]
    assert sens_peak > amb_peak, "the sensor body must peak after the air"
    lag_min = (sens_peak - amb_peak) / 60.0
    assert 10.0 < lag_min < 60.0
    # and with reduced amplitude, because the lag is also a low-pass filter
    assert np.ptp(b.sensor_c[day3]) < np.ptp(b.ambient_c[day3])


def test_probe_is_not_the_sensor() -> None:
    """An estimator that trusts the probe is trusting a lagged, offset, quantised proxy."""
    station = StationConfig.model_validate(
        {
            "sample_rate_hz": 50.0,
            "thermal": {"tau_thermal_s": 600.0, "t_sensor_init_c": 10.0},
            "temperature_probe": {
                "enabled": True,
                "lag_s": 300.0,
                "offset_c": 0.5,
                "noise_sigma_c": 0.0,
                "resolution_c": 0.25,
            },
        }
    )
    cfg = TemperatureConfig(mean_c=25.0, daily_amplitude_c=0.0, noise_sigma_c=0.0)
    model = ThermalModel(cfg, station, dt=1.0, start_time_us=0, rngs=streams(3))
    b = model.advance(np.arange(600.0))
    assert (b.probe_c < b.sensor_c).mean() > 0.9, "probe should trail the body while warming"
    assert np.allclose(np.round(b.probe_c / 0.25), b.probe_c / 0.25), "probe must be quantised"


# -- noise -------------------------------------------------------------------------------


def test_white_noise_has_the_configured_sd() -> None:
    w = WhiteNoise(3e-4, streams(4))
    x = w.advance(200_000)
    assert x.std() == pytest.approx(3e-4, rel=0.02)


def test_pink_noise_has_the_configured_sd_and_falls_as_one_over_f() -> None:
    from scipy import signal as sps

    dt = 0.02
    p = PinkNoise(1e-3, dt=dt, f_min_hz=0.01, f_max_hz=5.0, rngs=streams(5))
    x = p.advance(400_000)
    assert x.std() == pytest.approx(1e-3, rel=0.15)

    f, pxx = sps.welch(x, fs=1 / dt, nperseg=1 << 15)
    band = (f > 0.05) & (f < 4.0)
    slope = np.polyfit(np.log10(f[band]), np.log10(pxx[band]), 1)[0]
    assert -1.35 < slope < -0.65, f"expected roughly 1/f (slope -1), got {slope:.2f}"


def test_pink_noise_is_block_size_invariant() -> None:
    kw = {"dt": 0.02, "f_min_hz": 0.01, "f_max_hz": 5.0}
    one = PinkNoise(1.0, rngs=streams(6), **kw).advance(4096)
    p = PinkNoise(1.0, rngs=streams(6), **kw)
    two = np.concatenate([p.advance(1024) for _ in range(4)])
    np.testing.assert_allclose(one, two, rtol=0, atol=0)


def test_pink_noise_starts_stationary() -> None:
    """Sections are seeded from their stationary distribution, so there is no warm-up ramp."""
    p = PinkNoise(1.0, dt=0.02, f_min_hz=0.01, f_max_hz=5.0, rngs=streams(7))
    x = p.advance(200_000)
    head, tail = x[:20_000], x[-20_000:]
    assert abs(head.std() - tail.std()) / tail.std() < 0.6


def test_mains_is_disabled_by_default_and_periodic_when_enabled() -> None:
    off = MainsInterference(NoiseConfig(), streams(8))
    t = np.linspace(0, 0.1, 1000)
    assert (off.evaluate(t) == 0.0).all()

    cfg = NoiseConfig.model_validate(
        {"mains": {"enabled": True, "freq_hz": 50.0, "amplitude": 1e-3, "harmonics": []}}
    )
    on = MainsInterference(cfg, streams(8))
    t = np.linspace(0, 1.0, 100_001)
    y = on.evaluate(t)
    assert y.max() == pytest.approx(1e-3, rel=1e-3)
    # exactly periodic at 20 ms
    np.testing.assert_allclose(y[:1000], y[2000:3000], atol=1e-9)


# -- ADC ---------------------------------------------------------------------------------


def test_quantizer_round_trips_on_the_lattice() -> None:
    q = Quantizer(AdcConfig(bits=12, range_min=-1.0, range_max=1.0))
    x = np.linspace(-0.9, 0.9, 1001)
    counts, value, sat = q.quantize(x)
    assert not sat.any()
    assert np.abs(value - x).max() <= q.lsb / 2 + 1e-12
    np.testing.assert_array_equal(q.to_counts(value), counts)


def test_quantizer_flags_and_clips_saturation() -> None:
    q = Quantizer(AdcConfig(bits=8, range_min=0.0, range_max=1.0))
    counts, value, sat = q.quantize(np.array([-5.0, 0.5, 5.0]))
    assert sat.tolist() == [True, False, True]
    assert counts.tolist() == [0, 128, 255]
    assert value[0] == pytest.approx(0.0)
    assert value[-1] == pytest.approx(1.0)


def test_lsb_matches_the_declared_range() -> None:
    cfg = AdcConfig(bits=16, range_min=-0.5, range_max=3.0)
    assert cfg.levels == 65536
    assert cfg.lsb == pytest.approx(3.5 / 65535)
