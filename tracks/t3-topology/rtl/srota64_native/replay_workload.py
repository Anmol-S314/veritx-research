#!/usr/bin/env python3
"""Replay a captured topology trace through the SROTA64 native prototype.

Abstraction (important): the prototype flit is 80 bits, the captured trace
records 64-byte packets. One trace packet is replayed as one fabric packet, and
that is the whole of the mapping: the replay reproduces the trace's ordered
(src, dst, send-cycle) stream, not its byte volume or its original flit framing.

The driver injects in trace order at or after each packet's send cycle, waiting
while the head packet's source router is busy, and accepts every egress beat.
Delivery records are then audited independently: every packet must be delivered
exactly once, from its trace source to its trace destination, with its payload
identity intact, and the fabric must hold nothing at the end.
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


def parse_trace(path: Path, endpoints: int, limit: int | None) -> list[dict]:
    rows: list[dict] = []
    for line in path.read_text().splitlines():
        if not line.strip() or line.startswith("#"):
            continue
        parts = line.split()
        if len(parts) < 5:
            continue
        cycle, src, _rail, dst, size = (int(x) for x in parts[:5])
        if src >= endpoints or dst >= endpoints:
            raise SystemExit(f"endpoint out of range for a {endpoints}-router fabric: {src}->{dst}")
        rows.append({"cycle": cycle, "src": src, "dst": dst, "size": size})
        if limit is not None and len(rows) >= limit:
            break
    if not rows:
        raise SystemExit("trace produced no packets")
    base = min(r["cycle"] for r in rows)
    for r in rows:
        r["cycle"] -= base
    return rows


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--trace", type=Path,
                    default=REPO / "tracks/t3-topology/dse/inputs/traces/chakra_converted.trace")
    ap.add_argument("--limit", type=int, default=None)
    ap.add_argument("--receipt", type=Path, default=None)
    ap.add_argument("--keep", action="store_true", help="keep the scratch stimulus and delivery files")
    args = ap.parse_args()

    trace = args.trace.resolve()
    rows = parse_trace(trace, 64, args.limit)
    sizes = sorted({r["size"] for r in rows})
    if len(sizes) != 1:
        print(f"note: mixed trace packet sizes {sizes}; each packet still replays as one fabric packet")

    work = Path(tempfile.mkdtemp(prefix="srota64-replay."))
    stim = work / "stimulus.tsv"
    deliv = work / "deliveries.tsv"
    vvp = work / "tb_workload.vvp"
    stim.write_text("".join(
        f"{r['cycle']} {r['src']} {r['dst']} {i}\n" for i, r in enumerate(rows)))

    build = subprocess.run(
        ["iverilog", "-g2012", "-s", "tb_workload", "-o", str(vvp),
         str(HERE / "srota64_native.sv"), str(HERE / "tb_workload.sv")],
        capture_output=True, text=True)
    build_msgs = [l for l in (build.stdout + build.stderr).splitlines()
                  if "sorry: constant selects" not in l]
    if build.returncode != 0:
        print("\n".join(build_msgs), file=sys.stderr)
        return 2

    run = subprocess.run(
        ["vvp", str(vvp), f"+stimulus={stim}", f"+deliveries={deliv}",
         f"+packets={len(rows)}"],
        capture_output=True, text=True)
    run_msgs = [l for l in (run.stdout + run.stderr).splitlines() if l.strip()]
    print("\n".join(run_msgs[-4:]))
    if run.returncode != 0:
        print("replay run failed", file=sys.stderr)
        return 3

    delivered: dict[int, dict] = {}
    duplicate: list[int] = []
    stalled = False
    for line in deliv.read_text().splitlines():
        if line.strip() == "STALLED":
            stalled = True
            continue
        pid, inj_router, ejet_router, dst_field, inj, ejc = (int(x) for x in line.split())
        if pid in delivered:
            duplicate.append(pid)
        delivered[pid] = {"src": inj_router, "dst": ejet_router,
                          "dst_field": dst_field, "inject": inj, "eject": ejc}

    missing = [i for i in range(len(rows)) if i not in delivered]
    mismatched = [i for i, r in enumerate(rows)
                  if i in delivered and (delivered[i]["src"] != r["src"]
                                         or delivered[i]["dst"] != r["dst"]
                                         or delivered[i]["dst_field"] != r["dst"])]
    injected = [d for d in delivered.values() if d["inject"] >= 0]
    latencies = sorted(d["eject"] - d["inject"] for d in injected) or [0]

    passed = not stalled and not missing and not duplicate and not mismatched
    receipt = {
        "result": "PASS" if passed else "FAIL",
        "design": "srota64_native (in-repo SystemVerilog SROTA prototype, K=8, 64 routers, fixed row-first route)",
        "workload": {
            "trace": str(trace.relative_to(REPO)),
            "trace_sha256": hashlib.sha256(trace.read_bytes()).hexdigest(),
            "packets": len(rows),
            "distinct_pairs": len({(r["src"], r["dst"]) for r in rows}),
            "distinct_sources": len({r["src"] for r in rows}),
            "distinct_destinations": len({r["dst"] for r in rows}),
            "self_packets": sum(1 for r in rows if r["src"] == r["dst"]),
            "trace_packet_sizes_bytes": sizes,
            "send_cycle_span": [0, max(r["cycle"] for r in rows)],
            "provenance": "captured topology trace shipped in this repository; not an operator-approved capture set",
        },
        "abstraction": "one captured 64-byte packet replayed as one 80-bit fabric packet; "
                       "byte volume and original flit framing are not reproduced",
        "driver": "trace-ordered head-of-line injection, always-ready sink, "
                  "payload identity in bits [73:58] plus redundant destination tag in [57:54]",
        "audit": {
            "delivered_exactly_once": len(delivered) - len(duplicate),
            "missing": len(missing),
            "duplicates": len(duplicate),
            "wrong_endpoint": len(mismatched),
            "endpoint_meaning": "injected router and ejecting router must equal the trace source and destination; "
                                "the delivered destination field must equal the trace destination",
            "stalled": stalled,
        },
        "latency_cycles": {
            "min": latencies[0],
            "median": latencies[len(latencies) // 2],
            "p95": latencies[min(len(latencies) - 1, int(len(latencies) * 0.95))],
            "max": latencies[-1],
        },
        "source_sha256": {
            "srota64_native.sv": hashlib.sha256((HERE / "srota64_native.sv").read_bytes()).hexdigest(),
            "tb_workload.sv": hashlib.sha256((HERE / "tb_workload.sv").read_bytes()).hexdigest(),
            "replay_workload.py": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        },
        "limitations": [
            "behavioral one-entry-per-router model; not per-input buffering or credit timing",
            "single-flit unicast; captured packet sizes are not reproduced as multi-flit framing",
            "injection is head-of-line serialized by the driver, so measured latency includes driver stalls",
            "no synthesis, placement, timing or physical stage",
        ],
    }

    if args.receipt:
        args.receipt.write_text(json.dumps(receipt, indent=1) + "\n")
        print(f"receipt -> {args.receipt}")
    if not passed:
        print(json.dumps(receipt["audit"], indent=1), file=sys.stderr)
    if not args.keep:
        shutil.rmtree(work, ignore_errors=True)
    else:
        print(f"scratch kept at {work}")
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
