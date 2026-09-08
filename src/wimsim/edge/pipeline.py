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

**Observability lives at this seam, not inside the stages.** The pipeline is what already knows
where one stage ends and the next begins, so ``preprocess.py`` and ``detect.py`` need not learn
about OpenTelemetry to be measured. Both the metric registry and the tracer default to disabled, so
a pipeline constructed the way phase 2 constructed it behaves exactly as it did.

Spans are grouped per *block*: a ``block`` root with ``acquire``, ``preprocess`` and ``detect`` as
siblings beneath it, and ``estimate`` under the detection that produced it. Making ``acquire`` the
parent instead would report it as taking as long as the whole block, which is the opposite of the
per-stage latency the buildspec asks for. One consequence is worth stating: a pass whose window
straddles two blocks had some of its samples acquired inside an earlier trace. The trace shows the
block in which the pass was *detected*, and the ``straddles_block`` attribute says when that is not
the whole story.
"""

from __future__ import annotations

import time
from collections.abc import Callable, Iterator
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from wimsim.calibration import CalibrationProfile, estimator_from_state
from wimsim.core.config import EdgeConfig
from wimsim.core.schemas import MeasurementEvent, ProvenanceBlock
from wimsim.edge.acquisition import AcquisitionAgent
from wimsim.edge.detect import EventDetector
from wimsim.edge.estimate import MassEstimator
from wimsim.edge.preprocess import Preprocessor
from wimsim.observability.estimator import estimate_metrics
from wimsim.observability.metrics import Metrics, NullSink
from wimsim.observability.tracing import Tracing

if TYPE_CHECKING:  # pragma: no cover
    from wimsim.source.base import SourceAdapter

__all__ = ["OfflinePipeline"]


@dataclass(frozen=True, slots=True)
class _Detection:
    """A detection, plus the trace context of the block it came out of.

    The context is carried as data rather than left attached, because ``_detect`` is a generator:
    a ``with`` block held open across a ``yield`` stays attached while the consumer runs and
    detaches in whatever order the consumer happens to resume in, which produces traces that are
    wrong in a way nobody notices until they are being relied on.
    """

    detected: Any
    block_start_us: int
    parent: str | None

    @property
    def straddles_block(self) -> bool:
        """True when the pass began before the block it was detected in.

        Its earlier samples were acquired inside an earlier trace, so this trace's ``acquire``
        latency is not the whole story for this pass.
        """
        return self.detected.ts_start_us < self.block_start_us


class OfflinePipeline:
    """One station, one sensor, one pass over a stream."""

    def __init__(
        self,
        cfg: EdgeConfig,
        *,
        source: SourceAdapter,
        profile: CalibrationProfile | None,
        provenance: ProvenanceBlock,
        metrics: Metrics | None = None,
        tracing: Tracing | None = None,
    ) -> None:
        self.cfg = cfg
        self.source = source
        self.profile = profile
        self.provenance = provenance
        self.metrics = metrics or Metrics(NullSink())
        self.tracing = tracing or Tracing(None)

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
        self.profile_version = 0
        if profile is not None:
            self._report_profile(profile)

    def _build_estimator(self, profile: CalibrationProfile, estimator: Any = None) -> MassEstimator:
        """Wrap the estimator the profile names, from the shared registry.

        Shared rather than a table of its own, so that a profile the pipeline can run is exactly a
        profile ``recompute`` can re-derive. Two tables would eventually disagree, and the symptom
        would be an event that cannot be reproduced under the profile it names.

        ``estimator`` supplies a live instance instead of rebuilding one from the profile state.
        The closed loop needs that: it folds reference observations into an estimator with
        ``update()``, and rebuilding here would leave those updates in the caller's copy -- an RLS
        run would then report the same gain on every pass and be indistinguishable from the static
        baseline, with nothing failing to say so.
        """
        return MassEstimator(
            self.cfg.estimate,
            estimator=estimator if estimator is not None else estimator_from_state(profile.state),
            profile=profile,
            station_id=self.station_id,
            sensor_id=self.sensor_id,
        )

    def set_profile(self, profile: CalibrationProfile, *, estimator: Any = None) -> None:
        """Activate a new profile mid-stream, as phase-5 recalibration does.

        ``estimator`` hands over a live instance rather than one rebuilt from the state; see
        ``_build_estimator``.
        """
        self.profile = profile
        self.preprocessor.set_profile(profile)
        self.estimator = self._build_estimator(profile, estimator)
        self._report_profile(profile)

    def _report_profile(self, profile: CalibrationProfile) -> None:
        """Publish the active calibration to the metric stream.

        The version is an activation ordinal rather than anything read off the profile: what the
        dashboard needs is a step function it can annotate against, and the profile's identity is
        already carried by the ``calibration.profile_activated`` event. A ``profile_id`` label here
        would open a new series on every recalibration and make the step invisible.
        """
        self.profile_version += 1
        self.metrics.set("wim_cal_profile_version", self.profile_version)
        estimate_metrics(self.metrics, profile.state)

    def run(self, *, on_event: Callable[[MeasurementEvent], None] | None = None) -> list:
        """Acquire, preprocess, detect and estimate over the whole stream.

        ``on_event`` is called with each event *inside* its ``estimate`` span, which is what lets a
        publisher downstream of it join the same trace. Returning a list rather than yielding is
        deliberate: a generator that suspends inside a ``with`` block leaves the span's context
        attached while the consumer runs, and detaches it in whatever order the consumer happens to
        resume in. That produces traces that are wrong in a way nobody notices.
        """
        if self.estimator is None:
            raise RuntimeError(
                "no calibration profile is active, so no mass can be emitted. Fit one from "
                "reference observations and pass it in, or call set_profile() before run()."
            )
        preprocessing = self.preprocessor.describe()

        events: list[MeasurementEvent] = []
        for found in self._detect():
            event = self.estimate(
                found.detected,
                preprocessing,
                parent=found.parent,
                straddles_block=found.straddles_block,
                on_event=on_event,
            )
            events.append(event)
        return events

    def detect_only(self) -> Iterator:
        """Acquire, preprocess and detect, stopping before estimation.

        The offline runner needs this to fit a calibration before it can estimate anything, and it
        must be the *same* traced and measured path as ``run`` -- two loops would eventually
        disagree about how many samples arrived.
        """
        for found in self._detect():
            yield found.detected

    def _detect(self) -> Iterator[_Detection]:
        """The block loop, instrumented once."""
        block_index = 0
        block_start_us = 0

        stream = self.acquisition.stream()
        while True:
            # Pulled before the block span opens, because whether there is a block at all is only
            # known afterwards; `acquire` is then recorded over the interval just measured.
            before_samples = self.acquisition.samples_acquired
            before_missing = self.acquisition.missing_samples
            started_ns = time.time_ns()
            block = next(stream, None)
            finished_ns = time.time_ns()
            if block is None:
                break

            acquired = self.acquisition.samples_acquired - before_samples
            missing = self.acquisition.missing_samples - before_missing
            self.metrics.add("wim_samples_acquired_total", acquired)
            if missing:
                self.metrics.add("wim_sample_gaps_total", missing)

            with self.tracing.span("block", block_index=block_index) as block_span:
                self.tracing.record(
                    "acquire",
                    start_time_ns=started_ns,
                    end_time_ns=finished_ns,
                    samples=acquired,
                    missing_samples=missing or None,
                )

                with self.tracing.span("preprocess"):
                    prepared = self.preprocessor.process(block)

                with self.tracing.span("detect") as span:
                    detections = list(self.detector.process(prepared))
                    span.set_attribute("events", len(detections))

                if detections:
                    block_span.set_attribute("events", len(detections))
                    self.metrics.add("wim_events_detected_total", len(detections))
                # Captured here and handed out below, so that `estimate` can be parented to this
                # block without the generator having to suspend inside the span -- see _Detection.
                parent = self.tracing.current_traceparent()

            for detected in detections:
                yield _Detection(detected, block_start_us, parent)

            block_start_us = int(block.ts_us[0])
            block_index += 1

        # Whatever the detector is still holding when the stream ends. Outside the block loop
        # because there is no block behind it.
        with self.tracing.span("detect", final_flush=True) as span:
            detections = list(self.detector.flush())
            span.set_attribute("events", len(detections))
            parent = self.tracing.current_traceparent()
        if detections:
            self.metrics.add("wim_events_detected_total", len(detections))
        for detected in detections:
            yield _Detection(detected, block_start_us, parent)

    def estimate(
        self,
        detected,
        preprocessing,
        *,
        parent: str | None = None,
        straddles_block: bool = False,
        on_event: Callable[[MeasurementEvent], None] | None = None,
        interval: Any = None,
    ) -> MeasurementEvent:
        """Turn one detection into a measured event, inside its ``estimate`` span.

        Public because the offline runner has to detect the whole run before it can fit a
        calibration, and then estimate over the detections it already has. Routing that second pass
        through here rather than through a private shortcut is what keeps the metric counts and the
        span structure the same on both paths.

        ``on_event`` is called *inside* the span, which is what lets a publisher downstream of it
        join the same trace.

        ``interval`` replaces the estimator's own band while keeping its mass, which is how the
        conformal construction reaches an event: it needs a history of scored passes and so cannot
        live inside a single estimator. See ``edge/estimate.py``.
        """
        assert self.estimator is not None
        with self.tracing.continue_from(
            {"traceparent": parent},
            "estimate",
            axle_count=detected.axle_count,
            straddles_block=straddles_block or None,
        ) as span:
            self.events_emitted += 1
            self.axles_detected += detected.axle_count
            event = self.estimator.to_measurement_event(
                detected,
                provenance=self.provenance,
                preprocessing=preprocessing,
                temp_c=detected.temp_c,
                interval=interval,
            )
            span.set_attribute("event_id", event.event_id)
            span.set_attribute("mass_kg", event.mass_kg)
            self.metrics.observe("wim_interval_width", event.mass_ci_high - event.mass_ci_low)
            if on_event is not None:
                on_event(event)
        return event

    def stats(self) -> dict[str, float]:
        return {
            **self.acquisition.stats(),
            "events_detected": self.events_emitted,
            "axles_detected": self.axles_detected,
            "rejected_too_short": self.detector.rejected_too_short,
            "rejected_too_long": self.detector.rejected_too_long,
            "group_delay_s": self.preprocessor.group_delay_s,
        }
