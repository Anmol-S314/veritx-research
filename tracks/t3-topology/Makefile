# T3: Topology — Booksim + Timeloop + Accelergy
include ../common.mk
.PHONY: setup lint test sim timeloop energy area dashboard clean

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

timeloop:  ## full spine: Timeloop (one run per NoC size) -> traffic matrix -> sweep
	@mkdir -p results
	@echo "Running Timeloop — one mapping per node count in configs/ (PEs == tiles)..."
	@if python3 scripts/run_timeloop.py; then \
		echo "Extracting traffic matrices..."; \
		python3 scripts/timeloop_to_matrix.py 'results/timeloop_{n}.stats.txt' \
			-n auto -o 'results/traffic_matrix_{n}.txt'; \
		echo "Sweeping topologies (injection rate ramps to each one's knee)..."; \
		TRAFFIC_MATRIX='results/traffic_matrix_{n}.txt' python3 scripts/run_experiments.py; \
		echo "Done — results/ has topology_sweep.json + traffic_matrix_<N>.txt + timeloop_<N>.stats.txt"; \
	else \
		echo "  ⚠  Timeloop produced no stats; falling back to uniform traffic"; \
		python3 scripts/run_experiments.py; \
	fi

energy:  ## energy (Timeloop) + real die area (Accelergy) per NoC size
	@mkdir -p results
	@if ! ls results/timeloop_*.stats.txt >/dev/null 2>&1; then \
		echo "no Timeloop stats yet — running the model..."; \
		python3 scripts/run_timeloop.py; \
	fi
	@for f in results/timeloop_*.stats.txt; do \
		n=$$(basename $$f .stats.txt | sed 's/timeloop_//'); \
		python3 scripts/area_report.py -n $$n; \
		python3 scripts/energy_report.py $$f; \
		echo; \
	done

area:  ## die area from Accelergy (routers + buffers + MACs), per NoC size
	@mkdir -p results
	@for n in $$(python3 -c "import sys; sys.path.insert(0,'scripts'); \
		from timeloop_to_matrix import sizes_from_configs; print(' '.join(map(str, sizes_from_configs())))"); do \
		python3 scripts/area_report.py -n $$n; \
	done

dashboard:  ## (re)build report/t3/index.html from results/
	@python3 scripts/generate_dashboard.py

clean:  ## remove generated results + Timeloop artifacts
	@rm -rf results/ timeloop/timeloop-mapper* __pycache__/
