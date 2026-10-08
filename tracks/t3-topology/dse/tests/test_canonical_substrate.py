"""Phase A primitives: identity, finite state, concrete allocation and reproof."""
from dataclasses import replace
import json

import pytest

from veritx_dse.core.errors import InvalidInput, EvidenceInvalid, UnsupportedSemantics
from veritx_dse.model.resource_graph import ResourceGraph, TransportResource, resource_graph_from_topology
from veritx_dse.model.resource_allocation import ResourceAllocationArtifact, allocation_from_assignment
from veritx_dse.model.shared_resource import ResourceRef, ResourceKind
from veritx_dse.model.routing_policy_artifact import (
    RoutingPolicyArtifact, RoutingContext, RouteAction, RoutingRule, normalize_legacy_route,
)
from veritx_dse.model.routing_relation import RoutingStateBinding, RoutingStateDomain
from veritx_dse.model.vc_resource import VCResourceArtifact
from veritx_dse.verification.dependency_proof import (
    DependencyGraph, DependencyProof, prove_dependencies, ProofStrategy,
)


def ref(i, shared=False):
    return ResourceRef(ResourceKind.SHARED_LINK if shared else ResourceKind.CHANNEL, i)


def graph():
    return ResourceGraph("authored-test-topology", (0, 1, 2, 3), (
        TransportResource(ref(0), 0, (1,), 64, 1),
        TransportResource(ref(1), 1, (3,), 64, 1),
        TransportResource(ref(2), 0, (2,), 64, 1),
        TransportResource(ref(3), 2, (3,), 64, 1),
        TransportResource(ref(0, True), 0, (2, 1), 64, 1)))


def allocation(count=1):
    ids = tuple(range(count))
    resources = VCResourceArtifact(count, ids, (("DATA", ids),), tuple((v, v) for v in ids))
    return ResourceAllocationArtifact(resources, tuple((str(v), (v,)) for v in ids))


def diamond(*, stateful=False):
    g = graph()
    a = allocation(2 if stateful else 1)
    row = (RoutingStateBinding("shape", "ROW"),) if stateful else ()
    col = (RoutingStateBinding("shape", "COLUMN"),) if stateful else ()
    start = RoutingContext(0, 3, row)
    rules = [RoutingRule(start, (RouteAction(ref(0), 1, "0", row),))]
    starts = [start]
    if stateful:
        starts.append(RoutingContext(0, 3, col))
        rules.append(RoutingRule(starts[-1], (RouteAction(ref(2), 2, "1", col),)))
    else:
        rules[0] = RoutingRule(start, (RouteAction(ref(0), 1, "0"), RouteAction(ref(2), 2, "0")))
    rules.extend((RoutingRule(RoutingContext(1, 3, row), (RouteAction(ref(1), 3, "0", row),)),
                  RoutingRule(RoutingContext(2, 3, col), (RouteAction(ref(3), 3, "1" if stateful else "0", col),)),
                  RoutingRule(RoutingContext(3, 3, row), (RouteAction(None, 3, None),))))
    if stateful:
        rules.append(RoutingRule(RoutingContext(3, 3, col), (RouteAction(None, 3, None),)))
    p = RoutingPolicyArtifact(g.artifact_id(), "declared-diamond/v1",
        (RoutingStateDomain("shape", ("ROW", "COLUMN")),) if stateful else (),
        tuple(starts), tuple(rules), ((row, row), (col, col)) if stateful else (((), ()),))
    return g, p, a


def test_mixed_resource_namespace_and_tap_order_are_canonical():
    g = graph()
    assert g.resource(ref(0)).landing(None) == 1
    assert g.resource(ref(0, True)).landing(0) == 2
    assert g.resource(ref(0, True)).landing(1) == 1
    assert g.artifact_id() == replace(g, resources=tuple(reversed(g.resources))).artifact_id()
    wire = g.resource(ref(0, True))
    assert replace(g, resources=tuple(replace(r, destinations=(1, 2)) if r == wire else r for r in g.resources)).artifact_id() != g.artifact_id()


@pytest.mark.parametrize("change", [dict(source=9), dict(destinations=(9,)), dict(destinations=(0,))])
def test_invalid_resource_endpoints_refuse(change):
    if change == dict(destinations=(0,)):
        with pytest.raises(InvalidInput):
            replace(graph().resource(ref(0)), **change)
    else:
        with pytest.raises(InvalidInput, match="missing router"):
            replace(graph(), resources=(replace(graph().resource(ref(0)), **change),))


def test_resource_duplicate_and_wrong_tap_refuse():
    g = graph()
    with pytest.raises(InvalidInput, match="duplicate"):
        replace(g, resources=g.resources + (g.resources[0],))
    with pytest.raises(InvalidInput, match="tap"):
        g.resource(ref(0, True)).landing(2)
    with pytest.raises(InvalidInput, match="tap"):
        g.resource(ref(0)).landing(0)


@pytest.mark.parametrize("count", [1, 2, 4])
def test_allocation_and_resource_graph_roundtrip(count):
    a = allocation(count)
    assert ResourceAllocationArtifact.from_dict(json.loads(json.dumps(a.to_dict()))) == a
    g = graph()
    assert ResourceGraph.from_dict(json.loads(json.dumps(g.to_dict()))) == g
    with pytest.raises(InvalidInput):
        a.vcs("not allocated")


@pytest.mark.parametrize("partitions", [(("p", (0,)),), (("p", (0, 1)), ("q", (1,))), (("p", (0, 2)),)])
def test_sparse_overlapping_or_out_of_range_partitions_refuse(partitions):
    with pytest.raises(InvalidInput):
        replace(allocation(2), partitions=partitions)


@pytest.mark.parametrize("stateful", [False, True])
def test_adaptive_relation_and_concrete_proof_roundtrip(stateful):
    g, p, a = diamond(stateful=stateful)
    p.validate_against(g, a)
    assert RoutingPolicyArtifact.from_dict(json.loads(json.dumps(p.to_dict()))) == p
    proof = prove_dependencies(g, p, a)
    assert proof.verdict == "PASS"
    assert len(proof.graph.edges) == 2
    assert DependencyGraph.from_dict(json.loads(json.dumps(proof.graph.to_dict()))) == proof.graph
    assert DependencyProof.from_dict(json.loads(json.dumps(proof.to_dict())), resources=g, policy=p, allocation=a) == proof


def test_initial_state_is_latched_and_illegal_shape_switch_refuses():
    g, p, a = diamond(stateful=True)
    row = next(r for r in p.rules if r.context.router == 1)
    assert row.actions[0].next_state == row.context.state
    col = (RoutingStateBinding("shape", "COLUMN"),)
    changed = replace(row, actions=(replace(row.actions[0], next_state=col),))
    with pytest.raises(InvalidInput, match="illegal adaptive state transition"):
        replace(p, rules=tuple(changed if r == row else r for r in p.rules))


def test_multileg_state_changes_only_through_declared_transition():
    g = graph(); a = allocation()
    leg1 = (RoutingStateBinding("leg", 1),)
    leg2 = (RoutingStateBinding("leg", 2),)
    first = RoutingContext(0, 3, leg1)
    p = RoutingPolicyArtifact(g.artifact_id(), "two-leg/v1", (RoutingStateDomain("leg", (1, 2)),),
        (first,), (RoutingRule(first, (RouteAction(ref(0), 1, "0", leg2),)),
                   RoutingRule(RoutingContext(1, 3, leg2), (RouteAction(ref(1), 3, "0", leg2),)),
                   RoutingRule(RoutingContext(3, 3, leg2), (RouteAction(None, 3, None),))),
        ((leg1, leg2), (leg2, leg2)))
    assert prove_dependencies(g, p, a).verdict == "PASS"
    with pytest.raises(InvalidInput, match="illegal adaptive"):
        replace(p, allowed_state_transitions=((leg1, leg1), (leg2, leg2)))


@pytest.mark.parametrize("change", [dict(next_router=2), dict(resource=ref(3)), dict(vc_partition="unknown")])
def test_wrong_resource_next_router_or_partition_refuses(change):
    g, p, a = diamond()
    rule = next(r for r in p.rules if r.context.router == 1)
    bad = replace(rule, actions=(replace(rule.actions[0], **change),))
    changed = replace(p, rules=tuple(bad if r == rule else r for r in p.rules))
    with pytest.raises(InvalidInput):
        changed.validate_against(g, a)


def test_missing_and_unreachable_contexts_refuse():
    g, p, a = diamond()
    with pytest.raises(InvalidInput, match="missing"):
        replace(p, rules=tuple(r for r in p.rules if r.context.router != 1)).validate_against(g, a)
    extra = RoutingRule(RoutingContext(2, 2), (RouteAction(None, 2, None),))
    with pytest.raises(InvalidInput, match="unreachable"):
        replace(p, rules=p.rules + (extra,)).validate_against(g, a)


def test_cached_empty_graph_cannot_produce_pass():
    g, p, a = diamond()
    proof = prove_dependencies(g, p, a)
    with pytest.raises(EvidenceInvalid, match="parent-recomputed"):
        prove_dependencies(g, p, a, stored_graph=replace(proof.graph, nodes=(), edges=()))
    with pytest.raises(EvidenceInvalid, match="parent-recomputed"):
        replace(proof, graph=replace(proof.graph, edges=())).revalidate(g, p, a)


def test_cycle_and_self_loop_are_not_erased():
    g = ResourceGraph("cycle", (0, 1, 2), (
        TransportResource(ref(0), 0, (1,), 64, 1), TransportResource(ref(1), 1, (0,), 64, 1)))
    a = allocation()
    p = RoutingPolicyArtifact(g.artifact_id(), "loop/v1", (), (RoutingContext(0, 2),), (
        RoutingRule(RoutingContext(0, 2), (RouteAction(ref(0), 1, "0"),)),
        RoutingRule(RoutingContext(1, 2), (RouteAction(ref(1), 0, "0"),))), (((), ()),))
    proof = prove_dependencies(g, p, a)
    assert proof.verdict == "FAIL" and proof.cycle
    node = proof.graph.nodes[0]
    loop = replace(proof.graph, nodes=(node,), edges=((node, node),))
    assert loop.find_cycle() == [node, node]


def test_rank_recomputes_and_rank_violation_fails():
    g, p, a = diamond()
    p = replace(p, proof_strategy="STRICT_RESOURCE_RANK")
    provider = lambda _g, _p, _a, dep: {n: n[0].resource_id for n in dep.nodes}
    proof = prove_dependencies(g, p, a, rank_provider=provider)
    assert proof.strategy is ProofStrategy.STRICT_RESOURCE_RANK and proof.verdict == "PASS"
    assert prove_dependencies(g, p, a, rank_provider=lambda _g, _p, _a, dep: {n: 0 for n in dep.nodes}).verdict == "FAIL"
    changed = replace(proof, ranks=tuple((n, 99) for n, _r in proof.ranks))
    with pytest.raises(EvidenceInvalid):
        changed.revalidate(g, p, a, rank_provider=provider)
    with pytest.raises(UnsupportedSemantics):
        prove_dependencies(g, p, a)


def test_no_invented_escape_theorem():
    g, p, a = diamond()
    with pytest.raises(UnsupportedSemantics, match="accessibility/closure"):
        prove_dependencies(g, replace(p, proof_strategy="ESCAPE_SUBNETWORK"), a)


def test_parent_mutations_change_proof_identity():
    g, p, a = diamond()
    before = prove_dependencies(g, p, a).artifact_id()
    changed = replace(a, buffer_policy={"input_depth": 8})
    assert prove_dependencies(g, p, changed).artifact_id() != before
    assert replace(p, source_policy_id="another-declaration").artifact_id() != p.artifact_id()


def test_p2p_legacy_adapter_preserves_legacy_identity():
    from veritx_dse.application.fabric_compiler import FabricCompiler
    from veritx_dse.application.compile_intent import build_preset_request
    c = FabricCompiler().compile(build_preset_request("mesh4_hbm"))
    root = c.compiled_system
    assert root.routing_policy is not None and root.dependency_proof.verdict == "PASS"
    assert root.routing_policy.source_policy_id == c.bundle.router_route.artifact_hash
    assert root.child_identities()["router_route_hash"] == c.bundle.router_route.artifact_hash


def test_multidrop_adapter_requires_an_explicit_consistent_transit_allocation():
    from veritx_dse.application.fabric_compiler import FabricCompiler
    from veritx_dse.application.presets import build_typed_preset_request
    c = FabricCompiler().compile(build_typed_preset_request("gec_mecs16"))
    g = resource_graph_from_topology(c.bundle.topology)
    route = c.bundle.router_route
    a = allocation_from_assignment(c.bundle.vc_assignment, route)
    with pytest.raises(UnsupportedSemantics, match="transit transitions"):
        normalize_legacy_route(c.bundle.topology, route, a, g)
    a = replace(a, resources=replace(a.resources, allowed_transitions=route.allowed_transitions, artifact_hash=""))
    p = normalize_legacy_route(c.bundle.topology, route, a, g)
    assert prove_dependencies(g, p, a).verdict == "PASS"
    assert all(g.resource(action.resource).source == rule.context.router for rule in p.rules for action in rule.actions if not action.eject)


def test_indexed_256_router_512_resource_proof():
    # Large sparse declared flow set: no Cartesian state-space materialization.
    resources = tuple(TransportResource(ref(i), i % 256, ((i + 1) % 256,), 64, 1)
                      for i in range(512))
    g = ResourceGraph("256-router-sparse", tuple(range(256)), resources)
    a = allocation()
    rules = tuple(RoutingRule(RoutingContext(i, (i + 1) % 256),
                              (RouteAction(ref(i), (i + 1) % 256, "0"),)) for i in range(256))
    ejections = tuple(RoutingRule(RoutingContext(i, i), (RouteAction(None, i, None),)) for i in range(256))
    p = RoutingPolicyArtifact(g.artifact_id(), "one-hop/v1", (), tuple(r.context for r in rules),
                              rules + ejections, (((), ()),))
    proof = prove_dependencies(g, p, a)
    assert proof.verdict == "PASS" and len(g.resources) == 512 and len(proof.graph.nodes) == 256
