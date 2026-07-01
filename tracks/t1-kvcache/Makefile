# T1: KV-Cache QoS — gem5 / Garnet / ASTRA-sim
include ../common.mk
.PHONY: setup lint test sim clean

setup:  ## check gem5 (deferred build — see docs/adr/ADR-0001)
	@$(call want,gem5.opt)
	@command -v gem5.opt >/dev/null 2>&1 && gem5.opt --version 2>/dev/null | head -1 || true

lint:  ## syntax-check the Python scripts
	@python3 -m py_compile scripts/*.py 2>/dev/null || true

test:  ## sanity check
	@python3 scripts/sanity_test.py

sim:  ## run the experiment suite
	@python3 scripts/run_experiments.py

clean:  ## remove generated files + gem5 m5out/
	@rm -rf results/ m5out/ __pycache__/
