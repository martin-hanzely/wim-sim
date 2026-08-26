"""Phase-1 checkpoint figures.

Two plots, both diagnostic rather than decorative:

:func:`plot_pass`
    One vehicle pass: the quantised samples the station reported, with the noise-free signal that
    produced them drawn on top. The clean signal is *reconstructed* from the truth log's axle
    times, applied loads and the plant state at the pass -- not stored -- which is why the overlay is
    exact rather than interpolated from a 1 Hz series. If these two curves do not sit on top of each
    other, the generator disagrees with its own truth log and nothing downstream is worth measuring.

:func:`plot_run`
    The plant over the whole run: zero line, gain against its nominal value, both temperatures, and
    shaded intervals wherever a fault is active. This is the phase-1 preview of the phase-4
    calibration dashboard, with the estimate track still missing.

Grafana is the UI (buildspec section 13). These exist to make phase 1 checkable, not to become one.
"""

from __future__ import annotations

import itertools
import json
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

from wimsim.core.config import RunConfig
from wimsim.signal.pulses import pulse_waveform

__all__ = ["load_run", "plot_pass", "plot_run"]


def load_run(run_dir: Path) -> tuple[RunConfig, dict]:
    manifest = json.loads((run_dir / "manifest.json").read_text(encoding="utf-8"))
    return RunConfig.model_validate(manifest["config"]), manifest


def _clean_waveform(t: np.ndarray, row: pd.Series, cfg: RunConfig) -> np.ndarray:
    """The noise-free analog signal for one pass, rebuilt from the truth log."""
    out = np.full_like(t, float(row["q_at_peak"]))
    k = float(row["k_at_peak"])
    fwhm = float(row["pulse_fwhm_s"])
    for tau, load in zip(row["axle_times_s"], row["axle_applied_kg"], strict=True):
        out += k * float(load) * pulse_waveform(t - float(tau), fwhm, cfg.scenario.pulse)
    return out


def plot_pass(
    run_dir: Path,
    *,
    index: int | None = 0,
    pass_id: str | None = None,
    out_path: Path | None = None,
    pad_s: float = 0.15,
) -> Path:
    run_dir = Path(run_dir)
    cfg, manifest = load_run(run_dir)
    passes = pd.read_parquet(run_dir / "truth_passes.parquet")

    if pass_id is not None:
        match = passes[passes.pass_id == pass_id]
        if match.empty:
            raise SystemExit(f"no pass with pass_id {pass_id!r} in {run_dir}")
        row = match.iloc[0]
    else:
        if index is None or index >= len(passes):
            raise SystemExit(f"pass index {index} out of range (run has {len(passes)} passes)")
        row = passes.iloc[index]

    samples_path = run_dir / "samples.parquet"
    if not samples_path.exists():
        raise SystemExit(
            f"{run_dir} was written with output.samples: none, so there is no waveform to plot"
        )

    t_lo = float(row["t_entry_s"]) - pad_s
    t_hi = float(row["t_exit_s"]) + pad_s
    samples = pd.read_parquet(
        samples_path, filters=[("t_s", ">=", t_lo), ("t_s", "<=", t_hi)]
    ).sort_values("t_s")
    if samples.empty:
        raise SystemExit(
            f"no samples stored around t={t_lo:.2f}..{t_hi:.2f}s; widen output.window_pad_s"
        )

    grid = np.linspace(t_lo, t_hi, 4000)
    clean = _clean_waveform(grid, row, cfg)
    unit = cfg.station.adc.unit

    fig, (ax, ax2) = plt.subplots(
        2, 1, figsize=(11, 7), sharex=True, height_ratios=[3, 1], constrained_layout=True
    )

    # true signal underneath, wide and pale; reported samples on top, thin and dark. Drawn this way
    # round so that the interesting failure -- samples departing from truth -- is what stands out.
    ax.plot(grid, clean, lw=3.0, color="#f0a08f", label="true noise-free signal", zorder=1)
    ax.plot(
        samples.t_s,
        samples.raw_value,
        lw=0.7,
        color="#1f3d6b",
        label=f"reported samples ({unit})",
        zorder=2,
    )
    ax.axhline(float(row["q_at_peak"]), lw=0.9, ls=":", color="#666", label="true zero line q(t)")

    for j, (tau, static, applied) in enumerate(
        zip(row["axle_times_s"], row["axle_static_kg"], row["axle_applied_kg"], strict=True)
    ):
        ax.axvline(float(tau), lw=0.7, ls="--", color="#999", alpha=0.8)
        ax.annotate(
            f"axle {j + 1}\n{static:.0f} kg\n(applied {applied:.0f})",
            xy=(float(tau), ax.get_ylim()[1]),
            xytext=(0, -34),
            textcoords="offset points",
            ha="center",
            fontsize=7,
            color="#444",
        )

    peak_units = float(row["true_peak_units"]) + float(row["q_at_peak"])
    ax.plot([float(row["t_peak_s"])], [peak_units], "o", ms=6, color="#d94f3d")
    ax.set_ylabel(f"signal [{unit}]")
    ax.legend(loc="upper right", fontsize=8)
    ax.grid(alpha=0.25)
    ax.set_title(
        f"{manifest['scenario']} -- pass {int(row['pass_index'])} ({row['vehicle_class']}), "
        f"{row['speed_kmh']:.0f} km/h, {int(row['axle_count'])} axles\n"
        f"true mass {row['true_mass_kg']:.0f} kg   applied {row['applied_mass_kg']:.0f} kg "
        f"(dynamic error {row['dynamic_error_kg']:+.0f} kg)   "
        f"k={row['k_at_peak']:.6g} {unit}/kg   T_sensor={row['t_sensor_at_peak']:.2f} C",
        fontsize=9,
    )

    resid = samples.raw_value.to_numpy() - np.interp(samples.t_s.to_numpy(), grid, clean)
    ax2.plot(samples.t_s, resid, lw=0.7, color="#555")
    ax2.axhline(0.0, lw=0.8, color="#aaa")
    ax2.set_ylabel(f"noise [{unit}]")
    ax2.set_xlabel("t [s] since run start")
    ax2.grid(alpha=0.25)
    ax2.set_title(
        f"reported minus true: sd {resid.std():.3e} {unit} "
        f"(configured white {cfg.scenario.noise.white_sigma:.1e} + "
        f"pink {cfg.scenario.noise.pink_sigma:.1e}, ADC lsb {cfg.station.adc.lsb:.2e})",
        fontsize=8,
    )

    out_path = Path(out_path or run_dir / f"pass_{int(row['pass_index']):05d}.png")
    fig.savefig(out_path, dpi=140)
    plt.close(fig)
    return out_path


def plot_run(run_dir: Path, *, out_path: Path | None = None) -> Path:
    run_dir = Path(run_dir)
    cfg, manifest = load_run(run_dir)
    ts = pd.read_parquet(run_dir / "truth_timeseries.parquet")
    passes = pd.read_parquet(run_dir / "truth_passes.parquet")
    unit = cfg.station.adc.unit
    hours = ts.t_s / 3600.0

    fig, axes = plt.subplots(4, 1, figsize=(12, 10), sharex=True, constrained_layout=True)

    axes[0].plot(hours, ts.q_true, lw=1.0, color="#3b7dd8")
    axes[0].set_ylabel(f"q(t) [{unit}]")
    axes[0].set_title("true zero line", fontsize=9, loc="left")

    k0 = cfg.station.sensor.k0
    axes[1].plot(hours, 100.0 * (ts.k_true / k0 - 1.0), lw=1.0, color="#d94f3d")
    axes[1].axhline(0.0, lw=0.8, ls=":", color="#888")
    axes[1].set_ylabel("k/k0 - 1 [%]")
    axes[1].set_title(
        f"true sensitivity relative to nominal k0={k0:g} {unit}/kg", fontsize=9, loc="left"
    )

    axes[2].plot(hours, ts.t_ambient_true, lw=0.9, color="#888", label="ambient")
    axes[2].plot(hours, ts.t_sensor_true, lw=1.3, color="#c98b1b", label="sensor body")
    axes[2].axhline(cfg.station.sensor.t_ref_c, lw=0.8, ls=":", color="#aaa", label="T_ref")
    axes[2].set_ylabel("T [degC]")
    axes[2].legend(loc="upper right", fontsize=8)
    axes[2].set_title(
        f"thermal lag tau={cfg.station.thermal.tau_thermal_s / 60:.0f} min -- the sensor trails the "
        f"air, which is why instantaneous compensation cannot be exact",
        fontsize=9,
        loc="left",
    )

    axes[3].plot(
        passes.t_peak_s / 3600.0,
        passes.true_mass_kg / 1000.0,
        ".",
        ms=3,
        color="#4a7",
        label="true mass",
    )
    axes[3].set_ylabel("mass [t]")
    axes[3].set_xlabel("t [h] since run start")
    axes[3].legend(loc="upper right", fontsize=8)
    axes[3].set_title(f"{len(passes)} passes", fontsize=9, loc="left")

    # Shade fault intervals across every panel, from the truth log's own labels. Segmented on the
    # label *string*, not on active/inactive: when a second fault starts while the first is still
    # running, the shading is contiguous but the attribution changes, and the attribution is the
    # part a reader needs.
    labels = ts.active_faults.fillna("").to_numpy()
    if (labels != "").any():
        edges = np.flatnonzero(labels[1:] != labels[:-1]) + 1
        bounds = np.concatenate([[0], edges, [labels.size]])
        for lo, hi in itertools.pairwise(bounds):
            if labels[lo] == "":
                continue
            for ax in axes:
                ax.axvspan(hours.iloc[lo], hours.iloc[hi - 1], color="#d94f3d", alpha=0.09, lw=0)
            axes[0].annotate(
                labels[lo].replace(";", "\n"),
                xy=(hours.iloc[lo], axes[0].get_ylim()[1]),
                xytext=(3, -9),
                textcoords="offset points",
                fontsize=7,
                va="top",
                color="#a33",
            )

    for ax in axes:
        ax.grid(alpha=0.25)
    fig.suptitle(
        f"{manifest['scenario']} -- plant ground truth   "
        f"[config {manifest['provenance']['config_hash'][:12]}  seed {cfg.scenario.seed}]",
        fontsize=11,
    )

    out_path = Path(out_path or run_dir / "run_overview.png")
    fig.savefig(out_path, dpi=130)
    plt.close(fig)
    return out_path
