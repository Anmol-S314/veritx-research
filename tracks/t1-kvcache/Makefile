# T1: KVCache QoS — Makefile (gem5/Garnet/ASTRA-sim)
.PHONY: setup lint test sim clean

GEM5_BIN := $(shell which gem5.opt 2>/dev/null || echo /usr/local/bin/gem5.opt)

setup:
	@echo "Verifying gem5..."
	@test -x $(GEM5_BIN) || (echo "gem5 not found — rebuild Docker image"; exit 1)
	@$(GEM5_BIN) --version 2>/dev/null | head -1

lint:
	@echo "Linting gem5 configs..."
	@python3 -m py_compile scripts/*.py 2>/dev/null || true

test:
	@echo "Running T1 sanity sim (4x4 mesh, uniform)..."
	@python3 scripts/sanity_test.py

sim:
	@echo "Running T1 experiment suite..."
	@python3 scripts/run_experiments.py

clean:
	@rm -rf results/ m5out/ __pycache__/
