"""canonical.py — the canonical workload semantic artifact (Phase 9).

Rationale: docs/decisions/modules/workload.md
"""
from __future__ import annotations

from veritx_dse.core.errors import SemanticError

import hashlib
import json
from dataclasses import dataclass, field, replace
from typing import Any

SCHEMA_VERSION = 1

ALL_DIMENSIONS = "ALL"

class WorkloadError(ValueError, SemanticError):
    """The workload cannot be represented without scientific loss.

Rationale: docs/decisions/modules/workload.md
    """

_COMM_KINDS = frozenset({
    "SEND", "RECV", "ALLREDUCE", "ALLGATHER", "REDUCESCATTER",
    "ALLTOALL", "BROADCAST",
})
_EXPERT_KINDS = frozenset({"EXPERT_BEGIN", "EXPERT_END"})
_KNOWN_KINDS = _COMM_KINDS | {"COMPUTE"} | _EXPERT_KINDS

@dataclass(frozen=True)
class Parallelism:
    """Logical parallelism structure (TP/DP/EP/PP) of the workload."""
    tp: int = 1
    dp: int = 1
    ep: int = 1
    pp: int = 1

    def __post_init__(self) -> None:
        for name in ("tp", "dp", "ep", "pp"):
            v = getattr(self, name)
            if not isinstance(v, int) or isinstance(v, bool) or v < 1:
                raise WorkloadError(
                    f"parallelism {name} must be a positive int, got {v!r}")

    def to_dict(self) -> dict[str, int]:
        return {"tp": self.tp, "dp": self.dp, "ep": self.ep, "pp": self.pp}

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "Parallelism":
        return cls(tp=d.get("tp", 1), dp=d.get("dp", 1),
                   ep=d.get("ep", 1), pp=d.get("pp", 1))

@dataclass(frozen=True)
class WorkloadOp:
    """One semantic workload operation.

Rationale: docs/decisions/modules/workload.md
    """
    kind: str
    op_id: str
    bytes: int | None = None
    participants: tuple[int, ...] = ()
    scope: Any = None
    src: int | None = None
    dst: int | None = None
    duration_ns: int | None = None
    input_bytes: int | None = None
    weight_bytes: int | None = None
    output_bytes: int | None = None
    input_loc: str = "LOCAL"
    weight_loc: str = "LOCAL"
    output_loc: str = "LOCAL"
    batch_tag: str = "NONE"
    comm_kind: str | None = None
    expert_num: int | None = None
    label: str = ""

    @property
    def is_comm(self) -> bool:
        if self.kind in _COMM_KINDS:
            return True
        return self.kind in _EXPERT_KINDS and self.bytes is not None

    def to_dict(self) -> dict[str, Any]:
        d: dict[str, Any] = {"kind": self.kind, "op_id": self.op_id}
        if self.kind in _EXPERT_KINDS:
            d["expert_num"] = self.expert_num
            d["comm_kind"] = self.comm_kind
        if self.is_comm:
            d["bytes"] = self.bytes
            d["participants"] = list(self.participants)
            d["scope"] = self.scope
        if self.kind in ("SEND", "RECV", "BROADCAST"):
            d["src"] = self.src
            if self.kind in ("SEND", "RECV"):
                d["dst"] = self.dst
        if self.kind == "COMPUTE":
            d["duration_ns"] = self.duration_ns
            if self.batch_tag != "NONE":
                d["batch_tag"] = self.batch_tag
            for f in ("input_bytes", "weight_bytes", "output_bytes"):
                if getattr(self, f) is not None:
                    d[f] = getattr(self, f)
            for f in ("input_loc", "weight_loc", "output_loc"):
                if getattr(self, f) != "LOCAL":
                    d[f] = getattr(self, f)
        if self.label:
            d["label"] = self.label
        return d

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "WorkloadOp":
        kind = d.get("kind")
        if kind not in _KNOWN_KINDS:
            raise WorkloadError(
                f"unknown operation kind {kind!r} — supported: "
                f"{sorted(_KNOWN_KINDS)}. Unsupported workload semantics "
                "must be implemented or removed, never skipped (fail-closed).")
        participants = tuple(d.get("participants", ()))
        scope = d.get("scope")
        if kind == "COMPUTE":
            return cls(kind=kind, op_id=d["op_id"],
                       duration_ns=d.get("duration_ns"),
                       input_bytes=d.get("input_bytes"),
                       weight_bytes=d.get("weight_bytes"),
                       output_bytes=d.get("output_bytes"),
                       input_loc=d.get("input_loc", "LOCAL"),
                       weight_loc=d.get("weight_loc", "LOCAL"),
                       output_loc=d.get("output_loc", "LOCAL"),
                       batch_tag=d.get("batch_tag", "NONE"),
                       label=d.get("label", ""))
        return cls(
            kind=kind, op_id=d["op_id"], bytes=d.get("bytes"),
            participants=participants, scope=scope,
            src=d.get("src"), dst=d.get("dst"),
            comm_kind=d.get("comm_kind"),
            expert_num=d.get("expert_num"),
            label=d.get("label", ""))

def _check_ranks(participants: tuple[int, ...], num_participants: int,
                 where: str) -> None:
    for p in participants:
        if not isinstance(p, int) or isinstance(p, bool):
            raise WorkloadError(f"{where}: non-integer rank {p!r}")
        if not (0 <= p < num_participants):
            raise WorkloadError(
                f"{where}: rank {p} out of range [0, {num_participants})")

def _check_bytes(op_id: str, nbytes: Any) -> int:
    if not isinstance(nbytes, int) or isinstance(nbytes, bool) or nbytes <= 0:
        raise WorkloadError(
            f"op {op_id!r}: communication size must be a positive integer "
            f"of logical BYTES, got {nbytes!r} — ambiguous/missing units "
            "refuse rather than default (§10)")
    return nbytes

def _norm_scope(op_id: str, scope: Any) -> Any:
    if scope is None:
        raise WorkloadError(
            f"op {op_id!r}: missing dimensional scope — scope absence is "
            "not 'all dimensions' (the ASTRA fallback fabricates "
            "participation); pass an explicit vector or ALL_DIMENSIONS")
    if scope == ALL_DIMENSIONS:
        return ALL_DIMENSIONS
    if not isinstance(scope, (list, tuple)) or not scope or \
            not all(isinstance(v, bool) for v in scope):
        raise WorkloadError(
            f"op {op_id!r}: scope must be a non-empty boolean dim vector "
            f"or ALL_DIMENSIONS, got {scope!r}")
    return list(scope)

def _check_mem_bytes(op_id: str, name: str, v: int | None) -> int | None:
    if v is None:
        return None
    if not isinstance(v, int) or isinstance(v, bool) or v < 0:
        raise WorkloadError(
            f"op {op_id!r}: {name} must be a non-negative int of BYTES, "
            f"got {v!r}")
    return v

def _norm_mem_loc(op_id: str, name: str, v: str) -> str:
    """Validate one memory-location token against the trace grammar.

    The converter accepts LOCAL/REMOTE/CXL/STORAGE with an optional
    :<device>[.<channel>] suffix. Unknown or malformed tokens refuse —
    the converter maps unknown words to INVALID_MEMORY silently, and a
    silent invalid location would fabricate memory-side timing (§10)."""
    if not isinstance(v, str) or not v:
        raise WorkloadError(
            f"op {op_id!r}: {name} must be a non-empty location string, "
            f"got {v!r}")
    base = v.split(":", 1)[0]
    if base not in ("LOCAL", "REMOTE", "CXL", "STORAGE"):
        raise WorkloadError(
            f"op {op_id!r}: {name} {v!r} — unknown memory location; "
            "supported: LOCAL, REMOTE:<dev>[.<chan>], CXL..., STORAGE")
    if ":" in v:
        tail = v.split(":", 1)[1]
        parts = tail.split(".")
        if not parts or not all(p.isdigit() for p in parts if p != "") \
                or any(p == "" for p in parts):
            raise WorkloadError(
                f"op {op_id!r}: {name} {v!r} — malformed "
                "<dev>[.<chan>] suffix")
    return v

def build_compute_op(op_id: str, duration_ns: int, label: str = "", *,
                     bytes: int | None = None,
                     input_bytes: int | None = None,
                     weight_bytes: int | None = None,
                     output_bytes: int | None = None,
                     input_loc: str = "LOCAL",
                     weight_loc: str = "LOCAL",
                     output_loc: str = "LOCAL",
                     batch_tag: str = "NONE") -> WorkloadOp:
    if duration_ns is None or duration_ns < 0:
        raise WorkloadError(
            f"op {op_id!r}: compute duration_ns must be >= 0, "
            f"got {duration_ns!r}")
    if not isinstance(batch_tag, str) or not batch_tag:
        raise WorkloadError(
            f"op {op_id!r}: batch_tag must be a non-empty string "
            f"(the trace's batch tag column is converter-consumed "
            f"semantics), got {batch_tag!r}")
    if bytes is not None:
        raise WorkloadError(
            f"op {op_id!r}: a COMPUTE op cannot carry communication bytes "
            f"(got {bytes!r}) — one op, one semantic class")
    return WorkloadOp(
        kind="COMPUTE", op_id=op_id, duration_ns=duration_ns,
        input_bytes=_check_mem_bytes(op_id, "input_bytes", input_bytes),
        weight_bytes=_check_mem_bytes(op_id, "weight_bytes", weight_bytes),
        output_bytes=_check_mem_bytes(op_id, "output_bytes", output_bytes),
        input_loc=_norm_mem_loc(op_id, "input_loc", input_loc),
        weight_loc=_norm_mem_loc(op_id, "weight_loc", weight_loc),
        output_loc=_norm_mem_loc(op_id, "output_loc", output_loc),
        batch_tag=batch_tag, label=label)

def build_expert_begin_op(expert_num: int | None, *,
                          comm_kind: str | None = None,
                          bytes: int | None = None,
                          participants: tuple[int, ...] = (),
                          scope: Any = None,
                          end: bool = False,
                          label: str = "") -> WorkloadOp:
    """MoE structural marker (audit-backed: the converter branches on
    EXPERT rows). Optionally carries the dispatch (BEGIN) / combine (END)
    collective with full collective validation."""
    kind = "EXPERT_END" if end else "EXPERT_BEGIN"
    op_id_stub = f"expert{expert_num}"
    if expert_num is not None and (
            not isinstance(expert_num, int) or isinstance(expert_num, bool)
            or expert_num < 0):
        raise WorkloadError(
            f"{kind}: expert_num must be a non-negative int (or None for "
            f"END markers), got {expert_num!r}")
    if comm_kind is None:
        if bytes is not None or scope is not None:
            raise WorkloadError(
                f"{kind} {op_id_stub}: bare marker cannot carry comm "
                "bytes/scope without a comm_kind")
        return WorkloadOp(kind=kind, op_id=f"{kind.lower()}-{op_id_stub}",
                          expert_num=expert_num, label=label)
    if comm_kind not in ("ALLREDUCE", "ALLGATHER", "REDUCESCATTER",
                         "ALLTOALL"):
        raise WorkloadError(
            f"{kind} {op_id_stub}: marker collective {comm_kind!r} not "
            "supported (fail-closed)")
    if len(participants) < 2:
        raise WorkloadError(
            f"{kind} {op_id_stub}: collective needs >= 2 participants")
    _check_bytes(op_id_stub, bytes)
    return WorkloadOp(
        kind=kind, op_id=f"{kind.lower()}-{op_id_stub}", bytes=bytes,
        participants=tuple(participants), scope=_norm_scope(op_id_stub, scope),
        comm_kind=comm_kind, expert_num=expert_num, label=label)

def build_collective_op(op_id: str, kind: str, *, bytes: int,
                        participants: tuple[int, ...], scope: Any,
                        label: str = "") -> WorkloadOp:
    if kind not in ("ALLREDUCE", "ALLGATHER", "REDUCESCATTER", "ALLTOALL"):
        raise WorkloadError(f"op {op_id!r}: {kind!r} is not a collective "
                            "kind; use the dedicated builder")
    if len(participants) < 2:
        raise WorkloadError(
            f"op {op_id!r}: {len(participants)} participant(s) — a "
            "collective needs >= 2 (degenerate collectives were "
            "previously silently dropped, making the workload lighter "
            "than declared)")
    _check_bytes(op_id, bytes)
    return WorkloadOp(kind=kind, op_id=op_id, bytes=bytes,
                      participants=tuple(participants),
                      scope=_norm_scope(op_id, scope), label=label)

def build_p2p_op(op_id: str, kind: str, *, bytes: int,
                 src: int | None = None, dst: int | None = None,
                 label: str = "") -> WorkloadOp:
    if kind not in ("SEND", "RECV"):
        raise WorkloadError(f"op {op_id!r}: {kind!r} is not a P2P kind")
    if src is None or dst is None or src == dst:
        raise WorkloadError(
            f"op {op_id!r}: P2P needs explicit distinct src/dst endpoints, "
            f"got src={src!r} dst={dst!r}")
    _check_bytes(op_id, bytes)
    return WorkloadOp(kind=kind, op_id=op_id, bytes=bytes, src=src, dst=dst,
                      participants=(src, dst), scope=ALL_DIMENSIONS,
                      label=label)

@dataclass(frozen=True)
class WorkloadArtifact:
    """Versioned, immutable, content-addressed workload semantics.

Rationale: docs/decisions/modules/workload.md
    """
    workload_id: str
    source_kind: str
    parallelism: Parallelism
    num_participants: int
    ops: tuple[WorkloadOp, ...]
    schema_version: int = SCHEMA_VERSION
    artifact_hash: str = field(default="", compare=True)

    def __post_init__(self) -> None:
        if not isinstance(self.ops, tuple):
            object.__setattr__(self, "ops", tuple(self.ops))
        if not self.ops:
            raise WorkloadError(
                "artifact has no operations — an empty workload is not a "
                "simulatable workload")
        ids = [op.op_id for op in self.ops]
        if len(ids) != len(set(ids)):
            dupes = sorted({i for i in ids if ids.count(i) > 1})
            raise WorkloadError(f"duplicate operation id(s): {dupes}")
        for op in self.ops:
            _check_ranks(op.participants, self.num_participants,
                         f"op {op.op_id!r}")
        if not self.artifact_hash:
            object.__setattr__(self, "artifact_hash",
                               _content_hash(self._identity_dict()))

    def _identity_dict(self) -> dict[str, Any]:
        """Semantic identity: everything that defines the workload.

Rationale: docs/decisions/modules/workload.md
        """
        return {
            "schema_version": self.schema_version,
            "num_participants": self.num_participants,
            "parallelism": self.parallelism.to_dict(),
            "ops": [{k: v for k, v in op.to_dict().items() if k != "label"}
                    for op in self.ops],
        }

    def _canonical_bytes(self) -> bytes:
        return json.dumps(self._identity_dict(),
                          sort_keys=True, separators=(",", ":")).encode()

    def serialize(self) -> dict[str, Any]:
        """Deterministic JSON-safe serialization (roundtrips exactly)."""
        d = self._identity_dict()
        d["ops"] = [op.to_dict() for op in self.ops]
        d["workload_id"] = self.workload_id
        d["source_kind"] = self.source_kind
        d["artifact_hash"] = self.artifact_hash
        return d

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "WorkloadArtifact":
        ops = tuple(WorkloadOp.from_dict(od) for od in d["ops"])
        art = cls(
            workload_id=d["workload_id"], source_kind=d["source_kind"],
            parallelism=Parallelism.from_dict(d["parallelism"]),
            num_participants=d["num_participants"], ops=ops,
            schema_version=d.get("schema_version", SCHEMA_VERSION))
        if d.get("artifact_hash") not in (None, "", art.artifact_hash):
            raise WorkloadError(
                "artifact_hash mismatch: serialized artifact was tampered "
                f"with or produced by a different schema (recorded "
                f"{d.get('artifact_hash')!r}, computed {art.artifact_hash!r})")
        return art

    def comm_bytes_total(self) -> int:
        return sum(op.bytes for op in self.ops if op.is_comm)

    def comm_ops(self) -> tuple[WorkloadOp, ...]:
        return tuple(op for op in self.ops if op.is_comm)

def _content_hash(identity: dict[str, Any]) -> str:
    payload = json.dumps(identity, sort_keys=True,
                         separators=(",", ":")).encode()
    return "sha256:" + hashlib.sha256(payload).hexdigest()

_LAYER_FIELDS = 11

def _parse_comm_field(comm_field: str) -> tuple[str, Any]:
    """'ALLREDUCE:1,0' → ('ALLREDUCE', [True, False]); 'NONE' → ('NONE', None)."""
    if ":" in comm_field:
        base, dim_str = comm_field.split(":", 1)
        return base, [v == "1" for v in dim_str.split(",")]
    return comm_field, None

def artifact_from_trace_rows(rows: list, *, workload_id: str,
                             parallelism: Parallelism,
                             num_participants: int,
                             source_kind: str = "llmservingsim",
                             has_pp_stage_boundaries: bool = False,
                             ) -> WorkloadArtifact:
    """Canonicalize LLMServingSim trace-generator rows (Path B).

Rationale: docs/decisions/modules/workload.md
    """
    if has_pp_stage_boundaries:
        raise WorkloadError(
            "pp_stage_boundaries present — pipeline-partitioned traces "
            "cannot be canonicalized without semantic loss: the converter "
            "has no PP semantics and would hand every rank the full "
            "unpartitioned graph (Phase 1 T2, fail-closed)")
    ops: list[WorkloadOp] = []
    seq = 0

    def _nid(prefix: str) -> str:
        nonlocal seq
        s = f"{prefix}-{seq}"
        seq += 1
        return s

    for row in rows:
        if len(row) == 1:
            tokens = row[0].split()
            marker = tokens[0]
            if marker not in ("EXPERT", "PIM"):
                raise WorkloadError(
                    f"unknown marker row {row[0]!r} — expected EXPERT/PIM")
            if marker == "PIM":
                continue
            end = len(tokens) >= 2 and tokens[1] == "END"
            enum = None if end else (
                int(tokens[1]) if len(tokens) >= 2 else None)
            if len(tokens) >= 4:
                base, scope = _parse_comm_field(tokens[2])
                size = int(tokens[3])
                if base != "NONE":
                    if base not in ("ALLREDUCE", "ALLGATHER",
                                    "REDUCESCATTER", "ALLTOALL"):
                        raise WorkloadError(
                            f"unknown comm_type {base!r} in marker row "
                            f"{row[0]!r} — supported: {sorted(_COMM_KINDS)} "
                            "(fail-closed)")
                    op = build_expert_begin_op(
                        enum, comm_kind=base, bytes=size,
                        participants=tuple(range(num_participants)),
                        scope=scope if scope is not None
                        else ALL_DIMENSIONS, end=end)
                    ops.append(replace(op, op_id=_nid("expert")))
                    continue
            op = build_expert_begin_op(enum, end=end)
            ops.append(replace(op, op_id=_nid("expert")))
            continue

        if len(row) != _LAYER_FIELDS:
            raise WorkloadError(
                f"trace row has {len(row)} fields; expected "
                f"{_LAYER_FIELDS} (layer) or 1 (marker): {row!r}")
        name, comp_ns, il, inp, wl, wt, ol, out, comm_field, \
            comm_size, tag = row
        mem = {}
        for fname, raw in (("input_bytes", inp), ("weight_bytes", wt),
                           ("output_bytes", out)):
            v = int(raw)
            if v > 0:
                mem[fname] = v
        ops.append(build_compute_op(
            _nid("comp"), duration_ns=int(comp_ns),
            label=str(name), **mem,
            input_loc=str(il), weight_loc=str(wl), output_loc=str(ol),
            batch_tag=str(tag)))
        base, scope = _parse_comm_field(str(comm_field))
        if base == "NONE":
            if int(comm_size) != 0:
                raise WorkloadError(
                    f"layer {name!r}: comm_type NONE with nonzero size "
                    f"{comm_size} — P2P endpoints cannot be inferred from "
                    "a layer row; canonicalize from the SEND/RECV path "
                    "instead")
            continue
        if base not in _COMM_KINDS:
            raise WorkloadError(
                f"layer {name!r}: unknown comm_type {base!r} — supported: "
                f"{sorted(_COMM_KINDS)} (fail-closed)")
        ops.append(build_collective_op(
            _nid("coll"), base, bytes=int(comm_size),
            participants=tuple(range(num_participants)),
            scope=scope if scope is not None else ALL_DIMENSIONS,
            label=str(name)))

    if not ops:
        raise WorkloadError("no operations parsed from trace rows")
    return WorkloadArtifact(
        workload_id=workload_id, source_kind=source_kind,
        parallelism=parallelism, num_participants=num_participants,
        ops=tuple(ops))

class ConservationError(WorkloadError):
    """A lowering did not preserve the workload — a lowering failure,
    never a warning."""

def check_conservation(source: WorkloadArtifact,
                       lowered_ops: list[tuple]) -> None:
    """Mechanical conservation: source ops == lowered ops.

Rationale: docs/decisions/modules/workload.md
    """
    src_ops = source.ops
    if len(lowered_ops) != len(src_ops):
        expected = [op.kind for op in src_ops]
        got = [t[1] for t in lowered_ops]
        raise ConservationError(
            f"operation count mismatch: source has {len(src_ops)} ops "
            f"{expected}, lowering produced {len(lowered_ops)} {got}")
    for src, low in zip(src_ops, lowered_ops):
        low_id, low_kind = low[0], low[1]
        if low_kind != src.kind:
            raise ConservationError(
                f"operation class mismatch at {low_id!r}: source "
                f"{src.kind}, lowering {low_kind}")
        if src.op_id != low_id:
            raise ConservationError(
                f"operation identity mismatch: expected {src.op_id!r}, "
                f"lowering reported {low_id!r}")
        if src.is_comm:
            _, _, low_bytes, low_parts, low_scope = low
            if low_bytes != src.bytes:
                raise ConservationError(
                    f"op {src.op_id!r}: byte volume not conserved — source "
                    f"{src.bytes} logical bytes, lowering reported "
                    f"{low_bytes}")
            if tuple(low_parts or ()) != src.participants:
                raise ConservationError(
                    f"op {src.op_id!r}: participant set not conserved — "
                    f"source {src.participants}, lowering "
                    f"{tuple(low_parts or ())}")
            if low_scope != src.scope:
                raise ConservationError(
                    f"op {src.op_id!r}: dimensional scope not conserved — "
                    f"source {src.scope!r}, lowering {low_scope!r}")
