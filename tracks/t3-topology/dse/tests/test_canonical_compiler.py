"""Canonical candidate compiler tests — orchestration, not reinterpretation.

The compiler sequences the sealed Slice 2-22 authorities. These tests prove
it reproduces independently built children byte-for-byte, is deterministic,
attributes failures to stable stages, and never becomes a second semantic
authority.
"""
from __future__ import annotations

import ast
import dataclasses
import inspect

import pytest

from veritx_dse.compiler import canonical as cc
from veritx_dse.compiler.canonical import (
    CanonicalCompileError, CompileStage, CompiledAdaptiveRouting,
    CompiledDeterministicRouting, CompiledFabric, DeterministicVCSpec,
    FabricCompileSettings, ROUTE_ARTIFACT_NAME, RoutingRoleBindingSpec,
    VCResourceSpec, compile_adaptive_candidate, compile_deterministic_candidate,
)
from veritx_dse.core.route_artifact import ANYNET_MIN_HOPS, DOR_XY, RouteArtifact
from veritx_dse.model.address_decode import derive_address_decode
from veritx_dse.model.attachment import derive_attachment
from veritx_dse.model.compile_model import (
    AddressMap, AddressRange, Agent, AgentKind, CompileRequest, ModelFamily,
    NocConfig, QoSClass, Requirement, TopologyFamily, Workload,
)
from veritx_dse.model.fabric_artifact import (
    make_adaptive_fabric, make_deterministic_fabric,
)
from veritx_dse.model.mapping import MappingArtifact, RankPlacement, derive_mapping
from veritx_dse.model.packet_format import derive_packet_format
from veritx_dse.model.placement import build_inventory
from veritx_dse.model.resolved_fabric import (
    make_resolved_adaptive_fabric, make_resolved_deterministic_fabric,
)
from veritx_dse.model.resolved_route import derive_resolved_route
from veritx_dse.model.router_behavior import derive_router_behavior
from veritx_dse.model.routing_policy import (
    CandidateMode, DeadlockProofObligation, DecisionScope, PathMode,
    RandomnessMode, RoutingPolicyDefinition, RoutingResourceRole,
    RoutingResourceRoleKind, RuntimeObservation, SelectionLocus,
)
from veritx_dse.model.routing_realization import (
    make_adaptive_routing_realization, make_deterministic_routing_realization,
)
from veritx_dse.model.routing_relation_materialize import (
    materialize_routing_relation,
)
from veritx_dse.model.routing_resource_binding import (
    RoutingResourceBindingArtifact,
)
from veritx_dse.model.topology_artifact import materialize_topology
from veritx_dse.model.vc_assignment import make_vc_assignment_artifact
from veritx_dse.model.vc_resource import (
    VCResourceArtifact, vc_resources_from_assignment,
)

GOLDEN_DET = "0fba2ac3b154e7fe567e389a0865fa7fa7246f4c74c7d9afd6f63685b8a2f3e6"
GOLDEN_ADAPT = "128eb287b066d1f1d69be68f08acf1ae988370b2abe8702372ffd46c14f4ce56"
GOLDEN_ADAPT_3X3 = "a687f660a866931b9de11c926d47df5367db731efb101b09577447675191fcbb"

_MIN_ADAPT_TRANSITIONS = (
    (0, 0), (1, 0), (1, 1), (1, 2), (1, 3),
    (2, 0), (2, 1), (2, 2), (2, 3), (3, 0), (3, 1), (3, 2), (3, 3),
)


# ── fixtures ───────────────────────────────────────────────────────────────

def _dor_policy(**over) -> RoutingPolicyDefinition:
    kw = dict(
        id="dor_xy", algorithm="dimension_order", algorithm_version=1,
        path_mode=PathMode.MINIMAL, decision_scope=DecisionScope.STATIC,
        candidate_mode=CandidateMode.SINGLETON,
        selection_locus=SelectionLocus.ROUTE_COMPUTE,
        randomness=RandomnessMode.NONE,
        deadlock_proof_obligation=DeadlockProofObligation.DETERMINISTIC_CDG,
        resource_roles=(RoutingResourceRole(
            id="default", kind=RoutingResourceRoleKind.DEFAULT),),
        allowed_role_transitions=(("default", "default"),))
    kw.update(over)
    return RoutingPolicyDefinition(**kw)


def _anynet_policy(**over) -> RoutingPolicyDefinition:
    return _dor_policy(
        id="anynet_dijkstra", algorithm="weighted_shortest_path",
        parameters={"weight_metric": "hop_count",
                    "tie_break_policy": "anynet_ascending_min"}, **over)


def _min_adapt_policy(**over) -> RoutingPolicyDefinition:
    kw = dict(
        id="min_adapt_like", algorithm="per_hop_min_adaptive",
        algorithm_version=1, path_mode=PathMode.MINIMAL,
        decision_scope=DecisionScope.PER_HOP,
        candidate_mode=CandidateMode.CANDIDATE_SET,
        selection_locus=SelectionLocus.ROUTER_ALLOCATOR,
        randomness=RandomnessMode.NONE,
        deadlock_proof_obligation=DeadlockProofObligation.ESCAPE_SUBFUNCTION,
        runtime_observations=(RuntimeObservation.OUTPUT_CREDIT_OCCUPANCY,),
        resource_roles=(
            RoutingResourceRole(id="adaptive",
                                kind=RoutingResourceRoleKind.ADAPTIVE),
            RoutingResourceRole(id="escape",
                                kind=RoutingResourceRoleKind.ESCAPE)),
        allowed_role_transitions=(("adaptive", "adaptive"),
                                  ("adaptive", "escape"),
                                  ("escape", "escape")))
    kw.update(over)
    return RoutingPolicyDefinition(**kw)


def _design(compute: int = 3, *, tp: int = 1, pp: int = 1, ep: int = 1,
            dp: int = 1, hbm: int = 1, name: str = "HBM0",
            family: TopologyFamily = TopologyFamily.MESH, noc_kw=None,
            requirements=()) -> CompileRequest:
    return CompileRequest(
        workload=Workload(model_family=ModelFamily.MOE, tp=tp, pp=pp, ep=ep,
                          dp=dp),
        requirements=tuple(requirements),
        agents=(Agent(kind=AgentKind.COMPUTE_TILE, count=compute),
                Agent(kind=AgentKind.HBM_CONTROLLER, count=hbm)),
        dependencies=[],
        noc_config=NocConfig(topology_family=family, **(noc_kw or {})),
        address_map=AddressMap(ranges=(
            AddressRange(name=name, base=0x0, size=0x1000,
                         target_agent_idx=1),)))


def _settings(**over) -> FabricCompileSettings:
    kw = dict(max_packet_flits=8, input_buffer_depth_flits_per_vc=8,
              output_stage_depth_flits_per_vc=1)
    kw.update(over)
    return FabricCompileSettings(**kw)


def _vs(**over) -> DeterministicVCSpec:
    kw = dict(vc_count=1, traffic_class_to_vcs=(("default", (0,)),),
              vc_to_routing_class=((0, DOR_XY),),
              allowed_transitions=((0, 0),), escape_vcs=(), derivation="d")
    kw.update(over)
    return DeterministicVCSpec(**kw)


def _vrs(**over) -> VCResourceSpec:
    kw = dict(vc_count=4, traffic_class_to_vcs=(("default", (0, 1, 2, 3)),),
              allowed_transitions=_MIN_ADAPT_TRANSITIONS, derivation="")
    kw.update(over)
    return VCResourceSpec(**kw)


def _rbs(**over) -> RoutingRoleBindingSpec:
    kw = dict(role_to_vcs=(("adaptive", (1, 2, 3)), ("escape", (0,))))
    kw.update(over)
    return RoutingRoleBindingSpec(**kw)


def _det(design=None, *, policy=None, vc_spec=None, mapping=None,
         settings=None) -> CompiledFabric:
    design = design if design is not None else _design()
    return compile_deterministic_candidate(
        design=design, inventory=build_inventory(design),
        mapping=mapping if mapping is not None else derive_mapping(design),
        routing_policy=policy if policy is not None else _dor_policy(),
        vc_spec=vc_spec if vc_spec is not None else _vs(),
        settings=settings if settings is not None else _settings())


def _adapt(design=None, *, policy=None, vc_resource_spec=None,
           role_binding_spec=None, mapping=None,
           settings=None) -> CompiledFabric:
    design = design if design is not None else _design()
    return compile_adaptive_candidate(
        design=design, inventory=build_inventory(design),
        mapping=mapping if mapping is not None else derive_mapping(design),
        routing_policy=policy if policy is not None else _min_adapt_policy(),
        vc_resource_spec=(vc_resource_spec if vc_resource_spec is not None
                          else _vrs()),
        role_binding_spec=(role_binding_spec if role_binding_spec is not None
                           else _rbs()),
        settings=settings if settings is not None else _settings())


def _independent_det(design, policy) -> dict:
    inventory = build_inventory(design)
    topology = materialize_topology(inventory, design)
    attachment = derive_attachment(design=design, inventory=inventory,
                                   topology=topology)
    route = RouteArtifact.from_topology(topology, name=ROUTE_ARTIFACT_NAME,
                                        routing_classes=(DOR_XY,))
    resolved_route = derive_resolved_route(topology, attachment, route)
    vc_assignment = make_vc_assignment_artifact(
        resolved_route=resolved_route, vc_count=1,
        traffic_class_to_vcs={"default": [0]},
        vc_to_routing_class={0: DOR_XY}, allowed_transitions=((0, 0),),
        escape_vcs=(), derivation="d")
    vc_resource = vc_resources_from_assignment(vc_assignment)
    realization = make_deterministic_routing_realization(
        topology=topology, attachment=attachment, route=route,
        resolved_route=resolved_route, vc_assignment=vc_assignment,
        vc_resource=vc_resource)
    packet_format = derive_packet_format(topology, attachment, vc_resource,
                                         max_packet_flits=8)
    router_behavior = derive_router_behavior(vc_resource=vc_resource,
                                             buffer_depth_flits=8)
    address_decode = derive_address_decode(design=design,
                                           attachment=attachment)
    fabric = make_deterministic_fabric(
        topology=topology, attachment=attachment, vc_resource=vc_resource,
        routing_realization=realization, packet_format=packet_format,
        router_behavior=router_behavior, address_decode=address_decode,
        route=route, resolved_route=resolved_route,
        vc_assignment=vc_assignment)
    resolved_fabric = make_resolved_deterministic_fabric(
        design=design, inventory=inventory, mapping=derive_mapping(design),
        topology=topology, attachment=attachment, vc_resource=vc_resource,
        routing_realization=realization, packet_format=packet_format,
        router_behavior=router_behavior, address_decode=address_decode,
        fabric=fabric, route=route, resolved_route=resolved_route,
        vc_assignment=vc_assignment)
    return dict(topology=topology, attachment=attachment, route=route,
                resolved_route=resolved_route, vc_assignment=vc_assignment,
                vc_resource=vc_resource, realization=realization,
                packet_format=packet_format, router_behavior=router_behavior,
                address_decode=address_decode, fabric=fabric,
                resolved_fabric=resolved_fabric)


def _independent_adapt(design, policy) -> dict:
    inventory = build_inventory(design)
    topology = materialize_topology(inventory, design)
    attachment = derive_attachment(design=design, inventory=inventory,
                                   topology=topology)
    vc_resource = VCResourceArtifact(
        vc_count=4, vc_ids=(0, 1, 2, 3),
        traffic_class_to_vcs=(("default", (0, 1, 2, 3)),),
        allowed_transitions=_MIN_ADAPT_TRANSITIONS)
    relation = materialize_routing_relation(topology, policy)
    binding = RoutingResourceBindingArtifact(
        policy_hash=policy.policy_hash, vc_resource_hash=vc_resource.artifact_hash,
        role_to_vcs=(("adaptive", (1, 2, 3)), ("escape", (0,))))
    realization = make_adaptive_routing_realization(
        topology=topology, policy=policy, relation=relation,
        vc_resource=vc_resource, binding=binding)
    packet_format = derive_packet_format(topology, attachment, vc_resource,
                                         max_packet_flits=8)
    router_behavior = derive_router_behavior(vc_resource=vc_resource,
                                             buffer_depth_flits=8)
    address_decode = derive_address_decode(design=design,
                                           attachment=attachment)
    fabric = make_adaptive_fabric(
        topology=topology, attachment=attachment, vc_resource=vc_resource,
        routing_realization=realization, packet_format=packet_format,
        router_behavior=router_behavior, address_decode=address_decode,
        policy=policy, relation=relation, binding=binding)
    resolved_fabric = make_resolved_adaptive_fabric(
        design=design, inventory=inventory, mapping=derive_mapping(design),
        topology=topology, attachment=attachment, vc_resource=vc_resource,
        routing_realization=realization, packet_format=packet_format,
        router_behavior=router_behavior, address_decode=address_decode,
        fabric=fabric, policy=policy, relation=relation, binding=binding)
    return dict(topology=topology, attachment=attachment, relation=relation,
                binding=binding, vc_resource=vc_resource,
                realization=realization, packet_format=packet_format,
                router_behavior=router_behavior, address_decode=address_decode,
                fabric=fabric, resolved_fabric=resolved_fabric)


# ── goldens ────────────────────────────────────────────────────────────────

def test_deterministic_slice22_golden_reproduced():
    assert _det().resolved_fabric.resolved_fabric_hash == GOLDEN_DET


def test_adaptive_slice22_golden_reproduced():
    assert _adapt().resolved_fabric.resolved_fabric_hash == GOLDEN_ADAPT


def test_adaptive_3x3_slice22_golden_reproduced():
    assert _adapt(_design(compute=8)).resolved_fabric.resolved_fabric_hash \
        == GOLDEN_ADAPT_3X3


def test_all_intermediate_deterministic_hashes_pinned():
    compiled = _det()
    assert compiled.mapping.mapping_hash() \
        == derive_mapping(compiled.design).mapping_hash()
    assert compiled.topology.topology_hash() \
        == "27327bba5e1339e383a74f78fb38e8ab0e07da9aaa43bc999efb044959d0fdac"
    assert compiled.routing.route.artifact_hash \
        == "sha256:c3f2e5fd87e0efeb53f38d0532854c4727422725077ee44cfd59e6f5a637177b"
    assert compiled.fabric.fabric_hash \
        == "798d0b26fb505cfbf1c80167d9d9b00d5eeedd7be7e4a534a23ada7bfa9351e3"
    assert compiled.resolved_fabric.resolved_fabric_hash == GOLDEN_DET


# ── independent-builder equality ───────────────────────────────────────────

def test_compiler_equals_independent_deterministic_chain():
    design = _design()
    compiled = _det(design)
    independent = _independent_det(design, _dor_policy())
    assert compiled.topology.to_dict() == independent["topology"].to_dict()
    assert compiled.attachment.to_dict() == independent["attachment"].to_dict()
    assert compiled.routing.route.to_dict() == independent["route"].to_dict()
    assert compiled.routing.resolved_route.to_dict() \
        == independent["resolved_route"].to_dict()
    assert compiled.routing.vc_assignment.to_dict() \
        == independent["vc_assignment"].to_dict()
    assert compiled.vc_resource.to_dict() == independent["vc_resource"].to_dict()
    assert compiled.routing_realization.to_dict() \
        == independent["realization"].to_dict()
    assert compiled.packet_format.to_dict() \
        == independent["packet_format"].to_dict()
    assert compiled.router_behavior.to_dict() \
        == independent["router_behavior"].to_dict()
    assert compiled.address_decode.to_dict() \
        == independent["address_decode"].to_dict()
    assert compiled.fabric.to_dict() == independent["fabric"].to_dict()
    assert compiled.resolved_fabric.to_dict() \
        == independent["resolved_fabric"].to_dict()


def test_compiler_equals_independent_adaptive_chain():
    design = _design()
    policy = _min_adapt_policy()
    compiled = _adapt(design, policy=policy)
    independent = _independent_adapt(design, policy)
    assert compiled.topology.to_dict() == independent["topology"].to_dict()
    assert compiled.attachment.to_dict() == independent["attachment"].to_dict()
    assert compiled.routing.routing_relation.to_dict() \
        == independent["relation"].to_dict()
    assert compiled.routing.routing_resource_binding.to_dict() \
        == independent["binding"].to_dict()
    assert compiled.vc_resource.to_dict() == independent["vc_resource"].to_dict()
    assert compiled.routing_realization.to_dict() \
        == independent["realization"].to_dict()
    assert compiled.packet_format.to_dict() \
        == independent["packet_format"].to_dict()
    assert compiled.router_behavior.to_dict() \
        == independent["router_behavior"].to_dict()
    assert compiled.address_decode.to_dict() \
        == independent["address_decode"].to_dict()
    assert compiled.fabric.to_dict() == independent["fabric"].to_dict()
    assert compiled.resolved_fabric.to_dict() \
        == independent["resolved_fabric"].to_dict()


# ── result shape ───────────────────────────────────────────────────────────

def test_result_shape_and_no_independent_hash():
    compiled = _det()
    assert isinstance(compiled, CompiledFabric)
    assert isinstance(compiled.routing, CompiledDeterministicRouting)
    assert not hasattr(compiled, "compiled_fabric_hash")
    assert not hasattr(compiled.resolved_fabric, "compiled_fabric_hash")
    adaptive = _adapt()
    assert isinstance(adaptive.routing, CompiledAdaptiveRouting)
    assert adaptive.routing.routing_relation is not None
    assert adaptive.routing.routing_resource_binding is not None


# ── determinism / repeatability ────────────────────────────────────────────

def _snapshot(compiled: CompiledFabric) -> tuple:
    return (
        compiled.topology.to_dict(), compiled.attachment.to_dict(),
        compiled.vc_resource.to_dict(), compiled.routing_realization.to_dict(),
        compiled.packet_format.to_dict(), compiled.router_behavior.to_dict(),
        compiled.address_decode.to_dict(), compiled.fabric.to_dict(),
        compiled.resolved_fabric.to_dict(),
        tuple(sorted(repr(compiled.routing).split())))


def test_deterministic_repeatability_50x():
    first = _snapshot(_det())
    for _ in range(49):
        assert _snapshot(_det()) == first


def test_adaptive_repeatability_50x():
    first = _snapshot(_adapt())
    for _ in range(49):
        assert _snapshot(_adapt()) == first


# ── candidate selection is outside / mapping supplied ──────────────────────

def test_mapping_is_supplied_not_derived():
    source = inspect.getsource(cc)
    assert "derive_mapping" not in source
    tree = ast.parse(source)
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            assert "derive_mapping" not in (node.module or "")


def test_two_legal_mappings_compile_to_different_resolved():
    design = _design(compute=4, tp=2)
    inventory = build_inventory(design)
    compute = inventory.compute_instances
    baseline = _det(design)
    alternate = MappingArtifact(placements=(
        RankPlacement(rank=0, agent=compute[1]),
        RankPlacement(rank=1, agent=compute[0])))
    other = _det(design, mapping=alternate)
    assert other.mapping.mapping_hash() != baseline.mapping.mapping_hash()
    assert other.fabric.fabric_hash == baseline.fabric.fabric_hash
    assert other.resolved_fabric.resolved_fabric_hash \
        != baseline.resolved_fabric.resolved_fabric_hash


# ── policy variation ───────────────────────────────────────────────────────

def test_dor_and_anynet_share_common_hardware():
    dor = _det()
    anynet = _det(policy=_anynet_policy(),
                  vc_spec=_vs(vc_to_routing_class=((0, ANYNET_MIN_HOPS),)))
    assert dor.topology.to_dict() == anynet.topology.to_dict()
    assert dor.attachment.to_dict() == anynet.attachment.to_dict()
    assert dor.vc_resource.to_dict() == anynet.vc_resource.to_dict()
    assert dor.packet_format.to_dict() == anynet.packet_format.to_dict()
    assert dor.router_behavior.to_dict() == anynet.router_behavior.to_dict()
    assert dor.routing_realization.routing_realization_hash \
        != anynet.routing_realization.routing_realization_hash
    assert dor.fabric.fabric_hash != anynet.fabric.fabric_hash
    assert dor.resolved_fabric.resolved_fabric_hash \
        != anynet.resolved_fabric.resolved_fabric_hash


def test_min_adapt_policy_id_invariance_through_compiler():
    base = _adapt()
    renamed = _adapt(policy=_min_adapt_policy(id="renamed_policy"))
    assert base.routing.routing_relation.relation_hash \
        != renamed.routing.routing_relation.relation_hash
    assert base.routing_realization.routing_realization_hash \
        == renamed.routing_realization.routing_realization_hash
    assert base.fabric.fabric_hash == renamed.fabric.fabric_hash
    assert base.resolved_fabric.resolved_fabric_hash \
        == renamed.resolved_fabric.resolved_fabric_hash


def test_adaptive_materializer_only_accepts_escape_subfunction():
    with pytest.raises(CanonicalCompileError) as excinfo:
        _adapt(policy=_min_adapt_policy(
            deadlock_proof_obligation=DeadlockProofObligation.EXTERNAL))
    assert excinfo.value.stage is CompileStage.ROUTING


# ── address-decode order independence ──────────────────────────────────────

def test_address_decode_is_order_independent():
    compiled = _det()
    independent = derive_address_decode(design=compiled.design,
                                        attachment=compiled.attachment)
    assert compiled.address_decode.to_dict() == independent.to_dict()
    # address decode depends only on design + attachment
    assert compiled.address_decode.attachment_hash \
        == compiled.attachment.attachment_hash()


# ── compiler semantics version gate ────────────────────────────────────────

def test_unsupported_compiler_semantics_version_fails_at_input():
    design = _design()
    object.__setattr__(design, "compiler_semantics_version", 2)
    with pytest.raises(CanonicalCompileError) as excinfo:
        _det(design)
    assert excinfo.value.stage is CompileStage.INPUT


# ── error-stage matrix ─────────────────────────────────────────────────────

def test_unsupported_topology_family_fails_at_topology():
    with pytest.raises(CanonicalCompileError) as excinfo:
        _det(_design(family=TopologyFamily.GEC))
    assert excinfo.value.stage is CompileStage.TOPOLOGY


def test_mapping_rank_count_mismatch_fails_at_input():
    design = _design(compute=4, tp=2)
    inventory = build_inventory(design)
    short = MappingArtifact(placements=(
        RankPlacement(rank=0, agent=inventory.compute_instances[0]),))
    with pytest.raises(CanonicalCompileError) as excinfo:
        _det(design, mapping=short)
    assert excinfo.value.stage is CompileStage.INPUT


def test_unrepresentable_deterministic_policy_fails_at_routing():
    with pytest.raises(CanonicalCompileError) as excinfo:
        _det(policy=_min_adapt_policy())
    assert excinfo.value.stage is CompileStage.ROUTING


def test_unsupported_adaptive_policy_fails_at_routing():
    with pytest.raises(CanonicalCompileError) as excinfo:
        _adapt(policy=_dor_policy())
    assert excinfo.value.stage is CompileStage.ROUTING


def test_invalid_vc_spec_shape_fails_at_input():
    with pytest.raises(CanonicalCompileError) as excinfo:
        _vs(vc_count=0)
    assert excinfo.value.stage is CompileStage.INPUT


def test_invalid_deterministic_vc_reference_fails_at_vc():
    with pytest.raises(CanonicalCompileError) as excinfo:
        _det(vc_spec=_vs(traffic_class_to_vcs=(("default", (3,)),)))
    assert excinfo.value.stage is CompileStage.VC


def test_invalid_adaptive_vc_resource_fails_at_vc():
    with pytest.raises(CanonicalCompileError) as excinfo:
        _adapt(vc_resource_spec=_vrs(vc_count=2))
    assert excinfo.value.stage is CompileStage.VC


def test_invalid_role_binding_shape_fails_at_input():
    with pytest.raises(CanonicalCompileError) as excinfo:
        _rbs(role_to_vcs=(("escape", (0,)), ("escape", (1,))))
    assert excinfo.value.stage is CompileStage.INPUT


def test_semantic_role_binding_mismatch_fails_at_realization():
    with pytest.raises(CanonicalCompileError) as excinfo:
        _adapt(role_binding_spec=_rbs(
            role_to_vcs=(("adaptive", (0, 1, 2, 3)), ("escape", (0,)))))
    assert excinfo.value.stage is CompileStage.ROUTING_REALIZATION


def test_narrow_packet_width_fails_at_packet_format():
    with pytest.raises(CanonicalCompileError) as excinfo:
        _det(_design(noc_kw={"link_width": 7}))
    assert excinfo.value.stage is CompileStage.PACKET_FORMAT


def test_multi_instance_address_target_fails_at_address_decode():
    with pytest.raises(CanonicalCompileError) as excinfo:
        _det(_design(hbm=2))
    assert excinfo.value.stage is CompileStage.ADDRESS_DECODE


def test_rcu_intent_fails_at_resolved_fabric():
    with pytest.raises(CanonicalCompileError) as excinfo:
        _det(_design(noc_kw={"rcu_enabled": True}))
    assert excinfo.value.stage is CompileStage.RESOLVED_FABRIC


def test_multicast_intent_fails_at_resolved_fabric():
    with pytest.raises(CanonicalCompileError) as excinfo:
        _det(_design(noc_kw={"mcast_groups": 4}))
    assert excinfo.value.stage is CompileStage.RESOLVED_FABRIC


def test_error_preserves_cause_and_stage_name():
    with pytest.raises(CanonicalCompileError) as excinfo:
        _det(policy=_min_adapt_policy())
    error = excinfo.value
    assert error.stage is CompileStage.ROUTING
    assert "stage=ROUTING" in str(error)
    assert "cause=" in str(error)
    assert error.__cause__ is not None


# ── no verification / no requirements evaluation ──────────────────────────

def test_compilation_does_not_invoke_verification():
    source = inspect.getsource(cc)
    # the module never calls a verifier (its docstring may discuss them)
    assert "certify_" not in source
    assert "build_channel_vc_cdg" not in source
    compiled = _det()
    # verification is an explicit, separate downstream judgement
    from veritx_dse.verification.channel_vc_cdg import (
        certify_channel_vc_deadlock,
    )
    certificate = certify_channel_vc_deadlock(
        topology=compiled.topology,
        resolved_route=compiled.routing.resolved_route,
        router_route=compiled.routing.route,
        vc_assignment=compiled.routing.vc_assignment)
    assert certificate is not None
    assert compiled.resolved_fabric.resolved_fabric_hash == GOLDEN_DET


def test_requirements_are_not_evaluated():
    impossible = (Requirement(qos_class=QoSClass.LATENCY_CRITICAL,
                              latency_ceiling_cycles=0.0, binding=True),)
    design = _design(requirements=impossible)
    compiled = _det(design)
    assert design.requirements
    assert compiled.resolved_fabric.resolved_fabric_hash


# ── input immutability / atomicity ─────────────────────────────────────────

def test_compilation_does_not_mutate_inputs():
    design = _design()
    inventory = build_inventory(design)
    mapping = derive_mapping(design)
    policy = _dor_policy()
    before = (design.canonical_dict(), inventory.to_dict(), mapping.to_dict(),
              policy.to_dict())
    compile_deterministic_candidate(
        design=design, inventory=inventory, mapping=mapping,
        routing_policy=policy, vc_spec=_vs(), settings=_settings())
    after = (design.canonical_dict(), inventory.to_dict(), mapping.to_dict(),
             policy.to_dict())
    assert before == after


def test_specs_freeze_caller_owned_collections():
    source = {"default": [0]}
    transitions = [[0, 0]]
    spec = DeterministicVCSpec(
        vc_count=1, traffic_class_to_vcs=source,
        vc_to_routing_class={0: DOR_XY}, allowed_transitions=transitions,
        escape_vcs=[], derivation="d")
    source["default"].append(1)
    transitions.append([0, 1])
    assert spec.traffic_class_to_vcs == (("default", (0,)),)
    assert spec.allowed_transitions == ((0, 0),)


def test_specs_are_not_hashed_artifacts():
    for spec in (_settings(), _vs(), _vrs(), _rbs()):
        assert not hasattr(spec, "artifact_hash")
        assert not hasattr(spec, "to_dict")


# ── strict settings/specs ──────────────────────────────────────────────────

@pytest.mark.parametrize("field,bad", [
    ("max_packet_flits", True),
    ("max_packet_flits", 0),
    ("max_packet_flits", 1.0),
    ("input_buffer_depth_flits_per_vc", True),
    ("input_buffer_depth_flits_per_vc", 0),
    ("output_stage_depth_flits_per_vc", "1"),
])
def test_settings_reject_bad_values(field, bad):
    with pytest.raises(CanonicalCompileError) as excinfo:
        _settings(**{field: bad})
    assert excinfo.value.stage is CompileStage.INPUT


@pytest.mark.parametrize("field,bad", [
    ("vc_count", True),
    ("vc_count", 0),
    ("vc_count", 1.0),
    ("traffic_class_to_vcs", ()),
    ("traffic_class_to_vcs", (("default", ()),)),
    ("traffic_class_to_vcs", (("a", (0,)), ("a", (1,)))),
    ("vc_to_routing_class", ((0, DOR_XY), (0, DOR_XY))),
    ("escape_vcs", (True,)),
])
def test_deterministic_spec_rejects_bad_values(field, bad):
    with pytest.raises(CanonicalCompileError) as excinfo:
        _vs(**{field: bad})
    assert excinfo.value.stage is CompileStage.INPUT


@pytest.mark.parametrize("field,bad", [
    ("vc_count", 0),
    ("traffic_class_to_vcs", (("default", ()),)),
    ("allowed_transitions", (("x", 0),)),
])
def test_adaptive_spec_rejects_bad_values(field, bad):
    with pytest.raises(CanonicalCompileError) as excinfo:
        _vrs(**{field: bad})
    assert excinfo.value.stage is CompileStage.INPUT


def test_non_artifact_parents_are_refused():
    with pytest.raises(CanonicalCompileError) as excinfo:
        compile_deterministic_candidate(
            design=object(), inventory=object(), mapping=object(),
            routing_policy=object(), vc_spec=_vs(), settings=_settings())
    assert excinfo.value.stage is CompileStage.INPUT


# ── scope sentinels ────────────────────────────────────────────────────────

def test_module_imports_only_canonical_semantic_artifacts():
    tree = ast.parse(inspect.getsource(cc))
    imported: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            imported.add(node.module or "")
    forbidden = ("verification", "backend", "simulation", "cli", "reports",
                 "synthesis", "application", "service", "booksim", "astra",
                 "subprocess", "os", "pathlib", "shutil")
    for name in imported:
        assert not any(token in name.lower() for token in forbidden), name
    local = {name for name in imported if name.startswith("veritx_dse")}
    assert "veritx_dse.model.resolved_fabric" in local
    assert "veritx_dse.model.fabric_artifact" in local


def test_module_contains_no_second_authority_logic():
    source = inspect.getsource(cc).lower()
    for token in ("dijkstra", "bit_length", "log2", "ceil(", "subprocess",
                  "booksim", "astra", "routing_table", "neighbor",
                  "open(", "def _xy", "def _clamp", "def _route"):
        assert token not in source, token
    # no local VC-count computation: it is always passed through
    assert "min(" not in source
    assert "max(" not in source


def test_dependency_direction_is_semantic_artifacts_to_compiler():
    for module in ("veritx_dse.model.fabric_artifact",
                   "veritx_dse.model.resolved_fabric",
                   "veritx_dse.model.routing_realization"):
        imported = __import__(module, fromlist=["x"])
        source = inspect.getsource(imported)
        assert "compiler.canonical" not in source
        assert "veritx_dse.compiler" not in source
