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


def enforce_rtl_bridge_topology(links, bridge, x_dim=8, die=64):
    """Strip + warn on mesh links the RTL does NOT have at bridge nodes
    (seed ab55 / F14 root cause, 2026-08-14; Steve, additive on Dave's
    65fbbaa port_of rework).

    noc_2die.sv merges the bridge into the bridge nodes' E/W ports: die-A
    edge router (Y_DIM-1, BRIDGE_COL) EAST = bridge, die-B entry router
    (BRIDGE_ROW, BRIDGE_COL) WEST = bridge — those mesh links are REMOVED
    in the RTL. If the anynet ever regains them (regeneration scripts),
    port_of's geometry check passes (the neighbor exists in the graph)
    and the RTL loops the packet across the bridge. This guard strips
    them from the routing graph and warns, so tables always match the
    RTL regardless of how the anynet is produced.

    Directed note (2026-08-18, dave): the RTL removes the 56<->57 and
    64<->65 mesh links ENTIRELY (both directions): 56's E-input is
    overridden by br_f3b, so f_st2[0][57][PORT_W] has no consumer;
    64's W-input is the bridge br_f3b. Both directions are stripped
    from the routing graph — no directed one-way reverses are needed."""
    bridge_nodes = sorted(bridge)
    stripped = []
    for n in bridge_nodes:
        side = "A" if n < die else "B"
        r, c = divmod(n - (0 if side == "A" else die), x_dim)
        if side == "A" and r == x_dim - 1:
            phantom = n + 1      # die-A edge row: EAST is the bridge
            if phantom in links[n]:
                links[n].discard(phantom)
                links[phantom].discard(n)
                stripped.append((n, phantom))
        elif side == "B" and r == 0:
            # die-B: WEST of the entry node is the bridge, but (0, BRIDGE_COL)
            # has no WEST mesh neighbor at BRIDGE_COL=0 — and even when it
            # does, the 64-E stage (the east mesh direction) is NOT removed,
            # so the die-B row link is fully bidirectional in the RTL.
            continue
        else:
            continue
    if stripped:
        print("WARNING: anynet has mesh links the RTL removed at bridge "
              "nodes (phantom links — seed ab55/F14): "
              + ", ".join(f"router {a} router {b}" for a, b in sorted(stripped))
              + " — stripped from the routing graph so tables match the RTL.")
    return links
    return links


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


def port_of(src, hop, links):
    """RTL geometric port for a first-hop neighbor, validated against the
    ACTUAL link set. Geometric derivation alone is WRONG at the bridge
    nodes: die-B (0,3)=67 has NO west mesh link (west is the bridge back
    to die A), so 'dst west of me' must NOT return W — the only path goes
    around via the south link. Every port must lead to a neighbor that
    physically exists in the anynet (which already excludes the phantom
    mesh links the RTL's bridge ports replace)."""
    sx, sy = src % 8, src // 8
    hx, hy = hop % 8, hop // 8
    if hop == src:
        return 4
    # bridge link: 59 (die-A 7,3) exits EAST, 67 (die-B 0,3) exits WEST.
    # These are the ONLY cross-die links, and their direction is fixed by
    # the RTL's noc_2die.sv wiring regardless of geometry.
    if (src < 64) != (hop < 64):
        return 0 if src < 64 else 1
    # direction from src to hop by geometry.
    # N/S orientation (2026-08-18, dave, 011b root cause): the RTL's
    # noc_2die wiring has PORT_N connecting router y's N-input to router
    # (y+1)'s S-output — PORT_N points toward HIGHER y, PORT_S toward
    # LOWER y (router.sv route2d: dy>y -> PORT_N; Y>ly -> PORT_S; verified
    # empirically: die-A (7,0)->(6,0) detour is PORT_S and delivered
    # 2880/2880). The previous mapping (hy<sy -> d=2/N) was INVERTED:
    # table mode sent every vertical hop the wrong way -> "0/3663
    # ejected" (seed 011b, the table-routing RTL never-delivers bug).
    if hx > sx:
        d = 0
    elif hx < sx:
        d = 1
    elif hy < sy:
        d = 3
    else:
        d = 2
    # the geometric neighbor in direction d must actually be hop; if the
    # link is missing (bridge-adjacent node), geometry crossed a void and
    # the table must NOT emit that port — reroute via the real links.
    geo = {0: (sx + 1, sy), 1: (sx - 1, sy), 2: (sx, sy + 1), 3: (sx, sy - 1)}
    gx, gy = geo[d]
    if gy * 8 + gx == hop:
        return d
    # geometry disagrees with reality: hop is reached via a non-geometric
    # neighbor (e.g. 67 -> 75 south, then west around the missing link).
    # Find which of src's actual neighbors lies on the shortest path.
    for nb in sorted(links[src]):
        if nb == hop:
            nx, ny = nb % 8, nb // 8
            if nx > sx:
                return 0
            if nx < sx:
                return 1
            if ny < sy:
                return 3
            return 2
    # last resort: 4 = LOCAL (should not happen for cross-die)
    return 4


def main():
    if len(sys.argv) != 3:
        sys.exit("usage: gen_route_tables.py <anynet> <outdir>")
    _, anynet, outdir = sys.argv
    import os
    os.makedirs(outdir, exist_ok=True)
    links, bridge = parse_anynet(anynet)
    links = enforce_rtl_bridge_topology(links, bridge)
    for src in sorted(links):
        fh = first_hops(src, links)
        row = [4] * 128
        for dst, hop in fh.items():
            row[dst] = port_of(src, hop, links)
        with open(f"{outdir}/route_{src}.hex", "w") as f:
            for v in row:
                f.write(f"{v:01x}\n")
    print(f"{len(links)} route tables written to {outdir}")


if __name__ == "__main__":
    main()
