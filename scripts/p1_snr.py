"""Revision item 1.4 -- the decision criterion restated as a signal-to-noise ratio.

    SNR = reducible excess of the frozen arm  /  variance cost of the adaptive arm

both in squared error (kg^2), per scenario. Squared error because it decomposes (item 1.1) and the
variance cost is a variance.

Numerator, from the frozen arm's own runs (``p1_mem_*`` record the decomposition):
    excess_ms = rmse^2 - floor_ms          (= excess_ms_kg2 + cross_kg2, exactly)

Variance cost -- the steady-state excess MSE an adaptive estimator adds on a plant that is NOT
moving, i.e. what it pays for being able to move:

* RLS, forgetting lambda, p = 2 parameters: the exponentially weighted LS error covariance is
  sigma^2 (1 - lambda)/(1 + lambda) R_phi^-1, so the excess MSE on a fresh regressor is
  p sigma^2 (1 - lambda)/(1 + lambda). lambda = 1 has no steady-state cost (it -> 0 as 1/n).
* Periodic refit on a window of W: p sigma^2 / W.
* Kalman: the covariance recursion run over this scenario's own reference masses and intervals,
  from the commissioning covariance, with Q dt between references and the configured R; averaged
  over the run (there is no steady state within a run -- see ``kalman_cost_kg2``) and propagated
  to kg through J = [-1/k, -m/k], averaged over the fleet's masses.

sigma^2 is the noise of the label about the regression in kg^2: the scenario's dynamic floor in
squared error, floor_ms_kg2, as measured on the frozen arm's own runs. Sensor noise is not in it;
see the S1 caveat in the log.

Usage: python scripts/p1_snr.py   (reads data/results/p1_*; writes export/data/p1/p1_snr.csv)
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from wimsim.core.config import load_run_config
from wimsim.core.rng import streams
from wimsim.signal.vehicles import schedule_passes

DEV = ["S1_nominal", "S2_thermal_cycle", "S3_zero_drift_walk", "S4_step_fault", "S5_outage",
       "S6_combined", "S7_sparse_reference"]
HELD = ["H1_warm_front", "H2_gain_jolt", "H3_slow_fade", "H4_pileup"]
P = 2
LAMBDA = 0.99
WINDOW = 60
REF_EVERY = 10
K = 2.0079e-4            # kr_floor.yaml
R_CORRECTED = 2.933e-3
R_SHIPPED = 1.0e-8
Q_RATE = np.array([1.0e-7, 1.0e-11]) ** 2   # variance per second, [q, k]
MAX_GAP_S = 3600.0


def fleet(scen: str, seed: int = 1) -> tuple[np.ndarray, np.ndarray]:
    """Commissioning passes then every REF_EVERY-th, as the loop sees them; and their gaps."""
    cfg = load_run_config(scen, None, overrides=["scenario.output.samples=none"], seed=seed)
    passes = schedule_passes(cfg, streams(cfg.scenario.seed))
    t_all = np.array([p.t_peak_s for p in passes])
    m_all = np.array([p.true_mass_kg for p in passes])
    t = np.concatenate([t_all[:60], t_all[60::REF_EVERY]])
    m = np.concatenate([m_all[:60], m_all[60::REF_EVERY]])
    return m, np.minimum(np.diff(t), MAX_GAP_S)


def kalman_cost_kg2(masses: np.ndarray, gaps: np.ndarray, r: float, sigma2_kg2: float) -> float:
    """Run-averaged J C J' in kg^2 -- C the actual error covariance -- over every reference.

    Not a steady state: with Q this small the recursion needs ~sqrt(R / (E[m^2] Q dt)) ~ 4e4
    references to reach one, and a run has ~1e3. So the cost is what the filter actually carries
    over the run. P starts where ``KalmanCalibration.fit`` puts it -- the batch residual variance
    (here sigma2 in feature units, k^2 sigma2) times inv(H'H) over the first 60 passes -- which is
    the same for both R arms; only the recursion after it differs.
    """
    r_true = K * K * sigma2_kg2
    h0 = np.column_stack([np.ones(60), masses[:60]])
    p = np.linalg.inv(h0.T @ h0) * r_true
    # Two covariances. ``p`` is what the filter believes and sets its gain from; ``c`` is the
    # actual error covariance under that gain and the TRUE observation noise. They coincide when R
    # is right. With R = 1e-8 the belief collapses to almost nothing while the actual error does not,
    # and the cost is the actual one.
    c = p.copy()
    acc, n = np.zeros((2, 2)), 0
    for i in range(60, len(masses) - 1):
        q = np.diag(Q_RATE * gaps[i])
        p, c = p + q, c + q
        h = np.array([1.0, masses[i]])
        g = p @ h / (h @ p @ h + r)
        ikh = np.eye(2) - np.outer(g, h)
        p = ikh @ p @ ikh.T + np.outer(g, g) * r
        c = ikh @ c @ ikh.T + np.outer(g, g) * r_true
        acc += c
        n += 1
    p_run = acc / n
    j = np.stack([-np.ones_like(masses) / K, -masses / K], axis=1)
    return float(np.mean(np.einsum("ni,ij,nj->n", j, p_run, j)))


def frozen_arm(exp: str) -> pd.DataFrame:
    d = pd.read_parquet(f"data/results/{exp}/results.parquet")
    d = d[(d.estimator == "static_affine") & ~d.failed.astype(bool)]
    d = d.assign(excess_ms=d.rmse_kg**2 - d.floor_ms_kg2)
    return d.groupby("scenario")[["excess_ms", "floor_ms_kg2", "mae_kg", "dynamic_floor_kg"]].median()


def main() -> None:
    rows = []
    for exp, scens in (("p1_mem_dev", DEV), ("p1_mem_held", HELD)):
        fr = frozen_arm(exp)
        for s in scens:
            f = fr.loc[s]
            sigma2 = float(f.floor_ms_kg2)
            m, gaps = fleet(s)
            share = max(f.mae_kg - f.dynamic_floor_kg, 0.0) / f.mae_kg
            cost = {
                "rls_l099": P * sigma2 * (1 - LAMBDA) / (1 + LAMBDA),
                "periodic_refit": P * sigma2 / WINDOW,
                "kalman_corrected": kalman_cost_kg2(m, gaps, R_CORRECTED, sigma2),
                "kalman_shipped": kalman_cost_kg2(m, gaps, R_SHIPPED, sigma2),
            }
            for arm, c in cost.items():
                rows.append({"scenario": s, "arm": arm, "excess_ms_kg2": float(f.excess_ms),
                             "floor_ms_kg2": sigma2, "reducible_share_mae": share,
                             "variance_cost_kg2": c,
                             "snr": float(f.excess_ms) / c if c > 0 else np.inf})
    out = pd.DataFrame(rows)
    out.to_csv("export/data/p1/p1_snr.csv", index=False)
    with pd.option_context("display.width", 200):
        print(out.round(4).to_string(index=False))


if __name__ == "__main__":
    main()
