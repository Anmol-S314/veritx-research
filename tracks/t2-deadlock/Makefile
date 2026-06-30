# T2: Deadlock — Makefile (Booksim 2.0)
.PHONY: setup lint test sim clean

BOOKSIM := $(shell which booksim 2>/dev/null || echo /usr/local/bin/booksim)

setup:
	@echo "Verifying Booksim..."
	@test -x $(BOOKSIM) || (echo "Booksim not found — rebuild Docker image"; exit 1)
	@$(BOOKSIM) --version 2>/dev/null || echo "  OK"

lint:
	@echo "Linting Booksim configs..."
	@python3 -m py_compile scripts/*.py 2>/dev/null || true

test:
	@echo "Running T2 sanity sim (4x4 mesh, uniform)..."
	@python3 scripts/sanity_test.py

sim:
	@echo "Running T2 deadlock experiment suite..."
	@python3 scripts/run_experiments.py

clean:
	@rm -rf results/ __pycache__/
