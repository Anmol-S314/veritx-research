# T3: Topology — Booksim + ASTRA-Sim 2.0
include ../common.mk

MODEL ?= llama7b
CONFIG ?= baseline

.PHONY: setup lint test sim astrasim energy dashboard clean analysis aggregate plot report pa-report permissions lock pr-a-gate

# ---------------------------------------------------------------------------
# Dynamic paths — honour env.sh exports; fall back to sensible in-tree defaults
# ---------------------------------------------------------------------------
T3_DIR      ?= $(shell cd .. && pwd)/$(shell basename $(CURDIR))
T3_RESULTS  ?= $(CURDIR)/results/$(CONFIG)
T3_ANALYSIS ?= $(T3_RESULTS)/analysis
T3_OUTPUT   ?= $(T3_ANALYSIS)
T3_SCRIPTS  ?= $(CURDIR)/scripts
MPLBACKEND  ?= Agg

lock: ## regenerate dse/requirements.lock from the current environment (PR A)
	@cd dse && python3 lock_deps.py > requirements.lock && echo "  ✓ dse/requirements.lock regenerated"

pr-a-gate: ## PR A gate: clean env install from declared metadata + focused core tests
	@python3 -m venv /tmp/veritx-pra-venv && \
		/tmp/veritx-pra-venv/bin/pip install -q -e dse && \
		/tmp/veritx-pra-venv/bin/python -m pytest dse/tests/test_run_core.py dse/tests/test_slice_a_booksim.py -q -p no:cacheprovider && \
		rm -rf /tmp/veritx-pra-venv && echo "  ✓ PR A gate: install + focused tests OK"

setup: ## check the toolchain (Booksim required)
	@$(call need,booksim)
	@python3 -c "import accelergy" 2>/dev/null && \
		echo "  ✓ Booksim + Accelergy present" || \
		echo "  ⚠ accelergy not importable (ok for Booksim-only runs)"

lint: ## syntax-check the Python scripts + collect tests + binary-free selfchecks (CI-safe, no simulators)
	@python3 -m py_compile scripts/*.py scripts/lib/*.py dse/veritx_dse/**/*.py
	@python3 -m pytest dse/tests --collect-only -q -p no:cacheprovider
	@for s in analysis aggregate plot_curves compare_bars compare_curves compare_heatmap generate_dashboard; do \
		python3 scripts/$$s.py --selfcheck > /dev/null || exit 1; \
	done
	@python3 scripts/generate_chakra_trace.py --selfcheck > /dev/null
	@python3 scripts/run_astrasim.py --selfcheck > /dev/null

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

compare-report:  ## PA-04: surface latest veritx compare → stdout (no-op when step 2 not run)
	@python3 $(T3_SCRIPTS)/report_compare.py --results "$(T3_RESULTS)"

report pa-report: analysis aggregate plot compare-report ## PA: run full analysis pipeline (analysis + aggregate + plot + compare)

permissions:
	@chmod -R 777 "$(T3_RESULTS)" 2>/dev/null || true
