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
    assert abs(result.baseline_error) < 20.0, "a healthy estimator's signed median sits near zero"
    assert result.final_error > 300.0, "and the fault moved it, in a direction"


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
    result = time_to_reconverge(rows, fault_ts_us=SECOND * 200, window=40)
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
    """The baseline is the pre-fault *signed* median, so a healthy estimator's is near zero however
    wide its residual spread. An estimator whose errors are large but symmetric is not biased."""
    rows = _errors(600, shift_at=200, shift=400.0, recover_at=300, scale=50.0)
    result = time_to_reconverge(rows, fault_ts_us=SECOND * 200, window=40)
    assert abs(result.baseline_error) < 20.0


# -- why the statistic is signed ------------------------------------------------------------------


def test_a_bias_shift_smaller_than_the_spread_is_not_recovery() -> None:
    """The reason this metric was rewritten.

    It used to track a rolling median of |error| against 1.5x its pre-fault level. That is blind to
    any bias shift smaller than about half the spread, because |error| barely moves when a wide
    symmetric distribution slides sideways. Measured on `S7_sparse_reference`: static_affine was
    reported as reconverging in 187-327 s while carrying -96.7 kg of bias, on a residual spread of
    158 kg. The calibration had not recovered at all; the metric could not see it.

    A signed median sees it directly, which is what a metric about *calibration* has to do.
    """
    spread = 158.0
    rows = _errors(2000, shift_at=400, shift=-96.7, scale=spread, seed=5)

    # window=160, not the default 40. S7 scores seven thousand passes, so a window of forty is far
    # smaller than the data supports -- and the threshold scales as 1/sqrt(window), so at forty a
    # 97 kg bias on a 158 kg spread sits right on the line. See the resolution test below: the
    # limit is a property of the window, and choosing it is choosing what the metric can see.
    result = time_to_reconverge(rows, fault_ts_us=SECOND * 400, window=160)
    assert result.departed
    assert not result.reconverged, "a 97 kg bias on a 158 kg spread is not a recovery"
    assert result.final_error < -50.0


def test_the_smallest_resolvable_bias_is_a_stated_property_of_the_window() -> None:
    """The metric can only see a shift it can distinguish from sampling noise, and that limit is
    `tolerance_sigma * 1.2533 * sigma / sqrt(window)` -- about 0.59 sigma at the defaults, and
    tightening with the square root of the window.

    Worth pinning rather than discovering: a caller who needs to resolve a smaller bias has to
    spend passes on it, and gets a coarser recovery *time* in exchange. That trade is the design.
    """
    import math

    from wimsim.experiments.control_scoring import _MEDIAN_EFFICIENCY

    def limit(window: int, sigma: float = 1.0, tolerance_sigma: float = 3.0) -> float:
        return tolerance_sigma * _MEDIAN_EFFICIENCY * sigma / math.sqrt(window)

    assert limit(40) == pytest.approx(0.594, abs=0.01)
    assert limit(160) == pytest.approx(0.297, abs=0.01)

    # And it is the limit the implementation actually applies. Checked over several seeds and well
    # clear of the boundary on each side, because a single seed sitting near the line measures that
    # seed's realised noise rather than the rule -- the first version of this test asserted at
    # 0.9 sigma and failed on a stretch whose window median happened to land 3 standard errors low.
    for seed in (11, 12, 13):
        inside = _errors(800, shift_at=200, shift=0.20 * 50.0, scale=50.0, seed=seed)
        outside = _errors(800, shift_at=200, shift=2.00 * 50.0, scale=50.0, seed=seed)
        # Whether the metric can SEE the shift is the property under test, and that is `departed`.
        # A shift it cannot see produces no departure, and therefore no recovery either.
        assert not time_to_reconverge(inside, fault_ts_us=SECOND * 200, window=40).departed, seed
        assert time_to_reconverge(outside, fault_ts_us=SECOND * 200, window=40).departed, seed


def test_the_same_shift_would_have_passed_the_old_absolute_test() -> None:
    """A negative control for the test above: it only has force if |error| really is blind here."""
    import numpy as np

    rows = _errors(800, shift_at=200, shift=-96.7, scale=158.0, seed=5)
    absolute = np.abs([e for _ts, e in rows])
    before = float(np.median(absolute[160:200]))
    after = float(np.median(absolute[-40:]))
    assert after < 1.5 * before, (
        "the old rule's threshold was 1.5x the pre-fault median |error|, and this bias shift "
        "stays under it -- which is exactly how it was scored as recovered"
    )


def test_recovery_is_judged_against_the_noise_the_median_actually_has() -> None:
    """The threshold is `tolerance_sigma` standard errors of the median, which is the same test the
    controller applies when it decides drift has occurred (`_displaced`). The metric and the loop
    therefore agree on what "moved" means, rather than each carrying its own private definition.

    A wider spread has to permit a wider residual bias, or a noisy site could never reconverge.
    """
    quiet = time_to_reconverge(
        _errors(600, shift_at=200, shift=200.0, recover_at=300, scale=10.0, seed=7),
        fault_ts_us=SECOND * 200,
        window=40,
    )
    noisy = time_to_reconverge(
        _errors(600, shift_at=200, shift=200.0, recover_at=300, scale=80.0, seed=7),
        fault_ts_us=SECOND * 200,
        window=40,
    )
    assert quiet.reconverged and noisy.reconverged


def test_a_tighter_tolerance_refuses_the_recovery_a_looser_one_accepts() -> None:
    """`tolerance_sigma` has to bite, or it is decoration.

    The signal departs hard and then settles at a small residual offset. A loose tolerance calls
    that residual a recovery; a tight one does not. Both agree the error departed -- what they
    disagree about is whether it came back, which is the judgement the parameter exists to make.
    """
    rows = _errors(900, shift_at=200, shift=400.0, recover_at=300, scale=50.0, seed=8)
    rows = [(ts, e + (40.0 if i >= 300 else 0.0)) for i, (ts, e) in enumerate(rows)]

    loose = time_to_reconverge(rows, fault_ts_us=SECOND * 200, window=40, tolerance_sigma=12.0)
    tight = time_to_reconverge(rows, fault_ts_us=SECOND * 200, window=40, tolerance_sigma=1.0)

    assert loose.departed and tight.departed
    assert loose.reconverged
    assert not tight.reconverged


def test_an_error_that_never_departed_did_not_reconverge() -> None:
    """Found by running the rewritten metric on the case it was rewritten for.

    `S7_sparse_reference` injects a 3 % gain loss ramped over TWO HOURS. Reconvergence is measured
    from the fault's start time, and 187 s in, the ramp has barely begun -- the error has not moved,
    so the very first window is trivially "back at baseline" and the metric declared recovery from
    a disturbance that had not arrived yet. It reported 187 s under the old absolute statistic and
    187 s under the signed one, because the statistic was never the problem here.

    Recovery has to mean the error left and came back. If it never left, there was nothing to
    recover from, and saying so is more useful than a fast-looking number.
    """
    rows = _errors(800, shift_at=200, shift=0.0, scale=50.0, seed=21)
    result = time_to_reconverge(rows, fault_ts_us=SECOND * 200, window=40)

    assert result.measurable, "there were plenty of passes; the run was measurable"
    assert not result.departed
    assert not result.reconverged
    assert result.seconds is None


def test_a_slow_ramp_is_not_recovery_just_because_it_started_slowly() -> None:
    """The S7 shape: the error leaves gradually and does not come back inside the run."""
    rows = _errors(900, scale=50.0, seed=22)
    ramped = [
        (ts, e + (-300.0 * min((i - 200) / 400.0, 1.0) if i >= 200 else 0.0))
        for i, (ts, e) in enumerate(rows)
    ]
    result = time_to_reconverge(ramped, fault_ts_us=SECOND * 200, window=40)

    assert result.departed, "a 300 kg ramp on a 50 kg spread is a departure"
    assert not result.reconverged


def test_recovery_is_timed_from_the_fault_not_from_the_departure() -> None:
    """The number an operator cares about is how long the site was wrong, which starts when the
    fault was injected -- not when the metric first noticed."""
    rows = _errors(700, shift_at=200, shift=400.0, recover_at=300, scale=50.0, seed=23)
    result = time_to_reconverge(rows, fault_ts_us=SECOND * 200, window=40)

    assert result.departed and result.reconverged
    assert result.seconds >= 100.0, "recovery was at pass 300, a hundred passes after the fault"


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
        estimator = build_estimator(name)
        if not hasattr(estimator, "update"):
            continue
        cost = estimator_cost(estimator, observations)
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
