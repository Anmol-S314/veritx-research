# T4: Formal Verification — SymbiYosys + Yosys + CBMC
include ../common.mk
.PHONY: setup lint test sim clean

setup:  ## check the formal toolchain (Yosys, CBMC, SymbiYosys)
	@$(call need,yosys)
	@$(call need,cbmc)
	@$(call need,sby)
	@yosys --version 2>/dev/null | head -1

lint:  ## syntax-check the Python scripts
	@python3 -m py_compile scripts/*.py 2>/dev/null || true

test:  ## run the sanity proof
	@python3 scripts/sanity_test.py

sim:  ## run the formal verification suite
	@python3 scripts/run_experiments.py

clean:  ## remove generated files + logs
	@rm -rf results/ formal_logs/ __pycache__/
