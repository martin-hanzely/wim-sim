"""Paired significance testing over seeds.

Runs are paired by seed -- the same seed gives a byte-identical sample stream -- so the two arms of
a comparison differ in exactly one thing. That is what makes signed-rank applicable at all.

These tests are mostly about the ways a significance claim goes wrong: a family declared by
accident, a null result that was never attainable, an effect size confused with a p-value, and an
adjusted p-value that is not monotone in its own ranking.
"""

from __future__ import annotations

import pytest

from wimsim.experiments.stats import PairedTest, holm, min_attainable_p, wilcoxon_signed_rank


def test_a_real_difference_is_detected_with_enough_pairs() -> None:
    a = [100.0 + i * 0.5 for i in range(30)]
    b = [x - 12.0 for x in a]
    result = wilcoxon_signed_rank(a, b, label="governed vs ungoverned")

    assert result.n_pairs == 30
    assert result.p_value < 0.001
    assert result.median_difference == pytest.approx(-12.0)
    assert result.effect_size == pytest.approx(-1.0), "every pair moved the same way"


def test_identical_arms_are_reported_as_identical_not_as_a_null_result() -> None:
    """Several comparisons in this project produce *exactly* the same numbers with the controller on
    and off -- the loop never fired. That is a finding, not a failed test, and it must not be
    reported as "no significant difference" as though a difference had been looked for and missed.
    """
    a = [100.0, 101.0, 102.0]
    result = wilcoxon_signed_rank(a, list(a), label="identical")

    assert result.median_difference == 0.0
    assert result.effect_size == 0.0
    assert result.p_value == 1.0


def test_three_seeds_cannot_reach_significance_however_large_the_effect() -> None:
    """The reason the seed count had to change. With three pairs the smallest attainable two-sided
    p is 0.25, so no comparison can clear 0.05 -- a fact about the sample size and not about the
    system. Reporting "not significant" from three seeds would be reporting the design.
    """
    assert min_attainable_p(3) == pytest.approx(0.25)
    assert min_attainable_p(30) < 1e-8

    a = [100.0, 200.0, 300.0]
    b = [1.0, 2.0, 3.0]  # enormous, consistent effect
    assert wilcoxon_signed_rank(a, b).p_value > 0.05


def test_the_effect_size_is_reported_beside_the_p_value() -> None:
    """A p-value says whether a difference is detectable and nothing about whether it matters. On
    thirty seeds a one-gram difference is significant; the effect size is what stops that being
    written up as a result."""
    a = [100.0 + i * 0.01 for i in range(30)]
    b = [x - 0.001 for x in a]
    result = wilcoxon_signed_rank(a, b)

    assert result.p_value < 0.05
    assert abs(result.median_difference) < 0.01, "detectable, and negligible"


def test_holm_is_more_powerful_than_bonferroni_at_the_same_family_rate() -> None:
    """Which is why it is used. The smallest p in a family of four is multiplied by 4 under either,
    but the second smallest is multiplied by 3 rather than 4, and so on."""
    tests = [
        PairedTest(f"t{i}", 30, 0.0, 0.0, 0.0, 0.0, 0.0, p)
        for i, p in enumerate([0.001, 0.012, 0.030, 0.400])
    ]
    corrected = holm(tests)

    assert corrected[0].p_holm == pytest.approx(0.004)  # 4 x 0.001
    assert corrected[1].p_holm == pytest.approx(0.036)  # 3 x 0.012, Bonferroni would give 0.048
    assert corrected[1].significant
    assert not corrected[3].significant


def test_adjusted_p_values_are_monotone_in_their_own_ranking() -> None:
    """Without the running maximum, a test with a larger raw p can come out with a smaller adjusted
    one, and a reader sorting the table finds it inconsistent with itself."""
    tests = [
        PairedTest(f"t{i}", 30, 0.0, 0.0, 0.0, 0.0, 0.0, p)
        for i, p in enumerate([0.02, 0.021, 0.022, 0.023])
    ]
    corrected = sorted(holm(tests), key=lambda t: t.p_value)
    adjusted = [t.p_holm for t in corrected]
    assert adjusted == sorted(adjusted)


def test_the_family_is_whatever_the_caller_declares() -> None:
    """Correcting over one table and over every test in the paper are different claims. Making the
    family an argument keeps the choice visible at the call site."""
    one = holm([PairedTest("a", 30, 0.0, 0.0, 0.0, 0.0, 0.0, 0.03)])
    many = holm([PairedTest(f"t{i}", 30, 0.0, 0.0, 0.0, 0.0, 0.0, 0.03) for i in range(10)])

    assert one[0].significant
    assert not many[0].significant, "the same p-value, in a family of ten, does not survive"


def test_an_empty_family_is_not_a_crash() -> None:
    assert holm([]) == []


def test_mismatched_pair_lengths_are_refused() -> None:
    """Pairing by seed is the assumption the whole test rests on; silently truncating would break
    it without saying so."""
    with pytest.raises(ValueError, match="same length"):
        wilcoxon_signed_rank([1.0, 2.0, 3.0], [1.0, 2.0])


def test_missing_values_drop_the_pair_not_the_run() -> None:
    """A seed whose run failed, or whose metric is undefined, cannot contribute to a paired test --
    but the surviving pairs still can."""
    a = [1.0, 2.0, float("nan"), 4.0]
    b = [2.0, 3.0, 5.0, 5.0]
    assert wilcoxon_signed_rank(a, b).n_pairs == 3
