"""The estimator's own state, as metrics.

Separate from ``metrics.py`` because it knows what an ``EstimatorState`` is, and separate from
``calibration/`` because that package is numpy-only and framework-free by principle 6 -- it must
cross-compile to a Pi without an OpenTelemetry install anywhere near it. The dependency therefore
points this way: observability knows about the estimator, never the reverse.

**Sensor-side, deliberately.** ``wim_cal_gain_estimate`` is sensor units per kg, not kilograms per
sensor unit, so that it lands on the same axis as ``wim_cal_gain_true`` from the truth exporter and
neither side has to invert in a Grafana expression. The estimator fits in the prediction direction,
because prediction error in kilograms is what gets scored, and reports through
``EstimatorState.sensor_gain``/``sensor_bias``. See ``calibration/base.py``, where the two
conventions are defined; ``tests/test_truth_export.py`` is what keeps them agreeing.
"""

from __future__ import annotations

from wimsim.calibration import EstimatorState
from wimsim.observability.metrics import Metrics

__all__ = ["estimate_metrics"]


def estimate_metrics(metrics: Metrics, state: EstimatorState, **attributes: str) -> None:
    """Emit the calibration-loop gauges for one estimator state.

    Needs no truth permission: it reads the estimator's own parameters and nothing else.
    """
    metrics.set("wim_cal_gain_estimate", state.sensor_gain, **attributes)
    metrics.set("wim_cal_bias_estimate", state.sensor_bias, **attributes)
    metrics.set("wim_cal_temp_coeff_estimate", state.temp_coeff, **attributes)
    metrics.set("wim_cal_update_count", state.update_count, **attributes)
    trace = state.covariance_trace
    if trace is not None:
        metrics.set("wim_cal_covariance_trace", trace, **attributes)
