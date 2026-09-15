"""The sim-to-real gap report: what the simulator gets wrong, measured.

Buildspec section for phase 6: "sim-to-real gap report (compares noise PSD, drift rate, pulse shape
between synthetic and real; fits simulator parameters to the real passes)".

``docs/sim-to-real.md`` already contains this analysis, done by hand during phase 3. That is exactly
the problem: a hand-run analysis is a claim about one afternoon, and the recordings will be
re-imported, the model will change, and nobody will redo it. Making it a command is what turns those
paragraphs into something that can be re-run and disagreed with.

The report is deliberately *not* a pass/fail. A simulator that matched a real sensor on every
statistic would be suspicious rather than reassuring, and the useful output is a list of where the
two differ and by how much.
"""

from __future__ import annotations

import numpy as np
import pytest

from wimsim.experiments.gap_report import (
    GapReport,
    compare_noise,
    compare_pulse_shape,
    estimate_drift_rate,
    find_pulse_window,
    fit_crossing,
    fit_noise_parameters,
)

FS = 25_000.0


def _synthetic_noise(
    n: int, *, sigma: float = 1e-3, mains: float = 0.0, fs: float = FS, seed: int = 0
) -> np.ndarray:
    rng = np.random.default_rng(seed)
    t = np.arange(n) / fs
    signal = sigma * rng.standard_normal(n)
    if mains:
        signal = signal + mains * np.sin(2 * np.pi * 50.0 * t)
    return signal


# -- noise ----------------------------------------------------------------------------------------


def test_the_noise_comparison_recovers_a_known_white_level() -> None:
    """A synthetic stream against itself: the report has to agree with a number it was given
    before it is allowed to say anything about a number it was not."""
    a = _synthetic_noise(200_000, sigma=1e-3, seed=1)
    b = _synthetic_noise(200_000, sigma=1e-3, seed=2)
    result = compare_noise(a, b, fs=FS)

    assert result.reference_sigma == pytest.approx(1e-3, rel=0.05)
    assert result.candidate_sigma == pytest.approx(1e-3, rel=0.05)
    assert result.sigma_ratio == pytest.approx(1.0, rel=0.1)


def test_a_noisier_recording_is_reported_as_noisier() -> None:
    quiet = _synthetic_noise(200_000, sigma=1e-3, seed=1)
    loud = _synthetic_noise(200_000, sigma=4e-3, seed=2)
    result = compare_noise(quiet, loud, fs=FS)
    assert result.sigma_ratio == pytest.approx(4.0, rel=0.1)


def test_mains_is_found_and_quantified_rather_than_absorbed_into_the_noise_floor() -> None:
    """The phase-3 finding that changed the model: 50 Hz sits far above the local floor on every
    real recording, and it is *coherent*, so unlike white noise it does not average down over a
    pulse. A report that folded it into one sigma would hide the thing that matters."""
    clean = _synthetic_noise(200_000, sigma=1e-3, seed=1)
    humming = _synthetic_noise(200_000, sigma=1e-3, mains=8.7e-4, seed=2)

    result = compare_noise(clean, humming, fs=FS)
    assert result.candidate_mains_amplitude == pytest.approx(8.7e-4, rel=0.2)
    assert result.reference_mains_amplitude < 1e-4
    assert result.candidate_mains_db > 20.0


def test_the_psd_is_reported_in_bands_a_reader_can_act_on() -> None:
    """A full periodogram is not a finding. The bands are chosen around what the model has knobs
    for: the mains region, the pulse band, and the low-frequency drift region."""
    signal = _synthetic_noise(200_000, sigma=1e-3, mains=5e-4, seed=3)
    result = compare_noise(signal, signal, fs=FS)

    assert set(result.candidate_band_power) >= {"drift", "mains", "pulse"}
    assert all(v >= 0.0 for v in result.candidate_band_power.values())


def test_a_recording_too_short_to_resolve_the_bands_is_refused() -> None:
    with pytest.raises(ValueError, match="too short"):
        compare_noise(np.zeros(64), np.zeros(64), fs=FS)


# -- fitting the simulator to the real thing -------------------------------------------------------


def test_the_fit_returns_config_overrides_that_can_be_applied_directly() -> None:
    """The point of "fits simulator parameters to the real passes" is that the output is usable.
    A number in a report has to be retyped; a `--set` line does not."""
    signal = _synthetic_noise(400_000, sigma=2.3e-3, mains=6e-4, seed=4)
    fit = fit_noise_parameters(signal, fs=FS)

    assert fit.white_sigma == pytest.approx(2.3e-3, rel=0.1)
    assert fit.mains_amplitude == pytest.approx(6e-4, rel=0.25)

    overrides = fit.as_overrides()
    assert any("noise" in o for o in overrides)
    assert all("=" in o for o in overrides)


def test_the_white_level_is_measured_where_mains_is_not() -> None:
    """A standard deviation over the whole signal counts the hum as noise and overstates the white
    level, which is how the model came to be shipped with mains switched off and a sigma that had
    quietly absorbed it."""
    sigma = 1e-3
    with_hum = _synthetic_noise(400_000, sigma=sigma, mains=5e-3, seed=5)

    naive = float(np.std(with_hum))
    fit = fit_noise_parameters(with_hum, fs=FS)

    assert naive > 3 * sigma, "the test signal does not actually have dominant mains"
    assert fit.white_sigma == pytest.approx(sigma, rel=0.15)


# -- drift ------------------------------------------------------------------------------------------


def test_a_random_walk_is_reported_with_a_brownian_slope() -> None:
    """The phase-3 finding: the real low-frequency slope is -1.96 to -2.65, i.e. Brownian rather
    than flicker, so the random walk in the model is doing the work and the pink term is not."""
    rng = np.random.default_rng(6)
    walk = np.cumsum(rng.standard_normal(200_000)) * 1e-5
    drift = estimate_drift_rate(walk, fs=FS)

    assert -3.0 < drift.slope < -1.5
    assert drift.character == "brownian"


def test_white_noise_is_reported_as_flat_rather_than_as_drift() -> None:
    flat = _synthetic_noise(200_000, sigma=1e-3, seed=7)
    drift = estimate_drift_rate(flat, fs=FS)
    assert abs(drift.slope) < 0.6
    assert drift.character == "white"


def test_a_minute_of_data_cannot_separate_a_walk_from_a_trend_and_says_so() -> None:
    """Sixty seconds gives about a decade and a half of low-frequency resolution. Phase 3
    deliberately did not re-derive the drift model from it, and the report should carry that
    caveat rather than leave a reader to infer it."""
    rng = np.random.default_rng(8)
    short = np.cumsum(rng.standard_normal(int(60 * FS))) * 1e-5
    drift = estimate_drift_rate(short, fs=FS)
    assert drift.decades_resolved < 2.0
    assert drift.caveat


# -- pulse shape ------------------------------------------------------------------------------------


def test_the_best_fitting_shape_is_identified_with_its_residual() -> None:
    """Phase 3 fitted four candidates to six real crossings and the parabola won on five of them,
    at 5.2 % residual. The report re-runs that comparison rather than quoting it."""
    t = np.linspace(-1.0, 1.0, 501)
    parabola = np.clip(1.0 - (t / 0.7) ** 2, 0.0, None)

    result = compare_pulse_shape(parabola, dt_s=float(t[1] - t[0]))
    assert result.best_shape == "parabola"
    assert result.residuals["parabola"] < result.residuals["triangle"]
    assert result.residuals["parabola"] < 0.05


def test_a_gaussian_pulse_is_identified_as_gaussian() -> None:
    """The counterpart: the fitter must not simply always answer "parabola"."""
    t = np.linspace(-1.0, 1.0, 501)
    gaussian = np.exp(-0.5 * (t / 0.25) ** 2)
    result = compare_pulse_shape(gaussian, dt_s=float(t[1] - t[0]))
    assert result.best_shape == "gaussian"


def test_every_shipped_shape_is_scored_so_the_ranking_is_visible() -> None:
    t = np.linspace(-1.0, 1.0, 501)
    result = compare_pulse_shape(np.clip(1.0 - (t / 0.7) ** 2, 0.0, None), dt_s=0.004)
    assert set(result.residuals) == {"gaussian", "parabola", "raised_cosine", "triangle"}


def test_a_flat_window_has_no_pulse_to_fit_and_says_so() -> None:
    with pytest.raises(ValueError, match="no pulse"):
        compare_pulse_shape(np.zeros(501), dt_s=0.004)


# -- the report --------------------------------------------------------------------------------------


def test_a_report_renders_to_markdown_with_its_provenance() -> None:
    reference = _synthetic_noise(200_000, sigma=1e-3, seed=9)
    candidate = _synthetic_noise(200_000, sigma=2e-3, mains=5e-4, seed=10)

    report = GapReport(
        real_run="20260209_cintron1",
        scenario="S1_nominal",
        noise=compare_noise(reference, candidate, fs=FS),
        drift=estimate_drift_rate(candidate, fs=FS),
        pulse=None,
        fit=fit_noise_parameters(candidate, fs=FS),
    )
    text = report.to_markdown()

    assert "20260209_cintron1" in text
    assert "S1_nominal" in text
    assert "sigma" in text.lower()
    assert "--set" in text, "the fitted parameters should be usable without retyping them"


def test_the_report_is_a_comparison_not_a_verdict() -> None:
    """A simulator that matched a real sensor on every statistic would be suspicious rather than
    reassuring, so the report has no pass/fail and says what it is for."""
    reference = _synthetic_noise(100_000, sigma=1e-3, seed=11)
    report = GapReport(
        real_run="r",
        scenario="s",
        noise=compare_noise(reference, reference, fs=FS),
        drift=estimate_drift_rate(reference, fs=FS),
        pulse=None,
        fit=fit_noise_parameters(reference, fs=FS),
    )
    text = report.to_markdown().lower()
    assert "pass" not in text.split("passes")[0] or "fail" not in text
    assert report.to_dict()["noise"]["sigma_ratio"] == pytest.approx(1.0, rel=0.15)


def test_the_overrides_are_paths_the_config_loader_actually_accepts() -> None:
    """The claim `as_overrides` makes is that a fitted number does not have to be retyped. That is
    only true if the lines load, and `--set` refuses a key that does not already exist -- so a
    plausible-looking but wrong path fails loudly at the terminal rather than quietly here.

    Regression: the first version emitted `station.noise.white_sigma` and `station.sensor.q0`.
    Both live under `scenario.`, and neither would have loaded. The original test asserted only
    that the strings contained "noise" and "=", which is a test of the formatting.
    """
    from wimsim.core.config import load_run_config

    signal = _synthetic_noise(400_000, sigma=3.1e-3, mains=7e-4, seed=12)
    fit = fit_noise_parameters(signal, fs=FS)

    cfg = load_run_config("S1_nominal", overrides=fit.as_overrides())

    assert cfg.scenario.noise.white_sigma == pytest.approx(fit.white_sigma, rel=1e-3)
    assert cfg.scenario.noise.mains.amplitude == pytest.approx(fit.mains_amplitude, rel=1e-3)
    assert cfg.scenario.zero_drift.q0 == pytest.approx(fit.baseline, abs=1e-9)


def test_fitting_mains_turns_mains_on() -> None:
    """S1 ships with mains disabled. Handing back an amplitude while leaving `enabled: false` would
    produce a config that silently ignores the number that was just measured -- the more dangerous
    failure, because it looks applied."""
    from wimsim.core.config import load_run_config

    signal = _synthetic_noise(400_000, sigma=1e-3, mains=9e-4, seed=13)
    cfg = load_run_config(
        "S1_nominal", overrides=fit_noise_parameters(signal, fs=FS).as_overrides()
    )
    assert cfg.scenario.noise.mains.enabled is True


# -- finding the crossing to fit ------------------------------------------------------------------


def test_a_window_is_cut_around_the_largest_crossing() -> None:
    """`compare_pulse_shape` needs a window containing one pulse. On a real recording nobody has
    labelled the crossings, so the report has to find one before it can fit it."""
    fs = 2000.0
    n = int(20 * fs)
    signal = _synthetic_noise(n, sigma=1e-4, fs=fs, seed=14)
    t = np.arange(n) / fs
    signal = signal + 5e-3 * np.exp(-0.5 * ((t - 12.0) / 0.02) ** 2)

    window = find_pulse_window(signal, fs=fs, half_width_s=0.2)
    assert window is not None
    peak_at = (np.argmax(window) + 0) / fs
    assert abs(peak_at - 0.2) < 0.05, "the pulse should sit in the middle of the window"
    assert compare_pulse_shape(window, dt_s=1.0 / fs).best_shape == "gaussian"


def test_a_recording_with_no_crossing_in_it_returns_nothing_rather_than_noise() -> None:
    """A minute of an empty road is a valid recording, and fitting a shape to its largest noise
    excursion would produce a confident answer about nothing."""
    fs = 2000.0
    quiet = _synthetic_noise(int(20 * fs), sigma=1e-4, fs=fs, seed=15)
    assert find_pulse_window(quiet, fs=fs) is None


def test_the_scale_used_to_find_a_crossing_is_blind_to_the_crossing() -> None:
    """A plain standard deviation grows with the pulse it is being used to detect, so a large
    enough crossing raises its own threshold out of reach. This is the phase-3 real-data validator
    bug, and it is avoided the same way: the scale comes from successive differences."""
    fs = 2000.0
    n = int(20 * fs)
    t = np.arange(n) / fs
    for amplitude in (1e-3, 1e-2, 1e-1, 1.0):
        signal = _synthetic_noise(n, sigma=1e-4, fs=fs, seed=16)
        signal = signal + amplitude * np.exp(-0.5 * ((t - 12.0) / 0.02) ** 2)
        assert find_pulse_window(signal, fs=fs, half_width_s=0.2) is not None, amplitude


def test_a_negative_going_crossing_is_found_too() -> None:
    """Sign is a wiring convention. A finder that only saw positive pulses would report "no
    crossing" on half of the installations it was pointed at."""
    fs = 2000.0
    n = int(20 * fs)
    t = np.arange(n) / fs
    signal = _synthetic_noise(n, sigma=1e-4, fs=fs, seed=17)
    signal = signal - 5e-3 * np.exp(-0.5 * ((t - 12.0) / 0.02) ** 2)
    assert find_pulse_window(signal, fs=fs, half_width_s=0.2) is not None


def test_a_noisy_crossing_is_still_identified_by_its_shape() -> None:
    """Regression, found on `20260209_cintron1`: the fitter normalised by the single largest
    *sample*, which on a real crossing is a noise spike rather than the top of the pulse.

    That crossing is 1.7 s wide with a peak of about 4 microstrain and per-sample noise of 0.46,
    so the largest sample sits 75 % above the pulse itself. Dividing by it scaled the true shape
    down to 0.57 of unit height, and every candidate then fitted equally badly -- residuals 0.346
    to 0.370, a ranking with no information in it. High-frequency noise is not shape, so it has to
    come off before a shape is fitted.
    """
    rng = np.random.default_rng(18)
    t = np.linspace(-1.5, 1.5, 75_000)
    clean = np.exp(-0.5 * (t / 0.36) ** 2)
    noisy = clean + rng.standard_normal(t.size) * 0.115

    # On the real crossing the largest sample stood 77 % above the pulse; white noise alone
    # gets to about 43 %, which is already enough to destroy the ranking.
    assert np.max(noisy) > 1.4, "the test signal does not actually have the spikes it is about"

    result = compare_pulse_shape(noisy, dt_s=float(t[1] - t[0]))
    assert result.best_shape == "gaussian"
    assert result.residuals["gaussian"] < 0.05
    assert result.fwhm_s == pytest.approx(2.355 * 0.36, rel=0.1)


def test_a_pulse_wider_than_its_window_is_refused_rather_than_measured() -> None:
    """Regression: two of the sixteen real channel-runs came back with an FWHM of exactly 3000.0 ms
    on a 3000 ms window. That is not a 3 s pulse, it is a pulse the window cut in half, and the
    shape ranking computed from it is a ranking of the part that happened to fit.

    Reporting a number that is really the window's own size is worse than reporting nothing,
    because it looks like a measurement of the vehicle.
    """
    t = np.linspace(-1.0, 1.0, 2001)
    too_wide = np.exp(-0.5 * (t / 3.0) ** 2)  # half maximum is far outside the window

    with pytest.raises(ValueError, match="clipped"):
        compare_pulse_shape(too_wide, dt_s=float(t[1] - t[0]))


def test_a_pulse_that_fits_with_room_to_spare_is_still_measured() -> None:
    """The counterpart: the clipping check must not reject the ordinary case, or it would turn
    every crossing into a refusal."""
    t = np.linspace(-1.0, 1.0, 2001)
    fits = np.exp(-0.5 * (t / 0.2) ** 2)
    assert compare_pulse_shape(fits, dt_s=float(t[1] - t[0])).best_shape == "gaussian"


# -- fitting a crossing without being told how wide it is ------------------------------------------


def _record_with_pulse(
    *,
    fwhm_s: float,
    at_s: float = 15.0,
    duration_s: float = 60.0,
    fs: float = 2000.0,
    amplitude: float = 4e-6,
    sigma: float = 4.6e-7,
    drift: float = 0.0,
    seed: int = 20,
) -> np.ndarray:
    """A recording shaped like the real ones: a slow Gaussian crossing on a drifting baseline."""
    rng = np.random.default_rng(seed)
    n = int(duration_s * fs)
    t = np.arange(n) / fs
    s = rng.standard_normal(n) * sigma
    if drift:
        s = s + np.cumsum(rng.standard_normal(n)) * drift
    return s + amplitude * np.exp(-0.5 * ((t - at_s) / (fwhm_s / 2.355)) ** 2)


def test_a_crossing_is_fitted_without_being_told_its_width() -> None:
    """The window has to come from the recording. Too narrow and the fit measures the window
    instead of the vehicle; too wide and the drifting baseline dominates it."""
    record = _record_with_pulse(fwhm_s=0.9)
    fit = fit_crossing(record, fs=2000.0)

    assert fit.comparison is not None, fit.note
    assert fit.comparison.best_shape == "gaussian"
    assert fit.comparison.fwhm_s == pytest.approx(0.9, rel=0.15)


def test_a_width_is_only_reported_when_more_than_one_window_agrees_on_it() -> None:
    """A number that holds at one window width and nowhere else is a property of that width. The
    real recordings make this concrete: `cintron1/Tenzo1` returns 890-942 ms across every window
    that fits it, and that agreement is the evidence the number means anything."""
    fit = fit_crossing(_record_with_pulse(fwhm_s=0.9), fs=2000.0)
    assert fit.agreeing >= 2
    assert fit.spread < 0.15


def test_a_signal_that_switches_between_two_levels_is_not_a_crossing() -> None:
    """`20260209_fabia1/Tenzo1` is a bistable level, plus or minus 1.3 microstrain with plateaus
    tens of seconds long. It is not a vehicle, and a fitter that returned a shape for it would be
    describing a wiring artefact as a pulse."""
    fs = 2000.0
    n = int(60 * fs)
    level = np.where((np.arange(n) / fs > 10) & (np.arange(n) / fs < 35), -1.3e-6, 1.3e-6)
    rng = np.random.default_rng(21)
    fit = fit_crossing(level + rng.standard_normal(n) * 4.6e-7, fs=fs)

    assert fit.comparison is None
    assert fit.note


def test_an_empty_road_is_reported_as_an_empty_road() -> None:
    rng = np.random.default_rng(22)
    fit = fit_crossing(rng.standard_normal(int(60 * 2000)) * 4.6e-7, fs=2000.0)
    assert fit.comparison is None
    assert "no excursion" in fit.note.lower()


def test_a_crossing_wider_than_every_window_offered_is_refused() -> None:
    """Widening is what separates a clipped pulse from a contained one, so a crossing that clips
    every width on the ladder has to come back as a refusal rather than as the widest guess."""
    fit = fit_crossing(_record_with_pulse(fwhm_s=20.0, at_s=30.0), fs=2000.0)
    assert fit.comparison is None
    assert "clipped" in fit.note.lower()


def test_the_widths_that_were_tried_are_reported_either_way() -> None:
    """A refusal that does not say what was tried cannot be acted on, and a fit that does not say
    how many widths agreed cannot be weighed against another run's."""
    fitted = fit_crossing(_record_with_pulse(fwhm_s=0.9), fs=2000.0)
    refused = fit_crossing(_record_with_pulse(fwhm_s=20.0, at_s=30.0), fs=2000.0)
    assert fitted.tried == refused.tried > 2
