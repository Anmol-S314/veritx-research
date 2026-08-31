#!/usr/bin/env python3
"""model_to_trace.py — Convert unified TrafficModel to BookSim trace format.

Generates a {cyc src cl dst sz} trace file from traffic_model.json flow classes.
Each collective operation is decomposed into point-to-point packets scheduled
at realistic injection cycles based on the traffic model's constraints.

Usage:
    python3 model_to_trace.py \\
        --traffic-model models/traffic_model.json \\
        --nodes 64 \\
        --out inputs/traffic_model.trace \\
        [--ipc 0.5]  # injections per cycle per node (controls timing)
"""
import argparse
import json
import math
import sys
from pathlib import Path


# ── Collective decomposition ──────────────────────────────────────────

def ring_allreduce_packets(participants, total_bytes, cl=0, base_cycle=0, ipc=0.5, pkt_flits=4, accurate=False):
    """Decompose ring allreduce into point-to-point packets.

    Ring allreduce: 2(k-1) steps.
    Each step: every participant sends ONE message to next in ring.
    One packet per (step, sender) — matches real trace patterns.

    If accurate=True, scale pkt_flits by total_bytes to match real volumes
    (1 packet per step, packet size = bytes_per_step / 64B_per_flit).
    """
    k = len(participants)
    if k < 2:
        return []
    packets = []
    n_ring_steps = 2 * (k - 1)
    bytes_per_step = total_bytes / k if k > 0 else 0
    if accurate:
        pkt_flits = max(4, int(math.ceil(bytes_per_step / 64)))
    for step in range(n_ring_steps):
        for i, src in enumerate(participants):
            dst = participants[(i + 1) % k]
            cycle = base_cycle + (step * k + i) / ipc
            packets.append((int(cycle), src, cl, dst, pkt_flits))
    return packets


def ring_allgather_packets(participants, total_bytes, cl=0, base_cycle=0, ipc=0.5, pkt_flits=4, accurate=False):
    """Decompose ring allgather into point-to-point packets."""
    k = len(participants)
    if k < 2:
        return []
    packets = []
    bytes_per_step = total_bytes / k if k > 0 else 0
    if accurate:
        pkt_flits = max(4, int(math.ceil(bytes_per_step / 64)))
    for step in range(k - 1):
        for i, src in enumerate(participants):
            dst = participants[(i + 1) % k]
            cycle = base_cycle + (step * k + i) / ipc
            packets.append((int(cycle), src, cl, dst, pkt_flits))
    return packets


def ring_reducescatter_packets(participants, total_bytes, cl=0, base_cycle=0, ipc=0.5, pkt_flits=4, accurate=False):
    """Decompose ring reduce-scatter into point-to-point packets."""
    k = len(participants)
    if k < 2:
        return []
    packets = []
    bytes_per_step = total_bytes / k if k > 0 else 0
    if accurate:
        pkt_flits = max(4, int(math.ceil(bytes_per_step / 64)))
    for step in range(k - 1):
        for i, src in enumerate(participants):
            dst = participants[(i + 1) % k]
            cycle = base_cycle + (step * k + i) / ipc
            packets.append((int(cycle), src, cl, dst, pkt_flits))
    return packets


def alltoall_packets(participants, total_bytes, cl=0, base_cycle=0, ipc=0.5, pkt_flits=4, accurate=False):
    """Decompose all-to-all into point-to-point packets."""
    k = len(participants)
    if k < 2:
        return []
    packets = []
    n_pairs = k * (k - 1)
    bytes_per_pair = total_bytes / n_pairs if n_pairs > 0 else 0
    if accurate:
        pkt_flits = max(4, int(math.ceil(bytes_per_pair / 64)))
    for i, src in enumerate(participants):
        for j, dst in enumerate(participants):
            if i != j:
                cycle = base_cycle + (i * (k-1) + j) / ipc
                packets.append((int(cycle), src, cl, dst, pkt_flits))
    return packets


COLLECTIVE_DECOMPOSERS = {
    "allreduce": ring_allreduce_packets,
    "ALLREDUCE": ring_allreduce_packets,
    "allgather": ring_allgather_packets,
    "ALLGATHER": ring_allgather_packets,
    "reducescatter": ring_reducescatter_packets,
    "REDUCESCATTER": ring_reducescatter_packets,
    "alltoall": alltoall_packets,
    "ALLTOALL": alltoall_packets,
}


# ── Main converter ────────────────────────────────────────────────────

def model_to_trace(traffic_model, n_nodes, ipc=0.5, accurate=False):
    """Convert traffic model to trace packets.

    Returns list of (cyc, src, cl, dst, sz) tuples.
    If accurate=True, scale packet counts by bytes_per_invocation.
    """
    flow_classes = traffic_model["network"]["flow_classes"]
    all_packets = []
    cycle_offset = 0

    for cl_idx, fc in enumerate(flow_classes):
        comm_type = fc["comm_type"]
        bytes_per_inv = fc["bytes_per_invocation"]
        invocations = fc.get("invocations_per_batch", 1)
        instances = fc.get("instances", [])

        decomposer = COLLECTIVE_DECOMPOSERS.get(comm_type)
        if decomposer is None:
            print(f"WARNING: unknown comm_type '{comm_type}', skipping", file=sys.stderr)
            continue

        for inv in range(int(invocations)):
            for inst_idx, inst in enumerate(instances):
                participants = inst.get("participants", [])
                # Filter to valid node IDs
                participants = [p for p in participants if 0 <= p < n_nodes]
                if len(participants) < 2:
                    continue

                packets = decomposer(
                    participants, bytes_per_inv,
                    cl=cl_idx, base_cycle=cycle_offset, ipc=ipc,
                    accurate=accurate,
                )
                all_packets.extend(packets)

            # Advance cycle offset for next invocation
            cycle_offset += int(100 / ipc)

    # Sort by cycle and map all classes to class 0 (BookSim default)
    all_packets.sort(key=lambda p: (p[0], p[1]))
    all_packets = [(c, s, 0, d, sz) for c, s, cl, d, sz in all_packets]
    return all_packets


def write_trace(packets, outpath):
    """Write trace file in {cyc src cl dst sz} format."""
    with open(outpath, "w") as f:
        f.write(f"# Generated from traffic model: {len(packets)} packets\n")
        for cyc, src, cl, dst, sz in packets:
            f.write(f"{cyc} {src} {cl} {dst} {sz}\n")
    return len(packets)


# ── CLI ───────────────────────────────────────────────────────────────

def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--traffic-model", required=True,
                    help="Path to unified TrafficModel JSON")
    ap.add_argument("--nodes", type=int, default=64,
                    help="Number of nodes in the network (default: 64)")
    ap.add_argument("--out", required=True,
                    help="Output trace file path")
    ap.add_argument("--ipc", type=float, default=0.5,
                    help="Injections per cycle per node (default: 0.5)")
    ap.add_argument("--accurate-volumes", action="store_true",
                    help="Scale packet count by bytes_per_invocation (default: pattern-only, 1 pkt/step)")
    args = ap.parse_args()

    with open(args.traffic_model) as f:
        traffic_model = json.load(f)

    n_packets = 0
    flow_classes = traffic_model["network"]["flow_classes"]
    print(f"Traffic model: {len(flow_classes)} flow classes, {args.nodes} nodes")

    for fc in flow_classes:
        instances = fc.get("instances", [])
        invocations = int(fc.get("invocations_per_batch", 1))
        total_instances = len(instances) * invocations
        print(f"  {fc['name']}: {fc['comm_type']}, {total_instances} invocations, "
              f"{fc['bytes_per_invocation']} bytes")

    packets = model_to_trace(traffic_model, args.nodes, args.ipc, accurate=args.accurate_volumes)
    n = write_trace(packets, args.out)

    # Stats
    cycles = packets[-1][0] - packets[0][0] if packets else 0
    nodes_used = len(set(p[1] for p in packets))
    print(f"\nGenerated {n} packets over {cycles} cycles, {nodes_used} nodes used")
    print(f"Trace written: {args.out}")

    # Estimate injection rate
    if cycles > 0 and args.nodes > 0:
        ir = n / (cycles * args.nodes)
        print(f"Estimated IR: {ir:.4f} packets/node/cycle")

    return 0


if __name__ == "__main__":
    sys.exit(main())
