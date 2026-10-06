#!/usr/bin/env bash
# VeritX convergence gate — ONE script consumed by GitHub (.github/workflows)
# and GitLab (.gitlab-ci.yml) so the two CIs cannot diverge.
#
# Stages (every stage runs even when an earlier one fails):
#   1. product-gates   registry gates incl. capability truth
#   2. dse-pytest      full DSE unit suite
#   3. studio-tsc      Studio typecheck (SKIP when node is absent)
#   4. studio-vitest   Studio contract tests (SKIP when deps cannot install)
#   5. studio-pytest   Studio python tests
#
# Exit status: 0 only when every stage PASSes. A stage that cannot run
# reports SKIP with its reason and does not mask a FAIL elsewhere.
set -u
REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO"

PASS=0; FAIL=0; SKIP=0; FAILED_STAGES=""

stage() { # name, then command... — records PASS/FAIL, never stops the run
  local name="$1"; shift
  echo "--- ci-gate stage: $name ---"
  if "$@"; then
    echo "--- ci-gate $name: PASS ---"
    PASS=$((PASS + 1))
  else
    echo "--- ci-gate $name: FAIL ---"
    FAIL=$((FAIL + 1))
    FAILED_STAGES="$FAILED_STAGES $name"
  fi
}

skip() { # name, reason
  echo "--- ci-gate stage: $1 ---"
  echo "SKIP: $2"
  echo "--- ci-gate $1: SKIP ---"
  SKIP=$((SKIP + 1))
}

stage product-gates make -C tracks/t3-topology product-gates

stage dse-pytest env \
  PYTHONPATH="tracks/t3-topology/dse:tracks/t3-topology/dse/tests" \
  python3 -m pytest tracks/t3-topology/dse/tests -q -p no:randomly

if command -v node >/dev/null 2>&1 && command -v npx >/dev/null 2>&1; then
  if [ ! -d apps/studio/node_modules ]; then
    if command -v npm >/dev/null 2>&1; then
      stage studio-npm-ci npm --prefix apps/studio ci --no-audit --no-fund
    else
      skip studio-npm-ci "npm absent and apps/studio/node_modules missing"
    fi
  fi
  if [ -d apps/studio/node_modules ]; then
    stage studio-tsc bash -c 'cd apps/studio && npx tsc --noEmit'
    stage studio-vitest bash -c 'cd apps/studio && npx vitest run'
  else
    skip studio-tsc "apps/studio/node_modules absent"
    skip studio-vitest "apps/studio/node_modules absent"
  fi
else
  skip studio-tsc "node/npx absent"
  skip studio-vitest "node/npx absent"
fi

stage studio-pytest env \
  PYTHONPATH="tracks/t3-topology/dse:tracks/t3-topology/dse/tests" \
  python3 -m pytest apps/studio/tests -q -p no:randomly

echo "CI GATE: PASS=$PASS FAIL=$FAIL SKIP=$SKIP"
if [ "$FAIL" -ne 0 ]; then
  echo "CI GATE FAILED:$FAILED_STAGES"
  exit 1
fi
echo "CI GATE GREEN"
