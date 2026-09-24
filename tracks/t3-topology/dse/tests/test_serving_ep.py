"""Executable EP semantics over the canonical serving path (§12).

The vendored LLMServingSim emits dispatch ALLGATHER + per-rank expert
compute + combine REDUCESCATTER (NOT ALLTOALL). The canonical adapter
preserves exactly that: TP/EP participant groups may overlap and the
rank count is never multiplied.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

DSE = Path(__file__).resolve().parent.parent
TESTS = Path(__file__).resolve().parent
sys.path.insert(0, str(DSE))
sys.path.insert(0, str(TESTS))

from veritx_dse.backend import serving_round as sround  # noqa: E402
from veritx_dse.model.placement import ParallelismShape  # noqa: E402
from veritx_dse.simulation import serving_loop as sl  # noqa: E402
from veritx_dse.workload.graph import (  # noqa: E402
    KIND_COMPUTE, KIND_EXPERT_BEGIN, KIND_EXPERT_END,
)


def _shape():
    return ParallelismShape(tp=2, pp=1, ep=1, dp=1)


def _ep_plan():
    return sround.ServingBatchPlan(
        batch_id=0, instance_id=0, request_ids=("r0",),
        participant_ranks=(0, 1), phase="decode", tokens=16,
        collective_kind="ALLREDUCE", collective_bytes=4096,
        compute_ns=10_000, is_ep=True,
        ep_dispatch_kind="ALLGATHER", ep_dispatch_bytes=2048,
        ep_combine_kind="REDUCESCATTER", ep_combine_bytes=1024,
        expert_compute_ns=5_000)


def test_ep_lowers_to_dispatch_expert_combine_not_alltoall():
    plan = _ep_plan()
    graph = plan.to_workload_graph(parallelism=_shape())
    kinds = [op.kind for op in graph.operations]
    assert kinds[0] == KIND_EXPERT_BEGIN
    assert kinds[-1] == KIND_EXPERT_END
    assert "ALLTOALL" not in [
        op.detail.get("collective_kind") for op in graph.operations
        if op.detail is not None
    ]
    begin = graph.operations[0]
    end = graph.operations[-1]
    assert begin.detail["collective_kind"] == "ALLGATHER"
    assert end.detail["collective_kind"] == "REDUCESCATTER"
    experts = [op for op in graph.operations if op.kind == KIND_COMPUTE]
    assert len(experts) == 2
    assert sorted(op.owner for op in experts) == [0, 1]


def test_ep_reuses_the_same_ranks_no_multiplication():
    plan = _ep_plan()
    graph = plan.to_workload_graph(parallelism=_shape())
    seen = set()
    for op in graph.operations:
        detail = op.detail or {}
        for key in ("participants",):
            if key in detail and detail[key] is not None:
                seen.update(tuple(detail[key]))
        if op.owner is not None:
            seen.add(op.owner)
    assert seen == {0, 1}


def test_dense_plans_carry_no_ep_state():
    plan = sround.ServingBatchPlan(
        batch_id=0, instance_id=0, request_ids=("r0",),
        participant_ranks=(0, 1), phase="decode", tokens=16,
        collective_kind="ALLREDUCE", collective_bytes=4096,
        compute_ns=10_000)
    assert "ep_dispatch_kind" not in plan.identity_dict()
    with pytest.raises(sround.ServingRoundError):
        sround.ServingBatchPlan(
            batch_id=0, instance_id=0, request_ids=("r0",),
            participant_ranks=(0, 1), phase="decode", tokens=16,
            collective_kind="ALLREDUCE", collective_bytes=4096,
            compute_ns=10_000, ep_dispatch_bytes=10)


def test_plan_from_round_marks_ep_overlapping_ranks():
    from types import SimpleNamespace

    def _batch(i):
        return SimpleNamespace(batch_id=i, requests=[SimpleNamespace(id="r")],
                               total_len=8, num_prefill=0)

    plan = sround.plan_from_round(
        round_id=0,
        batches={0: _batch(0)},
        instance_ranks={0: (0, 1)},
        participant_count=2, collective_kind="ALLREDUCE",
        collective_bytes_for=lambda tokens: 4096,
        compute_ns_for=lambda tokens: 10_000,
        ep_size=2,
        ep_dispatch_bytes_for=lambda tokens: 2048,
        ep_combine_bytes_for=lambda tokens: 1024,
        expert_compute_ns_for=lambda tokens: 5_000)
    assert plan.batches[0].is_ep
    assert plan.batches[0].participant_ranks == (0, 1)
    graph = plan.to_workload_graph(parallelism=_shape())
    assert graph.operations[0].kind == KIND_EXPERT_BEGIN


def test_ep_size_beyond_ranks_refuses():
    from types import SimpleNamespace

    def _batch(i):
        return SimpleNamespace(batch_id=i, requests=[SimpleNamespace(id="r")],
                               total_len=8, num_prefill=0)

    with pytest.raises(sround.ServingRoundError):
        sround.plan_from_round(
            round_id=0, batches={0: _batch(0)},
            instance_ranks={0: (0, 1)}, participant_count=2,
            collective_kind="ALLREDUCE",
            collective_bytes_for=lambda tokens: 4096,
            compute_ns_for=lambda tokens: 10_000,
            ep_size=4,
            ep_dispatch_bytes_for=lambda tokens: 2048,
            ep_combine_bytes_for=lambda tokens: 1024,
            expert_compute_ns_for=lambda tokens: 5_000)


def test_ep_profile_fields_join_the_identity():
    import dataclasses
    base = sl.CertifiedServiceProfile(model="m")
    mutated = dataclasses.replace(base, ep_size=2)
    assert mutated.profile_id() != base.profile_id()
    mutated2 = dataclasses.replace(base, ep_dispatch_bytes_per_rank=1)
    assert mutated2.profile_id() != base.profile_id()
