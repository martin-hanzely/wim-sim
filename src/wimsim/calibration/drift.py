"""Drift detectors on the residual stream.

Four of them, because they fail differently and the experiment reports both false-alarm and
missed-detection rates. The asymmetry of those two costs is the whole design constraint: a missed
detection is a scale that is quietly wrong for hours, and a false alarm is a recalibration the
station did not need, which consumes reference vehicles that may not exist and briefly makes the
calibration *worse*. Either number alone is easy to make look good.

| detector | what it is built to see | how it fails |
|---|---|---|
| ``CUSUM`` | a persistent shift in the mean | a spread change trips it, for the wrong reason |
| ``PageHinkley`` | the same, against a running mean | slower on a ramp that drags its own reference |
| ``ADWIN`` | any change in mean, with a self-chosen window | needs the buffer to span the change |
| ``KSWindow`` | any change in *distribution* | needs two full windows, so it is the slowest |

**The shipped defaults were measured, not inherited.** Textbook values for these detectors assume a
context; this one has 800-observation runs between recalibrations and an operator who will stop
believing a station that cries wolf. Each default below is the loosest setting whose false-alarm
rate over thirty independent stationary runs of 800 observations was at most 2, with the median
delay to detect a 3-sigma step alongside it:

| detector | default | false alarms | median delay |
|---|---|---|---|
| ``CUSUM`` | ``threshold=12, slack=0.5`` | 2/30 | 5 |
| ``PageHinkley`` | ``threshold=15, tolerance=0.5`` | 0/30 | 6 |
| ``ADWIN`` | ``delta=0.002`` | 0/30 | 10 |
| ``KSWindow`` | ``window=60, alpha=1e-4`` | 0/30 | 24 |

The ordering is the interesting part and it is the expected one: the cumulative sums are fastest,
ADWIN pays a little for choosing its own window, and the distribution test pays the most because it
cannot say anything until it has two full windows. Reproduce with the sweep at the bottom of
``tests/test_drift.py``.

Three properties are shared, and all three exist because of something that would otherwise go wrong
in the field rather than because the literature says so.

**They learn their reference from the stream.** Residuals are not centred on zero: a scale that is
slightly miscalibrated has a biased residual stream from its very first pass. A detector that
assumed zero would call that drift, when it is simply where this station started. So each detector
spends a warm-up estimating the location and scale it will judge against, and alarms on nothing
until it has them.

**They standardise.** A residual stream is in kilograms and its spread depends on the site, the
fleet and the estimator. Thresholds expressed in standard deviations transfer between stations;
thresholds in kilograms do not, and a config file that has to be retuned per site is a config file
that will not be.

**They clip.** One pothole is one pothole. A 40-sigma pass lands a 40-sigma increment in a
cumulative sum, which trips CUSUM on the spot -- textbook behaviour, and useless here, because drift
is a change in the *process* and a station that recalibrates on every pothole is worse than one that
never recalibrates at all. Standardised values are therefore clipped before they are accumulated, so
a single bad pass contributes a bounded amount and a persistent shift still accumulates without
limit. The cost is that a step larger than the clip is registered as exactly the clip, which delays
nothing that matters: a 4-sigma step and a 40-sigma step both need detecting, and neither needs
detecting *faster* than the other.

**They latch, and must be reset.** After a recalibration the residuals are centred somewhere new. A
detector that was not reset alarms immediately and forever, and the controller recalibrates in a
loop until it runs out of reference vehicles. ``reset()`` is the controller's half of that contract.
The latch is the other half: ADWIN naturally raises its alarm only on the single update where it
cuts the window, and a controller polling once per pass would miss it entirely. All four therefore
hold the alarm until it is acknowledged, so that ``alarm`` means "drift has been seen and not yet
handled" for every detector rather than three of them.
"""

from __future__ import annotations

import math
from collections import deque
from typing import Protocol, runtime_checkable

import numpy as np

__all__ = [
    "ADWIN",
    "CUSUM",
    "DETECTORS",
    "DriftDetector",
    "KSWindow",
    "PageHinkley",
    "build_detector",
]

#: Below this the stream is treated as having no spread at all, and standardisation is skipped
#: rather than dividing by it. A noiseless residual stream is not a realistic input, but it is a
#: realistic *test* input and a detector that returns NaN on one cannot be trusted on anything.
_MIN_SCALE = 1e-12


@runtime_checkable
class DriftDetector(Protocol):
    """A running statistic and a boolean, per buildspec section 6."""

    name: str

    def update(self, value: float) -> float: ...

    @property
    def statistic(self) -> float: ...

    @property
    def alarm(self) -> bool: ...

    def reset(self) -> None: ...


class _Standardising:
    """Shared warm-up: learn a location and a scale, then judge against them.

    The scale is the median absolute deviation rather than a standard deviation, because the
    warm-up window will contain the occasional pothole and one 40-sigma pass would otherwise set a
    scale so wide the detector never fires again -- a failure that is completely silent.
    """

    name = "base"

    def __init__(self, *, warmup: int = 200, clip: float = 4.0) -> None:
        if warmup < 2:
            raise ValueError(f"warmup must be at least 2 observations; got {warmup}")
        if clip <= 0.0:
            raise ValueError(f"clip must be positive; got {clip}")
        self.warmup = int(warmup)
        self.clip = float(clip)
        self._latched = False
        self._warmup_values: list[float] = []
        self._centre = 0.0
        self._scale = 0.0
        self._ready = False

    @property
    def ready(self) -> bool:
        return self._ready

    def _absorb(self, value: float) -> bool:
        """Take one warm-up observation. True once the reference is established."""
        self._warmup_values.append(value)
        if len(self._warmup_values) < self.warmup:
            return False
        sample = np.asarray(self._warmup_values, dtype=np.float64)
        self._centre = float(np.median(sample))
        mad = float(np.median(np.abs(sample - self._centre)))
        self._scale = mad * 1.4826
        self._ready = True
        return True

    def _z(self, value: float) -> float:
        """Standardised, and clipped so one pothole cannot trip a cumulative sum."""
        if self._scale <= _MIN_SCALE:
            return 0.0
        z = (value - self._centre) / self._scale
        return max(-self.clip, min(self.clip, z))

    def _raise(self, condition: bool) -> bool:
        """Latch the alarm. Once raised it stays raised until ``reset`` acknowledges it."""
        self._latched = self._latched or condition
        return self._latched

    def _reset_reference(self) -> None:
        self._latched = False
        self._warmup_values.clear()
        self._centre = 0.0
        self._scale = 0.0
        self._ready = False


class CUSUM(_Standardising):
    """Two-sided cumulative sum. The classic, and the one to beat on detection delay.

    Accumulates standardised deviations beyond a slack ``k`` and alarms when either the upward or
    the downward accumulation crosses ``h``. The slack is what makes it a *drift* detector rather
    than an outlier detector: deviations smaller than ``k`` never accumulate at all, so a single
    pothole decays away while a persistent half-sigma shift eventually adds up.
    """

    name = "cusum"

    def __init__(self, *, threshold: float = 12.0, slack: float = 0.5, warmup: int = 200) -> None:
        super().__init__(warmup=warmup)
        self.threshold = float(threshold)
        self.slack = float(slack)
        self._high = 0.0
        self._low = 0.0
        self._alarm = False

    def update(self, value: float) -> float:
        if not self._ready:
            self._absorb(float(value))
            return self.statistic
        z = self._z(float(value))
        self._high = max(0.0, self._high + z - self.slack)
        self._low = max(0.0, self._low - z - self.slack)
        self._alarm = self._raise(self.statistic >= self.threshold)
        return self.statistic

    @property
    def statistic(self) -> float:
        return max(self._high, self._low)

    @property
    def alarm(self) -> bool:
        return self._alarm

    def reset(self) -> None:
        self._high = self._low = 0.0
        self._alarm = False
        self._reset_reference()


class PageHinkley(_Standardising):
    """Page-Hinkley: the deviation of the running mean from its own extremum.

    Where CUSUM judges against a reference fixed at warm-up, this judges against the mean of
    everything seen since the last reset -- so it adapts to a slow ramp rather than accumulating
    against it, and detects a step by how far the cumulative deviation has run from its own minimum.
    Both directions are tracked, because a scale can drift either way and only one of them is the
    dangerous one for revenue.
    """

    name = "page_hinkley"

    def __init__(
        self, *, threshold: float = 15.0, tolerance: float = 0.5, warmup: int = 200
    ) -> None:
        super().__init__(warmup=warmup)
        self.threshold = float(threshold)
        self.tolerance = float(tolerance)
        self._n = 0
        self._mean = 0.0
        self._up = 0.0
        self._down = 0.0
        self._min_up = 0.0
        self._max_down = 0.0
        self._alarm = False

    def update(self, value: float) -> float:
        if not self._ready:
            self._absorb(float(value))
            return self.statistic
        z = self._z(float(value))
        self._n += 1
        self._mean += (z - self._mean) / self._n

        self._up += z - self._mean - self.tolerance
        self._min_up = min(self._min_up, self._up)
        self._down += z - self._mean + self.tolerance
        self._max_down = max(self._max_down, self._down)

        self._alarm = self._raise(self.statistic >= self.threshold)
        return self.statistic

    @property
    def statistic(self) -> float:
        return max(self._up - self._min_up, self._max_down - self._down)

    @property
    def alarm(self) -> bool:
        return self._alarm

    def reset(self) -> None:
        self._n = 0
        self._mean = self._up = self._down = self._min_up = self._max_down = 0.0
        self._alarm = False
        self._reset_reference()


class ADWIN(_Standardising):
    """Adaptive windowing: keep a window, and cut it wherever the two halves disagree.

    Every split point of the current window is tested for a difference of means larger than a
    Hoeffding bound; when one is found the older part is dropped, which both raises the alarm and
    leaves the window describing only the new regime. The attraction is that it chooses its own
    window rather than being given one, so it does not have to be told how fast the drift will be.

    **This implements ADWIN's decision rule over a bounded ring buffer, not ADWIN2's exponential
    histograms.** The histograms are a memory optimisation -- they let the window grow unboundedly
    in logarithmic space -- and they are not part of the statistical claim. A station processing a
    few hundred passes an hour does not need them, and a faithful, readable version of the test is
    worth more here than a compressed one nobody will check. ``max_window`` is the honest cost:
    a change that takes longer than that to arrive will be absorbed rather than detected, which is
    what the ramp test is for.
    """

    name = "adwin"

    def __init__(
        self, *, delta: float = 0.002, warmup: int = 200, max_window: int = 512, min_sub: int = 20
    ) -> None:
        super().__init__(warmup=warmup)
        if not 0.0 < delta < 1.0:
            raise ValueError(f"delta is a confidence and must lie in (0, 1); got {delta}")
        self.delta = float(delta)
        self.max_window = int(max_window)
        self.min_sub = int(min_sub)
        self._window: deque[float] = deque(maxlen=self.max_window)
        self._statistic = 0.0
        self._alarm = False

    def update(self, value: float) -> float:
        if not self._ready:
            self._absorb(float(value))
            return self.statistic
        self._window.append(self._z(float(value)))
        self._alarm = self._latched
        self._statistic = 0.0

        n = len(self._window)
        if n < 2 * self.min_sub:
            return self._statistic

        values = np.asarray(self._window, dtype=np.float64)
        prefix = np.cumsum(values)
        total = float(prefix[-1])

        worst = 0.0
        cut_at: int | None = None
        for i in range(self.min_sub, n - self.min_sub + 1):
            n0, n1 = i, n - i
            mean0 = float(prefix[i - 1]) / n0
            mean1 = (total - float(prefix[i - 1])) / n1
            epsilon = self._hoeffding_bound(n0, n1, n)
            ratio = abs(mean0 - mean1) / epsilon
            if ratio > worst:
                worst = ratio
                if ratio > 1.0:
                    cut_at = i

        self._statistic = worst
        if cut_at is not None:
            self._alarm = self._raise(True)
            for _ in range(cut_at):
                self._window.popleft()
        return self._statistic

    def _hoeffding_bound(self, n0: int, n1: int, n: int) -> float:
        """ADWIN's cut threshold, on standardised values so the variance is 1 by construction."""
        m = 1.0 / (1.0 / n0 + 1.0 / n1)
        delta_prime = self.delta / max(n, 1)
        return math.sqrt(2.0 / m * math.log(2.0 / delta_prime))

    @property
    def statistic(self) -> float:
        return self._statistic

    @property
    def alarm(self) -> bool:
        return self._alarm

    def reset(self) -> None:
        self._window.clear()
        self._statistic = 0.0
        self._alarm = False
        self._reset_reference()


class KSWindow(_Standardising):
    """Two-sample Kolmogorov-Smirnov between a reference window and a recent one.

    The only one of the four that tests the whole distribution rather than its mean, which is why
    it is here: a scale whose noise has doubled has not moved its mean at all, and CUSUM and
    Page-Hinkley are blind to it by construction. It pays for that with latency -- it needs two full
    windows before it can say anything -- and with sensitivity to the window length, which is a
    genuine tuning burden and the reason it is not the default.

    The critical value is the standard asymptotic one, ``c(alpha) * sqrt((n+m)/(nm))``. Asymptotic
    is defensible at these window sizes and the alternative is an exact distribution that would need
    scipy, which principle 6 does not permit here.
    """

    name = "ks"

    def __init__(self, *, window: int = 60, alpha: float = 1e-4, warmup: int = 200) -> None:
        super().__init__(warmup=warmup)
        if window < 5:
            raise ValueError(f"window must hold at least 5 observations; got {window}")
        if not 0.0 < alpha < 1.0:
            raise ValueError(f"alpha is a significance and must lie in (0, 1); got {alpha}")
        self.window = int(window)
        self.alpha = float(alpha)
        self._reference: np.ndarray | None = None
        self._recent: deque[float] = deque(maxlen=self.window)
        self._statistic = 0.0
        self._alarm = False

    def update(self, value: float) -> float:
        if not self._ready:
            if self._absorb(float(value)):
                # The warm-up sample doubles as the reference distribution: it is already the
                # longest stretch of "normal" this detector will ever be handed.
                self._reference = np.sort(
                    np.asarray([self._z(v) for v in self._warmup_values], dtype=np.float64)
                )
            return self.statistic

        self._recent.append(self._z(float(value)))
        if self._reference is None or len(self._recent) < self.window:
            return self._statistic

        recent = np.sort(np.asarray(self._recent, dtype=np.float64))
        d = self._ks_distance(self._reference, recent)
        critical = self._critical_value(len(self._reference), len(recent))
        self._statistic = d / critical if critical > 0 else 0.0
        self._alarm = self._raise(self._statistic >= 1.0)
        return self._statistic

    @staticmethod
    def _ks_distance(a: np.ndarray, b: np.ndarray) -> float:
        """Sup-norm between two empirical CDFs. Both inputs are already sorted."""
        merged = np.concatenate([a, b])
        cdf_a = np.searchsorted(a, merged, side="right") / a.size
        cdf_b = np.searchsorted(b, merged, side="right") / b.size
        return float(np.max(np.abs(cdf_a - cdf_b)))

    def _critical_value(self, n: int, m: int) -> float:
        c = math.sqrt(-0.5 * math.log(self.alpha / 2.0))
        return c * math.sqrt((n + m) / (n * m))

    @property
    def statistic(self) -> float:
        return self._statistic

    @property
    def alarm(self) -> bool:
        return self._alarm

    def reset(self) -> None:
        self._reference = None
        self._recent.clear()
        self._statistic = 0.0
        self._alarm = False
        self._reset_reference()


#: Name -> constructor. Configs name detectors as strings and ``wim_drift_statistic`` is labelled by
#: detector, so this set is a contract with both the config files and the dashboard.
DETECTORS: dict[str, type] = {
    CUSUM.name: CUSUM,
    PageHinkley.name: PageHinkley,
    ADWIN.name: ADWIN,
    KSWindow.name: KSWindow,
}


def build_detector(name: str, **kwargs) -> DriftDetector:
    try:
        cls = DETECTORS[name]
    except KeyError:
        raise KeyError(f"unknown drift detector {name!r}; the set is {sorted(DETECTORS)}") from None
    return cls(**kwargs)
