"""The reference rate as the binding constraint, measured rather than argued by elimination.

Section VII-C reaches the reference rate by exclusion: nothing else that was varied moved the
result, so the rate must be what binds. Two relationships already present in the `reference_rate`
sweeps say something stronger and more specific, and neither is reported anywhere in the export.

**Detection recall falls monotonically as references thin, and reaches zero.** Not "the detector is
weak" -- it works at dense reference rates and stops working somewhere between one reference in ten
and one in twenty. That is a located failure with an operational reading: a site that supplies
references more often than the crossing gets drift detection, and a site that does not gets an
estimator with a detector attached that never fires.

**The governed-minus-ungoverned error difference is monotonic for static calibration and
identically zero for both adaptive estimators.** The loop is worth tens of kilograms where nothing
tracks the plant and worth nothing where something does.

Three definitions in here are load-bearing and each is easy to get wrong in a flattering direction.

*Recall is measured in the governed arm only.* With `edge.control.enabled=false` the detectors are
never constructed, so every ungoverned run reports `alarms 0, detected 0, recall 0.000`. Those
zeros are structural. Pooling the arms would halve the recall in every cell of the table and would
present "the detector was not running" as "the detector missed".

*The governance effect is the median of the per-seed differences, not the difference of the
medians.* The two arms are run over a byte-identical stream, which is the entire reason a paired
statistic is available here; taking medians first throws that away and the two quantities are not
equal on a skewed set.

*Signed bias travels beside the error and is never folded into it.* On this data the loop can
improve MAE while driving the signed bias through zero and out the other side, and a table of
``|bias|``, or of error alone, would show that as unambiguous improvement.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

__all__ = [
    "POOLED",
    "GovernanceCell",
    "RecallCell",
    "ZeroCrossing",
    "governance_by_rate",
    "governance_differences",
    "recall_by_rate",
    "recall_zero_crossing",
    "reference_curve_markdown",
    "write_reference_curve",
]

#: The estimator label of the row pooled over every estimator. A literal rather than an empty
#: string so it cannot be confused with a missing value in a table or a CSV.
POOLED = "all"


@dataclass(frozen=True, slots=True)
class RecallCell:
    """Detection recall and delay for one (scenario, estimator, reference rate)."""

    scenario: str
    estimator: str
    """An estimator name, or :data:`POOLED` for the row over all of them."""
    reference_every_n: int
    n_runs: int
    recall_mean: float
    recall_median: float
    recall_q1: float
    recall_q3: float
    faults_hit: int
    faults_missed: int
    n_delay: int
    """How many of the runs detected anything, and therefore have a delay at all."""
    delay_median: float
    delay_q1: float
    delay_q3: float
    false_alarms_per_hour: float

    @property
    def recall_defined(self) -> bool:
        """False when no fault was injected: a detector cannot miss what was never there."""
        return (self.faults_hit + self.faults_missed) > 0


@dataclass(frozen=True, slots=True)
class ZeroCrossing:
    """Where recall goes to zero, and how tightly the grid locates it."""

    scenario: str
    last_positive: int | None
    """The densest-but-one rate at which recall was still above zero, or None if none was."""
    first_zero: int | None
    """The densest rate at which recall was zero, or None if it never was."""
    located_to: float | None
    """``first_zero / last_positive`` -- the factor the crossing is bracketed within. None when
    the grid does not bracket it, which is a different statement from a wide bracket."""


@dataclass(frozen=True, slots=True)
class GovernanceCell:
    """Governed minus ungoverned, paired by seed, for one (scenario, estimator, rate)."""

    scenario: str
    estimator: str
    reference_every_n: int
    n_pairs: int
    n_identical: int
    """Pairs whose MAE came out exactly equal. A median of zero over thirty pairs means something
    different depending on whether it is thirty zeros or fifteen cancelling pairs."""
    mae_median: float
    mae_q1: float
    mae_q3: float
    mae_difference_of_medians: float
    """Kept beside the paired median so the two can be seen not to be the same number."""
    mae_governed: float
    mae_open: float
    bias_median: float
    bias_q1: float
    bias_q3: float
    bias_governed: float
    bias_open: float
    recalibrations: float
    """Median recalibrations in the governed arm -- the loop's activity, which is what a zero
    effect has to be read against."""


# -- reductions -----------------------------------------------------------------------------------


def _usable(frame: pd.DataFrame) -> pd.DataFrame:
    if "failed" not in frame:
        return frame
    return frame[~frame["failed"].fillna(False).astype(bool)]


def _require_rate_axis(frame: pd.DataFrame) -> pd.DataFrame:
    """The rows with a rate on them."""
    if "reference_every_n" not in frame.columns or frame["reference_every_n"].isna().all():
        raise ValueError(
            "this frame has no reference-rate axis, so neither relationship can be read from it. "
            "Run configs/experiments/reference_rate30.yaml."
        )
    return frame[frame["reference_every_n"].notna()]


def _require_rate_curve(frame: pd.DataFrame) -> pd.DataFrame:
    """As above, and the sweep must actually have varied the rate.

    The per-cell reductions are perfectly well defined at a single rate, so they do not impose
    this; the *report* does, because both relationships it presents are shapes against the rate
    and a one-point curve invites exactly the reading it cannot support. It is the same rule
    `_draw_reference_rate` already applies to the figure. `ladder30` and `heldout30` both pin
    `reference_every_n: 10`, and running the report on `heldout30` produced a table that looked
    like a rate study and was a single column.
    """
    rated = _require_rate_axis(frame)
    if rated["reference_every_n"].nunique() < 2:
        rate = rated["reference_every_n"].iloc[0]
        raise ValueError(
            f"this sweep ran one reference rate (1 in {rate:g}), so there is no curve to read. "
            "Both relationships here are shapes against the rate; a one-point curve would be "
            "presented as a trend. Run configs/experiments/reference_rate30.yaml."
        )
    return rated


def _quantiles(values: pd.Series | None) -> tuple[float, float, float, int]:
    """median, q1, q3, n over the finite values. NaN throughout when there are none.

    ``None`` is one of the ways there are none: ``DataFrame.get`` returns it for a column the
    sweep never wrote, and a sweep that ran no controller writes no detection delay. That is a
    cell with no sample, not an error -- the figures call this on frames from every sweep.
    """
    if values is None:
        return (float("nan"), float("nan"), float("nan"), 0)
    finite = pd.to_numeric(values, errors="coerce").dropna()
    if finite.empty:
        return (float("nan"), float("nan"), float("nan"), 0)
    return (
        float(finite.median()),
        float(finite.quantile(0.25)),
        float(finite.quantile(0.75)),
        int(finite.size),
    )


def _count(values: pd.Series | None) -> int:
    """Total over a count column, or zero when the sweep never wrote it."""
    if values is None:
        return 0
    return int(pd.to_numeric(values, errors="coerce").fillna(0).sum())


def _governed(frame: pd.DataFrame) -> pd.DataFrame:
    """The arm the detectors actually ran in.

    A sweep with no ``control_enabled`` column ran one arm and is taken at face value; one with the
    column is filtered, because the ungoverned rows carry structural zeros rather than misses.
    """
    if "control_enabled" not in frame.columns:
        return frame
    return frame[frame["control_enabled"].fillna(False).astype(bool)]


def recall_by_rate(frame: pd.DataFrame) -> list[RecallCell]:
    """Detection recall and delay against reference rate, per estimator and pooled over them.

    Governed arm only -- see the module docstring. Both the mean and the median are reported: the
    mean because recall over a handful of injected faults takes a few discrete values and its
    median is frequently 0.000 while the cell plainly detected something, and the median with its
    IQR because the mean of nine runs hides which of them did the detecting.
    """
    usable = _governed(_usable(_require_rate_axis(frame)))
    if usable.empty:
        return []

    cells: list[RecallCell] = []
    for scenario in dict.fromkeys(usable["scenario"]):
        rows = usable[usable["scenario"] == scenario]
        estimators = [*sorted(dict.fromkeys(rows["estimator"])), POOLED]
        for estimator in estimators:
            cell_rows = rows if estimator == POOLED else rows[rows["estimator"] == estimator]
            for rate in sorted(dict.fromkeys(cell_rows["reference_every_n"])):
                sel = cell_rows[cell_rows["reference_every_n"] == rate]
                if sel.empty:
                    continue
                raw = sel.get("recall")
                recall = (
                    pd.Series(dtype=float)
                    if raw is None
                    else pd.to_numeric(raw, errors="coerce").dropna()
                )
                r_med, r_q1, r_q3, n = _quantiles(raw)
                d_med, d_q1, d_q3, n_delay = _quantiles(sel.get("mean_detection_delay_s"))
                fa = pd.to_numeric(
                    sel.get("false_alarms_per_hour", pd.Series(dtype=float)), errors="coerce"
                ).dropna()
                cells.append(
                    RecallCell(
                        scenario=str(scenario),
                        estimator=str(estimator),
                        reference_every_n=int(rate),
                        n_runs=n,
                        recall_mean=float(recall.mean()) if not recall.empty else float("nan"),
                        recall_median=r_med,
                        recall_q1=r_q1,
                        recall_q3=r_q3,
                        faults_hit=_count(sel.get("detected")),
                        faults_missed=_count(sel.get("missed")),
                        n_delay=n_delay,
                        delay_median=d_med,
                        delay_q1=d_q1,
                        delay_q3=d_q3,
                        false_alarms_per_hour=float(fa.median()) if not fa.empty else float("nan"),
                    )
                )
    return cells


def recall_zero_crossing(cells: Iterable[RecallCell]) -> dict[str, ZeroCrossing]:
    """Per scenario, the two rates the zero crossing sits between, from the pooled rows.

    Reported as a bracket rather than a point because a bracket is what a grid of rates can
    support. ``located_to`` is the factor between the two: with rates 10 and 20 either side, the
    crossing is known to within a factor of two and no better, and saying "about fifteen" would be
    an interpolation between one measurement and another on a curve with no assumed shape.

    A scenario whose recall never reaches zero, and one already at zero on the densest rate run,
    both get ``located_to = None``. They are different statements -- the second one means the
    crossing is somewhere denser than anything in the grid -- so the two bracket fields distinguish
    them.
    """
    out: dict[str, ZeroCrossing] = {}
    pooled = [c for c in cells if c.estimator == POOLED]
    for scenario in dict.fromkeys(c.scenario for c in pooled):
        ladder = sorted(
            (c for c in pooled if c.scenario == scenario), key=lambda c: c.reference_every_n
        )
        last_positive: int | None = None
        first_zero: int | None = None
        for cell in ladder:
            if cell.recall_mean > 0.0:
                # Only rates denser than the first zero count: a lone positive cell beyond it
                # would not re-open a crossing that has already been passed.
                if first_zero is None:
                    last_positive = cell.reference_every_n
            elif first_zero is None:
                first_zero = cell.reference_every_n
        located = (
            first_zero / last_positive
            if first_zero is not None and last_positive is not None
            else None
        )
        out[scenario] = ZeroCrossing(
            scenario=scenario,
            last_positive=last_positive,
            first_zero=first_zero,
            located_to=located,
        )
    return out


#: What a governed-minus-ungoverned difference needs on the frame. Checked once and named, so a
#: sweep that cannot support the reduction is told which column is missing rather than raising a
#: KeyError from inside the pairing.
_GOVERNANCE_COLUMNS = ("seed", "control_enabled", "mae_kg", "bias_kg")


def _require_governance_columns(frame: pd.DataFrame) -> None:
    missing = [c for c in _GOVERNANCE_COLUMNS if c not in frame.columns]
    if missing:
        raise ValueError(
            f"no governed-minus-ungoverned difference can be taken from this frame: it is "
            f"missing {', '.join(missing)}. The sweep must declare `control_arms: [true, false]` "
            "and score both error and signed bias."
        )
    if frame["control_enabled"].nunique(dropna=False) < 2:
        raise ValueError(
            "this frame has one control arm, so there is no governed-minus-ungoverned difference "
            "to take. The sweep must declare `control_arms: [true, false]`."
        )


def _paired(sel: pd.DataFrame, column: str) -> tuple[pd.Series, pd.Series]:
    """The governed and ungoverned series for one cell, indexed by seed and aligned.

    Refuses rather than aligns away a seed present in one arm only, and a seed appearing twice in
    one arm -- the same two failures `compare.py` refuses, for the same reason. A dropped seed
    changes what the median is over without changing anything visible about it, and a duplicated
    one makes the difference depend on which of the two rows pandas happened to keep.
    """
    arms = {}
    for governed in (True, False):
        side = sel[sel["control_enabled"].fillna(False).astype(bool) == governed]
        series = pd.to_numeric(side.set_index("seed")[column], errors="coerce")
        if series.index.has_duplicates:
            dupes = sorted(set(series.index[series.index.duplicated()]))
            name = "governed" if governed else "ungoverned"
            raise ValueError(
                f"the {name} arm has more than one run for seed(s) {dupes}: an axis is free that "
                f"pairing does not account for. Hold it fixed before differencing."
            )
        arms[governed] = series

    only_governed = set(arms[True].index) - set(arms[False].index)
    only_open = set(arms[False].index) - set(arms[True].index)
    if only_governed or only_open:
        raise ValueError(
            f"unpaired seeds: {sorted(only_governed)} ran governed only and {sorted(only_open)} "
            "ungoverned only. The effect is a within-seed difference, so a seed present in one arm "
            "contributes nothing and dropping it silently would change what the median is over."
        )
    seeds = sorted(arms[True].index)
    return arms[True].loc[seeds], arms[False].loc[seeds]


def governance_by_rate(frame: pd.DataFrame) -> list[GovernanceCell]:
    """Governed minus ungoverned, paired by seed, against reference rate.

    One cell per (scenario, estimator, rate). No pooled row here: the whole finding is that the
    three estimators behave differently, and a row averaging a -40 kg effect with two zeros would
    describe none of them.
    """
    _require_governance_columns(frame)
    usable = _usable(_require_rate_axis(frame))
    if usable.empty:
        return []

    cells: list[GovernanceCell] = []
    for scenario in dict.fromkeys(usable["scenario"]):
        for estimator in sorted(dict.fromkeys(usable["estimator"])):
            same = (usable["scenario"] == scenario) & (usable["estimator"] == estimator)
            for rate in sorted(dict.fromkeys(usable[same]["reference_every_n"])):
                sel = usable[same & (usable["reference_every_n"] == rate)]
                if sel.empty:
                    continue
                mae_gov, mae_open = _paired(sel, "mae_kg")
                bias_gov, bias_open = _paired(sel, "bias_kg")
                mae_d = mae_gov - mae_open
                bias_d = bias_gov - bias_open
                recal = pd.to_numeric(
                    sel[sel["control_enabled"].fillna(False).astype(bool)].get(
                        "recalibrations", pd.Series(dtype=float)
                    ),
                    errors="coerce",
                ).dropna()
                m_med, m_q1, m_q3, n = _quantiles(mae_d)
                b_med, b_q1, b_q3, _ = _quantiles(bias_d)
                cells.append(
                    GovernanceCell(
                        scenario=str(scenario),
                        estimator=str(estimator),
                        reference_every_n=int(rate),
                        n_pairs=n,
                        n_identical=int((mae_d == 0.0).sum()),
                        mae_median=m_med,
                        mae_q1=m_q1,
                        mae_q3=m_q3,
                        mae_difference_of_medians=float(mae_gov.median() - mae_open.median()),
                        mae_governed=float(mae_gov.median()),
                        mae_open=float(mae_open.median()),
                        bias_median=b_med,
                        bias_q1=b_q1,
                        bias_q3=b_q3,
                        bias_governed=float(bias_gov.median()),
                        bias_open=float(bias_open.median()),
                        recalibrations=float(recal.median()) if not recal.empty else float("nan"),
                    )
                )
    return cells


def governance_differences(frame: pd.DataFrame) -> pd.DataFrame:
    """One row per (scenario, estimator, rate, seed): the paired differences themselves.

    The aggregates in :func:`governance_by_rate` are medians over these. They are exported and
    drawn as well as summarised because a median of 0.00 kg over thirty pairs and a median of
    0.00 kg over thirty pairs that each moved by 40 kg in opposite directions are the same number
    and not the same result.
    """
    _require_governance_columns(frame)
    usable = _usable(_require_rate_axis(frame))
    rows: list[dict[str, Any]] = []
    for scenario in dict.fromkeys(usable["scenario"]):
        for estimator in sorted(dict.fromkeys(usable["estimator"])):
            same = (usable["scenario"] == scenario) & (usable["estimator"] == estimator)
            for rate in sorted(dict.fromkeys(usable[same]["reference_every_n"])):
                sel = usable[same & (usable["reference_every_n"] == rate)]
                if sel.empty:
                    continue
                mae_gov, mae_open = _paired(sel, "mae_kg")
                bias_gov, bias_open = _paired(sel, "bias_kg")
                for seed in mae_gov.index:
                    rows.append(
                        {
                            "scenario": scenario,
                            "estimator": estimator,
                            "reference_every_n": int(rate),
                            "seed": int(seed),
                            "mae_governed_kg": float(mae_gov[seed]),
                            "mae_open_kg": float(mae_open[seed]),
                            "d_mae_kg": float(mae_gov[seed] - mae_open[seed]),
                            "bias_governed_kg": float(bias_gov[seed]),
                            "bias_open_kg": float(bias_open[seed]),
                            "d_bias_kg": float(bias_gov[seed] - bias_open[seed]),
                        }
                    )
    return pd.DataFrame(rows)


# -- the written report -----------------------------------------------------------------------


def _iqr(median: float, q1: float, q3: float, spec: str = "{:.2f}") -> str:
    if not np.isfinite(median):
        return "--"
    return f"{spec.format(median)} [{spec.format(q1)}, {spec.format(q3)}]"


def _crossing_sentence(cross: ZeroCrossing) -> str:
    if cross.first_zero is None:
        return (
            f"**{cross.scenario}**: recall is above zero at every rate run, down to one in "
            f"{cross.last_positive}. The crossing is sparser than this grid reaches."
        )
    if cross.last_positive is None:
        return (
            f"**{cross.scenario}**: recall is already zero at one in {cross.first_zero}, the "
            "densest rate run. The crossing is denser than this grid reaches and is not bracketed."
        )
    return (
        f"**{cross.scenario}**: recall crosses zero between one reference in "
        f"{cross.last_positive} and one in {cross.first_zero} -- located to within a factor of "
        f"{cross.located_to:.2g}, which is the resolution of the rate ladder and not a property "
        "of the detector."
    )


def reference_curve_markdown(frame: pd.DataFrame, *, experiment_id: str, git_commit: str) -> str:
    """Both tables and both readings, self-contained enough to write a section from."""
    usable = _usable(_require_rate_curve(frame))
    recall_cells = recall_by_rate(frame)
    crossings = recall_zero_crossing(recall_cells)
    failed = int(frame["failed"].fillna(False).sum()) if "failed" in frame else 0

    lines = [
        f"# The reference-rate curve: {experiment_id}",
        "",
        f"Commit `{git_commit}`. {len(frame)} runs"
        + (f", {failed} failed and excluded." if failed else ".")
        + f" Rates run: {', '.join('1 in ' + str(int(r)) for r in sorted(set(usable['reference_every_n'])))}.",
        "",
        "## A1 -- detection recall against reference rate",
        "",
        "**Governed arm only.** With the controller disabled the detectors are never constructed, "
        "so every ungoverned run in this sweep reports `alarms 0, detected 0, recall 0.000`. Those "
        "are structural zeros and pooling the two arms would halve every recall below while "
        "presenting 'the detector was not running' as 'the detector missed'.",
        "",
        "Recall is `detected / (detected + missed)` over the calibration faults injected into the "
        "scenario, crediting only alarms that fired *after* a fault and within the scoring "
        "horizon. The mean is given as well as the median because recall over two or three "
        "injected faults takes a few discrete values, and a cell that plainly detected something "
        "can still have a median of 0.000. Detection delay is a median over the runs that detected "
        "anything at all; `n delay` says how many those were, and a run that detected nothing "
        "contributes no delay rather than a zero.",
        "",
        "| scenario | estimator | 1 in | runs | recall mean | recall median (IQR) | hit | missed | "
        "n delay | delay s (IQR) | false alarms/h |",
        "| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |",
    ]
    for cell in recall_cells:
        recall_cols = (
            f"{cell.recall_mean:.3f} | "
            + _iqr(cell.recall_median, cell.recall_q1, cell.recall_q3, "{:.3f}")
            if cell.recall_defined
            else "undefined (no faults) | undefined (no faults)"
        )
        lines.append(
            f"| {cell.scenario} | {cell.estimator} | {cell.reference_every_n} | {cell.n_runs} | "
            f"{recall_cols} | {cell.faults_hit} | {cell.faults_missed} | {cell.n_delay} | "
            + _iqr(cell.delay_median, cell.delay_q1, cell.delay_q3, "{:.0f}")
            + f" | {cell.false_alarms_per_hour:.2f} |"
        )

    lines += ["", "### Where recall crosses zero", ""]
    lines += [f"- {_crossing_sentence(c)}" for c in crossings.values()]
    lines += [
        "",
        "The crossing is reported as a bracket because a bracket is what a ladder of rates can "
        "support. Interpolating a point inside it would assume a curve shape nothing here "
        "measures.",
        "",
    ]

    if all(c in usable.columns for c in _GOVERNANCE_COLUMNS) and (
        usable["control_enabled"].nunique() > 1
    ):
        gov_cells = governance_by_rate(frame)
        lines += [
            "## A2 -- the governance effect against reference rate",
            "",
            "Governed minus ungoverned over a byte-identical stream, **paired by seed**: the "
            "median of the per-seed differences, which is not the difference of the medians. Both "
            "are given so the two can be seen not to be the same number. Negative MAE is the loop "
            "helping.",
            "",
            "**Signed bias travels beside the error and is never folded into it.** The loop can "
            "improve MAE while pushing the signed bias through zero and out the other side; a "
            "column of `|bias|` would show that as unambiguous improvement. `identical` counts the "
            "seeds whose two arms produced exactly the same MAE, which is what a median of 0.00 "
            "has to be read against.",
            "",
            "| scenario | estimator | 1 in | pairs | identical | dMAE kg (IQR) | diff of medians | "
            "MAE gov | MAE open | dBias kg (IQR) | bias gov | bias open | recals |",
            "| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |",
        ]
        for cell in gov_cells:
            lines.append(
                f"| {cell.scenario} | {cell.estimator} | {cell.reference_every_n} | "
                f"{cell.n_pairs} | {cell.n_identical} | "
                + _iqr(cell.mae_median, cell.mae_q1, cell.mae_q3)
                + f" | {cell.mae_difference_of_medians:+.2f} | {cell.mae_governed:.2f} | "
                f"{cell.mae_open:.2f} | "
                + _iqr(cell.bias_median, cell.bias_q1, cell.bias_q3)
                + f" | {cell.bias_governed:+.2f} | {cell.bias_open:+.2f} | "
                f"{cell.recalibrations:.1f} |"
            )
        lines.append("")

    return "\n".join(lines)


def write_reference_curve(
    frame: pd.DataFrame, *, out_dir: Path | str, experiment_id: str, git_commit: str
) -> Path:
    """Write ``reference_curve.md`` beside the sweep's parquet, and the per-cell CSVs."""
    _require_rate_curve(frame)
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    text = reference_curve_markdown(frame, experiment_id=experiment_id, git_commit=git_commit)
    path = out / "reference_curve.md"
    path.write_text(f"{text}\n", encoding="utf-8")

    def _frame_of(cells: list[Any]) -> pd.DataFrame:
        return pd.DataFrame(
            [
                vars(c) if not hasattr(c, "__slots__") else {f: getattr(c, f) for f in c.__slots__}
                for c in cells
            ]
        )

    _frame_of(recall_by_rate(frame)).to_csv(out / "recall_by_rate.csv", index=False)
    if all(c in frame.columns for c in _GOVERNANCE_COLUMNS) and (
        frame["control_enabled"].nunique() > 1
    ):
        _frame_of(governance_by_rate(frame)).to_csv(out / "governance_by_rate.csv", index=False)
        governance_differences(frame).to_csv(out / "governance_pairs_long.csv", index=False)
    return path
