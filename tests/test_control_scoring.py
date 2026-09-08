"""Scoring the *loop*, not just the masses.

`scoring.py` answers "how wrong were the kilograms". These are the questions a control paper is
actually judged on, and buildspec section 10 names them: time to reconverge after an injected drift
event (called out as the headline control metric), the drift detector's false-alarm and
missed-detection rates, and what an estimator update costs.

Every one of them needs the *fault times*, which are truth-side, so all of this lives in
``experiments/`` and none of it is reachable from ``calibration/``.

The definitions matter more than the code, because each of these is easy to define in a way that
flatters the system. The ones here are chosen to be hard to game:

* reconvergence requires the error to come back **and stay back**, so a single lucky pass does not
  count as recovery;
* a detection only counts if it lands **after** the fault and inside a stated horizon, so an alarm
  that happened to fire beforehand is a false alarm rather than a prophecy;
* "never reconverged" is a reportable outcome, not a missing value to be dropped from a mean.
"""

from __future__ import annotations

import numpy as np
import pytest

from wimsim.experiments.control_scoring import (
    ControlScore,
    detector_rates,
    estimator_cost,
    time_to_reconverge,
)

SECOND = 1_000_000


def _errors(
    n: int,
    *,
    shift_at: int | None = None,
    shift: float = 0.0,
    recover_at: int | None = None,
    scale: float = 50.0,
    seed: int = 0,
):
    """(timestamp, signed error) pairs, one per pass, one second apart."""
    rng = np.random.default_rng(seed)
    rows = []
    for i in range(n):
        offset = 0.0
        if shift_at is not None and i >= shift_at:
            offset = shift
        if recover_at is not None and i >= recover_at:
            offset = 0.0
        rows.append((SECOND * i, offset + float(rng.standard_normal()) * scale))
    return rows


# -- time to reconverge --------------------------------------------------------------------------


def test_a_run_that_recovers_reports_when_it_did() -> None:
    rows = _errors(600, shift_at=200, shift=400.0, recover_at=300)
    result = time_to_reconverge(rows, fault_ts_us=SECOND * 200, window=40)

    assert result.reconverged
    # Recovery is at pass 300; the rolling window needs to fill before it can say so.
    assert 300 <= result.reconverged_at_ts_us / SECOND <= 360
    assert 100.0 <= result.seconds <= 160.0
    assert result.passes is not None and result.passes > 0


def test_a_run_that_never_recovers_says_so_rather_than_returning_nothing() -> None:
    """ "Never" is a result. Returning None and letting it be dropped from a mean would make a
    system that never recovers look identical to one that was not measured."""
    rows = _errors(600, shift_at=200, shift=400.0)
    result = time_to_reconverge(rows, fault_ts_us=SECOND * 200, window=40)

    assert not result.reconverged
    assert result.seconds is None
    assert result.baseline_abs_error > 0.0
    assert result.final_abs_error > 3 * result.baseline_abs_error


def test_recovery_must_be_sustained_not_a_single_lucky_pass() -> None:
    """A rolling median over a window is what makes this true: one pass that happens to land near
    zero in the middle of a fault cannot move a median over forty."""
    rows = _errors(600, shift_at=200, shift=400.0)
    rows[260] = (rows[260][0], 0.0)  # one lucky pass
    result = time_to_reconverge(rows, fault_ts_us=SECOND * 200, window=40)
    assert not result.reconverged


def test_a_partial_recovery_does_not_count() -> None:
    """Coming back to twice the pre-fault error is not reconvergence, and calling it that would
    make the headline metric meaningless."""
    rows = _errors(800, shift_at=200, shift=400.0, recover_at=300)
    rows = [(ts, e + (150.0 if i >= 300 else 0.0)) for i, (ts, e) in enumerate(rows)]
    result = time_to_reconverge(rows, fault_ts_us=SECOND * 200, window=40, tolerance=1.5)
    assert not result.reconverged


def test_the_tolerance_is_relative_to_the_pre_fault_error_not_absolute() -> None:
    """Sites differ by an order of magnitude in residual spread, so an absolute threshold would
    mean something different at each one and could not be compared across scenarios."""
    quiet = _errors(600, shift_at=200, shift=100.0, recover_at=300, scale=10.0, seed=1)
    noisy = _errors(600, shift_at=200, shift=500.0, recover_at=300, scale=50.0, seed=1)

    a = time_to_reconverge(quiet, fault_ts_us=SECOND * 200, window=40)
    b = time_to_reconverge(noisy, fault_ts_us=SECOND * 200, window=40)
    assert a.reconverged and b.reconverged
    assert abs(a.seconds - b.seconds) < 60.0


def test_a_fault_with_no_passes_after_it_is_reported_as_unmeasurable() -> None:
    """Distinct from "never reconverged": the run simply ended too soon to tell, and averaging the
    two together would be a lie in whichever direction was convenient."""
    rows = _errors(210, shift_at=200, shift=400.0)
    result = time_to_reconverge(rows, fault_ts_us=SECOND * 200, window=40)
    assert not result.reconverged
    assert not result.measurable


def test_passes_before_the_fault_set_the_baseline_and_are_not_scored() -> None:
    rows = _errors(600, shift_at=200, shift=400.0, recover_at=300, scale=50.0)
    result = time_to_reconverge(rows, fault_ts_us=SECOND * 200, window=40)
    assert 20.0 < result.baseline_abs_error < 60.0  # a half-normal mean of |N(0, 50)|


# -- detector rates ------------------------------------------------------------------------------


def test_a_fault_answered_by_an_alarm_inside_the_horizon_is_a_detection() -> None:
    rates = detector_rates(
        fault_ts_us=[SECOND * 1000],
        alarm_ts_us=[SECOND * 1100],
        horizon_s=600.0,
        duration_s=3600.0,
    )
    assert rates.detected == 1
    assert rates.missed == 0
    assert rates.false_alarms == 0
    assert rates.detection_delay_s == [pytest.approx(100.0)]


def test_an_alarm_before_the_fault_is_a_false_alarm_not_a_prophecy() -> None:
    """Direction matters. Crediting an alarm that fired first would let a twitchy detector score
    perfectly by alarming constantly."""
    rates = detector_rates(
        fault_ts_us=[SECOND * 1000],
        alarm_ts_us=[SECOND * 900],
        horizon_s=600.0,
        duration_s=3600.0,
    )
    assert rates.detected == 0
    assert rates.missed == 1
    assert rates.false_alarms == 1


def test_an_alarm_after_the_horizon_is_a_false_alarm_and_the_fault_is_missed() -> None:
    rates = detector_rates(
        fault_ts_us=[SECOND * 1000],
        alarm_ts_us=[SECOND * 5000],
        horizon_s=600.0,
        duration_s=7200.0,
    )
    assert rates.missed == 1
    assert rates.false_alarms == 1


def test_one_alarm_answers_one_fault_only() -> None:
    """Two faults and one alarm is one detection and one miss, however close together they are."""
    rates = detector_rates(
        fault_ts_us=[SECOND * 1000, SECOND * 1200],
        alarm_ts_us=[SECOND * 1100],
        horizon_s=600.0,
        duration_s=3600.0,
    )
    assert rates.detected == 1
    assert rates.missed == 1
    assert rates.false_alarms == 0


def test_extra_alarms_for_one_fault_are_counted_as_false() -> None:
    """A detector that fires five times for one fault has raised four alarms nobody needed, and an
    operator has to triage every one of them."""
    rates = detector_rates(
        fault_ts_us=[SECOND * 1000],
        alarm_ts_us=[SECOND * 1100, SECOND * 1200, SECOND * 1300],
        horizon_s=600.0,
        duration_s=3600.0,
    )
    assert rates.detected == 1
    assert rates.false_alarms == 2


def test_the_false_alarm_rate_has_a_denominator_an_operator_recognises() -> None:
    """Per hour of operation, because "twelve false alarms" means nothing without knowing whether
    that was a day or a year."""
    rates = detector_rates(
        fault_ts_us=[],
        alarm_ts_us=[SECOND * i for i in (100, 200)],
        horizon_s=600.0,
        duration_s=7200.0,
    )
    assert rates.false_alarms == 2
    assert rates.false_alarms_per_hour == pytest.approx(1.0)


def test_a_scenario_with_no_faults_can_still_be_scored() -> None:
    """S1 is the false-alarm measurement: nothing to detect, so every alarm is a false one."""
    rates = detector_rates(fault_ts_us=[], alarm_ts_us=[], horizon_s=600.0, duration_s=3600.0)
    assert rates.detected == 0 and rates.missed == 0 and rates.false_alarms == 0
    assert rates.recall is None, "recall on zero faults is undefined, not 1.0"


def test_recall_is_defined_when_there_are_faults() -> None:
    rates = detector_rates(
        fault_ts_us=[SECOND * 1000, SECOND * 2000],
        alarm_ts_us=[SECOND * 1100],
        horizon_s=600.0,
        duration_s=7200.0,
    )
    assert rates.recall == pytest.approx(0.5)


# -- estimator cost ------------------------------------------------------------------------------


def test_the_update_cost_is_reported_in_microseconds_and_bytes() -> None:
    """Buildspec section 10 asks for both, and the reason is deployment: this runs on a Pi beside
    a road, so an update that takes a millisecond or a state that will not fit in flash is a
    different kind of failure from an inaccurate one."""
    from wimsim.calibration import ReferenceObservation, build_estimator

    rng = np.random.default_rng(0)
    masses = rng.uniform(1000.0, 40000.0, 200)
    observations = [
        ReferenceObservation(
            ts_us=SECOND * i,
            feature=float(2.0e-4 * m),
            temp_c=20.0,
            reference_mass_kg=float(m),
        )
        for i, m in enumerate(masses)
    ]

    cost = estimator_cost(build_estimator("rls"), observations)
    assert 0.0 < cost.update_us < 10_000.0
    assert cost.state_bytes > 0
    assert cost.n_updates == len(observations)


def test_every_estimator_can_be_costed() -> None:
    from wimsim.calibration import ESTIMATORS, ReferenceObservation, build_estimator

    rng = np.random.default_rng(1)
    masses = rng.uniform(1000.0, 40000.0, 60)
    observations = [
        ReferenceObservation(
            ts_us=SECOND * i, feature=float(2.0e-4 * m), temp_c=20.0, reference_mass_kg=float(m)
        )
        for i, m in enumerate(masses)
    ]
    for name in ESTIMATORS:
        cost = estimator_cost(build_estimator(name), observations)
        assert cost.update_us > 0.0
        assert cost.state_bytes > 0


def test_the_carrying_state_is_bigger_than_the_frozen_one() -> None:
    """A covariance is state that has to survive a restart, and it is the reason the adaptive
    estimators cost more to persist than the baseline. Worth a number rather than a shrug."""
    from wimsim.calibration import ReferenceObservation, build_estimator

    rng = np.random.default_rng(2)
    masses = rng.uniform(1000.0, 40000.0, 40)
    observations = [
        ReferenceObservation(
            ts_us=SECOND * i, feature=float(2.0e-4 * m), temp_c=20.0, reference_mass_kg=float(m)
        )
        for i, m in enumerate(masses)
    ]
    baseline = estimator_cost(build_estimator("static_affine"), observations)
    adaptive = estimator_cost(build_estimator("kalman"), observations)
    assert adaptive.state_bytes > baseline.state_bytes


# -- the bundle ----------------------------------------------------------------------------------


def test_a_control_score_serialises_flat_for_the_results_table() -> None:
    """Results go to parquet and then to a comparison table, so nested structures would have to be
    flattened by every consumer instead of once here."""
    score = ControlScore(
        reconvergence=time_to_reconverge(
            _errors(600, shift_at=200, shift=400.0, recover_at=300),
            fault_ts_us=SECOND * 200,
            window=40,
        ),
        rates=detector_rates(
            fault_ts_us=[SECOND * 200],
            alarm_ts_us=[SECOND * 220],
            horizon_s=600.0,
            duration_s=600.0,
        ),
    )
    flat = score.to_dict()
    assert all(not isinstance(v, dict | list) for v in flat.values()), flat
    assert "reconverge_s" in flat
    assert "false_alarms_per_hour" in flat
    assert flat["detected"] == 1
