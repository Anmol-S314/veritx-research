"""Traffic-matrix assembly: Pass 1 (memory) + Pass 2 (collectives),
broken out PER PIPELINE STAGE (plan.md Section 5, extended).

A single combined N x N matrix hides which part of the layer is generating
NoC load. This module instead builds one matrix per stage:

    qkv_proj    -- Pass 1 only (output-channel split, no reduction)
    attention   -- Pass 1 for attention_qk/softmax/attention_sv, PLUS
                   Pass 2 head-group all-reduce traffic (Regime B only --
                   zero head-group edges in Regime A, so this matrix is
                   Pass-1-only there)
    out_proj    -- Pass 1 for out_proj, PLUS Pass 2 tp_global all-reduce
                   traffic for the out_proj partial-sum tensor
    gate_up_proj-- Pass 1 only (output-channel split, no reduction)
    down_proj   -- Pass 1 for down_proj, PLUS Pass 2 tp_global all-reduce
                   traffic for the down_proj partial-sum tensor
    full_layer  -- elementwise sum of the five above (== the old single
                   combined matrix)

Each is scoped to one op_template group so a stage's matrix only reflects
that stage's real traffic -- e.g. an all-qkv_proj stage matrix never has
tile<->tile edges, because qkv_proj never triggers a collective.
"""
import numpy as np

from tl_ir import TileProgram
from collectives import ring_allreduce_pairs
from softmax_accounting import softmax_dram_bytes

STAGE_BY_OP_TEMPLATE = {
    "qkv_proj": "qkv_proj",
    "attention_qk": "attention",
    "softmax": "attention",
    "attention_sv": "attention",
    "out_proj": "out_proj",
    "gate_up_proj": "gate_up_proj",
    "down_proj": "down_proj",
}
STAGES = ["qkv_proj", "attention", "out_proj", "gate_up_proj", "down_proj"]


def _tensor_stage(tensor):
    """Which stage 'owns' a given collective tensor's traffic."""
    if tensor.scope == "head_group":
        return "attention"
    if tensor.scope == "tp_global":
        if "outproj" in tensor.name.lower():
            return "out_proj"
        if "downproj" in tensor.name.lower():
            return "down_proj"
    return None  # not a reduced tensor -- no NoC collective traffic


def build_stage_traffic_matrices(program: TileProgram, runner, dtype_bytes: int) -> dict:
    """Returns {stage_name: (N+1)x(N+1) np.ndarray}, keys = STAGES + ['full_layer'].
    Row/col `num_tiles` (the last one) is the DRAM node in every matrix."""
    num_tiles = program.num_tiles
    dram_node = num_tiles
    size = num_tiles + 1
    matrices = {stage: np.zeros((size, size)) for stage in STAGES}

    # ---- Pass 1: memory traffic, routed into the op's stage matrix ----
    for op in program.ops:
        stage = STAGE_BY_OP_TEMPLATE[op.op_template]
        if op.op_template == "softmax":
            total = softmax_dram_bytes(op.shape["score_tensor_bytes"])
            read_bytes, write_bytes = total / 2, total / 2
        else:
            read_bytes, write_bytes = runner.get_dram_traffic(
                op.op_id, op.tile_id, op.op_template, op.shape, dtype_bytes,
            )
        matrices[stage][op.tile_id][dram_node] += read_bytes
        matrices[stage][dram_node][op.tile_id] += write_bytes

    # ---- Pass 2: collective traffic, routed into the owning stage's matrix ----
    for tensor in program.tensors.values():
        if tensor.reduction != "ring_allreduce":
            continue
        stage = _tensor_stage(tensor)
        if stage is None:
            continue
        for src, dst, b in ring_allreduce_pairs(tensor.producers, tensor.size_bytes):
            matrices[stage][src][dst] += b

    matrices["full_layer"] = sum(matrices[s] for s in STAGES)
    return matrices


def write_matrix(matrix: np.ndarray, path, normalize: bool = True):
    """Booksim `matrix(<file>)` format: one row of whitespace-separated
    values per line, row = src node, col = dst node, last node = DRAM.
    Normalization is per-file (each stage matrix normalized to its own max
    row sum) -- correct if you're feeding Booksim one stage at a time as
    separate simulation phases. Pass normalize=False if you need to compare
    absolute magnitude across stages instead."""
    mat = matrix.copy()
    if normalize:
        max_row = mat.sum(axis=1).max()
        if max_row > 0:
            mat = mat / max_row
    with open(path, "w") as f:
        f.write("# Timeloop-derived traffic matrix (row=src node, col=dst node; last node = DRAM)\n")
        for row in mat:
            f.write(" ".join(f"{v:g}" for v in row) + "\n")
