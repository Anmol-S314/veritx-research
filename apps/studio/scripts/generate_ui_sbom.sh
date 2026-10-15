#!/usr/bin/env sh
# Reproducible SBOM for the shipped web UI npm runtime graph only.
# Desktop/Tauri and bundled engine binaries require their own build artifacts.
set -eu
cd "$(dirname "$0")/.."
npx --yes @cyclonedx/cyclonedx-npm@6.0.1 \
  --omit dev \
  --spec-version 1.6 \
  --output-reproducible \
  --gather-license-texts \
  --validate \
  --output-file public/STUDIO_UI_SBOM.cdx.json
