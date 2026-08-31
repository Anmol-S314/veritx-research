#!/usr/bin/env python3
"""astra_flitdump_to_trace.py — ASTRA-sim flit_dump -> unified NoC trace (e213 format).

Input: BookSim2 flit_dump file, one line per RETIRED FLIT (booksim2-embed
trafficmanager.cpp:703):
    atime cl src dst pid itime
      atime = retirement cycle, itime = injection cycle.

Output: packet-level time-stamped trace, ONE LINE PER PACKET in the e213
unified format consumed by BOTH the BookSim ranking leg (evaluator.py
--trace / traffic_model.load_traffic) and the RTL replay leg
(noc_frontend gen_trace_hex -> trace_n%d.hex):
    cyc src cl dst sz
      cyc = first injection cycle of the packet (compute-comm overlap
            preserved from the ASTRA-sim run),
      sz  = packet size in flits.

This is the REAL dynamic-traffic path for seed 4f65: LLMServingSim ->
Chakra ET -> AstraSim_BookSim2 (booksim2-embed backend, verified 15,625,155
cycles unicast on Qwen3-30B-A3B) -> flit_dump -> THIS SCRIPT -> unified trace.
No synthetic phase windows involved.

Usage:
    python3 astra_flitdump_to_trace.py <flit_dump.txt> -o <trace.txt> [--stats out.json]
"""
import argparse
import json
import sys
from collections import defaultdict
from pathlib import Path


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("flit_dump", help="BookSim2 flit_dump file (atime cl src dst pid itime)")
    ap.add_argument("-o", "--out", default="astra_trace.txt",
                    help="unified trace output (cyc src cl dst sz)")
    ap.add_argument("--stats", default=None, help="optional JSON stats sidecar")
    ap.add_argument("--segment", type=int, default=0,
                    help="re-segment each message into <=N-flit packets spread "
                         "evenly across its observed injection window (ASTRA-sim "
                         "models collective chunks as single giant messages; 0 = keep)")
    args = ap.parse_args()

    # Stream the dump once; group flits into packets by (cl, src, dst, pid).
    pk_cycle = {}   # key -> first injection cycle
    pk_last = {}    # key -> last injection cycle
    pk_size = {}    # key -> flit count
    n_lines = 0
    t_min = None
    t_max = None
    with open(args.flit_dump) as f:
        for line in f:
            parts = line.split()
            if len(parts) < 6:
                continue
            atime, cl, src, dst, pid, itime = map(int, parts[:6])
            key = (cl, src, dst, pid)
            c = pk_cycle.get(key)
            if c is None or itime < c:
                pk_cycle[key] = itime
            l = pk_last.get(key)
            if l is None or itime > l:
                pk_last[key] = itime
            pk_size[key] = pk_size.get(key, 0) + 1
            n_lines += 1
            if t_min is None or itime < t_min:
                t_min = itime
            if t_max is None or itime > t_max:
                t_max = itime

    if not pk_size:
        sys.exit("no flits parsed from input")

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    span = (t_max - t_min + 1) if t_max != t_min else 1

    # Build (cyc, src, cl, dst, sz) records — either raw messages or re-segmented.
    recs = []
    for (cl, src, dst, pid), cyc in pk_cycle.items():
        sz = pk_size[(cl, src, dst, pid)]
        last = max(pk_last[(cl, src, dst, pid)], cyc)
        seg = args.segment
        if seg and sz > seg:
            n_seg = (sz + seg - 1) // seg
            width = max(last - cyc, 1)
            for i in range(n_seg):
                # spread segments evenly across the message's observed injection window
                sc = cyc + (i * width) // n_seg
                recs.append((sc, src, cl, dst, min(seg, sz - i * seg)))
        else:
            recs.append((cyc, src, cl, dst, sz))
    recs.sort(key=lambda r: r[0])

    with open(out, "w") as f:
        f.write(f"# ASTRA-sim flit_dump-derived trace ({n_lines} flits, "
                f"{len(recs)} packets, {span} cycles, cyc src cl dst sz)\n")
        for cyc, src, cl, dst, sz in recs:
            f.write(f"{cyc} {src} {cl} {dst} {sz}\n")

    print(f"{n_lines} flits -> {len(recs)} packets -> {out}")
    print(f"injection window: {t_min}..{t_max} ({span} cycles)")
    if args.stats:
        sizes = sorted(r[4] for r in recs)
        mean_sz = sum(sizes) / len(sizes)
        med_sz = sizes[len(sizes) // 2]
        Path(args.stats).write_text(json.dumps({
            "source": str(Path(args.flit_dump).name),
            "flits": n_lines,
            "packets": len(recs),
            "segment": args.segment,
            "window_cycles": span,
            "mean_pk_flits": round(mean_sz, 2),
            "median_pk_flits": med_sz,
            "max_pk_flits": max(sizes),
        }, indent=2))
        print(f"stats -> {args.stats}")


if __name__ == "__main__":
    main()
