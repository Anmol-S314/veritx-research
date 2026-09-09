#!/usr/bin/env python3
"""verify_ring.py — End-to-end RTL verification pipeline.

Usage:
  python3 verify_ring.py                          # 4-node ring
  python3 verify_ring.py --anynet custom_v2.anynet --limit 16  # 16-node
  python3 verify_ring.py --sweep                  # multi-IR sweep

Steps: gen → verilator → build → run at multiple IRs → check assertions.
"""
import argparse
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
REPO_ROOT = SCRIPT_DIR.parent.parent.parent.parent  # veritx-research/
RING4 = "/tmp/opencode/ring4b.anynet"


def run(cmd, cwd=None, timeout=120, check=True):
    r = subprocess.run(cmd, shell=True, cwd=cwd, capture_output=True, text=True, timeout=timeout)
    if check and r.returncode != 0:
        print(f"FAIL: {cmd}")
        print(f"  stdout: {r.stdout[-500:]}")
        print(f"  stderr: {r.stderr[-500:]}")
        sys.exit(1)
    return r


def gen_rtl(anynet, outdir, limit, buf=8):
    """Step 1: Generate RTL from .anynet topology."""
    print(f"[1/4] Generating RTL for {limit}-router topology...")
    gen_py = SCRIPT_DIR / "gen_rtl.py"
    run(f"python3 {gen_py} --anynet {anynet} --outdir {outdir} --limit {limit} --buf {buf}")
    files = list(Path(outdir).glob("*.sv")) + list(Path(outdir).glob("*.cpp"))
    print(f"  Generated {len(files)} files in {outdir}")
    return outdir


def build_rtl(workdir):
    """Step 2: Compile with Verilator + g++."""
    print(f"[2/4] Building Verilator binary...")
    r = run(f"make -C {workdir}", timeout=180, check=False)
    if r.returncode != 0:
        print(f"  BUILD FAILED:\n{r.stdout[-1000:]}\n{r.stderr[-1000:]}")
        sys.exit(1)
    binary = workdir / "obj_dir" / "Vnoc_top"
    if not binary.exists():
        print(f"  BUILD FAILED: binary not found at {binary}")
        sys.exit(1)
    size_mb = binary.stat().st_size / 1024 / 1024
    print(f"  Binary: {binary} ({size_mb:.1f} MB)")
    return binary


def run_sim(binary, ir, drain=20000):
    """Step 3: Run simulation at given injection rate."""
    env = os.environ.copy()
    env["NOC_IR"] = str(ir)
    env["NOC_DRAIN"] = str(drain)
    r = subprocess.run(
        [str(binary)],
        env=env, capture_output=True, text=True, timeout=300
    )
    return r.stdout + r.stderr


def check_results(output, ir):
    """Step 4: Parse output and check all assertions."""
    results = {}
    for line in output.split("\n"):
        line = line.strip()
        if "injected:" in line:
            parts = line.split()
            results["injected"] = int(parts[1])
        elif "ejected:" in line and "wrong" not in line:
            parts = line.split()
            results["ejected"] = int(parts[1])
        elif "wrong_dst:" in line:
            parts = line.split()
            results["wrong_dst"] = int(parts[1])
            results["wrong_dst_ok"] = "OK" in line
        elif "outstanding:" in line:
            parts = line.split()
            results["outstanding"] = int(parts[1])
            results["outstanding_ok"] = "OK" in line
        elif "status:" in line:
            results["pass"] = "PASS" in line
        elif "STUCK:" in line:
            if "stuck_list" not in results:
                results["stuck_list"] = []
            results["stuck_list"].append(line)
        elif "ASSERTION" in line or "OVF" in line or "CREDIT" in line:
            if "assertions" not in results:
                results["assertions"] = []
            results["assertions"].append(line)
        elif "RT_INJ-" in line:
            parts = line.split()
            for p in parts:
                if p.startswith("inj="):
                    results["rt_inj"] = int(p.split("=")[1])
                elif p.startswith("ej="):
                    results["rt_ej"] = int(p.split("=")[1])

    # Check assertions
    results["assertion_pass"] = True
    if "assertions" in results:
        results["assertion_pass"] = len(results["assertions"]) == 0

    return results


def print_report(results, ir):
    """Print verification report for one IR."""
    inj = results.get("injected", 0)
    ej = results.get("ejected", 0)
    wd = results.get("wrong_dst", 0)
    out = results.get("outstanding", 0)
    passed = results.get("pass", False)
    assertions_ok = results.get("assertion_pass", True)

    status = "PASS" if (passed and assertions_ok) else "FAIL"
    icon = "✅" if status == "PASS" else "❌"

    print(f"  IR={ir:.2f}  {icon} {status}  "
          f"inj={inj}  ej={ej}  wrong_dst={wd}  outstanding={out}"
          f"  {'assertions OK' if assertions_ok else 'ASSERTION FAILED'}")

    if not assertions_ok:
        for a in results.get("assertions", []):
            print(f"    ⚠️  {a}")

    stuck = results.get("stuck_list", [])
    if stuck:
        for s in stuck[:3]:
            print(f"    🔒 {s}")
        if len(stuck) > 3:
            print(f"    ... and {len(stuck)-3} more stuck packets")

    return status == "PASS"


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--anynet", default=RING4, help=".anynet topology file")
    ap.add_argument("--limit", type=int, default=4, help="max routers")
    ap.add_argument("--buf", type=int, default=8, help="buffer depth")
    ap.add_argument("--outdir", default=None, help="RTL output dir (default: auto)")
    ap.add_argument("--sweep", action="store_true", help="run at multiple IRs")
    ap.add_argument("--ir", type=float, default=0.08, help="injection rate")
    ap.add_argument("--drain", type=int, default=20000, help="drain cycles")
    args = ap.parse_args()

    outdir = args.outdir or tempfile.mkdtemp(prefix="verify_")
    outdir = Path(outdir)

    # Step 1: Generate RTL
    gen_rtl(args.anynet, outdir, args.limit, args.buf)

    # Step 2: Build
    binary = build_rtl(outdir)

    # Step 3+4: Run and check
    irs = [0.04, 0.08, 0.16, 0.24, 0.32] if args.sweep else [args.ir]

    print(f"\n[3/4] Running simulation at {len(irs)} injection rate(s)...")
    all_pass = True
    for ir in irs:
        output = run_sim(binary, ir, args.drain)
        results = check_results(output, ir)
        ok = print_report(results, ir)
        if not ok:
            all_pass = False

    # Step 5: Summary
    print(f"\n[4/4] Verification summary")
    print(f"  Topology: {args.anynet}")
    print(f"  Routers:  {args.limit}")
    print(f"  Buffer:   {args.buf}")
    print(f"  IRs tested: {irs}")
    print(f"  Overall: {'✅ ALL PASS' if all_pass else '❌ FAILURES DETECTED'}")

    if not all_pass:
        sys.exit(1)


if __name__ == "__main__":
    main()
