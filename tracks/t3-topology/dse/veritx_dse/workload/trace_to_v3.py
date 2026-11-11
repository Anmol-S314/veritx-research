"""LLMServingSim trace rows -> ``WorkloadV3``: the missing adapter.

WHY THIS EXISTS
---------------
``canonical.artifact_from_trace_rows`` already canonicalizes LLMServingSim
trace rows into a ``WorkloadArtifact`` (Path B). Nothing could consume the
result: ``intent_lowering.lower_compile_workload`` reads a
``CompileRequestV3``, whose ``workload`` is a ``WorkloadV3`` carrying
``model_family`` and ``collectives`` — and ``WorkloadArtifact`` has neither.
The import path therefore ended one type short of lowering. This module is
that one type.

WHAT IS CONVERTED, AND WHAT MUST BE DECLARED
-------------------------------------------
Converted, because the trace rows state them:

* every collective row becomes one ``CollectiveIntent`` — its kind and its
  payload bytes are the row's own ``comm_field``/``comm_size``. An expert
  region carries its collective in ``comm_kind`` (an ``EXPERT_BEGIN`` row
  whose ``comm_kind`` is ALLTOALL is the EP dispatch); a marker with no
  ``comm_kind`` declares no collective and contributes no intent;
* ``tp``/``pp``/``ep``/``dp`` come from the artifact's ``parallelism``, which
  the producer passed in when it built the artifact.

NOT converted, because the rows never state them:

* ``model_family`` — a trace row carries no family. Inferring one from a
  model name or from which collectives appear would be a guess wearing a
  fact's clothes.
* ``dimension`` — ``WorkloadOp.scope`` is a boolean dimension vector whose
  dimension ORDER is documented nowhere in this tree, so mapping position 0
  to TP is an assumption, not a reading. The caller declares the dimension.
* ``traffic_class`` — a QoS identity, declared elsewhere in the document.
  A trace row has no traffic class, and defaulting one would silently bind
  traffic to a class the author never chose.

This is the same law ``family_collectives`` follows: compute is DECLARED,
never inferred.

ONE DIMENSION IS NOT ENOUGH FOR A REAL TRACE
--------------------------------------------
A MoE trace mixes a TP all-reduce with an EP all-to-all. A single declared
dimension cannot describe both, so ``dimension_of_kind`` maps collective
kind to dimension. A kind present in the trace with no declared dimension is
refused rather than folded into another dimension's group.

FAIL-CLOSED REFUSALS
--------------------
Each refusal below is a real inconsistency rather than a missing nicety:

* ``BROADCAST`` — this trace dialect has no root field, and
  ``canonical.py`` already refuses a standalone BROADCAST row rather than
  inventing a root. The adapter refuses it for the same reason.
* multi-dimension ``scope`` — one ``CollectiveIntent`` ranges over exactly
  one dimension, so a row that participates on two cannot be expressed
  without dropping one. Refused rather than narrowed.
* undeclared payload — a zero/absent ``comm_size`` is not a collective.
* participant count vs declared dimension — a trace whose own rows address
  eight ranks while its declared parallelism says one is internally
  inconsistent. The mismatch is reported instead of being resolved in
  either direction.

PP IS ABSENT ON PURPOSE
-----------------------
``CollectiveDimension.PP`` is never produced: lowering refuses a
pipeline-dimension collective ("pipeline stages are not a collective"), and
the trace dialect has no PP scope anyway.
"""

from __future__ import annotations

from typing import Any, Mapping

from veritx_dse.model.compile_model import (
    CollectiveDimension,
    CollectiveIntent,
    CollectiveKind,
    ModelFamily,
    ServingMode,
    WorkloadSourceRef,
    WorkloadV3,
)

__all__ = [
    "TraceAdapterUnsupported",
    "dimension_size",
    "workload_v3_from_trace",
]

#: The dimension a fully-scoped ("ALL") collective ranges over.
_ALL_SCOPE = "ALL"

#: Row kinds the trace dialect can express, and the intent each becomes.
_KIND_OF_ROW = {
    "ALLREDUCE": CollectiveKind.ALLREDUCE,
    "ALLGATHER": CollectiveKind.ALLGATHER,
    "REDUCESCATTER": CollectiveKind.REDUCESCATTER,
    "ALLTOALL": CollectiveKind.ALLTOALL,
}


class TraceAdapterUnsupported(ValueError):
    """A trace cannot be expressed as a WorkloadV3 without inventing a fact."""


def dimension_size(parallelism: Any, dimension: CollectiveDimension) -> int:
    """Rank count of one dimension, read from the declared parallelism."""
    if dimension is CollectiveDimension.TP:
        return int(parallelism.tp)
    if dimension is CollectiveDimension.DP:
        return int(parallelism.dp)
    if dimension is CollectiveDimension.EP:
        return int(parallelism.ep)
    if dimension is CollectiveDimension.PP:
        return int(parallelism.pp)
    if dimension is CollectiveDimension.GLOBAL:
        return (int(parallelism.tp) * int(parallelism.pp)
                * int(parallelism.ep) * int(parallelism.dp))
    raise TraceAdapterUnsupported(f"unknown dimension {dimension!r}")


def _scope_claim(scope: Any) -> tuple[str, int]:
    """Describe what the row's scope vector claims, without ordering it.

    The vector's dimension order is undocumented, so this reads only what is
    order-independent: how many dimensions participate, and whether the row
    scopes every dimension.
    """
    if scope == _ALL_SCOPE:
        return ("all", 0)
    if scope is None:
        raise TraceAdapterUnsupported(
            "a collective row declares no dimensional scope — scope absence "
            "is not 'all dimensions' and the adapter will not assume one")
    if not isinstance(scope, (list, tuple)) or not scope:
        raise TraceAdapterUnsupported(
            f"scope must be a non-empty boolean vector or {_ALL_SCOPE!r}, "
            f"got {scope!r}")
    active = [value for value in scope if value]
    return ("single" if len(active) == 1 else "multi", len(active))


def _resolve_dimension(
    declared_kind: str,
    dimension: CollectiveDimension | None,
    dimension_of_kind: Mapping[str, CollectiveDimension] | None,
) -> CollectiveDimension:
    """The dimension this collective ranges over, as declared."""
    if dimension_of_kind is not None:
        if declared_kind not in dimension_of_kind:
            raise TraceAdapterUnsupported(
                f"the trace declares a {declared_kind} collective but "
                f"dimension_of_kind names no dimension for it "
                f"(declared: {sorted(dimension_of_kind)}) — folding it into "
                "another dimension's group would be an invention")
        resolved = dimension_of_kind[declared_kind]
    else:
        assert dimension is not None
        resolved = dimension
    if not isinstance(resolved, CollectiveDimension):
        raise TraceAdapterUnsupported(
            f"dimension for {declared_kind} must be a declared "
            f"CollectiveDimension, got {resolved!r}")
    return resolved


def workload_v3_from_trace(
    artifact: Any,
    *,
    model_family: ModelFamily,
    traffic_class: str,
    dimension: CollectiveDimension | None = None,
    dimension_of_kind: Mapping[str, CollectiveDimension] | None = None,
    model_name: str = "",
    serving_mode: ServingMode = ServingMode.MIXED,
    source_ref: WorkloadSourceRef | None = None,
) -> WorkloadV3:
    """Convert one canonical trace artifact into the v3 workload lowering reads.

    ``model_family`` and ``traffic_class`` are required keyword arguments
    because the trace rows do not carry them; there are no defaults, so a
    caller cannot inherit one by accident. Exactly one of ``dimension`` and
    ``dimension_of_kind`` must be declared.
    """
    if not isinstance(model_family, ModelFamily):
        raise TraceAdapterUnsupported(
            f"model_family must be a declared ModelFamily, got "
            f"{model_family!r}")
    if not isinstance(traffic_class, str) or not traffic_class:
        raise TraceAdapterUnsupported(
            "traffic_class must be a non-empty declared string")
    if (dimension is None) == (dimension_of_kind is None):
        raise TraceAdapterUnsupported(
            "declare exactly one of dimension / dimension_of_kind — a "
            "collective's rank space is never defaulted")
    if dimension is not None and not isinstance(dimension,
                                                CollectiveDimension):
        raise TraceAdapterUnsupported(
            f"dimension must be a declared CollectiveDimension, got "
            f"{dimension!r}")
    if dimension is CollectiveDimension.PP or (
            dimension_of_kind is not None
            and CollectiveDimension.PP in dimension_of_kind.values()):
        raise TraceAdapterUnsupported(
            "CollectiveDimension.PP is refused by lowering ('pipeline stages "
            "are not a collective'); the trace dialect has no PP scope either")

    parallelism = getattr(artifact, "parallelism", None)
    if parallelism is None:
        raise TraceAdapterUnsupported(
            "artifact declares no parallelism — tp/pp/ep/dp are required "
            "geometry, never defaulted")

    intents: list[CollectiveIntent] = []
    for op in artifact.comm_ops():
        row_kind = str(getattr(op, "kind", ""))
        # An expert region carries its collective in ``comm_kind``: the row is
        # EXPERT_BEGIN/END, and the dispatch all-to-all is a field of it. A
        # marker with no comm_kind declares no collective, so it contributes
        # no intent rather than a zero-byte one.
        if row_kind == "EXPERT_END":
            continue
        if row_kind == "EXPERT_BEGIN":
            declared_kind = getattr(op, "comm_kind", None)
            if declared_kind is None:
                continue
        else:
            declared_kind = row_kind
        if declared_kind == "BROADCAST":
            raise TraceAdapterUnsupported(
                "BROADCAST rows carry no root in this trace dialect; "
                "refusing rather than inventing one")
        kind = _KIND_OF_ROW.get(declared_kind)
        if kind is None:
            raise TraceAdapterUnsupported(
                f"collective kind {declared_kind!r} has no v3 intent mapping "
                f"(supported: {sorted(_KIND_OF_ROW)})")

        resolved = _resolve_dimension(declared_kind, dimension,
                                      dimension_of_kind)
        if resolved is CollectiveDimension.PP:
            raise TraceAdapterUnsupported(
                f"the trace declares a {declared_kind} collective on PP; "
                "lowering refuses pipeline-dimension collectives")

        payload = getattr(op, "bytes", None)
        if not isinstance(payload, int) or payload <= 0:
            raise TraceAdapterUnsupported(
                f"row {getattr(op, 'op_id', '?')!r} declares payload "
                f"{payload!r}; a collective's bytes are DECLARED, and the "
                "adapter will not substitute a representative size")

        scope_kind, active = _scope_claim(getattr(op, "scope", None))
        if scope_kind == "all":
            if resolved is not CollectiveDimension.GLOBAL:
                raise TraceAdapterUnsupported(
                    f"row {getattr(op, 'op_id', '?')!r} scopes ALL dimensions "
                    f"but the declared dimension is {resolved.value}; an "
                    "all-dimension collective is GLOBAL or it is a narrowing")
        elif scope_kind == "multi":
            raise TraceAdapterUnsupported(
                f"row {getattr(op, 'op_id', '?')!r} participates on {active} "
                "dimensions; one CollectiveIntent ranges over exactly one, so "
                "expressing this would drop a declared dimension")

        expected = dimension_size(parallelism, resolved)
        participants = tuple(getattr(op, "participants", ()) or ())
        if participants and len(participants) != expected:
            raise TraceAdapterUnsupported(
                f"row {getattr(op, 'op_id', '?')!r} addresses "
                f"{len(participants)} ranks but the declared "
                f"{resolved.value} size is {expected}; the trace and its "
                "own parallelism disagree")

        intents.append(CollectiveIntent(
            kind=kind, dimension=resolved, payload_bytes=payload,
            traffic_class=traffic_class))

    return WorkloadV3(
        model_family=model_family,
        model_name=model_name,
        tp=int(parallelism.tp), pp=int(parallelism.pp),
        ep=int(parallelism.ep), dp=int(parallelism.dp),
        serving_mode=serving_mode,
        collectives=tuple(intents),
        source_ref=source_ref,
    )
