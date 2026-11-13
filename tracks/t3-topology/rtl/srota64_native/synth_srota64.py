#!/usr/bin/env python3
"""Generic synthesis of the SROTA64 native prototype with Yosys.

This is synthesis only. There is no place and route, no timing analysis and no
approved target platform on this machine, so the numbers below are a
technology-independent cell and flop count from `proc; opt; memory; opt; stat`,
not an implementation result and not a performance claim.

Yosys needs hours rather than minutes on this design at 64 routers, so the run
can be done once into a log file and the receipt regenerated from that log with
`--from-log`.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[3]
TOPS = {
    "bridge": {
        "top": "axi5_srota_ep",
        "sources": ["axi5_srota_ep.sv"],
        "flow": "proc; memory -nomap; opt -fast; stat",
    },
    "fabric": {
        "top": "srota64_native",
        "sources": ["srota64_native.sv"],
        "flow": "proc; memory -nomap; opt -fast; stat",
    },
}


def yosys_script(kind: str) -> str:
    spec = TOPS[kind]
    lines = [f"read_verilog -sv {src}" for src in spec["sources"]]
    lines.append(f"hierarchy -top {spec['top']}")
    lines.extend(spec["flow"].split("; "))
    lines.append("stat")
    return "\n".join(lines) + "\n"


def parse_stat(log: str) -> dict:
    cells = re.findall(r"^\s+(\S+)\s+(\d+)\s*$", log, re.MULTILINE)
    counts = {}
    for name, n in cells:
        if name in {"cells", "wires", "wire bits", "public wires", "public wire bits",
                    "memories", "memory bits", "processes"}:
            continue
        counts[name.lstrip("\\")] = int(n)
    # Final "Number of cells:" line from stat.
    m = re.search(r"Number of cells:\s+(\d+)", log)
    total = int(m.group(1)) if m else None
    bits = re.search(r"Number of wire bits:\s+(\d+)", log)
    mems = re.search(r"Number of memories:\s+(\d+)", log)
    membits = re.search(r"Number of memory bits:\s+(\d+)", log)
    procs = re.search(r"Number of processes:\s+(\d+)", log)
    latches = re.search(r"Number of \$dlatch.*?:\s+(\d+)", log)
    return {
        "cells_total": total,
        "wire_bits": int(bits.group(1)) if bits else None,
        "memories": int(mems.group(1)) if mems else None,
        "memory_bits": int(membits.group(1)) if membits else None,
        "processes_left": int(procs.group(1)) if procs else None,
        "dlatches": int(latches.group(1)) if latches else 0,
        "cell_types": dict(sorted(counts.items(), key=lambda kv: -kv[1])[:20]),
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--top", choices=sorted(TOPS), default="bridge")
    ap.add_argument("--from-log", type=Path, default=None)
    ap.add_argument("--log", type=Path, default=None, help="write the yosys log here")
    ap.add_argument("--receipt", type=Path, default=None)
    ap.add_argument("--timeout", type=int, default=4 * 3600)
    args = ap.parse_args()

    if args.from_log:
        log = args.from_log.read_text(errors="replace")
        returncode = 0
    else:
        script = Path(tempfile.mkstemp(suffix=".ys")[1])
        script.write_text(yosys_script(args.top))
        run = subprocess.run(["yosys", str(script)], cwd=HERE, capture_output=True,
                             text=True, timeout=args.timeout)
        log = run.stdout + run.stderr
        returncode = run.returncode
        if args.log:
            args.log.write_text(log)
        if returncode != 0:
            print(log[-4000:], file=sys.stderr)
            return 2

    stat = parse_stat(log)
    warnings = [l for l in log.splitlines() if l.startswith("Warning:")]
    replaced = [l for l in warnings if "Replacing memory" in l]
    problems = [l for l in warnings if "latch" in l.lower() and "Replacing" not in l]
    ok = returncode == 0 and stat["cells_total"] is not None and stat["dlatches"] == 0

    import shutil
    receipt = {
        "result": "PASS" if ok else "FAIL",
        "stage": "generic synthesis only (Yosys read_verilog -> proc -> opt -> memory -nomap -> opt -> stat)",
        "design": TOPS[args.top]["sources"][0] + " (" + TOPS[args.top]["top"] + ")",
        "flow": TOPS[args.top]["flow"],
        "tool": subprocess.run(["yosys", "-V"], capture_output=True, text=True).stdout.strip().splitlines()[0]
                if shutil.which("yosys") else "yosys (version unavailable at receipt time)",
        "stat": stat,
        "warnings": {
            "count": len(warnings),
            "memory_replaced_by_registers": len(replaced),
            "latch_warnings": len(problems),
            "note": "the segment and payload arrays are behavioural prototypes; Yosys replaces them with "
                    "register lists, which is expected for this model and is not a memory inference success",
        },
        "source_sha256": {src: hashlib.sha256((HERE / src).read_bytes()).hexdigest()
                          for src in TOPS[args.top]["sources"]},
        "not_run": [
            "place and route",
            "static timing analysis",
            "power",
            "DRC/LVS",
            "approved target platform mapping",
        ],
        "why_not_run": "this machine has Yosys only: no nextpnr, no OpenROAD/OpenSTA, and no operator-approved "
                       "implementation platform, so a physical stage cannot be produced or claimed here",
        "limitations": [
            "technology-independent cell count, not standard-cell or FPGA numbers",
            "generic synthesis proves the model is synthesizable; it says nothing about achievable frequency, "
            "area on a real library, or timing correlation with the behavioural simulation",
        ],
    }
    if args.receipt:
        args.receipt.write_text(json.dumps(receipt, indent=1) + "\n")
        print(f"receipt -> {args.receipt}")
    print(json.dumps({k: stat[k] for k in ("cells_total", "wire_bits", "memory_bits", "dlatches")}, indent=1))
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
