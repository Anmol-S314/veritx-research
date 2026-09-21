"""veritx_dse.workload.migration — historical formats -> WorkloadGraph.

Slice 2c.3. ONE narrow boundary. It is not a workload authority: it reads
an authenticated historical representation, validates it with its OWN
historical rules, extracts semantics, and produces a ``WorkloadGraph``.
Nothing here is a runtime model — production consumers use the graph.

The migration law (Rule 2), enforced by ordering rather than by comment:

    legacy bytes
      -> legacy parser            (its own schema)
      -> legacy identity recomputed and COMPARED   <- refuses before here
      -> semantic extraction
      -> WorkloadGraph
      -> canonical-v2 identity

Legacy bytes are NEVER reinterpreted under v2 hashing, and a legacy hash
is never smuggled forward as canonical ancestry: it is preserved as
NON-IDENTITY provenance so old artefacts stay auditable.

Also here: the direct trace-row reader, which must NOT route through the
legacy workload authority (that is what dropped PIM — finding F16).
"""
from __future__ import annotations

from typing import Any, Iterable

from veritx_dse.core.artifact import EvidenceInvalid, InvalidInput, thaw
from veritx_dse.core.errors import UnsupportedSemantics
from veritx_dse.model.parallelism import ParallelismArtifact
from veritx_dse.workload.canonical_graph import (
    KIND_COLLECTIVE, KIND_COMPUTE, KIND_EXPERT_BEGIN, KIND_EXPERT_END,
    KIND_MULTICAST, KIND_P2P, KIND_PIM_BEGIN, KIND_PIM_END, OperationNode,
    WorkloadGraph, WorkloadSemantics, collective_detail, compute_detail,
    expert_detail, multicast_detail, p2p_detail, pim_detail,
    pim_end_detail,
)

#: historical formats this boundary understands
SOURCE_PHASE9 = "phase9-workload-v1"
SOURCE_WAVED = "waved-workload-v1"
SOURCE_TRACE = "llmservingsim-trace-rows-v1"

#: Phase-9 collective kinds -> canonical collective kinds
_PHASE9_COLLECTIVES = ("ALLREDUCE", "ALLGATHER", "REDUCESCATTER", "ALLTOALL",
                       "BROADCAST")
_PHASE9_P2P = ("SEND", "RECV")


def _phase9_provenance(art: Any) -> dict[str, Any]:
    """Non-identity ancestry. Explicitly NOT the new parent identity."""
    return {
        "source_format": SOURCE_PHASE9,
        "legacy_artifact_hash": art.artifact_hash,
        "legacy_workload_id": art.workload_id,
        "source_kind": art.source_kind,
    }


def _waved_provenance(art: Any) -> dict[str, Any]:
    return {
        "source_format": SOURCE_WAVED,
        "legacy_workload_id": art.workload_id(),
    }


# ── positional order -> explicit dependency chain ───────────────────────
def _chain(nodes: Iterable[OperationNode]) -> tuple[OperationNode, ...]:
    """Encode positional source order as an explicit chain.

    Phase-9 operation ORDER was semantic: ET row reconstruction, the
    positional memory stream and timeline v1 all chained operations
    positionally. Migration makes that relation explicit so no lowerer has
    to rely on tuple construction order (which canonical identity
    deliberately ignores).
    """
    out: list[OperationNode] = []
    previous: tuple[str, ...] = ()
    for node in nodes:
        out.append(OperationNode(node.operation_id, node.kind, previous,
                                 node.detail, node.owner, node.phase,
                                 node.step, node.label))
        previous = (node.operation_id,)
    return tuple(out)


# ── Phase-9 operation mapping ───────────────────────────────────────────
def _phase9_op(op: Any, count: int) -> OperationNode:
    kind = op.kind
    op_id = op.op_id
    if kind == "COMPUTE":
        detail = compute_detail(
            duration_ns=op.duration_ns if op.duration_ns is not None else 0,
            input_bytes=op.input_bytes, weight_bytes=op.weight_bytes,
            output_bytes=op.output_bytes,
            # explicit v2 defaults (values, not absences) — expanded only
            # AFTER the historical hash was validated
            input_loc=op.input_loc or "LOCAL",
            weight_loc=op.weight_loc or "LOCAL",
            output_loc=op.output_loc or "LOCAL",
            batch_tag=op.batch_tag or "NONE")
        return OperationNode(op_id, KIND_COMPUTE, (), detail,
                             label=op.label)
    if kind in _PHASE9_COLLECTIVES:
        detail = collective_detail(
            collective_kind=kind, participants=tuple(op.participants),
            payload_bytes=op.bytes, participant_count=count,
            scope=thaw(op.scope) if not isinstance(op.scope, str)
            else op.scope,
            source=op.src if kind == "BROADCAST" else None)
        return OperationNode(op_id, KIND_COLLECTIVE, (), detail,
                             label=op.label)
    if kind in _PHASE9_P2P:
        detail = p2p_detail(role=kind, src_rank=op.src, dst_rank=op.dst,
                            payload_bytes=op.bytes, participant_count=count)
        return OperationNode(op_id, KIND_P2P, (), detail, label=op.label)
    if kind in ("EXPERT_BEGIN", "EXPERT_END"):
        detail = expert_detail(
            end=(kind == "EXPERT_END"), expert_num=op.expert_num,
            collective_kind=op.comm_kind,
            participants=tuple(op.participants) if op.comm_kind else None,
            payload_bytes=op.bytes if op.comm_kind else None,
            scope=(thaw(op.scope) if not isinstance(op.scope, str)
                   else op.scope) if op.comm_kind else None,
            participant_count=count)
        return OperationNode(
            op_id, KIND_EXPERT_END if kind == "EXPERT_END"
            else KIND_EXPERT_BEGIN, (), detail, label=op.label)
    raise UnsupportedSemantics(
        f"Phase-9 operation kind {kind!r} has no canonical mapping")


def _phase9_parallelism(legacy: Any) -> ParallelismArtifact:
    """Named-field mapping ONLY.

    ``legacy`` declares (tp, dp, ep, pp) while ParallelismArtifact declares
    (tp, pp, ep, dp): a positional conversion would silently swap dp/ep/pp.
    """
    return ParallelismArtifact(tp=legacy.tp, pp=legacy.pp, ep=legacy.ep,
                               dp=legacy.dp)


def migrate_phase9_artifact(art: Any, *, validate: bool = True
                            ) -> WorkloadGraph:
    """Migrate an ALREADY-AUTHENTICATED Phase-9 WorkloadArtifact."""
    if validate:
        recomputed = type(art)(workload_id=art.workload_id,
                               source_kind=art.source_kind,
                               parallelism=art.parallelism,
                               num_participants=art.num_participants,
                               ops=art.ops).artifact_hash
        if recomputed != art.artifact_hash:
            raise EvidenceInvalid(
                f"legacy artifact_hash {art.artifact_hash} does not match "
                f"its content ({recomputed}): refusing to migrate an "
                "unauthenticated historical document")
    count = art.num_participants
    nodes = _chain(_phase9_op(op, count) for op in art.ops)
    return WorkloadGraph(
        parallelism=_phase9_parallelism(art.parallelism),
        participant_count=count,
        operations=nodes,
        semantics=WorkloadSemantics(),
        provenance=_phase9_provenance(art),
    )


def migrate_phase9_document(doc: dict, *, strict: bool = True
                            ) -> WorkloadGraph:
    """Validate a persisted Phase-9 document with ITS OWN rules, then
    migrate.

    The historical reader already recomputes the legacy hash from content
    and refuses a forged or tampered document, so validation is NOT
    re-implemented here (one implementation per rule). Its historical
    refusal is translated into the migration boundary's typed refusal so
    callers see one vocabulary while the original message is preserved.
    """
    from veritx_dse.workload.canonical import WorkloadArtifact, WorkloadError
    try:
        art = WorkloadArtifact.from_dict(doc)
    except WorkloadError as exc:
        raise EvidenceInvalid(
            f"refusing to migrate an unauthenticated Phase-9 document "
            f"(historical reader refused): {exc}") from None
    return migrate_phase9_artifact(art)


def phase9_to_canonical_identity(doc: dict) -> str:
    """Old hash first, new identity second — never the other way round."""
    return migrate_phase9_document(doc).workload_id()


# ── Wave-D migration ────────────────────────────────────────────────────
_WAVED_COLLECTIVE_KINDS = ("ALLREDUCE", "REDUCESCATTER", "ALLGATHER",
                           "ALLTOALL", "BROADCAST")


def migrate_waved_workload(art: Any, *, validate: bool = True
                           ) -> WorkloadGraph:
    """Migrate an authenticated Wave-D workload declaration."""
    if not validate:
        raise UnsupportedSemantics(
            "Wave-D migration always validates the historical identity "
            "first; there is no unvalidated path")
    parallelism = art.parallelism
    semantics = art.semantics
    count = parallelism.world_size      # the Wave-D addressed rank space
    nodes: list[OperationNode] = []
    for op in art.operations:
        detail = thaw(op.detail)
        kind = op.kind
        if kind == "COLLECTIVE":
            ck = detail.get("collective_kind")
            participants = tuple(detail["participants"])
            # Historical Wave-D BROADCAST used participants[0] as the root.
            # Migration records that explicitly; new authoring never infers it.
            source = (participants[0]
                      if ck == "BROADCAST"
                      and detail.get("source") is None else
                      detail.get("source"))
            new_detail = collective_detail(
                collective_kind=ck, participants=participants,
                payload_bytes=detail["payload_bytes"],
                participant_count=count, scope=detail.get("scope"),
                source=source)
            nodes.append(OperationNode(op.operation_id, KIND_COLLECTIVE,
                                       op.deps, new_detail, op.owner,
                                       op.phase, op.step, ""))
        elif kind == "P2P":
            new_detail = p2p_detail(
                role="TRANSFER", src_rank=detail["src_rank"],
                dst_rank=detail["dst_rank"],
                payload_bytes=detail["payload_bytes"],
                participant_count=count)
            nodes.append(OperationNode(op.operation_id, KIND_P2P, op.deps,
                                       new_detail, op.owner, op.phase,
                                       op.step, ""))
        elif kind == "MULTICAST":
            new_detail = multicast_detail(
                source_rank=detail["source_rank"],
                destinations=tuple(detail["destinations"]),
                payload_bytes=detail["payload_bytes"],
                replication=detail["replication"],
                participant_count=count)
            nodes.append(OperationNode(op.operation_id, KIND_MULTICAST,
                                       op.deps, new_detail, op.owner,
                                       op.phase, op.step, ""))
        else:
            raise UnsupportedSemantics(
                f"Wave-D operation kind {kind!r} has no canonical mapping")
    return WorkloadGraph(
        parallelism=parallelism,
        participant_count=count,
        operations=tuple(nodes),
        semantics=WorkloadSemantics(
            phase=semantics.phase,
            routing_policy=getattr(semantics, "routing_policy", None),
            shape=getattr(semantics, "shape_metadata", None),
            model_descriptor_hash=getattr(semantics,
                                          "model_descriptor_hash", None),
            model_descriptor_name=getattr(semantics, "model_descriptor",
                                          None)),
        provenance=_waved_provenance(art),
    )


def migrate_waved_document(doc: dict) -> WorkloadGraph:
    """Validate a persisted Wave-D document with ITS OWN rules, then migrate."""
    from veritx_dse.workload.graph import WaveDWorkload
    art = WaveDWorkload.from_dict(doc)
    return migrate_waved_workload(art)


__all__ = [
    "SOURCE_PHASE9", "SOURCE_TRACE", "SOURCE_WAVED",
    "migrate_phase9_artifact", "migrate_phase9_document",
    "migrate_waved_document", "migrate_waved_workload",
    "phase9_to_canonical_identity",
]
