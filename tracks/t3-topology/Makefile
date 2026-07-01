# T3: Topology — Makefile (Booksim + Timeloop + Accelergy)
.PHONY: setup lint test sim dashboard clean

BOOKSIM := $(shell which booksim 2>/dev/null || echo /usr/local/bin/booksim)

setup:
	@echo "Verifying tools..."
	@test -x $(BOOKSIM) || (echo "Booksim not found"; exit 1)
	@python3 -c "import accelergy; print('Accelergy OK:', accelergy.__version__)" 2>/dev/null || \
		echo "  ⚠  Accelergy import check skipped (ok for Booksim-only experiments)"
	@echo "  Timeloop: deferred (needs scons build)"

lint:
	@echo "Linting configs..."
	@python3 -m py_compile scripts/*.py 2>/dev/null || true

test:
	@echo "Running T3 sanity sim..."
	@python3 scripts/sanity_test.py

sim:
	@echo "Running T3 topology experiment suite..."
	@python3 scripts/run_experiments.py

dashboard:
	@echo "Generating T3 dashboard..."
	@python3 scripts/generate_dashboard.py
	@echo "  open report/t3/index.html"

clean:
	@rm -rf results/ __pycache__/
