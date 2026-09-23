"""The results table: the phase-6 checkpoint, as a file rather than as terminal output.

Buildspec: *"Checkpoint: a results table comparing all estimators across all scenarios."* Written
next to the parquet so a reader does not have to produce it, in Markdown because that is what goes
into a repository and a pull request, and in LaTeX because that is what goes into a paper. Both are
generated from the same frame, so they cannot disagree.

Two rules about how the numbers are presented, both of which exist to stop the table flattering the
system:

**A failed run appears.** It gets a row saying ``failed`` and its error. Averaging over the runs
that happened to succeed is how a sweep reports that everything is fine while a third of it fell
over.

**Every table names its provenance.** Experiment id, commit, and whether the tree was dirty. A dirty
tree means the commit does not identify the code that produced the numbers, so the table says so
rather than looking citable.
"""

from __future__ import annotations

from typing import Any

import pandas as pd

__all__ = ["detector_table", "latex_table", "markdown_table", "write_table"]

#: Column -> (heading, format). Ordered as a reader wants them: what the run was, then how accurate
#: it was, then what the control loop did, then what it cost.
COLUMNS: tuple[tuple[str, str, str], ...] = (
    ("scenario", "scenario", "{}"),
    ("estimator", "estimator", "{}"),
    ("seed", "seed", "{:.0f}"),
    # How many passes the row is a mean over. First of the numbers because everything to its right
    # is only as good as it is: `ladder` scored S1 on two passes -- 60 of its 62 crossings went to
    # the calibration window -- and a coverage of 0.5000 from two passes reads exactly like a
    # coverage of 0.5000 from four thousand unless the count is on the page.
    ("n_matched", "scored", "{:.0f}"),
    ("mae_kg", "MAE kg", "{:.2f}"),
    ("mape", "MAPE %", "{:.3%}"),
    ("bias_kg", "bias kg", "{:+.2f}"),
    ("dynamic_floor_kg", "floor kg", "{:.1f}"),
    ("coverage", "coverage", "{:.4f}"),
    ("mean_interval_width_kg", "width kg", "{:.0f}"),
    # Detection recall, not vehicle matching -- see `_ROW_TEMPLATE`. The two shared
    # this name until 2026-09-23 and the matching one was the one being lost.
    ("recall", "detect recall", "{:.3f}"),
    ("alarms", "alarms", "{:.0f}"),
    ("recalibrations", "recal", "{:.0f}"),
    ("detected", "faults hit", "{:.0f}"),
    ("missed", "missed", "{:.0f}"),
    ("false_alarms_per_hour", "FA/h", "{:.2f}"),
    ("reconverge_s", "reconv s", "{:.0f}"),
)


#: How many leading columns say *what the run was* rather than how it went. A failed row keeps
#: these and spends the rest on its error.
_IDENTITY = 3


def _cell(value: Any, spec: str) -> str:
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return "--"
    try:
        return spec.format(value)
    except (ValueError, TypeError):
        return str(value)


def _one_line(text: Any, limit: int = 160) -> str:
    """Collapse an exception into one line that fits in a table cell.

    Pydantic errors are several lines with a URL at the end; pasted verbatim they break out of the
    markdown row and take the rest of the table with them. The full text is in the parquet.
    """
    if not text:
        return "unknown error"
    joined = " ".join(str(text).split())
    joined = joined.replace("|", "/")  # a pipe would open a new cell
    return joined if len(joined) <= limit else joined[: limit - 1] + "..."


def _rows(frame: pd.DataFrame) -> list[list[str]]:
    ordered = frame.sort_values(
        [c for c in ("scenario", "estimator", "seed") if c in frame.columns]
    )
    out: list[list[str]] = []
    for row in ordered.to_dict("records"):
        if row.get("failed"):
            cells = [_cell(row.get(name), spec) for name, _h, spec in COLUMNS[:_IDENTITY]]
            # The error text, spanning the rest: a failed run has no numbers, and printing dashes
            # across a dozen columns hides *why* far more effectively than saying it once.
            cells.append(f"**failed** -- {_one_line(row.get('error'))}")
            cells += ["" for _ in COLUMNS[_IDENTITY + 1 :]]
            out.append(cells)
            continue
        out.append([_cell(row.get(name), spec) for name, _h, spec in COLUMNS])
    return out


def _header() -> list[str]:
    return [heading for _name, heading, _spec in COLUMNS]


def markdown_table(
    frame: pd.DataFrame, *, experiment_id: str, git_commit: str, git_dirty: bool = False
) -> str:
    header = _header()
    lines = [
        f"# Results: {experiment_id}",
        "",
        f"{len(frame)} runs, {int(frame['failed'].sum()) if 'failed' in frame else 0} failed. "
        f"Commit `{git_commit[:8]}`"
        + (" **(dirty tree -- these numbers are not citable)**" if git_dirty else "")
        + ".",
        "",
        "| " + " | ".join(header) + " |",
        "|" + "|".join("---" for _ in header) + "|",
    ]
    for row in _rows(frame):
        lines.append("| " + " | ".join(row) + " |")

    lines += [
        "",
        "`scored` is how many matched passes the row's statistics are a mean over; a short "
        "scenario can spend most of its crossings on the calibration window and leave very few. "
        "`floor` is the dynamic load error the vehicles brought with them: the part no calibration "
        "can remove, so an MAE below it would be a coincidence rather than a result. `FA/h` is "
        "false alarms per hour of simulated operation. `reconv s` is the time from the first "
        "injected fault until the error returned to its pre-fault level and stayed there; `--` "
        "means it never did, or that the run was too short to tell.",
    ]
    return "\n".join(lines) + "\n"


def latex_table(frame: pd.DataFrame, *, experiment_id: str, git_commit: str) -> str:
    """The same numbers, for a paper. Generated from the same frame so the two cannot disagree."""
    header = _header()
    lines = [
        "% Generated by wimsim; do not edit by hand.",
        f"% experiment: {experiment_id}  commit: {git_commit}",
        "\\begin{table}[t]",
        "  \\centering",
        "  \\small",
        "  \\begin{tabular}{" + "l" * 3 + "r" * (len(header) - 3) + "}",
        "    \\toprule",
        "    " + " & ".join(_escape(h) for h in header) + " \\\\",
        "    \\midrule",
    ]
    for row in _rows(frame):
        lines.append("    " + " & ".join(_escape(cell) for cell in row) + " \\\\")
    lines += [
        "    \\bottomrule",
        "  \\end{tabular}",
        f"  \\caption{{Estimator comparison across scenarios ({_escape(experiment_id)}).}}",
        f"  \\label{{tab:{experiment_id.replace('_', '-')}}}",
        "\\end{table}",
    ]
    return "\n".join(lines) + "\n"


def _escape(text: str) -> str:
    out = str(text)
    for char, replacement in (("_", r"\_"), ("%", r"\%"), ("&", r"\&"), ("#", r"\#")):
        out = out.replace(char, replacement)
    return out.replace("**", "")


def write_table(result: Any, spec: Any) -> None:
    """Write ``results.md`` and ``results.tex`` beside the parquet."""
    frame = result.frame
    if frame.empty:  # pragma: no cover - a sweep with no cells cannot be constructed
        return
    dirty = bool(frame["git_dirty"].any()) if "git_dirty" in frame else False

    (result.out_dir / "results.md").write_text(
        markdown_table(
            frame,
            experiment_id=spec.experiment_id,
            git_commit=result.git_commit,
            git_dirty=dirty,
        ),
        encoding="utf-8",
    )
    (result.out_dir / "results.tex").write_text(
        latex_table(frame, experiment_id=spec.experiment_id, git_commit=result.git_commit),
        encoding="utf-8",
    )


def _median_iqr(values: pd.Series, spec: str = "{:.2f}") -> str:
    """``median [q1, q3]`` over the finite values, or ``--`` if there are none.

    Medians rather than means throughout this table: detection delay over a handful of faults is a
    small, skewed sample, and one run that never detected drags a mean somewhere no run went.
    """
    finite = values.dropna()
    if finite.empty:
        return "--"
    q1, med, q3 = (float(finite.quantile(q)) for q in (0.25, 0.5, 0.75))
    return f"{spec.format(med)} [{spec.format(q1)}, {spec.format(q3)}]"


#: Column -> (heading, format) for the per-detector table. Recall first because it is the question,
#: false alarms beside it because either one alone can be made perfect by a useless detector.
_DETECTOR_COLUMNS = (
    ("recall", "detection recall (IQR)", "{:.3f}"),
    ("false_alarms_per_hour", "false alarms/h (IQR)", "{:.2f}"),
    ("mean_detection_delay_s", "detection delay s (IQR)", "{:.0f}"),
)


def detector_table(
    frame: pd.DataFrame, *, experiment_id: str, git_commit: str, by: str = "edge_config"
) -> str:
    """One row per scenario and detector arm: recall, false alarms, delay, each with its spread.

    Keyed on the detector arm as well as the scenario, because the sweep's whole purpose is that
    the arms differ; pooled on scenario alone the five arms become one row describing the ensemble
    under a heading that claims to compare them.

    Recall over a scenario with no injected fault is *undefined*, not zero, and is printed that way.
    A detector cannot miss what was never there, and a table that writes 0.000 into that cell says
    the opposite of what happened.
    """
    if by not in frame.columns or frame[by].nunique(dropna=False) < 2:
        raise ValueError(
            f"this frame carries one detector arm ({by!r} does not vary), so a per-detector "
            "comparison cannot be made from it. Run `configs/experiments/detectors.yaml`."
        )

    failed_mask = (
        frame["failed"].fillna(False).astype(bool)
        if "failed" in frame
        else pd.Series(False, index=frame.index)
    )
    usable = frame[~failed_mask]

    lines = [
        f"# Detectors: {experiment_id}",
        "",
        f"Commit `{git_commit}`. {len(frame)} runs"
        + (
            f", {int(failed_mask.sum())} failed and excluded from the medians."
            if failed_mask.any()
            else "."
        ),
        "",
        "Median across seeds with the interquartile range beside it. `runs` is how many runs each "
        "cell is a median over -- a median over five seeds and a median over one look identical "
        "otherwise.",
        "",
        "| scenario | detector | runs | faults hit | missed | "
        + " | ".join(h for _c, h, _f in _DETECTOR_COLUMNS)
        + " |",
        "| --- | --- | ---: | ---: | ---: | "
        + " | ".join("---:" for _ in _DETECTOR_COLUMNS)
        + " |",
    ]

    for scenario in dict.fromkeys(usable["scenario"]):
        for arm in sorted(dict.fromkeys(usable[by])):
            cell = usable[(usable["scenario"] == scenario) & (usable[by] == arm)]
            if cell.empty:
                continue
            hit = int(cell["detected"].fillna(0).sum())
            missed = int(cell["missed"].fillna(0).sum())
            values = []
            for column, _heading, spec in _DETECTOR_COLUMNS:
                if column == "recall" and hit + missed == 0:
                    # No fault was injected in this scenario, so there was nothing to recall.
                    values.append("undefined (no faults)")
                else:
                    values.append(_median_iqr(cell[column], spec))
            lines.append(
                f"| {scenario} | {arm} | {len(cell)} | {hit} | {missed} | "
                + " | ".join(values)
                + " |"
            )

    lines += [
        "",
        "Recall and false alarms are read together or not at all: a detector that alarms on every "
        "window has perfect recall, and one that never alarms has no false alarms.",
        "",
    ]
    return "\n".join(lines)
