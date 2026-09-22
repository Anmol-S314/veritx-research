"""route_artifact.py — one content-addressed router-level routing truth.

Routing must not be re-derived independently by each consumer. This module
materializes the routing replica into a versioned, content-addressed artifact
that downstream consumers reference by hash.

Schema v2 makes the ROUTING CLASS an explicit axis and realizes every route
as an exact hardware resource:

    routing_classes  canonical RoutingClassDefinition list
                     (id, algorithm, algorithm_version, parameters)
    entries          (routing_class_id, src_router, dst_router) -> channel_id

The exact table is execution authority. The class definition says what was
intended/derived; it never grants PASS by itself.

Identity vs transport:

  topology_hash     content identity of the parent TopologyArtifact
  route_table_hash  hash over routing_classes + entries ONLY — verifiable
                    without trusting provenance
  artifact_hash     hash over the full semantic envelope
  provenance        explanation text, transported but NOT hashed

Fail-closed at construction and parent validation: unknown algorithms,
disconnected graphs, non-integer resources, missing/extra coverage, a first
channel that does not leave src, non-adjacent channels, and whole-route
termination for every (class, src, dst) — a table can pick a legal first
channel for every pair and still loop forever.

Schema v1 ((src, dst) -> next_router, no class axis, no resource ids) is
REFUSED on the authoritative path; there is no silent migration.

DOR_XY is a non-wrap 2D-grid class: dimension order x then y,
wraparound=false. Torus/ring geometries are UNSUPPORTED for DOR_XY —
wraparound minimal routing is a different semantics with a different
deadlock theorem and gets its own class later.
"""
from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from dataclasses import dataclass, field
from types import MappingProxyType
from typing import Any

_SCHEMA_VERSION = 2
_HASH_TYPE_TAG = "srota/RouteArtifact"

ROUTING_ALGORITHM = "anynet_dijkstra_hops"

# AnyNet::route() tie-breaks, exactly as replicated in
# booksim_first_hop_table (anynet.cpp: ascending std::set rlist, first
# strict minimum; strict `<` relaxation so the first predecessor sticks;
# neighbors iterated ascending via std::map).
TIE_BREAK_POLICY = (
    "anynet.cpp exact: ascending candidate scan keeps first strict "
    "minimum; strict-< relaxation keeps first predecessor; ascending "
    "neighbor iteration (std::set/std::map order)"
)

# The routing-class namespace. Stable ids, not free-form labels.
ANYNET_MIN_HOPS = "ANYNET_MIN_HOPS"
DOR_XY = "DOR_XY"

# Materialization from a topology chooses the lowest channel id when a hop
# has parallel links; the choice is declared in the class parameters so it
# is part of routing identity, never silent.
_PARALLEL_REALIZATION = "min_channel_id"


class RouteArtifactError(ValueError):
    """The routing truth cannot be represented or trusted — fail closed."""


# ── hashing / graph helpers ──────────────────────────────────────────────

def _sha256_of(obj: Any) -> str:
    payload = json.dumps(obj, sort_keys=True, separators=(",", ":"),
                         ensure_ascii=True).encode()
    return "sha256:" + hashlib.sha256(payload).hexdigest()


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


def _anynet_replica_first_hops(
        n: int, adj: dict[int, set[int]]) -> dict[tuple[int, int], int]:
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
                continue                  # unreachable: callers gate
            v = t
            while prev[v] != s:
                v = prev[v]
            fh[(s, t)] = v
    return fh


def _route_entries_from_adj(
        adj: dict[int, set[int]]) -> dict[tuple[int, int], int]:
    """The one routing truth: AnyNet::route() first-hop table, all-pairs.

    Returns a next-ROUTER table (the algorithm's output). Callers that
    need hardware resources go through RouteArtifact, which maps each hop
    to an exact channel id. Disconnected graphs are refused here too —
    the public helper must fail closed exactly like the constructor, or
    it would hand out a partial table that looks like a route artifact.
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


def _freeze(value: Any) -> Any:
    """JSON-shaped input -> hashable canonical value (lists -> tuples)."""
    if isinstance(value, list):
        return tuple(_freeze(v) for v in value)
    if isinstance(value, dict):
        return tuple((k, _freeze(v)) for k, v in sorted(value.items()))
    return value


# ── routing classes ──────────────────────────────────────────────────────

@dataclass(frozen=True)
class RoutingClassDefinition:
    """Canonical definition of one routing class.

    The definition explains intent/derivation; the materialized entries in
    RouteArtifact are execution authority. Theorem scaffolding may later
    prove ``entries conform to definition`` + ``theorem applies``, never
    ``algorithm == 'DOR' therefore trust me''.
    """

    id: str
    algorithm: str
    algorithm_version: int
    parameters: tuple[tuple[str, Any], ...] = ()

    def __post_init__(self):
        for name in ("id", "algorithm"):
            value = getattr(self, name)
            if not isinstance(value, str) or not value:
                raise RouteArtifactError(
                    f"routing class {name} must be a non-empty string")
        if type(self.algorithm_version) is not int \
                or self.algorithm_version < 1:
            raise RouteArtifactError(
                "routing class algorithm_version must be a positive int")
        if not isinstance(self.parameters, tuple):
            raise RouteArtifactError(
                "routing class parameters must be a tuple of (name, value)")
        seen: set[str] = set()
        for item in self.parameters:
            if not isinstance(item, tuple) or len(item) != 2:
                raise RouteArtifactError(
                    "routing class parameters entries must be (name, value)")
            key = item[0]
            if not isinstance(key, str) or not key:
                raise RouteArtifactError(
                    "routing class parameter names must be non-empty strings")
            if key in seen:
                raise RouteArtifactError(
                    f"routing class parameter {key!r} declared twice")
            seen.add(key)
        # Defensive freeze: no caller-owned list/dict may survive inside a
        # sealed routing-class definition.
        object.__setattr__(
            self, "parameters",
            tuple((k, _freeze(v)) for k, v in self.parameters))
        try:
            json.dumps(self.parameters_dict(), sort_keys=True,
                       ensure_ascii=True)
        except (TypeError, ValueError) as exc:
            raise RouteArtifactError(
                f"routing class parameters are not JSON-serializable: "
                f"{exc}") from exc

    def parameters_dict(self) -> dict[str, Any]:
        return dict(self.parameters)

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "algorithm": self.algorithm,
            "algorithm_version": self.algorithm_version,
            "parameters": {k: v for k, v in self.parameters},
        }

    @classmethod
    def from_dict(cls, d: Any) -> "RoutingClassDefinition":
        if not isinstance(d, dict):
            raise RouteArtifactError(
                "routing class definition must be an object")
        allowed = {"id", "algorithm", "algorithm_version", "parameters"}
        unknown = set(d) - allowed
        if unknown:
            raise RouteArtifactError(
                f"routing class has unknown fields: {sorted(unknown)}")
        for key in allowed:
            if key not in d:
                raise RouteArtifactError(
                    f"routing class is missing required field {key!r}")
        raw = d["parameters"]
        if not isinstance(raw, dict):
            raise RouteArtifactError(
                "routing class parameters must be an object")
        return cls(id=d["id"], algorithm=d["algorithm"],
                   algorithm_version=d["algorithm_version"],
                   parameters=tuple((k, _freeze(v))
                                    for k, v in sorted(raw.items())))


ANYNET_MIN_HOPS_DEFINITION = RoutingClassDefinition(
    id=ANYNET_MIN_HOPS,
    algorithm=ROUTING_ALGORITHM,
    algorithm_version=1,
    parameters=(
        ("tie_break_policy", TIE_BREAK_POLICY),
        ("parallel_hop_realization", _PARALLEL_REALIZATION),
    ),
)

DOR_XY_DEFINITION = RoutingClassDefinition(
    id=DOR_XY,
    algorithm="dimension_order",
    algorithm_version=1,
    parameters=(
        ("dimension_order", ("x", "y")),
        ("wraparound", False),
    ),
)

_KNOWN_CLASSES = {
    ANYNET_MIN_HOPS: ANYNET_MIN_HOPS_DEFINITION,
    DOR_XY: DOR_XY_DEFINITION,
}


def _resolve_definition(class_or_id: Any) -> RoutingClassDefinition:
    if isinstance(class_or_id, RoutingClassDefinition):
        return class_or_id
    if isinstance(class_or_id, str):
        known = _KNOWN_CLASSES.get(class_or_id)
        if known is None:
            raise RouteArtifactError(
                f"unknown routing class {class_or_id!r}; known: "
                f"{sorted(_KNOWN_CLASSES)}")
        return known
    raise RouteArtifactError(
        f"routing class must be an id or RoutingClassDefinition, got "
        f"{type(class_or_id).__name__}")


# ── materializers (definition -> exact entries) ──────────────────────────

def _channels_by_hop(topology) -> dict[tuple[int, int], list[int]]:
    hops: dict[tuple[int, int], list[int]] = {}
    for ch in topology.channels:
        hops.setdefault((ch.src_router, ch.dst_router), []).append(
            ch.channel_id)
    for key in hops:
        hops[key].sort()
    return hops


def _anynet_channel_entries(topology) -> dict[tuple[int, int], int]:
    """ANYNET_MIN_HOPS realized against this topology.

    Parallel hops use the class-declared ``min_channel_id`` realization
    (recorded in the class parameters, hence in routing identity).
    """
    adj: dict[int, set[int]] = {r.router_id: set() for r in topology.routers}
    for c in topology.channels:
        adj[c.src_router].add(c.dst_router)
    hop = _route_entries_from_adj(adj)
    by_hop = _channels_by_hop(topology)
    out: dict[tuple[int, int], int] = {}
    for (s, t), nxt in hop.items():
        ids = by_hop.get((s, nxt), [])
        if not ids:
            raise RouteArtifactError(
                f"ANYNET_MIN_HOPS realizes ({s},{t}) via next router {nxt}, "
                f"but the topology has no directed channel {s}->{nxt}")
        out[(s, t)] = min(ids)
    return out


def _dor_xy_channel_entries(topology) -> dict[tuple[int, int], int]:
    """DOR_XY realized against a canonical non-wrap 2D grid.

    Semantics are exact: consume X displacement first, then Y. A router
    with a coordinate mismatch in X steps toward dx; otherwise it steps
    toward dy. Wraparound is NOT this class: non-adjacent (wrap/diagonal)
    channels and parallel hops are UNSUPPORTED, never approximated.
    """
    family = getattr(topology, "family", None)
    family_value = getattr(family, "value", family)
    if family_value not in ("mesh", "concentrated_mesh"):
        raise RouteArtifactError(
            f"UNSUPPORTED: DOR_XY requires a non-wrap 2D mesh or "
            f"concentrated mesh, got family={family_value!r} "
            "(torus/ring wraparound is a different routing class)")

    coord_of: dict[int, tuple[int, int]] = {}
    for r in topology.routers:
        coords = r.coordinates
        if len(coords) != 2:
            raise RouteArtifactError(
                f"UNSUPPORTED: DOR_XY requires 2D coordinates, router "
                f"{r.router_id} has {coords!r}")
        coord_of[r.router_id] = (coords[0], coords[1])
    if len(set(coord_of.values())) != len(coord_of):
        raise RouteArtifactError(
            "UNSUPPORTED: DOR_XY requires unique router coordinates")
    max_x = max(c[0] for c in coord_of.values())
    max_y = max(c[1] for c in coord_of.values())
    if len(coord_of) != (max_x + 1) * (max_y + 1):
        raise RouteArtifactError(
            "UNSUPPORTED: DOR_XY requires a full rectangular grid "
            f"({max_x + 1}x{max_y + 1}) with no holes")
    id_of = {c: r for r, c in coord_of.items()}

    def adjacent(a: tuple[int, int], b: tuple[int, int]) -> bool:
        return abs(a[0] - b[0]) + abs(a[1] - b[1]) == 1

    by_hop = _channels_by_hop(topology)
    for (src, dst) in by_hop:
        if not adjacent(coord_of[src], coord_of[dst]):
            raise RouteArtifactError(
                f"UNSUPPORTED: DOR_XY refuses non-adjacent/wraparound "
                f"channel {src}->{dst} "
                f"({coord_of[src]}->{coord_of[dst]})")

    out: dict[tuple[int, int], int] = {}
    for src, (x, y) in coord_of.items():
        for dst, (dx, dy) in coord_of.items():
            if src == dst:
                continue
            if x != dx:
                step = (x + (1 if dx > x else -1), y)
            else:
                step = (x, y + (1 if dy > y else -1))
            nbr = id_of[step]
            ids = by_hop.get((src, nbr), [])
            if len(ids) != 1:
                raise RouteArtifactError(
                    f"UNSUPPORTED: DOR_XY hop {src}->{nbr} is ambiguous: "
                    f"channels {sorted(ids)} (DOR_XY requires exactly one "
                    "directed channel per grid hop)")
            out[(src, dst)] = ids[0]
    return out


# ── the artifact ─────────────────────────────────────────────────────────

@dataclass(frozen=True)
class RouteArtifact:
    """Versioned, content-addressed exact per-class channel routing."""

    schema_version: int
    name: str
    topology_hash: str
    routing_classes: tuple[RoutingClassDefinition, ...]
    entries: dict[tuple[str, int, int], int] = field(default_factory=dict)
    provenance: str = ""
    route_table_hash: str = ""
    artifact_hash: str = ""

    def __post_init__(self):
        if type(self.schema_version) is not int or \
                self.schema_version != _SCHEMA_VERSION:
            raise RouteArtifactError(
                f"unsupported route-artifact schema_version "
                f"{self.schema_version!r} (expected {_SCHEMA_VERSION})")
        if not isinstance(self.name, str):
            raise RouteArtifactError("name must be a string")
        if not isinstance(self.topology_hash, str) or not self.topology_hash:
            raise RouteArtifactError(
                "topology_hash must be a non-empty string")
        if not isinstance(self.routing_classes, tuple) \
                or not self.routing_classes:
            raise RouteArtifactError("routing_classes must be a non-empty tuple")
        for definition in self.routing_classes:
            if not isinstance(definition, RoutingClassDefinition):
                raise RouteArtifactError(
                    "routing_classes must contain RoutingClassDefinition")
        ids = [d.id for d in self.routing_classes]
        if len(set(ids)) != len(ids):
            raise RouteArtifactError(
                "routing class ids must be unique (class order is semantic: "
                "the first class is the default)")
        if not isinstance(self.entries, Mapping):
            raise RouteArtifactError("entries must be an object")
        declared = set(ids)
        for key, channel_id in self.entries.items():
            if not isinstance(key, tuple) or len(key) != 3:
                raise RouteArtifactError(
                    "entry keys must be (routing_class, src, dst) tuples")
            cls, src, dst = key
            if not isinstance(cls, str) or not isinstance(src, int) \
                    or not isinstance(dst, int) \
                    or isinstance(src, bool) or isinstance(dst, bool):
                raise RouteArtifactError(
                    f"entry key {key!r} must be (str, int, int)")
            if cls not in declared:
                raise RouteArtifactError(
                    f"entry {key!r} references undeclared routing class "
                    f"{cls!r}")
            if type(channel_id) is not int:
                raise RouteArtifactError(
                    f"entry {key!r} channel id {channel_id!r} must be an int")
        # Defensive copy + read-only view: mutating the caller's dict after
        # construction cannot change this artifact's sealed contents.
        object.__setattr__(self, "entries",
                           MappingProxyType(dict(self.entries)))
        if not isinstance(self.provenance, str):
            raise RouteArtifactError("provenance must be a string")
        expected_table = self._compute_route_table_hash()
        if self.route_table_hash and self.route_table_hash != expected_table:
            raise RouteArtifactError(
                "route_table_hash does not match routing classes + entries")
        if not self.route_table_hash:
            object.__setattr__(self, "route_table_hash", expected_table)
        expected_artifact = self._compute_artifact_hash()
        if self.artifact_hash and self.artifact_hash != expected_artifact:
            raise RouteArtifactError(
                "artifact_hash does not match content")
        if not self.artifact_hash:
            object.__setattr__(self, "artifact_hash", expected_artifact)

    # ── identity ───────────────────────────────────────────────────────
    def identity_dict(self) -> dict[str, Any]:
        """The semantic envelope that route_table_hash/artifact_hash cover.

        ``name`` is presentation and ``provenance`` is explanation: both
        are transported by to_dict() and excluded from identity.
        """
        return {
            "type": _HASH_TYPE_TAG,
            "schema_version": self.schema_version,
            "topology_hash": self.topology_hash,
            "routing_classes": [d.to_dict() for d in self.routing_classes],
            "entries": [[cls, s, t, ch] for (cls, s, t), ch
                        in sorted(self.entries.items())],
        }

    def _compute_route_table_hash(self) -> str:
        return _sha256_of({
            "routing_classes": [d.to_dict() for d in self.routing_classes],
            "entries": [[cls, s, t, ch] for (cls, s, t), ch
                        in sorted(self.entries.items())],
        })

    def _compute_artifact_hash(self) -> str:
        return _sha256_of({
            "schema_version": self.schema_version,
            "topology_hash": self.topology_hash,
            "route_table_hash": self.route_table_hash,
        })

    # ── construction: sanctioned paths ─────────────────────────────────
    @classmethod
    def from_topology(
        cls, topology, *, name: str,
        routing_classes: Any = (ANYNET_MIN_HOPS,),
        entries: dict[tuple[str, int, int], int] | None = None,
    ) -> "RouteArtifact":
        """Materialize the requested classes against a TopologyArtifact.

        ``topology_hash`` is ``TopologyArtifact.topology_hash()`` EXACTLY;
        this artifact must not carry a second, differently-defined digest
        under the same name.
        """
        if isinstance(routing_classes, (str, RoutingClassDefinition)):
            routing_classes = (routing_classes,)
        definitions = tuple(_resolve_definition(c) for c in routing_classes)
        if entries is None:
            materialized: dict[tuple[str, int, int], int] = {}
            for definition in definitions:
                if definition.id == ANYNET_MIN_HOPS:
                    table = _anynet_channel_entries(topology)
                elif definition.id == DOR_XY:
                    table = _dor_xy_channel_entries(topology)
                else:
                    raise RouteArtifactError(
                        f"no materializer for routing class "
                        f"{definition.id!r} (algorithm "
                        f"{definition.algorithm!r})")
                for (s, t), ch in table.items():
                    materialized[(definition.id, s, t)] = ch
            entries = materialized
        artifact = cls(
            schema_version=_SCHEMA_VERSION,
            name=name,
            topology_hash=topology.topology_hash(),
            routing_classes=definitions,
            entries=dict(entries),
        )
        artifact.validate_against(topology)
        return artifact

    # ── parent validation ──────────────────────────────────────────────
    def _validate_channels(self, channel_by_id: dict[int, Any],
                           router_count: int) -> None:
        declared = [d.id for d in self.routing_classes]
        expected = {(cid, s, t) for cid in declared
                    for s in range(router_count)
                    for t in range(router_count) if s != t}
        got = set(self.entries)
        missing = expected - got
        if missing:
            raise RouteArtifactError(
                f"entries do not cover every routing class x router pair: "
                f"missing {len(missing)}, e.g. {sorted(missing)[:3]}")
        extra = got - expected
        if extra:
            raise RouteArtifactError(
                f"entries contain pairs outside the topology: "
                f"e.g. {sorted(extra)[:3]}")
        for cid in declared:
            # Functional-graph reachability per destination: every src must
            # reach dst without revisiting a router. Legal first hops are
            # not enough — a table can loop forever (R0->R2 via R1 and
            # R1->R2 via R0).
            for dst in range(router_count):
                color = [0] * router_count      # 0 open, 1 in-path, 2 done
                color[dst] = 2
                for src in range(router_count):
                    if src == dst or color[src] == 2:
                        continue
                    path: list[int] = []
                    cur = src
                    while color[cur] == 0:
                        color[cur] = 1
                        path.append(cur)
                        ch_id = self.entries[(cid, cur, dst)]
                        ch = channel_by_id.get(ch_id)
                        if ch is None:
                            raise RouteArtifactError(
                                f"({cid},{cur},{dst}): channel {ch_id} does "
                                "not exist in the topology")
                        if ch.src_router != cur:
                            raise RouteArtifactError(
                                f"({cid},{cur},{dst}): channel {ch_id} "
                                f"leaves router {ch.src_router}, not {cur}")
                        cur = ch.dst_router
                        if not 0 <= cur < router_count:
                            raise RouteArtifactError(
                                f"({cid},{cur},{dst}): channel {ch_id} "
                                f"reaches router {cur} outside the topology")
                    if color[cur] == 1:
                        start = path.index(cur)
                        raise RouteArtifactError(
                            f"({cid}) routing loop for destination {dst}: "
                            f"{path[start:] + [cur]} — a table may look "
                            "locally legal and still never terminate")
                    for node in path:
                        color[node] = 2

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
        self._validate_channels(
            {c.channel_id: c for c in topology.channels},
            topology.router_count)

    # ── serialization ─────────────────────────────────────────────────
    def serialize(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "name": self.name,
            "topology_hash": self.topology_hash,
            "routing_classes": [d.to_dict() for d in self.routing_classes],
            "entries": {f"{cls}|{s}|{t}": ch
                        for (cls, s, t), ch in sorted(self.entries.items())},
            "provenance": self.provenance,
            "route_table_hash": self.route_table_hash,
            "artifact_hash": self.artifact_hash,
        }

    def to_dict(self) -> dict[str, Any]:
        return self.serialize()

    @classmethod
    def from_dict(cls, d: Any) -> "RouteArtifact":
        """Load serialized v2; re-verifies every hash (tamper-evident).

        Self-integrity ONLY: call ``validate_against(topology)`` to prove
        channel legality and whole-route termination against a parent.
        Schema v1 is refused here — migration is explicit.
        """
        if not isinstance(d, dict):
            raise RouteArtifactError("route artifact must be an object")
        if d.get("schema_version") == 1:
            raise RouteArtifactError(
                "RouteArtifact schema v1 is refused on the authoritative "
                "path (it has no routing-class axis and no exact channel "
                "realization); there is no silent migration")
        allowed = {"schema_version", "name", "topology_hash",
                   "routing_classes", "entries", "provenance",
                   "route_table_hash", "artifact_hash"}
        unknown = set(d) - allowed
        if unknown:
            raise RouteArtifactError(
                f"route artifact has unknown fields: {sorted(unknown)}")
        for key in allowed - {"provenance"}:
            if key not in d:
                raise RouteArtifactError(
                    f"route artifact is missing required field {key!r}")
        classes = d["routing_classes"]
        if not isinstance(classes, list) or not classes:
            raise RouteArtifactError(
                "routing_classes must be a non-empty list")
        definitions = tuple(RoutingClassDefinition.from_dict(c)
                            for c in classes)
        declared = {defn.id for defn in definitions}
        raw_entries = d["entries"]
        if not isinstance(raw_entries, dict):
            raise RouteArtifactError("entries must be an object")
        entries: dict[tuple[str, int, int], int] = {}
        for key, value in raw_entries.items():
            parts = key.split("|")
            if len(parts) != 3:
                raise RouteArtifactError(
                    f"entry key {key!r} must be 'class|src|dst'")
            rid, s_raw, t_raw = parts
            if rid not in declared:
                raise RouteArtifactError(
                    f"entry {key!r} references undeclared routing class "
                    f"{rid!r}")
            try:
                s, t = int(s_raw), int(t_raw)
            except ValueError as exc:
                raise RouteArtifactError(
                    f"entry key {key!r} has non-integer router ids") from exc
            if type(value) is not int:
                raise RouteArtifactError(
                    f"entry {key!r} channel id {value!r} must be an int")
            entries[(rid, s, t)] = value
        return cls(
            schema_version=d["schema_version"],
            name=d["name"],
            topology_hash=d["topology_hash"],
            routing_classes=definitions,
            entries=entries,
            provenance=d.get("provenance", ""),
            route_table_hash=d["route_table_hash"],
            artifact_hash=d["artifact_hash"],
        )
