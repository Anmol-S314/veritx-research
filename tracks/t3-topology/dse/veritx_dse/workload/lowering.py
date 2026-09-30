"""lowering.py — canonical artifact → backend representations (Phase 9).

Rationale: docs/decisions/modules/workload.md
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

@dataclass(frozen=True)
class RowsProjection:
    """Regenerated trace rows + header + broadcast roots.

Rationale: docs/decisions/modules/workload.md
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

Rationale: docs/decisions/modules/workload.md
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
    pending_comm: WorkloadOp | None = None
    last_layer_row: int | None = None
    last_row_has_comm = False

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
                rows.append(((f"EXPERT END NONE 0" if end
                              else f"EXPERT {op.expert_num} NONE 0"),))
            last_layer_row = None
            last_row_has_comm = False
            continue
        if op.kind == "SEND":
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
            root_by_row[len(rows)] = op.src
            rows.append((f"BROADCAST {op.src} {op.bytes}",))
            continue
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

def _graph_comm_token(kind: str, payload_bytes: int, scope: Any) -> str:
    """Collective token in the converter's comm-column grammar."""
    if scope is None or scope == "ALL":
        return kind
    dims = ",".join("1" if v else "0" for v in scope)
    return f"{kind}:{dims}"

def rows_from_graph(graph: Any, *, target: str = "inspection"
                    ) -> RowsProjection:
    """Project a canonical WorkloadGraph back to LLMServingSim trace rows.

Rationale: docs/decisions/modules/workload.md
    """
    from veritx_dse.core.artifact import thaw
    ordered = graph.require_total_order()
    if target == "astra_chakra_et":
        bad = [op.operation_id for op in ordered
               if op.kind == "COLLECTIVE"
               and thaw(op.detail).get("collective_kind") == "BROADCAST"]
        if bad:
            raise UnsupportedSemantic(
                f"BROADCAST op(s) {bad} cannot be lowered to "
                "astra_chakra_et: standalone BROADCAST rows carry no root "
                "in this dialect — refusing rather than inventing one "
                "(fail-closed). The backend (Workload.cc issue_broadcast) "
                "is ready; the ET side needs explicit converter support "
                "first.")
        for op in ordered:
            if op.kind == "P2P":
                raise UnsupportedSemantic(
                    f"{op.operation_id}: P2P TRANSFER cannot be "
                    "represented in trace rows (the converter synthesizes "
                    "P/D pairs positionally; explicit endpoints would be "
                    "fabricated).")
            if op.kind == "MULTICAST":
                raise UnsupportedSemantic(
                    f"{op.operation_id}: MULTICAST destinations cannot be "
                    "represented in trace rows (no destination encoding "
                    "in the dialect).")
    rows: list = []
    root_by_row: dict[int, int] = {}
    comm_op_by_row: dict[int, str] = {}
    pp_groups = max(graph.parallelism.pp, 1)
    pending: tuple[str, str, str] | None = None

    def _flush_pending() -> None:
        nonlocal pending
        if pending is None:
            return
        token, size, op_id = pending
        pending = None
        rows.append(("compute-flush", "0",
                     "LOCAL", "0", "LOCAL", "0", "LOCAL", "0",
                     token, size, "BATCH_1"))
        comm_op_by_row[len(rows) - 1] = op_id

    last_layer_row: int | None = None
    last_row_has_comm = False
    for op in ordered:
        d = thaw(op.detail)
        kind = op.kind
        if kind == "COMPUTE":
            row = [op.label or op.operation_id, str(d["duration_ns"]),
                   d["input_loc"], str(d["input_bytes"] or 0),
                   d["weight_loc"], str(d["weight_bytes"] or 0),
                   d["output_loc"], str(d["output_bytes"] or 0),
                   "NONE", "0", d["batch_tag"]]
            merged = None
            if pending is not None:
                merged = pending
                pending = None
                row[8], row[9] = merged[0], merged[1]
            rows.append(tuple(row))
            last_layer_row = len(rows) - 1
            last_row_has_comm = row[8] != "NONE"
            if last_row_has_comm:
                assert merged is not None
                comm_op_by_row[last_layer_row] = merged[2]
            continue
        if kind in ("EXPERT_BEGIN", "EXPERT_END"):
            _flush_pending()
            end = kind == "EXPERT_END"
            ck = d.get("collective_kind")
            if ck is not None:
                scope = d.get("scope")
                dims = (":" + ",".join("1" if v else "0" for v in scope)
                        if isinstance(scope, (list, tuple)) else "")
                num = d.get("expert_num")
                if end:
                    marker = f"EXPERT END {ck}{dims} {d['payload_bytes']}"
                else:
                    marker = (f"EXPERT {num} {ck}{dims} "
                              f"{d['payload_bytes']}")
                rows.append((marker,))
                comm_op_by_row[len(rows) - 1] = op.operation_id
            else:
                rows.append(((f"EXPERT END NONE 0" if end
                              else f"EXPERT {d.get('expert_num')} NONE 0"),))
            last_layer_row = None
            last_row_has_comm = False
            continue
        if kind == "PIM_CHANNEL":
            rows.append((f"PIM {d['channel']}",))
            last_layer_row = None
            last_row_has_comm = False
            continue
        if kind == "PIM_END":
            rows.append(("PIM END",))
            last_layer_row = None
            last_row_has_comm = False
            continue
        if kind == "COLLECTIVE":
            ck = d["collective_kind"]
            if ck == "BROADCAST":
                _flush_pending()
                root_by_row[len(rows)] = d["source"]
                rows.append((f"BROADCAST {d['source']} "
                             f"{d['payload_bytes']}",))
                last_layer_row = None
                last_row_has_comm = False
                continue
            token = _graph_comm_token(ck, d["payload_bytes"],
                                      d.get("scope"))
            size = str(d["payload_bytes"])
            if last_layer_row is not None and not last_row_has_comm:
                row = list(rows[last_layer_row])
                row[8] = token
                row[9] = size
                rows[last_layer_row] = tuple(row)
                comm_op_by_row[last_layer_row] = op.operation_id
                last_row_has_comm = True
                continue
            if pending is not None:
                _flush_pending()
            pending = (token, size, op.operation_id)
            continue
        _flush_pending()
        rows.append((f"{kind} {op.operation_id} {d.get('payload_bytes')}",))
        last_layer_row = None
        last_row_has_comm = False
    _flush_pending()
    header = f"COLOCATED\t\tmodel_parallel_NPU_group: {pp_groups}"
    return RowsProjection(header_line=header, rows=rows,
                           root_by_row=root_by_row,
                           comm_op_by_row=comm_op_by_row)

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

Rationale: docs/decisions/modules/workload.md
    """
    if pp_stage_boundaries:
        raise LoweringError(
            "pp_stage_boundaries present — UNSUPPORTED_WORKLOAD_SEMANTIC: "
            "the ET converter has no pipeline-parallel semantics; "
            "converting would hand every rank the full unpartitioned "
            "graph with wrong communication semantics (Phase 1 T2, "
            "fail-closed)")
    rows_from_artifact(art, target="astra_chakra_et")
    header = _header_for(art, rows)
    et_paths, et_sha256s = _convert_rows(rows, header, output_prefix,
                                         num_npus)
    return LoweredEt(
        output_prefix=str(output_prefix),
        et_paths=tuple(et_paths),
        et_sha256s=tuple(et_sha256s),
        header_line=header,
        num_npus=num_npus, num_npu_group=num_npu_group)

def _convert_rows(rows: list, header_line: str, output_prefix,
                  num_npus: int) -> tuple[list, list]:
    """Shared converter seam: rows + header → ET files + hashes."""
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
    conv.convert_rows(rows and header_line, indexed)
    et_paths = []
    for npu in range(num_npus):
        p = f"{output_prefix}.{npu}.et"
        if not os.path.isfile(p):
            raise LoweringError(
                f"converter produced no ET for npu {npu} at {p!r}")
        et_paths.append(p)
    return et_paths, [_sha256(p) for p in et_paths]

def lower_to_et_graph(graph: Any, output_prefix, *,
                      num_npus: int, num_npu_group: int,
                      pp_stage_boundaries: list | None = None,
                      target: str = "astra_chakra_et") -> LoweredEt:
    """Lower a canonical WorkloadGraph to Chakra ET (M3).

Rationale: docs/decisions/modules/workload.md
    """
    if pp_stage_boundaries:
        raise LoweringError(
            "pp_stage_boundaries present — UNSUPPORTED_WORKLOAD_SEMANTIC: "
            "the ET converter has no pipeline-parallel semantics; "
            "converting would hand every rank the full unpartitioned "
            "graph with wrong communication semantics (Phase 1 T2, "
            "fail-closed)")
    proj = rows_from_graph(graph, target=target)
    header = _header_for_graph(graph)
    et_paths, et_sha256s = _convert_rows(proj.rows, header,
                                         output_prefix, num_npus)
    return LoweredEt(
        output_prefix=str(output_prefix),
        et_paths=tuple(et_paths),
        et_sha256s=tuple(et_sha256s),
        header_line=header,
        num_npus=num_npus, num_npu_group=num_npu_group)

def _header_for_graph(graph: Any) -> str:
    pp = max(graph.parallelism.pp, 1)
    return f"COLOCATED\t\tmodel_parallel_NPU_group: {pp}"

def _header_for(art: WorkloadArtifact, rows: list) -> str:
    del rows
    pp = max(art.parallelism.pp, 1)
    return f"COLOCATED\t\tmodel_parallel_NPU_group: {pp}"

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

Rationale: docs/decisions/modules/workload.md
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
            continue
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

def et_readback_conservation_graph(graph: Any, et_paths, *,
                                   num_npus: int,
                                   num_npu_group: int) -> EtConservation:
    """Mechanical §13 check for a graph lowering, against REAL ET bytes.

    Same partitioning law as the artifact check; comm views come from
    the graph's closed detail (collective payload/participants/scope,
    expert collectives included, BROADCAST skipped — it cannot ride
    the ET dialect, exactly as in the artifact path).
    """
    from veritx_dse.core.artifact import thaw
    views: list[tuple[bool, int, tuple, Any]] = []
    for op in graph.require_total_order():
        d = thaw(op.detail)
        if op.kind in ("EXPERT_BEGIN", "EXPERT_END"):
            if d.get("collective_kind"):
                views.append((d["collective_kind"] == "ALLTOALL",
                              d["payload_bytes"],
                              tuple(d["participants"]), d.get("scope")))
        elif op.kind == "COLLECTIVE":
            if d["collective_kind"] == "BROADCAST":
                continue
            views.append((d["collective_kind"] == "ALLTOALL",
                          d["payload_bytes"], tuple(d["participants"]),
                          d.get("scope")))
    return _conserve_comm_views(views, et_paths, num_npus=num_npus,
                                num_npu_group=num_npu_group)

def _conserve_comm_views(views: list[tuple[bool, int, tuple, Any]],
                         et_paths, *, num_npus: int,
                         num_npu_group: int) -> EtConservation:
    """Shared per-rank comm conservation over (is_alltoall, bytes,
    participants, scope) views."""
    npus_per_group = num_npus // num_npu_group
    per_rank_bytes = {p: 0 for p in range(num_npus)}
    detail: dict[str, Any] = {}
    for r in range(num_npus):
        group = r // npus_per_group
        nodes = _read_et_nodes(et_paths[r])
        found = []
        for nd in nodes:
            got = _node_comm(nd)
            if got is not None:
                found.append(got)
        expected = []
        for is_alltoall, nbytes, members, scope in views:
            lo = group * npus_per_group
            hi = lo + npus_per_group
            in_scope = all(lo <= p < hi for p in members)
            if is_alltoall:
                if any(lo <= p < hi for p in members):
                    expected.append((nbytes, scope))
            elif in_scope:
                expected.append((nbytes, scope))
        got_sizes = sorted((s for s, _ in found), reverse=True)
        exp_sizes = sorted((s for s, _ in expected), reverse=True)
        if got_sizes != exp_sizes:
            raise LoweringError(
                f"rank {r}: comm byte volumes not conserved — graph "
                f"expects {exp_sizes}, ET contains {got_sizes}")
        for (s, exp_scope), (_, got_dims) in zip(
                sorted(expected, key=lambda t: -t[0]),
                sorted(found, key=lambda t: -t[0])):
            scope_list = list(exp_scope) if isinstance(
                exp_scope, (list, tuple)) else None
            if scope_list is not None and got_dims is not None \
                    and list(got_dims) != scope_list:
                raise LoweringError(
                    f"rank {r}: dimensional scope not conserved — "
                    f"graph {scope_list}, ET {list(got_dims)}")
        per_rank_bytes[r] = sum(s for s, _ in found)
        detail[f"rank{r}_comm_nodes"] = len(found)
    for is_alltoall, nbytes, members, _scope in views:
        if is_alltoall:
            continue
        for p in members:
            if per_rank_bytes.get(p, 0) < nbytes:
                raise LoweringError(
                    f"participant {p} missing comm volume {nbytes} "
                    f"(saw {per_rank_bytes.get(p, 0)}) — participants not "
                    "conserved")
    return EtConservation(
        logical_ops_conserved=True,
        comm_bytes_conserved=True,
        participants_conserved=True,
        detail=detail)
