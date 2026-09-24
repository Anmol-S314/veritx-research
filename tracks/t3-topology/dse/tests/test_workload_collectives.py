"""Collective schedule + logical-message expansion tests.

The oracle here is deliberately INDEPENDENT: it re-derives the pinned step /
message / byte laws from the specification text, in this test module, using
its own equations. Production (``workload/collectives.py``) must never
import it, and this module must never call production to compute the
expected value — otherwise the differential test degenerates into "the spec
agrees with itself".
"""
from __future__ import annotations

import inspect

import pytest

from veritx_dse.core.errors import (
    ConservationFailed, InvalidInput, UnsupportedSchedule,
)
from veritx_dse.model.placement import ParallelismShape
from veritx_dse.workload import collectives as production_collectives
from veritx_dse.workload import messages as production_messages
from veritx_dse.workload.collectives import collective_schedule
from veritx_dse.workload.graph import (
    KIND_COLLECTIVE, OperationNode, WorkloadGraph, collective_detail,
)
from veritx_dse.workload.messages import LogicalMessageArtifactV2

SHAPE = ParallelismShape(tp=4, pp=1, ep=1, dp=1)
K = 4
COUNT = 4
KINDS = ("ALLREDUCE", "REDUCESCATTER", "ALLGATHER", "ALLTOALL", "BROADCAST")


# ── the independent reference/oracle equations ─────────────────────────────

def oracle_schedule(kind: str, k: int, b: int) -> dict[str, int]:
    """Spec-derived laws, written here from the declaration, not the code."""
    if kind == "ALLREDUCE":
        chunk = b // k
        return {"steps": 2 * (k - 1), "message_count": 2 * k * (k - 1),
                "message_bytes": chunk,
                "per_rank_sent": 2 * (k - 1) * chunk,
                "aggregate_payload": 2 * (k - 1) * b}
    if kind == "REDUCESCATTER":
        chunk = b // k
        return {"steps": k - 1, "message_count": k * (k - 1),
                "message_bytes": chunk,
                "per_rank_sent": (k - 1) * chunk,
                "aggregate_payload": (k - 1) * b}
    if kind == "ALLGATHER":
        # F-0006: ring ALLGATHER forwards CHUNKS of b/k (like REDUCESCATTER);
        # the previous oracle here used the whole b and over-counted by k.
        chunk = b // k
        return {"steps": k - 1, "message_count": k * (k - 1),
                "message_bytes": chunk,
                "per_rank_sent": (k - 1) * chunk,
                "aggregate_payload": (k - 1) * b}
    if kind == "ALLTOALL":
        chunk = b // k
        return {"steps": 1, "message_count": k * (k - 1),
                "message_bytes": chunk,
                "per_rank_sent": (k - 1) * chunk,
                "aggregate_payload": (k - 1) * b}
    if kind == "BROADCAST":
        return {"steps": 1, "message_count": k - 1, "message_bytes": b,
                "per_rank_sent": (k - 1) * b,
                "aggregate_payload": (k - 1) * b}
    raise AssertionError(kind)


# ── differential: production schedule vs the independent oracle ────────────

@pytest.mark.parametrize("kind", KINDS)
@pytest.mark.parametrize("k", [2, 4, 8])
def test_production_schedule_matches_independent_oracle(kind, k):
    payload = 64 if kind != "ALLGATHER" else 32
    assert payload % k == 0 or kind in ("ALLGATHER", "BROADCAST")
    assert collective_schedule(kind, k, payload) == oracle_schedule(kind, k,
                                                                   payload)


@pytest.mark.parametrize("kind", ("ALLREDUCE", "REDUCESCATTER", "ALLGATHER",
                                  "ALLTOALL"))
def test_non_divisible_payload_is_refused(kind):
    with pytest.raises(UnsupportedSchedule, match="requires B % k == 0"):
        collective_schedule(kind, 4, 10)


def test_unknown_collective_kind_is_refused():
    with pytest.raises(ValueError, match="unsupported collective kind"):
        collective_schedule("SCATTER", 4, 8)


# ── expansion: counts, bytes, per-rank laws ────────────────────────────────

def _artifact(ops) -> LogicalMessageArtifactV2:
    graph = WorkloadGraph(parallelism=SHAPE, participant_count=COUNT,
                          operations=tuple(ops))
    return LogicalMessageArtifactV2(graph=graph)


def _op(op_id, kind, payload=64, participants=tuple(range(K)), *,
        deps=(), **kw):
    return OperationNode(
        operation_id=op_id, kind=KIND_COLLECTIVE, deps=tuple(deps),
        detail=collective_detail(collective_kind=kind,
                                 participants=participants,
                                 payload_bytes=payload,
                                 participant_count=COUNT, **kw))


@pytest.mark.parametrize("kind", KINDS)
def test_expansion_matches_oracle_counts_and_bytes(kind):
    payload = 64 if kind != "ALLGATHER" else 32
    kwargs = {"source": 0} if kind == "BROADCAST" else {}
    artifact = _artifact([_op("c", kind, payload, **kwargs)])
    oracle = oracle_schedule(kind, K, payload)

    assert len(artifact.messages) == oracle["message_count"]
    assert sum(m.payload_bytes for m in artifact.messages) \
        == oracle["aggregate_payload"]
    assert all(m.payload_bytes == oracle["message_bytes"]
               for m in artifact.messages)
    record = artifact.schedules[0]
    assert record.steps == oracle["steps"]
    assert record.message_count == oracle["message_count"]
    assert record.message_bytes == oracle["message_bytes"]
    assert record.per_rank_sent == oracle["per_rank_sent"]
    assert record.aggregate_payload == oracle["aggregate_payload"]
    artifact.validate_conservation()


@pytest.mark.parametrize("kind", ("ALLREDUCE", "REDUCESCATTER", "ALLGATHER"))
def test_per_rank_sent_law_holds(kind):
    payload = 64 if kind != "ALLGATHER" else 32
    artifact = _artifact([_op("c", kind, payload)])
    oracle = oracle_schedule(kind, K, payload)
    per_rank: dict[int, int] = {}
    for m in artifact.messages:
        per_rank[m.src_rank] = per_rank.get(m.src_rank, 0) + m.payload_bytes
    assert set(per_rank) == set(range(K))
    assert set(per_rank.values()) == {oracle["per_rank_sent"]}


def test_broadcast_fans_out_from_the_declared_root():
    artifact = _artifact([_op("c", "BROADCAST", 32, source=2)])
    assert {m.src_rank for m in artifact.messages} == {2}
    assert {m.dst_rank for m in artifact.messages} == {0, 1, 3}
    assert artifact.schedules[0].algorithm == "ROOT_FANOUT"
    assert artifact.schedules[0].message_count == K - 1


def test_ring_algorithms_are_labelled_ring():
    for kind in ("ALLREDUCE", "REDUCESCATTER", "ALLGATHER"):
        artifact = _artifact([_op("c", kind, 32)])
        assert artifact.schedules[0].algorithm == "RING"
    assert _artifact([_op("c", "ALLTOALL", 32)]).schedules[0].algorithm \
        == "DIRECT"


def test_p2p_and_multicast_message_counts():
    from veritx_dse.workload.graph import multicast_detail, p2p_detail
    from veritx_dse.workload.graph import KIND_MULTICAST, KIND_P2P
    p2p = OperationNode(operation_id="p", kind=KIND_P2P,
                        detail=p2p_detail(role="TRANSFER", src_rank=0,
                                          dst_rank=3, payload_bytes=100,
                                          participant_count=COUNT))
    cast = OperationNode(operation_id="m", kind=KIND_MULTICAST,
                         detail=multicast_detail(
                             source_rank=0, destinations=(1, 2, 3),
                             payload_bytes=8,
                             replication="SOURCE_REPLICATION",
                             participant_count=COUNT))
    artifact = _artifact([p2p, cast])
    assert len(artifact.messages_for_operation("p")) == 1
    assert len(artifact.messages_for_operation("m")) == 3
    assert all(m.src_rank == 0 for m in artifact.messages_for_operation("m"))
    assert artifact.validate_conservation() is None


def test_message_ids_are_deterministic_and_ordered():
    artifact = _artifact([_op("c1", "ALLREDUCE", 64),
                          _op("c2", "ALLGATHER", 32, deps=("c1",))])
    again = _artifact([_op("c1", "ALLREDUCE", 64),
                       _op("c2", "ALLGATHER", 32, deps=("c1",))])
    assert [m.canonical() for m in artifact.messages] \
        == [m.canonical() for m in again.messages]
    assert artifact.message_artifact_id() == again.message_artifact_id()
    assert [m.seq for m in artifact.messages] == list(range(len(artifact.messages)))


# ── identity / conservation boundaries ─────────────────────────────────────

def test_artifact_identity_binds_the_graph_parent():
    artifact = _artifact([_op("c", "ALLREDUCE", 64)])
    doc = artifact.to_dict()
    assert doc["workload_id"] == artifact.graph.workload_id()
    loaded = LogicalMessageArtifactV2.from_dict(doc, graph=artifact.graph,
                                                strict=True)
    assert loaded.message_artifact_id() == artifact.message_artifact_id()


def test_forged_message_content_is_refused_on_strict_load():
    from veritx_dse.core.artifact import EvidenceInvalid
    artifact = _artifact([_op("c", "ALLREDUCE", 64)])
    doc = artifact.to_dict()
    doc["messages"][0]["payload_bytes"] += 1
    doc["message_artifact_id"] = artifact.message_artifact_id()  # stale id
    with pytest.raises(EvidenceInvalid, match="content forged"):
        LogicalMessageArtifactV2.from_dict(doc, graph=artifact.graph,
                                           strict=True)


def test_wrong_graph_parent_is_refused_on_strict_load():
    artifact = _artifact([_op("c", "ALLREDUCE", 64)])
    other_graph = WorkloadGraph(
        parallelism=ParallelismShape(tp=2, pp=1, ep=1, dp=1),
        participant_count=2,
        operations=(OperationNode(operation_id="c", kind=KIND_COLLECTIVE,
                                  detail=collective_detail(
                                      collective_kind="ALLREDUCE",
                                      participants=(0, 1), payload_bytes=8,
                                      participant_count=2)),))
    with pytest.raises(InvalidInput, match="does not match the verified"):
        LogicalMessageArtifactV2.from_dict(artifact.to_dict(),
                                           graph=other_graph, strict=True)


def test_send_recv_p2p_role_is_refused_at_expansion():
    from veritx_dse.core.errors import UnsupportedSemantics
    from veritx_dse.workload.graph import KIND_P2P, p2p_detail
    op = OperationNode(operation_id="p", kind=KIND_P2P,
                       detail=p2p_detail(role="SEND", src_rank=0, dst_rank=1,
                                         payload_bytes=8,
                                         participant_count=COUNT))
    with pytest.raises(UnsupportedSemantics, match="not a complete transfer"):
        _artifact([op])


def test_compute_and_pim_operations_generate_no_messages():
    from veritx_dse.workload.graph import (
        KIND_COMPUTE, KIND_PIM_CHANNEL, KIND_PIM_END, compute_detail,
        pim_detail, pim_end_detail,
    )
    ops = (
        OperationNode(operation_id="k", kind=KIND_COMPUTE,
                      detail=compute_detail(duration_ns=10,
                                            participant_count=COUNT)),
        OperationNode(operation_id="pc", kind=KIND_PIM_CHANNEL, deps=("k",),
                      detail=pim_detail(channel=0,
                                        participant_count=COUNT)),
        OperationNode(operation_id="pe", kind=KIND_PIM_END, deps=("pc",),
                      detail=pim_end_detail(participant_count=COUNT)),
    )
    artifact = _artifact(ops)
    assert artifact.messages == ()
    assert artifact.schedules == ()

def test_conservation_detects_a_violated_schedule():
    """If the schedule record and the messages disagree, it is a hard error."""
    artifact = _artifact([_op("c", "ALLREDUCE", 64)])
    record = artifact.schedules[0]
    from dataclasses import replace
    broken = replace(record, aggregate_payload=record.aggregate_payload + 8)
    object.__setattr__(artifact, "_schedules", (broken,))
    with pytest.raises(ConservationFailed, match="aggregate payload"):
        artifact.validate_conservation()


# ── independence sentinels ─────────────────────────────────────────────────

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


def test_production_collective_module_does_not_import_the_oracle():
    source = _stripped_source(production_collectives)
    assert "reference_semantics" not in source
    assert "test_workload" not in source
    assert "oracle" not in source.lower()


def test_messages_module_has_no_reference_oracle():
    source = _stripped_source(production_messages)
    assert "reference_semantics" not in source
    assert "oracle" not in source.lower()
    for forbidden in ("verification", "backend", "booksim", "simulation"):
        assert forbidden not in source
