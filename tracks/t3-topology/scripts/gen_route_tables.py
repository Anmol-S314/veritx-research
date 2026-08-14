#!/usr/bin/env python3
"""Generate Dijkstra-exact routing tables for the 2-die bridged topology.

BookSim's bridged_2die.cfg uses routing_function=min (anynet), which is
Dijkstra with std::map tie-breaking (ascending neighbor-id order, strict <
relaxation). XY/YX DOR heuristics diverge from that table — measured
4320/16256 src/dst pairs differ — and the divergence is exactly what built
the 1-VC bridge deadlock (multi-stream replay: 40/2927 ejected; BookSim
runs the same table deadlock-free at num_vcs=1).

This script reproduces BookSim's table EXACTLY (same algorithm, same
tie-break) and writes route_<src>.hex files, one 128-entry column of ports
per router, entry[dst] = port {0:E, 1:W, 2:N, 3:S, 4:L}. The RTL loads its
own column from route_<MY_ID>.hex when built with -DTWO_DIE_ROUTE_TABLE.

Usage: python3 scripts/gen_route_tables.py <anynet_file> <outdir>
"""
import sys
from collections import defaultdict, deque


def parse_anynet(path):
    links = defaultdict(set)
    bridge = {}
    for line in open(path):
        p = line.split()
        if len(p) == 4 and p[2] == "router":
            a, b = int(p[1]), int(p[3])
            links[a].add(b)
            links[b].add(a)
            # cross-die link = the bridge: die-A side is EAST, die-B WEST
            if (a < 64) != (b < 64):
                bridge[a] = "E"
                bridge[b] = "W"
    return links, bridge


def first_hops(start, links):
    """Dijkstra exactly as BookSim AnyNet::route: min over unvisited
    (set iteration = ascending id), strict <, std::map neighbor order."""
    dist = {i: float("inf") for i in links}
    prev = {i: -1 for i in links}
    dist[start] = 0
    unvisited = set(links)
    while unvisited:
        # BookSim scans std::set in ASCENDING id order and takes the first
        # node at min distance (strict < means ties never replace). Python's
        # min() over a set is ARBITRARY on ties — a genuine divergence that
        # broke the whole table (deadlock: paths differed from BookSim's).
        # Emulate: sorted() + stable min == first minimal in id order.
        min_cand = min(sorted(unvisited), key=lambda i: dist[i])
        unvisited.discard(min_cand)
        for nb in sorted(links[min_cand]):
            nd = dist[min_cand] + 1
            if nd < dist[nb]:
                dist[nb] = nd
                prev[nb] = min_cand
    fh = {}
    for i in links:
        if i == start:
            continue
        n = i
        while prev[n] != start and prev[n] != -1:
            n = prev[n]
        fh[i] = n
    return fh


def port_of(src, hop, bridge):
    """RTL geometric port for a first-hop neighbor.
    Bridge links are forced to their physical direction (die-A EAST,
    die-B WEST) — geometric derivation alone is WRONG there (the bridge
    connects (7,3)<->(0,3), which reads as N/S geometrically).
    Non-bridge links: direction from src to hop in the mesh."""
    if hop in bridge and src in bridge and bridge[hop] == bridge[src]:
        pass  # same bridge, unreachable branch; kept for clarity
    if hop in bridge and (src < 64) != (hop < 64):
        # src sits ON the bridge link; its direction is bridge[src] (die-A
        # EAST, die-B WEST). bridge[hop] is the far side's direction — the
        # reverse — which is NOT the port src exits on.
        return {"E": 0, "W": 1}[bridge[src]]
    sx, sy = src % 8, src // 8
    hx, hy = hop % 8, hop // 8
    if hop == src:
        return 4
    if hx > sx:
        return 0
    if hx < sx:
        return 1
    if hy < sy:
        return 2
    return 3


def main():
    if len(sys.argv) != 3:
        sys.exit("usage: gen_route_tables.py <anynet> <outdir>")
    _, anynet, outdir = sys.argv
    import os
    os.makedirs(outdir, exist_ok=True)
    links, bridge = parse_anynet(anynet)
    for src in sorted(links):
        fh = first_hops(src, links)
        row = [4] * 128
        for dst, hop in fh.items():
            row[dst] = port_of(src, hop, bridge)
        with open(f"{outdir}/route_{src}.hex", "w") as f:
            for v in row:
                f.write(f"{v:01x}\n")
    print(f"{len(links)} route tables written to {outdir}")


if __name__ == "__main__":
    main()
