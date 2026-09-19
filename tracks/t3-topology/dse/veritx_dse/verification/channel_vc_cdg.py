"""veritx_dse.verification.channel_vc_cdg — (channel, VC) CDG (Wave B3.3).

Dally–Seitz: a routing function is deadlock-free if its channel dependency
graph over the resources a packet can WAIT for is acyclic. With virtual
channels the resource is `(channel, vc)`, so the graph must be built over
`(channel, vc)` nodes with VC-transition edges, not over physical channels.

Nodes: every directed channel × every VC id in the VCAssignmentArtifact.
Edges: a packet on `(c_in, vc_in)` that arrives at router v and continues
toward any destination w uses an outgoing channel `c_out = v -> next(v, w)`
under the routing class of `vc_out`; the edge exists for every
`(vc_in -> vc_out)` transition the artifact allows. Ejection (w == v) adds
no edge. Parallel channels to the same neighbor are distinct resources and
all receive edges.

This certifier is honest about what it does NOT know:
  * only the DEFAULT routing class is interpretable today (the router-level
    route artifact is class-less; schema v2 adds classes);
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
from veritx_dse.model.vc_assignment import (
    DEFAULT_ROUTING_CLASS, VCAssignmentArtifact,
)

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
    # Number of routing decisions where the v1 table named a next ROUTER
    # that had more than one parallel directed channel. Each such decision
    # conservatively depends on every parallel channel (false FAIL is safe,
    # false PASS is not; schema v2 names a channel_id exactly).
    conservative_expansions: int = 0

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
    classes = {rc for _vc, rc in vc_assignment.vc_to_routing_class}
    unknown = classes - {DEFAULT_ROUTING_CLASS}
    if unknown:
        raise CDGError(
            f"routing classes {sorted(unknown)} have no executable "
            f"semantics in the router-level route artifact (schema v2) — "
            f"cannot build the realized CDG")

    entries: dict[tuple[int, int], int] = getattr(router_route, "entries", {})

    # The v1 route table names a next ROUTER, never a channel. Map the
    # physical hop (src_router, dst_router) to the exact directed channel(s)
    # that realize it; the packet that leaves v toward nxt requests channels
    # v->nxt, NOT channels leaving nxt (one hop too far).
    channels_by_edge: dict[tuple[int, int], list[int]] = {}
    for ch in topology.channels:
        channels_by_edge.setdefault(
            (ch.src_router, ch.dst_router), []).append(ch.channel_id)
    for edge in channels_by_edge:
        channels_by_edge[edge].sort()
    parallel_edges = {e for e, ids in channels_by_edge.items() if len(ids) > 1}
    router_count = topology.router_count

    transitions = vc_assignment.allowed_transitions
    nodes = tuple(
        (ch.channel_id, vc)
        for ch in topology.channels
        for vc in vc_assignment.vc_ids
    )
    edges: set[tuple[tuple[int, int], tuple[int, int]]] = set()
    conservative_expansions = 0
    for ch in topology.channels:
        u, v = ch.src_router, ch.dst_router
        for w in range(router_count):
            # A packet is on channel u->v toward w only if the table
            # routes w through v from u. Otherwise this channel is not on
            # that flow's path and creates no dependency.
            if w == u or w == v:
                continue
            if entries.get((u, w)) != v:
                continue
            nxt = entries.get((v, w))
            if nxt is None or nxt == v:
                continue
            out_ids = channels_by_edge.get((v, nxt), ())
            if not out_ids:
                raise CDGError(
                    f"route ({v},{w}) names next router {nxt}, but the "
                    f"topology has no directed channel {v}->{nxt} — the "
                    f"route table and the topology disagree")
            if (v, nxt) in parallel_edges:
                conservative_expansions += 1
            for out_id in out_ids:
                for vc_in, vc_out in transitions:
                    edges.add(((ch.channel_id, vc_in), (out_id, vc_out)))
    ordered = tuple(sorted(edges))
    return ChannelVCCDG(nodes=nodes, edges=ordered,
                        conservative_expansions=conservative_expansions)


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
    evidence["route_realization"] = "v1_next_router"
    evidence["conservative_parallel_channel_expansion"] = \
        cdg.conservative_expansions > 0
    evidence["conservative_expansion_count"] = cdg.conservative_expansions
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
