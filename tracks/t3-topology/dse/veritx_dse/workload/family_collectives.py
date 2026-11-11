"""Model-family → collective-intent patterns: the declared missing mapping.

WHY THIS EXISTS
---------------
``intent_lowering.py`` refuses a family outside (dense_transformer, MoE) that
declares no collectives, with: *"a non-transformer family has no implicit
intent→collective mapping, so it must state its collectives explicitly."*
That refusal is CORRECT — lowering lowers what is DECLARED and must never
invent communication. But it left four of the five families unusable unless
the author hand-wrote every collective.

This module supplies the missing mapping as a DECLARED, versioned table. It
is applied at AUTHORING time (``ProductService.put_draft``), never inside
lowering. By the time a request reaches lowering its collectives are
declared bytes on the document, so the "lowering never infers" law still
holds and every derived collective is visible and editable in the draft.

PAYLOAD SIZES ARE NEVER INVENTED
--------------------------------
A pattern names the declared compute field it reads. Derivation refuses when
the request declares no compute to read it from, rather than substituting a
representative constant. The numbers in the lowered artifact therefore trace
back to something the author wrote.

PP IS ABSENT ON PURPOSE
-----------------------
Pipeline-dimension collectives are refused by lowering ("pipeline stages are
not a collective"). No pattern uses PP, and ``_PATTERN_DIMENSIONS`` cannot
express it.
"""
from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Any, Mapping

from veritx_dse.model.compile_model import (
    CollectiveDimension,
    CollectiveIntent,
    CollectiveKind,
    ModelFamily,
)


class FamilyCollectiveUnsupported(ValueError):
    """A family's pattern needs a payload the request does not declare."""


#: Payload roles a pattern may read. Each maps to a declared ComputeStage
#: field — the mapping is the whole honesty argument of this module.
PAYLOAD_ROLES: dict[str, str] = {
    "weights": "weight_bytes",
    "activations": "input_bytes",
    "outputs": "output_bytes",
}


@dataclass(frozen=True)
class FamilyCollectivePattern:
    """One collective a family's execution implies.

    ``payload_role`` names the declared compute field carrying the size; it
    is a role, never a number, so nothing here can be fabricated.
    """
    kind: CollectiveKind
    dimension: CollectiveDimension
    traffic_class: str
    payload_role: str

    def __post_init__(self) -> None:
        if self.payload_role not in PAYLOAD_ROLES:
            raise ValueError(
                f"payload_role {self.payload_role!r} is not declared; "
                f"known roles {sorted(PAYLOAD_ROLES)}")
        if self.dimension is CollectiveDimension.PP:
            raise ValueError(
                "PP-dimension collectives are refused by lowering; a family "
                "pattern must not declare one")


#: The table. Shapes follow what the shipped workloads already declare
#: (`llama_dense_64tiles` -> allreduce/TP; `qwen3_moe` -> allreduce/TP plus
#: alltoall/EP dispatch+combine). DP carries no pattern because data-parallel
#: serving replicas are independent — they exchange nothing.
#: ``custom`` stays EMPTY by design: an author who says "custom" is stating
#: that no shipped pattern describes their workload, so they must declare
#: collectives explicitly (unchanged behaviour).
FAMILY_PATTERNS: dict[ModelFamily, tuple[FamilyCollectivePattern, ...]] = {
    ModelFamily.DENSE_TRANSFORMER: (
        # Tensor-parallel activation all-reduce per layer.
        FamilyCollectivePattern(CollectiveKind.ALLREDUCE,
                                CollectiveDimension.TP,
                                "tp_collective", "activations"),
    ),
    ModelFamily.MOE: (
        # Dense/attention path is still tensor-parallel.
        FamilyCollectivePattern(CollectiveKind.ALLREDUCE,
                                CollectiveDimension.TP,
                                "tp_collective", "activations"),
        # Expert dispatch: activations routed to the owning expert ranks.
        FamilyCollectivePattern(CollectiveKind.ALLTOALL,
                                CollectiveDimension.EP,
                                "ep_dispatch", "activations"),
        # Expert combine: expert outputs returned to the token's home rank.
        FamilyCollectivePattern(CollectiveKind.ALLTOALL,
                                CollectiveDimension.EP,
                                "ep_combine", "outputs"),
    ),
    ModelFamily.DIFFUSION: (
        # Denoising is sharded over tensor parallelism; each step gathers
        # the sharded activations before the next block.
        FamilyCollectivePattern(CollectiveKind.ALLGATHER,
                                CollectiveDimension.TP,
                                "activation_gather", "activations"),
    ),
    ModelFamily.CNN: (
        # Convolution tiles need their neighbours' boundary rows (halo).
        # Modelled as a tensor-parallel all-gather of the activation halo.
        FamilyCollectivePattern(CollectiveKind.ALLGATHER,
                                CollectiveDimension.TP,
                                "halo_exchange", "activations"),
    ),
    # No shipped pattern describes "custom": declare explicitly.
    ModelFamily.CUSTOM: (),
}


def declared_payloads(request: Any) -> dict[str, int]:
    """Largest declared byte count per role, from the request's compute.

    An empty dict means the request declares no compute — derivation then
    refuses instead of inventing a size.
    """
    compute = getattr(request, "compute", None)
    stages = tuple(getattr(compute, "stages", ()) or ())
    payloads: dict[str, int] = {}
    for stage in stages:
        for role, field in PAYLOAD_ROLES.items():
            value = getattr(stage, field, None)
            if isinstance(value, int) and not isinstance(value, bool) \
                    and value > 0:
                payloads[role] = max(payloads.get(role, 0), value)
    return payloads


def derive_family_collectives(
        family: ModelFamily,
        *,
        tp: int, pp: int, ep: int, dp: int,
        payloads: Mapping[str, int],
) -> tuple[CollectiveIntent, ...]:
    """Collectives implied by ``family`` at this parallelism.

    Patterns whose dimension is not actually split (size 1) are skipped: a
    single-member group is refused by lowering, and skipping states the
    truth that no communication happens along an unsplit axis.

    Raises:
        FamilyCollectiveUnsupported: a pattern needs a role the caller did
            not supply (never substituted).
    """
    sizes = {
        CollectiveDimension.TP: tp,
        CollectiveDimension.DP: dp,
        CollectiveDimension.EP: ep,
    }
    derived: list[CollectiveIntent] = []
    for pattern in FAMILY_PATTERNS.get(family, ()):
        if sizes.get(pattern.dimension, 1) <= 1:
            continue
        nbytes = payloads.get(pattern.payload_role)
        if not isinstance(nbytes, int) or isinstance(nbytes, bool) \
                or nbytes <= 0:
            raise FamilyCollectiveUnsupported(
                f"model_family={family.value} implies a "
                f"{pattern.kind.value} over {pattern.dimension.value} whose "
                f"payload comes from the declared "
                f"{PAYLOAD_ROLES[pattern.payload_role]} — the request "
                "declares no compute, so the size cannot be derived without "
                "inventing it. Declare compute stages or explicit "
                "collectives.")
        derived.append(CollectiveIntent(
            kind=pattern.kind,
            dimension=pattern.dimension,
            payload_bytes=nbytes,
            traffic_class=pattern.traffic_class))
    return tuple(derived)


def complete_family_collectives(request: Any) -> Any:
    """Fill in a family's implied collectives when the draft declares none.

    AUTHORING-TIME ONLY. Called from ``put_draft``; never from a read path,
    because completing on read would move the design hash of stored
    revisions. A request that already declares collectives is returned
    unchanged — an author's explicit intent always wins.
    """
    workload = getattr(request, "workload", None)
    if workload is None:
        return request
    if tuple(getattr(workload, "collectives", ()) or ()):
        return request
    family = getattr(workload, "model_family", None)
    if not isinstance(family, ModelFamily):
        return request
    if not FAMILY_PATTERNS.get(family):
        # custom (or unknown): leave it to lowering's explicit refusal.
        return request
    payloads = declared_payloads(request)
    if not payloads:
        # No declared compute: leave the request alone so lowering reports
        # the honest "declares nothing to lower" refusal.
        return request
    try:
        derived = derive_family_collectives(
            family,
            tp=workload.tp, pp=workload.pp, ep=workload.ep, dp=workload.dp,
            payloads=payloads)
    except FamilyCollectiveUnsupported:
        return request
    if not derived:
        return request
    return replace(request, workload=replace(workload, collectives=derived))
