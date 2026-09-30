#!/usr/bin/env python3
"""
qos_depth.py — Deep QoS model with per-class VCs, weighted arbitration,
and reorder-buffer model.

Extends qos_model.py with:
  - Per-class VC allocation (GS/BE/scavenger)
  - Weighted round-robin arbitration at output
  - Reorder buffer modeling (packet reordering due to adaptive routing)
  - Worst-case latency bound computation per flow class

Usage:
  python qos_depth.py --anynet .noc_p0/custom_v2.anynet --ir 0.08
"""

import argparse
import json
import math
from collections import defaultdict
from pathlib import Path

class PerClassVCAllocator:
    """Allocate VCs to traffic classes with strict priority."""

    def __init__(self, total_vcs: int, class_config: dict = None):
        self.total_vcs = total_vcs
        self.class_config = class_config or {
            "gs":   {"vcs": max(1, total_vcs // 2), "priority": 2, "weight": 0.5},
            "be":   {"vcs": max(1, total_vcs // 2), "priority": 1, "weight": 0.35},
            "scav": {"vcs": max(1, total_vcs // 4), "priority": 0, "weight": 0.15},
        }

    def allocate(self, traffic_class: str) -> int:
        """Return VC index for given class."""
        cfg = self.class_config.get(traffic_class, self.class_config["be"])
        return cfg["priority"]

    def get_vc_range(self, traffic_class: str) -> tuple:
        """Return (start, end) VC indices for this class."""
        cfg = self.class_config.get(traffic_class, self.class_config["be"])
        sorted_classes = sorted(self.class_config.items(),
                                key=lambda x: -x[1]["priority"])
        offset = 0
        for cls, c in sorted_classes:
            n_vcs = min(c["vcs"], self.total_vcs - offset)
            if cls == traffic_class:
                return (offset, offset + n_vcs)
            offset += n_vcs
        return (0, 1)

class WeightedRoundRobin:
    """Weighted round-robin arbiter for output port."""

    def __init__(self, weights: dict):
        self.weights = weights
        self.counter = defaultdict(int)
        self.grant = defaultdict(int)

    def arbitrate(self, requests: list) -> int:
        """
        requests: list of (class, packet_id) wanting this output port.
        Returns index into requests list of who gets granted.
        """
        if not requests:
            return -1

        total_weight = sum(self.weights.get(cls, 1.0) for cls, _ in requests)

        best_idx = 0
        best_score = -1.0
        for i, (cls, pid) in enumerate(requests):
            w = self.weights.get(cls, 1.0) / total_weight
            credit = self.counter[cls] / (w * sum(self.counter.values()) + 1e-9)
            score = 1.0 - credit
            if score > best_score:
                best_score = score
                best_idx = i

        granted_cls = requests[best_idx][0]
        self.counter[granted_cls] += 1
        self.grant[granted_cls] += 1
        return best_idx

class ReorderBuffer:
    """
    Model packet reordering due to adaptive routing.

    In a network with adaptive routing, packets from the same flow may take
    different paths and arrive out of order. The reorder buffer must hold
    packets until all predecessors arrive.

    Worst-case reordering = max_path_difference across all source-destination pairs.
    """

    def __init__(self, n_nodes: int):
        self.n_nodes = n_nodes

    def compute_reorder_bound(self, adj: dict, src: int, dst: int,
                              n_paths: int = 3) -> int:
        """
        Estimate worst-case reorder bound for a (src, dst) pair.

        Uses BFS to find the min and max path lengths over n_paths shortest paths.
        Reorder bound = max_path - min_path (packets on longer paths may overtake).
        """
        from collections import deque

        dist = {src: 0}
        queue = deque([src])
        while queue:
            node = queue.popleft()
            for nbr in adj.get(node, []):
                if nbr not in dist:
                    dist[nbr] = dist[node] + 1
                    queue.append(nbr)

        min_dist = dist.get(dst, self.n_nodes)

        path_counts = defaultdict(int)
        pq = [(0, src)]
        path_lengths = []

        while pq and len(path_lengths) < n_paths * 2:
            plen, node = pq.pop(0)
            if node == dst:
                path_lengths.append(plen)
                if len(path_lengths) >= n_paths * 2:
                    break
            for nbr in adj.get(node, []):
                new_len = plen + 1
                key = (nbr, new_len)
                if path_counts[key] < n_paths:
                    path_counts[key] += 1
                    pq.append((new_len, nbr))
                    pq.sort()

        if not path_lengths:
            return 0

        max_dist = max(path_lengths)
        return max(0, max_dist - min_dist)

def compute_qos_bounds(adj: dict, n_nodes: int, matrix: list,
                       ir: float = 0.08, n_vcs: int = 4,
                       buf_depth: int = 8) -> dict:
    """
    Compute per-class QoS bounds using deep model.

    Returns:
        {
            "per_flow": {flow: {class, wc_latency, reorder_bound, buffer_latency}},
            "per_class": {cls: {avg_latency, max_latency, max_reorder}},
            "admission": {gs_admitted, be_admitted, total_flows},
            "summary": str
        }
    """
    allocator = PerClassVCAllocator(n_vcs)
    reorder = ReorderBuffer(n_nodes)

    per_flow = {}
    per_class = defaultdict(list)
    per_class_rates = defaultdict(list)

    for src in range(n_nodes):
        for dst in range(n_nodes):
            if src == dst:
                continue
            rate = matrix[src][dst] if src < len(matrix) and dst < len(matrix[src]) else 0
            if rate < 1e-6:
                continue

            if rate > 0.05:
                cls = "gs"
            elif rate > 0.005:
                cls = "be"
            else:
                cls = "scav"

            from collections import deque
            dist = {src: 0}
            q = deque([src])
            while q:
                node = q.popleft()
                for nbr in adj.get(node, []):
                    if nbr not in dist:
                        dist[nbr] = dist[node] + 1
                        q.append(nbr)
            hops = dist.get(dst, n_nodes)

            buffer_lat = hops * buf_depth * (1.0 / max(0.001, rate * n_nodes))

            vc_priority_latency = 0
            if cls == "be":
                vc_priority_latency = allocator.class_config["gs"]["vcs"] * 2
            elif cls == "scav":
                vc_priority_latency = (allocator.class_config["gs"]["vcs"] +
                                       allocator.class_config["be"]["vcs"]) * 2

            reorder_bound = reorder.compute_reorder_bound(adj, src, dst)

            wc_latency = hops + buffer_lat + vc_priority_latency + reorder_bound

            flow_key = f"{src}->{dst}"
            per_flow[flow_key] = {
                "class": cls,
                "rate": rate,
                "hops": hops,
                "wc_latency": round(wc_latency, 2),
                "buffer_latency": round(buffer_lat, 2),
                "vc_priority_latency": vc_priority_latency,
                "reorder_bound": reorder_bound,
            }
            per_class[cls].append(wc_latency)
            per_class_rates[cls].append(rate)

    class_summary = {}
    for cls in ["gs", "be", "scav"]:
        lats = per_class.get(cls, [])
        if lats:
            class_summary[cls] = {
                "n_flows": len(lats),
                "avg_latency": round(sum(lats) / len(lats), 2),
                "max_latency": round(max(lats), 2),
                "p99_latency": round(sorted(lats)[int(len(lats) * 0.99)], 2),
            }
        else:
            class_summary[cls] = {"n_flows": 0}

    gs_vcs = allocator.class_config["gs"]["vcs"]
    be_vcs = allocator.class_config["be"]["vcs"]
    scav_vcs = allocator.class_config["scav"]["vcs"]
    gs_flows = len(per_class.get("gs", []))
    be_flows = len(per_class.get("be", []))
    scav_flows = len(per_class.get("scav", []))

    capacity_per_vc = n_nodes * buf_depth
    gs_cap = gs_vcs * capacity_per_vc
    be_cap = be_vcs * capacity_per_vc
    scav_cap = scav_vcs * capacity_per_vc
    gs_demand = sum(r for r in per_class_rates.get("gs", []))
    be_demand = sum(r for r in per_class_rates.get("be", []))
    scav_demand = sum(r for r in per_class_rates.get("scav", []))
    gs_admitted = min(gs_flows, int(gs_cap * min(1.0, gs_demand / (gs_cap + 1e-9))))
    be_admitted = min(be_flows, int(be_cap * min(1.0, be_demand / (be_cap + 1e-9))))
    scav_admitted = min(scav_flows, int(scav_cap * min(1.0, scav_demand / (scav_cap + 1e-9))))
    if gs_demand < gs_cap:
        gs_admitted = gs_flows
    if be_demand < be_cap:
        be_admitted = be_flows
    if scav_demand < scav_cap:
        scav_admitted = scav_flows

    admission = {
        "gs_admitted": gs_admitted,
        "gs_offered": gs_flows,
        "be_admitted": be_admitted,
        "be_offered": be_flows,
        "scav_admitted": scav_admitted,
        "scav_offered": scav_flows,
        "total_admitted": gs_admitted + be_admitted + scav_admitted,
        "total_offered": gs_flows + be_flows + scav_flows,
    }

    return {
        "per_flow": per_flow,
        "per_class": class_summary,
        "admission": admission,
        "summary": (
            f"{n_nodes} nodes, {n_vcs} VCs, ir={ir}: "
            f"GS={gs_admitted}/{gs_flows} BE={be_admitted}/{be_flows} "
            f"SCAV={scav_admitted}/{scav_flows} admitted"
        ),
    }

def main():
    ap = argparse.ArgumentParser(description="Deep QoS model with per-class VCs")
    ap.add_argument("--anynet", required=True, help=".anynet topology file")
    ap.add_argument("--matrix", help="Traffic matrix file")
    ap.add_argument("--ir", type=float, default=0.08, help="Injection rate")
    ap.add_argument("--vcs", type=int, default=4, help="Number of VCs")
    ap.add_argument("--buf", type=int, default=8, help="Buffer depth per VC")
    args = ap.parse_args()

    adj = defaultdict(list)
    n = 0
    with open(args.anynet) as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("//"):
                continue
            parts = line.split()
            if len(parts) >= 2 and parts[0] == "router":
                rid = int(parts[1])
                n = max(n, rid + 1)
                for p in parts[2:]:
                    if p.isdigit():
                        adj[rid].append(int(p))

    matrix = [[0.0] * n for _ in range(n)]
    if args.matrix:
        mat_rows = []
        with open(args.matrix) as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith('#'):
                    continue
                vals = [float(x) for x in line.split()]
                mat_rows.append(vals)
        for i, row in enumerate(mat_rows):
            for j, val in enumerate(row):
                if i < n and j < n:
                    matrix[i][j] = val

    result = compute_qos_bounds(adj, n, matrix, args.ir, args.vcs, args.buf)

    print(json.dumps({
        "per_class": result["per_class"],
        "admission": result["admission"],
        "summary": result["summary"],
    }, indent=2))

if __name__ == "__main__":
    main()
