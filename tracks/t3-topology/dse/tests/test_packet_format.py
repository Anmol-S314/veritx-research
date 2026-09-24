"""PacketFormatArtifact v2 tests — routing-independent canonical flit format.

Parents are topology, attachment and concrete VC resources only. The
historical 4-endpoint/1-VC/64-bit layout is the semantic oracle; hashes are
new v2 identities because the VC parent intentionally changed.
"""
from __future__ import annotations

import ast
import dataclasses
import inspect

import pytest

from veritx_dse.model import packet_format as pf
from veritx_dse.model.attachment import (
    AgentAttachmentArtifact, derive_attachment,
)
from veritx_dse.model.compile_model import (
    Agent, AgentKind, CompileRequest, ModelFamily, NocConfig, TopologyFamily,
    Workload,
)
from veritx_dse.model.packet_format import (
    FLIT_TYPE_BODY, FLIT_TYPE_ENCODING, FLIT_TYPE_HEAD, FLIT_TYPE_SINGLE,
    FLIT_TYPE_TAIL, FLIT_TYPE_WIDTH, FieldMutability, FlitField,
    FlitFieldRole, PacketFormatArtifact, PacketFormatError,
    canonical_field_layout, derive_packet_format, encoding_width,
)
from veritx_dse.model.placement import build_inventory
from veritx_dse.model.topology_artifact import (
    MaterializedFamily, TopologyArtifact, materialize_family,
    materialize_topology,
)
from veritx_dse.model.vc_resource import VCResourceArtifact

GOLDEN_4EP_1VC_64 = (
    "b766b061e74e6eaeb9461ee6669903a2fcc44d5ebb141ec72d9c08e2e23c3689")
GOLDEN_4EP_4VC_64 = (
    "e6486c6bbdc08c355ff900691f281673f70219f61a0f17f4e3a6fd93ee4dd640")
GOLDEN_65EP_4VC_128 = (
    "224408aec9ce8223caf88a89e7a447f3232a8029934db78ad8c7770e5ef94263")
GOLDEN_4EP_1VC_128 = (
    "69759ff3b1b66195d81175d8acd5617b9dcce647263725c41fffc00a2d729d0e")
GOLDEN_MIN_ADAPT_RESOURCE = (
    "aeb8083c2ea853560a2bd15b0ce9115307c98db063c4e87b3e7b3047fada899f")

_MIN_ADAPT_TRANSITIONS = (
    (0, 0), (1, 0), (1, 1), (1, 2), (1, 3),
    (2, 0), (2, 1), (2, 2), (2, 3), (3, 0), (3, 1), (3, 2), (3, 3),
)

EXPECTED_FIELDS = {
    "topology_hash", "attachment_hash", "vc_resource_hash", "flit_width_bits",
    "max_packet_flits", "fields", "schema_version", "packet_format_hash",
}

FORBIDDEN_TOKENS = (
    "design_hash", "mapping_hash", "route_hash", "relation_hash",
    "policy_hash", "binding_hash", "vc_assignment_hash", "routing_class",
    "routing_role", "escape", "phase", "backend", "seed", "run_id",
    "timestamp", "git_sha", "booksim", "astra",
)


def _fabric(n: int, width_bits: int | None = None):
    cr = CompileRequest(
        workload=Workload(model_family=ModelFamily.MOE, tp=1, pp=1, ep=1, dp=1),
        requirements=[], agents=[Agent(kind=AgentKind.COMPUTE_TILE, count=n)],
        dependencies=[],
        noc_config=NocConfig(topology_family=TopologyFamily.MESH))
    inv = build_inventory(cr)
    if width_bits is None:
        topology = materialize_topology(inv, cr)
    else:
        topology = materialize_family(MaterializedFamily.MESH,
                                      endpoint_count=n,
                                      width_bits=width_bits)
    attachment = derive_attachment(design=cr, inventory=inv, topology=topology)
    return topology, attachment


def _vc(n: int) -> VCResourceArtifact:
    return VCResourceArtifact(
        vc_count=n, vc_ids=tuple(range(n)),
        traffic_class_to_vcs=(("default", tuple(range(n))),),
        allowed_transitions=tuple((i, i) for i in range(n)))


def _min_adapt_resource() -> VCResourceArtifact:
    return VCResourceArtifact(
        vc_count=4, vc_ids=(0, 1, 2, 3),
        traffic_class_to_vcs=(("default", (0, 1, 2, 3)),),
        allowed_transitions=_MIN_ADAPT_TRANSITIONS)


def _oracle_artifact() -> PacketFormatArtifact:
    topology, attachment = _fabric(4)
    return derive_packet_format(topology, attachment, _vc(1),
                                max_packet_flits=8)


# ── historical layout oracle ───────────────────────────────────────────────

def test_historical_oracle_layout_is_reproduced():
    artifact = _oracle_artifact()
    assert [(f.name, f.lsb, f.msb, f.width, f.role.value,
             f.mutability.value) for f in artifact.fields] == [
        ("payload", 0, 56, 57, "payload", "payload"),
        ("source_endpoint", 57, 58, 2, "source_endpoint", "packet_immutable"),
        ("destination_endpoint", 59, 60, 2, "destination_endpoint",
         "packet_immutable"),
        ("flit_type", 61, 62, 2, "flit_type", "flit_structural"),
        ("vc_id", 63, 63, 1, "vc_id", "hop_local"),
    ]
    assert artifact.header_width_bits == 7
    assert artifact.payload_bits_per_flit == 57
    assert artifact.endpoint_capacity == 4
    assert artifact.vc_capacity == 2
    assert artifact.max_network_payload_bits == 456
    assert artifact.flit_width_bits == 64


def test_mutability_semantics_are_pinned():
    artifact = _oracle_artifact()
    by_role = {f.role: f.mutability for f in artifact.fields}
    assert by_role[FlitFieldRole.PAYLOAD] is FieldMutability.PAYLOAD
    assert by_role[FlitFieldRole.SOURCE_ENDPOINT] \
        is FieldMutability.PACKET_IMMUTABLE
    assert by_role[FlitFieldRole.DESTINATION_ENDPOINT] \
        is FieldMutability.PACKET_IMMUTABLE
    assert by_role[FlitFieldRole.FLIT_TYPE] is FieldMutability.FLIT_STRUCTURAL
    assert by_role[FlitFieldRole.VC_ID] is FieldMutability.HOP_LOCAL


def test_flit_type_encoding_is_pinned():
    assert FLIT_TYPE_WIDTH == 2
    assert FLIT_TYPE_ENCODING == ((FLIT_TYPE_HEAD, 0), (FLIT_TYPE_BODY, 1),
                                  (FLIT_TYPE_TAIL, 2), (FLIT_TYPE_SINGLE, 3))


# ── golden hashes ──────────────────────────────────────────────────────────

def test_golden_4ep_1vc_64():
    assert _oracle_artifact().packet_format_hash == GOLDEN_4EP_1VC_64


def test_golden_4ep_4vc_64():
    topology, attachment = _fabric(4)
    artifact = derive_packet_format(topology, attachment, _vc(4),
                                    max_packet_flits=8)
    assert artifact.packet_format_hash == GOLDEN_4EP_4VC_64


def test_golden_65ep_4vc_128():
    topology, attachment = _fabric(65, width_bits=128)
    artifact = derive_packet_format(topology, attachment, _vc(4),
                                    max_packet_flits=16)
    assert artifact.packet_format_hash == GOLDEN_65EP_4VC_128
    assert artifact.endpoint_width_bits == 7
    assert artifact.vc_width_bits == 2
    assert artifact.payload_bits_per_flit == 110
    assert artifact.max_network_payload_bits == 1760


def test_golden_4ep_1vc_128():
    topology, attachment = _fabric(4, width_bits=128)
    artifact = derive_packet_format(topology, attachment, _vc(1),
                                    max_packet_flits=8)
    assert artifact.flit_width_bits == 128
    assert artifact.packet_format_hash == GOLDEN_4EP_1VC_128


# ── flit width authority ───────────────────────────────────────────────────

def test_uniform_64_and_128_channel_widths():
    for width in (64, 128):
        topology, attachment = _fabric(4, width_bits=width)
        artifact = derive_packet_format(topology, attachment, _vc(1),
                                        max_packet_flits=8)
        assert artifact.flit_width_bits == width


def test_heterogeneous_channel_widths_are_refused():
    topology, attachment = _fabric(4)
    channels = list(topology.channels)
    channels[0] = dataclasses.replace(channels[0], width_bits=32)
    mixed = TopologyArtifact(family=topology.family,
                             routers=topology.routers,
                             channels=tuple(channels))
    with pytest.raises(PacketFormatError, match="heterogeneous"):
        derive_packet_format(mixed, attachment, _vc(1), max_packet_flits=8)


def test_channel_less_topology_is_refused():
    topology = materialize_family(MaterializedFamily.MESH, endpoint_count=1)
    assert topology.channel_count == 0
    cr = CompileRequest(
        workload=Workload(model_family=ModelFamily.MOE, tp=1, pp=1, ep=1, dp=1),
        requirements=[], agents=[Agent(kind=AgentKind.COMPUTE_TILE, count=1)],
        dependencies=[],
        noc_config=NocConfig(topology_family=TopologyFamily.MESH))
    inventory = build_inventory(cr)
    attachment = derive_attachment(design=cr, inventory=inventory,
                                   topology=topology)
    with pytest.raises(PacketFormatError, match="no inter-router channels"):
        derive_packet_format(topology, attachment, _vc(1), max_packet_flits=8)


def test_changing_only_channel_width_changes_identity():
    narrow = _oracle_artifact()
    wide_topology, wide_attachment = _fabric(4, width_bits=128)
    wide = derive_packet_format(wide_topology, wide_attachment, _vc(1),
                                max_packet_flits=8)
    assert wide.flit_width_bits != narrow.flit_width_bits
    assert wide.packet_format_hash != narrow.packet_format_hash


def test_no_requested_width_override_exists():
    assert not hasattr(pf, "DEFAULT_FLIT_WIDTH_BITS")
    source = inspect.getsource(pf.derive_packet_format)
    assert "requested_flit_width" not in source


# ── endpoint and VC capacity boundaries ────────────────────────────────────

@pytest.mark.parametrize("count,width", [
    (1, 1), (2, 1), (4, 2), (64, 6), (65, 7), (72, 7),
])
def test_encoding_width_boundaries(count, width):
    assert encoding_width(count) == width


@pytest.mark.parametrize("count,width", [
    (2, 1), (4, 2), (64, 6), (65, 7), (72, 7),
])
def test_endpoint_width_from_real_attachments(count, width):
    topology, attachment = _fabric(count)
    artifact = derive_packet_format(topology, attachment, _vc(1),
                                    max_packet_flits=8)
    assert artifact.endpoint_width_bits == width
    assert artifact.endpoint_capacity >= count


@pytest.mark.parametrize("count,width", [
    (1, 1), (2, 1), (3, 2), (4, 2), (5, 3),
])
def test_vc_width_boundaries(count, width):
    assert encoding_width(count) == width
    topology, attachment = _fabric(4)
    artifact = derive_packet_format(topology, attachment, _vc(count),
                                    max_packet_flits=8)
    assert artifact.vc_width_bits == width
    assert artifact.vc_capacity >= count


def test_vc_eligibility_change_keeps_layout_but_moves_parent_identity():
    topology, attachment = _fabric(4)
    left_resource = VCResourceArtifact(
        vc_count=4, vc_ids=(0, 1, 2, 3),
        traffic_class_to_vcs=(("A", (0, 1)),),
        allowed_transitions=tuple((i, i) for i in range(4)))
    right_resource = VCResourceArtifact(
        vc_count=4, vc_ids=(0, 1, 2, 3),
        traffic_class_to_vcs=(("B", (2, 3)),),
        allowed_transitions=tuple((i, i) for i in range(4)))
    assert left_resource.artifact_hash != right_resource.artifact_hash
    left = derive_packet_format(topology, attachment, left_resource,
                                max_packet_flits=8)
    right = derive_packet_format(topology, attachment, right_resource,
                                 max_packet_flits=8)
    assert left.fields == right.fields
    assert left.vc_width_bits == right.vc_width_bits == 2
    assert left.vc_resource_hash != right.vc_resource_hash
    assert left.packet_format_hash != right.packet_format_hash


def test_payload_must_be_at_least_one_bit():
    topology, attachment = _fabric(4)
    channels = tuple(dataclasses.replace(c, width_bits=7)
                     for c in topology.channels)
    tiny = TopologyArtifact(family=topology.family, routers=topology.routers,
                            channels=channels)
    with pytest.raises(PacketFormatError, match="UNSUPPORTED"):
        derive_packet_format(tiny, attachment, _vc(1), max_packet_flits=8)


# ── packetization helper ───────────────────────────────────────────────────

def test_network_packet_count_for_bits():
    artifact = _oracle_artifact()
    assert artifact.network_packet_count_for_bits(1) == 1
    assert artifact.network_packet_count_for_bits(456) == 1
    assert artifact.network_packet_count_for_bits(457) == 2
    assert artifact.network_packet_count_for_bits(912) == 2
    assert artifact.network_packet_count_for_bits(913) == 3


@pytest.mark.parametrize("bad", [0, True, 1.5, "8"])
def test_network_packet_count_is_strict(bad):
    artifact = _oracle_artifact()
    with pytest.raises(PacketFormatError):
        artifact.network_packet_count_for_bits(bad)


# ── routing independence ───────────────────────────────────────────────────

def test_packet_format_is_independent_of_routing_semantics():
    topology, attachment = _fabric(4)
    before = derive_packet_format(topology, attachment, _vc(1),
                                  max_packet_flits=8)
    from veritx_dse.core.route_artifact import DOR_XY, RouteArtifact
    from veritx_dse.model.routing_policy import (
        CandidateMode, DeadlockProofObligation, DecisionScope, PathMode,
        RandomnessMode, RoutingPolicyDefinition, RoutingResourceRole,
        RoutingResourceRoleKind, RuntimeObservation, SelectionLocus,
    )
    from veritx_dse.model.routing_relation_materialize import (
        materialize_routing_relation,
    )
    RouteArtifact.from_topology(topology, name="d", routing_classes=(DOR_XY,))
    policy = RoutingPolicyDefinition(
        id="min_adapt_mesh", algorithm="per_hop_min_adaptive",
        algorithm_version=1, path_mode=PathMode.MINIMAL,
        decision_scope=DecisionScope.PER_HOP,
        candidate_mode=CandidateMode.CANDIDATE_SET,
        selection_locus=SelectionLocus.ROUTER_ALLOCATOR,
        randomness=RandomnessMode.NONE,
        deadlock_proof_obligation=DeadlockProofObligation.ESCAPE_SUBFUNCTION,
        runtime_observations=(RuntimeObservation.OUTPUT_CREDIT_OCCUPANCY,),
        resource_roles=(RoutingResourceRole(
            id="adaptive", kind=RoutingResourceRoleKind.ADAPTIVE),
            RoutingResourceRole(
                id="escape", kind=RoutingResourceRoleKind.ESCAPE)),
        allowed_role_transitions=(("adaptive", "adaptive"),
                                  ("adaptive", "escape"),
                                  ("escape", "escape")))
    materialize_routing_relation(topology, policy)
    after = derive_packet_format(topology, attachment, _vc(1),
                                 max_packet_flits=8)
    assert after.to_dict() == before.to_dict()


def test_min_adapt_vc_resource_is_compatible():
    topology, attachment = _fabric(4)
    artifact = derive_packet_format(topology, attachment, _min_adapt_resource(),
                                    max_packet_flits=8)
    assert artifact.vc_width_bits == 2
    assert artifact.payload_bits_per_flit == 56
    assert artifact.packet_format_hash == GOLDEN_MIN_ADAPT_RESOURCE


# ── strict serialization ───────────────────────────────────────────────────

def _valid_dict() -> dict:
    return _oracle_artifact().to_dict()


def test_round_trip_is_lossless():
    artifact = _oracle_artifact()
    restored = PacketFormatArtifact.from_dict(artifact.to_dict())
    assert restored.packet_format_hash == artifact.packet_format_hash
    assert restored.to_dict() == artifact.to_dict()
    assert restored == artifact


def test_unknown_fields_are_refused():
    d = _valid_dict()
    d["extra"] = 1
    with pytest.raises(PacketFormatError, match="unknown fields"):
        PacketFormatArtifact.from_dict(d)


@pytest.mark.parametrize("field", sorted(EXPECTED_FIELDS | {"type"}))
def test_missing_required_fields_are_refused(field):
    d = _valid_dict()
    d.pop(field)
    with pytest.raises(PacketFormatError):
        PacketFormatArtifact.from_dict(d)


@pytest.mark.parametrize("bad", [None, "srota/VCResourceArtifact", 7])
def test_type_tag_is_strict(bad):
    d = _valid_dict()
    if bad is None:
        d.pop("type")
    else:
        d["type"] = bad
    with pytest.raises(PacketFormatError, match="type"):
        PacketFormatArtifact.from_dict(d)


@pytest.mark.parametrize("bad", [1, 3, True, "2", 2.0])
def test_schema_version_is_strict(bad):
    d = _valid_dict()
    d["schema_version"] = bad
    with pytest.raises(PacketFormatError, match="schema_version"):
        PacketFormatArtifact.from_dict(d)


def test_parent_hash_shapes_are_strict():
    for field in ("topology_hash", "attachment_hash", "vc_resource_hash"):
        d = _valid_dict()
        d[field] = 7
        with pytest.raises(PacketFormatError, match=field):
            PacketFormatArtifact.from_dict(d)
        d = _valid_dict()
        d[field] = ""
        with pytest.raises(PacketFormatError, match=field):
            PacketFormatArtifact.from_dict(d)


@pytest.mark.parametrize("bad", [True, 1.5, "64", 0])
def test_flit_width_is_strict(bad):
    d = _valid_dict()
    d["flit_width_bits"] = bad
    with pytest.raises(PacketFormatError):
        PacketFormatArtifact.from_dict(d)


@pytest.mark.parametrize("bad", [True, 1.5, "8", 0])
def test_max_packet_flits_is_strict(bad):
    d = _valid_dict()
    d["max_packet_flits"] = bad
    with pytest.raises(PacketFormatError):
        PacketFormatArtifact.from_dict(d)


def test_persisted_fields_must_be_sorted():
    d = _valid_dict()
    d["fields"] = list(reversed(d["fields"]))
    with pytest.raises(PacketFormatError, match="sorted by lsb"):
        PacketFormatArtifact.from_dict(d)


def test_unknown_role_and_mutability_are_refused():
    d = _valid_dict()
    d["fields"][0]["role"] = "checksum"
    with pytest.raises(PacketFormatError, match="unknown flit field role"):
        PacketFormatArtifact.from_dict(d)
    d = _valid_dict()
    d["fields"][0]["mutability"] = "mutable"
    with pytest.raises(PacketFormatError, match="unknown flit field mutability"):
        PacketFormatArtifact.from_dict(d)


def test_field_hash_is_required_and_verified():
    d = _valid_dict()
    d.pop("packet_format_hash")
    with pytest.raises(PacketFormatError, match="missing required"):
        PacketFormatArtifact.from_dict(d)
    d = _valid_dict()
    d["packet_format_hash"] = ""
    with pytest.raises(PacketFormatError, match="packet_format_hash"):
        PacketFormatArtifact.from_dict(d)
    d = _valid_dict()
    d["packet_format_hash"] = "0" * 64
    with pytest.raises(PacketFormatError, match="packet_format_hash"):
        PacketFormatArtifact.from_dict(d)


# ── field descriptor strictness ────────────────────────────────────────────

def test_field_descriptor_strictness():
    with pytest.raises(PacketFormatError, match="must be named"):
        FlitField("vc", 63, 1, FlitFieldRole.VC_ID,
                  FieldMutability.HOP_LOCAL)
    with pytest.raises(PacketFormatError, match="requires mutability"):
        FlitField("vc_id", 63, 1, FlitFieldRole.VC_ID,
                  FieldMutability.PAYLOAD)
    with pytest.raises(PacketFormatError, match="must be >= 1"):
        FlitField("payload", 0, 0, FlitFieldRole.PAYLOAD,
                  FieldMutability.PAYLOAD)
    with pytest.raises(PacketFormatError, match=">= 0"):
        FlitField("payload", -1, 1, FlitFieldRole.PAYLOAD,
                  FieldMutability.PAYLOAD)


def test_layout_gap_overlap_and_coverage_are_refused():
    good = canonical_field_layout(endpoint_width=2, vc_width=1,
                                  payload_width=57)
    with pytest.raises(PacketFormatError, match="not contiguous"):
        PacketFormatArtifact(
            topology_hash="a" * 64, attachment_hash="b" * 64,
            vc_resource_hash="c" * 64, flit_width_bits=64,
            max_packet_flits=8,
            fields=(good[0], dataclasses.replace(good[1], lsb=58),
                    good[2], good[3], good[4]))
    with pytest.raises(PacketFormatError, match="not contiguous"):
        PacketFormatArtifact(
            topology_hash="a" * 64, attachment_hash="b" * 64,
            vc_resource_hash="c" * 64, flit_width_bits=64,
            max_packet_flits=8,
            fields=(good[0], dataclasses.replace(good[1], lsb=56),
                    good[2], good[3], good[4]))
    with pytest.raises(PacketFormatError, match="cover"):
        PacketFormatArtifact(
            topology_hash="a" * 64, attachment_hash="b" * 64,
            vc_resource_hash="c" * 64, flit_width_bits=64,
            max_packet_flits=8,
            fields=(good[0], good[1], good[2], good[3],
                    dataclasses.replace(good[4], width=2)))


def test_duplicate_roles_and_names_are_refused():
    good = canonical_field_layout(endpoint_width=2, vc_width=1,
                                  payload_width=57)
    with pytest.raises(PacketFormatError, match="duplicate roles"):
        PacketFormatArtifact(
            topology_hash="a" * 64, attachment_hash="b" * 64,
            vc_resource_hash="c" * 64, flit_width_bits=64,
            max_packet_flits=8, fields=(good[0], good[0], good[2], good[3],
                                        good[4]))
    with pytest.raises(PacketFormatError, match="missing roles"):
        PacketFormatArtifact(
            topology_hash="a" * 64, attachment_hash="b" * 64,
            vc_resource_hash="c" * 64, flit_width_bits=64,
            max_packet_flits=8, fields=(good[0], good[1]))


def test_canonical_field_order_is_enforced():
    good = canonical_field_layout(endpoint_width=2, vc_width=1,
                                  payload_width=57)
    # source placed at lsb 0 forces a non-canonical role order in lsb space
    reordered = (dataclasses.replace(good[1], lsb=0),
                 dataclasses.replace(good[0], lsb=2),
                 good[2], good[3], good[4])
    with pytest.raises(PacketFormatError, match="field order"):
        PacketFormatArtifact(
            topology_hash="a" * 64, attachment_hash="b" * 64,
            vc_resource_hash="c" * 64, flit_width_bits=64,
            max_packet_flits=8, fields=reordered)


def test_construction_order_does_not_move_identity():
    artifact = _oracle_artifact()
    reordered = PacketFormatArtifact(
        topology_hash=artifact.topology_hash,
        attachment_hash=artifact.attachment_hash,
        vc_resource_hash=artifact.vc_resource_hash,
        flit_width_bits=artifact.flit_width_bits,
        max_packet_flits=artifact.max_packet_flits,
        fields=tuple(reversed(artifact.fields)))
    assert reordered.packet_format_hash == artifact.packet_format_hash
    assert reordered.to_dict() == artifact.to_dict()


# ── parent validation / tamper gates ───────────────────────────────────────

def test_parent_recomputation_refuses_forged_layout():
    topology, attachment = _fabric(4)
    resource = _vc(1)
    forged = PacketFormatArtifact(
        topology_hash=topology.topology_hash(),
        attachment_hash=attachment.attachment_hash(),
        vc_resource_hash=resource.artifact_hash,
        flit_width_bits=64, max_packet_flits=8,
        fields=canonical_field_layout(endpoint_width=3, vc_width=1,
                                      payload_width=55))
    # self-consistent: from_dict accepts it...
    loaded = PacketFormatArtifact.from_dict(forged.to_dict())
    assert loaded.packet_format_hash == forged.packet_format_hash
    # ...but parent recomputation refuses it
    with pytest.raises(PacketFormatError, match="canonical"):
        loaded.validate_against(topology, attachment, resource)


def test_parent_recomputation_refuses_forged_flit_width():
    topology, attachment = _fabric(4)
    resource = _vc(1)
    forged = PacketFormatArtifact(
        topology_hash=topology.topology_hash(),
        attachment_hash=attachment.attachment_hash(),
        vc_resource_hash=resource.artifact_hash,
        flit_width_bits=63, max_packet_flits=8,
        fields=canonical_field_layout(endpoint_width=2, vc_width=1,
                                      payload_width=56))
    with pytest.raises(PacketFormatError, match="channel width"):
        forged.validate_against(topology, attachment, resource)


def test_wrong_parents_are_refused():
    topology, attachment = _fabric(4)
    artifact = _oracle_artifact()
    other_topology, _other = _fabric(4, width_bits=128)
    with pytest.raises(PacketFormatError, match="topology_hash"):
        artifact.validate_against(other_topology, attachment, _vc(1))
    endpoints = list(attachment.endpoints)
    endpoints[0], endpoints[1] = (
        dataclasses.replace(endpoints[0], router_id=endpoints[1].router_id,
                            port_id=endpoints[1].port_id),
        dataclasses.replace(endpoints[1], router_id=endpoints[0].router_id,
                            port_id=endpoints[0].port_id))
    other_attachment = AgentAttachmentArtifact(
        topology_hash=attachment.topology_hash, endpoints=tuple(endpoints))
    assert other_attachment.attachment_hash() != attachment.attachment_hash()
    with pytest.raises(PacketFormatError, match="attachment_hash"):
        artifact.validate_against(topology, other_attachment, _vc(1))
    with pytest.raises(PacketFormatError, match="vc_resource_hash"):
        artifact.validate_against(topology, attachment, _vc(4))


def test_attachment_illegal_for_topology_is_refused():
    topology, attachment = _fabric(4)
    ring = materialize_family(MaterializedFamily.RING, endpoint_count=2)
    object.__setattr__(attachment, "topology_hash", ring.topology_hash())
    forged = PacketFormatArtifact(
        topology_hash=ring.topology_hash(),
        attachment_hash=attachment.attachment_hash(),
        vc_resource_hash=_vc(1).artifact_hash,
        flit_width_bits=64, max_packet_flits=8,
        fields=canonical_field_layout(endpoint_width=2, vc_width=1,
                                      payload_width=57))
    with pytest.raises(PacketFormatError, match="not legal for the topology"):
        forged.validate_against(ring, attachment, _vc(1))


def test_non_artifact_parents_are_refused():
    artifact = _oracle_artifact()
    topology, attachment = _fabric(4)
    with pytest.raises(PacketFormatError, match="TopologyArtifact"):
        artifact.validate_against(object(), attachment, _vc(1))
    with pytest.raises(PacketFormatError, match="AgentAttachmentArtifact"):
        artifact.validate_against(topology, object(), _vc(1))
    with pytest.raises(PacketFormatError, match="VCResourceArtifact"):
        artifact.validate_against(topology, attachment, object())


def test_builder_requires_an_explicit_packet_bound():
    topology, attachment = _fabric(4)
    with pytest.raises(TypeError):
        derive_packet_format(topology, attachment, _vc(1))
    with pytest.raises(PacketFormatError, match="max_packet_flits"):
        derive_packet_format(topology, attachment, _vc(1),
                             max_packet_flits=0)


# ── immutability / scope sentinels ─────────────────────────────────────────

def test_artifact_is_frozen_and_tuple_backed():
    artifact = _oracle_artifact()
    with pytest.raises(dataclasses.FrozenInstanceError):
        artifact.flit_width_bits = 128
    assert isinstance(artifact.fields, tuple)
    with pytest.raises(TypeError):
        artifact.fields[0] = artifact.fields[1]


def test_to_dict_returns_fresh_data():
    artifact = _oracle_artifact()
    first = artifact.to_dict()
    first["fields"][0]["width"] = 1
    first["fields"].clear()
    second = artifact.to_dict()
    assert len(second["fields"]) == 5
    assert second["fields"][0]["width"] == 57
    assert artifact.packet_format_hash == GOLDEN_4EP_1VC_64


def test_schema_has_no_routing_or_backend_fields():
    names = {f.name for f in dataclasses.fields(PacketFormatArtifact)}
    assert names == EXPECTED_FIELDS
    blob = str(_oracle_artifact().to_dict()).lower()
    for token in FORBIDDEN_TOKENS:
        assert token not in blob


def test_module_imports_only_allowed_layers():
    tree = ast.parse(inspect.getsource(pf))
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
        "veritx_dse.model.attachment",
        "veritx_dse.model.topology_artifact",
        "veritx_dse.model.vc_resource",
    }
    forbidden = ("route_artifact", "resolved_route", "vc_assignment",
                 "routing_policy", "routing_relation", "routing_resource",
                 "channel_vc_cdg", "protocol_vc", "adaptive_escape",
                 "booksim", "astra", "backend", "cli")
    for name in imported:
        assert not any(token in name.lower() for token in forbidden), name
