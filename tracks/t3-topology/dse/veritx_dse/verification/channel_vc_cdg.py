"""veritx_dse.verification.channel_vc_cdg — independent (channel, VC) CDG.

Dally–Seitz: a routing function is deadlock-free when the channel dependency
graph over the resources a packet can WAIT for is acyclic. With virtual
channels the resource is exactly ``(directed_channel_id, vc_id)``, so the
graph must be built over those resources and their VC transitions, never
over physical channels alone.

Nodes: every directed topology channel × every VC id in the VC artifact.
Edges: a packet holding ``(c_in, vc_in)`` that reaches router ``v`` en route
to destination ``d`` may request the exact outgoing channel its NEXT class
selects for ``(v, d)``, for every allowed transition ``vc_in -> vc_out``.

Routing-class convention (corrected):

    class_in  = routing_class(vc_in)    # the class that chose c_in
    class_out = routing_class(vc_out)   # the class that chooses the next hop

The HELD channel comes from ``class_in``'s route table; the REQUESTED channel
comes from ``class_out``'s route table. Deriving both sides from ``class_out``
is wrong: it invents dependencies for packets that never travelled the
``class_out`` path. This verifier consumes the candidate VCAssignmentArtifact
as given and judges it independently of whatever policy produced it.

Honest scope:

  * routing + VC dependency proof only — the attachment hash is carried
    transitively from the ResolvedRouteArtifact, but attachment completeness
    is NOT recertified here;
  * buffering/credits are not modeled; ``CHANNEL_VC_DEPENDENCY_ACYCLIC``
    needs no allocator semantics;
  * a VC bound to a routing class the router route did not materialize is
    UNSUPPORTED, never a guessed PASS;
  * a designated escape VC is evidence only: it is reported, and it NEVER
    bypasses graph analysis or produces PASS by itself.

Malformed or tampered parents raise ``CDGError``; they are never converted
into UNSUPPORTED or PASS. A cyclic graph FAILs with a deterministic witness.
"""
from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any

from veritx_dse.core.artifact import freeze, thaw
from veritx_dse.core.route_artifact import RouteArtifact, RouteArtifactError
from veritx_dse.model.resolved_route import ResolvedRouteArtifact
from veritx_dse.model.topology_artifact import TopologyArtifact
from veritx_dse.model.vc_assignment import VCAssignmentArtifact, VCAssignmentError

CHANNEL_VC_DEPENDENCY_ACYCLIC = "CHANNEL_VC_DEPENDENCY_ACYCLIC"

# The deadlock-proof vocabulary. One entry is executed in this slice; the
# others are named so callers cannot mistake "no method" for "any method".
DEADLOCK_PROOF_METHODS = (
    "DETERMINISTIC_DOR_THEOREM",
    CHANNEL_VC_DEPENDENCY_ACYCLIC,
    "ESCAPE_SUBNETWORK_THEOREM",
    "FORMAL_BOUNDED_CHECK",
)

DEADLOCK_CERTIFICATE_SCHEMA_VERSION = 1
VERDICTS = ("PASS", "FAIL", "UNSUPPORTED", "NOT_RUN")

CDG_TOOL = "veritx_dse.verification.channel_vc_cdg"
CDG_SCOPE = ("routing+VC dependency proof only (Dally-Seitz (channel,vc) "
             "dependencies); attachment completeness is not recertified "
             "here; buffering/credits not modeled")

Verdict = str  # "PASS" | "FAIL" | "UNSUPPORTED" | "NOT_RUN"

ChannelVC = tuple[int, int]


class CDGError(ValueError):
    """The CDG request is inconsistent or tampered with — fail closed."""


@dataclass(frozen=True)
class ChannelVCCDG:
    """The realized dependency graph, deterministic node/edge order."""

    nodes: tuple[ChannelVC, ...]                 # (channel_id, vc)
    edges: tuple[tuple[ChannelVC, ChannelVC], ...]
    cdg_route_classes: tuple[str, ...] = ()

    @property
    def node_count(self) -> int:
        return len(self.nodes)

    @property
    def edge_count(self) -> int:
        return len(self.edges)

    def adjacency(self) -> dict[ChannelVC, list[ChannelVC]]:
        adj: dict[ChannelVC, list[ChannelVC]] = {n: [] for n in self.nodes}
        for src, dst in self.edges:
            adj[src].append(dst)
        return adj

    def find_cycle(self) -> list[ChannelVC] | None:
        """First cycle in deterministic DFS order, or None if acyclic."""
        adj = self.adjacency()
        WHITE, GRAY, BLACK = 0, 1, 2
        color = {n: WHITE for n in self.nodes}
        parent: dict[ChannelVC, ChannelVC | None] = {}
        for root in self.nodes:
            if color[root] != WHITE:
                continue
            stack: list[tuple[ChannelVC, int]] = [(root, 0)]
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


def _require_types(
        topology: TopologyArtifact,
        router_route: RouteArtifact,
        vc_assignment: VCAssignmentArtifact,
) -> None:
    if not isinstance(topology, TopologyArtifact):
        raise CDGError("topology must be a TopologyArtifact")
    if not isinstance(router_route, RouteArtifact):
        raise CDGError("router_route must be a RouteArtifact")
    if not isinstance(vc_assignment, VCAssignmentArtifact):
        raise CDGError("vc_assignment must be a VCAssignmentArtifact")


def build_channel_vc_cdg(
        topology: TopologyArtifact,
        router_route: RouteArtifact,
        vc_assignment: VCAssignmentArtifact,
) -> ChannelVCCDG:
    """Expand routing over the (channel, VC) resources.

    Raises CDGError if the VC assignment uses a routing class this
    certifier cannot interpret (the caller reports UNSUPPORTED).
    """
    _require_types(topology, router_route, vc_assignment)
    if router_route.schema_version != 2:
        raise CDGError(
            "router route is not schema v2 (class-aware channel "
            "realization) — cannot build the realized CDG")
    declared = {d.id for d in router_route.routing_classes}
    if not declared:
        raise CDGError(
            "router route does not declare routing classes (schema v2 "
            "required) — cannot build the realized CDG")
    class_of_vc = dict(vc_assignment.vc_to_routing_class)
    unknown = set(class_of_vc.values()) - declared
    if unknown:
        raise CDGError(
            f"VC routing classes {sorted(unknown)} are not defined by the "
            f"router route (has {sorted(declared)}) — cannot build the "
            f"realized CDG")

    # One exact table per declared class, validated once up front.
    per_class: dict[str, dict[tuple[int, int], int]] = {cid: {}
                                                        for cid in declared}
    for (cid, s, d), ch in router_route.entries.items():
        table = per_class.get(cid)
        if table is None:
            raise CDGError(
                f"router route entry {cid!r} is not a declared routing class")
        table[(s, d)] = ch
    channel_by_id = {c.channel_id: c for c in topology.channels}
    for cid in sorted(per_class):
        for (s, d), ch_id in sorted(per_class[cid].items()):
            if type(ch_id) is not int or ch_id not in channel_by_id:
                raise CDGError(
                    f"{cid} route ({s},{d}) names channel {ch_id!r}, which "
                    f"is not in the topology")

    nodes = tuple(
        (ch.channel_id, vc)
        for ch in topology.channels
        for vc in vc_assignment.vc_ids
    )
    # The held channel is chosen by class_in; the requested channel is
    # chosen by class_out. A transition between routing classes therefore
    # crosses the dependency exactly once.
    edges: set[tuple[ChannelVC, ChannelVC]] = set()
    for vc_in, vc_out in vc_assignment.allowed_transitions:
        class_in = class_of_vc[vc_in]
        class_out = class_of_vc[vc_out]
        table_in = per_class[class_in]
        table_out = per_class[class_out]
        for (s, d), in_id in sorted(table_in.items()):
            v = channel_by_id[in_id].dst_router
            if v == d:
                continue                 # eject at v: no dependency
            out_id = table_out.get((v, d))
            if out_id is None:
                raise CDGError(
                    f"{class_in} route ({s},{d}) reaches router {v} but the "
                    f"{class_out} route has no entry for ({v},{d}) — the "
                    f"{class_in}->{class_out} transition is not realizable")
            out_ch = channel_by_id[out_id]
            if out_ch.src_router != v:
                raise CDGError(
                    f"{class_out} route ({v},{d}) names channel {out_id}, "
                    f"which does not leave router {v}")
            edges.add(((in_id, vc_in), (out_id, vc_out)))

    return ChannelVCCDG(nodes=nodes, edges=tuple(sorted(edges)),
                        cdg_route_classes=tuple(sorted(declared)))


@dataclass(frozen=True)
class DeadlockCertificate:
    """Immutable structured deadlock verdict with every bound artifact hash.

    ``evidence`` is frozen at construction into an immutable value tree, so
    caller-owned dictionaries/lists cannot mutate the result and callers
    cannot mutate it through the attribute. ``to_dict()`` returns a fresh
    thawed copy on every call.

    The certificate carries the attachment hash transitively from the
    ResolvedRouteArtifact; it does not certify attachment semantics.
    """

    proof_method: str
    verdict: Verdict
    topology_hash: str
    attachment_hash: str
    router_route_hash: str
    resolved_route_hash: str
    vc_assignment_hash: str
    router_behavior_hash: str
    evidence: Mapping[str, Any] = field(default_factory=dict)
    tool: str = CDG_TOOL
    scope: str = CDG_SCOPE
    schema_version: int = DEADLOCK_CERTIFICATE_SCHEMA_VERSION

    def __post_init__(self):
        if self.proof_method not in DEADLOCK_PROOF_METHODS:
            raise CDGError(
                f"proof method {self.proof_method!r} is not in the closed "
                f"vocabulary {list(DEADLOCK_PROOF_METHODS)}")
        if self.verdict not in VERDICTS:
            raise CDGError(
                f"verdict {self.verdict!r} is not one of {list(VERDICTS)}")
        for name in ("topology_hash", "attachment_hash", "router_route_hash",
                     "resolved_route_hash", "vc_assignment_hash"):
            value = getattr(self, name)
            if not isinstance(value, str) or not value:
                raise CDGError(f"{name} must be a non-empty string")
        if not isinstance(self.router_behavior_hash, str):
            raise CDGError("router_behavior_hash must be a string")
        if not isinstance(self.tool, str) or not self.tool:
            raise CDGError("tool must be a non-empty string")
        if not isinstance(self.scope, str) or not self.scope:
            raise CDGError("scope must be a non-empty string")
        if type(self.schema_version) is not int or \
                self.schema_version != DEADLOCK_CERTIFICATE_SCHEMA_VERSION:
            raise CDGError(
                f"unsupported deadlock-certificate schema_version "
                f"{self.schema_version!r}")
        if not isinstance(self.evidence, Mapping):
            raise CDGError("evidence must be a mapping")
        # Defensive freeze: no caller-owned mutable state survives, and the
        # attribute itself is immutable.
        object.__setattr__(self, "evidence", freeze(self.evidence))

    def to_dict(self) -> dict[str, Any]:
        return {
            "type": "srota/DeadlockCertificate",
            "schema_version": self.schema_version,
            "proof_method": self.proof_method,
            "verdict": self.verdict,
            "topology_hash": self.topology_hash,
            "attachment_hash": self.attachment_hash,
            "router_route_hash": self.router_route_hash,
            "resolved_route_hash": self.resolved_route_hash,
            "vc_assignment_hash": self.vc_assignment_hash,
            "router_behavior_hash": self.router_behavior_hash,
            "evidence": thaw(self.evidence),
            "tool": self.tool,
            "scope": self.scope,
        }


def _binding_hashes(
        topology: TopologyArtifact,
        resolved_route: ResolvedRouteArtifact,
        router_route: RouteArtifact,
        vc_assignment: VCAssignmentArtifact,
) -> tuple[str, str, str, str, str]:
    """Prove the parent chain this verifier actually relies on.

    Deliberately does NOT call ``resolved_route.validate_against(...)``:
    that also requires the real AgentAttachmentArtifact. Attachment
    completeness is not recertified here (see ``CDG_SCOPE``).
    """
    if not isinstance(topology, TopologyArtifact):
        raise CDGError("topology must be a TopologyArtifact")
    if not isinstance(resolved_route, ResolvedRouteArtifact):
        raise CDGError("resolved_route must be a ResolvedRouteArtifact")
    if not isinstance(router_route, RouteArtifact):
        raise CDGError("router_route must be a RouteArtifact")
    if not isinstance(vc_assignment, VCAssignmentArtifact):
        raise CDGError("vc_assignment must be a VCAssignmentArtifact")
    if router_route.schema_version != 2:
        raise CDGError(
            "router route is not schema v2 (class-aware channel "
            "realization); v1 is refused on the certification path")
    if resolved_route.topology_hash != topology.topology_hash():
        raise CDGError("resolved route does not bind this topology")
    if resolved_route.router_route_hash != router_route.artifact_hash:
        raise CDGError("resolved route does not bind this router route")
    if vc_assignment.resolved_route_hash != resolved_route.resolved_route_hash():
        raise CDGError("VC assignment does not bind this resolved route")
    try:
        router_route.validate_against(topology)
    except RouteArtifactError as exc:
        raise CDGError(
            f"router route fails parent validation against the topology: "
            f"{exc}") from exc
    try:
        vc_assignment.validate_against(resolved_route)
    except VCAssignmentError as exc:
        raise CDGError(
            f"VC assignment fails parent validation against the resolved "
            f"route: {exc}") from exc
    return (topology.topology_hash(), resolved_route.attachment_hash,
            router_route.artifact_hash, resolved_route.resolved_route_hash(),
            vc_assignment.vc_assignment_hash())


def certify_channel_vc_deadlock(
        *,
        topology: TopologyArtifact,
        resolved_route: ResolvedRouteArtifact,
        router_route: RouteArtifact,
        vc_assignment: VCAssignmentArtifact,
        router_behavior_hash: str = "",
) -> DeadlockCertificate:
    """Prove or refute acyclicity of the realized (channel, VC) CDG.

    Verdicts: PASS (acyclic), FAIL (deterministic cycle witness),
    UNSUPPORTED (routing/VC semantics not interpretable exactly). A
    designated escape VC never changes the verdict by itself.
    """
    topo_hash, att_hash, router_hash, rr_hash, vc_hash = _binding_hashes(
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
            router_route_hash=router_hash, resolved_route_hash=rr_hash,
            vc_assignment_hash=vc_hash,
            router_behavior_hash=router_behavior_hash, evidence=evidence)

    evidence["node_count"] = cdg.node_count
    evidence["edge_count"] = cdg.edge_count
    evidence["route_realization"] = "v2_channel_id"
    evidence["cdg_route_classes"] = list(cdg.cdg_route_classes)
    cycle = cdg.find_cycle()
    if cycle is None:
        evidence["acyclic"] = True
        return DeadlockCertificate(
            proof_method=CHANNEL_VC_DEPENDENCY_ACYCLIC, verdict="PASS",
            topology_hash=topo_hash, attachment_hash=att_hash,
            router_route_hash=router_hash, resolved_route_hash=rr_hash,
            vc_assignment_hash=vc_hash,
            router_behavior_hash=router_behavior_hash, evidence=evidence)
    evidence["acyclic"] = False
    evidence["cycle"] = [list(node) for node in cycle]
    return DeadlockCertificate(
        proof_method=CHANNEL_VC_DEPENDENCY_ACYCLIC, verdict="FAIL",
        topology_hash=topo_hash, attachment_hash=att_hash,
        router_route_hash=router_hash, resolved_route_hash=rr_hash,
        vc_assignment_hash=vc_hash,
        router_behavior_hash=router_behavior_hash, evidence=evidence)
