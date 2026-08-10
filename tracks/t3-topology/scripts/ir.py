"""Data model (IR) for the Timeloop -> Booksim spatial-mapping pipeline.

See plan.md Section 3 for the design rationale. Zero external dependencies
so every other stage (mapping strategy, Timeloop runner, traffic-matrix
assembly) can import it without circular-import risk.
"""
from __future__ import annotations
from dataclasses import dataclass, field


@dataclass
class ModelSpec:
    hidden_size: int
    num_heads: int
    num_kv_heads: int
    head_dim: int
    ffn_intermediate_size: int
    seq_len: int
    num_layers: int
    dtype_bytes: int = 2  # bf16/fp16 default

    def __post_init__(self):
        if self.num_heads % self.num_kv_heads != 0:
            raise ValueError(
                f"num_heads ({self.num_heads}) must be a multiple of "
                f"num_kv_heads ({self.num_kv_heads})."
            )


@dataclass
class OpAssignment:
    op_id: str                  # unique, e.g. "L0_qkv_proj_tile3"
    tile_id: int
    op_template: str            # "qkv_proj" | "attention_qk" | "attention_sv"
                                 # | "out_proj" | "gate_up_proj" | "down_proj"
                                 # | "softmax" (analytical, no Timeloop run)
    shape: dict                 # resolved M/N/K (or score_tensor_bytes for softmax)
    produces: str                # TensorHandle name this op contributes to
    consumes: list = field(default_factory=list)


@dataclass
class TensorHandle:
    name: str                    # e.g. "Score_head7", "TPPartial_outproj"
    size_bytes: int
    producers: list = field(default_factory=list)   # tile_ids contributing
    consumers: list = field(default_factory=list)   # tile_ids that need it
    reduction: str = None        # None | "ring_allreduce"
    scope: str = None            # "head_group" | "tp_global" | None


@dataclass
class TileProgram:
    num_tiles: int
    ops: list = field(default_factory=list)
    tensors: dict = field(default_factory=dict)

    def add_op(self, op: OpAssignment):
        self.ops.append(op)

    def add_tensor(self, tensor: TensorHandle):
        """Merge if a tensor with this name already exists (defensive --
        in v1's MegatronTPStrategy every tensor name is written exactly
        once, but this keeps the IR safe for future, less regular
        strategies where producers might be added incrementally)."""
        if tensor.name in self.tensors:
            existing = self.tensors[tensor.name]
            existing.producers = sorted(set(existing.producers) | set(tensor.producers))
            existing.consumers = sorted(set(existing.consumers) | set(tensor.consumers))
        else:
            self.tensors[tensor.name] = tensor