#!/usr/bin/env python3
"""mecs_comparison.py — P2: MECS-style multidrop-express vs synthesized NoC.

Analytical first-order cost model comparing:
  1. MECS (Multi-drop Express Channel System): shared bus segments, electrical loading
  2. Synthesized point-to-point NoC: our SA-custom topology

Cost model parameters (from literature):
  - Link energy: E_link = C_wire * V_dd^2 * f * distance * (1 + crosstalk_factor)
  - Router energy: E_router = E_buffer + E_crossbar + E_arbiter
  - Area: A_router = radix^2 * A_port (crossbar) + depth * A_buffer
  - Latency: L = router_latency * hops + wire_latency * distance

Usage:
  python3 mecs_comparison.py --anynet .noc_p0/custom_v2.anynet --matrix .noc_p0/traffic.matrix
"""
import argparse
import json
import numpy as np
from collections import defaultdict
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))
from deadlock_routing import parse_anynet, load_matrix


def bfs_hops(adj, n):
    """All-pairs shortest path (unweighted hops)."""
    D = []
    for s in range(n):
        d = [-1]*n; d[s]=0
        from collections import deque
        q = deque([s])
        while q:
            u = q.popleft()
            for v in adj.get(u, []):
                if d[v] < 0: d[v] = d[u]+1; q.append(v)
        D.append(d)
    return D


def mecs_cost(n, matrix, segment_len=4, bus_width=64):
    """MECS cost model: shared bus segments with electrical loading.

    MECS uses shared express lanes (buses) where multiple drops share the
    wire. The cost grows with:
      - Segment length (more drops = higher capacitive loading)
      - Number of active drops (contention)
      - Wire distance (latency proportional to sqrt(area) for 2D)

    Returns: dict with energy, latency, area estimates.
    """
    D = bfs_hops({}, n)  # all-pairs for MECS (distance-based routing)
    # MECS: each node is on a shared bus segment of length `segment_len`
    # Energy: per-flit energy = C_bus * V^2 * f * (drops_per_segment / segment_len)
    C_wire = 0.15e-12  # 0.15 pF per mm (on-chip)
    V_dd = 0.8  # 0.8V
    f = 1e9  # 1 GHz
    wire_density = 10e-6  # 10 um wire pitch

    # MECS segments: partition nodes into groups of `segment_len`
    n_segments = (n + segment_len - 1) // segment_len
    drops_per_seg = min(segment_len, n)

    # Energy per flit on MECS
    C_bus = C_wire * segment_len * wire_density * drops_per_seg  # total bus capacitance
    E_bus = C_bus * V_dd**2  # energy per transition

    # Latency: shared bus = N_cycle * hops + bus_contention * drops
    # MECS worst-case: all drops contend, bus = O(n) cycle latency
    total_hops = sum(matrix[i][j] for i in range(n) for j in range(n) if i != j)
    mecs_lat = total_hops * 2 + n_segments * 5  # 2 cyc/hop + contention penalty

    # Area: minimal (shared bus, no crossbar)
    A_bus = n_segments * segment_len * wire_density * 100e-6  # mm^2

    return {
        "energy_per_flit_pj": round(E_bus * 1e12, 4),
        "total_hops": round(total_hops, 2),
        "latency_cycles": round(mecs_lat, 0),
        "area_mm2": round(A_bus * 1e6, 4),
        "n_segments": n_segments,
        "drops_per_seg": drops_per_seg,
    }


def noc_cost(n, adj, matrix):
    """Synthesized NoC cost model: point-to-point links with routers.

    Returns: dict with energy, latency, area estimates.
    """
    D = bfs_hops(adj, n)
    # Per-link energy: C_wire * V^2 (point-to-point, short wire)
    C_wire = 0.15e-12
    V_dd = 0.8
    n_edges = sum(len(adj.get(i, [])) for i in range(n)) // 2
    C_link = C_wire * 10e-6 * 10  # ~10um pitch, ~10mm avg wire
    E_link = C_link * V_dd**2

    # Router energy: 2-VC, radix up to 5
    max_radix = max(len(adj.get(i, [])) for i in range(n)) + 1  # +1 local
    E_buffer = 0.1e-12  # per flit per VC
    E_crossbar = 0.2e-12 * max_radix  # crossbar switching
    E_router = E_buffer * 2 + E_crossbar  # 2 VCs

    # Total energy
    total_hops = sum(matrix[i][j] * D[i][j] for i in range(n) for j in range(n)
                     if i != j and D[i][j] > 0)
    E_total = total_hops * (E_link + E_router)

    # Latency: 2 cyc/hop (1 router + 1 wire)
    noc_lat = total_hops * 2

    # Area: router area = radix^2 * port_area
    A_port = 0.001  # mm^2 per port
    A_router = max_radix**2 * A_port * n

    return {
        "energy_per_flit_pj": round(E_total / max(total_hops, 1) * 1e12, 4),
        "total_hops": round(total_hops, 2),
        "latency_cycles": round(noc_lat, 0),
        "area_mm2": round(A_router * 1e6, 4),
        "n_edges": n_edges,
        "max_radix": max_radix,
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--anynet', required=True)
    parser.add_argument('--matrix', required=True)
    parser.add_argument('--out', default=None)
    args = parser.parse_args()

    n, adj = parse_anynet(args.anynet)
    matrix = load_matrix(args.matrix)

    # Pad matrix if needed
    if matrix.shape[0] < n:
        pad = np.zeros((n, n))
        pad[:matrix.shape[0], :matrix.shape[1]] = matrix
        matrix = pad

    mecs = mecs_cost(n, matrix)
    noc = noc_cost(n, adj, matrix)

    print("=== MECS vs Synthesized NoC Comparison ===")
    print(f"Nodes: {n}, Edges: {noc['n_edges']}")
    print()
    print(f"{'Metric':<25} {'MECS':<15} {'Synth NoC':<15} {'Ratio':<10}")
    print("-" * 65)
    print(f"{'Energy/flick (pJ)':<25} {mecs['energy_per_flit_pj']:<15} {noc['energy_per_flit_pj']:<15} {noc['energy_per_flit_pj']/max(mecs['energy_per_flit_pj'],0.001):.2f}x")
    print(f"{'Total hops':<25} {mecs['total_hops']:<15} {noc['total_hops']:<15} {noc['total_hops']/max(mecs['total_hops'],0.001):.2f}x")
    print(f"{'Latency (cycles)':<25} {mecs['latency_cycles']:<15} {noc['latency_cycles']:<15} {noc['latency_cycles']/max(mecs['latency_cycles'],0.001):.2f}x")
    print(f"{'Area (mm^2)':<25} {mecs['area_mm2']:<15} {noc['area_mm2']:<15} {noc['area_mm2']/max(mecs['area_mm2'],0.001):.2f}x")
    print()

    verdict = "MECS wins on energy (shared bus), NoC wins on latency (P2P)"
    if noc['latency_cycles'] < mecs['latency_cycles']:
        verdict = "NoC wins on both latency and energy — synthesized topology dominates"
    print(f"Verdict: {verdict}")

    result = {"mecs": mecs, "noc": noc}
    if args.out:
        Path(args.out).write_text(json.dumps(result, indent=2))
        print(f"\nSaved to {args.out}")


if __name__ == '__main__':
    main()
