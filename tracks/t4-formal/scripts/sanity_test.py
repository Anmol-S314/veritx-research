#!/usr/bin/env python3
"""T4 Formal — sanity test: run SymbiYosys on a counter with BMC."""
import subprocess, json, sys, os
from pathlib import Path

RTL_DIR = Path(__file__).parent.parent / "rtl"
RESULTS = Path(__file__).parent.parent / "results"

SBY_SCRIPT = """\
[options]
mode bmc
depth 10

[engines]
smtbmc z3

[script]
read -formal {rtl}
prep -top counter

[files]
{rtl}
"""

def main():
    RESULTS.mkdir(parents=True, exist_ok=True)
    rtl_file = RTL_DIR / "counter.sv"
    if not rtl_file.exists():
        print(f"  RTL not found: {rtl_file}")
        sys.exit(1)

    sby = os.environ.get("SBY_BIN") or "sby"
    build_dir = RESULTS / "sby_counter_bmc"
    build_dir.mkdir(exist_ok=True)

    script = SBY_SCRIPT.format(rtl=str(rtl_file))
    script_path = build_dir / "counter.sby"
    script_path.write_text(script)

    result = subprocess.run(
        [sby, "-f", str(script_path)],
        capture_output=True, text=True, timeout=120,
        cwd=str(build_dir)
    )
    stdout = result.stdout
    status = "pass" if "PASS" in stdout or "SUCCESS" in stdout else "fail"
    print(f"  SymbiYosys result: {status}")

    data = {
        "track": "t4-formal",
        "design": "counter",
        "mode": "bmc",
        "depth": 10,
        "status": status,
        "output": stdout[-500:]
    }
    report = RESULTS / "sanity_result.json"
    with open(report, "w") as f:
        json.dump(data, f, indent=2)

    if status == "fail":
        print(f"  Formal proof FAILED:\n{result.stderr[:500]}")
        sys.exit(1)
    print("  T4 sanity OK")

if __name__ == "__main__":
    main()
