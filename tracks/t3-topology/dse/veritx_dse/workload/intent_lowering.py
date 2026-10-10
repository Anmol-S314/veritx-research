"""veritx_dse.workload.intent_lowering — v3 intent → canonical WorkloadGraph.

Rationale: docs/decisions/modules/workload.md
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from veritx_dse.core.errors import (
    InvalidInput,
    MappingInvalid,
    UnsupportedSemantics,
)
from veritx_dse.model.compile_model import (
    CollectiveDimension,
    CollectiveIntent,
    CollectiveKind,
    CompileRequestV3,
    CompileRequestV3SchemaError,
    ModelFamily,
    derive_v3_traffic_classes,
)
from veritx_dse.model.placement import ParallelismShape, rank_of
from veritx_dse.workload.graph import (
    WorkloadGraph,
    WorkloadSemantics,
    collective_detail,
)
from veritx_dse.workload.collectives import collective_schedule
from veritx_dse.workload.messages import (
    LogicalMessageArtifactV2, LogicalMessageArtifactV3,
)

LOWERING_SCHEMA_VERSION = 1
LOWERER_ID = "veritx_dse.workload.intent_lowering/v3.1"

@dataclass(frozen=True)
class LoweredWorkload:
    """A v3 lowering result: canonical graph + traffic-class sidecar.

Rationale: docs/decisions/modules/workload.md
    """

    graph: WorkloadGraph
    traffic_class_by_operation: tuple[tuple[str, str], ...]
    design_hash: str

    def __post_init__(self) -> None:
        if not isinstance(self.graph, WorkloadGraph):
            raise InvalidInput("graph must be a WorkloadGraph")
        if not isinstance(self.design_hash, str) or not self.design_hash:
            raise InvalidInput("design_hash must be a non-empty string")
        pairs = tuple(self.traffic_class_by_operation)
        op_ids = [op.operation_id for op in self.graph.of_kind("COLLECTIVE")]
        if sorted(op for op, _ in pairs) != sorted(op_ids):
            raise InvalidInput(
                "traffic_class_by_operation must name every COLLECTIVE "
                "operation exactly once")
        if [op for op, _ in pairs] != sorted(op for op, _ in pairs):
            raise InvalidInput(
                "traffic_class_by_operation must be sorted by operation id")
        for op, cls in pairs:
            if not isinstance(cls, str) or not cls:
                raise InvalidInput(
                    f"traffic class for {op!r} must be a non-empty string")
        object.__setattr__(self, "traffic_class_by_operation", pairs)

    @property
    def classes(self) -> tuple[str, ...]:
        """Sorted distinct traffic classes across operations."""
        return tuple(sorted({cls for _, cls in self.traffic_class_by_operation}))

    @property
    def unified_traffic_class(self) -> str | None:
        """The single class when all operations agree, else None."""
        classes = self.classes
        return classes[0] if len(classes) == 1 else None

    def class_for(self, operation_id: str) -> str:
        """Traffic class of one lowered operation (KeyError-free)."""
        for op, cls in self.traffic_class_by_operation:
            if op == operation_id:
                return cls
        raise InvalidInput(
            f"operation {operation_id!r} is not a lowered collective")

def _intent_kind_name(intent: CollectiveIntent) -> str:
    """Canonical (uppercase) collective name for the graph detail."""
    return intent.kind.value.upper()

def _groups_for_dimension(tp: int, pp: int, ep: int, dp: int,
                          family: str) -> tuple[tuple[int, ...], ...]:
    """All groups of one family in canonical order, via the sealed rank
    algebra (model.placement.rank_of). Mirrors the retired
    ParallelismArtifact.groups derivation exactly: TP groups vary t at
    fixed (p,e,d); EP groups vary e at fixed (t,p,d); DP groups vary d
    at fixed (t,p,e); GLOBAL is the single all-ranks group."""
    out: list[tuple[int, ...]] = []
    if family == "TP":
        for p in range(pp):
            for d in range(dp):
                for e in range(ep):
                    out.append(tuple(
                        rank_of(i, p, e, d, tp=tp, pp=pp, ep=ep, dp=dp)
                        for i in range(tp)))
    elif family == "EP":
        for t in range(tp):
            for p in range(pp):
                for d in range(dp):
                    out.append(tuple(
                        rank_of(t, p, i, d, tp=tp, pp=pp, ep=ep, dp=dp)
                        for i in range(ep)))
    elif family == "DP":
        for t in range(tp):
            for p in range(pp):
                for e in range(ep):
                    out.append(tuple(
                        rank_of(t, p, e, i, tp=tp, pp=pp, ep=ep, dp=dp)
                        for i in range(dp)))
    else:
        out.append(tuple(range(tp * pp * ep * dp)))
    return tuple(out)

def _expand_dimension(intent: CollectiveIntent, index: int,
                      parallelism: ParallelismShape,
                      ) -> tuple[tuple[int, ...], ...]:
    """Participant groups for one intent's dimension (B4).

    Total and deterministic: groups derive from the sealed rank algebra
    (coverage, disjointness, cardinality by construction), so no rank is
    guessed.
    """
    dim = intent.dimension
    tp, pp, ep, dp = (parallelism.tp, parallelism.pp,
                      parallelism.ep, parallelism.dp)
    if dim == CollectiveDimension.GLOBAL:
        return _groups_for_dimension(tp, pp, ep, dp, "GLOBAL")
    if dim == CollectiveDimension.PP:
        raise UnsupportedSemantics(
            f"collective #{index} ({intent.kind.value}): PP-dimension "
            f"collectives are UNSUPPORTED — pipeline stages are not "
            f"collective peers (stages communicate point-to-point); "
            f"pp>1 geometry still scopes TP/DP groups within stages")
    family = dim.value
    return _groups_for_dimension(tp, pp, ep, dp, family)

#: Canonical lowering is a pure function of the request's design_hash and the
#: resulting workload is immutable — yet preflight, evaluation-plan, evaluate,
#: requirements and capability-truth each re-lower the SAME design from
#: scratch (millions of packets for correlator-class inputs). Memoize it.
#: Deliberately tiny: the lowered workload is large, so this exists to stop a
#: repeat lowering within a session, not to memoize the whole server.
_LOWERED_CACHE: dict[str, "LoweredWorkload"] = {}
_LOWERED_CACHE_LIMIT = 2


def lower_compile_workload(request: CompileRequestV3) -> LoweredWorkload:
    """Lower a v3 request's workload intent to a canonical WorkloadGraph.
    Raises:
        InvalidInput: non-v3 request, empty intent, BROADCAST root
            outside an expanded group, or sidecar mismatch (internal).
        UnsupportedSemantics: non-dense/non-MoE family, PP-dimension
            collective, single-member group, or otherwise unprovable
            intent.
        UnsupportedSchedule: payload indivisible under the pinned
            schedule (from collective_schedule, unmodified).

Rationale: docs/decisions/modules/workload.md
    """
    from veritx_dse.model.generation import is_v4_request
    if not isinstance(request, CompileRequestV3) and not is_v4_request(request):
        raise InvalidInput(
            f"lower_compile_workload takes a CompileRequestV3 or a "
            f"CompileRequestV4, got "
            f"{type(request).__name__} — v2 interpretation is frozen; "
            f"migrate explicitly via migrate_v2_to_v3")

    _cache_key = request.design_hash()
    _cached = _LOWERED_CACHE.get(_cache_key)
    if _cached is not None:
        return _cached

    wl = request.workload
    declared = tuple(getattr(wl, "collectives", ()) or ())
    if wl.model_family not in (ModelFamily.DENSE_TRANSFORMER,
                               ModelFamily.MOE) and not declared:
        raise UnsupportedSemantics(
            f"model_family={wl.model_family.value} declares no collectives "
            "— a non-transformer family has no implicit intent→collective "
            "mapping, so it must state its collectives explicitly (kind, "
            "dimension, payload_bytes, traffic_class)")
    compute = getattr(request, "compute", None)
    compute_stages = tuple(getattr(compute, "stages", ()) or ())
    if not declared and not compute_stages:
        raise InvalidInput(
            "intent declares no collectives and no compute — an empty "
            "workload specifies nothing to lower (compute is DECLARED, "
            "never inferred: fabricating durations or memory operands "
            "would be dishonest)")
    parallelism = ParallelismShape(tp=wl.tp, pp=wl.pp, ep=wl.ep, dp=wl.dp)
    participant_count = parallelism.world_size

    from veritx_dse.workload.graph import OperationNode, compute_detail

    operations: list[OperationNode] = []
    class_pairs: list[tuple[str, str]] = []
    prev_op_id: str | None = None
    for index, stage in enumerate(compute_stages):
        op_id = f"k{index:03d}_{stage.stage_id}"
        operations.append(OperationNode(
            operation_id=op_id,
            kind="COMPUTE",
            deps=(prev_op_id,) if prev_op_id is not None else (),
            detail=compute_detail(
                duration_ns=stage.duration_ns,
                input_bytes=stage.input_bytes,
                weight_bytes=stage.weight_bytes,
                output_bytes=stage.output_bytes,
                input_loc=stage.input_loc,
                weight_loc=stage.weight_loc,
                output_loc=stage.output_loc,
                participant_count=participant_count),
            owner=stage.owner,
            label=f"compute {stage.stage_id}",
        ))
        prev_op_id = op_id
    for i, intent in enumerate(wl.collectives):
        if not isinstance(intent, CollectiveIntent):
            raise InvalidInput(
                f"collective #{i} must be a CollectiveIntent")
        groups = _expand_dimension(intent, i, parallelism)
        kind_name = _intent_kind_name(intent)
        for j, members in enumerate(groups):
            if len(members) < 2:
                raise UnsupportedSemantics(
                    f"collective #{i} ({intent.kind.value} over "
                    f"{intent.dimension.value}): group {j} has "
                    f"{len(members)} member(s) — a one-member collective "
                    f"intent is never represented")
            collective_schedule(kind_name, len(members),
                                intent.payload_bytes)
            source: int | None = None
            if intent.kind == CollectiveKind.BROADCAST:
                assert intent.source_rank is not None
                if intent.source_rank not in members:
                    raise InvalidInput(
                        f"collective #{i} BROADCAST source_rank "
                        f"{intent.source_rank} is not in expanded group "
                        f"{j} {list(members)} — refusing to invent a "
                        f"per-group root")
                source = intent.source_rank
            op_id = (f"c{i:03d}_{intent.kind.value}_"
                     f"{intent.dimension.value.lower()}_g{j:02d}")
            detail = collective_detail(
                collective_kind=kind_name,
                participants=members,
                payload_bytes=intent.payload_bytes,
                participant_count=participant_count,
                scope=None,
                source=source,
            )
            operations.append(OperationNode(
                operation_id=op_id,
                kind="COLLECTIVE",
                deps=(prev_op_id,) if prev_op_id is not None else (),
                detail=detail,
                label=f"{kind_name} {intent.dimension.value} group {j}",
            ))
            class_pairs.append((op_id, intent.traffic_class))
            prev_op_id = op_id

    # Compute provenance survives lowering: the durations in the COMPUTE
    # operations below are only as trustworthy as their source, so the
    # source rides in the graph provenance where comparison and evidence
    # can read it. No compute stages means no compute origin to carry.
    _source = getattr(compute, "source", None)
    if hasattr(_source, "to_dict"):
        compute_source = _source.to_dict()
    elif isinstance(_source, dict):
        compute_source = dict(_source)
    else:
        compute_source = {"kind": "unspecified",
                          "detail": "no compute stages in this lowering",
                          "reference": ""}
    graph = WorkloadGraph(
        parallelism=parallelism,
        participant_count=participant_count,
        operations=tuple(operations),
        semantics=WorkloadSemantics(),
        provenance={
            "lowerer": LOWERER_ID,
            "lowering_schema_version": LOWERING_SCHEMA_VERSION,
            "design_hash": request.design_hash(),
            "collective_intents": len(wl.collectives),
            "compute_stages": len(compute_stages),
            "compute_source": compute_source,
        },
    )
    graph.require_total_order()
    lowered = LoweredWorkload(
        graph=graph,
        traffic_class_by_operation=tuple(sorted(class_pairs)),
        design_hash=request.design_hash(),
    )
    if len(_LOWERED_CACHE) >= _LOWERED_CACHE_LIMIT:
        _LOWERED_CACHE.clear()
    _LOWERED_CACHE[_cache_key] = lowered
    return lowered

def build_single_class_messages(
        lowered: LoweredWorkload) -> LogicalMessageArtifactV2:
    """Logical messages for a single-class lowering (common fast path).

Rationale: docs/decisions/modules/workload.md
    """
    if not isinstance(lowered, LoweredWorkload):
        raise InvalidInput(
            f"build_single_class_messages takes a LoweredWorkload, got "
            f"{type(lowered).__name__}")
    unified = lowered.unified_traffic_class
    if unified is None:
        raise UnsupportedSemantics(
            f"lowering spans classes {list(lowered.classes)} — one "
            f"LogicalMessageArtifactV2 cannot carry per-message classes; "
            f"the P1B evaluator binds each operation's class from "
            f"traffic_class_by_operation instead")
    return LogicalMessageArtifactV2(graph=lowered.graph,
                                    traffic_class=unified)

def build_multi_class_messages(
        lowered: LoweredWorkload) -> LogicalMessageArtifactV3:
    """Logical messages for a multi-class lowering (MoE fast path).

Rationale: docs/decisions/modules/workload.md
    """
    if not isinstance(lowered, LoweredWorkload):
        raise InvalidInput(
            f"build_multi_class_messages takes a LoweredWorkload, got "
            f"{type(lowered).__name__}")
    if lowered.unified_traffic_class is not None:
        raise InvalidInput(
            f"lowering is single-class "
            f"({lowered.unified_traffic_class!r}): use "
            f"build_single_class_messages, never a V3 artifact")
    return LogicalMessageArtifactV3(
        graph=lowered.graph,
        traffic_class_by_operation=lowered.traffic_class_by_operation)

def _assert_bound_on_assignment(lowered: LoweredWorkload,
                                vc_assignment: Any,
                                classes: tuple[str, ...]) -> None:
    """The flat, ONE-assignment class/VC admission check.

    ``classes`` is the set of traffic classes this assignment is the
    authority for. On a single-plane design that is every lowered class;
    on a multi-plane fabric it is only the classes bound to this subnet.

Rationale: docs/decisions/modules/workload.md
    """
    try:
        entries = dict((cls, tuple(vcs))
                       for cls, vcs in vc_assignment.traffic_class_to_vcs)
    except (AttributeError, TypeError, ValueError) as exc:
        raise InvalidInput(
            f"vc_assignment has no valid traffic_class_to_vcs mapping: "
            f"{exc}") from exc
    for cls in classes:
        if cls not in entries or not entries[cls]:
            raise MappingInvalid(
                f"traffic class {cls!r} has no legal VC mapping in the "
                f"VC assignment (known: {sorted(entries)}) — refusing an "
                f"unroutable class instead of silently using VC0")
    routing_of = getattr(vc_assignment, "vc_to_routing_class", None)
    transitions = getattr(vc_assignment, "allowed_transitions", None)
    envelope = getattr(vc_assignment, "vc_ids", None)
    if routing_of is None or transitions is None or envelope is None:
        raise MappingInvalid(
            "VC assignment carries no routing authority "
            "(vc_to_routing_class / allowed_transitions / vc_ids): "
            "the deadlock proof cannot reason about these classes — "
            "refusing")
    try:
        routing_of = dict(routing_of)
        envelope = tuple(envelope)
    except (AttributeError, TypeError, ValueError) as exc:
        raise MappingInvalid(
            f"VC assignment routing authority is malformed: {exc}"
        ) from exc
    bound = {cls: set(entries[cls]) for cls in classes}
    for cls in sorted(bound):
        missing = sorted(vc for vc in bound[cls] if vc not in routing_of)
        if missing:
            raise MappingInvalid(
                f"traffic class {cls!r} uses VCs {missing} with no "
                f"routing class: the (channel, VC) proof cannot cover "
                f"them — refusing")
    missing_ends = sorted({vc for pair in transitions for vc in pair}
                          - set(routing_of))
    if missing_ends:
        raise MappingInvalid(
            f"allowed VC transitions touch {missing_ends} with no "
            f"routing class: the (channel, VC) proof cannot cover them "
            f"— refusing")
    users: dict[int, list[str]] = {}
    for cls, vcs in bound.items():
        for vc in vcs:
            users.setdefault(vc, []).append(cls)
    shared = {vc: names for vc, names in users.items()
              if len(names) > 1}
    if shared and any(set(entries[cls]) != set(envelope)
                       for cls in bound):
        detail = "; ".join(
            f"VC {vc} shared by {sorted(names)}"
            for vc, names in sorted(shared.items()))
        raise MappingInvalid(
            f"traffic classes share VC subsets ({detail}) the backend "
            f"does not execute: every bound class must carry the full "
            f"VC envelope {sorted(envelope)} — refusing")


def assert_traffic_classes_bound(lowered: LoweredWorkload,
                                 vc_assignment: Any, *,
                                 multi_plane: Any = None) -> None:
    """Admission check mirroring the evaluator traffic-class gate (B3).

    Without ``multi_plane`` this is the flat single-subnet check. WITH it,
    Plane C is a SECOND subnet whose VC index space is independent of Plane
    D's, so each class is admitted against ITS OWN subnet's assignment and
    "shared VC" is only meaningful WITHIN a subnet: two classes on different
    subnets never share a resource even when their indices coincide.

Rationale: docs/decisions/modules/workload.md
    """
    if not isinstance(lowered, LoweredWorkload):
        raise InvalidInput(
            f"assert_traffic_classes_bound takes a LoweredWorkload, got "
            f"{type(lowered).__name__}")
    if multi_plane is None:
        _assert_bound_on_assignment(lowered, vc_assignment, lowered.classes)
        return
    from veritx_dse.model.multi_plane_vc import (
        MultiPlaneVCError, MultiPlaneVCAssignment,
    )
    if not isinstance(multi_plane, MultiPlaneVCAssignment):
        raise InvalidInput(
            f"multi_plane must be a MultiPlaneVCAssignment or None, got "
            f"{type(multi_plane).__name__}")
    primary_hash = getattr(vc_assignment, "vc_assignment_hash", None)
    if (not callable(primary_hash)
            or primary_hash() != multi_plane.primary.vc_assignment_hash()):
        raise MappingInvalid(
            "the multi-plane binding's primary is not the compiled VC "
            "assignment — refusing a binding that describes another fabric")
    by_subnet: dict[int, list[str]] = {}
    for cls in lowered.classes:
        try:
            subnet = multi_plane.subnet_of(cls)
        except MultiPlaneVCError as exc:
            raise MappingInvalid(
                f"traffic class {cls!r} has no subnet binding on a "
                f"multi-plane fabric — refusing an unroutable class "
                f"instead of guessing a plane") from exc
        by_subnet.setdefault(subnet, []).append(cls)
    for subnet in sorted(by_subnet):
        _assert_bound_on_assignment(
            lowered, multi_plane.assignment_for(subnet),
            tuple(by_subnet[subnet]))

def bridge_to_evaluation_messages(
        lowered: LoweredWorkload, *,
        requested_traffic_class: str | None = None,
) -> LogicalMessageArtifactV2:
    """P1B integration bridge: lowered workload → evaluator messages.

Rationale: docs/decisions/modules/workload.md
    """
    if not isinstance(lowered, LoweredWorkload):
        raise InvalidInput(
            f"bridge_to_evaluation_messages takes a LoweredWorkload, "
            f"got {type(lowered).__name__}")
    unified = lowered.unified_traffic_class
    if unified is None:
        raise UnsupportedSemantics(
            f"lowering spans classes {list(lowered.classes)}: no "
            f"single-class V2 message artifact can represent "
            f"per-operation classes without loss — use the V3 "
            f"multi-class lowering (its artifact executes on the "
            f"certified multi-class profile)")
    if requested_traffic_class is not None and \
            requested_traffic_class != unified:
        raise InvalidInput(
            f"requested traffic class {requested_traffic_class!r} does "
            f"not match the lowered class {unified!r}: eval-time "
            f"relabeling is refused (EvaluationOptions.traffic_class "
            f"is an assertion, never a label)")
    return build_single_class_messages(lowered)

__all__ = [
    "LOWERER_ID",
    "LOWERING_SCHEMA_VERSION",
    "LoweredWorkload",
    "assert_traffic_classes_bound",
    "bridge_to_evaluation_messages",
    "build_single_class_messages",
    "build_multi_class_messages",
    "lower_compile_workload",
]
