"""The paper's regenerated figures, numbered as in the article. 300 dpi, deterministic, no timestamps.

Article numbering (repo file -> article): F2 -> F2, F4 -> F5, F6 -> F7, F7 -> F8, F9 -> F10,
F11 -> F12, F13 -> F13, F14 -> F14; F3 is new. Article F4, F6, F9 and F11 are sweep figures carried
over unchanged. The repo's former F12 (accuracy against GVW) is not in the article and is no longer
generated.

Every figure gets a sidecar ``export/figures/<stem>.md`` naming the statistic it plots. The
statistic is the median of per-seed paired differences throughout (decision A); the difference of
medians is not used anywhere.
"""

# ruff: noqa: RUF001  -- captions use typographic minus and multiplication signs on purpose

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


RES = Path("data/results")


def results(name):
    """A Phase 1 sweep's results; ``name`` with shards ``name_s*`` is merged first."""
    out = RES / name
    if not (out / "results.parquet").exists():
        from wimsim.experiments.merge import merge_shards
        merge_shards(sorted(RES.glob(f"{name}_s[0-9]*")), out_dir=out)
    return pd.read_parquet(out / "results.parquet")


def mae_by_seed(names, scen, est, edge=None):
    """Per-seed MAE of one arm on one scenario, concatenated over sweeps (stages), seed-indexed."""
    parts = []
    for n in names:
        d = results(n)
        d = d[(d.scenario == scen) & (d.estimator == est) & ~d.failed.astype(bool)]
        if edge is not None:
            d = d[d.edge_config == edge]
        parts.append(d.set_index("seed").mae_kg)
    out = pd.concat(parts).sort_index()
    assert not out.index.duplicated().any(), (names, scen, est, edge)
    return out


def stored_by_seed(df, scen, est):
    return wide(df, scen, "mae_kg")[est]


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


def rank_biserial_ranked(y, x):
    """Matched-pairs rank-biserial weighted by rank (Kerby), the form the Wilcoxon test carries."""
    from wimsim.experiments.stats import wilcoxon_signed_rank
    return float(wilcoxon_signed_rank(list(x), list(y)).effect_size)


def rb_boot_ci(y, x, n=5000):
    d = y - x
    idx = RNG.integers(0, len(d), size=(n, len(d)))
    samp = d[idx]
    nz = samp != 0
    cnt = nz.sum(axis=1)
    rb = np.where(cnt > 0, ((samp > 0).sum(axis=1) - (samp < 0).sum(axis=1)) / np.maximum(cnt, 1), 0.0)
    return float(np.quantile(rb, 0.025)), float(np.quantile(rb, 0.975))


def sidecar(png, *, title, statistic, sample, data, caption, notes=()):
    """Write ``<stem>.md`` beside the figure. Every number in it is computed by the caller."""
    p = OUT / (Path(png).stem + ".md")
    lines = [f"# {title}", "", f"**File:** `{png}`  ", f"**Data:** {data}", "",
             f"**Statistic:** {statistic}", "", f"**Sample:** {sample}", "", "## Caption", "",
             caption]
    if notes:
        lines += ["", "## Notes", ""] + [f"- {n}" for n in notes]
    p.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"  wrote {p}")


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
           lw=0.5, hatch="//", label="excess = MAE − floor, frozen (a difference, not a component)")
    ax.bar(x + wdt/2, floors, wdt, color="#b0b0b0", edgecolor="black", lw=0.5)
    ax.bar(x + wdt/2, track_ex, wdt, bottom=floors, color="#1f77b4", edgecolor="black",
           lw=0.5, label="excess after the best tracked arm's median paired difference")
    for i_, (f, fe, te) in enumerate(zip(floors, frozen_ex, track_ex, strict=False)):
        ax.text(i_ - wdt/2, f + fe + 10, f"{fe:,.0f}", ha="center", fontsize=7.5)
        ax.text(i_ + wdt/2, f + te + 10, f"{te:,.0f}", ha="center", fontsize=7.5, color="#1f77b4")
    ax.set_xticks(x)
    ax.set_xticklabels([])
    ax.set_ylabel("median absolute error (kg)")
    _nl = chr(10)
    ax.set_title(
        "F2 — The floor no estimator can remove, and the excess over it" + _nl
        + "[ladder30, 30 seeds. Excess = median frozen MAE − median floor: a difference of MAEs, "
          "not an additive component." + _nl
        + "Right bar: frozen excess plus the best tracked arm's MEDIAN PAIRED DIFFERENCE. "
          "Lower panel: the excess alone, log axis.]", fontsize=9.6)
    ax.legend(fontsize=8.5, loc="upper left")
    ax.grid(axis="y", alpha=0.25)
    ax.set_axisbelow(True)

    # -- bottom: the excess alone, log scale ----------------------------------------------
    ax2.bar(x - wdt/2, np.maximum(frozen_ex, 1e-2), wdt, color="#777777", edgecolor="black",
            lw=0.5, hatch="//", label="frozen")
    ax2.bar(x + wdt/2, np.maximum(track_ex, 1e-2), wdt, color="#1f77b4", edgecolor="black",
            lw=0.5, label="best tracked")
    ax2.set_yscale("log")
    ax2.set_ylim(0.3, 2.0e4)
    for i_, (fe, te, bt, f) in enumerate(zip(frozen_ex, track_ex, tracked_name, floors, strict=False)):
        rec = 100 * (fe - te) / fe if fe > 1e-9 else np.nan
        big = np.isfinite(rec) and rec >= 50
        ax2.text(i_, 6000, (f"recovers {rec:.0f} %" if abs(rec) >= 1 else f"recovers {rec:.1f} %"),
                 ha="center", fontsize=8.2,
                 color="#0a6b2f" if big else "#555555",
                 fontweight="bold" if big else "normal")
        ax2.text(i_, 2600, f"excess share {100 * fe / (f + fe):.0f} %", ha="center", fontsize=7.5,
                 color="#8b0000" if f < 1e-9 else "#555555",
                 fontweight="bold" if f < 1e-9 else "normal")
        ax2.text(i_, 1150, bt, ha="center", fontsize=7.5, color="#1f77b4")
    ax2.set_xticks(x)
    ax2.set_xticklabels(
        [s.replace("_", chr(10), 1) + chr(10)
         + (f"excess = {r:.2f}× floor" if np.isfinite(r) else "floor = 0")
         for s, r in zip(SCENS, ratio, strict=False)], fontsize=8.2)
    ax2.set_ylabel("recoverable excess over the floor (kg, log)")
    ax2.legend(fontsize=8.5, loc="lower right", ncol=2, framealpha=0.95)
    ax2.grid(axis="y", alpha=0.25, which="both")
    ax2.set_axisbelow(True)

    fig.tight_layout()
    save(fig, "F2__error_decomposition.png")
    per_arm = {f"{e}_{k}": [] for e in ("rls", "kalman") for k in ("paired_diff_kg", "recovered_pct")}
    for s, fe in zip(SCENS, frozen_ex, strict=True):
        for e in ("rls", "kalman"):
            d = paired_median(lad, s, e)
            per_arm[f"{e}_paired_diff_kg"].append(round(d, 2))
            per_arm[f"{e}_recovered_pct"].append(round(-100 * d / fe, 1) if fe > 1e-9 else np.nan)
    return pd.DataFrame({"scenario": SCENS, "floor_kg": np.round(floors, 1),
                         "frozen_excess_kg": np.round(frozen_ex, 1),
                         "best_tracked_arm": tracked_name,
                         "tracked_excess_kg": np.round(track_ex, 1),
                         "excess_over_floor": np.round(ratio, 3),
                         "reducible_share_pct": np.round(100 * frozen_ex / (floors + frozen_ex), 1),
                         "median_paired_diff_kg": np.round(paired, 2),
                         "recovered_pct": np.round(
                             np.where(frozen_ex > 1e-9, -100*paired/np.maximum(frozen_ex,1e-9), np.nan), 1),
                         **per_arm})


def f2_sidecar(t):
    s1 = t.set_index("scenario").loc["S1_nominal"]
    hi = t[t.recovered_pct >= 50]
    sidecar(
        "F2__error_decomposition.png", title="F2 — Error decomposition",
        statistic="Recovered share = −(median over seeds of the per-seed paired difference, tracked − "
                  "frozen MAE) / frozen excess. Frozen excess = median frozen MAE − median dynamic-load "
                  "floor. The difference of medians is not used.",
        sample="ladder30, 30 seeds per scenario per arm, seven development scenarios.",
        data="`export/data/F2_decomposition.csv` (best arm and both arms, per scenario).",
        caption=(
            "Upper panel: median absolute error per scenario, drawn as the dynamic-load floor "
            "(the error of an estimator that knew each vehicle's static mass exactly) with the excess "
            "over it stacked above, for the frozen arm (left) and for the frozen arm plus the best "
            "tracked arm's median paired difference (right). The excess is a DIFFERENCE, MAE_total − "
            "MAE_floor, not a component: mean absolute error is not additive, and the stacked bar shows "
            "where the floor sits, not a partition of the error. Lower panel: the excess alone on a log "
            "axis, with the excess share (excess / frozen MAE) and the share of it the best tracked arm "
            "recovers. "
            + "; ".join(f"{r.scenario.split('_')[0]} {r.recovered_pct:.1f} % ({r.best_tracked_arm})"
                        for _, r in hi.iterrows())
            + f". S1 is shown deliberately: its floor is {s1.floor_kg:.1f} kg, so its excess share is "
            f"{s1.reducible_share_pct:.0f} % — the largest possible — on an excess of {s1.frozen_excess_kg:.1f} kg, "
            f"and the best arm recovers {s1.recovered_pct:.1f} % of it. A large share is not a "
            "sufficient condition for adaptation to help."),
        notes=["Both arms' recovered shares are in the CSV (`rls_recovered_pct`, `kalman_recovered_pct`); "
               "the figure draws the arm with the more negative median paired difference.",
               "The S1 share is 100 % by construction (floor 0); it is not a rounding artefact."])


# ---------------------------------------------------------------- F3 (new)
LAMBDAS = ["0.95", "0.99", "0.995", "0.999", "1.0"]
F3_SCENS = ["S2_thermal_cycle", "S4_step_fault", "S7_sparse_reference"]


def sweep_arm(scen, lam):
    """Per-seed RLS MAE at forgetting factor ``lam``, seeds 1-30, from the stages that hold it."""
    if lam == "0.99":
        return stored_by_seed(lad, scen, "rls")
    if lam == "0.95":
        esc = "p1_esc_lambda095_s2" if scen == "S2_thermal_cycle" else "p1_esc_lambda095"
        return mae_by_seed(["p1_lambda", esc], scen, "rls", "rls_l095")
    if lam == "1.0":
        esc = "p1_mem_dev_l1_esc" if scen == "S2_thermal_cycle" else "p1_esc_lambda_fill"
        return mae_by_seed(["p1_mem_dev_l1", esc], scen, "rls", "rls_l1")
    edge = {"0.995": "rls_l0995", "0.999": "rls_l0999"}[lam]
    esc = "p1_esc_lambda" if scen == "S2_thermal_cycle" else "p1_esc_lambda_fill"
    return mae_by_seed(["p1_lambda", esc], scen, "rls", edge)


def ladder30_family_p_holm(scen, est):
    """p_holm of ``static_affine -> est`` on ``scen`` in ladder30's own 14-comparison family."""
    from wimsim.experiments.stats import holm, wilcoxon_signed_rank
    tests, keys = [], []
    for sc in SCENS:
        w = wide(lad, sc, "mae_kg")
        for e in ("rls", "kalman"):
            tests.append(wilcoxon_signed_rank(list(w["static_affine"]), list(w[e])))
            keys.append((sc, e))
    return float(holm(tests)[keys.index((scen, est))].p_holm)


def f3():
    from wimsim.experiments.stats import holm, wilcoxon_signed_rank

    diffs, rows, tests = {}, [], []
    for scen in F3_SCENS:
        frozen = stored_by_seed(lad, scen, "static_affine")
        for lam in LAMBDAS:
            arm = sweep_arm(scen, lam)
            assert list(arm.index) == list(range(1, 31)), (scen, lam, list(arm.index))
            d = arm - frozen.reindex(arm.index)
            diffs[scen, lam] = d
            for stage, dd in (("10 seeds", d.loc[1:10]), ("30 seeds", d)):
                tst = wilcoxon_signed_rank(list(frozen.reindex(dd.index)), list(arm.reindex(dd.index)),
                                           label=f"{scen}|{lam}|{stage}")
                rows.append({"scenario": scen, "lambda": lam, "stage": stage, "seeds": len(dd),
                             "median_paired_diff_kg": float(np.median(dd)),
                             "signs": f"+{int((dd > 0).sum())}/-{int((dd < 0).sum())}",
                             "p": tst.p_value, "rb_rank": tst.effect_size,
                             "rb_sign": rank_biserial(dd.to_numpy(), np.zeros(len(dd)))})
                tests.append(tst)
    # Holm within each stage, over the fifteen arm-versus-frozen comparisons the figure draws.
    t = pd.DataFrame(rows)
    for stage in ("10 seeds", "30 seeds"):
        idx = t.index[t.stage == stage]
        adj = holm([tests[i] for i in idx])
        t.loc[idx, "p_holm"] = [a.p_holm for a in adj]
    excess = {sc: float(np.median(stored_by_seed(lad, sc, "static_affine")) - floor_med(lad, sc))
              for sc in F3_SCENS}
    t["frozen_excess_kg"] = t.scenario.map(excess)
    t["recovered_pct"] = -100 * t.median_paired_diff_kg / t.frozen_excess_kg

    # S4: the shorter memory against the shipped one.
    s4 = wilcoxon_signed_rank(list(sweep_arm("S4_step_fault", "0.99")), list(sweep_arm("S4_step_fault", "0.95")))
    d4 = sweep_arm("S4_step_fault", "0.95") - sweep_arm("S4_step_fault", "0.99")

    # The Kalman with R corrected: no forgetting factor, and its effective memory changes with its
    # covariance over the run, so there is no defined place for it on this axis. Table only.
    kal = []
    for scen in F3_SCENS:
        k = mae_by_seed(["p1_r_dev_floor"] + (["p1_r_dev_floor_esc"] if any(
            results("p1_r_dev_floor_esc").scenario == scen) else []), scen, "kalman")
        d = k - stored_by_seed(lad, scen, "static_affine").reindex(k.index)
        kal.append({"scenario": scen, "arm": "kalman, R corrected (kr_floor), shipped Q", "seeds": len(d),
                    "median_paired_diff_kg": float(np.median(d)),
                    "signs": f"+{int((d > 0).sum())}/-{int((d < 0).sum())}",
                    "recovered_pct": -100 * float(np.median(d)) / excess[scen]})
    kal = pd.DataFrame(kal)

    t30 = t[t.stage == "30 seeds"].set_index(["scenario", "lambda"])
    fig, axes = plt.subplots(1, 3, figsize=(15.0, 5.6))
    x = np.arange(len(LAMBDAS))
    for ax, scen in zip(axes, F3_SCENS, strict=True):
        ex = excess[scen]
        data = [diffs[scen, lam].to_numpy() for lam in LAMBDAS]
        ax.boxplot(data, positions=x, widths=0.5, whis=(5, 95), showfliers=False,
                   medianprops={"color": "black", "lw": 1.8},
                   boxprops={"color": "#1f77b4"}, whiskerprops={"color": "#1f77b4"},
                   capprops={"color": "#1f77b4"})
        for i, v in enumerate(data):
            jit = (np.arange(v.size) % 9 - 4) * 0.035
            ax.scatter(i + jit, v, s=8, color="#1f77b4", alpha=0.35, lw=0, zorder=2)
        ax.axhline(0, color="#444444", lw=1.4, label="frozen (static_affine)")
        ax.axhline(-ex, color="#8b0000", lw=1.2, ls="--", label=f"floor: all {ex:.1f} kg of excess recovered")
        for i, lam in enumerate(LAMBDAS):
            r = t30.loc[(scen, lam)]
            star = "*" if r.p_holm < 0.05 else "n.s."
            ax.text(i, 1.0, f"{r.median_paired_diff_kg:+.2f}\n{r.signs}\n{star}",
                    transform=ax.get_xaxis_transform(), ha="center", va="bottom", fontsize=7.2,
                    color="#0a6b2f" if (r.p_holm < 0.05 and r.median_paired_diff_kg < 0)
                    else ("#b00000" if r.p_holm < 0.05 else "#555555"))
        ax.set_xticks(x)
        ax.set_xticklabels([f"λ={lam}" + ("\n(shipped)" if lam == "0.99" else "") for lam in LAMBDAS],
                           fontsize=8)
        ax.set_title(f"{scen}\nrecoverable excess {ex:.1f} kg", fontsize=9.5, pad=44)
        ax.grid(axis="y", alpha=0.25)
        ax.set_axisbelow(True)
    axes[0].set_ylabel("RLS − frozen MAE, per seed (kg)   · negative = adapting helps")
    axes[0].legend(fontsize=7.6, loc="lower left")
    s2 = t30.loc["S2_thermal_cycle"]
    l30 = ladder30_family_p_holm("S2_thermal_cycle", "rls")
    axes[0].annotate(
        f"sign changes between 0.95 ({s2.loc['0.95'].median_paired_diff_kg:+.1f}) and 0.99;\n"
        f"at 0.99: p {s2.loc['0.99'].p:.3f}; p_holm {l30:.2f} in ladder30's 14-test family,\n"
        f"{s2.loc['0.99'].p_holm:.3f} in this figure's 15-cell family. At 0.995: p_holm "
        f"{s2.loc['0.995'].p_holm:.0e}",
        xy=(0.5, 0.97), xycoords="axes fraction", ha="center", va="top", fontsize=7.6,
        bbox={"boxstyle": "round", "fc": "#fffbe6", "ec": "#b8860b", "lw": 0.7})
    axes[1].annotate(f"0.95 beats 0.99 by {-np.median(d4):.1f} kg\non {int((d4 < 0).sum())} of {len(d4)} seeds",
                     xy=(0.0, float(np.median(diffs['S4_step_fault', '0.95']))), xytext=(1.3, -5),
                     fontsize=8, arrowprops={"arrowstyle": "->", "lw": 0.8})
    for ax in axes[1:]:
        ax.legend(fontsize=7.6, loc="lower right")
    fig.suptitle("F3 — RLS against the frozen arm across the forgetting factor  "
                 "[30 seeds per cell; box 25–75 %, whiskers 5–95 %, dots = seeds; "
                 "label above: median paired diff, signs, Holm over the 15 cells]", fontsize=10, y=1.02)
    fig.tight_layout()
    save(fig, "F3__forgetting_factor_sweep.png")
    t.to_csv("export/data/F3_lambda_sweep.csv", index=False)
    kal.to_csv("export/data/F3_kalman_corrected_R.csv", index=False)

    s4r = t30.loc["S4_step_fault"]
    s7r = t30.loc["S7_sparse_reference"]
    best = {sc: t30.loc[sc].median_paired_diff_kg.idxmin() for sc in F3_SCENS}
    sidecar(
        "F3__forgetting_factor_sweep.png", title="F3 — The forgetting-factor sweep",
        statistic="Per seed: RLS MAE at λ minus frozen MAE on the same seed. Plotted: the distribution of "
                  "those paired differences over 30 seeds; labelled: their median, the sign count, and "
                  "Wilcoxon signed-rank p, Holm-corrected over the fifteen cells. The difference of "
                  "medians is not used.",
        sample="30 seeds per cell, 5 λ × 3 scenarios. Frozen and λ = 0.99 from ladder30 (seeds 1–30); "
               "other λ: seeds 1–10 from p1_lambda / p1_mem_dev_l1, seeds 11–30 from the thirty-seed "
               "stages. Cells unanimous at ten seeds (S2 at 0.95; S4 and S7 at 0.995, 0.999, 1.0) were "
               "escalated for figure uniformity, not because the protocol required it. Both stages are "
               "in the CSV (`stage`).",
        data="`export/data/F3_lambda_sweep.csv` (cells, both stages); "
             "`export/data/F3_kalman_corrected_R.csv` (Kalman, table only).",
        caption=(
            "RLS against the frozen arm across the forgetting factor, with the frozen arm as the zero line "
            "and the floor drawn where the whole of the scenario's recoverable excess would be recovered "
            f"(S2 {excess['S2_thermal_cycle']:.1f}, S4 {excess['S4_step_fault']:.1f}, "
            f"S7 {excess['S7_sparse_reference']:.1f} kg). The argument is excess against misadjustment. "
            f"On S2 the sign changes between λ = 0.95 ({s2.loc['0.95'].median_paired_diff_kg:+.2f} kg, "
            f"{s2.loc['0.95'].signs}) and λ = 0.99: a short memory costs more than the whole excess. The "
            "At the shipped λ = 0.99 the difference is "
            f"{s2.loc['0.99'].median_paired_diff_kg:+.2f} kg ({s2.loc['0.99'].signs}, raw p "
            f"{s2.loc['0.99'].p:.3f}); whether that separates depends on the correction family: p_holm "
            f"{l30:.3f} in ladder30's pre-registered 14-test family (not separated), "
            f"{s2.loc['0.99'].p_holm:.3f} in this figure's 15-cell family (separated). At 0.995 it is "
            f"{s2.loc['0.995'].median_paired_diff_kg:+.2f} kg ({s2.loc['0.995'].signs}, p_holm "
            f"{s2.loc['0.995'].p_holm:.1e}) and at 0.999 {s2.loc['0.999'].median_paired_diff_kg:+.2f} kg "
            f"({s2.loc['0.999'].signs}). [PENDING: the article's inference sentence for S2 at 0.99 "
            "depends on which family it adopts; see the notes.] On S4 the ordering is "
            f"reversed: λ = 0.95 is best ({s4r.loc['0.95'].median_paired_diff_kg:+.1f} kg against frozen) and "
            f"beats λ = 0.99 by {-np.median(d4):.1f} kg on {int((d4 < 0).sum())} of {len(d4)} seeds "
            f"(p {s4.p_value:.1e}). On S7 the best cell is λ = {best['S7_sparse_reference']} "
            f"({s7r.loc[best['S7_sparse_reference']].median_paired_diff_kg:+.1f} kg)."),
        notes=["The Kalman with R corrected is NOT drawn: it has no forgetting factor, and its effective "
               "memory changes with its covariance through the run, so no position on the λ axis is "
               "defined. Its values are in `F3_kalman_corrected_R.csv`: "
               + "; ".join(f"{r.scenario.split('_')[0]} {r.median_paired_diff_kg:+.2f} kg ({r.signs}, "
                           f"{r.seeds} seeds)" for _, r in kal.iterrows()) + ".",
               "Choosing the best λ from this sweep and reporting it on the same scenarios is in-sample; the "
               "held-out check is F12(b).",
               "Holm here is over this figure's fifteen cells; the p_holm values in the escalation tables "
               "are over their own families and differ.",
               "The dashed floor line is drawn at minus the MEDIAN frozen excess. Each seed has its own "
               "excess, so individual seeds can fall below the line without recovering more than that seed's "
               "own excess.",
               "FAMILY DEPENDENCE, S2 at λ = 0.99: raw p 0.029. Holm over ladder30's 14 shipped-setting "
               "comparisons (the pre-registered family the single-setting benchmark used) gives 0.198, not "
               "separated; Holm over this figure's 15 cells, where the other fourteen p are all small, leaves "
               "it at 0.029, separated. 'At 0.99 the evidence is null' is true of the single-setting "
               "benchmark's own correction, not of the data."])
    return t


# ---------------------------------------------------------------- F5 (repo F4)
def f5():
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
                         "rb_rank": rank_biserial_ranked(y, x),
                         "median_paired_diff_kg": float(np.median(y - x)),
                         "signs": f"+{int((y - x > 0).sum())}/-{int((y - x < 0).sum())}"})
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
    ax.set_xlabel("rank-biserial on the paired differences, sign-count form "
                  "(negative = tracking better)")
    ax.set_xlim(-1.18, 1.18)
    ax.set_title("F5 — Effect size against the frozen arm AT THE SHIPPED MEMORY (RLS λ = 0.99), "
                 "ordered by excess\n"
                 "[ladder30, 30 seeds, 14 comparisons; bars are bootstrap 95 % CI, 5000 resamples;\n"
                 "filled marker = CI excludes zero. One memory length only — see F3.]", fontsize=9.5)
    ax.grid(axis="x", alpha=0.25)
    ax.set_axisbelow(True)
    h = [plt.Line2D([], [], color=COL[e], marker=MARK[e], ls="", label=e) for e in ("rls", "kalman")]
    ax.legend(handles=h, fontsize=8.5, loc="lower left")
    save(fig, "F5__effect_sizes.png")
    sig = t[(t.hi < 0) | (t.lo > 0)]
    s6k = t[(t.scenario == "S6_combined") & (t.estimator == "kalman")].iloc[0]
    sidecar(
        "F5__effect_sizes.png", title="F5 — Effect sizes at the shipped memory",
        statistic="Rank-biserial correlation of the per-seed paired differences (tracked − frozen MAE), "
                  "SIGN-COUNT form: (#positive − #negative) / #nonzero. Intervals: percentile bootstrap "
                  "over seeds, 5 000 resamples, fixed RNG. The rank-weighted (Kerby) form that the "
                  "Wilcoxon test carries is in the CSV as `rb_rank`; the median paired difference in kg "
                  "is `median_paired_diff_kg`.",
        sample="ladder30, 30 seeds, 7 scenarios × 2 tracked arms = 14 comparisons.",
        data="`export/data/F5_effect_sizes.csv`.",
        caption=(
            "Effect of tracking against the frozen arm for all fourteen comparisons AT ONE SETTING: RLS "
            "at the shipped forgetting factor λ = 0.99 and the Kalman at its shipped Q and R. Ordered by "
            "the scenario's excess over the floor, largest at the top. This figure shows where "
            "adaptation helps at one memory length, not where adaptation helps: F3 shows that on S2 the "
            "conclusion at λ = 0.99 (no separation) reverses at λ ≥ 0.995, and on S4 a shorter memory "
            f"does better still. {len(sig)} of 14 intervals exclude zero. S6/kalman sits at "
            f"{s6k.rb:+.2f} ({s6k.signs}), its interval [{s6k.lo:+.2f}, {s6k.hi:+.2f}]."),
        notes=["The x-axis label in the previous version read 'matched-pairs rank-biserial', which "
               "conventionally names the rank-weighted form; the plotted quantity has always been the "
               "sign-count form. Both are in the CSV; the article should name the one it quotes."])
    return t


# ---------------------------------------------------------------- F7 (repo F6)
def f7_bias():
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
            rows.append({"scenario": s, "estimator": e,
                         "median_signed_bias_kg": med_s[-1], "signed_lo": lo_s[-1], "signed_hi": hi_s[-1],
                         "median_abs_bias_kg": med_a[-1], "abs_lo": lo_a[-1], "abs_hi": hi_a[-1],
                         "mean_abs_bias_kg": float(np.mean(np.abs(b))),
                         "mean_signed_bias_kg": float(np.mean(b))})
        for ax, M, L, H in ((axes[0], med_s, lo_s, hi_s), (axes[1], med_a, lo_a, hi_a)):
            M = np.array(M)
            ax.bar(x + (j - 1) * wdt, M, wdt, color=COL[e], edgecolor="black", lw=0.4, label=e)
            ax.errorbar(x + (j - 1) * wdt, M,
                        yerr=[M - np.array(L), np.array(H) - M],
                        fmt="none", ecolor="black", capsize=2, lw=0.8)

    axes[0].axhline(0, color="black", lw=0.8)
    axes[0].set_ylabel("MEDIAN SIGNED BIAS (kg)\nmedian over seeds of the run's mean error", fontsize=8.5)
    axes[0].set_title("F7 — Bias by scenario and arm: two statistics, labelled\n"
                      "[ladder30, 30 seeds; per run, bias = mean signed error over the run's vehicles. "
                      "Bars are medians over seeds, bootstrap 95 % CI.]",
                      fontsize=10)
    axes[1].set_ylabel("MEDIAN ABSOLUTE BIAS (kg)\nmedian over seeds of |run's mean error|", fontsize=8.5)
    axes[1].set_yscale("symlog", linthresh=1.0)
    axes[1].set_xticks(x)
    axes[1].set_xticklabels([s.replace("_", "\n", 1) for s in SCENS], fontsize=8.5)
    # annotate S2, the one that matters
    i2 = SCENS.index("S2_thermal_cycle")
    a = {e: float(np.median(np.abs(wide(lad, "S2_thermal_cycle", "bias_kg")[e]))) for e in ESTS}
    sg = {e: float(np.median(wide(lad, "S2_thermal_cycle", "bias_kg")[e])) for e in ESTS}
    axes[0].annotate(f"S2 frozen: {sg['static_affine']:+.1f} kg (median signed)",
                     xy=(i2 - wdt, sg["static_affine"]), xytext=(i2 + 0.6, sg["static_affine"] * 2.2),
                     fontsize=8, arrowprops={"arrowstyle": "->", "lw": 0.8})
    axes[1].annotate(f"S2 median |bias|: {a['static_affine']:.2f} → {a['rls']:.2f} kg (rls),"
                     f" {a['kalman']:.2f} (kalman)\n$p_{{holm}}$ < 1e-5 for both",
                     xy=(i2 - wdt, a["static_affine"]), xytext=(i2 + 0.45, 0.35),
                     fontsize=8, ha="left", bbox={"boxstyle": "round", "fc": "white", "ec": "#999999", "lw": 0.6},
                     arrowprops={"arrowstyle": "->", "lw": 0.8})
    for ax in axes:
        ax.grid(axis="y", alpha=0.25)
    ax.set_axisbelow(True)
    axes[0].legend(fontsize=8.5, ncol=3)
    save(fig, "F7__bias_by_scenario.png")
    t = pd.DataFrame(rows)
    s2 = t[t.scenario == "S2_thermal_cycle"].set_index("estimator")
    sidecar(
        "F7__bias_by_scenario.png", title="F7 — Bias by scenario and arm",
        statistic="Per run, bias = mean signed error (estimated − static mass) over the run's vehicles. "
                  "Upper panel: MEDIAN over seeds of that signed bias. Lower panel: MEDIAN over seeds of "
                  "its absolute value. Intervals: bootstrap 95 % CI of the median, 5 000 resamples. "
                  "Means over seeds of both are in the CSV and are not plotted.",
        sample="ladder30, 30 seeds, 7 scenarios × 3 arms.",
        data="`export/data/F7_bias.csv`.",
        caption=(
            "Two statistics, labelled, because an earlier draft conflated them. On S2 the frozen arm's "
            f"median absolute bias is {s2.loc['static_affine', 'median_abs_bias_kg']:.2f} kg against "
            f"{s2.loc['rls', 'median_abs_bias_kg']:.2f} kg (rls) and {s2.loc['kalman', 'median_abs_bias_kg']:.2f} kg "
            f"(kalman); its median signed bias is {s2.loc['static_affine', 'median_signed_bias_kg']:+.2f} kg "
            f"(rls {s2.loc['rls', 'median_signed_bias_kg']:+.2f}, kalman {s2.loc['kalman', 'median_signed_bias_kg']:+.2f}). "
            "The absolute and signed medians differ because the sign of a run's bias varies across seeds: "
            "a median of |b| is not |median of b|."),
        notes=["The brief calls 23.67 / 5.74 / 5.62 the 'mean absolute bias'. They are the MEDIAN over "
               "seeds of |run bias| (the run bias itself being a mean over vehicles). The MEAN over seeds "
               f"of |run bias| is {s2.loc['static_affine', 'mean_abs_bias_kg']:.2f} / "
               f"{s2.loc['rls', 'mean_abs_bias_kg']:.2f} / {s2.loc['kalman', 'mean_abs_bias_kg']:.2f} kg. "
               "Suggested wording: 'median absolute bias'.",
               "The p_holm < 1e-5 annotation is carried from the Phase 0 bias tests (ladder30, frozen vs each "
               "tracked arm on |bias|), not recomputed here."])
    return t


# ---------------------------------------------------------------- F8 (repo F7)
def f8():
    # Plant trajectory of S2 seed 1 (sensor temperature and gain at 50 Hz). Produced during the
    # Phase 0 audit (B3) and previously read from that session's scratchpad; copied here unchanged.
    tr = pd.read_csv("export/data/F8_s2_seed1_trajectory.csv")
    RATE, N_CAL = 180.0, 60
    win_s = N_CAL / RATE * 3600.0
    w = tr[tr.t_s <= win_s]
    t_run_med = float(tr.T_sensor_c.median())
    t_win_mean = float(w.T_sensor_c.mean())
    k_run_med = float(tr.k.median())
    k_win = float(w.k.mean())
    off = (k_win - k_run_med) / k_run_med
    m_mean = float(pd.read_csv("export/data/vehicle_mass_by_scenario.csv",
                               index_col="scenario").loc["S2_thermal_cycle", "mean_kg"])

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
            f"→ {off*m_mean:+.1f} kg on the mean vehicle ({m_mean:,.0f} kg)\n"
            f"→ {off*20000:+.1f} kg on a 20 t vehicle\n"
            f"carried as a BIAS for the whole run,\nbecause the fit is then frozen",
            transform=ax.transAxes, ha="right", va="top", fontsize=8.5,
            bbox={"boxstyle": "round", "fc": "#fffbe6", "ec": "#b8860b", "lw": 0.8})
    ax.set_xlabel("sensor-body temperature (°C)")
    ax.set_ylabel("probability density (1/°C)")
    ax.set_title("F8 — The fitting window against deployment conditions\n"
                 "[S2_thermal_cycle, seed 1; 60 calibration passes at 180 veh/h; plant grid 50 Hz]",
                 fontsize=10)
    ax.legend(fontsize=8.5, loc="upper left")
    ax.grid(alpha=0.25)
    ax.set_axisbelow(True)
    save(fig, "F8__fitting_window.png")
    sidecar(
        "F8__fitting_window.png", title="F8 — Fitting window against deployment conditions",
        statistic="Descriptive, one run: histograms of sensor-body temperature; the run median and the "
                  "window mean. No paired comparison is plotted.",
        sample="S2_thermal_cycle, seed 1; plant grid at 50 Hz over 72 h; the window is the 60 "
               "calibration passes at 180 veh/h.",
        data="`export/data/F8_s2_seed1_trajectory.csv` (input trajectory).",
        caption=(
            f"The frozen arm is fitted on a {win_s / 60:.1f}-minute window whose mean sensor temperature "
            f"is {t_win_mean:.2f} °C, {t_run_med - t_win_mean:.2f} °C below the deployment median of "
            f"{t_run_med:.2f} °C. Temperature is not a model input: the model maps feature to mass, and "
            "temperature acts on the gain as a hidden variable. What the window misrepresents is therefore "
            "the conditional P(mass | feature), which depends on that hidden variable — an unrepresentative "
            f"fitting sample, not a covariate shift. The window's gain is {100 * off:+.3f} % from the run "
            f"median, {off * m_mean:+.1f} kg on the mean S2 vehicle ({m_mean:,.0f} kg), carried as a bias because the fit is frozen."),
        notes=["The caption must not say 'covariate shift': the covariate (the feature) is not what moves.",
               "The previous version used a mean vehicle of 6 325 kg with no stored source; this one uses the S2 fleet mean from `export/data/vehicle_mass_by_scenario.csv`."])
    return {"window_min": win_s / 60, "T_window_mean_c": t_win_mean,
            "T_run_median_c": t_run_med, "delta_c": t_run_med - t_win_mean,
            "gain_offset_pct": 100 * off}


# ---------------------------------------------------------------- F10 (repo F9)
def f10():
    rows = []
    for s in SCENS:
        wa, wb = wide(lad, s, "mae_kg"), wide(cin, s, "mae_kg")
        if wb is None or wb.empty:
            continue
        for e in ("rls", "kalman"):
            if e not in wb.columns:
                continue
            ya, xa = wa[e].to_numpy(), wa["static_affine"].to_numpy()
            yb, xb = wb[e].to_numpy(), wb["static_affine"].to_numpy()
            rows.append({"scenario": s, "estimator": e,
                         "contact": rank_biserial(ya, xa), "influence": rank_biserial(yb, xb),
                         "contact_rb_rank": rank_biserial_ranked(ya, xa),
                         "influence_rb_rank": rank_biserial_ranked(yb, xb),
                         "contact_median_paired_diff_kg": float(np.median(ya - xa)),
                         "influence_median_paired_diff_kg": float(np.median(yb - xb))})
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
    ax.set_xlabel("effect on the contact-force instrument  (ladder30)\n"
                  "rank-biserial of the per-seed paired differences, sign-count form")
    ax.set_ylabel("effect on the influence-line instrument  (cintron_ladder30)")
    ax.set_xlim(-1.15, 1.15)
    ax.set_ylim(-1.15, 1.15)
    ax.set_aspect("equal")
    ax.set_title("F10 — Does the ladder result transfer between instruments?\n"
                 "[30 seeds each; negative = tracking beats frozen. Points on the identity line transfer.]",
                 fontsize=9.5)
    h = [plt.Line2D([], [], color=COL[e], marker=MARK[e], ls="", label=e) for e in ("rls", "kalman")]
    ax.legend(handles=h, fontsize=8.5, loc="upper left")
    ax.grid(alpha=0.25)
    ax.set_axisbelow(True)
    save(fig, "F10__instrument_transfer.png")
    same = int((np.sign(t.contact) == np.sign(t.influence)).sum())
    sidecar(
        "F10__instrument_transfer.png", title="F10 — Transfer between front ends",
        statistic="Both axes: rank-biserial of the per-seed paired differences (tracked − frozen MAE), "
                  "sign-count form. Computed on paired differences only. The rank-weighted form and the "
                  "median paired difference in kg on each instrument are in the CSV.",
        sample="ladder30 (contact-force front end) and cintron_ladder30 (influence-line front end), "
               f"30 seeds each, {len(t)} comparisons.",
        data="`export/data/F10_transfer.csv`.",
        caption=(
            "Each point is one tracked-versus-frozen comparison, its effect on the contact-force front end "
            "against the same comparison on the influence-line front end. Points on the identity line "
            f"transferred; distance from it is the transfer gap. {same} of {len(t)} keep their sign."))
    return t


# ---------------------------------------------------------------- F12 (repo F11)
def tuned_transfer():
    """The memory chosen on a development scenario, applied to its held-out counterpart.

    Paired differences in kg, per seed, against frozen and against the shipped lambda = 0.99.
    Development stages: p1_lambda (seeds 1-10) + the thirty-seed escalation. Held out: H2 at ten
    seeds (unanimous, not escalated), H1 at thirty (split at ten, escalated).
    """
    cases = [
        ("S4_step_fault", "H2_gain_jolt", "rls_l095", "0.95",
         mae_by_seed(["p1_lambda"], "S4_step_fault", "rls", "rls_l095")
         .combine_first(mae_by_seed(["p1_esc_lambda095"], "S4_step_fault", "rls")),
         mae_by_seed(["p1_lambda_held_h2"], "H2_gain_jolt", "rls")),
        ("S2_thermal_cycle", "H1_warm_front", "rls_l0999", "0.999",
         mae_by_seed(["p1_lambda", "p1_esc_lambda"], "S2_thermal_cycle", "rls", "rls_l0999"),
         mae_by_seed(["p1_lambda_held_h1", "p1_lambda_held_h1_esc"], "H1_warm_front", "rls")),
    ]
    rows = []
    for dev_s, held_s, _edge, lam, dev, held in cases:
        for side, scen, arm, src in (("development", dev_s, dev, lad), ("held out", held_s, held, hel)):
            for ref in ("static_affine", "rls"):
                base = stored_by_seed(src, scen, ref)
                d = (arm - base.reindex(arm.index)).dropna()
                rows.append({"chosen_on": dev_s, "applied_to": scen, "side": side, "lambda": lam,
                             "against": "frozen" if ref == "static_affine" else "rls λ=0.99",
                             "seeds": len(d), "median_paired_diff_kg": float(np.median(d)),
                             "signs": f"+{int((d > 0).sum())}/-{int((d < 0).sum())}",
                             "per_seed": d.to_numpy()})
    return pd.DataFrame(rows)


def f12():
    rows = []
    for h_s, d_s in HS_MAP.items():
        wd, wh = wide(lad, d_s, "mae_kg"), wide(hel, h_s, "mae_kg")
        for e in ("rls", "kalman"):
            rows.append({"held_out": h_s, "development": d_s, "estimator": e,
                         "dev": rank_biserial(wd[e].to_numpy(), wd["static_affine"].to_numpy()),
                         "held": rank_biserial(wh[e].to_numpy(), wh["static_affine"].to_numpy())})
    t = pd.DataFrame(rows)
    t["reproduces"] = np.sign(t.dev) == np.sign(t.held)
    fig, (ax, axt) = plt.subplots(1, 2, figsize=(13.6, 7.2),
                                  gridspec_kw={"width_ratios": [1.15, 1.0]})
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
    ax.set_xlabel("effect on the development scenario (ladder30)\n"
                  "rank-biserial of the per-seed paired differences, sign-count form")
    ax.set_ylabel("effect on its held-out counterpart (heldout30)")
    ax.set_xlim(-1.15, 1.15)
    ax.set_ylim(-1.15, 1.15)
    ax.set_aspect("equal")
    ax.set_title("(a) Shipped settings, development against held out\n"
                 "[30 seeds each; red ring = the effect changed sign. H1 drawn 5.6×, H3 2.4× harder.]",
                 fontsize=9.5)
    h = [plt.Line2D([], [], color=COL[e], marker=MARK[e], ls="", label=e) for e in ("rls", "kalman")]
    ax.legend(handles=h, fontsize=8.5, loc="lower right")
    ax.grid(alpha=0.25)
    ax.set_axisbelow(True)

    # (b) tuned memory: kg, so it does not share (a)'s axes
    tt = tuned_transfer()
    labels = []
    for i, r in tt.iterrows():
        y = len(tt) - 1 - i
        c = "#1f77b4" if r.against == "frozen" else "#6a3d9a"
        jit = (np.arange(len(r.per_seed)) % 7 - 3) * 0.05
        axt.scatter(r.per_seed, y + jit, s=9, color=c, alpha=0.45, lw=0)
        axt.plot([r.median_paired_diff_kg] * 2, [y - 0.32, y + 0.32], color=c, lw=2.6)
        axt.text(1.02, y, f"{r.median_paired_diff_kg:+.1f} kg  {r.signs}", transform=axt.get_yaxis_transform(),
                 fontsize=7.6, va="center", color=c)
        labels.append(f"{r.applied_to.split('_')[0]} ({r.side}, n={r.seeds})\n"
                      f"λ={r['lambda']} − {r.against}")
    axt.axvline(0, color="#999999", lw=0.8, ls=":")
    axt.set_yticks(range(len(tt)))
    axt.set_yticklabels(labels[::-1], fontsize=7.4)
    axt.set_xscale("symlog", linthresh=10)
    axt.set_xlabel("paired difference, tuned λ − reference (kg, symlog)  · negative = tuned better")
    axt.set_title("(b) Memory tuned on a development scenario, applied to its held-out pair\n"
                  "[per-seed paired differences; bar = median]", fontsize=9.5)
    axt.grid(axis="x", alpha=0.25)
    fig.suptitle("F12 — Does the development result reproduce out of distribution?", fontsize=10.5)
    fig.tight_layout()
    save(fig, "F12__development_vs_heldout.png")
    nflip = int((~t.reproduces).sum())
    flips = ", ".join(f"{r.held_out.split('_')[0]}/{r.estimator}" for _, r in t[~t.reproduces].iterrows())
    h2 = tt[(tt.applied_to == "H2_gain_jolt")].set_index("against")
    h1 = tt[(tt.applied_to == "H1_warm_front")].set_index("against")
    sidecar(
        "F12__development_vs_heldout.png", title="F12 — Development against held out",
        statistic="(a) rank-biserial of the per-seed paired differences (tracked − frozen MAE), sign-count "
                  "form, on each side. (b) per-seed paired differences in kg and their median. No "
                  "difference of medians anywhere.",
        sample="(a) ladder30 and heldout30, 30 seeds each, 8 matched pairs. (b) development side 30 seeds; "
               f"H2 {int(h2.seeds.iloc[0])} seeds (unanimous at ten, not escalated); H1 {int(h1.seeds.iloc[0])} seeds.",
        data="`export/data/F12_heldout.csv` (a); `export/data/F12_tuned_transfer.csv` (b).",
        caption=(
            f"(a) {nflip} of {len(t)} matched pairs change sign ({flips}), ringed in red. Read with the "
            "difficulty confound: H1 was drawn 5.6× and H3 2.4× further above their own floors than their "
            "development counterparts, while H2 and H4 were drawn at comparable difficulty, so "
            "non-reproduction is not separable from a harder draw. (b) A memory chosen on a development "
            "scenario, applied unchanged to its held-out pair. λ = 0.95, chosen on S4, beats frozen on H2 by "
            f"{-h2.loc['frozen', 'median_paired_diff_kg']:.1f} kg ({h2.loc['frozen', 'signs']}) and the shipped "
            f"λ = 0.99 by {-h2.loc['rls λ=0.99', 'median_paired_diff_kg']:.1f} kg ({h2.loc['rls λ=0.99', 'signs']}). "
            f"λ = 0.999, chosen on S2, does not transfer to H1: {h1.loc['frozen', 'median_paired_diff_kg']:+.1f} kg "
            f"against frozen ({h1.loc['frozen', 'signs']}), {h1.loc['rls λ=0.99', 'median_paired_diff_kg']:+.1f} kg "
            f"against λ = 0.99 ({h1.loc['rls λ=0.99', 'signs']}, p_holm 0.32 at thirty seeds)."),
        notes=["Panel (b) is separate because its points are kg, not rank-biserial; on (a)'s axes the H2 "
               "points would sit at (−1, −1) on top of the shipped-RLS point.",
               "The 5.6× and 2.4× difficulty ratios are carried from the Phase 0 audit.",
               "H1 p_holm 0.32 is from `export/data/p1/p1_escalations.csv` (family '1.3 held-out tuned lambda')."])
    tt.drop(columns="per_seed").to_csv("export/data/F12_tuned_transfer.csv", index=False)
    return t


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
    sidecar(
        "F13__estimator_cost.png", title="F13 — Cost and state size",
        statistic="Mean time per update over the measured updates, and persisted state in bytes. No "
                  "paired comparison.",
        sample=f"{n_up:,} updates per estimator on {host}; not a board measurement.",
        data="`export/data/F13_cost.csv`.",
        caption="Unchanged from the previous version. The ratio between arms is what the figure supports, "
                "not the absolute numbers.")
    return p.reset_index()


# ---------------------------------------------------------------- F14
def f14():
    q = pd.read_csv("export/data/kalman_q_ladder.csv")
    ABL = 29.3
    fig, ax = plt.subplots(figsize=(8.6, 5.2))
    ax.plot(q.q, q.dmae, marker="o", color="#d62728", lw=1.8, markersize=8,
            markeredgecolor="black", label="H1 penalty: kalman − static_affine (median, 10 seeds)")
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
    ax.set_title("F14 — A process-noise sweep that does not explain the H1 penalty\n"
                 "[H1_warm_front, 10 seeds; all five points unanimous across seeds, $p_{holm}$ = 0.0098.\n"
                 "The dependence runs the wrong way and never approaches the ablation's value.]",
                 fontsize=9.5)
    ax.legend(fontsize=8.5, loc="lower left")
    ax.grid(alpha=0.25)
    ax.set_axisbelow(True)
    save(fig, "F14__h1_process_noise.png")

    # Shipped Kalman against the corrected-R filter with Q rescaled to the shipped Q/R ratio, on every
    # scenario: thirty-seed stage where it was escalated, ten-seed stage where ten were unanimous.
    esc = pd.read_csv("export/data/p1/p1_escalations.csv")
    esc = esc[esc.comparison.str.contains("kalman shipped R -> kalman Q-rescaled") & (esc.seeds == 30)]
    kq = pd.read_csv("export/data/p1/p1_kq_dev.csv")
    kq = kq[kq.comparison.str.contains("export:ladder30:kalman -> p1_kq_dev:kalman")]
    rows = [(c.split(" / ")[0], r.median_paired_diff, r.signs, 30, r.p_holm)
            for c, r in zip(esc.comparison, esc.itertuples(), strict=True)]
    have = {r[0] for r in rows}
    rows += [(c.split(" / ")[0], r.median_paired_diff, r.signs, 10, r.p_holm)
             for c, r in zip(kq.comparison, kq.itertuples(), strict=True) if c.split(" / ")[0] not in have]
    qr = pd.DataFrame(rows, columns=["scenario", "median_paired_diff_kg", "signs", "seeds", "p_holm"])
    qr.to_csv("export/data/F14_q_rescaled_vs_shipped.csv", index=False)
    worst = qr.loc[qr.median_paired_diff_kg.abs().idxmax()]
    h1 = qr.set_index("scenario").loc["H1_warm_front"]
    top3 = qr.reindex(qr.median_paired_diff_kg.abs().sort_values(ascending=False).index).head(3)
    sidecar(
        "F14__h1_process_noise.png", title="F14 — H1 process-noise sweep",
        statistic="y: median over seeds of the per-seed paired difference, Kalman − frozen MAE, on H1, "
                  "one point per Q₁₁. The sweep's p_holm is over its five Q values.",
        sample="H1_warm_front, 10 seeds per Q value; the shipped-vs-rescaled check: 30 seeds where "
               "escalated, 10 where ten were unanimous (S6).",
        data="`export/data/kalman_q_ladder.csv` (sweep); `export/data/F14_q_rescaled_vs_shipped.csv` (check).",
        caption=(
            "The H1 Kalman penalty against the gain's process noise over four decades. Stiffening Q makes "
            "the penalty worse, loosening it makes it smaller, and across the whole range it never "
            "approaches the ablation's +29.3 kg: the sweep does not explain the result. An earlier draft "
            "allowed that the penalty might be an artefact of a misspecified observation noise R; that "
            "explanation is withdrawn. With R corrected and Q rescaled to keep the shipped Q/R ratio, the "
            "filter differs from the shipped one by at most "
            f"{abs(worst.median_paired_diff_kg):.1f} kg on any scenario ("
            + ", ".join(f"{r.scenario.split('_')[0]} {r.median_paired_diff_kg:+.1f}" for _, r in top3.iterrows())
            + f"), all {int((qr.median_paired_diff_kg < 0).sum())} of {len(qr)} in the rescaled filter's favour, "
            f"and on H1 by {h1.median_paired_diff_kg:+.1f} kg ({h1.signs}, p_holm {h1.p_holm:.2f}). The "
            "penalty therefore depends on neither R nor the adaptation rate, and remains unexplained. The "
            "Q/R equivalence is approximate over a finite run from a finite initial covariance, not exact."),
        notes=["The plot is unchanged; only the caption is.",
               "'Within 1.2 kg on every scenario' was a ten-seed, development-only figure and is superseded."])
    return q


if __name__ == "__main__":
    print("generating figures")
    t2 = f2()
    f2_sidecar(t2)
    t3 = f3()
    t5 = f5()
    t7 = f7_bias()
    t8 = f8()
    t10 = f10()
    t12 = f12()
    t13 = f13()
    t14 = f14()
    t2.to_csv("export/data/F2_decomposition.csv", index=False)
    t5.to_csv("export/data/F5_effect_sizes.csv", index=False)
    t7.to_csv("export/data/F7_bias.csv", index=False)
    t10.to_csv("export/data/F10_transfer.csv", index=False)
    t12.to_csv("export/data/F12_heldout.csv", index=False)
    t13.to_csv("export/data/F13_cost.csv", index=False)
    with pd.option_context("display.width", 220, "display.max_columns", 30):
        print("\nF8 window:", {k: round(v, 3) for k, v in t8.items()})
        print("\nF2:\n", t2.to_string(index=False))
        print("\nF3 (30 seeds):\n", t3[t3.stage == "30 seeds"].round(4).to_string(index=False))
        print("\nF5:\n", t5.round(3).to_string(index=False))
        print("\nF12:\n", t12.to_string(index=False))
