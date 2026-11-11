#!/usr/bin/env python3
"""Project the measured Llama TP=4 operation ledger into a ring BookSim trace.

The source paper reports operation counts and payload shapes, not packet events.
This output is therefore a declared ring/schedule projection, never a captured
NCCL trace. See README.md and projection assumptions below.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

PROFILE = Path(__file__).with_name("collectives.json")
WORLD = 4
FLIT_BYTES = 32                 # chosen projection: 256-bit flit
MAX_PACKET_FLITS = 16           # chosen projection: 512-byte max packet
PACKET_GAP_CYCLES = 1           # chosen: one packet/source/cycle
ROUND_BARRIER_GAP_CYCLES = 32   # chosen: fixed, not measured NCCL timing


def packet_sizes(payload_bytes: int) -> list[int]:
    """Return BookSim packet sizes in flits, preserving exact payload bytes."""
    total_flits, remainder = divmod(payload_bytes, FLIT_BYTES)
    if remainder:
        raise ValueError(f"payload {payload_bytes} is not flit-aligned")
    packets, tail = divmod(total_flits, MAX_PACKET_FLITS)
    result = [MAX_PACKET_FLITS] * packets
    if tail:
        result.append(tail)
    return result


def project(profile: dict, *, smoke: bool = False):
    """Yield (cycle, src, class=0, dst, flits) under explicit ring assumptions."""
    ops = {(op["phase"], op["operation"]): op
           for op in profile["operations"]}
    cycle = 0
    sent = 0
    prefill_ops = 1 if smoke else ops[("prefill", "all_reduce")]["count"]
    decode_ops = 65 if smoke else ops[("decode", "all_reduce")]["count"]
    prefill_gathers = 1 if smoke else ops[("prefill", "gather")]["count"]
    decode_gathers = 1 if smoke else ops[("decode", "gather")]["count"]

    def ring_collective(payload_bytes: int):
        nonlocal cycle, sent
        # Ring reduce-scatter + all-gather: 2*(P-1) rounds. Each rank sends
        # one quarter of its per-rank payload to its clockwise neighbor/round.
        message = payload_bytes // WORLD
        if message * WORLD != payload_bytes:
            raise ValueError("all-reduce payload must divide across 4 ranks")
        sizes = packet_sizes(message)
        for _round in range(2 * (WORLD - 1)):
            for src in range(WORLD):
                dst = (src + 1) % WORLD
                for i, flits in enumerate(sizes):
                    yield (cycle + i * PACKET_GAP_CYCLES, src, 0, dst, flits)
                    sent += 1
            cycle += (len(sizes) * PACKET_GAP_CYCLES
                      + ROUND_BARRIER_GAP_CYCLES)

    def gather(payload_bytes: int):
        nonlocal cycle, sent
        sizes = packet_sizes(payload_bytes)
        # Projection assumption: ranks 1..3 gather directly to root rank 0.
        for src in range(1, WORLD):
            for i, flits in enumerate(sizes):
                yield (cycle + i * PACKET_GAP_CYCLES, src, 0, 0, flits)
                sent += 1
        cycle += len(sizes) * PACKET_GAP_CYCLES + ROUND_BARRIER_GAP_CYCLES

    prefill = ops[("prefill", "all_reduce")]
    prefill_gather = ops[("prefill", "gather")]
    decode = ops[("decode", "all_reduce")]
    decode_gather = ops[("decode", "gather")]
    if not smoke and decode["count"] != 65 * decode_gather["count"]:
        raise ValueError("decode AllReduce count must reconcile as 65 calls/token")

    for _ in range(prefill_ops):
        yield from ring_collective(prefill["payload_bytes_per_rank_per_call"])
    for _ in range(prefill_gathers):
        yield from gather(prefill_gather["payload_bytes_per_rank_per_call"])

    # The paper's 8,255 decode AllReduces = 65 per 127 generated tokens.
    # Preserve the measured operation counts; the order within each token is
    # projected as 65 sequential AllReduces followed by one Gather.
    for token in range(decode_ops // 65):
        for _ in range(65):
            yield from ring_collective(decode["payload_bytes_per_rank_per_call"])
        if token < decode_gathers:
            yield from gather(decode_gather["payload_bytes_per_rank_per_call"])

    if sent == 0:
        raise ValueError("projection emitted no packets")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--out", type=Path, required=True,
                    help="output `cyc src cl dst sz` trace path")
    ap.add_argument("--smoke", action="store_true",
                    help="project one prefill and one full 65-collective decode token")
    args = ap.parse_args()
    profile = json.loads(PROFILE.read_text())
    args.out.parent.mkdir(parents=True, exist_ok=True)
    count = 0
    max_cycle = 0
    with args.out.open("w") as f:
        f.write("# PROJECTED, NOT OBSERVED PACKETS; see adjacent README.md\n")
        f.write("# source=arXiv:2507.14392 Table III/IV; algorithm=ring\n")
        f.write("# assumptions: 4 ranks, clockwise ring, 256-bit flits, max 16 flits,\n")
        f.write("# one packet/source/cycle, 32-cycle ring-round barrier, no compute gaps\n")
        for row in project(profile, smoke=args.smoke):
            f.write("%d %d %d %d %d\n" % row)
            count += 1
            max_cycle = max(max_cycle, row[0])
    print(f"projection packets={count} max_cycle={max_cycle} output={args.out}")
    expected = 19_284 if args.smoke else 1_639_584
    if count != expected:
        raise SystemExit(f"projection count drifted: expected {expected}, got {count}")


if __name__ == "__main__":
    main()
