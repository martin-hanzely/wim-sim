# Dashboards

Five, provisioned from this directory into the `wimsim` folder in Grafana. Read-only in the UI on
purpose: a dashboard edited in a browser and never committed is a result nobody else can reproduce.

| file | what it answers |
|---|---|
| `station-operations.json` | Is the station alive, and how much is it producing? |
| `measurement.json` | What did one pass look like, and what mass came out with what interval? |
| `calibration-loop.json` | What does the estimator believe, and is it true? *(the centrepiece)* |
| `data-integrity.json` | Is what arrived what was measured? |
| `accuracy-uncertainty.json` | How wrong are the masses, and do the intervals admit it? |

## Seeing data in them

```bash
docker compose --profile core up -d
alembic upgrade head

# A run whose timestamps are recent, so `now-6h` has something in it. The scenario's own
# start_time is 2025-06-01 and every artifact is stamped with it, which is right for
# reproducibility and wrong for a live-looking dashboard -- so override it for a demo.
wimsim generate S1_nominal --out data/synthetic/demo \
  --set "scenario.start_time=$(date -u -d '-20 minutes' +%Y-%m-%dT%H:%M:%SZ)"

wimsim load-truth data/synthetic/demo            # truth.* -- the estimate has nothing to sit on without it
wimsim ingest --otlp http://localhost:4317 &     # broker -> TimescaleDB
wimsim edge-run data/synthetic/demo --otlp http://localhost:4317 --speed 12 --calibration-passes 10
```

`--speed` matters. Without it a fifteen-minute run finishes in seconds: every point lands in one
Prometheus scrape, every trace shares a millisecond, and buffer depth never leaves zero because the
publisher drains as fast as the pipeline fills it. Nothing on these pages can be judged from that.

## Checking them

```bash
pytest tests/test_dashboards.py      # no stack needed
python scripts/check_dashboards.py   # needs the stack up
```

Grafana fails silently: a panel whose metric was renamed, whose datasource uid does not resolve, or
whose column no longer exists renders an empty graph and says nothing about why — and an empty graph
on a monitoring dashboard reads as "nothing is happening", which is the most dangerous way to be
wrong. So the contract is tested. The offline test checks that every PromQL panel names a metric the
registry declares and every datasource uid is provisioned; the script asks Grafana itself to run all
47 panels and reports what came back.

Both have already earned their keep. The offline shape of them would not have caught either of the
two real faults found while writing these — a `wim.dlq` query using a column called `ts` when the
table calls it `received_at`, and the OTel Prometheus exporter silently appending units to every
metric name, so `wim_buffer_depth` was scraped as `wim_buffer_depth_ratio` and every Prometheus
panel was querying a series that did not exist. Both are fixed; the second is why
`docker/otel-collector/config.yaml` sets `add_metric_suffixes: false`.

## Panels that are legitimately empty

Not every blank panel is a bug, and the ones that are not say so in their own description:

- **Drift detector statistics, controller state, covariance trace** — the controller and the Kalman
  estimator arrive in phase 5. The panels are provisioned now so that the shape of the dashboard is
  fixed before the results are.
- **Sensor stream** — sample streaming is off by default. A 2 kHz channel is 173 million rows a day
  and the events are what the system exists to produce; turn it on for one station while debugging a
  detection, not as a matter of course.
- **Rejections, publish failures, sample gaps** — a clean run has none. These are panels you want to
  stay empty.
- **Everything on Accuracy and uncertainty, in replay mode** — every panel there joins to the truth
  log, and real recordings have no reference mass. That is the honest state of a deployment without
  a weighbridge, not a broken dashboard.

## Two conventions worth knowing before reading a panel

**Gain is drawn sensor-side.** `cal_gain` and `k_true` are both sensor units per kg, so the headline
overlay needs no inversion on either side. The estimator fits in the prediction direction — because
prediction error in kilograms is what gets scored — and reports through `EstimatorState.sensor_gain`.

**Bias is not.** `cal_bias` is *not* comparable with `q_true` and is deliberately on its own panel.
The preprocessor's zero-line tracker removes the plant's zero line before the feature is taken, so
what the estimator fits is the residual the tracker left behind: order 1e-4, against a `q_true` of
0.05. Drawn together they would read as a badly wrong estimator when it is a correct one.
