# T3: Topology — Makefile (Booksim + Timeloop + Accelergy)
.PHONY: setup lint test sim timeloop dashboard clean

BOOKSIM := $(shell which booksim 2>/dev/null || echo /usr/local/bin/booksim)
TIMELOOP := $(shell which timeloop-model 2>/dev/null || echo /usr/local/bin/timeloop-model)
TIMELOOP_DIR := $(abspath timeloop)

setup:
	@echo "Verifying tools..."
	@test -x $(BOOKSIM) || (echo "Booksim not found"; exit 1)
	@python3 -c "import accelergy; print('Accelergy OK:', accelergy.__version__)" 2>/dev/null || \
		echo "  ⚠  Accelergy import check skipped (ok for Booksim-only experiments)"
	@test -x $(TIMELOOP) || (echo "  ⚠  timeloop-model not found — Timeloop spine unavailable (ok for uniform runs)")

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

# Timeloop→Booksim spine: generate traffic matrix from workload model, then sweep
timeloop:
	@echo "Running Timeloop workload model..."
	@mkdir -p timeloop results
	@cd timeloop && $(TIMELOOP) problem.yaml arch.yaml map.yaml 2>&1 | tee ../results/timeloop.log
	@echo "Extracting traffic matrix..."
	@python3 scripts/timeloop_to_matrix.py results/timeloop.stats.txt -n 16 -o results/traffic_matrix.txt
	@echo "Running Booksim with generated traffic matrix..."
	@TRAFFIC_MATRIX=results/traffic_matrix.txt python3 scripts/run_experiments.py
	@echo "Done — results in results/ ; matrix in results/traffic_matrix.txt"

dashboard:
	@echo "Generating T3 dashboard..."
	@python3 scripts/generate_dashboard.py
	@echo "  open report/t3/index.html"

clean:
	@rm -rf results/ timeloop/timeloop-model* __pycache__/
