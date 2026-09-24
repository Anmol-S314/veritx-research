"""veritx_dse.workload.intent_lowering — v3 intent → canonical WorkloadGraph.

P1C: product workload intent lowers deterministically to the ONE canonical
WorkloadGraph authority (workload/graph.py — consumed, never forked). v2
requests are REFUSED here: v2 interpretation is frozen, and a
v2 CollectiveOp carries no dimension/payload/traffic-class facts to lower
from (compile_model B1 finding 1). Migrate explicitly first.

Lowering laws (all enforced, none assumed):

* **Dimensions derive groups, never guesses.** TP/DP/EP expand through
  ParallelismArtifact.groups (total, law-checked: every rank in exactly
  one group — tp=8,dp=4 yields four TP groups of eight). GLOBAL is the
  single all-ranks group. Group membership is derived, so participants
  are exact by construction; ranks are never guessed from group_size.
* **PP stages are not collective peers.** A PP-dimension COLLECTIVE is a
  typed refusal (stages communicate point-to-point; no proven peer
  semantics). pp>1 GEOMETRY is still supported: TP/DP groups scope
  within stages via the canonical rank algebra.
* **Dense transformer only.** Any other model family is a typed refusal —
  MoE dispatch/combine, diffusion, CNN, and custom topologies have no
  proven intent→collective mapping here.
* **Ordered collectives.** Declared intent order becomes an explicit op
  chain (each op depends on its predecessor), so the graph has a unique
  dependency-derived total order. Declaration order is therefore v3
  identity (reordering intents is a different design).
* **No fabricated roots, scopes, or phases.** BROADCAST requires an
  explicit source_rank present in EVERY expanded group (multi-group
  broadcast with one root refuses rather than inventing per-group
  roots); scope is always None (undeclared is not ALL); phase is always
  None — serving_mode is serving characterization, never a per-operation
  phase declaration (no PREFILL_HEAVY -> pure-PREFILL mapping without
  evidence, and none is claimed).
* **Schedulability proven at lower time.** Every expanded group is
  checked against workload/collectives.py::collective_schedule (the
  pinned schedule authority) before the op is built: divisibility
  (B % k), minimums, and kind support refuse HERE, not at the backend.
* **Traffic classes ride alongside, not inside.** The canonical detail
  grammar carries no traffic-class field (by canonical law), so the
  lowering returns the graph PLUS a per-operation class sidecar
  (LoweredWorkload). One class per message is P1B evaluator wire-up
  (single-class fast path: build_single_class_messages); this module
  never forks messages.py.

B1 audit findings (for the record — see compile_model v3 section for
full evidence): the v2 per-element byte-count field meaning unproven (never
here); DependencyGraph names ad hoc in v2 (v3 unifies through
derive_v3_traffic_classes); v2 Requirement has no traffic_class;
LogicalMessageArtifactV2 is single-class (hence the sidecar);
trace_path is environment-sensitive (v3 has no path field).
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
from veritx_dse.workload.messages import LogicalMessageArtifactV2

LOWERING_SCHEMA_VERSION = 1
LOWERER_ID = "veritx_dse.workload.intent_lowering/v3.1"


@dataclass(frozen=True)
class LoweredWorkload:
    """A v3 lowering result: canonical graph + traffic-class sidecar.

    ``graph`` is the canonical authority (identity-bearing).
    ``traffic_class_by_operation`` maps every COLLECTIVE operation id to
    its unified-namespace class (sorted by operation id; complete: every
    graph COLLECTIVE op appears exactly once). ``design_hash`` binds the
    v3 request identity this was lowered from.
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
    else:  # GLOBAL
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
    family = dim.value  # TP / DP / EP match the group families
    return _groups_for_dimension(tp, pp, ep, dp, family)


def lower_compile_workload(request: CompileRequestV3) -> LoweredWorkload:
    """Lower a v3 request's workload intent to a canonical WorkloadGraph.

    Supported: dense transformer + TP/DP/EP/GLOBAL intents with ordered
    collectives. Everything else is a typed refusal (see module laws).
    Deterministic: same request -> byte-identical graph (workload_id
    stable across runs and processes).

    Raises:
        InvalidInput: non-v3 request, empty intent, BROADCAST root
            outside an expanded group, or sidecar mismatch (internal).
        UnsupportedSemantics: non-dense family, PP-dimension collective,
            single-member group, or otherwise unprovable intent.
        UnsupportedSchedule: payload indivisible under the pinned
            schedule (from collective_schedule, unmodified).
    """
    if not isinstance(request, CompileRequestV3):
        raise InvalidInput(
            f"lower_compile_workload takes a CompileRequestV3, got "
            f"{type(request).__name__} — v2 interpretation is frozen; "
            f"migrate explicitly via migrate_v2_to_v3")
    wl = request.workload
    if wl.model_family != ModelFamily.DENSE_TRANSFORMER:
        raise UnsupportedSemantics(
            f"intent lowering supports model_family=dense_transformer, "
            f"got {wl.model_family.value} — MoE dispatch/combine, "
            f"diffusion, CNN, and custom intents have no proven "
            f"intent→collective mapping here")
    if not wl.collectives:
        raise InvalidInput(
            "intent declares no collectives — a fabric workload with no "
            "communication is under-specified (compute lowering is not "
            "established: fabricating compute durations would be "
            "dishonest)")
    parallelism = ParallelismShape(tp=wl.tp, pp=wl.pp, ep=wl.ep, dp=wl.dp)
    participant_count = parallelism.world_size

    from veritx_dse.workload.graph import OperationNode

    operations: list[OperationNode] = []
    class_pairs: list[tuple[str, str]] = []
    prev_op_id: str | None = None
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
            # Prove schedulability against the pinned authority NOW.
            collective_schedule(kind_name, len(members),
                                intent.payload_bytes)
            source: int | None = None
            if intent.kind == CollectiveKind.BROADCAST:
                assert intent.source_rank is not None  # ctor law
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
                scope=None,  # undeclared is not ALL — never fabricated
                source=source,
            )
            operations.append(OperationNode(
                operation_id=op_id,
                kind="COLLECTIVE",
                deps=(prev_op_id,) if prev_op_id is not None else (),
                detail=detail,
                # phase stays None: serving_mode never maps to a
                # per-operation phase (no evidence for the mapping).
                label=f"{kind_name} {intent.dimension.value} group {j}",
            ))
            class_pairs.append((op_id, intent.traffic_class))
            prev_op_id = op_id

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
        },
    )
    # The chain construction guarantees a unique dependency order; prove
    # it (a positional source must satisfy this naturally, and any
    # future edit that breaks chaining refuses here, not downstream).
    graph.require_total_order()
    return LoweredWorkload(
        graph=graph,
        traffic_class_by_operation=tuple(sorted(class_pairs)),
        design_hash=request.design_hash(),
    )


def build_single_class_messages(
        lowered: LoweredWorkload) -> LogicalMessageArtifactV2:
    """Logical messages for a single-class lowering (common fast path).

    Refuses multi-class lowerings: one V2 artifact assigns one class to
    every message, so a multi-class graph cannot be represented without
    loss. Per-message classes are P1B evaluator wire-up (integration
    note in the P1C report); this helper covers the mesh_dense_64 case
    where every intent shares one class.
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


def assert_traffic_classes_bound(lowered: LoweredWorkload,
                                 vc_assignment: Any) -> None:
    """Admission check mirroring the evaluator traffic-class gate (B3).

    Every lowered class must exist in the VC artifact's
    traffic_class_to_vcs with a non-empty legal VC set. Unknown class =
    typed refusal, never a silent VC0. P1B calls the same predicate
    before backend spawn; P1C calls it at lowering time so an unbound
    intent fails before any evaluation is attempted.
    """
    if not isinstance(lowered, LoweredWorkload):
        raise InvalidInput(
            f"assert_traffic_classes_bound takes a LoweredWorkload, got "
            f"{type(lowered).__name__}")
    try:
        entries = dict((cls, tuple(vcs))
                       for cls, vcs in vc_assignment.traffic_class_to_vcs)
    except (AttributeError, TypeError, ValueError) as exc:
        raise InvalidInput(
            f"vc_assignment has no valid traffic_class_to_vcs mapping: "
            f"{exc}") from exc
    for cls in lowered.classes:
        if cls not in entries or not entries[cls]:
            raise MappingInvalid(
                f"traffic class {cls!r} has no legal VC mapping in the "
                f"VC assignment (known: {sorted(entries)}) — refusing an "
                f"unroutable class instead of silently using VC0")




def bridge_to_evaluation_messages(
        lowered: LoweredWorkload, *,
        requested_traffic_class: str | None = None,
) -> LogicalMessageArtifactV2:
    """P1B integration bridge: lowered workload → evaluator messages.

    P1C phase-2 (Fix 3). The P1B evaluator takes one global traffic
    class while LoweredWorkload carries per-operation classes:

    * **Supported first case** — the lowering is single-class
      (``unified_traffic_class is not None``): route through
      build_single_class_messages() into the canonical
      LogicalMessage → PhysicalTraffic → gates → backend chain.
      Every message honestly carries the lowered class.
    * **Multi-class → typed refusal** (UnsupportedSemantics, code
      UNSUPPORTED_SEMANTICS — P1B maps it to EvaluationOutcome
      UNSUPPORTED): one V2 artifact cannot carry per-message classes,
      so representing it would be lossy. This stands until a
      versioned per-operation message artifact lands. The collective
      schedule is NOT forked, v2 message identity is NOT mutated, and
      the sidecar (traffic_class_by_operation) is kept as the
      per-operation record for that future artifact.

    ``requested_traffic_class`` carries the P1B
    EvaluationOptions.traffic_class through as an ASSERTION, never a
    label: when given it must equal the lowered class, else refusal.
    Direction for P1B: that option is legacy/test-only — a user must
    never relabel traffic at eval time (e.g. best_effort evaluated as
    latency_critical would forge QoS evidence). The lowered intent
    owns class names; evaluation only checks them.
    """
    if not isinstance(lowered, LoweredWorkload):
        raise InvalidInput(
            f"bridge_to_evaluation_messages takes a LoweredWorkload, "
            f"got {type(lowered).__name__}")
    unified = lowered.unified_traffic_class
    if unified is None:
        raise UnsupportedSemantics(
            f"lowering spans classes {list(lowered.classes)}: no "
            f"single-class message artifact can represent per-operation "
            f"classes without loss — UNSUPPORTED until a versioned "
            f"per-operation message artifact lands (sidecar retained)")
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
    "lower_compile_workload",
]
