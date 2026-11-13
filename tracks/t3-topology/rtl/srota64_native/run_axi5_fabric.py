#!/usr/bin/env python3
"""Build and run the AXI5-through-SROTA64 transaction suite, then emit a receipt.

The suite is 4096 ordered endpoint pairs, each a full AXI5 write (AW + W + B)
followed by a full read (AR + R) whose data crosses the fabric. Verilator is
used because the same suite takes about half an hour under Icarus at roughly
20 ms of wall clock per simulated cycle with 64 bridges instantiated.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[3]
SOURCES = ["srota64_native.sv", "axi5_srota_ep.sv", "tb_axi5_fabric.sv"]


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--receipt", type=Path, default=None)
    ap.add_argument("--keep", action="store_true")
    ap.add_argument("--jobs", type=int, default=4)
    args = ap.parse_args()

    work = Path(tempfile.mkdtemp(prefix="srota64-axi5."))
    try:
        build = subprocess.run(
            ["verilator", "--binary", "--timing", "-Wno-fatal", "-Wno-lint", "-Wno-style",
             f"-j", str(args.jobs), "--top-module", "tb_axi5_fabric", "-Mdir", str(work),
             *SOURCES, "-o", "sim_axi5"],
            cwd=HERE, capture_output=True, text=True)
        if build.returncode != 0:
            print(build.stdout[-4000:], file=sys.stderr)
            print(build.stderr[-4000:], file=sys.stderr)
            return 2

        run = subprocess.run([str(work / "sim_axi5")], cwd=HERE, capture_output=True, text=True)
        lines = [l for l in (run.stdout + run.stderr).splitlines() if l.strip()]
        passed = run.returncode == 0 and any(l.startswith("PASS") for l in lines)
        print("\n".join([l for l in lines if l.startswith(("PASS", "FAIL", "%Error", "%Fatal"))]
                        + lines[-2:]))

        receipt = {
            "result": "PASS" if passed else "FAIL",
            "scope": "AXI5 read and write transactions carried end-to-end through the in-repo "
                     "SROTA64 native fabric; this is the transaction workstream, not the deleted "
                     "Chisel-emitted candidate and not physical implementation",
            "simulator": subprocess.run(["verilator", "--version"], capture_output=True,
                                        text=True).stdout.strip(),
            "checks": {
                "ordered_pairs": 4096,
                "per_pair": "AXI5 write (AW+W+B) then read (AR+R) of one word, "
                            "with BID and RID equal to the issued ids and read data equal to written data",
                "strobe_cases": 2,
                "concurrent_transactions": 2,
                "drain": "every router slot empty, no reply outstanding at any endpoint",
            },
            "output": [l for l in lines if l.startswith("PASS")] + lines[-2:],
            "exit_code": run.returncode,
            "source_sha256": {name: sha(HERE / name) for name in SOURCES},
            "bridge_contract": {
                "address_map": "address bits [11:6] select the destination router, [5:2] select the "
                               "16-word region word",
                "payload": "op[73:72] peer[71:66] id[65:58] word[57:54] wstrb[53:50] data[49:18]",
                "outstanding": "one write and one read per endpoint, in-order replies",
                "responder": "each endpoint owns a 16-word memory; WRITE applies per-lane strobes then "
                             "acks, READ_REQ returns the stored word",
            },
            "limitations": [
                "single beat per transaction; awlen and arlen are ignored, no bursts",
                "no exclusive, atomic, cache, domain or QoS semantics",
                "one outstanding write and one outstanding read per endpoint; no reordering",
                "the fabric remains a behavioral one-entry-per-router prototype, so this proves "
                "transaction correctness through it, not production timing or throughput",
                "no synthesis, placement, timing closure or physical stage",
            ],
        }
        if args.receipt:
            args.receipt.write_text(json.dumps(receipt, indent=1) + "\n")
            print(f"receipt -> {args.receipt}")
        return 0 if passed else 1
    finally:
        if args.keep:
            print(f"build kept at {work}")
        else:
            shutil.rmtree(work, ignore_errors=True)


if __name__ == "__main__":
    raise SystemExit(main())
