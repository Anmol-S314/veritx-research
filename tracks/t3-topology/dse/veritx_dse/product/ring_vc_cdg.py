"""VC-aware channel-dependency analysis of the native ring.

Why this exists
---------------
The composed family path routes the ring with the fork's own law and the
composed router keeps two VC classes: VC 0 is the free (minimal-hop) table
and VC 1 is the escape table, with buffers per (port, VC). The composed CDG
proof therefore has to be VC-aware: a buffer wait can only ever be against a
buffer of the SAME VC, so a cycle that spans VCs is not a wait cycle.

What it proves
--------------
1. The law the fork executes — the direction is chosen once per flow and
   the dateline half is computed at the injection hop and then kept (the
   fork's own ``dor_next_torus`` only recomputes the partition when a flit
   TURNS INTO a dimension, and a 1-D ring is entered once) — leaves every
   VC class with a cyclic channel dependency graph. A circular buffer wait
   is therefore possible for the ring, in the model exactly as in the RTL.
2. The same ring with the dateline half recomputed per hop (the classic
   dateline VC switch) leaves every VC class acyclic, and the switch is
   one-way, so no cycle can use it twice.

The conclusion the product needs is (1): the ring's deadlock is INHERITED
from the certified routing law, not introduced by the RTL. Fixing it needs a
law change (a VC switch at the wrap), which changes the law the certified
BookSim profile measures, so it is an architecture decision, not a bug fix.

Scope: the dependency model is the standard wormhole one — at a router, the
input channel depends on the output channel when a flit may occupy the input
buffer of that VC while waiting for the output buffer of that VC. Fairness,
credit correctness and liveness under arbitrary traffic are NOT covered here.
"""
from __future__ import annotations

from typing import Callable, Iterable

Channel = tuple[int, int]
Edge = tuple[Channel, int, Channel, int]

DIRECTIONS = (0, 1)


def ring_next_router(source: int, destination: int, n: int,
                     direction: int) -> int:
    """The fork's hop in one direction: 0 is +1 (right), 1 is -1 (left)."""
    return (source + (1 if direction == 0 else -1)) % n


def fork_direction(source: int, destination: int, n: int) -> tuple[int, ...]:
    """Every direction the fork may legally take for this flow.

    The fork picks the minimal wrap; the diametral tie admits either face
    (``RandomInt(1)``), so both are legal and both are analysed.
    """
    forward = (destination - source) % n
    if n % 2 == 0 and forward == n // 2:
        return (0, 1)
    return (0,) if forward <= n // 2 else (1,)


def fork_partition(source: int, destination: int) -> int:
    """The fork's fixed dateline partition, computed at the injection hop.

    ``dor_next_torus`` sets the partition only when turning into a
    dimension; for a 1-D ring that is the injection hop, and the value is
    ``1`` exactly when the injection router is above the destination. The
    fork then keeps it for every later hop.
    """
    return 1 if source > destination else 0


def per_hop_partition(router: int, destination: int) -> int:
    """The classic dateline half, recomputed at every hop."""
    return 1 if router > destination else 0


def ring_path(source: int, destination: int, n: int, direction: int) -> list[int]:
    """The routers a flow traverses, injection first, destination last."""
    path = [source]
    router = source
    while router != destination:
        router = ring_next_router(router, destination, n, direction)
        path.append(router)
    return path


def ring_edges(n: int,
               vc_of_hop: Callable[[int, int, int], int]) -> list[Edge]:
    """Every VC-aware dependency edge the ring's routing can produce.

    ``vc_of_hop(source, destination, router)`` gives the VC a flow occupies
    on the hop that leaves ``router``. An edge joins the channel a flow
    arrived on to the channel it departs on, carrying the VC of each side:
    a buffer wait is only possible between buffers of the same VC, but the
    VC of the arrival and of the departure are recorded separately so a VC
    switch is visible rather than hidden.
    """
    edges: list[Edge] = []
    for source in range(n):
        for destination in range(n):
            if source == destination:
                continue
            for direction in fork_direction(source, destination, n):
                path = ring_path(source, destination, n, direction)
                for index, router in enumerate(path[:-1]):
                    out_channel = (router, path[index + 1])
                    out_vc = vc_of_hop(source, destination, router)
                    if index == 0:
                        continue
                    in_channel = (path[index - 1], router)
                    in_vc = vc_of_hop(source, destination, path[index - 1])
                    edges.append((in_channel, in_vc, out_channel, out_vc))
    return edges


def _adjacency(edges: Iterable[Edge], *, same_vc_only: bool) -> dict:
    graph: dict[tuple[Channel, int], set[tuple[Channel, int]]] = {}
    for in_channel, in_vc, out_channel, out_vc in edges:
        if same_vc_only and in_vc != out_vc:
            continue
        graph.setdefault((in_channel, in_vc), set()).add((out_channel, out_vc))
    return graph


def _find_cycle(graph: dict) -> list | None:
    """One cycle of the graph, or None when it is acyclic."""
    WHITE, GREY, BLACK = 0, 1, 2
    colour: dict = {node: WHITE for node in graph}
    for node in list(graph):
        if colour[node] != WHITE:
            continue
        stack = [(node, iter(graph.get(node, ())))]
        colour[node] = GREY
        path = [node]
        while stack:
            current, successors = stack[-1]
            advanced = False
            for successor in successors:
                if colour.get(successor, WHITE) == GREY:
                    index = path.index(successor)
                    return path[index:] + [successor]
                if colour.get(successor, WHITE) == WHITE:
                    colour[successor] = GREY
                    path.append(successor)
                    stack.append((successor, iter(graph.get(successor, ()))))
                    advanced = True
                    break
            if not advanced:
                colour[current] = BLACK
                stack.pop()
                path.pop()
    return None


def vc_acyclicity(n: int,
                  vc_of_hop: Callable[[int, int, int], int]) -> dict:
    """Per-VC and union acyclicity of the ring's dependency graph."""
    edges = ring_edges(n, vc_of_hop)
    per_vc: dict[int, dict] = {}
    same_vc_graph = _adjacency(edges, same_vc_only=True)
    for vc in sorted({vc for _i, ivc, _o, ovc in edges for vc in (ivc, ovc)}):
        sub = {node: {s for s in successors if s[1] == vc}
               for node, successors in same_vc_graph.items() if node[1] == vc}
        cycle = _find_cycle(sub)
        per_vc[vc] = {
            "acyclic": cycle is None,
            "cycle": None if cycle is None else [
                {"channel": list(channel), "vc": node_vc}
                for (channel, node_vc) in cycle],
        }
    union_graph = _adjacency(edges, same_vc_only=False)
    union_cycle = _find_cycle(union_graph)
    return {
        "edges": len(edges),
        "per_vc": per_vc,
        "union_acyclic": union_cycle is None,
        "union_cycle": None if union_cycle is None else [
            {"channel": list(channel), "vc": node_vc}
            for (channel, node_vc) in union_cycle],
    }


def fork_law(n: int) -> dict:
    """The law the fork (and therefore the RTL) executes."""
    return vc_acyclicity(
        n, lambda source, destination, router: fork_partition(source, destination))


def dateline_switch_law(n: int) -> dict:
    """The classic dateline VC switch: the half is recomputed per hop."""
    return vc_acyclicity(
        n, lambda source, destination, router: per_hop_partition(router, destination))


def analyze(n: int) -> dict:
    """Both laws, side by side, with the verdicts spelled out."""
    fork = fork_law(n)
    switch = dateline_switch_law(n)
    return {
        "routers": n,
        "fork_law": {
            "per_vc_acyclic": all(v["acyclic"] for v in fork["per_vc"].values()),
            "union_acyclic": fork["union_acyclic"],
            "edges": fork["edges"],
        },
        "dateline_switch_law": {
            "per_vc_acyclic": all(v["acyclic"] for v in switch["per_vc"].values()),
            "union_acyclic": switch["union_acyclic"],
            "edges": switch["edges"],
        },
        "verdict": (
            "the executed law leaves every VC class cyclic, so a circular "
            "buffer wait is possible for the ring"
            if not all(v["acyclic"] for v in fork["per_vc"].values())
            else "the executed law leaves every VC class acyclic"),
    }


__all__ = [
    "analyze",
    "dateline_switch_law",
    "fork_direction",
    "fork_law",
    "fork_partition",
    "per_hop_partition",
    "ring_edges",
    "ring_next_router",
    "ring_path",
    "vc_acyclicity",
]
