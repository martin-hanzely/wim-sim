"""Re-deriving stored events under a different calibration profile.

Buildspec section 6: "Historical events must be recomputable under a different profile -- implement
``recompute --from <ts> --profile <id>`` and prove it in a test." This is the function behind that
command; ``cli.py`` supplies the rows and writes the result back.

It works because of three earlier decisions, none of which looked like they were for this:

* **``event_id`` is a UUIDv5 of station, sensor and ``ts_start`` and of nothing else** -- not the
  mass, not the profile. A recomputed event therefore carries the same id, and the phase-3 upsert
  updates the row in place instead of inserting a second opinion about the same vehicle.
* **``raw_peak`` is stored before thermal compensation.** ``compensated_peak`` was divided by
  ``1 + alpha*(T - T_ref)`` using the *old* profile's coefficient, so recomputing from it would
  leave the old correction in place and put the new estimator on top of it -- an error that is
  small, systematic and very hard to find. Starting from ``raw_peak`` and redoing the division is
  exact.
* **``temperature_c`` is stored per event**, which it was not until phase 4 noticed the column was
  always null. Without it the compensation could not be redone at all, and recompute would have
  been quietly exact only for profiles that happen to share a temperature coefficient.

Two rules about refusing rather than guessing. A profile whose estimator this build cannot
construct, or which is not fitted, is refused *before any row is touched* -- half a recompute leaves
a window holding masses from two different laws with no way to tell which is which. And a row with
no ``raw_peak`` is skipped and counted rather than recomputed from the compensated value, because
the alternative is a number that is exact for some profiles and wrong for others with nothing to
distinguish them.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from typing import Any

from wimsim.calibration import CalibrationProfile, estimator_from_state

__all__ = ["RecomputeResult", "recompute_rows"]


@dataclass(frozen=True, slots=True)
class RecomputeResult:
    """What a recompute did, in enough detail to be reported rather than assumed."""

    rows: list[dict[str, Any]] = field(default_factory=list)
    n_recomputed: int = 0
    n_skipped: int = 0
    n_without_temperature: int = 0
    n_outside_window: int = 0
    profile_id: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "profile_id": self.profile_id,
            "n_recomputed": self.n_recomputed,
            "n_skipped": self.n_skipped,
            "n_without_temperature": self.n_without_temperature,
            "n_outside_window": self.n_outside_window,
        }


def _thermal_factor(temperature_c: float | None, temp_coeff: float, t_ref_c: float) -> float:
    """``1 + alpha*(T - T_ref)``, the same expression the preprocessor applies.

    Duplicated deliberately rather than imported: ``edge/preprocess.py`` works on numpy arrays of a
    live block and this works on one stored row, and coupling the two would make a scalar recompute
    depend on the shape of the streaming path. ``tests/test_recompute.py`` pins the arithmetic, and
    the identity test -- recomputing under the profile that produced a row reproduces it to 1e-12 --
    is what would catch the two drifting apart.
    """
    if temp_coeff == 0.0 or temperature_c is None:
        return 1.0
    factor = 1.0 + temp_coeff * (float(temperature_c) - t_ref_c)
    # A factor at or below zero would invert the signal. The preprocessor refuses it the same way.
    return factor if factor > 1e-6 else 1.0


def recompute_rows(
    rows: Iterable[dict[str, Any]],
    profile: CalibrationProfile,
    *,
    from_ts_us: int | None = None,
) -> RecomputeResult:
    """Re-derive the mass and interval of each row under ``profile``.

    ``from_ts_us`` bounds the window by ``ts_start``, inclusive. Rows before it are left alone.
    """
    state = profile.state
    if not state.fitted:
        raise ValueError(
            f"profile {profile.profile_id!r} is not fitted, so it cannot predict a mass. "
            "Refusing before touching any row: a partial recompute leaves the window holding "
            "masses from two different laws with no way to tell them apart."
        )
    estimator = estimator_from_state(state)  # raises for an estimator this build cannot construct

    recomputed: list[dict[str, Any]] = []
    skipped = 0
    without_temperature = 0
    outside = 0

    for row in rows:
        if from_ts_us is not None and int(row["ts_start"]) < int(from_ts_us):
            outside += 1
            continue

        raw_peak = row.get("raw_peak")
        if raw_peak is None:
            skipped += 1
            continue

        temperature = row.get("temperature_c")
        if temperature is None:
            without_temperature += 1

        factor = _thermal_factor(temperature, state.temp_coeff, state.t_ref_c)
        compensated = float(raw_peak) / factor
        estimate = estimator.predict(compensated, float(temperature or state.t_ref_c))

        recomputed.append(
            {
                **row,
                "compensated_peak": compensated,
                "mass_kg": estimate.mass_kg,
                "mass_ci_low": estimate.mass_ci_low,
                "mass_ci_high": estimate.mass_ci_high,
                "coverage_target": estimate.coverage_target,
                "profile_id": profile.profile_id,
                "estimator": state.estimator,
                "cal_gain": state.sensor_gain,
                "cal_bias": state.sensor_bias,
                "cal_temp_coeff": state.temp_coeff,
                "cal_state_hash": state.state_hash,
                "cal_update_count": state.update_count,
                "cal_covariance_trace": state.covariance_trace,
            }
        )

    return RecomputeResult(
        rows=recomputed,
        n_recomputed=len(recomputed),
        n_skipped=skipped,
        n_without_temperature=without_temperature,
        n_outside_window=outside,
        profile_id=profile.profile_id,
    )


def recompute_columns() -> Sequence[str]:
    """The columns a recompute rewrites. Everything else on the row is carried through untouched."""
    return (
        "compensated_peak",
        "mass_kg",
        "mass_ci_low",
        "mass_ci_high",
        "coverage_target",
        "profile_id",
        "estimator",
        "cal_gain",
        "cal_bias",
        "cal_temp_coeff",
        "cal_state_hash",
        "cal_update_count",
        "cal_covariance_trace",
    )
