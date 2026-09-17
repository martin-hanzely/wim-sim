"""Scoring: the one layer allowed to join estimates with ground truth.

Everything else in the system is quarantined from ``wimsim.signal``. This is not, and that is the
whole design: truth enters the system exactly once, at the point where results are computed, and
never anywhere a decision is made.

Matching is where scoring goes wrong quietly. A detector that reports every vehicle 40 ms late
still measured every vehicle; a matcher that insists on exact timestamps would report 100 % misses
and 100 % false positives, and the resulting MAE would be computed over an empty set.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from wimsim.experiments.scoring import match_events, score_events


def _truth(n: int = 5, *, start: float = 1.0, spacing: float = 10.0, mass: float = 10000.0):
    rows = []
    for i in range(n):
        t = start + i * spacing
        rows.append(
            {
                "pass_id": f"p{i}",
                "pass_index": i,
                "vehicle_class": "rigid_truck",
                "t_entry_s": t,
                "t_exit_s": t + 0.2,
                "t_peak_s": t + 0.1,
                "ts_peak_us": int((t + 0.1) * 1e6),
                "true_mass_kg": mass + 100.0 * i,
                "applied_mass_kg": mass + 100.0 * i,
                "axle_count": 3,
                "speed_kmh": 85.0,
            }
        )
    return pd.DataFrame(rows)


class _Ev:
    """Minimal stand-in for MeasurementEvent: scoring only touches these fields."""

    def __init__(
        self,
        ts_start,
        ts_peak,
        ts_end,
        mass,
        lo=None,
        hi=None,
        axles=3,
        interval_source="conformal_relative",
    ):
        self.interval_source = interval_source
        self.event_id = f"e{ts_peak}"
        self.ts_start = int(ts_start * 1e6)
        self.ts_peak = int(ts_peak * 1e6)
        self.ts_end = int(ts_end * 1e6)
        self.mass_kg = mass
        self.mass_ci_low = mass - 500.0 if lo is None else lo
        self.mass_ci_high = mass + 500.0 if hi is None else hi
        self.axle_count = axles
        self.quality_flag = "ok"


def _events_for(truth: pd.DataFrame, *, offset_s: float = 0.0, error_kg: float = 0.0):
    return [
        _Ev(
            r.t_entry_s + offset_s,
            r.t_peak_s + offset_s,
            r.t_exit_s + offset_s,
            r.true_mass_kg + error_kg,
            axles=int(r.axle_count),
        )
        for r in truth.itertuples()
    ]


# -- matching -------------------------------------------------------------------------------


def test_perfect_alignment_matches_everything() -> None:
    truth = _truth()
    matched, missed, spurious = match_events(_events_for(truth), truth, tolerance_s=0.25)
    assert len(matched) == len(truth)
    assert missed.empty
    assert spurious == []


def test_a_constant_detection_lag_still_matches() -> None:
    """A detector 40 ms late measured every vehicle. Insisting on exact times would report a
    total failure and then compute MAE over nothing."""
    truth = _truth()
    matched, missed, spurious = match_events(
        _events_for(truth, offset_s=0.04), truth, tolerance_s=0.25
    )
    assert len(matched) == len(truth)
    assert missed.empty
    assert spurious == []


def test_a_lag_beyond_tolerance_is_reported_as_missed_and_spurious() -> None:
    truth = _truth()
    matched, missed, spurious = match_events(
        _events_for(truth, offset_s=5.0), truth, tolerance_s=0.25
    )
    assert matched.empty
    assert len(missed) == len(truth)
    assert len(spurious) == len(truth)


def test_matching_is_one_to_one() -> None:
    """Two events over one pass must not both claim it, or recall would exceed 1."""
    truth = _truth(n=1)
    events = [
        _Ev(1.0, 1.10, 1.2, 10000.0),
        _Ev(1.0, 1.12, 1.2, 10100.0),
    ]
    matched, missed, spurious = match_events(events, truth, tolerance_s=0.25)
    assert len(matched) == 1
    assert len(spurious) == 1
    assert missed.empty


def test_the_closest_candidate_wins() -> None:
    truth = _truth(n=1)
    far = _Ev(1.0, 1.30, 1.4, 9000.0)
    near = _Ev(1.0, 1.10, 1.2, 10000.0)
    matched, _, spurious = match_events([far, near], truth, tolerance_s=0.35)
    assert matched.iloc[0]["mass_kg"] == 10000.0
    assert spurious == [far.event_id]


def test_a_missed_pass_is_reported_with_its_identity() -> None:
    truth = _truth(n=3)
    events = _events_for(truth)[:2]
    matched, missed, spurious = match_events(events, truth, tolerance_s=0.25)
    assert len(matched) == 2
    assert list(missed.pass_id) == ["p2"]
    assert spurious == []


# -- metrics ---------------------------------------------------------------------------------


def test_a_perfect_pipeline_scores_zero_error() -> None:
    truth = _truth()
    result = score_events(_events_for(truth), truth)
    assert result.n_matched == len(truth)
    assert result.mae_kg == pytest.approx(0.0)
    assert result.rmse_kg == pytest.approx(0.0)
    assert result.bias_kg == pytest.approx(0.0)
    assert result.mape == pytest.approx(0.0)
    assert result.recall == pytest.approx(1.0)
    assert result.false_positive_rate == pytest.approx(0.0)


def test_a_constant_overestimate_shows_up_as_bias_not_just_error() -> None:
    """MAE alone cannot distinguish a miscalibrated scale from a noisy one. Bias can."""
    truth = _truth()
    result = score_events(_events_for(truth, error_kg=250.0), truth)
    assert result.mae_kg == pytest.approx(250.0)
    assert result.bias_kg == pytest.approx(250.0)


def test_a_symmetric_error_has_large_mae_and_near_zero_bias() -> None:
    truth = _truth(n=4)
    events = _events_for(truth)
    for i, ev in enumerate(events):
        ev.mass_kg += 200.0 if i % 2 == 0 else -200.0
    result = score_events(events, truth)
    assert result.mae_kg == pytest.approx(200.0)
    assert abs(result.bias_kg) < 1e-9


def test_mape_is_relative_and_rmse_punishes_outliers() -> None:
    truth = _truth(n=4, mass=10000.0, spacing=10.0)
    events = _events_for(truth)
    events[0].mass_kg += 2000.0
    result = score_events(events, truth)
    assert result.rmse_kg > result.mae_kg
    assert result.mape == pytest.approx(0.25 * 2000.0 / 10000.0, rel=0.05)


def test_coverage_is_measured_against_the_emitted_interval() -> None:
    truth = _truth(n=10)
    events = _events_for(truth)
    for ev in events[:3]:
        ev.mass_ci_low = ev.mass_kg + 1.0  # interval that excludes the truth
        ev.mass_ci_high = ev.mass_kg + 2.0
    result = score_events(events, truth)
    assert result.coverage == pytest.approx(0.7)
    assert result.mean_interval_width_kg > 0


def test_the_dynamic_load_floor_is_reported_separately() -> None:
    """The gap between static and applied mass is irreducible: no calibration recovers a static
    mass from one crossing of a bouncing vehicle. Reporting only error-vs-static would blame the
    pipeline for physics."""
    truth = _truth(n=4)
    truth["applied_mass_kg"] = truth["true_mass_kg"] + 300.0
    events = [
        _Ev(r.t_entry_s, r.t_peak_s, r.t_exit_s, r.applied_mass_kg) for r in truth.itertuples()
    ]
    result = score_events(events, truth)
    assert result.mae_kg == pytest.approx(300.0), "measured against static mass"
    assert result.mae_vs_applied_kg == pytest.approx(0.0), "the pipeline itself was exact"
    assert result.dynamic_floor_kg == pytest.approx(300.0)


def test_axle_count_accuracy_is_reported() -> None:
    truth = _truth(n=4)
    events = _events_for(truth)
    events[0].axle_count = 2
    result = score_events(events, truth)
    assert result.axle_count_accuracy == pytest.approx(0.75)


def test_scoring_an_empty_match_set_reports_nan_rather_than_crashing() -> None:
    """A pipeline that detected nothing is a result, not an exception -- and its MAE is undefined,
    not zero."""
    truth = _truth()
    result = score_events([], truth)
    assert result.n_matched == 0
    assert result.recall == pytest.approx(0.0)
    assert np.isnan(result.mae_kg)


def test_per_class_breakdown() -> None:
    truth = _truth(n=4)
    truth.loc[:1, "vehicle_class"] = "car"
    events = _events_for(truth)
    events[0].mass_kg += 500.0
    result = score_events(events, truth)
    assert set(result.per_class) == {"car", "rigid_truck"}
    assert result.per_class["car"]["mae_kg"] == pytest.approx(250.0)
    assert result.per_class["rigid_truck"]["mae_kg"] == pytest.approx(0.0)


def test_result_serialises_to_json_friendly_types() -> None:
    import json

    result = score_events(_events_for(_truth()), _truth())
    json.dumps(result.to_dict())


# -- coverage is only meaningful within one interval construction ---------------------------------


def _mixed(truth, *, n_fallback: int):
    """Events whose first `n_fallback` carry a uselessly narrow analytic band, the rest a wide
    conformal one -- the shape a sparse-reference run actually produces."""
    out = []
    for i, r in enumerate(truth.itertuples()):
        fallback = i < n_fallback
        out.append(
            _Ev(
                r.t_entry_s,
                r.t_peak_s,
                r.t_exit_s,
                r.true_mass_kg + 300.0,
                lo=r.true_mass_kg + 299.0 if fallback else r.true_mass_kg - 2000.0,
                hi=r.true_mass_kg + 301.0 if fallback else r.true_mass_kg + 2000.0,
                interval_source="kalman_analytic" if fallback else "conformal_relative",
            )
        )
    return out


def test_coverage_is_reported_per_interval_source() -> None:
    """A run can emit intervals from more than one construction, and pooling them produces a number
    that describes neither.

    Measured on `S4_step_fault` with Kalman at one reference in fifty. `uncertainty.method` is
    `conformal`, but conformal needs 19 scored references before it can claim a 95 % quantile, and
    at that rate they take four hours to arrive. For those four hours every event silently carries
    the estimator's own analytic band -- which for the Kalman filter is the construction phase 5
    measured at coverage 0.0065 and chose conformal specifically to avoid:

        hours 0-2    coverage 0.004   mean width    11 kg
        hours 2-4    coverage 0.010   mean width     2 kg
        hours 4-16   coverage 0.914+  mean width  1435-1791 kg

    The headline 0.741 averages a broken quarter with a working three quarters.
    """
    truth = _truth(8)
    result = score_events(_mixed(truth, n_fallback=4), truth)

    assert set(result.coverage_by_source) == {"kalman_analytic", "conformal_relative"}
    n_bad, cov_bad = result.coverage_by_source["kalman_analytic"]
    n_good, cov_good = result.coverage_by_source["conformal_relative"]
    assert (n_bad, n_good) == (4, 4)
    assert cov_bad == 0.0
    assert cov_good == 1.0
    assert result.coverage == pytest.approx(0.5), "the pooled figure still describes neither"


def test_a_single_source_run_reports_one_entry() -> None:
    """The common case must not grow a structure that has to be unpacked to mean anything."""
    truth = _truth(6)
    result = score_events(_events_for(truth), truth)
    assert list(result.coverage_by_source) == ["conformal_relative"]
    assert result.n_interval_fallback == 0


def test_the_fallback_count_names_intervals_the_config_did_not_ask_for() -> None:
    """`interval_source` already recorded which construction produced each band. What was missing
    was anyone comparing it against the construction that was configured."""
    truth = _truth(10)
    result = score_events(_mixed(truth, n_fallback=3), truth, expected_interval_source="conformal")

    assert result.n_interval_fallback == 3
    assert result.n_interval_expected == 7
    assert result.coverage_expected == pytest.approx(1.0)
    assert result.coverage == pytest.approx(0.7)


def test_with_no_expectation_stated_nothing_is_called_a_fallback() -> None:
    """Scoring does not get to invent a preference the configuration never expressed."""
    truth = _truth(4)
    result = score_events(_mixed(truth, n_fallback=4), truth)
    assert result.n_interval_fallback == 0
    assert result.coverage_expected is None


def test_the_breakdown_survives_serialisation() -> None:
    truth = _truth(8)
    payload = score_events(
        _mixed(truth, n_fallback=4), truth, expected_interval_source="conformal"
    ).to_dict()
    assert payload["n_interval_fallback"] == 4
    assert "kalman_analytic" in payload["coverage_by_source"]
