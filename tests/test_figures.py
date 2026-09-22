"""Figures for a sweep.

Buildspec section 10: "a LaTeX/Markdown comparison table and matplotlib figures written straight to
``data/results/<id>/figures/``".

Four figures, because four questions are being asked of the sweep and no one plot answers more than
one. Most of what follows is about the ways a figure can be *dishonest*, which is a different
failure from being wrong:

* **MAE is drawn against the dynamic floor**, not on its own. The floor is the error the vehicles
  brought with them, and on an axis in bare kilograms an estimator two per cent above its floor and
  one three times above a smaller floor can look equally good.
* **Coverage is drawn against its nominal target.** 0.91 is a good number or a bad one depending
  entirely on what was promised, so the promise belongs on the figure.
* **Failed runs are visible.** A bar absent because the run crashed looks exactly like a bar absent
  because the value was zero.
* **Seeds are drawn, not averaged away.** Three seeds exist to give a number an error bar, and a
  plot that means over them has thrown away the only thing separating a result from an anecdote.

The plotting itself is barely tested, on purpose: asserting on pixels tests matplotlib. What is
tested is the data each figure is drawn from, which is where a figure actually goes wrong.
"""

from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest

from wimsim.experiments.figures import (
    FIGURES,
    accuracy_ratios,
    coverage_rows,
    detector_points,
    recal_points,
    reconvergence_rows,
    write_figures,
)


def _frame(**overrides) -> pd.DataFrame:
    rows = []
    for scenario, floor in (("S1_nominal", 0.0), ("S4_step_fault", 141.0), ("S6_combined", 180.0)):
        for estimator in ("static_affine", "rls", "kalman"):
            for seed in (1, 2, 3):
                rows.append(
                    {
                        "scenario": scenario,
                        "estimator": estimator,
                        "seed": seed,
                        "n_matched": 400,
                        "mae_kg": floor * 1.2 + seed,
                        "dynamic_floor_kg": floor,
                        "coverage": 0.93 + 0.005 * seed,
                        "mean_interval_width_kg": 900.0,
                        "recall": 0.98,
                        "false_alarms_per_hour": 0.2 * seed,
                        "detected": 2,
                        "missed": 0,
                        "reconverge_s": 2500.0 + 100 * seed,
                        "reconverged": True,
                        "reconverge_measurable": True,
                        "failed": False,
                        "error": None,
                    }
                )
    frame = pd.DataFrame(rows)
    for key, value in overrides.items():
        frame[key] = value
    return frame


# -- what gets written ----------------------------------------------------------------------------


def test_every_figure_the_frame_supports_is_written(tmp_path: Path) -> None:
    """Not every named figure is drawable from every sweep -- `reference_rate` needs a sweep that
    varies the rate, and an axis with nothing on it is not written at all. What must hold is that
    nothing drawable is skipped.
    """
    written = write_figures(_frame(), out_dir=tmp_path, experiment_id="t")
    assert {p.name for p in written if p.suffix == ".png"} == {
        f"{n}.png" for n in FIGURES if n not in ("reference_rate", "recal_tradeoff")
    }
    assert all(p.is_file() and p.stat().st_size > 0 for p in written)


def test_a_rate_sweep_draws_every_figure_including_the_rate_one(tmp_path: Path) -> None:
    written = write_figures(_rate_frame(), out_dir=tmp_path, experiment_id="t")
    assert {f"{n}.png" for n in FIGURES} <= {p.name for p in written}


def test_the_figures_land_under_the_results_directory(tmp_path: Path) -> None:
    """Buildspec: "written straight to `data/results/<id>/figures/`", beside the parquet they
    describe, so a results directory is one thing a reader can be handed."""
    write_figures(_frame(), out_dir=tmp_path, experiment_id="t")
    assert (tmp_path / "figures").is_dir()


def test_each_figure_ships_with_a_caption_saying_what_it_is_for(tmp_path: Path) -> None:
    """A figure separated from its caption is a shape. The captions live in a file beside the
    figures rather than only in the code that drew them."""
    write_figures(_frame(), out_dir=tmp_path, experiment_id="t")
    readme = (tmp_path / "figures" / "README.md").read_text(encoding="utf-8")

    for name in FIGURES:
        assert f"{name}.png" in readme
    assert "floor" in readme.lower(), "the accuracy figure's axis needs explaining"


def test_a_sweep_in_which_everything_failed_produces_no_figures_rather_than_empty_ones(
    tmp_path: Path,
) -> None:
    """An axis with nothing on it is not a result. A reader shown four plausible-looking empty
    plots has been told less than one shown none."""
    frame = _frame()
    frame["failed"] = True
    frame["mae_kg"] = None
    assert write_figures(frame, out_dir=tmp_path, experiment_id="t") == []


def test_the_failure_count_is_carried_onto_the_figures(tmp_path: Path) -> None:
    """The title is the part of a figure that survives being pasted into a slide, so that is where
    "nine of these twenty-seven runs are not here" has to go."""
    frame = _frame()
    frame.loc[frame["estimator"] == "rls", "failed"] = True
    write_figures(frame, out_dir=tmp_path, experiment_id="t")
    readme = (tmp_path / "figures" / "README.md").read_text(encoding="utf-8")
    assert "9 of 27" in readme


def test_the_same_frame_draws_the_same_bytes(tmp_path: Path) -> None:
    """Principle 4. A figure that changes between runs cannot be diffed, and a reviewer cannot tell
    a re-render from a new result."""
    a = sorted(write_figures(_frame(), out_dir=tmp_path / "a", experiment_id="t"))
    b = sorted(write_figures(_frame(), out_dir=tmp_path / "b", experiment_id="t"))
    for left, right in zip(a, b, strict=True):
        assert left.read_bytes() == right.read_bytes(), left.name


# -- what the figures are drawn from ---------------------------------------------------------------


def test_accuracy_is_expressed_as_a_multiple_of_the_floor(tmp_path: Path) -> None:
    """The dynamic floor spans two orders of magnitude across this sweep -- 0 kg on S1, 180 kg on
    S6 -- so an axis in bare kilograms compares scenarios rather than estimators."""
    ratios = accuracy_ratios(_frame())
    assert ratios[("S4_step_fault", "kalman")] == pytest.approx(
        [(141 * 1.2 + s) / 141 for s in (1, 2, 3)]
    )


def test_a_scenario_with_no_floor_is_kept_out_of_the_ratio_figure() -> None:
    """S1 has no dynamic load, so its floor is zero and "MAE as a multiple of the floor" is a
    division by zero rather than an impressive number."""
    ratios = accuracy_ratios(_frame())
    assert not any(scenario == "S1_nominal" for scenario, _est in ratios)


def test_seeds_are_kept_rather_than_averaged_away() -> None:
    assert len(accuracy_ratios(_frame())[("S6_combined", "rls")]) == 3


def test_a_failed_run_contributes_nothing_and_is_not_read_as_zero() -> None:
    frame = _frame()
    frame.loc[(frame["estimator"] == "rls") & (frame["seed"] == 2), ["failed", "mae_kg"]] = [
        True,
        None,
    ]
    assert len(accuracy_ratios(frame)[("S4_step_fault", "rls")]) == 2


def test_coverage_carries_the_target_it_is_being_judged_against() -> None:
    """0.91 is a good number or a bad one depending entirely on what was promised."""
    rows, target = coverage_rows(_frame())
    assert target == pytest.approx(0.95)
    assert rows[("S4_step_fault", "kalman")] == pytest.approx([0.935, 0.94, 0.945])


def test_reconvergence_only_covers_scenarios_that_had_something_to_reconverge_from() -> None:
    """S1 has no faults. A zero bar there reads as "reconverged instantly", which is the opposite
    of "the question was never asked"."""
    frame = _frame()
    frame.loc[frame["scenario"] == "S1_nominal", "reconverge_measurable"] = False
    frame.loc[frame["scenario"] == "S1_nominal", "reconverge_s"] = None

    rows = reconvergence_rows(frame)
    assert not any(scenario == "S1_nominal" for scenario, _est in rows)
    assert ("S4_step_fault", "kalman") in rows


def test_a_run_that_never_reconverged_is_separated_from_one_that_was_never_measured() -> None:
    """Two different outcomes that a bare `reconverge_s` of NaN cannot tell apart, and averaging
    them together would flatter whichever way was convenient."""
    frame = _frame()
    stuck = (frame["scenario"] == "S4_step_fault") & (frame["estimator"] == "rls")
    frame.loc[stuck, "reconverged"] = False
    frame.loc[stuck, "reconverge_s"] = None

    rows = reconvergence_rows(frame)
    assert rows[("S4_step_fault", "rls")].never_reconverged == 3
    assert rows[("S4_step_fault", "rls")].seconds == []
    assert rows[("S4_step_fault", "kalman")].never_reconverged == 0


def test_the_detector_figure_plots_the_trade_off_an_operator_actually_faces() -> None:
    """Recall against false alarms per hour. Either alone can be made perfect by a detector that is
    useless in the other direction, which is why they belong on the same axes."""
    points = detector_points(_frame())[("S4_step_fault", "rls")]
    assert [fa for fa, _r in points] == pytest.approx([0.2, 0.4, 0.6])
    assert [recall for _fa, recall in points] == pytest.approx([0.98, 0.98, 0.98])


def test_a_scenario_with_no_faults_has_no_recall_and_is_still_plotted_for_its_false_alarms() -> (
    None
):
    """S1 is the false-alarm measurement: there is nothing to detect, so recall is undefined but
    every alarm is a real cost. Dropping it would remove the only clean measurement of that cost."""
    frame = _frame()
    frame.loc[frame["scenario"] == "S1_nominal", "recall"] = None

    points = detector_points(frame)
    assert ("S1_nominal", "rls") in points
    assert all(recall is None for _fa, recall in points[("S1_nominal", "rls")])


# -- the reference-rate figure --------------------------------------------------------------------


def _rate_frame(**overrides) -> pd.DataFrame:
    """A rate sweep: accuracy degrades as references get rarer, and faster with the loop off."""
    rows = []
    for rate in (2, 10, 50):
        for control in (True, False):
            for estimator in ("static_affine", "kalman"):
                for seed in (1, 2, 3):
                    penalty = (rate / 2) ** 0.5 * (1.0 if control else 1.6)
                    rows.append(
                        {
                            "scenario": "S4_step_fault",
                            "estimator": estimator,
                            "seed": seed,
                            "reference_every_n": rate,
                            "control_enabled": control,
                            "n_matched": 3000,
                            "mae_kg": 130.0 * penalty + seed,
                            "dynamic_floor_kg": 130.0,
                            "coverage": 0.94,
                            "mean_interval_width_kg": 900.0,
                            "recall": 0.5,
                            "false_alarms_per_hour": 0.1,
                            "detected": 1,
                            "missed": 1,
                            "recalibrations": 3 if control else 0,
                            "reconverge_s": 900.0,
                            "reconverged": True,
                            "reconverge_measurable": True,
                            "failed": False,
                            "error": None,
                        }
                    )
    frame = pd.DataFrame(rows)
    for key, value in overrides.items():
        frame[key] = value
    return frame


def test_the_rate_figure_is_drawn_only_when_the_rate_actually_varies(tmp_path: Path) -> None:
    """`ladder` runs at a single rate. A one-point curve is not a trend, and drawing it would
    invite exactly the reading it cannot support."""
    written = write_figures(_frame(), out_dir=tmp_path, experiment_id="t")
    assert not any(p.stem == "reference_rate" for p in written)

    written = write_figures(_rate_frame(), out_dir=tmp_path / "r", experiment_id="t")
    assert any(p.stem == "reference_rate" for p in written)


def test_the_rate_curves_keep_the_two_arms_apart() -> None:
    """The whole question is the gap between them. Averaging the controller-on and controller-off
    runs together would answer a question nobody asked."""
    from wimsim.experiments.figures import rate_curves

    curves = rate_curves(_rate_frame())
    assert ("S4_step_fault", "static_affine", True) in curves
    assert ("S4_step_fault", "static_affine", False) in curves
    assert sorted(curves[("S4_step_fault", "static_affine", True)]) == [2, 10, 50]
    assert len(curves[("S4_step_fault", "static_affine", True)][2]) == 3, "three seeds, kept"


def test_the_rate_curves_keep_the_scenarios_apart() -> None:
    """Regression, seen on the first real sweep: the curves were keyed on estimator and arm only,
    so S4 and S7 were pooled into one median. Their floors differ -- static_affine sits at 1.41x on
    S4 and 1.16x on S7 -- and the pooled line came out at 1.27x, which describes neither.

    A median over two scenarios is not a property of either of them.
    """
    from wimsim.experiments.figures import rate_curves

    frame = _rate_frame()
    other = frame.copy()
    other["scenario"] = "S7_sparse_reference"
    other["mae_kg"] = other["mae_kg"] * 0.5
    curves = rate_curves(pd.concat([frame, other], ignore_index=True))

    s4 = curves[("S4_step_fault", "kalman", True)][2]
    s7 = curves[("S7_sparse_reference", "kalman", True)][2]
    assert s4 != pytest.approx(s7)
    assert {k[0] for k in curves} == {"S4_step_fault", "S7_sparse_reference"}


def test_the_rate_curves_are_expressed_against_the_floor() -> None:
    from wimsim.experiments.figures import rate_curves

    curves = rate_curves(_rate_frame())
    assert curves[("S4_step_fault", "kalman", True)][2] == pytest.approx(
        [1.0 + s / 130.0 for s in (1, 2, 3)]
    )


def test_a_frame_with_no_control_column_still_draws_one_curve_per_estimator() -> None:
    """An older sweep has no arm axis. It should still produce a rate figure rather than nothing."""
    from wimsim.experiments.figures import rate_curves

    frame = _rate_frame().drop(columns=["control_enabled"])
    curves = rate_curves(frame)
    assert {k[2] for k in curves} == {None}


# -- the recalibration/coverage trade ---------------------------------------------------------


def _recal_frame(**overrides) -> pd.DataFrame:
    """A `recal_coverage`-shaped frame: confirm_sigma is the knob, recalibrations the consequence.

    Lower confirm_sigma confirms drift more readily, so more recalibrations, so more of the run
    spent on the estimator's fallback band while conformal warms back up.
    """
    rows = []
    for edge, sigma, recals in (
        ("recal_s15", 1.5, 9),
        ("recal_s30", 3.0, 4),
        ("recal_s60", 6.0, 1),
    ):
        for estimator in ("static_affine", "rls"):
            for seed in (1, 2, 3):
                rows.append(
                    {
                        "scenario": "S4_step_fault",
                        "estimator": estimator,
                        "seed": seed,
                        "edge_config": edge,
                        "confirm_sigma": sigma,
                        "recalibrations": recals + (seed - 2),
                        "n_events": 400,
                        "n_matched": 400,
                        "n_interval_fallback": 30 * recals,
                        "coverage": 0.95 - 0.02 * recals,
                        "coverage_expected": 0.95,
                        "mae_kg": 200.0 - 5.0 * recals,
                        "dynamic_floor_kg": 141.0,
                        "reconverged": True,
                        "reconverge_measurable": True,
                        "reconverge_s": 400.0,
                        "false_alarms_per_hour": 0.2,
                        "recall": 1.0,
                        "mean_interval_width_kg": 900.0,
                        "failed": False,
                    }
                    | overrides
                )
    return pd.DataFrame(rows)


def test_the_trade_is_drawn_against_measured_recalibrations_not_the_knob_that_caused_them() -> None:
    """`confirm_sigma` is what was set; recalibrations are what happened. Two estimators at the
    same sigma need not recalibrate the same number of times, and plotting the knob would draw
    them as one point."""
    points = recal_points(_recal_frame())

    xs = sorted(p.recalibrations for p in points[("S4_step_fault", "rls")])
    assert xs == [0, 1, 2, 3, 4, 5, 8, 9, 10]
    assert all(isinstance(p.recalibrations, int) for p in points[("S4_step_fault", "rls")])


def test_the_fallback_share_is_a_fraction_of_events_rather_than_a_count() -> None:
    """A count is not comparable between runs of different length, and the sweeps do not all run
    the same number of vehicles."""
    points = {p.recalibrations: p for p in recal_points(_recal_frame())[("S4_step_fault", "rls")]}

    assert points[9].fallback_share == pytest.approx(270 / 400)
    assert points[1].fallback_share == pytest.approx(30 / 400)


def test_both_halves_of_the_trade_are_carried_on_the_same_point() -> None:
    """The claim is that recalibration buys mass accuracy and costs interval validity. A point
    carrying only one of the two cannot support or refute it."""
    point = recal_points(_recal_frame())[("S4_step_fault", "rls")][0]

    assert point.coverage is not None
    assert point.mae_ratio is not None and point.mae_ratio > 0.0


def test_a_run_with_no_coverage_is_dropped_rather_than_drawn_at_zero() -> None:
    frame = _recal_frame()
    frame.loc[frame.edge_config == "recal_s15", "coverage"] = float("nan")
    points = recal_points(frame)

    assert all(p.recalibrations < 8 for p in points[("S4_step_fault", "rls")])


def test_the_figure_is_not_drawn_when_recalibration_never_varied(tmp_path: Path) -> None:
    """On a sweep where every arm recalibrated the same number of times there is no trade to
    show, and a vertical stripe of points invites a reading it cannot support."""
    frame = _recal_frame()
    frame["recalibrations"] = 3
    written = write_figures(frame, out_dir=tmp_path, experiment_id="flat")

    assert not any(p.name.startswith("recal_tradeoff") for p in written)


def test_the_trade_figure_is_drawn_when_it_varies(tmp_path: Path) -> None:
    written = write_figures(_recal_frame(), out_dir=tmp_path, experiment_id="recal_coverage")
    assert any(p.name == "recal_tradeoff.png" for p in written)
