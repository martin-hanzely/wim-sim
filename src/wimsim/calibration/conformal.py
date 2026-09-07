"""Split conformal prediction: an interval that does not ask the residuals to be Gaussian.

Buildspec section 6 calls empirical coverage "the single most persuasive number for a small-real-data
paper". The analytic intervals shipped so far only earn it when their assumptions hold, and there is
already evidence from this project that they do not: phase 2 measured empirical coverage of 0.906
against a nominal 0.95 on clean synthetic data, and phase 4 measured 0.750 once mains hum was
enabled -- because mains is coherent, so the error it adds is structured rather than Gaussian and an
interval built from a standard deviation misprices it.

**The textbook justification for this is not quite right, and the measured one is better.** "A
Gaussian interval under-covers on non-Gaussian residuals" is false as a general statement: over
sixty calibration draws per shape it lands within 0.001 of nominal on Student-t(3) and within 0.006
on a lognormal, essentially by luck -- the standard deviation is inflated by the same tail that
produces the extreme residuals, and the two errors cancel. Where it fails, it fails badly and in
both directions: 0.936 on a Laplace, and 1.000 on a bimodal residual stream, where a standard
deviation inflated by the hole in the middle gives a band so wide it can no longer distinguish an
overloaded truck from a legal one. Over-covering is not the safe failure it sounds like. So the
claim worth making is about *reliability*: the analytic interval's accuracy depends on a
distribution shape nobody measured, and conformal's does not.

Conformal makes no distributional assumption. Given nonconformity scores from a calibration set that
is exchangeable with what comes next, the interval built from the
``ceil((n+1)(1-alpha))``-th smallest score covers with probability at least ``1-alpha`` in *finite
samples*. That ``(n+1)`` is not a rounding detail: it is what turns an asymptotic statement into a
guarantee, and it only visibly matters at small ``n`` -- which is exactly the regime a station with a
handful of reference vehicles lives in permanently.

**Two scores, and the second is the interesting one.**

``absolute``
    ``|truth - prediction|``. A constant-width band, directly comparable with the residual-spread
    and Kalman intervals.
``relative``
    ``|truth - prediction| / |prediction|``. A band proportional to the load.

The relative score exists because of a measurement made in phase 4: once the Kalman filter has
converged, over 95 % of its interval variance is ``R/k^2``, the sensor's own noise mapped into
kilograms, which for an additive sensor noise does not depend on the load at all. So the analytic
interval is very nearly constant-width -- and so is anything built from a residual standard
deviation. But a weighing error is largely *proportional* to what is being weighed, so a constant
band over-covers cars and under-covers trucks while averaging out to something that looks nominal.
Normalising the score fixes the shape without giving up the guarantee, and the marginal coverage
becomes conditional coverage at every load, which is a strictly stronger statement.

**The honest limitation is exchangeability, and drift breaks it.** A calibration set gathered before
a step fault does not describe the residuals after one. The design here is a bounded sliding window,
so the set forgets: coverage degrades gracefully into "recent history" rather than resting on a
guarantee that has quietly stopped applying. Combined with the controller resetting it on
recalibration, that is the best available answer short of an online conformal method with an
adaptive level, which is a phase-6 question.
"""

from __future__ import annotations

import math
from collections import deque
from collections.abc import Iterable, Sequence

import numpy as np

from wimsim.calibration.base import MassEstimate

__all__ = ["ConformalInterval"]

SCORES = ("absolute", "relative")

#: Default window. Long enough that the quantile is stable, short enough that a month-old residual
#: is not still speaking for a scale that has been recalibrated twice since.
_DEFAULT_MAX_CALIBRATION = 500


class ConformalInterval:
    """A quantile of past errors, and the interval it implies."""

    def __init__(
        self,
        *,
        coverage_target: float = 0.95,
        score: str = "absolute",
        max_calibration: int = _DEFAULT_MAX_CALIBRATION,
    ) -> None:
        if not 0.0 < coverage_target < 1.0:
            raise ValueError(f"coverage_target must lie in (0, 1); got {coverage_target}")
        if score not in SCORES:
            raise ValueError(f"score must be one of {SCORES}; got {score!r}")

        self.coverage_target = float(coverage_target)
        self.score = score
        self.max_calibration = int(max_calibration)
        self._scores: deque[float] = deque(maxlen=self.max_calibration)

    # -- the minimum that makes the guarantee true --------------------------------------------

    @property
    def min_calibration(self) -> int:
        """Fewest scores for which a conforming quantile exists.

        The index is ``ceil((n+1)(1-alpha))``; below ``1/alpha - 1`` that index exceeds ``n``, so
        there is no score high enough and any interval returned would be a weaker claim wearing the
        same name.
        """
        return int(math.ceil(1.0 / (1.0 - self.coverage_target)) - 1)

    @property
    def n_calibration(self) -> int:
        return len(self._scores)

    @property
    def calibrated(self) -> bool:
        return self.n_calibration >= self.min_calibration

    # -- gathering scores -----------------------------------------------------------------------

    def observe(self, reference_mass_kg: float, predicted_mass_kg: float) -> None:
        """Fold one scored pass into the calibration set.

        One at a time, because that is how reference vehicles arrive in the field.
        """
        self._scores.append(self._nonconformity(reference_mass_kg, predicted_mass_kg))

    def calibrate(self, pairs: Iterable[tuple[float, float]]) -> float:
        """Replace the calibration set with ``(reference, prediction)`` pairs. Returns the quantile."""
        rows = list(pairs)
        if len(rows) < self.min_calibration:
            raise ValueError(
                f"split conformal at {self.coverage_target:.2f} coverage needs at least "
                f"{self.min_calibration} calibration scores; got {len(rows)}. Below that no score "
                "is high enough to carry the finite-sample guarantee."
            )
        self._scores.clear()
        for reference, prediction in rows:
            self.observe(reference, prediction)
        return self.quantile

    def reset(self) -> None:
        """Forget everything. Called on recalibration: the old residuals describe an estimator
        that no longer exists."""
        self._scores.clear()

    # -- the interval ----------------------------------------------------------------------------

    @property
    def quantile(self) -> float:
        """The ``ceil((n+1)(1-alpha))``-th smallest score."""
        if not self.calibrated:
            raise RuntimeError(
                f"not calibrated: {self.n_calibration} scores, {self.min_calibration} needed for "
                f"{self.coverage_target:.2f} coverage"
            )
        scores = np.sort(np.asarray(self._scores, dtype=np.float64))
        n = scores.size
        index = int(math.ceil((n + 1) * self.coverage_target))
        # Only reachable when n is exactly at the minimum, where the correction lands on n itself.
        index = min(index, n)
        return float(scores[index - 1])

    def interval(self, predicted_mass_kg: float) -> MassEstimate:
        """The prediction, with a band read off the quantile of past errors."""
        prediction = float(predicted_mass_kg)
        half = self.quantile * (abs(prediction) if self.score == "relative" else 1.0)
        return MassEstimate(
            mass_kg=prediction,
            mass_ci_low=prediction - half,
            mass_ci_high=prediction + half,
            coverage_target=self.coverage_target,
            interval_source=f"conformal_{self.score}",
        )

    # -- serialisation ----------------------------------------------------------------------------

    def to_dict(self) -> dict:
        """Plain JSON. The scores travel with it: a station that restarts without its calibration
        set has to spend the next several hundred passes earning one back, during which it has no
        honest interval to emit at all."""
        return {
            "coverage_target": self.coverage_target,
            "score": self.score,
            "max_calibration": self.max_calibration,
            "scores": [float(s) for s in self._scores],
        }

    @classmethod
    def from_dict(cls, payload: dict) -> ConformalInterval:
        conformal = cls(
            coverage_target=float(payload.get("coverage_target", 0.95)),
            score=str(payload.get("score", "absolute")),
            max_calibration=int(payload.get("max_calibration", _DEFAULT_MAX_CALIBRATION)),
        )
        conformal._scores.extend(float(s) for s in payload.get("scores", ()))
        return conformal

    # -- internals ---------------------------------------------------------------------------------

    def _nonconformity(self, reference_mass_kg: float, predicted_mass_kg: float) -> float:
        error = abs(float(reference_mass_kg) - float(predicted_mass_kg))
        if self.score == "absolute":
            return error
        denominator = abs(float(predicted_mass_kg))
        # A prediction of zero has no scale to normalise by. Rather than divide by it, fall back to
        # the absolute score for that one pass: an infinite nonconformity would poison the quantile
        # for the whole window.
        return error / denominator if denominator > 0.0 else error

    def scores(self) -> Sequence[float]:
        """The calibration set, oldest first. For the scoring layer and for tests."""
        return tuple(self._scores)
