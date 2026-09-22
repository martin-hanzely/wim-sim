"""The per-detector comparison table.

Section IV-G describes four detectors running in parallel. The shipped config runs two, so every
detection number the project had reported was the behaviour of that pair and nothing was known
about the other two. This table is what the `detectors` sweep is turned into, and these tests are
about the ways such a table misleads: a recall of zero where recall is undefined, a median with no
spread beside it, and an arm summarised over a different number of runs than its neighbour.
"""

from __future__ import annotations

import pandas as pd
import pytest

from wimsim.experiments.table import detector_table


def _frame(**overrides) -> pd.DataFrame:
    rows = []
    arms = {
        "detect_cusum": (2, 0, 0.4, 61.0),
        "detect_ph": (1, 1, 0.1, 140.0),
        "detect_all4": (2, 0, 3.9, 38.0),
    }
    for scenario in ("S4_step_fault", "S6_combined"):
        for arm, (hit, missed, fa, delay) in arms.items():
            for seed in (1, 2, 3, 4, 5):
                rows.append(
                    {
                        "scenario": scenario,
                        "estimator": "rls",
                        "edge_config": arm,
                        "seed": seed,
                        "detected": hit,
                        "missed": missed,
                        "recall": hit / (hit + missed),
                        "false_alarms_per_hour": fa + 0.1 * seed,
                        "mean_detection_delay_s": delay + seed,
                        "failed": False,
                    }
                    | overrides
                )
    return pd.DataFrame(rows)


def test_each_detector_arm_gets_its_own_row_rather_than_being_pooled() -> None:
    """The whole point of the sweep. Keyed on scenario and estimator alone, the five arms collapse
    into one row and the table says what the ensemble did while claiming to compare detectors."""
    text = detector_table(_frame(), experiment_id="detectors", git_commit="abc1234")

    for arm in ("detect_cusum", "detect_ph", "detect_all4"):
        assert text.count(arm) == 2, f"{arm} once per scenario"


def test_every_number_carries_its_spread_and_its_sample_size() -> None:
    """A median over five seeds and a median over one look identical on the page."""
    text = detector_table(_frame(), experiment_id="detectors", git_commit="abc1234")

    assert "IQR" in text
    assert "| 5 |" in text, "runs per cell"


def test_a_scenario_with_no_faults_reports_undefined_recall_rather_than_zero() -> None:
    """Recall over zero faults is undefined. Printing 0.000 says the detectors missed everything."""
    frame = _frame()
    frame.loc[frame.scenario == "S6_combined", ["detected", "missed", "recall"]] = [0, 0, None]
    text = detector_table(frame, experiment_id="detectors", git_commit="abc1234")

    assert "undefined" in text
    assert "0.000" not in text.split("S6_combined")[1]


def test_the_false_alarm_rate_is_reported_even_where_recall_is_undefined() -> None:
    """A scenario with nothing to detect is the cleanest measurement of what a false alarm costs,
    so it is the one cell that must not be dropped for having no recall."""
    frame = _frame()
    frame.loc[frame.scenario == "S6_combined", ["detected", "missed", "recall"]] = [0, 0, None]
    tail = detector_table(frame, experiment_id="detectors", git_commit="abc1234").split(
        "S6_combined"
    )[1]

    assert "4.0" in tail or "3.9" in tail or "4.1" in tail


def test_a_failed_run_is_counted_rather_than_quietly_reducing_the_sample() -> None:
    frame = _frame()
    frame.loc[(frame.edge_config == "detect_ph") & (frame.seed == 1), "failed"] = True
    text = detector_table(frame, experiment_id="detectors", git_commit="abc1234")

    assert "2 failed" in text, "one per scenario"
    assert "| detect_ph | 4 |" in text, "the cell is a median over four runs, and says so"


def test_the_table_names_the_code_that_produced_it() -> None:
    text = detector_table(_frame(), experiment_id="detectors", git_commit="abc1234")
    assert "abc1234" in text and "detectors" in text


def test_a_frame_with_no_detector_axis_is_refused_rather_than_drawn_as_one_row() -> None:
    """Handed the ladder, this table would report the shipped pair under a heading claiming to
    compare five arms."""
    frame = _frame()
    frame["edge_config"] = "default"
    with pytest.raises(ValueError, match="one detector arm"):
        detector_table(frame, experiment_id="ladder", git_commit="abc1234")
