# T2: Deadlock-Free Routing — Booksim 2.0
include ../common.mk
.PHONY: setup lint test sim clean

setup:  ## check Booksim is available
	@$(call need,booksim)
	@echo "  ✓ Booksim present"

lint:  ## syntax-check the Python scripts
	@python3 -m py_compile scripts/*.py 2>/dev/null || true

test:  ## quick sanity sim (4x4 mesh, uniform)
	@python3 scripts/sanity_test.py

sim:  ## run the deadlock experiment suite
	@python3 scripts/run_experiments.py

clean:  ## remove generated files
	@rm -rf results/ __pycache__/
