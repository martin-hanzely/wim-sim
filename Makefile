# wim-sim -- developer entry points.
# PY is overridable: make PY=python3.12 test
PY ?= .venv/Scripts/python
SCENARIO ?= S1_nominal
OUT ?= data/synthetic/$(SCENARIO)

.PHONY: install sim inspect checkpoint determinism test lint clean up dashboards experiment

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

# --- placeholders for later phases, declared so the interface is stable ---
up:            ## phase 3
	@echo "phase 3: docker compose up -d"
dashboards:    ## phase 4
	@echo "phase 4: provision Grafana dashboards"
experiment:    ## phase 6
	@echo "phase 6: wimsim experiment run <id>"
