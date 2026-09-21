"""veritx_dse.workload.intent_lowering — product intent → WorkloadGraph.

The ONE CompileRequest.Workload → WorkloadGraph pass (P1B.2). It
converts Level-A/B user intent into canonical executable workload
semantics and knows NOTHING about BookSim, traces, or backends: no
backend import may ever appear here (the FabricEvaluator owns the
backend seam).

Supported subset (intentionally narrow — see
docs/WORKLOAD-EVALUATION-AUTHORITY.md §7):

    model_family  DENSE_TRANSFORMER only
    trace_path    None only (a trace is a different authority)
    collectives   exactly one, kind in ALLREDUCE/ALLGATHER/
                  REDUCESCATTER/ALLTOALL, group_size == world_size,
                  group_size >= 2, payload_bytes declared
    scope         always None (undeclared is not ALL)
    phase         always absent (serving_mode is a mix, not a phase)

Everything else is UnsupportedSemantics with a reason: the canonical
system can represent it, but product intent does not yet carry enough
information. requirements and dependencies are NOT consumed here —
aggregate network timing is not per-QoS latency (P1C), and a single
op has no sequencing.
"""
from __future__ import annotations

from typing import Any

from veritx_dse.core.errors import UnsupportedSemantics
from veritx_dse.model.compile_model import (
    CompileRequest, ModelFamily,
)
from veritx_dse.model.parallelism import ParallelismArtifact

from .canonical_graph import (
    KIND_COLLECTIVE, OperationNode, WorkloadGraph, WorkloadSemantics,
    collective_detail,
)

LOWERER_VERSION = "intent_lowering/v1"

# Canonical collective names the product lowerer can emit. BROADCAST is
# absent on purpose: the canonical graph refuses an invented root, and
# CompileRequest carries no explicit one.
_SUPPORTED_COLLECTIVES = frozenset({
    "ALLREDUCE", "ALLGATHER", "REDUCESCATTER", "ALLTOALL",
})


def _unsupported(request: CompileRequest, reason: str) -> UnsupportedSemantics:
    return UnsupportedSemantics(
        f"cannot lower workload to a WorkloadGraph: {reason} "
        f"(design {request.design_hash()[:16]}…)")


def lower_compile_workload(request: CompileRequest) -> WorkloadGraph:
    """Lower one CompileRequest's workload to a canonical WorkloadGraph."""
    wl = request.workload
    if wl.model_family is not ModelFamily.DENSE_TRANSFORMER:
        raise _unsupported(
            request, f"model_family {wl.model_family.value!r} is not "
            "lowered yet (only dense_transformer)")
    if wl.trace_path is not None:
        raise _unsupported(
            request, f"trace_path {wl.trace_path!r} is a different "
            "workload authority than declared intent")
    if len(wl.collectives) != 1:
        raise _unsupported(
            request, f"expected exactly one declared collective, got "
            f"{len(wl.collectives)} (multi-collective sequencing is not "
            "represented in product intent)")
    coll = wl.collectives[0]
    kind = coll.kind.value.upper()
    if kind not in _SUPPORTED_COLLECTIVES:
        raise _unsupported(
            request, f"collective kind {coll.kind.value!r} carries no "
            "explicit root or lowering (BROADCAST needs a declared "
            "source; MoE/PIM need the workload synthesizer)")
    world = wl.world_size
    if coll.group_size != world:
        raise _unsupported(
            request, f"collective group_size {coll.group_size} != workload "
            f"world_size {world} with no explicit group declaration "
            "(ranks are never guessed)")
    if coll.group_size < 2:
        raise _unsupported(
            request, "single-rank collective has no network traffic "
            "to evaluate")
    if coll.payload_bytes is None:
        raise _unsupported(
            request, "collective declares no payload_bytes "
            "(bytes_per_element is historical, never inferred)")
    participants = tuple(range(world))
    node = OperationNode(
        operation_id="collective-0",
        kind=KIND_COLLECTIVE,
        deps=(),
        detail=collective_detail(
            collective_kind=kind,
            participants=participants,
            payload_bytes=coll.payload_bytes,
            participant_count=world,
            scope=None),
        label=f"{coll.kind.value} x{coll.group_size}",
    )
    return WorkloadGraph(
        parallelism=ParallelismArtifact(
            tp=wl.tp, pp=wl.pp, ep=wl.ep, dp=wl.dp),
        participant_count=world,
        operations=(node,),
        semantics=WorkloadSemantics(),
        provenance={"lowerer": LOWERER_VERSION,
                    "design_hash": request.design_hash()},
    )


__all__ = ["LOWERER_VERSION", "lower_compile_workload"]
