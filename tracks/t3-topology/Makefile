# T3: Topology — Booksim + Timeloop + Accelergy
include ../common.mk
.PHONY: setup lint test sim timeloop dashboard clean

setup:  ## check the toolchain (Booksim required; Timeloop/Accelergy optional)
	@$(call need,booksim)
	@$(call want,timeloop-mapper)
	@python3 -c "import accelergy" 2>/dev/null && echo "  ✓ Booksim + Accelergy present" || echo "  ⚠ accelergy not importable (ok for Booksim-only runs)"

lint:  ## syntax-check the Python scripts
	@python3 -m py_compile scripts/*.py 2>/dev/null || true

test:  ## quick sanity sweep (the CI gate)
	@python3 scripts/sanity_test.py

sim:  ## uniform-traffic topology sweep (baseline)
	@python3 scripts/run_experiments.py

timeloop:  ## full spine: Timeloop workload -> traffic matrix -> topology sweep
	@mkdir -p results
	-cd timeloop && timeloop-mapper mapper.yaml arch.yaml problem.yaml 2>&1 | tee ../results/timeloop.log
	@if [ -f timeloop/timeloop-mapper.stats.txt ]; then \
		cp timeloop/timeloop-mapper.stats.txt results/timeloop.stats.txt; \
		echo "Extracting traffic matrix..."; \
		python3 scripts/timeloop_to_matrix.py results/timeloop.stats.txt -n 16 -o results/traffic_matrix.txt; \
		echo "Sweeping topologies on the Timeloop traffic matrix..."; \
		TRAFFIC_MATRIX=results/traffic_matrix.txt RATES="0.002,0.005,0.01,0.02,0.03" python3 scripts/run_experiments.py; \
		echo "Done — results/ has topology_sweep.json + traffic_matrix.txt + timeloop.stats.txt"; \
	else \
		echo "  ⚠  Timeloop produced no stats; falling back to uniform traffic"; \
		python3 scripts/run_experiments.py; \
	fi

dashboard:  ## (re)build report/t3/index.html from results/
	@python3 scripts/generate_dashboard.py

clean:  ## remove generated results + Timeloop artifacts
	@rm -rf results/ timeloop/timeloop-mapper* __pycache__/
