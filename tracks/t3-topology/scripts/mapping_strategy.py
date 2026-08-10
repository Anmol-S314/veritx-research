"""MegatronTPStrategy.map() -- plan.md Section 4 decision tree.

Builds a single-layer TileProgram (steady-state single-layer replay is the
v1 assumption, plan.md Section 8). Callers scale the resulting traffic by
num_layers for a whole-model estimate -- see run_pipeline.py.

For v1, cross-tile traffic only arises at exactly two collective scopes
(plan.md Section 2 / Section 3): head-group all-reduce (Regime B only,
around attention_qk/attention_sv) and global TP all-reduce (both regimes,
around out_proj/down_proj). Everything else is either fully local
(Regime A attention) or a plain output-channel split (no reduction).
"""
from ir import OpAssignment, TensorHandle, TileProgram
from distribute import assign_heads_regime_a, distribute_regime_b, split_sizes


class MegatronTPStrategy:

    def map(self, model_spec, num_tiles: int) -> TileProgram:
        m = model_spec
        program = TileProgram(num_tiles=num_tiles)
        tiles_per_head = num_tiles / m.num_heads

        if tiles_per_head <= 1:
            self._map_regime_a(program, m, num_tiles)
        else:
            self._map_regime_b(program, m, num_tiles)

        self._map_ffn_and_outproj(program, m, num_tiles)
        return program

    # ---------------- Regime A: num_tiles <= num_heads ---------------------

    def _map_regime_a(self, program, m, num_tiles):
        head_assignment = assign_heads_regime_a(m.num_heads, num_tiles)

        for tile_id, heads in head_assignment.items():
            n_heads = len(heads)
            if n_heads == 0:
                continue

            # qkv_proj: column-parallel, no reduction. One fused GEMM per
            # tile covering all heads it owns (3*head_dim output cols/head).
            qkv_name = f"QKV_tile{tile_id}"
            program.add_op(OpAssignment(
                op_id=f"qkv_proj_tile{tile_id}", tile_id=tile_id, op_template="qkv_proj",
                shape={"M": m.seq_len, "N": 3 * m.head_dim * n_heads, "K": m.hidden_size},
                produces=qkv_name, consumes=[],
            ))

            for h in heads:
                # attention_qk: fully local to this tile, no reduction.
                score_name = f"Score_head{h}"
                score_bytes = m.seq_len * m.seq_len * m.dtype_bytes
                program.add_op(OpAssignment(
                    op_id=f"attention_qk_head{h}", tile_id=tile_id, op_template="attention_qk",
                    shape={"M": m.seq_len, "N": m.seq_len, "K": m.head_dim},
                    produces=score_name, consumes=[qkv_name],
                ))
                program.add_tensor(TensorHandle(
                    name=score_name, size_bytes=score_bytes,
                    producers=[tile_id], consumers=[tile_id],
                    reduction=None, scope=None,
                ))

                # softmax: analytical, fully local, no Timeloop run.
                prob_name = f"Prob_head{h}"
                program.add_op(OpAssignment(
                    op_id=f"softmax_head{h}", tile_id=tile_id, op_template="softmax",
                    shape={"score_tensor_bytes": score_bytes},
                    produces=prob_name, consumes=[score_name],
                ))

                # attention_sv: fully local, no reduction.
                ctx_name = f"Context_head{h}"
                program.add_op(OpAssignment(
                    op_id=f"attention_sv_head{h}", tile_id=tile_id, op_template="attention_sv",
                    shape={"M": m.seq_len, "N": m.head_dim, "K": m.seq_len},
                    produces=ctx_name, consumes=[prob_name],
                ))
                program.add_tensor(TensorHandle(
                    name=ctx_name, size_bytes=m.seq_len * m.head_dim * m.dtype_bytes,
                    producers=[tile_id], consumers=[tile_id],
                    reduction=None, scope=None,
                ))

    # ---------------- Regime B: num_tiles > num_heads -----------------------

    def _map_regime_b(self, program, m, num_tiles):
        head_tile_counts = distribute_regime_b(m.num_heads, num_tiles)

        for head_id, group_tiles in head_tile_counts.items():
            k = len(group_tiles)

            # qkv_proj: split this head's 3*head_dim output cols across
            # the k tiles that share it. No reduction (output split).
            qkv_cols = split_sizes(3 * m.head_dim, k)
            for tile_id, cols in zip(group_tiles, qkv_cols):
                program.add_op(OpAssignment(
                    op_id=f"qkv_proj_head{head_id}_tile{tile_id}", tile_id=tile_id,
                    op_template="qkv_proj",
                    shape={"M": m.seq_len, "N": cols, "K": m.hidden_size},
                    produces=f"QKV_head{head_id}_tile{tile_id}", consumes=[],
                ))

            # attention_qk: split head_dim (the reduction/contraction dim)
            # -> each tile computes a PARTIAL score matrix -> head-group
            # all-reduce before softmax.
            hd_slices = split_sizes(m.head_dim, k)
            score_name = f"Score_head{head_id}"
            full_score_bytes = m.seq_len * m.seq_len * m.dtype_bytes
            for tile_id, k_slice in zip(group_tiles, hd_slices):
                program.add_op(OpAssignment(
                    op_id=f"attention_qk_head{head_id}_tile{tile_id}", tile_id=tile_id,
                    op_template="attention_qk",
                    shape={"M": m.seq_len, "N": m.seq_len, "K": k_slice},
                    produces=score_name, consumes=[f"QKV_head{head_id}_tile{tile_id}"],
                ))
            program.add_tensor(TensorHandle(
                name=score_name, size_bytes=full_score_bytes,
                producers=list(group_tiles), consumers=list(group_tiles),
                reduction="ring_allreduce", scope="head_group",
            ))

            # softmax: analytical. Ring all-reduce output is already
            # replicated to every participant, so every tile in the group
            # has the full score matrix with zero extra NoC traffic -- the
            # softmax itself is attributed to the designated tile
            # (group_tiles[0]) purely for bookkeeping; the DRAM byte cost
            # doesn't depend on which tile "does" it.
            designated = group_tiles[0]
            prob_name = f"Prob_head{head_id}"
            program.add_op(OpAssignment(
                op_id=f"softmax_head{head_id}", tile_id=designated, op_template="softmax",
                shape={"score_tensor_bytes": full_score_bytes},
                produces=prob_name, consumes=[score_name],
            ))

            # attention_sv: split seq_len (the reduction/contraction dim)
            # -> each tile computes a PARTIAL context -> head-group
            # all-reduce.
            seq_slices = split_sizes(m.seq_len, k)
            ctx_name = f"Context_head{head_id}"
            for tile_id, k_slice in zip(group_tiles, seq_slices):
                program.add_op(OpAssignment(
                    op_id=f"attention_sv_head{head_id}_tile{tile_id}", tile_id=tile_id,
                    op_template="attention_sv",
                    shape={"M": m.seq_len, "N": m.head_dim, "K": k_slice},
                    produces=ctx_name, consumes=[prob_name],
                ))
            program.add_tensor(TensorHandle(
                name=ctx_name, size_bytes=m.seq_len * m.head_dim * m.dtype_bytes,
                producers=list(group_tiles), consumers=list(group_tiles),
                reduction="ring_allreduce", scope="head_group",
            ))

    # ---------------- Shared across both regimes ----------------------------

    def _map_ffn_and_outproj(self, program, m, num_tiles):
        """out_proj / gate_up_proj / down_proj: unchanged regardless of how
        attention was internally partitioned -- always split across ALL
        num_tiles (plan.md Section 1/2). out_proj and down_proj are
        row-parallel and always need the *global* TP all-reduce."""
        out_cols = split_sizes(m.hidden_size, num_tiles)
        ffn_cols = split_sizes(2 * m.ffn_intermediate_size, num_tiles)  # gate+up fused
        down_k = split_sizes(m.ffn_intermediate_size, num_tiles)

        outproj_name = "TPPartial_outproj"
        downproj_name = "TPPartial_downproj"

        for tile_id in range(num_tiles):
            program.add_op(OpAssignment(
                op_id=f"out_proj_tile{tile_id}", tile_id=tile_id, op_template="out_proj",
                shape={"M": m.seq_len, "N": out_cols[tile_id], "K": m.hidden_size},
                produces=outproj_name, consumes=[],
            ))
            program.add_op(OpAssignment(
                op_id=f"gate_up_proj_tile{tile_id}", tile_id=tile_id, op_template="gate_up_proj",
                shape={"M": m.seq_len, "N": ffn_cols[tile_id], "K": m.hidden_size},
                produces=f"FFNIntermediate_tile{tile_id}", consumes=[],
            ))
            program.add_op(OpAssignment(
                op_id=f"down_proj_tile{tile_id}", tile_id=tile_id, op_template="down_proj",
                shape={"M": m.seq_len, "N": m.hidden_size, "K": down_k[tile_id]},
                produces=downproj_name, consumes=[f"FFNIntermediate_tile{tile_id}"],
            ))

        tp_bytes = m.seq_len * m.hidden_size * m.dtype_bytes
        program.add_tensor(TensorHandle(
            name=outproj_name, size_bytes=tp_bytes,
            producers=list(range(num_tiles)), consumers=list(range(num_tiles)),
            reduction="ring_allreduce", scope="tp_global",
        ))
        program.add_tensor(TensorHandle(
            name=downproj_name, size_bytes=tp_bytes,
            producers=list(range(num_tiles)), consumers=list(range(num_tiles)),
            reduction="ring_allreduce", scope="tp_global",
        ))