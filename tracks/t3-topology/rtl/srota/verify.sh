#!/usr/bin/env bash
set -euo pipefail

script_dir=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)

"$script_dir/lint.sh"
"$script_dir/sim_route.sh"
"$script_dir/sim_sidebuf.sh"
"$script_dir/sim_router_valiant.sh"
"$script_dir/sim_router_stall.sh"
"$script_dir/sim_mecs_channel.sh"

printf 'PASS: Srota extraction lint and directed simulation suite\n'
