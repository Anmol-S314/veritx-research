"""veritx_dse.workload.canonical_graph — the ONE canonical workload authority.

Slice 2c, step 1: the authority itself. Nothing consumes it yet.

This module will become ``workload/graph.py`` when the competing
authorities are deleted (step 10): ``WaveDWorkload`` currently owns that
path. It is deliberately NOT named ``graph.py`` yet, because two workload
authorities in one module is worse than two modules for one migration
step, and a forwarding shim is forbidden.

Design laws (all enforced, none assumed):

* **One operation, one payload.** An ``OperationNode`` carries its closed
  per-kind ``detail`` mapping. There is no ``collectives=`` /
  ``p2p_transfers=`` / ``multicasts=`` side list to re-join by id.
* **The participant namespace is not the geometry.**
  ``participant_count`` is the rank space the operations address;
  ``parallelism`` is the system geometry. For a two-instance cluster they
  are 4 and 8. Ranks validate against ``participant_count``.
* **Absent stays absent.** ``owner``, ``phase``, ``step``, ``scope`` and
  ``routing_policy`` are optional because a legitimate source may not
  declare them. ``scope=None`` (undeclared) is NOT ``scope="ALL"``.
* **Declarations are permissive; schedules are strict.** A non-divisible
  ALLREDUCE is a valid declaration; the exact ring expansion refuses it.
  That law lives in ``workload/collectives.py``, not here.
* **Provenance never moves identity.** ``provenance`` is not hashed;
  labels and source spellings are not science (finding F23).
* **Structure is checked before any backend.** Stray/unclosed EXPERT and
  PIM regions refuse HERE, not as a Chakra IndexError.

Identity uses the shared ``core.artifact`` machinery — one implementation.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Iterable

from veritx_dse.core.artifact import (
    EvidenceInvalid, FrozenMap, ImmutableError, InvalidInput, content_hash,
    freeze, require_embedded_id, require_fields, require_schema_version,
    require_type_tag, thaw,
)
from veritx_dse.core.errors import (
    MappingInvalid, UnsupportedSchedule, UnsupportedSemantics,
)
from veritx_dse.model.parallelism import ParallelismArtifact

SCHEMA_VERSION = 1
_HASH_TYPE_TAG = "srota/WorkloadGraph"

# ── the canonical operation vocabulary (eight kinds) ────────────────────
KIND_COMPUTE = "COMPUTE"
KIND_COLLECTIVE = "COLLECTIVE"
KIND_P2P = "P2P"
KIND_MULTICAST = "MULTICAST"
KIND_EXPERT_BEGIN = "EXPERT_BEGIN"
KIND_EXPERT_END = "EXPERT_END"
KIND_PIM_BEGIN = "PIM_BEGIN"
KIND_PIM_END = "PIM_END"
ALL_KINDS = (KIND_COMPUTE, KIND_COLLECTIVE, KIND_P2P, KIND_MULTICAST,
             KIND_EXPERT_BEGIN, KIND_EXPERT_END, KIND_PIM_BEGIN, KIND_PIM_END)

# collective kinds a COLLECTIVE / EXPERT payload may name
COLLECTIVE_KINDS = ("ALLREDUCE", "REDUCESCATTER", "ALLGATHER", "ALLTOALL",
                    "BROADCAST")
# p2p roles: a Wave-D P2P is a complete transfer; legacy SEND/RECV rows are
# not paired here, ever
P2P_ROLES = ("TRANSFER", "SEND", "RECV")
# replication strategies (MULTICAST)
REPLICATION_KINDS = ("SOURCE_REPLICATION",)

# scope: three DISTINCT states.  None = undeclared, ALL = explicitly all
# dimensions, tuple = explicit dimension mask.
SCOPE_ALL = "ALL"

# canonical-v2 normalizes genuine semantic DEFAULTS (values), never
# absences. These are the Phase-9 defaults, stated explicitly.
DEFAULT_LOC = "LOCAL"
DEFAULT_BATCH_TAG = "NONE"

# closed key sets -------------------------------------------------------
_COMPUTE_KEYS = frozenset({
    "duration_ns", "input_bytes", "weight_bytes", "output_bytes",
    "input_loc", "weight_loc", "output_loc", "batch_tag",
})
_COLLECTIVE_KEYS = frozenset({
    "collective_kind", "participants", "payload_bytes", "scope", "source",
})
_P2P_KEYS = frozenset({"role", "src_rank", "dst_rank", "payload_bytes"})
_MULTICAST_KEYS = frozenset({"source_rank", "destinations", "payload_bytes",
                             "replication"})
_EXPERT_KEYS = frozenset({
    "expert_num", "collective_kind", "participants", "payload_bytes", "scope",
})
_PIM_BEGIN_KEYS = frozenset({"channel"})
_PIM_END_KEYS = frozenset()
DETAIL_KEYS = {
    KIND_COMPUTE: _COMPUTE_KEYS,
    KIND_COLLECTIVE: _COLLECTIVE_KEYS,
    KIND_P2P: _P2P_KEYS,
    KIND_MULTICAST: _MULTICAST_KEYS,
    KIND_EXPERT_BEGIN: _EXPERT_KEYS,
    KIND_EXPERT_END: _EXPERT_KEYS,
    KIND_PIM_BEGIN: _PIM_BEGIN_KEYS,
    KIND_PIM_END: _PIM_END_KEYS,
}

_NODE_KEYS = frozenset({"operation_id", "kind", "deps", "owner", "phase",
                        "step", "label", "detail"})
_GRAPH_KEYS = frozenset({"type", "schema_version", "parallelism",
                         "participant_count", "semantics", "operations",
                         "provenance", "workload_id"})
_SEMANTICS_KEYS = frozenset({"phase", "routing_policy", "shape",
                             "model_descriptor", "model_descriptor_hash"})
_PHASES = ("PREFILL", "DECODE")
_OPTIONAL_NODE_FIELDS = ("owner", "phase", "step")


def _int(value: Any, what: str, *, minimum: int = 0,
         optional: bool = False) -> int | None:
    if value is None and optional:
        return None
    if type(value) is not int or isinstance(value, bool) or value < minimum:
        raise InvalidInput(f"{what} must be an int >= {minimum}, got "
                           f"{value!r}")
    return value


def _str(value: Any, what: str, *, optional: bool = False) -> str | None:
    if value is None and optional:
        return None
    if not isinstance(value, str) or not value:
        raise InvalidInput(f"{what} must be a non-empty string, got "
                           f"{value!r}")
    return value


def _norm_scope(scope: Any, what: str) -> str | tuple[bool, ...] | None:
    """Three states, never collapsed: None != ALL != mask."""
    if scope is None:
        return None
    if scope == SCOPE_ALL:
        return SCOPE_ALL
    if isinstance(scope, (list, tuple)) and scope and \
            all(isinstance(v, bool) for v in scope):
        return tuple(scope)
    raise InvalidInput(
        f"{what}: scope must be None (undeclared), {SCOPE_ALL!r}, or a "
        f"non-empty boolean dim mask — got {scope!r}")


def _ranks(value: Any, what: str, count: int,
           *, minimum: int = 1) -> tuple[int, ...]:
    if not isinstance(value, (list, tuple)) or not value:
        raise InvalidInput(f"{what} must be a non-empty sequence of ranks")
    out: list[int] = []
    for p in value:
        if type(p) is not int or isinstance(p, bool) or p < 0 or p >= count:
            raise InvalidInput(
                f"{what}: rank {p!r} outside the participant namespace "
                f"[0, {count})")
        out.append(p)
    if len(set(out)) != len(out):
        raise InvalidInput(f"{what} has duplicate ranks: {sorted(out)}")
    if minimum and len(out) < minimum:
        raise InvalidInput(
            f"{what}: {len(out)} participant(s); a collective needs >= "
            f"{minimum}")
    return tuple(out)


# ── per-kind detail builders (validated, closed) ────────────────────────
def compute_detail(*, duration_ns: int, input_bytes: int | None = None,
                   weight_bytes: int | None = None,
                   output_bytes: int | None = None,
                   input_loc: str = DEFAULT_LOC,
                   weight_loc: str = DEFAULT_LOC,
                   output_loc: str = DEFAULT_LOC,
                   batch_tag: str = DEFAULT_BATCH_TAG) -> FrozenMap:
    """COMPUTE payload. v2 states the defaults EXPLICITLY (they are values,
    not absences) so the canonical form is readable without knowing the
    legacy compressor."""
    _int(duration_ns, "duration_ns")
    _str(batch_tag, "batch_tag")
    for name, v in (("input_loc", input_loc), ("weight_loc", weight_loc),
                    ("output_loc", output_loc)):
        _str(v, name)
    for name, v in (("input_bytes", input_bytes),
                    ("weight_bytes", weight_bytes),
                    ("output_bytes", output_bytes)):
        if v is not None:
            _int(v, name)
    return freeze({
        "duration_ns": duration_ns,
        "input_bytes": input_bytes, "weight_bytes": weight_bytes,
        "output_bytes": output_bytes,
        "input_loc": input_loc, "weight_loc": weight_loc,
        "output_loc": output_loc, "batch_tag": batch_tag,
    })


def collective_detail(*, collective_kind: str, participants: Iterable[int],
                      payload_bytes: int, participant_count: int,
                      scope: Any = None, source: int | None = None
                      ) -> FrozenMap:
    """COLLECTIVE payload. BROADCAST requires an explicit ``source``; every
    other kind refuses one (a declared source on ALLREDUCE would be a
    fabricated field)."""
    if collective_kind not in COLLECTIVE_KINDS:
        raise UnsupportedSemantics(
            f"collective kind {collective_kind!r} is outside the canonical "
            f"set {COLLECTIVE_KINDS}")
    _int(payload_bytes, "payload_bytes", minimum=1)
    ranks = _ranks(participants, "participants", participant_count)
    if collective_kind == "BROADCAST":
        if source is None:
            raise InvalidInput(
                "BROADCAST requires an explicit source rank — "
                "participants[0] is a legacy convenience, not a law")
        if source not in ranks:
            raise InvalidInput(
                f"BROADCAST source {source} is not among the participants")
    elif source is not None:
        raise InvalidInput(
            f"{collective_kind} must not declare a source (got {source!r})")
    return freeze({
        "collective_kind": collective_kind, "participants": ranks,
        "payload_bytes": payload_bytes,
        "scope": _norm_scope(scope, "collective scope"), "source": source,
    })


def p2p_detail(*, role: str, src_rank: int, dst_rank: int,
               payload_bytes: int, participant_count: int) -> FrozenMap:
    """P2P payload. ``TRANSFER`` is a complete Wave-D transfer; ``SEND`` /
    ``RECV`` are legacy identity-bearing roles and are NOT paired here."""
    if role not in P2P_ROLES:
        raise InvalidInput(f"p2p role must be one of {P2P_ROLES}, "
                           f"got {role!r}")
    _int(payload_bytes, "payload_bytes", minimum=1)
    _ranks((src_rank,), "src_rank", participant_count)
    _ranks((dst_rank,), "dst_rank", participant_count)
    if src_rank == dst_rank:
        raise InvalidInput("p2p src_rank and dst_rank must differ")
    return freeze({"role": role, "src_rank": src_rank, "dst_rank": dst_rank,
                   "payload_bytes": payload_bytes})


def multicast_detail(*, source_rank: int, destinations: Iterable[int],
                     payload_bytes: int, replication: str,
                     participant_count: int) -> FrozenMap:
    if replication not in REPLICATION_KINDS:
        raise UnsupportedSemantics(
            f"multicast replication {replication!r} is outside "
            f"{REPLICATION_KINDS}")
    _int(payload_bytes, "payload_bytes", minimum=1)
    _ranks((source_rank,), "source_rank", participant_count)
    dests = _ranks(destinations, "destinations", participant_count)
    if source_rank in dests:
        raise InvalidInput(
            "multicast source must not appear among its destinations "
            "(source replication sends to OTHERS)")
    return freeze({"source_rank": source_rank, "destinations": dests,
                   "payload_bytes": payload_bytes, "replication": replication})


def expert_detail(*, expert_num: int | None = None,
                  collective_kind: str | None = None,
                  participants: Iterable[int] | None = None,
                  payload_bytes: int | None = None,
                  scope: Any = None, participant_count: int) -> FrozenMap:
    """EXPERT_BEGIN / EXPERT_END payload.

    Both markers may carry a collective: LLMServingSim emits a dispatch
    collective at BEGIN and a combine collective (e.g. REDUCESCATTER) at
    END. ``EXPERT_END`` is therefore NOT payload-free.
    """
    if expert_num is not None:
        _int(expert_num, "expert_num")
    if collective_kind is None:
        if participants is not None or payload_bytes is not None:
            raise InvalidInput(
                "expert marker: participants/payload_bytes require a "
                "collective_kind")
        return freeze({"expert_num": expert_num, "collective_kind": None,
                       "participants": None, "payload_bytes": None,
                       "scope": None})
    if collective_kind not in COLLECTIVE_KINDS:
        raise UnsupportedSemantics(
            f"expert collective kind {collective_kind!r} is outside the "
            f"canonical set {COLLECTIVE_KINDS}")
    if participants is None or payload_bytes is None:
        raise InvalidInput(
            "expert collective requires participants and payload_bytes")
    _int(payload_bytes, "payload_bytes", minimum=1)
    ranks = _ranks(participants, "participants", participant_count)
    return freeze({"expert_num": expert_num,
                   "collective_kind": collective_kind, "participants": ranks,
                   "payload_bytes": payload_bytes,
                   "scope": _norm_scope(scope, "expert scope")})


def pim_detail(*, channel: int) -> FrozenMap:
    """PIM_BEGIN payload: the channel identifier the region executes on."""
    _int(channel, "channel")
    return freeze({"channel": channel})


def pim_end_detail() -> FrozenMap:
    return freeze({})


# ── the operation node ──────────────────────────────────────────────────
@dataclass(frozen=True)
class OperationNode:
    """One canonical operation: identity, ordering, and exactly one
    closed per-kind ``detail`` payload."""

    operation_id: str
    kind: str
    deps: tuple[str, ...] = ()
    detail: Any = None
    owner: int | None = None
    phase: str | None = None
    step: int | None = None
    label: str = ""

    def __post_init__(self) -> None:
        _str(self.operation_id, "operation_id")
        if self.kind not in ALL_KINDS:
            raise InvalidInput(
                f"operation {self.operation_id!r}: unknown kind "
                f"{self.kind!r} (canonical kinds: {ALL_KINDS}) — an unknown "
                "operation never enters a valid workload")
        if not isinstance(self.deps, tuple) or \
                not all(isinstance(d, str) and d for d in self.deps):
            raise InvalidInput(
                f"operation {self.operation_id!r}: deps must be a tuple of "
                "non-empty operation ids")
        if self.operation_id in self.deps:
            raise InvalidInput(
                f"operation {self.operation_id!r} depends on itself")
        if len(set(self.deps)) != len(self.deps):
            raise InvalidInput(
                f"operation {self.operation_id!r}: duplicate dependencies")
        _int(self.owner, "owner", optional=True)
        if self.phase is not None and self.phase not in _PHASES:
            raise UnsupportedSemantics(
                f"operation {self.operation_id!r}: phase {self.phase!r} is "
                f"outside {_PHASES}")
        _int(self.step, "step", optional=True)
        if not isinstance(self.label, str):
            raise InvalidInput("label must be a string")
        try:
            frozen = freeze(self.detail)
        except ImmutableError as exc:
            raise InvalidInput(
                f"operation {self.operation_id!r}: detail is not a canonical "
                f"value: {exc}") from None
        if not isinstance(frozen, FrozenMap):
            raise InvalidInput(
                f"operation {self.operation_id!r}: detail must be an object")
        unknown = sorted(set(frozen) - DETAIL_KEYS[self.kind])
        if unknown:
            raise InvalidInput(
                f"operation {self.operation_id!r} ({self.kind}) has unknown "
                f"detail fields {unknown}; the per-kind schema is closed")
        object.__setattr__(self, "detail", frozen)

    #: which optional metadata was actually DECLARED (absence is meaningful)
    def declared_metadata(self) -> dict[str, Any]:
        return {name: getattr(self, name) for name in _OPTIONAL_NODE_FIELDS
                if getattr(self, name) is not None}

    def identity_dict(self) -> dict[str, Any]:
        """Semantic content only. ``label`` is presentation (F23): source
        spelling is not science."""
        return {
            "operation_id": self.operation_id,
            "kind": self.kind,
            "deps": list(self.deps),
            "owner": self.owner,
            "phase": self.phase,
            "step": self.step,
            "detail": thaw(self.detail),
        }

    def to_dict(self) -> dict[str, Any]:
        return {**self.identity_dict(), "label": self.label}

    @classmethod
    def from_dict(cls, d: Any, *, strict: bool = False
                  ) -> "OperationNode":
        if not isinstance(d, dict):
            raise InvalidInput("operation node must be an object")
        require_fields(d, _NODE_KEYS, "operation node")
        return cls(
            operation_id=d.get("operation_id"), kind=d.get("kind"),
            deps=tuple(d.get("deps") or ()), detail=d.get("detail"),
            owner=d.get("owner"), phase=d.get("phase"),
            step=d.get("step"), label=d.get("label", ""))


# ── the workload semantics envelope ─────────────────────────────────────
@dataclass(frozen=True)
class WorkloadSemantics:
    """Semantic envelope. Every field is OPTIONAL because a legitimate
    source may not declare it (Phase-9 declared neither a global phase nor
    a routing policy). Absent is not ``PREFILL``."""

    phase: str | None = None
    routing_policy: str | None = None
    shape: Any = None
    model_descriptor: str | None = None
    model_descriptor_hash: str | None = None

    def __post_init__(self) -> None:
        if self.phase is not None and self.phase not in _PHASES:
            raise UnsupportedSemantics(
                f"semantics phase {self.phase!r} is outside {_PHASES}")
        if self.routing_policy is not None:
            _str(self.routing_policy, "routing_policy")
        _str(self.model_descriptor, "model_descriptor", optional=True)
        _str(self.model_descriptor_hash, "model_descriptor_hash",
             optional=True)

    def identity_dict(self) -> dict[str, Any]:
        return {"phase": self.phase, "routing_policy": self.routing_policy,
                "shape": thaw(self.shape),
                "model_descriptor": self.model_descriptor,
                "model_descriptor_hash": self.model_descriptor_hash}

    def to_dict(self) -> dict[str, Any]:
        return self.identity_dict()

    @classmethod
    def from_dict(cls, d: Any, *, strict: bool = False
                  ) -> "WorkloadSemantics":
        if d is None:
            return cls()
        if not isinstance(d, dict):
            raise InvalidInput("semantics must be an object")
        require_fields(d, _SEMANTICS_KEYS, "semantics")
        return cls(phase=d.get("phase"),
                    routing_policy=d.get("routing_policy"),
                    shape=d.get("shape"),
                    model_descriptor=d.get("model_descriptor"),
                    model_descriptor_hash=d.get("model_descriptor_hash"))


# ── the graph ───────────────────────────────────────────────────────────
@dataclass(frozen=True)
class WorkloadGraph:
    """The one canonical workload authority.

    ``provenance`` is deliberately NOT part of ``workload_id()``: it
    carries source metadata (origin run, trace file, source spelling) that
    must never move scientific identity.
    """

    parallelism: ParallelismArtifact
    participant_count: int
    operations: tuple[OperationNode, ...]
    semantics: WorkloadSemantics = field(default_factory=WorkloadSemantics)
    provenance: Any = None
    schema_version: int = SCHEMA_VERSION

    def __post_init__(self) -> None:
        if not isinstance(self.parallelism, ParallelismArtifact):
            raise InvalidInput("parallelism must be a ParallelismArtifact")
        _int(self.participant_count, "participant_count", minimum=1)
        if self.schema_version != SCHEMA_VERSION:
            raise InvalidInput(
                f"unsupported schema_version {self.schema_version!r} "
                f"(expected {SCHEMA_VERSION})")
        if not isinstance(self.semantics, WorkloadSemantics):
            raise InvalidInput("semantics must be a WorkloadSemantics")
        ops = tuple(self.operations)
        if not ops:
            raise InvalidInput(
                "a workload with no operations is not a simulatable "
                "workload")
        object.__setattr__(self, "operations", ops)
        ids = [op.operation_id for op in ops]
        dupes = sorted({i for i in ids if ids.count(i) > 1})
        if dupes:
            raise InvalidInput(f"duplicate operation id(s): {dupes}")
        known = set(ids)
        for op in ops:
            missing = sorted(set(op.deps) - known)
            if missing:
                raise InvalidInput(
                    f"operation {op.operation_id!r} depends on unknown "
                    f"operation(s) {missing}")
        try:
            object.__setattr__(self, "provenance", freeze(self.provenance))
        except ImmutableError as exc:
            raise InvalidInput(f"provenance is not canonical: {exc}") \
                from None
        self._validate_acyclic()
        self.validate_structure()

    # ── structural laws ────────────────────────────────────────────────
    def _validate_acyclic(self) -> None:
        by_id = {op.operation_id: op for op in self.operations}
        state: dict[str, int] = {}

        def visit(node_id: str) -> None:
            colour = state.get(node_id, 0)
            if colour == 1:
                raise InvalidInput(
                    f"dependency cycle through operation {node_id!r}")
            if colour == 2:
                return
            state[node_id] = 1
            for dep in by_id[node_id].deps:
                visit(dep)
            state[node_id] = 2

        for op in self.operations:
            visit(op.operation_id)

    def validate_structure(self) -> None:
        """Region balance for EXPERT and PIM markers.

        A stray END or an unclosed BEGIN refuses HERE — a malformed source
        structure must never reach a backend to crash there.
        """
        for begin_kind, end_kind, what in (
                (KIND_EXPERT_BEGIN, KIND_EXPERT_END, "EXPERT"),
                (KIND_PIM_BEGIN, KIND_PIM_END, "PIM")):
            open_regions = 0
            for op in self.operations:
                if op.kind == begin_kind:
                    open_regions += 1
                elif op.kind == end_kind:
                    open_regions -= 1
                    if open_regions < 0:
                        raise InvalidInput(
                            f"stray {what}_END at operation "
                            f"{op.operation_id!r}: no open {what}_BEGIN "
                            "region (refusing malformed source structure)")
            if open_regions:
                raise InvalidInput(
                    f"{open_regions} unclosed {what}_BEGIN region(s): the "
                    f"source grammar requires a matching {what}_END")
        for op in self.operations:
            if op.kind in (KIND_PIM_BEGIN, KIND_PIM_END) and \
                    op.detail is not None and \
                    op.kind == KIND_PIM_BEGIN and "channel" not in op.detail:
                raise InvalidInput(
                    f"PIM_BEGIN {op.operation_id!r} must declare a channel")

    # ── accessors ──────────────────────────────────────────────────────
    def by_id(self, operation_id: str) -> OperationNode:
        for op in self.operations:
            if op.operation_id == operation_id:
                return op
        raise InvalidInput(f"no operation {operation_id!r}")

    def of_kind(self, kind: str) -> tuple[OperationNode, ...]:
        return tuple(op for op in self.operations if op.kind == kind)

    @property
    def requires_pim(self) -> bool:
        return any(op.kind in (KIND_PIM_BEGIN, KIND_PIM_END)
                   for op in self.operations)

    # ── identity ───────────────────────────────────────────────────────
    def identity_dict(self) -> dict[str, Any]:
        """Semantic identity: schema, geometry, PARTICIPANT namespace,
        semantics, and the DAG in canonical (topological) order."""
        return {
            "type": _HASH_TYPE_TAG,
            "schema_version": self.schema_version,
            "parallelism": self.parallelism.identity_dict(),
            "participant_count": self.participant_count,
            "semantics": self.semantics.identity_dict(),
            "operations": [self.by_id(i).identity_dict()
                           for i in self._topological_ids()],
        }

    def _topological_ids(self) -> tuple[str, ...]:
        """Deterministic order: dependencies first, ties by operation id.

        Dependency edges are the semantic scheduling relation; the order
        is canonicalised so two graphs with the same DAG and the same
        operation ids hash identically regardless of construction order.
        """
        import heapq
        by_id = {op.operation_id: op for op in self.operations}
        pending = {i: set(op.deps) for i, op in by_id.items()}
        ready = [i for i, deps in pending.items() if not deps]
        heapq.heapify(ready)
        out: list[str] = []
        while ready:
            node_id = heapq.heappop(ready)
            out.append(node_id)
            for other, deps in pending.items():
                if node_id in deps:
                    deps.discard(node_id)
                    if not deps and other not in out and other not in ready:
                        heapq.heappush(ready, other)
        return tuple(out)

    def workload_id(self) -> str:
        return content_hash(_HASH_TYPE_TAG, self.schema_version,
                            self.identity_dict())

    def to_dict(self) -> dict[str, Any]:
        """Persisted form: identity fields PLUS the full parallelism
        document (derived world_size and embedded parallelism_id) so a
        strict reader can validate it, and the operations in construction
        order. ``identity_dict`` stays order-canonical and derived-free.
        """
        return {
            **self.identity_dict(),
            "parallelism": self.parallelism.to_dict(),
            "workload_id": self.workload_id(),
            "operations": [op.to_dict() for op in self.operations],
            "provenance": thaw(self.provenance),
        }

    @classmethod
    def from_dict(cls, d: Any, *, strict: bool = False
                  ) -> "WorkloadGraph":
        if not isinstance(d, dict):
            raise InvalidInput("workload graph must be an object")
        require_fields(d, _GRAPH_KEYS, "workload graph")
        require_type_tag(d, _HASH_TYPE_TAG, "workload graph")
        require_schema_version(d, SCHEMA_VERSION, "workload graph")
        graph = cls(
            parallelism=ParallelismArtifact.from_dict(
                d.get("parallelism"), strict=strict),
            participant_count=d.get("participant_count"),
            operations=tuple(OperationNode.from_dict(op, strict=strict)
                             for op in (d.get("operations") or ())),
            semantics=WorkloadSemantics.from_dict(d.get("semantics")),
            provenance=d.get("provenance"),
        )
        if strict:
            require_embedded_id(d, "workload_id", graph.workload_id(),
                                "workload graph")
        elif d.get("workload_id") and \
                d["workload_id"] != graph.workload_id():
            raise EvidenceInvalid(
                "workload_id does not match the canonical content")
        return graph


__all__ = [
    "ALL_KINDS", "COLLECTIVE_KINDS", "DEFAULT_BATCH_TAG", "DEFAULT_LOC",
    "DETAIL_KEYS", "KIND_COLLECTIVE", "KIND_COMPUTE", "KIND_EXPERT_BEGIN",
    "KIND_EXPERT_END", "KIND_MULTICAST", "KIND_P2P", "KIND_PIM_BEGIN",
    "KIND_PIM_END", "OperationNode", "P2P_ROLES", "REPLICATION_KINDS",
    "SCHEMA_VERSION", "SCOPE_ALL", "WorkloadGraph", "WorkloadSemantics",
    "collective_detail", "compute_detail", "expert_detail",
    "multicast_detail", "p2p_detail", "pim_detail", "pim_end_detail",
]
