"""AddressDecodeArtifact v3 tests — canonical NI address-decode semantics.

Parent is ``AgentAttachmentArtifact`` only. Historical schema v2 is used as
a semantic oracle; v3 hashes are new because the identity implementation
and parent identities changed.
"""
from __future__ import annotations

import ast
import dataclasses
import inspect

import pytest

from veritx_dse.model import address_decode as ad
from veritx_dse.model.address_decode import (
    ADDRESS_DOMAIN_BITS, ADDRESS_DOMAIN_SIZE, AddressDecodeArtifact,
    AddressDecodeEntry, AddressDecodeError, AddressTransform,
    UnmatchedAddressPolicy, derive_address_decode,
)
from veritx_dse.model.attachment import derive_attachment
from veritx_dse.model.compile_model import (
    AddressMap, AddressRange, Agent, AgentKind, CompileRequest, ModelFamily,
    NocConfig, TopologyFamily, Workload,
)
from veritx_dse.model.packet_format import FlitFieldRole, derive_packet_format
from veritx_dse.model.placement import build_inventory
from veritx_dse.model.topology_artifact import materialize_topology
from veritx_dse.model.vc_resource import VCResourceArtifact

GOLDEN_EMPTY = (
    "ca8c1dff05618ffd1a5b8602b398060659b51facda951e959c5ccbf78a364286")
GOLDEN_ONE_RANGE = (
    "a3b11dc2255cb4433e72d14add5ddcd7badbb156da97f7efb9d186800f528a72")
GOLDEN_TWO_RANGES = (
    "f8958edd61bec860463af029e1f0d73fb4ca1710c48bb59f683fd81120591270")

SCHEMA_FIELDS = {
    "attachment_hash", "entries", "address_transform",
    "unmatched_address_policy", "schema_version", "address_decode_hash",
}
SERIALIZED_KEYS = SCHEMA_FIELDS | {"type"}
IDENTITY_KEYS = {
    "type", "schema_version", "attachment_hash", "address_transform",
    "unmatched_address_policy", "entries",
}
FORBIDDEN_TOKENS = (
    "design_hash", "mapping_hash", "topology_hash", "route_hash",
    "policy_hash", "vc_resource_hash", "packet_format_hash",
    "router_behavior_hash", "rank", "router_id", "channel_id", "backend",
    "seed", "timestamp", "verdict", "booksim", "astra",
)


# ── fixtures ───────────────────────────────────────────────────────────────

def _compute(count: int, **kw) -> Agent:
    return Agent(kind=AgentKind.COMPUTE_TILE, count=count, **kw)


def _hbm(count: int, **kw) -> Agent:
    return Agent(kind=AgentKind.HBM_CONTROLLER, count=count, **kw)


def _range(name, base, size, group=1) -> AddressRange:
    return AddressRange(name=name, base=base, size=size,
                        target_agent_idx=group)


def _map(*ranges) -> AddressMap:
    return AddressMap(ranges=tuple(ranges))


def _build(agents, ranges=()):
    design = CompileRequest(
        workload=Workload(model_family=ModelFamily.MOE, tp=1, pp=1, ep=1, dp=1),
        requirements=[], agents=tuple(agents), dependencies=[],
        noc_config=NocConfig(topology_family=TopologyFamily.MESH),
        address_map=AddressMap(ranges=tuple(ranges)))
    inventory = build_inventory(design)
    topology = materialize_topology(inventory, design)
    attachment = derive_attachment(design=design, inventory=inventory,
                                   topology=topology)
    return design, attachment, topology


def _artifact(attachment_hash, entries, *,
              transform=AddressTransform.IDENTITY,
              policy=UnmatchedAddressPolicy.ERROR) -> AddressDecodeArtifact:
    return AddressDecodeArtifact(
        attachment_hash=attachment_hash, entries=tuple(entries),
        address_transform=transform, unmatched_address_policy=policy)


def _decode(design, attachment) -> AddressDecodeArtifact:
    return derive_address_decode(design=design, attachment=attachment)


def _one_range():
    design, attachment, _topology = _build(
        [_compute(4), _hbm(1)], [_range("HBM0", 0x0, 0x1000, 1)])
    return design, attachment, _decode(design, attachment)


def _two_ranges():
    design, attachment, _topology = _build(
        [_compute(1), _hbm(1)],
        [_range("A", 0x0, 0x100, 0), _range("B", 0x1000, 0x100, 1)])
    return design, attachment, _decode(design, attachment)


def _hbm_endpoint(attachment):
    return next(endpoint for endpoint in attachment.endpoints
                if endpoint.agent.group_index == 1)


# ── constants and vocabulary ───────────────────────────────────────────────

def test_address_domain_constants():
    assert ADDRESS_DOMAIN_BITS == 64
    assert ADDRESS_DOMAIN_SIZE == 1 << 64


def test_vocabulary_is_exactly_pinned():
    assert [(m.name, m.value) for m in AddressTransform] == [
        ("IDENTITY", "IDENTITY")]
    assert [(m.name, m.value) for m in UnmatchedAddressPolicy] == [
        ("ERROR", "ERROR")]


# ── golden pins ────────────────────────────────────────────────────────────

def test_golden_empty_address_map():
    design, attachment, _topology = _build([_compute(4)])
    artifact = _decode(design, attachment)
    assert artifact.entries == ()
    assert artifact.address_transform is AddressTransform.IDENTITY
    assert artifact.unmatched_address_policy is UnmatchedAddressPolicy.ERROR
    assert artifact.address_decode_hash == GOLDEN_EMPTY


def test_golden_one_range():
    _design, attachment, artifact = _one_range()
    assert artifact.address_decode_hash == GOLDEN_ONE_RANGE
    entry = artifact.entries[0]
    endpoint = _hbm_endpoint(attachment)
    assert entry.name == "HBM0"
    assert entry.base == 0
    assert entry.size == 0x1000
    assert entry.target_agent_group == 1
    assert entry.target_endpoint_id == endpoint.endpoint_id
    assert endpoint.interface.address_width_bits == 64


def test_golden_two_ranges():
    _design, attachment, artifact = _two_ranges()
    assert artifact.address_decode_hash == GOLDEN_TWO_RANGES
    assert [entry.target_endpoint_id for entry in artifact.entries] == [0, 1]
    assert [entry.target_agent_group for entry in artifact.entries] == [0, 1]


# ── empty address map ──────────────────────────────────────────────────────

def test_empty_map_means_every_address_is_unmatched():
    design, attachment, _topology = _build([_compute(4)])
    artifact = _decode(design, attachment)
    assert artifact.entries == ()
    assert artifact.address_transform is AddressTransform.IDENTITY
    assert artifact.unmatched_address_policy is UnmatchedAddressPolicy.ERROR
    loaded = AddressDecodeArtifact.from_dict(artifact.to_dict())
    assert loaded.address_decode_hash == artifact.address_decode_hash
    # no fabricated default memory target
    assert loaded.entries == ()


# ── label / design-identity separation ─────────────────────────────────────

def test_label_does_not_move_hardware_identity():
    design_a, attachment_a, _topology_a = _build(
        [_compute(4), _hbm(1)], [_range("HBM0", 0x0, 0x1000, 1)])
    design_b, attachment_b, _topology_b = _build(
        [_compute(4), _hbm(1)], [_range("weights", 0x0, 0x1000, 1)])
    # range names are design intent...
    assert design_a.design_hash() != design_b.design_hash()
    # ...but not NI hardware identity
    assert attachment_a.attachment_hash() == attachment_b.attachment_hash()
    decode_a = _decode(design_a, attachment_a)
    decode_b = _decode(design_b, attachment_b)
    assert decode_a.address_decode_hash == decode_b.address_decode_hash
    # semantic comparison ignores names across revisions
    decode_b.validate_against(design_a.address_map, attachment_a)


def test_entry_name_round_trips():
    _design, _attachment, artifact = _one_range()
    persisted = artifact.to_dict()
    assert persisted["entries"][0]["name"] == "HBM0"
    loaded = AddressDecodeArtifact.from_dict(persisted)
    assert loaded.entries == artifact.entries
    assert loaded.entries[0].name == "HBM0"


def test_rename_does_not_move_hash():
    _design, attachment, artifact = _one_range()
    renamed = dataclasses.replace(artifact.entries[0], name="dram_bank")
    twin = _artifact(attachment.attachment_hash(), (renamed,))
    assert twin.address_decode_hash == artifact.address_decode_hash
    assert twin.entries[0].name == "dram_bank"


def test_name_tamper_is_not_a_hash_failure():
    _design, _attachment, artifact = _one_range()
    persisted = artifact.to_dict()
    persisted["entries"][0]["name"] = "renamed"
    loaded = AddressDecodeArtifact.from_dict(persisted)
    assert loaded.address_decode_hash == artifact.address_decode_hash
    assert loaded.entries[0].name == "renamed"


# ── semantic identity mutations ────────────────────────────────────────────

@pytest.mark.parametrize("field,value", [
    ("base", 0x100),
    ("size", 0x200),
    ("target_agent_group", 1),
    ("target_endpoint_id", 1),
])
def test_single_semantic_mutation_moves_identity(field, value):
    _design, attachment, artifact = _two_ranges()
    mutated = dataclasses.replace(artifact.entries[0], **{field: value})
    twin = _artifact(attachment.attachment_hash(),
                     (mutated, artifact.entries[1]))
    assert twin.address_decode_hash != artifact.address_decode_hash


def test_target_change_moves_identity():
    _design, attachment, artifact = _one_range()
    entry = artifact.entries[0]
    twin = _artifact(attachment.attachment_hash(), (
        dataclasses.replace(entry, target_endpoint_id=entry.target_endpoint_id
                            + 1),))
    assert twin.entries[0].base == entry.base
    assert twin.entries[0].size == entry.size
    assert twin.address_decode_hash != artifact.address_decode_hash


def test_attachment_parent_change_moves_identity():
    design, attachment, artifact = _one_range()
    _cr2, chi_attachment, _topo2 = _build(
        [_compute(4), _hbm(1, protocol="CHI")],
        [_range("HBM0", 0x0, 0x1000, 1)])
    assert chi_attachment.attachment_hash() != attachment.attachment_hash()
    twin = _artifact(chi_attachment.attachment_hash(), artifact.entries)
    assert twin.address_decode_hash != artifact.address_decode_hash
    assert design.address_map.ranges[0].base == 0


# ── attachment validation ──────────────────────────────────────────────────

def test_singleton_group_resolves_to_exact_endpoint():
    design, attachment, artifact = _one_range()
    entry = artifact.entries[0]
    endpoint = next(endpoint for endpoint in attachment.endpoints
                    if endpoint.endpoint_id == entry.target_endpoint_id)
    assert entry.target_agent_group == 1
    assert endpoint.agent.group_index == 1
    artifact.validate_against_attachment(attachment)
    artifact.validate_against(design.address_map, attachment)


def test_validate_against_attachment_needs_no_design():
    _design, attachment, artifact = _one_range()
    artifact.validate_against_attachment(attachment)
    _cr2, other, _topo2 = _build([_compute(4), _hbm(1, protocol="CHI")],
                                 [_range("HBM0", 0x0, 0x1000, 1)])
    with pytest.raises(AddressDecodeError, match="attachment_hash"):
        artifact.validate_against_attachment(other)


def test_non_artifact_attachment_is_refused():
    _design, _attachment, artifact = _one_range()
    with pytest.raises(AddressDecodeError, match="AgentAttachmentArtifact"):
        artifact.validate_against_attachment(object())


def test_nonexistent_endpoint_is_refused():
    _design, attachment, artifact = _one_range()
    entry = dataclasses.replace(artifact.entries[0], target_endpoint_id=99)
    bad = _artifact(attachment.attachment_hash(), (entry,))
    with pytest.raises(AddressDecodeError, match="not in the attachment"):
        bad.validate_against_attachment(attachment)


def test_group_endpoint_disagreement_is_refused():
    _design, attachment, artifact = _one_range()
    hbm_endpoint = _hbm_endpoint(attachment)
    entry = dataclasses.replace(artifact.entries[0], target_agent_group=0,
                                target_endpoint_id=hbm_endpoint.endpoint_id)
    bad = _artifact(attachment.attachment_hash(), (entry,))
    with pytest.raises(AddressDecodeError, match="belongs to group"):
        bad.validate_against_attachment(attachment)


def test_map_targeting_group_with_no_endpoint_is_refused():
    _design, attachment, artifact = _one_range()
    with pytest.raises(AddressDecodeError, match="no attached endpoint"):
        artifact.validate_against(_map(_range("Y", 0, 0x100, 7)), attachment)


def test_non_address_map_is_refused():
    _design, attachment, artifact = _one_range()
    with pytest.raises(AddressDecodeError, match="AddressMap"):
        artifact.validate_against(object(), attachment)


# ── multi-instance refusal ─────────────────────────────────────────────────

def test_derive_refuses_multi_instance_target():
    design, attachment, _topology = _build(
        [_compute(4), _hbm(2)], [_range("HBM0", 0x0, 0x100, 1)])
    with pytest.raises(AddressDecodeError, match="UNSUPPORTED"):
        _decode(design, attachment)


def test_validation_refuses_multi_instance_target():
    _design, attachment, _topology = _build([_compute(4), _hbm(2)])
    first_hbm = _hbm_endpoint(attachment)
    bad = _artifact(attachment.attachment_hash(), (
        AddressDecodeEntry("X", 0, 0x100, 1, first_hbm.endpoint_id),))
    with pytest.raises(AddressDecodeError, match="UNSUPPORTED"):
        bad.validate_against_attachment(attachment)


# ── address width boundaries ───────────────────────────────────────────────

def test_exact_interface_fit_passes():
    design, attachment, _topology = _build(
        [_compute(4), _hbm(1, addr_width=32)],
        [_range("HBM0", 0xFFFF_0000, 0x1_0000, 1)])
    artifact = _decode(design, attachment)
    entry = artifact.entries[0]
    assert entry.base + entry.size == 1 << 32
    assert _hbm_endpoint(attachment).interface.address_width_bits == 32


def test_interface_overflow_by_one_fails():
    design, attachment, _topology = _build(
        [_compute(4), _hbm(1, addr_width=32)],
        [_range("HBM0", 0xFFFF_0000, 0x1_0001, 1)])
    with pytest.raises(AddressDecodeError, match="32-bit address"):
        _decode(design, attachment)


def test_global_valid_but_interface_invalid_fails():
    design, attachment, _topology = _build(
        [_compute(4), _hbm(1, addr_width=32)],
        [_range("HBM0", 0x1_0000_0000, 0x100, 1)])
    assert 0x1_0000_0000 + 0x100 <= ADDRESS_DOMAIN_SIZE
    with pytest.raises(AddressDecodeError, match="32-bit address"):
        _decode(design, attachment)


def test_global_domain_overflow_is_refused():
    with pytest.raises(AddressDecodeError, match="overflow"):
        AddressDecodeEntry("A", ADDRESS_DOMAIN_SIZE - 0x10, 0x20, 1, 0)


# ── overlap / order / duplicates ───────────────────────────────────────────

def test_adjacent_ranges_are_valid():
    artifact = _artifact("a" * 64, (
        AddressDecodeEntry("A", 0x0, 0x100, 0, 0),
        AddressDecodeEntry("B", 0x100, 0x100, 1, 1)))
    assert len(artifact.entries) == 2


def test_overlapping_ranges_are_refused():
    with pytest.raises(AddressDecodeError, match="overlap"):
        _artifact("a" * 64, (
            AddressDecodeEntry("A", 0x0, 0x1000, 1, 0),
            AddressDecodeEntry("B", 0x800, 0x1000, 1, 1)))


def test_duplicate_semantic_range_is_refused():
    with pytest.raises(AddressDecodeError, match="duplicate semantic"):
        _artifact("a" * 64, (
            AddressDecodeEntry("A", 0x0, 0x100, 1, 0),
            AddressDecodeEntry("B", 0x0, 0x100, 1, 0)))


def test_repeated_presentation_name_is_not_a_collision():
    artifact = _artifact("a" * 64, (
        AddressDecodeEntry("MEM", 0x0, 0x100, 0, 0),
        AddressDecodeEntry("MEM", 0x100, 0x100, 1, 1)))
    assert [entry.name for entry in artifact.entries] == ["MEM", "MEM"]


def test_unsorted_entries_are_refused():
    with pytest.raises(AddressDecodeError, match="canonical semantic order"):
        _artifact("a" * 64, (
            AddressDecodeEntry("A", 0x1000, 0x100, 1, 1),
            AddressDecodeEntry("B", 0x0, 0x100, 0, 0)))


def test_construction_is_independent_of_source_range_order():
    forward_design, forward_attachment, _topo = _build(
        [_compute(1), _hbm(1)],
        [_range("A", 0x0, 0x100, 0), _range("B", 0x1000, 0x100, 1)])
    reverse_design, reverse_attachment, _topo2 = _build(
        [_compute(1), _hbm(1)],
        [_range("B", 0x1000, 0x100, 1), _range("A", 0x0, 0x100, 0)])
    forward = _decode(forward_design, forward_attachment)
    reverse = _decode(reverse_design, reverse_attachment)
    assert forward.address_decode_hash == reverse.address_decode_hash
    assert forward_design.design_hash() == reverse_design.design_hash()


def test_noncanonical_persisted_order_is_refused():
    _design, _attachment, artifact = _two_ranges()
    persisted = artifact.to_dict()
    persisted["entries"] = list(reversed(persisted["entries"]))
    with pytest.raises(AddressDecodeError, match="canonical semantic order"):
        AddressDecodeArtifact.from_dict(persisted)


# ── tamper gate ────────────────────────────────────────────────────────────

def test_forged_self_consistent_table_fails_design_validation():
    design, attachment, artifact = _one_range()
    endpoint_id = artifact.entries[0].target_endpoint_id
    forged = _artifact(attachment.attachment_hash(), (
        AddressDecodeEntry("HBM0", 0x2000, 0x1000, 1, endpoint_id),))
    loaded = AddressDecodeArtifact.from_dict(forged.to_dict())
    assert loaded.address_decode_hash == forged.address_decode_hash
    loaded.validate_against_attachment(attachment)
    with pytest.raises(AddressDecodeError, match="do not match"):
        loaded.validate_against(design.address_map, attachment)


# ── strict construction ────────────────────────────────────────────────────

def test_entry_construction_is_strict():
    with pytest.raises(AddressDecodeError, match="non-empty string"):
        AddressDecodeEntry("", 0, 1, 0, 0)
    for bad in (True, 1.5, "0", None):
        with pytest.raises(AddressDecodeError, match="exact int"):
            AddressDecodeEntry("A", bad, 1, 0, 0)
    with pytest.raises(AddressDecodeError, match=">= 0"):
        AddressDecodeEntry("A", -1, 1, 0, 0)
    with pytest.raises(AddressDecodeError, match=">= 1"):
        AddressDecodeEntry("A", 0, 0, 0, 0)
    for bad in (True, 1.5, "0"):
        with pytest.raises(AddressDecodeError, match="exact int"):
            AddressDecodeEntry("A", 0, 1, bad, 0)
        with pytest.raises(AddressDecodeError, match="exact int"):
            AddressDecodeEntry("A", 0, 1, 0, bad)


def test_entries_must_be_a_tuple():
    with pytest.raises(AddressDecodeError, match="must be a tuple"):
        AddressDecodeArtifact(
            attachment_hash="a" * 64,
            entries=[AddressDecodeEntry("A", 0, 1, 0, 0)],
            address_transform=AddressTransform.IDENTITY,
            unmatched_address_policy=UnmatchedAddressPolicy.ERROR)


def test_attachment_hash_shape_is_strict():
    for bad in ("", "a" * 63, "A" * 64, "g" * 64, 7, None):
        with pytest.raises(AddressDecodeError, match="attachment_hash"):
            _artifact(bad, ())


def test_transform_and_policy_must_be_enums():
    with pytest.raises(AddressDecodeError, match="AddressTransform"):
        _artifact("a" * 64, (), transform="IDENTITY")
    with pytest.raises(AddressDecodeError, match="UnmatchedAddressPolicy"):
        _artifact("a" * 64, (), policy="ERROR")


def test_schema_version_must_be_exactly_3():
    for bad in (1, 2, 4, "3", True):
        with pytest.raises(AddressDecodeError, match="schema_version"):
            AddressDecodeArtifact(
                attachment_hash="a" * 64, entries=(),
                address_transform=AddressTransform.IDENTITY,
                unmatched_address_policy=UnmatchedAddressPolicy.ERROR,
                schema_version=bad)


def test_constructor_hash_mismatch_is_refused():
    _design, _attachment, artifact = _one_range()
    with pytest.raises(AddressDecodeError, match="does not match content"):
        dataclasses.replace(artifact, address_decode_hash="0" * 64)


# ── strict serialization ───────────────────────────────────────────────────

def test_roundtrip_is_lossless():
    _design, _attachment, artifact = _two_ranges()
    loaded = AddressDecodeArtifact.from_dict(artifact.to_dict())
    assert loaded == artifact
    assert loaded.to_dict() == artifact.to_dict()


def test_serialized_keys_are_exactly_the_schema():
    _design, _attachment, artifact = _one_range()
    assert set(artifact.identity_dict()) == IDENTITY_KEYS
    assert set(artifact.to_dict()) == SERIALIZED_KEYS
    assert {field.name for field in dataclasses.fields(AddressDecodeArtifact)} \
        == SCHEMA_FIELDS
    assert "name" not in artifact.identity_dict()["entries"][0]


def test_unknown_fields_are_refused():
    _design, _attachment, artifact = _one_range()
    persisted = artifact.to_dict()
    persisted["extra"] = 1
    with pytest.raises(AddressDecodeError, match="unknown fields"):
        AddressDecodeArtifact.from_dict(persisted)


@pytest.mark.parametrize("field", sorted(SCHEMA_FIELDS))
def test_missing_fields_are_refused(field):
    _design, _attachment, artifact = _one_range()
    persisted = artifact.to_dict()
    persisted.pop(field)
    with pytest.raises(AddressDecodeError):
        AddressDecodeArtifact.from_dict(persisted)


@pytest.mark.parametrize("bad", [None, "srota/AddressDecode", 7])
def test_type_tag_is_strict(bad):
    _design, _attachment, artifact = _one_range()
    persisted = artifact.to_dict()
    if bad is None:
        persisted.pop("type")
    else:
        persisted["type"] = bad
    with pytest.raises(AddressDecodeError, match="type"):
        AddressDecodeArtifact.from_dict(persisted)


def test_schema_v1_is_refused_with_useful_message():
    _design, _attachment, artifact = _one_range()
    persisted = artifact.to_dict()
    persisted["schema_version"] = 1
    with pytest.raises(AddressDecodeError,
                       match="schema v1|silent migration|Rebuild"):
        AddressDecodeArtifact.from_dict(persisted)


def test_schema_v2_is_refused_with_useful_message():
    _design, _attachment, artifact = _one_range()
    persisted = artifact.to_dict()
    persisted["schema_version"] = 2
    persisted["type"] = "srota/AddressDecode"
    with pytest.raises(AddressDecodeError,
                       match="schema v2|silent migration|Rebuild"):
        AddressDecodeArtifact.from_dict(persisted)


@pytest.mark.parametrize("field,value,match", [
    ("address_transform", "SUBTRACT_BASE", "unknown address transform"),
    ("address_transform", "IDENTITY2", "unknown address transform"),
    ("unmatched_address_policy", "DROP", "unknown unmatched address policy"),
    ("unmatched_address_policy", "WRAP", "unknown unmatched address policy"),
])
def test_wrong_transform_or_policy_is_refused(field, value, match):
    _design, _attachment, artifact = _one_range()
    persisted = artifact.to_dict()
    persisted[field] = value
    with pytest.raises(AddressDecodeError, match=match):
        AddressDecodeArtifact.from_dict(persisted)


def test_entries_must_be_a_json_list():
    _design, _attachment, artifact = _one_range()
    persisted = artifact.to_dict()
    persisted["entries"] = {"not": "a list"}
    with pytest.raises(AddressDecodeError, match="JSON list"):
        AddressDecodeArtifact.from_dict(persisted)


def test_malformed_entry_shape_is_refused():
    _design, _attachment, artifact = _one_range()
    persisted = artifact.to_dict()
    persisted["entries"][0]["extra"] = 1
    with pytest.raises(AddressDecodeError, match="unknown fields"):
        AddressDecodeArtifact.from_dict(persisted)
    persisted = artifact.to_dict()
    persisted["entries"][0].pop("base")
    with pytest.raises(AddressDecodeError, match="missing required"):
        AddressDecodeArtifact.from_dict(persisted)


@pytest.mark.parametrize("field", ["base", "size", "target_agent_group",
                                   "target_endpoint_id"])
@pytest.mark.parametrize("bad", [True, 1.5, "1"])
def test_persisted_entry_ints_reject_bool_float_string(field, bad):
    _design, _attachment, artifact = _one_range()
    persisted = artifact.to_dict()
    persisted["entries"][0][field] = bad
    with pytest.raises(AddressDecodeError, match="exact int"):
        AddressDecodeArtifact.from_dict(persisted)


def test_persisted_entry_name_is_required():
    _design, _attachment, artifact = _one_range()
    persisted = artifact.to_dict()
    persisted["entries"][0].pop("name")
    with pytest.raises(AddressDecodeError, match="name"):
        AddressDecodeArtifact.from_dict(persisted)


def test_hash_must_be_present_and_match():
    _design, _attachment, artifact = _one_range()
    persisted = artifact.to_dict()
    persisted.pop("address_decode_hash")
    with pytest.raises(AddressDecodeError, match="address_decode_hash"):
        AddressDecodeArtifact.from_dict(persisted)
    persisted = artifact.to_dict()
    persisted["address_decode_hash"] = "0" * 64
    with pytest.raises(AddressDecodeError, match="does not match content"):
        AddressDecodeArtifact.from_dict(persisted)
    persisted = artifact.to_dict()
    persisted["address_decode_hash"] = 7
    with pytest.raises(AddressDecodeError, match="address_decode_hash"):
        AddressDecodeArtifact.from_dict(persisted)


# ── derivation ─────────────────────────────────────────────────────────────

def test_derive_requires_a_real_compile_request():
    _design, attachment, _topology = _one_range()
    with pytest.raises(AddressDecodeError, match="CompileRequest"):
        derive_address_decode(design=object(), attachment=attachment)


def test_derive_requires_a_real_attachment():
    design, _attachment, _topology = _one_range()
    with pytest.raises(AddressDecodeError, match="AgentAttachmentArtifact"):
        derive_address_decode(design=design, attachment=object())


def test_derive_refuses_group_outside_the_design():
    design, attachment, _topology = _build([_compute(4), _hbm(1)])
    bad = dataclasses.replace(design,
                              address_map=_map(_range("X", 0, 0x100, 7)))
    with pytest.raises(AddressDecodeError, match="outside the design"):
        _decode(bad, attachment)


def test_derive_refuses_group_with_no_attached_endpoint():
    design, attachment, _topology = _build([_compute(4), _hbm(1)])
    bad = dataclasses.replace(design,
                              address_map=_map(_range("X", 0, 0x100, 5)))
    with pytest.raises(AddressDecodeError, match="outside the design"):
        _decode(bad, attachment)


def test_derivation_does_not_depend_on_mapping():
    from veritx_dse.model.mapping import derive_mapping
    design, attachment, _topology = _one_range()
    before = _decode(design, attachment)
    derive_mapping(design)
    after = _decode(design, attachment)
    assert after.address_decode_hash == before.address_decode_hash


# ── immutability ───────────────────────────────────────────────────────────

def test_artifact_is_frozen_and_tuple_backed():
    _design, _attachment, artifact = _one_range()
    with pytest.raises(dataclasses.FrozenInstanceError):
        artifact.attachment_hash = "b" * 64
    assert isinstance(artifact.entries, tuple)
    with pytest.raises(TypeError):
        artifact.entries[0] = artifact.entries[0]


def test_to_dict_returns_fresh_data():
    _design, _attachment, artifact = _one_range()
    first = artifact.to_dict()
    first["entries"][0]["base"] = 0xDEAD
    first["entries"].clear()
    second = artifact.to_dict()
    assert second["entries"][0]["base"] == 0
    assert artifact.address_decode_hash == GOLDEN_ONE_RANGE


# ── scope sentinels ────────────────────────────────────────────────────────

def test_payload_has_no_design_or_routing_fields():
    _design, _attachment, artifact = _one_range()
    blob = repr(artifact.to_dict()).lower()
    for token in FORBIDDEN_TOKENS:
        assert token not in blob, token


def test_module_imports_only_allowed_layers():
    tree = ast.parse(inspect.getsource(ad))
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
        "veritx_dse.model.compile_model",
    }
    forbidden = ("topology", "mapping", "placement", "packet_format", "route",
                 "resolved_route", "vc_assignment", "vc_resource", "routing",
                 "router_behavior", "channel_vc_cdg", "protocol_vc",
                 "adaptive_escape", "booksim", "astra", "backend", "cli")
    for name in imported:
        assert not any(token in name.lower() for token in forbidden), name


def test_no_routing_or_backend_authority_symbols():
    for token in ("TopologyArtifact", "MappingArtifact", "PacketFormatArtifact",
                  "RouteArtifact", "ResolvedRouteArtifact",
                  "VCAssignmentArtifact", "VCResourceArtifact",
                  "RoutingPolicyDefinition", "RoutingRelationArtifact",
                  "RouterBehaviorArtifact", "BookSim", "ASTRA"):
        assert not hasattr(ad, token), token


def test_packet_format_gains_no_address_field():
    _design, attachment, topology = _build(
        [_compute(4), _hbm(1)], [_range("HBM0", 0x0, 0x1000, 1)])
    resource = VCResourceArtifact(
        vc_count=1, vc_ids=(0,), traffic_class_to_vcs=(("default", (0,)),),
        allowed_transitions=((0, 0),))
    packet = derive_packet_format(topology, attachment, resource,
                                  max_packet_flits=8)
    roles = {role.value for role in FlitFieldRole}
    assert roles == {"payload", "source_endpoint", "destination_endpoint",
                     "flit_type", "vc_id"}
    assert not any("address" in role for role in roles)
    blob = repr(packet.to_dict()).lower()
    assert "address" not in blob
    assert "destination_endpoint" in blob
