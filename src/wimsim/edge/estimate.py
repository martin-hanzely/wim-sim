"""Stage 4 of the edge pipeline: a detected window becomes a mass with an interval.

Thin by design. All of the statistics live in ``wimsim.calibration``, which stays numpy-only so it
can be cross-deployed; this module is the adapter that chooses a feature, decides how to combine
axles, and assembles the transport payload. Conversion runs one way only -- an event is built *from*
an :class:`~wimsim.calibration.EstimatorState`, never the reverse -- so the estimator core never
learns that pydantic exists.

Two configurable choices, and neither has an obviously correct answer, which is why both are config
rather than code:

``feature``
    ``peak`` is speed-invariant but sees the full noise bandwidth of one instant; ``area`` averages
    the noise down but scales with load/speed, and a single sensor cannot measure speed. See
    ``docs/signal-model.md``.
``axle_summation``
    ``whole_signal`` treats the vehicle as one measurement carrying one zero error;
    ``per_axle_sum`` treats each axle as its own. They differ exactly in how many times the fitted
    intercept is charged, and in how the prediction intervals combine.
"""

from __future__ import annotations

import math

from wimsim.calibration import CalibrationEstimator, CalibrationProfile, MassEstimate
from wimsim.core.config import EstimateConfig
from wimsim.core.schemas import (
    CalibrationBlock,
    MeasurementEvent,
    PreprocessingBlock,
    ProvenanceBlock,
)
from wimsim.edge.detect import DetectedEvent

__all__ = ["MassEstimator"]


class MassEstimator:
    """Applies the active calibration profile to a detected event."""

    def __init__(
        self,
        cfg: EstimateConfig,
        *,
        estimator: CalibrationEstimator,
        profile: CalibrationProfile,
        station_id: str,
        sensor_id: str,
    ) -> None:
        self.cfg = cfg
        self.estimator = estimator
        self.profile = profile
        self.station_id = station_id
        self.sensor_id = sensor_id

    # -- features ---------------------------------------------------------------------------

    def _vehicle_feature(self, event: DetectedEvent) -> float:
        return event.axle_peak_sum if self.cfg.feature == "peak" else event.area

    def _axle_features(self, event: DetectedEvent) -> list[float]:
        if self.cfg.feature == "peak":
            return [a.peak for a in event.axles]
        return [a.area for a in event.axles]

    # -- estimation --------------------------------------------------------------------------

    def estimate(self, event: DetectedEvent, temp_c: float | None = None) -> MassEstimate:
        temperature = 0.0 if temp_c is None else float(temp_c)

        if self.cfg.axle_summation == "whole_signal" or event.axle_count <= 1:
            return self.estimator.predict(self._vehicle_feature(event), temperature)

        parts = [self.estimator.predict(x, temperature) for x in self._axle_features(event)]
        mass = float(sum(p.mass_kg for p in parts))
        # Axle errors are independent draws from the same residual distribution, so their half
        # widths add in quadrature. Adding them linearly would claim a four-axle truck is four times
        # as uncertain as a single axle when independence makes it twice.
        half = math.sqrt(sum(((p.mass_ci_high - p.mass_ci_low) / 2.0) ** 2 for p in parts))
        first = parts[0]
        return MassEstimate(
            mass_kg=mass,
            mass_ci_low=mass - half,
            mass_ci_high=mass + half,
            coverage_target=first.coverage_target,
            interval_source=first.interval_source,
        )

    # -- transport ---------------------------------------------------------------------------

    def calibration_block(self) -> CalibrationBlock:
        """The estimator state, in the convention the truth log and the dashboard use.

        ``gain`` and ``bias`` are reported **sensor-side** (sensor units per kg, sensor units), not
        in the estimator's internal prediction direction, so the calibration dashboard can draw the
        estimate on the same axes as ``k_true`` and ``q_true`` without either side inverting.
        """
        state = self.estimator.state()
        return CalibrationBlock(
            profile_id=self.profile.profile_id,
            estimator=state.estimator,
            gain=state.sensor_gain,
            bias=state.sensor_bias,
            temp_coeff=state.temp_coeff,
            state_hash=state.state_hash,
            update_count=state.update_count,
            covariance_trace=state.covariance_trace,
        )

    def to_measurement_event(
        self,
        event: DetectedEvent,
        *,
        provenance: ProvenanceBlock,
        preprocessing: PreprocessingBlock,
        temp_c: float | None = None,
        trace_id: str | None = None,
        interval: MassEstimate | None = None,
    ) -> MeasurementEvent:
        """One detected window as a publishable event.

        ``interval`` replaces the estimator's own band while keeping its mass. That is how the
        conformal construction reaches an event: it needs a history of scored passes, so it cannot
        live inside a single estimator, and teaching MassEstimator about it would put the choice of
        interval construction somewhere the experiment cannot sweep. The mass is never taken from
        the override -- only the band and the coverage it claims.
        """
        estimate = self.estimate(event, temp_c)
        band = interval or estimate
        return MeasurementEvent(
            station_id=self.station_id,
            sensor_id=self.sensor_id,
            ts_start=event.ts_start_us,
            ts_peak=event.ts_peak_us,
            ts_end=event.ts_end_us,
            raw_peak=event.raw_peak,
            raw_area=event.raw_area,
            compensated_peak=event.peak,
            compensated_area=event.area,
            temperature_c=temp_c,
            speed_mps=None,  # a single sensor cannot measure speed; see edge/detect.py
            axle_count=event.axle_count,
            mass_kg=estimate.mass_kg,
            mass_ci_low=band.mass_ci_low,
            mass_ci_high=band.mass_ci_high,
            coverage_target=band.coverage_target,
            interval_source=band.interval_source,
            calibration=self.calibration_block(),
            preprocessing=preprocessing,
            provenance=provenance,
            quality_flag=event.quality_flag,
            trace_id=trace_id,
        )
