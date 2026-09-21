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
from collections.abc import Mapping
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
_NODE_KEYS_PERSISTED = _NODE_KEYS
_GRAPH_KEYS = frozenset({"type", "schema_version", "parallelism",
                         "participant_count", "semantics", "operations",
                         "provenance", "workload_id"})
_SEMANTICS_KEYS = frozenset({"phase", "routing_policy", "shape",
                             "model_descriptor_hash",
                             "model_descriptor_name"})
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


_LOC_BASES = ("LOCAL", "REMOTE", "CXL", "STORAGE")


def _norm_mem_loc(value: Any, what: str) -> str:
    """Memory-location grammar, ported from the sealed Phase-9 authority.

    LOCAL | REMOTE:<dev>[.<chan>] | CXL... | STORAGE, with a digit-only
    suffix. Unknown tokens refuse HERE: the converter silently maps an
    unknown word to INVALID_MEMORY, and a silently invalid location would
    fabricate memory-side timing.
    """
    if not isinstance(value, str) or not value:
        raise InvalidInput(
            f"{what} must be a non-empty location string, got {value!r}")
    base = value.split(":", 1)[0]
    if base not in _LOC_BASES:
        raise InvalidInput(
            f"{what} {value!r} — unknown memory location; supported: "
            "LOCAL, REMOTE:<dev>[.<chan>], CXL..., STORAGE")
    if ":" in value:
        tail = value.split(":", 1)[1]
        parts = tail.split(".")
        if not parts or any(part == "" for part in parts) or \
                not all(part.isdigit() for part in parts):
            raise InvalidInput(
                f"{what} {value!r} — malformed <dev>[.<chan>] suffix")
    return value


# EXPERT source grammar carries no broadcast root, so an EXPERT payload
# must not claim BROADCAST: that would fabricate incomplete semantics.
EXPERT_COLLECTIVE_KINDS = ("ALLREDUCE", "REDUCESCATTER", "ALLGATHER",
                           "ALLTOALL")

_SHAPE_KEYS = ("num_layers", "hidden_size", "bytes_per_elem", "decode_steps",
               "num_experts", "top_k")


def _norm_shape(shape: Any) -> None | FrozenMap:
    """Deep-frozen shape metadata with the Wave-D field rules."""
    if shape is None:
        return None
    if not isinstance(shape, Mapping):
        raise InvalidInput("semantics shape must be an object or None")
    unknown = sorted(set(shape) - set(_SHAPE_KEYS))
    if unknown:
        raise InvalidInput(
            f"semantics shape has unsupported fields {unknown}; "
            f"supported: {sorted(_SHAPE_KEYS)}")
    for key, value in shape.items():
        _int(value, f"semantics shape {key!r}")
    frozen = freeze(dict(shape))          # deep copy: never alias caller
    assert isinstance(frozen, FrozenMap)
    return frozen


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


def _ranks(value: Any, what: str, count: int | None,
           *, minimum: int = 1) -> tuple[int, ...]:
    if not isinstance(value, (list, tuple)) or not value:
        raise InvalidInput(f"{what} must be a non-empty sequence of ranks")
    out: list[int] = []
    for p in value:
        if type(p) is not int or isinstance(p, bool) or p < 0:
            raise InvalidInput(
                f"{what}: rank {p!r} must be a non-negative int")
        if count is not None and p >= count:
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


def _canonical_detail(kind: str, raw: Any,
                      participant_count: int | None) -> FrozenMap:
    """THE detail validator: exact key set + full semantic revalidation.

    Every canonical detail must have EXACTLY its canonical field set —
    optional semantic values are represented explicitly as ``None``, never
    by dropping canonical keys. This is the single implementation used by
    the builders AND by every reader (a strict reader is an adversarial
    boundary, so it may not trust that a builder validated the value).
    """
    if kind not in DETAIL_KEYS:
        raise InvalidInput(f"unknown operation kind {kind!r}")
    if not isinstance(raw, Mapping):
        raise InvalidInput(
            f"{kind} detail must be an object, got {type(raw).__name__}")
    allowed = DETAIL_KEYS[kind]
    unknown = sorted(set(raw) - allowed)
    if unknown:
        raise InvalidInput(f"{kind} detail has unknown fields {unknown}")
    missing = sorted(allowed - set(raw))
    if missing:
        raise InvalidInput(
            f"{kind} detail is missing canonical field(s) {missing} — "
            "optional values are explicit nulls, not absent keys")
    d = dict(raw)
    if kind == KIND_COMPUTE:
        _int(d["duration_ns"], "COMPUTE duration_ns")
        for name in ("input_bytes", "weight_bytes", "output_bytes"):
            if d[name] is not None:
                _int(d[name], f"COMPUTE {name}")
        for name in ("input_loc", "weight_loc", "output_loc"):
            _norm_mem_loc(d[name], f"COMPUTE {name}")
        _str(d["batch_tag"], "COMPUTE batch_tag")
    elif kind == KIND_COLLECTIVE:
        if d["collective_kind"] not in COLLECTIVE_KINDS:
            raise UnsupportedSemantics(
                f"COLLECTIVE kind {d['collective_kind']!r} is outside "
                f"{COLLECTIVE_KINDS}")
        _int(d["payload_bytes"], "COLLECTIVE payload_bytes", minimum=1)
        ranks = _ranks(d["participants"], "COLLECTIVE participants",
                       participant_count, minimum=2)
        _norm_scope(d["scope"], "COLLECTIVE scope")
        if d["collective_kind"] == "BROADCAST":
            source = d["source"]
            if source is None:
                raise InvalidInput(
                    "BROADCAST requires an explicit source rank — "
                    "participants[0] is a legacy convenience, not a law")
            _int(source, "BROADCAST source")
            if isinstance(source, bool) or source not in ranks:
                raise InvalidInput(
                    f"BROADCAST source {source!r} is not a participating "
                    "rank")
        elif d["source"] is not None:
            raise InvalidInput(
                f"{d['collective_kind']} must not declare a source "
                f"(got {d['source']!r})")
    elif kind == KIND_P2P:
        if d["role"] not in P2P_ROLES:
            raise InvalidInput(f"P2P role must be one of {P2P_ROLES}, "
                               f"got {d['role']!r}")
        _int(d["payload_bytes"], "P2P payload_bytes", minimum=1)
        _ranks((d["src_rank"],), "P2P src_rank", participant_count)
        _ranks((d["dst_rank"],), "P2P dst_rank", participant_count)
        if d["src_rank"] == d["dst_rank"]:
            raise InvalidInput("P2P src_rank and dst_rank must differ")
    elif kind == KIND_MULTICAST:
        if d["replication"] not in REPLICATION_KINDS:
            raise UnsupportedSemantics(
                f"multicast replication {d['replication']!r} is outside "
                f"{REPLICATION_KINDS}")
        _int(d["payload_bytes"], "MULTICAST payload_bytes", minimum=1)
        _ranks((d["source_rank"],), "MULTICAST source_rank",
               participant_count)
        dests = _ranks(d["destinations"], "MULTICAST destinations",
                       participant_count)
        if d["source_rank"] in dests:
            raise InvalidInput(
                "multicast source must not appear among its destinations")
    elif kind in (KIND_EXPERT_BEGIN, KIND_EXPERT_END):
        if d["expert_num"] is not None:
            _int(d["expert_num"], "EXPERT expert_num")
        ck = d["collective_kind"]
        if ck is None:
            for name in ("participants", "payload_bytes", "scope"):
                if d[name] is not None:
                    raise InvalidInput(
                        f"EXPERT {name} requires a collective_kind")
            return freeze(d)
        if ck not in EXPERT_COLLECTIVE_KINDS:
            raise UnsupportedSemantics(
                f"EXPERT collective {ck!r} is outside the expert source "
                f"grammar {EXPERT_COLLECTIVE_KINDS} (no broadcast root is "
                "carried, so BROADCAST would fabricate incomplete "
                "semantics)")
        if d["participants"] is None or d["payload_bytes"] is None:
            raise InvalidInput(
                "EXPERT collective requires participants and payload_bytes")
        _int(d["payload_bytes"], "EXPERT payload_bytes", minimum=1)
        _ranks(d["participants"], "EXPERT participants", participant_count,
               minimum=2)
        _norm_scope(d["scope"], "EXPERT scope")
    elif kind == KIND_PIM_BEGIN:
        _int(d["channel"], "PIM channel")
    return freeze(d)


# ── per-kind detail builders (validated, closed) ────────────────────────
def compute_detail(*, duration_ns: int, input_bytes: int | None = None,
                   weight_bytes: int | None = None,
                   output_bytes: int | None = None,
                   input_loc: str = DEFAULT_LOC,
                   weight_loc: str = DEFAULT_LOC,
                   output_loc: str = DEFAULT_LOC,
                   batch_tag: str = DEFAULT_BATCH_TAG,
                   participant_count: int = 1) -> FrozenMap:
    """COMPUTE payload. v2 states the defaults EXPLICITLY (they are values,
    not absences) so the canonical form is readable without knowing the
    legacy compressor."""
    return _canonical_detail(KIND_COMPUTE, {
        "duration_ns": duration_ns,
        "input_bytes": input_bytes, "weight_bytes": weight_bytes,
        "output_bytes": output_bytes,
        "input_loc": input_loc, "weight_loc": weight_loc,
        "output_loc": output_loc, "batch_tag": batch_tag,
    }, participant_count)


def collective_detail(*, collective_kind: str, participants: Iterable[int],
                      payload_bytes: int, participant_count: int,
                      scope: Any = None, source: int | None = None
                      ) -> FrozenMap:
    """COLLECTIVE payload. BROADCAST requires an explicit ``source``; every
    other kind refuses one (a declared source on ALLREDUCE would be a
    fabricated field)."""
    # NO semantic restatement here: _canonical_detail is the one
    # implementation (2.5.1). Duplicated laws drift.
    return _canonical_detail(KIND_COLLECTIVE, {
        "collective_kind": collective_kind,
        "participants": tuple(participants),
        "payload_bytes": payload_bytes, "scope": scope, "source": source,
    }, participant_count)


def p2p_detail(*, role: str, src_rank: int, dst_rank: int,
               payload_bytes: int, participant_count: int) -> FrozenMap:
    """P2P payload. ``TRANSFER`` is a complete Wave-D transfer; ``SEND`` /
    ``RECV`` are legacy identity-bearing roles and are NOT paired here."""
    return _canonical_detail(KIND_P2P, {
        "role": role, "src_rank": src_rank, "dst_rank": dst_rank,
        "payload_bytes": payload_bytes}, participant_count)


def multicast_detail(*, source_rank: int, destinations: Iterable[int],
                     payload_bytes: int, replication: str,
                     participant_count: int) -> FrozenMap:
    return _canonical_detail(KIND_MULTICAST, {
        "source_rank": source_rank, "destinations": tuple(destinations),
        "payload_bytes": payload_bytes, "replication": replication},
        participant_count)


def expert_detail(*, end: bool = False, expert_num: int | None = None,
                  collective_kind: str | None = None,
                  participants: Iterable[int] | None = None,
                  payload_bytes: int | None = None,
                  scope: Any = None, participant_count: int) -> FrozenMap:
    """EXPERT_BEGIN / EXPERT_END payload.

    Both markers may carry a collective: LLMServingSim emits a dispatch
    collective at BEGIN and a combine collective (e.g. REDUCESCATTER) at
    END. ``EXPERT_END`` is therefore NOT payload-free.
    """
    if collective_kind is None:
        # pass the caller's values THROUGH: hard-coding None here would
        # silently drop a declared payload instead of refusing it
        return _canonical_detail(
            KIND_EXPERT_END if end else KIND_EXPERT_BEGIN, {
                "expert_num": expert_num, "collective_kind": None,
                "participants": participants, "payload_bytes": payload_bytes,
                "scope": scope}, participant_count)
    return _canonical_detail(
        KIND_EXPERT_END if end else KIND_EXPERT_BEGIN, {
            "expert_num": expert_num, "collective_kind": collective_kind,
            "participants": participants, "payload_bytes": payload_bytes,
            "scope": scope}, participant_count)


def pim_detail(*, channel: int, participant_count: int = 1) -> FrozenMap:
    """PIM_BEGIN payload: the channel identifier the region executes on."""
    return _canonical_detail(KIND_PIM_BEGIN, {"channel": channel},
                             participant_count)


def pim_end_detail(*, participant_count: int = 1) -> FrozenMap:
    return _canonical_detail(KIND_PIM_END, {}, participant_count)


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
        # ONE validator for builders and readers alike: exact key set plus
        # full semantic revalidation. A strict reader is adversarial and
        # may not trust that a builder produced this value.
        try:
            # STRUCTURE ONLY: a bare node does not know the participant
            # namespace, and it must not cache one (a frozen object that
            # changes depending on which graph touched it last is an
            # aliasing bug). The GRAPH validates bounds against its own
            # namespace, without writing anything back into the node.
            object.__setattr__(self, "detail", _canonical_detail(
                self.kind, thaw(frozen), None))
        except (InvalidInput, UnsupportedSemantics) as exc:  # context
            raise type(exc)(
                f"operation {self.operation_id!r} ({self.kind}): "
                f"{exc}") from None

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
    def from_dict(cls, d: Any, *, strict: bool = False,
                  participant_count: int | None = None) -> "OperationNode":
        if not isinstance(d, dict):
            raise InvalidInput("operation node must be an object")
        require_fields(d, _NODE_KEYS, "operation node")
        if strict:
            missing = sorted(_NODE_KEYS_PERSISTED - set(d))
            if missing:
                raise InvalidInput(
                    f"persisted operation is missing canonical field(s) "
                    f"{missing}")
        node = cls(
            operation_id=d.get("operation_id"), kind=d.get("kind"),
            deps=tuple(d.get("deps") or ()), detail=d.get("detail"),
            owner=d.get("owner"), phase=d.get("phase"),
            step=d.get("step"), label=d.get("label", ""))
        if participant_count is not None:
            # validate against the reader's namespace, store NOTHING
            _canonical_detail(node.kind, thaw(node.detail),
                              participant_count)
        return node


# ── the workload semantics envelope ─────────────────────────────────────
@dataclass(frozen=True)
class WorkloadSemantics:
    """Semantic envelope. Every field is OPTIONAL because a legitimate
    source may not declare it (Phase-9 declared neither a global phase nor
    a routing policy). Absent is not ``PREFILL``."""

    phase: str | None = None
    routing_policy: str | None = None
    shape: Any = None
    #: SEMANTIC: the descriptor hash is identity-bearing.
    model_descriptor_hash: str | None = None
    #: PROVENANCE: a descriptor NAME is human/source metadata. It is kept
    #: for reconstruction and must NOT move scientific identity.
    model_descriptor_name: str | None = None

    def __post_init__(self) -> None:
        if self.phase is not None and self.phase not in _PHASES:
            raise UnsupportedSemantics(
                f"semantics phase {self.phase!r} is outside {_PHASES}")
        if self.routing_policy is not None:
            _str(self.routing_policy, "routing_policy")
        _str(self.model_descriptor_name, "model_descriptor_name",
             optional=True)
        _str(self.model_descriptor_hash, "model_descriptor_hash",
             optional=True)
        object.__setattr__(self, "shape", _norm_shape(self.shape))

    #: semantic (identity-bearing) content only
    def identity_dict(self) -> dict[str, Any]:
        return {"phase": self.phase, "routing_policy": self.routing_policy,
                "shape": thaw(self.shape),
                "model_descriptor_hash": self.model_descriptor_hash}

    def to_dict(self) -> dict[str, Any]:
        #: the name rides in the persisted document (reconstruction needs
        #: it) but not in identity_dict.
        return {**self.identity_dict(),
                "model_descriptor_name": self.model_descriptor_name}

    @classmethod
    def from_dict(cls, d: Any, *, strict: bool = False
                  ) -> "WorkloadSemantics":
        if d is None:
            return cls()
        if not isinstance(d, dict):
            raise InvalidInput("semantics must be an object")
        require_fields(d, _SEMANTICS_KEYS, "semantics")
        if strict:
            missing = sorted(_SEMANTICS_KEYS - set(d))
            if missing:
                raise InvalidInput(
                    f"persisted semantics is missing canonical field(s) "
                    f"{missing}")
        return cls(phase=d.get("phase"),
                    routing_policy=d.get("routing_policy"),
                    shape=d.get("shape"),
                    model_descriptor_hash=d.get("model_descriptor_hash"),
                    model_descriptor_name=d.get("model_descriptor_name"))


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
        # Namespace law enforced HERE, read-only: the node is frozen and
        # stays byte-identical no matter which graphs reference it. The
        # same node may legally live in graphs with different participant
        # counts; passing validation is what makes that legal.
        for op in ops:
            _canonical_detail(op.kind, thaw(op.detail),
                              self.participant_count)
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
        self._validate_owner_namespace()
        self._validate_phase_consistency()
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

    def _validate_owner_namespace(self) -> None:
        """The participant namespace law applies to ``owner`` too.

        Rank 4 is a legal WORLD rank when world_size is 8, but it is
        outside a 4-rank participant namespace: owning work there would
        address a rank the trace never declared.
        """
        for op in self.operations:
            if op.owner is None:
                continue
            if not 0 <= op.owner < self.participant_count:
                raise InvalidInput(
                    f"operation {op.operation_id!r}: owner {op.owner} is "
                    f"outside the participant namespace "
                    f"[0, {self.participant_count})")

    def _validate_phase_consistency(self) -> None:
        """A declared global phase and a declared per-op phase must agree."""
        global_phase = self.semantics.phase
        if global_phase is None:
            return
        for op in self.operations:
            if op.phase is not None and op.phase != global_phase:
                raise InvalidInput(
                    f"operation {op.operation_id!r} declares phase "
                    f"{op.phase!r} but the graph declares "
                    f"{global_phase!r}: one graph, one phase meaning")

    # ── canonical ordering (one helper, no per-lowerer orders) ─────────
    def _unique_topological_order(self) -> tuple[str, ...]:
        """The dependency-derived order, refusing ambiguity.

        Raises when more than one operation is simultaneously ready: such
        a graph has no unique dependency order, so region membership
        (EXPERT/PIM) would have to come from construction order, which
        identity deliberately ignores. Refusing is the only honest answer;
        a legitimate positional source (LLMServingSim/ET rows, Phase-9
        ops) migrates to an explicit chain and satisfies this naturally.
        """
        import heapq
        by_id = {op.operation_id: op for op in self.operations}
        pending = {i: set(op.deps) for i, op in by_id.items()}
        ready = [i for i, deps in pending.items() if not deps]
        heapq.heapify(ready)
        out: list[str] = []
        while ready:
            if len(ready) > 1:
                raise InvalidInput(
                    "workload has no unique dependency-derived operation "
                    "order (independent operations are simultaneously "
                    "ready): construction order cannot carry semantics, so "
                    "region membership would be ambiguous. Chain the "
                    "source operations explicitly (source grammars are "
                    "positional).")
            node_id = heapq.heappop(ready)
            out.append(node_id)
            for other, deps in pending.items():
                if node_id in deps:
                    deps.discard(node_id)
                    if not deps and other not in out:
                        heapq.heappush(ready, other)
        return tuple(out)

    def ordered_operations(self) -> tuple[OperationNode, ...]:
        """The canonical consumer order (dependency-derived).

        Lowerers that need a TOTAL order (legacy ET row reconstruction,
        the positional memory stream, timeline v1) must prove it with
        ``require_total_order()`` first; logical-message lowering may use
        canonical topological order where a partial DAG is valid.
        """
        return tuple(self.by_id(i) for i in self._topological_ids())

    def require_total_order(self) -> tuple[OperationNode, ...]:
        """A total order, or a refusal — never an invented ordering."""
        return tuple(self.by_id(i) for i in self._unique_topological_order())

    def validate_structure(self) -> None:
        """Region balance for EXPERT and PIM markers.

        A stray END or an unclosed BEGIN refuses HERE — a malformed source
        structure must never reach a backend to crash there.
        """
        markers = any(op.kind in (KIND_EXPERT_BEGIN, KIND_EXPERT_END,
                                  KIND_PIM_BEGIN, KIND_PIM_END)
                      for op in self.operations)
        if markers:
            # region membership comes from the DEPENDENCY order, never
            # from construction order (which identity ignores)
            order = [self.by_id(i) for i in self._unique_topological_order()]
        else:
            order = list(self.operations)
        for begin_kind, end_kind, what in (
                (KIND_EXPERT_BEGIN, KIND_EXPERT_END, "EXPERT"),
                (KIND_PIM_BEGIN, KIND_PIM_END, "PIM")):
            open_regions = 0
            for op in order:
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
            if op.kind == KIND_PIM_BEGIN and "channel" not in op.detail:
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
            "semantics": self.semantics.to_dict(),
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
        if strict:
            missing = sorted(_GRAPH_KEYS - set(d))
            if missing:
                raise InvalidInput(
                    f"persisted workload graph is missing canonical "
                    f"field(s) {missing}")
        count = d.get("participant_count")
        graph = cls(
            parallelism=ParallelismArtifact.from_dict(
                d.get("parallelism"), strict=strict),
            participant_count=count,
            operations=tuple(
                OperationNode.from_dict(op, strict=strict,
                                        participant_count=count)
                for op in (d.get("operations") or ())),
            semantics=WorkloadSemantics.from_dict(d.get("semantics"),
                                                  strict=strict),
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
