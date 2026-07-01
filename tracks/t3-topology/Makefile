# T3: Topology — Makefile (Booksim + Timeloop + Accelergy)
.PHONY: setup lint test sim timeloop dashboard clean

BOOKSIM := $(shell which booksim 2>/dev/null || echo /usr/local/bin/booksim)
TIMELOOP := $(shell which timeloop-mapper 2>/dev/null || echo /usr/local/bin/timeloop-mapper)
TIMELOOP_DIR := $(abspath timeloop)

setup:
	@echo "Verifying tools..."
	@test -x $(BOOKSIM) || (echo "Booksim not found"; exit 1)
	@python3 -c "import accelergy; print('Accelergy OK:', accelergy.__version__)" 2>/dev/null || \
		echo "  ⚠  Accelergy import check skipped (ok for Booksim-only experiments)"
	@test -x $(TIMELOOP) || (echo "  ⚠  timeloop-mapper not found — Timeloop spine unavailable (ok for uniform runs)")

lint:
	@echo "Linting configs..."
	@python3 -m py_compile scripts/*.py 2>/dev/null || true

test:
	@echo "Running T3 sanity sim..."
	@python3 scripts/sanity_test.py

# Full sweep: uniform traffic baseline (always runs)
sim:
	@echo "Running T3 topology experiment suite (uniform traffic)..."
	@python3 scripts/run_experiments.py

# Timeloop→Booksim spine: model the workload, turn it into a traffic matrix, sweep.
# timeloop-mapper writes timeloop-mapper.stats.txt into timeloop/; copy it where
# the bridge expects it. Falls back to a uniform sweep if Timeloop is unavailable.
timeloop:
	@echo "Running Timeloop workload model (mapper search)..."
	@mkdir -p results
	-cd timeloop && $(TIMELOOP) mapper.yaml arch.yaml problem.yaml 2>&1 | tee ../results/timeloop.log
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

dashboard:
	@echo "Generating T3 dashboard..."
	@python3 scripts/generate_dashboard.py
	@echo "  open report/t3/index.html"

clean:
	@rm -rf results/ timeloop/timeloop-mapper* __pycache__/
