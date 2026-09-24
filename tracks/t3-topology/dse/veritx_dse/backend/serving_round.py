"""Slice 36 — certified per-round serving qualification and round evidence.

The service loop decides *what* a round means (a real ``Batch`` of real
``Request`` objects).  This module turns that into a qualified canonical
round and authenticates what the runtime actually did.

Two separations matter here:

``stable machine  vs  round workload``
    ``AstraMachineProjection.machine_id`` folds in the projection that
    qualified it, which is correct for one-shot qualification and wrong for a
    live loop where every round has a different batch.  ``physical_id()`` is
    the stable, workload-independent machine identity; each round binds its
    own workload identity *plus* the machine and namespace identities, so the
    three are always authenticated together and a round can never be
    transplanted onto a machine qualified for something else.

``serving intent  vs  physical lowering``
    A ``ServingBatchPlan`` carries serving semantics only (which requests, how
    many tokens, which collective intent, which canonical participant ranks).
    Physical endpoints, ET filenames, communicator groups and BookSim config
    stay canonical (Slices 31-34).  Collectives are lowered as *intent*; the
    certified tier never expands a ring here, because
    ``expansion_authority = ASTRA``.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, Mapping

from veritx_dse.core.artifact import content_hash

SERVING_ROUND_SCHEMA_VERSION = 1
LEDGER_SCHEMA_VERSION = 1

#: Chakra CollectiveCommType numbers, as emitted by the runtime ledger
CHAKRA_COLLECTIVE_TYPE = {"ALLREDUCE": 0, "ALLGATHER": 2, "BROADCAST": 5,
                          "ALLTOALL": 6, "REDUCESCATTER": 7}
_TYPE_NAME_BY_NUMBER = {v: k for k, v in CHAKRA_COLLECTIVE_TYPE.items()}

#: the only collective expansion authority this slice certifies
EXPANSION_AUTHORITY_ASTRA = "astra_comm_coll"
TIER_ASTRA_OWNED_COLLECTIVE = "ASTRA_OWNED_COLLECTIVE_EXECUTION"


class ServingRoundError(ValueError):
    """A round could not be qualified, or the runtime deviated from it."""


# ── dense data-parallel participation (serving/scheduling semantics) ─────

@dataclass(frozen=True)
class DpMemberRecord:
    """One DP group member's participation in a synchronized round.

    ``original_total_len`` is the member's real batch shape; ``padded``
    is the shape it actually executes after quorum padding.  ``is_dummy``
    is explicit -- it is never inferred from an empty request list.
    """

    instance_id: int
    batch_id: int
    is_dummy: bool
    original_total_len: int
    padded_total_len: int

    def identity_dict(self) -> dict[str, Any]:
        return {
            "instance_id": self.instance_id,
            "batch_id": self.batch_id,
            "participation": "DUMMY" if self.is_dummy else "REAL",
            "original_total_len": self.original_total_len,
            "padded_total_len": self.padded_total_len,
        }


@dataclass(frozen=True)
class DpQuorumRecord:
    """One synchronized dense-DP round: the decision, made auditable.

    ``dp_sum_total_len`` is deliberately ``max_total_len`` and NOT
    ``max_total_len * group_size`` -- that is the historical rule and the
    seam a later EP slice will read.
    """

    group_id: str
    members: tuple[DpMemberRecord, ...]
    max_total_len: int
    dp_sum_total_len: int

    def __post_init__(self) -> None:
        if not self.group_id:
            raise ServingRoundError("a DP quorum needs a group id")
        if len(self.members) < 2:
            raise ServingRoundError(
                f"DP group {self.group_id!r} quorum has "
                f"{len(self.members)} member(s)")
        if self.dp_sum_total_len != self.max_total_len:
            raise ServingRoundError(
                "dp_sum_total_len must equal max_total_len, not "
                "max_total_len * group_size")

    def real_members(self) -> tuple[DpMemberRecord, ...]:
        return tuple(m for m in self.members if not m.is_dummy)

    def dummy_members(self) -> tuple[DpMemberRecord, ...]:
        return tuple(m for m in self.members if m.is_dummy)

    def identity_dict(self) -> dict[str, Any]:
        return {
            "group_id": self.group_id,
            "members": [m.identity_dict() for m in self.members],
            "max_total_len": self.max_total_len,
            "dp_sum_total_len": self.dp_sum_total_len,
        }


# ── serving batch plan (serving intent only) ──────────────────────────────

@dataclass(frozen=True)
class ServingBatchPlan:
    """Workload semantics for exactly one serving round.

    Deliberately free of physical placement: no endpoint ids, no ET paths, no
    BookSim configuration.  ``participant_ranks`` are *canonical* workload
    ranks; the canonical namespace owns rank -> endpoint.
    """

    batch_id: int
    instance_id: int
    request_ids: tuple[str, ...]
    participant_ranks: tuple[int, ...]
    phase: str                      # "prefill" | "decode"
    tokens: int
    collective_kind: str
    collective_bytes: int
    compute_ns: int
    #: dense-DP participation.  Defaults keep non-DP plan identities
    #: byte-identical; a dummy is explicit, never inferred from empty requests.
    is_dp_dummy: bool = False
    dp_group_id: str = ""
    #: expert-parallel (MoE) participation.  Defaults keep dense plan
    #: identities byte-identical; EP reuses the same participant ranks
    #: (ep_size <= instance ranks; TP/EP overlap, no rank multiplication).
    #: The executable semantics are dispatch ALLGATHER + per-rank expert
    #: compute + combine REDUCESCATTER, exactly as LLMServingSim emits.
    is_ep: bool = False
    ep_dispatch_kind: str = "ALLGATHER"
    ep_dispatch_bytes: int = 0
    ep_combine_kind: str = "REDUCESCATTER"
    ep_combine_bytes: int = 0
    expert_compute_ns: int = 0

    def __post_init__(self) -> None:
        if self.is_dp_dummy and self.request_ids:
            raise ServingRoundError(
                f"DP dummy for instance {self.instance_id} carries user "
                f"request(s) {list(self.request_ids)}; a dummy retires none")
        if self.is_dp_dummy and not self.dp_group_id:
            raise ServingRoundError(
                "a DP dummy must name the DP group it synchronizes")
        if self.dp_group_id and not self.is_dp_dummy and not self.request_ids:
            raise ServingRoundError(
                "a DP member with no requests is a dummy and must say so")
        if self.is_ep:
            if self.ep_dispatch_kind not in CHAKRA_COLLECTIVE_TYPE:
                raise ServingRoundError(
                    f"unsupported EP dispatch kind "
                    f"{self.ep_dispatch_kind!r}; the certified profile "
                    f"supports {sorted(CHAKRA_COLLECTIVE_TYPE)}")
            if self.ep_combine_kind not in CHAKRA_COLLECTIVE_TYPE:
                raise ServingRoundError(
                    f"unsupported EP combine kind "
                    f"{self.ep_combine_kind!r}; the certified profile "
                    f"supports {sorted(CHAKRA_COLLECTIVE_TYPE)}")
            if self.ep_dispatch_bytes <= 0 or self.ep_combine_bytes <= 0:
                raise ServingRoundError(
                    "an EP batch must carry positive dispatch/combine sizes")
            if self.expert_compute_ns <= 0:
                raise ServingRoundError(
                    "an EP batch must carry positive expert compute")
        elif (self.ep_dispatch_bytes or self.ep_combine_bytes
                or self.expert_compute_ns
                or self.ep_dispatch_kind != "ALLGATHER"
                or self.ep_combine_kind != "REDUCESCATTER"):
            raise ServingRoundError(
                "a dense batch must not carry EP dispatch/combine state; "
                "EP participation is explicit, never inferred")
        if self.phase not in ("prefill", "decode"):
            raise ServingRoundError(
                f"batch phase must be prefill or decode, got {self.phase!r}")
        if not self.participant_ranks:
            raise ServingRoundError(
                f"batch {self.batch_id} has no participant ranks")
        if len(set(self.participant_ranks)) != len(self.participant_ranks):
            raise ServingRoundError(
                f"batch {self.batch_id} repeats a participant rank")
        if self.collective_kind not in CHAKRA_COLLECTIVE_TYPE:
            raise ServingRoundError(
                f"unsupported collective kind {self.collective_kind!r}; the "
                f"certified profile supports "
                f"{sorted(CHAKRA_COLLECTIVE_TYPE)}")
        if self.collective_bytes <= 0:
            raise ServingRoundError(
                "a certified round must carry a positive collective size")
        if self.compute_ns <= 0:
            raise ServingRoundError("compute_ns must be positive")

    @property
    def collective_type_number(self) -> int:
        return CHAKRA_COLLECTIVE_TYPE[self.collective_kind]

    def identity_dict(self) -> dict[str, Any]:
        return {
            "type": "srota/ServingBatchPlan",
            "schema_version": SERVING_ROUND_SCHEMA_VERSION,
            "batch_id": self.batch_id,
            "instance_id": self.instance_id,
            "request_ids": list(self.request_ids),
            "participant_ranks": list(self.participant_ranks),
            "phase": self.phase,
            "tokens": self.tokens,
            "collective_kind": self.collective_kind,
            "collective_type_number": self.collective_type_number,
            "collective_bytes": self.collective_bytes,
            "compute_ns": self.compute_ns,
            **({"dp_group_id": self.dp_group_id,
                "dp_participation": "DUMMY" if self.is_dp_dummy else "REAL"}
               if (self.is_dp_dummy or self.dp_group_id) else {}),
            **({"ep_dispatch_kind": self.ep_dispatch_kind,
                "ep_dispatch_bytes": self.ep_dispatch_bytes,
                "ep_combine_kind": self.ep_combine_kind,
                "ep_combine_bytes": self.ep_combine_bytes,
                "expert_compute_ns": self.expert_compute_ns}
               if self.is_ep else {}),
        }

    def plan_id(self) -> str:
        return content_hash("srota/ServingBatchPlan", 1, self.identity_dict())

    # -- canonical lowering (intent only) ---------------------------------
    def to_workload_graph(self, *, parallelism: Any) -> Any:
        """Lower serving intent to a canonical workload graph.

        The collective is expressed as *intent* with its participant set -- it
        is never expanded into ring messages here.  In EP mode the batch
        lowers to dispatch ALLGATHER + per-rank expert compute + combine
        REDUCESCATTER, exactly as LLMServingSim emits (TP/EP overlap, no
        rank multiplication).
        """
        from veritx_dse.workload.graph import (
            KIND_COLLECTIVE, KIND_COMPUTE, KIND_EXPERT_BEGIN,
            KIND_EXPERT_END, OperationNode, WorkloadGraph,
            collective_detail, compute_detail, expert_detail,
        )
        participants = tuple(sorted(self.participant_ranks))
        count = len(participants)
        if self.is_ep:
            dispatch_id = f"batch{self.batch_id}-ep-dispatch"
            combine_id = f"batch{self.batch_id}-ep-combine"
            expert_ids = tuple(
                f"batch{self.batch_id}-expert-r{rank}"
                for rank in participants)
            expert_ops = []
            prev = dispatch_id
            for op_id, rank in zip(expert_ids, participants):
                expert_ops.append(OperationNode(
                    operation_id=op_id, kind=KIND_COMPUTE, owner=rank,
                    deps=(prev,),
                    detail=compute_detail(
                        duration_ns=self.expert_compute_ns,
                        participant_count=count)))
                prev = op_id
            operations = (
                OperationNode(
                    operation_id=dispatch_id, kind=KIND_EXPERT_BEGIN,
                    detail=expert_detail(
                        collective_kind=self.ep_dispatch_kind,
                        participants=participants,
                        payload_bytes=self.ep_dispatch_bytes,
                        participant_count=count)),
                *expert_ops,
                OperationNode(
                    operation_id=combine_id, kind=KIND_EXPERT_END,
                    deps=(prev,),
                    detail=expert_detail(
                        end=True, collective_kind=self.ep_combine_kind,
                        participants=participants,
                        payload_bytes=self.ep_combine_bytes,
                        participant_count=count)),
            )
            return WorkloadGraph(
                parallelism=parallelism, participant_count=count,
                operations=operations)
        operations = (
            OperationNode(operation_id=f"batch{self.batch_id}-{self.phase}",
                          kind=KIND_COMPUTE,
                          detail=compute_detail(duration_ns=self.compute_ns,
                                                participant_count=count)),
            OperationNode(operation_id=f"batch{self.batch_id}-tp",
                          kind=KIND_COLLECTIVE,
                          deps=(f"batch{self.batch_id}-{self.phase}",),
                          detail=collective_detail(
                              collective_kind=self.collective_kind,
                              participants=participants,
                              payload_bytes=self.collective_bytes,
                              participant_count=count)),
        )
        return WorkloadGraph(parallelism=parallelism, participant_count=count,
                             operations=operations)

    def to_round_projection(self, *, resolved_fabric: Any, mapping: Any,
                            attachment: Any, parallelism: Any) -> Any:
        """A qualified ``AstraWorkloadProjection`` for this round."""
        from veritx_dse.backend.astra import AstraWorkloadProjection
        from veritx_dse.workload.messages import LogicalMessageArtifactV2
        graph = self.to_workload_graph(parallelism=parallelism)
        logical = LogicalMessageArtifactV2(graph=graph)
        return AstraWorkloadProjection.build(
            logical=logical, resolved_fabric=resolved_fabric,
            mapping=mapping, attachment=attachment,
            et_granularity="collectives")


def plan_from_batch(batch: Any, *, instance_id: int, participant_ranks: Iterable[int],
                    collective_kind: str, collective_bytes: int,
                    compute_ns: int, request_ids: Iterable[str] = ()
                    ) -> ServingBatchPlan:
    """Derive a plan from a *real* LLMServingSim ``Batch``.

    Only fields the batch actually owns are read from it: the batch id, its
    request list and whether it is a prefill or decode batch.  Sizes and
    durations are serving-semantics inputs supplied by the certified profile;
    nothing about placement is taken from the batch.
    """
    batch_id = getattr(batch, "batch_id", None)
    if not isinstance(batch_id, int):
        raise ServingRoundError(
            "plan_from_batch requires a real Batch with an integer batch_id")
    phase = "prefill" if getattr(batch, "num_prefill", 0) else "decode"
    ids = tuple(str(r) for r in request_ids) or tuple(
        str(getattr(req, "id", index))
        for index, req in enumerate(getattr(batch, "requests", ()) or ()))
    return ServingBatchPlan(
        batch_id=batch_id, instance_id=instance_id,
        request_ids=ids, participant_ranks=tuple(sorted(participant_ranks)),
        phase=phase, tokens=int(getattr(batch, "total_len", 0) or 0),
        collective_kind=collective_kind, collective_bytes=collective_bytes,
        compute_ns=compute_ns)


def plan_from_round(*, round_id: int, batches: Mapping[int, Any],
                    participant_ranks: Iterable[int], collective_kind: str,
                    collective_bytes: int, compute_ns: int) -> ServingBatchPlan:
    """One *global* round plan over every instance that has a real batch.

    A certified round carries one communicator group, so it spans the full
    participant set; ``batches`` maps serving instance -> real ``Batch``.
    Only fields a real batch owns are read.  The phase is prefill if *any*
    instance is prefilling, because the round's collective is one workload
    and a mixed round must not be labelled decode.

    ``instance_id = -1`` marks a round that belongs to no single instance;
    the plan identity still binds every contributing batch id and request id.
    """
    if not batches:
        raise ServingRoundError("a round requires at least one real batch")
    ids: list[str] = []
    tokens = 0
    phase = "decode"
    for instance_id in sorted(batches):
        batch = batches[instance_id]
        batch_id = getattr(batch, "batch_id", None)
        if not isinstance(batch_id, int):
            raise ServingRoundError(
                f"instance {instance_id} supplied a non-Batch with no "
                "integer batch_id")
        for request in getattr(batch, "requests", ()) or ():
            ids.append(f"inst{instance_id}:req{getattr(request, 'id', len(ids))}")
        tokens += int(getattr(batch, "total_len", 0) or 0)
        if getattr(batch, "num_prefill", 0):
            phase = "prefill"
    if not ids:
        raise ServingRoundError(
            "a round's batches carry no requests; an empty round is not "
            "service evidence")
    return ServingBatchPlan(
        batch_id=int(round_id), instance_id=-1, request_ids=tuple(ids),
        participant_ranks=tuple(sorted(participant_ranks)), phase=phase,
        tokens=tokens, collective_kind=collective_kind,
        collective_bytes=collective_bytes, compute_ns=compute_ns)


# ── the round plan: one batch plan per scheduled instance ────────────────

ROUND_PLAN_SCHEMA_VERSION = 1


def compute_operation_id(*, round_id: int, instance_id: int, batch_id: int,
                         rank: int) -> str:
    """Globally unambiguous owned-compute operation id.

    ``batch_id`` alone is NOT unique: every ``Scheduler`` numbers its own
    batches from zero, so two instances routinely produce batch 0.
    """
    return (f"round{round_id}-inst{instance_id}-batch{batch_id}"
            f"-compute-r{rank}")


def collective_operation_id(*, round_id: int, instance_id: int,
                            batch_id: int) -> str:
    return f"round{round_id}-inst{instance_id}-batch{batch_id}-tp"


@dataclass(frozen=True)
class ServingRoundPlan:
    """One service round: the serving batches of every scheduled instance.

    This is a *container*, not a workload model.  Each instance keeps its own
    ``ServingBatchPlan`` -- its own ranks, phase, tokens, collective size and
    compute -- so independent TP groups never collapse into one collective.
    """

    round_id: int
    participant_count: int
    batches: tuple[ServingBatchPlan, ...]
    #: dense-DP quorums resolved in this round (empty for non-DP rounds)
    dp_quorums: tuple[DpQuorumRecord, ...] = ()
    schema_version: int = ROUND_PLAN_SCHEMA_VERSION

    def __post_init__(self) -> None:
        if not self.batches:
            raise ServingRoundError(
                "a round requires at least one scheduled instance")
        if self.participant_count <= 0:
            raise ServingRoundError("participant_count must be positive")
        ids = [b.instance_id for b in self.batches]
        if len(set(ids)) != len(ids):
            raise ServingRoundError(
                f"a round repeats a serving instance: {sorted(ids)}")
        if ids != sorted(ids):
            raise ServingRoundError(
                "a round's batches must be ordered by instance id")
        for batch in self.batches:
            for rank in batch.participant_ranks:
                if not 0 <= rank < self.participant_count:
                    raise ServingRoundError(
                        f"instance {batch.instance_id} names rank {rank} "
                        f"outside the serving participant namespace "
                        f"[0, {self.participant_count})")

    # -- queries ----------------------------------------------------------
    def instance_ids(self) -> tuple[int, ...]:
        return tuple(b.instance_id for b in self.batches)

    def batch_for(self, instance_id: int) -> ServingBatchPlan:
        for batch in self.batches:
            if batch.instance_id == instance_id:
                return batch
        raise ServingRoundError(f"no batch for instance {instance_id}")

    def operation_ids(self) -> tuple[str, ...]:
        ids: list[str] = []
        for batch in self.batches:
            for rank in batch.participant_ranks:
                ids.append(compute_operation_id(
                    round_id=self.round_id, instance_id=batch.instance_id,
                    batch_id=batch.batch_id, rank=rank))
            ids.append(collective_operation_id(
                round_id=self.round_id, instance_id=batch.instance_id,
                batch_id=batch.batch_id))
        return tuple(ids)

    def identity_dict(self) -> dict[str, Any]:
        return {
            "type": "srota/ServingRoundPlan",
            "schema_version": self.schema_version,
            "round_id": self.round_id,
            "participant_count": self.participant_count,
            "batches": [batch.identity_dict() for batch in self.batches],
            **({"dp_quorums": [q.identity_dict() for q in self.dp_quorums]}
               if self.dp_quorums else {}),
        }

    def plan_id(self) -> str:
        return content_hash("srota/ServingRoundPlan", 1, self.identity_dict())

    # -- canonical lowering ------------------------------------------------
    def to_workload_graph(self, *, parallelism: Any) -> Any:
        """One owned compute chain + one TP collective per instance.

        The graph's participant namespace is the whole serving namespace, so
        operation participant sets stay explicit: a TP group of two ranks in
        an eight-rank namespace is legal without inventing a DP axis.
        EP batches lower to dispatch + expert compute + combine over the
        same ranks (no rank multiplication).
        """
        from veritx_dse.workload.graph import (
            KIND_COLLECTIVE, KIND_COMPUTE, KIND_EXPERT_BEGIN,
            KIND_EXPERT_END, OperationNode, WorkloadGraph,
            collective_detail, compute_detail, expert_detail,
        )
        operations: list[Any] = []
        for batch in self.batches:
            participants = tuple(sorted(batch.participant_ranks))
            if batch.is_ep:
                dispatch_id = collective_operation_id(
                    round_id=self.round_id, instance_id=batch.instance_id,
                    batch_id=batch.batch_id) + "-ep-dispatch"
                combine_id = collective_operation_id(
                    round_id=self.round_id, instance_id=batch.instance_id,
                    batch_id=batch.batch_id) + "-ep-combine"
                # Chain expert computes positionally: the canonical graph
                # requires a unique dependency-derived order, so parallel
                # expert ranks migrate to an explicit chain (structural,
                # not temporal — service time is still the max rank).
                prev_ep = dispatch_id
                operations.append(OperationNode(
                    operation_id=dispatch_id, kind=KIND_EXPERT_BEGIN,
                    detail=expert_detail(
                        collective_kind=batch.ep_dispatch_kind,
                        participants=participants,
                        payload_bytes=batch.ep_dispatch_bytes,
                        participant_count=self.participant_count)))
                for rank in participants:
                    op_id = (f"round{self.round_id}-inst{batch.instance_id}"
                             f"-batch{batch.batch_id}-expert-r{rank}")
                    operations.append(OperationNode(
                        operation_id=op_id, kind=KIND_COMPUTE, owner=rank,
                        deps=(prev_ep,),
                        detail=compute_detail(
                            duration_ns=batch.expert_compute_ns,
                            participant_count=self.participant_count)))
                    prev_ep = op_id
                operations.append(OperationNode(
                    operation_id=combine_id, kind=KIND_EXPERT_END,
                    deps=(prev_ep,),
                    detail=expert_detail(
                        end=True, collective_kind=batch.ep_combine_kind,
                        participants=participants,
                        payload_bytes=batch.ep_combine_bytes,
                        participant_count=self.participant_count)))
                continue
            compute_ids = []
            for rank in participants:
                op_id = compute_operation_id(
                    round_id=self.round_id, instance_id=batch.instance_id,
                    batch_id=batch.batch_id, rank=rank)
                compute_ids.append(op_id)
                operations.append(OperationNode(
                    operation_id=op_id, kind=KIND_COMPUTE, owner=rank,
                    detail=compute_detail(
                        duration_ns=batch.compute_ns,
                        participant_count=self.participant_count)))
            operations.append(OperationNode(
                operation_id=collective_operation_id(
                    round_id=self.round_id, instance_id=batch.instance_id,
                    batch_id=batch.batch_id),
                kind=KIND_COLLECTIVE, deps=tuple(compute_ids),
                detail=collective_detail(
                    collective_kind=batch.collective_kind,
                    participants=participants,
                    payload_bytes=batch.collective_bytes,
                    participant_count=self.participant_count)))
        return WorkloadGraph(parallelism=parallelism,
                             participant_count=self.participant_count,
                             operations=tuple(operations))

    def to_round_projection(self, *, resolved_fabric: Any, mapping: Any,
                            attachment: Any, parallelism: Any) -> Any:
        from veritx_dse.backend.astra import AstraWorkloadProjection
        from veritx_dse.workload.messages import LogicalMessageArtifactV2
        graph = self.to_workload_graph(parallelism=parallelism)
        return AstraWorkloadProjection.build(
            logical=LogicalMessageArtifactV2(graph=graph),
            resolved_fabric=resolved_fabric, mapping=mapping,
            attachment=attachment, et_granularity="collectives")


def plan_from_round(*, round_id: int, batches: Mapping[int, Any],
                    instance_ranks: Mapping[int, tuple[int, ...]],
                    participant_count: int, collective_kind: str,
                    collective_bytes_for: Any,
                    compute_ns_for: Any,
                    dummy_instances: frozenset[int] = frozenset(),
                    dp_group_ids: Mapping[int, str] | None = None,
                    dp_quorums: tuple[DpQuorumRecord, ...] = (),
                    ep_size: int = 1,
                    ep_dispatch_kind: str = "ALLGATHER",
                    ep_combine_kind: str = "REDUCESCATTER",
                    ep_dispatch_bytes_for: Any = None,
                    ep_combine_bytes_for: Any = None,
                    expert_compute_ns_for: Any = None,
                    ) -> ServingRoundPlan:
    """Build one round plan from the real ``Batch`` of each instance.

    Only fields a real batch owns are read from it (id, requests, total_len,
    prefill/decode).  The declared profile values are computed per batch --
    never over an aggregate token count -- and, for DP members, only AFTER
    quorum padding, so ``batch.total_len`` here is the *executed* shape.

    ``dummy_instances`` names the members whose batch is an explicit DP dummy:
    an empty request list is accepted for those and refused for everyone else,
    so an arbitrary empty batch can never masquerade as DP participation.
    """
    if not batches:
        raise ServingRoundError("a round requires at least one real batch")
    dp_group_ids = dict(dp_group_ids or {})
    is_ep = ep_size > 1
    if is_ep:
        for instance_id in sorted(batches):
            ranks = instance_ranks.get(instance_id, ())
            if len(ranks) < ep_size:
                raise ServingRoundError(
                    f"EP size {ep_size} exceeds the ranks bound to serving "
                    f"instance {instance_id} ({len(ranks)}); TP/EP groups "
                    "overlap, the rank count is never multiplied")
    plans: list[ServingBatchPlan] = []
    for instance_id in sorted(batches):
        batch = batches[instance_id]
        batch_id = getattr(batch, "batch_id", None)
        if not isinstance(batch_id, int):
            raise ServingRoundError(
                f"instance {instance_id} supplied a non-Batch with no "
                "integer batch_id")
        if instance_id not in instance_ranks:
            raise ServingRoundError(
                f"no canonical ranks are bound to serving instance "
                f"{instance_id}")
        is_dummy = instance_id in dummy_instances
        ids = tuple(f"inst{instance_id}:req{getattr(request, 'id', index)}"
                    for index, request in
                    enumerate(getattr(batch, "requests", ()) or ()))
        if not ids and not is_dummy:
            raise ServingRoundError(
                f"instance {instance_id} scheduled a batch with no requests")
        tokens = int(getattr(batch, "total_len", 0) or 0)
        plans.append(ServingBatchPlan(
            batch_id=batch_id, instance_id=instance_id, request_ids=ids,
            participant_ranks=tuple(sorted(instance_ranks[instance_id])),
            phase="prefill" if getattr(batch, "num_prefill", 0) else "decode",
            tokens=tokens, collective_kind=collective_kind,
            collective_bytes=int(collective_bytes_for(tokens=tokens)),
            compute_ns=int(compute_ns_for(tokens=tokens)),
            is_dp_dummy=is_dummy,
            dp_group_id=dp_group_ids.get(instance_id, ""),
            is_ep=is_ep,
            ep_dispatch_kind=ep_dispatch_kind,
            ep_dispatch_bytes=int(ep_dispatch_bytes_for(tokens=tokens))
            if is_ep and ep_dispatch_bytes_for is not None else 0,
            ep_combine_kind=ep_combine_kind,
            ep_combine_bytes=int(ep_combine_bytes_for(tokens=tokens))
            if is_ep and ep_combine_bytes_for is not None else 0,
            expert_compute_ns=int(expert_compute_ns_for(tokens=tokens))
            if is_ep and expert_compute_ns_for is not None else 0))
    return ServingRoundPlan(round_id=int(round_id),
                            participant_count=participant_count,
                            batches=tuple(plans), dp_quorums=dp_quorums)


# ── collective ledger validation (§9) ─────────────────────────────────────

@dataclass(frozen=True)
class CollectiveContract:
    """The exact runtime contract of ONE collective operation.

    Keyed by the ASTRA node id, so two collectives that share a kind and byte
    size but differ in membership stay distinguishable.
    """

    operation_id: str
    astra_node_id: int
    collective_kind: str
    payload_bytes: int
    endpoints: tuple[int, ...]

    def identity_dict(self) -> dict[str, Any]:
        return {
            "operation_id": self.operation_id,
            "astra_node_id": self.astra_node_id,
            "collective_kind": self.collective_kind,
            "payload_bytes": self.payload_bytes,
            "endpoints": list(self.endpoints),
        }


def collective_contract(*, projection: Any, binding: Any
                        ) -> tuple[CollectiveContract, ...]:
    """Derive the expected runtime contract from projection + binding.

    Node ids come from the projection's own deterministic node plan, which is
    the same plan ``write_chakra`` emits, so the contract cannot drift from
    what the runtime was actually given.
    """
    node_ids = dict(projection.collective_node_ids())
    rows: list[CollectiveContract] = []
    for op_id, kind, payload, _participants in projection.collective_operations:
        if op_id not in node_ids:
            raise ServingRoundError(
                f"collective {op_id!r} has no emitted Chakra node id")
        rows.append(CollectiveContract(
            operation_id=op_id, astra_node_id=node_ids[op_id],
            collective_kind=kind, payload_bytes=payload,
            endpoints=binding.membership_for(op_id)))
    if not rows:
        raise ServingRoundError("the round declares no collective")
    return tuple(rows)


def validate_collective_ledger_contract(
        entries: tuple[LedgerCollective, ...],
        *, contract: tuple[CollectiveContract, ...]) -> None:
    """Fail closed unless every collective matches its own node's contract.

    Aggregate counts are not evidence: each collective is checked against its
    own ASTRA node id, its own membership, its own submitter set and its own
    declared size/type, and unexpected collective nodes refuse.
    """
    by_node: dict[int, list[LedgerCollective]] = {}
    for entry in entries:
        by_node.setdefault(entry.astra_node, []).append(entry)
    expected_nodes = {row.astra_node_id for row in contract}
    unexpected = sorted(set(by_node) - expected_nodes)
    if unexpected:
        raise ServingRoundError(
            f"the runtime submitted collective node id(s) {unexpected} that "
            "this round never projected")

    for row in contract:
        submissions = by_node.get(row.astra_node_id, [])
        if not submissions:
            raise ServingRoundError(
                f"the runtime never submitted collective "
                f"{row.operation_id!r} (ASTRA node {row.astra_node_id}); "
                "the projected collective was not executed")
        kinds = {entry.kind for entry in submissions}
        if kinds != {row.collective_kind}:
            raise ServingRoundError(
                f"collective {row.operation_id!r} (node "
                f"{row.astra_node_id}): projected {row.collective_kind} but "
                f"the runtime submitted {sorted(k for k in kinds if k)}")
        sizes = {entry.comm_size for entry in submissions}
        if sizes != {row.payload_bytes}:
            raise ServingRoundError(
                f"collective {row.operation_id!r} (node "
                f"{row.astra_node_id}): projected {row.payload_bytes} bytes "
                f"but the runtime submitted {sorted(sizes)}")
        for entry in submissions:
            if not entry.has_group:
                raise ServingRoundError(
                    f"collective {row.operation_id!r}: rank {entry.rank} "
                    "submitted without a communicator group")
            if tuple(sorted(entry.members)) != row.endpoints:
                raise ServingRoundError(
                    f"collective {row.operation_id!r} (node "
                    f"{row.astra_node_id}): projected membership "
                    f"{list(row.endpoints)} but the runtime used "
                    f"{list(entry.members)}")
        submitters = {entry.rank for entry in submissions}
        if submitters != set(row.endpoints):
            missing = sorted(set(row.endpoints) - submitters)
            extra = sorted(submitters - set(row.endpoints))
            raise ServingRoundError(
                f"collective {row.operation_id!r} (node "
                f"{row.astra_node_id}) was submitted by {len(submitters)} of "
                f"{len(row.endpoints)} endpoints (missing {missing}, "
                f"unexpected {extra})")


@dataclass(frozen=True)
class LedgerCollective:
    """One parsed ``[LEDGER][COLL_SUBMIT]`` -- the runtime's own statement."""

    rank: int
    astra_node: int
    comm_type: int
    comm_size: int
    members: tuple[int, ...]
    has_group: bool
    tick: int

    @property
    def kind(self) -> str | None:
        return _TYPE_NAME_BY_NUMBER.get(self.comm_type)


def parse_collective_ledger(lines: Iterable[str]
                            ) -> tuple[LedgerCollective, ...]:
    """Structural parse of the runtime's collective-submission ledger."""
    import re
    pattern = re.compile(
        r"\[LEDGER\]\[COLL_SUBMIT\]\s+rank=(\d+)\s+astra_node=(\d+)\s+"
        r"comm_type=(\d+)\s+comm_size=(\d+)\s+priority=(\d+)\s+"
        r"involved_dims=(\S+)\s+group_members=(\S+)\s+tick=(\d+)")
    parsed: list[LedgerCollective] = []
    for line in lines:
        match = pattern.search(line)
        if match is None:
            continue
        members_text = match.group(7)
        if members_text in ("none", "-", ""):
            members: tuple[int, ...] = ()
            has_group = False
        else:
            try:
                members = tuple(int(tok) for tok in
                                members_text.strip("{}[]").split(",") if tok)
            except ValueError as exc:
                raise ServingRoundError(
                    f"malformed ledger membership {members_text!r}") from exc
            has_group = True
        parsed.append(LedgerCollective(
            rank=int(match.group(1)), astra_node=int(match.group(2)),
            comm_type=int(match.group(3)), comm_size=int(match.group(4)),
            members=members, has_group=has_group, tick=int(match.group(8))))
    return tuple(parsed)


def validate_collective_ledger(entries: tuple[LedgerCollective, ...], *,
                               plan: ServingBatchPlan,
                               expected_members: tuple[int, ...]) -> None:
    """Fail closed when the runtime's ledger contradicts the projected round.

    The ledger is ASTRA's own record of what it expanded, so a disagreement is
    an execution deviation, not a cosmetic difference.
    """
    if not entries:
        raise ServingRoundError(
            f"the runtime emitted no [LEDGER][COLL_SUBMIT] for batch "
            f"{plan.batch_id}; the projected collective was never submitted")

    kinds = {entry.kind for entry in entries}
    if kinds != {plan.collective_kind}:
        raise ServingRoundError(
            f"collective type mismatch: projected {plan.collective_kind} "
            f"(#{plan.collective_type_number}) but the runtime submitted "
            f"{sorted(k for k in kinds if k)}")

    sizes = {entry.comm_size for entry in entries}
    if len(sizes) != 1:
        raise ServingRoundError(
            f"the runtime submitted inconsistent collective sizes {sizes}")
    submitted = sizes.pop()
    if submitted != plan.collective_bytes:
        raise ServingRoundError(
            f"collective byte-size mismatch: projected "
            f"{plan.collective_bytes} but the runtime submitted {submitted}")

    expected = tuple(sorted(expected_members))
    for entry in entries:
        if not entry.has_group:
            raise ServingRoundError(
                f"rank {entry.rank} submitted the collective without a "
                "communicator group; the projected round assigned one")
        if tuple(sorted(entry.members)) != expected:
            raise ServingRoundError(
                f"collective membership mismatch for rank {entry.rank}: "
                f"projected {list(expected)} but the runtime used "
                f"{list(entry.members)}")

    ranks = {entry.rank for entry in entries}
    if not ranks <= set(expected):
        raise ServingRoundError(
            f"the runtime submitted the collective from ranks "
            f"{sorted(ranks - set(expected))} outside the projected "
            "participant set")
    # The NUMBER of submissions is part of the contract, not just their
    # content: every participant submits the collective, so a ledger holding
    # only some ranks' lines must not validate green.  A subset check alone
    # accepts a single submission for a 16-rank round -- which is exactly how
    # a truncated/partially-evicted ledger slipped through once.
    if ranks != set(expected):
        missing = sorted(set(expected) - ranks)
        raise ServingRoundError(
            f"the runtime submitted the collective from only {len(ranks)} of "
            f"{len(set(expected))} participant ranks (missing {missing})")


# ── round qualification (§6) ──────────────────────────────────────────────

@dataclass(frozen=True)
class AstraServingRoundQualification:
    """Round workload identity + machine identity + namespace identity."""

    physical_machine_id: str
    machine_id: str
    plan_id: str
    round_projection_id: str
    namespace_id: str
    participant_mapping_id: str
    serving_binding_id: str
    staged_workload_id: str
    communicator_group_id: str
    backend_id: str
    astra_binary_sha256: str
    et_granularity: str
    expansion_authority: str
    network_evidence_tier: str
    #: the round's collective binding -- round-specific membership over the
    #: stable namespace; empty for historical namespace-group rounds
    collective_binding_id: str = ""
    #: per-collective runtime contract, ordered by operation id
    collective_contract: tuple[CollectiveContract, ...] = ()
    #: dense-DP quorums synchronized in this round
    dp_quorums: tuple[DpQuorumRecord, ...] = ()
    schema_version: int = SERVING_ROUND_SCHEMA_VERSION

    def __post_init__(self) -> None:
        if self.expansion_authority != EXPANSION_AUTHORITY_ASTRA:
            raise ServingRoundError(
                f"certified rounds require {EXPANSION_AUTHORITY_ASTRA}, got "
                f"{self.expansion_authority!r}")
        if self.network_evidence_tier != TIER_ASTRA_OWNED_COLLECTIVE:
            raise ServingRoundError(
                f"certified rounds require {TIER_ASTRA_OWNED_COLLECTIVE}")
        for name in ("physical_machine_id", "machine_id", "plan_id",
                     "round_projection_id", "namespace_id",
                     "participant_mapping_id", "staged_workload_id",
                     "communicator_group_id", "astra_binary_sha256"):
            if not getattr(self, name):
                raise ServingRoundError(
                    f"round qualification is missing {name}")

    def identity_dict(self) -> dict[str, Any]:
        return {
            "type": "srota/AstraServingRoundQualification",
            "schema_version": self.schema_version,
            "physical_machine_id": self.physical_machine_id,
            "machine_id": self.machine_id,
            "plan_id": self.plan_id,
            "round_projection_id": self.round_projection_id,
            "namespace_id": self.namespace_id,
            "participant_mapping_id": self.participant_mapping_id,
            "serving_binding_id": self.serving_binding_id,
            "staged_workload_id": self.staged_workload_id,
            "communicator_group_id": self.communicator_group_id,
            "backend_id": self.backend_id,
            "astra_binary_sha256": self.astra_binary_sha256,
            "et_granularity": self.et_granularity,
            "expansion_authority": self.expansion_authority,
            "network_evidence_tier": self.network_evidence_tier,
            **({"collective_binding_id": self.collective_binding_id,
                "collective_contract": [row.identity_dict()
                                        for row in self.collective_contract]}
               if self.collective_binding_id else {}),
            **({"dp_quorums": [q.identity_dict() for q in self.dp_quorums]}
               if self.dp_quorums else {}),
        }

    def round_id(self) -> str:
        return content_hash("srota/AstraServingRoundQualification", 1,
                            self.identity_dict())


def qualify_round(*, machine: Any, plan: Any, backend: Any,
                  staged: Any, directory: str | Path,
                  resolved_fabric: Any, mapping: Any, attachment: Any,
                  parallelism: Any, collective_binding: Any = None,
                  dp_quorums: Any = None
                  ) -> tuple[AstraServingRoundQualification, Any]:
    """Qualify one serving round against the stable machine + namespace.

    ``collective_binding`` supplies the round's own collective memberships and
    communicator groups.  Without one, the stable namespace's groups are used
    (the historical single-group behaviour).  ``dp_quorums`` defaults to the
    plan's own record, so DP participation can never be qualified away.
    """
    backend.assert_network_authority()
    projection = plan.to_round_projection(
        resolved_fabric=resolved_fabric, mapping=mapping,
        attachment=attachment, parallelism=parallelism)
    if projection.expansion_authority() != EXPANSION_AUTHORITY_ASTRA:
        raise ServingRoundError(
            "the certified round lowered to "
            f"{projection.expansion_authority()}; canonical-message mode is "
            "not certified for serving")
    namespace = backend.binding.namespace
    participants = namespace.participant_endpoints()
    staged_members = tuple(sorted(endpoint for endpoint, _ in
                                  staged.endpoint_files))
    if not set(staged_members) <= set(participants):
        raise ServingRoundError(
            f"staged endpoints {list(staged_members)} are not canonical "
            f"participants {list(participants)}")
    if collective_binding is None:
        # historical: one round over the whole participant set
        if staged_members != participants:
            raise ServingRoundError(
                f"staged endpoints {list(staged_members)} do not match the "
                f"canonical participant endpoints {list(participants)}")
    else:
        # a round stages exactly the endpoints its collectives name; an idle
        # serving instance stages nothing and must not be forced to work
        needed: set[int] = set()
        for _op_id, members, _mechanism in collective_binding.operations:
            needed |= set(members)
        if not needed <= set(staged_members):
            raise ServingRoundError(
                "the round's collectives name endpoint(s) "
                f"{sorted(needed - set(staged_members))} that were never "
                "staged")
    groups = (collective_binding.groups if collective_binding is not None
              else backend.binding.namespace.groups)
    contract = (collective_contract(projection=projection,
                                    binding=collective_binding)
                if collective_binding is not None else ())
    qualification = AstraServingRoundQualification(
        physical_machine_id=machine.physical_id(),
        machine_id=machine.machine_id(),
        plan_id=plan.plan_id(),
        round_projection_id=projection.projection_id(),
        namespace_id=namespace.namespace_id(),
        participant_mapping_id=namespace.participant_mapping_id,
        serving_binding_id=backend.binding.binding_id(),
        staged_workload_id=staged.translation_id,
        communicator_group_id=groups.groups_id(),
        collective_binding_id=(collective_binding.binding_id()
                               if collective_binding is not None else ""),
        collective_contract=contract,
        dp_quorums=tuple(getattr(plan, "dp_quorums", ())
                         if dp_quorums is None else dp_quorums),
        backend_id=backend.backend_id(),
        astra_binary_sha256=backend.astra_binary_sha256,
        et_granularity=projection.et_granularity,
        expansion_authority=projection.expansion_authority(),
        network_evidence_tier=TIER_ASTRA_OWNED_COLLECTIVE)
    return qualification, projection


# ── authenticated per-round evidence (§8) ─────────────────────────────────

@dataclass(frozen=True)
class CanonicalServingRoundEvidence:
    """Content-addressed evidence for exactly one executed round."""

    qualification_id: str
    physical_machine_id: str
    machine_id: str
    plan_id: str
    round_projection_id: str
    namespace_id: str
    participant_mapping_id: str
    serving_binding_id: str
    staged_workload_id: str
    communicator_group_id: str
    astra_binary_sha256: str
    embedded_fabric_abi_version: str
    standalone_config_sha256: str
    network_evidence_tier: str
    expansion_authority: str
    dispatched_instances: tuple[int, ...]
    per_endpoint_completions: tuple[tuple[int, int], ...]
    completion_attributions: tuple[tuple[int, int, int], ...]
    collective_ledger: tuple[tuple[int, int, int, tuple[int, ...]], ...]
    autonomous_injection_packets: int | None
    backend_cycles: int | None
    parser_version: str
    #: round-specific collective binding + per-collective runtime contract
    collective_binding_id: str = ""
    collective_contract: tuple[CollectiveContract, ...] = ()
    #: dense-DP quorums synchronized in this round
    dp_quorums: tuple[DpQuorumRecord, ...] = ()
    schema_version: int = SERVING_ROUND_SCHEMA_VERSION

    def identity_dict(self) -> dict[str, Any]:
        return {
            "type": "srota/CanonicalServingRoundEvidence",
            "schema_version": self.schema_version,
            "parser_version": self.parser_version,
            "qualification_id": self.qualification_id,
            "physical_machine_id": self.physical_machine_id,
            "machine_id": self.machine_id,
            "plan_id": self.plan_id,
            "round_projection_id": self.round_projection_id,
            "namespace_id": self.namespace_id,
            "participant_mapping_id": self.participant_mapping_id,
            "serving_binding_id": self.serving_binding_id,
            "staged_workload_id": self.staged_workload_id,
            "communicator_group_id": self.communicator_group_id,
            "astra_binary_sha256": self.astra_binary_sha256,
            "embedded_fabric_abi_version":
                self.embedded_fabric_abi_version,
            "standalone_config_sha256": self.standalone_config_sha256,
            "network_evidence_tier": self.network_evidence_tier,
            "expansion_authority": self.expansion_authority,
            **({"collective_binding_id": self.collective_binding_id,
                "collective_contract": [row.identity_dict()
                                        for row in self.collective_contract]}
               if self.collective_binding_id else {}),
            **({"dp_quorums": [q.identity_dict() for q in self.dp_quorums]}
               if self.dp_quorums else {}),
            "dispatched_instances": list(self.dispatched_instances),
            "per_endpoint_completions":
                [[e, c] for e, c in self.per_endpoint_completions],
            "completion_attributions":
                [[e, r, i] for e, r, i in self.completion_attributions],
            "collective_ledger":
                [[rank, node, ctype, list(members)]
                 for rank, node, ctype, members in self.collective_ledger],
            "autonomous_injection_packets": self.autonomous_injection_packets,
            "backend_cycles": self.backend_cycles,
        }

    def evidence_id(self) -> str:
        return content_hash("srota/CanonicalServingRoundEvidence", 1,
                            self.identity_dict())

    def to_dict(self) -> dict[str, Any]:
        payload = dict(self.identity_dict())
        payload["evidence_id"] = self.evidence_id()
        return payload

    def canonical_bytes(self) -> bytes:
        return (json.dumps(self.to_dict(), sort_keys=True, indent=2)
                + "\n").encode("utf-8")


def round_evidence_from_outcome(*, qualification: AstraServingRoundQualification,
                                outcome: Any, machine: Any,
                                parser_version: str) -> CanonicalServingRoundEvidence:
    """Authenticate a round outcome against its qualification."""
    ledger = parse_collective_ledger(outcome.collective_ledger)
    return CanonicalServingRoundEvidence(
        qualification_id=qualification.round_id(),
        physical_machine_id=qualification.physical_machine_id,
        machine_id=qualification.machine_id,
        plan_id=qualification.plan_id,
        round_projection_id=qualification.round_projection_id,
        namespace_id=qualification.namespace_id,
        participant_mapping_id=qualification.participant_mapping_id,
        serving_binding_id=qualification.serving_binding_id,
        staged_workload_id=qualification.staged_workload_id,
        communicator_group_id=qualification.communicator_group_id,
        astra_binary_sha256=qualification.astra_binary_sha256,
        embedded_fabric_abi_version=machine.embedded_fabric_abi_version,
        standalone_config_sha256=machine.standalone_config_sha256,
        network_evidence_tier=qualification.network_evidence_tier,
        expansion_authority=qualification.expansion_authority,
        dispatched_instances=tuple(outcome.dispatched_instances),
        per_endpoint_completions=tuple(outcome.endpoint_completions),
        completion_attributions=tuple(
            (row.endpoint, row.rank, row.instance)
            for row in outcome.attributions),
        collective_ledger=tuple(
            (entry.rank, entry.astra_node, entry.comm_type, entry.members)
            for entry in ledger),
        autonomous_injection_packets=outcome.autonomous_injection_packets,
        backend_cycles=outcome.backend_cycles,
        collective_binding_id=qualification.collective_binding_id,
        collective_contract=tuple(qualification.collective_contract),
        dp_quorums=tuple(qualification.dp_quorums),
        parser_version=parser_version)
