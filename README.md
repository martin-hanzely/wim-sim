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
| 2 | Edge pipeline offline: preprocessor, event detector, `StaticAffine`, scoring vs. truth | not started |
| 3 | Infrastructure: docker-compose, MQTT publisher with persistent buffer, ingest + DLQ, TimescaleDB | not started |
| 4 | Full observability: OTel tracing, metric set, truth exporter, five dashboards | not started |
| 5 | The controller: RLS + Kalman, drift detectors, MAPE-K state machine, conformal UQ, profile store | not started |
| 6 | Experiments and real data: runner, scenario suite, `ReplaySource`, sim-to-real gap report | not started |

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

# prove determinism
wimsim generate S1_nominal --out .determinism/a -q
wimsim generate S1_nominal --out .determinism/b -q
wimsim verify-determinism .determinism/a .determinism/b

# what the real drives must look like, fixed before they arrive
wimsim real-data-schema
wimsim validate-real-data data/real/EXAMPLE
```

Or via `make`: `make sim`, `make test`, `make checkpoint`, `make determinism`.

Any command that resolves a config takes `--set path.to.key=value`, so a sweep never needs a
generated YAML file:

```bash
wimsim generate S4_step_fault --out data/synthetic/short \
  --set scenario.duration_s=3600 --set station.sensor.k0=1.8e-4 --seed 7
```

> **Provenance needs a commit.** `git init` has been run but nothing is committed, so every run
> reports `git: not a checkout (dirty)`. Make the first commit and provenance starts identifying the
> code that produced each artifact. Runs from a dirty tree stay marked as such, deliberately — see
> [`docs/determinism.md`](docs/determinism.md).

## Repository layout

```
configs/stations/     physical station description (sensor, ADC, thermal constants)
configs/scenarios/    what happens during a run (duration, traffic, drift, faults)
configs/estimators/   calibration algorithm configs           (phase 2+)
configs/experiments/  sweeps that produce paper tables        (phase 6)
src/wimsim/core/      domain types, config, provenance, deterministic RNG
src/wimsim/signal/    generative model + ground-truth log  <- estimators may never import this
src/wimsim/source/    SourceAdapter implementations
src/wimsim/edge/      acquisition -> preprocess -> detect -> estimate -> publish   (phase 2+)
src/wimsim/calibration/  estimators, drift detection, profile store, UQ        (phase 5)
data/real/            the real test drives land here (EXAMPLE/ shows the required shape)
data/synthetic/       generated runs
data/results/         experiment outputs
docs/                 signal-model.md, real-data-schema.md
```

## Documentation

- [`docs/signal-model.md`](docs/signal-model.md) -- every term of the generative model, with units
  and the physical argument for it. Read this before trusting any number the simulator produces.
- [`docs/real-data-schema.md`](docs/real-data-schema.md) -- the drop-in schema the real drives must
  conform to. Fixed now, so the data arrives without negotiation.
- [`docs/determinism.md`](docs/determinism.md) -- how reproducibility is actually enforced.
