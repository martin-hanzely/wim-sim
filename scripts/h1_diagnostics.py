"""Per-event diagnostics for the H1 penalty (revision item B4).

The hypothesis under test: the Kalman filter predicts by inverting its measurement model,
``m = (s - q_hat) / k_hat``, so if ``k_hat`` (theta_1) drifts small the inversion amplifies every
error, and the cost is a heavy-tailed spread that neither R nor the adaptation rate would touch.

For every matched vehicle this records the signed error against the static mass, the sensor-side
state the event was weighed with (``k_hat``, ``q_hat``, the covariance trace -- all carried on the
event's calibration block), the true ``k`` and ``q`` at the peak, and the time since the last
reference label. For every reference update it records the covariance before propagation, after
propagation (Kalman: the prior the update sees) and after the update, and the gap since the
previous label.

Each run checks itself: the MAE recomputed from the per-event rows must equal the closed loop's own
score, and, where the same cell was run in a stored sweep, that sweep's ``mae_kg``.

Usage:
  python scripts/h1_diagnostics.py --arm kalman_shipped --seeds 1-10 --out data/results/b4_h1
  arms: static, rls, kalman_shipped, kalman_corrected
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
from wimsim.experiments.closed_loop import _cutoff_s, run_closed_loop
from wimsim.experiments.offline import load_run
from wimsim.experiments.scoring import match_events
from wimsim.signal.writer import write_run

SCENARIO = "H1_warm_front"
# The heldout30 / p1_r_held_floor cells, unchanged: same edge overrides, reference rate and budget.
ARMS = {
    "static": ("default", "static_affine", "heldout30"),
    "rls": ("default", "rls", "heldout30"),
    "kalman_shipped": ("default", "kalman", "heldout30"),
    "kalman_corrected": ("kr_floor", "kalman", "p1_r_held_floor"),
}
EDGE_OVERRIDES = [
    "edge.control.enabled=true",
    "edge.drift.page_hinkley_threshold=7.5",
    "edge.control.reference_every_n=10",
]

_UPDATES: list[dict] = []


def _cov(est) -> np.ndarray:
    return np.array(est.state().covariance, dtype=float) if est._fitted else np.full((2, 2), np.nan)


def _wrap(cls) -> None:
    original = cls.update

    def update(self, observation):
        p_pre = _cov(self)
        p_prior = None
        if isinstance(self, KalmanCalibration):
            # the propagated covariance is what the update actually sees; record it by advancing
            # first (idempotent: the update's own advance then has dt = 0)
            self._advance_to(int(observation.ts_us))
            p_prior = np.array(self._p, dtype=float)
        state = original(self, observation)
        p_post = np.array(state.covariance, dtype=float)
        _UPDATES.append(
            {
                "ts_us": int(observation.ts_us),
                "k_hat": state.sensor_gain,
                "q_hat": state.sensor_bias,
                "trace_pre": float(np.trace(p_pre)),
                "trace_prior": float(np.trace(p_prior)) if p_prior is not None else np.nan,
                "maxeig_prior": (
                    float(np.linalg.eigvalsh(p_prior).max()) if p_prior is not None else np.nan
                ),
                "trace_post": float(np.trace(p_post)),
                "p_kk_prior": float(p_prior[1, 1]) if p_prior is not None else np.nan,
                "p_kk_post": float(p_post[1, 1]) if isinstance(self, KalmanCalibration) else np.nan,
            }
        )
        return state

    cls.update = update


def detected_for(result):
    """The closed loop's detected list, as `_cutoff_s` needs it: only the n_cal-th entry's end."""
    return [type("D", (), {"ts_end_us": ev.ts_end})() for ev in result.events]


def _seeds(text: str) -> list[int]:
    if "-" in text:
        a, b = text.split("-")
        return list(range(int(a), int(b) + 1))
    return [int(s) for s in text.split(",")]


def _stored_mae(sweep: str, estimator: str, seed: int) -> float | None:
    path = Path("data/results") / sweep / "results.parquet"
    if not path.exists():
        return None
    d = pd.read_parquet(path)
    row = d[(d.scenario == SCENARIO) & (d.estimator == estimator) & (d.seed == seed)]
    return float(row.mae_kg.iloc[0]) if len(row) else None


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--arm", choices=sorted(ARMS), required=True)
    ap.add_argument("--seeds", default="1-10")
    ap.add_argument("--out", type=Path, required=True)
    args = ap.parse_args()

    _wrap(RecursiveLeastSquares)
    _wrap(KalmanCalibration)
    edge_name, estimator, sweep = ARMS[args.arm]
    edge = load_edge_config(
        edge_name, overrides=[*EDGE_OVERRIDES, f"edge.estimate.estimator={estimator}"]
    )
    args.out.mkdir(parents=True, exist_ok=True)

    for seed in _seeds(args.seeds):
        _UPDATES.clear()
        cfg = load_run_config(SCENARIO, None, overrides=["scenario.output.samples=none"], seed=seed)
        with tempfile.TemporaryDirectory() as tmp:
            out = write_run(cfg, Path(tmp) / "run")
            cfg, truth, _ = load_run(out.out_dir)
            result = run_closed_loop(cfg, truth, edge, calibration_passes=60)

        # exactly the closed loop's own scoring set: the calibration passes are not scored
        held_out = truth[truth["t_entry_s"] > _cutoff_s(truth, detected_for(result), 60)]
        matched, _missed, _spurious = match_events(
            result.events[60:], held_out.reset_index(drop=True)
        )
        by_id = {ev.event_id: ev for ev in result.events}
        cal = pd.DataFrame(
            [
                {
                    "event_id": eid,
                    "k_hat": by_id[eid].calibration.gain,
                    "q_hat": by_id[eid].calibration.bias,
                    "cov_trace": by_id[eid].calibration.covariance_trace,
                    "feature": by_id[eid].compensated_peak,
                    "update_count": by_id[eid].calibration.update_count,
                }
                for eid in matched["event_id"]
            ]
        )
        ev = matched.reset_index(drop=True).join(cal.drop(columns="event_id"))
        ev["error_kg"] = ev["mass_kg"] - ev["true_mass_kg"]
        ev = ev.sort_values("ts_peak_us").reset_index(drop=True)

        upd = pd.DataFrame(_UPDATES)
        if len(upd):
            upd = upd.sort_values("ts_us").reset_index(drop=True)
            upd["gap_s"] = upd["ts_us"].diff() / 1e6
            last = np.searchsorted(upd["ts_us"].to_numpy(), ev["ts_peak_us"].to_numpy()) - 1
            ref_ts = np.where(last >= 0, upd["ts_us"].to_numpy()[np.clip(last, 0, None)], np.nan)
            ev["since_label_s"] = (ev["ts_peak_us"].to_numpy() - ref_ts) / 1e6
        else:
            ev["since_label_s"] = np.nan

        mae = float(ev["error_kg"].abs().mean())
        own = result.score.mae_kg
        assert np.isclose(mae, own, rtol=0, atol=1e-9), (mae, own)
        stored = _stored_mae(sweep, estimator, seed)
        if stored is not None:
            assert np.isclose(mae, stored, rtol=0, atol=1e-6), (mae, stored)

        keep = ["ts_peak_us", "t_peak_s", "true_mass_kg", "applied_mass_kg", "mass_kg", "error_kg",
                "k_hat", "q_hat", "cov_trace", "feature", "update_count", "k_at_peak",
                "q_at_peak", "since_label_s"]
        ev[[c for c in keep if c in ev]].assign(seed=seed, arm=args.arm).to_parquet(
            args.out / f"{args.arm}__events_seed{seed}.parquet", index=False
        )
        if len(upd):
            upd.assign(seed=seed, arm=args.arm).to_parquet(
                args.out / f"{args.arm}__updates_seed{seed}.parquet", index=False
            )
        print(
            f"{args.arm} seed {seed}: {len(ev)} events, {len(upd)} updates, MAE {mae:.3f} kg "
            f"(stored {stored if stored is None else round(stored, 3)}), "
            f"k_hat min {ev.k_hat.min():.4g}",
            flush=True,
        )


if __name__ == "__main__":
    main()
