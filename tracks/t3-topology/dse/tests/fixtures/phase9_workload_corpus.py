"""Phase-9/14/16 workload corpus — captured BEFORE any 2c edit.

The old canonical workload carries semantics the Wave-D graph does not
(compute duration, memory operand bytes/locations, dimensional scope,
expert markers, batch tags, source provenance, ordered lowering). This
corpus is the evidence that the 2c consolidation is a UNION, not an
amputation: it records what the old authority produces today, so the
canonical WorkloadGraph can be compared against it afterwards.

Run:  python3 /tmp/phase9_corpus.py <out.json>
"""
from __future__ import annotations

import hashlib
import json
import sys
import tempfile
from pathlib import Path

DSE = Path("/home/datavex/veritx-audit/tracks/t3-topology/dse")
sys.path.insert(0, str(DSE))

from veritx_dse.workload.canonical import (  # noqa: E402
    ALL_DIMENSIONS, Parallelism, WorkloadArtifact, WorkloadError, WorkloadOp,
    artifact_from_trace_rows, build_broadcast_op, build_collective_op,
    build_compute_op, build_expert_begin_op, build_p2p_op,
)


def layer_row(name, comp_ns, inp, wt, out, comm="NONE", size=0,
              tag="BATCH_1", inp_loc="LOCAL", wt_loc="LOCAL",
              out_loc="LOCAL"):
    """LLMServingSim trace row (the dialect the Chakra converter consumes)."""
    return (name, str(comp_ns), inp_loc, str(inp), wt_loc, str(wt),
            out_loc, str(out), comm, str(size), tag)
from veritx_dse.workload.lowering import (  # noqa: E402
    build_lowering_manifest, lower_to_et, rows_from_artifact,
)
from veritx_dse.workload.memory_lowering import (  # noqa: E402
    DEFAULT_POLICY, MemorySystemDesign, resolve_memory,
)
from veritx_dse.workload.timeline import (  # noqa: E402
    BackendBinding, OpService, ServiceBinding, build_timeline,
)

CORPUS: dict[str, object] = {}


def digest(value) -> str:
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, default=str,
                   separators=(",", ":")).encode()).hexdigest()


def artifact(ops, *, parallelism=None, num_participants=4,
             workload_id="w", source_kind="test"):
    return WorkloadArtifact(
        workload_id=workload_id, source_kind=source_kind,
        parallelism=parallelism or Parallelism(tp=1, dp=4),
        num_participants=num_participants, ops=tuple(ops))


def record_artifact(tag: str, art: WorkloadArtifact) -> None:
    CORPUS[f"{tag}/artifact_hash"] = art.artifact_hash
    CORPUS[f"{tag}/serialize"] = art.serialize()
    CORPUS[f"{tag}/comm_bytes_total"] = art.comm_bytes_total()
    CORPUS[f"{tag}/op_ids"] = [op.op_id for op in art.ops]
    CORPUS[f"{tag}/op_dicts"] = [op.to_dict() for op in art.ops]


# ── 1. operation semantics by kind ──────────────────────────────────────
def c(op_id="c0", **kw):
    d = dict(duration_ns=100, input_bytes=1024, weight_bytes=8192,
             output_bytes=512)
    d.update(kw)
    return build_compute_op(op_id, **d)


CASES = {
    "compute_only": [c("c0")],
    "compute_allreduce": [c("c0"),
                          build_collective_op("g0", "ALLREDUCE", bytes=4096,
                                              participants=(0, 1, 2, 3),
                                              scope=ALL_DIMENSIONS)],
    "allgather": [c("c0"), build_collective_op("g0", "ALLGATHER", bytes=1024,
                                               participants=(0, 1, 2, 3),
                                               scope=ALL_DIMENSIONS)],
    "reducescatter": [c("c0"),
                      build_collective_op("g0", "REDUCESCATTER", bytes=1024,
                                          participants=(0, 1, 2, 3),
                                          scope=ALL_DIMENSIONS)],
    "alltoall": [c("c0"), build_collective_op("g0", "ALLTOALL", bytes=1024,
                                              participants=(0, 1, 2, 3),
                                              scope=ALL_DIMENSIONS)],
    "broadcast": [c("c0"),
                  build_broadcast_op("g0", bytes=2048, source=2,
                                     participants=(0, 1, 2, 3))],
    "scope_tp_only": [c("c0"),
                      build_collective_op("g0", "ALLREDUCE", bytes=2048,
                                          participants=(0, 1),
                                          scope=[True, False, False, False])],
    "scope_explicit_all": [c("c0"),
                           build_collective_op("g0", "ALLREDUCE", bytes=2048,
                                               participants=(0, 1, 2, 3),
                                               scope=ALL_DIMENSIONS)],
    "p2p": [c("c0"), build_p2p_op("t0", "SEND", bytes=300, src=0, dst=2)],
    "memory_operands": [c("m0", input_bytes=2048, weight_bytes=4096,
                          output_bytes=1024, input_loc="LOCAL",
                          weight_loc="LOCAL", output_loc="LOCAL",
                          batch_tag="B1")],
    "expert_marker_only": [c("c0"),
                           build_expert_begin_op(3, end=False),
                           build_expert_begin_op(None, end=True)],
    "expert_with_collective": [
        c("c0"),
        build_expert_begin_op(3, comm_kind="ALLTOALL", bytes=1024,
                              participants=(0, 1, 2, 3),
                              scope=ALL_DIMENSIONS),
        build_expert_begin_op(None, end=True)],
}
for tag, ops in CASES.items():
    art = artifact(ops)
    record_artifact(tag, art)

# ── 2. op-level semantic fields (the union checklist) ───────────────────
for tag, ops in CASES.items():
    for op in ops:
        CORPUS[f"op/{tag}/{op.op_id}"] = op.to_dict()

# ── 3. refusals: the old authority's exact refusals must survive ────────
REFUSALS = {
    "compute_with_comm_bytes": lambda: build_compute_op("c", 10, bytes=5),
    "remote_operand_loc": lambda: build_compute_op(
        "c", 10, input_bytes=1, input_loc="REMOTE"),
    "cxl_operand_loc": lambda: build_compute_op(
        "c", 10, input_bytes=1, input_loc="CXL"),
    "unknown_kind": lambda: WorkloadOp(kind="NOPE", op_id="x"),
    "duplicate_ids": lambda: artifact([c("c0"), c("c0")]),
    "empty_ops": lambda: artifact([]),
    "participant_out_of_range": lambda: artifact(
        [build_collective_op("g0", "ALLREDUCE", bytes=4, participants=(0, 9), scope=ALL_DIMENSIONS)]),
    "non_divisible_allreduce": lambda: artifact(
        [build_collective_op("g0", "ALLREDUCE", bytes=1000,
                             participants=(0, 1, 2), scope=ALL_DIMENSIONS)]),
    "empty_batch_tag": lambda: build_compute_op("c", 10, batch_tag=""),
    "negative_duration": lambda: build_compute_op("c", -1),
}
for tag, fn in REFUSALS.items():
    try:
        fn()
        CORPUS[f"refusal/{tag}"] = "NO REFUSAL"
    except Exception as exc:  # noqa: BLE001 - the refusal IS the datum
        CORPUS[f"refusal/{tag}"] = {"type": type(exc).__name__,
                                    "msg": str(exc)[:160]}

# ── 4. lowering: rows + ET projection ───────────────────────────────────
for tag, ops in CASES.items():
    art = artifact(ops)
    try:
        projection = rows_from_artifact(art)
    except Exception as exc:  # noqa: BLE001
        CORPUS[f"rows/{tag}/refusal"] = {"type": type(exc).__name__,
                                         "msg": str(exc)[:160]}
        CORPUS[f"et/{tag}/refusal"] = CORPUS[f"rows/{tag}/refusal"]
        continue
    CORPUS[f"rows/{tag}/rows"] = projection.rows
    CORPUS[f"rows/{tag}/summary"] = getattr(projection, "__dict__", {})
    with tempfile.TemporaryDirectory() as tmp:
        try:
            lowered = lower_to_et(art, projection.rows,
                                  Path(tmp) / "et",
                                  num_npus=4, num_npu_group=1)
            CORPUS[f"et/{tag}/count"] = lowered.et_count
            CORPUS[f"et/{tag}/sha256s"] = lowered.et_sha256s
            CORPUS[f"et/{tag}/manifest"] = build_lowering_manifest(
                art, lowered, "astra_chakra_et").to_dict()
        except Exception as exc:  # noqa: BLE001
            CORPUS[f"et/{tag}/refusal"] = {"type": type(exc).__name__,
                                           "msg": str(exc)[:160]}

# ── 5. memory lowering ─────────────────────────────────────────────────
DESIGN = MemorySystemDesign(hbm_devices=(0,))
POLICY = DEFAULT_POLICY

MEM_CASES = {
    "operands_local": [c("m0", input_bytes=2048, weight_bytes=4096,
                         output_bytes=1024)],
    "operands_plus_collective": [
        c("m0", input_bytes=2048, weight_bytes=4096, output_bytes=1024),
        build_collective_op("g0", "ALLREDUCE", bytes=4096,
                            participants=(0, 1, 2, 3),
                            scope=ALL_DIMENSIONS)],
    "no_operands": [build_collective_op("g0", "ALLREDUCE", bytes=4096,
                                        participants=(0, 1, 2, 3),
                                        scope=ALL_DIMENSIONS)],
}
for tag, ops in MEM_CASES.items():
    art = artifact(ops)
    try:
        resolved = resolve_memory(art, DESIGN, policy=POLICY, issue_node=0)
        CORPUS[f"memory/{tag}/artifact_digest"] = digest(
            resolved.artifact.to_dict())
        CORPUS[f"memory/{tag}/artifact"] = resolved.artifact.to_dict()
        CORPUS[f"memory/{tag}/conserved"] = resolved.conserved()
        CORPUS[f"memory/{tag}/report"] = getattr(
            resolved, "conservation_report", None)
    except Exception as exc:  # noqa: BLE001
        CORPUS[f"memory/{tag}/refusal"] = {"type": type(exc).__name__,
                                           "msg": str(exc)[:160]}

# non-LOCAL locations serialize (fields appear only when non-default),
# and the RESOLVER is where the location law lives
for loc in ("REMOTE", "CXL", "STORAGE"):
    op = build_compute_op("c", 10, input_bytes=64, input_loc=loc)
    art = artifact([op])
    CORPUS[f"loc/{loc}/op_to_dict"] = op.to_dict()
    CORPUS[f"loc/{loc}/artifact_hash"] = art.artifact_hash
    try:
        resolve_memory(art, DESIGN, policy=POLICY, issue_node=0)
        CORPUS[f"loc/{loc}/resolver"] = "NO REFUSAL"
    except Exception as exc:  # noqa: BLE001
        CORPUS[f"loc/{loc}/resolver"] = {"type": type(exc).__name__,
                                         "msg": str(exc)[:160]}

# ambiguous attribution must refuse (no silent node-zero assignment)
try:
    resolve_memory(artifact([c("m0", input_bytes=1), c("m1", input_bytes=1)]),
                   DESIGN, policy=POLICY)
    CORPUS["memory/ambiguous_attribution"] = "NO REFUSAL"
except Exception as exc:  # noqa: BLE001
    CORPUS["memory/ambiguous_attribution"] = {
        "type": type(exc).__name__, "msg": str(exc)[:160]}

# ── 6. timeline / attribution (Phase 16) ───────────────────────────────
BINDING = ServiceBinding(
    compute=BackendBinding(producer="timeloop", fidelity="MODELED",
                           ns_per_cycle=0.5),
    net=BackendBinding(producer="booksim", fidelity="QUALIFIED",
                       ns_per_cycle=0.5),
    mem=BackendBinding(producer="ramulator", fidelity="MODELED",
                       ns_per_cycle=0.5))
for tag in ("compute_allreduce", "memory_operands", "scope_tp_only"):
    art = artifact(CASES[tag])
    services = {op.op_id: OpService(compute_cycles=100, mem_cycles=10)
                for op in art.ops}
    try:
        timeline = build_timeline(art, BINDING, services)
        CORPUS[f"timeline/{tag}"] = timeline.to_dict()
    except Exception as exc:  # noqa: BLE001
        CORPUS[f"timeline/{tag}/refusal"] = {"type": type(exc).__name__,
                                             "msg": str(exc)[:160]}

# ── 7. trace-row path (the ET/Chakra converter needs real layer rows) ──
TRACE_CASES = {
    "serving_dense_allreduce": (
        [layer_row("attention", 1000, 2048, 4096, 2048,
                   comm="ALLREDUCE:1,0", size=2048),
         layer_row("o_proj", 500, 1024, 2048, 1024)], dict(tp=2)),
    "serving_multi_comm": (
        [layer_row("attention", 1000, 2048, 4096, 2048,
                   comm="ALLREDUCE:1,0", size=2048),
         layer_row("mlp", 800, 4096, 8192, 4096,
                   comm="ALLGATHER:1,0", size=4096),
         layer_row("o_proj", 500, 1024, 2048, 1024)], dict(tp=2)),
    "serving_expert_rows": (
        [layer_row("attention", 1000, 2048, 4096, 2048),
         ("EXPERT 0 ALLGATHER:1,0 4096",),
         layer_row("mlp.expert", 300, 128, 256, 128),
         ("EXPERT END REDUCESCATTER:1,0 4096",)], dict(tp=2, ep=2)),
}
for tag, (rows, para) in TRACE_CASES.items():
    art = artifact_from_trace_rows(
        rows, workload_id="inst0-batch1",
        parallelism=Parallelism(**para), num_participants=2)
    CORPUS[f"trace/{tag}/artifact_hash"] = art.artifact_hash
    CORPUS[f"trace/{tag}/serialize"] = art.serialize()
    CORPUS[f"trace/{tag}/op_kinds"] = [op.kind for op in art.ops]
    CORPUS[f"trace/{tag}/op_dicts"] = [op.to_dict() for op in art.ops]
    regenerated = rows_from_artifact(art).rows
    CORPUS[f"trace/{tag}/rows_roundtrip"] = list(regenerated)
    CORPUS[f"trace/{tag}/rows_roundtrip_equal"] =         list(regenerated) == list(rows)
    with tempfile.TemporaryDirectory() as tmp:
        try:
            lowered = lower_to_et(art, list(regenerated),
                                  Path(tmp) / "llm", num_npus=2,
                                  num_npu_group=1)
            CORPUS[f"trace/{tag}/et_count"] = lowered.et_count
            CORPUS[f"trace/{tag}/et_sha256s"] = lowered.et_sha256s
            CORPUS[f"trace/{tag}/et_manifest"] = \
                build_lowering_manifest(
                    art, lowered, "astra_chakra_et").to_dict()
        except Exception as exc:  # noqa: BLE001
            CORPUS[f"trace/{tag}/et_refusal"] = {
                "type": type(exc).__name__, "msg": str(exc)[:160]}
    try:
        resolved = resolve_memory(art, DESIGN, policy=POLICY, issue_node=0)
        CORPUS[f"trace/{tag}/memory_digest"] = digest(
            resolved.artifact.to_dict())
        CORPUS[f"trace/{tag}/memory_conserved"] = resolved.conserved()
    except Exception as exc:  # noqa: BLE001
        CORPUS[f"trace/{tag}/memory_refusal"] = {
            "type": type(exc).__name__, "msg": str(exc)[:160]}

def corpus_digest(corpus: dict) -> str:
    return digest(corpus)


def build_corpus() -> dict:
    return CORPUS


if __name__ == "__main__":  # pragma: no cover - manual re-capture
    out = Path(sys.argv[1])
    out.write_text(json.dumps(CORPUS, indent=2, sort_keys=True,
                              default=str) + "\n")
    print(f"phase9 corpus written: {out} ({len(CORPUS)} entries)")
    print("corpus digest:", digest(CORPUS))
