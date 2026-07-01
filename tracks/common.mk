# ─────────────────────────────────────────────────────────────────────────────
# Shared machinery for every track. Put `include ../common.mk` at the TOP of a
# track Makefile, then give each target a `## one-line help` comment.
#
# Adding a track:  copy an existing tracks/<x>/, keep the same verbs
# (setup / lint / test / sim), `include ../common.mk`, and it shows up in
# `make help` and `make TRACK=<x> ...` automatically — no root Makefile change.
#
# In a recipe:
#   @$(call need,<tool>)   hard-fail with a "run in the image" hint if missing
#   @$(call want,<tool>)   soft warning only (optional / deferred tools)
# ─────────────────────────────────────────────────────────────────────────────
.DEFAULT_GOAL := help

need = command -v $(1) >/dev/null 2>&1 || { echo "  ✗ $(1) not found — run inside the tools image:  make run TRACK=$(notdir $(CURDIR)) CMD=<target>"; exit 1; }
want = command -v $(1) >/dev/null 2>&1 || echo "  ⚠ $(1) not found (optional here; full runs need the tools image)"

.PHONY: help
help:  ## list this track's commands
	@echo "$(notdir $(CURDIR)) — make <target>   (tools live in the image; from repo root: make run TRACK=$(notdir $(CURDIR)) CMD=<target>)"
	@grep -hE '^[a-zA-Z][a-zA-Z0-9_-]*:.*##' $(MAKEFILE_LIST) | sort -u | \
		awk 'BEGIN{FS=":.*## "}{printf "  %-12s %s\n", $$1, $$2}'
