# wim-sim -- WiM Self-Calibration Testbed

An observable software simulation of a Weigh-in-Motion (WiM) measurement chain, built so that a
closed-loop self-calibration controller can be developed, instrumented and evaluated against known
ground truth -- and so that real vehicle-pass data can later be replayed through the *identical*
pipeline without code changes.

> **Not a metrological instrument.** This artifact validates architecture and control behaviour.
> It makes no claim of certified weighing accuracy, anywhere, ever.

---

## Non-negotiable design principles

These constrain every decision in this repository.

1. **Ground truth is a first-class output of the simulator, never an input to the estimator.**
   `signal/truth.py` writes the truth log (true mass per pass, true `k(t)`, true `q(t)`, true sensor
   temperature). The estimator is *structurally incapable* of reading it: `calibration/` may not
   import anything from `wimsim.signal`, and `tests/test_truth_isolation.py` fails the build if it
   ever does.
2. **One interface for synthetic and real data.** Everything downstream of `SourceAdapter` is
   identical whether samples come from the generator or from a replayed recording of real passes.
   When the real drives arrive, only a config line changes.
3. **Every emitted mass value carries full provenance.** Calibration profile id, estimator state at
   emission, filter parameters, config hash, seed, git commit, schema version. A result you cannot
   reproduce is not a result.
4. **Determinism.** Same seed + same config => byte-identical output. This is a hard test
   (`tests/test_determinism.py`), not an aspiration.
5. **Observability is data, not decoration.** Calibration state is exported as time series so loop
   convergence is *visible*, not inferred from logs.
6. **The estimator core stays dependency-light (numpy only) and framework-free** so it can be
   cross-deployed to a Raspberry Pi / Jetson unchanged. No MQTT, no database, no logging framework
   inside the estimator classes.

---

## Status

| Phase | Scope | State |
|---|---|---|
| 1 | Skeleton and truth: config, domain types, generative signal model, truth log, `SyntheticSource`, CLI, determinism test | **done** |
| 2 | Edge pipeline offline: preprocessor, event detector, `StaticAffine`, scoring vs. truth | **done** -- MAE 1.43 kg (0.054 %) on `S1_nominal` |
| 3 | Infrastructure: docker-compose, MQTT publisher with persistent buffer, ingest + DLQ, TimescaleDB | **done** -- synthetic passes visible in Grafana end to end |
| 4 | Full observability: OTel tracing, metric set, truth exporter, five dashboards | **done** -- one pass traceable acquire-to-persist in Tempo; all five dashboards live |
| 5 | The controller: RLS + Kalman, drift detectors, MAPE-K state machine, conformal UQ, profile store | **done** -- on `S4_step_fault` bias falls from -136.9 kg to -9.4 kg, both injected faults detected and corrected |
| 6 | Experiments and real data: runner, scenario suite, `ReplaySource`, sim-to-real gap report | **done** -- 63-run checkpoint table, 0 failed; on `S7_sparse_reference` the adaptive estimators cut bias from -96.7 kg to -15 kg, and the detector now finds real crossings on 14 of 16 channel-runs |

---

## Quick start

```bash
python -m venv .venv
.venv/Scripts/python -m pip install -e ".[dev]"        # Windows
# source .venv/bin/activate && pip install -e ".[dev]" # POSIX

# generate a run
wimsim generate --scenario S1_nominal --out data/synthetic/S1_demo

# what did we just make?
wimsim inspect data/synthetic/S1_demo

# Phase 1 checkpoint: a synthetic pass with its truth values
wimsim plot-pass data/synthetic/S1_demo --index 0

# Phase 2 checkpoint: run the edge pipeline and score it against truth
wimsim pipelines
wimsim run data/synthetic/S1_demo --edge default

# phase 3: bring up the stack and take a run all the way to Grafana
docker compose --profile full up -d
alembic upgrade head
# ... then publish a run and watch it land: see docs/infrastructure.md

# Phase 4 checkpoint: one pass, one trace, acquire -> persist, with the dashboards live.
# --speed matters: unpaced, a 15-minute run finishes in seconds and every panel is unreadable.
wimsim load-truth data/synthetic/S1_demo
wimsim ingest --otlp http://localhost:4317 &
wimsim edge-run data/synthetic/S1_demo --otlp http://localhost:4317 --speed 12
python scripts/check_dashboards.py    # ask Grafana to run all 47 panels

# Phase 5 checkpoint: close the loop on a scenario with two injected sensitivity steps.
# --no-control runs the identical pipeline with the controller off: the arm every claim
# about the controller has to be measured against.
wimsim generate S4_step_fault --out data/synthetic/S4_demo --samples none
wimsim control data/synthetic/S4_demo --reference-every 2 --calibration-passes 60 --no-control
wimsim control data/synthetic/S4_demo --reference-every 2 --calibration-passes 60
wimsim profiles data/synthetic/S4_demo/profiles.default.jsonl

# re-derive stored history under a different calibration (dry run unless --apply)
wimsim recompute --profile p-001-... --from 2025-06-01T04:00:00Z \
  --profiles data/synthetic/S4_demo/profiles.default.jsonl

# prove determinism
wimsim generate S1_nominal --out .determinism/a -q
wimsim generate S1_nominal --out .determinism/b -q
wimsim verify-determinism .determinism/a .determinism/b

# what the real drives must look like, fixed before they arrive
wimsim real-data-schema
wimsim validate-real-data data/real/EXAMPLE

# Phase 6 checkpoint: every estimator across every scenario, three seeds each.
# --dry-run prints the grid and what it costs without running anything.
wimsim experiment ladder --dry-run
wimsim experiment ladder            # -> data/results/ladder/{results.parquet,md,tex,figures/}

# the real recordings. `detect` stops before estimation, because detection is the one part of
# the pipeline a recording can drive end to end -- everything past it needs a truth log.
wimsim detect S8_replay_real --edge cintron_platform   --set scenario.source.replay.run_dir=data/real/20260209_cintron1   --set scenario.source.replay.channel=Tenzo1

# where the simulator and the real sensor disagree, and the --set lines that close the gap
wimsim gap-report data/real/20260209_cintron1 --channel Tenzo1
```

Or via `make`: `make sim`, `make test`, `make checkpoint`, `make determinism`.

Any command that resolves a config takes `--set path.to.key=value`, so a sweep never needs a
generated YAML file:

```bash
wimsim generate S4_step_fault --out data/synthetic/short \
  --set scenario.duration_s=3600 --set station.sensor.k0=1.8e-4 --seed 7
```

> **Provenance needs a clean tree.** Every artifact records the commit that produced it, and runs
> from a dirty tree are marked as such — a results table from a dirty tree says so on its face,
> because a commit that does not identify the code is worse than no commit at all. See
> [`docs/determinism.md`](docs/determinism.md).

## Repository layout

```
configs/stations/     physical station description (sensor, ADC, thermal constants)
configs/scenarios/    what happens during a run (duration, traffic, drift, faults)
configs/estimators/   edge pipeline configs: filter, detector, feature, estimator
configs/experiments/  sweeps that produce paper tables        (phase 6)
src/wimsim/core/      domain types, config, provenance, deterministic RNG
src/wimsim/signal/    generative model + ground-truth log  <- estimators may never import this
src/wimsim/source/    SourceAdapter implementations
src/wimsim/edge/      acquisition -> preprocess -> detect -> estimate
src/wimsim/transport/ persistent spool + MQTT publisher
src/wimsim/ingest/    validation, dead-letter queue
src/wimsim/storage/   TimescaleDB schema, Alembic migrations, idempotent writer
src/wimsim/observability/  metric registry, tracing, structured logging
docker/               service configs for the compose stack
dashboards/           Grafana dashboards, provisioned read-only from the repo
src/wimsim/calibration/  estimators, drift detectors, MAPE-K controller, UQ, profile store
                      (numpy only -- cross-deploys to a Pi unchanged)
data/real/            the real test drives land here (EXAMPLE/ shows the required shape)
data/synthetic/       generated runs
data/results/         experiment outputs
scripts/              operational checks that need the stack up
docs/                 signal-model.md, observability.md, experiments.md, sim-to-real.md
```

## Documentation

- [`docs/signal-model.md`](docs/signal-model.md) -- every term of the generative model, with units
  and the physical argument for it. Read this before trusting any number the simulator produces.
- [`docs/real-data-schema.md`](docs/real-data-schema.md) -- the drop-in schema the real drives must
  conform to. Fixed now, so the data arrives without negotiation.
- [`docs/edge-pipeline.md`](docs/edge-pipeline.md) -- what phase 2 measured, including three
  findings that changed the design: area loses to peak by 650x on a single sensor, the despiker was
  eating 20 % of a car's peak, and a low-pass cutoff must clear the pulse band by 3x.
- [`docs/infrastructure.md`](docs/infrastructure.md) -- the phase-3 stack: what each service is
  for, how an event travels from the generator to a dashboard, and the failure modes the
  publisher and ingest are built around.
- [`docs/controller.md`](docs/controller.md) -- phase 5: the estimator ladder, the drift
  detectors and their measured operating points, the MAPE-K machine, conformal intervals, and the
  profile store. Includes the checkpoint numbers and the project's clearest answer to "how small a
  drift can this system act on" -- two floors, of which the one I had documented as binding turned
  out not to be.
- [`docs/observability.md`](docs/observability.md) -- the phase-4 layers: the metric registry and
  why it refuses things, how one trace crosses a broker with no headers, and the three faults that
  only turned up when the data was plotted (a column that was always null, a dashboard querying a
  column that does not exist, and every Prometheus metric silently renamed by the exporter).
- [`docs/sim-to-real.md`](docs/sim-to-real.md) -- what the eight real recordings say about the
  model. The headline: the hardware is a structural strain sensor, not the contact-force sensor
  the buildspec assumes, and speed *is* observable from its two gauges.
- [`docs/experiments.md`](docs/experiments.md) -- phase 6: the runner, the results table, the
  figures, the sim-to-real gap report, and the three separate reasons the default pipeline detected
  nothing at all on the real recordings.
- [`docs/determinism.md`](docs/determinism.md) -- how reproducibility is actually enforced.
