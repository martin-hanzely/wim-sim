# ruff: noqa
"""B4: H1 per-event diagnostics summary, from data/results/b4_h1 (scripts/h1_diagnostics.py).

Note: the event field `feature` written by h1_diagnostics.py is the single largest peak, NOT the
feature the estimator inverts (axle_peak_sum under whole_signal). Distribution statistics below do
not use it; scripts/b4_h1_offset_gain.py recovers the inverted feature as mass*k_hat + q_hat.
"""
import glob

import numpy as np
import pandas as pd
from scipy import stats

D = "data/results/b4_h1"
ev = pd.concat(pd.read_parquet(f) for f in glob.glob(f"{D}/*__events_seed*.parquet"))
up = pd.concat(pd.read_parquet(f) for f in glob.glob(f"{D}/*__updates_seed*.parquet"))
ev["abs"] = ev.error_kg.abs()
ev["rel"] = ev.error_kg / ev.true_mass_kg
ev["kratio"] = ev.k_hat / ev.k_at_peak
ARMS = ["static", "rls", "kalman_shipped", "kalman_corrected"]
pd.set_option("display.width", 250)
pd.set_option("display.max_columns", 40)

# 1. distribution per arm (per seed, then median over seeds)
def dist(g):
    a = g["abs"].to_numpy()
    top = np.sort(a)[::-1][: max(1, len(a) // 100)]
    return pd.Series({
        "mae": a.mean(), "p50": np.percentile(a, 50), "p90": np.percentile(a, 90),
        "p99": np.percentile(a, 99), "max": a.max(),
        "kurt_err": stats.kurtosis(g.error_kg), "top1pct_share": top.sum() / a.sum(),
        "mae_rel_pct": 100 * g.rel.abs().mean(), "p99_rel_pct": 100 * np.percentile(g.rel.abs(), 99),
        "kurt_rel": stats.kurtosis(g.rel), "bias": g.error_kg.mean(),
        "k_ratio_min": g.kratio.min(), "k_ratio_p01": np.percentile(g.kratio, 1),
        "k_ratio_med": g.kratio.median(), "k_ratio_max": g.kratio.max(),
        "k_hat_min": g.k_hat.min(), "k_sign_changes": int((np.diff(np.sign(g.k_hat)) != 0).sum()),
        "n": len(a),
    })
per = ev.groupby(["arm", "seed"]).apply(dist)
print("== per-arm, median over 10 seeds\n", per.groupby("arm").median().loc[ARMS].T.round(4))

# 2. paired per-event: identical vehicles across arms (same seed, same truth pass)
w = ev.pivot_table(index=["seed", "ts_peak_us"], columns="arm", values="abs")
k = ev.pivot_table(index=["seed", "ts_peak_us"], columns="arm", values="kratio")
m = ev.groupby(["seed", "ts_peak_us"]).true_mass_kg.first()
print("\nmatched-vehicle sets equal across arms:", w.notna().all(axis=1).mean())
w = w.dropna()
for arm in ["rls", "kalman_shipped", "kalman_corrected"]:
    d = w[arm] - w["static"]
    pen = d.groupby("seed").mean()
    # quantile ratio arm/static: flat => uniform widening, rising => tail
    qs = [0.5, 0.9, 0.99, 0.999]
    qr = {q: (w[arm].groupby("seed").quantile(q) / w["static"].groupby("seed").quantile(q)).median() for q in qs}
    # contribution of the top 1% per-event penalties to the penalty
    def top_share(g):
        g = g.sort_values(ascending=False)
        n = max(1, len(g) // 100)
        return g.iloc[:n].sum() / g.sum()
    ts = d.groupby("seed").apply(top_share)
    # penalty with each arm's worst 1% |error| events removed (both arms, same vehicles removed)
    def trimmed(seed):
        x = w.loc[seed]
        cut = x[arm].quantile(0.99)
        keep = x[arm] <= cut
        return (x[arm][keep] - x["static"][keep]).mean()
    tr = pd.Series({s: trimmed(s) for s in w.index.get_level_values(0).unique()})
    # penalty restricted to events where k_hat/k_true is within 10% of 1
    kk = k[arm].reindex(w.index)
    near = (kk - 1).abs() <= 0.10
    pn = (d[near]).groupby("seed").mean()
    print(f"\n== {arm} vs static: per-seed mean penalty median {pen.median():+.1f} kg "
          f"(min {pen.min():+.1f}, max {pen.max():+.1f}); signs {(pen>0).sum()}/{len(pen)}")
    print("   quantile ratio arm/static (median over seeds):", {q: round(v, 3) for q, v in qr.items()})
    print(f"   share of penalty from top 1% of per-event penalties: median {ts.median():.3f}")
    print(f"   penalty with arm's worst 1% events removed: median {tr.median():+.1f} kg")
    print(f"   fraction of events with |k_hat/k - 1| <= 0.10: {near.mean():.3f}; penalty on those: median {pn.median():+.1f} kg")
    # by mass decile: is the penalty proportional to mass (gain error) or flat?
    dec = pd.qcut(m.reindex(w.index), 5, labels=False)
    print("   mean penalty by mass quintile (kg):", d.groupby(dec).mean().round(1).to_dict(),
          " rel %:", (100 * d / m.reindex(w.index)).groupby(dec).mean().round(2).to_dict())

# 3. k_hat trajectory: kratio over time, per arm
print("\n== k_hat/k_true quantiles across all events")
print(ev.groupby("arm").kratio.describe(percentiles=[.001, .01, .5, .99, .999]).loc[ARMS].round(4))
print("\n== true k range on H1:", ev.k_at_peak.min(), ev.k_at_peak.max())

# 4. covariance around label gaps (Kalman arms)
for arm in ["kalman_shipped", "kalman_corrected", "rls"]:
    u = up[up.arm == arm].copy()
    big = u.gap_s >= 1800
    print(f"\n== {arm}: updates {len(u)}, gaps>=1800s {big.sum()}, max gap {u.gap_s.max():.0f}s, "
          f"gaps>=3600s {(u.gap_s>=3600).sum()}")
    if arm.startswith("kalman"):
        print("   trace_prior median: gap>=1800", u.trace_prior[big].median(), " other", u.trace_prior[~big].median())
        print("   p_kk prior median: gap>=1800", u.p_kk_prior[big].median(), " other", u.p_kk_prior[~big].median())
    e = ev[ev.arm == arm].merge(ev[ev.arm == "static"][["seed", "ts_peak_us", "abs"]],
                                on=["seed", "ts_peak_us"], suffixes=("", "_st"))
    e["pen"] = e["abs"] - e["abs_st"]
    bins = pd.cut(e.since_label_s, [0, 300, 900, 1800, 3600, 1e9])
    print("   mean per-event penalty by time since last label:\n",
          e.groupby(bins, observed=True).pen.agg(["mean", "count"]).round(2).to_string())
