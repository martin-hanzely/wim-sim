"""Figures for a sweep, written beside the parquet they describe.

Buildspec section 10: "a LaTeX/Markdown comparison table and matplotlib figures written straight to
``data/results/<id>/figures/``".

Four figures, because the sweep is asked four different questions and no one plot answers more than
one of them:

``accuracy``
    MAE as a multiple of the dynamic floor. Not MAE in kilograms -- the floor spans two orders of
    magnitude across the scenario set, so a bare axis compares scenarios rather than estimators,
    and an estimator sitting two per cent above a large floor would look worse than one sitting
    three times above a small one.
``coverage``
    Empirical coverage against the nominal target, which is drawn. 0.91 is a good number or a bad
    one depending entirely on what was promised.
``reconvergence``
    Seconds from an injected fault until the error came back and stayed back. The headline control
    metric, and the one scenarios without faults are kept out of: a zero bar there would read as
    "reconverged instantly" rather than "the question was never asked".
``detectors``
    Recall against false alarms per hour. Either alone can be made perfect by a detector that is
    useless in the other direction, so they belong on one pair of axes.

Three rules the figures follow, all of which exist to stop a plot flattering the system:

**Seeds are drawn, not averaged.** Three seeds exist to give a number an error bar. A plot that
means over them has thrown away the only thing separating a result from an anecdote.

**Failed runs are counted where a reader will see it.** A bar absent because a run crashed looks
exactly like a bar absent because the value was zero, so the count goes in the title and in the
captions file.

**The same frame draws the same bytes.** Principle 4 applies to figures too: one that changes
between renders cannot be diffed, and a reviewer cannot tell a re-render from a new result.

Grafana remains the UI (buildspec section 13). These exist so a results directory is one thing that
can be handed to somebody, not to become a dashboard.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from matplotlib.ticker import FuncFormatter

__all__ = [
    "FIGURES",
    "RecalPoint",
    "Reconvergence",
    "accuracy_ratios",
    "coverage_rows",
    "detector_curves",
    "detector_points",
    "governance_rate_points",
    "rate_curves",
    "recal_points",
    "recall_rate_points",
    "reconvergence_rows",
    "write_figures",
]

#: Figure stem -> caption. The caption is written to ``figures/README.md`` rather than living only
#: in the code that drew it, because a figure separated from its caption is a shape.
FIGURES: dict[str, str] = {
    "accuracy": (
        "MAE as a multiple of the dynamic floor, on a log axis -- the load error the vehicles "
        "brought with them, "
        "which no calibration can remove. 1.0 is the floor; below it would be a coincidence rather "
        "than a result. Scenarios with no dynamic load have no floor to divide by and are absent. "
        "One marker per seed."
    ),
    "coverage": (
        "Empirical coverage of the prediction interval against its nominal target, drawn as the "
        "dashed line. Above the line is conservative, below it is an interval that promises more "
        "than it delivers. One marker per seed."
    ),
    "reconvergence": (
        "Seconds from the first injected fault until the error returned to its pre-fault level and "
        "stayed there. Scenarios with no faults are absent rather than drawn at zero. Runs that "
        "never reconverged are counted in the label rather than dropped, because dropping them "
        "makes a system that never recovers look identical to one that was not measured."
    ),
    "reference_rate": (
        "MAE as a multiple of the dynamic floor against how often a reference vehicle arrives, "
        "with the control loop on (solid) and off (dashed) over the identical stream. The gap "
        "between a pair of lines is what the loop is worth at that rate; where they meet, it is "
        "worth nothing and the estimator is doing the work alone. One marker per seed."
    ),
    "recal_tradeoff": (
        "What a recalibration costs. Each point is one run, placed at the number of times the loop "
        "recalibrated in it -- the measured consequence of `confirm_sigma`, not the setting "
        "itself. Left: delivered coverage, against its nominal target as the dashed line. Middle: "
        "the share of events emitted on the estimator's own fallback interval rather than the "
        "configured one, which is the mechanism -- `run_closed_loop` resets the conformal "
        "calibration set on every profile activation, and the warm-up that follows is served by "
        "the fallback band. Right: MAE against the dynamic floor, which is what the recalibration "
        "was for. A figure of the left panel alone would show recalibration as pure cost and a "
        "figure of the right alone as pure benefit."
    ),
    "detector_curve": (
        "Recall against false alarms per hour, with each detector's threshold stepped from the "
        "shipped value to three more sensitive ones -- the trade-off curve rather than the single "
        "point the shipped configuration sits on. One line per detector, one marker per threshold, "
        "ordered by the false-alarm rate actually measured rather than by the setting, because the "
        "knobs run in opposite directions (a LOWER CUSUM threshold and a HIGHER KS alpha are both "
        "more sensitive). The detector each arm is drawn for is read from the detectors it runs, "
        "not from its name. Medians across seeds."
    ),
    "recall_vs_rate": (
        "Detection recall and detection delay against how often a reference vehicle arrives, one "
        "panel column per scenario. Top: mean recall over the injected calibration faults "
        "(fraction, dimensionless), one line per estimator plus a heavy line pooled over all of "
        "them; the open circles are the per-run recalls, so the sample size is visible rather "
        "than stated. Bottom: mean detection delay in seconds from fault onset, median across the "
        "runs that detected anything, with the interquartile range as a band -- a run that "
        "detected nothing contributes no delay rather than a zero. **Governed arm only**: with "
        "the controller disabled the detectors are never constructed, so the ungoverned runs "
        "carry structural zeros rather than misses. The point: detection is not uniformly broken. "
        "It works at dense reference rates and ceases at a located rate, which is what makes the "
        "reference rate the binding constraint rather than the detector."
    ),
    "governance_vs_rate": (
        "What the control loop is worth, against how often a reference vehicle arrives. Governed "
        "minus ungoverned over a byte-identical stream, paired by seed: one open marker per seed, "
        "the line through the per-seed medians. Top row: MAE difference in kg, where negative is "
        "the loop helping. Bottom row: SIGNED bias difference in kg, drawn beside the error and "
        "never folded into it, because the loop can improve MAE while pushing the bias through "
        "zero and out the other side. The dashed line at zero is 'the loop changed nothing', "
        "which is where both adaptive estimators sit at every rate. The point: the loop is worth "
        "tens of kilograms to static calibration at dense reference rates, decays to nothing as "
        "references thin, and is worth nothing at any rate to an estimator that already tracks."
    ),
    "detectors": (
        "Recall against false alarms per hour of simulated operation: the trade-off an operator "
        "actually faces. Either axis alone can be made perfect by a detector that is useless in "
        "the other direction. Scenarios with no faults have undefined recall and appear on the "
        "false-alarm axis only, as ticks *below* the zero line -- undefined recall is not a "
        "recall of zero, and a scenario with nothing to detect is the cleanest measurement of "
        "what a false alarm costs."
    ),
}

#: Where "recall is undefined" is drawn on the detector figure: below the axis, so it cannot be
#: read as a recall of zero.
_UNDEFINED_ROW = -0.09

#: Distinct without relying on colour alone, since these end up printed and pasted into slides.
_MARKERS = ("o", "s", "^", "D", "v", "P")

_Key = tuple[str, str]


def _usable(frame: pd.DataFrame) -> pd.DataFrame:
    if "failed" not in frame:
        return frame
    return frame[~frame["failed"].fillna(False).astype(bool)]


def _keys(frame: pd.DataFrame) -> list[_Key]:
    """Scenario/estimator pairs, in the frame's own scenario order and a stable estimator order."""
    scenarios = list(dict.fromkeys(frame["scenario"]))
    estimators = sorted(dict.fromkeys(frame["estimator"]))
    present = set(zip(frame["scenario"], frame["estimator"], strict=True))
    return [(s, e) for s in scenarios for e in estimators if (s, e) in present]


def _values(frame: pd.DataFrame, key: _Key, column: str) -> list[float]:
    rows = frame[(frame["scenario"] == key[0]) & (frame["estimator"] == key[1])]
    series = rows.sort_values("seed")[column]
    return [float(v) for v in series if pd.notna(v)]


def accuracy_ratios(frame: pd.DataFrame) -> dict[_Key, list[float]]:
    """MAE as a multiple of the dynamic floor, one value per seed.

    A scenario whose floor is zero carries no dynamic load, so the ratio is a division by zero
    rather than an impressive number, and it is left out.
    """
    usable = _usable(frame)
    usable = usable[usable["dynamic_floor_kg"].fillna(0.0) > 0.0]
    out: dict[_Key, list[float]] = {}
    for key in _keys(usable):
        rows = usable[(usable["scenario"] == key[0]) & (usable["estimator"] == key[1])]
        rows = rows.sort_values("seed")
        ratios = [
            float(mae) / float(floor)
            for mae, floor in zip(rows["mae_kg"], rows["dynamic_floor_kg"], strict=True)
            if pd.notna(mae) and floor > 0
        ]
        if ratios:
            out[key] = ratios
    return out


def coverage_rows(
    frame: pd.DataFrame, target: float | None = None
) -> tuple[dict[_Key, list[float]], float]:
    """Empirical coverage per seed, and the nominal target it is being judged against."""
    if target is None:
        from wimsim.core.config import EstimateConfig

        # From the config rather than a literal 0.95, so the line on the figure moves when the
        # shipped target does instead of quietly disagreeing with it.
        target = float(EstimateConfig().coverage_target)
    usable = _usable(frame)
    rows = {k: _values(usable, k, "coverage") for k in _keys(usable)}
    return {k: v for k, v in rows.items() if v}, target


@dataclass(frozen=True, slots=True)
class Reconvergence:
    """Reconvergence times for one scenario/estimator, and the runs that never got there.

    The two are kept apart because a bare NaN cannot tell "never reconverged" from "the run was too
    short to tell", and averaging them together would flatter whichever way was convenient.
    """

    seconds: list[float] = field(default_factory=list)
    never_reconverged: int = 0
    unmeasurable: int = 0


def reconvergence_rows(frame: pd.DataFrame) -> dict[_Key, Reconvergence]:
    """Time to reconverge per seed, for the scenarios that had a fault to reconverge from."""
    usable = _usable(frame)
    if "reconverge_measurable" in usable:
        measurable = usable["reconverge_measurable"].fillna(False).astype(bool)
    else:  # pragma: no cover - a frame from before the control columns existed
        measurable = pd.Series(True, index=usable.index)

    out: dict[_Key, Reconvergence] = {}
    for key in _keys(usable):
        rows = usable[(usable["scenario"] == key[0]) & (usable["estimator"] == key[1])]
        if not measurable.loc[rows.index].any():
            continue
        reconverged = rows["reconverged"].fillna(False).astype(bool)
        out[key] = Reconvergence(
            seconds=sorted(float(v) for v in rows.loc[reconverged, "reconverge_s"] if pd.notna(v)),
            never_reconverged=int((~reconverged & measurable.loc[rows.index]).sum()),
            unmeasurable=int((~measurable.loc[rows.index]).sum()),
        )
    return out


def detector_points(frame: pd.DataFrame) -> dict[_Key, list[tuple[float, float | None]]]:
    """``(false alarms per hour, recall)`` per seed.

    Recall is ``None`` where the scenario had no faults: recall on zero faults is undefined, not
    1.0, and a scenario with nothing to detect is still the cleanest measurement of what a detector
    costs when it is wrong.
    """
    usable = _usable(frame)
    out: dict[_Key, list[tuple[float, float | None]]] = {}
    for key in _keys(usable):
        rows = usable[(usable["scenario"] == key[0]) & (usable["estimator"] == key[1])]
        rows = rows.sort_values("seed")
        points = [
            (float(fa), float(recall) if pd.notna(recall) else None)
            for fa, recall in zip(rows["false_alarms_per_hour"], rows["recall"], strict=True)
            if pd.notna(fa)
        ]
        if points:
            out[key] = points
    return out


@dataclass(frozen=True, slots=True)
class RecalPoint:
    """One run on the recalibration trade: what it cost and what it bought.

    Both halves live on the same point on purpose. Recalibration improves the mass and reopens the
    conformal warm-up window, and either half plotted alone reads as a verdict.
    """

    recalibrations: int
    coverage: float
    fallback_share: float
    """Events emitted on the estimator's fallback interval, as a fraction of the run's events. A
    fraction rather than a count because runs are not all the same length."""
    mae_ratio: float | None
    """MAE as a multiple of the dynamic floor, or ``None`` where the scenario has no floor."""
    coverage_expected: float | None
    """Coverage over only those events that got the configured interval -- the band's own
    performance, with the fallback's contribution taken out."""


def recal_points(frame: pd.DataFrame) -> dict[_Key, list[RecalPoint]]:
    """The recalibration trade, one point per run.

    Placed at the *measured* recalibration count rather than at the ``confirm_sigma`` that produced
    it: two estimators at the same sigma need not recalibrate the same number of times, and the
    knob is not the quantity the trade is about. Runs with no coverage to report are dropped rather
    than drawn at zero.
    """
    usable = _usable(frame)
    if "recalibrations" not in usable or "coverage" not in usable:
        return {}
    out: dict[_Key, list[RecalPoint]] = {}
    for key in _keys(usable):
        rows = usable[(usable["scenario"] == key[0]) & (usable["estimator"] == key[1])]
        points: list[RecalPoint] = []
        for _i, row in rows.sort_values("seed").iterrows():
            if pd.isna(row.get("recalibrations")) or pd.isna(row.get("coverage")):
                continue
            events = float(row.get("n_events") or row.get("n_matched") or 0.0)
            fallback = float(row.get("n_interval_fallback") or 0.0)
            floor = float(row.get("dynamic_floor_kg") or 0.0)
            mae = row.get("mae_kg")
            expected = row.get("coverage_expected")
            points.append(
                RecalPoint(
                    recalibrations=int(row["recalibrations"]),
                    coverage=float(row["coverage"]),
                    fallback_share=(fallback / events) if events > 0 else float("nan"),
                    mae_ratio=(float(mae) / floor) if floor > 0 and pd.notna(mae) else None,
                    coverage_expected=float(expected) if pd.notna(expected) else None,
                )
            )
        if points:
            out[key] = points
    return out


def _family_of(edge_config: str) -> str:
    """The detectors an arm actually runs, as a stable label.

    Read from the configuration rather than parsed out of the name: an arm named for one detector
    and configured with another would be drawn on the wrong curve, and the name is the part nothing
    validates. Falls back to the name when the config cannot be loaded, so a frame from a renamed or
    deleted config still draws.
    """
    try:
        from wimsim.core.config import load_edge_config

        return "+".join(load_edge_config(edge_config).drift.detectors)
    except Exception:  # pragma: no cover - a config that no longer exists
        return edge_config


def detector_curves(frame: pd.DataFrame) -> dict[_Key, list[tuple[float, float]]]:
    """``(false alarms per hour, recall)`` per threshold arm, keyed by scenario and detector.

    Keyed on the detector rather than on the estimator, because a threshold sweep varies
    `edge_config` and leaves the estimator fixed -- so the figure's usual key would collapse every
    arm into one cloud and hide the trade-off the sweep exists to measure.

    Each point is one arm's median across seeds, and the points are ordered by the *measured*
    false-alarm rate. Ordering by the configured threshold would draw half the families backwards,
    since ADWIN's delta and KS's alpha get more sensitive as they rise while CUSUM's and
    Page-Hinkley's thresholds get more sensitive as they fall.
    """
    usable = _usable(frame)
    if "edge_config" not in usable or usable["edge_config"].nunique(dropna=False) < 2:
        return {}

    out: dict[_Key, list[tuple[float, float]]] = {}
    for scenario in dict.fromkeys(usable["scenario"]):
        rows = usable[usable["scenario"] == scenario]
        by_family: dict[str, list[tuple[float, float]]] = {}
        for arm in sorted(dict.fromkeys(rows["edge_config"])):
            cell = rows[rows["edge_config"] == arm]
            fa = cell["false_alarms_per_hour"].dropna()
            recall = cell["recall"].dropna()
            if fa.empty or recall.empty:
                continue
            by_family.setdefault(_family_of(str(arm)), []).append(
                (float(fa.median()), float(recall.median()))
            )
        for family, points in by_family.items():
            if points:
                out[(scenario, family)] = sorted(points)
    return out


_RateKey = tuple[str, str, bool | None]


def rate_curves(frame: pd.DataFrame) -> dict[_RateKey, dict[int, list[float]]]:
    """``(scenario, estimator, controller on?) -> reference rate -> MAE/floor, one per seed``.

    The two arms are kept apart because the gap between them *is* the question. Averaging the
    controller-on and controller-off runs together would answer one nobody asked.

    Scenarios are kept apart for a reason found on the first real sweep, where they were not:
    S4 and S7 were pooled into one median, and since static_affine sits at 1.41x its floor on S4
    and 1.16x on S7, the pooled line came out at 1.27x -- a number describing neither.
    """
    usable = _usable(frame)
    if "reference_every_n" not in usable:
        return {}
    usable = usable[usable["dynamic_floor_kg"].fillna(0.0) > 0.0]
    usable = usable[usable["reference_every_n"].notna()]
    if usable.empty:
        return {}

    arms = (
        usable["control_enabled"]
        if "control_enabled" in usable
        else pd.Series([None] * len(usable), index=usable.index)
    )
    out: dict[_RateKey, dict[int, list[float]]] = {}
    scenarios = list(dict.fromkeys(usable["scenario"]))
    for scenario in scenarios:
        for estimator in sorted(dict.fromkeys(usable["estimator"])):
            for arm in sorted(dict.fromkeys(arms), key=lambda a: (a is None, not a)):
                same = (usable["scenario"] == scenario) & (usable["estimator"] == estimator)
                sel = usable[same & (arms == arm)] if arm is not None else usable[same]
                if sel.empty:
                    continue
                by_rate: dict[int, list[float]] = {}
                for rate in sorted(dict.fromkeys(sel["reference_every_n"])):
                    rows = sel[sel["reference_every_n"] == rate].sort_values("seed")
                    vals = [
                        float(m) / float(f)
                        for m, f in zip(rows["mae_kg"], rows["dynamic_floor_kg"], strict=True)
                        if pd.notna(m) and f > 0
                    ]
                    if vals:
                        by_rate[int(rate)] = vals
                if by_rate:
                    out[(scenario, estimator, arm)] = by_rate
    return out


# -- drawing ---------------------------------------------------------------------------------------


#: Raster resolution. 300 is the floor most journals set for a figure that is not vector, and
#: `export/figures/FIGURES.md` claimed 300 while this said 150 -- the document was describing a
#: figure the code did not produce. Changed here rather than in the document, because the brief
#: asks for publication resolution and 150 is not it.
_DPI = 300


def _save(fig: Any, path: Path) -> Path:
    # No timestamp in the metadata: a figure that changes between renders cannot be diffed.
    fig.savefig(path, dpi=_DPI, bbox_inches="tight", metadata={"Software": "wimsim"})
    plt.close(fig)
    return path


def _grouped_axes(keys: list[_Key], title: str) -> tuple[Any, Any, dict[str, float]]:
    """One x position per scenario, with estimators offset within it."""
    scenarios = list(dict.fromkeys(s for s, _e in keys))
    fig, ax = plt.subplots(figsize=(max(6.0, 1.6 * len(scenarios) + 2.0), 4.0))
    ax.set_title(title)
    ax.set_xticks(range(len(scenarios)))
    ax.set_xticklabels(scenarios, rotation=20, ha="right")
    ax.grid(axis="y", alpha=0.3, linewidth=0.5)
    return fig, ax, {s: float(i) for i, s in enumerate(scenarios)}


def _offsets(estimators: list[str]) -> dict[str, float]:
    if len(estimators) == 1:
        return {estimators[0]: 0.0}
    span = 0.6
    return {
        e: -span / 2 + span * i / (len(estimators) - 1) for i, e in enumerate(sorted(estimators))
    }


def _scatter(ax: Any, positions: Mapping[str, float], keys: list[_Key], series, ylabel: str):
    estimators = sorted({e for _s, e in keys})
    offsets = _offsets(estimators)
    markers = dict(zip(estimators, _MARKERS, strict=False))
    for index, estimator in enumerate(estimators):
        xs, ys = [], []
        for scenario, est in keys:
            if est != estimator:
                continue
            for value in series[(scenario, est)]:
                xs.append(positions[scenario] + offsets[estimator])
                ys.append(value)
        ax.scatter(
            xs,
            ys,
            label=estimator,
            marker=markers[estimator],
            s=34,
            color=f"C{index}",
            zorder=3,
            alpha=0.85,
        )
    ax.set_ylabel(ylabel)
    ax.legend(fontsize=8, framealpha=0.9)


def _draw_accuracy(frame: pd.DataFrame, title: str, path: Path) -> Path | None:
    ratios = accuracy_ratios(frame)
    if not ratios:
        return None
    keys = list(ratios)
    fig, ax, positions = _grouped_axes(keys, title)
    _scatter(ax, positions, keys, ratios, "MAE / dynamic floor")
    ax.axhline(1.0, color="k", linestyle="--", linewidth=1.0, zorder=2)
    ax.annotate(
        "the floor: error the vehicles brought with them",
        xy=(0.01, 1.0),
        xycoords=("axes fraction", "data"),
        xytext=(0, 4),
        textcoords="offset points",
        fontsize=7,
        color="k",
    )
    # Log. On the shipped ladder S6 reaches 4.1x the floor and every other scenario sits between
    # 1.00 and 1.40, so a linear axis spends four fifths of its height on the one scenario that is
    # obviously hard and compresses the range where the estimators actually differ -- 1.13x against
    # 1.40x on S4 is the headline result, and it is a few pixels tall.
    ax.set_yscale("log")
    top = max(max(v) for v in ratios.values())
    ax.set_ylim(0.95, top * 1.15)
    # Explicit ticks. The data spans well under one decade, where matplotlib's log locator puts
    # almost nothing, so the axis would otherwise carry a single "1x" label and no way to read a
    # value off it.
    ticks = [t for t in (1.0, 1.1, 1.25, 1.5, 2.0, 3.0, 4.0, 6.0, 10.0) if t <= top * 1.15]
    ax.set_yticks(ticks)
    ax.set_yticks([], minor=True)
    ax.yaxis.set_major_formatter(FuncFormatter(lambda v, _pos: f"{v:g}x"))
    return _save(fig, path)


def _draw_coverage(frame: pd.DataFrame, title: str, path: Path) -> Path | None:
    rows, target = coverage_rows(frame)
    if not rows:
        return None
    keys = list(rows)
    fig, ax, positions = _grouped_axes(keys, title)
    _scatter(ax, positions, keys, rows, "empirical coverage")
    ax.axhline(target, color="k", linestyle="--", linewidth=1.0, zorder=2)
    ax.annotate(
        f"nominal {target:.2f}",
        xy=(0.01, target),
        xycoords=("axes fraction", "data"),
        xytext=(0, 4),
        textcoords="offset points",
        fontsize=7,
    )
    return _save(fig, path)


def _draw_reconvergence(frame: pd.DataFrame, title: str, path: Path) -> Path | None:
    rows = reconvergence_rows(frame)
    if not rows:
        return None
    keys = list(rows)
    fig, ax, positions = _grouped_axes(keys, title)
    _scatter(ax, positions, keys, {k: v.seconds for k, v in rows.items()}, "time to reconverge (s)")

    # A run that never reconverged has no y value to plot, so it is written on the axis instead of
    # being silently absent.
    stuck = [(k, v.never_reconverged) for k, v in rows.items() if v.never_reconverged]
    if stuck:
        ax.set_xlabel(
            "never reconverged: "
            + ", ".join(f"{s}/{e} x{n}" for (s, e), n in stuck)
            + " (not plotted)",
            fontsize=7,
        )
    ax.set_ylim(bottom=0.0)
    return _save(fig, path)


def _draw_detectors(frame: pd.DataFrame, title: str, path: Path) -> Path | None:
    points = detector_points(frame)
    if not points:
        return None
    fig, ax = plt.subplots(figsize=(6.0, 4.0))
    ax.set_title(title)
    estimators = sorted({e for _s, e in points})
    markers = dict(zip(estimators, _MARKERS, strict=False))
    for index, estimator in enumerate(estimators):
        xs = [p[0] for k, ps in points.items() if k[1] == estimator for p in ps if p[1] is not None]
        ys = [p[1] for k, ps in points.items() if k[1] == estimator for p in ps if p[1] is not None]
        undefined = [
            p[0] for k, ps in points.items() if k[1] == estimator for p in ps if p[1] is None
        ]
        ax.scatter(xs, ys, label=estimator, marker=markers[estimator], s=34, color=f"C{index}")
        # Below the axis, not at zero. A scenario with no faults has *undefined* recall, and drawn
        # at y=0 it is pixel-for-pixel a detector that missed everything -- the one confusion this
        # figure exists to avoid.
        ax.scatter(
            undefined,
            np.full(len(undefined), _UNDEFINED_ROW),
            marker="|",
            s=80,
            color=f"C{index}",
            alpha=0.7,
            clip_on=False,
        )
    ax.set_xlabel("false alarms per hour")
    ax.set_ylabel("recall")
    ax.set_ylim(_UNDEFINED_ROW - 0.04, 1.05)
    ax.axhline(0.0, color="0.6", linewidth=0.8)
    ax.set_yticks([0.0, 0.25, 0.5, 0.75, 1.0])
    ax.grid(alpha=0.3, linewidth=0.5)
    ax.annotate(
        "below the line: no calibration fault in the scenario, so recall is undefined -- not zero",
        xy=(0.02, _UNDEFINED_ROW / 2.0),
        xycoords=("axes fraction", "data"),
        fontsize=7,
        va="center",
    )
    ax.legend(fontsize=8, framealpha=0.9)
    return _save(fig, path)


def _draw_reference_rate(frame: pd.DataFrame, title: str, path: Path) -> Path | None:
    curves = rate_curves(frame)
    rates = sorted({r for c in curves.values() for r in c})
    if len(rates) < 2:
        # A one-point curve is not a trend, and drawing it invites exactly the reading it cannot
        # support. `ladder` runs at a single rate.
        return None

    scenarios = list(dict.fromkeys(k[0] for k in curves))
    fig, axes = plt.subplots(
        1, len(scenarios), figsize=(4.6 * len(scenarios) + 1.0, 4.2), sharey=True, squeeze=False
    )
    fig.suptitle(title)
    estimators = sorted({e for _s, e, _a in curves})
    markers = dict(zip(estimators, _MARKERS, strict=False))

    for ax, scenario in zip(axes[0], scenarios, strict=True):
        for index, estimator in enumerate(estimators):
            for arm in (True, False, None):
                by_rate = curves.get((scenario, estimator, arm))
                if not by_rate:
                    continue
                xs = sorted(by_rate)
                med = [float(np.median(by_rate[r])) for r in xs]
                label = estimator + ("" if arm is None else ("  loop on" if arm else "  loop off"))
                ax.plot(
                    xs,
                    med,
                    "--" if arm is False else "-",
                    color=f"C{index}",
                    linewidth=1.6,
                    label=label,
                    zorder=3,
                )
                for r in xs:
                    ax.scatter(
                        [r] * len(by_rate[r]),
                        by_rate[r],
                        marker=markers[estimator],
                        s=16,
                        color=f"C{index}",
                        alpha=0.4,
                        zorder=2,
                    )
        ax.axhline(1.0, color="k", linestyle=":", linewidth=1.0, zorder=1)
        ax.set_title(scenario, fontsize=9)
        # Log, because the rates span 25x and the interesting behaviour is at the dense end. Minor
        # ticks off: matplotlib labels them "3 x 10^0" and they collide with the "1 in N" majors.
        ax.set_xscale("log")
        ax.set_xticks(rates)
        ax.set_xticks([], minor=True)
        ax.xaxis.set_major_formatter(FuncFormatter(lambda v, _p: f"1 in {v:g}"))
        ax.set_xlabel("how often a reference vehicle arrives")
        ax.grid(alpha=0.3, linewidth=0.5)

    axes[0][0].set_ylabel("MAE / dynamic floor")
    axes[0][0].annotate(
        "the floor",
        xy=(0.01, 1.0),
        xycoords=("axes fraction", "data"),
        xytext=(0, 3),
        textcoords="offset points",
        fontsize=7,
    )
    axes[0][-1].legend(fontsize=7, framealpha=0.9, ncol=2)
    fig.tight_layout()
    return _save(fig, path)


def _draw_recal_tradeoff(frame: pd.DataFrame, title: str, path: Path) -> Path | None:
    points = recal_points(frame)
    if not points:
        return None
    counts = {p.recalibrations for series in points.values() for p in series}
    if len(counts) < 2:
        # Every arm recalibrated the same number of times, so there is no trade in this sweep. A
        # vertical stripe of points invites a reading about frequency that the data cannot support.
        return None

    _rows, target = coverage_rows(frame)
    estimators = sorted({e for _s, e in points})
    markers = dict(zip(estimators, _MARKERS, strict=False))
    scenarios = list(dict.fromkeys(s for s, _e in points))

    fig, axes = plt.subplots(1, 3, figsize=(13.5, 4.2), squeeze=False)
    fig.suptitle(title)
    panels = (
        ("coverage", lambda p: p.coverage, "delivered coverage"),
        ("fallback", lambda p: p.fallback_share, "share of events on a fallback interval"),
        ("mae", lambda p: p.mae_ratio, "MAE / dynamic floor"),
    )

    for ax, (_name, value, ylabel) in zip(axes[0], panels, strict=True):
        for index, estimator in enumerate(estimators):
            xs, ys = [], []
            medians: dict[int, list[float]] = {}
            for scenario in scenarios:
                for p in points.get((scenario, estimator), ()):
                    v = value(p)
                    if v is None or not np.isfinite(v):
                        continue
                    xs.append(p.recalibrations)
                    ys.append(v)
                    medians.setdefault(p.recalibrations, []).append(v)
            if not xs:
                continue
            ax.scatter(
                xs,
                ys,
                marker=markers[estimator],
                s=26,
                color=f"C{index}",
                alpha=0.45,
                zorder=2,
                label=estimator,
            )
            ordered = sorted(medians)
            ax.plot(
                ordered,
                [float(np.median(medians[k])) for k in ordered],
                "-",
                color=f"C{index}",
                linewidth=1.6,
                zorder=3,
            )
        ax.set_xlabel("recalibrations in the run")
        ax.set_ylabel(ylabel)
        ax.grid(alpha=0.3, linewidth=0.5)

    axes[0][0].axhline(target, color="k", linestyle="--", linewidth=1.0, zorder=1)
    axes[0][0].annotate(
        f"nominal {target:g}",
        xy=(0.02, target),
        xycoords=("axes fraction", "data"),
        xytext=(0, 3),
        textcoords="offset points",
        fontsize=7,
    )
    axes[0][2].axhline(1.0, color="k", linestyle=":", linewidth=1.0, zorder=1)
    axes[0][0].legend(fontsize=8, framealpha=0.9)
    fig.tight_layout()
    return _save(fig, path)


def _draw_detector_curve(frame: pd.DataFrame, title: str, path: Path) -> Path | None:
    curves = detector_curves(frame)
    if not curves or all(len(p) < 2 for p in curves.values()):
        # One threshold per detector is a point, not a curve, and drawing it invites exactly the
        # reading about the trade-off that a single operating point cannot support.
        return None

    scenarios = list(dict.fromkeys(s for s, _f in curves))
    families = sorted({f for _s, f in curves})
    markers = dict(zip(families, _MARKERS, strict=False))

    fig, axes = plt.subplots(
        1, len(scenarios), figsize=(5.0 * len(scenarios) + 1.0, 4.2), sharey=True, squeeze=False
    )
    fig.suptitle(title)
    for ax, scenario in zip(axes[0], scenarios, strict=True):
        for index, family in enumerate(families):
            points = curves.get((scenario, family))
            if not points:
                continue
            xs = [p[0] for p in points]
            ys = [p[1] for p in points]
            ax.plot(xs, ys, "-", color=f"C{index}", linewidth=1.5, zorder=2)
            ax.scatter(
                xs, ys, marker=markers[family], s=40, color=f"C{index}", label=family, zorder=3
            )
        ax.set_title(scenario, fontsize=9)
        ax.set_xlabel("false alarms per hour")
        ax.set_ylim(-0.03, 1.03)
        ax.grid(alpha=0.3, linewidth=0.5)

    axes[0][0].set_ylabel("detection recall")
    axes[0][-1].legend(fontsize=8, framealpha=0.9, title="detectors run", title_fontsize=8)
    fig.tight_layout()
    return _save(fig, path)


def _rate_axis(ax: Any, rates: list[int]) -> None:
    """Shared x axis for the two reference-rate figures: log, labelled "1 in N".

    Log because the rates span fifty-fold and everything interesting is at the dense end. Minor
    ticks off because matplotlib labels them "3 x 10^0" and they collide with the majors.
    """
    ax.set_xscale("log")
    ax.set_xticks(rates)
    ax.set_xticks([], minor=True)
    ax.xaxis.set_major_formatter(FuncFormatter(lambda v, _p: f"1 in {v:g}"))
    ax.grid(alpha=0.3, linewidth=0.5)


def recall_rate_points(frame: pd.DataFrame) -> dict[str, dict[str, list[Any]]]:
    """``scenario -> estimator -> cells``, the reduction the recall figure draws."""
    from wimsim.experiments.reference_curve import recall_by_rate

    out: dict[str, dict[str, list[Any]]] = {}
    for cell in recall_by_rate(frame):
        out.setdefault(cell.scenario, {}).setdefault(cell.estimator, []).append(cell)
    return out


def _draw_recall_vs_rate(frame: pd.DataFrame, title: str, path: Path) -> Path | None:
    from wimsim.experiments.reference_curve import POOLED

    if "reference_every_n" not in frame or frame["reference_every_n"].nunique(dropna=True) < 2:
        # A one-point curve is not a trend, and drawing it invites the reading it cannot support.
        return None
    by_scenario = recall_rate_points(frame)
    if not by_scenario:
        return None
    # Nothing was ever injected: recall is undefined rather than zero, and an axis of zeros would
    # report the detectors as failing at something they were never asked to do.
    defined = any(
        cell.recall_defined
        for series in by_scenario.values()
        for cells in series.values()
        for cell in cells
    )
    if not defined:
        return None

    governed = _usable(frame)
    if "control_enabled" in governed:
        governed = governed[governed["control_enabled"].fillna(False).astype(bool)]

    scenarios = list(by_scenario)
    rates = sorted(
        {c.reference_every_n for s in by_scenario.values() for v in s.values() for c in v}
    )
    fig, axes = plt.subplots(
        2, len(scenarios), figsize=(4.6 * len(scenarios) + 1.0, 6.4), sharex=True, squeeze=False
    )
    fig.suptitle(title)
    estimators = sorted({e for s in by_scenario.values() for e in s if e != POOLED})
    markers = dict(zip(estimators, _MARKERS, strict=False))

    for column, scenario in enumerate(scenarios):
        top, bottom = axes[0][column], axes[1][column]
        series = by_scenario[scenario]
        for index, estimator in enumerate(estimators):
            cells = sorted(series.get(estimator, []), key=lambda c: c.reference_every_n)
            if not cells:
                continue
            xs = [c.reference_every_n for c in cells]
            top.plot(
                xs,
                [c.recall_mean for c in cells],
                "-",
                color=f"C{index}",
                linewidth=1.4,
                marker=markers[estimator],
                markersize=4,
                label=estimator,
                zorder=3,
            )
            delayed = [c for c in cells if c.n_delay]
            if delayed:
                dx = [c.reference_every_n for c in delayed]
                bottom.plot(
                    dx,
                    [c.delay_median for c in delayed],
                    "-",
                    color=f"C{index}",
                    linewidth=1.4,
                    marker=markers[estimator],
                    markersize=4,
                    label=estimator,
                    zorder=3,
                )
                bottom.fill_between(
                    dx,
                    [c.delay_q1 for c in delayed],
                    [c.delay_q3 for c in delayed],
                    color=f"C{index}",
                    alpha=0.12,
                    linewidth=0,
                    zorder=2,
                )
        pooled = sorted(series.get(POOLED, []), key=lambda c: c.reference_every_n)
        if pooled:
            top.plot(
                [c.reference_every_n for c in pooled],
                [c.recall_mean for c in pooled],
                "-",
                color="k",
                linewidth=2.6,
                alpha=0.75,
                zorder=4,
                label=f"pooled, n={pooled[0].n_runs} per rate",
            )
        # Per-run recalls, so the sample behind each mean is visible rather than asserted.
        rows = governed[governed["scenario"] == scenario]
        if "recall" in rows:
            top.scatter(
                rows["reference_every_n"],
                rows["recall"],
                s=12,
                facecolors="none",
                edgecolors="0.4",
                linewidths=0.5,
                alpha=0.5,
                zorder=1,
            )
        top.axhline(0.0, color="k", linestyle=":", linewidth=1.0, zorder=1)
        top.set_title(scenario, fontsize=9)
        top.set_ylim(-0.08, 1.08)
        _rate_axis(top, rates)
        _rate_axis(bottom, rates)
        bottom.set_xlabel("how often a reference vehicle arrives")

    axes[0][0].set_ylabel("detection recall (fraction)")
    axes[1][0].set_ylabel("detection delay (s), median [IQR]")
    axes[0][-1].legend(fontsize=7, framealpha=0.9, loc="upper right")
    fig.tight_layout()
    return _save(fig, path)


def governance_rate_points(
    frame: pd.DataFrame,
) -> dict[tuple[str, str], dict[int, tuple[list[float], list[float]]]]:
    """``(scenario, estimator) -> rate -> (per-seed dMAE, per-seed dBias)``."""
    from wimsim.experiments.reference_curve import governance_differences

    pairs = governance_differences(frame)
    out: dict[tuple[str, str], dict[int, tuple[list[float], list[float]]]] = {}
    if pairs.empty:
        return out
    for (scenario, estimator, rate), block in pairs.groupby(
        ["scenario", "estimator", "reference_every_n"], sort=True
    ):
        out.setdefault((str(scenario), str(estimator)), {})[int(rate)] = (
            [float(v) for v in block["d_mae_kg"]],
            [float(v) for v in block["d_bias_kg"]],
        )
    return out


def _draw_governance_vs_rate(frame: pd.DataFrame, title: str, path: Path) -> Path | None:
    from wimsim.experiments.reference_curve import _GOVERNANCE_COLUMNS

    # Not every sweep scores both arms, and not every sweep scores signed bias. Either absence
    # means there is no difference to draw, which is a blank axis rather than a result.
    if any(c not in frame.columns for c in _GOVERNANCE_COLUMNS):
        return None
    if frame["control_enabled"].nunique(dropna=True) < 2:
        return None
    if "reference_every_n" not in frame or frame["reference_every_n"].nunique(dropna=True) < 2:
        return None
    points = governance_rate_points(frame)
    if not points:
        return None

    scenarios = list(dict.fromkeys(s for s, _e in points))
    rates = sorted({r for series in points.values() for r in series})
    estimators = sorted({e for _s, e in points})
    markers = dict(zip(estimators, _MARKERS, strict=False))

    fig, axes = plt.subplots(
        2, len(scenarios), figsize=(4.6 * len(scenarios) + 1.0, 6.4), sharex=True, squeeze=False
    )
    fig.suptitle(title)

    for column, scenario in enumerate(scenarios):
        for row in (0, 1):
            ax = axes[row][column]
            for index, estimator in enumerate(estimators):
                series = points.get((scenario, estimator))
                if not series:
                    continue
                xs = sorted(series)
                vals = [series[r][row] for r in xs]
                ax.plot(
                    xs,
                    [float(np.median(v)) for v in vals],
                    "-",
                    color=f"C{index}",
                    linewidth=1.5,
                    marker=markers[estimator],
                    markersize=4,
                    label=f"{estimator}, n={len(vals[0])} seeds",
                    zorder=3,
                )
                for rate, seeds in zip(xs, vals, strict=True):
                    ax.scatter(
                        [rate] * len(seeds),
                        seeds,
                        s=12,
                        facecolors="none",
                        edgecolors=f"C{index}",
                        linewidths=0.5,
                        alpha=0.45,
                        zorder=2,
                    )
            ax.axhline(0.0, color="k", linestyle="--", linewidth=1.0, zorder=1)
            _rate_axis(ax, rates)
            if row == 0:
                ax.set_title(scenario, fontsize=9)
            else:
                ax.set_xlabel("how often a reference vehicle arrives")

    axes[0][0].set_ylabel("governed - ungoverned MAE (kg)")
    axes[1][0].set_ylabel("governed - ungoverned SIGNED bias (kg)")
    axes[0][0].annotate(
        "zero: the loop changed nothing",
        xy=(0.02, 0.0),
        xycoords=("axes fraction", "data"),
        xytext=(0, 4),
        textcoords="offset points",
        fontsize=7,
    )
    axes[0][-1].legend(fontsize=7, framealpha=0.9)
    fig.tight_layout()
    return _save(fig, path)


_DRAW = {
    "accuracy": _draw_accuracy,
    "reference_rate": _draw_reference_rate,
    "recall_vs_rate": _draw_recall_vs_rate,
    "governance_vs_rate": _draw_governance_vs_rate,
    "coverage": _draw_coverage,
    "reconvergence": _draw_reconvergence,
    "detectors": _draw_detectors,
    "detector_curve": _draw_detector_curve,
    "recal_tradeoff": _draw_recal_tradeoff,
}


def write_figures(frame: pd.DataFrame, *, out_dir: Path | str, experiment_id: str) -> list[Path]:
    """Draw every figure the frame supports into ``<out_dir>/figures/``.

    Returns the paths written, PNGs and the captions file. A figure with nothing to draw is not
    written at all: an axis with no data on it is not a result, and a reader shown four
    plausible-looking empty plots has been told less than one shown none.
    """
    if frame.empty:
        return []
    figures = Path(out_dir) / "figures"
    figures.mkdir(parents=True, exist_ok=True)

    failed = int(frame["failed"].fillna(False).sum()) if "failed" in frame else 0
    provenance = f"{experiment_id} -- {len(frame) - failed} of {len(frame)} runs"
    if failed:
        provenance += f", {failed} failed"

    written: list[Path] = []
    drawn: list[str] = []
    for name, draw in _DRAW.items():
        path = draw(frame, f"{name}  [{provenance}]", figures / f"{name}.png")
        if path is not None:
            written.append(path)
            drawn.append(name)

    if not written:
        return []

    lines = [
        f"# Figures: {experiment_id}",
        "",
        f"{len(frame) - failed} of {len(frame)} runs are drawn"
        + (f"; {failed} of {len(frame)} failed and carry no values." if failed else "."),
        "",
    ]
    for name in drawn:
        lines += [f"### `{name}.png`", "", FIGURES[name], ""]
    missing = [n for n in FIGURES if n not in drawn]
    if missing:
        lines += [
            "### Not drawn",
            "",
            "These had no data in this sweep, and an empty axis is not a result: "
            + ", ".join(f"`{n}.png`" for n in missing)
            + ".",
            "",
        ]
    readme = figures / "README.md"
    readme.write_text("\n".join(lines), encoding="utf-8")
    written.append(readme)
    return written
