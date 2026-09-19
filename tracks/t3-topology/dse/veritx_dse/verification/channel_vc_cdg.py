"""veritx_dse.verification.channel_vc_cdg — (channel, VC) CDG (Wave B3.3).

Dally–Seitz: a routing function is deadlock-free if its channel dependency
graph over the resources a packet can WAIT for is acyclic. With virtual
channels the resource is `(channel, vc)`, so the graph must be built over
`(channel, vc)` nodes with VC-transition edges, not over physical channels.

Nodes: every directed channel × every VC id in the VCAssignmentArtifact.
Edges: for the route class the packet uses, a packet on `(c_in, vc_in)`
that reaches router v en route to destination d requests the EXACT
outgoing channel `(class, v, d)` from the v2 RouteArtifact; the edge
exists for every `(vc_in -> vc_out)` transition the artifact allows.
Ejection (d == v) adds no edge. Channel ids are exact hardware resources:
the v1 next-router ambiguity is gone.

This certifier is honest about what it does NOT know:
  * B3.2d interim: every VC must use one class (the router route's
    default). Selecting the class from `vc_out` per transition is B3.3d;
    until then a multi-class VC assignment is UNSUPPORTED, never a
    guessed PASS;
  * allowed transitions default to VC-preserving, so no escape subnetwork
    is conjured to launder a cyclic physical graph into a PASS;
  * buffering is not modeled — `CHANNEL_VC_DEPENDENCY_ACYCLIC` does not
    need credit/allocator semantics, and `router_behavior_hash` is bound
    when the RouterBehaviorArtifact exists (B3.4).

A cyclic graph FAILs with a witnessed cycle. A class the certifier cannot
interpret yields UNSUPPORTED, never a silent PASS.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from veritx_dse.model.resolved_route import ResolvedRouteArtifact
from veritx_dse.model.topology_artifact import TopologyArtifact
from veritx_dse.model.vc_assignment import VCAssignmentArtifact

CHANNEL_VC_DEPENDENCY_ACYCLIC = "CHANNEL_VC_DEPENDENCY_ACYCLIC"

# The deadlock-proof vocabulary (spec §12). One entry today; the others are
# named so callers cannot mistake "no method" for "any method".
DEADLOCK_PROOF_METHODS = (
    "DETERMINISTIC_DOR_THEOREM",
    CHANNEL_VC_DEPENDENCY_ACYCLIC,
    "ESCAPE_SUBNETWORK_THEOREM",
    "FORMAL_BOUNDED_CHECK",
)

CDG_TOOL = "veritx_dse.verification.channel_vc_cdg"
CDG_SCOPE = ("routing+VC structure only; Dally-Seitz (channel,vc) "
             "dependencies; buffering/credits not modeled")

Verdict = str  # "PASS" | "FAIL" | "UNSUPPORTED" | "NOT_RUN"


class CDGError(ValueError):
    """The CDG request is inconsistent or tampered with — fail closed."""


@dataclass(frozen=True)
class ChannelVCCDG:
    """The realized dependency graph, deterministic node/edge order."""

    nodes: tuple[tuple[int, int], ...]           # (channel_id, vc)
    edges: tuple[tuple[tuple[int, int], tuple[int, int]], ...]
    cdg_route_class: str = ""

    @property
    def node_count(self) -> int:
        return len(self.nodes)

    @property
    def edge_count(self) -> int:
        return len(self.edges)

    def adjacency(self) -> dict[tuple[int, int], list[tuple[int, int]]]:
        adj: dict[tuple[int, int], list[tuple[int, int]]] = {
            n: [] for n in self.nodes
        }
        for src, dst in self.edges:
            adj[src].append(dst)
        return adj

    def find_cycle(self) -> list[tuple[int, int]] | None:
        """First cycle in deterministic DFS order, or None if acyclic."""
        adj = self.adjacency()
        WHITE, GRAY, BLACK = 0, 1, 2
        color = {n: WHITE for n in self.nodes}
        parent: dict[tuple[int, int], tuple[int, int] | None] = {}
        for root in self.nodes:
            if color[root] != WHITE:
                continue
            stack: list[tuple[tuple[int, int], int]] = [(root, 0)]
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


def build_channel_vc_cdg(
        topology: TopologyArtifact,
        router_route: Any,
        vc_assignment: VCAssignmentArtifact,
) -> ChannelVCCDG:
    """Expand routing over the (channel, VC) resources.

    Raises CDGError if the VC assignment uses a routing class this
    certifier cannot interpret (the caller reports UNSUPPORTED).
    """
    definitions = getattr(router_route, "routing_classes", None)
    if not definitions:
        raise CDGError(
            "router route does not declare routing classes (schema v2 "
            "required) — cannot build the realized CDG")
    entry_class = definitions[0].id
    classes = {rc for _vc, rc in vc_assignment.vc_to_routing_class}
    if classes != {entry_class}:
        raise CDGError(
            f"VC routing classes {sorted(classes)} are not the single "
            f"router-route class {entry_class!r}; per-vc_out class "
            f"selection is B3.3d — cannot build the realized CDG")
    entries = {(s, d): ch
               for (cls, s, d), ch in router_route.entries.items()
               if cls == entry_class}
    channel_by_id = {c.channel_id: c for c in topology.channels}

    transitions = vc_assignment.allowed_transitions
    nodes = tuple(
        (ch.channel_id, vc)
        for ch in topology.channels
        for vc in vc_assignment.vc_ids
    )
    edges: set[tuple[tuple[int, int], tuple[int, int]]] = set()
    for (s, d), ch_id in sorted(entries.items()):
        ch = channel_by_id.get(ch_id)
        if ch is None:
            raise CDGError(
                f"route ({s},{d}) names channel {ch_id}, which is not in "
                f"the topology")
        v = ch.dst_router
        if v == d:
            continue                     # eject at v: no dependency
        out_id = entries.get((v, d))
        if out_id is None:
            raise CDGError(
                f"route ({s},{d}) reaches router {v} but has no entry "
                f"for ({v},{d}) — the route table is not total")
        out_ch = channel_by_id.get(out_id)
        if out_ch is None or out_ch.src_router != v:
            raise CDGError(
                f"route ({v},{d}) names channel {out_id}, which does not "
                f"leave router {v}")
        for vc_in, vc_out in transitions:
            edges.add(((ch_id, vc_in), (out_id, vc_out)))
    ordered = tuple(sorted(edges))
    return ChannelVCCDG(nodes=nodes, edges=ordered, cdg_route_class=entry_class)


@dataclass(frozen=True)
class DeadlockCertificate:
    """Structured deadlock verdict with every bound artifact hash."""

    proof_method: str
    verdict: Verdict
    topology_hash: str
    attachment_hash: str
    resolved_route_hash: str
    vc_assignment_hash: str
    router_behavior_hash: str
    evidence: dict[str, Any] = field(default_factory=dict)
    tool: str = CDG_TOOL
    scope: str = CDG_SCOPE
    schema_version: int = 1

    def to_dict(self) -> dict[str, Any]:
        return {
            "type": "srota/DeadlockCertificate",
            "schema_version": self.schema_version,
            "proof_method": self.proof_method,
            "verdict": self.verdict,
            "topology_hash": self.topology_hash,
            "attachment_hash": self.attachment_hash,
            "resolved_route_hash": self.resolved_route_hash,
            "vc_assignment_hash": self.vc_assignment_hash,
            "router_behavior_hash": self.router_behavior_hash,
            "evidence": self.evidence,
            "tool": self.tool,
            "scope": self.scope,
        }


def _binding_hashes(
        topology: TopologyArtifact,
        resolved_route: ResolvedRouteArtifact,
        router_route: Any,
        vc_assignment: VCAssignmentArtifact,
) -> tuple[str, str, str, str]:
    if resolved_route.topology_hash != topology.topology_hash():
        raise CDGError("resolved route does not bind this topology")
    if resolved_route.router_route_hash != getattr(router_route, "artifact_hash", ""):
        raise CDGError("resolved route does not bind this router route")
    if getattr(router_route, "schema_version", None) != 2:
        raise CDGError(
            "router route is not schema v2 (class-aware channel "
            "realization); v1 is refused on the certification path")
    if vc_assignment.resolved_route_hash != resolved_route.resolved_route_hash():
        raise CDGError("VC assignment does not bind this resolved route")
    return (topology.topology_hash(), resolved_route.attachment_hash,
            resolved_route.resolved_route_hash(),
            vc_assignment.vc_assignment_hash())


def certify_channel_vc_deadlock(
        *,
        topology: TopologyArtifact,
        resolved_route: ResolvedRouteArtifact,
        router_route: Any,
        vc_assignment: VCAssignmentArtifact,
        router_behavior_hash: str = "",
) -> DeadlockCertificate:
    """Prove or refute acyclicity of the realized (channel, VC) CDG."""
    topo_hash, att_hash, rr_hash, vc_hash = _binding_hashes(
        topology, resolved_route, router_route, vc_assignment)

    classes = sorted({rc for _vc, rc in vc_assignment.vc_to_routing_class})
    evidence: dict[str, Any] = {
        "vc_count": vc_assignment.vc_count,
        "routing_classes": classes,
        "escape_vcs": list(vc_assignment.escape_vcs),
    }

    try:
        cdg = build_channel_vc_cdg(topology, router_route, vc_assignment)
    except CDGError as exc:
        evidence["unsupported_reason"] = str(exc)
        return DeadlockCertificate(
            proof_method=CHANNEL_VC_DEPENDENCY_ACYCLIC, verdict="UNSUPPORTED",
            topology_hash=topo_hash, attachment_hash=att_hash,
            resolved_route_hash=rr_hash, vc_assignment_hash=vc_hash,
            router_behavior_hash=router_behavior_hash, evidence=evidence)

    evidence["node_count"] = cdg.node_count
    evidence["edge_count"] = cdg.edge_count
    evidence["route_realization"] = "v2_channel_id"
    evidence["cdg_route_class"] = cdg.cdg_route_class
    cycle = cdg.find_cycle()
    if cycle is None:
        evidence["acyclic"] = True
        return DeadlockCertificate(
            proof_method=CHANNEL_VC_DEPENDENCY_ACYCLIC, verdict="PASS",
            topology_hash=topo_hash, attachment_hash=att_hash,
            resolved_route_hash=rr_hash, vc_assignment_hash=vc_hash,
            router_behavior_hash=router_behavior_hash, evidence=evidence)
    evidence["acyclic"] = False
    evidence["cycle"] = [list(node) for node in cycle]
    return DeadlockCertificate(
        proof_method=CHANNEL_VC_DEPENDENCY_ACYCLIC, verdict="FAIL",
        topology_hash=topo_hash, attachment_hash=att_hash,
        resolved_route_hash=rr_hash, vc_assignment_hash=vc_hash,
        router_behavior_hash=router_behavior_hash, evidence=evidence)
