"""Leave-one-recording-out cross-validation of the simulator parameters.

Section V-C concedes that no simulator parameter has ever been cross-validated. These tests are
about the ways a cross-validation can be accidentally not one: a fold that sees the recording it
is predicting, a statistic that is really measuring the traffic, and a missing measurement written
in as a zero.
"""

from __future__ import annotations

import math

import numpy as np
import pytest

from wimsim.experiments.sim_crossval import (
    PLANT_RATE_HZ,
    STRAIN_TO_MV_PER_V,
    RecordingStats,
    _log2_ratio,
    fit_parameters,
    leave_one_out,
    measure,
    quiescent_mask,
    to_station_units,
)

FS = 2000.0


def _noise(n: int, sigma: float, seed: int = 0) -> np.ndarray:
    return np.random.default_rng(seed).normal(0.0, sigma, n)


def _with_crossing(n: int, sigma: float, *, amplitude: float, at: int, width: int) -> np.ndarray:
    x = _noise(n, sigma)
    t = np.arange(n)
    x += amplitude * np.exp(-(((t - at) / width) ** 2))
    return x


def _stats(**over) -> RecordingStats:
    base = {
        "name": "r",
        "n_samples": 1000,
        "duration_s": 60.0,
        "sample_rate_hz": FS,
        "quiescent_fraction": 0.9,
        "white_sigma": 1.0,
        "mains_amplitude": 2.0,
        "baseline": 0.1,
        "drift_slope": -2.0,
        "decades_resolved": 1.5,
        "increment_sd": 0.01,
        "increment_robust_sd": 0.01,
        "increment_white_part": 0.0,
        "increment_kurtosis": 0.0,
        "fwhm_s": 0.8,
        "best_shape": "parabola",
        "shape_residual": 0.05,
    }
    base.update(over)
    return RecordingStats(**base)


# -- excising the crossings -------------------------------------------------------------------


def test_a_crossing_and_its_neighbourhood_are_excised() -> None:
    """A one-second drive-over is a far larger excursion than the noise being measured. Left in,
    it dominates the low-frequency slope, and the drift statistic becomes a measurement of the
    traffic."""
    signal = _with_crossing(60_000, 1e-3, amplitude=0.05, at=30_000, width=400)
    mask = quiescent_mask(signal, fs=FS)

    assert not mask[30_000]
    assert mask[:10_000].all()
    assert 0.5 < mask.mean() < 1.0


def test_an_empty_recording_keeps_all_of_itself() -> None:
    """A minute of empty road is a valid recording, not a failure to find anything."""
    mask = quiescent_mask(_noise(60_000, 1e-3), fs=FS)
    assert mask.mean() > 0.99


def test_the_quiescent_fraction_is_reported_so_a_weak_measurement_is_visible() -> None:
    signal = _with_crossing(60_000, 1e-3, amplitude=0.05, at=30_000, width=400)
    stats = measure(signal, fs=FS, name="r")

    assert 0.0 < stats.quiescent_fraction < 1.0


# -- what gets measured -----------------------------------------------------------------------


def test_the_white_floor_is_recovered_from_a_known_signal() -> None:
    stats = measure(_noise(120_000, 2.5e-3), fs=FS, name="r")
    assert stats.white_sigma == pytest.approx(2.5e-3, rel=0.15)


def test_a_recording_with_no_crossing_has_no_event_shape_rather_than_a_zero_one() -> None:
    """Writing 0.0 s of FWHM into that cell would be a measurement of nothing."""
    stats = measure(_noise(120_000, 1e-3), fs=FS, name="r")

    assert math.isnan(stats.fwhm_s)
    assert stats.best_shape == ""


def test_increments_are_measured_after_decimating_to_the_plant_rate() -> None:
    """Differencing at the sample rate measures the white noise twice and says nothing about the
    zero line, which is what the model's random walk parameter is about."""
    sigma = 1e-3
    stats = measure(_noise(240_000, sigma), fs=FS, name="r")

    # White noise decimated by F averages down by sqrt(F); differencing two such means multiplies
    # by sqrt(2). Anything near `sigma` itself would mean the decimation did not happen.
    expected = sigma / math.sqrt(FS / PLANT_RATE_HZ) * math.sqrt(2.0)
    assert stats.increment_sd == pytest.approx(expected, rel=0.2)


# -- pooling ----------------------------------------------------------------------------------


def test_parameters_are_pooled_by_median_so_one_odd_recording_cannot_set_them() -> None:
    stats = [_stats(white_sigma=v) for v in (1.0, 1.1, 0.9, 50.0)]
    assert fit_parameters(stats).white_sigma == pytest.approx(1.05)


def test_the_pulse_shape_is_pooled_by_majority_and_ties_break_deterministically() -> None:
    majority = [_stats(best_shape=s) for s in ("parabola", "parabola", "emg")]
    assert fit_parameters(majority).pulse_shape == "parabola"

    tie = [_stats(best_shape=s) for s in ("emg", "parabola")]
    assert fit_parameters(tie).pulse_shape == "emg"


def test_a_recording_with_no_measurable_shape_does_not_poison_the_pool() -> None:
    stats = [_stats(fwhm_s=0.8), _stats(fwhm_s=float("nan")), _stats(fwhm_s=0.9)]
    fitted = fit_parameters(stats)

    assert fitted.influence_length_m == pytest.approx(0.85 * 0.78)


def test_the_increment_spread_becomes_a_per_root_second_random_walk_scale() -> None:
    fitted = fit_parameters([_stats(increment_robust_sd=0.02, increment_white_part=0.0)])
    assert fitted.random_walk_sigma_per_sqrt_s == pytest.approx(0.02 * math.sqrt(PLANT_RATE_HZ))


def test_the_white_noise_part_of_the_increment_spread_is_removed_before_fitting() -> None:
    """Without this the fitted walk is mostly a restatement of the white sigma. On the real
    corpus the white part is 1.45e-5 of a total 1.9e-5 -- three quarters of the spread the first
    version attributed to the zero line."""
    fitted = fit_parameters([_stats(increment_robust_sd=0.05, increment_white_part=0.04)])
    expected = math.sqrt(0.05**2 - 0.04**2) * math.sqrt(PLANT_RATE_HZ)

    assert fitted.random_walk_sigma_per_sqrt_s == pytest.approx(expected)


def test_a_recording_whose_increments_are_all_white_noise_fits_no_walk_rather_than_a_negative_one() -> (
    None
):
    fitted = fit_parameters([_stats(increment_robust_sd=0.01, increment_white_part=0.02)])
    assert fitted.random_walk_sigma_per_sqrt_s == pytest.approx(0.0)


def test_the_fit_uses_the_robust_spread_so_a_few_spikes_cannot_set_it() -> None:
    """Three of the eight real recordings have an increment sd five times their robust scale,
    with excess kurtosis from +800 to +1700 against the Gaussian 0 the model assumes. An
    sd-based fit would set the simulator's random walk from a handful of samples."""
    spiky = _stats(increment_sd=0.5, increment_robust_sd=0.01, increment_white_part=0.0)
    assert fit_parameters([spiky]).random_walk_sigma_per_sqrt_s == pytest.approx(
        0.01 * math.sqrt(PLANT_RATE_HZ)
    )


def test_fitting_on_nothing_is_refused() -> None:
    with pytest.raises(ValueError, match="no recordings"):
        fit_parameters([])


def test_the_overrides_name_paths_that_exist_in_a_real_config() -> None:
    """`--set` refuses a key that does not already exist, so a path that is merely plausible
    fails at the terminal after the fit has been run and thrown away."""
    from wimsim.core.config import load_run_config

    fitted = fit_parameters([_stats()])
    cfg = load_run_config("S1_nominal", None, overrides=fitted.as_overrides())

    assert cfg.scenario.noise.mains.enabled is True


# -- the fold construction ---------------------------------------------------------------------


def test_two_recordings_are_refused_because_that_is_not_a_cross_validation() -> None:
    with pytest.raises(ValueError, match="not a cross-validation"):
        leave_one_out(["a", "b"])


def test_the_disagreement_is_symmetric_in_direction() -> None:
    """A plain ratio makes 0.5x look smaller than 2x. They are the same size of disagreement."""
    assert _log2_ratio(2.0, 1.0) == pytest.approx(1.0)
    assert _log2_ratio(1.0, 2.0) == pytest.approx(-1.0)
    assert math.isnan(_log2_ratio(0.0, 1.0))


# -- the two bugs the first run of this module had --------------------------------------------


def test_slow_drift_is_not_mistaken_for_a_crossing() -> None:
    """Regression. Measured against a GLOBAL median, the zero line is itself an excursion: these
    recordings wander by several sample-noise sigmas across a minute, and the first version
    marked four of eight recordings as 100 % crossing on that basis."""
    n = 150_000
    drift = 2e-5 * np.sin(np.linspace(0.0, 2.0 * math.pi, n))
    signal = drift + _noise(n, 1e-6, seed=3)

    mask = quiescent_mask(signal, fs=FS)
    assert mask.mean() > 0.95


def test_a_crossing_riding_on_drift_is_still_excised() -> None:
    n = 150_000
    drift = 2e-5 * np.sin(np.linspace(0.0, 2.0 * math.pi, n))
    signal = drift + _noise(n, 1e-6, seed=4)
    signal += 1e-4 * np.exp(-(((np.arange(n) - 75_000) / 800) ** 2))

    mask = quiescent_mask(signal, fs=FS)
    assert not mask[75_000]
    assert 0.8 < mask.mean() < 1.0


def test_a_recording_that_is_almost_all_crossing_is_refused_not_silently_widened() -> None:
    """Regression. The first version fell back to the full signal here, which measured the noise
    on the crossings it had just excised -- and said so nowhere."""
    # 75 s of recording with a crossing every three seconds. Each one excises itself plus two
    # seconds either side, so nothing quiescent survives. A single very wide pulse would NOT do
    # it: over six seconds the rolling baseline tracks the pulse, and by this definition a
    # disturbance that slow is the zero line rather than a vehicle.
    n = 150_000
    t = np.arange(n)
    signal = _noise(n, 1e-6, seed=5)
    for centre in range(3_000, n, 6_000):
        signal = signal + 1e-4 * np.exp(-(((t - centre) / 200) ** 2))
    with pytest.raises(ValueError, match="outside a crossing"):
        measure(signal, fs=FS, name="all-pulse")


def test_strain_is_converted_into_the_simulator_units() -> None:
    """Regression, and the reason the first run looked like a success. A strain-valued white
    sigma fed into a mV/V-valued config key reproduces itself exactly when measured back, so the
    fold reported an agreement of 0.02 between two numbers that were not the same quantity."""
    signal, scale = to_station_units(
        np.array([1e-4, 2e-4]), recording_unit="strain", station_unit="mV/V"
    )
    assert scale == pytest.approx(STRAIN_TO_MV_PER_V)
    assert signal[0] == pytest.approx(0.05)


def test_an_undeclared_unit_pair_is_refused_rather_than_passed_through() -> None:
    with pytest.raises(ValueError, match="no conversion"):
        to_station_units(np.array([1.0]), recording_unit="counts", station_unit="mV/V")
