"""F6, corrected: estimated gain against the true gain, both in the sensor direction.

The original `s2__gain_tracking.png` drew each arm's `gain` column — sensor units per kg, i.e. k̂ —
against "required (1/k_true)", the prediction direction. Plotted as deviations from their own
medians, the two directions have opposite signs, so any agreement appeared as anti-correlation
(REVISION_LOG, item 1.5). This redraws the same run with k_true, like with like.

Inputs (both from S2_thermal_cycle, seed 1, ladder30's configuration):
  export/data/s2_gain_trajectory_long.csv   per-event k̂ for static_affine, rls, kalman
  export/data/F8_s2_seed1_trajectory.csv    true k(t) and temperatures on the plant grid
Writes export/figures/F6__s2_gain_tracking__CORRECTION.png, its sidecar .md, and
export/data/F6_correction_stats.csv.
"""

# ruff: noqa: RUF001

from __future__ import annotations

from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

OUT = Path("export/figures")
DATA = Path("export/data")
STEM = "F6__s2_gain_tracking__CORRECTION"
COLORS = {"static_affine": "black", "rls": "#1f77b4", "kalman": "#d62728"}
# the Kalman start-up transient, excluded from the statistics as in the original figure
WARMUP_S = 3600.0


def main() -> pd.DataFrame:
    est = pd.read_csv(DATA / "s2_gain_trajectory_long.csv")
    tr = pd.read_csv(DATA / "F8_s2_seed1_trajectory.csv").sort_values("t_s")
    k_true = np.interp(est.t_s, tr.t_s, tr.k)
    est = est.assign(k_true=k_true)

    rows = []
    for name, g in est.groupby("estimator"):
        g = g[g.t_s >= WARMUP_S]
        dev_hat = g.gain / g.gain.median() - 1.0
        dev_true = g.k_true / g.k_true.median() - 1.0
        corr = float(np.corrcoef(g.gain, g.k_true)[0, 1]) if g.gain.std() > 0 else np.nan
        corr_mismatch = (
            float(np.corrcoef(g.gain, 1.0 / g.k_true)[0, 1]) if g.gain.std() > 0 else np.nan
        )
        rms_dist = float(np.sqrt(np.mean((dev_hat - dev_true) ** 2)))
        rows.append(
            {
                "estimator": name,
                "n_events": len(g),
                "corr_khat_ktrue": corr,
                "corr_khat_inv_ktrue_original_figure": corr_mismatch,
                "rms_distance_pct": 100 * rms_dist,
            }
        )
    stats = pd.DataFrame(rows).set_index("estimator").loc[["static_affine", "rls", "kalman"]]
    const_rms = 100 * float(
        np.sqrt(np.mean((tr.k / tr.k.median() - 1.0)[tr.t_s >= WARMUP_S] ** 2))
    )

    fig, (ax, axt) = plt.subplots(
        2, 1, figsize=(10, 7.2), sharex=True, gridspec_kw={"height_ratios": [2.4, 1]}
    )
    th = tr.t_s / 3600
    ax.plot(th, 100 * (tr.k / tr.k.median() - 1), color="#2ca02c", lw=2.2,
            label="true gain k_true (sensor direction)")
    for name in ["static_affine", "rls", "kalman"]:
        g = est[est.estimator == name]
        lab = {"static_affine": "static_affine (frozen)"}.get(name, name)
        ax.step(g.t_s / 3600, 100 * (g.gain / g.gain.median() - 1), where="post",
                color=COLORS[name], lw=1.2 if name != "static_affine" else 1.4,
                ls="--" if name == "static_affine" else "-", label=f"{lab}: k̂")
    ax.set_ylim(-1.6, 1.6)
    ax.axhline(0, color="grey", lw=0.5, ls=":")
    ax.set_ylabel("deviation from own median (%)")
    r = stats["corr_khat_ktrue"]
    ax.text(
        0.01, 0.03,
        f"corr(k̂, k_true), t ≥ 1 h:  RLS {r['rls']:+.2f}   Kalman {r['kalman']:+.2f}\n"
        f"rms distance from k_true:  RLS {stats.loc['rls', 'rms_distance_pct']:.2f} %   "
        f"Kalman {stats.loc['kalman', 'rms_distance_pct']:.2f} %   "
        f"a constant {const_rms:.2f} %",
        transform=ax.transAxes, fontsize=8.5, va="bottom",
        bbox={"boxstyle": "round", "fc": "white", "ec": "grey", "lw": 0.6},
    )
    ax.set_title(
        "F6 (CORRECTION) — S2_thermal_cycle, seed 1: estimated gain against the true gain, "
        "both sensor-side\n[the original plotted k̂ against 1/k_true, which inverts the sign "
        "of any agreement; Kalman start-up transient clipped]",
        fontsize=9.5,
    )
    ax.legend(fontsize=8, ncol=2, loc="upper right")
    ax.grid(alpha=0.25)

    axt.plot(th, tr.T_air_c, color="#ff7f0e", lw=1, label="ambient")
    axt.plot(th, tr.T_probe_c, color="#17becf", lw=1.6, label="probe (what the edge reads)")
    axt.plot(th, tr.T_sensor_c, color="#8c564b", lw=1.2, ls="--",
             label="sensor body (what sets k)")
    axt.set_ylabel("temperature (°C)")
    axt.set_xlabel("time (h)")
    axt.set_ylim(top=31)
    axt.legend(fontsize=8, ncol=3, loc="upper right")
    axt.grid(alpha=0.25)
    fig.tight_layout()
    OUT.mkdir(parents=True, exist_ok=True)
    fig.savefig(OUT / f"{STEM}.png", dpi=300, metadata={"Software": None})
    plt.close(fig)

    stats.round(4).to_csv(DATA / "F6_correction_stats.csv")
    (OUT / f"{STEM}.md").write_text(
        "# F6 (CORRECTION) — Estimated against true gain on S2\n\n"
        f"**File:** `{STEM}.png`  \n"
        "**Replaces:** `s2__gain_tracking.png`, which plotted k̂ against 1/k_true.  \n"
        "**Data:** `export/data/s2_gain_trajectory_long.csv`, "
        "`export/data/F8_s2_seed1_trajectory.csv`; statistics in "
        "`export/data/F6_correction_stats.csv`.\n\n"
        "**Statistic:** descriptive, one run: each series as a deviation from its own median; "
        "Pearson correlation of k̂ with k_true and rms distance between their relative "
        "deviations, from t = 1 h (after the Kalman start-up transient).\n\n"
        "**Sample:** S2_thermal_cycle, seed 1, ladder30's configuration.\n\n"
        "## Caption\n\n"
        "Estimated sensor gain k̂ for the frozen, RLS and Kalman arms against the true gain "
        "k_true, both in the sensor direction and both as deviations from their own medians. "
        f"On this seed k̂ correlates with k_true at {r['rls']:+.2f} (RLS) and "
        f"{r['kalman']:+.2f} (Kalman): weakly positive, not negative. The adaptive "
        f"estimates sit {stats.loc['rls', 'rms_distance_pct']:.2f} % (RLS) and "
        f"{stats.loc['kalman', 'rms_distance_pct']:.2f} % (Kalman) rms from the true "
        f"trajectory, against {const_rms:.2f} % for a constant: their motion is mostly noise, "
        "not tracking. Over ten seeds (item 1.5, instrumented runs) the correlation is +0.03 "
        "to +0.21 by arm and the distance 2–7 times a constant's.\n\n"
        "## Notes\n\n"
        "- The original figure's anti-correlation is the sign of a direction mismatch: on the "
        "same data, corr(k̂, 1/k_true) is "
        f"{stats.loc['rls', 'corr_khat_inv_ktrue_original_figure']:+.2f} (RLS) and "
        f"{stats.loc['kalman', 'corr_khat_inv_ktrue_original_figure']:+.2f} (Kalman).\n"
        "- The script that drew the original was never committed; this one is "
        "`scripts/f6_gain_tracking_correction.py`.\n",
        encoding="utf-8",
    )
    return stats


if __name__ == "__main__":
    s = main()
    print(s.round(4).to_string())
