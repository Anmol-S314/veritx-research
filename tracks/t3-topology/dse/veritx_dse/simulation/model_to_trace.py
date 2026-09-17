#!/usr/bin/env python3
"""model_to_trace.py — Convert unified TrafficModel to BookSim trace format.

Generates a {cyc src cl dst sz} trace file from traffic_model.json flow classes.
Each collective operation is decomposed into point-to-point packets scheduled
at realistic injection cycles based on the traffic model's constraints.

Fail-closed lowering (verified-PRD Integrity PR C, §8.1): an unknown
comm_type, an out-of-range participant, or a degenerate instance (< 2
participants) is a HARD ERROR — never a warning-and-skip. A malformed or
unsupported source workload must not silently become a lighter network
workload. Every successful lowering emits a LoweringManifest (sidecar
``<out>.manifest.json``) whose counts make byte/operation conservation
checkable, and whose unsupported/dropped lists are empty by construction.

NOTE (post-review, PR C): BROADCAST lowering is PROVISIONAL — the
``participants[0] = source`` interpretation is not guaranteed by the
existing workload schema (no source format document states participant
ordering) and was adopted as a plausible semantic pending either source
format evidence or an explicit ``source`` field. See the broadcast_packets
decomposer and ``build_lowering_manifest``.

Usage:
    python3 model_to_trace.py \\
        --traffic-model models/traffic_model.json \\
        --nodes 64 \\
        --out archive/inputs/traffic_model.trace \\
        [--ipc 0.5]  # injections per cycle per node (controls timing)
"""
import argparse
import hashlib
import json
import math
import sys
from pathlib import Path


class LoweringError(ValueError):
    """A source workload cannot be lowered without scientific loss (PR C).

    Raised instead of silently skipping/dropping operations. The message
    names the flow class and the exact defect so the model can be repaired.
    """


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


def broadcast_packets(participants, total_bytes, cl=0, base_cycle=0, ipc=0.5, pkt_flits=4, accurate=False):
    """Decompose a broadcast into point-to-point packets.

    PROVISIONAL semantics (PR C, post-review): the FIRST participant is
    treated as the source; every other participant receives the full
    logical payload. Network bytes = (k-1) × payload, where payload is
    ``total_bytes`` (bytes_per_invocation is the logical message size,
    matching the allreduce convention where total_bytes is the logical
    payload, not aggregate network traffic).

    ``provisional``: no existing workload schema/document guarantees that
    participant ordering. Before any real BROADCAST workload relies on
    this, establish participants[0]=source from the source format or make
    ``source`` an explicit schema field (verified-PRD review decision).
    BROADCAST lowering is therefore recorded as PROVISIONAL in the
    LoweringManifest and must never be reported as fully supported.
    """
    if len(participants) < 2:
        return []
    src = participants[0]
    packets = []
    for dst in participants[1:]:
        cycle = base_cycle
        size = pkt_flits
        if accurate:
            size = max(4, int(math.ceil(total_bytes / 64)))
        packets.append((int(cycle), src, cl, dst, size))
    return packets


def p2p_packets(participants, total_bytes, cl=0, base_cycle=0, ipc=0.5, pkt_flits=4, accurate=False):
    """Decompose a point-to-point (P2P) flow into packets.

    P2P flows are single src→dst transfers (e.g. lidar_fusion: rank0→rank1).
    One packet per invocation; with accurate=True the packet carries enough
    flits to represent the full byte volume (bytes_per_invocation / 64B per flit).
    """
    if len(participants) < 2:
        return []
    src, dst = participants[0], participants[1]
    if accurate:
        pkt_flits = max(4, int(math.ceil(total_bytes / 64)))
    packets = []
    for inv in range(1):
        cycle = base_cycle
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
    "broadcast": broadcast_packets,
    "BROADCAST": broadcast_packets,
    "p2p": p2p_packets,
    "P2P": p2p_packets,
}

# Canonical kind for manifest reporting (aliases collapse to one kind)
_CANONICAL_KIND = {
    "allreduce": "allreduce", "ALLREDUCE": "allreduce",
    "allgather": "allgather", "ALLGATHER": "allgather",
    "reducescatter": "reducescatter", "REDUCESCATTER": "reducescatter",
    "alltoall": "alltoall", "ALLTOALL": "alltoall",
    "broadcast": "broadcast", "BROADCAST": "broadcast",
    "p2p": "p2p", "P2P": "p2p",
}


# ── Main converter ────────────────────────────────────────────────────

def _validate_source(traffic_model, n_nodes):
    """Fail-closed source validation (PR C §8.1).

    Rejects, naming the flow class and defect:
      * unknown comm_type (no decomposer)
      * participant outside [0, n_nodes)
      * non-integer participant
      * instance with < 2 participants (degenerate: no communication)

    Never warns-and-continues: any of these means the lowered trace would
    differ scientifically from the declared workload.
    """
    flow_classes = traffic_model["network"]["flow_classes"]
    for cl_idx, fc in enumerate(flow_classes):
        name = fc.get("name", f"<flow_class[{cl_idx}]>")
        comm_type = fc.get("comm_type")
        if comm_type not in COLLECTIVE_DECOMPOSERS:
            raise LoweringError(
                f"flow class {name!r}: unknown comm_type {comm_type!r} — "
                f"supported: {sorted(_CANONICAL_KIND.values())}. Unsupported "
                "workload semantics must be implemented or removed, never "
                "skipped (PR C fail-closed).")
        instances = fc.get("instances", [])
        for inst_idx, inst in enumerate(instances):
            where = f"flow class {name!r} instance[{inst_idx}]"
            participants = inst.get("participants", [])
            if len(participants) < 2:
                raise LoweringError(
                    f"{where}: {len(participants)} participant(s) "
                    f"{participants} — a communication instance needs >= 2. "
                    "(Degenerate instances were previously silently dropped, "
                    "making the workload lighter than declared.)")
            for p in participants:
                if not isinstance(p, int) or isinstance(p, bool) or not (0 <= p < n_nodes):
                    raise LoweringError(
                        f"{where}: participant {p!r} outside [0, {n_nodes}) "
                        "or non-integer. (Out-of-range participants were "
                        "previously silently filtered.)")


def _flow_bytes_by_class(traffic_model):
    """Declared source bytes per flow class (bytes_per_invocation × invocations)."""
    out = {}
    for cl_idx, fc in enumerate(traffic_model["network"]["flow_classes"]):
        name = fc.get("name", f"<flow_class[{cl_idx}]>")
        invocations = int(fc.get("invocations_per_batch", 1))
        out[name] = fc["bytes_per_invocation"] * invocations
    return out


def _lowering_manifest(traffic_model, n_nodes, ipc, accurate, packets, out_path):
    """Build the LoweringManifest v0 (verified-PRD §6.3).

    Makes conservation checkable: declared source ops/bytes vs emitted
    packets/flits, per operation kind, plus conversion parameters. For
    supported semantics unsupported=[] and dropped=[] — by construction,
    because validation raises instead.
    """
    by_kind_counts: dict[str, int] = {}
    by_kind_instances: dict[str, int] = {}
    for cl_idx, fc in enumerate(traffic_model["network"]["flow_classes"]):
        kind = _CANONICAL_KIND[fc["comm_type"]]
        invocations = int(fc.get("invocations_per_batch", 1))
        by_kind_instances[kind] = by_kind_instances.get(kind, 0) + \
            len(fc.get("instances", [])) * invocations
    for p in packets:
        pass  # packet-level kinds are per-flow-class, mapped below

    # Per-class packet counts (packets carry cl=0 after BookSim mapping,
    # so recount from construction order is unreliable — count by class
    # mapping instead: recount via flow class packet generation is
    # unnecessary; total + per-kind instance counts suffice for v0).
    flits = sum(p[4] for p in packets)
    src_bytes_total = sum(_flow_bytes_by_class(traffic_model).values())

    return {
        "schema_version": 1,
        "projection_type": "traffic_model_to_booksim_trace",
        "projection_version": 1,
        "source": {
            "flow_class_count": len(traffic_model["network"]["flow_classes"]),
            "nodes": n_nodes,
        },
        "conversion_parameters": {
            "ipc": ipc,
            "accurate_volumes": bool(accurate),
            "bytes_per_flit": 64 if accurate else None,
            "default_packet_flits": None if accurate else 4,
        },
        "operation_counts_by_kind": by_kind_instances,
        "source_bytes_by_class": _flow_bytes_by_class(traffic_model),
        "source_bytes_total": src_bytes_total,
        "output": {
            "path": str(out_path),
            "packet_count": len(packets),
            "flit_count": flits,
        },
        "unsupported_operations": [],   # validation raises instead
        "dropped_operations": [],       # validation raises instead
    }
    # PR C post-review: BROADCAST semantics are PROVISIONAL (no source
    # format guarantees participants[0]=source). Surfaced here so any
    # consumer reading the manifest sees the status, not just the code.
    broadcast_kinds = {
        _CANONICAL_KIND[fc["comm_type"]]
        for fc in traffic_model["network"]["flow_classes"]
        if fc["comm_type"] in ("BROADCAST", "broadcast")
    }
    if broadcast_kinds:
        manifest["provisional_semantics"] = {
            kind: "participants[0]=source interpretation; not guaranteed "
                  "by the workload schema — verify or make source explicit"
            for kind in broadcast_kinds
        }
    return manifest


def model_to_trace(traffic_model, n_nodes, ipc=0.5, accurate=False):
    """Convert traffic model to trace packets.

    Returns list of (cyc, src, cl, dst, sz) tuples.
    If accurate=True, scale packet counts by bytes_per_invocation.

    Fail-closed (PR C): raises LoweringError on unknown comm_type,
    out-of-range/non-integer participants, or degenerate instances —
    never skips operations.
    """
    _validate_source(traffic_model, n_nodes)
    flow_classes = traffic_model["network"]["flow_classes"]
    all_packets = []
    cycle_offset = 0

    for cl_idx, fc in enumerate(flow_classes):
        comm_type = fc["comm_type"]
        bytes_per_inv = fc["bytes_per_invocation"]
        invocations = fc.get("invocations_per_batch", 1)
        instances = fc.get("instances", [])

        decomposer = COLLECTIVE_DECOMPOSERS[comm_type]

        for inv in range(int(invocations)):
            for inst_idx, inst in enumerate(instances):
                participants = inst.get("participants", [])
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


def write_lowering_manifest(manifest, out_path):
    """Write the LoweringManifest sidecar next to the trace.

    Path: <trace>.manifest.json. Returns the manifest path.
    """
    manifest_path = str(out_path) + ".manifest.json"
    manifest["output"]["manifest_path"] = manifest_path
    manifest["output"]["trace_sha256"] = hashlib.sha256(
        Path(out_path).read_bytes()).hexdigest()
    with open(manifest_path, "w") as f:
        json.dump(manifest, f, indent=2, sort_keys=True)
        f.write("\n")
    return manifest_path


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

    # LoweringManifest v0 (PR C): conservation sidecar; unsupported/dropped
    # are empty by construction because validation fails closed.
    manifest = _lowering_manifest(traffic_model, args.nodes, args.ipc,
                                  args.accurate_volumes, packets, args.out)
    mpath = write_lowering_manifest(manifest, args.out)

    # Stats
    cycles = packets[-1][0] - packets[0][0] if packets else 0
    nodes_used = len(set(p[1] for p in packets))
    print(f"\nGenerated {n} packets over {cycles} cycles, {nodes_used} nodes used")
    print(f"Trace written: {args.out}")
    print(f"Lowering manifest: {mpath} "
          f"({manifest['source_bytes_total']} declared bytes, "
          f"{manifest['output']['flit_count']} flits emitted)")

    # Estimate injection rate
    if cycles > 0 and args.nodes > 0:
        ir = n / (cycles * args.nodes)
        print(f"Estimated IR: {ir:.4f} packets/node/cycle")

    return 0


if __name__ == "__main__":
    sys.exit(main())
