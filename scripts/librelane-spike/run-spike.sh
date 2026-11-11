#!/usr/bin/env bash
# LibreLane + ASAP7 feasibility spike for the composed project_top.sv.
#
# This runner reproduces docs/design/asap7-librelane-spike.md.
# It proves two things end-to-end on a podman host:
#   1. PDK availability (ASAP7 via volare/ciel -- BLOCKED, with evidence)
#   2. Flow mechanics for the slice RTL (PASS for the small memory module;
#      BLOCKED at the SV frontend for the full composed top)
#
# Env knobs:
#   SPIKE_HOME  scratch dir (default: $HOME/librelane-spike)
#   TMPDIR      MUST be a disk-backed dir: host /tmp is a usrquota tmpfs
#               where pip/volare writes fail with "Disk quota exceeded".
set -euo pipefail

SPIKE_HOME="${SPIKE_HOME:-$HOME/librelane-spike}"
PDK_ROOT="${PDK_ROOT:-$SPIKE_HOME/pdks}"
export TMPDIR="$SPIKE_HOME/tmp"
mkdir -p "$TMPDIR" "$PDK_ROOT"

# 0) LibreLane framework + PDK tools (the actual tool binaries come from
#    the container image below; podman is the container engine).
uv pip install --python "$SPIKE_HOME/.venv/bin/python" librelane==3.0.17 volare ciel
"$SPIKE_HOME/.venv/bin/librelane" --version        # -> LibreLane v3.0.17

# 1) ASAP7 PDK availability (expected: none -- see spike doc for evidence).
#    ciel rejects asap7 as an unknown family; volare ls-remote returns an
#    empty list for it. Run these to see the raw output yourself:
#      ciel ls-remote --pdk-family asap7
#      volare ls-remote --pdk asap7

# 2) Obtainable fallback PDK (sky130A, the hash LibreLane itself pins):
#    LibreLane 3.0.17 pdk_hashes.yaml pins sky130 -> 8afc8346...
podman pull ghcr.io/librelane/librelane:3.0.17     # tools image, NOT a PDK
"$SPIKE_HOME/.venv/bin/volare" fetch --pdk-root "$PDK_ROOT" \
  8afc8346a57fe1ab7934ba5a6056ea8b43078e71
"$SPIKE_HOME/.venv/bin/volare" enable --pdk-root "$PDK_ROOT" \
  8afc8346a57fe1ab7934ba5a6056ea8b43078e71

export PDK_ROOT
cd "$SPIKE_HOME/project_top"      # holds src/*.sv (10 slice files) + config
"$SPIKE_HOME/.venv/bin/librelane" --dockerized config.json
