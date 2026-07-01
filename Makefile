# VeritX Research — top-level.  Run `make help` for commands.
# Pick a track with TRACK=<name> (default onboarding). The tools (Booksim, gem5,
# Timeloop, Yosys, …) live in a container image; `make run` / `make shell`
# execute inside it. Container runtime (podman or docker) is auto-detected.
.DEFAULT_GOAL := help
.PHONY: help all setup lint test sim report clean run shell pull image-build image-push

TRACK     ?= onboarding
IMAGE     ?= ghcr.io/anmol-s314/veritx-tools-base:latest
CONTAINER := $(shell command -v podman 2>/dev/null || command -v docker 2>/dev/null || echo podman)
RUN        = $(CONTAINER) run --rm -v "$(PWD)":/workspace -w /workspace

help:  ## list top-level commands
	@echo "VeritX — make <target> [TRACK=t3-topology]"
	@grep -hE '^[a-zA-Z][a-zA-Z0-9_-]*:.*##' $(MAKEFILE_LIST) | sort | \
		awk 'BEGIN{FS=":.*## "}{printf "  %-13s %s\n", $$1, $$2}'
	@echo "  setup|lint|test|sim   run that phase for TRACK (e.g. make test TRACK=t4-formal)"
	@echo "tracks: onboarding t1-kvcache t2-deadlock t3-topology t4-formal"

all: setup lint test  ## setup + lint + test for TRACK

setup lint test sim:
	@$(MAKE) -C tracks/$(TRACK) $@

report:  ## build the aggregate report from results/
	@mkdir -p report && python3 scripts/generate_report.py

clean:  ## clean every track + report/ results/
	@for d in tracks/*/; do $(MAKE) -C $$d clean 2>/dev/null || true; done
	@rm -rf report/ results/

pull:  ## pull the prebuilt tools image
	$(CONTAINER) pull $(IMAGE)

run:  ## run a track command in the image:  make run TRACK=t3-topology CMD=timeloop
	$(RUN) $(IMAGE) make -C tracks/$(TRACK) $(CMD)

shell:  ## open an interactive shell in the tools image
	$(CONTAINER) run --rm -it -v "$(PWD)":/workspace -w /workspace $(IMAGE) bash

image-build:  ## build the tools image locally
	$(CONTAINER) build -t $(IMAGE) .

image-push:  ## push the tools image to the registry (needs write auth)
	$(CONTAINER) push $(IMAGE)
