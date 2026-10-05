"""The nine figures for the narrowed paper. 300 dpi, deterministic, no timestamps."""

from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

_DPI = 300
OUT = Path("export/figures")
OUT.mkdir(parents=True, exist_ok=True)
RNG = np.random.default_rng(20261004)        # fixed: bootstrap CIs must be reproducible

SCENS = ["S1_nominal", "S2_thermal_cycle", "S3_zero_drift_walk", "S4_step_fault",
         "S5_outage", "S6_combined", "S7_sparse_reference"]
ESTS = ["static_affine", "rls", "kalman"]
COL = {"static_affine": "#444444", "rls": "#1f77b4", "kalman": "#d62728"}
MARK = {"static_affine": "o", "rls": "s", "kalman": "^"}

HS_MAP = {"H1_warm_front": "S2_thermal_cycle", "H2_gain_jolt": "S4_step_fault",
          "H3_slow_fade": "S7_sparse_reference", "H4_pileup": "S6_combined"}

lad = pd.read_csv("export/data/ladder30_long.csv")
cin = pd.read_csv("export/data/cintron_ladder30_long.csv")
hel = pd.read_csv("export/data/heldout30_long.csv")


def wide(df, scen, metric):
    s = df[(df.scenario == scen) & (df.metric == metric)]
    return s.pivot_table(index="seed", columns="estimator", values="value")


def floor_med(df, scen):
    s = df[(df.scenario == scen) & (df.metric == "dynamic_floor_kg")]
    return float(np.median(s.groupby("seed")["value"].first()))


def rank_biserial(y, x):
    d = y - x
    nz = d[d != 0]
    if nz.size == 0:
        return 0.0
    return float((np.sum(nz > 0) - np.sum(nz < 0)) / nz.size)


def rb_boot_ci(y, x, n=5000):
    d = y - x
    idx = RNG.integers(0, len(d), size=(n, len(d)))
    samp = d[idx]
    nz = samp != 0
    cnt = nz.sum(axis=1)
    rb = np.where(cnt > 0, ((samp > 0).sum(axis=1) - (samp < 0).sum(axis=1)) / np.maximum(cnt, 1), 0.0)
    return float(np.quantile(rb, 0.025)), float(np.quantile(rb, 0.975))


def save(fig, name):
    p = OUT / name
    fig.savefig(p, dpi=_DPI, bbox_inches="tight", metadata={"Software": "wimsim"})
    plt.close(fig)
    print(f"  wrote {p}  {p.stat().st_size//1024} KiB")
    return p


def paired_median(df, scen, arm):
    """Median over seeds of (arm - static_affine) MAE: the statistic the Wilcoxon test is run on.

    Decision A of the Phase 0 audit. The difference of medians this replaced corresponds to no
    test reported anywhere, and on S7 it overstated the recovered share by fourteen points.
    """
    w = wide(df, scen, "mae_kg")
    return float(np.median(w[arm] - w["static_affine"]))


def best_tracked(df, scen):
    """The tracked arm with the more negative median paired difference on this scenario."""
    return min(("rls", "kalman"), key=lambda e: paired_median(df, scen, e))


# ---------------------------------------------------------------- F2
def f2():
    frozen_ex, track_ex, floors, tracked_name, paired = [], [], [], [], []
    for s in SCENS:
        f = floor_med(lad, s)
        w = wide(lad, s, "mae_kg")
        bt = best_tracked(lad, s)
        d = paired_median(lad, s, bt)
        floors.append(f)
        fe = max(np.median(w["static_affine"]) - f, 0.0)
        frozen_ex.append(fe)
        # Not clipped at zero: an arm that does worse than frozen shows it (decision B).
        track_ex.append(fe + d)
        paired.append(d)
        tracked_name.append(bt)
    floors = np.array(floors)
    frozen_ex = np.array(frozen_ex)
    track_ex = np.array(track_ex)
    paired = np.array(paired)
    ratio = np.where(floors > 1e-9, frozen_ex / np.maximum(floors, 1e-9), np.nan)

    x = np.arange(len(SCENS))
    wdt = 0.38
    fig, (ax, ax2) = plt.subplots(2, 1, figsize=(11.2, 8.8),
                                  gridspec_kw={"height_ratios": [1.25, 1.0]})

    # -- top: total error, floor + excess -------------------------------------------------
    ax.bar(x - wdt/2, floors, wdt, color="#b0b0b0", edgecolor="black", lw=0.5,
           label="dynamic-load floor (irreducible)")
    ax.bar(x - wdt/2, frozen_ex, wdt, bottom=floors, color="#777777", edgecolor="black",
           lw=0.5, hatch="//", label="recoverable excess — frozen")
    ax.bar(x + wdt/2, floors, wdt, color="#b0b0b0", edgecolor="black", lw=0.5)
    ax.bar(x + wdt/2, track_ex, wdt, bottom=floors, color="#1f77b4", edgecolor="black",
           lw=0.5, label="recoverable excess — best tracked")
    for i_, (f, fe, te) in enumerate(zip(floors, frozen_ex, track_ex, strict=False)):
        ax.text(i_ - wdt/2, f + fe + 10, f"{fe:,.0f}", ha="center", fontsize=7.5)
        ax.text(i_ + wdt/2, f + te + 10, f"{te:,.0f}", ha="center", fontsize=7.5, color="#1f77b4")
    ax.set_xticks(x)
    ax.set_xticklabels([])
    ax.set_ylabel("median absolute error (kg)")
    _nl = chr(10)
    ax.set_title(
        "F2 — Error decomposition: the floor no estimator can remove, and the excess it can" + _nl
        + "[ladder30, 30 seeds. Left bar frozen (static_affine, median); right bar frozen plus the "
          "median paired difference of the best tracked arm." + _nl
        + "S6 dominates the linear scale, so the lower panel repeats the recoverable excess "
          "alone on a log axis.]", fontsize=9.6)
    ax.legend(fontsize=8.5, loc="upper left")
    ax.grid(axis="y", alpha=0.25)
    ax.set_axisbelow(True)

    # -- bottom: the excess alone, log scale ----------------------------------------------
    ax2.bar(x - wdt/2, np.maximum(frozen_ex, 1e-2), wdt, color="#777777", edgecolor="black",
            lw=0.5, hatch="//", label="frozen")
    ax2.bar(x + wdt/2, np.maximum(track_ex, 1e-2), wdt, color="#1f77b4", edgecolor="black",
            lw=0.5, label="best tracked")
    ax2.set_yscale("log")
    ax2.set_ylim(0.3, 1.2e4)
    for i_, (fe, te, bt, _r) in enumerate(zip(frozen_ex, track_ex, tracked_name, ratio, strict=False)):
        rec = 100 * (fe - te) / fe if fe > 1e-9 else np.nan
        big = np.isfinite(rec) and rec >= 50
        ax2.text(i_, 4200, (f"recovers {rec:.0f} %" if np.isfinite(rec) else "n/a"),
                 ha="center", fontsize=8.2,
                 color="#0a6b2f" if big else "#555555",
                 fontweight="bold" if big else "normal")
        ax2.text(i_, 1600, bt, ha="center", fontsize=7.5, color="#1f77b4")
    ax2.set_xticks(x)
    ax2.set_xticklabels(
        [s.replace("_", chr(10), 1) + chr(10)
         + (f"excess = {r:.2f}× floor" if np.isfinite(r) else "floor = 0")  # noqa: RUF001
         for s, r in zip(SCENS, ratio, strict=False)], fontsize=8.2)
    ax2.set_ylabel("recoverable excess over the floor (kg, log)")
    ax2.legend(fontsize=8.5, loc="lower right", ncol=2, framealpha=0.95)
    ax2.grid(axis="y", alpha=0.25, which="both")
    ax2.set_axisbelow(True)

    fig.tight_layout()
    save(fig, "F2__error_decomposition.png")
    return pd.DataFrame({"scenario": SCENS, "floor_kg": np.round(floors, 1),
                         "frozen_excess_kg": np.round(frozen_ex, 1),
                         "best_tracked_arm": tracked_name,
                         "tracked_excess_kg": np.round(track_ex, 1),
                         "excess_over_floor": np.round(ratio, 3),
                         "reducible_share_pct": np.round(100 * frozen_ex / (floors + frozen_ex), 1),
                         "median_paired_diff_kg": np.round(paired, 2),
                         "recovered_pct": np.round(
                             np.where(frozen_ex > 1e-9, -100*paired/np.maximum(frozen_ex,1e-9), np.nan), 1)})


# ---------------------------------------------------------------- F4
def f4():
    rows = []
    for s in SCENS:
        f = floor_med(lad, s)
        w = wide(lad, s, "mae_kg")
        excess = float(np.median(w["static_affine"]) - f)
        for e in ("rls", "kalman"):
            x, y = w["static_affine"].to_numpy(), w[e].to_numpy()
            rb = rank_biserial(y, x)
            lo, hi = rb_boot_ci(y, x)
            rows.append({"scenario": s, "estimator": e, "excess_kg": excess,
                         "floor_kg": f, "excess_over_floor": (excess / f) if f > 1e-9 else np.nan,
                         "rb": rb, "lo": lo, "hi": hi,
                         "median_diff": float(np.median(y - x))})
    t = pd.DataFrame(rows).sort_values("excess_kg").reset_index(drop=True)

    fig, ax = plt.subplots(figsize=(9.6, 7.2))
    ypos = np.arange(len(t))
    for i, r in t.iterrows():
        sig = r.hi < 0 or r.lo > 0
        ax.errorbar(r.rb, i, xerr=[[r.rb - r.lo], [r.hi - r.rb]], fmt=MARK[r.estimator],
                    color=COL[r.estimator], ecolor=COL[r.estimator],
                    markerfacecolor=COL[r.estimator] if sig else "white",
                    capsize=3, lw=1.2, markersize=7)
    ax.axvline(0, color="#999999", lw=0.8, ls=":")
    ax.set_yticks(ypos)
    ax.set_yticklabels([
        f"{r.scenario}  |  {r.estimator}   [excess {r.excess_kg:,.0f} kg"
        + (f" = {r.excess_over_floor:.2f}x floor]" if np.isfinite(r.excess_over_floor) else ", floor 0]")
        for _, r in t.iterrows()], fontsize=7.6)
    ax.set_xlabel("matched-pairs rank-biserial correlation (negative = tracking better)")
    ax.set_xlim(-1.18, 1.18)
    ax.set_title("F4 — Effect size against the frozen arm, ordered by that scenario's recoverable excess\n"
                 "[ladder30, 30 seeds, 14 comparisons; bars are bootstrap 95 % CI, 5000 resamples;\n"
                 "filled marker = CI excludes zero. Ordering is the argument.]", fontsize=9.5)
    ax.grid(axis="x", alpha=0.25)
    ax.set_axisbelow(True)
    h = [plt.Line2D([], [], color=COL[e], marker=MARK[e], ls="", label=e) for e in ("rls", "kalman")]
    ax.legend(handles=h, fontsize=8.5, loc="lower left")
    save(fig, "F4__effect_sizes.png")
    return t


# ---------------------------------------------------------------- F6
def f6():
    fig, axes = plt.subplots(2, 1, figsize=(11.0, 7.4), sharex=True)
    x = np.arange(len(SCENS))
    wdt = 0.26
    rows = []
    for j, e in enumerate(ESTS):
        med_s, lo_s, hi_s, med_a, lo_a, hi_a = [], [], [], [], [], []
        for s in SCENS:
            b = wide(lad, s, "bias_kg")[e].to_numpy()
            for arr, (M, L, H) in ((b, (med_s, lo_s, hi_s)), (np.abs(b), (med_a, lo_a, hi_a))):
                bs = np.median(arr[RNG.integers(0, len(arr), size=(5000, len(arr)))], axis=1)
                M.append(float(np.median(arr)))
                L.append(float(np.quantile(bs, 0.025)))
                H.append(float(np.quantile(bs, 0.975)))
            rows.append({"scenario": s, "estimator": e, "signed_bias_kg": med_s[-1],
                         "abs_bias_kg": med_a[-1], "abs_lo": lo_a[-1], "abs_hi": hi_a[-1]})
        for ax, M, L, H in ((axes[0], med_s, lo_s, hi_s), (axes[1], med_a, lo_a, hi_a)):
            M = np.array(M)
            ax.bar(x + (j - 1) * wdt, M, wdt, color=COL[e], edgecolor="black", lw=0.4, label=e)
            ax.errorbar(x + (j - 1) * wdt, M,
                        yerr=[M - np.array(L), np.array(H) - M],
                        fmt="none", ecolor="black", capsize=2, lw=0.8)

    axes[0].axhline(0, color="black", lw=0.8)
    axes[0].set_ylabel("signed bias (kg)")
    axes[0].set_title("F6 — Bias by scenario and arm, median over 30 seeds, bootstrap 95 % CI\n"
                      "[ladder30. Sign is kept: a bias that cancels in |error| is still a bias.]",
                      fontsize=10)
    axes[1].set_ylabel("absolute bias (kg)")
    axes[1].set_yscale("symlog", linthresh=1.0)
    axes[1].set_xticks(x)
    axes[1].set_xticklabels([s.replace("_", "\n", 1) for s in SCENS], fontsize=8.5)
    # annotate S2, the one that matters
    i2 = SCENS.index("S2_thermal_cycle")
    a = {e: float(np.median(np.abs(wide(lad, "S2_thermal_cycle", "bias_kg")[e]))) for e in ESTS}
    axes[1].annotate(f"S2: {a['static_affine']:.1f} → {a['rls']:.1f} kg (rls),"
                     f" {a['kalman']:.1f} (kalman)\n$p_{{holm}}$ < 1e-5 for both",
                     xy=(i2, a["static_affine"]), xytext=(i2 - 0.1, a["static_affine"] * 9),
                     fontsize=8, ha="center",
                     arrowprops={"arrowstyle": "->", "lw": 0.8})
    for ax in axes:
        ax.grid(axis="y", alpha=0.25)
    ax.set_axisbelow(True)
    axes[0].legend(fontsize=8.5, ncol=3)
    save(fig, "F6__bias_by_scenario.png")
    return pd.DataFrame(rows)


# ---------------------------------------------------------------- F7
def f7():
    tr = pd.read_csv(str(Path("C:/Users/hanze/AppData/Local/Temp/claude/"
                              "C--Users-hanze-Desktop-phd1/"
                              "d7735158-a9a4-43cb-b7de-a34e9f09a33e/scratchpad/b3_traj_seed1.csv")))
    RATE, N_CAL = 180.0, 60
    win_s = N_CAL / RATE * 3600.0
    w = tr[tr.t_s <= win_s]
    t_run_med = float(tr.T_sensor_c.median())
    t_win_mean = float(w.T_sensor_c.mean())
    k_run_med = float(tr.k.median())
    k_win = float(w.k.mean())
    off = (k_win - k_run_med) / k_run_med

    fig, ax = plt.subplots(figsize=(9.4, 5.2))
    bins = np.linspace(tr.T_sensor_c.min(), tr.T_sensor_c.max(), 60)
    ax.hist(tr.T_sensor_c, bins=bins, color="#b0c4de", edgecolor="#5577aa", lw=0.3,
            density=True, label=f"whole run, 72 h  (median {t_run_med:.2f} °C)")
    ax.hist(w.T_sensor_c, bins=bins, color="#d62728", alpha=0.75, edgecolor="#8b0000",
            lw=0.3, density=True,
            label=f"commissioning window, first {win_s/60:.0f} min  (mean {t_win_mean:.2f} °C)")
    ax.axvline(t_run_med, color="#33528a", lw=1.6)
    ax.axvline(t_win_mean, color="#8b0000", lw=1.6)
    ax.annotate("", xy=(t_win_mean, 0.30), xytext=(t_run_med, 0.30),
                arrowprops={"arrowstyle": "<->", "color": "black", "lw": 1.1})
    ax.text((t_win_mean + t_run_med) / 2, 0.315,
            f"ΔT = {t_run_med - t_win_mean:.2f} °C", ha="center", fontsize=9.5)
    ax.text(0.98, 0.70,
            f"gain in window is {100*off:+.3f} % from the run median\n"
            f"→ {off*6325:+.1f} kg on the mean vehicle (6 325 kg)\n"
            f"→ {off*20000:+.1f} kg on a 20 t vehicle\n"
            f"carried as a BIAS for the whole run,\nbecause the fit is then frozen",
            transform=ax.transAxes, ha="right", va="top", fontsize=8.5,
            bbox={"boxstyle": "round", "fc": "#fffbe6", "ec": "#b8860b", "lw": 0.8})
    ax.set_xlabel("sensor-body temperature (°C)")
    ax.set_ylabel("probability density (1/°C)")
    ax.set_title("F7 — The commissioning anchor: where in the thermal cycle the frozen fit was taken\n"
                 "[S2_thermal_cycle, seed 1; 60 calibration passes at 180 veh/h; plant grid 50 Hz]",
                 fontsize=10)
    ax.legend(fontsize=8.5, loc="upper left")
    ax.grid(alpha=0.25)
    ax.set_axisbelow(True)
    save(fig, "F7__commissioning_anchor.png")
    return {"window_min": win_s / 60, "T_window_mean_c": t_win_mean,
            "T_run_median_c": t_run_med, "delta_c": t_run_med - t_win_mean,
            "gain_offset_pct": 100 * off}


# ---------------------------------------------------------------- F9
def f9():
    rows = []
    for s in SCENS:
        wa, wb = wide(lad, s, "mae_kg"), wide(cin, s, "mae_kg")
        if wb is None or wb.empty:
            continue
        for e in ("rls", "kalman"):
            if e not in wb.columns:
                continue
            rows.append({"scenario": s, "estimator": e,
                         "contact": rank_biserial(wa[e].to_numpy(), wa["static_affine"].to_numpy()),
                         "influence": rank_biserial(wb[e].to_numpy(), wb["static_affine"].to_numpy())})
    t = pd.DataFrame(rows)
    fig, ax = plt.subplots(figsize=(7.4, 7.0))
    ax.plot([-1.1, 1.1], [-1.1, 1.1], color="#999999", lw=1.0, ls="--", label="identity")
    ax.axhline(0, color="#cccccc", lw=0.7)
    ax.axvline(0, color="#cccccc", lw=0.7)
    for _, r in t.iterrows():
        ax.scatter(r.contact, r.influence, marker=MARK[r.estimator], s=70,
                   color=COL[r.estimator], edgecolor="black", lw=0.5, zorder=3)
        ax.annotate(r.scenario.replace("_", " ").replace(" ", "\n", 1),
                    (r.contact, r.influence), textcoords="offset points",
                    xytext=(7, -3), fontsize=6.8)
    ax.set_xlabel("effect on the contact-force instrument  (ladder30, rank-biserial)")
    ax.set_ylabel("effect on the influence-line instrument  (cintron_ladder30)")
    ax.set_xlim(-1.15, 1.15)
    ax.set_ylim(-1.15, 1.15)
    ax.set_aspect("equal")
    ax.set_title("F9 — Does the ladder result transfer between instruments?\n"
                 "[30 seeds each; negative = tracking beats frozen. Points on the identity line transfer.]",
                 fontsize=9.5)
    h = [plt.Line2D([], [], color=COL[e], marker=MARK[e], ls="", label=e) for e in ("rls", "kalman")]
    ax.legend(handles=h, fontsize=8.5, loc="upper left")
    ax.grid(alpha=0.25)
    ax.set_axisbelow(True)
    save(fig, "F9__instrument_transfer.png")
    return t


# ---------------------------------------------------------------- F11
def f11():
    rows = []
    for h_s, d_s in HS_MAP.items():
        wd, wh = wide(lad, d_s, "mae_kg"), wide(hel, h_s, "mae_kg")
        for e in ("rls", "kalman"):
            rows.append({"held_out": h_s, "development": d_s, "estimator": e,
                         "dev": rank_biserial(wd[e].to_numpy(), wd["static_affine"].to_numpy()),
                         "held": rank_biserial(wh[e].to_numpy(), wh["static_affine"].to_numpy())})
    t = pd.DataFrame(rows)
    t["reproduces"] = np.sign(t.dev) == np.sign(t.held)
    fig, ax = plt.subplots(figsize=(7.6, 7.2))
    ax.plot([-1.1, 1.1], [-1.1, 1.1], color="#999999", lw=1.0, ls="--", label="identity")
    ax.axhline(0, color="#cccccc", lw=0.7)
    ax.axvline(0, color="#cccccc", lw=0.7)
    ax.fill_between([-1.15, 0], 0, 1.15, color="#ffe6e6", alpha=0.6, zorder=0)
    ax.fill_between([0, 1.15], -1.15, 0, color="#ffe6e6", alpha=0.6, zorder=0)
    ax.text(-1.08, 1.06, "sign does not reproduce", fontsize=7.5, color="#aa0000", va="top")
    for _, r in t.iterrows():
        bad = not r.reproduces
        ax.scatter(r.dev, r.held, marker=MARK[r.estimator], s=95,
                   color=COL[r.estimator], edgecolor="#c00000" if bad else "black",
                   lw=1.8 if bad else 0.5, zorder=3)
        ax.annotate(f"{r.held_out.split('_')[0]}↔{r.development.split('_')[0]}",
                    (r.dev, r.held), textcoords="offset points", xytext=(8, -3),
                    fontsize=7.2, color="#c00000" if bad else "black",
                    fontweight="bold" if bad else "normal")
    ax.set_xlabel("effect on the development scenario (ladder30, rank-biserial)")
    ax.set_ylabel("effect on its held-out counterpart (heldout30)")
    ax.set_xlim(-1.15, 1.15)
    ax.set_ylim(-1.15, 1.15)
    ax.set_aspect("equal")
    ax.set_title("F11 — Development against held out, matched by disturbance class\n"
                 "[30 seeds each; red ring = the effect changed sign. Shaded quadrants are non-reproduction.]",
                 fontsize=9.5)
    h = [plt.Line2D([], [], color=COL[e], marker=MARK[e], ls="", label=e) for e in ("rls", "kalman")]
    ax.legend(handles=h, fontsize=8.5, loc="lower right")
    ax.grid(alpha=0.25)
    ax.set_axisbelow(True)
    save(fig, "F11__development_vs_heldout.png")
    return t


# ---------------------------------------------------------------- F12
def f12(gvw):
    BANDS = [(0, 5, "A (5)", "#c8e6c9"), (5, 7, "B+ (7)", "#dcedc8"),
             (7, 10, "B (10)", "#fff9c4"), (10, 15, "C (15)", "#ffe0b2"),
             (15, 20, "D+ (20)", "#ffccbc"), (20, 25, "D (25)", "#ffcdd2")]
    fig, ax = plt.subplots(figsize=(11.0, 5.8))
    for lo, hi, lab, c in BANDS:
        ax.axhspan(lo, hi, color=c, zorder=0)
        ax.text(len(SCENS) - 0.42, (lo + hi) / 2, lab, fontsize=7.5, va="center", color="#555555")
    x = np.arange(len(SCENS))
    wdt = 0.26
    rows = []
    for j, e in enumerate(ESTS):
        vals = []
        for s in SCENS:
            m = float(np.median(wide(lad, s, "mae_kg")[e]))
            mean_gvw = float(gvw.loc[s, "mean_kg"])
            truck_gvw = float(gvw.loc[s, "mean_ge3500"])
            vals.append(100 * m / mean_gvw)
            rows.append({"scenario": s, "estimator": e, "mae_kg": round(m, 2),
                         "mean_gvw_all_kg": round(mean_gvw, 1),
                         "mae_pct_all": round(100 * m / mean_gvw, 3),
                         "mean_gvw_trucks_ge3p5t_kg": round(truck_gvw, 1),
                         "mae_pct_trucks": round(100 * m / truck_gvw, 3)})
        ax.bar(x + (j - 1) * wdt, vals, wdt, color=COL[e], edgecolor="black", lw=0.4,
               label=e, zorder=3)
    ax.set_xticks(x)
    ax.set_xticklabels([s.replace("_", "\n", 1) for s in SCENS], fontsize=8.5)
    ax.set_ylabel("median absolute error as % of mean gross vehicle weight")
    ax.set_xlim(-0.6, len(SCENS) - 0.1)
    tg = float(gvw.loc["S4_step_fault", "mean_ge3500"])
    ag = float(gvw.loc["S4_step_fault", "mean_kg"])
    _nl = chr(10)
    ax.set_title(
        "F12 — Error relative to vehicle mass, against COST 323 accuracy-class bands" + _nl
        + f"[ladder30, medians over 30 seeds, normalised by each scenario's WHOLE-FLEET mean GVW "
          f"(~{ag:,.0f} kg). The fleet median is 1,555 kg: it is car-dominated." + _nl
        + "INDICATIVE ONLY on two counts — COST 323 classes are defined on a confidence interval "
          "for the mean, not on MAE, and they apply to TRUCKS." + _nl
        + f"Against the ≥3.5 t subset (mean ~{tg:,.0f} kg) every bar falls by about a factor of "
          "four; both denominators are in the sidecar CSV. A truck-only MAE would need per-event "
          "data the export does not carry.]",
        fontsize=8.3)
    ax.legend(fontsize=8.5, ncol=3, loc="upper left")
    ax.grid(axis="y", alpha=0.3, zorder=1)
    ax.set_axisbelow(False)
    save(fig, "F12__accuracy_vs_gvw.png")
    return pd.DataFrame(rows)


# ---------------------------------------------------------------- F13
def f13():
    f = pd.read_csv("export/data/footprint_long.csv")
    p = f.pivot_table(index="estimator", columns="metric", values="value").loc[ESTS]
    host = f.host.iloc[0]
    n_up = int(p["n_updates"].iloc[0])
    fig, axes = plt.subplots(1, 2, figsize=(9.6, 4.2))
    for ax, col, lab, fmt in ((axes[0], "update_us", "time per update (µs)", "{:.2f}"),
                              (axes[1], "state_bytes", "persisted state (bytes)", "{:.0f}")):
        v = p[col].to_numpy()
        ax.bar(range(3), v, 0.55, color=[COL[e] for e in ESTS], edgecolor="black", lw=0.5)
        for i, val in enumerate(v):
            ax.text(i, val * 1.02, fmt.format(val), ha="center", fontsize=9)
        ax.set_xticks(range(3))
        ax.set_xticklabels(ESTS, fontsize=8.5)
        ax.set_ylabel(lab)
        ax.set_ylim(0, v.max() * 1.18)
        ax.grid(axis="y", alpha=0.25)
    ax.set_axisbelow(True)
    fig.suptitle("F13 — What each rung of the ladder costs to run\n"
                 f"[mean over {n_up:,} updates on {host}. "
                 "Not a board measurement; treat as a ratio between arms, not an absolute.]",
                 fontsize=9.5)
    fig.tight_layout()
    save(fig, "F13__estimator_cost.png")
    return p.reset_index()


# ---------------------------------------------------------------- F14
def f14():
    q = pd.read_csv("export/data/kalman_q_ladder.csv")
    ABL = 29.3
    fig, ax = plt.subplots(figsize=(8.6, 5.2))
    ax.plot(q.q, q.dmae, marker="o", color="#d62728", lw=1.8, markersize=8,
            markeredgecolor="black", label="H1 penalty: kalman − static_affine (median, 10 seeds)")  # noqa: RUF001
    for _, r in q.iterrows():
        ax.annotate(f"{r.dmae:+.0f}", (r.q, r.dmae), textcoords="offset points",
                    xytext=(0, 11), ha="center", fontsize=8)
    ax.axhline(ABL, color="#1f77b4", lw=1.6, ls="--",
               label=f"the ablation's quoted 'fixed variance cost' = +{ABL} kg")
    ax.axhline(0, color="#999999", lw=0.8, ls=":")
    ax.axvline(1e-11, color="#555555", lw=1.0, ls="-.", alpha=0.7)
    ax.text(1.15e-11, 60, "shipped Q", fontsize=8, rotation=90, color="#555555")
    ax.annotate("stiffer Q → penalty WORSE\n(the label predicts the opposite)",
                xy=(1e-13, q.dmae.iloc[0]), xytext=(1.6e-13, 190), fontsize=8.5,
                arrowprops={"arrowstyle": "->", "lw": 0.9})
    ax.set_xscale("log")
    ax.set_xlabel("Kalman gain process noise  $Q_{11}$  (sd per second)")
    ax.set_ylabel("MAE penalty against the frozen arm (kg)")
    ax.set_ylim(0, 310)
    ax.set_title("F14 — The H1 penalty against the Kalman's own process noise\n"
                 "[H1_warm_front, 10 seeds; all five points unanimous across seeds, $p_{holm}$ = 0.0098.\n"
                 "The dependence runs the wrong way and never approaches the ablation's value.]",
                 fontsize=9.5)
    ax.legend(fontsize=8.5, loc="lower left")
    ax.grid(alpha=0.25)
    ax.set_axisbelow(True)
    save(fig, "F14__h1_process_noise.png")
    return q


if __name__ == "__main__":
    print("generating figures")
    gvw = pd.read_csv("export/data/vehicle_mass_by_scenario.csv", index_col="scenario")
    t2 = f2()
    t4 = f4()
    t6 = f6()
    t7 = f7()
    t9 = f9()
    t11 = f11()
    t12 = f12(gvw)
    t13 = f13()
    t14 = f14()
    t2.to_csv("export/data/F2_decomposition.csv", index=False)
    t4.to_csv("export/data/F4_effect_sizes.csv", index=False)
    t6.to_csv("export/data/F6_bias.csv", index=False)
    t9.to_csv("export/data/F9_transfer.csv", index=False)
    t11.to_csv("export/data/F11_heldout.csv", index=False)
    t12.to_csv("export/data/F12_relative_accuracy.csv", index=False)
    t13.to_csv("export/data/F13_cost.csv", index=False)
    print("\nF7 anchor:", {k: round(v, 3) for k, v in t7.items()})
    print("\nF2:\n", t2.to_string(index=False))
    print("\nF11:\n", t11.to_string(index=False))
