"""Independent reference for the canonical custom routing semantic.

NEVER import the production producer. This module is a from-scratch
implementation of the SAME specification, written as a DIFFERENT algorithm
so agreement is evidence rather than tautology.

SPECIFICATION (from routing_materialize._weighted_first_hops' own
docstring, restated independently):

    For every ordered pair (src, dst):
      choose the path minimising
          (1) total route_weight, then
          (2) the lexicographically smallest COMPLETE channel-id sequence

PRODUCTION ALGORITHM: Dijkstra with tuple relaxation on
(cost, channel-id sequence).

REFERENCE ALGORITHM (this file): a two-phase construction —
  phase 1  plain Bellman-Ford relaxation on COST ALONE (no sequences),
           giving d[v] = min cost from src to v;
  phase 2  walk forward from src, and at each step take the SMALLEST
           channel id among channels that lie on SOME minimum-cost path to
           dst (i.e. cost(ch) + d[dst_router(ch)] == remaining cost).

Phase 2 is a greedy lexicographic construction over the min-cost DAG, which
is structurally different from Dijkstra-with-sequences and does not use a
heap or a settled set. Two different algorithms reaching the same route is
the point.
"""
from __future__ import annotations


def _outgoing(nodes, channels):
    out = {n: [] for n in nodes}
    for c in channels:
        out[c["src"]].append(c)
    for lst in out.values():
        lst.sort(key=lambda c: c["channel_id"])
    return out


def min_cost(nodes, channels, src, dst):
    """Plain Bellman-Ford on cost alone. Independent of phase 2."""
    INF = float("inf")
    d = {n: INF for n in nodes}
    d[src] = 0
    for _ in range(len(nodes)):
        changed = False
        for c in channels:
            if d[c["src"]] + c["weight"] < d[c["dst"]]:
                d[c["dst"]] = d[c["src"]] + c["weight"]
                changed = True
        if not changed:
            break
    return d[dst]


def canonical_path(nodes, channels, src, dst):
    """The canonical full channel-id path, or None when unreachable.

    Returns the tuple of channel ids. Built by greedy lexicographic
    selection over the min-cost DAG.
    """
    if src == dst:
        return ()
    out = _outgoing(nodes, channels)
    d = {}
    INF = float("inf")
    # cost-to-dst: run Bellman-Ford FROM dst over the reversed graph.
    rev = {n: [] for n in nodes}
    for c in channels:
        rev[c["dst"]].append(c)
    dd = {n: INF for n in nodes}
    dd[dst] = 0
    for _ in range(len(nodes)):
        changed = False
        for c in channels:
            # reverse edge dst_router -> src_router
            if dd[c["dst"]] + c["weight"] < dd[c["src"]]:
                dd[c["src"]] = dd[c["dst"]] + c["weight"]
                changed = True
        if not changed:
            break
    if dd[src] == INF:
        return None

    path = []
    cur = src
    remaining = dd[src]
    seen = set()
    while cur != dst:
        if cur in seen:
            return None            # would imply a zero-cost cycle
        seen.add(cur)
        # smallest channel id on SOME minimum-cost path to dst
        best = None
        for c in out[cur]:
            if c["weight"] + dd[c["dst"]] == remaining:
                if best is None or c["channel_id"] < best["channel_id"]:
                    best = c
        if best is None:
            return None
        path.append(best["channel_id"])
        remaining -= best["weight"]
        cur = best["dst"]
    return tuple(path)


def canonical_first_hops(nodes, channels):
    """{（src, dst): first_channel_id} for every reachable ordered pair."""
    out = {}
    for src in nodes:
        for dst in nodes:
            if src == dst:
                continue
            p = canonical_path(nodes, channels, src, dst)
            if p:
                out[(src, dst)] = p[0]
    return out


def walk_route(entries, channels_by_id, src, dst, limit=1000):
    """Walk a first-hop table into a FULL channel-id path.

    Used to turn the production RouteArtifact (first-hop only) into a full
    path for comparison against `canonical_path`.
    """
    path = []
    cur = src
    while cur != dst:
        cid = entries.get((src if not path else cur, dst))
        if cid is None:
            return None
        ch = channels_by_id.get(cid)
        if ch is None:
            return None
        path.append(cid)
        cur = ch["dst"]
        if len(path) > limit:
            return None
    return tuple(path)
