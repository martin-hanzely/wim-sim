"""Scoring: the one layer allowed to join estimates with ground truth.

Everything downstream of ``SourceAdapter`` is quarantined from ``wimsim.signal``. This module is
not, and that is the design rather than an exception to it: truth enters the system exactly once, at
the point where results are computed, and never anywhere a decision is made. ``experiments/`` is
deliberately absent from the quarantine list in ``tests/test_truth_isolation.py``.

**Matching is where scoring goes wrong quietly.** A detector reporting every vehicle 40 ms late has
measured every vehicle; a matcher insisting on exact timestamps would report a total failure and
then compute a mean error over an empty set. So events are matched to passes by *interval overlap*
with a tolerance, one-to-one, closest-first -- and what fails to match is reported as a miss or a
false positive rather than dropped.

**Two error figures are reported, and the difference between them is the point.**

``mae_kg``
    Against ``true_mass_kg``: the static mass a weighbridge would report. This is the number the
    system is judged on.
``mae_vs_applied_kg``
    Against ``applied_mass_kg``: the load actually pressing on the sensor, including body bounce.
    This is the error the *pipeline* is responsible for.

The gap between them is irreducible. No calibration recovers a static mass from a single crossing of
a bouncing vehicle, so reporting only the first would blame the pipeline for physics, and reporting
only the second would flatter it.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol

import numpy as np
import pandas as pd

__all__ = ["ScoreResult", "match_events", "score_events"]


class _Scoreable(Protocol):
    """What scoring needs from an event. ``MeasurementEvent`` satisfies it structurally."""

    event_id: str
    ts_start: int
    ts_peak: int
    ts_end: int
    mass_kg: float
    mass_ci_low: float
    mass_ci_high: float
    interval_source: str


def _nan_mean(values: np.ndarray) -> float:
    return float(np.mean(values)) if values.size else float("nan")


@dataclass(frozen=True, slots=True)
class ScoreResult:
    """Everything phase 2 can honestly say about a run."""

    n_truth: int
    n_events: int
    n_matched: int
    n_missed: int
    n_false_positive: int

    mae_kg: float
    mape: float
    rmse_kg: float
    bias_kg: float
    """Signed mean error. MAE alone cannot tell a miscalibrated scale from a noisy one."""

    mae_vs_applied_kg: float
    dynamic_floor_kg: float
    """Mean |applied - static|: the error no calibration can remove."""

    coverage: float
    """Empirical fraction of intervals containing the truth. Buildspec section 6 calls this the
    single most persuasive number for a small-real-data paper, so it is computed from the start.

    Pooled over every interval in the run, which is only meaningful when they all came from the
    same construction. See :attr:`coverage_by_source`."""
    mean_interval_width_kg: float

    axle_count_accuracy: float

    coverage_by_source: dict[str, tuple[int, float]] = field(default_factory=dict)
    """``interval_source -> (n, coverage)``.

    A run can emit intervals from more than one construction, and pooling them describes none of
    them. Measured on ``S4_step_fault`` with Kalman at one reference in fifty: ``uncertainty.method``
    is ``conformal``, conformal needs 19 scored references before it can claim a 95 % quantile, and
    at that rate they take four hours to arrive. Until then every event silently carries the
    estimator's own analytic band -- which for the Kalman filter is the construction phase 5
    measured at coverage 0.0065 and chose conformal specifically to avoid. Coverage ran 0.004 for
    four hours and 0.914-1.000 for the remaining twelve; the headline 0.741 was the average of a
    broken quarter and a working three quarters."""

    n_interval_fallback: int = 0
    """Intervals that did NOT come from the configured construction. Zero unless the caller states
    what it configured -- scoring does not get to invent a preference."""
    n_interval_expected: int = 0
    coverage_expected: float | None = None
    """Coverage over the intervals the configuration actually asked for."""
    per_class: dict[str, dict[str, float]] = field(default_factory=dict)

    @property
    def recall(self) -> float:
        return self.n_matched / self.n_truth if self.n_truth else float("nan")

    @property
    def false_positive_rate(self) -> float:
        return self.n_false_positive / self.n_events if self.n_events else 0.0

    def to_dict(self) -> dict[str, Any]:
        return {
            "n_truth": self.n_truth,
            "n_events": self.n_events,
            "n_matched": self.n_matched,
            "n_missed": self.n_missed,
            "n_false_positive": self.n_false_positive,
            "recall": self.recall,
            "false_positive_rate": self.false_positive_rate,
            "mae_kg": self.mae_kg,
            "mape": self.mape,
            "rmse_kg": self.rmse_kg,
            "bias_kg": self.bias_kg,
            "mae_vs_applied_kg": self.mae_vs_applied_kg,
            "dynamic_floor_kg": self.dynamic_floor_kg,
            "coverage": self.coverage,
            "mean_interval_width_kg": self.mean_interval_width_kg,
            "coverage_by_source": {k: list(v) for k, v in self.coverage_by_source.items()},
            "n_interval_fallback": self.n_interval_fallback,
            "n_interval_expected": self.n_interval_expected,
            "coverage_expected": self.coverage_expected,
            "axle_count_accuracy": self.axle_count_accuracy,
            "per_class": self.per_class,
        }


def match_events(
    events: list[_Scoreable],
    truth: pd.DataFrame,
    *,
    tolerance_s: float = 0.25,
) -> tuple[pd.DataFrame, pd.DataFrame, list[str]]:
    """One-to-one match of events to truth passes.

    Returns ``(matched, missed, spurious_event_ids)``. A pair is a candidate when the event's window
    overlaps the pass's window widened by ``tolerance_s``; among the candidates, the closest by peak
    time wins, and each side may be used once. Greedy closest-first is chosen over an optimal
    assignment deliberately: it is what a human would do reading a chart, and with vehicles spaced
    seconds apart the two agree.
    """
    if not events:
        return pd.DataFrame(), truth.copy(), []

    tol_us = tolerance_s * 1e6
    truth_start = truth["t_entry_s"].to_numpy() * 1e6 - tol_us
    truth_end = truth["t_exit_s"].to_numpy() * 1e6 + tol_us
    truth_peak = truth["ts_peak_us"].to_numpy().astype(np.float64)
    # ts_peak_us is absolute; t_entry_s is relative. Rebase truth onto the absolute axis.
    epoch = truth_peak - truth["t_peak_s"].to_numpy() * 1e6
    truth_start += epoch
    truth_end += epoch

    candidates: list[tuple[float, int, int]] = []
    for ei, ev in enumerate(events):
        overlaps = (ev.ts_end >= truth_start) & (ev.ts_start <= truth_end)
        for ti in np.flatnonzero(overlaps).tolist():
            candidates.append((abs(ev.ts_peak - truth_peak[ti]), ei, ti))
    candidates.sort()

    used_events: set[int] = set()
    used_truth: set[int] = set()
    pairs: list[tuple[int, int, float]] = []
    for dt, ei, ti in candidates:
        if ei in used_events or ti in used_truth:
            continue
        used_events.add(ei)
        used_truth.add(ti)
        pairs.append((ei, ti, dt / 1e6))

    if pairs:
        pairs.sort(key=lambda p: p[1])
        rows = []
        for ei, ti, dt_s in pairs:
            ev = events[ei]
            row = truth.iloc[ti].to_dict()
            row.update(
                {
                    "event_id": ev.event_id,
                    "mass_kg": float(ev.mass_kg),
                    "mass_ci_low": float(ev.mass_ci_low),
                    "mass_ci_high": float(ev.mass_ci_high),
                    "interval_source": getattr(ev, "interval_source", None) or "unknown",
                    "event_axle_count": getattr(ev, "axle_count", None),
                    "quality_flag": getattr(ev, "quality_flag", "ok"),
                    "match_dt_s": dt_s,
                }
            )
            rows.append(row)
        matched = pd.DataFrame(rows)
    else:
        matched = pd.DataFrame()

    missed = truth.drop(index=truth.index[sorted(used_truth)]) if used_truth else truth.copy()
    spurious = [ev.event_id for i, ev in enumerate(events) if i not in used_events]
    return matched, missed, spurious


def score_events(
    events: list[_Scoreable],
    truth: pd.DataFrame,
    *,
    tolerance_s: float = 0.25,
    expected_interval_source: str | None = None,
) -> ScoreResult:
    """Match, then measure. Undefined statistics come back as NaN, never as zero.

    ``expected_interval_source`` is the construction the pipeline was *configured* to use, as a
    prefix -- ``"conformal"`` matches ``conformal_relative`` and ``conformal_absolute``. Given it,
    the result separates the intervals that came from it from the ones that did not, because a
    fallback band and a configured band are different instruments and averaging their coverage
    describes neither. Omitted, nothing is called a fallback: scoring does not get to invent a
    preference the configuration never expressed.
    """
    matched, missed, spurious = match_events(events, truth, tolerance_s=tolerance_s)

    if matched.empty:
        nan = float("nan")
        return ScoreResult(
            n_truth=len(truth),
            n_events=len(events),
            n_matched=0,
            n_missed=len(missed),
            n_false_positive=len(spurious),
            mae_kg=nan,
            mape=nan,
            rmse_kg=nan,
            bias_kg=nan,
            mae_vs_applied_kg=nan,
            dynamic_floor_kg=nan,
            coverage=nan,
            mean_interval_width_kg=nan,
            axle_count_accuracy=nan,
        )

    est = matched["mass_kg"].to_numpy()
    static = matched["true_mass_kg"].to_numpy()
    applied = matched.get("applied_mass_kg", matched["true_mass_kg"]).to_numpy()
    error = est - static

    covered = (matched["mass_ci_low"].to_numpy() <= static) & (
        static <= matched["mass_ci_high"].to_numpy()
    )
    sources = matched.get(
        "interval_source", pd.Series(["unknown"] * len(matched), index=matched.index)
    ).to_numpy()
    by_source = {
        str(name): (int((sources == name).sum()), float(covered[sources == name].mean()))
        for name in dict.fromkeys(sources)
    }
    if expected_interval_source is None:
        n_fallback, n_expected, coverage_expected = 0, 0, None
    else:
        wanted = np.array([str(x).startswith(expected_interval_source) for x in sources])
        n_expected = int(wanted.sum())
        n_fallback = int((~wanted).sum())
        coverage_expected = float(covered[wanted].mean()) if n_expected else None
    widths = matched["mass_ci_high"].to_numpy() - matched["mass_ci_low"].to_numpy()

    axle_truth = matched.get("axle_count")
    axle_est = matched.get("event_axle_count")
    if axle_truth is None or axle_est is None or axle_est.isna().all():
        axle_accuracy = float("nan")
    else:
        axle_accuracy = float(np.mean(axle_truth.to_numpy() == axle_est.to_numpy()))

    per_class: dict[str, dict[str, float]] = {}
    if "vehicle_class" in matched:
        for name, group in matched.groupby("vehicle_class"):
            err = group["mass_kg"].to_numpy() - group["true_mass_kg"].to_numpy()
            per_class[str(name)] = {
                "n": int(len(group)),
                "mae_kg": float(np.mean(np.abs(err))),
                "bias_kg": float(np.mean(err)),
                "mape": float(np.mean(np.abs(err) / group["true_mass_kg"].to_numpy())),
            }

    return ScoreResult(
        n_truth=len(truth),
        n_events=len(events),
        n_matched=len(matched),
        n_missed=len(missed),
        n_false_positive=len(spurious),
        mae_kg=float(np.mean(np.abs(error))),
        mape=float(np.mean(np.abs(error) / static)),
        rmse_kg=float(np.sqrt(np.mean(error**2))),
        bias_kg=float(np.mean(error)),
        mae_vs_applied_kg=float(np.mean(np.abs(est - applied))),
        dynamic_floor_kg=_nan_mean(np.abs(applied - static)),
        coverage=float(np.mean(covered)),
        mean_interval_width_kg=float(np.mean(widths)),
        coverage_by_source=by_source,
        n_interval_fallback=n_fallback,
        n_interval_expected=n_expected,
        coverage_expected=coverage_expected,
        axle_count_accuracy=axle_accuracy,
        per_class=per_class,
    )
