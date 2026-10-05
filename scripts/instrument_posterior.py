"""Record the adaptive estimators' internal state after every reference update (revision item 1.5).

The posterior covariance is estimator state that no run persists -- events carry only its trace --
so this wraps ``update`` on the two adaptive estimators for the duration of one closed-loop run and
records, after every reference observation:

* the parameter estimate and its covariance, and from it the posterior correlation between the
  two parameters (RLS: [gain, bias] in the prediction direction; Kalman: [q, k], sensor side);
* the estimate expressed in the sensor direction, ``k_hat`` and ``q_hat``, for both estimators;
* the plant's true ``k`` and ``q`` at that reference vehicle's peak, from the truth log.

Wrapping the class method rather than one instance is deliberate: a controller recalibration
replaces the live estimator with a fresh one, and every instance must be recorded.

Usage:
  python scripts/instrument_posterior.py --scenario S2_thermal_cycle --estimator rls \
      --edge default --seeds 1,2,3 --out data/results/revision_p1/posterior
  ... --override scenario.zero_drift.temp_coupling_per_c=0.0   (the offset-coupling ablation)
"""

from __future__ import annotations

import argparse
import tempfile
from pathlib import Path

import numpy as np
import pandas as pd

from wimsim.calibration.kalman import KalmanCalibration
from wimsim.calibration.rls import RecursiveLeastSquares
from wimsim.core.config import load_edge_config, load_run_config
from wimsim.experiments.closed_loop import run_closed_loop
from wimsim.experiments.offline import load_run
from wimsim.signal.writer import write_run

_RECORDS: list[dict] = []


def _wrap(cls) -> None:
    original = cls.update

    def update(self, observation):
        state = original(self, observation)
        p = np.array(state.covariance, dtype=float)
        corr = float(p[0, 1] / np.sqrt(p[0, 0] * p[1, 1])) if p[0, 0] > 0 and p[1, 1] > 0 else np.nan
        _RECORDS.append(
            {
                "ts_us": int(observation.ts_us),
                "reference_mass_kg": float(observation.reference_mass_kg),
                "feature": float(observation.feature),
                "gain": state.gain,
                "bias": state.bias,
                "k_hat": state.sensor_gain,
                "q_hat": state.sensor_bias,
                "p00": float(p[0, 0]),
                "p01": float(p[0, 1]),
                "p11": float(p[1, 1]),
                "posterior_corr": corr,
            }
        )
        return state

    cls.update = update


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--scenario", default="S2_thermal_cycle")
    ap.add_argument("--estimator", choices=["rls", "kalman"], required=True)
    ap.add_argument("--edge", default="default")
    ap.add_argument("--seeds", default="1,2,3")
    ap.add_argument("--override", action="append", default=[])
    ap.add_argument("--edge-override", action="append", default=[])
    ap.add_argument("--label", default=None)
    ap.add_argument("--out", type=Path, required=True)
    args = ap.parse_args()

    _wrap(RecursiveLeastSquares)
    _wrap(KalmanCalibration)

    edge = load_edge_config(
        args.edge,
        overrides=[
            "edge.control.enabled=true",
            "edge.drift.page_hinkley_threshold=15.0",
            "edge.control.reference_every_n=10",
            f"edge.estimate.estimator={args.estimator}",
            *args.edge_override,
        ],
    )
    label = args.label or f"{args.scenario}__{args.estimator}__{args.edge}"
    args.out.mkdir(parents=True, exist_ok=True)
    frames = []
    for seed in [int(s) for s in args.seeds.split(",")]:
        _RECORDS.clear()
        cfg = load_run_config(
            args.scenario, None, overrides=["scenario.output.samples=none", *args.override],
            seed=seed,
        )
        with tempfile.TemporaryDirectory() as tmp:
            out = write_run(cfg, Path(tmp) / "run")
            cfg, truth, _ = load_run(out.out_dir)
            result = run_closed_loop(cfg, truth, edge, calibration_passes=60)
        rec = pd.DataFrame(_RECORDS)
        t = truth[["ts_peak_us", "k_at_peak", "q_at_peak"]].sort_values("ts_peak_us")
        rec = pd.merge_asof(
            rec.sort_values("ts_us"), t, left_on="ts_us", right_on="ts_peak_us",
            direction="nearest",
        )
        rec["seed"] = seed
        rec["label"] = label
        rec["mae_kg"] = result.score.mae_kg if result.score else np.nan
        frames.append(rec)
        print(
            f"{label} seed {seed}: {len(rec)} updates, median posterior corr "
            f"{rec.posterior_corr.median():+.4f}, corr(k_hat, k_true) "
            f"{rec.k_hat.corr(rec.k_at_peak):+.3f}, MAE {rec.mae_kg.iloc[0]:.2f} kg",
            flush=True,
        )
    pd.concat(frames).to_parquet(args.out / f"{label}.parquet", index=False)


if __name__ == "__main__":
    main()
