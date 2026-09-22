"""Calibrating across the real recordings instead of within one of them.

`wimsim score-real` fits and scores inside a single recording. On this corpus that barely works and
proves nothing: the recordings are 60 s each and yield one to seven crossings, two of them cannot be
scored at all because every crossing is needed to fit, and where it does run, the calibration and
the test come from the same minute of the same drive-over.

**Leave one recording out.** Fit on every other recording's crossings and predict the held-out one.
It is the standard construction and it is the one that answers the question actually being asked --
whether a calibration fitted here transfers *there* -- rather than whether a straight line can be
drawn through six points and then evaluated on two of them.

Holding out a whole *recording* rather than random crossings matters. Crossings within a recording
share a vehicle, a driver, a line across the platform and a minute of thermal state; a random split
leaks all of that across the fold boundary and reports a number far better than the site will give.

What this still cannot do is weigh anything. The reference masses are the inference in
`docs/sim-to-real.md`, so every figure here measures whether the pipeline reproduces that inference
across recordings. That is a real question -- a calibration that did not transfer would show up here
regardless of whether the masses are right -- but it is not a metrological one.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import numpy as np

from wimsim.calibration import ReferenceObservation, build_estimator
from wimsim.core.config import EdgeConfig

__all__ = ["Fold", "PooledResult", "collect_observations", "run_pooled"]


@dataclass(frozen=True, slots=True)
class Fold:
    """One held-out recording, scored against a calibration fitted on the others."""

    run_id: str
    n_calibration: int
    n_scored: int
    mae_kg: float
    mape: float
    bias_kg: float
    coverage: float
    mean_interval_width_kg: float
    fitted_gain: float
    """The estimator's gain, in kg per feature unit -- the inverse of the sensor's strain per kg.
    Named for what it is: `EstimatorState.gain` runs mass-on-feature, the direction the estimator
    predicts in."""
    error: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "run_id": self.run_id,
            "n_calibration": self.n_calibration,
            "n_scored": self.n_scored,
            "mae_kg": self.mae_kg,
            "mape": self.mape,
            "bias_kg": self.bias_kg,
            "coverage": self.coverage,
            "mean_interval_width_kg": self.mean_interval_width_kg,
            "fitted_gain": self.fitted_gain,
            "error": self.error,
        }


@dataclass
class PooledResult:
    """Every fold, and the corpus-wide figures over all held-out predictions."""

    folds: list[Fold] = field(default_factory=list)
    n_recordings: int = 0
    n_observations: int = 0
    mae_kg: float = float("nan")
    mape: float = float("nan")
    bias_kg: float = float("nan")
    coverage: float = float("nan")
    skipped: dict[str, str] = field(default_factory=dict)
    """Recordings that could not be read at all, and why. Reported rather than dropped: a corpus
    that quietly excludes half its inputs reports the half that worked."""
    gain_spread: float = float("nan")
    """max/min fitted gain across folds, minus one. How much the calibration moves when the data
    it was fitted on changes -- which is the question leave-one-out exists to ask."""

    def to_dict(self) -> dict[str, Any]:
        return {
            "n_recordings": self.n_recordings,
            "n_observations": self.n_observations,
            "mae_kg": self.mae_kg,
            "mape": self.mape,
            "bias_kg": self.bias_kg,
            "coverage": self.coverage,
            "gain_spread": self.gain_spread,
            "skipped": dict(self.skipped),
            "folds": [f.to_dict() for f in self.folds],
        }


def collect_observations(
    run_dir: Path | str,
    edge_cfg: EdgeConfig,
    *,
    channel: str,
    tolerance_s: float = 1.0,
) -> list[ReferenceObservation]:
    """Detect a recording's crossings and pair each with its reference row.

    A detection with no reference behind it teaches nothing and is dropped, which is the same rule
    the synthetic bootstrap applies.
    """
    from wimsim.core.config import RunConfig, load_run_config
    from wimsim.edge.pipeline import OfflinePipeline
    from wimsim.experiments.offline import _bootstrap_profile, _feature_of, _provenance_for
    from wimsim.source import build_source
    from wimsim.source.reference import load_reference

    path = Path(run_dir)
    tree = load_run_config("S8_replay_real").model_dump(mode="json")
    tree["scenario"]["source"] = {
        "kind": "replay",
        "replay": {
            "run_dir": str(path),
            "channel": channel,
            "rate": "accelerated",
            "speed_multiplier": None,
        },
    }
    cfg = RunConfig.model_validate(tree)
    source = build_source(cfg)
    reference = load_reference(path, t0_us=source.metadata.start_time_us)

    pipeline = OfflinePipeline(
        edge_cfg,
        source=build_source(cfg),
        profile=_bootstrap_profile(edge_cfg),
        provenance=_provenance_for(cfg),
    )
    ref_t = reference["t_peak_s"].to_numpy()
    ref_m = reference["true_mass_kg"].to_numpy()

    out: list[ReferenceObservation] = []
    for event in pipeline.detect_only():
        i = int(np.abs(ref_t - event.t_peak_s).argmin())
        if abs(ref_t[i] - event.t_peak_s) > tolerance_s:
            continue
        out.append(
            ReferenceObservation(
                ts_us=event.ts_peak_us,
                feature=_feature_of(edge_cfg, event),
                temp_c=event.temp_c or 0.0,
                reference_mass_kg=float(ref_m[i]),
                axle_count=event.axle_count,
                source="supervised",
            )
        )
    return out


def run_pooled(
    run_dirs: list[Path | str],
    edge_cfg: EdgeConfig,
    *,
    channel: str = "Tenzo2",
    estimator: str = "static_affine",
    tolerance_s: float = 1.0,
) -> PooledResult:
    """Leave-one-recording-out over the corpus."""
    by_run: dict[str, list[ReferenceObservation]] = {}
    skipped: dict[str, str] = {}
    for run_dir in run_dirs:
        path = Path(run_dir)
        try:
            obs = collect_observations(path, edge_cfg, channel=channel, tolerance_s=tolerance_s)
        except (OSError, KeyError, ValueError) as exc:
            # A recording that cannot be read at all -- a channel this corpus does not have, a
            # missing reference file -- is excluded, and saying which and why beats a corpus that
            # quietly reports the recordings that happened to work.
            skipped[path.name] = str(exc)
            continue
        if obs:
            by_run[path.name] = obs
        else:
            skipped[path.name] = "no detected crossing matched a reference row"

    result = PooledResult(
        n_recordings=len(by_run),
        n_observations=sum(len(v) for v in by_run.values()),
        skipped=skipped,
    )
    if len(by_run) < 2:
        return result

    errors: list[float] = []
    relative: list[float] = []
    covered: list[bool] = []
    gains: list[float] = []

    for held_out, scored in by_run.items():
        calibration = [o for name, obs in by_run.items() if name != held_out for o in obs]
        est = build_estimator(estimator)
        try:
            state = est.fit(calibration)
        except (ValueError, RuntimeError) as exc:
            nan = float("nan")
            result.folds.append(
                Fold(held_out, len(calibration), 0, nan, nan, nan, nan, nan, nan, str(exc))
            )
            continue

        fold_err, fold_cov, widths = [], [], []
        for o in scored:
            band = est.predict(o.feature, o.temp_c)
            fold_err.append(band.mass_kg - o.reference_mass_kg)
            fold_cov.append(band.mass_ci_low <= o.reference_mass_kg <= band.mass_ci_high)
            widths.append(band.mass_ci_high - band.mass_ci_low)

        err = np.array(fold_err, dtype=np.float64)
        masses = np.array([o.reference_mass_kg for o in scored], dtype=np.float64)
        gains.append(float(state.gain))
        errors.extend(err.tolist())
        relative.extend((np.abs(err) / masses).tolist())
        covered.extend(fold_cov)

        result.folds.append(
            Fold(
                run_id=held_out,
                n_calibration=len(calibration),
                n_scored=len(scored),
                mae_kg=float(np.mean(np.abs(err))),
                mape=float(np.mean(np.abs(err) / masses)),
                bias_kg=float(np.mean(err)),
                coverage=float(np.mean(fold_cov)),
                mean_interval_width_kg=float(np.mean(widths)),
                fitted_gain=float(state.gain),
            )
        )

    if errors:
        e = np.array(errors, dtype=np.float64)
        result.mae_kg = float(np.mean(np.abs(e)))
        result.mape = float(np.mean(relative))
        result.bias_kg = float(np.mean(e))
        result.coverage = float(np.mean(covered))
    if gains:
        lo, hi = min(gains), max(gains)
        result.gain_spread = float(hi / lo - 1.0) if lo > 0 else float("nan")
    return result
