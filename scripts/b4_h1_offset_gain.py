# ruff: noqa
"""B4: split of the H1 penalty into the arm's offset and gain, against frozen, per matched vehicle."""
import glob

import pandas as pd

D = "data/results/b4_h1"
ev = pd.concat(pd.read_parquet(f) for f in glob.glob(f"{D}/*__events_seed*.parquet"))
ev["x"] = ev.mass_kg * ev.k_hat + ev.q_hat
st = ev[ev.arm == "static"].set_index(["seed", "ts_peak_us"])
res = {}
for arm in ["rls", "kalman_shipped", "kalman_corrected"]:
    a = ev[ev.arm == arm].set_index(["seed", "ts_peak_us"])
    s = st.reindex(a.index)
    print(arm, "feature identical to frozen's: max rel diff", float(((a.x - s.x).abs() / s.x.abs()).max()))
    x, m = s.x, a.true_mass_kg
    e_s = s.error_kg.abs()
    def pen(mhat):
        return ((mhat - m).abs() - e_s).groupby("seed").mean().median()
    res[arm] = {
        "penalty (arm)": pen(a.mass_kg),
        "arm gain, frozen offset": pen((x - s.q_hat) / a.k_hat),
        "frozen gain, arm offset": pen((x - a.q_hat) / s.k_hat),
        "median |offset diff| kg": float(((a.q_hat - s.q_hat) / a.k_hat).abs().groupby("seed").median().median()),
        "median signed offset diff kg": float(((s.q_hat - a.q_hat) / a.k_hat).groupby("seed").median().median()),
        "median k_hat/k_frozen": float((a.k_hat / s.k_hat).median()),
        "corr(posterior q,k) proxy: corr(q_hat,k_hat)": float(a[["q_hat", "k_hat"]].corr().iloc[0, 1]),
    }
    # does the offset move with the gain (trade-off) or with time?
    off_kg = (s.q_hat - a.q_hat) / a.k_hat
    print("   corr(offset diff, k_hat/k_frozen):", round(float(off_kg.corr(a.k_hat / s.k_hat)), 3))
print(pd.DataFrame(res).round(3).to_string())
