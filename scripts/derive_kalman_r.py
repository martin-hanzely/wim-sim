"""Derive the Kalman measurement noise R from the station's own scale (revision item 1.2).

R is the variance of the observation ``z = feature`` about ``q + k * m_static``. The part of that
variance no calibration can remove is the dynamic load -- the applied mass differs from the static
mass the reference reports -- and in feature units it is ``k^2 * E[(m_applied - m_static)^2]``.

Two quantities, each measured rather than assumed:

* ``E[(m_applied - m_static)^2]`` over every vehicle the generator schedules, on the development
  scenarios that share the base traffic (S2-S5). ``schedule_passes`` is called with the seed's own
  streams, which is the first thing the generator does, so these are the vehicles of the run
  without synthesising its signal. H1-H4 are not read: R is a station property and the held-out
  scenarios must not inform it.
* ``k`` from the station's own commissioning fit -- the Kalman arm's seed fit of feature on mass
  over the first calibration passes, which is the profile the filter starts from. Taken on the two
  shortest S2-S5 scenarios: the seed fit sees only the first passes, before any injected fault.

The script also prints the batch residual variance of that same fit, in feature units^2: the
total observation variance the commissioning data itself shows, for comparison.

Usage: python scripts/derive_kalman_r.py [--station default|cintron_sim]
"""

from __future__ import annotations

import argparse
import json
import tempfile
from pathlib import Path

import numpy as np

from wimsim.core.config import load_edge_config, load_run_config
from wimsim.core.rng import streams
from wimsim.experiments.closed_loop import run_closed_loop
from wimsim.experiments.offline import load_run
from wimsim.signal.vehicles import schedule_passes
from wimsim.signal.writer import write_run

SCENARIOS = ["S2_thermal_cycle", "S3_zero_drift_walk", "S4_step_fault", "S5_outage"]
TRUTH_SEEDS = list(range(1, 11))
GAIN_SCENARIOS = ["S4_step_fault", "S5_outage"]
GAIN_SEEDS = [1, 2, 3]

STATIONS = {
    "default": {"edge": "default", "overrides": ["scenario.output.samples=none"]},
    "cintron_sim": {
        "edge": "cintron_sim",
        "overrides": [
            "scenario.output.samples=none",
            "scenario.pulse.shape=influence_line",
            "scenario.pulse.width_source=influence_length",
        ],
    },
}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--station", default="default", choices=sorted(STATIONS))
    parser.add_argument("--calibration-passes", type=int, default=60)
    args = parser.parse_args()
    station = STATIONS[args.station]

    dyn_ms, dyn_abs, n_veh = {}, {}, {}
    for scen in SCENARIOS:
        squares, absolutes = [], []
        for seed in TRUTH_SEEDS:
            cfg = load_run_config(scen, args.station, overrides=station["overrides"], seed=seed)
            passes = schedule_passes(cfg, streams(cfg.scenario.seed))
            d = np.array([p.applied_mass_kg - p.true_mass_kg for p in passes], dtype=float)
            squares.append(d**2)
            absolutes.append(np.abs(d))
        sq = np.concatenate(squares)
        dyn_ms[scen] = float(sq.mean())
        dyn_abs[scen] = float(np.concatenate(absolutes).mean())
        n_veh[scen] = int(sq.size)

    ks, resid_var = [], []
    edge = load_edge_config(station["edge"], overrides=["edge.estimate.estimator=kalman"])
    for scen in GAIN_SCENARIOS:
        for seed in GAIN_SEEDS:
            cfg = load_run_config(scen, args.station, overrides=station["overrides"], seed=seed)
            with tempfile.TemporaryDirectory() as tmp:
                out = write_run(cfg, Path(tmp) / "run")
                cfg, truth, _ = load_run(out.out_dir)
                result = run_closed_loop(
                    cfg, truth, edge, calibration_passes=args.calibration_passes
                )
            seed_state = result.profiles[0].state
            k = 1.0 / seed_state.gain  # state is reported in the prediction direction
            ks.append(k)
            # residual_sd is the batch residual in kg, seeded as variance / k^2
            resid_var.append((seed_state.residual_sd * k) ** 2)

    pooled_ms = float(np.average(list(dyn_ms.values()), weights=list(n_veh.values())))
    k_med = float(np.median(ks))
    r = k_med**2 * pooled_ms
    report = {
        "station": args.station,
        "dynamic_ms_kg2_by_scenario": dyn_ms,
        "dynamic_mae_kg_by_scenario": dyn_abs,
        "n_vehicles_by_scenario": n_veh,
        "dynamic_rms_kg_pooled": pooled_ms**0.5,
        "k_feature_per_kg_seed_fits": ks,
        "k_feature_per_kg_median": k_med,
        "batch_residual_var_feature2": resid_var,
        "R_feature2": r,
        "R_over_shipped_1e-8": r / 1.0e-8,
        "sigma_kg_implied_by_shipped_R": (1.0e-8**0.5) / k_med,
    }
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
