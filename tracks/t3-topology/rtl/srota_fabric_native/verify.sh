#!/usr/bin/env bash
set -euo pipefail

script_dir=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
repo_root=$(cd -- "$script_dir/../../../.." && pwd)
tmp_dir=$(mktemp -d "${TMPDIR:-/tmp}/srota-fabric-native.XXXXXX")
trap 'rm -rf -- "$tmp_dir"' EXIT

blocker='SROTA_FABRIC_BLOCKER_MECS_ROUTER_BINDING'
if ! grep -Fq "$blocker" "$script_dir/README.md"; then
  echo "FAIL: documented typed blocker missing: $blocker" >&2
  exit 1
fi

# Validate the leaf routing and shared-channel primitives that the blocker
# prevents us from composing into a speculative end-to-end fabric.
"$repo_root/tracks/t3-topology/rtl/srota/sim_route.sh" >"$tmp_dir/route.log" 2>&1
"$repo_root/tracks/t3-topology/rtl/srota/sim_mecs_channel.sh" >"$tmp_dir/mecs.log" 2>&1

echo "PASS: typed fabric blocker documented"
grep -E 'PASS:|PASS ' "$tmp_dir/route.log" | tail -n 2
grep -E 'PASS:|PASS ' "$tmp_dir/mecs.log" | tail -n 2
echo "NOTE: no fabric packet test run; integration is blocked by unresolved MECS/router binding semantics."
