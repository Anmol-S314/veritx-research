"""Phase 9 — canonical workload semantics (WorkloadArtifact).

Seam-level tests only: the artifact constructor/serializer, the trace-rows
canonicalizer, and the conservation checker. No backend internals mocked.
Fail-closed rules (PR C lineage) are pinned with diagnostics, not booleans.
"""
import json
import pytest

from veritx_dse.workload.canonical import (
    ALL_DIMENSIONS,
    WorkloadError,
    WorkloadArtifact,
    WorkloadOp,
    Parallelism,
    build_compute_op,
    build_collective_op,
    build_p2p_op,
    build_broadcast_op,
    build_expert_begin_op,
    artifact_from_trace_rows,
    check_conservation,
)
from veritx_dse.workload.lowering import (
    rows_from_artifact,
    lower_to_et,
    build_lowering_manifest,
    et_readback_conservation,
    LoweringError,
    UnsupportedSemantic,
)


# ── helpers ──────────────────────────────────────────────────────────────

def _para(**kw):
    base = dict(tp=2, dp=1, ep=2, pp=1)
    base.update(kw)
    return Parallelism(**base)


def _comm_ops():
    """Minimal two-op workload: a scoped TP allreduce + a compute."""
    return [
        build_collective_op(
            "coll-0", "ALLREDUCE", bytes=2048, participants=(0, 1),
            scope=[True, False]),
        build_compute_op("comp-0", duration_ns=100),
    ]


# ── construction / identity ──────────────────────────────────────────────

class TestConstruction:
    def test_valid_artifact_builds(self):
        art = WorkloadArtifact(
            workload_id="golden-a-batch0",
            source_kind="llmservingsim",
            parallelism=_para(),
            num_participants=2,
            ops=_comm_ops(),
        )
        assert art.schema_version == 1
        assert art.artifact_hash  # computed, non-empty

    def test_roundtrip_preserves_identity(self):
        art = WorkloadArtifact(
            workload_id="w", source_kind="llmservingsim",
            parallelism=_para(), num_participants=2, ops=_comm_ops())
        d = art.serialize()
        art2 = WorkloadArtifact.from_dict(d)
        assert art2.artifact_hash == art.artifact_hash
        assert art2 == art

    def test_empty_operations_rejected(self):
        with pytest.raises(WorkloadError, match="no operations"):
            WorkloadArtifact(
                workload_id="w", source_kind="synthetic",
                parallelism=_para(), num_participants=2, ops=[])


class TestHashing:
    def _art(self, **over):
        ops = over.pop("ops", None) or _comm_ops()
        return WorkloadArtifact(
            workload_id="w", source_kind="llmservingsim",
            parallelism=over.pop("parallelism", _para()),
            num_participants=2, ops=ops)

    def test_same_semantics_same_hash(self):
        a = self._art()
        b = WorkloadArtifact.from_dict(a.serialize())
        assert a.artifact_hash == b.artifact_hash

    def test_label_is_presentation_not_identity(self):
        def _mk(label):
            return [build_collective_op(
                "coll-0", "ALLREDUCE", bytes=2048, participants=(0, 1),
                scope=[True, False], label=label),
                build_compute_op("comp-0", duration_ns=100)]
        a = self._art(ops=_mk("o_proj TP allreduce"))
        b = self._art(ops=_mk(""))  # identical except label
        assert a.artifact_hash == b.artifact_hash

    def test_label_roundtrips_as_sidecar_never_identity(self):
        # §16 + lowering contract: labels ride in the serialized artifact
        # (ET node names are source layer labels — byte-faithful backend
        # lowering needs them) but are stripped from identity, so the
        # content hash ignores them entirely.
        def _mk(label):
            return [build_collective_op(
                "coll-0", "ALLREDUCE", bytes=2048, participants=(0, 1),
                scope=[True, False], label=label),
                build_compute_op("comp-0", duration_ns=100, label=label)]
        a = self._art(ops=_mk("embedding_0"))
        b = self._art(ops=_mk("o_proj"))
        assert a.artifact_hash == b.artifact_hash  # identity ignores labels
        ra = WorkloadArtifact.from_dict(a.serialize())
        assert [op.label for op in ra.ops] == ["embedding_0", "embedding_0"]
        assert ra.artifact_hash == a.artifact_hash  # sidecar didn't re-hash

    def test_memory_locations_are_identity(self):
        # tensor_loc/tensor_device drive ASTRA's issue_remote_mem — a
        # REMOTE↔LOCAL change alters memory-side timing, so locations are
        # semantic and MUST change the hash (§16: semantic change ⇒
        # identity change).
        a = self._art(ops=[build_compute_op(
            "comp-0", duration_ns=100, input_bytes=40,
            input_loc="REMOTE:0")])
        b = self._art(ops=[build_compute_op(
            "comp-0", duration_ns=100, input_bytes=40)])
        assert a.artifact_hash != b.artifact_hash
        ra = WorkloadArtifact.from_dict(a.serialize())
        assert ra.ops[0].input_loc == "REMOTE:0"  # roundtrips

    def test_participant_change_changes_hash(self):
        a = self._art()
        ops = [build_collective_op(
            "coll-0", "ALLREDUCE", bytes=2048, participants=(1, 0),
            scope=[True, False]),
            build_compute_op("comp-0", duration_ns=100)]
        assert self._art(ops=ops).artifact_hash != a.artifact_hash

    def test_size_change_changes_hash(self):
        a = self._art()
        ops = [build_collective_op(
            "coll-0", "ALLREDUCE", bytes=4096, participants=(0, 1),
            scope=[True, False]),
            build_compute_op("comp-0", duration_ns=100)]
        assert self._art(ops=ops).artifact_hash != a.artifact_hash

    def test_ordering_is_semantic(self):
        a = self._art()
        assert self._art(ops=list(reversed(_comm_ops()))).artifact_hash \
            != a.artifact_hash

    def test_all_dims_distinct_from_explicit_full(self):
        """§7 ruling: intentional ALL != explicit [True, True]."""
        one = build_collective_op("c", "ALLREDUCE", bytes=64,
                                  participants=(0, 1), scope=ALL_DIMENSIONS)
        other = build_collective_op("c", "ALLREDUCE", bytes=64,
                                    participants=(0, 1), scope=[True, True])
        assert one.scope != other.scope


# ── fail-closed validation (PR C lineage) ────────────────────────────────

class TestFailClosed:
    def test_unknown_kind_refused(self):
        d = WorkloadArtifact(
            workload_id="w", source_kind="synthetic",
            parallelism=_para(), num_participants=2, ops=_comm_ops()
        ).serialize()
        d["ops"][0]["kind"] = "ALLTOALLV"  # not a supported semantic
        with pytest.raises(WorkloadError, match="ALLTOALLV"):
            WorkloadArtifact.from_dict(d)

    def test_out_of_range_rank_refused(self):
        with pytest.raises(WorkloadError, match="out of range"):
            WorkloadArtifact(
                workload_id="w", source_kind="synthetic",
                parallelism=_para(), num_participants=2,
                ops=[build_collective_op(
                    "c", "ALLREDUCE", bytes=64, participants=(0, 5),
                    scope=ALL_DIMENSIONS)])

    def test_degenerate_collective_refused(self):
        with pytest.raises(WorkloadError, match="needs >= 2"):
            WorkloadArtifact(
                workload_id="w", source_kind="synthetic",
                parallelism=_para(), num_participants=2,
                ops=[build_collective_op(
                    "c", "ALLREDUCE", bytes=64, participants=(0,),
                    scope=ALL_DIMENSIONS)])

    def test_p2p_needs_exact_pair(self):
        with pytest.raises(WorkloadError, match="src/dst"):
            build_p2p_op("s", "SEND", bytes=64)  # no endpoints

    def test_zero_byte_collective_refused(self):
        with pytest.raises(WorkloadError, match="positive integer"):
            build_collective_op("c", "ALLREDUCE", bytes=0,
                                participants=(0, 1), scope=ALL_DIMENSIONS)

    def test_compute_cannot_carry_bytes(self):
        with pytest.raises(WorkloadError, match="bytes"):
            build_compute_op("c", duration_ns=10, bytes=5)

    def test_duplicate_op_id_refused(self):
        with pytest.raises(WorkloadError, match="duplicate"):
            WorkloadArtifact(
                workload_id="w", source_kind="synthetic",
                parallelism=_para(), num_participants=2,
                ops=_comm_ops() + [build_compute_op("comp-0",
                                                    duration_ns=1)])


class TestSchemaExtensions:
    """Memory sizes and MoE structure are audited backend-consumed
    semantics (the converter branches on them) — they must survive
    canonicalization for the artifact to be a true parent."""

    def test_memory_fields_roundtrip_and_hash(self):
        op = build_compute_op("c", duration_ns=100, input_bytes=2048,
                              weight_bytes=4096, output_bytes=2048)
        rt = WorkloadOp.from_dict(op.to_dict())
        assert rt.input_bytes == 2048 and rt.weight_bytes == 4096
        a = WorkloadArtifact(
            workload_id="w", source_kind="synthetic",
            parallelism=_para(), num_participants=1, ops=[op])
        b = WorkloadArtifact(
            workload_id="w", source_kind="synthetic",
            parallelism=_para(), num_participants=1,
            ops=[build_compute_op("c", duration_ns=100)])
        assert a.artifact_hash != b.artifact_hash

    def test_expert_marker_roundtrip(self):
        op = build_expert_begin_op(0, comm_kind="ALLGATHER", bytes=4096,
                                   participants=(0, 1), scope=[True, False])
        rt = WorkloadOp.from_dict(op.to_dict())
        assert rt.kind == "EXPERT_BEGIN"
        assert rt.comm_kind == "ALLGATHER" and rt.bytes == 4096
        assert rt.scope == [True, False]

    def test_pp_stage_boundaries_fails_closed(self):
        rows = [_layer_row("mlp", 700, 512, 1024, 512)]
        with pytest.raises(WorkloadError, match="pp_stage_boundaries"):
            artifact_from_trace_rows(
                rows, workload_id="w", parallelism=_para(pp=2),
                num_participants=2, has_pp_stage_boundaries=True)




# ── BROADCAST ruling (§6: Case B — source explicit, not positional) ─────

class TestBroadcastRuling:
    def test_source_required(self):
        with pytest.raises(WorkloadError, match="source"):
            build_broadcast_op("b", bytes=512, participants=(0, 1, 2))

    def test_explicit_source_preserved(self):
        op = build_broadcast_op("b", bytes=512, participants=(1, 0, 2),
                                source=1)
        assert op.src == 1
        art = WorkloadArtifact(
            workload_id="w", source_kind="synthetic",
            parallelism=_para(tp=1), num_participants=3, ops=[op])
        rt = WorkloadArtifact.from_dict(art.serialize())
        assert rt.ops[0].src == 1
        assert rt.ops[0].participants == (1, 0, 2)

    def test_source_must_be_participant(self):
        with pytest.raises(WorkloadError, match="participant"):
            build_broadcast_op("b", bytes=512, participants=(0, 1, 2),
                               source=9)


# ── dimensional scope (§7) ───────────────────────────────────────────────

class TestScope:
    def test_explicit_scope_roundtrips(self):
        op = build_collective_op("c", "ALLTOALL", bytes=128,
                                 participants=(0, 1),
                                 scope=[True, False])
        rt = WorkloadArtifact.from_dict(WorkloadArtifact(
            workload_id="w", source_kind="synthetic",
            parallelism=_para(), num_participants=2, ops=[op]).serialize())
        assert rt.ops[0].scope == [True, False]

    def test_all_dimensions_sentinel_distinct_from_absent(self):
        """Missing scope is a construction error for comm ops; the sentinel
        is an explicit value. They are not interchangeable."""
        with pytest.raises(WorkloadError, match="scope"):
            build_collective_op("c", "ALLREDUCE", bytes=64,
                                participants=(0, 1), scope=None)


# ── canonicalization from real trace rows (Path B grammar) ──────────────

def _layer_row(name, comp_ns, inp, wt, out, comm="NONE", size=0,
               tag="BATCH_1", inp_loc="LOCAL", wt_loc="LOCAL",
               out_loc="LOCAL"):
    return (name, str(comp_ns), inp_loc, str(inp), wt_loc, str(wt),
            out_loc, str(out), comm, str(size), tag)


class TestFromTraceRows:
    def test_dense_layer_with_scoped_allreduce(self):
        rows = [
            _layer_row("attention", 1000, 2048, 4096, 2048,
                       comm="ALLREDUCE:1,0", size=2048),
            _layer_row("o_proj", 500, 1024, 2048, 1024),
        ]
        art = artifact_from_trace_rows(
            rows, workload_id="inst0-batch1",
            parallelism=_para(tp=2), num_participants=2)
        kinds = [op.kind for op in art.ops]
        # per layer: compute + (comm when declared)
        assert kinds == ["COMPUTE", "ALLREDUCE", "COMPUTE"]
        coll = art.ops[1]
        assert coll.bytes == 2048
        assert coll.scope == [True, False]
        assert coll.participants == (0, 1)

    def test_none_comm_zero_size_is_compute_only(self):
        rows = [_layer_row("mlp", 700, 512, 1024, 512)]
        art = artifact_from_trace_rows(
            rows, workload_id="w", parallelism=_para(tp=1),
            num_participants=1)
        assert [op.kind for op in art.ops] == ["COMPUTE"]
        assert art.ops[0].duration_ns == 700

    def test_unknown_comm_type_fails_closed(self):
        rows = [_layer_row("x", 100, 1, 1, 1, comm="ALLTOALLV:1,0",
                           size=64)]
        with pytest.raises(WorkloadError, match="ALLTOALLV"):
            artifact_from_trace_rows(
                rows, workload_id="w", parallelism=_para(),
                num_participants=2)

    def test_marker_row_expert_dispatch(self):
        rows = [
            ("EXPERT 0 ALLGATHER:1,0 4096",),
            _layer_row("mlp.expert", 300, 128, 256, 128),
            ("EXPERT END REDUCESCATTER:1,0 4096",),
        ]
        art = artifact_from_trace_rows(
            rows, workload_id="w", parallelism=_para(),
            num_participants=2)
        kinds = [op.kind for op in art.ops]
        # MoE structure is canonical: EXPERT markers carry the
        # dispatch/combine collectives (§18: structural semantics
        # survive canonicalization)
        assert kinds == ["EXPERT_BEGIN", "COMPUTE", "EXPERT_END"]
        assert art.ops[0].comm_kind == "ALLGATHER"
        assert art.ops[0].bytes == 4096
        assert art.ops[0].scope == [True, False]
        assert art.ops[2].comm_kind == "REDUCESCATTER"

    def test_source_row_locations_captured_verbatim(self):
        # Real generator rows carry REMOTE:<dev> on first/last layers (the
        # Chakra MEM_LOAD/MEM_STORE contract). Canonicalization must keep
        # them — dropping them was the byte-parity bug this cycle fixed.
        rows = [
            _layer_row("embedding", 5323, 40, 622329856, 40960,
                       inp_loc="REMOTE:0", wt_loc="LOCAL", out_loc="LOCAL"),
            _layer_row("sampler", 25933, 2565120, 0, 40,
                       inp_loc="LOCAL", wt_loc="LOCAL", out_loc="REMOTE:0"),
        ]
        art = artifact_from_trace_rows(
            rows, workload_id="w", parallelism=_para(),
            num_participants=2)
        comps = [op for op in art.ops if op.kind == "COMPUTE"]
        assert comps[0].input_loc == "REMOTE:0"
        assert comps[0].weight_loc == "LOCAL"
        assert comps[1].output_loc == "REMOTE:0"


# ── conservation invariants (§13) ────────────────────────────────────────

class TestConservation:
    def test_lowered_logical_ops_must_match(self):
        src = WorkloadArtifact(
            workload_id="w", source_kind="synthetic",
            parallelism=_para(), num_participants=2, ops=_comm_ops())
        lowered = [("coll-0", "ALLREDUCE", 2048, (0, 1), [True, False]),
                   ("comp-0", "COMPUTE", None, None, None)]
        check_conservation(src, lowered)  # must not raise

    def test_operation_count_mismatch_raises(self):
        src = WorkloadArtifact(
            workload_id="w", source_kind="synthetic",
            parallelism=_para(), num_participants=2, ops=_comm_ops())
        lowered = [("coll-0", "ALLREDUCE", 2048, (0, 1), [True, False])]
        with pytest.raises(Exception, match="COMPUTE"):
            check_conservation(src, lowered)

    def test_byte_volume_mismatch_raises(self):
        src = WorkloadArtifact(
            workload_id="w", source_kind="synthetic",
            parallelism=_para(), num_participants=2, ops=_comm_ops())
        lowered = [("coll-0", "ALLREDUCE", 1024, (0, 1), [True, False]),
                   ("comp-0", "COMPUTE", None, None, None)]
        with pytest.raises(Exception, match="bytes"):
            check_conservation(src, lowered)

    def test_participant_mismatch_raises(self):
        src = WorkloadArtifact(
            workload_id="w", source_kind="synthetic",
            parallelism=_para(), num_participants=2, ops=_comm_ops())
        lowered = [("coll-0", "ALLREDUCE", 2048, (0, 2), [True, False]),
                   ("comp-0", "COMPUTE", None, None, None)]
        with pytest.raises(Exception, match="participant"):
            check_conservation(src, lowered)


# ── lowering: the artifact is the parent (§11/§14/§20) ──────────────────

class TestRowsFromArtifact:
    def test_rows_reproduce_source_rows(self):
        rows = [
            _layer_row("attention", 1000, 2048, 4096, 2048,
                       comm="ALLREDUCE:1,0", size=2048),
            _layer_row("o_proj", 500, 1024, 2048, 1024),
        ]
        art = artifact_from_trace_rows(
            rows, workload_id="w", parallelism=_para(tp=2),
            num_participants=2)
        out = rows_from_artifact(art)
        assert out.rows == rows
        assert out.header_line.startswith("COLOCATED")

    def test_rows_from_synthetic_carry_semantic_content(self):
        art = WorkloadArtifact(
            workload_id="w", source_kind="synthetic",
            parallelism=_para(), num_participants=2, ops=_comm_ops())
        out = rows_from_artifact(art)
        # co-location: the ALLREDUCE rides the compute row's comm
        # columns (col 8 type, col 9 logical BYTES) — the dialect shape
        assert out.rows[0][8] == "ALLREDUCE:1,0"
        assert int(out.rows[0][9]) == 2048

    def test_expert_rows_roundtrip(self):
        rows = [
            ("EXPERT 0 ALLGATHER:1,0 4096",),
            _layer_row("mlp.expert", 300, 128, 256, 128),
            ("EXPERT END REDUCESCATTER:1,0 4096",),
        ]
        art = artifact_from_trace_rows(
            rows, workload_id="w", parallelism=_para(),
            num_participants=2)
        assert rows_from_artifact(art).rows == rows


class TestLowerToEt:
    """Sufficiency gate (reviewer's test): backend inputs regenerated from
    the artifact ALONE — never consulting the source rows — must equal the
    proven path's output byte for byte."""

    def test_et_regeneration_is_sufficient(self, tmp_path):
        rows = [
            _layer_row("attention", 1000, 2048, 4096, 2048,
                       comm="ALLREDUCE:1,0", size=2048),
            _layer_row("o_proj", 500, 1024, 2048, 1024),
        ]
        art = artifact_from_trace_rows(
            rows, workload_id="w", parallelism=_para(tp=2),
            num_participants=2)
        a = lower_to_et(art, rows_from_artifact(art).rows,
                        tmp_path / "a" / "llm", num_npus=2, num_npu_group=1)
        b = lower_to_et(art, rows, tmp_path / "b" / "llm",
                        num_npus=2, num_npu_group=1)
        assert a.et_count == 2
        assert a.et_sha256s == b.et_sha256s

    def test_pp_stage_boundaries_rejected_at_lowering(self, tmp_path):
        art = WorkloadArtifact(
            workload_id="w", source_kind="synthetic",
            parallelism=_para(pp=2), num_participants=2, ops=_comm_ops())
        rows = rows_from_artifact(art).rows
        with pytest.raises(LoweringError, match="pp_stage_boundaries"):
            lower_to_et(art, rows, tmp_path / "llm", num_npus=2,
                        num_npu_group=2, pp_stage_boundaries=[0, 1])


class TestLoweringManifest:
    def test_manifest_distinguishes_transformations_from_losses(
            self, tmp_path):
        rows = [
            _layer_row("attention", 1000, 2048, 4096, 2048,
                       comm="ALLREDUCE:1,0", size=2048),
            _layer_row("o_proj", 500, 1024, 2048, 1024),
        ]
        art = artifact_from_trace_rows(
            rows, workload_id="w", parallelism=_para(tp=2),
            num_participants=2)
        lowered = lower_to_et(art, rows_from_artifact(art).rows,
                              tmp_path / "llm", num_npus=2, num_npu_group=1)
        m = build_lowering_manifest(art, lowered, "astra_chakra_et")
        assert m.schema_version == 1
        assert m.source_workload_hash == art.artifact_hash
        assert m.semantic_losses == []
        assert m.transformations  # ns→cycles, BYTES→ET attrs: conserved
        assert m.op_counts == {"COMPUTE": 2, "ALLREDUCE": 1}
        assert m.participant_coverage == {0: 1, 1: 1}
        assert m.output_hashes["format"] == "chakra_et"

    def test_et_conservation_against_real_bytes(self, tmp_path):
        rows = [
            _layer_row("attention", 1000, 2048, 4096, 2048,
                       comm="ALLREDUCE:1,0", size=2048),
            _layer_row("o_proj", 500, 1024, 2048, 1024),
        ]
        art = artifact_from_trace_rows(
            rows, workload_id="w", parallelism=_para(tp=2),
            num_participants=2)
        lowered = lower_to_et(art, rows_from_artifact(art).rows,
                              tmp_path / "llm", num_npus=2, num_npu_group=1)
        got = et_readback_conservation(art, lowered.et_paths,
                                       num_npus=2, num_npu_group=1)
        assert got.logical_ops_conserved
        assert got.comm_bytes_conserved
        assert got.participants_conserved

    def test_broadcast_cannot_produce_zero_loss_et(self, tmp_path):
        """§18: an unsupported semantic cannot produce a zero-loss
        manifest — BROADCAST has no ET lowering until the converter
        learns bcast_root emission, so it must refuse."""
        op = build_broadcast_op("b", bytes=512, participants=(0, 1),
                                source=1)
        art = WorkloadArtifact(
            workload_id="w", source_kind="synthetic",
            parallelism=_para(tp=1), num_participants=2, ops=[op])
        with pytest.raises(UnsupportedSemantic, match="BROADCAST"):
            rows_from_artifact(art, target="astra_chakra_et")

    def test_broadcast_rows_carry_explicit_root_for_inspection(self):
        op = build_broadcast_op("b", bytes=512, participants=(0, 1),
                                source=1)
        art = WorkloadArtifact(
            workload_id="w", source_kind="synthetic",
            parallelism=_para(tp=1), num_participants=2, ops=[op])
        out = rows_from_artifact(art)  # inspection target: no ET claim
        assert out.root_by_row[0] == 1


# ── run integration: slice persists + comparison consumes (§14/§17) ─────

class TestRunIntegration:
    """canonicalize_run_workload: every saved trace in a run's inputs
    root becomes a workload artifact; the run's workload index carries
    canonical hashes that comparison fingerprints consume."""

    def _write_run(self, tmp_path):
        rows = [
            _layer_row("attention", 1000, 2048, 4096, 2048,
                       comm="ALLREDUCE:1,0", size=2048),
            _layer_row("o_proj", 500, 1024, 2048, 1024),
        ]
        trace_dir = tmp_path / "inputs" / "trace" / "RTXPRO6000" / "M"
        trace_dir.mkdir(parents=True)
        lines = ["COLOCATED\t\tmodel_parallel_NPU_group: 1", str(len(rows))]
        for i, r in enumerate(rows):
            lines.append(" ".join([f"{r[0]}_{i}", *r[1:]]))
        (trace_dir / "instance0_batch1.txt").write_text(
            "\n".join(lines) + "\n")
        cluster = {
            "num_nodes": 1,
            "nodes": [{"num_instances": 1, "instances": [
                {"model_name": "M", "hardware": "RTXPRO6000",
                 "num_npus": 2, "tp_size": 2, "pp_size": 1,
                 "ep_size": 2}]}],
        }
        cpath = tmp_path / "cluster.json"
        cpath.write_text(json.dumps(cluster))
        return tmp_path, cpath

    def test_canonicalize_run_writes_artifacts(self, tmp_path):
        from veritx_dse.workload.serve import canonicalize_run_workload
        run_root, cpath = self._write_run(tmp_path)
        index = canonicalize_run_workload(run_root, cpath)
        assert index["artifacts"], "no artifact produced"
        entry = index["artifacts"][0]
        assert entry["artifact_hash"].startswith("sha256:")
        assert entry["parallelism"]["tp"] == 2
        assert entry["parallelism"]["pp"] == 1
        art = WorkloadArtifact.from_dict(
            json.loads((run_root / "workload"
                        / f"{entry['name']}.workload.json").read_text()))
        assert art.artifact_hash == entry["artifact_hash"]

    def test_canonicalize_run_writes_workloadgraph(self, tmp_path):
        """M3: every trace also yields a verified WorkloadGraph doc."""
        from veritx_dse.workload.canonical_graph import WorkloadGraph
        from veritx_dse.workload.serve import (
            canonicalize_run_workload, workload_graph_identity,
        )
        run_root, cpath = self._write_run(tmp_path)
        index = canonicalize_run_workload(run_root, cpath)
        entry = index["artifacts"][0]
        assert entry["workload_graph_id"].startswith("sha256:")
        doc = json.loads((run_root / "workload"
                          / entry["workloadgraph_file"]).read_text())
        graph = WorkloadGraph.from_dict(doc, strict=True)
        assert graph.workload_id() == entry["workload_graph_id"]
        assert graph.participant_count == 2
        assert workload_graph_identity(index) == \
            entry["workload_graph_id"]

    def test_canonicalize_is_deterministic(self, tmp_path):
        from veritx_dse.workload.serve import canonicalize_run_workload
        run_root, cpath = self._write_run(tmp_path)
        i1 = canonicalize_run_workload(run_root, cpath)
        i2 = canonicalize_run_workload(run_root, cpath)
        assert i1 == i2

    def test_no_traces_is_an_error(self, tmp_path):
        from veritx_dse.workload.serve import canonicalize_run_workload
        run_root, cpath = self._write_run(tmp_path)
        import shutil
        shutil.rmtree(run_root / "inputs" / "trace")
        with pytest.raises(WorkloadError, match="no trace"):
            canonicalize_run_workload(run_root, cpath)

    def test_fingerprint_consumes_canonical_hash(self, tmp_path):
        from veritx_dse.workload.serve import canonicalize_run_workload
        from veritx_dse.core.comparison import fingerprint_from_run
        run_root, cpath = self._write_run(tmp_path)
        index = canonicalize_run_workload(run_root, cpath)
        h = index["artifacts"][0]["artifact_hash"]
        # minimal run-dir shape fingerprint_from_run reads
        (run_root / "spec.resolved.json").write_text(json.dumps(
            {"serving": {"cluster": "c", "network_backend": "booksim"},
             "replication": {"mode": "deterministic"}}))
        (run_root / "manifest.json").write_text(json.dumps(
            {"run_id": run_root.name, "results": []}))
        fp = fingerprint_from_run(run_root)
        assert fp["workload_hash"] == h
        assert fp["workload_certified"] is True
