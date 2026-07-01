# Onboarding Track
include ../common.mk
.PHONY: setup lint test sim clean

setup:  ## nothing to install — tools come from the image
	@echo "Onboarding: all tools are provided by the container image."

lint:  ## (no lint for onboarding)
	@echo "No lint for onboarding."

test:  ## validate the toolchain is reachable
	@python3 scripts/sanity_test.py

sim:  ## (no simulation for onboarding)
	@echo "No simulation for onboarding."

clean:  ## remove generated files
	@rm -rf results/ __pycache__/
