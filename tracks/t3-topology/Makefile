# T3: Topology — Booksim + Timeloop + Accelergy

include ../common.mk

CONFIG ?= baseline

.PHONY: setup lint test sim timeloop energy dashboard clean analysis aggregate plot

# ---------------------------------------------------------------------------
# Dynamic paths — honour env.sh exports; fall back to sensible in-tree defaults
# ---------------------------------------------------------------------------
T3_DIR      ?= $(shell cd .. && pwd)/$(shell basename $(CURDIR))
T3_RESULTS  ?= $(CURDIR)/results
T3_OUTPUT   ?= $(CURDIR)/output
T3_SCRIPTS  ?= $(CURDIR)/scripts
MPLBACKEND  ?= Agg

setup: ## check the toolchain (Booksim required; Timeloop/Accelergy optional)
	@$(call need,booksim)
	@$(call want,timeloop-mapper)
	@python3 -c "import accelergy" 2>/dev/null && \
		echo "  ✓ Booksim + Accelergy present" || \
		echo "  ⚠ accelergy not importable (ok for Booksim-only runs)"

lint: ## syntax-check the Python scripts
	@python3 -m py_compile scripts/*.py 2>/dev/null || true

test: ## quick sanity sweep (the CI gate)
	@python3 scripts/sanity_test.py

sim: ## topology sweep
	@CONFIG=$(CONFIG) \
	python3 scripts/run_experiments.py --config $(CONFIG)

timeloop:  ## full spine: Timeloop workload -> traffic matrix -> topology sweep -> NoC energy
	@mkdir -p results
	-cd timeloop && timeloop-mapper mapper.yaml arch.yaml problem.yaml 2>&1 | tee ../results/timeloop.log
	@if [ -f timeloop/timeloop-mapper.stats.txt ]; then \
		cp timeloop/timeloop-mapper.stats.txt results/timeloop.stats.txt; \
		echo "Extracting traffic matrix..."; \
		python3 scripts/timeloop_to_matrix.py results/timeloop.stats.txt -n 16 -o results/traffic_matrix.txt; \
		echo "Sweeping topologies on the Timeloop traffic matrix..."; \
		TRAFFIC_MATRIX=results/traffic_matrix.txt RATES="0.002,0.005,0.01,0.02,0.04,0.05" python3 scripts/run_experiments.py; \
		echo "Calibrating NoC energy from Booksim hops (Accelergy bridge)..."; \
		python3 scripts/noc_energy_bridge.py; \
		echo "Done — results/ has topology_sweep.json + traffic_matrix.txt + timeloop.stats.txt + noc_energy.json"; \
	else \
		echo "  ⚠  Timeloop produced no stats; falling back to uniform traffic"; \
		python3 scripts/run_experiments.py; \
		echo "Calibrating NoC energy from Booksim hops (Accelergy bridge)..."; \
		python3 scripts/noc_energy_bridge.py; \
		echo "Done — results/ has topology_sweep.json + noc_energy.json (no Timeloop traffic matrix this run)"; \
	fi

timeloop-workload: ## full spine: Timeloop workload -> traffic matrix -> topology sweep
	@mkdir -p results

	@echo "========================================"
	@echo "Running Timeloop Pipeline"
	@echo "Configuration : $(CONFIG)"
	@echo "========================================"

	@CONFIG=$(CONFIG) \
	python3 scripts/run_timeloop_pipeline.py --config $(CONFIG)

	@if [ -f results/$(CONFIG)/execution.json ]; then \
		echo ""; \
		echo "Combining Timeloop statistics..."; \
		CONFIG=$(CONFIG) python3 scripts/combine_timeloop_stats.py; \
		echo ""; \
		echo "Generating combined traffic matrix..."; \
		python3 scripts/timeloop_to_matrix.py \
			results/$(CONFIG)/timeloop.stats.txt \
			-n 16 \
			-o results/$(CONFIG)/traffic_matrix.txt; \
		echo ""; \
		echo "Sweeping topologies..."; \
		CONFIG=$(CONFIG) \
		TRAFFIC_MATRIX=results/$(CONFIG)/traffic_matrix.txt \
		RATES="0.002,0.005,0.01,0.02,0.03" \
		python3 scripts/run_experiments.py --config $(CONFIG); \
		echo ""; \
        echo "Calibrating NoC energy (Accelergy bridge)..."; \
        CONFIG=$(CONFIG) \
        python3 scripts/noc_energy_bridge.py; \
		echo ""; \
		echo "========================================"; \
		echo "Pipeline complete"; \
		echo "========================================"; \
		echo "Configuration : $(CONFIG)"; \
		echo "Results saved under:"; \
		echo "  results/$(CONFIG)/"; \
		echo ""; \
		echo "Generated:"; \
		echo "  • operations/<id>/stats.txt"; \
		echo "  • operations/<id>/map.txt"; \
		echo "  • operations/<id>/map+stats.xml"; \
		echo "  • operations/<id>/traffic_matrix.txt"; \
		echo "  • execution.json"; \
		echo "  • timeloop.stats.txt"; \
		echo "  • traffic_matrix.txt"; \
		echo "  • topology_sweep.json"; \
	else \
		echo "⚠ execution.json not found. Falling back to topology sweep."; \
		CONFIG=$(CONFIG) \
		python3 scripts/run_experiments.py --config $(CONFIG); \
	fi

energy: ## Timeloop energy breakdown
	@CONFIG=$(CONFIG) \
	python3 scripts/energy_report.py \
		results/$(CONFIG)/timeloop.stats.txt \
		--config $(CONFIG)


dashboard:
	@python3 scripts/generate_dashboard.py --config $(CONFIG)

clean: ## remove generated results + Timeloop artifacts

	@rm -rf results/ timeloop/timeloop-mapper* __pycache__/

analysis:  ## PA-01: load sweep JSON → DataFrame summary
	@mkdir -p "$(T3_OUTPUT)"
	@python3 $(T3_SCRIPTS)/analysis.py

aggregate:  ## PA-02: merge all results → $(T3_OUTPUT)/aggregate.csv
	@mkdir -p "$(T3_OUTPUT)"
	@python3 $(T3_SCRIPTS)/aggregate.py \
	    --results "$(T3_RESULTS)" \
	    --out "$(T3_OUTPUT)/aggregate.csv"

plot:  ## PA-03: latency-throughput curves → $(T3_OUTPUT)/latency_curves.png
	@mkdir -p "$(T3_OUTPUT)"
	MPLBACKEND=$(MPLBACKEND) python3 $(T3_SCRIPTS)/plot_curves.py \
	    --sweep "$(T3_RESULTS)/topology_sweep.json" \
	    --hops --out "$(T3_OUTPUT)/latency_curves.png"