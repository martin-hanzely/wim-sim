"""Items 1.5 and 1.7, from the instrumented S2 runs in data/results/revision_p1/posterior.

1.5 -- per configuration (arm x offset coupling on/off), across seeds:
  * the posterior correlation between the two parameters, median over the run's updates. RLS
    reports [gain, bias] in the prediction direction (mass on feature); Kalman [q, k] on the sensor
    side (feature on mass). Both regressors are far from centred, so the hypothesis is a strong
    negative correlation in both;
  * corr(k_hat, k_true) over the run -- the Sec. V-C anti-correlation, like with like (B3f
    correlated k_hat against 1/k_true, which flips the sign);
  * rms distance of k_hat's relative deviation from k_true's, against a constant's;
  * the hypothesis's own prediction for the Kalman, -E[m] / sqrt(E[m^2]) over reference masses.

1.7 -- the thermal contribution to the frozen arm's error on S2, derived rather than asserted.
  The zero line is removed upstream by the preprocessor's tracker, so temperature reaches the
  frozen model through the gain alone. A frozen model exact at reference gain k_ref errs on a
  pass by t = m_applied * (k / k_ref - 1); the dynamic error is b = m_applied - m_static. The
  thermal contribution is what t adds on top of b:
      dMAE = mean|b + t| - mean|b|        dMSE = mean((b + t)^2) - mean(b^2)
  with k_ref the deployment-mean gain (thermal motion alone) and, separately, the mean gain over
  the 60 commissioning passes (thermal motion plus the initialisation offset of Sec. V-C).

Writes export/data/p1/p1_posterior.csv and export/data/p1/p1_thermal_s2.csv.
"""

from __future__ import annotations

import glob
import re
from pathlib import Path

import numpy as np
import pandas as pd

SRC = Path("data/results/revision_p1/posterior")
LABEL = re.compile(r"S2__(\w+?)__(\w+?)__coupling_(on|off)__seed(\d+)")


def posterior() -> pd.DataFrame:
    rows = []
    for f in sorted(SRC.glob("S2__*__seed*.parquet")):
        if "__truth_" in f.name:
            continue
        est, edge, coup, seed = LABEL.match(f.stem).groups()
        r = pd.read_parquet(f)
        m = r.reference_mass_kg.to_numpy()
        rows.append({
            "arm": f"{est}@{edge}", "coupling": coup, "seed": int(seed), "n_updates": len(r),
            "posterior_corr": float(r.posterior_corr.median()),
            "predicted_corr_kalman": float(-m.mean() / np.sqrt((m**2).mean())),
            "corr_khat_ktrue": float(r.k_hat.corr(r.k_at_peak)),
            # B3f's second claim, like with like: relative deviations about each series' own mean;
            # a constant's distance is just the target's rms.
            "rms_dev_estimate_vs_true": float(np.sqrt(np.mean(
                (r.k_hat / r.k_hat.mean() - r.k_at_peak / r.k_at_peak.mean()) ** 2))),
            "rms_dev_constant_vs_true": float(np.sqrt(np.mean(
                (r.k_at_peak / r.k_at_peak.mean() - 1.0) ** 2))),
            "mae_kg": float(r.mae_kg.iloc[0]),
        })
    return pd.DataFrame(rows)


def thermal() -> pd.DataFrame:
    rows = []
    for f in sorted(glob.glob(str(SRC / "S2__rls__default__coupling_on__seed*__truth_seed*.parquet"))):
        t = pd.read_parquet(f).sort_values("t_peak_s")
        b = (t.applied_mass_kg - t.true_mass_kg).to_numpy()
        for ref_name, k_ref in (("deployment_mean", t.k_at_peak.mean()),
                                ("commissioning_60", t.k_at_peak.iloc[:60].mean())):
            th = t.applied_mass_kg.to_numpy() * (t.k_at_peak.to_numpy() / k_ref - 1.0)
            rows.append({
                "seed": int(t.seed.iloc[0]), "k_ref": ref_name,
                "floor_mae_kg": float(np.abs(b).mean()),
                "thermal_rms_kg": float(np.sqrt((th**2).mean())),
                "thermal_mean_kg": float(th.mean()),
                "d_mae_kg": float(np.abs(b + th).mean() - np.abs(b).mean()),
                "d_mse_kg2": float(((b + th) ** 2).mean() - (b**2).mean()),
                "quadrature_claim_kg": float(np.hypot(np.abs(b).mean(),
                                                      np.sqrt((th**2).mean())) - np.abs(b).mean()),
            })
    return pd.DataFrame(rows)


def main() -> None:
    out = Path("export/data/p1")
    p = posterior()
    p.to_csv(out / "p1_posterior.csv", index=False)
    summary = p.groupby(["arm", "coupling"]).agg(
        seeds=("seed", "nunique"),
        posterior_corr=("posterior_corr", "median"),
        predicted_corr_kalman=("predicted_corr_kalman", "median"),
        corr_khat_ktrue=("corr_khat_ktrue", "median"),
        n_negative=("corr_khat_ktrue", lambda s: int((s < 0).sum())),
        rms_estimate=("rms_dev_estimate_vs_true", "median"),
        rms_constant=("rms_dev_constant_vs_true", "median"),
        mae_kg=("mae_kg", "median"),
    )
    with pd.option_context("display.width", 200):
        print(summary.round(3).to_string())
        th = thermal()
        th.to_csv(out / "p1_thermal_s2.csv", index=False)
        print(th.groupby("k_ref").median(numeric_only=True).drop(columns="seed").round(3).to_string())


if __name__ == "__main__":
    main()
