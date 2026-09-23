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

    def __post_init__(self) -> None:
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
        }

    def plan_id(self) -> str:
        return content_hash("srota/ServingBatchPlan", 1, self.identity_dict())

    # -- canonical lowering (intent only) ---------------------------------
    def to_workload_graph(self, *, parallelism: Any) -> Any:
        """Lower serving intent to a canonical workload graph.

        The collective is expressed as *intent* with its participant set -- it
        is never expanded into ring messages here.
        """
        from veritx_dse.workload.graph import (
            KIND_COLLECTIVE, KIND_COMPUTE, OperationNode, WorkloadGraph,
            collective_detail, compute_detail,
        )
        participants = tuple(sorted(self.participant_ranks))
        count = len(participants)
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


# ── collective ledger validation (§9) ─────────────────────────────────────

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
        }

    def round_id(self) -> str:
        return content_hash("srota/AstraServingRoundQualification", 1,
                            self.identity_dict())


def qualify_round(*, machine: Any, plan: ServingBatchPlan, backend: Any,
                  staged: Any, directory: str | Path,
                  resolved_fabric: Any, mapping: Any, attachment: Any,
                  parallelism: Any) -> tuple[AstraServingRoundQualification,
                                             Any]:
    """Qualify one serving round against the stable machine + namespace."""
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
    expected_members = namespace.participant_endpoints()
    staged_members = tuple(sorted(endpoint for endpoint, _ in
                                  staged.endpoint_files))
    if staged_members != expected_members:
        raise ServingRoundError(
            f"staged endpoints {list(staged_members)} do not match the "
            f"canonical participant endpoints {list(expected_members)}")
    group_json = backend.binding.namespace.groups.to_json()
    qualification = AstraServingRoundQualification(
        physical_machine_id=machine.physical_id(),
        machine_id=machine.machine_id(),
        plan_id=plan.plan_id(),
        round_projection_id=projection.projection_id(),
        namespace_id=namespace.namespace_id(),
        participant_mapping_id=namespace.participant_mapping_id,
        serving_binding_id=backend.binding.binding_id(),
        staged_workload_id=staged.translation_id,
        communicator_group_id=content_hash(
            "srota/AstraCommunicatorGroups", 1,
            {"text": group_json}),
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
        parser_version=parser_version)
