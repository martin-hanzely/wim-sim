"""Revision item 1.6(a) -- the floor from a literature DLC prior, without simulator ground truth.

If the dynamic wheel force has standard deviation DLC x static load and is roughly Gaussian, a
vehicle's dynamic error is |b| ~ DLC * m * |Z|, so the floor is E|b| = DLC * sqrt(2/pi) * mean(m).
mean(m) is the station's own fleet mean, which a station knows from its reference masses.

DLC from the literature: "0.05 to 0.3 depending on vehicle suspension, speed, and road roughness"
(Misaghi, Tirado, Nazarian & Carrasco 2021, Transportation Engineering 3:100045,
doi:10.1016/j.treng.2021.100045 -- sentence read via search summaries, not first-hand; to verify).
Evaluated at both ends and at 0.10. The simulator's own value is A/sqrt(2) = 0.0424, which this
script does not use.

Decision: the article's own rule (Sec. VI-A) -- reducible share < 3 %: do not adapt; > 10 %: adapt
(test); between: no call. Share = (frozen MAE - floor) / frozen MAE, frozen MAE from the stored
30-seed sweeps.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

DLCS = (0.05, 0.10, 0.30)


def decision(share: float) -> str:
    if share < 0.03:
        return "do not adapt"
    if share > 0.10:
        return "adapt"
    return "no call"


def main() -> None:
    mass = pd.read_csv("export/data/vehicle_mass_by_scenario.csv", index_col="scenario")
    rows = []
    for sweep in ("ladder30", "heldout30"):
        d = pd.read_csv(f"export/data/{sweep}_long.csv")
        d = d[d.estimator == "static_affine"]
        for scen, g in d.groupby("scenario"):
            mae = g[g.metric == "mae_kg"].value.median()
            floor = g[g.metric == "dynamic_floor_kg"].value.median()
            true_share = max(mae - floor, 0.0) / mae
            row = {"scenario": scen, "frozen_mae_kg": mae, "true_floor_kg": floor,
                   "true_share": true_share, "true_decision": decision(true_share)}
            for dlc in DLCS:
                est = dlc * np.sqrt(2 / np.pi) * mass.loc[scen, "mean_kg"]
                share = max(mae - est, 0.0) / mae
                row[f"floor_dlc{dlc}"] = est
                row[f"share_dlc{dlc}"] = share
                row[f"decision_dlc{dlc}"] = decision(share)
            rows.append(row)
    out = pd.DataFrame(rows)
    out.to_csv("export/data/p1/p1_floor_prior.csv", index=False)
    cols = ["scenario", "true_floor_kg", "true_share", "true_decision"] + [
        c for dlc in DLCS for c in (f"floor_dlc{dlc}", f"share_dlc{dlc}", f"decision_dlc{dlc}")]
    with pd.option_context("display.width", 250):
        print(out[cols].round(3).to_string(index=False))


if __name__ == "__main__":
    main()
