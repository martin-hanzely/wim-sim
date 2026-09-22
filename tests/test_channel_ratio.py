"""Two channels watched against each other, with no reference vehicle involved.

Every other detector in `calibration/` watches the residual against a known mass, so every one of
them needs reference vehicles -- and the reference-rate sweep measured what that costs when they are
scarce. A two-channel installation has a signal that is free: the gauges sit at a fixed amplitude
ratio because they are two views of the same load, and nothing about that needs to know what the
vehicle weighed.

The tests are mostly about the boundaries of the claim, because a detector that is oversold is worse
than one that is absent:

* it sees a fault in ONE channel, which is exactly what the residual detectors are worst at;
* it is blind to anything common to both, which is what they are best at;
* it detects without diagnosing -- two channels give one equation, so which channel moved is not
  recoverable from the ratio;
* and it must not learn the fault it has just found.
"""

from __future__ import annotations

import numpy as np
import pytest

from wimsim.calibration.channel_ratio import ChannelRatioMonitor


def _healthy(n: int, *, ratio: float = 2.9, spread: float = 0.35, seed: int = 0):
    """(Tenzo1, Tenzo2) peaks at the measured ratio and scatter."""
    rng = np.random.default_rng(seed)
    out = []
    for _ in range(n):
        a = float(rng.uniform(4.0e-6, 6.5e-6))
        out.append((a, a * (ratio + float(rng.normal(0.0, spread)))))
    return out


def test_a_healthy_pair_never_alarms() -> None:
    """At the real corpus's scatter: ratio 2.98 +/- 0.37 on the Citroen, 2.78 +/- 0.34 on the
    Fabia. A monitor that cannot sit quietly through that is unusable here."""
    monitor = ChannelRatioMonitor()
    for a, b in _healthy(400, seed=1):
        monitor.observe(a, b)
    assert not monitor.alarmed
    assert monitor.ready


def test_one_channel_losing_sensitivity_is_caught() -> None:
    """The fault the residual detectors are worst at: a single gauge drifting while the other is
    fine. Against a reference vehicle it looks like a small mass error; against the other channel
    it is unmistakable."""
    monitor = ChannelRatioMonitor()
    for a, b in _healthy(60, seed=2):
        monitor.observe(a, b)
    assert not monitor.alarmed

    for a, b in _healthy(40, seed=3):
        monitor.observe(a, b * 0.5)  # Tenzo2 loses half its sensitivity
    assert monitor.alarmed


def test_a_fault_common_to_both_channels_is_invisible_and_that_is_stated() -> None:
    """A platform losing stiffness, a temperature moving both gauges, one amplifier supply feeding
    both -- the ratio does not move. This is a complement to the residual detectors, not a
    substitute, and the test exists so the limitation is not discovered in the field."""
    monitor = ChannelRatioMonitor()
    for a, b in _healthy(60, seed=4):
        monitor.observe(a, b)
    for a, b in _healthy(60, seed=5):
        monitor.observe(a * 0.4, b * 0.4)  # both channels lose 60 %
    assert not monitor.alarmed


def test_it_does_not_learn_the_fault_it_just_found() -> None:
    """A detector that folds the outlier into its own baseline stops being able to see it, which is
    how a drift monitor ends up reporting that everything is fine through a fault."""
    monitor = ChannelRatioMonitor()
    for a, b in _healthy(60, seed=6):
        monitor.observe(a, b)
    before, _ = monitor.baseline()

    for a, b in _healthy(200, seed=7):
        monitor.observe(a, b * 0.5)
    after, _ = monitor.baseline()

    assert monitor.alarmed
    assert after == pytest.approx(before, rel=0.05), "the baseline followed the fault"


def test_the_alarm_latches_until_it_is_reset() -> None:
    """Every other detector in this package latches; this one has to agree with them or the
    controller has two notions of what an alarm is."""
    monitor = ChannelRatioMonitor()
    for a, b in _healthy(60, seed=8):
        monitor.observe(a, b)
    for a, b in _healthy(5, seed=9):
        monitor.observe(a, b * 0.5)
    assert monitor.alarmed

    for a, b in _healthy(50, seed=10):
        monitor.observe(a, b)
    assert monitor.alarmed, "a latched alarm must survive the fault going away"

    monitor.reset()
    assert not monitor.alarmed
    assert not monitor.ready


def test_it_says_nothing_before_it_has_a_baseline() -> None:
    monitor = ChannelRatioMonitor(warmup=12)
    for a, b in _healthy(11, seed=11):
        assert not monitor.observe(a, b)
    assert not monitor.ready
    assert np.isnan(monitor.baseline()[0])


def test_a_crossing_too_small_to_have_a_ratio_is_ignored() -> None:
    """Two near-zero peaks divide into a number with no information and enormous variance, and
    folding those in would widen the baseline until nothing could ever trip it."""
    monitor = ChannelRatioMonitor(min_peak=1.0e-6)
    for a, b in _healthy(60, seed=12):
        monitor.observe(a, b)
    baseline_before = monitor.baseline()

    for _ in range(50):
        monitor.observe(1.0e-9, 9.0e-9)  # ratio 9, but both peaks are noise
    assert not monitor.alarmed
    assert monitor.baseline() == pytest.approx(baseline_before)


def test_a_zero_reference_peak_is_not_a_division_by_zero() -> None:
    monitor = ChannelRatioMonitor()
    for a, b in _healthy(60, seed=13):
        monitor.observe(a, b)
    assert not monitor.observe(0.0, 5.0e-6)
    assert not monitor.observe(float("nan"), 5.0e-6)


def test_the_resolution_limit_is_the_scatter_and_is_stated() -> None:
    """The measured ratio spread is 12 % of its own value, so at three sigmas a single-channel
    change has to reach roughly 36 % before three consecutive crossings fall outside the band.

    This finds gross faults -- a gauge half dead, a bond failing, a channel unplugged -- and will
    not find a 10 % drift. Worth pinning, because a detector believed to be more sensitive than it
    is, is worse than no detector.
    """
    for factor, expected in ((0.90, False), (1.20, False), (0.50, True), (2.00, True)):
        monitor = ChannelRatioMonitor()
        for a, b in _healthy(60, seed=14):
            monitor.observe(a, b)
        for a, b in _healthy(40, seed=15):
            monitor.observe(a, b * factor)
        assert monitor.alarmed is expected, factor


def test_it_reports_its_state_for_a_dashboard() -> None:
    monitor = ChannelRatioMonitor()
    for a, b in _healthy(60, seed=16):
        monitor.observe(a, b)
    payload = monitor.to_dict()
    assert payload["ready"] and not payload["alarmed"]
    assert payload["baseline_ratio"] == pytest.approx(2.9, rel=0.1)
    assert payload["n_seen"] == 60


def test_a_warmup_too_short_to_estimate_a_spread_is_refused() -> None:
    with pytest.raises(ValueError, match="warmup"):
        ChannelRatioMonitor(warmup=2)
