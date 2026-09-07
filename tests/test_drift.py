"""Drift detectors on the residual stream.

Four detectors, because they fail differently and the paper reports both false-alarm and
missed-detection rates. The tests are organised around that: every detector gets the same battery,
so the table they produce is a comparison rather than four separate anecdotes.

What makes a detector *useful here* rather than merely correct is the asymmetry of the costs. A
missed detection means a scale that is quietly wrong for hours. A false alarm means a recalibration
the station did not need, which consumes reference vehicles that may not exist and briefly makes the
calibration worse. Neither number is meaningful without the other, so both are measured on every
detector below.
"""

from __future__ import annotations

import numpy as np
import pytest

from wimsim.calibration import (
    ADWIN,
    CUSUM,
    DETECTORS,
    DriftDetector,
    KSWindow,
    PageHinkley,
    build_detector,
)

#: The shipped defaults, with a shorter warm-up so the tests do not spend a thousand observations
#: getting started. Deliberately *not* a separate set of tuning: a battery tuned for the tests would
#: be measuring something nobody ships. See the sweep at the bottom of this file for where these
#: numbers come from.
BATTERY = {
    "cusum": lambda: CUSUM(warmup=100),
    "page_hinkley": lambda: PageHinkley(warmup=100),
    "adwin": lambda: ADWIN(warmup=100),
    "ks": lambda: KSWindow(warmup=100),
}
NAMES = sorted(BATTERY)


def _stream(n: int, *, shift: float = 0.0, scale: float = 1.0, seed: int = 0) -> np.ndarray:
    rng = np.random.default_rng(seed)
    return shift + scale * rng.standard_normal(n)


# -- the interface ---------------------------------------------------------------------------


@pytest.mark.parametrize("name", NAMES)
def test_every_detector_satisfies_the_protocol(name: str) -> None:
    assert isinstance(BATTERY[name](), DriftDetector)


@pytest.mark.parametrize("name", NAMES)
def test_the_registry_can_build_every_detector_by_name(name: str) -> None:
    """Configs name detectors as strings and the drift metric is labelled by detector, so the set
    of names is a contract with both the config files and the dashboard."""
    assert name in DETECTORS
    detector = build_detector(name)
    assert detector.name == name


def test_an_unknown_detector_name_is_refused_with_the_list() -> None:
    with pytest.raises(KeyError, match="cusum"):
        build_detector("cusim")


@pytest.mark.parametrize("name", NAMES)
def test_a_fresh_detector_is_not_alarming(name: str) -> None:
    detector = BATTERY[name]()
    assert not detector.alarm
    assert detector.statistic == 0.0


# -- warm-up ---------------------------------------------------------------------------------


@pytest.mark.parametrize("name", NAMES)
def test_nothing_alarms_during_warmup(name: str) -> None:
    """A detector that fires while it is still learning what normal looks like would trigger a
    recalibration on the first vehicle after every restart."""
    detector = BATTERY[name]()
    for value in _stream(80, shift=50.0, scale=10.0, seed=1):
        detector.update(float(value))
        assert not detector.alarm


@pytest.mark.parametrize("name", NAMES)
def test_the_reference_is_learned_from_the_stream_not_assumed_to_be_zero(name: str) -> None:
    """Residuals are not centred on zero in general -- a miscalibrated scale has a biased residual
    stream from the first pass. A detector that assumes zero would call that drift, when it is
    simply where this station started."""
    detector = BATTERY[name]()
    for value in _stream(400, shift=17.0, scale=2.0, seed=2):
        detector.update(float(value))
    assert not detector.alarm


# -- detection -------------------------------------------------------------------------------


@pytest.mark.parametrize("name", NAMES)
def test_a_step_in_the_mean_is_detected(name: str) -> None:
    detector = BATTERY[name]()
    for value in _stream(300, seed=3):
        detector.update(float(value))
    assert not detector.alarm, "alarmed before the step"

    for value in _stream(200, shift=3.0, seed=4):
        detector.update(float(value))
        if detector.alarm:
            break
    assert detector.alarm


@pytest.mark.parametrize("name", NAMES)
def test_detection_delay_is_reported_and_is_not_absurd(name: str) -> None:
    """Time-to-detect is half of the headline control metric -- the other half is time to
    reconverge after it. A detector with an unbounded delay is a detector that does not work."""
    detector = BATTERY[name]()
    for value in _stream(300, seed=5):
        detector.update(float(value))

    delay = None
    for i, value in enumerate(_stream(300, shift=3.0, seed=6), start=1):
        detector.update(float(value))
        if detector.alarm:
            delay = i
            break
    assert delay is not None and delay <= 100


@pytest.mark.parametrize("name", NAMES)
def test_a_larger_step_is_detected_sooner(name: str) -> None:
    """The monotonicity that makes a detector interpretable. Without it, an alarm says nothing
    about how bad the drift is."""

    def delay(shift: float) -> int:
        detector = BATTERY[name]()
        for value in _stream(300, seed=7):
            detector.update(float(value))
        for i, value in enumerate(_stream(400, shift=shift, seed=8), start=1):
            detector.update(float(value))
            if detector.alarm:
                return i
        return 10_000

    assert delay(4.0) <= delay(1.0)


# -- false alarms ------------------------------------------------------------------------------


@pytest.mark.parametrize("name", NAMES)
def test_the_false_alarm_rate_on_a_stationary_stream_is_low(name: str) -> None:
    """The number that decides whether a controller can be left running unattended.

    Twenty independent stationary streams of 800 observations. A detector that fires on more than
    a couple of them is one that would recalibrate a healthy station several times a day.
    """
    alarms = 0
    for seed in range(20):
        detector = BATTERY[name]()
        for value in _stream(800, seed=1000 + seed):
            detector.update(float(value))
            if detector.alarm:
                alarms += 1
                break
    assert alarms <= 2, f"{name} raised {alarms}/20 false alarms"


@pytest.mark.parametrize("name", NAMES)
def test_a_single_outlier_does_not_raise_an_alarm(name: str) -> None:
    """One bad pass is a bad pass. Drift is a change in the *process*, and a detector that cannot
    tell them apart will recalibrate on every pothole."""
    detector = BATTERY[name]()
    for value in _stream(300, seed=9):
        detector.update(float(value))
    detector.update(40.0)
    assert not detector.alarm


# -- what distinguishes them ---------------------------------------------------------------------


def test_only_the_distribution_test_sees_a_change_that_leaves_the_moments_alone() -> None:
    """Why four detectors rather than one, established the hard way.

    The obvious claim -- that CUSUM and Page-Hinkley are blind to a change in *spread* -- turns out
    to be false here, and measurably so: on a fourfold variance increase all four fire, and CUSUM is
    the fastest of them. It fires for the wrong reason (a wider distribution random-walks its
    cumulative sum across the threshold sooner) but it fires, so that is not the discriminator.

    What genuinely separates them is a change that leaves *both* moments alone. A residual stream
    that goes from Gaussian to two-point with the same mean and the same variance is a fleet that
    has become two fleets, or a second failure mode adding occasional large errors that cancel on
    average. Measured over twenty runs: KS detects it 20/20, and the three mean-based detectors
    detect it 0/20. That is the argument for reporting the detectors separately rather than
    collapsing them into one alarm.
    """
    rng = np.random.default_rng(31)

    def detects_matched_moment_change(name: str) -> bool:
        detector = BATTERY[name]()
        for value in _stream(400, seed=11):
            detector.update(float(value))
        assert not detector.alarm
        for value in rng.choice([-1.0, 1.0], size=400):  # mean 0, variance 1, no centre
            detector.update(float(value))
            if detector.alarm:
                return True
        return False

    assert detects_matched_moment_change("ks")
    assert not detects_matched_moment_change("cusum")
    assert not detects_matched_moment_change("page_hinkley")
    assert not detects_matched_moment_change("adwin")


@pytest.mark.parametrize("name", NAMES)
def test_a_change_in_spread_alone_is_detected_by_all_four(name: str) -> None:
    """The counterpart to the test above, and the reason it had to be written that way. A scale
    whose noise has quadrupled is broken even though its mean is untouched, and every detector here
    does notice -- so nothing is missing this failure, whatever the textbook says about CUSUM."""
    detector = BATTERY[name]()
    for value in _stream(400, seed=11):
        detector.update(float(value))
    for value in _stream(600, scale=4.0, seed=12):
        detector.update(float(value))
        if detector.alarm:
            return
    pytest.fail(f"{name} did not notice a fourfold increase in residual spread")


@pytest.mark.parametrize("name", NAMES)
def test_a_slow_ramp_is_eventually_detected(name: str) -> None:
    """Thermal drift is a ramp, not a step, and a detector that only responds to steps would miss
    the failure mode this project is actually about."""
    detector = BATTERY[name]()
    for value in _stream(300, seed=13):
        detector.update(float(value))

    rng = np.random.default_rng(14)
    fired = False
    for i in range(600):
        detector.update(float(0.01 * i + rng.standard_normal()))
        if detector.alarm:
            fired = True
            break
    assert fired


# -- resetting ------------------------------------------------------------------------------------


@pytest.mark.parametrize("name", NAMES)
def test_reset_clears_the_alarm_and_relearns_the_new_normal(name: str) -> None:
    """The controller's side of the contract. After a recalibration the residuals are centred
    somewhere new; a detector that was not reset would alarm immediately and forever, and the
    station would recalibrate in a loop until it ran out of reference vehicles.
    """
    detector = BATTERY[name]()
    for value in _stream(300, seed=15):
        detector.update(float(value))
    for value in _stream(300, shift=5.0, seed=16):
        detector.update(float(value))
    assert detector.alarm

    detector.reset()
    assert not detector.alarm
    assert detector.statistic == 0.0

    for value in _stream(400, shift=5.0, seed=17):
        detector.update(float(value))
    assert not detector.alarm, "re-alarmed on the level it was reset onto"


@pytest.mark.parametrize("name", NAMES)
def test_the_statistic_is_finite_and_non_negative_throughout(name: str) -> None:
    """It is published as a gauge and drawn on a dashboard; a NaN there is a panel that stops
    updating without saying why."""
    detector = BATTERY[name]()
    for value in np.concatenate([_stream(200, seed=18), _stream(200, shift=6.0, seed=19)]):
        detector.update(float(value))
        assert np.isfinite(detector.statistic)
        assert detector.statistic >= 0.0


@pytest.mark.parametrize("name", NAMES)
def test_a_degenerate_stream_does_not_divide_by_zero(name: str) -> None:
    """A perfectly noiseless residual stream has zero spread, and every one of these detectors
    standardises by it somewhere."""
    detector = BATTERY[name]()
    for _ in range(400):
        detector.update(1.0)
    assert np.isfinite(detector.statistic)
    detector.update(1.0)
    assert np.isfinite(detector.statistic)


# -- the sweep behind the shipped defaults -----------------------------------------------------


@pytest.mark.slow
def test_the_documented_operating_points_reproduce() -> None:
    """The table in ``calibration/drift.py`` is a measurement, so it has to be re-measurable.

    Each default is the loosest setting whose false-alarm count over thirty stationary runs of 800
    observations is at most two. Thresholds tightened from the textbook values on the strength of
    exactly this: at CUSUM's conventional h=5 the false-alarm count was 25 out of 30, which is a
    station that recalibrates several times a day for no reason.
    """
    expected_max_false_alarms = {"cusum": 2, "page_hinkley": 1, "adwin": 1, "ks": 1}

    for name, allowed in expected_max_false_alarms.items():
        alarms = 0
        for seed in range(30):
            detector = BATTERY[name]()
            for value in _stream(800, seed=5000 + seed):
                detector.update(float(value))
                if detector.alarm:
                    alarms += 1
                    break
        assert alarms <= allowed, f"{name}: {alarms}/30 false alarms at the shipped default"

    delays = {}
    for name in NAMES:
        runs = []
        for seed in range(10):
            detector = BATTERY[name]()
            for value in _stream(300, seed=100 + seed):
                detector.update(float(value))
            for i, value in enumerate(_stream(400, shift=3.0, seed=200 + seed), start=1):
                detector.update(float(value))
                if detector.alarm:
                    runs.append(i)
                    break
        delays[name] = float(np.median(runs))

    # Cumulative sums fastest, ADWIN paying a little to choose its own window, the distribution
    # test slowest because it cannot speak until it holds two full windows.
    assert delays["cusum"] <= delays["adwin"] <= delays["ks"]
    assert delays["page_hinkley"] <= delays["adwin"]
    assert all(d <= 40 for d in delays.values())
