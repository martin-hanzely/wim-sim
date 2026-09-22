"""Calibration: estimators, and later drift detection, the MAPE-K controller, UQ and the profile
store.

**Two import rules hold over this package, and both are enforced by tests rather than convention.**

1. It may not reach ``wimsim.signal``, directly or transitively. The estimator must be structurally
   incapable of reading ground truth (principle 1) -- see ``tests/test_truth_isolation.py``.
2. It may import nothing but the standard library, numpy and ``wimsim.core``. No pydantic, no MQTT,
   no database, no logging framework, so the estimator core cross-deploys to a Raspberry Pi or
   Jetson unchanged (principle 6) -- see ``tests/test_architecture.py``.

Phase 2 ships the baseline. ``RecursiveLeastSquares``, ``KalmanCalibration`` and the optional
``ResidualLearner`` arrive in phase 5, behind the same interface.
"""

from wimsim.calibration.affine_temp import AffineTemp
from wimsim.calibration.base import (
    CalibrationEstimator,
    CalibrationProfile,
    EstimatorState,
    MassEstimate,
    ReferenceObservation,
)
from wimsim.calibration.channel_ratio import ChannelRatioMonitor
from wimsim.calibration.conformal import ConformalInterval
from wimsim.calibration.controller import (
    ARBITRATION_MODES,
    ControllerConfig,
    ControllerEvent,
    RecalibrationController,
)
from wimsim.calibration.drift import (
    ADWIN,
    CUSUM,
    DETECTORS,
    DriftDetector,
    KSWindow,
    PageHinkley,
    build_detector,
)
from wimsim.calibration.kalman import KalmanCalibration
from wimsim.calibration.registry import (
    ESTIMATORS,
    build_estimator,
    estimator_from_state,
)
from wimsim.calibration.rls import RecursiveLeastSquares
from wimsim.calibration.static_affine import StaticAffine
from wimsim.calibration.store import ProfileStore

__all__ = [
    "ADWIN",
    "ARBITRATION_MODES",
    "CUSUM",
    "DETECTORS",
    "ESTIMATORS",
    "AffineTemp",
    "CalibrationEstimator",
    "CalibrationProfile",
    "ChannelRatioMonitor",
    "ConformalInterval",
    "ControllerConfig",
    "ControllerEvent",
    "DriftDetector",
    "EstimatorState",
    "KSWindow",
    "KalmanCalibration",
    "MassEstimate",
    "PageHinkley",
    "ProfileStore",
    "RecalibrationController",
    "RecursiveLeastSquares",
    "ReferenceObservation",
    "StaticAffine",
    "build_detector",
    "build_estimator",
    "estimator_from_state",
]
