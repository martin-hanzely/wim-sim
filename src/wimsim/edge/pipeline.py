"""The edge pipeline, wired: acquire -> preprocess -> detect -> estimate.

Phase 2 runs it offline. There is no transport and no database, and the stages are connected by
ordinary function calls rather than the bounded queues of buildspec section 5 -- those exist to
decouple producers from consumers under back-pressure, and offline there is no back-pressure to
decouple. The stage *boundaries* are already the ones the queues will sit on, so phase 3 replaces
the calls and nothing else.

The pipeline takes a ``SourceAdapter``, so it cannot tell a synthetic stream from a replayed
recording, and it takes a ``CalibrationProfile``, so it cannot invent a calibration. Both are
deliberate: the first is principle 2, and the second means an event can always name the law that
produced it.

**This module never imports ``wimsim.signal``, even transitively.** The source is passed in, and its
type is imported only under ``TYPE_CHECKING``, because importing ``wimsim.source`` at runtime would
execute that package's ``__init__`` and pull the generator in behind it.
"""

from __future__ import annotations

from collections.abc import Iterator
from typing import TYPE_CHECKING

from wimsim.calibration import CalibrationProfile, StaticAffine
from wimsim.core.config import EdgeConfig
from wimsim.core.schemas import MeasurementEvent, ProvenanceBlock
from wimsim.edge.acquisition import AcquisitionAgent
from wimsim.edge.detect import EventDetector
from wimsim.edge.estimate import MassEstimator
from wimsim.edge.preprocess import Preprocessor

if TYPE_CHECKING:  # pragma: no cover
    from wimsim.source.base import SourceAdapter

__all__ = ["OfflinePipeline"]

_ESTIMATORS = {"static_affine": StaticAffine}


class OfflinePipeline:
    """One station, one sensor, one pass over a stream."""

    def __init__(
        self,
        cfg: EdgeConfig,
        *,
        source: SourceAdapter,
        profile: CalibrationProfile | None,
        provenance: ProvenanceBlock,
    ) -> None:
        self.cfg = cfg
        self.source = source
        self.profile = profile
        self.provenance = provenance

        meta = source.metadata
        self.station_id = meta.station_id
        self.sensor_id = meta.sensor_id

        self.acquisition = AcquisitionAgent(source, sample_rate_hz=meta.sample_rate_hz)
        self.preprocessor = Preprocessor(
            cfg.preprocess, sample_rate_hz=meta.sample_rate_hz, profile=profile
        )
        self.detector = EventDetector(cfg.detect, sample_rate_hz=meta.sample_rate_hz)
        self.estimator: MassEstimator | None = None
        if profile is not None:
            self.estimator = self._build_estimator(profile)

        self.events_emitted = 0
        self.axles_detected = 0

    def _build_estimator(self, profile: CalibrationProfile) -> MassEstimator:
        name = profile.state.estimator
        cls = _ESTIMATORS.get(name)
        if cls is None:
            raise ValueError(
                f"unknown estimator {name!r}; phase 2 ships {sorted(_ESTIMATORS)} and phase 5 adds "
                "rls, kalman and the residual learner"
            )
        return MassEstimator(
            self.cfg.estimate,
            estimator=cls.from_state(profile.state),
            profile=profile,
            station_id=self.station_id,
            sensor_id=self.sensor_id,
        )

    def set_profile(self, profile: CalibrationProfile) -> None:
        """Activate a new profile mid-stream, as phase-5 recalibration will."""
        self.profile = profile
        self.preprocessor.set_profile(profile)
        self.estimator = self._build_estimator(profile)

    def run(self) -> Iterator[MeasurementEvent]:
        if self.estimator is None:
            raise RuntimeError(
                "no calibration profile is active, so no mass can be emitted. Fit one from "
                "reference observations and pass it in, or call set_profile() before run()."
            )
        preprocessing = self.preprocessor.describe()

        for block in self.acquisition.stream():
            prepared = self.preprocessor.process(block)
            for detected in self.detector.process(prepared):
                yield self._emit(detected, preprocessing)
        for detected in self.detector.flush():
            yield self._emit(detected, preprocessing)

    def _emit(self, detected, preprocessing) -> MeasurementEvent:
        assert self.estimator is not None
        self.events_emitted += 1
        self.axles_detected += detected.axle_count
        return self.estimator.to_measurement_event(
            detected, provenance=self.provenance, preprocessing=preprocessing
        )

    def stats(self) -> dict[str, float]:
        return {
            **self.acquisition.stats(),
            "events_detected": self.events_emitted,
            "axles_detected": self.axles_detected,
            "rejected_too_short": self.detector.rejected_too_short,
            "rejected_too_long": self.detector.rejected_too_long,
            "group_delay_s": self.preprocessor.group_delay_s,
        }
