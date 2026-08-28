# wim-sim -- developer entry points.
# PY is overridable: make PY=python3.12 test
PY ?= .venv/Scripts/python
SCENARIO ?= S1_nominal
EDGE ?= default
OUT ?= data/synthetic/$(SCENARIO)

.PHONY: install sim inspect checkpoint determinism test clean up up-core down logs migrate score experiment

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

experiment:    ## phase 6
	@echo "phase 6: wimsim experiment run <id>"
