# T3: Topology — Booksim + ASTRA-Sim 2.0
include ../common.mk

MODEL ?= llama7b
CONFIG ?= baseline

.PHONY: setup lint test sim astrasim energy dashboard clean analysis aggregate plot report pa-report permissions

# ---------------------------------------------------------------------------
# Dynamic paths — honour env.sh exports; fall back to sensible in-tree defaults
# ---------------------------------------------------------------------------
T3_DIR      ?= $(shell cd .. && pwd)/$(shell basename $(CURDIR))
T3_RESULTS  ?= $(CURDIR)/results/$(CONFIG)
T3_ANALYSIS ?= $(T3_RESULTS)/analysis
T3_OUTPUT   ?= $(T3_ANALYSIS)
T3_SCRIPTS  ?= $(CURDIR)/scripts
MPLBACKEND  ?= Agg

setup: ## check the toolchain (Booksim required)
	@$(call need,booksim)
	@python3 -c "import accelergy" 2>/dev/null && \
		echo "  ✓ Booksim + Accelergy present" || \
		echo "  ⚠ accelergy not importable (ok for Booksim-only runs)"

lint: ## syntax-check the Python scripts
	@python3 -m py_compile scripts/*.py 2>/dev/null || true

test: ## quick sanity sweep (the CI gate)
	@python3 scripts/sanity_test.py

sim: ## topology sweep (Booksim backend)
	@CONFIG=$(CONFIG) \
	python3 scripts/run_experiments.py --config $(CONFIG)

astrasim:  ## ASTRA-Sim 2.0 Chakra workload -> network sweep -> energy
	@CONFIG=$(CONFIG) \
	python3 scripts/run_astrasim.py --config $(CONFIG) --model $(MODEL)

energy: ## NoC & workload energy breakdown
	@CONFIG=$(CONFIG) \
	python3 scripts/noc_energy_bridge.py

dashboard: ## build Plotly dashboard
	@python3 scripts/generate_dashboard.py --config $(CONFIG)

clean: ## remove generated results + build artifacts
	@rm -rf results/ timeloop/timeloop-mapper* __pycache__ scripts/__pycache__

analysis:  ## PA-01: read sweep JSON → print DataFrame summary
	@python3 $(T3_SCRIPTS)/analysis.py \
	    --sweep "$(T3_RESULTS)/topology_sweep.json"

aggregate:  ## PA-02: merge all results → $(T3_ANALYSIS)/aggregate.csv
	@mkdir -p "$(T3_ANALYSIS)"
	@python3 $(T3_SCRIPTS)/aggregate.py \
	    --results "$(T3_RESULTS)" \
	    --out "$(T3_ANALYSIS)/aggregate.csv"

plot:  ## PA-03: latency-throughput curves → $(T3_ANALYSIS)/latency_curves.png
	@mkdir -p "$(T3_ANALYSIS)"
	MPLBACKEND=$(MPLBACKEND) python3 $(T3_SCRIPTS)/plot_curves.py \
	    --sweep "$(T3_RESULTS)/topology_sweep.json" \
	    --hops --out "$(T3_ANALYSIS)/latency_curves.png"

report pa-report: analysis aggregate plot ## PA: run full analysis pipeline (analysis + aggregate + plot)

permissions:
	@chmod -R 777 "$(T3_RESULTS)" 2>/dev/null || true
