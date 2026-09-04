"""The truth overlay: ground truth as metrics, emitted from outside the measurement path.

Buildspec section 9 asks for four series -- ``wim_cal_gain_true``, ``wim_cal_bias_true``,
``wim_temperature_true``, ``wim_mass_true`` -- labelled ``source="truth"`` and "emitted by a
separate exporter that reads the truth log, **never** by the estimator path". They exist so the
calibration dashboard can draw what the estimator believes on top of what was actually true, which
is the only way convergence and drift recovery become visible rather than argued.

**Why this module is in ``experiments/``.** ``observability/`` is imported by the edge and is
therefore quarantined from ``wimsim.signal`` by ``test_truth_isolation.py``; putting a truth reader
in it would either break that test or, worse, force it to be relaxed. ``experiments/`` is already
the designated truth-joining layer and already outside the quarantine, and nothing on the
measurement path imports it -- which ``test_truth_export.py`` checks structurally rather than
trusting.

**The overlay is drawn sensor-side.** ``k_true`` and ``q_true`` go out untouched and the estimator
inverts through ``EstimatorState.sensor_gain``/``sensor_bias``. That convention was settled in
``calibration/base.py``; what matters here is only that both ends agree, because a truth gain of
2e-4 plotted against a prediction gain of 5000 is a panel that looks broken rather than wrong, and
that kind of mistake survives review.

The quality metrics that need a reference mass -- absolute error, relative error, rolling coverage
-- are emitted from here too, for the same reason: computing them means reading the truth log. Only
``wim_interval_width`` stays on the edge, because it needs no reference.
"""

from __future__ import annotations

import pandas as pd

from wimsim.experiments.scoring import match_events
from wimsim.observability.estimator import estimate_metrics
from wimsim.observability.metrics import Metrics, build_metrics

#: Re-exported. The estimate side lives in ``observability/estimator.py`` because the *edge* emits
#: it whenever a profile is activated, and the edge must not import ``experiments`` -- but the two
#: conventions still have to agree, so the test that checks they do imports both from here.
__all__ = ["TruthExporter", "build_truth_metrics", "estimate_metrics"]


def build_truth_metrics(
    *,
    station_id: str,
    run_id: str | None = None,
    endpoint: str | None = None,
) -> Metrics:
    """A ``Metrics`` permitted to emit the truth series. The only place that permission is given."""
    return build_metrics(
        station_id=station_id, run_id=run_id, truth_allowed=True, endpoint=endpoint
    )


class TruthExporter:
    """Reads a truth log and emits it as metrics. Writes nothing back to the pipeline."""

    def __init__(self, metrics: Metrics, *, require_truth_permission: bool = True) -> None:
        if require_truth_permission and not metrics.truth_allowed:
            raise PermissionError(
                "the truth exporter needs a registry built with truth_allowed=True. Use "
                "build_truth_metrics(); an estimator-path registry must never carry these series."
            )
        self.metrics = metrics

    # -- the four truth series ------------------------------------------------------------------

    def export_timeseries(self, truth: pd.DataFrame) -> int:
        """Plant gain, zero line and true sensor temperature, one point per plant-grid row.

        The true sensor temperature is *not* the probe reading: the probe has its own offset and
        noise, and the gap between them is what a temperature-compensating estimator is fighting.
        """
        for row in truth.itertuples(index=False):
            self.metrics.set("wim_cal_gain_true", float(row.k_true))
            self.metrics.set("wim_cal_bias_true", float(row.q_true))
            self.metrics.set("wim_temperature_true", float(row.t_sensor_true))
        return len(truth)

    def export_passes(self, truth: pd.DataFrame) -> int:
        """The true mass of each vehicle, carrying its class.

        The class label travels with the mass because per-class accuracy is a headline result and a
        mass with no class cannot contribute to one.
        """
        for row in truth.itertuples(index=False):
            self.metrics.set(
                "wim_mass_true",
                float(row.true_mass_kg),
                vehicle_class=str(getattr(row, "vehicle_class", "unknown")),
            )
        return len(truth)

    # -- quality, which needs a reference mass ----------------------------------------------------

    def export_quality(
        self, events: list, truth: pd.DataFrame, *, tolerance_s: float = 0.25
    ) -> int:
        """Absolute error, relative error and rolling coverage, for the matched passes only.

        Unmatched events are left out rather than scored against the nearest pass: a false positive
        has no reference mass, and inventing one would put a fictitious error into the histogram.
        They are counted as false positives by ``score_events``, which is where they belong.

        Coverage is emitted as a *running* fraction rather than a final one, because the question
        the dashboard answers is "is the interval honest right now", and a single end-of-run number
        cannot show an interval that stopped being honest halfway through.
        """
        matched, _missed, _spurious = match_events(events, truth, tolerance_s=tolerance_s)
        if matched.empty:
            return 0

        covered = 0
        for n, row in enumerate(matched.itertuples(index=False), start=1):
            true_mass = float(row.true_mass_kg)
            error = float(row.mass_kg) - true_mass
            self.metrics.observe("wim_mass_abs_error", abs(error))
            if true_mass:
                self.metrics.observe("wim_mass_rel_error", abs(error) / true_mass)
            if row.mass_ci_low <= true_mass <= row.mass_ci_high:
                covered += 1
            self.metrics.set("wim_coverage_rolling", covered / n)
        return len(matched)
