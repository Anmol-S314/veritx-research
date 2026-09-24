"""RouterBehaviorArtifact v3 tests — routing-independent router semantics.

Parent is ``VCResourceArtifact`` only. The historical baseline is used as a
semantic oracle; v3 hashes are new because the parent intentionally changed
from the routing-specific VCAssignmentArtifact.
"""
from __future__ import annotations

import ast
import dataclasses
import inspect

import pytest

from veritx_dse.core.route_artifact import ANYNET_MIN_HOPS, DOR_XY, RouteArtifact
from veritx_dse.model import router_behavior as rb
from veritx_dse.model.attachment import derive_attachment
from veritx_dse.model.compile_model import (
    Agent, AgentKind, CompileRequest, ModelFamily, NocConfig, TopologyFamily,
    Workload,
)
from veritx_dse.model.packet_format import (
    FieldMutability, FlitFieldRole, derive_packet_format,
)
from veritx_dse.model.placement import build_inventory
from veritx_dse.model.resolved_route import derive_resolved_route
from veritx_dse.model.router_behavior import (
    AllocatorPolicy, BufferOrganization, FlowControlProtocol,
    InputVCPacketPolicy, RouterBehaviorArtifact, RouterBehaviorError,
    VCAllocationScope, VCReusePolicy, canonical_allocator,
    derive_router_behavior,
)
from veritx_dse.model.routing_policy import (
    CandidateMode, DeadlockProofObligation, DecisionScope, PathMode,
    RandomnessMode, RoutingPolicyDefinition, RoutingResourceRole,
    RoutingResourceRoleKind, RuntimeObservation, SelectionLocus,
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

GOLDEN_1VC_ISLIP = (
    "0846fde87f152995232f05102b5ca6c837c199dcfab3783746263531d8d22b92")
GOLDEN_1VC_RR = (
    "eb7e3becf149261eb250139309f67e263c577d4655dd9c85f2ff667231a1fc9f")
GOLDEN_MIN_ADAPT_4VC = (
    "a79d69bca081fed8e20feaa9181f36453565a16fde1f5a5818d66df224e4590f")
GOLDEN_1VC_DEPTH_16 = (
    "4b0eb3e5343fd65a120e02a3c303880ecb72161700b6ced0ab888a5b92da89b3")

_MIN_ADAPT_TRANSITIONS = (
    (0, 0), (1, 0), (1, 1), (1, 2), (1, 3),
    (2, 0), (2, 1), (2, 2), (2, 3), (3, 0), (3, 1), (3, 2), (3, 3),
)

SEMANTIC_FIELDS = {
    "vc_resource_hash",
    "buffer_organization", "input_buffer_depth_flits_per_vc",
    "output_stage_depth_flits_per_vc",
    "flow_control", "credit_return_latency_cycles", "vc_reuse_policy",
    "vc_allocator", "switch_allocator", "allocator_iterations",
    "hold_switch_for_packet", "input_vc_packet_policy",
    "vc_allocation_scope",
    "input_speedup", "output_speedup", "internal_speedup",
    "route_compute_cycles", "vc_alloc_cycles", "switch_alloc_cycles",
    "switch_traversal_cycles", "output_delay_cycles",
}
DATACLASS_FIELDS = SEMANTIC_FIELDS | {"schema_version", "router_behavior_hash"}
IDENTITY_KEYS = SEMANTIC_FIELDS | {"type", "schema_version"}
SERIALIZED_KEYS = IDENTITY_KEYS | {"router_behavior_hash"}

FORBIDDEN_TOKENS = (
    "topology_hash", "attachment_hash", "packet_format_hash", "route_hash",
    "resolved_route_hash", "policy_hash", "relation_hash", "binding_hash",
    "vc_assignment_hash", "channel_id", "endpoint_id", "router_id",
    "routing_class", "routing_role", "escape", "backend", "seed", "run_id",
    "timestamp", "verdict", "booksim", "astra",
)


# ── fixtures ───────────────────────────────────────────────────────────────

def _vc(n: int, *, transitions=None,
        traffic=(("default", None),)) -> VCResourceArtifact:
    if transitions is None:
        transitions = tuple((i, i) for i in range(n))
    rows = []
    for cls, vcs in traffic:
        rows.append((cls, tuple(range(n)) if vcs is None else vcs))
    return VCResourceArtifact(vc_count=n, vc_ids=tuple(range(n)),
                              traffic_class_to_vcs=tuple(rows),
                              allowed_transitions=transitions)


def _min_adapt_resource() -> VCResourceArtifact:
    return _vc(4, transitions=_MIN_ADAPT_TRANSITIONS,
               traffic=(("default", (0, 1, 2, 3)),))


def _baseline(vc_resource=None, **kw) -> RouterBehaviorArtifact:
    if vc_resource is None:
        vc_resource = _vc(1)
    return derive_router_behavior(vc_resource=vc_resource, **kw)


def _mutate(art: RouterBehaviorArtifact,
            **kw) -> RouterBehaviorArtifact:
    return dataclasses.replace(art, router_behavior_hash="", **kw)


def _fabric4():
    cr = CompileRequest(
        workload=Workload(model_family=ModelFamily.MOE, tp=1, pp=1, ep=1, dp=1),
        requirements=[], agents=[Agent(kind=AgentKind.COMPUTE_TILE, count=4)],
        dependencies=[],
        noc_config=NocConfig(topology_family=TopologyFamily.MESH))
    inv = build_inventory(cr)
    topology = materialize_topology(inv, cr)
    attachment = derive_attachment(design=cr, inventory=inv, topology=topology)
    return cr, inv, topology, attachment


def _min_adapt_policy() -> RoutingPolicyDefinition:
    return RoutingPolicyDefinition(
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


def _legacy_assignments():
    _cr, _inv, topology, attachment = _fabric4()
    anynet_route = RouteArtifact.from_topology(
        topology, name="anynet", routing_classes=(ANYNET_MIN_HOPS,))
    dor_route = RouteArtifact.from_topology(
        topology, name="dor", routing_classes=(DOR_XY,))
    anynet_resolved = derive_resolved_route(topology, attachment, anynet_route)
    dor_resolved = derive_resolved_route(topology, attachment, dor_route)
    transitions = _MIN_ADAPT_TRANSITIONS
    left = make_vc_assignment_artifact(
        resolved_route=anynet_resolved, derivation="legacy-left",
        vc_count=4, traffic_class_to_vcs={"default": [0, 1, 2, 3]},
        vc_to_routing_class={i: ANYNET_MIN_HOPS for i in range(4)},
        allowed_transitions=transitions, escape_vcs=(0,))
    right = make_vc_assignment_artifact(
        resolved_route=dor_resolved, derivation="legacy-right",
        vc_count=4, traffic_class_to_vcs={"default": [0, 1, 2, 3]},
        vc_to_routing_class={i: DOR_XY for i in range(4)},
        allowed_transitions=transitions, escape_vcs=())
    return left, right


# ── vocabulary ─────────────────────────────────────────────────────────────

def test_vocabulary_is_exactly_pinned():
    assert [(m.name, m.value) for m in BufferOrganization] == [
        ("PER_INPUT_PORT_PER_VC", "per_input_port_per_vc")]
    assert [(m.name, m.value) for m in FlowControlProtocol] == [
        ("CREDIT", "credit")]
    assert [(m.name, m.value) for m in AllocatorPolicy] == [
        ("ISLIP", "islip"), ("ROUND_ROBIN", "round_robin")]
    assert [(m.name, m.value) for m in InputVCPacketPolicy] == [
        ("ONE_PACKET_AT_A_TIME", "one_packet_at_a_time")]
    assert [(m.name, m.value) for m in VCAllocationScope] == [
        ("PACKET", "packet")]
    assert [(m.name, m.value) for m in VCReusePolicy] == [
        ("WAIT_FOR_TAIL_CREDIT", "wait_for_tail_credit"),
        ("RELEASE_ON_TAIL_SEND", "release_on_tail_send")]


def test_no_speculative_vocabulary():
    assert not hasattr(rb, "PacketHoldPolicy")
    assert not hasattr(rb, "SwitchArbitrationPolicy")
    names = {field.name for field in dataclasses.fields(RouterBehaviorArtifact)}
    assert "packet_hold_policy" not in names
    assert "packet_hold_policy" not in IDENTITY_KEYS


# ── historical baseline semantic oracle ────────────────────────────────────

def test_historical_baseline_semantics_are_preserved():
    art = _baseline()
    assert art.buffer_organization is BufferOrganization.PER_INPUT_PORT_PER_VC
    assert art.input_buffer_depth_flits_per_vc == 8
    assert art.output_stage_depth_flits_per_vc == 1
    assert art.flow_control is FlowControlProtocol.CREDIT
    assert art.credit_return_latency_cycles == 1
    assert art.vc_reuse_policy is VCReusePolicy.WAIT_FOR_TAIL_CREDIT
    assert art.vc_allocator is AllocatorPolicy.ISLIP
    assert art.switch_allocator is AllocatorPolicy.ISLIP
    assert art.allocator_iterations == 1
    assert art.hold_switch_for_packet is False
    assert art.input_vc_packet_policy is \
        InputVCPacketPolicy.ONE_PACKET_AT_A_TIME
    assert art.vc_allocation_scope is VCAllocationScope.PACKET
    assert (art.input_speedup, art.output_speedup,
            art.internal_speedup) == (1, 1, 1)
    assert art.route_compute_cycles == 0
    assert art.vc_alloc_cycles == 1
    assert art.switch_alloc_cycles == 1
    assert art.switch_traversal_cycles == 1
    assert art.output_delay_cycles == 0
    assert art.schema_version == 3


def test_corrected_packet_context_semantics_are_independent():
    art = _baseline()
    held = _mutate(art, hold_switch_for_packet=True)
    assert held.hold_switch_for_packet is True
    assert held.input_vc_packet_policy is \
        InputVCPacketPolicy.ONE_PACKET_AT_A_TIME
    assert held.vc_allocation_scope is VCAllocationScope.PACKET
    assert held.router_behavior_hash != art.router_behavior_hash
    # packet context and allocation scope are not switch granularity
    assert art.hold_switch_for_packet is False
    assert art.input_vc_packet_policy is not None
    assert art.vc_allocation_scope is not None


def test_baseline_hash_is_not_the_historical_hash():
    # v3 domain is new; historical v2 hashes must not be reproduced
    assert _baseline().router_behavior_hash == GOLDEN_1VC_ISLIP
    assert rb._HASH_TYPE_TAG == "srota/RouterBehaviorArtifact"
    assert rb.ROUTER_BEHAVIOR_SCHEMA_VERSION == 3


# ── golden pins ────────────────────────────────────────────────────────────

def test_golden_one_vc_islip():
    assert _baseline().router_behavior_hash == GOLDEN_1VC_ISLIP


def test_golden_one_vc_round_robin():
    art = _baseline(arbitration="round_robin")
    assert art.vc_allocator is AllocatorPolicy.ROUND_ROBIN
    assert art.switch_allocator is AllocatorPolicy.ROUND_ROBIN
    assert art.router_behavior_hash == GOLDEN_1VC_RR


def test_golden_min_adapt_four_vc():
    art = _baseline(vc_resource=_min_adapt_resource())
    assert art.router_behavior_hash == GOLDEN_MIN_ADAPT_4VC


def test_golden_input_buffer_depth_16():
    art = _baseline(buffer_depth_flits=16)
    assert art.input_buffer_depth_flits_per_vc == 16
    assert art.router_behavior_hash == GOLDEN_1VC_DEPTH_16


# ── arbitration normalization ──────────────────────────────────────────────

@pytest.mark.parametrize("label,expected", [
    (None, AllocatorPolicy.ISLIP),
    ("islip", AllocatorPolicy.ISLIP),
    (" iSLIP ", AllocatorPolicy.ISLIP),
    ("round_robin", AllocatorPolicy.ROUND_ROBIN),
    ("round-robin", AllocatorPolicy.ROUND_ROBIN),
    ("rr", AllocatorPolicy.ROUND_ROBIN),
    ("RR", AllocatorPolicy.ROUND_ROBIN),
])
def test_canonical_allocator_aliases(label, expected):
    assert canonical_allocator(label) is expected


@pytest.mark.parametrize("bad", ["priority", "escape_first", "random",
                                 "greedy", "free_form_thing", ""])
def test_canonical_allocator_fails_closed(bad):
    with pytest.raises(RouterBehaviorError, match="arbitration"):
        canonical_allocator(bad)


@pytest.mark.parametrize("bad", [7, 1.5, True, ["islip"]])
def test_canonical_allocator_rejects_non_strings(bad):
    with pytest.raises(RouterBehaviorError, match="arbitration"):
        canonical_allocator(bad)


def test_raw_arbitration_spelling_is_not_identity():
    none = _baseline(arbitration=None)
    islip = _baseline(arbitration="islip")
    spaced = _baseline(arbitration=" iSLIP ")
    assert none.router_behavior_hash == islip.router_behavior_hash \
        == spaced.router_behavior_hash == GOLDEN_1VC_ISLIP


def test_round_robin_aliases_share_one_identity():
    hashes = {_baseline(arbitration=alias).router_behavior_hash
              for alias in ("round_robin", "round-robin", "rr", "RR")}
    assert hashes == {GOLDEN_1VC_RR}


def test_unknown_arbitration_in_builder_is_refused():
    with pytest.raises(RouterBehaviorError, match="arbitration"):
        _baseline(arbitration="priority")


# ── VC reuse policy ────────────────────────────────────────────────────────

def test_reuse_policies_are_distinct_valid_states():
    wait = _baseline()
    release = _mutate(wait, vc_reuse_policy=VCReusePolicy.RELEASE_ON_TAIL_SEND)
    assert wait.vc_reuse_policy is VCReusePolicy.WAIT_FOR_TAIL_CREDIT
    assert release.vc_reuse_policy is VCReusePolicy.RELEASE_ON_TAIL_SEND
    assert wait.router_behavior_hash != release.router_behavior_hash
    loaded = RouterBehaviorArtifact.from_dict(release.to_dict())
    assert loaded.vc_reuse_policy is VCReusePolicy.RELEASE_ON_TAIL_SEND
    assert loaded.router_behavior_hash == release.router_behavior_hash


# ── parent validation ──────────────────────────────────────────────────────

def test_one_vc_resource_is_a_valid_parent():
    resource = _vc(1)
    art = _baseline(vc_resource=resource)
    assert art.validate_against(resource) is None


def test_min_adapt_four_vc_resource_is_a_valid_parent():
    resource = _min_adapt_resource()
    art = _baseline(vc_resource=resource)
    art.validate_against(resource)
    assert art.vc_resource_hash == resource.artifact_hash
    assert resource.vc_count == 4


def test_minimal_resources_are_valid_parents():
    # no identity transitions, not every VC traffic-injectable, no escape
    sparse = _vc(4, transitions=(), traffic=(("default", (0,)),))
    art = _baseline(vc_resource=sparse)
    art.validate_against(sparse)
    assert art.vc_resource_hash == sparse.artifact_hash


def test_wrong_parent_hash_is_refused():
    art = _baseline(vc_resource=_vc(1))
    with pytest.raises(RouterBehaviorError, match="vc_resource_hash"):
        art.validate_against(_vc(2))


def test_non_resource_parent_is_refused():
    art = _baseline()
    with pytest.raises(RouterBehaviorError, match="VCResourceArtifact"):
        art.validate_against(object())


def test_tampered_parent_is_refused():
    resource = _vc(1)
    art = _baseline(vc_resource=resource)
    object.__setattr__(resource, "artifact_hash", "0" * 64)
    with pytest.raises(RouterBehaviorError, match="inconsistent"):
        art.validate_against(resource)


def test_tampered_behavior_hash_is_refused_on_validate():
    art = _baseline()
    object.__setattr__(art, "router_behavior_hash", "0" * 64)
    with pytest.raises(RouterBehaviorError, match="does not match content"):
        art.validate_against(_vc(1))


def test_transition_semantics_flow_through_the_parent():
    left = _vc(2, transitions=((0, 0), (1, 1)))
    right = _vc(2, transitions=((0, 0), (0, 1), (1, 1)))
    left_art = _baseline(vc_resource=left)
    right_art = _baseline(vc_resource=right)
    assert left_art.vc_resource_hash != right_art.vc_resource_hash
    assert left_art.router_behavior_hash != right_art.router_behavior_hash
    left_art.validate_against(left)
    right_art.validate_against(right)


def test_no_transition_table_authority():
    art = _baseline()
    assert not hasattr(art, "allowed_transitions")
    assert "allowed_transitions" not in art.to_dict()
    assert "allowed_transitions" not in dataclasses.asdict(art)


# ── legacy projection proof ────────────────────────────────────────────────

def test_legacy_routing_labels_do_not_move_router_identity():
    left, right = _legacy_assignments()
    assert left.vc_assignment_hash() != right.vc_assignment_hash()
    projected_left = vc_resources_from_assignment(left)
    projected_right = vc_resources_from_assignment(right)
    assert projected_left.artifact_hash == projected_right.artifact_hash
    behavior_left = _baseline(vc_resource=projected_left)
    behavior_right = _baseline(vc_resource=projected_right)
    assert behavior_left.router_behavior_hash \
        == behavior_right.router_behavior_hash == GOLDEN_MIN_ADAPT_4VC
    behavior_left.validate_against(projected_left)
    behavior_right.validate_against(projected_right)


def test_projected_behavior_matches_direct_resource_behavior():
    left, _right = _legacy_assignments()
    projected = vc_resources_from_assignment(left)
    assert projected.artifact_hash == _min_adapt_resource().artifact_hash
    assert _baseline(vc_resource=projected).router_behavior_hash \
        == GOLDEN_MIN_ADAPT_4VC


# ── deterministic / adaptive reuse ─────────────────────────────────────────

def test_deterministic_and_adaptive_chains_reuse_one_behavior():
    _cr, _inv, topology, attachment = _fabric4()
    resource = _min_adapt_resource()
    behavior = _baseline(vc_resource=resource)

    dor_route = RouteArtifact.from_topology(
        topology, name="dor", routing_classes=(DOR_XY,))
    resolved = derive_resolved_route(topology, attachment, dor_route)
    assignment = make_vc_assignment_artifact(
        resolved_route=resolved, derivation="det-chain",
        vc_count=4, traffic_class_to_vcs={"default": [0, 1, 2, 3]},
        vc_to_routing_class={i: DOR_XY for i in range(4)},
        allowed_transitions=_MIN_ADAPT_TRANSITIONS, escape_vcs=())
    projected = vc_resources_from_assignment(assignment)
    assert projected.artifact_hash == resource.artifact_hash
    behavior.validate_against(projected)

    policy = _min_adapt_policy()
    relation = materialize_routing_relation(topology, policy)
    binding = RoutingResourceBindingArtifact(
        policy_hash=policy.policy_hash,
        vc_resource_hash=resource.artifact_hash,
        role_to_vcs=(("adaptive", (1, 2, 3)), ("escape", (0,))))
    binding.validate_against(policy, resource)
    assert relation.relation_hash and binding.binding_hash
    assert behavior.router_behavior_hash == GOLDEN_MIN_ADAPT_4VC


# ── packet-format independence ─────────────────────────────────────────────

def test_packet_format_is_not_a_parent():
    art = _baseline()
    assert "packet_format_hash" not in art.identity_dict()
    assert "packet_format_hash" not in art.to_dict()


def test_flit_width_and_packet_bound_do_not_move_router_identity():
    cr, inv, topology64, attachment64 = _fabric4()
    resource = _min_adapt_resource()
    behavior = _baseline(vc_resource=resource)
    topology128 = materialize_family(MaterializedFamily.MESH,
                                     endpoint_count=4, width_bits=128)
    attachment128 = derive_attachment(design=cr, inventory=inv,
                                      topology=topology128)
    narrow = derive_packet_format(topology64, attachment64, resource,
                                  max_packet_flits=8)
    wide = derive_packet_format(topology128, attachment128, resource,
                                max_packet_flits=16)
    assert narrow.flit_width_bits == 64
    assert wide.flit_width_bits == 128
    assert narrow.packet_format_hash != wide.packet_format_hash
    assert behavior.router_behavior_hash == GOLDEN_MIN_ADAPT_4VC


def test_packet_context_structure_is_compatible_with_slice17():
    _cr, _inv, topology, attachment = _fabric4()
    resource = _min_adapt_resource()
    behavior = _baseline(vc_resource=resource)
    packet = derive_packet_format(topology, attachment, resource,
                                  max_packet_flits=8)
    roles = {field.role for field in packet.fields}
    assert FlitFieldRole.FLIT_TYPE in roles
    vc_field = next(field for field in packet.fields
                    if field.role is FlitFieldRole.VC_ID)
    assert vc_field.mutability is FieldMutability.HOP_LOCAL
    assert behavior.input_vc_packet_policy is \
        InputVCPacketPolicy.ONE_PACKET_AT_A_TIME
    assert behavior.vc_allocation_scope is VCAllocationScope.PACKET
    # structural compatibility, not a parent dependency: the only shared
    # keys are the artifact header and the shared VC-resource parent
    assert set(behavior.identity_dict()) & set(packet.identity_dict()) == {
        "type", "schema_version", "vc_resource_hash"}
    assert "packet_format_hash" not in behavior.identity_dict()
    assert "router_behavior_hash" not in packet.identity_dict()


# ── identity mutation gates ────────────────────────────────────────────────

_MUTATIONS = [
    ("route_compute_cycles", 1),
    ("vc_alloc_cycles", 2),
    ("switch_alloc_cycles", 2),
    ("switch_traversal_cycles", 2),
    ("output_delay_cycles", 1),
    ("input_speedup", 2),
    ("output_speedup", 2),
    ("internal_speedup", 2),
    ("allocator_iterations", 2),
    ("input_buffer_depth_flits_per_vc", 16),
    ("output_stage_depth_flits_per_vc", 2),
    ("credit_return_latency_cycles", 2),
    ("vc_allocator", AllocatorPolicy.ROUND_ROBIN),
    ("switch_allocator", AllocatorPolicy.ROUND_ROBIN),
    ("hold_switch_for_packet", True),
    ("vc_reuse_policy", VCReusePolicy.RELEASE_ON_TAIL_SEND),
]


@pytest.mark.parametrize("field,value", _MUTATIONS)
def test_single_semantic_mutation_moves_identity(field, value):
    art = _baseline()
    twin = _mutate(art, **{field: value})
    assert twin.router_behavior_hash != art.router_behavior_hash
    left = art.identity_dict()
    right = twin.identity_dict()
    changed = {key for key in left if left[key] != right[key]}
    assert changed == {field}


def test_parent_change_moves_identity():
    one = _baseline(vc_resource=_vc(1))
    two = _baseline(vc_resource=_vc(2))
    assert one.router_behavior_hash != two.router_behavior_hash
    changed = {key for key in one.identity_dict()
               if one.identity_dict()[key] != two.identity_dict()[key]}
    assert changed == {"vc_resource_hash"}


def test_islip_and_round_robin_differ():
    islip = _baseline()
    rr = _baseline(arbitration="rr")
    assert islip.vc_allocator is AllocatorPolicy.ISLIP
    assert rr.vc_allocator is AllocatorPolicy.ROUND_ROBIN
    assert islip.router_behavior_hash != rr.router_behavior_hash


# ── strict construction ────────────────────────────────────────────────────

@pytest.mark.parametrize("field", [
    "input_buffer_depth_flits_per_vc", "output_stage_depth_flits_per_vc",
    "credit_return_latency_cycles", "allocator_iterations",
    "input_speedup", "output_speedup", "internal_speedup",
    "route_compute_cycles", "vc_alloc_cycles", "switch_alloc_cycles",
    "switch_traversal_cycles", "output_delay_cycles",
])
@pytest.mark.parametrize("bad", [True, False, 1.0, "1", None])
def test_int_fields_refuse_non_exact_ints(field, bad):
    art = _baseline()
    with pytest.raises(RouterBehaviorError, match="exact int"):
        _mutate(art, **{field: bad})


@pytest.mark.parametrize("field,value,match", [
    ("input_buffer_depth_flits_per_vc", 0, ">= 1"),
    ("output_stage_depth_flits_per_vc", 0, ">= 1"),
    ("allocator_iterations", 0, ">= 1"),
    ("input_speedup", 0, ">= 1"),
    ("output_speedup", 0, ">= 1"),
    ("internal_speedup", 0, ">= 1"),
    ("credit_return_latency_cycles", -1, ">= 0"),
    ("route_compute_cycles", -1, ">= 0"),
    ("vc_alloc_cycles", -1, ">= 0"),
    ("switch_alloc_cycles", -1, ">= 0"),
    ("switch_traversal_cycles", -1, ">= 0"),
    ("output_delay_cycles", -1, ">= 0"),
])
def test_int_fields_enforce_ranges(field, value, match):
    art = _baseline()
    with pytest.raises(RouterBehaviorError, match=match):
        _mutate(art, **{field: value})


@pytest.mark.parametrize("bad", [0, 1, "true", None, 1.0])
def test_hold_switch_requires_exact_bool(bad):
    art = _baseline()
    with pytest.raises(RouterBehaviorError, match="exact bool"):
        _mutate(art, hold_switch_for_packet=bad)


@pytest.mark.parametrize("field,raw", [
    ("buffer_organization", "per_input_port_per_vc"),
    ("flow_control", "credit"),
    ("vc_reuse_policy", "wait_for_tail_credit"),
    ("vc_allocator", "islip"),
    ("switch_allocator", "round_robin"),
    ("input_vc_packet_policy", "one_packet_at_a_time"),
    ("vc_allocation_scope", "packet"),
])
def test_enums_must_be_enum_instances_in_construction(field, raw):
    art = _baseline()
    with pytest.raises(RouterBehaviorError, match="must be a"):
        _mutate(art, **{field: raw})


@pytest.mark.parametrize("bad", [
    "", "a" * 63, "a" * 65, "A" * 64, "g" * 64, 7, None, b"a" * 64,
])
def test_vc_resource_hash_shape_is_strict(bad):
    art = _baseline()
    with pytest.raises(RouterBehaviorError, match="vc_resource_hash"):
        _mutate(art, vc_resource_hash=bad)


@pytest.mark.parametrize("bad", [1, 2, 4, "3", True, None, 3.0])
def test_schema_version_must_be_exactly_3(bad):
    art = _baseline()
    with pytest.raises(RouterBehaviorError, match="schema_version"):
        _mutate(art, schema_version=bad)


def test_construction_requires_every_semantic_field():
    with pytest.raises(TypeError):
        RouterBehaviorArtifact(vc_resource_hash="a" * 64)
    art = _baseline()
    for field in sorted(SEMANTIC_FIELDS - {"vc_resource_hash"}):
        kw = {name: getattr(art, name) for name in SEMANTIC_FIELDS
              if name != field}
        with pytest.raises(TypeError):
            RouterBehaviorArtifact(**kw)


def test_constructor_hash_mismatch_is_refused():
    art = _baseline()
    with pytest.raises(RouterBehaviorError, match="does not match content"):
        dataclasses.replace(art, router_behavior_hash="0" * 64)


# ── strict serialization ───────────────────────────────────────────────────

def test_roundtrip_is_lossless():
    art = _baseline(vc_resource=_min_adapt_resource())
    loaded = RouterBehaviorArtifact.from_dict(art.to_dict())
    assert loaded.router_behavior_hash == art.router_behavior_hash
    assert loaded.to_dict() == art.to_dict()
    assert loaded == art


def test_serialized_keys_are_exactly_the_schema():
    art = _baseline()
    assert set(art.identity_dict()) == IDENTITY_KEYS
    assert set(art.to_dict()) == SERIALIZED_KEYS
    assert {f.name for f in dataclasses.fields(RouterBehaviorArtifact)} \
        == DATACLASS_FIELDS


def test_serialization_omits_nothing_semantic():
    art = _baseline()
    d = art.to_dict()
    for field in SEMANTIC_FIELDS:
        assert field in d
    assert d["input_vc_packet_policy"] == "one_packet_at_a_time"
    assert d["vc_allocation_scope"] == "packet"
    assert d["buffer_organization"] == "per_input_port_per_vc"
    assert d["flow_control"] == "credit"
    assert d["vc_reuse_policy"] == "wait_for_tail_credit"
    assert d["vc_allocator"] == "islip"
    assert d["switch_allocator"] == "islip"


def test_unknown_fields_are_refused():
    d = _baseline().to_dict()
    d["extra"] = 1
    with pytest.raises(RouterBehaviorError, match="unknown fields"):
        RouterBehaviorArtifact.from_dict(d)


def test_removed_historical_fields_are_refused():
    d = _baseline().to_dict()
    d["packet_hold_policy"] = "flit_interleaved"
    with pytest.raises(RouterBehaviorError, match="unknown fields"):
        RouterBehaviorArtifact.from_dict(d)
    d = _baseline().to_dict()
    d["vc_assignment_hash"] = "a" * 64
    with pytest.raises(RouterBehaviorError, match="unknown fields"):
        RouterBehaviorArtifact.from_dict(d)


@pytest.mark.parametrize("field", sorted(SERIALIZED_KEYS))
def test_missing_fields_are_refused(field):
    d = _baseline().to_dict()
    d.pop(field)
    with pytest.raises(RouterBehaviorError):
        RouterBehaviorArtifact.from_dict(d)


@pytest.mark.parametrize("bad", [None, "srota/PacketFormatArtifact", 7])
def test_type_tag_is_strict(bad):
    d = _baseline().to_dict()
    if bad is None:
        d.pop("type")
    else:
        d["type"] = bad
    with pytest.raises(RouterBehaviorError, match="type"):
        RouterBehaviorArtifact.from_dict(d)


def test_schema_v1_is_refused_with_useful_message():
    d = _baseline().to_dict()
    d["schema_version"] = 1
    d["packet_hold_policy"] = "flit_interleaved"
    with pytest.raises(RouterBehaviorError,
                       match="schema v1|packet_hold_policy|silent migration"):
        RouterBehaviorArtifact.from_dict(d)


def test_schema_v2_is_refused_with_useful_message():
    d = _baseline().to_dict()
    d["schema_version"] = 2
    d["vc_assignment_hash"] = "a" * 64
    with pytest.raises(RouterBehaviorError,
                       match="schema v2|VCAssignmentArtifact|"
                             "VCResourceArtifact|silent migration"):
        RouterBehaviorArtifact.from_dict(d)


def test_historical_v2_shape_is_refused_before_unknown_key_check():
    historical = {
        "type": "srota/RouterBehaviorArtifact",
        "schema_version": 2,
        "vc_assignment_hash": "a" * 64,
        "buffer_organization": "per_input_port_per_vc",
        "input_buffer_depth_flits_per_vc": 8,
        "output_stage_depth_flits_per_vc": 1,
        "flow_control": "credit",
        "credit_return_latency_cycles": 1,
        "vc_reuse_policy": "wait_for_tail_credit",
        "vc_allocator": "islip",
        "switch_allocator": "islip",
        "allocator_iterations": 1,
        "hold_switch_for_packet": False,
        "input_vc_packet_policy": "one_packet_at_a_time",
        "vc_allocation_scope": "packet",
        "input_speedup": 1,
        "output_speedup": 1,
        "internal_speedup": 1,
        "route_compute_cycles": 0,
        "vc_alloc_cycles": 1,
        "switch_alloc_cycles": 1,
        "switch_traversal_cycles": 1,
        "output_delay_cycles": 0,
        "artifact_hash": "a" * 64,
    }
    with pytest.raises(RouterBehaviorError, match="schema v2"):
        RouterBehaviorArtifact.from_dict(historical)


@pytest.mark.parametrize("field,value,match", [
    ("buffer_organization", "shared", "unknown buffer organization"),
    ("flow_control", "credit_based", "unknown flow control"),
    ("vc_reuse_policy", "immediate", "unknown VC reuse policy"),
    ("vc_allocator", "priority", "unknown VC allocator"),
    ("switch_allocator", "magic", "unknown switch allocator"),
    ("input_vc_packet_policy", "interleaved",
     "unknown input VC packet policy"),
    ("vc_allocation_scope", "flit", "unknown VC allocation scope"),
])
def test_unknown_persisted_enum_values_are_refused(field, value, match):
    d = _baseline().to_dict()
    d[field] = value
    with pytest.raises(RouterBehaviorError, match=match):
        RouterBehaviorArtifact.from_dict(d)


@pytest.mark.parametrize("field", [
    "input_buffer_depth_flits_per_vc", "output_stage_depth_flits_per_vc",
    "credit_return_latency_cycles", "allocator_iterations",
    "input_speedup", "output_speedup", "internal_speedup",
    "route_compute_cycles", "vc_alloc_cycles", "switch_alloc_cycles",
    "switch_traversal_cycles", "output_delay_cycles",
])
@pytest.mark.parametrize("bad", [True, 1.5, "1"])
def test_persisted_ints_reject_bool_float_string(field, bad):
    d = _baseline().to_dict()
    d[field] = bad
    with pytest.raises(RouterBehaviorError, match="exact int"):
        RouterBehaviorArtifact.from_dict(d)


@pytest.mark.parametrize("bad", [0, 1, "true", None])
def test_persisted_hold_switch_rejects_non_bool(bad):
    d = _baseline().to_dict()
    d["hold_switch_for_packet"] = bad
    with pytest.raises(RouterBehaviorError, match="exact bool"):
        RouterBehaviorArtifact.from_dict(d)


def test_hash_must_be_present_and_match():
    d = _baseline().to_dict()
    d.pop("router_behavior_hash")
    with pytest.raises(RouterBehaviorError, match="router_behavior_hash"):
        RouterBehaviorArtifact.from_dict(d)
    d = _baseline().to_dict()
    d["router_behavior_hash"] = "0" * 64
    with pytest.raises(RouterBehaviorError, match="does not match content"):
        RouterBehaviorArtifact.from_dict(d)
    d = _baseline().to_dict()
    d["router_behavior_hash"] = 7
    with pytest.raises(RouterBehaviorError, match="router_behavior_hash"):
        RouterBehaviorArtifact.from_dict(d)


# ── builder authority boundary ─────────────────────────────────────────────

def test_builder_is_keyword_only():
    with pytest.raises(TypeError):
        derive_router_behavior(_vc(1))


def test_builder_rejects_non_resource():
    with pytest.raises(RouterBehaviorError, match="VCResourceArtifact"):
        derive_router_behavior(vc_resource=object())


@pytest.mark.parametrize("kw,match", [
    ({"buffer_depth_flits": 0}, "buffer_depth_flits"),
    ({"buffer_depth_flits": True}, "exact int"),
    ({"output_stage_depth_flits": 0}, "output_stage_depth_flits"),
    ({"output_stage_depth_flits": "1"}, "exact int"),
])
def test_builder_rejects_bad_depths(kw, match):
    with pytest.raises(RouterBehaviorError, match=match):
        _baseline(**kw)


def test_builder_respects_output_stage_depth():
    art = _baseline(output_stage_depth_flits=4)
    assert art.output_stage_depth_flits_per_vc == 4


# ── scope sentinels ────────────────────────────────────────────────────────

def test_identity_has_no_routing_or_backend_fields():
    art = _baseline()
    blob = repr(art.to_dict()).lower()
    for token in FORBIDDEN_TOKENS:
        assert token not in blob, token


def test_module_imports_only_allowed_layers():
    tree = ast.parse(inspect.getsource(rb))
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
        "veritx_dse.model.vc_resource",
    }
    forbidden = ("topology", "attachment", "packet_format", "route",
                 "resolved_route", "vc_assignment", "routing_policy",
                 "routing_relation", "routing_resource", "channel_vc_cdg",
                 "protocol_vc", "adaptive_escape", "booksim", "astra",
                 "backend", "cli")
    for name in imported:
        assert not any(token in name.lower() for token in forbidden), name


def test_no_routing_or_backend_authority_symbols():
    for token in ("VCAssignmentArtifact", "RouteArtifact",
                  "RoutingPolicyDefinition", "RoutingRelationArtifact",
                  "RoutingResourceBindingArtifact", "PacketFormatArtifact",
                  "TopologyArtifact", "AgentAttachmentArtifact",
                  "BookSim", "ASTRA", "escape_priority", "congestion"):
        assert not hasattr(rb, token), token
    names = {field.name for field in dataclasses.fields(RouterBehaviorArtifact)}
    assert "allowed_transitions" not in names
    assert "escape_vcs" not in names
    assert "routing_class" not in names
