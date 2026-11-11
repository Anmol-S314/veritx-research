#!/usr/bin/env bash
set -euo pipefail

script_dir=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
verilator=${VERILATOR:-verilator}

if ! command -v "$verilator" >/dev/null 2>&1; then
  printf 'error: Verilator not found: %s\n' "$verilator" >&2
  exit 127
fi

package="$script_dir/srota_route_pkg.sv"
if [[ ! -f "$package" ]]; then
  printf 'error: missing package source: %s\n' "$package" >&2
  exit 1
fi

mapfile -t sources < <(
  find "$script_dir" -maxdepth 1 -type f -name 'srota_*.sv' ! -name 'srota_route_pkg.sv' -print | sort
)
sources=("$package" "${sources[@]}")

mapfile -t declared_modules < <(
  awk '/^[[:space:]]*module[[:space:]]+/ { name = $2; sub(/[ #(].*/, "", name); print name }' "${sources[@]}" | sort -u
)

expected=(
  srota_route_compute
  srota_arb
  srota_arb_l0_golden
  srota_arb_l1_slack
  srota_arb_l2_stc
  srota_fiu_pathsel
  srota_drop_cell
  srota_mecs_row
  srota_mecs_col
  srota_sidebuf
  srota_credit_mgr
  srota_router_d
  srota_top
)

for top in "${expected[@]}"; do
  if ! printf '%s\n' "${declared_modules[@]}" | grep -Fqx -- "$top"; then
    printf 'error: expected top module not found: %s\n' "$top" >&2
    exit 1
  fi
done

build_dir=$(mktemp -d "${TMPDIR:-/tmp/opencode}/srota-verilator.XXXXXX")
trap 'rm -rf -- "$build_dir"' EXIT

for top in "${expected[@]}"; do
  printf 'Linting %s\n' "$top"
  "$verilator" --lint-only --Mdir "$build_dir/$top" --top-module "$top" \
    "${sources[@]}"
done

printf 'PASS: linted %d Srota top modules\n' "${#expected[@]}"
