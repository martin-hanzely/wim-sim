"""The calibration interface, and the types that cross it.

**Dependency-light on purpose.** Nothing in this package imports anything but the standard library,
numpy and ``wimsim.core`` -- no pydantic, no MQTT, no database, no logging framework. Principle 6
says the estimator core must cross-deploy to a Raspberry Pi or Jetson unchanged, and
``tests/test_architecture.py`` fails the build if that stops being true. Conversion to transport
models happens at the edge, in one direction only: the pipeline builds a payload *from* an
:class:`EstimatorState`, never the reverse.

Two parameter conventions exist and both are needed, so both are exposed rather than one being
silently implied:

``gain`` / ``bias``
    The **prediction direction**: ``mass_kg = gain * feature + bias``, kg per sensor unit and kg.
    This is what the estimator fits, because prediction error in kilograms is what gets scored.

``sensor_gain`` / ``sensor_bias``
    The **sensor side**: ``feature = sensor_bias + sensor_gain * mass``, sensor units per kg and
    sensor units. This is the convention the truth log uses.

They are exact algebraic inverses of each other, so no information is duplicated. Note that they
are *not* what you would get by running least squares in the other direction: regressing mass on
feature and regressing feature on mass give different answers whenever the feature carries noise
(regression dilution). Fitting in the prediction direction is the deliberate choice, since that is
the error the experiment reports.

**Only the gain is comparable with the truth log.** ``sensor_gain`` sits on top of ``k_true`` --
measured at 2.0002e-4 against a true 2.0e-4 on the phase-4 demo run, which is what makes the
calibration dashboard's headline overlay meaningful. ``sensor_bias`` is *not* comparable with
``q_true``, because the preprocessor's zero-line tracker has already removed the plant's zero line
before the feature is taken; what the estimator fits is the small residual offset the tracker left
behind (order 1e-4 against a ``q_true`` of 0.05). Drawing them on one axis would show a flat line
and a near-zero line and read as a badly wrong estimator when it is in fact a correct one, so the
dashboard keeps them apart and says why.
"""

from __future__ import annotations

import hashlib
import json
import math
from dataclasses import dataclass, field
from typing import Any, Protocol, runtime_checkable

__all__ = [
    "CalibrationEstimator",
    "CalibrationProfile",
    "EstimatorState",
    "MassEstimate",
    "ReferenceObservation",
]


@dataclass(frozen=True, slots=True)
class ReferenceObservation:
    """A pass whose true mass is known well enough to calibrate against.

    In ``supervised`` mode this is a known reference vehicle. In ``population`` mode (phase 5) it is
    a statistic of a rolling axle-load distribution dressed in the same shape, so that both modes
    drive the same ``update`` path.

    ``reference_mass_kg`` is *not* ground truth. It carries its own uncertainty -- a static
    weighbridge is not perfect and the vehicle may have changed load between measurements -- which
    is why ``sigma_kg`` exists and why the scoring layer reports accuracy relative to a reference
    rather than absolutely.
    """

    ts_us: int
    feature: float
    """The preprocessed quantity the estimator consumes: compensated peak, or area, per config."""
    temp_c: float
    reference_mass_kg: float
    sigma_kg: float | None = None
    """Standard uncertainty of the reference, kg. None means unweighted."""
    speed_mps: float | None = None
    axle_count: int | None = None
    source: str = "supervised"


@dataclass(frozen=True, slots=True)
class MassEstimate:
    """A mass with an interval. The interval is part of the answer, not an ornament."""

    mass_kg: float
    mass_ci_low: float
    mass_ci_high: float
    coverage_target: float = 0.95
    interval_source: str = "residual_sd"
    """How the interval was derived: residual_sd, kalman_analytic, conformal. Recorded because
    phase 5 compares them and a number whose provenance is unknown cannot be compared."""

    def __post_init__(self) -> None:
        if not (self.mass_ci_low <= self.mass_kg <= self.mass_ci_high):
            raise ValueError(
                f"interval must bracket the estimate: {self.mass_ci_low} / {self.mass_kg} / "
                f"{self.mass_ci_high}"
            )

    @property
    def width(self) -> float:
        return self.mass_ci_high - self.mass_ci_low


@dataclass(frozen=True, slots=True)
class EstimatorState:
    """Serialisable, hashable snapshot of what an estimator computes.

    ``state_hash`` covers the parameters only -- not ``update_count``, not timestamps. Two
    estimators that would predict identically hash identically, which is what makes the hash usable
    as "did the calibration actually change" on a dashboard and in the profile store.
    """

    estimator: str
    gain: float
    bias: float
    temp_coeff: float = 0.0
    t_ref_c: float = 20.0
    residual_sd: float | None = None
    coverage_target: float = 0.95
    update_count: int = 0
    fitted: bool = False
    n_fit: int = 0
    covariance: tuple[tuple[float, ...], ...] | None = None
    """State covariance, row-major, for estimators that carry one (phase 5). None otherwise --
    not zero, because "no covariance" and "zero covariance" mean very different things."""
    extra: dict[str, Any] = field(default_factory=dict)

    # -- derived, sensor-side view ---------------------------------------------------------

    @property
    def sensor_gain(self) -> float:
        """Sensor units per kg. Directly comparable with ``k_true`` in the truth log."""
        if self.gain == 0.0:
            return math.inf
        return 1.0 / self.gain

    @property
    def sensor_bias(self) -> float:
        """Sensor units. *Not* directly comparable with ``q_true``: the preprocessor's zero-line
        tracker removes the plant's zero line before the feature is taken, so this is the residual
        the tracker left behind, not q. See the module docstring."""
        if self.gain == 0.0:
            return math.nan
        return -self.bias / self.gain

    @property
    def covariance_trace(self) -> float | None:
        if self.covariance is None:
            return None
        return float(sum(self.covariance[i][i] for i in range(len(self.covariance))))

    # -- serialisation ----------------------------------------------------------------------

    def _hashable_params(self) -> dict[str, Any]:
        return {
            "estimator": self.estimator,
            "gain": self.gain,
            "bias": self.bias,
            "temp_coeff": self.temp_coeff,
            "t_ref_c": self.t_ref_c,
            "fitted": self.fitted,
        }

    @property
    def state_hash(self) -> str:
        blob = json.dumps(self._hashable_params(), sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(blob.encode("utf-8")).hexdigest()[:16]

    def to_dict(self) -> dict[str, Any]:
        return {
            "estimator": self.estimator,
            "gain": float(self.gain),
            "bias": float(self.bias),
            "temp_coeff": float(self.temp_coeff),
            "t_ref_c": float(self.t_ref_c),
            "residual_sd": None if self.residual_sd is None else float(self.residual_sd),
            "coverage_target": float(self.coverage_target),
            "update_count": int(self.update_count),
            "fitted": bool(self.fitted),
            "n_fit": int(self.n_fit),
            "covariance": (
                None
                if self.covariance is None
                else [[float(v) for v in row] for row in self.covariance]
            ),
            "extra": dict(self.extra),
        }

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> EstimatorState:
        cov = payload.get("covariance")
        return cls(
            estimator=payload["estimator"],
            gain=float(payload["gain"]),
            bias=float(payload["bias"]),
            temp_coeff=float(payload.get("temp_coeff", 0.0)),
            t_ref_c=float(payload.get("t_ref_c", 20.0)),
            residual_sd=(
                None if payload.get("residual_sd") is None else float(payload["residual_sd"])
            ),
            coverage_target=float(payload.get("coverage_target", 0.95)),
            update_count=int(payload.get("update_count", 0)),
            fitted=bool(payload.get("fitted", False)),
            n_fit=int(payload.get("n_fit", 0)),
            covariance=(
                None if cov is None else tuple(tuple(float(v) for v in row) for row in cov)
            ),
            extra=dict(payload.get("extra", {})),
        )


@dataclass(frozen=True, slots=True)
class CalibrationProfile:
    """A named, versioned, activated estimator state.

    Append-only by construction: ``superseded_by`` is set when a newer profile replaces this one,
    and nothing is ever edited in place. The full store, with ``recompute --from <ts>
    --profile <id>``, is phase 5; what exists here is the record an emitted event points at, so
    that every mass can name the calibration that produced it.
    """

    profile_id: str
    state: EstimatorState
    activated_ts_us: int
    superseded_by: str | None = None
    reason: str = "bootstrap"
    provenance: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_state(
        cls,
        state: EstimatorState,
        *,
        profile_id: str,
        activated_ts_us: int,
        reason: str = "bootstrap",
        provenance: dict[str, Any] | None = None,
    ) -> CalibrationProfile:
        return cls(
            profile_id=profile_id,
            state=state,
            activated_ts_us=int(activated_ts_us),
            reason=reason,
            provenance=dict(provenance or {}),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "profile_id": self.profile_id,
            "state": self.state.to_dict(),
            "activated_ts_us": self.activated_ts_us,
            "superseded_by": self.superseded_by,
            "reason": self.reason,
            "provenance": dict(self.provenance),
        }

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> CalibrationProfile:
        return cls(
            profile_id=payload["profile_id"],
            state=EstimatorState.from_dict(payload["state"]),
            activated_ts_us=int(payload["activated_ts_us"]),
            superseded_by=payload.get("superseded_by"),
            reason=payload.get("reason", "bootstrap"),
            provenance=dict(payload.get("provenance", {})),
        )


@runtime_checkable
class CalibrationEstimator(Protocol):
    """The common interface, exactly as the buildspec specifies it."""

    def predict(self, x_comp: float, temp_c: float) -> MassEstimate: ...

    def update(self, observation: ReferenceObservation) -> EstimatorState: ...

    def state(self) -> EstimatorState: ...
