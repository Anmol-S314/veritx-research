"""shared_resource_deadlock — a deadlock verdict for shared-wire fabrics.

``channel_vc_cdg`` proves point-to-point fabrics: its nodes are
``(channel_id, vc)`` and it refuses any topology carrying shared links, which
is correct fail-closed behaviour for an assumption it cannot honor.
``shared_resource_cdg`` builds the graph its assumption cannot describe.

This module is the verdict layer over that graph, in the same vocabulary the
point-to-point certificate uses, so a caller does not have to know which of
the two produced it:

    proof_method = CHANNEL_VC_DEPENDENCY_ACYCLIC
    verdict      = PASS     no cycle in the concrete (resource, vc) graph
                 = FAIL      a cycle exists, and it is reported
                 = UNSUPPORTED  no graph could be built from this route

An UNSUPPORTED here is NOT a pass. A route whose table is inconsistent has no
dependency graph, and "we could not build one" must never read as "no cycle".
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from veritx_dse.core.errors import SemanticError
from veritx_dse.verification.shared_resource_cdg import (
    SharedResourceCDG,
    SharedResourceCDGError,
)

SHARED_RESOURCE_DEADLOCK_TOOL = (
    "veritx_dse.verification.shared_resource_deadlock")
SHARED_RESOURCE_DEADLOCK_SCOPE = (
    "routing+VC dependency proof over SHARED wires (one driver, many "
    "contending taps), expressed as concrete (resource, vc) nodes; "
    "arbitration fairness, buffer/credit availability and traffic-class "
    "injection eligibility are NOT modeled. GEC hybrid checks the complete "
    "topology-bound candidate union, not an ESCAPE theorem; other adaptive "
    "route sets without a supported dependency model are refused")

VERDICTS = ("PASS", "FAIL", "UNSUPPORTED")

class SharedResourceDeadlockError(ValueError, SemanticError):
    """The verdict request is malformed — fail closed."""

@dataclass(frozen=True)
class SharedResourceDeadlockVerdict:
    """The verdict, the method, and the witness when there is one."""

    proof_method: str
    verdict: str
    route_artifact_id: str
    routing_class: str
    node_count: int
    edge_count: int
    cycle: tuple[Any, ...] = ()
    reason: str = ""
    topology_hash: str = ""
    rank_proof_id: str = ""

    @property
    def passed(self) -> bool:
        return self.verdict == "PASS"

    def as_dict(self) -> dict[str, Any]:
        return {
            "proof_method": self.proof_method,
            "verdict": self.verdict,
            "route_artifact_id": self.route_artifact_id,
            "routing_class": self.routing_class,
            "node_count": self.node_count,
            "edge_count": self.edge_count,
            "cycle": [[str(resource), vc] for resource, vc in self.cycle],
            "reason": self.reason,
            "tool": SHARED_RESOURCE_DEADLOCK_TOOL,
            "scope": SHARED_RESOURCE_DEADLOCK_SCOPE,
            **({"topology_hash": self.topology_hash, "rank_proof_id": self.rank_proof_id}
               if self.rank_proof_id else {}),
        }

_CHANNEL_VC_DEPENDENCY_ACYCLIC = "CHANNEL_VC_DEPENDENCY_ACYCLIC"

def _verdict(route: Any, cdg: SharedResourceCDG,
             *, reason: str = "") -> SharedResourceDeadlockVerdict:
    cycle = cdg.find_cycle()
    if cycle is None:
        return SharedResourceDeadlockVerdict(
            proof_method=_CHANNEL_VC_DEPENDENCY_ACYCLIC, verdict="PASS",
            route_artifact_id=route.route_artifact_id(),
            routing_class=route.routing_class, node_count=cdg.node_count,
            edge_count=cdg.edge_count,
            reason=reason or (
                "no cycle in the concrete (resource, vc) dependency graph "
                f"({cdg.node_count} nodes, {cdg.edge_count} edges)"))
    return SharedResourceDeadlockVerdict(
        proof_method=_CHANNEL_VC_DEPENDENCY_ACYCLIC, verdict="FAIL",
        route_artifact_id=route.route_artifact_id(),
        routing_class=route.routing_class, node_count=cdg.node_count,
        edge_count=cdg.edge_count, cycle=tuple(cycle),
        reason="the shared-resource dependency graph contains a cycle: "
               + " -> ".join(f"{resource}@{vc}" for resource, vc in cycle))

def verify_shared_resource_deadlock(route: Any, *, topology: Any = None
                                    ) -> SharedResourceDeadlockVerdict:
    """Check modeled dependencies; hybrid PASS requires topology binding.

    No hybrid escape role/subfunction is declared by the canonical model.
    Complete-union acyclicity is not an escape or allocator progress theorem.
    """
    from veritx_dse.model.route_artifact_v3 import (
        RouteArtifactV3, ShapePolicyRoute,
    )
    from veritx_dse.model.srota_rank_route import RankPolicyRoute, SrotaRankRouteError
    from veritx_dse.model.gec_hybrid_route import GecHybridRoute, GecHybridCandidateError
    if not isinstance(route, (RouteArtifactV3, ShapePolicyRoute,
                              RankPolicyRoute, GecHybridRoute)):
        raise SharedResourceDeadlockError(
            f"route must be a RouteArtifactV3, a ShapePolicyRoute or a "
            f"RankPolicyRoute, got {type(route).__name__}")
    rank_proof = None
    try:
        if isinstance(route, GecHybridRoute):
            from veritx_dse.model.topology_artifact import TopologyArtifact
            from veritx_dse.verification.gec_hybrid_instance import prove_gec_hybrid_instance
            if not isinstance(topology, TopologyArtifact):
                raise GecHybridCandidateError("hybrid verdict requires the actual topology artifact")
            route.validate_against(topology)
            rank_proof = prove_gec_hybrid_instance(route.params, topology)
        cdg = route.shared_resource_cdg()
        if isinstance(route, GecHybridRoute):
            if cdg.nodes != rank_proof.graph.nodes or cdg.edges != rank_proof.graph.edges:
                raise GecHybridCandidateError("hybrid graph differs from the complete ranked candidate union")
            cdg = SharedResourceCDG(cdg.nodes, cdg.edges, cdg.partition_to_vcs)
    except (SharedResourceCDGError, GecHybridCandidateError, SrotaRankRouteError) as exc:
        # Refused, not passed. A table with no consistent graph is exactly
        # the case where a lenient reading would report safety for a fabric
        # nothing checked.
        return SharedResourceDeadlockVerdict(
            proof_method=_CHANNEL_VC_DEPENDENCY_ACYCLIC,
            verdict="UNSUPPORTED",
            route_artifact_id=route.route_artifact_id(),
            routing_class=route.routing_class, node_count=0, edge_count=0,
            reason=f"no dependency graph could be built from this route: "
                   f"{exc}")
    result = _verdict(route, cdg)
    if rank_proof is not None:
        from dataclasses import replace
        result = replace(result, topology_hash=rank_proof.topology_hash,
                         rank_proof_id=rank_proof.proof_id(),
                         reason=result.reason + "; complete topology-bound candidate union only, not an ESCAPE theorem")
    return result

__all__ = [
    "SharedResourceDeadlockError", "SharedResourceDeadlockVerdict",
    "verify_shared_resource_deadlock", "VERDICTS",
    "SHARED_RESOURCE_DEADLOCK_TOOL", "SHARED_RESOURCE_DEADLOCK_SCOPE",
]
