"""Rank-proof invariants and negative controls, not an escape-VC theorem."""
from dataclasses import replace

import pytest

from veritx_dse.model.shared_resource import ResourceKind, ResourceRef
from veritx_dse.model.topology_artifact import materialize_gec_hybrid
from veritx_dse.verification import gec_hybrid_instance as proof
from veritx_dse.verification.gec_hybrid_candidate_cdg import (
    GecHybridCandidateError, GecHybridParams,
)


def _instance(k=3, c=1, o=1, d=2):
    params = GecHybridParams(k=k, c=c, o=o, d=d, num_vcs=2*d)
    topology = materialize_gec_hybrid(k=k, concentration=c, o=o, d=d)
    return params, topology


@pytest.mark.parametrize("k,c,o,d", [(3, 1, 1, 2), (4, 2, 1, 3), (5, 1, 2, 2)])
def test_bound_union_has_strict_resource_rank(k, c, o, d):
    params, topology = _instance(k, c, o, d)
    result = proof.prove_gec_hybrid_instance(params, topology)
    ranks = dict(result.resource_ranks)
    assert result.graph.find_cycle() is None
    assert all(ranks[a[0]] < ranks[b[0]] for a, b in result.graph.edges)
    assert result.topology_hash == topology.topology_hash()
    assert result.to_dict()["scope"] == "STRUCTURAL_CANDIDATE_UNION_ONLY"
    assert "ESCAPE" not in result.to_dict()["proof_method"]
    assert result.proof_id() == proof.prove_gec_hybrid_instance(params, topology).proof_id()


def test_proof_uses_actual_resource_ids_not_synthetic_port_offsets():
    params, topology = _instance()
    topology = replace(topology,
        channels=tuple(replace(ch, channel_id=i)
                       for i, ch in enumerate(reversed(topology.channels))),
        shared_links=tuple(replace(w, shared_link_id=i)
                           for i, w in enumerate(reversed(topology.shared_links))))
    result = proof.prove_gec_hybrid_instance(params, topology)
    actual = {ResourceRef(ResourceKind.CHANNEL, ch.channel_id)
              for ch in topology.channels} | {
        ResourceRef(ResourceKind.SHARED_LINK, w.shared_link_id)
        for w in topology.shared_links}
    assert {r for r, _vc in result.graph.nodes} == actual


def test_wrong_tap_order_refuses_instead_of_certifying_a_different_fabric():
    params, topology = _instance()
    changed = replace(topology.shared_links[0],
                      taps=tuple(reversed(topology.shared_links[0].taps)))
    topology = replace(topology, shared_links=(changed,) + topology.shared_links[1:])
    with pytest.raises(GecHybridCandidateError, match="tap ordering"):
        proof.prove_gec_hybrid_instance(params, topology)


def test_missing_mesh_edge_refuses():
    params, topology = _instance()
    topology = replace(topology, channels=topology.channels[:-1])
    with pytest.raises(GecHybridCandidateError, match="mesh channels"):
        proof.prove_gec_hybrid_instance(params, topology)


def test_backward_dependency_fails_rank_proof(monkeypatch):
    params, topology = _instance()
    graph = proof.build_gec_hybrid_candidate_cdg(params)
    first, second = graph.edges[0]
    broken = replace(graph, edges=graph.edges + ((second, first),))
    monkeypatch.setattr(proof, "build_gec_hybrid_candidate_cdg", lambda _p: broken)
    with pytest.raises(GecHybridCandidateError, match="strict resource rank"):
        proof.prove_gec_hybrid_instance(params, topology)


def test_proof_identity_binds_vc_count_even_when_extra_vc_is_unused():
    params, topology = _instance()
    a = proof.prove_gec_hybrid_instance(params, topology)
    b = proof.prove_gec_hybrid_instance(replace(params, num_vcs=5), topology)
    assert a.graph.nodes == b.graph.nodes  # odd tail VC is unused by the source
    assert a.proof_id() != b.proof_id()


@pytest.mark.parametrize("k,c,o,d", [(3, 1, 1, 2), (4, 2, 1, 3), (5, 1, 2, 2)])
def test_standalone_hybrid_verdict_binds_complete_topology_union(k, c, o, d):
    from veritx_dse.model.gec_hybrid_route import gec_hybrid_route_for_topology
    from veritx_dse.verification.shared_resource_deadlock import verify_shared_resource_deadlock
    params, topology = _instance(k, c, o, d)
    route = gec_hybrid_route_for_topology(params, topology)
    verdict = verify_shared_resource_deadlock(route, topology=topology)
    assert verdict.verdict == "PASS"
    assert verdict.route_artifact_id == route.route_artifact_id()
    assert verdict.topology_hash == topology.topology_hash()
    assert verdict.rank_proof_id == proof.prove_gec_hybrid_instance(params, topology).proof_id()
    assert "not an ESCAPE theorem" in verdict.reason
    assert verify_shared_resource_deadlock(route).verdict == "UNSUPPORTED"


@pytest.mark.parametrize("tamper", ["missing_context", "missing_mecs", "tap", "landing", "resource", "phase", "hash"])
def test_hybrid_verdict_refuses_incomplete_or_rewritten_candidates(tamper):
    from veritx_dse.model.gec_hybrid_route import gec_hybrid_route_for_topology
    from veritx_dse.verification.shared_resource_deadlock import verify_shared_resource_deadlock
    params, topology = _instance()
    route = gec_hybrid_route_for_topology(params, topology)
    choices = dict(route.choices)
    key = (0, 8)
    options = choices[key]
    mesh_index = next(i for i, option in enumerate(options) if option.resource.kind is ResourceKind.CHANNEL)
    mecs_index = next(i for i, option in enumerate(options) if option.resource.kind is ResourceKind.SHARED_LINK)
    if tamper == "missing_context":
        del choices[key]
    elif tamper == "missing_mecs":
        choices[key] = tuple(o for o in options if o.resource.kind is ResourceKind.CHANNEL)
    elif tamper != "hash":
        index = mecs_index if tamper == "tap" else mesh_index
        changed = options[index]
        if tamper == "tap":
            changed = replace(changed, tap=1 - changed.tap)
        elif tamper == "landing":
            changed = replace(changed, next_router=0)
        elif tamper == "resource":
            changed = replace(changed, resource=ResourceRef(ResourceKind.CHANNEL, 999))
        elif tamper == "phase":
            changed = replace(changed, vc_partition=params.num_vcs - 1)
        choices[key] = options[:index] + (changed,) + options[index + 1:]
    broken = replace(route, choices=choices, topology_hash="wrong" if tamper == "hash" else route.topology_hash)
    verdict = verify_shared_resource_deadlock(broken, topology=topology)
    assert verdict.verdict == "UNSUPPORTED"
    assert not verdict.passed
    assert not verdict.rank_proof_id


def test_hybrid_verdict_refuses_a_backwards_or_cyclic_graph(monkeypatch):
    from veritx_dse.model.gec_hybrid_route import GecHybridRoute, gec_hybrid_route_for_topology
    from veritx_dse.verification.shared_resource_deadlock import verify_shared_resource_deadlock
    params, topology = _instance()
    route = gec_hybrid_route_for_topology(params, topology)
    graph = route.shared_resource_cdg()
    a, b = graph.edges[0]
    broken = replace(graph, edges=graph.edges + ((b, a),))
    monkeypatch.setattr(GecHybridRoute, "shared_resource_cdg", lambda _route: broken)
    verdict = verify_shared_resource_deadlock(route, topology=topology)
    assert verdict.verdict == "UNSUPPORTED"
    assert "ranked candidate union" in verdict.reason
