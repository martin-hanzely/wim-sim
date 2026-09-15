# wim-sim -- developer entry points.
# PY is overridable: make PY=python3.12 test
PY ?= .venv/Scripts/python
SCENARIO ?= S1_nominal
EDGE ?= default
OUT ?= data/synthetic/$(SCENARIO)
EXPERIMENT ?= ladder
REAL ?= data/real/20260209_cintron1
CHANNEL ?= Tenzo1

.PHONY: install sim inspect checkpoint determinism test clean up up-core down logs migrate
.PHONY: score experiment experiment-dry detect-real gap-report

install:
	$(PY) -m pip install -e ".[dev]"

## generate a synthetic run (override: make sim SCENARIO=S4_step_fault)
sim:
	$(PY) -m wimsim.cli generate --scenario $(SCENARIO) --out $(OUT)

inspect:
	$(PY) -m wimsim.cli inspect $(OUT)

## Phase 1 checkpoint: a plot of a synthetic pass with its truth values
checkpoint: sim
	$(PY) -m wimsim.cli plot-pass $(OUT) --index 0
	$(PY) -m wimsim.cli plot-run $(OUT)

## same seed + same config => byte-identical output
determinism:
	$(PY) -m wimsim.cli generate --scenario $(SCENARIO) --out .determinism/a --quiet
	$(PY) -m wimsim.cli generate --scenario $(SCENARIO) --out .determinism/b --quiet
	$(PY) -m wimsim.cli verify-determinism .determinism/a .determinism/b

test:
	$(PY) -m pytest -q

clean:
	rm -rf .determinism .pytest_cache
	find . -name __pycache__ -type d -prune -exec rm -rf {} +

## bring up the whole stack (broker, database, observability plane)
up:
	docker compose --profile full up -d

## just the broker and the database -- enough for the pipeline and its tests
up-core:
	docker compose --profile core up -d

down:
	docker compose --profile full down

logs:
	docker compose --profile full logs -f --tail=100

## create or update the database schema. Alembic owns it; nothing else creates a table.
migrate:
	$(PY) -m alembic upgrade head

## run the edge pipeline over a run and score it against truth
score: sim
	$(PY) -m wimsim.cli run $(OUT) --edge $(EDGE)

## Phase 6 checkpoint: every estimator across every scenario, three seeds each.
## About an hour. `make experiment EXPERIMENT=quick` is the two-scenario version.
## Results, table, LaTeX and figures land in data/results/$(EXPERIMENT)/.
experiment:
	$(PY) -m wimsim.cli experiment $(EXPERIMENT)

## the grid and what it costs, running nothing
experiment-dry:
	$(PY) -m wimsim.cli experiment $(EXPERIMENT) --dry-run

## what the detector finds in a real recording. No masses: that needs a weighed vehicle.
detect-real:
	$(PY) -m wimsim.cli detect S8_replay_real --edge cintron_platform \
	  --set scenario.source.replay.run_dir=$(REAL) \
	  --set scenario.source.replay.channel=$(CHANNEL)

## where the simulator and the real sensor disagree
gap-report:
	$(PY) -m wimsim.cli gap-report $(REAL) --channel $(CHANNEL)
