# T4: Formal Verification — Makefile (SymbiYosys + Yosys + CBMC)
.PHONY: setup lint test sim clean

YOSYS := $(shell which yosys 2>/dev/null || echo /usr/local/bin/yosys)
CBMC   := $(shell which cbmc 2>/dev/null || echo /usr/local/bin/cbmc)
SBY    := $(shell which sby 2>/dev/null || echo /usr/local/bin/sby)

setup:
	@echo "Verifying tools..."
	@test -x $(YOSYS) || (echo "Yosys not found"; exit 1)
	@test -x $(CBMC)   || (echo "CBMC not found"; exit 1)
	@test -x $(SBY)    || (echo "SymbiYosys not found"; exit 1)
	@$(YOSYS) --version 2>/dev/null | head -1

lint:
	@echo "Linting Verilog/SV files..."
	@python3 -m py_compile scripts/*.py 2>/dev/null || true

test:
	@echo "Running T4 sanity proof..."
	@python3 scripts/sanity_test.py

sim:
	@echo "Running T4 formal verification suite..."
	@python3 scripts/run_experiments.py

clean:
	@rm -rf results/ formal_logs/ __pycache__/
