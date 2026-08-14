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
    for line in open(path):
        p = line.split()
        if len(p) == 4 and p[2] == "router":
            a, b = int(p[1]), int(p[3])
            links[a].add(b)
            links[b].add(a)
    return links


def first_hops(start, links):
    """Dijkstra exactly as BookSim AnyNet::route: min over unvisited
    (set iteration = ascending id), strict <, std::map neighbor order."""
    dist = {i: float("inf") for i in links}
    prev = {i: -1 for i in links}
    dist[start] = 0
    unvisited = set(links)
    while unvisited:
        min_cand = min(unvisited, key=lambda i: dist[i])
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


def main():
    if len(sys.argv) != 3:
        sys.exit("usage: gen_route_tables.py <anynet> <outdir>")
    _, anynet, outdir = sys.argv
    import os
    os.makedirs(outdir, exist_ok=True)
    links = parse_anynet(anynet)
    for src in sorted(links):
        sx, sy = src % 8, src // 8
        fh = first_hops(src, links)
        row = [4] * 128
        for dst, hop in fh.items():
            hx, hy = hop % 8, hop // 8
            if hop == src:
                row[dst] = 4
            elif hx > sx:
                row[dst] = 0
            elif hx < sx:
                row[dst] = 1
            elif hy < sy:
                row[dst] = 2
            else:
                row[dst] = 3
        with open(f"{outdir}/route_{src}.hex", "w") as f:
            for v in row:
                f.write(f"{v:01x}\n")
    print(f"{len(links)} route tables written to {outdir}")


if __name__ == "__main__":
    main()
