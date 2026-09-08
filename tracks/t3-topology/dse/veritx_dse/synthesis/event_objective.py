"""event_objective.py — Score a candidate topology DIRECTLY from the event
stream (no intermediate matrix aggregation).

This closes the gap identified after Test 3: synthesis consumed re-aggregated
matrices. Here the objective reads the lossless event representation:

  - dram_io events      → per-tile DRAM load (context; not fabric edges)
  - collective events   → kept STRUCTURAL {participants, size_bytes}; scored
                          under MULTIPLE algorithms (ring / halving-doubling)
                          on the candidate topology, best algorithm wins
  - flow class priority → deadline-critical flows (prio 1) count more

Objective = sum over collectives of priority_weight * algo_weight *
            priced_geodesic_latency(participants, size, adj, algo)

This is the thing a pre-aggregated matrix CANNOT express (Test 2, Proof 2).
"""
import json
import math
import sys
from pathlib import Path

import numpy as np

# Local import: milp_topology_v2 lives in the same package. Fall back to a
# path import when this file is executed directly as a script (python3
# event_objective.py …), where package-relative imports are unavailable.
try:
    from .milp_topology_v2 import PIPE_COST, WIRE_COST, _edge_len
except ImportError:  # script mode: sibling module sits next to this file
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    from milp_topology_v2 import PIPE_COST, WIRE_COST, _edge_len


# ── Algorithm decompositions on a GIVEN topology ────────────────────────

def ring_schedule(participants):
    """Ring all-reduce data movement: k steps × k hops along participant ring.
    Returns list of (src, dst, chunk_fraction) moves per step."""
    k = len(participants)
    if k <= 1:
        return []
    return [(participants[i], participants[(i + 1) % k], 1.0 / k)
            for i in range(k)] * (2 * (k - 1))


def halving_doubling_schedule(participants):
    """Recursive halving/doubling: log2(k) stages, distance-doubling partners."""
    k = len(participants)
    if k <= 1 or (k & (k - 1)) != 0:
        return ring_schedule(participants)
    moves = []
    for s in range(int(math.log2(k))):
        dist = 1 << s
        for i in range(k):
            moves.append((participants[i], participants[i ^ dist], dist / k))
    return moves


ALGORITHMS = {"ring": ring_schedule, "halving_doubling": halving_doubling_schedule}


# ── Topology helpers ────────────────────────────────────────────────────

def _dijkstra(adj, xy, source):
    """Shortest physical-latency paths from source over adjacency."""
    import heapq
    dist = {source: 0.0}
    pq = [(0.0, source)]
    while pq:
        du, u = heapq.heappop(pq)
        if du > dist.get(u, math.inf):
            continue
        for v in adj[u]:
            nd = du + PIPE_COST + WIRE_COST * _edge_len(u, v, xy)
            if nd < dist.get(v, math.inf):
                dist[v] = nd
                heapq.heappush(pq, (nd, v))
    return dist


def _pair_cost(dist, u, v):
    du, dv = dist.get(u), dist.get(v)
    if du is None or dv is None or math.isinf(du) or math.isinf(dv):
        return None  # unreachable — topology invalid for this schedule
    return abs(dv - du)


# ── Event-stream objective ──────────────────────────────────────────────

# Fallback weights when an event carries no priority of its own.
# NOTE: with frontier_timing.py output, priorities are SLO-DERIVED
# (decode=deadline-critical -> 1) and carried IN the events; these
# defaults only apply to legacy untimed streams.
PRIORITY_WEIGHTS = {1: 4.0, 2: 1.0}


def score_topology(adj, xy, events, algorithms=("ring", "halving_doubling")):
    """Returns (objective, detail dict). Lower = better.

    Scores each collective event under every algorithm ON THIS TOPOLOGY;
    the cheapest algorithm's cost counts. Returns None-equivalent (inf-like
    large value) if any required move is unreachable.
    """
    total = 0.0
    detail = []

    for col in events["collectives"]:
        prio_w = PRIORITY_WEIGHTS.get(col.get("priority", 2), 1.0)
        size = col["size_bytes"]
        k = len(col["participants"])
        best_algo, best_cost = None, math.inf

        for algo_name in algorithms:
            sched = ALGORITHMS[algo_name](col["participants"])
            # Cache Dijkstra per source within this schedule evaluation
            dists = {}
            cost = 0.0
            feasible = True
            for src, dst, frac in sched:
                if src not in dists:
                    dists[src] = _dijkstra(adj, xy, src)
                pc = _pair_cost(dists[src], src, dst)
                if pc is None:
                    feasible = False
                    break
                cost += frac * size * pc
            if feasible and best_cost > cost:
                best_cost, best_algo = cost, algo_name

        if best_algo is None:
            # Some algorithm moves unreachable on this topology.
            # Penalty MUST exceed any feasible cost (~1e9 here) or the
            # optimizer will prefer broken topologies.
            return 1e15, {"infeasible": col["tensor"]}

        total += prio_w * best_cost
        detail.append({"tensor": col["tensor"], "algo": best_algo,
                       "cost_cycles_x_bytes": best_cost})

    return total, {"collectives": detail}


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Score topology from event stream")
    parser.add_argument("events", help="Path to events JSON file")
    parser.add_argument("topo", help="Path to topology JSON file")
    args = parser.parse_args()

    events = json.load(open(args.events))
    t3 = json.load(open(args.topo))

    def adj_from_edges(edges):
        adj = {}
        for a, b in edges:
            adj.setdefault(a, set()).add(b)
            adj.setdefault(b, set()).add(a)
        return adj

    xy = [(x, y) for y in range(8) for x in range(8)]
    adjA = adj_from_edges([tuple(e) for e in t3["edges"]["static_matrix"]])
    objA, detA = score_topology(adjA, xy, events)
    print(f"T3 static_matrix topology: objective={objA:.3e}")
    for d in detA["collectives"]:
        print(f"  {d['tensor']}: best algo={d['algo']}, cost={d['cost_cycles_x_bytes']:.3e}")
