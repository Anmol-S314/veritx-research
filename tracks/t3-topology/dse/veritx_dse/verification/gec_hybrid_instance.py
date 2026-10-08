"""Topology-bound, per-instance proof for the hybrid candidate union.

The source resolves X before Y. Within a dimension, mesh hops advance in
one direction; a MECS jump finishes that dimension. Thus mesh resources
precede that dimension's shared wires, and all X resources precede all Y
resources. A strict integer rank on every union edge proves acyclicity
without inventing a distinguished escape VC.

This is a standalone structural check, not a compiler certificate, escape
subnetwork theorem, allocator-fairness proof, or execution qualification.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from veritx_dse.core.artifact import content_id
from veritx_dse.model.shared_resource import ResourceKind, ResourceRef
from veritx_dse.model.topology_artifact import (
    MaterializedFamily, TopologyArtifact, materialize_gec_hybrid,
)
from veritx_dse.verification.gec_hybrid_candidate_cdg import (
    GecHybridCandidateCDG, GecHybridCandidateError, GecHybridParams,
    build_gec_hybrid_candidate_cdg, gec_hybrid_candidates,
)

GEC_HYBRID_INSTANCE_PROOF_V1 = "GEC_HYBRID_RANKED_CANDIDATE_UNION_V1"


@dataclass(frozen=True)
class GecHybridInstanceProof:
    topology_hash: str
    params: GecHybridParams
    graph: GecHybridCandidateCDG
    resource_ranks: tuple[tuple[ResourceRef, int], ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "proof_method": GEC_HYBRID_INSTANCE_PROOF_V1,
            "scope": "STRUCTURAL_CANDIDATE_UNION_ONLY",
            "topology_hash": self.topology_hash,
            "params": {name: getattr(self.params, name)
                       for name in ("k", "c", "o", "d", "num_vcs")},
            "graph": self.graph.canonical_dict(),
            "resource_ranks": [[r.to_dict(), rank]
                               for r, rank in self.resource_ranks],
        }

    def proof_id(self) -> str:
        return content_id("srota/GecHybridInstanceProof/v1", self.to_dict())


def prove_gec_hybrid_instance(
        params: GecHybridParams, topology: TopologyArtifact
) -> GecHybridInstanceProof:
    """Bind every candidate to a real resource and check strict edge ranks.

    Invalid geometry, taps, or routing invariants refuse rather than return
    a vacuous proof. Actual IDs need not match the materializer's numbering.
    """
    if not isinstance(params, GecHybridParams):
        raise GecHybridCandidateError("params must be GecHybridParams")
    if not isinstance(topology, TopologyArtifact) or \
            topology.family is not MaterializedFamily.GEC_HYBRID:
        raise GecHybridCandidateError("topology must be a GEC_HYBRID artifact")
    expected = materialize_gec_hybrid(
        k=params.k, concentration=params.c, o=params.o, d=params.d)
    if topology.routers != expected.routers:
        raise GecHybridCandidateError("router geometry does not match params")
    channels = {(ch.src_router, ch.dst_router): ch for ch in topology.channels}
    wires = {(wire.src_router, wire.taps): wire
             for wire in topology.shared_links}
    if len(channels) != len(topology.channels) or set(channels) != {
            (ch.src_router, ch.dst_router) for ch in expected.channels}:
        raise GecHybridCandidateError("mesh channels do not match params")
    if len(wires) != len(topology.shared_links) or set(wires) != {
            (wire.src_router, wire.taps) for wire in expected.shared_links}:
        raise GecHybridCandidateError("shared wire tap ordering does not match params")

    k = params.k
    bindings: dict[ResourceRef, ResourceRef] = {}
    ranks: dict[ResourceRef, int] = {}
    for src in range(params.router_count):
        x, y = src % k, src // k
        for dest in range(params.node_count):
            dst = dest // params.c
            dx, dy = dst % k, dst // k
            remaining = abs(dx - x) + abs(dy - y)
            for hop in gec_hybrid_candidates(params, src_router=src, dest_node=dest):
                nx, ny = hop.next_router % k, hop.next_router // k
                if abs(dx - nx) + abs(dy - ny) >= remaining:
                    raise GecHybridCandidateError("candidate does not approach destination")
                if hop.is_mesh:
                    channel = channels.get((src, hop.next_router))
                    if channel is None:
                        raise GecHybridCandidateError("candidate names no mesh channel")
                    resource = ResourceRef(ResourceKind.CHANNEL, channel.channel_id)
                    position, next_position = (x, nx) if hop.phase == 0 else (y, ny)
                    rank = position if next_position > position else k - 1 - position
                    if hop.phase == 1:
                        rank += k + 1
                else:
                    peers = [q for q in range(k) if q != (x if hop.phase == 0 else y)]
                    target = nx if hop.phase == 0 else ny
                    group = peers.index(target) // params.d
                    selected = peers[group * params.d:(group + 1) * params.d]
                    taps = tuple(y * k + q if hop.phase == 0 else q * k + x
                                 for q in selected)
                    wire = wires[(src, taps)]
                    if hop.tap is None or wire.taps[hop.tap] != hop.next_router:
                        raise GecHybridCandidateError("candidate tap lands on the wrong router")
                    resource = ResourceRef(ResourceKind.SHARED_LINK, wire.shared_link_id)
                    rank = k if hop.phase == 0 else 2 * k + 1
                if hop.resource in bindings and bindings[hop.resource] != resource:
                    raise GecHybridCandidateError("analysis resource aliases two real resources")
                bindings[hop.resource] = resource
                if resource in ranks and ranks[resource] != rank:
                    raise GecHybridCandidateError("resource rank depends on destination")
                ranks[resource] = rank

    analysis = build_gec_hybrid_candidate_cdg(params)
    def bind(node):
        resource, vc = node
        if resource not in bindings:
            raise GecHybridCandidateError("candidate graph names an unbound resource")
        if type(vc) is not int or not 0 <= vc < params.num_vcs:
            raise GecHybridCandidateError("candidate graph VC is out of range")
        return bindings[resource], vc

    nodes = tuple(sorted({bind(node) for node in analysis.nodes}))
    edges = tuple(sorted({(bind(a), bind(b)) for a, b in analysis.edges}))
    node_set = set(nodes)
    for a, b in edges:
        if a not in node_set or b not in node_set:
            raise GecHybridCandidateError("candidate edge endpoint is absent")
        if ranks[a[0]] >= ranks[b[0]]:
            raise GecHybridCandidateError("candidate edge violates strict resource rank")
    if not nodes or not edges:
        raise GecHybridCandidateError("candidate graph is empty")
    return GecHybridInstanceProof(
        topology_hash=topology.topology_hash(), params=params,
        graph=GecHybridCandidateCDG(
            nodes=nodes, edges=edges, candidate_count=analysis.candidate_count,
            vc_count=analysis.vc_count),
        resource_ranks=tuple(sorted(ranks.items())))
