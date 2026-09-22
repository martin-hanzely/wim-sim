"""Paired significance testing over seeds: Wilcoxon signed-rank with Holm correction.

Until this existed every number the project reported was descriptive, and the manuscript had to say
so. What makes a test possible here is that runs are **paired by seed**: the same seed gives a
byte-identical sample stream, so the controller-on and controller-off arms of a comparison differ in
exactly one thing. That is the setting signed-rank is for.

**Wilcoxon rather than a t-test**, because nothing here is known to be normal and several
distributions are visibly not -- MAE across seeds on S6 spans 640 to 745 kg with three points, and a
scenario with an injected fault produces a mixture rather than a bell.

**Holm rather than Bonferroni**, because Holm is uniformly more powerful at the same family-wise
error rate and there is no reason to accept the weaker one. The family is declared explicitly by the
caller: correcting over "every test I ran" and correcting over "the seven scenarios in this table"
are different claims, and which one is being made has to be a decision rather than an accident.

**What this cannot fix.** A p-value over three seeds is nearly meaningless -- the smallest attainable
two-sided p for n=3 is 0.25, so *nothing* can reach 0.05. Thirty seeds make the test possible. It
still does not address the deeper problem that the estimator hyperparameters were tuned on the same
scenarios used to evaluate them; see ``export/OPEN.md``.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import numpy as np

__all__ = ["PairedTest", "holm", "min_attainable_p", "wilcoxon_signed_rank"]


@dataclass(frozen=True, slots=True)
class PairedTest:
    """One paired comparison, before and after correction."""

    label: str
    n_pairs: int
    median_a: float
    median_b: float
    median_difference: float
    """Median of the per-seed differences (b - a). Not the difference of medians, which is not the
    same quantity and is not what the test is about."""
    effect_size: float
    """Matched-pairs rank-biserial correlation, in [-1, 1]. Reported because a p-value says whether
    a difference is detectable and says nothing at all about whether it matters."""
    statistic: float
    p_value: float
    p_holm: float = float("nan")
    significant: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "label": self.label,
            "n_pairs": self.n_pairs,
            "median_a": self.median_a,
            "median_b": self.median_b,
            "median_difference": self.median_difference,
            "effect_size_rank_biserial": self.effect_size,
            "statistic": self.statistic,
            "p_value": self.p_value,
            "p_holm": self.p_holm,
            "significant_at_0.05": self.significant,
        }


def min_attainable_p(n_pairs: int) -> float:
    """The smallest two-sided p-value the test can produce with this many pairs.

    Worth calling before believing a null result. With three seeds it is 0.25, so no comparison can
    reach 0.05 however large the effect -- a fact about the sample size, not about the system.
    """
    if n_pairs < 1:
        return float("nan")
    return min(2.0 / (2.0**n_pairs), 1.0)


def wilcoxon_signed_rank(a: list[float], b: list[float], *, label: str = "") -> PairedTest:
    """Two-sided Wilcoxon signed-rank on paired samples, with a rank-biserial effect size.

    ``a`` and ``b`` are matched element-wise -- element *i* of each must be the same seed. Pairs
    whose difference is exactly zero are discarded, which is Wilcoxon's own convention and which
    matters here: several comparisons in this project produce *identical* values with the controller
    on and off, and those pairs carry no information about a difference.
    """
    from scipy import stats

    x = np.asarray(a, dtype=np.float64)
    y = np.asarray(b, dtype=np.float64)
    if x.shape != y.shape:
        raise ValueError(f"paired samples must be the same length; got {x.shape} and {y.shape}")

    keep = np.isfinite(x) & np.isfinite(y)
    x, y = x[keep], y[keep]
    diff = y - x
    nonzero = diff != 0.0

    median_a = float(np.median(x)) if x.size else float("nan")
    median_b = float(np.median(y)) if y.size else float("nan")
    median_diff = float(np.median(diff)) if diff.size else float("nan")

    if nonzero.sum() < 1:
        # Every pair identical. Not a failure and not a null result to be reported as one: the two
        # arms produced the same numbers, which is itself the finding.
        return PairedTest(label, int(x.size), median_a, median_b, 0.0, 0.0, float("nan"), 1.0)

    statistic, p_value = stats.wilcoxon(x, y, zero_method="wilcox", alternative="two-sided")

    # Matched-pairs rank-biserial: (W+ - W-) / sum of ranks.
    d = diff[nonzero]
    ranks = stats.rankdata(np.abs(d))
    total = ranks.sum()
    effect = float((ranks[d > 0].sum() - ranks[d < 0].sum()) / total) if total else 0.0

    return PairedTest(
        label=label,
        n_pairs=int(nonzero.sum()),
        median_a=median_a,
        median_b=median_b,
        median_difference=median_diff,
        effect_size=effect,
        statistic=float(statistic),
        p_value=float(p_value),
    )


def holm(tests: list[PairedTest], *, alpha: float = 0.05) -> list[PairedTest]:
    """Holm-Bonferroni step-down correction over a declared family.

    The family is whatever the caller passes, and that is deliberate: correcting over one table and
    correcting over every test in the paper are different claims, and the choice should be visible
    at the call site rather than buried here.

    Holm rather than Bonferroni because it controls the same family-wise error rate with uniformly
    more power. Adjusted p-values are made monotone, so a later test can never be reported as more
    significant than an earlier one it did not beat.
    """
    if not tests:
        return []
    order = sorted(range(len(tests)), key=lambda i: tests[i].p_value)
    m = len(tests)
    adjusted = [0.0] * m
    running = 0.0
    for rank, idx in enumerate(order):
        value = (m - rank) * tests[idx].p_value
        running = max(running, value)  # monotone by construction
        adjusted[idx] = min(running, 1.0)

    return [
        PairedTest(
            label=t.label,
            n_pairs=t.n_pairs,
            median_a=t.median_a,
            median_b=t.median_b,
            median_difference=t.median_difference,
            effect_size=t.effect_size,
            statistic=t.statistic,
            p_value=t.p_value,
            p_holm=adjusted[i],
            significant=bool(adjusted[i] <= alpha),
        )
        for i, t in enumerate(tests)
    ]
