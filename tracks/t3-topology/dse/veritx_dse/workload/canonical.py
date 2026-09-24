"""canonical.py — the canonical workload semantic artifact (Phase 9).

One authoritative workload-semantic representation that all supported
execution paths can lower from without silently changing the workload.

Derived from the audited semantics of the two live workload paths:

  Path B (serving):  LLMServingSim trace_generator rows → chakra → ET
  Path A (standalone BookSim): traffic_model.json flow classes

Represented semantic classes are exactly those the backends consume today
(no speculative collectives): COMPUTE, P2P send/recv, ALLREDUCE,
ALLGATHER, REDUCESCATTER, ALLTOALL, BROADCAST. Unknown kinds fail closed
(PR C lineage) — never warn-and-skip.

Rulings encoded here (Phase 9 handoff documents the evidence):

  BROADCAST (§6, Case B): the source format never guaranteed
  participants[0]=source, so source is an explicit validated field. The
  ASTRA backend already carries `bcast_root`; the positional convention
  does not survive canonicalization.

  Dimensional scope (§7): a comm op carries either an explicit boolean
  dim-participation vector or the ALL_DIMENSIONS sentinel. Scope absence
  on a comm op is a construction error — it is never read as "all dims",
  because the ASTRA fallback fabricates participation when the attribute
  is missing. Explicit [True, True] and ALL_DIMENSIONS are distinct
  values (they hash differently).

  Units (§10): every comm size is logical BYTES. Backend lowering may
  convert bytes→packets→flits but records the conversion parameters in
  its LoweringManifest — never silently.

  Identity (§16): the content hash covers schema version, participants,
  parallelism, and the ordered semantic ops. Presentation labels are
  excluded (a label rename must not change identity); operation order is
  semantic and therefore included.
"""
from __future__ import annotations

from veritx_dse.core.errors import SemanticError

import hashlib
import json
from dataclasses import dataclass, field, replace
from typing import Any

SCHEMA_VERSION = 1

# Explicit "every dimension participates" sentinel (§7). Distinct value
# from any concrete vector; serializes as the string "ALL".
ALL_DIMENSIONS = "ALL"


class WorkloadError(ValueError, SemanticError):
    """The workload cannot be represented without scientific loss.

    Raised on unknown operation kinds, invalid participants, missing
    required scope/units, or conservation failure — never a warning.
    (PR C fail-closed lineage; Phase 9 §4/§5/§13.)
    """


# ── operation model (§4: exactly what backends consume today) ───────────

_COMM_KINDS = frozenset({
    "SEND", "RECV", "ALLREDUCE", "ALLGATHER", "REDUCESCATTER",
    "ALLTOALL", "BROADCAST",
})
# MoE structural markers (audit: the converter branches on EXPERT rows to
# build the per-EP-rank subgraph and attach the dispatch/combine
# collectives). They optionally carry a collective.
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

    kind:     one of _KNOWN_KINDS (unknown → WorkloadError)
    op_id:    stable logical identity within the artifact
    bytes:    communication volume in logical BYTES (comm ops only);
              compute ops carry bytes=None — mixing the two is an error
    participants: tuple of ranks, all validated against the artifact
    scope:    explicit dim-participation vector or ALL_DIMENSIONS
              (comm ops); None (unused) on compute ops
    src/dst:  explicit endpoints for SEND/RECV/BROADCAST (§6: never
              inferred from participant order)
    duration_ns: compute duration in nanoseconds (compute ops only)
    input_bytes/weight_bytes/output_bytes: memory operand sizes in BYTES
              (compute ops; the converter emits memory load/store nodes
              from them — audit-backed semantics, part of identity)
    input_loc/weight_loc/output_loc: memory operand locations, the
              trace's verbatim location grammar ("LOCAL", "REMOTE:<dev>",
              "REMOTE:<dev>.<chan>", "CXL...", "STORAGE") — the converter
              derives tensor_loc/tensor_device from them and ASTRA
              dispatches issue_remote_mem on the result, so they are
              converter-consumed semantics and part of identity
    comm_kind: for EXPERT_BEGIN/EXPERT_END markers, the optional
              collective they carry (None = bare structural marker)
    expert_num: expert index for EXPERT markers
    label:    presentation-only; excluded from the content hash
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
            d["scope"] = self.scope  # "ALL" sentinel or explicit vector
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
        # Presentation sidecar (§16): serialized so backend lowerings can
        # reproduce executed bytes (ET node names come from source layer
        # labels), but _identity_dict strips it — a label rename must not
        # change workload identity.
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


# ── builders (validate eagerly; the only sanctioned constructors) ────────

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


def build_broadcast_op(op_id: str, *, bytes: int,
                       participants: tuple[int, ...],
                       source: int | None = None,
                       label: str = "") -> WorkloadOp:
    """BROADCAST with explicit source (§6 Case B).

    The historical participants[0]=source convention is provisional and
    not guaranteed by any source format; the canonical artifact requires
    the source explicitly (ASTRA's `bcast_root` already exists, so the
    backend side is ready for it).
    """
    if source is None:
        raise WorkloadError(
            f"op {op_id!r}: BROADCAST requires an explicit source rank — "
            "participants[0]=source is a provisional convention, not a "
            "source-format guarantee (§6)")
    if len(participants) < 2:
        raise WorkloadError(
            f"op {op_id!r}: BROADCAST needs >= 2 participants "
            f"(source + at least one destination)")
    if source not in participants:
        raise WorkloadError(
            f"op {op_id!r}: BROADCAST source {source} is not among the "
            "participants")
    _check_bytes(op_id, bytes)
    return WorkloadOp(kind="BROADCAST", op_id=op_id, bytes=bytes,
                      participants=tuple(participants), src=source,
                      scope=ALL_DIMENSIONS, label=label)


# ── the artifact ─────────────────────────────────────────────────────────

@dataclass(frozen=True)
class WorkloadArtifact:
    """Versioned, immutable, content-addressed workload semantics.

    Not a universal IR: exactly the semantic content the audited
    execution paths consume. Lowering proceeds from this artifact to
    backend representations; every lowering emits a LoweringManifest
    and must pass conservation checks (§13).
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

    # -- identity (§16) ----------------------------------------------------

    def _identity_dict(self) -> dict[str, Any]:
        """Semantic identity: everything that defines the workload.

        Excluded on purpose: labels, timestamps, paths, run ids —
        presentation metadata must not alter scientific identity (labels
        DO ride in serialize() as a lowering sidecar; they are stripped
        here so the content hash never sees them).
        Included: operation ORDER (semantically meaningful; the ET
        lowering chains nodes positionally).
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
        # Presentation sidecar (§16): labels ride in the serialized
        # artifact so backend lowerings reproduce executed bytes (ET node
        # names are source layer labels); they were stripped from
        # _identity_dict, so the recorded artifact_hash never covers them.
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

    # -- aggregate facts used by conservation and manifests ----------------

    def comm_bytes_total(self) -> int:
        return sum(op.bytes for op in self.ops if op.is_comm)

    def comm_ops(self) -> tuple[WorkloadOp, ...]:
        return tuple(op for op in self.ops if op.is_comm)


def _content_hash(identity: dict[str, Any]) -> str:
    payload = json.dumps(identity, sort_keys=True,
                         separators=(",", ":")).encode()
    return "sha256:" + hashlib.sha256(payload).hexdigest()


# ── canonicalization from Path B trace rows ──────────────────────────────

_LAYER_FIELDS = 11  # (name, comp_ns, inp_loc, inp, wt_loc, wt, out_loc, out,
#                     comm_type, comm_size, batch_tag)


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

    The rows ARE the semantic source for serving runs: the in-process
    chakra converter consumes exactly these field tuples (11 fields per
    layer row, 1 field for EXPERT/PIM markers), so canonicalizing from
    them loses nothing the backend ever saw.

    Fail-closed: an unknown comm_type is a WorkloadError naming the type
    — mirroring _parse_comm_type's supported set plus SEND/RECV pairs,
    which the converter synthesizes for PP from adjacent sizes.

    has_pp_stage_boundaries: the trace header declared pp_stage_boundaries
    (Phase 1 T2 ruling): the ET converter has no pipeline-parallel
    semantics and refuses them, so canonicalization refuses too — the
    semantics cannot survive the lowering, so they cannot enter the
    canonical artifact silently.
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
            # Marker row: EXPERT <n> <comm_type> <size> / EXPERT END ...
            tokens = row[0].split()
            marker = tokens[0]
            if marker not in ("EXPERT", "PIM"):
                raise WorkloadError(
                    f"unknown marker row {row[0]!r} — expected EXPERT/PIM")
            if marker == "PIM":
                continue  # no comm fields on PIM markers today
            # tokens[1] is the expert id (or END for the combine marker);
            # both EXPERT and EXPERT END carry optional comm fields.
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
        # Location columns are converter-consumed semantics (tensor_loc /
        # tensor_device in the ET; ASTRA dispatches issue_remote_mem on
        # them) — carried verbatim and validated, never dropped.
        ops.append(build_compute_op(
            _nid("comp"), duration_ns=int(comp_ns),
            label=str(name), **mem,
            input_loc=str(il), weight_loc=str(wl), output_loc=str(ol),
            batch_tag=str(tag)))
        base, scope = _parse_comm_field(str(comm_field))
        if base == "NONE":
            if int(comm_size) != 0:
                # P/D KV send in the serving trace: point-to-point bytes
                # on a NONE comm row are the pp kv transfer in
                # decode-heavy placement; represent as an explicit P2P
                # only when a source path declares it — otherwise refuse,
                # because inferring endpoints here would fabricate
                # semantics (§5).
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


# ── conservation invariants (§13) ────────────────────────────────────────

class ConservationError(WorkloadError):
    """A lowering did not preserve the workload — a lowering failure,
    never a warning."""


def check_conservation(source: WorkloadArtifact,
                       lowered_ops: list[tuple]) -> None:
    """Mechanical conservation: source ops == lowered ops.

    lowered_ops: iterable of tuples. For comm ops:
        (op_id, kind, bytes, participants_tuple, scope)
    For compute ops:
        (op_id, "COMPUTE", None, None, None)

    Order-sensitive (the ET lowering chains nodes positionally), so a
    reordering is itself a conservation failure, matching §9.
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
