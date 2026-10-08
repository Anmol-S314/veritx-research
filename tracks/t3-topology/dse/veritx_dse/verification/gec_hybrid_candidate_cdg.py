"""Conservative candidate-union CDG for BookSim ``hybrid_gec``.

Every runtime-selected dependency is included. A cycle is inconclusive,
not an escape-subnetwork counterexample. Candidate semantics live in the
model layer; historical imports remain available here for compatibility.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from veritx_dse.model.gec_hybrid_route import (
    GecHybridCandidateError, GecHybridParams, GecHybridCandidate,
    gec_hybrid_candidates, select_gec_hybrid_candidate,
)
from veritx_dse.model.shared_resource import ResourceVC
from veritx_dse.verification.shared_resource_cdg import SharedResourceCDG

GEC_HYBRID_CANDIDATE_CDG_V1 = "GEC_HYBRID_CANDIDATE_CDG_V1"


@dataclass(frozen=True)
class GecHybridCandidateCDG:
    nodes: tuple[ResourceVC, ...]
    edges: tuple[tuple[ResourceVC, ResourceVC], ...]
    candidate_count: int
    vc_count: int

    def find_cycle(self) -> list[ResourceVC] | None:
        return SharedResourceCDG(
            nodes=self.nodes, edges=self.edges, partition_to_vcs={}
        ).find_cycle()

    def canonical_dict(self) -> dict[str, Any]:
        return {
            "proof_method": GEC_HYBRID_CANDIDATE_CDG_V1,
            "nodes": [[resource.to_dict(), vc] for resource, vc in self.nodes],
            "edges": [[[a[0].to_dict(), a[1]], [b[0].to_dict(), b[1]]]
                      for a, b in self.edges],
            "candidate_count": self.candidate_count,
            "vc_count": self.vc_count,
        }


def build_gec_hybrid_candidate_cdg(params: GecHybridParams) -> GecHybridCandidateCDG:
    """All source-legal consecutive resource/VC dependencies, before binding."""
    if not isinstance(params, GecHybridParams):
        raise GecHybridCandidateError("params must be GecHybridParams")
    hops, nodes = {}, set()
    candidate_count = 0
    for src in range(params.router_count):
        for dest in range(params.node_count):
            row = gec_hybrid_candidates(params, src_router=src, dest_node=dest)
            hops[(src, dest)] = row
            candidate_count += len(row)
            for hop in row:
                nodes.update((hop.resource, vc) for vc in hop.vcs)
    edges = set()
    for (_src, dest), first_hops in hops.items():
        for first in first_hops:
            for second in hops[(first.next_router, dest)]:
                if first.phase > second.phase:
                    raise GecHybridCandidateError("candidate route violates X-before-Y phase order")
                for vc_in in first.vcs:
                    for vc_out in second.vcs:
                        edges.add(((first.resource, vc_in), (second.resource, vc_out)))
    return GecHybridCandidateCDG(tuple(sorted(nodes)), tuple(sorted(edges)),
                                 candidate_count, params.num_vcs)


__all__ = [
    "GEC_HYBRID_CANDIDATE_CDG_V1", "GecHybridCandidateError", "GecHybridParams",
    "GecHybridCandidate", "GecHybridCandidateCDG", "gec_hybrid_candidates",
    "select_gec_hybrid_candidate", "build_gec_hybrid_candidate_cdg",
]
