# VeritX Research — top-level.  Run `make help` for commands.
# Pick a track with TRACK=<name> (default onboarding). The tools (Booksim, gem5,
# Timeloop, Yosys, …) live in a container image; `make run` / `make shell`
# execute inside it. Container runtime (podman or docker) is auto-detected.
.DEFAULT_GOAL := help
.PHONY: help all setup lint test sim report site clean run shell pull image-build image-push

TRACK     ?= onboarding
# The GitLab (datavex) registry is canonical — that is where we work, and it is
# what .gitlab-ci.yml runs. GHCR is kept in sync by the GitHub mirror's CI, since
# GitHub runners cannot reach the internal host; override with IMAGE=... to use it:
#   make shell IMAGE=ghcr.io/anmol-s314/veritx-tools-base:latest
IMAGE_REPO ?= internal-devrepo.datavex.ai:5050/anmol/veritx-research/veritx-tools-base
# `latest` is a moving target — pin TAG to a commit SHA to reproduce an old result:
#   make run TRACK=t3-topology TAG=a1b2c3d
TAG       ?= latest
IMAGE     ?= $(IMAGE_REPO):$(TAG)
SHA       := $(shell git rev-parse --short HEAD 2>/dev/null || echo unknown)
TRACKS    := $(notdir $(patsubst %/,%,$(wildcard tracks/*/)))
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

site:  ## validate the front-facing site (pages, links, assets, no private URLs)
	python3 scripts/check_site.py site/

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
	$(CONTAINER) build --label org.opencontainers.image.revision=$(SHA) \
		-t $(IMAGE_REPO):$(SHA) -t $(IMAGE_REPO):latest .

image-push:  ## push THIS COMMIT's image (:<sha>) — does not touch `latest`
	$(CONTAINER) push $(IMAGE_REPO):$(SHA)
	@echo "  pushed $(IMAGE_REPO):$(SHA) — latest unchanged; 'make image-promote' moves it"

# Same gate CI enforces, by hand: `latest` is what every contributor and every CI
# job pulls, so it only moves after the image has actually run the suite. Pushing
# straight to `latest` is how an untested image becomes everyone's image.
image-promote:  ## run every track's tests against :<sha>, then make it `latest`
	@echo "gating $(IMAGE_REPO):$(SHA) — running every track's tests inside it"
	@for t in $(TRACKS); do \
		echo "  --- $$t"; \
		$(RUN) $(IMAGE_REPO):$(SHA) make -C tracks/$$t test || \
			{ echo "  ✗ $$t failed — NOT promoting; latest stays where it is"; exit 1; }; \
	done
	$(CONTAINER) tag $(IMAGE_REPO):$(SHA) $(IMAGE_REPO):latest
	$(CONTAINER) push $(IMAGE_REPO):latest
	@echo "  promoted $(SHA) -> latest"

image-rev:  ## which commit built the image you are actually running?
	@$(CONTAINER) inspect --format '{{index .Config.Labels "org.opencontainers.image.revision"}}' \
		$(IMAGE) 2>/dev/null | grep . || echo "unlabelled — built before versioning, or stale"
