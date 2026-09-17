#!/usr/bin/env python3
"""chakra_to_dse.py — Convert LLMServingSim text traces into DSE trace format.

Reads per-batch trace files from LLMServingSim's trace generator
(instance0_batch0.txt, instance1_batch0.txt) and emits time-stamped DSE
traces (cyc src cl dst sz) suitable for:
  - BookSim matrix derivation (evaluator._trace_to_matrix)
  - RTL replay via noc_frontend (trace_n%d.hex)
  - Dynamic trace mode in recommend.py (--trace)

Collective decomposition into point-to-point:
  ALLREDUCE:1,0     → ring: rank[i] → rank[(i+1)%N]
  ALLGATHER:1,1     → ring: rank[i] → rank[(i+1)%N] (MoE dispatch within EP group)
  REDUCESCATTER:1,1 → ring: rank[i] → rank[(i-1)%N] (MoE reduce within EP group)
  ALLTOALL:0,1      → permuted: rank[i] → rank[(i+ep_size)%N] (cross-EP-group)
  DP_ALLREDUCE      → ring between DP group members (cross-instance sync)
  REMOTE:0          → excluded (KV-cache remote memory, <0.1%)

Class assignment:
  0 = ALLREDUCE (TP collective)
  1 = ALLGATHER/REDUCESCATTER/ALLTOALL (EP dispatch/reduce)
  2 = DP allreduce (cross-instance sync)
  3 = REMOTE (excluded)

Usage:
  python3 chakra_to_dse.py instance0_batch0.txt instance1_batch0.txt \
    --npu-map "0,4,8,12,16,20,24,28,32,36,40,44,48,52,56,60" \
    --ep-size 2 --dp-group "0,1" --speedup 100 --out trace.trace
"""
import argparse
import re
import sys
from pathlib import Path

# LLMServingSim trace line formats
LINE_RE = re.compile(
    r"^\s*(?P<name>\S+)\s+(?P<comp>\d+)\s+"
    r"(?P<in_loc>\S+)\s+(?P<in_size>\d+)\s+"
    r"(?P<w_loc>\S+)\s+(?P<w_size>\d+)\s+"
    r"(?P<out_loc>\S+)\s+(?P<out_size>\d+)\s+"
    r"(?P<comm>\S+)\s+(?P<comm_size>\d+)\s+(?P<misc>\S+)")
EXP_RE = re.compile(
    r"^\s*EXPERT\s+(?P<id>\d+)\s+(?P<comm>\S+)\s+(?P<size>\d+)")

# DSE flit size (64 bytes = 1 flit in the RTL)
FLIT_BYTES = 64
# Max flits per packet — realistic NoC packets are 8-16 flits (512B-1KB)
# Larger packets reduce header overhead but increase per-hop latency.
# 16 flits is the sweet spot: realistic and BookSim handles it in 30s.
MAX_FLITS_PER_PKT = 16


def parse_trace(path):
    """Parse LLMServingSim text trace into a list of ops."""
    ops = []
    with open(path) as f:
        for line in f:
            m = EXP_RE.match(line)
            if m:
                comm = m.group("comm")
                size = int(m.group("size"))
                if comm != "NONE" and size > 0:
                    # Parse ALLTOALL:0,1 → comm_type="ALLTOALL", involved_dim=[False,True]
                    base_comm = comm.split(":")[0] if ":" in comm else comm
                    ops.append({
                        "name": f"expert_{m.group('id')}",
                        "comp_us": 0,
                        "comm_type": base_comm,
                        "comm_bytes": size,
                        "comm_size_str": comm,
                    })
                continue
            m = LINE_RE.match(line)
            if m:
                comp = int(m.group("comp"))
                comm = m.group("comm")
                comm_size = int(m.group("comm_size"))
                if comm != "NONE" and comm_size > 0:
                    base_comm = comm.split(":")[0] if ":" in comm else comm
                    ops.append({
                        "name": m.group("name"),
                        "comp_us": comp,
                        "comm_type": base_comm,
                        "comm_bytes": comm_size,
                        "comm_size_str": comm,
                    })
                elif comp > 0:
                    ops.append({
                        "name": m.group("name"),
                        "comp_us": comp,
                        "comm_type": "NONE",
                        "comm_bytes": 0,
                        "comm_size_str": "NONE",
                    })
    return ops


def _tree_steps(n_ranks):
    """Generate binary tree communication pairs for O(log N) steps.
    Returns list of (step, sender, receiver) for each tree step.
    """
    steps = []
    step = 0
    stride = 1
    while stride < n_ranks:
        for i in range(n_ranks):
            if (i // stride) % 2 == 0:
                partner = i + stride
                if partner < n_ranks:
                    steps.append((step, i, partner))
        step += 1
        stride *= 2
    return steps


def _butterfly_steps(n_ranks):
    """Generate butterfly alltoall pairs for O(log N) steps.
    Returns list of (step, sender, receiver) for each butterfly step.
    """
    steps = []
    step = 0
    stride = 1
    while stride < n_ranks:
        for i in range(n_ranks):
            partner = i ^ stride  # XOR for butterfly
            if partner > i:  # avoid duplicates
                steps.append((step, i, partner))
        step += 1
        stride *= 2
    return steps


def generate_dse_trace(ops, npu_map, speedup=100, base_cycle=10,
                       ep_size=1, dp_instances=None, collective="ring",
                       pkt_flits_override=None):
    """Generate DSE trace entries from parsed ops.

    Args:
        ops: list of parsed ops from parse_trace()
        npu_map: list of node IDs for ranks
        speedup: computation time divider
        base_cycle: starting cycle offset
        ep_size: expert parallel size (for ALLTOALL decomposition)
        dp_instances: list of instance IDs in DP group (for cross-instance sync)
        collective: "ring", "star", "tree", or "butterfly"
        pkt_flits_override: if set, override packet flit count

    Returns:
        list of (cycle, src, class, dst, size_flits) tuples
    """
    entries = []
    cycle = base_cycle
    n_ranks = len(npu_map)

    for op in ops:
        # Advance cycle by computation time
        cycle += max(1, op["comp_us"] // speedup)

        comm = op["comm_type"]
        nbytes = op["comm_bytes"]
        if nbytes == 0 or comm == "NONE":
            continue

        # Convert bytes to flits, then split into packets
        # pkt_flits is the actual flit count per packet
        # n_pkts is how many packets we need to transfer all the data
        size_flits = max(1, (nbytes + FLIT_BYTES - 1) // FLIT_BYTES)
        pkt_flits = pkt_flits_override if pkt_flits_override else min(size_flits, MAX_FLITS_PER_PKT)
        n_pkts = max(1, (size_flits + pkt_flits - 1) // pkt_flits)
        # Conservation: every packet carries full pkt_flits EXCEPT the
        # last, which carries the remainder — total emitted flits ==
        # size_flits exactly (no fabricated bytes for non-multiples).
        _pkt_sizes = [pkt_flits] * n_pkts
        _pkt_sizes[-1] = size_flits - pkt_flits * (n_pkts - 1)

        if comm == "ALLREDUCE":
            if collective == "star":
                # Star: rank 0 sends to all, all send to rank 0
                root = npu_map[0]
                for p in range(n_pkts):
                    for i in range(1, n_ranks):
                        c = cycle + p * n_ranks + i
                        entries.append((c, root, 0, npu_map[i], _pkt_sizes[p]))
                        entries.append((c + n_ranks, npu_map[i], 0, root, _pkt_sizes[p]))
            elif collective == "tree":
                # Tree: O(log N) steps, each rank sends to partner
                tree = _tree_steps(n_ranks)
                for p in range(n_pkts):
                    for step, sender, receiver in tree:
                        c = cycle + p * len(tree) * 2 + step * 2
                        entries.append((c, npu_map[sender], 0, npu_map[receiver], _pkt_sizes[p]))
                        entries.append((c + 1, npu_map[receiver], 0, npu_map[sender], _pkt_sizes[p]))
            elif collective == "butterfly":
                # Butterfly: O(log N) steps, XOR-based pairs
                bf = _butterfly_steps(n_ranks)
                for p in range(n_pkts):
                    for step, sender, receiver in bf:
                        c = cycle + p * len(bf) * 2 + step * 2
                        entries.append((c, npu_map[sender], 0, npu_map[receiver], _pkt_sizes[p]))
                        entries.append((c + 1, npu_map[receiver], 0, npu_map[sender], _pkt_sizes[p]))
            else:  # ring
                for p in range(n_pkts):
                    for i in range(n_ranks):
                        c = cycle + p * n_ranks + i
                        entries.append((c, npu_map[i], 0, npu_map[(i + 1) % n_ranks], _pkt_sizes[p]))

        elif comm == "ALLGATHER":
            if collective == "star":
                root = npu_map[0]
                for p in range(n_pkts):
                    for i in range(1, n_ranks):
                        c = cycle + p * n_ranks + i
                        entries.append((c, root, 1, npu_map[i], _pkt_sizes[p]))
            elif collective == "tree":
                tree = _tree_steps(n_ranks)
                for p in range(n_pkts):
                    for step, sender, receiver in tree:
                        c = cycle + p * len(tree) + step
                        entries.append((c, npu_map[sender], 1, npu_map[receiver], _pkt_sizes[p]))
            elif collective == "butterfly":
                bf = _butterfly_steps(n_ranks)
                for p in range(n_pkts):
                    for step, sender, receiver in bf:
                        c = cycle + p * len(bf) + step
                        entries.append((c, npu_map[sender], 1, npu_map[receiver], _pkt_sizes[p]))
                        entries.append((c, npu_map[receiver], 1, npu_map[sender], _pkt_sizes[p]))
            else:  # ring
                for p in range(n_pkts):
                    for i in range(n_ranks):
                        c = cycle + p * n_ranks + i
                        entries.append((c, npu_map[i], 1, npu_map[(i + 1) % n_ranks], _pkt_sizes[p]))

        elif comm == "REDUCESCATTER":
            if collective == "star":
                root = npu_map[0]
                for p in range(n_pkts):
                    for i in range(1, n_ranks):
                        c = cycle + p * n_ranks + i
                        entries.append((c, npu_map[i], 1, root, _pkt_sizes[p]))
            elif collective == "tree":
                tree = _tree_steps(n_ranks)
                for p in range(n_pkts):
                    for step, sender, receiver in reversed(tree):
                        c = cycle + p * len(tree) + (len(tree) - 1 - step)
                        entries.append((c, npu_map[sender], 1, npu_map[receiver], _pkt_sizes[p]))
            elif collective == "butterfly":
                bf = _butterfly_steps(n_ranks)
                for p in range(n_pkts):
                    for step, sender, receiver in reversed(bf):
                        c = cycle + p * len(bf) + (len(bf) - 1 - step)
                        entries.append((c, npu_map[sender], 1, npu_map[receiver], _pkt_sizes[p]))
                        entries.append((c, npu_map[receiver], 1, npu_map[sender], _pkt_sizes[p]))
            else:  # ring
                for p in range(n_pkts):
                    for i in range(n_ranks):
                        c = cycle + p * n_ranks + i
                        entries.append((c, npu_map[i], 1, npu_map[(i - 1) % n_ranks], _pkt_sizes[p]))

        elif comm == "ALLTOALL":
            if collective == "butterfly":
                bf = _butterfly_steps(n_ranks)
                for p in range(n_pkts):
                    for step, sender, receiver in bf:
                        c = cycle + p * len(bf) + step
                        entries.append((c, npu_map[sender], 1, npu_map[receiver], _pkt_sizes[p]))
                        entries.append((c, npu_map[receiver], 1, npu_map[sender], _pkt_sizes[p]))
            else:  # ring permutation
                for p in range(n_pkts):
                    for i in range(n_ranks):
                        c = cycle + p * n_ranks + i
                        ep_group_start = (i // ep_size) * ep_size
                        dst_rank = ep_group_start + ((i - ep_group_start + 1) % ep_size)
                        entries.append((c, npu_map[i], 1, npu_map[dst_rank], _pkt_sizes[p]))

        elif comm == "REMOTE":
            # KV-cache remote memory — excluded
            pass

        else:
            pass

    return entries


def generate_dp_allreduce(dp_traces, npu_map_all, dp_cycle_offset=0):
    """Generate DP allreduce entries between instances in the same DP group.

    Each instance computes independently, then syncs via ring allreduce.
    The DP allreduce happens AFTER all per-instance ops complete.

    Args:
        dp_traces: list of (ops, npu_map) tuples for each instance
        npu_map_all: combined node map for all instances
        dp_cycle_offset: cycle offset for DP sync

    Returns:
        list of (cycle, src, class, dst, size_flits) tuples
    """
    entries = []
    n_instances = len(dp_traces)

    if n_instances < 2:
        return entries

    # Find the max cycle across all instances
    max_cycle = 0
    for ops, npu_map in dp_traces:
        cycle = 10
        for op in ops:
            cycle += max(1, op["comp_us"] // 100)
        if cycle > max_cycle:
            max_cycle = cycle

    # DP allreduce: ring between instance heads
    # Instance 0 rank 0 ↔ Instance 1 rank 0 ↔ ...
    dp_cycle = max_cycle + dp_cycle_offset
    dp_npkts = 4  # 4 packets for DP sync (model gradient)

    for p in range(dp_npkts):
        for i in range(n_instances):
            src_instance = dp_traces[i][1][0]  # First rank of instance i
            dst_instance = dp_traces[(i + 1) % n_instances][1][0]
            c = dp_cycle + p * n_instances + i
            entries.append((c, src_instance, 2, dst_instance, 64))  # 64 flits = 4KB gradient

    return entries


def write_dse_trace(entries, out_path):
    """Write DSE trace in (cyc src cl dst sz) format."""
    with open(out_path, "w") as f:
        for cyc, src, cl, dst, sz in entries:
            f.write(f"{cyc} {src} {cl} {dst} {sz}\n")


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("traces", nargs="+", help="LLMServingSim text trace(s)")
    ap.add_argument("--npu-map", default="0,4,8,12,16,20,24,28,32,36,40,44,48,52,56,60",
                    help="Comma-separated node IDs for ranks (default: 16 ranks)")
    ap.add_argument("--speedup", type=int, default=100,
                    help="Computation time divider (default: 100)")
    ap.add_argument("--ep-size", type=int, default=2,
                    help="Expert parallel size for ALLTOALL decomposition (default: 2)")
    ap.add_argument("--collective", default="ring", choices=["ring", "star", "tree", "butterfly"],
                    help="Collective algorithm (default: ring)")
    ap.add_argument("--pkt-flits", type=int, default=None,
                    help="Override packet size in flits (default: auto from trace)")
    ap.add_argument("--dp-instances", default=None,
                    help="Comma-separated instance indices in DP group (e.g. '0,1')")
    ap.add_argument("--out", default=None,
                    help="Output path (default: <trace>.dse.txt)")
    ap.add_argument("--stats", action="store_true",
                    help="Print per-class statistics")
    args = ap.parse_args()

    npu_map = [int(x) for x in args.npu_map.split(",")]

    # Parse DP group
    dp_instances = None
    if args.dp_instances:
        dp_instances = [int(x) for x in args.dp_instances.split(",")]

    all_entries = []
    all_ops = []

    # Process each trace file
    for i, trace_path in enumerate(args.traces):
        trace = Path(trace_path)
        if not trace.exists():
            print(f"Warning: {trace} not found, skipping", file=sys.stderr)
            continue

        # Each instance gets its own slice of the npu_map
        instance_npus = npu_map[i::len(args.traces)] if len(args.traces) > 1 else npu_map

        ops = parse_trace(trace)
        all_ops.extend(ops)

        entries = generate_dse_trace(ops, instance_npus,
                                     speedup=args.speedup,
                                     ep_size=args.ep_size,
                                     collective=args.collective,
                                     pkt_flits_override=args.pkt_flits)
        all_entries.extend(entries)

    # Add DP allreduce if multiple instances
    if dp_instances and len(args.traces) > 1:
        dp_traces = []
        for i in dp_instances:
            trace = Path(args.traces[i])
            instance_npus = npu_map[i::len(args.traces)]
            ops = parse_trace(trace)
            dp_traces.append((ops, instance_npus))

        dp_entries = generate_dp_allreduce(dp_traces, npu_map)
        all_entries.extend(dp_entries)

    # Sort by cycle
    all_entries.sort(key=lambda x: x[0])

    # Write output
    out = Path(args.out) if args.out else Path(args.traces[0]).with_suffix(".trace")
    write_dse_trace(all_entries, out)

    # Stats
    n_allreduce = sum(1 for _, _, cl, _, _ in all_entries if cl == 0)
    n_ep = sum(1 for _, _, cl, _, _ in all_entries if cl == 1)
    n_dp = sum(1 for _, _, cl, _, _ in all_entries if cl == 2)
    total_bytes = sum(sz * FLIT_BYTES for _, _, _, _, sz in all_entries)
    max_cycle = max((c for c, _, _, _, _ in all_entries), default=0)
    n_nodes = max((max(s, d) for _, s, _, d, _ in all_entries), default=0) + 1

    print(f"chakra_to_dse: {len(all_entries)} packets, {len(all_ops)} ops parsed")
    print(f"  ALLREDUCE (TP):  {n_allreduce} pkts")
    print(f"  EP dispatch:     {n_ep} pkts (ALLGATHER/REDUCESCATTER/ALLTOALL)")
    print(f"  DP allreduce:    {n_dp} pkts")
    print(f"  total bytes:     {total_bytes:,} ({total_bytes // 1024} KB)")
    print(f"  max cycle:       {max_cycle}, nodes used: {n_nodes}")
    print(f"  output:          {out}")

    if args.stats:
        print(f"\n  Per-op breakdown:")
        for op in all_ops:
            if op["comm_type"] != "NONE" and op["comm_bytes"] > 0:
                print(f"    {op['name']:30s} {op['comm_type']:20s} {op['comm_bytes']:>12,} bytes")


if __name__ == "__main__":
    main()
