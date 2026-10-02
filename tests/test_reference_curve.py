"""The reference rate as the binding constraint.

Two relationships live in the `reference_rate` sweeps and nowhere in the export: detection recall
against reference rate, and the governed-minus-ungoverned error difference against reference rate.
Section VII-C currently argues the reference rate is the binding constraint *by elimination*. These
reductions measure it directly, so what they must not do is overstate it.

The failure modes they are written against are specific. Detection recall is emitted as 0.000 in
the ungoverned arm because the detectors never run there, so pooling the arms would halve every
recall in the table and make a structural zero look like a measurement. And a governance effect is
a paired quantity: the difference of two medians is not the median of the differences, and only the
second one is what running the arms over a byte-identical stream buys.
"""

from __future__ import annotations

import pandas as pd
import pytest

from wimsim.experiments.reference_curve import (
    POOLED,
    governance_by_rate,
    recall_by_rate,
    recall_zero_crossing,
    reference_curve_markdown,
)


def _row(**over) -> dict:
    row = {
        "scenario": "S4_step_fault",
        "estimator": "rls",
        "seed": 1,
        "reference_every_n": 10,
        "control_enabled": True,
        "recall": 1.0,
        "mean_detection_delay_s": 100.0,
        "detected": 2,
        "missed": 0,
        "mae_kg": 150.0,
        "bias_kg": -10.0,
        "false_alarms_per_hour": 0.0,
        "recalibrations": 1,
        "failed": False,
    }
    row.update(over)
    return row


def _frame(rows: list[dict]) -> pd.DataFrame:
    return pd.DataFrame(rows)


def _both_arms() -> pd.DataFrame:
    return _frame([_row(seed=s, control_enabled=arm) for s in (1, 2, 3) for arm in (True, False)])


# -- A1: detection recall --------------------------------------------------------------------


def test_the_ungoverned_arm_is_excluded_rather_than_pooled() -> None:
    """The detectors do not run with the controller disabled, so every ungoverned run reports
    `alarms 0, recall 0.000`. That is a structural zero, not a miss, and pooling the two arms
    would halve the recall of every cell in the table."""
    frame = _frame(
        [_row(seed=s, control_enabled=True, recall=1.0) for s in (1, 2, 3)]
        + [_row(seed=s, control_enabled=False, recall=0.0, detected=0, missed=2) for s in (1, 2, 3)]
    )

    cells = {(c.estimator, c.reference_every_n): c for c in recall_by_rate(frame)}
    cell = cells[("rls", 10)]

    assert cell.n_runs == 3
    assert cell.recall_mean == pytest.approx(1.0)


def test_a_cell_reports_mean_and_median_with_its_spread_and_its_sample_size() -> None:
    frame = _frame([_row(seed=s, recall=r) for s, r in ((1, 0.0), (2, 0.5), (3, 1.0))])
    cell = next(c for c in recall_by_rate(frame) if c.estimator == "rls")

    assert cell.n_runs == 3
    assert cell.recall_mean == pytest.approx(0.5)
    assert cell.recall_median == pytest.approx(0.5)
    assert (cell.recall_q1, cell.recall_q3) == pytest.approx((0.25, 0.75))


def test_the_pooled_row_is_over_every_estimator_and_says_how_many_runs() -> None:
    frame = _frame(
        [
            _row(seed=s, estimator=e, recall=1.0 if e == "rls" else 0.0)
            for e in ("rls", "kalman")
            for s in (1, 2, 3)
        ]
    )
    cells = {(c.estimator, c.reference_every_n): c for c in recall_by_rate(frame)}

    assert cells[(POOLED, 10)].n_runs == 6
    assert cells[(POOLED, 10)].recall_mean == pytest.approx(0.5)
    assert cells[("rls", 10)].recall_mean == pytest.approx(1.0)
    assert cells[("kalman", 10)].recall_mean == pytest.approx(0.0)


def test_detection_delay_is_a_median_over_the_runs_that_detected_anything() -> None:
    """A run that detected nothing has no delay to report. Writing its missing delay in as a zero
    would make the detector look fastest exactly where it was blindest."""
    frame = _frame(
        [
            _row(seed=1, recall=1.0, mean_detection_delay_s=200.0),
            _row(seed=2, recall=1.0, mean_detection_delay_s=400.0),
            _row(seed=3, recall=0.0, detected=0, missed=2, mean_detection_delay_s=float("nan")),
        ]
    )
    cell = next(c for c in recall_by_rate(frame) if c.estimator == "rls")

    assert cell.n_runs == 3
    assert cell.n_delay == 2
    assert cell.delay_median == pytest.approx(300.0)


def test_a_scenario_with_no_injected_fault_has_undefined_recall_not_zero() -> None:
    frame = _frame([_row(seed=s, recall=0.0, detected=0, missed=0) for s in (1, 2, 3)])
    cell = next(c for c in recall_by_rate(frame) if c.estimator == "rls")

    assert cell.faults_hit == 0 and cell.faults_missed == 0
    assert cell.recall_defined is False


# -- where recall crosses zero ----------------------------------------------------------------


def test_the_zero_crossing_is_bracketed_by_the_two_rates_either_side_of_it() -> None:
    frame = _frame(
        [
            _row(seed=s, reference_every_n=n, recall=r)
            for n, r in ((2, 0.6), (10, 0.3), (20, 0.0), (50, 0.0))
            for s in (1, 2, 3)
        ]
    )
    cross = recall_zero_crossing(recall_by_rate(frame))["S4_step_fault"]

    assert (cross.last_positive, cross.first_zero) == (10, 20)
    assert cross.located_to == pytest.approx(2.0)  # a factor of two: 10 < n <= 20


def test_a_recall_that_never_reaches_zero_has_no_crossing_rather_than_a_guessed_one() -> None:
    frame = _frame(
        [_row(seed=s, reference_every_n=n, recall=0.5) for n in (2, 10, 50) for s in (1, 2, 3)]
    )
    cross = recall_zero_crossing(recall_by_rate(frame))["S4_step_fault"]

    assert cross.first_zero is None
    assert cross.located_to is None


def test_a_recall_already_zero_at_the_densest_rate_is_reported_as_unbracketed() -> None:
    """Nothing in the grid was dense enough to show a positive recall, so the crossing is not
    between two measured rates -- it is somewhere denser than anything that was run."""
    frame = _frame(
        [
            _row(seed=s, reference_every_n=n, recall=0.0, detected=0, missed=2)
            for n in (2, 10, 50)
            for s in (1, 2, 3)
        ]
    )
    cross = recall_zero_crossing(recall_by_rate(frame))["S4_step_fault"]

    assert cross.last_positive is None
    assert cross.first_zero == 2
    assert cross.located_to is None


# -- A2: the governance effect ------------------------------------------------------------------


def test_the_governance_effect_is_the_median_of_paired_differences() -> None:
    """Not the difference of medians. With the arms run over a byte-identical stream the pairing
    is the whole measurement, and on a skewed set the two quantities differ."""
    frame = _frame(
        [
            _row(seed=s, control_enabled=True, mae_kg=m)
            for s, m in ((1, 100.0), (2, 100.0), (3, 10.0))
        ]
        + [
            _row(seed=s, control_enabled=False, mae_kg=m)
            for s, m in ((1, 110.0), (2, 101.0), (3, 100.0))
        ]
    )
    cell = next(c for c in governance_by_rate(frame) if c.estimator == "rls")

    assert cell.n_pairs == 3
    assert cell.mae_median == pytest.approx(-10.0)  # median of -10, -1, -90
    assert cell.mae_difference_of_medians == pytest.approx(-1.0)  # 100 - 101, for contrast


def test_signed_bias_is_carried_beside_the_error_and_is_never_folded_into_it() -> None:
    """A cell where governance improves MAE and worsens signed bias has to be representable as
    exactly that. Reporting |bias|, or reporting error alone, would hide it."""
    frame = _frame(
        [_row(seed=s, control_enabled=True, mae_kg=90.0, bias_kg=-80.0) for s in (1, 2, 3)]
        + [_row(seed=s, control_enabled=False, mae_kg=100.0, bias_kg=-5.0) for s in (1, 2, 3)]
    )
    cell = next(c for c in governance_by_rate(frame) if c.estimator == "rls")

    assert cell.mae_median == pytest.approx(-10.0)
    assert cell.bias_median == pytest.approx(-75.0)
    assert cell.bias_governed == pytest.approx(-80.0)
    assert cell.bias_open == pytest.approx(-5.0)


def test_pairs_that_came_out_identical_are_counted() -> None:
    """The headline negative result is that most cells do not move at all, and a median of zero
    over thirty pairs means something different depending on whether it is thirty zeros or
    fifteen cancelling pairs."""
    frame = _frame(
        [
            _row(seed=s, control_enabled=arm, mae_kg=100.0)
            for s in (1, 2, 3)
            for arm in (True, False)
        ]
    )
    cell = next(c for c in governance_by_rate(frame) if c.estimator == "rls")

    assert cell.n_identical == 3
    assert cell.mae_median == pytest.approx(0.0)


def test_an_unpaired_seed_is_refused_rather_than_silently_dropped() -> None:
    frame = _frame(
        [_row(seed=s, control_enabled=True) for s in (1, 2, 3)]
        + [_row(seed=s, control_enabled=False) for s in (1, 2)]
    )
    with pytest.raises(ValueError, match="unpaired"):
        governance_by_rate(frame)


def test_two_runs_of_one_seed_in_one_arm_are_refused() -> None:
    """An axis is free that the pairing does not account for -- the same failure `compare.py`
    refuses, for the same reason: the difference would be taken against an arbitrary one of them."""
    frame = _frame(
        [_row(seed=s, control_enabled=True) for s in (1, 2, 3)]
        + [_row(seed=s, control_enabled=False) for s in (1, 2, 3, 3)]
    )
    with pytest.raises(ValueError, match="more than one run"):
        governance_by_rate(frame)


def test_failed_runs_are_excluded_from_both_reductions() -> None:
    frame = _frame(
        [_row(seed=s, recall=1.0) for s in (1, 2)]
        + [_row(seed=3, recall=0.0, failed=True, mae_kg=float("nan"))]
    )
    cell = next(c for c in recall_by_rate(frame) if c.estimator == "rls")
    assert cell.n_runs == 2


# -- the written report ---------------------------------------------------------------------------


def test_the_report_states_that_recall_is_measured_in_the_governed_arm_only() -> None:
    text = reference_curve_markdown(_both_arms(), experiment_id="rr", git_commit="abc")

    assert "governed arm only" in text.lower()
    assert "abc" in text


def test_the_report_names_the_sample_size_of_every_cell() -> None:
    text = reference_curve_markdown(_both_arms(), experiment_id="rr", git_commit="abc")

    assert "runs" in text
    assert "| 3 |" in text


def test_a_frame_without_a_rate_axis_is_refused() -> None:
    frame = _both_arms().drop(columns=["reference_every_n"])
    with pytest.raises(ValueError, match="no reference-rate axis"):
        reference_curve_markdown(frame, experiment_id="rr", git_commit="abc")


# -- frames that cannot support a reduction --------------------------------------------------


def test_a_sweep_that_scored_no_detection_delay_reports_no_delay_rather_than_crashing() -> None:
    """Regression. `DataFrame.get` returns None for a column the sweep never wrote, and the
    first version passed that straight into `pd.to_numeric`, which returns a scalar NaN with no
    `.dropna`. Found by the figure tests, whose frames are deliberately sparser than a real
    sweep's -- which is the point of them.
    """
    frame = _frame([_row(seed=s) for s in (1, 2, 3)]).drop(
        columns=["mean_detection_delay_s", "detected", "missed"]
    )
    cell = next(c for c in recall_by_rate(frame) if c.estimator == "rls")

    assert cell.n_delay == 0
    assert cell.faults_hit == 0 and cell.faults_missed == 0
    assert cell.recall_defined is False


def test_a_sweep_without_signed_bias_is_refused_by_name() -> None:
    """The governance reduction needs four columns and says which one is missing. A KeyError
    from inside the pairing names a pandas index, not the thing to fix."""
    frame = _both_arms().drop(columns=["bias_kg"])
    with pytest.raises(ValueError, match="bias_kg"):
        governance_by_rate(frame)
