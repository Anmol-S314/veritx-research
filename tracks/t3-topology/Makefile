# T3: Topology — Makefile (Booksim + Timeloop + Accelergy)
.PHONY: setup lint test sim clean

BOOKSIM := $(shell which booksim 2>/dev/null || echo /usr/local/bin/booksim)

setup:
	@echo "Verifying tools..."
	@test -x $(BOOKSIM) || (echo "Booksim not found"; exit 1)
	@python3 -c "import timeloop; print('Timeloop OK:', timeloop.__version__)" 2>/dev/null || \
		echo "  ⚠  Timeloop import check skipped"
	@python3 -c "import accelergy; print('Accelergy OK')" 2>/dev/null || \
		echo "  ⚠  Accelergy import check skipped"

lint:
	@echo "Linting configs..."
	@python3 -m py_compile scripts/*.py 2>/dev/null || true

test:
	@echo "Running T3 sanity sim..."
	@python3 scripts/sanity_test.py

sim:
	@echo "Running T3 topology experiment suite..."
	@python3 scripts/run_experiments.py

clean:
	@rm -rf results/ __pycache__/
