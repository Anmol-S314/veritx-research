#!/usr/bin/env bash
# cleanup_runs.sh — remove regenerable run artifacts, keep the evidence.
#
# Policy (what is kept, always):
#   * docs/product/evidence/**                       — pinned release evidence
#   * runs/chipyard-gec6, runs/chipyard-router-physical — cited physical evidence
#   * runs/veritx-p2p7p11-evidence, runs/veritx-p2p8-repro — cited bundles
#   * runs/studio-store/**                            — the product's project store
#   * the NEWEST runs/sequential-gates-*               — the running gate chain
#   * the NEWEST runs/rtl-*matrix*                     — the live family-matrix run
#   * every manifest.json / *.log / *.json report      — the evidence inside a run
#
# What is removed:
#   * Verilator/Icarus build trees (obj_*/, *.vvp, Vtb_*, *.o, *.a) — regenerable
#   * emitted RTL trees inside matrix runs (the manifest keeps their sha256s)
#   * stale pytest basetemps, scratch experiment dirs, old gate dirs
#
# Usage: scripts/cleanup_runs.sh [--dry-run] [--keep-gates N] [--keep-matrix N]
set -uo pipefail

REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO"

DRY=0
KEEP_GATES=1
KEEP_MATRIX=1
while [ $# -gt 0 ]; do
  case "$1" in
    --dry-run) DRY=1 ;;
    --keep-gates) KEEP_GATES="${2:-1}"; shift ;;
    --keep-matrix) KEEP_MATRIX="${2:-1}"; shift ;;
    *) echo "unknown argument: $1" >&2; exit 2 ;;
  esac
  shift
done

freed=0
removed=0

report() {
  local size="$1"; local path="$2"
  freed=$((freed + size))
  removed=$((removed + 1))
  if [ "$DRY" = "1" ]; then
    echo "would remove $(human "$size")  $path"
  else
    rm -rf "$path" && echo "removed $(human "$size")  $path"
  fi
}

human() {
  awk -v k="$1" 'BEGIN{ if (k > 1048576) printf "%.1fG", k/1048576; else if (k > 1024) printf "%.0fM", k/1024; else printf "%dK", k }'
}

size_of() { du -sk "$1" 2>/dev/null | cut -f1; }

# 1. Build trees inside runs/ (keep manifests and logs).
while IFS= read -r obj; do
  [ -d "$obj" ] || continue
  report "$(size_of "$obj")" "$obj"
done < <(find runs -maxdepth 4 -type d \( -name 'obj_*' -o -name 'obj_dir' \) 2>/dev/null)

# 2. Emitted RTL trees of superseded matrix runs (the newest is kept whole).
mapfile -t matrices < <(find runs -maxdepth 1 -type d -name 'rtl-*matrix*' -printf '%T@ %p\n' 2>/dev/null | sort -rn | cut -d' ' -f2-)
if [ "${#matrices[@]}" -gt "$KEEP_MATRIX" ]; then
  for (( i = KEEP_MATRIX; i < ${#matrices[@]}; i++ )); do
    while IFS= read -r rtl; do
      [ -d "$rtl" ] || continue
      report "$(size_of "$rtl")" "$rtl"
    done < <(find "${matrices[$i]}" -maxdepth 2 -type d -name rtl 2>/dev/null)
  done
fi

# 3. Old gate chains (the newest stays: it is the live one).
mapfile -t gates < <(find runs -maxdepth 1 -type d -name 'sequential-gates-*' -printf '%T@ %p\n' 2>/dev/null | sort -rn | cut -d' ' -f2-)
if [ "${#gates[@]}" -gt "$KEEP_GATES" ]; then
  for (( i = KEEP_GATES; i < ${#gates[@]}; i++ )); do
    report "$(size_of "${gates[$i]}")" "${gates[$i]}"
  done
fi

# 4. Stale pytest basetemps (keep the newest; a live run's dir is the newest).
#    Anything modified in the last 10 minutes is left alone.
mapfile -t bases < <(find .scratch/tmp/pytest-of-datavex -maxdepth 1 -type d -name 'pytest-*' -printf '%T@ %p\n' 2>/dev/null | sort -rn | cut -d' ' -f2-)
if [ "${#bases[@]}" -gt 1 ]; then
  for (( i = 1; i < ${#bases[@]}; i++ )); do
    if [ -n "$(find "${bases[$i]}" -maxdepth 0 -mmin -10 2>/dev/null)" ]; then
      echo "skipping (modified in the last 10 min)  ${bases[$i]}"
      continue
    fi
    report "$(size_of "${bases[$i]}")" "${bases[$i]}"
  done
fi

# 5. Scratch experiment dirs (everything except the pytest tree), skipping
#    anything touched in the last 10 minutes — a live run owns those.
if [ -d .scratch/tmp ]; then
  while IFS= read -r entry; do
    case "$entry" in
      */pytest-of-datavex) continue ;;
    esac
    if [ -n "$(find "$entry" -maxdepth 0 -mmin -10 2>/dev/null)" ]; then
      echo "skipping (modified in the last 10 min)  $entry"
      continue
    fi
    report "$(size_of "$entry")" "$entry"
  done < <(find .scratch/tmp -mindepth 1 -maxdepth 1 2>/dev/null)
fi
if [ -d .scratch/tmp ]; then
  while IFS= read -r entry; do
    case "$entry" in
      */pytest-of-datavex) continue ;;
    esac
    report "$(size_of "$entry")" "$entry"
  done < <(find .scratch/tmp -mindepth 1 -maxdepth 1 2>/dev/null)
fi

# 6. The repo-local RTL scratch build trees.
for dir in tracks/t3-topology/rtl/multi_seat/obj_conc tracks/t3-topology/rtl/formal/addr_decode_formal; do
  if [ -d "$dir" ]; then
    report "$(size_of "$dir")" "$dir"
  fi
done

echo "---"
if [ "$DRY" = "1" ]; then
  echo "dry run: $removed paths, would free $(human "$freed")"
else
  echo "cleanup done: $removed paths removed, $(human "$freed") freed"
fi
