"""Canonical ASTRA/Chakra projection tests.

Proves the projection consumes LogicalMessageArtifactV2 (never the
BookSim-oriented PhysicalTrafficArtifactV2), keeps ONE collective
authority, binds provenance, conserves bytes, refuses unsupported
semantics, and emits real (decodable) Chakra ET for both granularities.
"""
from __future__ import annotations

import inspect
from pathlib import Path
from types import SimpleNamespace

import pytest

from test_canonical_compiler import _det, _design  # test-only canonical fixture

from veritx_dse.backend import astra
from veritx_dse.workload.graph import (
    KIND_COLLECTIVE, KIND_COMPUTE, KIND_EXPERT_BEGIN, KIND_EXPERT_END,
    KIND_MULTICAST, KIND_P2P, KIND_PIM_CHANNEL, KIND_PIM_END, OperationNode,
    WorkloadGraph, collective_detail, compute_detail, expert_detail,
    multicast_detail, p2p_detail, pim_detail, pim_end_detail,
)
from veritx_dse.workload.messages import LogicalMessageArtifactV2

COUNT = 16
PAYLOAD = 1024


def _compiled():
    return _det(_design(compute=COUNT, tp=COUNT))


def _ops(*, collective=True, payload=PAYLOAD):
    ops = [OperationNode(operation_id="pre", kind=KIND_COMPUTE,
                         detail=compute_detail(duration_ns=10000,
                                               participant_count=COUNT))]
    if collective:
        ops.append(OperationNode(
            operation_id="ar", kind=KIND_COLLECTIVE, deps=("pre",),
            detail=collective_detail(
                collective_kind="ALLREDUCE", participants=tuple(range(COUNT)),
                payload_bytes=payload, participant_count=COUNT)))
    return tuple(ops)


def _logical(ops=None, *, count=COUNT, compiled=None):
    compiled = compiled or _compiled()
    graph = WorkloadGraph(parallelism=compiled.inventory.parallelism,
                          participant_count=count,
                          operations=ops if ops is not None else _ops())
    return compiled, LogicalMessageArtifactV2(graph=graph)


def _projection(**kwargs):
    compiled, logical = _logical()
    kwargs.setdefault("resolved_fabric", compiled.resolved_fabric)
    kwargs.setdefault("mapping", compiled.mapping)
    kwargs.setdefault("attachment", compiled.attachment)
    return astra.AstraWorkloadProjection.build(logical=logical, **kwargs)


# ── semantic classification: zero vs lowered vs unsupported ────────────────

def test_zero_traffic_kinds_are_classified_as_zero_not_unsupported():
    compiled, logical = _logical(ops=(
        OperationNode(operation_id="k", kind=KIND_COMPUTE,
                      detail=compute_detail(duration_ns=1,
                                            participant_count=COUNT)),
        OperationNode(operation_id="pc", kind=KIND_PIM_CHANNEL, deps=("k",),
                      detail=pim_detail(channel=0, participant_count=COUNT)),
        OperationNode(operation_id="pe", kind=KIND_PIM_END, deps=("pc",),
                      detail=pim_end_detail(participant_count=COUNT)),
    ))
    rows = astra.audit_operations(logical.graph)
    assert {r["classification"] for r in rows} == {astra.ZERO_TRAFFIC}
    projection = astra.AstraWorkloadProjection.build(
        logical=logical, resolved_fabric=compiled.resolved_fabric,
        mapping=compiled.mapping, attachment=compiled.attachment)
    assert projection.messages == ()


def test_expert_without_collective_is_zero_and_with_collective_is_lowered():
    without = SimpleNamespace(kind=KIND_EXPERT_BEGIN,
                              detail={"participants": None})
    withcoll = SimpleNamespace(kind=KIND_EXPERT_END,
                               detail={"participants": (0, 1)})
    assert astra.classify_operation(without) == astra.ZERO_TRAFFIC
    assert astra.classify_operation(withcoll) == astra.LOWERED


def test_unknown_kind_is_unsupported():
    assert astra.classify_operation(SimpleNamespace(kind="TELEPORT",
                                                    detail={})) \
        == astra.UNSUPPORTED


def test_build_refuses_unsupported_semantics_rather_than_zero(monkeypatch):
    compiled, logical = _logical()
    monkeypatch.setattr(astra, "_LOWERED_KINDS", ())
    with pytest.raises(astra.AstraLoweringRefused, match="no canonical ASTRA"):
        astra.AstraWorkloadProjection.build(
            logical=logical, resolved_fabric=compiled.resolved_fabric,
            mapping=compiled.mapping, attachment=compiled.attachment)


def test_multicast_is_labelled_replicated_unicast():
    ops = (OperationNode(operation_id="m", kind=KIND_MULTICAST,
                         detail=multicast_detail(
                             source_rank=0, destinations=(1, 2),
                             payload_bytes=64,
                             replication="SOURCE_REPLICATION",
                             participant_count=COUNT)),)
    compiled, logical = _logical(ops)
    projection = astra.AstraWorkloadProjection.build(
        logical=logical, resolved_fabric=compiled.resolved_fabric,
        mapping=compiled.mapping, attachment=compiled.attachment)
    assert projection.evidence_scope() == "replicated_unicast"
    assert len(projection.messages) == 2


# ── parent validation ──────────────────────────────────────────────────────

def test_build_requires_canonical_parents():
    compiled, logical = _logical()
    other = _det(_design(compute=4, tp=4))
    with pytest.raises(astra.AstraError, match="does not belong"):
        astra.AstraWorkloadProjection.build(
            logical=logical, resolved_fabric=compiled.resolved_fabric,
            mapping=other.mapping, attachment=compiled.attachment)
    for bad in ({"logical": object()}, {"resolved_fabric": object()},
                {"mapping": object()}, {"attachment": object()}):
        kwargs = dict(logical=logical,
                      resolved_fabric=compiled.resolved_fabric,
                      mapping=compiled.mapping,
                      attachment=compiled.attachment)
        kwargs.update(bad)
        with pytest.raises(astra.AstraError):
            astra.AstraWorkloadProjection.build(**kwargs)


# ── identity / determinism / provenance ────────────────────────────────────

def test_projection_is_deterministic_and_binds_provenance():
    compiled, logical = _logical()
    a = astra.AstraWorkloadProjection.build(
        logical=logical, resolved_fabric=compiled.resolved_fabric,
        mapping=compiled.mapping, attachment=compiled.attachment)
    b = astra.AstraWorkloadProjection.build(
        logical=logical, resolved_fabric=compiled.resolved_fabric,
        mapping=compiled.mapping, attachment=compiled.attachment)
    assert a.projection_id() == b.projection_id()
    assert a.canonical_bytes() == b.canonical_bytes()
    doc = a.identity_dict()
    assert doc["workload_id"] == logical.graph.workload_id()
    assert doc["message_artifact_id"] == logical.message_artifact_id()
    assert doc["resolved_fabric_hash"] \
        == compiled.resolved_fabric.resolved_fabric_hash
    assert doc["mapping_hash"] == compiled.mapping.mapping_hash()
    assert doc["attachment_hash"] == compiled.attachment.attachment_hash()
    assert doc["lowering_semantics_version"] \
        == astra.LOWERING_SEMANTICS_VERSION


def test_identity_binds_lowering_parameters():
    base = _projection()
    assert _projection(mtu_bytes=256).projection_id() != base.projection_id()
    assert _projection(comm_attr_abi="int").projection_id() \
        != base.projection_id()
    assert _projection(et_granularity="collectives").projection_id() \
        != base.projection_id()
    assert base.identity_dict()["expansion_authority"] \
        == "srota_logical_messages"
    assert _projection(et_granularity="collectives").identity_dict()[
        "expansion_authority"] == "astra_comm_coll"


def test_changed_workload_moves_projection_id():
    compiled, logical_a = _logical()
    _, logical_b = _logical(ops=_ops(payload=2048))
    a = astra.AstraWorkloadProjection.build(
        logical=logical_a, resolved_fabric=compiled.resolved_fabric,
        mapping=compiled.mapping, attachment=compiled.attachment)
    b = astra.AstraWorkloadProjection.build(
        logical=logical_b, resolved_fabric=compiled.resolved_fabric,
        mapping=compiled.mapping, attachment=compiled.attachment)
    assert a.projection_id() != b.projection_id()


# ── byte conservation + MTU fragmentation ──────────────────────────────────

def test_message_bytes_are_conserved_exactly():
    compiled, logical = _logical()
    projection = astra.AstraWorkloadProjection.build(
        logical=logical, resolved_fabric=compiled.resolved_fabric,
        mapping=compiled.mapping, attachment=compiled.attachment)
    logical_bytes = sum(m.payload_bytes for m in logical.messages)
    assert projection.total_payload_bytes() == logical_bytes
    assert projection.presented_bytes() == logical_bytes
    assert sum(len(p.fragments) for p in projection.messages) \
        == len(logical.messages)


def test_fragmentation_conserves_and_is_bounded_by_mtu():
    projection = _projection(mtu_bytes=256)
    for message in projection.messages:
        assert sum(message.fragments) == message.payload_bytes
        assert all(0 < f <= 256 for f in message.fragments)
    assert projection.presented_bytes() == projection.total_payload_bytes()


def test_fragment_payload_boundaries():
    assert astra.fragment_payload(100, None) == (100,)
    assert astra.fragment_payload(100, 100) == (100,)
    assert astra.fragment_payload(100, 99) == (99, 1)
    assert astra.fragment_payload(300, 100) == (100, 100, 100)
    with pytest.raises(astra.AstraError, match="positive"):
        astra.fragment_payload(0, None)
    with pytest.raises(astra.AstraError, match="mtu_bytes"):
        astra.fragment_payload(10, 0)


def test_projection_rejects_internal_fragment_mismatch():
    projection = _projection()
    broken = astra.AstraMessage(
        sequence=0, operation_id="ar", kind=KIND_COLLECTIVE,
        collective_kind="ALLREDUCE", step=0, phase=None, src_rank=0,
        dst_rank=1, payload_bytes=100, traffic_class="DEFAULT",
        fragments=(99,))
    with pytest.raises(astra.AstraError, match="conserve"):
        astra.AstraWorkloadProjection(
            messages=(broken,), participant_count=COUNT,
            message_artifact_id="m", workload_id="w",
            resolved_fabric_hash="r", mapping_hash="x", attachment_hash="a")


# ── Chakra ET emission (real protobuf) ─────────────────────────────────────

def _decode(path: Path):
    from chakra.schema.protobuf import et_def_pb2 as pb
    from chakra.src.third_party.utils import protolib
    with open(path, "rb") as handle:
        metadata = pb.GlobalMetadata()
        assert protolib.decodeMessage(handle, metadata)
        nodes = []
        while True:
            node = pb.Node()
            if not protolib.decodeMessage(handle, node):  # EOF -> False
                break
            nodes.append(node)
    return metadata, nodes


def test_chakra_files_use_the_runtime_naming_convention(tmp_path):
    projection = _projection()
    written = projection.write_chakra(directory=tmp_path, stem="canon")
    names = {p.name for p in written}
    assert "canon.et" in names
    for rank in range(COUNT):
        assert f"canon.et.{rank}.et" in names
    # the base is the rank-0 file, as the runtime expects
    assert (tmp_path / "canon.et").read_bytes() \
        == (tmp_path / "canon.et.0.et").read_bytes()


def test_message_granularity_emits_send_recv_without_re_expanding(tmp_path):
    projection = _projection(et_granularity="messages")
    projection.write_chakra(directory=tmp_path, stem="m")
    _, nodes = _decode(tmp_path / "m.et.0.et")
    types = [n.type for n in nodes]
    assert types[0] == 4  # COMP_NODE
    assert all(t in (5, 6) for t in types[1:])  # SEND/RECV only
    comm = nodes[1]
    attr = {a.name: (a.uint32_val or a.uint64_val) for a in comm.attr}
    assert set(attr) == {"comm_src", "comm_dst", "comm_size"}
    assert attr["comm_size"] == 64          # 1024 B / 16 ranks
    # one pair per logical message, and NO collective node anywhere
    assert len(projection.messages) == 480
    assert not any(t == 7 for t in types)


def test_collective_granularity_emits_one_coll_node_per_operation(tmp_path):
    projection = _projection(et_granularity="collectives")
    projection.write_chakra(directory=tmp_path, stem="c")
    _, nodes = _decode(tmp_path / "c.et.0.et")
    colls = [n for n in nodes if n.type == 7]
    assert len(colls) == 1
    attr = {a.name: (a.uint64_val or a.int64_val) for a in colls[0].attr}
    assert attr["comm_type"] == 0        # ALL_REDUCE
    assert attr["comm_size"] == PAYLOAD
    assert any(a.name == "involved_dim" for a in colls[0].attr)


def test_chakra_emission_is_deterministic(tmp_path):
    projection = _projection()
    projection.write_chakra(directory=tmp_path / "a", stem="w")
    projection.write_chakra(directory=tmp_path / "b", stem="w")
    for rank in range(COUNT):
        assert (tmp_path / "a" / f"w.et.{rank}.et").read_bytes() \
            == (tmp_path / "b" / f"w.et.{rank}.et").read_bytes()


def test_et_metadata_carries_the_chakra_schema(tmp_path):
    _projection().write_chakra(directory=tmp_path, stem="w")
    metadata, _ = _decode(tmp_path / "w.et.0.et")
    schema = next(a.string_val for a in metadata.attr if a.name == "schema")
    assert schema == "1.0.2-chakra.0.0.4"


# ── architectural boundary sentinels ───────────────────────────────────────

def _stripped_source(module) -> str:
    import ast as _ast
    source = inspect.getsource(module)
    tree = _ast.parse(source)
    ranges = []
    for node in _ast.walk(tree):
        if isinstance(node, (_ast.Module, _ast.ClassDef, _ast.FunctionDef,
                             _ast.AsyncFunctionDef)) \
                and node.body \
                and isinstance(node.body[0], _ast.Expr) \
                and isinstance(node.body[0].value, _ast.Constant) \
                and isinstance(node.body[0].value.value, str):
            ranges.append((node.body[0].lineno, node.body[0].end_lineno))
    return "".join(
        line for number, line in enumerate(source.splitlines(keepends=True),
                                           start=1)
        if not any(low <= number <= high for low, high in ranges))


def test_adapter_never_imports_the_booksim_flit_artifact():
    source = _stripped_source(astra)
    for forbidden in ("PhysicalTrafficArtifactV2", "workload.traffic",
                      "packetize_message", "flitize_packet",
                      "participant_endpoint_mapping", "packet_format"):
        assert forbidden not in source, forbidden


def test_adapter_does_not_import_backend_or_cli_authorities():
    source = inspect.getsource(astra)
    for forbidden in ("llmservingsim", "ramulator", "chakra_to_et",
                      "veritx_dse.cli"):
        assert forbidden not in source, forbidden
