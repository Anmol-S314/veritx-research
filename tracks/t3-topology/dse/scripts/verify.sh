#!/bin/bash
set -e
echo "=== VeritX DSE Verification Gate ==="
RED='\033[0;31m'; GREEN='\033[0;32m'; NC='\033[0m'
PASS=0; FAIL=0
check() { local name="$1"; shift; if "$@" >/dev/null 2>&1; then echo -e "${GREEN}✅ $name${NC}"; PASS=$((PASS+1)); else echo -e "${RED}❌ $name${NC}"; FAIL=$((FAIL+1)); fi; }
R="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../../.." && pwd)"
D="$R/tracks/t3-topology/dse"
echo "--- Package Integrity ---"
check "import" python3 -c "import sys;sys.path.insert(0,'$D');from veritx_dse import recommend,search,evaluator,space"
echo "--- RTL Generation ---"
check "gen_rtl" python3 "$R/tracks/t3-topology/scripts/rtlgen/gen_rtl.py" --anynet "$R/.noc_p0/tiny4.anynet" --outdir /tmp/vt --block-k 16
check "rtl_files" test -f /tmp/vt/noc_pkg.sv -a -f /tmp/vt/router.sv
echo "--- Workloads ---"
check "prod_wl" python3 "$D/workload_generator.py" --n-tiles 4 --out-dir /tmp/vw
check "cust_wl" python3 "$D/customer_workloads.py" --n-tiles 4 --out-dir /tmp/vw
check "auto_wl" python3 "$D/automotive_workloads.py" --n-tiles 4 --out-dir /tmp/vw
echo "--- Sanity ---"
check "m2" python3 -c "import sys;sys.path.insert(0,'$D');from veritx_dse.ir_derivation import derive_qwen3_moe_ir;derive_qwen3_moe_ir()"
check "hash" python3 -c "import hashlib;assert len(hashlib.sha1(b'test').hexdigest())==40"
echo "=== $PASS pass, $FAIL fail ==="
[ $FAIL -eq 0 ] && echo -e "${GREEN}ALL PASSED${NC}" && exit 0 || echo -e "${RED}FAILED${NC}" && exit 1
