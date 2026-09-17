"""Running a pipeline over a run, offline, and scoring what comes out.

This is the phase-2 checkpoint made executable: point it at a run directory, get an MAE.

**The stream is regenerated rather than read back.** A run directory need not contain
``samples.parquet`` at all -- long scenarios default to keeping only windows, and dense ones to
keeping nothing -- but ``manifest.json`` holds the fully resolved config, and the same seed and
config produce a byte-identical stream by construction (principle 4). Regenerating is therefore
exact, costs no disk, and is checked by the determinism tests rather than assumed here.

**Bootstrapping the baseline.** ``StaticAffine`` must be fitted before it can predict, and in the
field that fit comes from reference vehicles of known mass. Offline, the equivalent is a
*calibration split*: the first ``calibration_passes`` vehicles have their masses read from the truth
log and handed to the estimator as ``ReferenceObservation``s, exactly as a known reference vehicle
would be. Everything after the split is scored, so no pass is ever both training and test data.

One pass over the stream suffices in phase 2, and the reason is worth stating because it will stop
being true. Feature extraction depends on the active profile only through the preprocessor's
temperature compensation, and ``StaticAffine`` does not fit a temperature coefficient -- so the
bootstrap profile and the fitted one compensate identically and the features do not move. Phase 5's
estimators do adapt their coefficient, and will need the two-pass structure.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

import pandas as pd

from wimsim.calibration import (
    CalibrationProfile,
    EstimatorState,
    ReferenceObservation,
    StaticAffine,
)
from wimsim.core.config import EdgeConfig, RunConfig
from wimsim.core.provenance import collect
from wimsim.core.schemas import MeasurementEvent, ProvenanceBlock
from wimsim.edge.detect import DetectedEvent
from wimsim.edge.pipeline import OfflinePipeline
from wimsim.experiments.scoring import ScoreResult, score_events
from wimsim.observability.metrics import Metrics
from wimsim.observability.tracing import Tracing
from wimsim.source import SyntheticSource

__all__ = ["OfflineResult", "load_run", "run_offline"]


@dataclass(frozen=True, slots=True)
class OfflineResult:
    run_config: RunConfig
    edge_config: EdgeConfig
    profile: CalibrationProfile
    events: list[MeasurementEvent]
    score: ScoreResult
    stats: dict[str, float]
    calibration_passes: int

    def to_dict(self) -> dict:
        return {
            "scenario": self.run_config.scenario.name,
            "station_id": self.run_config.station.station_id,
            "config_hash": self.run_config.config_hash(),
            "edge_config": self.edge_config.name,
            "edge_config_hash": self.edge_config.config_hash(),
            "feature": self.edge_config.estimate.feature,
            "axle_summation": self.edge_config.estimate.axle_summation,
            "estimator": self.profile.state.estimator,
            "calibration_passes": self.calibration_passes,
            "profile": self.profile.to_dict(),
            "stats": self.stats,
            "score": self.score.to_dict(),
        }


def load_run(run_dir: Path) -> tuple[RunConfig, pd.DataFrame, dict]:
    """Resolved config, truth passes, and the manifest, from a run directory."""
    run_dir = Path(run_dir)
    manifest = json.loads((run_dir / "manifest.json").read_text(encoding="utf-8"))
    cfg = RunConfig.model_validate(manifest["config"])
    truth = pd.read_parquet(run_dir / "truth_passes.parquet")
    return cfg, truth, manifest


def _bootstrap_profile(edge_cfg: EdgeConfig) -> CalibrationProfile:
    """A profile that compensates for nothing, used only to extract features before the fit.

    ``fitted`` stays False so that any attempt to *predict* through it raises rather than returning
    a plausible-looking number.
    """
    state = EstimatorState(
        estimator=edge_cfg.estimate.estimator,
        gain=1.0,
        bias=0.0,
        temp_coeff=0.0,
        coverage_target=edge_cfg.estimate.coverage_target,
        fitted=False,
    )
    return CalibrationProfile.from_state(
        state, profile_id="bootstrap", activated_ts_us=0, reason="bootstrap"
    )


def _feature_of(edge_cfg: EdgeConfig, event: DetectedEvent) -> float:
    return event.axle_peak_sum if edge_cfg.estimate.feature == "peak" else event.area


def run_offline(
    cfg: RunConfig,
    truth: pd.DataFrame,
    edge_cfg: EdgeConfig,
    *,
    calibration_passes: int | None = None,
    match_tolerance_s: float = 0.25,
    metrics: Metrics | None = None,
    tracing: Tracing | None = None,
) -> OfflineResult:
    """Detect over the whole run, fit on the calibration split, estimate, score the rest."""
    n_cal = calibration_passes or edge_cfg.estimate.bootstrap_passes

    source = SyntheticSource(cfg)
    pipeline = OfflinePipeline(
        edge_cfg,
        source=source,
        profile=_bootstrap_profile(edge_cfg),
        provenance=_provenance_for(cfg),
        metrics=metrics,
        tracing=tracing,
    )

    detected = list(pipeline.detect_only())
    if len(detected) <= n_cal:
        raise ValueError(
            f"{len(detected)} events detected but {n_cal} are reserved for calibration; there "
            "would be nothing left to score. Lengthen the run or lower bootstrap_passes."
        )

    profile = _fit_profile(edge_cfg, detected[:n_cal], truth, match_tolerance_s)
    pipeline.set_profile(profile)

    preprocessing = pipeline.preprocessor.describe()
    events = [pipeline.estimate(d, preprocessing) for d in detected]

    # Score only the held-out part. A pass used to fit the calibration cannot also test it.
    held_out = _held_out_truth(truth, detected, n_cal)
    scored_events = events[n_cal:]
    return OfflineResult(
        run_config=cfg,
        edge_config=edge_cfg,
        profile=profile,
        events=events,
        score=score_events(
            scored_events,
            held_out,
            tolerance_s=match_tolerance_s,
            expected_interval_source=edge_cfg.uncertainty.method,
        ),
        stats=pipeline.stats(),
        calibration_passes=n_cal,
    )


def _provenance_for(cfg: RunConfig) -> ProvenanceBlock:
    prov = collect(config_hash=cfg.config_hash(), seed=cfg.scenario.seed, mode=cfg.mode)
    return ProvenanceBlock(
        config_hash=prov.config_hash,
        seed=prov.seed,
        mode=prov.mode,
        git_commit=prov.git_commit,
        git_dirty=prov.git_dirty,
    )


def _fit_profile(
    edge_cfg: EdgeConfig,
    calibration_events: list[DetectedEvent],
    truth: pd.DataFrame,
    tolerance_s: float,
) -> CalibrationProfile:
    """Fit the baseline from reference vehicles, matched to detections by time."""
    epoch_us = float(truth["ts_peak_us"].iloc[0]) - float(truth["t_peak_s"].iloc[0]) * 1e6
    peaks = truth["t_peak_s"].to_numpy()

    observations: list[ReferenceObservation] = []
    for event in calibration_events:
        t_peak_s = (event.ts_peak_us - epoch_us) / 1e6
        i = int(abs(peaks - t_peak_s).argmin())
        if abs(peaks[i] - t_peak_s) > tolerance_s:
            continue  # a detection with no reference vehicle behind it teaches nothing
        observations.append(
            ReferenceObservation(
                ts_us=event.ts_peak_us,
                feature=_feature_of(edge_cfg, event),
                temp_c=0.0,
                reference_mass_kg=float(truth["true_mass_kg"].iloc[i]),
                axle_count=event.axle_count,
                source="supervised",
            )
        )

    if len(observations) < 2:
        raise ValueError(
            f"only {len(observations)} calibration observations could be matched to reference "
            "vehicles; a two-parameter fit needs at least two"
        )

    estimator = StaticAffine(coverage_target=edge_cfg.estimate.coverage_target)
    estimator.fit(observations)
    return CalibrationProfile.from_state(
        estimator.state(),
        profile_id=f"p-{estimator.state().state_hash}",
        activated_ts_us=observations[-1].ts_us,
        reason="bootstrap",
        provenance={"n_reference_observations": len(observations)},
    )


def _held_out_truth(truth: pd.DataFrame, detected: list[DetectedEvent], n_cal: int) -> pd.DataFrame:
    """Truth passes after the calibration split, by time rather than by index.

    Index would be wrong whenever detection missed a pass: the split is defined by *when* the
    calibration ended, not by how many detections preceded it.
    """
    if n_cal == 0 or not detected:
        return truth
    epoch_us = float(truth["ts_peak_us"].iloc[0]) - float(truth["t_peak_s"].iloc[0]) * 1e6
    cutoff_s = (detected[n_cal - 1].ts_end_us - epoch_us) / 1e6
    return truth[truth["t_entry_s"] > cutoff_s].reset_index(drop=True)
