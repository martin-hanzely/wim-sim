"""Revision item 1.6(b) -- the floor from repeated crossings of one reference vehicle.

What a station would do: cross its calibration truck N times, compare each measured mass with the
truck's weighbridge mass, and read the spread. The coefficient of variation of measured/static is
the truck's gross-mass dynamic load coefficient; assuming the dynamic error scales with mass, the
fleet floor is  floor_est = sqrt(2/pi) * CV * mean fleet mass  (the fleet mean is known from the
station's reference masses). Nothing here needs the simulator's per-vehicle floor.

Emulation. The generator has no "same vehicle again" mode, so N crossings of the 5-axle artic class
are drawn from the scenario's own traffic (same road, same dynamic-load model). The measured mass of
a crossing is its applied mass: the sensor adds ~1 kg against a ~300 kg spread, and a frozen
calibration's gain bias scales the spread by a fraction of a per cent; both are ignored, and the
log says so. Class members differ in static mass, so CV is taken of applied/static per crossing,
which is what one truck at fixed load would show.

N = 20 crossings (a morning's work for a test truck). The decision is resampled 1000 times over
which 20 crossings are drawn, so the answer includes how often a real campaign of that size would
reach each decision.

Decision rule: the article's Sec. VI-A, as in 1.6(a).
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from wimsim.core.config import load_run_config
from wimsim.core.rng import streams
from wimsim.signal.vehicles import schedule_passes

SCENARIOS = ["S2_thermal_cycle", "S3_zero_drift_walk", "S4_step_fault", "S5_outage",
             "S6_combined", "S7_sparse_reference", "H1_warm_front", "H2_gain_jolt",
             "H3_slow_fade", "H4_pileup"]
TRUCK = "artic_5axle"
N_CROSSINGS = 20
N_RESAMPLE = 1000


def decision(share: float) -> str:
    if share < 0.03:
        return "do not adapt"
    if share > 0.10:
        return "adapt"
    return "no call"


def frozen_mae_and_floor() -> pd.DataFrame:
    rows = []
    for sweep in ("ladder30", "heldout30"):
        d = pd.read_csv(f"export/data/{sweep}_long.csv")
        d = d[d.estimator == "static_affine"]
        for scen, g in d.groupby("scenario"):
            rows.append({"scenario": scen,
                         "frozen_mae_kg": g[g.metric == "mae_kg"].value.median(),
                         "true_floor_kg": g[g.metric == "dynamic_floor_kg"].value.median()})
    return pd.DataFrame(rows).set_index("scenario")


def main() -> None:
    ref = frozen_mae_and_floor()
    rng = np.random.default_rng(20261005)
    rows = []
    for scen in SCENARIOS:
        cfg = load_run_config(scen, None, overrides=["scenario.output.samples=none"], seed=1)
        passes = schedule_passes(cfg, streams(cfg.scenario.seed))
        ratio = np.array([p.applied_mass_kg / p.true_mass_kg for p in passes
                          if p.vehicle_class == TRUCK])
        mean_mass = float(np.mean([p.true_mass_kg for p in passes]))
        mae, true_floor = ref.loc[scen, "frozen_mae_kg"], ref.loc[scen, "true_floor_kg"]
        true_share = max(mae - true_floor, 0.0) / mae

        cv_all = float(np.std(ratio, ddof=1))
        floor_all = np.sqrt(2 / np.pi) * cv_all * mean_mass
        draws = []
        for _ in range(N_RESAMPLE):
            sample = rng.choice(ratio, size=N_CROSSINGS, replace=False)
            f = np.sqrt(2 / np.pi) * np.std(sample, ddof=1) * mean_mass
            draws.append((f, decision(max(mae - f, 0.0) / mae)))
        f_draws = np.array([d[0] for d in draws])
        agree = np.mean([d[1] == decision(true_share) for d in draws])
        rows.append({
            "scenario": scen, "n_truck_crossings_available": len(ratio),
            "truck_gross_cv": cv_all, "true_floor_kg": true_floor,
            "floor_est_kg": floor_all, "floor_est_over_true": floor_all / true_floor,
            "floor_est_p05_kg": float(np.quantile(f_draws, 0.05)),
            "floor_est_p95_kg": float(np.quantile(f_draws, 0.95)),
            "true_share": true_share,
            "est_share": max(mae - floor_all, 0.0) / mae,
            "true_decision": decision(true_share),
            "est_decision": decision(max(mae - floor_all, 0.0) / mae),
            "p_same_decision_n20": float(agree),
        })
    out = pd.DataFrame(rows)
    out.to_csv("export/data/p1/p1_floor_repeat.csv", index=False)
    with pd.option_context("display.width", 250):
        print(out.round(3).to_string(index=False))


if __name__ == "__main__":
    main()
