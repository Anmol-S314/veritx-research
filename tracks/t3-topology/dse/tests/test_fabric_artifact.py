"""FabricArtifact v1 tests — canonical hardware composition identity.

FabricArtifact is the content-addressed root over resolved hardware child
identities. It is composition only: design intent, mapping, certificates,
backends, runs and provenance stay outside ``fabric_hash``.
"""
from __future__ import annotations

import ast
import dataclasses
import inspect

import pytest

from veritx_dse.core.route_artifact import (
    ANYNET_MIN_HOPS, DOR_XY, RouteArtifact,
)
from veritx_dse.model import fabric_artifact as fa
from veritx_dse.model.address_decode import (
    AddressDecodeArtifact, AddressDecodeEntry, AddressTransform,
    UnmatchedAddressPolicy, derive_address_decode,
)
from veritx_dse.model.attachment import derive_attachment
from veritx_dse.model.compile_model import (
    AddressMap, AddressRange, Agent, AgentKind, CompileRequest, ModelFamily,
    NocConfig, TopologyFamily, Workload,
)
from veritx_dse.model.fabric_artifact import (
    FABRIC_SCHEMA_VERSION, FabricArtifact, FabricArtifactError,
    PlaneComposition, make_adaptive_fabric, make_deterministic_fabric,
)
from veritx_dse.model.packet_format import derive_packet_format
from veritx_dse.model.placement import build_inventory
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
from veritx_dse.model.vc_resource import (
    VCResourceArtifact, vc_resources_from_assignment,
)

GOLDEN_DET_DOR_2X2 = (
    "798d0b26fb505cfbf1c80167d9d9b00d5eeedd7be7e4a534a23ada7bfa9351e3")
GOLDEN_DET_ANYNET_2X2 = (
    "d9cdfa3fc2e54cfa476260b1ae9df238b1930bdc1ee28dfcc3b1dbc2bad40c28")
GOLDEN_ADAPTIVE_2X2 = (
    "5428c4ce333b9bbe66d0d6efcf9a03ae6e7e089fc7e61eb5832f0e41d7a0e806")
GOLDEN_ADAPTIVE_3X3 = (
    "15790d8a6916dafd157f8458cf1da889e814ed90d3123b46543490ffad636f32")
GOLDEN_DET_4VC_2X2 = (
    "73dc289c9cb35f1fd2ff22aa2ac7d7147487c775f331490c412d07cdcf974a84")

_MIN_ADAPT_TRANSITIONS = (
    (0, 0), (1, 0), (1, 1), (1, 2), (1, 3),
    (2, 0), (2, 1), (2, 2), (2, 3), (3, 0), (3, 1), (3, 2), (3, 3),
)

SCHEMA_FIELDS = {
    "topology_hash", "attachment_hash", "vc_resource_hash",
    "routing_realization_hash", "packet_format_hash", "router_behavior_hash",
    "address_decode_hash", "plane_composition", "schema_version",
    "fabric_hash",
}
IDENTITY_KEYS = {
    "type", "schema_version", "topology_hash", "attachment_hash",
    "vc_resource_hash", "routing_realization_hash", "packet_format_hash",
    "router_behavior_hash", "address_decode_hash", "plane_composition",
}
SERIALIZED_KEYS = SCHEMA_FIELDS | {"type"}
FORBIDDEN_TOKENS = (
    "design_hash", "mapping_hash", "inventory_hash", "policy_hash",
    "relation_hash", "route_hash", "resolved_route_hash",
    "vc_assignment_hash", "binding_hash", "certificate", "proof",
    "obligation", "verdict", "backend", "seed", "timestamp", "git_sha",
    "run_id", "metrics", "escape_vcs", "vc_to_routing_class",
)


# ── fixtures ───────────────────────────────────────────────────────────────

@dataclasses.dataclass(frozen=True)
class _Det:
    design: CompileRequest
    topology: object
    attachment: object
    vc: VCResourceArtifact
    route: RouteArtifact
    resolved: object
    assignment: object
    realization: object
    packet_format: object
    router_behavior: object
    address_decode: object
    fabric: FabricArtifact


@dataclasses.dataclass(frozen=True)
class _Adapt:
    design: CompileRequest
    topology: object
    attachment: object
    vc: VCResourceArtifact
    policy: RoutingPolicyDefinition
    relation: object
    binding: object
    realization: object
    packet_format: object
    router_behavior: object
    address_decode: object
    fabric: FabricArtifact


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


def _design(compute: int = 3, *, name: str = "HBM0", base: int = 0x0,
            size: int = 0x1000, compute_kw=None,
            hbm_kw=None) -> CompileRequest:
    agents = (
        Agent(kind=AgentKind.COMPUTE_TILE, count=compute, **(compute_kw or {})),
        Agent(kind=AgentKind.HBM_CONTROLLER, count=1, **(hbm_kw or {})),
    )
    return CompileRequest(
        workload=Workload(model_family=ModelFamily.MOE, tp=1, pp=1, ep=1, dp=1),
        requirements=[], agents=agents, dependencies=[],
        noc_config=NocConfig(topology_family=TopologyFamily.MESH),
        address_map=AddressMap(ranges=(
            AddressRange(name=name, base=base, size=size,
                         target_agent_idx=1),)))


def _det_bundle(design=None, vc=None, topology=None, *, max_flits: int = 8,
                depth: int = 8, classes=(DOR_XY,), mapping=None,
                transitions=((0, 0),), escape=()) -> _Det:
    design = design if design is not None else _design()
    vc = vc if vc is not None else _vc1()
    topology = (topology if topology is not None
                else materialize_topology(build_inventory(design), design))
    attachment = derive_attachment(design=design,
                                   inventory=build_inventory(design),
                                   topology=topology)
    route = RouteArtifact.from_topology(topology, name="r",
                                        routing_classes=classes)
    resolved = derive_resolved_route(topology, attachment, route)
    assignment = make_vc_assignment_artifact(
        resolved_route=resolved, derivation="d", vc_count=vc.vc_count,
        traffic_class_to_vcs={"default": list(range(vc.vc_count))},
        vc_to_routing_class=(mapping if mapping is not None
                             else {i: classes[0] for i in range(vc.vc_count)}),
        allowed_transitions=transitions, escape_vcs=escape)
    projection = vc_resources_from_assignment(assignment)
    assert projection.artifact_hash == vc.artifact_hash
    realization = make_deterministic_routing_realization(
        topology=topology, attachment=attachment, route=route,
        resolved_route=resolved, vc_assignment=assignment, vc_resource=vc)
    packet_format = derive_packet_format(topology, attachment, vc,
                                         max_packet_flits=max_flits)
    router_behavior = derive_router_behavior(vc_resource=vc,
                                             buffer_depth_flits=depth)
    address_decode = derive_address_decode(design=design, attachment=attachment)
    fabric = make_deterministic_fabric(
        topology=topology, attachment=attachment, vc_resource=vc,
        routing_realization=realization, packet_format=packet_format,
        router_behavior=router_behavior, address_decode=address_decode,
        route=route, resolved_route=resolved, vc_assignment=assignment)
    return _Det(design, topology, attachment, vc, route, resolved, assignment,
                realization, packet_format, router_behavior, address_decode,
                fabric)


def _adapt_bundle(design=None, vc=None, topology=None, *, policy=None,
                  max_flits: int = 8, depth: int = 8, relation=None,
                  binding=None) -> _Adapt:
    design = design if design is not None else _design()
    vc = vc if vc is not None else _vc4()
    policy = policy if policy is not None else _min_adapt_policy()
    topology = (topology if topology is not None
                else materialize_topology(build_inventory(design), design))
    attachment = derive_attachment(design=design,
                                   inventory=build_inventory(design),
                                   topology=topology)
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
                                         max_packet_flits=max_flits)
    router_behavior = derive_router_behavior(vc_resource=vc,
                                             buffer_depth_flits=depth)
    address_decode = derive_address_decode(design=design, attachment=attachment)
    fabric = make_adaptive_fabric(
        topology=topology, attachment=attachment, vc_resource=vc,
        routing_realization=realization, packet_format=packet_format,
        router_behavior=router_behavior, address_decode=address_decode,
        policy=policy, relation=relation, binding=binding)
    return _Adapt(design, topology, attachment, vc, policy, relation, binding,
                  realization, packet_format, router_behavior, address_decode,
                  fabric)


def _common_hashes(bundle) -> tuple:
    return (bundle.topology.topology_hash(), bundle.attachment.attachment_hash(),
            bundle.vc.artifact_hash, bundle.packet_format.packet_format_hash,
            bundle.router_behavior.router_behavior_hash,
            bundle.address_decode.address_decode_hash)


# ── vocabulary and schema ──────────────────────────────────────────────────

def test_plane_composition_vocabulary_is_exactly_pinned():
    assert [(m.name, m.value) for m in PlaneComposition] == [
        ("SINGLE_PLANE", "single_plane")]
    assert FABRIC_SCHEMA_VERSION == 1


def test_schema_fields_are_exactly_pinned():
    assert {f.name for f in dataclasses.fields(FabricArtifact)} == SCHEMA_FIELDS
    bundle = _det_bundle()
    assert set(bundle.fabric.identity_dict()) == IDENTITY_KEYS
    assert set(bundle.fabric.to_dict()) == SERIALIZED_KEYS


# ── golden pins ────────────────────────────────────────────────────────────

def test_golden_deterministic_dor_2x2():
    bundle = _det_bundle()
    assert bundle.fabric.plane_composition is PlaneComposition.SINGLE_PLANE
    assert bundle.fabric.fabric_hash == GOLDEN_DET_DOR_2X2


def test_golden_deterministic_anynet_2x2():
    bundle = _det_bundle(classes=(ANYNET_MIN_HOPS,))
    assert bundle.fabric.fabric_hash == GOLDEN_DET_ANYNET_2X2


def test_golden_adaptive_2x2():
    bundle = _adapt_bundle()
    assert bundle.fabric.fabric_hash == GOLDEN_ADAPTIVE_2X2


def test_golden_adaptive_3x3():
    bundle = _adapt_bundle(design=_design(compute=8))
    assert bundle.fabric.fabric_hash == GOLDEN_ADAPTIVE_3X3


def test_golden_deterministic_four_vc_2x2():
    bundle = _det_bundle(vc=_vc4(), mapping={i: DOR_XY for i in range(4)},
                         transitions=_MIN_ADAPT_TRANSITIONS)
    assert bundle.fabric.fabric_hash == GOLDEN_DET_4VC_2X2


# ── common-child comparisons ───────────────────────────────────────────────

def test_dor_and_anynet_share_all_common_children():
    dor = _det_bundle()
    anynet = _det_bundle(classes=(ANYNET_MIN_HOPS,))
    assert _common_hashes(dor) == _common_hashes(anynet)
    assert dor.realization.routing_realization_hash \
        != anynet.realization.routing_realization_hash
    assert dor.fabric.fabric_hash != anynet.fabric.fabric_hash


def test_deterministic_and_adaptive_share_common_hardware():
    deterministic = _det_bundle(vc=_vc4(),
                                mapping={i: DOR_XY for i in range(4)},
                                transitions=_MIN_ADAPT_TRANSITIONS)
    adaptive = _adapt_bundle()
    assert _common_hashes(deterministic) == _common_hashes(adaptive)
    assert deterministic.realization.routing_realization_hash \
        != adaptive.realization.routing_realization_hash
    assert deterministic.fabric.fabric_hash != adaptive.fabric.fabric_hash


# ── clock / power domain gates ─────────────────────────────────────────────

@pytest.mark.parametrize("compute_kw,hbm_kw", [
    (None, None),
    ({"clock_domain": "clkA"}, {"clock_domain": "clkA"}),
])
def test_legal_clock_domains(compute_kw, hbm_kw):
    bundle = _det_bundle(design=_design(compute_kw=compute_kw,
                                        hbm_kw=hbm_kw))
    assert bundle.fabric.fabric_hash


@pytest.mark.parametrize("compute_kw,hbm_kw", [
    (None, {"clock_domain": "clkA"}),
    ({"clock_domain": "clkA"}, {"clock_domain": "clkB"}),
])
def test_multi_clock_domains_are_refused(compute_kw, hbm_kw):
    with pytest.raises(FabricArtifactError, match="UNSUPPORTED"):
        _det_bundle(design=_design(compute_kw=compute_kw, hbm_kw=hbm_kw))


@pytest.mark.parametrize("compute_kw,hbm_kw", [
    (None, None),
    ({"power_domain": "pd0"}, {"power_domain": "pd0"}),
])
def test_legal_power_domains(compute_kw, hbm_kw):
    bundle = _det_bundle(design=_design(compute_kw=compute_kw,
                                        hbm_kw=hbm_kw))
    assert bundle.fabric.fabric_hash


@pytest.mark.parametrize("compute_kw,hbm_kw", [
    (None, {"power_domain": "pd0"}),
    ({"power_domain": "pd0"}, {"power_domain": "pd1"}),
])
def test_multi_power_domains_are_refused(compute_kw, hbm_kw):
    with pytest.raises(FabricArtifactError, match="UNSUPPORTED"):
        _det_bundle(design=_design(compute_kw=compute_kw, hbm_kw=hbm_kw))


# ── hardware mutation gates ────────────────────────────────────────────────

def test_topology_mutation_moves_fabric_hash():
    base = _det_bundle()
    torus = materialize_family(MaterializedFamily.TORUS, endpoint_count=4)
    mutated = _det_bundle(topology=torus, classes=(ANYNET_MIN_HOPS,))
    assert mutated.topology.topology_hash() != base.topology.topology_hash()
    assert mutated.fabric.fabric_hash != base.fabric.fabric_hash


def test_attachment_mutation_moves_fabric_hash():
    base = _det_bundle()
    mutated = _det_bundle(design=_design(hbm_kw={"data_width": 512}))
    assert mutated.topology.topology_hash() == base.topology.topology_hash()
    assert mutated.attachment.attachment_hash() \
        != base.attachment.attachment_hash()
    assert mutated.fabric.fabric_hash != base.fabric.fabric_hash


def test_vc_resource_mutation_moves_fabric_hash():
    base = _det_bundle()
    mutated = _det_bundle(vc=_vc4(), mapping={i: DOR_XY for i in range(4)},
                          transitions=_MIN_ADAPT_TRANSITIONS)
    assert mutated.vc.artifact_hash != base.vc.artifact_hash
    assert mutated.fabric.fabric_hash != base.fabric.fabric_hash


def test_routing_mutation_moves_fabric_hash():
    base = _det_bundle()
    mutated = _det_bundle(classes=(ANYNET_MIN_HOPS,))
    assert _common_hashes(base) == _common_hashes(mutated)
    assert mutated.fabric.fabric_hash != base.fabric.fabric_hash


def test_packet_format_mutation_moves_fabric_hash():
    base = _det_bundle()
    mutated = _det_bundle(max_flits=16)
    assert mutated.packet_format.packet_format_hash \
        != base.packet_format.packet_format_hash
    assert mutated.realization.routing_realization_hash \
        == base.realization.routing_realization_hash
    assert mutated.router_behavior.router_behavior_hash \
        == base.router_behavior.router_behavior_hash
    assert mutated.fabric.fabric_hash != base.fabric.fabric_hash


def test_router_behavior_mutation_moves_fabric_hash():
    base = _det_bundle()
    mutated = _det_bundle(depth=16)
    assert mutated.router_behavior.router_behavior_hash \
        != base.router_behavior.router_behavior_hash
    assert mutated.realization.routing_realization_hash \
        == base.realization.routing_realization_hash
    assert mutated.packet_format.packet_format_hash \
        == base.packet_format.packet_format_hash
    assert mutated.address_decode.address_decode_hash \
        == base.address_decode.address_decode_hash
    assert mutated.fabric.fabric_hash != base.fabric.fabric_hash


def test_address_decode_mutation_moves_fabric_hash():
    base = _det_bundle()
    mutated = _det_bundle(design=_design(base=0x2000))
    assert mutated.attachment.attachment_hash() \
        == base.attachment.attachment_hash()
    assert mutated.address_decode.address_decode_hash \
        != base.address_decode.address_decode_hash
    assert mutated.realization.routing_realization_hash \
        == base.realization.routing_realization_hash
    assert mutated.fabric.fabric_hash != base.fabric.fabric_hash


# ── hash cascade ───────────────────────────────────────────────────────────

def test_vc_resource_cascade():
    base = _det_bundle()
    mutated = _det_bundle(vc=_vc4(), mapping={i: DOR_XY for i in range(4)},
                          transitions=_MIN_ADAPT_TRANSITIONS)
    assert mutated.realization.routing_realization_hash \
        != base.realization.routing_realization_hash
    assert mutated.packet_format.packet_format_hash \
        != base.packet_format.packet_format_hash
    assert mutated.router_behavior.router_behavior_hash \
        != base.router_behavior.router_behavior_hash
    # attachment/address decode did not change
    assert mutated.attachment.attachment_hash() \
        == base.attachment.attachment_hash()
    assert mutated.address_decode.address_decode_hash \
        == base.address_decode.address_decode_hash
    assert mutated.fabric.fabric_hash != base.fabric.fabric_hash


def test_router_behavior_leaf_cascade():
    base = _det_bundle()
    mutated = _det_bundle(depth=16)
    assert mutated.router_behavior.router_behavior_hash \
        != base.router_behavior.router_behavior_hash
    assert mutated.fabric.fabric_hash != base.fabric.fabric_hash
    for name in ("topology", "attachment", "vc", "realization",
                 "packet_format", "address_decode"):
        if name == "topology":
            left, right = (base.topology.topology_hash(),
                           mutated.topology.topology_hash())
        elif name == "attachment":
            left, right = (base.attachment.attachment_hash(),
                           mutated.attachment.attachment_hash())
        elif name == "vc":
            left, right = base.vc.artifact_hash, mutated.vc.artifact_hash
        elif name == "realization":
            left, right = (base.realization.routing_realization_hash,
                           mutated.realization.routing_realization_hash)
        elif name == "packet_format":
            left, right = (base.packet_format.packet_format_hash,
                           mutated.packet_format.packet_format_hash)
        else:
            left, right = (base.address_decode.address_decode_hash,
                           mutated.address_decode.address_decode_hash)
        assert left == right, name


# ── identity invariance ────────────────────────────────────────────────────

def test_adaptive_policy_id_invariance():
    base = _adapt_bundle()
    policy = _min_adapt_policy()
    renamed = dataclasses.replace(policy, id="renamed_policy", policy_hash="")
    renamed_relation = dataclasses.replace(base.relation,
                                           policy_hash=renamed.policy_hash,
                                           relation_hash="")
    renamed_binding = dataclasses.replace(base.binding,
                                          policy_hash=renamed.policy_hash,
                                          binding_hash="")
    twin = _adapt_bundle(policy=renamed)
    # rebuild twin's relation/binding to match the renamed policy
    twin = _adapt_bundle(policy=renamed)
    assert policy.policy_hash != renamed.policy_hash
    assert renamed_relation.relation_hash != base.relation.relation_hash
    assert renamed_binding.binding_hash != base.binding.binding_hash
    assert twin.fabric.fabric_hash == base.fabric.fabric_hash


def test_adaptive_proof_obligation_invariance():
    base = _adapt_bundle()
    policy = _min_adapt_policy()
    alternate = dataclasses.replace(
        policy, deadlock_proof_obligation=DeadlockProofObligation.EXTERNAL,
        policy_hash="")
    alternate_relation = dataclasses.replace(
        base.relation, policy_hash=alternate.policy_hash, relation_hash="")
    alternate_binding = dataclasses.replace(
        base.binding, policy_hash=alternate.policy_hash, binding_hash="")
    twin = _adapt_bundle(policy=alternate, relation=alternate_relation,
                         binding=alternate_binding)
    assert policy.policy_hash != alternate.policy_hash
    assert twin.realization.routing_realization_hash \
        == base.realization.routing_realization_hash
    assert twin.fabric.fabric_hash == base.fabric.fabric_hash


def test_deterministic_escape_designation_invariance():
    without = _det_bundle(escape=())
    with_escape = _det_bundle(escape=(0,))
    assert without.assignment.vc_assignment_hash() \
        != with_escape.assignment.vc_assignment_hash()
    assert without.realization.routing_realization_hash \
        == with_escape.realization.routing_realization_hash
    assert without.fabric.fabric_hash == with_escape.fabric.fabric_hash


def test_address_label_invariance():
    base = _det_bundle()
    renamed = _det_bundle(design=_design(name="weights"))
    assert base.design.design_hash() != renamed.design.design_hash()
    assert base.attachment.attachment_hash() \
        == renamed.attachment.attachment_hash()
    assert base.address_decode.address_decode_hash \
        == renamed.address_decode.address_decode_hash
    assert base.fabric.fabric_hash == renamed.fabric.fabric_hash


# ── hardware-only address validation ───────────────────────────────────────

def test_fabric_does_not_validate_against_a_design_address_map():
    base = _det_bundle()
    hbm = next(endpoint for endpoint in base.attachment.endpoints
               if endpoint.agent.group_index == 1)
    hardware_legal = AddressDecodeArtifact(
        attachment_hash=base.attachment.attachment_hash(),
        entries=(AddressDecodeEntry("unrelated", 0x4000, 0x1000, 1,
                                    hbm.endpoint_id),),
        address_transform=AddressTransform.IDENTITY,
        unmatched_address_policy=UnmatchedAddressPolicy.ERROR)
    fabric = make_deterministic_fabric(
        topology=base.topology, attachment=base.attachment, vc_resource=base.vc,
        routing_realization=base.realization,
        packet_format=base.packet_format,
        router_behavior=base.router_behavior, address_decode=hardware_legal,
        route=base.route, resolved_route=base.resolved,
        vc_assignment=base.assignment)
    assert fabric.address_decode_hash != base.fabric.address_decode_hash
    assert fabric.fabric_hash != base.fabric.fabric_hash


# ── Frankenstein DAG refusals ──────────────────────────────────────────────

def _compose_det(base, **over):
    kwargs = dict(
        topology=base.topology, attachment=base.attachment,
        vc_resource=base.vc, routing_realization=base.realization,
        packet_format=base.packet_format,
        router_behavior=base.router_behavior,
        address_decode=base.address_decode, route=base.route,
        resolved_route=base.resolved, vc_assignment=base.assignment)
    kwargs.update(over)
    return make_deterministic_fabric(**kwargs)


def test_frankenstein_packet_format_topology():
    base = _det_bundle()
    other = _det_bundle(topology=materialize_family(
        MaterializedFamily.TORUS, endpoint_count=4),
        classes=(ANYNET_MIN_HOPS,))
    with pytest.raises(FabricArtifactError, match="packet_format.topology"):
        _compose_det(base, packet_format=other.packet_format)


def test_frankenstein_packet_format_attachment():
    base = _det_bundle()
    other = _det_bundle(design=_design(hbm_kw={"data_width": 512}))
    with pytest.raises(FabricArtifactError, match="packet_format.attachment"):
        _compose_det(base, packet_format=other.packet_format)


def test_frankenstein_packet_format_vc_resource():
    base = _det_bundle()
    other = _det_bundle(vc=_vc4(), mapping={i: DOR_XY for i in range(4)},
                        transitions=_MIN_ADAPT_TRANSITIONS)
    with pytest.raises(FabricArtifactError, match="packet_format.vc_resource"):
        _compose_det(base, packet_format=other.packet_format)


def test_frankenstein_router_behavior_vc_resource():
    base = _det_bundle()
    other = _det_bundle(vc=_vc4(), mapping={i: DOR_XY for i in range(4)},
                        transitions=_MIN_ADAPT_TRANSITIONS)
    with pytest.raises(FabricArtifactError,
                       match="router_behavior.vc_resource"):
        _compose_det(base, router_behavior=other.router_behavior)


def test_frankenstein_routing_realization_topology():
    base = _det_bundle()
    other = _det_bundle(topology=materialize_family(
        MaterializedFamily.TORUS, endpoint_count=4),
        classes=(ANYNET_MIN_HOPS,))
    with pytest.raises(FabricArtifactError,
                       match="routing_realization.topology"):
        _compose_det(base, routing_realization=other.realization)


def test_frankenstein_routing_realization_vc_resource():
    base = _det_bundle()
    other = _det_bundle(vc=_vc4(), mapping={i: DOR_XY for i in range(4)},
                        transitions=_MIN_ADAPT_TRANSITIONS)
    with pytest.raises(FabricArtifactError,
                       match="routing_realization.vc_resource"):
        _compose_det(base, routing_realization=other.realization)


def test_frankenstein_address_decode_attachment():
    base = _det_bundle()
    other = _det_bundle(design=_design(hbm_kw={"data_width": 512}))
    assert other.address_decode.attachment_hash \
        != base.attachment.attachment_hash()
    with pytest.raises(FabricArtifactError, match="address_decode.attachment"):
        _compose_det(base, address_decode=other.address_decode)


def test_frankenstein_deterministic_unrelated_route_sources():
    base = _det_bundle()
    other = _det_bundle(classes=(ANYNET_MIN_HOPS,))
    with pytest.raises(FabricArtifactError):
        _compose_det(base, route=other.route, resolved_route=other.resolved,
                     vc_assignment=other.assignment)


def test_frankenstein_adaptive_unrelated_sources():
    base = _adapt_bundle()
    policy = _min_adapt_policy()
    renamed = dataclasses.replace(policy, id="other_policy", policy_hash="")
    other = _adapt_bundle(policy=renamed)
    with pytest.raises(FabricArtifactError):
        make_adaptive_fabric(
            topology=base.topology, attachment=base.attachment,
            vc_resource=base.vc, routing_realization=base.realization,
            packet_format=base.packet_format,
            router_behavior=base.router_behavior,
            address_decode=base.address_decode, policy=renamed,
            relation=other.relation, binding=other.binding)


# ── explicit branch refusal ────────────────────────────────────────────────

def test_branches_refuse_each_other():
    deterministic = _det_bundle()
    adaptive = _adapt_bundle()
    with pytest.raises(FabricArtifactError, match="DETERMINISTIC"):
        adaptive.fabric.validate_against_deterministic(
            topology=adaptive.topology, attachment=adaptive.attachment,
            vc_resource=adaptive.vc,
            routing_realization=adaptive.realization,
            packet_format=adaptive.packet_format,
            router_behavior=adaptive.router_behavior,
            address_decode=adaptive.address_decode, route=deterministic.route,
            resolved_route=deterministic.resolved,
            vc_assignment=deterministic.assignment)
    with pytest.raises(FabricArtifactError, match="ADAPTIVE"):
        deterministic.fabric.validate_against_adaptive(
            topology=deterministic.topology,
            attachment=deterministic.attachment, vc_resource=deterministic.vc,
            routing_realization=deterministic.realization,
            packet_format=deterministic.packet_format,
            router_behavior=deterministic.router_behavior,
            address_decode=deterministic.address_decode,
            policy=adaptive.policy, relation=adaptive.relation,
            binding=adaptive.binding)


# ── builders are composition only ──────────────────────────────────────────

def test_builders_require_every_parent():
    base = _det_bundle()
    with pytest.raises(TypeError):
        make_deterministic_fabric(topology=base.topology)
    with pytest.raises(TypeError):
        make_adaptive_fabric(topology=base.topology)


def test_builders_do_not_construct_missing_children():
    base = _det_bundle()
    with pytest.raises(FabricArtifactError, match="packet_format"):
        _compose_det(base, packet_format=object())


def test_validate_common_rejects_non_artifacts():
    base = _det_bundle()
    with pytest.raises(FabricArtifactError, match="TopologyArtifact"):
        base.fabric.validate_against_deterministic(
            topology=object(), attachment=base.attachment, vc_resource=base.vc,
            routing_realization=base.realization,
            packet_format=base.packet_format,
            router_behavior=base.router_behavior,
            address_decode=base.address_decode, route=base.route,
            resolved_route=base.resolved, vc_assignment=base.assignment)


# ── strict serialization / immutability ────────────────────────────────────

def test_roundtrip_is_lossless():
    base = _det_bundle()
    loaded = FabricArtifact.from_dict(base.fabric.to_dict())
    assert loaded == base.fabric
    assert loaded.to_dict() == base.fabric.to_dict()


def test_unknown_and_missing_fields_are_refused():
    base = _det_bundle()
    persisted = base.fabric.to_dict()
    persisted["extra"] = 1
    with pytest.raises(FabricArtifactError, match="unknown fields"):
        FabricArtifact.from_dict(persisted)
    for field in sorted(SERIALIZED_KEYS):
        persisted = base.fabric.to_dict()
        persisted.pop(field)
        with pytest.raises(FabricArtifactError):
            FabricArtifact.from_dict(persisted)


@pytest.mark.parametrize("bad", [None, "srota/RoutingRealizationArtifact", 7])
def test_type_tag_is_strict(bad):
    base = _det_bundle()
    persisted = base.fabric.to_dict()
    if bad is None:
        persisted.pop("type")
    else:
        persisted["type"] = bad
    with pytest.raises(FabricArtifactError, match="type"):
        FabricArtifact.from_dict(persisted)


@pytest.mark.parametrize("bad", [0, 2, "1", True])
def test_schema_version_is_strict(bad):
    base = _det_bundle()
    persisted = base.fabric.to_dict()
    persisted["schema_version"] = bad
    with pytest.raises(FabricArtifactError, match="schema_version"):
        FabricArtifact.from_dict(persisted)


@pytest.mark.parametrize("bad", ["multi_plane", "dual", 2, "single"])
def test_plane_composition_is_strict(bad):
    base = _det_bundle()
    persisted = base.fabric.to_dict()
    persisted["plane_composition"] = bad
    with pytest.raises(FabricArtifactError, match="plane"):
        FabricArtifact.from_dict(persisted)


@pytest.mark.parametrize("field", [
    "topology_hash", "attachment_hash", "vc_resource_hash",
    "routing_realization_hash", "packet_format_hash", "router_behavior_hash",
    "address_decode_hash", "fabric_hash",
])
@pytest.mark.parametrize("bad", [True, 7, "", "a" * 63, "A" * 64, "g" * 64])
def test_hash_fields_are_strict(field, bad):
    base = _det_bundle()
    persisted = base.fabric.to_dict()
    persisted[field] = bad
    with pytest.raises(FabricArtifactError, match="hash"):
        FabricArtifact.from_dict(persisted)


def test_tampered_hash_is_refused():
    base = _det_bundle()
    persisted = base.fabric.to_dict()
    persisted["fabric_hash"] = "0" * 64
    with pytest.raises(FabricArtifactError, match="does not match"):
        FabricArtifact.from_dict(persisted)


def test_forged_self_consistent_fabric_fails_branch_validation():
    base = _det_bundle()
    forged = dataclasses.replace(base.fabric, fabric_hash="",
                                 topology_hash="0" * 64)
    loaded = FabricArtifact.from_dict(forged.to_dict())
    assert loaded.fabric_hash == forged.fabric_hash
    with pytest.raises(FabricArtifactError, match="topology_hash"):
        loaded.validate_against_deterministic(
            topology=base.topology, attachment=base.attachment, vc_resource=base.vc,
            routing_realization=base.realization,
            packet_format=base.packet_format,
            router_behavior=base.router_behavior,
            address_decode=base.address_decode, route=base.route,
            resolved_route=base.resolved, vc_assignment=base.assignment)


def test_artifact_is_frozen_and_to_dict_is_fresh():
    base = _det_bundle()
    with pytest.raises(dataclasses.FrozenInstanceError):
        base.fabric.topology_hash = "a" * 64
    first = base.fabric.to_dict()
    first["plane_composition"] = "tampered"
    first.clear()
    second = base.fabric.to_dict()
    assert second["plane_composition"] == "single_plane"
    assert base.fabric.fabric_hash == GOLDEN_DET_DOR_2X2


# ── certificate / scope sentinels ──────────────────────────────────────────

def test_no_certificate_or_design_fields():
    base = _det_bundle()
    blob = repr(base.fabric.to_dict()).lower()
    for token in FORBIDDEN_TOKENS:
        assert token not in blob, token
    assert not hasattr(base.fabric, "certificate")
    assert not hasattr(base.fabric, "design_hash")
    assert not hasattr(base.fabric, "policy_hash")


def test_module_imports_only_allowed_layers():
    tree = ast.parse(inspect.getsource(fa))
    imported: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            imported.add(node.module or "")
    local = {name for name in imported if name.startswith("veritx_dse")}
    assert local == {
        "veritx_dse.core.artifact",
        "veritx_dse.core.errors",
        "veritx_dse.core.route_artifact",
        "veritx_dse.model.address_decode",
        "veritx_dse.model.attachment",
        "veritx_dse.model.packet_format",
        "veritx_dse.model.resolved_route",
        "veritx_dse.model.router_behavior",
        "veritx_dse.model.routing_policy",
        "veritx_dse.model.routing_realization",
        "veritx_dse.model.routing_relation",
        "veritx_dse.model.routing_resource_binding",
        "veritx_dse.model.topology_artifact",
        "veritx_dse.model.vc_assignment",
        "veritx_dse.model.vc_resource",
    }
    forbidden = ("compile_model", "mapping", "placement", "verification",
                 "backend", "booksim", "astra", "cli", "report")
    for name in imported:
        assert not any(token in name.lower() for token in forbidden), name


def test_no_optional_parent_mega_validator():
    source = inspect.getsource(fa)
    # two explicit builders; no route=None/policy=None optional soup
    assert "def make_deterministic_fabric" in source
    assert "def make_adaptive_fabric" in source
    assert "def validate_against_deterministic" in source
    assert "def validate_against_adaptive" in source
