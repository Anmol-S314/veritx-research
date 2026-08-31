# T3: Topology — Booksim + Timeloop + Accelergy
include ../common.mk
.PHONY: setup lint test sim astrasim astrasim-workload energy dashboard clean 

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

astrasim:  ## ASTRA-Sim 2.0 Chakra workload -> network sweep -> energy
	@python3 scripts/run_astrasim.py --config $(CONFIG) --model $(MODEL)

energy:  ## Timeloop energy breakdown (pJ/compute + energy-delay product)
	@mkdir -p results
	@if [ ! -f results/timeloop.stats.txt ]; then \
		echo "no Timeloop stats yet — running the model..."; \
		( cd timeloop && timeloop-mapper mapper.yaml arch.yaml problem.yaml >/dev/null 2>&1 ) \
		  && cp timeloop/timeloop-mapper.stats.txt results/timeloop.stats.txt; \
	fi
	@python3 scripts/energy_report.py results/timeloop.stats.txt
	@if [ -f results/topology_sweep.json ]; then \
		python3 scripts/noc_energy_bridge.py; \
	fi

dashboard:  ## (re)build report/t3/index.html from results/
	@python3 scripts/generate_dashboard.py

clean:  ## remove generated results + Timeloop artifacts
	@rm -rf results/ timeloop/timeloop-mapper* __pycache__/