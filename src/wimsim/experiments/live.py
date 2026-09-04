"""Driving a station against the running stack: publish, trace, measure, and load the truth.

``offline.py`` answers "what is the MAE"; this answers "what does the system look like while it is
working". Same pipeline, same config, same estimator -- the difference is that events go to the
broker as they are produced, the stages carry spans, and the truth log is loaded into the ``truth.*``
schema so the dashboards have something to draw the estimate against.

Three decisions worth writing down.

**Publishing happens inside the estimate span.** ``OfflinePipeline.run`` calls ``on_event`` before
closing it, so the ``publish`` span is a child, so the stamped ``traceparent`` names the pass's own
trace. That is the whole reason ``run`` takes a callback instead of yielding: a generator suspended
inside a span attaches its context to whatever the consumer does next.

**The truth overlay goes to TimescaleDB, not to Prometheus.** A replayed run pushes fifteen minutes
of plant state in whatever wall-clock time the replay takes; Prometheus keeps the last value it
scraped, so gauge points arriving faster than the scrape interval are simply lost -- the overlay
would be a handful of survivors and would look like a sparse, broken series rather than a plant
trajectory. The database keeps every point with its own timestamp, and a Grafana panel joining
``measurement_event`` to ``truth.truth_pass`` on time is exact. The Prometheus truth metrics stay in
the registry because they are right for a station that is genuinely live; they are simply not the
right instrument for a replay.

**The calibration is still fitted from reference vehicles.** Same calibration split as offline, for
the same reason: the estimator cannot start from nothing, and in the field that first fit comes from
vehicles of known mass. Nothing after the split reads truth.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any

import pandas as pd

from wimsim.core.config import EdgeConfig, RunConfig
from wimsim.core.schemas import MeasurementEvent
from wimsim.edge.pipeline import OfflinePipeline
from wimsim.experiments.offline import _bootstrap_profile, _fit_profile, _provenance_for
from wimsim.observability.logging import bind, get_logger
from wimsim.observability.metrics import Metrics, NullSink
from wimsim.observability.tracing import Tracing
from wimsim.source import PacedSource, SyntheticSource

__all__ = ["LiveResult", "run_live"]

log = get_logger("experiments.live")


@dataclass
class LiveResult:
    events: list[MeasurementEvent] = field(default_factory=list)
    published: int = 0
    buffered: int = 0
    elapsed_s: float = 0.0
    max_lag_s: float = 0.0
    profile_id: str = ""
    stats: dict[str, Any] = field(default_factory=dict)


def run_live(
    cfg: RunConfig,
    truth: pd.DataFrame,
    edge_cfg: EdgeConfig,
    *,
    publisher: Any,
    metrics: Metrics | None = None,
    tracing: Tracing | None = None,
    calibration_passes: int | None = None,
    speed: float | None = None,
    match_tolerance_s: float = 0.25,
) -> LiveResult:
    """Fit a profile, then stream the run through the pipeline and out to the broker.

    ``speed`` paces the replay against a wall clock; ``None`` runs as fast as the machine allows,
    which is right for a smoke test and wrong for looking at a dashboard.
    """
    metrics = metrics or Metrics(NullSink())
    tracing = tracing or Tracing(None)
    n_cal = calibration_passes or edge_cfg.estimate.bootstrap_passes

    profile = _bootstrap_calibration(cfg, truth, edge_cfg, n_cal, match_tolerance_s)
    log.info(
        "calibration fitted",
        extra={"profile_id": profile.profile_id, "sensor_gain": profile.state.sensor_gain},
    )

    source: Any = SyntheticSource(cfg)
    paced = PacedSource(source, speed=speed) if speed else None
    pipeline = OfflinePipeline(
        edge_cfg,
        source=paced or source,
        profile=profile,
        provenance=_provenance_for(cfg),
        metrics=metrics,
        tracing=tracing,
    )

    result = LiveResult(profile_id=profile.profile_id)

    def emit(event: MeasurementEvent) -> None:
        publisher.publish_model(event)
        result.published += 1
        with bind(event_id=event.event_id, profile_id=profile.profile_id):
            log.info(
                "pass measured",
                extra={
                    "mass_kg": round(event.mass_kg, 1),
                    "axle_count": event.axle_count,
                    "buffer_depth": publisher.buffer_depth,
                },
            )

    started = time.monotonic()
    with bind(station_id=cfg.station.station_id, profile_id=profile.profile_id):
        result.events = pipeline.run(on_event=emit)
        publisher.flush()
    result.elapsed_s = time.monotonic() - started
    result.buffered = publisher.buffer_depth
    result.max_lag_s = paced.max_lag_s if paced else 0.0
    result.stats = pipeline.stats()

    if result.buffered:
        log.warning("run finished with a backlog", extra={"buffer_depth": result.buffered})
    return result


def _bootstrap_calibration(cfg, truth, edge_cfg, n_cal, tolerance_s):
    """Detect once, unpublished, purely to fit the profile the live run will use.

    A second pass over the stream, which is affordable and honest: the alternative is publishing
    events estimated through a profile that is not fitted yet, and a mass emitted under a bootstrap
    calibration is a number nobody should keep.
    """
    fitting = OfflinePipeline(
        edge_cfg,
        source=SyntheticSource(cfg),
        profile=_bootstrap_profile(edge_cfg),
        provenance=_provenance_for(cfg),
    )
    detected = list(fitting.detect_only())
    if len(detected) <= n_cal:
        raise ValueError(
            f"{len(detected)} events detected but {n_cal} are reserved for calibration; there "
            "would be nothing left to publish. Lengthen the run or lower bootstrap_passes."
        )
    return _fit_profile(edge_cfg, detected[:n_cal], truth, tolerance_s)


def load_truth(writer: Any, run_dir, *, run_id: str, station_id: str) -> tuple[int, int]:
    """Load a run's truth log into the ``truth.*`` schema. Returns ``(passes, timeseries)``.

    Separate from the measurement path in the schema, in the code, and in the import graph. In
    replay mode there is nothing to load and the dashboards degrade to showing only what was
    measured, which is buildspec section 8's requirement and the honest behaviour anyway.
    """
    from pathlib import Path

    run_dir = Path(run_dir)
    passes = pd.read_parquet(run_dir / "truth_passes.parquet")
    series = pd.read_parquet(run_dir / "truth_timeseries.parquet")
    n_passes = writer.write_truth_passes(run_id, station_id, passes.to_dict("records"))
    n_series = writer.write_truth_timeseries(run_id, station_id, series.to_dict("records"))
    return n_passes, n_series
