"""route_artifact.py — one content-addressed routing truth (Phase 10).

The program (§14): no subsystem should independently reinterpret the
routing algorithm and merely hope it agrees. The certifier already
replicates AnyNet::route() hop-for-hop (documented tie-breaks); this
module promotes that replica into a versioned, content-addressed
artifact that downstream consumers (F6 verification now; BookSim/RTL
eventually) reference by hash.

Identity vs transport (the Phase-9 lesson, applied):

  topology_hash      hash over the CANONICAL graph serialization
                     (sorted adjacency), not raw file bytes — comment
                     and whitespace noise must not alter identity
  routing_algorithm  the EXECUTED semantics ("anynet_dijkstra_hops"),
                     not the design label ("dor", "dim_order", ...)
  tie_break_policy   the documented AnyNet tie-break string
  entries            {(src,dst): next_hop} — first hop after src,
                     all-pairs minus diagonal (the AnyNet contract)
  route_table_hash   hash over entries ONLY: the hash a consumer
                     (BookSim/RTL) can verify against without trusting
                     the rest of the artifact
  artifact_hash      hash over the full identity dict

Fail-closed at construction: weighted topologies are refused (PR D —
the replica is hop-count based, so certifying a weighted graph would
certify route set A while BookSim executes route set B), disconnected
graphs are refused, entries must have exact all-pairs coverage with
next hops that are actual neighbors. The per-class axis is deferred to
schema v2 with the VC artifact (§14: no VC-aware deadlock claims while
only physical channels are checked).
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from typing import Any

ROUTING_ALGORITHM = "anynet_dijkstra_hops"

# AnyNet::route() tie-breaks, exactly as replicated in
# booksim_first_hop_table (anynet.cpp: ascending std::set rlist, first
# strict minimum; strict `<` relaxation so the first predecessor
# sticks; neighbors iterated ascending via std::map).
TIE_BREAK_POLICY = (
    "anynet.cpp exact: ascending candidate scan keeps first strict "
    "minimum; strict-< relaxation keeps first predecessor; ascending "
    "neighbor iteration (std::set/std::map order)"
)

_SCHEMA_VERSION = 1


class RouteArtifactError(ValueError):
    """The routing truth cannot be represented or trusted — fail closed."""


def _sha256_of(obj: Any) -> str:
    payload = json.dumps(obj, sort_keys=True, separators=(",", ":"),
                         ensure_ascii=True).encode()
    return "sha256:" + hashlib.sha256(payload).hexdigest()


def _canonical_adjacency(adj: dict[int, set[int]]) -> list[list[int]]:
    return [[int(v) for v in sorted(adj[k])] for k in sorted(adj)]


def topology_hash_from_adj(adj: dict[int, set[int]]) -> str:
    """Content identity of the routed graph: canonical serialization."""
    return _sha256_of({"kind": "anynet_router_graph",
                       "adjacency": _canonical_adjacency(adj)})


# Naming (Wave B3.2): a standalone AnyNet graph has no TopologyArtifact, so
# this digest is a ROUTING-GRAPH hash, not a fabric topology identity. New
# code binds through RouteArtifact.from_topology(); the column rename to
# ``routing_graph_hash`` lands with the schema v2 route artifact (B3.2d).
routing_graph_hash_from_adj = topology_hash_from_adj


def _anynet_replica_first_hops(n: int,
                               adj: dict[int, set[int]]) -> dict[tuple[int, int], int]:
    """The first-hop table BookSim's AnyNet actually builds — replicated
    exactly from AnyNet::route() (networks/anynet.cpp), because the
    certifier must evaluate the SAME routes the simulator executes.

    Tie-break semantics, from the C++ source:
      * candidate scan is over std::set<int> rlist (ascending) keeping the
        FIRST strict minimum -> min() over an ascending list;
      * relaxation uses strict `<` -> the first predecessor sticks;
      * neighbor iteration is std::map (ascending id).
    All-pairs (BookSim's table covers every destination regardless of T),
    so the CDG check is a conservative superset of any traffic pattern.
    Returns {(s,t): next_hop_after_s}.
    """
    fh = {}
    INF = float("inf")
    for s in range(n):
        dist = [INF] * n
        prev = [-1] * n
        dist[s] = 0
        rlist = list(range(n))            # std::set<int>: ascending
        while rlist:
            u = min(rlist, key=lambda x: dist[x])   # first strict min wins
            rlist.remove(u)
            for v in sorted(adj[u]):      # std::map: ascending neighbors
                nd = dist[u] + 1          # distance is hops (anynet.cpp)
                if nd < dist[v]:          # strict: first predecessor sticks
                    dist[v] = nd
                    prev[v] = u
        for t in range(n):
            if t == s or dist[t] == INF:
                continue                  # unreachable: callers gate on connectivity
            v = t
            while prev[v] != s:
                v = prev[v]
            fh[(s, t)] = v
    return fh


def route_entries_from_adj(adj: dict[int, set[int]]) -> dict[tuple[int, int], int]:
    """The one routing truth: AnyNet::route() first-hop table, all-pairs.

    Delegates to the exact replica (tie-breaks documented there); the
    adjacency is normalized to range(n) first, matching BookSim's
    sequential-id requirement. Disconnected graphs are refused here too —
    the public helper must fail closed exactly like the constructor, or it
    would hand out a partial table that looks like a route artifact.
    """
    n = max(adj) + 1 if adj else 0
    if sorted(adj) != list(range(n)):
        raise RouteArtifactError(
            "router ids not sequential 0..n-1 — BookSim requires it")
    if not _is_connected(adj, n):
        raise RouteArtifactError(
            "topology is disconnected — a partial first-hop table is not a "
            "route artifact (use a diagnostic helper, never this one)")
    return dict(_anynet_replica_first_hops(n, adj))


@dataclass(frozen=True)
class RouteArtifact:
    """Versioned, content-addressed exact next-hop routing behavior."""
    schema_version: int
    name: str
    topology_hash: str
    routing_algorithm: str
    tie_break_policy: str
    entries: dict[tuple[int, int], int] = field(default_factory=dict)
    route_table_hash: str = ""
    artifact_hash: str = ""

    # ── construction ──────────────────────────────────────────────────
    @classmethod
    def from_adjacency(
        cls, adj: dict[int, set[int]], *, name: str,
        routing_algorithm: str = ROUTING_ALGORITHM,
        entries: dict[tuple[int, int], int] | None = None,
        weights: dict[tuple[int, int], float] | None = None,
    ) -> "RouteArtifact":
        if routing_algorithm != ROUTING_ALGORITHM:
            raise RouteArtifactError(
                f"routing_algorithm {routing_algorithm!r} unsupported — "
                f"the certified executed semantics are "
                f"{ROUTING_ALGORITHM!r} (fail-closed)")
        if weights:
            raise RouteArtifactError(
                "weighted topologies are refused on the certification "
                "path (PR D): the route replica is hop-count based, so "
                "a weighted graph would certify route set A while "
                "BookSim executes route set B")
        if not adj:
            raise RouteArtifactError("empty adjacency — nothing to route")
        n = max(adj) + 1
        if sorted(adj) != list(range(n)):
            raise RouteArtifactError(
                f"router ids not sequential 0..{n - 1} — BookSim "
                "requires sequential ids starting with 0")
        if not _is_connected(adj, n):
            raise RouteArtifactError(
                "topology is disconnected — routing cannot be total; "
                "certifying a partial table would lie about coverage")
        if entries is None:
            entries = route_entries_from_adj(adj)
        # per-entry legality first (names the offending flow), then
        # exact all-pairs coverage
        _validate_entries(adj, entries)
        thash = topology_hash_from_adj(adj)
        ttable = _sha256_of({"entries": _canon_entries(entries)})
        ahash = _sha256_of({
            "schema_version": _SCHEMA_VERSION,
            "topology_hash": thash,
            "routing_algorithm": routing_algorithm,
            "tie_break_policy": TIE_BREAK_POLICY,
            "route_table_hash": ttable,
        })
        return cls(schema_version=_SCHEMA_VERSION, name=name,
                   topology_hash=thash, routing_algorithm=routing_algorithm,
                   tie_break_policy=TIE_BREAK_POLICY,
                   entries=dict(entries), route_table_hash=ttable,
                   artifact_hash=ahash)

    @classmethod
    def from_topology(cls, topology, *, name: str,
                      entries: dict[tuple[int, int], int] | None = None,
                      routing_algorithm: str = ROUTING_ALGORITHM
                      ) -> "RouteArtifact":
        """Authoritative router routing bound to a materialized TopologyArtifact.

        ``topology_hash`` is ``TopologyArtifact.topology_hash()`` EXACTLY —
        after B3.1 there is one topology identity, and this artifact must not
        carry a second, differently-defined digest of the same name.
        """
        adj: dict[int, set[int]] = {r.router_id: set() for r in topology.routers}
        for c in topology.channels:
            adj[c.src_router].add(c.dst_router)
        art = cls.from_adjacency(adj, name=name,
                                 routing_algorithm=routing_algorithm,
                                 entries=entries)
        thash = topology.topology_hash()
        ahash = _sha256_of({
            "schema_version": art.schema_version,
            "topology_hash": thash,
            "routing_algorithm": art.routing_algorithm,
            "tie_break_policy": art.tie_break_policy,
            "route_table_hash": art.route_table_hash,
        })
        bound = cls(schema_version=art.schema_version, name=art.name,
                    topology_hash=thash,
                    routing_algorithm=art.routing_algorithm,
                    tie_break_policy=art.tie_break_policy,
                    entries=art.entries,
                    route_table_hash=art.route_table_hash,
                    artifact_hash=ahash)
        bound.validate_against(topology)
        return bound

    def validate_against(self, topology) -> None:
        """Parent legality against the materialized TopologyArtifact.

        Deliberately separate from from_dict (self-integrity): a child can
        prove it was not tampered with without possessing its parent; the
        seam proves its references are legal.
        """
        if self.topology_hash != topology.topology_hash():
            raise RouteArtifactError(
                "topology_hash does not match the materialized topology "
                "(standalone routing-graph digests are not fabric identities)")
        channels = {(c.src_router, c.dst_router) for c in topology.channels}
        for (s, t), nh in sorted(self.entries.items()):
            if (s, nh) not in channels:
                raise RouteArtifactError(
                    f"({s},{t}): next hop {nh} is not a directed channel in "
                    "the materialized topology")
        expected = {(s, t) for s in range(topology.router_count)
                    for t in range(topology.router_count) if s != t}
        if set(self.entries) != expected:
            raise RouteArtifactError(
                "entries do not cover all router pairs of the materialized "
                "topology (partial tables are not authoritative artifacts)")

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "RouteArtifact":
        """Load serialized form; re-verifies every hash (tamper-evident).

        ``name`` is presentation (excluded from artifact_hash), but it
        must still roundtrip: consumers key run artifacts by it.
        """
        try:
            art = cls(
                schema_version=int(d["schema_version"]),
                name=d["name"],
                topology_hash=d["topology_hash"],
                routing_algorithm=d["routing_algorithm"],
                tie_break_policy=d["tie_break_policy"],
                entries={tuple(map(int, k.split("|"))): int(v)
                         for k, v in d["entries"].items()},
                route_table_hash=d["route_table_hash"],
                artifact_hash=d["artifact_hash"],
            )
        except (KeyError, ValueError, TypeError) as e:
            raise RouteArtifactError(f"malformed RouteArtifact: {e}") from e
        if art.schema_version != _SCHEMA_VERSION:
            raise RouteArtifactError(
                f"schema_version {art.schema_version} unsupported "
                f"(expected {_SCHEMA_VERSION})")
        if art.routing_algorithm != ROUTING_ALGORITHM:
            raise RouteArtifactError(
                f"routing_algorithm {art.routing_algorithm!r} unsupported")
        ttable = _sha256_of({"entries": _canon_entries(art.entries)})
        if ttable != art.route_table_hash:
            raise RouteArtifactError(
                f"route_table_hash mismatch: recorded {art.route_table_hash} "
                f"but entries hash to {ttable} — the table was tampered "
                "with or corrupted")
        ahash = _sha256_of({
            "schema_version": art.schema_version,
            "topology_hash": art.topology_hash,
            "routing_algorithm": art.routing_algorithm,
            "tie_break_policy": art.tie_break_policy,
            "route_table_hash": art.route_table_hash,
        })
        if ahash != art.artifact_hash:
            raise RouteArtifactError(
                f"artifact_hash mismatch: recorded {art.artifact_hash} but "
                f"fields hash to {ahash} — the artifact was tampered with")
        return art

    # ── serialization ─────────────────────────────────────────────────
    def serialize(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "name": self.name,
            "topology_hash": self.topology_hash,
            "routing_algorithm": self.routing_algorithm,
            "tie_break_policy": self.tie_break_policy,
            "entries": {f"{s}|{t}": nh
                        for (s, t), nh in sorted(self.entries.items())},
            "route_table_hash": self.route_table_hash,
            "artifact_hash": self.artifact_hash,
        }

    def to_dict(self) -> dict[str, Any]:
        return self.serialize()


def _canon_entries(entries: dict[tuple[int, int], int]) -> list[list[int]]:
    return [[s, t, nh] for (s, t), nh in sorted(entries.items())]


def _is_connected(adj: dict[int, set[int]], n: int) -> bool:
    if n == 0:
        return False
    seen = {0}
    q = [0]
    while q:
        u = q.pop()
        for v in adj.get(u, ()):
            if v not in seen:
                seen.add(v)
                q.append(v)
    return len(seen) == n


def _validate_entries(adj: dict[int, set[int]],
                      entries: dict[tuple[int, int], int]) -> None:
    n = max(adj) + 1
    for (s, t), nh in sorted(entries.items()):
        if not isinstance(nh, int) or isinstance(nh, bool):
            raise RouteArtifactError(
                f"({s},{t}): next hop {nh!r} is not an integer")
        if not (0 <= nh < n):
            raise RouteArtifactError(
                f"({s},{t}): next hop {nh} out of range [0, {n})")
        if nh == s or nh not in adj.get(s, set()):
            raise RouteArtifactError(
                f"({s},{t}): next hop {nh} is not a neighbor of {s} — "
                "a next hop must be an adjacent router")
    expected = {(s, t) for s in range(n) for t in range(n) if s != t}
    got = set(entries)
    missing = expected - got
    if missing:
        raise RouteArtifactError(
            f"entries do not cover all-pairs: missing {len(missing)} "
            f"flows, e.g. {sorted(missing)[:3]} — a partial table lies "
            "about coverage (fail-closed)")
    extra = got - expected
    if extra:
        raise RouteArtifactError(
            f"entries contain non-all-pairs flows, e.g. {sorted(extra)[:3]}")


def artifact_from_anynet(g, *, name: str) -> RouteArtifact:
    """Build the artifact from a parsed anynet graph (core/anynet.py).

    Weighted topologies are refused here (PR D): the parser records
    non-unit weights, and the replica is hop-count based.
    """
    if getattr(g, "has_non_unit_weights", False):
        raise RouteArtifactError(
            "weighted anynet refused (PR D): certified routes would not "
            "be executed routes; weights must flow through the replica "
            "end-to-end before weighted certification exists")
    return RouteArtifact.from_adjacency(g.sequential_adj(), name=name)


def equivalence_report(artifact: RouteArtifact,
                       executed: dict[tuple[int, int], int]) -> dict[str, Any]:
    """Compare the artifact against an executed first-hop table.

    Every difference stays visible with pinned per-flow diagnostics;
    missing/extra flows are first-class findings, never silently
    dropped (the Phase-8 failure-visibility rule, applied to routing).
    """
    a, e = artifact.entries, dict(executed)
    mismatched, missing_in_executed, extra_in_executed = [], [], []
    for (s, t), nh in sorted(a.items()):
        if (s, t) not in e:
            missing_in_executed.append({"src": s, "dst": t,
                                        "artifact_next_hop": nh})
        elif e[(s, t)] != nh:
            mismatched.append({"src": s, "dst": t,
                               "artifact_next_hop": nh,
                               "executed_next_hop": e[(s, t)]})
    for (s, t), nh in sorted(e.items()):
        if (s, t) not in a:
            extra_in_executed.append({"src": s, "dst": t,
                                      "executed_next_hop": nh})
    ok = not (mismatched or missing_in_executed or extra_in_executed)
    return {
        "status": "COMPARABLE" if ok else "DIVERGENT",
        "routing_algorithm": artifact.routing_algorithm,
        "route_table_hash": artifact.route_table_hash,
        "coverage": {
            "artifact_flows": len(a),
            "executed_flows": len(e),
            "matched": len(a) - len(mismatched) - len(missing_in_executed),
        },
        "mismatched": mismatched,
        "missing_in_executed": missing_in_executed,
        "extra_in_executed": extra_in_executed,
        "entries": len(a),
    }
