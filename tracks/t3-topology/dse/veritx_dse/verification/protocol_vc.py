"""veritx_dse.verification.protocol_vc — E4 BLOCKING dependency separation.

This is an independent verifier, not a routing verifier and not a VC
generator. It answers exactly one question:

    Given a CompileRequest E4 dependency graph and a candidate
    traffic-class → VC mapping, does VC isolation separate every
    BLOCKING dependency cycle?

Model (explicitly assumed, not proven here):

    for each BLOCKING edge  src -> dst:
        shared = VCs(src) ∩ VCs(dst)
        shared non-empty  ->  the dependency remains coupled
        shared empty      ->  the dependency is separated

The coupled BLOCKING subgraph must be acyclic for PASS. This assumes that
disjoint virtual channels isolate the protocol buffering dependency the E4
edge represents; it does NOT model allocator/buffer credit semantics, it
does NOT prove channel-routing deadlock (that is the channel×VC verifier's
job), and it does NOT certify collective concurrency. The two verifiers
must agree independently before a candidate is accepted.

Multi-VC classes are handled conservatively: any shared VC keeps the edge
coupled. No "convenient VC" is chosen to make a proof pass.

Malformed candidates fail closed: a traffic class that appears in a
BLOCKING edge but has no VC mapping raises ``ProtocolVCError`` — never
PASS, never UNSUPPORTED. Collectives are recorded as NOT_MODELED evidence
and never contribute VCs or alter the E4 verdict.
"""
from __future__ import annotations

from veritx_dse.core.errors import SemanticError

from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any

from veritx_dse.core.artifact import freeze, thaw
from veritx_dse.model.compile_model import CompileRequest, DepKind
from veritx_dse.model.vc_assignment import VCAssignmentArtifact

PROTOCOL_VC_DEPENDENCY_ACYCLIC = "PROTOCOL_VC_DEPENDENCY_ACYCLIC"
PROTOCOL_VC_PROOF_METHODS = (PROTOCOL_VC_DEPENDENCY_ACYCLIC,)

PROTOCOL_VC_TOOL = "veritx_dse.verification.protocol_vc"
PROTOCOL_VC_SCOPE = (
    "CompileRequest E4 BLOCKING traffic-class dependencies only; assumes "
    "disjoint VCs isolate the represented protocol buffering dependency; "
    "does not prove channel-routing deadlock or collective concurrency")

PROTOCOL_VC_VERDICTS = ("PASS", "FAIL")
PROTOCOL_VC_CERTIFICATE_SCHEMA_VERSION = 1

COLLECTIVE_SEMANTICS_ABSENT = "ABSENT"
COLLECTIVE_SEMANTICS_NOT_MODELED = "NOT_MODELED"

Verdict = str  # "PASS" | "FAIL"


class ProtocolVCError(ValueError, SemanticError):
    """The protocol/VC separation request is malformed — fail closed."""


@dataclass(frozen=True)
class ProtocolVCGraph:
    """Coupled BLOCKING graph: deterministic node and edge order."""

    nodes: tuple[str, ...]
    coupled_edges: tuple[tuple[str, str], ...]
    separated_edges: tuple[tuple[str, str], ...]

    @property
    def coupled_edge_count(self) -> int:
        return len(self.coupled_edges)

    @property
    def separated_edge_count(self) -> int:
        return len(self.separated_edges)

    def adjacency(self) -> dict[str, list[str]]:
        adj: dict[str, list[str]] = {n: [] for n in self.nodes}
        for src, dst in self.coupled_edges:
            adj[src].append(dst)
        return adj

    def find_cycle(self) -> list[str] | None:
        """First cycle in deterministic DFS order, or None if acyclic."""
        adj = self.adjacency()
        WHITE, GRAY, BLACK = 0, 1, 2
        color = {n: WHITE for n in self.nodes}
        parent: dict[str, str | None] = {}
        for root in self.nodes:
            if color[root] != WHITE:
                continue
            stack: list[tuple[str, int]] = [(root, 0)]
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


def _require_types(design: CompileRequest,
                   vc_assignment: VCAssignmentArtifact) -> None:
    if not isinstance(design, CompileRequest):
        raise ProtocolVCError("design must be a CompileRequest")
    if not isinstance(vc_assignment, VCAssignmentArtifact):
        raise ProtocolVCError("vc_assignment must be a VCAssignmentArtifact")


def _blocking_edges(design: CompileRequest) -> list[tuple[str, str]]:
    return [(d.source, d.target)
            for d in design.dependencies.dependencies
            if d.kind == DepKind.BLOCKING]


def build_protocol_vc_graph(
        design: CompileRequest,
        vc_assignment: VCAssignmentArtifact,
) -> ProtocolVCGraph:
    """Split BLOCKING edges into coupled and VC-separated sets.

    Raises ProtocolVCError when a traffic class in a BLOCKING edge has no
    VC mapping (the candidate does not state what traffic uses which VC).
    """
    _require_types(design, vc_assignment)
    vc_by_class = dict(vc_assignment.traffic_class_to_vcs)
    blocking = _blocking_edges(design)
    participants = sorted({node for edge in blocking for node in edge})
    missing = [cls for cls in participants if cls not in vc_by_class]
    if missing:
        raise ProtocolVCError(
            f"traffic classes {missing} appear in BLOCKING dependencies but "
            f"have no VC mapping in the candidate assignment")
    coupled: set[tuple[str, str]] = set()
    separated: set[tuple[str, str]] = set()
    for src, dst in blocking:
        shared = set(vc_by_class[src]) & set(vc_by_class[dst])
        if shared:
            coupled.add((src, dst))
        else:
            separated.add((src, dst))
    return ProtocolVCGraph(nodes=tuple(participants),
                           coupled_edges=tuple(sorted(coupled)),
                           separated_edges=tuple(sorted(separated)))


@dataclass(frozen=True)
class ProtocolVCCertificate:
    """Immutable verdict on BLOCKING dependency separation.

    ``evidence`` is frozen at construction, so caller-owned mappings and
    lists cannot mutate the certificate and callers cannot mutate it through
    the attribute. ``to_dict()`` returns a fresh thawed copy each call.
    """

    proof_method: str
    verdict: Verdict
    design_hash: str
    vc_assignment_hash: str
    evidence: Mapping[str, Any] = field(default_factory=dict)
    tool: str = PROTOCOL_VC_TOOL
    scope: str = PROTOCOL_VC_SCOPE
    schema_version: int = PROTOCOL_VC_CERTIFICATE_SCHEMA_VERSION

    def __post_init__(self):
        if self.proof_method not in PROTOCOL_VC_PROOF_METHODS:
            raise ProtocolVCError(
                f"proof method {self.proof_method!r} is not in the closed "
                f"vocabulary {list(PROTOCOL_VC_PROOF_METHODS)}")
        if self.verdict not in PROTOCOL_VC_VERDICTS:
            raise ProtocolVCError(
                f"verdict {self.verdict!r} is not one of "
                f"{list(PROTOCOL_VC_VERDICTS)}")
        for name in ("design_hash", "vc_assignment_hash"):
            value = getattr(self, name)
            if not isinstance(value, str) or not value:
                raise ProtocolVCError(f"{name} must be a non-empty string")
        if not isinstance(self.tool, str) or not self.tool:
            raise ProtocolVCError("tool must be a non-empty string")
        if not isinstance(self.scope, str) or not self.scope:
            raise ProtocolVCError("scope must be a non-empty string")
        if type(self.schema_version) is not int or \
                self.schema_version != PROTOCOL_VC_CERTIFICATE_SCHEMA_VERSION:
            raise ProtocolVCError(
                f"unsupported protocol-vc certificate schema_version "
                f"{self.schema_version!r}")
        if not isinstance(self.evidence, Mapping):
            raise ProtocolVCError("evidence must be a mapping")
        object.__setattr__(self, "evidence", freeze(self.evidence))

    def to_dict(self) -> dict[str, Any]:
        return {
            "type": "srota/ProtocolVCCertificate",
            "schema_version": self.schema_version,
            "proof_method": self.proof_method,
            "verdict": self.verdict,
            "design_hash": self.design_hash,
            "vc_assignment_hash": self.vc_assignment_hash,
            "evidence": thaw(self.evidence),
            "tool": self.tool,
            "scope": self.scope,
        }


def certify_protocol_vc_separation(
        *,
        design: CompileRequest,
        vc_assignment: VCAssignmentArtifact,
) -> ProtocolVCCertificate:
    """Prove or refute BLOCKING-cycle separation under the VC-isolation model.

    PASS: the coupled BLOCKING subgraph is acyclic.
    FAIL: a deterministic coupled cycle witness exists.
    Malformed candidates (missing traffic-class mapping, bad parent types)
    raise ProtocolVCError; collectives are recorded as NOT_MODELED and never
    change the E4 verdict.
    """
    graph = build_protocol_vc_graph(design, vc_assignment)
    kinds = [d.kind for d in design.dependencies.dependencies]
    multi_rank_collectives = [c for c in design.workload.collectives
                              if c.group_size > 1]
    evidence: dict[str, Any] = {
        "blocking_edge_count": len(_blocking_edges(design)),
        "coupled_edge_count": graph.coupled_edge_count,
        "separated_edge_count": graph.separated_edge_count,
        "coupled_edges": [list(edge) for edge in graph.coupled_edges],
        "separated_edges": [list(edge) for edge in graph.separated_edges],
        "traffic_class_to_vcs": {
            cls: list(vcs) for cls, vcs
            in sorted(dict(vc_assignment.traffic_class_to_vcs).items())},
        "ordering_edge_count": kinds.count(DepKind.ORDERING),
        "independent_edge_count": kinds.count(DepKind.INDEPENDENT),
        "proof_assumption":
            "disjoint_vcs_isolate_protocol_buffering_dependency",
        "multi_rank_collective_count": len(multi_rank_collectives),
        "collective_vc_semantics": (
            COLLECTIVE_SEMANTICS_NOT_MODELED if multi_rank_collectives
            else COLLECTIVE_SEMANTICS_ABSENT),
    }
    cycle = graph.find_cycle()
    if cycle is None:
        evidence["acyclic"] = True
        return ProtocolVCCertificate(
            proof_method=PROTOCOL_VC_DEPENDENCY_ACYCLIC, verdict="PASS",
            design_hash=design.design_hash(),
            vc_assignment_hash=vc_assignment.vc_assignment_hash(),
            evidence=evidence)
    evidence["acyclic"] = False
    evidence["cycle"] = list(cycle)
    return ProtocolVCCertificate(
        proof_method=PROTOCOL_VC_DEPENDENCY_ACYCLIC, verdict="FAIL",
        design_hash=design.design_hash(),
        vc_assignment_hash=vc_assignment.vc_assignment_hash(),
        evidence=evidence)
