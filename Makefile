# VeritX Research — top-level.  Run `make help` for commands.
# Pick a track with TRACK=<name> (default onboarding). The tools (Booksim, gem5,
# Timeloop, Yosys, …) live in a container image; `make run` / `make shell`
# execute inside it. Container runtime (podman or docker) is auto-detected.
.DEFAULT_GOAL := help
.PHONY: help all setup lint test sim report clean run shell pull image-build image-push
.PHONY: tools tool-info tool-build tool-run tool-sync tool-tag tool-pick tool-clean

TRACK     ?= onboarding
IMAGE     ?= ghcr.io/anmol-s314/veritx-tools-base:latest
CONTAINER := $(shell command -v podman 2>/dev/null || command -v docker 2>/dev/null || echo podman)
RUN        = $(CONTAINER) run --rm -v "$(PWD)":/workspace -w /workspace
CONFIG    ?= baseline

help:  ## list top-level commands
	@echo "VeritX — make <target> [TRACK=t3-topology]"
	@grep -hE '^[a-zA-Z][a-zA-Z0-9_-]*:.*##' $(MAKEFILE_LIST) | sort | \
		awk 'BEGIN{FS=":.*## "}{printf "  %-13s %s\n", $$1, $$2}'
	@echo "  setup|lint|test|sim   run that phase for TRACK (e.g. make test TRACK=t4-formal)"
	@echo "tracks: onboarding t1-kvcache t2-deadlock t3-topology t4-formal"

all: setup lint test  ## setup + lint + test for TRACK

setup lint test sim:
	@$(MAKE) -C tracks/$(TRACK) $@

analysis aggregate plot:  ## run PA target for TRACK in container (CONFIG=baseline)
	$(RUN) $(IMAGE) make -C tracks/$(TRACK) $@ \
	    T3_RESULTS=/workspace/tracks/$(TRACK)/results/$(CONFIG)

pa-report:  ## run full PA pipeline (analysis+aggregate+plot) in container
	$(RUN) $(IMAGE) make -C tracks/$(TRACK) report \
	    T3_RESULTS=/workspace/tracks/$(TRACK)/results/$(CONFIG)

report:  ## build the aggregate report from results/
	@mkdir -p report
	$(RUN) -e MPLBACKEND=Agg $(IMAGE) python3 scripts/generate_report.py

clean:	## clean every track + report/ results/
	@$(RUN) $(IMAGE) sh -c 'for d in tracks/*/; do $(MAKE) -C "$$d" clean 2>/dev/null || true; done; rm -rf report/ results/'

pull:  ## pull the prebuilt tools image
	$(CONTAINER) pull $(IMAGE)

run:  ## run a track command in the image:  make run TRACK=t3-topology CMD=timeloop
	$(RUN) $(IMAGE) make -C tracks/$(TRACK) $(CMD) CONFIG=${CONFIG}

shell:  ## open an interactive shell in the tools image
	$(CONTAINER) run --rm -it -v "$(PWD)":/workspace -w /workspace $(IMAGE) bash

image-build:  ## build the tools image locally
	$(CONTAINER) build -t $(IMAGE) .

image-push:  ## push the tools image to the registry (needs write auth)
	$(CONTAINER) push $(IMAGE)

# -- Release backend build + provenance manifests (host toolchain) --
# Builds every backend the release gates need from tracked source only and
# writes a build-time provenance manifest beside each binary. A released
# binary without a manifest is never pinned for reusable evidence.
#
# ONE toolchain variable controls both the build and the manifest, so a
# release cannot record a compiler it did not use (C1.5). Choose the
# toolchain with `RELEASE_CXX=clang++ make release-build`; it is passed
# explicitly to the recursive make (BookSim), the ASTRA build and the
# Ramulator cmake, so an ambient `CXX` cannot desynchronise them.

RELEASE_CXX ?= g++

.PHONY: release-build release-manifest
release-build:  ## build all release-gate backends from source + manifests
	$(MAKE) -C third_party/booksim2/src CXX=$(RELEASE_CXX)
	CXX=$(RELEASE_CXX) JOBS=$${JOBS:-$$(nproc)} sh third_party/astra-sim/build/astra_booksim2/build.sh
	cd third_party/ramulator2 && CXX=$(RELEASE_CXX) JOBS=$${JOBS:-$$(nproc)} ./build.sh
	$(MAKE) release-manifest RELEASE_CXX=$(RELEASE_CXX)

release-manifest:  ## write build-time provenance manifests for built backends
	python3 scripts/write_build_manifest.py third_party/booksim2/src/booksim \
	    --recipe-version booksim2-fork/v1 --compiler $(RELEASE_CXX) \
	    --build-config Release --flag=-O3 --flag=-g
	python3 scripts/write_build_manifest.py \
	    third_party/astra-sim/astra-sim/network_frontend/booksim2/bin/AstraSim_BookSim2 \
	    --recipe-version astra-sim+booksim2/v1 --compiler $(RELEASE_CXX) \
	    --build-config Release

# -- Vendored tool management (scripts/tools.py) --

tools:  ## list all vendored tools with status
	@python3 scripts/tools.py

tool-info:  ## show details for TOOL (e.g. make tool-info TOOL=booksim2)
	@python3 scripts/tools.py $(TOOL) info

tool-build:  ## build TOOL (e.g. make tool-build TOOL=booksim2)
	@python3 scripts/tools.py $(TOOL) build

tool-sync:  ## sync TOOL to downstream copies (e.g. make tool-sync TOOL=booksim2)
	@python3 scripts/tools.py $(TOOL) sync

tool-tag:  ## tag TOOL at VERSION (e.g. make tool-tag TOOL=booksim2 VER=2.1)
	@python3 scripts/tools.py $(TOOL) tag $(VER)

tool-pick:  ## interactive version picker for TOOL
	@python3 scripts/tools.py $(TOOL) pick

tool-run:  ## run TOOL binary with ARGS (e.g. make tool-run TOOL=booksim2 ARGS="cfg trace.txt")
	@python3 scripts/tools.py $(TOOL) run $(ARGS)

tool-clean:  ## clean TOOL build artifacts
	@python3 scripts/tools.py $(TOOL) clean

tool-image:  ## rebuild container image with current tool versions
	$(CONTAINER) build -t $(IMAGE) .

tool-image-push:  ## push container image to registry
	$(CONTAINER) push $(IMAGE)
