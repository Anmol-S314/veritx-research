#!/usr/bin/env python3
"""T4 Formal — run all formal proofs (BMC and induction) on all RTL designs."""
import subprocess, json, sys, os, time
from pathlib import Path

RTL_DIR = Path(__file__).parent.parent / "rtl"
RESULTS_DIR = Path(__file__).parent.parent / "results"
DESIGNS = sorted(RTL_DIR.glob("*.sv"))

def gen_sby(rtl_path: Path, mode: str, depth: int) -> str:
    top = rtl_path.stem
    return f"""\
[options]
mode {mode}
depth {depth}
dump_vcd on

[engines]
smtbmc z3

[script]
read -formal {rtl_path}
prep -top {top}

[files]
{rtl_path}
"""

def run_proof(rtl: Path, mode: str, depth: int) -> dict:
    sby = os.environ.get("SBY_BIN") or "sby"
    top = rtl.stem
    tag = f"{top}_{mode}_d{depth}"
    build_dir = RESULTS_DIR / tag
    build_dir.mkdir(parents=True, exist_ok=True)

    script = gen_sby(rtl, mode, depth)
    script_path = build_dir / f"{top}.sby"
    script_path.write_text(script)

    start = time.time()
    result = subprocess.run(
        [sby, "-f", str(script_path)],
        capture_output=True, text=True, timeout=300,
        cwd=str(build_dir)
    )
    elapsed = time.time() - start

    stdout = result.stdout
    passed = "PASS" in stdout or "SUCCESS" in stdout
    status = "pass" if passed else "fail"

    trace_vcd = build_dir / "engine_0" / "trace.vcd"
    trace_path = str(trace_vcd) if trace_vcd.exists() else None

    return {
        "design": top,
        "mode": mode,
        "depth": depth,
        "status": status,
        "elapsed_s": round(elapsed, 2),
        "trace_vcd": trace_path,
        "output_truncated": stdout[-500:] if not passed else "",
    }

def main():
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    all_results = []

    # bmc depth 10/20 + prove = sby's k-induction mode (no "induction" mode exists)
    for rtl in DESIGNS:
        for mode, depths in [("bmc", [10, 20]), ("prove", [10])]:
            for depth in depths:
                print(f"  {rtl.stem} [{mode} depth={depth}] ...", end=" ")
                res = run_proof(rtl, mode, depth)
                print(res["status"])
                all_results.append(res)

    report = RESULTS_DIR / "experiments.json"
    with open(report, "w") as f:
        json.dump(all_results, f, indent=2)
    print(f"\n  {len(all_results)} proofs → {report}")

    failures = [r for r in all_results if r["status"] == "fail"]
    if failures:
        print(f"  ⚠  {len(failures)} proof(s) failed")
        for f in failures:
            print(f"     {f['design']} [{f['mode']} d={f['depth']}]")

if __name__ == "__main__":
    main()
