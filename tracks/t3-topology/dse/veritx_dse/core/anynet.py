"""core/anynet.py — the ONE anynet links parser.

Rationale: docs/decisions/modules/core.md
"""
from __future__ import annotations

from veritx_dse.core.errors import SemanticError

from dataclasses import dataclass, field
from pathlib import Path

class AnynetError(ValueError, SemanticError):
    """Malformed anynet file — mirrors BookSim's assert-and-die, loudly."""

@dataclass
class AnynetGraph:
    """Parsed anynet: undirected router graph + node attachments.

Rationale: docs/decisions/modules/core.md
    """
    router_adj: dict[int, set[int]] = field(default_factory=dict)
    node_router: dict[int, int] = field(default_factory=dict)
    non_unit_weights: list[tuple[int, int]] = field(default_factory=list)
    router_weight: dict[tuple[int, int], int] = field(default_factory=dict)
    #: Declared ONE-WAY directions (src -> {dst}). A link is bidirectional
    #: only when both routers' lines name each other, so this is the literal
    #: file content, not a symmetrized view.
    router_directed: dict[int, set[int]] = field(default_factory=dict)
    #: Routing cost per declared direction. Defaults to the latency when the
    #: file gives no cost token (the historic single-number semantics).
    router_cost: dict[tuple[int, int], int] = field(default_factory=dict)
    #: Declared parallel lanes per direction: a repeated clause is a lane.
    router_lanes: dict[tuple[int, int], int] = field(default_factory=dict)

    @property
    def has_non_unit_weights(self) -> bool:
        return bool(self.non_unit_weights)

    @property
    def has_parallel_lanes(self) -> bool:
        return any(n > 1 for n in self.router_lanes.values())

    @property
    def is_symmetric(self) -> bool:
        """Every declared direction has its reverse declared too."""
        return all(src in self.router_directed.get(dst, set())
                   for src, dsts in self.router_directed.items()
                   for dst in dsts)

    @property
    def n_routers(self) -> int:
        return len(self.router_adj)

    @property
    def n_nodes(self) -> int:
        return len(self.node_router)

    @property
    def n_edges(self) -> int:
        return sum(len(v) for v in self.router_adj.values()) // 2

    def sequential_adj(self) -> dict[int, set[int]]:
        """Adjacency normalized to range(n_routers).

        BookSim requires sequential ids from 0, so this is identity for
        valid files; it makes the precondition loud for invalid ones
        instead of silently returning empty rows for missing ids.
        """
        n = self.n_routers
        if any(i not in self.router_adj for i in range(n)):
            raise AnynetError(
                f"router ids not sequential 0..{n - 1} — BookSim requires "
                f"'sequential starting with 0'")
        return self.router_adj

def parse_anynet_file(path: str | Path) -> AnynetGraph:
    """Parse any BookSim-legal links file: one-line or two-line dialect."""
    g = AnynetGraph()
    with open(path) as f:
        for line_no, line in enumerate(f, 1):
            toks = [t for t in line.split() if t]
            if not toks or toks[0].startswith(("*", "#", "//")):
                continue
            try:
                _parse_line(toks, g, line_no)
            except AnynetError:
                raise
            except (ValueError, IndexError) as e:
                raise AnynetError(f"{path}:{line_no}: {e}") from e
    return g

def _parse_line(toks: list[str], g: AnynetGraph, line_no: int) -> None:
    head_kind, head = toks[0], None
    if head_kind not in ("router", "node"):
        raise AnynetError(f"unknown head type {toks[0]!r}")
    if len(toks) < 2:
        raise AnynetError("head id missing")
    head = _int(toks[1], "head id")

    if head_kind == "router":
        g.router_adj.setdefault(head, set())

    i = 2
    while i < len(toks):
        kind = toks[i]
        if kind not in ("router", "node"):
            raise AnynetError(f"expected 'router'/'node', got {kind!r}")
        if i + 1 >= len(toks):
            raise AnynetError(f"{kind} body id missing")
        body = _int(toks[i + 1], f"{kind} id")
        i += 2
        weight = 1
        cost: int | None = None
        if i < len(toks) and toks[i] not in ("router", "node"):
            weight = _int(toks[i], "latency")
            i += 1
            # The optional second number is the routing cost; routing
            # minimises it, so it is tracked apart from the wire delay.
            if i < len(toks) and toks[i] not in ("router", "node"):
                cost = _int(toks[i], "cost")
                i += 1
            if weight != 1:
                g.non_unit_weights.append((line_no, weight))
        if cost is None:
            cost = weight

        if head_kind == "router" and kind == "router":
            g.router_adj.setdefault(body, set())
            g.router_adj[head].add(body)
            g.router_adj[body].add(head)
            g.router_weight[(head, body)] = weight
            g.router_cost[(head, body)] = cost
            g.router_lanes[(head, body)] = \
                g.router_lanes.get((head, body), 0) + 1
            g.router_directed.setdefault(head, set()).add(body)
        elif head_kind == "router" and kind == "node":
            _attach(g, body, head, line_no)
        elif head_kind == "node" and kind == "router":
            _attach(g, head, body, line_no)
        else:
            raise AnynetError("node-to-node link is invalid (anynet.cpp asserts)")

def _attach(g: AnynetGraph, node: int, router: int, line_no: int) -> None:
    prev = g.node_router.get(node)
    if prev is not None and prev != router:
        raise AnynetError(
            f"node {node} attaches to routers {prev} and {router} — "
            f"a node must attach to exactly one router")
    g.node_router[node] = router

def _int(tok: str, what: str) -> int:
    try:
        return int(tok)
    except ValueError:
        raise AnynetError(f"{what} is not an integer: {tok!r}") from None

def parse_anynet_pair(path: str | Path) -> tuple[int, dict[int, set[int]]]:
    """(n_routers, undirected adjacency over range(n)) — the legacy tuple.

    Consumers: deadlock_routing.parse_anynet (CDG analysis) and archive
    scripts. Sequentiality is enforced, matching BookSim's own constraint.
    """
    g = parse_anynet_file(path)
    return g.n_routers, g.sequential_adj()

def count_anynet_edges(path: str | Path) -> tuple[int, int]:
    """(n_routers, n_edges) — presets.count_anynet_edges delegates here."""
    g = parse_anynet_file(path)
    return g.n_routers, g.n_edges

def check_anynet_connected(path: str | Path) -> tuple[bool, int, int]:
    """(strongly_connected, n_routers, n_unreached) over DECLARED directions.

    BookSim builds an all-pairs routing table, so a router that cannot be
    reached from every other makes ``AnyNet::route`` spin forever. The gate
    is therefore STRONG connectivity of the declared direction graph, not
    the undirected union (which would call a one-way link connected). A
    directed graph is strongly connected iff router 0 reaches every router
    and every router reaches router 0, so two BFS passes suffice. Files with
    no declared directions (legacy/symmetric) use the undirected union.

    Unreadable/empty files yield (False, 0, 0) — callers report 'no routers
    parsed' rather than crashing.
    """
    try:
        g = parse_anynet_file(path)
    except (OSError, AnynetError):
        return False, 0, 0
    n = g.n_routers
    if n == 0:
        return False, 0, 0
    forward = g.router_directed or g.router_adj
    reverse: dict[int, set[int]] = {}
    for src, dsts in forward.items():
        for dst in dsts:
            reverse.setdefault(dst, set()).add(src)

    def _reach(adj: dict[int, set[int]]) -> int:
        seen = {0}
        frontier = [0]
        while frontier:
            nxt = []
            for u in frontier:
                for v in adj.get(u, ()):
                    if v not in seen:
                        seen.add(v)
                        nxt.append(v)
            frontier = nxt
        return len(seen)

    reached = min(_reach(forward), _reach(reverse))
    return reached == n, n, n - reached
