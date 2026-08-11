# T3: Topology — Booksim + Timeloop + Accelergy
include ../common.mk
.PHONY: setup lint test sim planes timeloop energy area dashboard hw rtl clean

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

planes:  ## plane-separation: DMA bursts vs control traffic (FlooNoC claim)
	@$(if $(BOOKSIM_BIN),,$(call need,booksim))
	@python3 scripts/plane_separation.py

timeloop:  ## full spine: Timeloop (one run per NoC size) -> traffic matrix -> sweep
	@mkdir -p results
	@echo "Running Timeloop — one mapping per node count in configs/ (PEs == tiles)..."
	@# && all the way down: the stages were chained with ';', so make only ever saw
	@# the exit status of the trailing echo — every failure downstream of Timeloop
	@# (a matrix that didn't build, a topology that produced no curve) reported
	@# success. The spine is only green if every stage of it is.
	@if python3 scripts/run_timeloop.py; then \
		echo "Extracting traffic matrices..." && \
		python3 scripts/timeloop_to_matrix.py 'results/timeloop_{n}.stats.txt' \
			-n auto -o 'results/traffic_matrix_{n}.txt' && \
		echo "Sweeping topologies (injection rate ramps to each one's knee)..." && \
		TRAFFIC_MATRIX='results/traffic_matrix_{n}.txt' python3 scripts/run_experiments.py && \
		echo "Done — results/ has topology_sweep.json + traffic_matrix_<N>.txt + timeloop_<N>.stats.txt"; \
	else \
		echo "  ⚠  Timeloop produced no stats; falling back to uniform traffic" && \
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

hw:  ## build+run the Tenstorrent NoC multicast microbench (needs tt-metal SDK + board; NOT in CI)
	@# deliberately NOT called from setup/lint/test, so the hardware-less ci: matrix never hits it.
	@# build.sh exits with instructions if TT_METAL_HOME / a board is absent.
	@cd hardware && ./build.sh && ./noc_multicast_bw

rtl:  ## RTL slice status (see RTL-ARC.md; NOT in CI — needs Verilator/Yosys, no board)
	@# RTL-ARC.md Phase 0 contract is the gate: the RTL↔BookSim parameter table must be
	@# pinned (committed) before any RTL is written. Verilator + Yosys-sby gate the
	@# later phases; neither is required for setup/lint/test.
	@echo "RTL slice (RTL-ARC.md) — Phase 0 contract must land before RTL:"
	@rg -n "The contract|Gate R1" RTL-ARC.md | sed 's/^/  /'
	@if command -v verilator >/dev/null 2>&1; then echo "  ✓ verilator present"; else echo "  ⚠ verilator missing (needed for Gate R1 co-sim)"; fi
	@if command -v yosys >/dev/null 2>&1 && command -v sby >/dev/null 2>&1; then echo "  ✓ yosys + sby present (Gate R4)"; else echo "  ⚠ yosys/sby missing (Gate R4; re-enable in the tools image)"; fi

clean:  ## remove generated results + Timeloop artifacts
	@rm -rf results/ timeloop/timeloop-mapper* __pycache__/
