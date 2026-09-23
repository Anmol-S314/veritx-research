"""ResolvedFabric v1 tests — the design/mapping -> hardware seam.

``ResolvedFabric`` binds exact design intent, logical rank geometry and
rank->agent mapping to one canonical hardware fabric. It derives nothing
and absorbs no verification evidence.
"""
from __future__ import annotations

import ast
import dataclasses
import inspect

import pytest

from veritx_dse.core.route_artifact import (
    ANYNET_MIN_HOPS, DOR_XY, RouteArtifact,
)
from veritx_dse.model import resolved_fabric as rf
from veritx_dse.model.address_decode import (
    AddressDecodeArtifact, AddressDecodeEntry, AddressTransform,
    UnmatchedAddressPolicy, derive_address_decode,
)
from veritx_dse.model.attachment import derive_attachment
from veritx_dse.model.compile_model import (
    AddressMap, AddressRange, Agent, AgentKind, CompileRequest, ModelFamily,
    NocConfig, QoSClass, Requirement, TopologyFamily, Workload,
)
from veritx_dse.model.fabric_artifact import (
    make_adaptive_fabric, make_deterministic_fabric,
)
from veritx_dse.model.mapping import (
    MappingArtifact, RankPlacement, derive_mapping,
)
from veritx_dse.model.packet_format import derive_packet_format
from veritx_dse.model.placement import build_inventory
from veritx_dse.model.resolved_fabric import (
    RESOLVED_FABRIC_SCHEMA_VERSION, ResolvedFabric, ResolvedFabricError,
    check_noc_field_classification, make_resolved_adaptive_fabric,
    make_resolved_deterministic_fabric, noc_semantic_fields,
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
from veritx_dse.model.topology_artifact import (
    MaterializedFamily, materialize_family, materialize_topology,
)
from veritx_dse.model.vc_assignment import make_vc_assignment_artifact
from veritx_dse.model.vc_resource import VCResourceArtifact

# ResolvedFabric goldens: identity-only move under compiler semantics v2
# (the design_hash parent moved); hardware children stay pinned elsewhere.
GOLDEN_DET_RESOLVED = (
    "9d74cd9678e28c0c99493866bf90ae3f036f51f0d6abc834bfca94d9c2ebb6f1")
GOLDEN_ADAPTIVE_RESOLVED = (
    "80ea0a88e5f7cbdff9406809efb9b5a5076dfdc1222675767157b97e0866cf15")
GOLDEN_ADAPTIVE_3X3_RESOLVED = (
    "400ddd28a38cb83cde641c9b19fa7df3a14a4c509ef308253bb565b910eb6bde")

_MIN_ADAPT_TRANSITIONS = (
    (0, 0), (1, 0), (1, 1), (1, 2), (1, 3),
    (2, 0), (2, 1), (2, 2), (2, 3), (3, 0), (3, 1), (3, 2), (3, 3),
)

SCHEMA_FIELDS = {
    "design_hash", "mapping_hash", "fabric_hash", "schema_version",
    "resolved_fabric_hash",
}
IDENTITY_KEYS = {"type", "schema_version", "design_hash", "mapping_hash",
                 "fabric_hash"}
SERIALIZED_KEYS = SCHEMA_FIELDS | {"type"}
EVIDENCE_TOKENS = (
    "certificate", "verdict", "proof_obligation", "qualification",
    "metric", "latency_ceiling", "bandwidth_floor", "area", "power",
    "synthesis", "backend", "seed", "timestamp", "run_id",
)


# ── fixtures ───────────────────────────────────────────────────────────────

def _vc1() -> VCResourceArtifact:
    return VCResourceArtifact(
        vc_count=1, vc_ids=(0,),
        traffic_class_to_vcs=(("default", (0,)),),
        allowed_transitions=((0, 0),))


def _vc4() -> VCResourceArtifact:
    return VCResourceArtifact(
        vc_count=4, vc_ids=(0, 1, 2, 3),
        traffic_class_to_vcs=(("default", (0, 1, 2, 3)),),
        allowed_transitions=_MIN_ADAPT_TRANSITIONS)


def _policy(**over) -> RoutingPolicyDefinition:
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
            dp: int = 1, name: str = "HBM0", base: int = 0x0,
            size: int = 0x1000, family: TopologyFamily = TopologyFamily.MESH,
            compute_groups: int = 1, noc_kw=None,
            requirements=()) -> CompileRequest:
    groups = [Agent(kind=AgentKind.COMPUTE_TILE, count=compute)]
    if compute_groups > 1:
        groups.append(Agent(kind=AgentKind.COMPUTE_TILE, count=1))
    groups.append(Agent(kind=AgentKind.HBM_CONTROLLER, count=1))
    return CompileRequest(
        workload=Workload(model_family=ModelFamily.MOE, tp=tp, pp=pp, ep=ep,
                          dp=dp),
        requirements=tuple(requirements), agents=tuple(groups),
        dependencies=[],
        noc_config=NocConfig(topology_family=family, **(noc_kw or {})),
        address_map=AddressMap(ranges=(
            AddressRange(name=name, base=base, size=size,
                         target_agent_idx=len(groups) - 1),)))


@dataclasses.dataclass(frozen=True)
class _Det:
    design: object
    inventory: object
    topology: object
    attachment: object
    mapping: object
    vc: object
    route: object
    resolved_route: object
    vc_assignment: object
    realization: object
    packet_format: object
    router_behavior: object
    address_decode: object
    fabric: object
    resolved: ResolvedFabric


@dataclasses.dataclass(frozen=True)
class _Adapt:
    design: object
    inventory: object
    topology: object
    attachment: object
    mapping: object
    vc: object
    policy: object
    relation: object
    binding: object
    realization: object
    packet_format: object
    router_behavior: object
    address_decode: object
    fabric: object
    resolved: ResolvedFabric


def _det_chain(design=None, *, classes=(DOR_XY,), vc=None,
               depth: int = 8) -> _Det:
    design = design if design is not None else _design()
    vc = vc if vc is not None else _vc1()
    inventory = build_inventory(design)
    topology = materialize_topology(inventory, design)
    attachment = derive_attachment(design=design, inventory=inventory,
                                   topology=topology)
    mapping = derive_mapping(design)
    route = RouteArtifact.from_topology(topology, name="r",
                                        routing_classes=classes)
    resolved_route = derive_resolved_route(topology, attachment, route)
    vc_assignment = make_vc_assignment_artifact(
        resolved_route=resolved_route, derivation="d", vc_count=vc.vc_count,
        traffic_class_to_vcs={"default": list(range(vc.vc_count))},
        vc_to_routing_class={i: classes[0] for i in range(vc.vc_count)},
        allowed_transitions=((0, 0),))
    realization = make_deterministic_routing_realization(
        topology=topology, attachment=attachment, route=route,
        resolved_route=resolved_route, vc_assignment=vc_assignment,
        vc_resource=vc)
    packet_format = derive_packet_format(topology, attachment, vc,
                                         max_packet_flits=8)
    router_behavior = derive_router_behavior(
        vc_resource=vc, buffer_depth_flits=depth,
        arbitration=design.noc_config.arbitration)
    address_decode = derive_address_decode(design=design,
                                           attachment=attachment)
    fabric = make_deterministic_fabric(
        topology=topology, attachment=attachment, vc_resource=vc,
        routing_realization=realization, packet_format=packet_format,
        router_behavior=router_behavior, address_decode=address_decode,
        route=route, resolved_route=resolved_route,
        vc_assignment=vc_assignment)
    resolved = make_resolved_deterministic_fabric(
        design=design, inventory=inventory, mapping=mapping,
        topology=topology, attachment=attachment, vc_resource=vc,
        routing_realization=realization, packet_format=packet_format,
        router_behavior=router_behavior, address_decode=address_decode,
        fabric=fabric, route=route, resolved_route=resolved_route,
        vc_assignment=vc_assignment)
    return _Det(design, inventory, topology, attachment, mapping, vc, route,
                resolved_route, vc_assignment, realization, packet_format,
                router_behavior, address_decode, fabric, resolved)


def _adapt_chain(design=None, *, policy=None, relation=None,
                 binding=None) -> _Adapt:
    design = design if design is not None else _design()
    vc = _vc4()
    policy = policy if policy is not None else _policy()
    inventory = build_inventory(design)
    topology = materialize_topology(inventory, design)
    attachment = derive_attachment(design=design, inventory=inventory,
                                   topology=topology)
    mapping = derive_mapping(design)
    relation = (relation if relation is not None
                else materialize_routing_relation(topology, policy))
    binding = (binding if binding is not None
               else RoutingResourceBindingArtifact(
                   policy_hash=policy.policy_hash,
                   vc_resource_hash=vc.artifact_hash,
                   role_to_vcs=(("adaptive", (1, 2, 3)), ("escape", (0,)))))
    realization = make_adaptive_routing_realization(
        topology=topology, policy=policy, relation=relation, vc_resource=vc,
        binding=binding)
    packet_format = derive_packet_format(topology, attachment, vc,
                                         max_packet_flits=8)
    router_behavior = derive_router_behavior(vc_resource=vc,
                                             buffer_depth_flits=8)
    address_decode = derive_address_decode(design=design,
                                           attachment=attachment)
    fabric = make_adaptive_fabric(
        topology=topology, attachment=attachment, vc_resource=vc,
        routing_realization=realization, packet_format=packet_format,
        router_behavior=router_behavior, address_decode=address_decode,
        policy=policy, relation=relation, binding=binding)
    resolved = make_resolved_adaptive_fabric(
        design=design, inventory=inventory, mapping=mapping,
        topology=topology, attachment=attachment, vc_resource=vc,
        routing_realization=realization, packet_format=packet_format,
        router_behavior=router_behavior, address_decode=address_decode,
        fabric=fabric, policy=policy, relation=relation, binding=binding)
    return _Adapt(design, inventory, topology, attachment, mapping, vc, policy,
                  relation, binding, realization, packet_format,
                  router_behavior, address_decode, fabric, resolved)


def _resolve_det(chain: _Det, **over) -> ResolvedFabric:
    kwargs = dict(
        design=chain.design, inventory=chain.inventory, mapping=chain.mapping,
        topology=chain.topology, attachment=chain.attachment, vc_resource=chain.vc,
        routing_realization=chain.realization,
        packet_format=chain.packet_format,
        router_behavior=chain.router_behavior,
        address_decode=chain.address_decode, fabric=chain.fabric,
        route=chain.route, resolved_route=chain.resolved_route,
        vc_assignment=chain.vc_assignment)
    kwargs.update(over)
    return make_resolved_deterministic_fabric(**kwargs)


# ── schema and identity ────────────────────────────────────────────────────

def test_schema_fields_and_identity_equation():
    assert RESOLVED_FABRIC_SCHEMA_VERSION == 1
    assert {f.name for f in dataclasses.fields(ResolvedFabric)} == SCHEMA_FIELDS
    chain = _det_chain()
    assert set(chain.resolved.identity_dict()) == IDENTITY_KEYS
    assert set(chain.resolved.to_dict()) == SERIALIZED_KEYS
    assert chain.resolved.resolved_fabric_hash \
        == chain.resolved._compute_hash()
    assert chain.resolved.design_hash == chain.design.design_hash()
    assert chain.resolved.mapping_hash == chain.mapping.mapping_hash()
    assert chain.resolved.fabric_hash == chain.fabric.fabric_hash


def test_no_inventory_hash_or_child_hashes():
    chain = _det_chain()
    assert not hasattr(chain.resolved, "inventory_hash")
    blob = repr(chain.resolved.to_dict()).lower()
    for token in ("inventory_hash", "topology_hash", "attachment_hash",
                  "routing_hash", "vc_resource_hash", "packet_format_hash",
                  "router_behavior_hash", "address_decode_hash"):
        assert token not in blob, token


# ── golden pins ────────────────────────────────────────────────────────────

def test_golden_deterministic_resolved_fabric():
    chain = _det_chain()
    assert chain.resolved.resolved_fabric_hash == GOLDEN_DET_RESOLVED


def test_golden_adaptive_resolved_fabric():
    chain = _adapt_chain()
    assert chain.resolved.resolved_fabric_hash == GOLDEN_ADAPTIVE_RESOLVED


def test_golden_adaptive_3x3_resolved_fabric():
    chain = _adapt_chain(_design(compute=8))
    assert chain.resolved.resolved_fabric_hash == GOLDEN_ADAPTIVE_3X3_RESOLVED


# ── NocConfig classification sentinel ──────────────────────────────────────

def test_noc_config_classification_is_exhaustive():
    assert noc_semantic_fields() == set(rf.NOC_FIELD_CLASSIFICATION)
    assert set(rf.NOC_FIELD_CLASSIFICATION.values()) <= {
        "REPRESENTED", "NON_HARDWARE", "UNSUPPORTED_V1"}
    represented = {name for name, kind in rf.NOC_FIELD_CLASSIFICATION.items()
                   if kind == "REPRESENTED"}
    assert represented == {"topology_family", "radix", "concentration",
                           "link_width", "arbitration"}
    unsupported = {name for name, kind in rf.NOC_FIELD_CLASSIFICATION.items()
                   if kind == "UNSUPPORTED_V1"}
    assert unsupported == {"rcu_enabled", "mcast_groups",
                           "mcast_setup_cycles"}
    check_noc_field_classification()


def test_unclassified_noc_field_fails_closed(monkeypatch):
    trimmed = dict(rf.NOC_FIELD_CLASSIFICATION)
    trimmed.pop("rcu_enabled")
    monkeypatch.setattr(rf, "NOC_FIELD_CLASSIFICATION", trimmed)
    with pytest.raises(ResolvedFabricError, match="unclassified NocConfig"):
        check_noc_field_classification()


# ── design intent audit / unsupported gates ───────────────────────────────

def test_rcu_intent_is_unsupported():
    with pytest.raises(ResolvedFabricError, match="UNSUPPORTED"):
        _det_chain(_design(noc_kw={"rcu_enabled": True}))


def test_multicast_group_intent_is_unsupported():
    with pytest.raises(ResolvedFabricError, match="UNSUPPORTED"):
        _det_chain(_design(noc_kw={"mcast_groups": 4}))


def test_multicast_setup_intent_is_unsupported():
    with pytest.raises(ResolvedFabricError, match="UNSUPPORTED"):
        _det_chain(_design(noc_kw={"mcast_setup_cycles": 2}))


def test_multi_power_domain_intent_is_unsupported():
    design = _design()
    physical = dataclasses.replace(design.physical, num_power_domains=2)
    with pytest.raises(ResolvedFabricError, match="UNSUPPORTED"):
        _det_chain(dataclasses.replace(design, physical=physical))


def test_requirements_are_not_resolved_identity():
    requirements = (Requirement(qos_class=QoSClass.LATENCY_CRITICAL,
                                latency_ceiling_cycles=1.0, binding=True),)
    chain = _det_chain(_design(requirements=requirements))
    # a structurally resolved fabric makes no claim about requirements
    assert chain.resolved.resolved_fabric_hash
    assert "requirement" not in repr(chain.resolved.to_dict()).lower()
    assert not hasattr(chain.resolved, "requirements")


def test_link_width_intent_is_represented():
    chain = _det_chain(_design(noc_kw={"link_width": 128}))
    assert chain.packet_format.flit_width_bits == 128
    assert chain.resolved.resolved_fabric_hash


def test_router_arbitration_intent_is_enforced():
    good = _det_chain(_design(noc_kw={"arbitration": "rr"}))
    assert good.resolved.resolved_fabric_hash
    # a root bound to an rr design but carrying iSLIP hardware must fail
    islip = _det_chain()
    rr_design = _design(noc_kw={"arbitration": "rr"})
    forged = ResolvedFabric(
        design_hash=rr_design.design_hash(),
        mapping_hash=islip.mapping.mapping_hash(),
        fabric_hash=islip.fabric.fabric_hash)
    with pytest.raises(ResolvedFabricError, match="arbitration"):
        forged.validate_against_deterministic(
            design=rr_design, inventory=islip.inventory,
            mapping=islip.mapping, topology=islip.topology,
            attachment=islip.attachment, vc_resource=islip.vc,
            routing_realization=islip.realization,
            packet_format=islip.packet_format,
            router_behavior=islip.router_behavior,
            address_decode=islip.address_decode, fabric=islip.fabric,
            route=islip.route, resolved_route=islip.resolved_route,
            vc_assignment=islip.vc_assignment)


# ── design / inventory / mapping seams ─────────────────────────────────────

def test_design_inventory_geometry_must_match_exactly():
    chain = _det_chain()
    other_inventory = build_inventory(_design(tp=2, pp=2))
    with pytest.raises(ResolvedFabricError, match="parallelism"):
        _resolve_det(chain, design=_design(tp=4), inventory=other_inventory)


def test_rank_namespace_coordinates_are_validated():
    chain = _det_chain(_design(compute=4, tp=2))
    bad_rank = dataclasses.replace(chain.inventory.ranks[1], tp=9)
    object.__setattr__(chain.inventory, "ranks",
                       (chain.inventory.ranks[0], bad_rank))
    with pytest.raises(ResolvedFabricError, match="rank namespace"):
        _resolve_det(chain)


def test_mapping_must_cover_the_inventory_rank_sequence():
    chain = _det_chain(_design(compute=4, tp=2))
    short = MappingArtifact(placements=(
        RankPlacement(rank=0, agent=chain.inventory.compute_instances[0]),))
    with pytest.raises(ResolvedFabricError, match="rank_count"):
        _resolve_det(chain, mapping=short)


def test_mapping_referencing_unattached_agent_is_refused():
    chain = _det_chain(_design(compute=1, compute_groups=2))
    dropped = chain.mapping.placements[0].agent
    object.__setattr__(chain.attachment, "endpoints", tuple(
        endpoint for endpoint in chain.attachment.endpoints
        if (endpoint.agent.group_index, endpoint.agent.instance_index)
        != (dropped.group_index, dropped.instance_index)))
    with pytest.raises(ResolvedFabricError, match="not attached"):
        _resolve_det(chain)


def test_idle_attached_agents_need_not_be_mapped():
    chain = _det_chain(_design(compute=4, tp=2))
    assert chain.mapping.rank_count == 2
    assert len(chain.attachment.endpoints) == 5
    assert chain.resolved.resolved_fabric_hash


def test_design_attachment_mismatch_is_refused():
    chain = _det_chain()
    other = _det_chain(_design(compute=4))
    with pytest.raises(ResolvedFabricError, match="attachment"):
        _resolve_det(chain, attachment=other.attachment)


# ── address-map equivalence ────────────────────────────────────────────────

def test_address_decode_must_realize_the_design_address_map():
    chain = _det_chain()
    other = _det_chain(_design(base=0x2000))
    with pytest.raises(ResolvedFabricError, match="address map"):
        _resolve_det(chain, address_decode=other.address_decode)


def test_hardware_valid_design_invalid_contrast():
    chain = _det_chain()
    hbm = next(endpoint for endpoint in chain.attachment.endpoints
               if endpoint.agent.group_index == 1)
    wrong_decode = AddressDecodeArtifact(
        attachment_hash=chain.attachment.attachment_hash(),
        entries=(AddressDecodeEntry("unrelated", 0x4000, 0x1000, 1,
                                    hbm.endpoint_id),),
        address_transform=AddressTransform.IDENTITY,
        unmatched_address_policy=UnmatchedAddressPolicy.ERROR)
    # hardware-valid: the fabric composes
    wrong_fabric = make_deterministic_fabric(
        topology=chain.topology, attachment=chain.attachment,
        vc_resource=chain.vc, routing_realization=chain.realization,
        packet_format=chain.packet_format,
        router_behavior=chain.router_behavior, address_decode=wrong_decode,
        route=chain.route, resolved_route=chain.resolved_route,
        vc_assignment=chain.vc_assignment)
    assert wrong_fabric.fabric_hash
    # design-invalid: the resolved seam refuses
    with pytest.raises(ResolvedFabricError, match="address map"):
        _resolve_det(chain, address_decode=wrong_decode, fabric=wrong_fabric)


# ── topology intent ────────────────────────────────────────────────────────

def test_topology_must_implement_design_intent():
    chain = _det_chain()
    torus = materialize_family(MaterializedFamily.TORUS,
                               endpoint_count=chain.inventory.agent_count)
    attachment = derive_attachment(design=chain.design,
                                   inventory=chain.inventory, topology=torus)
    route = RouteArtifact.from_topology(torus, name="r",
                                        routing_classes=(ANYNET_MIN_HOPS,))
    resolved_route = derive_resolved_route(torus, attachment, route)
    vc_assignment = make_vc_assignment_artifact(
        resolved_route=resolved_route, derivation="d", vc_count=1,
        traffic_class_to_vcs={"default": [0]},
        vc_to_routing_class={0: ANYNET_MIN_HOPS},
        allowed_transitions=((0, 0),))
    realization = make_deterministic_routing_realization(
        topology=torus, attachment=attachment, route=route,
        resolved_route=resolved_route, vc_assignment=vc_assignment,
        vc_resource=chain.vc)
    packet_format = derive_packet_format(torus, attachment, chain.vc,
                                         max_packet_flits=8)
    address_decode = derive_address_decode(design=chain.design,
                                           attachment=attachment)
    fabric = make_deterministic_fabric(
        topology=torus, attachment=attachment, vc_resource=chain.vc,
        routing_realization=realization, packet_format=packet_format,
        router_behavior=chain.router_behavior, address_decode=address_decode,
        route=route, resolved_route=resolved_route,
        vc_assignment=vc_assignment)
    with pytest.raises(ResolvedFabricError, match="topology intent"):
        _resolve_det(chain, topology=torus, attachment=attachment,
                     routing_realization=realization,
                     packet_format=packet_format,
                     address_decode=address_decode, fabric=fabric,
                     route=route, resolved_route=resolved_route,
                     vc_assignment=vc_assignment)


# ── invariance ─────────────────────────────────────────────────────────────

def test_address_label_variation_moves_resolved_but_not_fabric():
    base = _det_chain()
    renamed = _det_chain(_design(name="weights"))
    assert base.design.design_hash() != renamed.design.design_hash()
    assert base.fabric.fabric_hash == renamed.fabric.fabric_hash
    assert base.resolved.resolved_fabric_hash \
        != renamed.resolved.resolved_fabric_hash


def test_policy_id_variation_does_not_move_resolved():
    base = _adapt_chain()
    renamed = _adapt_chain(policy=_policy(id="renamed_policy"))
    assert base.fabric.fabric_hash == renamed.fabric.fabric_hash
    assert base.design.design_hash() == renamed.design.design_hash()
    assert base.mapping.mapping_hash() == renamed.mapping.mapping_hash()
    assert base.resolved.resolved_fabric_hash \
        == renamed.resolved.resolved_fabric_hash


def test_proof_obligation_variation_does_not_move_resolved():
    base = _adapt_chain()
    alternate = dataclasses.replace(
        base.policy,
        deadlock_proof_obligation=DeadlockProofObligation.EXTERNAL,
        policy_hash="")
    alternate_relation = dataclasses.replace(
        base.relation, policy_hash=alternate.policy_hash, relation_hash="")
    alternate_binding = dataclasses.replace(
        base.binding, policy_hash=alternate.policy_hash, binding_hash="")
    twin = _adapt_chain(policy=alternate, relation=alternate_relation,
                        binding=alternate_binding)
    assert base.policy.policy_hash != alternate.policy_hash
    assert base.fabric.fabric_hash == twin.fabric.fabric_hash
    assert base.resolved.resolved_fabric_hash \
        == twin.resolved.resolved_fabric_hash


def test_legal_mapping_variation_moves_resolved_only():
    chain = _det_chain()
    compute = chain.inventory.compute_instances
    alt_mapping = MappingArtifact(placements=(
        RankPlacement(rank=0, agent=compute[1]),))
    alt = _resolve_det(chain, mapping=alt_mapping)
    assert alt.mapping_hash != chain.resolved.mapping_hash
    assert alt.design_hash == chain.resolved.design_hash
    assert alt.fabric_hash == chain.resolved.fabric_hash
    assert alt.resolved_fabric_hash != chain.resolved.resolved_fabric_hash


def test_design_intent_variation_moves_everything():
    mesh = _det_chain()
    torus_design = _design(family=TopologyFamily.TORUS)
    torus = _det_chain(torus_design, classes=(ANYNET_MIN_HOPS,))
    assert mesh.design.design_hash() != torus.design.design_hash()
    assert mesh.fabric.fabric_hash != torus.fabric.fabric_hash
    assert mesh.resolved.resolved_fabric_hash \
        != torus.resolved.resolved_fabric_hash


# ── Frankenstein seams ─────────────────────────────────────────────────────

def test_frankenstein_matrix():
    chain = _det_chain()
    # 1. design A + inventory B with different TP/PP geometry
    with pytest.raises(ResolvedFabricError, match="parallelism"):
        _resolve_det(chain, design=_design(tp=4),
                     inventory=build_inventory(_design(tp=2, pp=2)))
    # 2. design A + attachment from design B
    with pytest.raises(ResolvedFabricError, match="attachment"):
        _resolve_det(chain, attachment=_det_chain(_design(compute=4)).attachment)
    # 3. design A + address decode from another address map
    with pytest.raises(ResolvedFabricError, match="address map"):
        _resolve_det(chain,
                     address_decode=_det_chain(_design(base=0x2000)).address_decode)
    # 5. mapping missing a logical rank
    with pytest.raises(ResolvedFabricError, match="rank_count"):
        _resolve_det(_det_chain(_design(compute=4, tp=2)),
                     mapping=MappingArtifact(placements=(
                         RankPlacement(
                             rank=0,
                             agent=build_inventory(
                                 _design(compute=4, tp=2)).compute_instances[0]),)))
    # 6. mapping with incorrect rank-coordinate namespace
    two = _det_chain(_design(compute=4, tp=2))
    object.__setattr__(two.inventory, "ranks", (
        two.inventory.ranks[0],
        dataclasses.replace(two.inventory.ranks[1], tp=9)))
    with pytest.raises(ResolvedFabricError, match="rank namespace"):
        _resolve_det(two)
    # 10. hardware-valid fabric assembled for another design
    other = _det_chain(_design(compute=4))
    with pytest.raises(ResolvedFabricError):
        _resolve_det(chain, attachment=other.attachment, fabric=other.fabric)


def test_mapping_unattached_agent_seam_is_named():
    chain = _det_chain(_design(compute=1, compute_groups=2))
    dropped = chain.mapping.placements[0].agent
    object.__setattr__(chain.attachment, "endpoints", tuple(
        endpoint for endpoint in chain.attachment.endpoints
        if (endpoint.agent.group_index, endpoint.agent.instance_index)
        != (dropped.group_index, dropped.instance_index)))
    with pytest.raises(ResolvedFabricError, match="not attached"):
        _resolve_det(chain)


# ── explicit branch refusal ────────────────────────────────────────────────

def test_branches_refuse_each_other():
    deterministic = _det_chain()
    adaptive = _adapt_chain()
    with pytest.raises(ResolvedFabricError):
        make_resolved_deterministic_fabric(
            design=adaptive.design, inventory=adaptive.inventory,
            mapping=adaptive.mapping, topology=adaptive.topology,
            attachment=adaptive.attachment, vc_resource=adaptive.vc,
            routing_realization=adaptive.realization,
            packet_format=adaptive.packet_format,
            router_behavior=adaptive.router_behavior,
            address_decode=adaptive.address_decode, fabric=adaptive.fabric,
            route=deterministic.route,
            resolved_route=deterministic.resolved_route,
            vc_assignment=deterministic.vc_assignment)


def test_non_artifact_parents_are_refused():
    chain = _det_chain()
    with pytest.raises(ResolvedFabricError, match="CompileRequest"):
        _resolve_det(chain, design=object())
    with pytest.raises(ResolvedFabricError, match="MappingArtifact"):
        _resolve_det(chain, mapping=object())
    with pytest.raises(ResolvedFabricError, match="FabricArtifact"):
        _resolve_det(chain, fabric=object())


# ── strict serialization / immutability ────────────────────────────────────

def test_roundtrip_is_lossless():
    chain = _det_chain()
    loaded = ResolvedFabric.from_dict(chain.resolved.to_dict())
    assert loaded == chain.resolved
    assert loaded.to_dict() == chain.resolved.to_dict()


def test_unknown_and_missing_fields_are_refused():
    chain = _det_chain()
    persisted = chain.resolved.to_dict()
    persisted["extra"] = 1
    with pytest.raises(ResolvedFabricError, match="unknown fields"):
        ResolvedFabric.from_dict(persisted)
    for field in sorted(SERIALIZED_KEYS):
        persisted = chain.resolved.to_dict()
        persisted.pop(field)
        with pytest.raises(ResolvedFabricError):
            ResolvedFabric.from_dict(persisted)


@pytest.mark.parametrize("bad", [None, "srota/FabricArtifact", 7])
def test_type_tag_is_strict(bad):
    chain = _det_chain()
    persisted = chain.resolved.to_dict()
    if bad is None:
        persisted.pop("type")
    else:
        persisted["type"] = bad
    with pytest.raises(ResolvedFabricError, match="type"):
        ResolvedFabric.from_dict(persisted)


@pytest.mark.parametrize("bad", [0, 2, "1", True])
def test_schema_version_is_strict(bad):
    chain = _det_chain()
    persisted = chain.resolved.to_dict()
    persisted["schema_version"] = bad
    with pytest.raises(ResolvedFabricError, match="schema_version"):
        ResolvedFabric.from_dict(persisted)


@pytest.mark.parametrize("field", ["design_hash", "mapping_hash",
                                    "fabric_hash", "resolved_fabric_hash"])
@pytest.mark.parametrize("bad", [True, 7, "", "a" * 63, "A" * 64, "g" * 64])
def test_hash_fields_are_strict(field, bad):
    chain = _det_chain()
    persisted = chain.resolved.to_dict()
    persisted[field] = bad
    with pytest.raises(ResolvedFabricError, match="hash"):
        ResolvedFabric.from_dict(persisted)


def test_tampered_hash_is_refused():
    chain = _det_chain()
    persisted = chain.resolved.to_dict()
    persisted["resolved_fabric_hash"] = "0" * 64
    with pytest.raises(ResolvedFabricError, match="does not match"):
        ResolvedFabric.from_dict(persisted)


def test_forged_self_consistent_root_fails_validation():
    chain = _det_chain()
    forged = dataclasses.replace(chain.resolved, resolved_fabric_hash="",
                                 design_hash="0" * 64)
    loaded = ResolvedFabric.from_dict(forged.to_dict())
    assert loaded.resolved_fabric_hash == forged.resolved_fabric_hash
    with pytest.raises(ResolvedFabricError, match="design_hash"):
        _resolve_det(chain, fabric=chain.fabric)  # sanity: real chain resolves
        loaded.validate_against_deterministic(
            design=chain.design, inventory=chain.inventory,
            mapping=chain.mapping, topology=chain.topology,
            attachment=chain.attachment, vc_resource=chain.vc,
            routing_realization=chain.realization,
            packet_format=chain.packet_format,
            router_behavior=chain.router_behavior,
            address_decode=chain.address_decode, fabric=chain.fabric,
            route=chain.route, resolved_route=chain.resolved_route,
            vc_assignment=chain.vc_assignment)


def test_artifact_is_frozen_and_to_dict_is_fresh():
    chain = _det_chain()
    with pytest.raises(dataclasses.FrozenInstanceError):
        chain.resolved.design_hash = "a" * 64
    first = chain.resolved.to_dict()
    first.clear()
    second = chain.resolved.to_dict()
    assert second["design_hash"] == chain.design.design_hash()
    assert chain.resolved.resolved_fabric_hash == GOLDEN_DET_RESOLVED


# ── scope sentinels ────────────────────────────────────────────────────────

def test_no_evidence_or_backend_fields():
    chain = _det_chain()
    blob = repr(chain.resolved.to_dict()).lower()
    for token in EVIDENCE_TOKENS:
        assert token not in blob, token
    for token in ("certificate", "verdict", "backend", "qualified",
                  "meets_requirements"):
        assert not hasattr(chain.resolved, token)


def test_docstring_pins_resolved_terminology():
    doc = rf.__doc__.lower()
    assert "structurally and semantically bound" in doc
    assert "verified" in doc
    assert "requirements" in doc


def test_module_imports_only_allowed_layers():
    tree = ast.parse(inspect.getsource(rf))
    imported: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            imported.add(node.module or "")
    forbidden = ("verification", "backend", "booksim", "astra", "cli",
                 "report", "rtl", "synthesis")
    for name in imported:
        assert not any(token in name.lower() for token in forbidden), name
    local = {name for name in imported if name.startswith("veritx_dse")}
    assert "veritx_dse.model.compile_model" in local
    assert "veritx_dse.model.fabric_artifact" in local
