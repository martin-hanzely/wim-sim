"""Name to estimator, in one place.

A stored profile names its estimator as a string -- ``"static_affine"``, ``"rls"``, ``"kalman"`` --
because a profile has to be readable by something that is not this program. That makes this mapping
load-bearing: a profile naming an estimator nothing can build is a mass nobody can ever reproduce,
which defeats the point of storing the profile at all.

Kept separate from ``__init__`` so that ``edge/pipeline.py`` and ``experiments/recompute.py`` share
one table rather than each keeping a private one that drifts.
"""

from __future__ import annotations

from typing import Any

from wimsim.calibration.base import EstimatorState
from wimsim.calibration.kalman import KalmanCalibration
from wimsim.calibration.rls import RecursiveLeastSquares
from wimsim.calibration.static_affine import StaticAffine

__all__ = ["ESTIMATORS", "build_estimator", "estimator_from_state"]

#: Every estimator buildspec section 6 asks for, keyed by the name it reports in its own state.
#: ``ResidualLearner`` is phase 6 and behind a feature flag, so it is deliberately absent.
ESTIMATORS: dict[str, type] = {
    StaticAffine.estimator_name: StaticAffine,
    RecursiveLeastSquares.estimator_name: RecursiveLeastSquares,
    KalmanCalibration.estimator_name: KalmanCalibration,
}


def build_estimator(name: str, **kwargs: Any):
    """A fresh estimator by name."""
    try:
        cls = ESTIMATORS[name]
    except KeyError:
        raise KeyError(
            f"unknown estimator {name!r}; the registry holds {sorted(ESTIMATORS)}. Phase 6 adds "
            "residual_learner behind a feature flag."
        ) from None
    return cls(**kwargs)


def estimator_from_state(state: EstimatorState):
    """Rebuild the estimator a state came from, parameters and covariance included.

    This is what makes a stored profile more than a record: an event can be re-derived under it,
    which is what ``recompute --from <ts> --profile <id>`` does.
    """
    try:
        cls = ESTIMATORS[state.estimator]
    except KeyError:
        raise KeyError(
            f"the profile names estimator {state.estimator!r}, which this build cannot construct; "
            f"the registry holds {sorted(ESTIMATORS)}. An event emitted under it cannot be "
            "reproduced by this version of the code."
        ) from None
    return cls.from_state(state)
