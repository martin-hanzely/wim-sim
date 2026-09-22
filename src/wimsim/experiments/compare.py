"""Paired comparisons over a sweep's results, with the family declared rather than assumed.

:mod:`wimsim.experiments.stats` performs one test. This decides *which* tests to perform and what
family they are corrected over, which is the part that determines what the resulting p-values mean.

**The family is the argument, not a default.** Correcting over the seven scenarios of one table and
correcting over every test in a paper are different claims about the same numbers. Each
:func:`compare_*` here declares one family and corrects within it; combining two of them into one
claim means correcting again, which is the caller's decision to make explicitly.

**Pairing is by seed within one cell of every other axis.** A sweep that varies the reference rate
or the edge config has more than one run per seed, so seed alone does not name a run; those axes are
held fixed and compared within rather than pooled over, and a seed that still names two runs is
refused rather than resolved.

**Pairing is by seed and nothing else.** The same seed gives a byte-identical sample stream, so an
arm-to-arm comparison at fixed seed differs in one thing. Any comparison that cannot be paired that
way -- different scenarios, different durations -- is not attempted here, because an unpaired
signed-rank test would be a different and weaker instrument wearing the same name.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pandas as pd

from wimsim.experiments.stats import PairedTest, holm, min_attainable_p, wilcoxon_signed_rank

__all__ = [
    "compare_arms",
    "compare_estimators",
    "comparison_markdown",
    "family_report",
    "write_comparison",
]


#: Sweep axes other than scenario, estimator and seed. A frame with one of these left free has more
#: than one run per seed per arm, so pairing by seed alone would compare runs that differ in two
#: things. The comparisons below hold them fixed rather than pooling over them.
_FREE_AXES = ("reference_every_n", "edge_config", "station", "control_enabled")


def _free_axes(frame: pd.DataFrame, *, exclude: tuple[str, ...] = ()) -> list[str]:
    """Axes present in the frame, varying, and not already being compared across."""
    return [
        name
        for name in _FREE_AXES
        if name not in exclude and name in frame.columns and frame[name].nunique(dropna=False) > 1
    ]


def _cells(frame: pd.DataFrame, axes: list[str]):
    """``(label suffix, sub-frame)`` for each combination of the free axes. One cell if there are
    none."""
    if not axes:
        yield "", frame
        return
    for values, group in frame.groupby(axes, sort=True, dropna=False):
        values = values if isinstance(values, tuple) else (values,)
        yield " / ".join(f"{a}={v}" for a, v in zip(axes, values, strict=True)), group


def _paired(
    frame: pd.DataFrame, metric: str, mask_a: pd.Series, mask_b: pd.Series
) -> tuple[list[float], list[float]]:
    """Values for two arms, aligned on seed. Seeds present in only one arm are dropped.

    A seed naming more than one run in either arm is refused rather than resolved. Taking the first
    would produce a table that looks paired and is not, which is the failure this whole module
    exists to make impossible.
    """
    a = frame[mask_a].set_index("seed")[metric]
    b = frame[mask_b].set_index("seed")[metric]
    for side, series in (("A", a), ("B", b)):
        if series.index.has_duplicates:
            dupes = sorted(set(series.index[series.index.duplicated()]))
            raise ValueError(
                f"arm {side} has more than one run for seed(s) {dupes}: an axis is free that "
                f"pairing does not account for. Hold it fixed before comparing."
            )
    shared = sorted(set(a.index) & set(b.index))
    return [float(a.loc[s]) for s in shared], [float(b.loc[s]) for s in shared]


def compare_arms(
    frame: pd.DataFrame,
    *,
    metric: str = "mae_kg",
    alpha: float = 0.05,
) -> list[PairedTest]:
    """Controller on against controller off, per (scenario, estimator), corrected as one family.

    The family is every scenario/estimator cell in the frame, because the claim being made is about
    the loop in general rather than about one scenario. A claim about a single scenario would be a
    family of one and would not need correcting at all -- which is exactly why the choice has to be
    visible.
    """
    if "control_enabled" not in frame.columns:
        return []
    if frame["control_enabled"].fillna(False).astype(bool).nunique() < 2:
        # One arm only. There is no comparison to make, which is different from a comparison that
        # could not be paired, and the caller distinguishes them with `family_report(note=...)`.
        return []
    axes = _free_axes(frame, exclude=("control_enabled",))
    tests: list[PairedTest] = []
    for (scenario, estimator), group in frame.groupby(["scenario", "estimator"], sort=True):
        for suffix, cell in _cells(group, axes):
            on = cell["control_enabled"].fillna(False).astype(bool)
            a, b = _paired(cell, metric, ~on, on)
            if len(a) < 2:
                continue
            label = " / ".join(filter(None, (scenario, suffix, estimator, "loop off->on")))
            tests.append(wilcoxon_signed_rank(a, b, label=label))
    return holm(tests, alpha=alpha)


def compare_estimators(
    frame: pd.DataFrame,
    *,
    baseline: str = "static_affine",
    metric: str = "mae_kg",
    alpha: float = 0.05,
) -> list[PairedTest]:
    """Every estimator against a baseline, per scenario, corrected as one family.

    Paired by seed against the baseline's run on the same seed and scenario -- the same stream, a
    different estimator reading it.
    """
    tests: list[PairedTest] = []
    estimators = sorted(set(frame["estimator"]) - {baseline})
    axes = _free_axes(frame)
    for scenario, group in frame.groupby("scenario", sort=True):
        for suffix, cell in _cells(group, axes):
            base = cell["estimator"] == baseline
            if not base.any():
                continue
            for estimator in estimators:
                a, b = _paired(cell, metric, base, cell["estimator"] == estimator)
                if len(a) < 2:
                    continue
                label = " / ".join(filter(None, (scenario, suffix, f"{baseline}->{estimator}")))
                tests.append(wilcoxon_signed_rank(a, b, label=label))
    return holm(tests, alpha=alpha)


def family_report(
    tests: list[PairedTest], *, metric: str, family: str, note: str = ""
) -> dict[str, Any]:
    """A family's results plus the facts needed to read them honestly.

    ``note`` says why a family is empty when it is empty by design -- an axis the sweep did not
    vary is not a comparison that failed.

    ``floor_p`` is the smallest p-value the smallest test in the family could have produced. If a
    null result sits above it, the test had no power to find anything and reporting "no significant
    difference" would be reporting the sample size.
    """
    if not tests:
        return {"family": family, "metric": metric, "n_tests": 0, "note": note, "tests": []}
    smallest = min(t.n_pairs for t in tests)
    return {
        "family": family,
        "metric": metric,
        "n_tests": len(tests),
        "min_pairs": smallest,
        "floor_p": min_attainable_p(smallest),
        "n_significant": sum(t.significant for t in tests),
        "tests": [t.to_dict() | {"verdict": _verdict(t)} for t in tests],
    }


def _verdict(test: PairedTest) -> str:
    """What the test actually found, in words, distinguishing the three outcomes that get confused.

    "No significant difference" is a claim that a difference was looked for and not found. It is
    wrong for two of the three cases here: arms that produced identical numbers (the loop never
    fired) and families too small to reach 0.05 at all.
    """
    if test.median_difference == 0.0 and test.effect_size == 0.0:
        return "identical -- the two arms produced the same numbers"
    if test.significant:
        direction = "better" if test.median_difference < 0 else "worse"
        return f"{direction} (p_holm = {test.p_holm:.3g})"
    return f"not separated (p_holm = {test.p_holm:.3g})"


_HEADER = "| comparison | n | median A | median B | median diff | effect | p | p (Holm) | verdict |"
_RULE = "| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | --- |"


def comparison_markdown(reports: list[dict[str, Any]]) -> str:
    """One table per family, each headed by the family it was corrected over.

    The family is printed because a p-value corrected over four tests and one corrected over forty
    are different numbers, and a table that omits it leaves the reader to assume whichever family
    flatters the result.
    """
    lines: list[str] = ["# Paired comparisons", ""]
    lines += [
        "Wilcoxon signed-rank on runs paired by seed, Holm-corrected within each family below.",
        "Median diff is the median of the per-seed differences (B - A), which is not the difference",
        "of the medians. Effect is the matched-pairs rank-biserial correlation.",
        "",
    ]
    for report in reports:
        lines += [f"## {report['family']}  (`{report['metric']}`)", ""]
        if not report.get("n_tests"):
            lines += [report.get("note") or "No comparison in this family could be paired.", ""]
            continue
        floor = report["floor_p"]
        lines += [
            f"{report['n_tests']} tests, {report['n_significant']} significant at 0.05 "
            f"after correction. The smallest test in the family rests on "
            f"{report['min_pairs']} pair(s) with a nonzero difference -- pairs that came out "
            "exactly equal carry no information about a difference and are Wilcoxon's own "
            "discards, so that count and not the seed count is what sets the power.",
            "",
        ]
        if floor > 0.05:
            lines += [
                f"**No test in this family could have reached 0.05.** With {report['min_pairs']} "
                f"nonzero pair(s) the smallest attainable two-sided p is {floor:.3g}, so every null result "
                "below is a statement about the seed count and not about the system.",
                "",
            ]
        lines += [_HEADER, _RULE]
        for test in report["tests"]:
            lines.append(
                f"| {test['label']} | {test['n_pairs']} | {test['median_a']:.3g} | "
                f"{test['median_b']:.3g} | {test['median_difference']:+.3g} | "
                f"{test['effect_size_rank_biserial']:+.2f} | {test['p_value']:.3g} | "
                f"{test['p_holm']:.3g} | {test['verdict']} |"
            )
        lines.append("")
    return "\n".join(lines)


def write_comparison(
    frame: pd.DataFrame,
    *,
    out_dir: Path | str,
    experiment_id: str,
    baseline: str = "static_affine",
    metric: str = "mae_kg",
) -> list[Path]:
    """Write ``comparisons.md`` and ``comparisons.json`` beside a sweep's other results.

    Two families, corrected separately and labelled as such: the controller's two arms, and every
    estimator against a baseline. They are not combined, because a reader who wants them corrected
    as one family is making a different claim and should have to say so.
    """
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)

    reports = [
        family_report(
            compare_arms(frame, metric=metric),
            metric=metric,
            family="control loop off vs on, every scenario and estimator",
            note=(
                ""
                if "control_enabled" in frame.columns
                and frame["control_enabled"].nunique(dropna=False) > 1
                else "The controller was not an axis in this sweep: every run is on the same arm, "
                "so there is no off-against-on comparison to make here."
            ),
        ),
        family_report(
            compare_estimators(frame, baseline=baseline, metric=metric),
            metric=metric,
            family=f"every estimator against {baseline}, every scenario",
        ),
    ]
    payload = {"experiment_id": experiment_id, "metric": metric, "families": reports}
    md = out / "comparisons.md"
    js = out / "comparisons.json"
    md.write_text(comparison_markdown(reports) + "\n", encoding="utf-8")
    js.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return [md, js]
