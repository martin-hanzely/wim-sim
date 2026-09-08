"""The loop, closed: estimate, score against a reference, detect drift, recalibrate, verify.

``offline.py`` fits once and measures the result. This runs the same pipeline with the phase-5
controller in it, and it is the only place in the project where all five pieces meet -- an adaptive
estimator, four drift detectors, the MAPE-K machine, conformal intervals and the profile store.

**Where the truth enters, and why that is allowed.** The controller needs residuals, and a residual
needs a reference mass. In the field that mass comes from a transponder-equipped fleet vehicle or a
weighbridge a mile up the road; here it comes from the truth log, read *by this module*. That is the
whole point of the ``ReferenceObservation`` boundary: ``calibration/`` receives a mass and cannot
tell where it came from, and ``tests/test_truth_isolation.py`` proves it never reaches for one
itself. ``experiments/`` is the designated truth-joining layer and is deliberately outside the
quarantine.

**One pass in ``reference_every_n`` is a reference, and that number is the experiment.** It is the
supply rate of known masses, and it decides whether self-calibration is possible at a site at all:
a motorway with a co-located weighbridge and a rural road with none are the same code and completely
different problems. ``S7_sparse_reference`` exists to push it to zero.

It also sets how long the *detectors* take to become usable, which is less obvious and was worth a
wasted afternoon. A detector's warm-up is counted in residuals, residuals arrive only on reference
passes, so readiness costs ``drift.warmup * reference_every_n`` passes. On ``S4_step_fault`` at the
old default that was 33,144 s of a 57,600 s run -- past both injected faults, which the detector had
by then learned as normal, reporting zero alarms and looking entirely healthy while doing it.
``detectors_ready_after_references`` is on the result so that a run which could not have detected
anything says so.

**Both adaptation mechanisms run, and they interact.** An RLS or Kalman estimator folds every
reference observation into itself continuously; the controller performs a wholesale refit when drift
is *confirmed*. A sufficiently fast estimator may absorb a step before any detector alarms, so the
controller never fires -- which is not a bug but a result, and the reason the ladder is run with
``static_affine`` for the checkpoint: it isolates the controller by using an estimator that cannot
adapt on its own.

**The single-pass caveat, inherited and still true.** Feature extraction depends on the active
profile only through the preprocessor's temperature compensation. Every estimator shipped here fits
``temp_coeff = 0``, so activating a new profile mid-stream does not move the features and one pass
over the detections remains exact. An estimator that fitted a temperature coefficient would need
the two-pass structure ``offline.py`` describes, and this module would have to be rewritten around
it rather than extended.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import numpy as np
import pandas as pd

from wimsim.calibration import (
    CalibrationProfile,
    ConformalInterval,
    ControllerConfig,
    ControllerEvent,
    EstimatorState,
    RecalibrationController,
    ReferenceObservation,
    build_detector,
    build_estimator,
    estimator_from_state,
)
from wimsim.core.config import EdgeConfig, RunConfig
from wimsim.core.schemas import MeasurementEvent
from wimsim.edge.pipeline import OfflinePipeline
from wimsim.experiments.offline import _bootstrap_profile, _feature_of, _provenance_for
from wimsim.experiments.scoring import ScoreResult, score_events
from wimsim.observability.estimator import estimate_metrics
from wimsim.observability.metrics import Metrics, NullSink
from wimsim.source import SyntheticSource

__all__ = ["ClosedLoopResult", "run_closed_loop"]


@dataclass
class ClosedLoopResult:
    run_config: RunConfig
    edge_config: EdgeConfig
    events: list[MeasurementEvent] = field(default_factory=list)
    score: ScoreResult | None = None
    controller_events: list[ControllerEvent] = field(default_factory=list)
    profiles: list[CalibrationProfile] = field(default_factory=list)
    state_timeline: list[tuple[int, str]] = field(default_factory=list)
    n_references: int = 0
    n_detected: int = 0
    detectors_ready_after_references: int | None = None
    """How many reference observations it took before any detector could raise an alarm.

    Reported because a run in which the fault arrived before this number is not a test of the
    detector at all -- it is a test of whether the detector can learn a post-fault level as normal,
    which it can. Time to readiness is ``drift.warmup * control.reference_every_n`` passes."""
    stats: dict[str, Any] = field(default_factory=dict)

    @property
    def recalibrations(self) -> int:
        return sum(1 for e in self.controller_events if e.kind == "recalibrated")

    @property
    def alarms(self) -> int:
        return sum(1 for e in self.controller_events if e.kind == "drift_detected")

    @property
    def degradations(self) -> int:
        return sum(1 for e in self.controller_events if e.kind == "degraded")

    def to_dict(self) -> dict[str, Any]:
        return {
            "scenario": self.run_config.scenario.name,
            "station_id": self.run_config.station.station_id,
            "config_hash": self.run_config.config_hash(),
            "edge_config": self.edge_config.name,
            "edge_config_hash": self.edge_config.config_hash(),
            "estimator": self.edge_config.estimate.estimator,
            "control_enabled": self.edge_config.control.enabled,
            "detectors": list(self.edge_config.drift.detectors),
            "uncertainty": self.edge_config.uncertainty.method,
            "n_detected": self.n_detected,
            "n_references": self.n_references,
            "detectors_ready_after_references": self.detectors_ready_after_references,
            "alarms": self.alarms,
            "recalibrations": self.recalibrations,
            "degradations": self.degradations,
            "final_state": self.state_timeline[-1][1] if self.state_timeline else "MONITORING",
            "profiles": [p.profile_id for p in self.profiles],
            "stats": self.stats,
            "score": None if self.score is None else self.score.to_dict(),
        }


def _detectors_for(cfg: EdgeConfig) -> list:
    """Build the configured detectors, translating one config section into four constructors."""
    drift = cfg.drift
    options: dict[str, dict[str, Any]] = {
        "cusum": {"threshold": drift.cusum_threshold, "slack": drift.cusum_slack},
        "page_hinkley": {
            "threshold": drift.page_hinkley_threshold,
            "tolerance": drift.page_hinkley_tolerance,
        },
        "adwin": {"delta": drift.adwin_delta},
        "ks": {"window": drift.ks_window, "alpha": drift.ks_alpha},
    }
    return [build_detector(name, warmup=drift.warmup, **options[name]) for name in drift.detectors]


def _estimator_for(cfg: EdgeConfig):
    """A fresh estimator with the tuning its config section carries."""
    est = cfg.estimate
    shared = {"coverage_target": est.coverage_target}
    if est.estimator == "rls":
        return build_estimator("rls", forgetting=est.forgetting, **shared)
    if est.estimator == "kalman":
        return build_estimator(
            "kalman",
            measurement_noise=est.measurement_noise,
            process_noise_bias=est.process_noise_bias,
            process_noise_gain=est.process_noise_gain,
            **shared,
        )
    return build_estimator(est.estimator, **shared)


class _TruthReferences:
    """Reference masses, looked up by time. The only thing in this file that reads the truth log.

    Isolated into a class of its own so the boundary is a single, greppable object rather than a
    call scattered through the loop. What leaves it is a ``ReferenceObservation`` -- a mass and a
    feature -- which is exactly what a weighbridge would supply.
    """

    def __init__(self, truth: pd.DataFrame, *, tolerance_s: float) -> None:
        self._peaks = truth["t_peak_s"].to_numpy()
        self._masses = truth["true_mass_kg"].to_numpy()
        self._epoch_us = float(truth["ts_peak_us"].iloc[0]) - float(truth["t_peak_s"].iloc[0]) * 1e6
        self._tolerance_s = float(tolerance_s)

    def mass_at(self, ts_peak_us: int) -> float | None:
        """The reference mass for a crossing at that instant, or None if nothing matches."""
        if self._peaks.size == 0:
            return None
        t_peak_s = (int(ts_peak_us) - self._epoch_us) / 1e6
        i = int(np.abs(self._peaks - t_peak_s).argmin())
        if abs(float(self._peaks[i]) - t_peak_s) > self._tolerance_s:
            return None
        return float(self._masses[i])


def run_closed_loop(
    cfg: RunConfig,
    truth: pd.DataFrame,
    edge_cfg: EdgeConfig,
    *,
    metrics: Metrics | None = None,
    calibration_passes: int | None = None,
    match_tolerance_s: float = 0.25,
    profile_store: Any = None,
) -> ClosedLoopResult:
    """Run the scenario with the controller in the loop and score what comes out."""
    metrics = metrics or Metrics(NullSink())
    n_cal = calibration_passes or edge_cfg.estimate.bootstrap_passes

    source = SyntheticSource(cfg)
    pipeline = OfflinePipeline(
        edge_cfg,
        source=source,
        profile=_bootstrap_profile(edge_cfg),
        provenance=_provenance_for(cfg),
        metrics=metrics,
    )
    detected = list(pipeline.detect_only())
    if len(detected) <= n_cal:
        raise ValueError(
            f"{len(detected)} events detected but {n_cal} are reserved for the initial "
            "calibration; there would be nothing left to control. Lengthen the run or lower "
            "bootstrap_passes."
        )

    references = _TruthReferences(truth, tolerance_s=match_tolerance_s)
    estimator = _estimator_for(edge_cfg)
    profile = _fit_initial(estimator, edge_cfg, detected[:n_cal], references)
    # The *same* instance, not one rebuilt from the state: every update() below has to reach the
    # events the pipeline emits, or the adaptive rungs of the ladder are silently inert.
    pipeline.set_profile(profile, estimator=estimator)

    result = ClosedLoopResult(
        run_config=cfg, edge_config=edge_cfg, n_detected=len(detected), profiles=[profile]
    )
    if profile_store is not None:
        profile_store.append(profile)

    conformal = _conformal_for(edge_cfg)
    controller = (
        _controller_for(edge_cfg, estimator, references) if edge_cfg.control.enabled else None
    )

    preprocessing = pipeline.preprocessor.describe()
    every = max(edge_cfg.control.reference_every_n, 1)

    for index, detection in enumerate(detected):
        interval = _conformal_interval(conformal, estimator, detection, edge_cfg)
        event = pipeline.estimate(detection, preprocessing, interval=interval)
        result.events.append(event)

        # A reference vehicle. In the field: a transponder, or a weighbridge up the road.
        if index % every:
            continue
        reference_mass = references.mass_at(detection.ts_peak_us)
        if reference_mass is None:
            continue
        result.n_references += 1

        observation = ReferenceObservation(
            ts_us=detection.ts_peak_us,
            feature=_feature_of(edge_cfg, detection),
            temp_c=detection.temp_c or 0.0,
            reference_mass_kg=reference_mass,
            axle_count=detection.axle_count,
            source=edge_cfg.control.reference_mode,
        )

        residual = event.mass_kg - reference_mass
        metrics.set("wim_cal_residual", residual)
        conformal.observe(reference_mass, event.mass_kg)

        # The estimator's own continuous adaptation. StaticAffine counts and changes nothing.
        estimator.update(observation)

        if controller is None:
            continue
        controller.offer_reference(observation)
        events = controller.observe(detection.ts_peak_us, residual)
        if result.detectors_ready_after_references is None and all(
            getattr(d, "ready", True) for d in controller.detectors
        ):
            result.detectors_ready_after_references = result.n_references
        _report_controller(metrics, controller)
        result.state_timeline.append((detection.ts_peak_us, controller.state))
        for controller_event in events:
            result.controller_events.append(controller_event)
            if controller_event.kind == "recalibrated":
                metrics.add("wim_recalibration_triggered_total", 1, reason="drift_confirmed")
            if controller_event.kind == "profile_activated" and controller_event.estimator_state:
                # The refit produced a fresh estimator inside the controller, so the loop's own
                # instance is replaced by one restored from that state -- and handed to the
                # pipeline, so continuous adaptation resumes from the new profile.
                estimator = estimator_from_state(controller_event.estimator_state)
                new_profile = _activate(
                    pipeline,
                    controller_event.estimator_state,
                    detection.ts_peak_us,
                    estimator,
                    ordinal=len(result.profiles),
                )
                result.profiles.append(new_profile)
                if profile_store is not None:
                    profile_store.append(new_profile)
                # The old residual quantiles describe an estimator that no longer exists.
                conformal.reset()

    held_out = truth[truth["t_entry_s"] > _cutoff_s(truth, detected, n_cal)].reset_index(drop=True)
    result.score = score_events(result.events[n_cal:], held_out, tolerance_s=match_tolerance_s)
    result.stats = pipeline.stats()
    if controller is not None:
        result.stats.update({f"controller_{k}": v for k, v in controller.to_dict().items()})
    return result


# ----------------------------------------------------------------------------------------------
# wiring helpers
# ----------------------------------------------------------------------------------------------


def _profile_id(ordinal: int, state: EstimatorState) -> str:
    """``p-<activation ordinal>-<state hash>``.

    The ordinal is what makes it unique: a recalibration can legitimately produce a state identical
    to an earlier one -- it means the reference buffer did not yet hold the post-fault evidence --
    and that activation is still a distinct record with its own timestamp and its own reason. The
    hash is kept in the id anyway because it makes "did the calibration actually change" answerable
    by eye, which is the question anyone reading a profile history asks first.
    """
    return f"p-{ordinal:03d}-{state.state_hash}"


def _fit_initial(estimator, edge_cfg, calibration_detections, references) -> CalibrationProfile:
    """The bootstrap calibration, from reference vehicles rather than from every pass."""
    observations = []
    for detection in calibration_detections:
        mass = references.mass_at(detection.ts_peak_us)
        if mass is None:
            continue  # a detection with no reference vehicle behind it teaches nothing
        observations.append(
            ReferenceObservation(
                ts_us=detection.ts_peak_us,
                feature=_feature_of(edge_cfg, detection),
                temp_c=detection.temp_c or 0.0,
                reference_mass_kg=mass,
                axle_count=detection.axle_count,
            )
        )
    if len(observations) < 2:
        raise ValueError(
            f"only {len(observations)} calibration observations could be matched to reference "
            "vehicles; a two-parameter fit needs at least two"
        )
    estimator.fit(observations)
    state = estimator.state()
    return CalibrationProfile.from_state(
        state,
        profile_id=_profile_id(0, state),
        activated_ts_us=observations[-1].ts_us,
        reason="bootstrap",
        provenance={"n_reference_observations": len(observations)},
    )


def _controller_for(edge_cfg: EdgeConfig, estimator, references) -> RecalibrationController:
    control = edge_cfg.control

    def recalibrate(observations: list[ReferenceObservation]) -> EstimatorState:
        """A wholesale refit from the buffered reference vehicles.

        A *fresh* estimator, not the running one. Refitting in place would leave an adaptive
        estimator's covariance describing evidence gathered before the fault, so it would resist
        exactly the correction it was just told to make.
        """
        fresh = _estimator_for(edge_cfg)
        fresh.fit(observations)
        return fresh.state()

    return RecalibrationController(
        ControllerConfig(
            confirmation_passes=control.confirmation_passes,
            confirm_sigma=control.confirm_sigma,
            min_reference_observations=control.min_reference_observations,
            cooldown_s=control.cooldown_s,
            verification_passes=control.verification_passes,
            max_references=control.max_references,
            arbitration=control.arbitration,
        ),
        detectors=_detectors_for(edge_cfg),
        recalibrate=recalibrate,
    )


def _conformal_for(edge_cfg: EdgeConfig) -> ConformalInterval:
    """Always built, even on the analytic arm.

    It costs a deque and it means the run reports what the conformal interval *would* have been,
    which is the paired comparison the buildspec asks for without needing a second run.
    """
    uq = edge_cfg.uncertainty
    return ConformalInterval(
        coverage_target=edge_cfg.estimate.coverage_target,
        score=uq.conformal_score,
        max_calibration=uq.max_calibration,
    )


def _conformal_interval(conformal, estimator, detection, edge_cfg):
    """The conformal band for this pass, or None to keep the estimator's analytic one."""
    if edge_cfg.uncertainty.method != "conformal" or not conformal.calibrated:
        return None
    # The band has to be centred on the mass this estimator is about to report, so the prediction
    # is made twice: once here for the interval and once inside the pipeline for the record. Both
    # are pure functions of the same state, so they agree exactly.
    predicted = estimator.predict(_feature_of(edge_cfg, detection), detection.temp_c or 0.0)
    return conformal.interval(predicted.mass_kg)


def _activate(
    pipeline: OfflinePipeline,
    state: EstimatorState,
    ts_us: int,
    estimator: Any = None,
    ordinal: int = 1,
) -> CalibrationProfile:
    """Put a recalibrated state into service.

    Unlike the continuous updates, this *is* a new profile: it has its own id, its own activation
    time and its own row in the store, because a wholesale refit is the law changing rather than
    the law being refined.
    """
    profile = CalibrationProfile.from_state(
        state,
        profile_id=_profile_id(ordinal, state),
        activated_ts_us=int(ts_us),
        reason="drift_confirmed",
    )
    pipeline.set_profile(profile, estimator=estimator)
    return profile


def _report_controller(metrics: Metrics, controller: RecalibrationController) -> None:
    for detector in controller.detectors:
        metrics.set("wim_drift_statistic", detector.statistic, detector=detector.name)
    for name, active in controller.state_one_hot().items():
        metrics.set("wim_cal_state", active, state=name)
    if controller.active_state is not None:
        estimate_metrics(metrics, controller.active_state)


def _cutoff_s(truth: pd.DataFrame, detected: list, n_cal: int) -> float:
    """Where the calibration split ends, in scenario seconds.

    By *time* rather than by index: index would be wrong whenever detection missed a pass, and the
    split is defined by when the calibration ended rather than by how many detections preceded it.
    """
    if n_cal == 0 or not detected:
        return float("-inf")
    epoch_us = float(truth["ts_peak_us"].iloc[0]) - float(truth["t_peak_s"].iloc[0]) * 1e6
    return (detected[n_cal - 1].ts_end_us - epoch_us) / 1e6
