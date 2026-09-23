"""Canonical WorkloadGraph tests — the reclaimed workload authority.

Ported and re-parented from the strongest Wave-E/studio lineage
(``test_canonical_workload_graph.py``) onto the CURRENT canonical geometry
authority (``ParallelismShape``). The laws themselves are unchanged:
participant namespace != geometry, absent is not a default, declarations
are permissive while schedules are strict, and identity is deterministic.
"""
from __future__ import annotations

import dataclasses

import pytest

from veritx_dse.core.artifact import EvidenceInvalid
from veritx_dse.core.errors import (
    InvalidInput, UnsupportedSemantics,
)
from veritx_dse.model.placement import ParallelismShape
from veritx_dse.workload.graph import (
    KIND_COLLECTIVE, KIND_COMPUTE, KIND_EXPERT_BEGIN, KIND_EXPERT_END,
    KIND_MULTICAST, KIND_P2P, KIND_PIM_CHANNEL, KIND_PIM_END, OperationNode,
    WorkloadGraph, WorkloadSemantics, collective_detail, compute_detail,
    expert_detail, multicast_detail, p2p_detail, pim_detail, pim_end_detail,
)

SHAPE = ParallelismShape(tp=4, pp=1, ep=1, dp=1)
COUNT = 4


def _collective(op_id="c0", kind="ALLREDUCE", participants=(0, 1, 2, 3),
                payload=64, deps=(), **kw):
    return OperationNode(
        operation_id=op_id, kind=KIND_COLLECTIVE, deps=tuple(deps),
        detail=collective_detail(
            collective_kind=kind, participants=participants,
            payload_bytes=payload, participant_count=COUNT, **kw))


def _graph(*ops, shape=SHAPE, count=COUNT, semantics=None, provenance=None):
    return WorkloadGraph(parallelism=shape, participant_count=count,
                         operations=tuple(ops),
                         semantics=semantics or WorkloadSemantics(),
                         provenance=provenance)


# ── identity determinism ───────────────────────────────────────────────────

def test_identity_is_deterministic_and_construction_order_free():
    a = _collective("a", payload=64)
    b = _collective("b", kind="ALLGATHER", payload=32, deps=("a",))
    forward = _graph(a, b)
    backward = _graph(b, a)
    assert forward.workload_id() == backward.workload_id()
    assert forward.identity_dict() == backward.identity_dict()


def test_label_and_provenance_are_not_identity():
    a = _collective("a")
    base = _graph(a)
    labelled = _graph(dataclasses.replace(a, label="source spelling"))
    assert labelled.workload_id() == base.workload_id()
    sourced = _graph(a, provenance={"origin": "run-7", "file": "x.et"})
    assert sourced.workload_id() == base.workload_id()
    assert sourced.to_dict()["provenance"] == {"origin": "run-7",
                                              "file": "x.et"}


def test_geometry_and_participant_count_are_identity():
    base = _graph(_collective())
    other_shape = _graph(_collective(), shape=ParallelismShape(tp=2, pp=2,
                                                               ep=1, dp=1))
    assert other_shape.workload_id() != base.workload_id()
    fewer = _graph(_collective(participants=(0, 1), payload=8), count=2)
    assert fewer.workload_id() != base.workload_id()


# ── strict round trip ──────────────────────────────────────────────────────

def test_strict_round_trip_is_lossless():
    graph = _graph(_collective(),
                   OperationNode(operation_id="p", kind=KIND_P2P,
                                 deps=("c0",),
                                 detail=p2p_detail(role="TRANSFER",
                                                   src_rank=0, dst_rank=2,
                                                   payload_bytes=100,
                                                   participant_count=COUNT)))
    loaded = WorkloadGraph.from_dict(graph.to_dict(), strict=True)
    assert loaded.workload_id() == graph.workload_id()
    assert loaded.to_dict() == graph.to_dict()


def test_tampered_workload_id_is_refused():
    doc = _graph(_collective()).to_dict()
    doc["workload_id"] = "sha256:" + "0" * 64
    with pytest.raises(EvidenceInvalid):
        WorkloadGraph.from_dict(doc, strict=True)


def test_unknown_graph_field_is_refused():
    doc = _graph(_collective()).to_dict()
    doc["extra"] = 1
    with pytest.raises(InvalidInput):
        WorkloadGraph.from_dict(doc, strict=True)


def test_non_parallelism_shape_is_refused():
    with pytest.raises(InvalidInput):
        WorkloadGraph(parallelism={"tp": 4, "pp": 1, "ep": 1, "dp": 1},
                      participant_count=COUNT,
                      operations=(_collective(),))


# ── participant namespace ──────────────────────────────────────────────────

def test_collective_rank_outside_participant_namespace_is_refused():
    with pytest.raises(InvalidInput, match="outside the participant namespace"):
        _graph(_collective(participants=(0, 1, 2, 4)))


def test_owner_outside_participant_namespace_is_refused():
    op = OperationNode(operation_id="a", kind=KIND_COMPUTE, owner=7,
                       detail=compute_detail(duration_ns=10,
                                             participant_count=COUNT))
    with pytest.raises(InvalidInput, match="owner"):
        _graph(op)


def test_rank_is_legal_in_world_but_not_in_namespace():
    """A node valid for an 8-rank namespace is refused by a 4-rank graph."""
    op = OperationNode(operation_id="c0", kind=KIND_COLLECTIVE,
                       detail=collective_detail(
                           collective_kind="ALLREDUCE",
                           participants=(0, 1, 2, 4), payload_bytes=64,
                           participant_count=8))
    with pytest.raises(InvalidInput, match="outside the participant namespace"):
        _graph(op, count=4)
    # ...and the very same node is legal in the 8-rank namespace
    assert _graph(op, count=8).by_id("c0") is op


# ── detail closure and defaults ────────────────────────────────────────────

def test_unknown_operation_kind_is_refused():
    with pytest.raises(InvalidInput, match="unknown kind"):
        OperationNode(operation_id="x", kind="ROUTE", detail={})


def test_unknown_detail_field_is_refused():
    with pytest.raises(InvalidInput, match="unknown fields"):
        OperationNode(operation_id="x", kind=KIND_COMPUTE,
                      detail={"duration_ns": 1, "bogus": 2})


def test_missing_canonical_detail_field_is_refused():
    with pytest.raises(InvalidInput, match="missing canonical field"):
        OperationNode(operation_id="x", kind=KIND_COMPUTE,
                      detail={"duration_ns": 1})


def test_scope_none_is_not_all():
    undeclared = _collective("a", scope=None)
    declared_all = _collective("b", scope="ALL")
    assert _graph(undeclared).workload_id() != _graph(declared_all).workload_id()


def test_compute_defaults_are_explicit_values():
    op = OperationNode(operation_id="k", kind=KIND_COMPUTE,
                       detail=compute_detail(duration_ns=5,
                                             participant_count=COUNT))
    assert op.detail["input_loc"] == "LOCAL"
    assert op.detail["batch_tag"] == "NONE"
    assert op.detail["input_bytes"] is None


def test_unknown_memory_location_is_refused():
    with pytest.raises(InvalidInput, match="unknown memory location"):
        compute_detail(duration_ns=1, input_loc="MARS", participant_count=1)


# ── dependency laws ────────────────────────────────────────────────────────

def test_unknown_dependency_is_refused():
    with pytest.raises(InvalidInput, match="unknown operation"):
        _graph(_collective("a", deps=("ghost",)))


def test_self_dependency_is_refused():
    with pytest.raises(InvalidInput, match="depends on itself"):
        _collective("a", deps=("a",))


def test_dependency_cycle_is_refused():
    a = _collective("a", deps=("b",))
    b = _collective("b", deps=("a",))
    with pytest.raises(InvalidInput, match="cycle"):
        _graph(a, b)


def test_duplicate_operation_id_is_refused():
    with pytest.raises(InvalidInput, match="duplicate operation id"):
        _graph(_collective("a"), _collective("a"))


def test_empty_workload_is_refused():
    with pytest.raises(InvalidInput, match="no operations"):
        _graph()


# ── region structure ───────────────────────────────────────────────────────

def test_stray_expert_end_is_refused():
    with pytest.raises(InvalidInput, match="stray EXPERT_END"):
        _graph(OperationNode(operation_id="e", kind=KIND_EXPERT_END,
                             detail=expert_detail(end=True,
                                                  participant_count=COUNT)))


def test_unclosed_expert_begin_is_refused():
    with pytest.raises(InvalidInput, match="unclosed EXPERT_BEGIN"):
        _graph(OperationNode(operation_id="b", kind=KIND_EXPERT_BEGIN,
                             detail=expert_detail(participant_count=COUNT)))


def test_stray_pim_end_is_refused():
    with pytest.raises(InvalidInput, match="stray PIM_END"):
        _graph(OperationNode(operation_id="p", kind=KIND_PIM_END,
                             detail=pim_end_detail(participant_count=COUNT)))


def test_unclosed_pim_is_refused():
    with pytest.raises(InvalidInput, match="PIM mode is active"):
        _graph(OperationNode(operation_id="p", kind=KIND_PIM_CHANNEL,
                             detail=pim_detail(channel=0,
                                               participant_count=COUNT)))


def test_expert_broadcast_is_refused():
    with pytest.raises(UnsupportedSemantics, match="BROADCAST"):
        expert_detail(collective_kind="BROADCAST", participants=(0, 1),
                      payload_bytes=8, participant_count=COUNT)


def test_expert_collective_fields_without_kind_are_refused():
    with pytest.raises(InvalidInput, match="requires a collective_kind"):
        expert_detail(participants=(0, 1), payload_bytes=8,
                      participant_count=COUNT)


def test_broadcast_requires_explicit_source():
    with pytest.raises(InvalidInput, match="requires an explicit source"):
        collective_detail(collective_kind="BROADCAST",
                          participants=(0, 1, 2, 3), payload_bytes=8,
                          participant_count=COUNT)
    with pytest.raises(InvalidInput, match="not a participating rank"):
        collective_detail(collective_kind="BROADCAST",
                          participants=(0, 1, 2, 3), payload_bytes=8,
                          source=9, participant_count=COUNT)


def test_non_broadcast_source_is_refused():
    with pytest.raises(InvalidInput, match="must not declare a source"):
        collective_detail(collective_kind="ALLREDUCE",
                          participants=(0, 1), payload_bytes=8, source=0,
                          participant_count=COUNT)


def test_p2p_self_transfer_is_refused():
    with pytest.raises(InvalidInput, match="must differ"):
        p2p_detail(role="TRANSFER", src_rank=1, dst_rank=1,
                   payload_bytes=8, participant_count=COUNT)


def test_p2p_unknown_role_is_refused():
    with pytest.raises(InvalidInput, match="P2P role"):
        p2p_detail(role="BROADCASTISH", src_rank=0, dst_rank=1,
                   payload_bytes=8, participant_count=COUNT)


def test_multicast_source_in_destinations_is_refused():
    with pytest.raises(InvalidInput, match="source must not appear"):
        multicast_detail(source_rank=1, destinations=(1, 2), payload_bytes=8,
                         replication="SOURCE_REPLICATION",
                         participant_count=COUNT)


def test_collective_needs_two_participants():
    with pytest.raises(InvalidInput, match="needs >= 2"):
        collective_detail(collective_kind="ALLREDUCE", participants=(0,),
                          payload_bytes=8, participant_count=COUNT)


def test_duplicate_participants_are_refused():
    with pytest.raises(InvalidInput, match="duplicate ranks"):
        collective_detail(collective_kind="ALLREDUCE",
                          participants=(0, 1, 1), payload_bytes=8,
                          participant_count=COUNT)


# ── semantics envelope ─────────────────────────────────────────────────────

def test_phase_consistency_is_enforced():
    op = OperationNode(operation_id="a", kind=KIND_COMPUTE, phase="DECODE",
                       detail=compute_detail(duration_ns=1,
                                             participant_count=COUNT))
    with pytest.raises(InvalidInput, match="one graph, one phase"):
        _graph(op, semantics=WorkloadSemantics(phase="PREFILL"))


def test_unknown_semantics_phase_is_refused():
    with pytest.raises(UnsupportedSemantics):
        WorkloadSemantics(phase="TRAINING")


def test_absent_phase_is_not_prefill():
    assert WorkloadSemantics().phase is None
    assert WorkloadSemantics().identity_dict()["phase"] is None


def test_model_descriptor_name_is_provenance_not_identity():
    a = WorkloadSemantics(model_descriptor_hash="sha256:" + "1" * 64,
                          model_descriptor_name="qwen")
    b = WorkloadSemantics(model_descriptor_hash="sha256:" + "1" * 64,
                          model_descriptor_name="llama")
    assert a.identity_dict() == b.identity_dict()
    assert _graph(_collective(), semantics=a).workload_id() \
        == _graph(_collective(), semantics=b).workload_id()


# ── node reuse / no aliasing ───────────────────────────────────────────────

def test_same_node_is_byte_identical_across_graphs():
    node = _collective(participants=(0, 1), payload=8)
    small = _graph(node, count=4)
    other = WorkloadGraph(parallelism=ParallelismShape(tp=2, pp=1, ep=1, dp=1),
                          participant_count=2, operations=(node,))
    assert small.by_id("c0") is node
    assert other.by_id("c0") is node
    assert node.detail == small.by_id("c0").detail  # frozen: never rewritten
    assert small.workload_id() != other.workload_id()


def test_total_order_is_refused_when_ambiguous():
    a = _collective("a")
    b = _collective("b")
    graph = _graph(a, b)
    with pytest.raises(InvalidInput, match="no unique dependency-derived"):
        graph.require_total_order()
    chained = _graph(a, _collective("b", deps=("a",)))
    assert [o.operation_id for o in chained.require_total_order()] == \
        ["a", "b"]


def test_graph_is_frozen():
    graph = _graph(_collective())
    with pytest.raises(dataclasses.FrozenInstanceError):
        graph.participant_count = 99
