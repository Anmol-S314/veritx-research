"""core/anynet.py — the ONE anynet links parser.

BookSim's `AnyNet::readFile` (third_party/booksim2/src/networks/anynet.cpp)
defines exactly one grammar, and this module implements it once. Everything
that reads .anynet/.links files delegates here — deadlock_routing, flow_certifier, presets — because three independent parsers had already
diverged: deadlock_routing dropped reverse edges (one-direction link files
parsed as DIRECTED graphs, silently corrupting CDG analysis), and
presets._parse_anynet_adj required >=5 tokens per line and peer-scanning
from index 4 (two-line link files yielded EMPTY adjacency → "disconnected").

The grammar (verified against anynet.cpp readFile, not guessed):

    line := head_type head_id (body_type body_id [weight])*
    head_type, body_type ∈ {router, node}     weight defaults to 1
    router↔router : a network edge — BookSym inserts the reverse channel
                    itself, so files may declare one direction or both
    node↔router   : node attachment; a node attaches to exactly ONE router
    node↔node     : invalid (BookSim asserts)

"Router and node numbers must be sequential starting with 0" (anynet.cpp
header) — we keep that as a documented precondition, same as upstream.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path


class AnynetError(ValueError):
    """Malformed anynet file — mirrors BookSim's assert-and-die, loudly."""


@dataclass
class AnynetGraph:
    """Parsed anynet: undirected router graph + node attachments.

    ``non_unit_weights`` records which lines carried a trailing weight token.
    PR D (verified-PRD §6.4): the certification replica computes hop-count
    distances, while BookSim's AnyNet Dijkstra uses the stored weight as the
    edge distance — on weighted topologies the certified route set is NOT
    the executed route set. Certification paths must therefore reject
    non-unit weights (fail-closed) until weights flow through the replica.
    """
    router_adj: dict[int, set[int]] = field(default_factory=dict)
    node_router: dict[int, int] = field(default_factory=dict)
    non_unit_weights: list[tuple[int, int]] = field(default_factory=list)

    @property
    def has_non_unit_weights(self) -> bool:
        return bool(self.non_unit_weights)

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
                continue  # anynet.cpp skips empties; comments by convention
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
        # optional weight token (LINK_WEIGHT state): any bare integer sets
        # the channel latency BookSim uses as edge distance. Recorded, not
        # folded into adjacency — PR D consumers enforce the policy.
        if i < len(toks) and toks[i] not in ("router", "node"):
            w = _int(toks[i], "weight")
            if w != 1:
                g.non_unit_weights.append((line_no, w))
            i += 1

        if head_kind == "router" and kind == "router":
            # BookSim symmetrizes: inserts the reverse channel if absent.
            g.router_adj.setdefault(body, set())
            g.router_adj[head].add(body)
            g.router_adj[body].add(head)
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


# ── derived helpers (the shapes every consumer wants) ────────────────────


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
    """(connected, n_routers, n_unreached) via BFS from router 0.

    BookSim hangs on disconnected graphs, so callers gate on this before
    any simulation. Unreadable/empty files yield (False, 0, 0) — callers
    report 'no routers parsed' rather than crashing.
    """
    try:
        g = parse_anynet_file(path)
    except (OSError, AnynetError):
        return False, 0, 0
    n = g.n_routers
    if n == 0:
        return False, 0, 0
    seen = {0}
    frontier = [0]
    while frontier:
        nxt = []
        for u in frontier:
            for v in g.router_adj[u]:
                if v not in seen:
                    seen.add(v)
                    nxt.append(v)
        frontier = nxt
    return len(seen) == n, n, n - len(seen)
