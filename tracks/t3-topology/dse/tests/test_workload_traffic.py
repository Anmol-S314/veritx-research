"""Participant→endpoint binding + physical packet/flit conservation.

Re-parented from the strongest Wave-E/studio lineage
(``test_physical_traffic_v2.py`` + ``test_packet_format``-era packet laws)
onto the CURRENT canonical authorities: MappingArtifact, AgentAttachmentArtifact,
NodeInventory, PacketFormatArtifact and ResolvedFabric.

The packet oracle below is an independent restatement of the bit-exact laws;
it never calls the production packetizer to compute its expectation.
"""
from __future__ import annotations

import dataclasses

import pytest

from test_canonical_compiler import _det, _design  # test-only canonical fixture

from veritx_dse.core.artifact import EvidenceInvalid
from veritx_dse.core.errors import ConservationFailed, InvalidInput, MappingInvalid
from veritx_dse.model.mapping import MappingArtifact, RankPlacement
from veritx_dse.model.placement import ParallelismShape
from veritx_dse.workload.graph import (
    KIND_COLLECTIVE, KIND_P2P, OperationNode, WorkloadGraph, collective_detail,
    p2p_detail,
)
from veritx_dse.workload.messages import LogicalMessageArtifactV2
from veritx_dse.workload.traffic import (
    PhysicalTrafficArtifactV2, ParticipantEndpointMapping, bind_participants,
    flitize_packet, header_width_bits, packet_capacity_bits, packetize_message,
    payload_width_bits,
)


# ── fixtures ───────────────────────────────────────────────────────────────

def _compiled(compute: int = 8, tp: int = 8):
    return _det(_design(compute=compute, tp=tp))


def _graph_for(compiled, *, participant_count=None, participants=None,
               payload=64, shape=None):
    count = participant_count or compiled.inventory.rank_count
    parts = tuple(participants if participants is not None
                  else range(count))
    return WorkloadGraph(
        parallelism=shape or compiled.inventory.parallelism,
        participant_count=count,
        operations=(OperationNode(
            operation_id="c0", kind=KIND_COLLECTIVE,
            detail=collective_detail(collective_kind="ALLREDUCE",
                                     participants=parts,
                                     payload_bytes=payload,
                                     participant_count=count)),))


def _traffic(compiled, graph=None, **overrides):
    graph = graph or _graph_for(compiled)
    logical = LogicalMessageArtifactV2(graph=graph)
    kwargs = dict(logical=logical, resolved_fabric=compiled.resolved_fabric,
                  mapping=compiled.mapping, attachment=compiled.attachment,
                  inventory=compiled.inventory,
                  packet_format=compiled.packet_format)
    kwargs.update(overrides)
    return PhysicalTrafficArtifactV2(**kwargs)


# ── participant binding ────────────────────────────────────────────────────

def test_binding_is_mapping_derived_and_covers_the_namespace():
    compiled = _compiled()
    pem = bind_participants(participant_count=8, mapping=compiled.mapping,
                            attachment=compiled.attachment,
                            resolved_fabric=compiled.resolved_fabric)
    expected_endpoint = {}
    for endpoint in compiled.attachment.endpoints:
        agent = endpoint.agent
        expected_endpoint[(agent.group_index, agent.instance_index,
                           agent.kind)] = endpoint.endpoint_id
    for rank, endpoint_id in pem.rank_to_endpoint:
        agent = {p.rank: p.agent for p in compiled.mapping.placements}[rank]
        assert endpoint_id == expected_endpoint[
            (agent.group_index, agent.instance_index, agent.kind)]
    assert pem.fabric_id == compiled.resolved_fabric.resolved_fabric_hash
    assert len({e for _, e in pem.rank_to_endpoint}) == 8


def test_binding_follows_the_mapping_not_rank_equality():
    """A permuted mapping moves the endpoint of a rank: rank != endpoint."""
    compiled = _compiled(compute=4, tp=2)
    compute = compiled.inventory.compute_instances
    permuted = MappingArtifact(placements=(
        RankPlacement(rank=0, agent=compute[1]),
        RankPlacement(rank=1, agent=compute[0])))
    forged_root = dataclasses.replace(
        compiled.resolved_fabric,
        mapping_hash=permuted.mapping_hash(),
        resolved_fabric_hash="")
    canonical = bind_participants(participant_count=2,
                                  mapping=compiled.mapping,
                                  attachment=compiled.attachment,
                                  resolved_fabric=compiled.resolved_fabric)
    swapped = bind_participants(participant_count=2, mapping=permuted,
                                attachment=compiled.attachment,
                                resolved_fabric=forged_root)
    assert canonical.endpoint_for(0) != swapped.endpoint_for(0)
    assert canonical.endpoint_for(0) == swapped.endpoint_for(1)
    assert canonical.endpoint_for(1) == swapped.endpoint_for(0)


def test_subset_participant_namespace_binds_only_declared_ranks():
    compiled = _compiled()          # world size 8
    graph = _graph_for(compiled, participant_count=4,
                       participants=(0, 1, 2, 3), payload=32)
    traffic = _traffic(compiled, graph)
    pem = traffic.participant_endpoint_mapping()
    assert [r for r, _ in pem.rank_to_endpoint] == [0, 1, 2, 3]
    assert all(m.src_rank < 4 and m.dst_rank < 4
               for m in traffic.logical.messages)


def test_participant_beyond_the_world_is_refused():
    compiled = _compiled()
    graph = _graph_for(compiled, participant_count=9,
                       participants=tuple(range(9)), payload=72)
    with pytest.raises(MappingInvalid, match="no mapping placement"):
        _traffic(compiled, graph)


def test_mapping_from_another_fabric_is_refused():
    compiled = _compiled()
    other = _compiled(compute=4, tp=4)
    with pytest.raises(MappingInvalid, match="mapping does not belong"):
        _traffic(compiled, mapping=other.mapping)


def test_packet_format_from_another_attachment_is_refused():
    compiled = _compiled()
    other = _compiled(compute=4, tp=4)
    with pytest.raises(MappingInvalid, match="packet format was not derived"):
        _traffic(compiled, packet_format=other.packet_format)


def test_geometry_transposition_is_refused():
    compiled = _compiled()
    transposed = ParallelismShape(tp=4, pp=2, ep=1, dp=1)
    assert transposed.world_size == compiled.inventory.parallelism.world_size
    graph = _graph_for(compiled, participant_count=8, shape=transposed)
    with pytest.raises(MappingInvalid, match="does not match the physical"):
        _traffic(compiled, graph)


def test_participant_mapping_validates_its_own_shape():
    with pytest.raises(MappingInvalid, match="participant_count"):
        ParticipantEndpointMapping(participant_count=2,
                                   rank_to_endpoint=((0, 0),), fabric_id="x")
    with pytest.raises(MappingInvalid, match="one endpoint per participant"):
        ParticipantEndpointMapping(participant_count=2,
                                   rank_to_endpoint=((0, 5), (1, 5)),
                                   fabric_id="x")


# ── independent packet/flit oracle ─────────────────────────────────────────

def oracle_packets(message_bits: int, q: int, l_: int, f: int):
    capacity = q * l_
    rows, remaining, idx = [], message_bits, 0
    while remaining > 0:
        payload = min(capacity, remaining)
        remaining -= payload
        flits = -(-payload // q)
        padding = flits * q - payload
        rows.append((idx, payload, flits, padding, flits * (f - q),
                     flits * f))
        idx += 1
    return rows


@pytest.mark.parametrize("payload_bytes", [1, 100, 424, 1000, 5000])
def test_packetization_matches_the_independent_oracle(payload_bytes):
    compiled = _compiled()
    graph = WorkloadGraph(
        parallelism=compiled.inventory.parallelism,
        participant_count=8,
        operations=(OperationNode(
            operation_id="p0", kind=KIND_P2P,
            detail=p2p_detail(role="TRANSFER", src_rank=0, dst_rank=5,
                              payload_bytes=payload_bytes,
                              participant_count=8)),))
    traffic = _traffic(compiled, graph)
    pf = compiled.packet_format
    q, f = payload_width_bits(pf), pf.flit_width_bits
    rows = oracle_packets(payload_bytes * 8, q, pf.max_packet_flits, f)
    packets = traffic.traffic[0].packets
    assert [(p.packet_index, p.payload_bits, p.flit_count, p.padding_bits,
             p.header_bits, p.transmitted_bits) for p in packets] == rows
    traffic.validate_conservation()


def test_payload_width_and_capacity_come_from_the_field_layout():
    compiled = _compiled()
    pf = compiled.packet_format
    payload_fields = [fld for fld in pf.fields
                      if fld.role.value == "payload"]
    assert len(payload_fields) == 1
    assert payload_width_bits(pf) == payload_fields[0].width
    assert header_width_bits(pf) == pf.flit_width_bits - payload_fields[0].width
    assert packet_capacity_bits(pf) == payload_width_bits(pf) * pf.max_packet_flits


def test_single_flit_and_empty_boundaries():
    capacity = 424
    assert packetize_message(capacity, _compiled().packet_format) == [capacity]
    assert packetize_message(capacity + 1, _compiled().packet_format) \
        == [capacity, 1]
    with pytest.raises(InvalidInput, match="must be positive"):
        packetize_message(0, _compiled().packet_format)


def test_flit_padding_is_bounded_by_the_payload_width():
    compiled = _compiled()
    pf = compiled.packet_format
    q = payload_width_bits(pf)
    for payload_bits in (1, 52, 53, 54, 105):
        _, padding, transmitted = flitize_packet(payload_bits, pf)
        assert 0 <= padding < q
        assert transmitted == padding + payload_bits \
            + ((-(-payload_bits // q)) * header_width_bits(pf))


# ── conservation / ledger ──────────────────────────────────────────────────

def test_totals_conserve_message_bits():
    compiled = _compiled()
    traffic = _traffic(compiled)
    traffic.validate_conservation()
    totals = traffic.totals()
    logical_bits = sum(m.payload_bytes for m in traffic.logical.messages) * 8
    assert totals["packet_payload_bits"] == logical_bits
    assert totals["transmitted_bits"] == totals["header_bits"] \
        + totals["packet_payload_bits"] + totals["padding_bits"]
    for t in traffic.traffic:
        assert sum(p.payload_bits for p in t.packets) == t.message_bits


def test_ledger_reports_per_operation_classes():
    compiled = _compiled()
    traffic = _traffic(compiled)
    rows = {e.operation_id: e for e in traffic.ledger()}
    entry = rows["c0"]
    assert entry.operation_kind == KIND_COLLECTIVE
    assert entry.source_logical_payload_bytes == 64
    assert entry.message_count == len(traffic.logical.messages)
    assert entry.packet_count == len(traffic.traffic[0].packets) or \
        entry.packet_count == sum(len(t.packets) for t in traffic.traffic)
    assert entry.rank_binding_valid and entry.endpoint_binding_valid


def test_conservation_failure_is_a_hard_error():
    compiled = _compiled()
    traffic = _traffic(compiled)
    broken = dataclasses.replace(traffic.traffic[0],
                                 packets=(dataclasses.replace(
                                     traffic.traffic[0].packets[0],
                                     transmitted_bits=1),))
    object.__setattr__(traffic, "_traffic",
                       (broken,) + traffic.traffic[1:])
    with pytest.raises(ConservationFailed):
        traffic.validate_conservation()


# ── identity / strict loader ───────────────────────────────────────────────

def test_identity_is_stable_and_strict_round_trip_is_lossless():
    compiled = _compiled()
    traffic = _traffic(compiled)
    again = _traffic(compiled)
    assert traffic.physical_traffic_id() == again.physical_traffic_id()
    loaded = PhysicalTrafficArtifactV2.from_dict(
        traffic.to_dict(), logical=traffic.logical,
        resolved_fabric=compiled.resolved_fabric, mapping=compiled.mapping,
        attachment=compiled.attachment, inventory=compiled.inventory,
        packet_format=compiled.packet_format, strict=True)
    assert loaded.physical_traffic_id() == traffic.physical_traffic_id()


def test_identity_binds_the_participant_mapping():
    compiled = _compiled()
    doc = _traffic(compiled).identity_dict()
    assert doc["participant_endpoint_mapping_id"] \
        == _traffic(compiled).participant_endpoint_mapping().binding_id()
    assert doc["resolved_fabric_hash"] \
        == compiled.resolved_fabric.resolved_fabric_hash
    assert doc["packet_format_hash"] == compiled.packet_format.packet_format_hash


def test_tampered_packet_content_is_refused_on_strict_load():
    compiled = _compiled()
    traffic = _traffic(compiled)
    doc = traffic.to_dict()
    doc["traffic"][0][0]["payload_bits"] += 1
    with pytest.raises(EvidenceInvalid, match="content forged"):
        PhysicalTrafficArtifactV2.from_dict(
            doc, logical=traffic.logical,
            resolved_fabric=compiled.resolved_fabric, mapping=compiled.mapping,
            attachment=compiled.attachment, inventory=compiled.inventory,
            packet_format=compiled.packet_format, strict=True)


def test_wrong_logical_parent_is_refused_on_strict_load():
    compiled_a = _compiled()
    compiled_b = _compiled(compute=4, tp=4)
    traffic_b = _traffic(compiled_b)
    traffic_a = _traffic(compiled_a)
    with pytest.raises(InvalidInput, match="verified logical parent"):
        PhysicalTrafficArtifactV2.from_dict(
            traffic_b.to_dict(), logical=traffic_a.logical,
            resolved_fabric=compiled_b.resolved_fabric,
            mapping=compiled_b.mapping, attachment=compiled_b.attachment,
            inventory=compiled_b.inventory,
            packet_format=compiled_b.packet_format, strict=True)


# ── end-to-end canonical spine ─────────────────────────────────────────────

def test_full_spine_from_compile_request_without_historical_control_plane():
    """CompileRequest → canonical fabric → graph → messages → traffic."""
    compiled = _compiled()
    inventory = compiled.inventory
    graph = WorkloadGraph(
        parallelism=inventory.parallelism,
        participant_count=inventory.rank_count,
        operations=(
            OperationNode(operation_id="ar", kind=KIND_COLLECTIVE,
                          detail=collective_detail(
                              collective_kind="ALLREDUCE",
                              participants=tuple(range(inventory.rank_count)),
                              payload_bytes=64,
                              participant_count=inventory.rank_count)),
            OperationNode(operation_id="tx", kind=KIND_P2P, deps=("ar",),
                          detail=p2p_detail(role="TRANSFER", src_rank=0,
                                            dst_rank=inventory.rank_count - 1,
                                            payload_bytes=1500,
                                            participant_count=inventory.rank_count)),
        ))
    logical = LogicalMessageArtifactV2(graph=graph)
    logical.validate_conservation()
    traffic = PhysicalTrafficArtifactV2(
        logical=logical, resolved_fabric=compiled.resolved_fabric,
        mapping=compiled.mapping, attachment=compiled.attachment,
        inventory=inventory, packet_format=compiled.packet_format)
    traffic.validate_conservation()
    assert traffic.totals()["packet_payload_bits"] \
        == sum(m.payload_bytes for m in logical.messages) * 8
    assert traffic.participant_endpoint_mapping().participant_count \
        == inventory.rank_count
