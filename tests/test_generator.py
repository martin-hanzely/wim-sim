"""The generator as a whole: does the signal it emits match the truth it logs?

This is the test that matters most in phase 1. Everything later -- detector, estimator, controller,
dashboards -- is measured against the truth log. If the truth log and the samples disagree, every
number produced downstream is meaningless, and the disagreement would be invisible because there is
nothing else to compare against.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from wimsim.core.config import RunConfig, load_run_config
from wimsim.signal.generator import SignalGenerator
from wimsim.signal.pulses import pulse_waveform


def _quiet_cfg(**overrides: str) -> RunConfig:
    """S1 with all noise removed: the signal should then equal the truth exactly."""
    base = [
        "scenario.duration_s=300.0",
        "scenario.block_seconds=30.0",
        "scenario.output.samples=full",
        "scenario.noise.white_sigma=0.0",
        "scenario.noise.pink_sigma=0.0",
        "station.temperature_probe.noise_sigma_c=0.0",
    ]
    return load_run_config(
        "S1_nominal", overrides=base + [f"{k}={v}" for k, v in overrides.items()]
    )


def test_noise_free_signal_equals_q_plus_k_times_load() -> None:
    """The model is x = q + k*load + n. With n switched off, that identity must hold to the LSB."""
    cfg = _quiet_cfg()
    gen = SignalGenerator(cfg)
    lsb = cfg.station.adc.lsb
    checked = 0
    for block in gen.blocks():
        t = block.truth
        expected = t.q_true + t.k_true * t.load_kg
        np.testing.assert_allclose(t.x_clean, expected, rtol=0, atol=1e-15)
        # and the reported samples equal that, to within one quantisation step
        assert np.abs(block.samples.raw_value - expected).max() <= lsb / 2 + 1e-12
        checked += block.samples.n
    assert checked == cfg.sample_count


def test_reported_value_lies_on_the_adc_lattice() -> None:
    cfg = _quiet_cfg()
    gen = SignalGenerator(cfg)
    q = gen.quantizer
    for block in gen.blocks():
        np.testing.assert_allclose(
            block.samples.raw_value, q.to_value(block.samples.raw_counts), rtol=0, atol=1e-12
        )


def test_truth_peak_is_the_continuous_maximum_not_the_sampled_one() -> None:
    """``peak_load_kg`` is the maximum of the continuous waveform, and must be exactly that.

    Checked against a grid twenty times finer than the acquisition rate, because the point of
    recording the continuous peak is that it does *not* depend on where the samples happen to fall.
    The sampled maximum is necessarily lower; that gap is the subject of
    :func:`test_discrete_peak_error_is_bounded_by_the_sampling_limit`.
    """
    from wimsim.signal.vehicles import pass_waveform

    cfg = _quiet_cfg()
    gen = SignalGenerator(cfg)
    assert len(gen.passes) > 5
    for p in gen.passes:
        fwhm = p.pulse_fwhm_s[0]
        fine = np.arange(p.t_entry_s - 8 * fwhm, p.t_exit_s + 8 * fwhm, fwhm / 500.0)
        y = pass_waveform(
            fine,
            np.asarray(p.axle_times_s),
            np.asarray(p.axle_applied_kg),
            fwhm,
            cfg.scenario.pulse,
        )
        assert y.max() == pytest.approx(p.peak_load_kg, rel=1e-5)
        assert fine[int(np.argmax(y))] == pytest.approx(p.t_peak_s, abs=fwhm / 50.0)


def test_generated_load_waveform_matches_the_truth_log_per_pass() -> None:
    """The load the generator puts into the signal must be the load the truth log records."""
    from wimsim.signal.vehicles import pass_waveform

    cfg = _quiet_cfg()
    gen = SignalGenerator(cfg)
    checked = 0
    for block in gen.blocks():
        t = block.truth
        t0, t1 = float(t.t_s[0]), float(t.t_s[-1])
        for p in gen.passes:
            margin = 8 * p.pulse_fwhm_s[0]
            if not (t0 + margin < p.t_entry_s and p.t_exit_s < t1 - margin):
                continue  # only passes wholly inside this block, so nothing overlaps the edge
            sel = (t.t_s >= p.t_entry_s - margin) & (t.t_s <= p.t_exit_s + margin)
            expected = pass_waveform(
                t.t_s[sel],
                np.asarray(p.axle_times_s),
                np.asarray(p.axle_applied_kg),
                p.pulse_fwhm_s[0],
                cfg.scenario.pulse,
            )
            # other passes may contribute inside the window; require the difference to be tiny
            np.testing.assert_allclose(t.load_kg[sel], expected, rtol=1e-9, atol=1e-6)
            checked += 1
    assert checked > 5, f"only checked {checked} passes; the fixture is too short to be meaningful"


def test_truth_area_matches_the_generated_waveform() -> None:
    cfg = _quiet_cfg()
    gen = SignalGenerator(cfg)
    dt = 1.0 / cfg.station.sample_rate_hz
    checked = 0
    for block in gen.blocks():
        t = block.truth
        t0, t1 = float(t.t_s[0]), float(t.t_s[-1])
        for p in gen.passes:
            margin = 8 * p.pulse_fwhm_s[0]
            if not (t0 + margin < p.t_entry_s and p.t_exit_s < t1 - margin):
                continue
            sel = (t.t_s >= p.t_entry_s - margin) & (t.t_s <= p.t_exit_s + margin)
            area = float(t.load_kg[sel].sum() * dt)
            assert area == pytest.approx(p.area_load_kg_s, rel=5e-3)
            checked += 1
    assert checked > 5


def _recover_peaks(cfg: RunConfig):
    """Per pass: (relative error of the discrete peak, of the interpolated peak, sampling bound).

    The sampling bound is the worst-case error of picking the largest *sample* of a Gaussian whose
    true maximum can fall anywhere between two samples:
    ``1 - exp(-(dt/2)^2 / (2 sigma^2))``.
    """
    from wimsim.signal.pulses import FWHM_TO_SIGMA

    gen = SignalGenerator(cfg)
    dt = 1.0 / cfg.station.sample_rate_hz
    out = []
    for block in gen.blocks():
        t = block.truth
        t0, t1 = float(t.t_s[0]), float(t.t_s[-1])
        for p in gen.passes:
            margin = 8 * p.pulse_fwhm_s[0]
            if not (t0 + margin < p.t_entry_s and p.t_exit_s < t1 - margin):
                continue
            sel = np.flatnonzero((t.t_s >= p.t_entry_s - margin) & (t.t_s <= p.t_exit_s + margin))
            x = block.samples.raw_value[sel]
            k = float(np.interp(p.t_peak_s, t.t_s, t.k_true))
            q = float(np.interp(p.t_peak_s, t.t_s, t.q_true))
            i = int(np.argmax(x))
            discrete = (x[i] - q) / k
            # three-point parabolic vertex through the sample maximum and its neighbours
            if 0 < i < x.size - 1:
                y0, y1, y2 = x[i - 1] - q, x[i] - q, x[i + 1] - q
                denom = y0 - 2 * y1 + y2
                shift = 0.5 * (y0 - y2) / denom if denom != 0 else 0.0
                interpolated = (y1 - 0.25 * (y0 - y2) * shift) / k
            else:
                interpolated = discrete
            sigma = p.pulse_fwhm_s[0] * FWHM_TO_SIGMA
            bound = 1.0 - np.exp(-((dt / 2) ** 2) / (2 * sigma**2))
            out.append(
                (
                    abs(discrete - p.peak_load_kg) / p.peak_load_kg,
                    abs(interpolated - p.peak_load_kg) / p.peak_load_kg,
                    float(bound),
                )
            )
    return out


def test_discrete_peak_error_is_bounded_by_the_sampling_limit() -> None:
    """Peak-picking on raw samples cannot beat the sample grid, and this pins how badly.

    Worth stating explicitly, because it is a design constraint the phase-2 detector inherits: at
    2 kHz a car's 5 ms pulse is only ten samples wide, so the largest *sample* undershoots the true
    peak by up to a few tenths of a percent. That is not noise and does not average away.
    """
    results = _recover_peaks(_quiet_cfg())
    assert len(results) > 5, f"only {len(results)} passes wholly inside a block"
    for discrete, _interp, bound in results:
        assert discrete <= bound * 1.05 + 1e-9, (
            f"{discrete:.2%} exceeds the sampling bound {bound:.2%}"
        )
    assert max(d for d, _, _ in results) > 1e-4, "the bound would be vacuous if error were zero"


def test_perfect_conditions_recover_the_peak_to_better_than_a_tenth_of_a_percent() -> None:
    """Buildspec section 11: no noise, no drift => error < 0.1 %.

    Phase 1 has no estimator, so the check is made on the quantity an estimator will consume: the
    peak, sub-sample interpolated, inverted through the known k and q. If *this* cannot hit 0.1 %,
    nothing downstream can. Phase 2 repeats the check through the real detector and the StaticAffine
    path; the interpolation used here is a floor, not the implementation.
    """
    results = _recover_peaks(_quiet_cfg())
    worst = max(interp for _, interp, _ in results)
    assert worst < 1e-3, f"worst interpolated peak recovery error {worst:.3%}"


def test_dynamic_load_makes_applied_differ_from_static() -> None:
    cfg = _quiet_cfg(**{"scenario.traffic.dynamic_load.enabled": "true"})
    gen = SignalGenerator(cfg)
    dyn = np.array([p.applied_mass_kg - p.true_mass_kg for p in gen.passes])
    assert (dyn != 0).any()
    rel = np.abs(dyn) / np.array([p.true_mass_kg for p in gen.passes])
    assert rel.max() < 0.25, "body bounce should perturb load, not replace it"


def test_dynamic_load_off_means_applied_equals_static() -> None:
    gen = SignalGenerator(_quiet_cfg())
    for p in gen.passes:
        assert p.applied_mass_kg == pytest.approx(p.true_mass_kg)


def test_gain_step_fault_lands_exactly_on_the_sample_grid() -> None:
    """Faults are evaluated on the sample grid, so a step must not be smeared by interpolation."""
    cfg = load_run_config(
        "S1_nominal",
        overrides=[
            "scenario.duration_s=60.0",
            "scenario.block_seconds=10.0",
            "scenario.output.samples=none",
            'scenario.faults=[{"type": "gain_instability", "label": "jump", "t_start_s": 30.0, "factor": 0.9}]',
        ],
    )
    gen = SignalGenerator(cfg)
    k0 = cfg.station.sensor.k0
    for block in gen.blocks():
        t = block.truth
        before = t.k_true[t.t_s < 30.0]
        after = t.k_true[t.t_s >= 30.0]
        if before.size:
            np.testing.assert_allclose(before, k0, rtol=1e-12)
        if after.size:
            np.testing.assert_allclose(after, 0.9 * k0, rtol=1e-12)


def test_channel_dropout_marks_samples_invalid_and_holds_the_last_value() -> None:
    cfg = load_run_config(
        "S1_nominal",
        overrides=[
            "scenario.duration_s=60.0",
            "scenario.block_seconds=10.0",
            "scenario.output.samples=full",
            'scenario.faults=[{"type": "channel_dropout", "label": "stuck", "t_start_s": 20.0, "duration_s": 15.0, "mode": "stuck"}]',
        ],
    )
    gen = SignalGenerator(cfg)
    for block in gen.blocks():
        s, t = block.samples, block.truth
        inside = (t.t_s >= 20.0) & (t.t_s < 35.0)
        if not inside.any():
            assert s.valid.all()
            continue
        assert not s.valid[inside].any(), "dropout samples must be flagged invalid"
        assert len(np.unique(s.raw_counts[inside])) == 1, "a stuck channel reports one value"
        # the plant keeps moving underneath: truth is unaffected by an acquisition fault
        assert np.isfinite(t.k_true[inside]).all()


def test_dropout_spans_a_block_boundary_without_resetting_the_held_value() -> None:
    cfg = load_run_config(
        "S1_nominal",
        overrides=[
            "scenario.duration_s=60.0",
            "scenario.block_seconds=10.0",
            "scenario.output.samples=full",
            'scenario.faults=[{"type": "channel_dropout", "label": "stuck", "t_start_s": 15.0, "duration_s": 20.0, "mode": "stuck"}]',
        ],
    )
    held = set()
    for block in SignalGenerator(cfg).blocks():
        inside = (block.truth.t_s >= 15.0) & (block.truth.t_s < 35.0)
        if inside.any():
            held.update(np.unique(block.samples.raw_counts[inside]).tolist())
    assert len(held) == 1, f"the held value changed across a block boundary: {sorted(held)}"


def test_clock_skew_shifts_reported_timestamps_only() -> None:
    cfg = load_run_config(
        "S1_nominal",
        overrides=[
            "scenario.duration_s=60.0",
            "scenario.block_seconds=10.0",
            "scenario.output.samples=none",
            'scenario.faults=[{"type": "clock_skew", "label": "slip", "t_start_s": 30.0, "offset_s": 0.5, "drift_ppm": 0.0}]',
        ],
    )
    start_us = int(cfg.scenario.start_time.timestamp() * 1e6)
    for block in SignalGenerator(cfg).blocks():
        s, t = block.samples, block.truth
        implied = (s.ts_us - start_us) / 1e6
        np.testing.assert_allclose(implied - t.t_s, t.clock_offset_s, atol=2e-6)
        assert (t.clock_offset_s[t.t_s < 30.0] == 0.0).all()
        assert np.allclose(t.clock_offset_s[t.t_s >= 30.0], 0.5)


def test_generator_is_single_use() -> None:
    gen = SignalGenerator(_quiet_cfg())
    for _ in gen.blocks():
        break
    with pytest.raises(RuntimeError, match="single-use"):
        next(iter(gen.blocks()))
    gen.reset()
    next(iter(gen.blocks()))  # fine again after reset


def test_saturation_is_flagged_when_the_range_is_too_small() -> None:
    cfg = _quiet_cfg(**{"station.adc.range_max": "0.15"})
    gen = SignalGenerator(cfg)
    saturated = any(block.samples.saturated.any() for block in gen.blocks())
    assert saturated, "a 0.15 mV/V ceiling cannot represent any vehicle"


def test_truth_files_agree_with_the_generator(short_run) -> None:
    """The written truth log must be the same truth the generator produced."""
    passes = pd.read_parquet(short_run.out_dir / "truth_passes.parquet")
    assert len(passes) == len(short_run.generator.passes)
    for row, p in zip(passes.itertuples(), short_run.generator.passes, strict=True):
        assert row.pass_id == p.pass_id
        assert row.true_mass_kg == pytest.approx(p.true_mass_kg)
        assert row.peak_load_kg == pytest.approx(p.peak_load_kg)
    assert passes.pass_id.is_unique


def test_pass_ids_are_deterministic_across_runs(short_cfg: RunConfig) -> None:
    a = SignalGenerator(short_cfg).passes
    b = SignalGenerator(short_cfg).passes
    assert [p.pass_id for p in a] == [p.pass_id for p in b]


def test_pass_waveform_superposes_axles() -> None:
    """``pass_waveform`` is the primitive both the generator and the truth log build on."""
    from wimsim.core.config import PulseConfig
    from wimsim.signal.vehicles import pass_waveform

    cfg = PulseConfig(shape="gaussian")
    t = np.linspace(-0.1, 0.1, 5001)
    taus = np.array([-0.01, 0.01])
    loads = np.array([3000.0, 5000.0])
    manual = sum(
        load * pulse_waveform(t - tau, 0.01, cfg) for tau, load in zip(taus, loads, strict=True)
    )
    np.testing.assert_allclose(pass_waveform(t, taus, loads, 0.01, cfg), manual, rtol=0, atol=0)


def test_widely_spaced_axles_peak_at_the_heaviest_axle() -> None:
    """With no overlap, peak_load_kg must be exactly the heaviest axle -- and with overlap, more."""
    from wimsim.core.config import PulseConfig
    from wimsim.signal.vehicles import pass_waveform

    cfg = PulseConfig(shape="gaussian")
    fwhm = 0.005
    loads = np.array([4000.0, 7000.0])

    far = np.array([0.0, 1.0])
    grid = np.linspace(-0.2, 1.2, 200_001)
    assert pass_waveform(grid, far, loads, fwhm, cfg).max() == pytest.approx(7000.0, rel=1e-6)

    near = np.array([0.0, 0.5 * fwhm])
    assert pass_waveform(grid, near, loads, fwhm, cfg).max() > 7000.0
