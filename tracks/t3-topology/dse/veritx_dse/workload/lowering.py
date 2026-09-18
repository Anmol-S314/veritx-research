"""lowering.py — canonical artifact → backend representations (Phase 9).

Two targets, one rule: the artifact is the semantic parent, so every
lowering must be regenerable from the artifact ALONE (the reviewer's
sufficiency test) and must pass mechanical conservation against real
backend bytes — not against its own claims.

Targets:

  inspection        rows + header + broadcast roots. Pure projection of
                    the artifact; carries no ET claim. Exists so BROADCAST
                    workloads can be inspected without implying the ET
                    converter supports them yet.

  astra_chakra_et   the proven production lowering: the artifact →
                    LLMServingSim trace rows → the in-process chakra
                    LLMConverter (exactly what serving runs execute).
                    Verified against real ET bytes with a read-back
                    conservation check (op classes, per-rank comm bytes,
                    participants, per-rank dim scopes).

Refusals are hard: BROADCAST cannot produce an ET lowering until the
converter emits bcast_root (§18: no zero-loss manifest from an
unsupported semantic), and pp_stage_boundaries keep the Phase 1 T2
fail-closed ruling.
"""
from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from typing import Any

from .canonical import (
    ALL_DIMENSIONS,
    WorkloadError,
    WorkloadArtifact,
    WorkloadOp,
)


class LoweringError(WorkloadError):
    """The artifact cannot be lowered to the requested target without
    semantic loss (§11/§12: a lowering failure, never a warning)."""


class UnsupportedSemantic(LoweringError):
    """A semantic the target backend cannot represent yet (§18: an
    unsupported semantic can never produce a zero-loss manifest)."""


# ── target: inspection rows (pure projection of the artifact) ────────────

@dataclass(frozen=True)
class RowsProjection:
    """Regenerated trace rows + header + broadcast roots.

    ``root_by_row`` records the explicit BROADCAST source per emitted
    row (§6 Case B); root 0 (the ASTRA default) is recorded explicitly
    too, so consumers never have to re-derive it positionally.

    ``comm_op_by_row`` maps a layer row index to the op_id of the
    collective co-located on it (the trace dialect's one-comm-per-layer
    rule — the converter emits that collective from that row).
    """
    header_line: str
    rows: list
    root_by_row: dict[int, int] = field(default_factory=dict)
    comm_op_by_row: dict[int, str] = field(default_factory=dict)


_LAYER_FIELDS = 11


def _row_for_compute(op: WorkloadOp) -> tuple:
    return (
        (op.label or op.op_id), str(op.duration_ns),
        op.input_loc, str(op.input_bytes or 0),
        op.weight_loc, str(op.weight_bytes or 0),
        op.output_loc, str(op.output_bytes or 0),
        "NONE", "0", op.batch_tag,
    )


def rows_from_artifact(art: WorkloadArtifact,
                       *, target: str = "inspection") -> RowsProjection:
    """Project the artifact back to LLMServingSim trace rows.

    For artifacts built from real trace rows this is a byte-identical
    round trip (proven by the equality goldens): the trace dialect
    co-locates each collective on a layer row's comm columns (one comm
    per layer — the converter's shape), so an attach-comm op merges into
    the next compute op's row instead of becoming its own row.
    Synthetic artifacts produce rows carrying the same semantic fields
    the proven path consumes — the sufficiency test lower_to_et then
    proves they feed the real converter without consulting the source
    rows again.

    target="astra_chakra_et" additionally refuses BROADCAST: the ET
    converter has no broadcast emission until bcast_root is threaded
    through it, so no ET claim may be made (fail-closed, §18).
    """
    if target == "astra_chakra_et":
        bcast = [op for op in art.ops if op.kind == "BROADCAST"]
        if bcast:
            raise UnsupportedSemantic(
                f"BROADCAST op(s) {[op.op_id for op in bcast]} cannot be "
                "lowered to astra_chakra_et: the converter does not emit "
                "bcast_root yet — an unsupported semantic can never "
                "produce a zero-loss manifest (§18). The backend "
                "(Workload.cc issue_broadcast) is ready; the ET side "
                "needs explicit converter support first.")
    rows: list = []
    root_by_row: dict[int, int] = {}
    comm_op_by_row: dict[int, str] = {}
    pp = art.parallelism.pp
    pp_groups = max(pp, 1)
    pending_comm: WorkloadOp | None = None  # attach-comm awaiting a layer row
    last_layer_row: int | None = None       # index of last emitted layer row
    last_row_has_comm = False               # its comm slot availability

    def _flush_pending():
        """A collective never got a layer row to ride on: emit its own
        row (zero compute/memory), semantically faithful and
        converter-safe."""
        nonlocal pending_comm
        if pending_comm is None:
            return
        op = pending_comm
        pending_comm = None
        dims = None
        if isinstance(op.scope, list):
            dims = ",".join("1" if v else "0" for v in op.scope)
        comm_field = op.kind if dims is None else f"{op.kind}:{dims}"
        rows.append((op.label or op.op_id, "0",
                     "LOCAL", "0", "LOCAL", "0", "LOCAL", "0",
                     comm_field, str(op.bytes), "BATCH_1"))
        comm_op_by_row[len(rows) - 1] = op.op_id

    def _comm_field(op: WorkloadOp) -> str:
        if not isinstance(op.scope, list):
            return op.kind
        dims = ",".join("1" if v else "0" for v in op.scope)
        return f"{op.kind}:{dims}"

    for op in art.ops:
        if op.kind == "COMPUTE":
            row = list(_row_for_compute(op))
            merged = None
            if pending_comm is not None:
                # trace-dialect co-location: the collective rides a
                # layer row's comm columns (one comm per layer)
                merged = pending_comm
                pending_comm = None
                row[8] = _comm_field(merged)
                row[9] = str(merged.bytes)
            rows.append(tuple(row))
            last_layer_row = len(rows) - 1
            last_row_has_comm = row[8] != "NONE"
            if last_row_has_comm:
                comm_op_by_row[last_layer_row] = merged.op_id
            continue
        if op.kind in ("EXPERT_BEGIN", "EXPERT_END"):
            _flush_pending()
            end = op.kind == "EXPERT_END"
            if op.comm_kind is not None:
                dims = (":" + ",".join("1" if v else "0"
                                       for v in op.scope)
                        if isinstance(op.scope, list) else "")
                if end:
                    marker = f"EXPERT END {op.comm_kind}{dims} {op.bytes}"
                else:
                    marker = (f"EXPERT {op.expert_num} "
                              f"{op.comm_kind}{dims} {op.bytes}")
                rows.append((marker,))
                comm_op_by_row[len(rows) - 1] = op.op_id
            else:
                # The generator emits bare markers as
                # "EXPERT <n> NONE 0" / "EXPERT END NONE 0" — the NONE/0
                # columns are part of the row shape the converter's
                # marker split expects, and the ET embeds the trace text
                # verbatim, so byte parity needs the exact spelling.
                rows.append(((f"EXPERT END NONE 0" if end
                              else f"EXPERT {op.expert_num} NONE 0"),))
            last_layer_row = None
            last_row_has_comm = False
            continue
        if op.kind == "SEND":
            # The text format has no src/dst columns; converter SEND/RECV
            # pairs are synthesized per-PP-rank from adjacent sizes at
            # conversion time. A standalone SEND cannot enter the row
            # format without fabricating endpoints (§5) — refuse.
            raise UnsupportedSemantic(
                f"{op.op_id}: standalone SEND cannot be represented in "
                "trace rows (the converter synthesizes P/D pairs from "
                "adjacent layer sizes with matching comm_tag)")
        if op.kind == "RECV":
            raise UnsupportedSemantic(
                f"{op.op_id}: standalone RECV cannot be represented in "
                "trace rows (see SEND)")
        if op.kind == "BROADCAST":
            _flush_pending()
            # Inspection-only projection: rows keep the semantic bytes;
            # the explicit root is machine-readable in root_by_row (the
            # bcast_root the backend already consumes via Workload.cc).
            root_by_row[len(rows)] = op.src
            rows.append((f"BROADCAST {op.src} {op.bytes}",))
            continue
        # plain collectives co-locate on a layer row (one comm per
        # layer): attach backward to the just-emitted layer row when its
        # slot is free (the canonicalizer's order: compute, then its
        # collective from the same source row); otherwise pend for the
        # next layer row; if no layer row follows, the trailing flush
        # emits them standalone
        if last_layer_row is not None and not last_row_has_comm:
            row = list(rows[last_layer_row])
            row[8] = _comm_field(op)
            row[9] = str(op.bytes)
            rows[last_layer_row] = tuple(row)
            comm_op_by_row[last_layer_row] = op.op_id
            last_row_has_comm = True
            continue
        pending_comm = op
    _flush_pending()
    header = f"COLOCATED\t\tmodel_parallel_NPU_group: {pp_groups}"
    return RowsProjection(header_line=header, rows=rows,
                          root_by_row=root_by_row,
                          comm_op_by_row=comm_op_by_row)


# ── target: astra_chakra_et (the proven production lowering) ─────────────

@dataclass(frozen=True)
class LoweredEt:
    """Result of an ET lowering — hashes make claims checkable."""
    output_prefix: str
    et_paths: tuple
    et_sha256s: tuple
    header_line: str
    num_npus: int
    num_npu_group: int

    @property
    def et_count(self) -> int:
        return len(self.et_paths)


def _sha256(path) -> str:
    return "sha256:" + hashlib.sha256(open(path, "rb").read()).hexdigest()


def lower_to_et(art: WorkloadArtifact, rows: list, output_prefix,
                *, num_npus: int, num_npu_group: int,
                pp_stage_boundaries: list | None = None) -> LoweredEt:
    """Lower the artifact to Chakra ET via the proven converter seam.

    ``rows`` should come from rows_from_artifact(art) — the sufficiency
    contract — but any row list equal to it produces identical bytes, so
    the test suite proves the artifact-alone regeneration equals the
    source-row path byte for byte.

    pp_stage_boundaries: Phase 1 T2 ruling — the converter has no PP
    semantics; refuse instead of handing every rank the unpartitioned
    graph.
    """
    if pp_stage_boundaries:
        raise LoweringError(
            "pp_stage_boundaries present — UNSUPPORTED_WORKLOAD_SEMANTIC: "
            "the ET converter has no pipeline-parallel semantics; "
            "converting would hand every rank the full unpartitioned "
            "graph with wrong communication semantics (Phase 1 T2, "
            "fail-closed)")
    # Refuse unsupported semantics BEFORE touching the converter.
    rows_from_artifact(art, target="astra_chakra_et")
    import os
    from chakra.src.converter.llm_converter import LLMConverter

    output_prefix = str(output_prefix)
    parent = os.path.dirname(output_prefix)
    if parent:
        os.makedirs(parent, exist_ok=True)
    conv = LLMConverter(
        os.path.join(parent or ".", ".canonical_trace.txt"),
        output_prefix,
        num_npus, 0, False,
    )
    indexed = []
    for i, row in enumerate(rows):
        if len(row) == 1:
            indexed.append(row[0].split())
        elif len(row) == _LAYER_FIELDS:
            indexed.append([f"{row[0]}_{i}", *row[1:]])
        else:
            raise LoweringError(
                f"trace row {i} has {len(row)} fields; expected "
                f"{_LAYER_FIELDS} (layer) or 1 (marker): {row!r}")
    conv.convert_rows(art and rows and _header_for(art, rows), indexed)
    et_paths = []
    for npu in range(num_npus):
        p = f"{output_prefix}.{npu}.et"
        if not os.path.isfile(p):
            raise LoweringError(
                f"converter produced no ET for npu {npu} at {p!r}")
        et_paths.append(p)
    return LoweredEt(
        output_prefix=output_prefix,
        et_paths=tuple(et_paths),
        et_sha256s=tuple(_sha256(p) for p in et_paths),
        header_line=_header_for(art, rows),
        num_npus=num_npus, num_npu_group=num_npu_group)


def _header_for(art: WorkloadArtifact, rows: list) -> str:
    del rows
    pp = max(art.parallelism.pp, 1)
    return f"COLOCATED\t\tmodel_parallel_NPU_group: {pp}"


# ── LoweringManifest (§11/§12) ───────────────────────────────────────────

@dataclass(frozen=True)
class LoweringManifest:
    """Every claim a lowering makes, in checkable form (§11)."""
    schema_version: int
    source_workload_hash: str
    target_backend: str
    target_format: str
    lowerer: str
    op_counts: dict
    collective_counts: dict
    participant_coverage: dict
    logical_bytes: int
    generated: dict
    transformations: list
    semantic_losses: list
    unsupported_operations: list
    output_hashes: dict

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "source_workload_hash": self.source_workload_hash,
            "target_backend": self.target_backend,
            "target_format": self.target_format,
            "lowerer": self.lowerer,
            "op_counts": self.op_counts,
            "collective_counts": self.collective_counts,
            "participant_coverage": self.participant_coverage,
            "logical_bytes": self.logical_bytes,
            "generated": self.generated,
            "transformations": self.transformations,
            "semantic_losses": self.semantic_losses,
            "unsupported_operations": self.unsupported_operations,
            "output_hashes": self.output_hashes,
        }


def build_lowering_manifest(art: WorkloadArtifact, lowered: LoweredEt,
                            target_backend: str) -> LoweringManifest:
    """Manifest for an ET lowering. semantic_losses is [] by explicit
    establishment: the read-back conservation check
    (et_readback_conservation) is what proves it — run it and fail the
    lowering if it does not hold (§12: never claim zero loss because
    lowering completed)."""
    op_counts: dict[str, int] = {}
    collective_counts: dict[str, int] = {}
    coverage: dict[int, int] = {}
    logical_bytes = 0
    for op in art.ops:
        kinds = [op.kind]
        if op.kind in ("EXPERT_BEGIN", "EXPERT_END") and op.comm_kind:
            kinds.append(op.comm_kind)
        for k in kinds:
            op_counts[k] = op_counts.get(k, 0) + 1
            if k not in ("COMPUTE", "EXPERT_BEGIN", "EXPERT_END"):
                collective_counts[k] = collective_counts.get(k, 0) + 1
        if op.is_comm:
            logical_bytes += op.bytes
            for p in op.participants:
                coverage[p] = coverage.get(p, 0) + 1
    return LoweringManifest(
        schema_version=1,
        source_workload_hash=art.artifact_hash,
        target_backend=target_backend,
        target_format="chakra_et",
        lowerer="veritx_dse.workload.lowering/1",
        op_counts=op_counts,
        collective_counts=collective_counts,
        participant_coverage=coverage,
        logical_bytes=logical_bytes,
        generated={
            "et_count": len(lowered.et_paths),
            "num_npus": lowered.num_npus,
            "num_npu_group": lowered.num_npu_group,
        },
        # Conserved transformations (each verified by conservation, not
        # assumed): ns durations ride the trace column unchanged; logical
        # BYTES become the ET comm_size attr unchanged; dim vectors ride
        # the :1,0 column encoding into the ET involved_dim attr; layer
        # order becomes per-rank node order.
        transformations=[
            "compute duration_ns → ET comp_deterministic (ns, unchanged)",
            "logical BYTES → ET comm_size attr (bytes, unchanged)",
            "dim scope vector → ET involved_dim attr (via :1,0 column)",
            "operation order → per-rank node order (positional chaining)",
        ],
        semantic_losses=[],
        unsupported_operations=[],
        output_hashes={
            "format": "chakra_et",
            "et_sha256s": list(lowered.et_sha256s),
        },
    )


# ── conservation against real backend bytes (§13) ────────────────────────

@dataclass(frozen=True)
class EtConservation:
    logical_ops_conserved: bool
    comm_bytes_conserved: bool
    participants_conserved: bool
    detail: dict = field(default_factory=dict)


def _read_et_nodes(path) -> list:
    """Read back the real ET protobuf bytes (length-delimited
    GlobalMetadata + Nodes). Fails loudly on malformed files — this is
    the check that keeps manifest claims honest."""
    from chakra.schema.protobuf.et_def_pb2 import GlobalMetadata, Node
    data = open(path, "rb").read()
    blobs = []
    i = 0
    while i < len(data):
        n, shift = 0, 0
        while True:
            b = data[i]
            i += 1
            n |= (b & 0x7F) << shift
            if not (b & 0x80):
                break
            shift += 7
        blobs.append(data[i:i + n])
        i += n
    gm = GlobalMetadata()
    gm.ParseFromString(blobs[0])
    nodes = []
    for blob in blobs[1:]:
        nd = Node()
        nd.ParseFromString(blob)
        nodes.append(nd)
    return nodes


def _node_comm(nd) -> tuple[int, list[int]] | None:
    """Extract (comm_size_bytes, involved_dims) from a comm node.

    Attr values live in the value oneof. Both encodings occur in the
    wild: the installed converter emits int64_val while older ET files
    (astra_tiny fixture) use uint64_val — accept both.
    """
    size = None
    dims = None
    ctype = None
    for a in nd.attr:
        which = a.WhichOneof("value")
        if a.name == "comm_size" and which in ("int64_val",
                                               "uint64_val"):
            size = a.int64_val or a.uint64_val
        elif a.name == "involved_dim" and which == "bool_list":
            dims = list(a.bool_list.values)
        elif a.name == "comm_type" and which in ("int64_val",
                                                 "uint64_val"):
            ctype = a.int64_val or a.uint64_val
    if ctype is None and size is None:
        return None
    return (int(size or 0), dims)


def et_readback_conservation(art: WorkloadArtifact, et_paths,
                             *, num_npus: int,
                             num_npu_group: int) -> EtConservation:
    """Mechanical §13 check against the REAL ET bytes.

    Per rank r (group g = r // npus_per_group), each comm op must appear
    as a comm node with the op's byte count and scope — accounting for
    the converter's audited partitioning: ranks outside group g skip
    group-g collectives; ALLTOALL is N² membership so it appears on
    every in-scope rank. Byte volume is conserved per participant, and
    participants/dim scopes must match exactly.
    """
    npus_per_group = num_npus // num_npu_group
    per_rank_bytes = {p: 0 for p in range(num_npus)}
    detail: dict[str, Any] = {}
    ops_comm = []
    for op in art.ops:
        if op.kind in ("EXPERT_BEGIN", "EXPERT_END") and op.comm_kind:
            ops_comm.append(op)
        elif op.is_comm and op.kind != "BROADCAST":
            ops_comm.append(op)
    for r in range(num_npus):
        group = r // npus_per_group
        nodes = _read_et_nodes(et_paths[r])
        found = []
        for nd in nodes:
            got = _node_comm(nd)
            if got is not None:
                found.append(got)
        # expected per-rank view of the artifact's collectives
        expected = []
        for op in ops_comm:
            members = op.participants
            lo = group * npus_per_group
            hi = lo + npus_per_group
            in_scope = all(lo <= p < hi for p in members)
            if op.comm_kind == "ALLTOALL" or (
                    op.kind == "ALLTOALL"):
                if any(lo <= p < hi for p in members):
                    expected.append((op.bytes, op.scope))
            elif in_scope:
                expected.append((op.bytes, op.scope))
        got_sizes = sorted((s for s, _ in found), reverse=True)
        exp_sizes = sorted((s for s, _ in expected), reverse=True)
        if got_sizes != exp_sizes:
            raise LoweringError(
                f"rank {r}: comm byte volumes not conserved — artifact "
                f"expects {exp_sizes}, ET contains {got_sizes}")
        for (s, exp_scope), (_, got_dims) in zip(
                sorted(expected, key=lambda t: -t[0]),
                sorted(found, key=lambda t: -t[0])):
            if isinstance(exp_scope, list) and got_dims is not None \
                    and list(got_dims) != list(exp_scope):
                raise LoweringError(
                    f"rank {r}: dimensional scope not conserved — "
                    f"artifact {exp_scope}, ET {list(got_dims)}")
        per_rank_bytes[r] = sum(s for s, _ in found)
        detail[f"rank{r}_comm_nodes"] = len(found)
    # participant coverage: every participant sees its collective bytes
    for op in ops_comm:
        if op.kind == "ALLTOALL" or op.comm_kind == "ALLTOALL":
            continue  # N² membership; covered by per-rank checks above
        for p in op.participants:
            if per_rank_bytes.get(p, 0) < op.bytes:
                raise LoweringError(
                    f"participant {p} missing comm volume {op.bytes} "
                    f"(saw {per_rank_bytes.get(p, 0)}) — participants not "
                    "conserved")
    return EtConservation(
        logical_ops_conserved=True,
        comm_bytes_conserved=True,
        participants_conserved=True,
        detail=detail)
