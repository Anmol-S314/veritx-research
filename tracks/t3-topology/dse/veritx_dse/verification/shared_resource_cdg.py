"""shared_resource_cdg — the dependency graph for fabrics with SHARED wires.

Why a second CDG builder instead of extending the existing one
--------------------------------------------------------------
``channel_vc_cdg`` is built on one assumption: a route step is an integer
``channel_id``, whose ``dst_router`` IS the router the packet reaches. Every
edge it adds depends on that. It also refuses topologies carrying shared
links for exactly this reason — which is correct, fail-closed behavior.

A shared wire breaks the assumption. The wire is the same for every
destination on it; only the TAP distinguishes them. So the resource of a hop
comes from a ``RouteDecision`` (resource + tap + landing router + partition),
not from a channel index.

This module is intentionally FAMILY-BLIND. It consumes decisions and a
partition->VCs map and produces a graph over CONCRETE ``(resource, vc)``
nodes. It knows nothing about rows, columns, ranks, phases, SROTA or GEC —
which is what lets one proof cover all of them.

The one theorem this encodes, stated so it can be falsified
-----------------------------------------------------------
A hop that requires partition p may be carried by any VC in p. Therefore an
edge exists from ``(resource_in, vc_in)`` to ``(resource_out, vc_out)`` iff
some route reaches the intermediate router using ``resource_in`` while
requiring a partition containing ``vc_in``, and continues on ``resource_out``
while requiring a partition containing ``vc_out``.

Two invariants make that meaningful:

  * partitions are DISJOINT — a VC in two partitions could serve two hops
    whose separation is what the proof relies on, so an overlap is refused
    rather than reasoned about;
  * nodes are ``(resource, vc)`` and never ``(resource, partition)`` — see
    model/shared_resource.py for why a collapsed node is unsound.

Limits, stated rather than implied: this proves routing-dependent resource
cycles only. It does not model arbitration fairness, buffer/credit
availability, or traffic-class injection eligibility, and it does not by
itself discharge an adaptive-routing obligation.

Rationale: docs/decisions/modules/verification.md
"""
from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from veritx_dse.core.artifact import content_id
from veritx_dse.core.errors import SemanticError
from veritx_dse.model.shared_resource import (
    ResourceKind,
    ResourceRef,
    ResourceVC,
    RouteDecision,
    SharedResourceError,
)

SHARED_RESOURCE_CDG_SCHEMA_VERSION = 1
_HASH_TYPE_TAG = "srota/SharedResourceCDG"

class SharedResourceCDGError(ValueError, SemanticError):
    """The table is inconsistent or tampered with — fail closed."""

@dataclass(frozen=True)
class SharedResourceCDG:
    """Concrete ``(resource, vc)`` dependency graph, deterministic order."""

    nodes: tuple[ResourceVC, ...]
    edges: tuple[tuple[ResourceVC, ResourceVC], ...]
    partition_to_vcs: Mapping[int, tuple[int, ...]]
    unused_transitions: tuple[tuple[int, int], ...] = ()
    schema_version: int = SHARED_RESOURCE_CDG_SCHEMA_VERSION

    @property
    def node_count(self) -> int:
        return len(self.nodes)

    @property
    def edge_count(self) -> int:
        return len(self.edges)

    def adjacency(self) -> dict[ResourceVC, list[ResourceVC]]:
        adj: dict[ResourceVC, list[ResourceVC]] = {n: [] for n in self.nodes}
        for src, dst in self.edges:
            adj[src].append(dst)
        return adj

    def find_cycle(self) -> list[ResourceVC] | None:
        """First cycle in deterministic DFS order, or None if acyclic."""
        adj = self.adjacency()
        WHITE, GRAY, BLACK = 0, 1, 2
        color = {n: WHITE for n in self.nodes}
        parent: dict[ResourceVC, ResourceVC | None] = {}
        for root in self.nodes:
            if color[root] != WHITE:
                continue
            stack: list[tuple[ResourceVC, int]] = [(root, 0)]
            color[root] = GRAY
            parent[root] = None
            while stack:
                node, idx = stack[-1]
                if idx < len(adj[node]):
                    stack[-1] = (node, idx + 1)
                    nxt = adj[node][idx]
                    if color[nxt] == WHITE:
                        color[nxt] = GRAY
                        parent[nxt] = node
                        stack.append((nxt, 0))
                    elif color[nxt] == GRAY:
                        cycle = [nxt]
                        cur = node
                        while cur is not None and cur != nxt:
                            cycle.append(cur)
                            cur = parent[cur]
                        cycle.append(nxt)
                        cycle.reverse()
                        return cycle
                else:
                    color[node] = BLACK
                    stack.pop()
        return None

    def canonical_dict(self) -> dict[str, Any]:
        return {
            "nodes": [[r.to_dict(), vc] for r, vc in self.nodes],
            "edges": [[[a[0].to_dict(), a[1]], [b[0].to_dict(), b[1]]]
                      for a, b in self.edges],
            "partition_to_vcs": {str(p): list(v)
                                 for p, v in sorted(
                                     self.partition_to_vcs.items())},
        }

    def cdg_id(self) -> str:
        return content_id(f"{_HASH_TYPE_TAG}/v{self.schema_version}",
                          self.canonical_dict())

def _require_partitions(
        partition_to_vcs: Any) -> dict[int, tuple[int, ...]]:
    if not isinstance(partition_to_vcs, Mapping) or not partition_to_vcs:
        raise SharedResourceCDGError(
            "partition_to_vcs must be a non-empty mapping of partition -> VCs")
    out: dict[int, tuple[int, ...]] = {}
    owner: dict[int, int] = {}
    for partition, vcs in partition_to_vcs.items():
        if type(partition) is not int or partition < 0:
            raise SharedResourceCDGError(
                f"partition ids must be non-negative ints, got {partition!r}")
        if isinstance(vcs, (str, bytes)) or not isinstance(
                vcs, (tuple, list, frozenset)):
            raise SharedResourceCDGError(
                f"partition {partition} must map to a collection of VCs, got "
                f"{vcs!r}")
        resolved: list[int] = []
        for vc in vcs:
            if type(vc) is not int or vc < 0:
                raise SharedResourceCDGError(
                    f"partition {partition} names a non-int VC {vc!r}")
            if vc in owner:
                # Overlap is refused, not reasoned about: a VC shared by two
                # partitions can serve hops whose separation is exactly what
                # the acyclicity argument relies on.
                raise SharedResourceCDGError(
                    f"VC {vc} is in both partition {owner[vc]} and partition "
                    f"{partition} — partitions must be disjoint for the "
                    "dependency proof to mean anything")
            owner[vc] = partition
            resolved.append(vc)
        if not resolved:
            raise SharedResourceCDGError(
                f"partition {partition} has no VCs, so no hop can use it")
        out[partition] = tuple(sorted(resolved))
    return out

def _require_decisions(
        decisions: Any, routers: tuple[int, ...]
) -> dict[tuple[int, int], tuple[RouteDecision, ...]]:
    if not isinstance(decisions, Mapping) or not decisions:
        raise SharedResourceCDGError(
            "decisions must be a non-empty mapping of (src, dst) -> "
            "RouteDecision")
    known = set(routers)
    out: dict[tuple[int, int], tuple[RouteDecision, ...]] = {}
    for key, decision in decisions.items():
        if (not isinstance(key, tuple) or len(key) != 2
                or any(type(v) is not int for v in key)):
            raise SharedResourceCDGError(
                f"decision key {key!r} must be a (src_router, dst_router) "
                "pair of ints")
        src, dst = key
        if src not in known:
            raise SharedResourceCDGError(
                f"decision key {key!r} names source router {src}, which is "
                "outside the declared router set")
        # The second component names a TERMINAL, not a router: a
        # concentrated fabric has c terminals per router, so a terminal id
        # legitimately exceeds every router id, and `src == dst` does NOT
        # mean "zero-length route". Only non-negativity is checkable here;
        # terminality is decided against the destination ROUTER, which the
        # caller supplies through `node_to_router`.
        if dst < 0:
            raise SharedResourceCDGError(
                f"decision key {key!r} names negative destination {dst}")
        choices = decision if isinstance(decision, tuple) else (decision,)
        if not choices:
            raise SharedResourceCDGError(
                f"decision {key!r} has no choices; a route pair with no "
                "realizable decision is not a route")
        for choice in choices:
            if not isinstance(choice, RouteDecision):
                raise SharedResourceCDGError(
                    f"decision {key!r} must hold RouteDecision values, got "
                    f"{type(choice).__name__}")
        out[key] = tuple(choices)
    return out

def build_shared_resource_cdg(
        *,
        decisions: Mapping[tuple[int, int], RouteDecision],
        partition_to_vcs: Mapping[int, tuple[int, ...]],
        allowed_transitions: tuple[tuple[int, int], ...],
        routers: tuple[int, ...],
        node_to_router: Mapping[int, int] | None = None,
) -> SharedResourceCDG:
    """Expand a deterministic decision table over concrete (resource, VC).

    ``decisions`` may map a (src, dst) pair to ONE ``RouteDecision`` or to a
    TUPLE of them. The tuple form is how an ADAPTIVE rule is modelled: when
    the route is chosen at runtime (SROTA's shape policy picks by telemetry
    load, GEC's hybrid by live credit), there is no single decision per pair,
    and the obligation becomes "the UNION of every realizable choice, with
    the choices separated by VC, is acyclic" — which is what the simulator's
    own static check does. A single decision stays a 1-tuple, so the
    deterministic case is unchanged.

    ``node_to_router`` maps a destination TERMINAL to the router it attaches
    to. It is required whenever a terminal id is not also a router id (a
    concentrated fabric has c terminals per router), because terminality —
    "does this hop end the route?" — is a question about the destination
    ROUTER. Defaulting it to the identity is only sound for c == 1.
    """
    partitions = _require_partitions(partition_to_vcs)
    table = _require_decisions(decisions, tuple(routers))
    terminal_map = dict(node_to_router or {})
    for node, router in terminal_map.items():
        if router not in set(routers):
            raise SharedResourceCDGError(
                f"node_to_router maps terminal {node} to router {router}, "
                "which is not a declared router")

    if not isinstance(allowed_transitions, tuple):
        raise SharedResourceCDGError(
            "allowed_transitions must be a tuple of (vc_in, vc_out) pairs")
    transitions: list[tuple[int, int]] = []
    for pair in allowed_transitions:
        if (not isinstance(pair, tuple) or len(pair) != 2
                or any(type(v) is not int for v in pair)):
            raise SharedResourceCDGError(
                f"allowed transition {pair!r} must be a (vc_in, vc_out) pair")
        transitions.append(pair)
    known_vcs = {vc for vcs in partitions.values() for vc in vcs}
    stray = sorted({vc for pair in transitions for vc in pair} - known_vcs)
    if stray:
        raise SharedResourceCDGError(
            f"allowed transitions name VCs {stray} that no partition "
            "contains, so they can never be eligible for any hop")

    all_vcs = tuple(sorted({vc for vcs in partitions.values()
                            for vc in vcs}))

    def is_terminal(decision: RouteDecision, dest: int) -> bool:
        """A hop that ENDS the route imposes no eligibility of its own.

        The eject port is the last resource a packet occupies, so its VC set
        is whatever arrived — the whole range by definition. That is why it
        is exempt from the partition map (it would necessarily overlap every
        transit partition) AND from the disjointness rule: it has no
        outgoing edges, so no cycle can pass through it. Treating it as a
        normal transit hop would be wrong in the other direction — it would
        pretend only one tap's VCs may eject.
        """
        return decision.next_router == terminal_map.get(dest, dest)

    # Every TRANSIT hop's partition must be resolvable, and every
    # intermediate router must have a continuation. Both are declaration
    # errors, not proof outcomes, so they are raised rather than reported as
    # a cycle.
    for (s, d), choices in sorted(table.items()):
        for decision in choices:
            if is_terminal(decision, d):
                continue
            if decision.vc_partition not in partitions:
                raise SharedResourceCDGError(
                    f"decision ({s},{d}) requires partition "
                    f"{decision.vc_partition}, which has no VC mapping")
            if (decision.next_router, d) not in table:
                raise SharedResourceCDGError(
                    f"decision ({s},{d}) reaches router "
                    f"{decision.next_router} but the table has no entry for "
                    f"({decision.next_router},{d}) — the hop is not "
                    "realizable")

    nodes: set[ResourceVC] = set()
    for (s, d), choices in table.items():
        for decision in choices:
            eligible = (all_vcs if is_terminal(decision, d)
                        else partitions[decision.vc_partition])
            for vc in eligible:
                nodes.add((decision.resource, vc))

    edges: set[tuple[ResourceVC, ResourceVC]] = set()
    realized: set[tuple[int, int]] = set()
    for vc_in, vc_out in transitions:
        for (s, d), choices_in in sorted(table.items()):
            for decision_in in choices_in:
                # A terminal hop is never a source: it has no successor.
                if is_terminal(decision_in, d):
                    continue
                if vc_in not in partitions[decision_in.vc_partition]:
                    continue
                # EVERY realizable continuation is an edge: an adaptive rule
                # may take any of them, so the graph must be acyclic under
                # all of them, not just the one a static table would pick.
                for decision_out in table[(decision_in.next_router, d)]:
                    if is_terminal(decision_out, d):
                        # Ejecting is not an allocation step: the flit leaves
                        # on the VC it arrived on, so the transition must be
                        # identity. Allowing a VC change here would invent a
                        # resource occupancy that never happens.
                        if vc_out != vc_in:
                            continue
                    elif vc_out not in partitions[decision_out.vc_partition]:
                        continue
                    edges.add(((decision_in.resource, vc_in),
                               (decision_out.resource, vc_out)))
                    realized.add((vc_in, vc_out))

    unused = tuple(sorted(set(transitions) - realized))
    return SharedResourceCDG(
        nodes=tuple(sorted(nodes)),
        edges=tuple(sorted(edges)),
        partition_to_vcs={p: v for p, v in partitions.items()},
        unused_transitions=unused)

def shared_resources_of(decisions: Mapping[tuple[int, int],
                                           RouteDecision]
                        ) -> tuple[ResourceRef, ...]:
    """The distinct resources a table uses, sorted. Inspection helper."""
    return tuple(sorted({d.resource for d in decisions.values()}))

def assert_no_shared_channel_tap(*decisions: RouteDecision) -> None:
    """Guard used by callers that must stay point-to-point.

    A private channel carrying a tap means the caller built a shared-wire
    decision on a fabric that has no shared wires — refuse rather than let
    the tap silently do nothing.
    """
    for decision in decisions:
        if decision.resource.kind is ResourceKind.CHANNEL \
                and decision.tap is not None:      # pragma: no cover - guard
            raise SharedResourceCDGError(
                f"private channel {decision.resource} carries tap "
                f"{decision.tap}")

__all__ = [
    "SharedResourceCDGError",
    "SharedResourceCDG",
    "build_shared_resource_cdg",
    "shared_resources_of",
    "assert_no_shared_channel_tap",
    "SHARED_RESOURCE_CDG_SCHEMA_VERSION",
]

# Re-exported so callers can build decisions without a second import.
__all__ += ["ResourceRef", "ResourceKind", "RouteDecision", "ResourceVC",
            "SharedResourceError"]

_ = (SharedResourceError,)  # keep the re-export honest under lint
