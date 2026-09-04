# Observability

Principle 5 says observability is data, not decoration. What that means in practice is that every
claim on a dashboard has to be traceable to a number some component actually emitted, and that a
panel which cannot be populated should say why rather than render an empty graph.

Phase 4 is three layers — metrics, traces, logs — plus five dashboards and the checkpoint that
proves they connect.

---

## The metric registry

Buildspec section 9 names twenty-six metrics. `observability/metrics.py` declares exactly those,
once, and every emission goes through the registry: an unknown name raises, the wrong instrument
kind raises, and a metric declared to carry a label raises without it.

That discipline exists because **Grafana fails silently**. A metric renamed in code and not in a
panel query renders an empty graph and says nothing about why, and an empty graph on a monitoring
dashboard reads as "nothing is happening" — the most dangerous possible way to be wrong.
`tests/test_metrics.py` keeps a literal transcription of the spec's list so the two cannot drift,
and `tests/test_dashboards.py` checks every PromQL panel names a metric the registry declares.

Three design decisions.

**The default is a no-op.** No collector, no exporter, no background thread, no requirement that
OpenTelemetry even be importable. The edge has to run on a station whose link is down (scenario S5)
and the test suite has to run without docker. `build_metrics` reads the standard
`OTEL_EXPORTER_OTLP_ENDPOINT` and `OTEL_SDK_DISABLED` rather than inventing a config surface.

**Validation happens on the null path too.** A registry that only checked names when a collector was
attached would move every typo into production.

**Truth metrics are refused unless the caller declares itself the truth exporter.**
`test_truth_isolation.py` enforces principle 1 across imports, but that leaves an
observability-shaped hole: `wim_mass_true` emitted by the edge would put ground truth into the same
Prometheus a controller could query — a leak through the network rather than the import graph. The
permission defaults to off, and the registry stamps `source="truth"` itself so a caller cannot put a
truth series where dashboards expect an estimate.

### Names, and a fault the checker found

The OTel Prometheus exporter appends the OTel unit to every metric name by default. `wim_buffer_depth`
(unit `1`) was scraped as `wim_buffer_depth_ratio`, `wim_cal_gain_estimate` as
`wim_cal_gain_estimate_per_kg`, `wim_publish_latency_ms` as `wim_publish_latency_ms_milliseconds`.
Every Prometheus panel was querying a series that did not exist, and every one of them rendered as a
quiet system.

`docker/otel-collector/config.yaml` now sets `add_metric_suffixes: false`, so the buildspec's names,
the registry's names and the panels' names are the same three strings. Disabling the automatic
`_total` on counters costs nothing: the registry already names counters `..._total` itself, and a
test enforces that they are the only metrics that do.

### Where each metric comes from

The instrumentation sits at the pipeline and transport **seams**, not inside the individual stages.
Those seams already know where one stage ends and the next begins, so `preprocess.py` and `detect.py`
need not learn about OpenTelemetry to be measured. Everything defaults to off, which is why the
phase-2 numbers remain comparable.

| emitted by | metrics |
|---|---|
| `edge/pipeline.py` | `wim_samples_acquired_total`, `wim_sample_gaps_total`, `wim_events_detected_total`, `wim_interval_width`, `wim_cal_*_estimate`, `wim_cal_profile_version` |
| `transport/publisher.py` | `wim_publish_latency_ms`, `wim_buffer_depth`, `wim_publish_failures_total` |
| `ingest/consumer.py` | `wim_dlq_total{reason}`, `wim_ingest_lag_ms`, `wim_db_write_latency_ms{table}` |
| `experiments/truth_export.py` | the four `*_true` series, and the quality metrics that need a reference mass |

Two splits in that table are consequences of principle 1 rather than choices. `wim_interval_width`
is on the edge because it needs no reference mass; absolute error, relative error and rolling
coverage are in the truth exporter because computing them means reading the truth log.

Two measurement decisions worth stating:

- **Publish latency ignores rows spooled by a previous process.** Their enqueue time died with that
  process; a wall-clock difference across a restart is a six-hour outage, not a publish latency, and
  putting one into the histogram would ruin it. The tracking map is also capped at 10k, because
  during a long outage the depth gauge is the number that matters.
- **Ingest lag has clock skew left in, deliberately.** A station whose clock is wrong lands its data
  in the wrong bucket on every dashboard, and that has to be visible somewhere rather than quietly
  corrected at the boundary.

---

## Tracing

The requirement is concrete: select a vehicle pass in Tempo and see
`acquire → preprocess → detect → estimate → publish → ingest → persist` as one trace with per-stage
latency.

**Across the broker there is no header to put the context in.** MQTT 3.1.1 has none, so it rides in
the payload. The payload carries two fields, redundantly and on purpose:

- `trace_id` — the queryable form. A database column, a Grafana data link, a field on every log line.
- `traceparent` — the functional form. A trace id alone cannot re-parent a span, because a child
  needs its parent's *span* id too; without it the ingest span floats as a second root inside the
  same trace, which looks fine in a trace list and is useless in a waterfall.

They are stamped together from one call so they cannot disagree. Adding `traceparent` was an
additive optional field, so `SCHEMA_VERSION` went to 1.1.0 and a 1.0.0 consumer keeps working.

A malformed context is dropped, never fatal — the measurement is worth more than its trace.

### The shape of a trace

```
block                       (structural root, one per acquisition block)
├── acquire                 recorded over the pull interval
├── preprocess
├── detect
└── estimate                one per pass detected in this block
    └── publish             stamps the payload here -- the last moment the edge holds both
        ├── ingest          (other process)
        └── persist         (other process)
```

`block` is a structural parent, not a stage of the measurement. It exists because per-stage latency
needs the stages to be *siblings*: making `acquire` the parent would report it as taking as long as
everything it contains, which is the opposite of what the buildspec asks for.

Three things this shape forced:

- **`Tracing.record()`**, which emits a span over an interval the caller measured. Needed twice:
  for `acquire`, because whether a block exists is only known after pulling it and opening the
  enclosing span first would leave an empty span at every end of stream; and for `persist`, below.
- **`_detect()` hands the block's traceparent out as data** rather than holding a `with` open across
  its `yield`. A context manager suspended across a yield stays attached while the consumer runs and
  detaches in whatever order the consumer resumes in; the resulting traces are wrong in a way nobody
  notices until they are being relied on.
- **`persist` is one span per row, over the batch's real interval, parented to the `ingest` that
  queued that row.** A flush writes many passes, so a single span could belong to only one of their
  traces and every other pass would end at `ingest` with no visible database write. Parenting to the
  *publish* context instead — the obvious shortcut, since the row already carries it — draws persist
  as a sibling of ingest: two concurrent operations where one follows the other. Each queued row
  therefore remembers its ingest span, under a key popped before the row reaches the writer.

One caveat is written into the span rather than left implicit: a pass whose window straddles two
blocks had some of its samples acquired inside an earlier trace. `straddles_block` says so.

---

## Logs

Structured JSON to Loki, every line carrying `event_id`, `trace_id`, `station_id`, `profile_id`,
`run_id`. The rule is stronger than "present when known" — the keys are **always** there, null when
unset — because a Loki filter on a sometimes-present key silently drops exactly the lines that would
have explained the problem.

Two things I had to correct while building it:

- **The context is snapshotted onto the record at creation, not read at format time.** The first
  version read the contextvar inside the formatter, and the tests caught it: formatting happens
  later, in another thread for a batching handler, by which point the `with bind(...)` scope the
  line belongs to has unwound and every field reads null.
- **It is a `LoggerAdapter`, not a `logging.Filter`.** A filter installed on the `wimsim` logger
  never sees records from `wimsim.edge.detect`: during propagation only handlers run, not the
  ancestors' filters.

`trace_id` fills itself from the active span, because requiring every call site to pass it means
most eventually do not. An explicit `bind` still wins, for ingest replaying a stored payload whose
trace is not the one it is currently in.

Loki indexes only `service_name` and `service_instance_id`; the rest arrive as structured metadata,
so a per-pass `mass_kg` does not open a stream per vehicle.

---

## Dashboards

Five, provisioned read-only from `dashboards/`. See [`dashboards/README.md`](../dashboards/README.md)
for what each answers, how to get data into them, and which panels are meant to be empty.

Two conventions matter before reading the calibration dashboard, and both were discovered while
building it:

**Gain is drawn sensor-side.** `cal_gain` and `k_true` are both sensor units per kg, so the headline
overlay needs no inversion on either side — measured at 2.0002e-4 against a true 2.0e-4 on the demo
run. The estimator fits in the prediction direction, because prediction error in kilograms is what
gets scored, and reports through `EstimatorState.sensor_gain`.

**Bias is not comparable with `q_true`**, and gets its own panel saying so. The preprocessor's
zero-line tracker removes the plant's zero line before the feature is taken, so what the estimator
fits is the residual the tracker left behind: order 1e-4, against a `q_true` of 0.05. Drawn together
they would read as a badly wrong estimator when it is a correct one.

The calibration and accuracy dashboards read truth from **TimescaleDB, not Prometheus**. A replayed
run pushes plant state faster than any scrape interval and a gauge only keeps the last value scraped,
so the overlay would be a handful of survivors that looks like a broken series rather than a plant
trajectory. The Prometheus truth metrics remain in the registry because they are right for a station
that is genuinely live; they are the wrong instrument for a replay.

---

## The checkpoint

```bash
docker compose --profile full up -d
alembic upgrade head

wimsim load-truth data/synthetic/S1_demo
wimsim ingest --otlp http://localhost:4317 &
wimsim edge-run data/synthetic/S1_demo --otlp http://localhost:4317 --speed 12 --calibration-passes 10

pytest tests/test_checkpoint_tracing.py     # the checkpoint, as an assertion
python scripts/check_dashboards.py          # ask Grafana to run all 47 panels
```

On the demo run: 47 passes published, 0 buffered, 0 dead-lettered, worst pacing lag 0.000 s, one
trace per pass containing all seven stages across two services, and 47 panels returning data through
Grafana's own query API.

`--speed` is not cosmetic. Unpaced, a fifteen-minute run finishes in seconds: every point lands in
one Prometheus scrape, every trace shares a millisecond, and buffer depth never leaves zero because
the publisher drains as fast as the pipeline fills it. Nothing on the dashboards can be judged from
that. Pacing lives in `PacedSource`, a decorator over `SourceAdapter`, so the pipeline still cannot
tell what it is reading (principle 2); the schedule is absolute rather than per block, so a stalled
block does not push every later one late and falling behind surfaces as `max_lag_s` instead of
hiding as drift.

---

## What phase 4 found in the existing code

Three faults that reading would not have caught, all surfaced by trying to draw the data:

1. **`measurement_event.temperature_c` was always null.** `MassEstimator.to_measurement_event`
   takes a `temp_c` and nobody passed one. Nothing was numerically wrong — `StaticAffine` ignores it
   because the preprocessor has already applied the thermal correction — but the *record* was
   missing, and phase 5's estimators fit their coefficient against exactly this reading. Left alone
   it would have surfaced in phase 5 as an estimator that could not learn a temperature coefficient.
2. **A `wim.dlq` panel querying a column called `ts`.** The table calls it `received_at`.
3. **Every Prometheus metric silently renamed by the exporter**, described above.

The first is the one worth remembering: it is not a bug in anything, it is a field that was never
populated, and the only thing that could find it was trying to plot it.
