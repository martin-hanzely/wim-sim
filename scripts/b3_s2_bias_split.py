# ruff: noqa
"""B3: reconstruct the frozen S2 signed bias per seed from stored truth (revision_p1/posterior/*truth*),
and split it into the thermal window term and the 60-pass fit-sampling term."""
import glob
import re

import numpy as np
import pandas as pd

d = pd.read_parquet("data/results/ladder30/results.parquet")
f = d[(d.scenario == "S2_thermal_cycle") & (d.estimator == "static_affine")].set_index("seed")
rows = []
for p in sorted(glob.glob("data/results/revision_p1/posterior/S2__*__truth_seed*.parquet")):
    lab = re.search(r"S2__(\w+?)__\w+?__coupling_(on|off)__seed(\d+)__", p)
    t = pd.read_parquet(p).sort_values("t_peak_s").reset_index(drop=True)
    seed = int(lab.group(3))
    x = t.k_at_peak * t.applied_mass_kg          # feature, offset removed, no sensor noise
    cal, dep = t.iloc[:60], t.iloc[60:]
    A = np.column_stack([x[:60], np.ones(60)])
    g, b = np.linalg.lstsq(A, cal.true_mass_kg, rcond=None)[0]
    est = g * x[60:] + b
    bias_fit = float((est - dep.true_mass_kg).mean())
    # thermal-only: exact frozen model at the window's mean gain, no dynamic load in the fit
    kref = cal.k_at_peak.mean()
    bias_th = float((dep.applied_mass_kg * (dep.k_at_peak / kref - 1)).mean())
    # fit noise only: same fit with the gain held constant (thermal removed)
    xk = t.k_at_peak.mean() * t.applied_mass_kg
    g2, b2 = np.linalg.lstsq(np.column_stack([xk[:60], np.ones(60)]), cal.true_mass_kg, rcond=None)[0]
    bias_noise = float((g2 * xk[60:] + b2 - dep.true_mass_kg).mean())
    rows.append(dict(src=lab.group(1) + "_" + lab.group(2), seed=seed, stored=f.bias_kg.get(seed),
                     reconstructed=bias_fit, thermal_only=bias_th, fit_noise_only=bias_noise,
                     n=len(t)))
r = pd.DataFrame(rows).drop_duplicates(["src", "seed"]).sort_values(["src", "seed"])
print(r.round(2).to_string(index=False))
for s, g in r.groupby("src"):
    print(s, "corr(stored, reconstructed) =", round(g.stored.corr(g.reconstructed), 3),
          " median abs diff", round((g.stored - g.reconstructed).abs().median(), 2))
