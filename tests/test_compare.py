"""Which paired tests to run over a sweep, and what family they are corrected over.

`stats.py` performs one test; this decides which, and the family decision is what determines what
the p-values mean. These tests are about that decision and about the ways pairing silently breaks.
"""

from __future__ import annotations

import json

import pandas as pd
import pytest

from wimsim.experiments.compare import (
    _paired,
    compare_arms,
    compare_estimators,
    comparison_markdown,
    family_report,
    write_comparison,
)


def _frame(n_seeds: int = 30, *, effect: float = 20.0, scenarios=("S4_step_fault",)):
    """A sweep frame with the controller arm making a consistent difference."""
    rows = []
    for scenario in scenarios:
        for estimator in ("static_affine", "rls"):
            for seed in range(1, n_seeds + 1):
                base = 150.0 + seed * 0.3
                for on in (False, True):
                    rows.append(
                        {
                            "scenario": scenario,
                            "estimator": estimator,
                            "seed": seed,
                            "control_enabled": on,
                            "mae_kg": base - (effect if on and estimator == "static_affine" else 0),
                        }
                    )
    return pd.DataFrame(rows)


def test_a_consistent_arm_difference_is_detected_and_a_null_one_is_not() -> None:
    """The controller helps static_affine in this frame and does nothing for rls, which is the
    shape the real sweeps have."""
    tests = {t.label: t for t in compare_arms(_frame())}

    static = tests["S4_step_fault / static_affine / loop off->on"]
    rls = tests["S4_step_fault / rls / loop off->on"]

    assert static.significant and static.median_difference == pytest.approx(-20.0)
    assert not rls.significant
    assert rls.median_difference == 0.0


def test_pairing_is_by_seed_so_a_missing_seed_drops_the_pair_not_the_cell() -> None:
    """A run that failed leaves its seed present in one arm and absent from the other. Silently
    comparing unequal-length samples would turn a paired test into an unpaired one wearing the same
    name."""
    frame = _frame(n_seeds=30)
    frame = frame.drop(
        frame[(frame.seed == 7) & frame.control_enabled & (frame.estimator == "rls")].index
    )
    tests = {t.label: t for t in compare_arms(frame)}
    assert tests["S4_step_fault / rls / loop off->on"].n_pairs <= 29
    assert tests["S4_step_fault / static_affine / loop off->on"].n_pairs == 30


def test_the_family_is_every_cell_in_the_frame() -> None:
    """Two scenarios and two estimators is a family of four, and a p-value that survives a family of
    one may not survive that."""
    tests = compare_arms(_frame(scenarios=("S4_step_fault", "S6_combined")))
    assert len(tests) == 4
    assert all(t.p_holm >= t.p_value for t in tests), "correction can only make a p-value larger"


def test_a_cell_with_too_few_pairs_is_skipped_rather_than_tested() -> None:
    tests = compare_arms(_frame(n_seeds=1))
    assert tests == []


def test_estimators_are_compared_against_a_baseline_on_the_same_seed() -> None:
    frame = _frame(n_seeds=30)
    frame = frame[~frame.control_enabled]
    tests = compare_estimators(frame, baseline="static_affine")
    assert [t.label for t in tests] == ["S4_step_fault / static_affine->rls"]
    assert tests[0].n_pairs == 30


def test_the_report_carries_the_smallest_p_the_family_could_have_produced() -> None:
    """So a null result can be read correctly. Above this floor, the test had no power to find
    anything and "no significant difference" is a statement about the seed count.
    """
    three = family_report(compare_arms(_frame(n_seeds=3)), metric="mae_kg", family="arms")
    thirty = family_report(compare_arms(_frame(n_seeds=30)), metric="mae_kg", family="arms")

    assert three["floor_p"] == pytest.approx(0.25)
    assert three["n_significant"] == 0, "nothing can be significant at three seeds"
    assert thirty["floor_p"] < 1e-8
    assert thirty["n_significant"] >= 1


def test_a_frame_without_the_control_column_yields_no_arm_tests() -> None:
    frame = _frame().drop(columns=["control_enabled"])
    assert compare_arms(frame) == []


def test_an_empty_family_reports_zero_rather_than_failing() -> None:
    assert family_report([], metric="mae_kg", family="none")["n_tests"] == 0


def test_the_table_says_what_family_each_p_value_was_corrected_over() -> None:
    """A p-value is uninterpretable without it, and a table that omits it is inviting the reader
    to assume the most favourable family."""
    text = comparison_markdown(
        [family_report(compare_arms(_frame()), metric="mae_kg", family="loop off vs on")]
    )
    assert "loop off vs on" in text
    assert "2 tests" in text or "n_tests" in text.lower() or "tests: 2" in text


def test_a_null_result_is_printed_beside_the_smallest_p_it_could_have_had() -> None:
    """At three seeds nothing can clear 0.05, so "not significant" is a statement about the seed
    count. The floor has to be on the page next to it."""
    text = comparison_markdown(
        [family_report(compare_arms(_frame(n_seeds=3)), metric="mae_kg", family="arms")]
    )
    assert "0.25" in text
    assert "No test in this family could have reached" in text


def test_a_cell_where_the_two_arms_were_identical_is_not_called_a_null_result() -> None:
    """The loop never fired. Reporting that as "no significant difference" says a difference was
    looked for and not found, which is a different and wrong claim."""
    text = comparison_markdown(
        [family_report(compare_arms(_frame(effect=0.0)), metric="mae_kg", family="arms")]
    )
    assert "identical" in text.lower()


def test_writing_a_comparison_produces_both_a_table_and_the_numbers_behind_it(tmp_path) -> None:
    written = write_comparison(_frame(), out_dir=tmp_path, experiment_id="ladder30")
    names = {p.name for p in written}
    assert names == {"comparisons.md", "comparisons.json"}
    payload = json.loads((tmp_path / "comparisons.json").read_text(encoding="utf-8"))
    assert payload["experiment_id"] == "ladder30"
    assert {f["family"] for f in payload["families"]}


def test_a_seed_appearing_twice_in_one_arm_is_refused_rather_than_silently_halved() -> None:
    """The sweeps have axes beyond scenario/estimator/seed -- reference rate, edge config, station.
    With one of those left free a seed names two runs, and taking the first would produce a table
    that looks paired and is not.
    """
    frame = _frame(n_seeds=6)
    frame["reference_every_n"] = [10 if s <= 3 else 25 for s in frame.seed]

    with pytest.raises(ValueError, match="more than one run"):
        _paired(frame, "mae_kg", frame.estimator == "rls", frame.estimator == "static_affine")


def test_a_free_axis_is_held_fixed_rather_than_collapsed() -> None:
    """Two reference rates is two comparisons, not one comparison over twice the runs. Pooling
    them would compare a rate-10 run against a rate-25 run and call the difference the estimator."""
    frame = _frame(n_seeds=6)
    frame = frame[~frame.control_enabled].copy()
    frame["reference_every_n"] = [10 if s <= 3 else 25 for s in frame.seed]

    tests = compare_estimators(frame, baseline="static_affine")

    assert len(tests) == 2, "one comparison per rate"
    assert all(t.n_pairs <= 3 for t in tests)
    assert {t.label for t in tests} == {
        "S4_step_fault / reference_every_n=10 / static_affine->rls",
        "S4_step_fault / reference_every_n=25 / static_affine->rls",
    }


def test_an_axis_that_was_never_swept_is_not_reported_as_a_pairing_failure() -> None:
    """`ladder` runs one controller arm, so there is no off-vs-on comparison to make. Printing
    "could not be paired" there says the comparison was attempted and failed, which is a claim
    about the data rather than about the sweep's design."""
    frame = _frame()
    frame = frame[frame.control_enabled].copy()
    text = comparison_markdown(
        [family_report(compare_arms(frame), metric="mae_kg", family="arms", note="not an axis")]
    )
    assert "not an axis" in text
    assert "could not be paired" not in text
