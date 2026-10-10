"""Source replication is a byte-exact unicast model, not router branching."""
from dataclasses import replace

import pytest

from test_canonical_compiler import _design, _det
from veritx_dse.core.errors import ConservationFailed, EvidenceInvalid, InvalidInput, UnsupportedSemantics
from veritx_dse.model.mapping import MappingArtifact, RankPlacement
from veritx_dse.workload.graph import (
    KIND_COLLECTIVE, KIND_MULTICAST, KIND_P2P, OperationNode, WorkloadGraph,
    collective_detail, multicast_detail, p2p_detail,
)
from veritx_dse.workload.messages import LogicalMessageArtifactV2, LogicalMessageArtifactV3
from veritx_dse.workload.traffic import PhysicalTrafficArtifactV2, PhysicalTrafficArtifactV3, payload_width_bits


@pytest.fixture(scope="module")
def compiled():
    return _det(_design(compute=4, tp=4))


def _model(compiled, version=2, destinations=(1, 3), payload=301):
    graph = WorkloadGraph(
        parallelism=compiled.inventory.parallelism, participant_count=4,
        operations=(OperationNode(
            operation_id="mc", kind=KIND_MULTICAST,
            detail=multicast_detail(source_rank=2, destinations=destinations,
                                    payload_bytes=payload,
                                    replication="SOURCE_REPLICATION",
                                    participant_count=4)),))
    logical = (LogicalMessageArtifactV2(graph=graph, traffic_class="fanout")
               if version == 2 else LogicalMessageArtifactV3(
                   graph=graph, traffic_class_by_operation=(("mc", "fanout"),)))
    parents = dict(logical=logical, resolved_fabric=compiled.resolved_fabric,
                   mapping=compiled.mapping, attachment=compiled.attachment,
                   inventory=compiled.inventory, packet_format=compiled.packet_format)
    cls = PhysicalTrafficArtifactV2 if version == 2 else PhysicalTrafficArtifactV3
    return cls(**parents), parents


@pytest.mark.parametrize("version", [2, 3])
@pytest.mark.parametrize("destinations", [(1,), (0, 1, 3)])
@pytest.mark.parametrize("payload", [1, 301, 4097])
def test_replica_bytes_flits_and_parent_recomputed_roundtrip(compiled, version, destinations, payload):
    physical, parents = _model(compiled, version, destinations, payload)
    physical.validate_conservation()
    logical = physical.logical
    rec, = logical.multicast_records()
    assert rec.aggregate_payload_bytes == len(destinations) * payload
    assert not logical.schedules
    assert {m.dst_rank for m in rec.replicas} == set(destinations)
    assert {m.traffic_class for m in rec.replicas} == {"fanout"}
    assert len({m.message_id for m in rec.replicas}) == len(destinations)
    logical_reloaded = type(logical).from_dict(logical.to_dict(), graph=logical.graph, strict=True)
    assert logical_reloaded.multicast_records() == (rec,)
    reloaded = type(physical).from_dict(physical.to_dict(), **parents, strict=True)
    ledger, = reloaded.multicast_ledger()
    assert ledger["replication"] == "SOURCE_REPLICATION"
    assert ledger["execution_scope"] == "replicated_unicast"
    assert ledger["evidence_scope"] == "MODELED_SOURCE_REPLICATION_ONLY"
    assert ledger["source_logical_payload_bytes"] == payload
    assert ledger["source_injected_payload_bytes"] == len(destinations) * payload
    assert ledger["delivered_payload_bytes"] == len(destinations) * payload
    assert ledger["packet_payload_bits"] == len(destinations) * payload * 8
    assert ledger["transmitted_bits"] == ledger["packet_payload_bits"] + ledger["header_bits"] + ledger["padding_bits"]
    row, = physical.ledger()
    assert row.scheduled_message_bytes == row.generated_message_bytes == len(destinations) * payload
    assert row.source_logical_payload_bytes == payload
    # Independent integer packet/flit law, not the production packetizer.
    q = payload_width_bits(compiled.packet_format)
    capacity = q * compiled.packet_format.max_packet_flits
    full, tail = divmod(payload * 8, capacity)
    bits = [capacity] * full + ([tail] if tail else [])
    expected_flits = sum((b + q - 1) // q for b in bits)
    assert ledger["flit_count"] == len(destinations) * expected_flits
    pem = physical.participant_endpoint_mapping()
    for replica in ledger["replicas"]:
        assert replica["source_endpoint"] == pem.endpoint_for(2)
        assert replica["destination_endpoint"] == pem.endpoint_for(replica["destination_rank"])
        assert replica["flit_count"] == expected_flits
        assert [p["payload_bits"] for p in replica["packets"]] == bits


@pytest.mark.parametrize("version", [2, 3])
@pytest.mark.parametrize("mutation", [
    "missing", "duplicate", "destination", "source", "payload", "identity",
    "seq", "step", "foreign_id", "class", "phase", "order",
])
def test_intent_to_replica_tampering_is_refused(compiled, version, mutation):
    physical, parents = _model(compiled, version)
    logical = physical.logical
    first, second = logical.messages
    rows = {
        "missing": (first,), "duplicate": (first, first),
        "destination": (first, replace(second, dst_rank=0)),
        "source": (replace(first, src_rank=0), second),
        "payload": (replace(first, payload_bytes=302), replace(second, payload_bytes=300)),
        "identity": (first, replace(second, message_id=first.message_id)),
        "seq": (first, replace(second, seq=first.seq)),
        "step": (replace(first, step=1), second),
        "foreign_id": (replace(first, message_id="other#0"), second),
        "class": (replace(first, traffic_class="foreign"), second),
        "phase": (replace(first, phase="foreign"), second),
        "order": (second, first),
    }[mutation]
    object.__setattr__(logical, "_messages", rows)
    with pytest.raises(ConservationFailed, match="multicast"):
        logical.validate_conservation()
    # Consumer must not packetize a self-hashed but invalid logical parent.
    with pytest.raises(ConservationFailed, match="multicast"):
        type(physical)(**parents)


@pytest.mark.parametrize("version", [2, 3])
@pytest.mark.parametrize("mutation", ["missing", "duplicate", "rank", "endpoint", "agent", "payload", "packet_endpoint", "flits"])
def test_physical_replica_tampering_is_refused(compiled, version, mutation):
    physical, _ = _model(compiled, version)
    first, second = physical.traffic
    packet, *tail = first.packets
    rows = {
        "missing": (first,), "duplicate": (first, first),
        "rank": (replace(first, dst=replace(first.dst, rank=0)), second),
        "endpoint": (replace(first, dst=replace(first.dst, endpoint_id=0)), second),
        "agent": (replace(first, src=replace(first.src, agent_instance_id="foreign")), second),
        "payload": (replace(first, payload_bytes=302), second),
        "packet_endpoint": (replace(first, packets=(replace(packet, dst_endpoint=0), *tail)), second),
        "flits": (replace(first, packets=(replace(packet, flit_count=packet.flit_count + 1), *tail)), second),
    }[mutation]
    object.__setattr__(physical, "_traffic", rows)
    with pytest.raises(ConservationFailed, match="multicast"):
        physical.validate_conservation()
    with pytest.raises(ConservationFailed, match="multicast"):
        physical.multicast_ledger()


@pytest.mark.parametrize("version", [2, 3])
def test_serialized_replica_coverage_and_packet_tampering_is_refused(compiled, version):
    physical, parents = _model(compiled, version)
    logical = physical.logical
    doc = logical.to_dict()
    doc["messages"][1]["dst_rank"] = 0
    with pytest.raises(EvidenceInvalid):
        type(logical).from_dict(doc, graph=logical.graph, strict=True)
    doc = physical.to_dict()
    doc["traffic"][0][0]["dst_endpoint"] = 0
    with pytest.raises(EvidenceInvalid):
        type(physical).from_dict(doc, **parents, strict=True)


@pytest.mark.parametrize("version", [2, 3])
def test_real_permuted_mapping_moves_replica_endpoints_not_logical_identity(compiled, version):
    agents = compiled.inventory.compute_instances
    mapping = MappingArtifact(placements=tuple(
        RankPlacement(rank=rank, agent=agents[(rank + 1) % 4])
        for rank in range(4)))
    moved_compilation = _det(compiled.design, mapping=mapping)
    original, _ = _model(compiled, version)
    moved, _ = _model(moved_compilation, version)
    assert original.logical.message_artifact_id() == moved.logical.message_artifact_id()
    assert original.physical_traffic_id() != moved.physical_traffic_id()
    original_rows = original.multicast_ledger()[0]["replicas"]
    moved_rows = moved.multicast_ledger()[0]["replicas"]
    assert [r["destination_rank"] for r in original_rows] == [r["destination_rank"] for r in moved_rows]
    assert [r["destination_endpoint"] for r in original_rows] != [r["destination_endpoint"] for r in moved_rows]
    assert moved_rows[0]["source_endpoint"] == moved.participant_endpoint_mapping().endpoint_for(2)
    moved.validate_conservation()


def test_broadcast_and_multicast_remain_distinct_and_v3_requires_class_coverage(compiled):
    physical, _ = _model(compiled)
    multicast = physical.logical.graph.operations[0]
    broadcast = OperationNode(operation_id="bc", kind=KIND_COLLECTIVE,
                              detail=collective_detail(collective_kind="BROADCAST",
                                  participants=(2, 1, 3), source=2,
                                  payload_bytes=301, participant_count=4))
    transfer = OperationNode(operation_id="p", kind=KIND_P2P,
                             detail=p2p_detail(src_rank=0, dst_rank=1,
                                 payload_bytes=1, role="TRANSFER", participant_count=4))
    graph = replace(physical.logical.graph, operations=(multicast, broadcast, transfer))
    logical = LogicalMessageArtifactV3(graph=graph, traffic_class_by_operation=(
        ("mc", "fanout"), ("bc", "collective"), ("p", "point")))
    logical.validate_conservation()
    assert [s.collective_id for s in logical.schedules] == ["bc"]
    assert [r.operation_id for r in logical.multicast_records()] == ["mc"]
    assert logical.classes == ("collective", "fanout", "point")
    with pytest.raises(InvalidInput, match="exactly once"):
        LogicalMessageArtifactV3(graph=graph, traffic_class_by_operation=(("bc", "collective"),))


def test_hardware_replication_is_never_lowered(compiled):
    physical, _ = _model(compiled)
    op = physical.logical.graph.operations[0]
    with pytest.raises(UnsupportedSemantics, match="replication"):
        replace(physical.logical.graph, operations=(replace(op, detail={
            **dict(op.detail), "replication": "HARDWARE_REPLICATION"}),))
