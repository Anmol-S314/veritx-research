"""Contract tests for the workload→memory resolver (Phase 14b).

Strict locations, explicit attribution, conservation by construction.
No Ramulator, no CLI.
"""
import sys
from pathlib import Path

import pytest

DSE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(DSE))

from veritx_dse.core.memory import AddressMappingPolicy
from veritx_dse.workload.canonical import (
    Parallelism, WorkloadArtifact, build_collective_op, build_compute_op)
from veritx_dse.workload.lowering import LoweringError, UnsupportedSemantic
from veritx_dse.workload.memory_lowering import (
    DEFAULT_POLICY, RESOLVER_ID, MemorySystemDesign, ResolvedMemory,
    resolve_memory,
)

DESIGN = MemorySystemDesign(hbm_devices=(0,))


def _op(op_id, **kw):
    d = {"duration_ns": 100, "input_bytes": 1024, "weight_bytes": 8192,
         "output_bytes": 512}
    d.update(kw)
    return build_compute_op(op_id, **d)


def _workload(ops, num_participants=2):
    return WorkloadArtifact(
        workload_id="w", source_kind="test", parallelism=Parallelism(),
        num_participants=num_participants, ops=tuple(ops))


def _resolve(ops, design=DESIGN, num_participants=2, **kw):
    kw.setdefault("issue_node", 0)
    return resolve_memory(_workload(ops, num_participants), design, **kw)


# ── happy path ──────────────────────────────────────────────────────────

class TestResolve:
    def test_regions_accesses_and_totals(self):
        res = _resolve([_op("op0"), _op("op1")])
        art = res.artifact
        assert sorted(r.region_id for r in art.regions) == [
            "op0.input", "op0.output", "op0.weight",
            "op1.input", "op1.output", "op1.weight"]
        assert sorted(a.access_id for a in art.accesses) == [
            f"acc.{r}" for r in sorted(("op0.input", "op0.output",
                                        "op0.weight", "op1.input",
                                        "op1.output", "op1.weight"))]
        kinds = {a.access_id: a.kind for a in art.accesses}
        assert kinds["acc.op0.input"] == "READ"
        assert kinds["acc.op0.weight"] == "READ"
        assert kinds["acc.op0.output"] == "WRITE"
        assert res.workload_operand_bytes == 2 * (1024 + 8192 + 512) == 19456
        assert res.conserved()
        assert art.source_workload_hash.startswith("sha256:")

    def test_object_classes_fixed_no_inference(self):
        res = _resolve([_op("op0")])
        by_id = {r.region_id: r.object_type for r in res.artifact.regions}
        assert by_id == {"op0.input": "ACTIVATION",
                         "op0.weight": "WEIGHT",
                         "op0.output": "OUTPUT"}

    def test_stream_order_and_dependencies(self):
        res = _resolve([_op("op0"), _op("op1")])
        order = [a.access_id for a in res.artifact.accesses]
        assert order == ["acc.op0.input", "acc.op0.weight",
                         "acc.op0.output", "acc.op1.input",
                         "acc.op1.weight", "acc.op1.output"]
        deps = {a.access_id: list(a.dependencies)
                for a in res.artifact.accesses}
        # write after its op's reads; op1 chains after op0's tail
        assert deps["acc.op0.output"] == ["acc.op0.input",
                                          "acc.op0.weight"]
        assert deps["acc.op1.input"] == ["acc.op0.output"]
        assert deps["acc.op0.input"] == []

    def test_comm_ops_contribute_no_regions(self):
        coll = build_collective_op("c0", "ALLREDUCE", bytes=4096,
                                   participants=(0, 1), scope=[True, False])
        res = _resolve([_op("op0"), coll])
        assert len(res.artifact.regions) == 3
        assert res.conserved()

    def test_zero_and_none_operands_skipped(self):
        res = _resolve([_op("op0", input_bytes=0, weight_bytes=None)])
        assert [r.region_id for r in res.artifact.regions] == ["op0.output"]
        assert res.workload_operand_bytes == 512
        assert res.conserved()

    def test_deterministic(self):
        # Same input → same hash, resolved twice.
        a = _resolve([_op("op0"), _op("op1")]).artifact.artifact_hash
        c = _resolve([_op("op0"), _op("op1")]).artifact.artifact_hash
        assert a == c

    def test_workload_order_is_identity(self):
        # Workload op order is execution order (positional chaining), so a
        # reordered workload resolves to a DIFFERENT artifact — order must
        # not silently canonicalize away.
        a = _resolve([_op("op0"), _op("op1")]).artifact.artifact_hash
        b = _resolve([_op("op1"), _op("op0")]).artifact.artifact_hash
        assert a != b

    def test_roundtrip(self):
        from veritx_dse.core.memory import MemoryArtifact
        art = _resolve([_op("op0")]).artifact
        assert MemoryArtifact.from_dict(art.to_dict()).artifact_hash == \
            art.artifact_hash

    def test_assumptions_recorded(self):
        art = _resolve([_op("op0")]).artifact
        assert art.assumptions[0] == f"resolver:{RESOLVER_ID}"
        assert any("op-scoped" in a for a in art.assumptions)
        assert any("issue-node" in a for a in art.assumptions)

    def test_empty_memory_demand_refused(self):
        coll = build_collective_op("c0", "ALLREDUCE", bytes=64,
                                   participants=(0, 1), scope=[True, False])
        with pytest.raises(LoweringError):
            _resolve([coll])


# ── strict locations ────────────────────────────────────────────────────

class TestLocations:
    def test_remote_refused(self):
        with pytest.raises(UnsupportedSemantic, match="REMOTE"):
            _resolve([_op("op0", input_loc="REMOTE:1")])

    def test_cxl_refused(self):
        with pytest.raises(UnsupportedSemantic, match="CXL"):
            _resolve([_op("op0", weight_loc="CXL:0")])

    def test_storage_refused(self):
        with pytest.raises(UnsupportedSemantic, match="STORAGE"):
            _resolve([_op("op0", output_loc="STORAGE")])

    def test_local_wrong_device_refused(self):
        with pytest.raises(UnsupportedSemantic):
            _resolve([_op("op0", input_loc="LOCAL:7")])

    def test_refusal_is_atomic(self):
        # The good op's regions must not escape inside a partial artifact:
        # resolve either returns conserved output or raises.
        with pytest.raises(UnsupportedSemantic):
            _resolve([_op("op0"), _op("op1", weight_loc="REMOTE:0")])


# ── attribution ─────────────────────────────────────────────────────────

class TestAttribution:
    def test_ambiguous_attribution_refused(self):
        wl = _workload([_op("op0")], num_participants=4)
        with pytest.raises(LoweringError, match="issue_node"):
            resolve_memory(wl, DESIGN)

    def test_single_participant_defaults_to_node_0(self):
        wl = _workload([_op("op0")], num_participants=1)
        res = resolve_memory(wl, DESIGN)
        assert {a.source_node for a in res.artifact.accesses} == {0}
        assert not any("issue-node" in a
                       for a in res.artifact.assumptions)

    def test_int_node_out_of_range_refused(self):
        with pytest.raises(LoweringError):
            _resolve([_op("op0")], issue_node=2)

    def test_explicit_map(self):
        res = _resolve([_op("op0"), _op("op1")],
                       issue_node={"op0": 0, "op1": 1})
        nodes = {a.access_id: a.source_node
                 for a in res.artifact.accesses}
        assert nodes["acc.op0.input"] == 0
        assert nodes["acc.op1.input"] == 1

    def test_map_missing_and_extra_refused(self):
        with pytest.raises(LoweringError):
            _resolve([_op("op0"), _op("op1")], issue_node={"op0": 0})
        with pytest.raises(LoweringError):
            _resolve([_op("op0")], issue_node={"op0": 0, "ghost": 1})


# ── real workload path (Path B serving rows → canonical → memory) ──────

class TestRealWorkloadPath:
    def _serving_workload(self):
        from veritx_dse.workload.canonical import (
            Parallelism, artifact_from_trace_rows)
        rows = [
            ("attention", "1000", "LOCAL", "2048", "LOCAL", "4096",
             "LOCAL", "2048", "ALLREDUCE:1,0", "2048", "BATCH_1"),
            ("mlp", "700", "LOCAL", "512", "LOCAL", "1024",
             "LOCAL", "512", "NONE", "0", "BATCH_1"),
        ]
        return artifact_from_trace_rows(
            rows, workload_id="serve-test", parallelism=Parallelism(),
            num_participants=2)

    def test_trace_rows_resolve_conserved(self):
        wl = self._serving_workload()
        res = resolve_memory(wl, DESIGN, issue_node=1)
        # attention(2048+4096+2048) + mlp(512+1024+512) = 10240
        assert res.workload_operand_bytes == 10240
        assert res.conserved()
        assert len(res.artifact.regions) == 6
        assert len(res.artifact.accesses) == 6
        assert res.artifact.source_workload_hash == wl.artifact_hash
        assert {a.source_node for a in res.artifact.accesses} == {1}
        # The co-located ALLREDUCE is fabric traffic: regions trace only
        # to the two COMPUTE ops (canonical ids comp-0/comp-2 — the
        # collective consumes coll-1 in the sequence).
        assert {r.source_op_id for r in res.artifact.regions} == \
            {"comp-0", "comp-2"}

class TestDesign:
    def test_empty_design_refused(self):
        with pytest.raises(LoweringError):
            MemorySystemDesign(hbm_devices=())

    def test_multi_hbm_refused(self):
        with pytest.raises(UnsupportedSemantic, match="sharding"):
            MemorySystemDesign(hbm_devices=(0, 1))

    def test_custom_policy_flows_into_identity(self):
        policy = AddressMappingPolicy(name="contiguous_aligned_v1",
                                      version=1, alignment_bytes=4096,
                                      parameters={})
        res = _resolve([_op("op0")], policy=policy)
        assert res.artifact.mapping_policy.alignment_bytes == 4096
        assert res.conserved()


class TestMemorySeamMigrationFixture:
    """The workload -> memory seam, pinned for the 2c migration.

    This IS the integration seam (strengthened, not duplicated). It drives
    real serving rows -> canonical workload -> resolve_memory and pins the
    values 2c must preserve. Identity law for the migration:

        region_table_hash    MUST NOT MOVE  (pure memory semantics)
        access_stream_hash   MUST NOT MOVE  (pure memory semantics)
        regions/accesses/ordering/deps/source_node   MUST NOT MOVE
        Ramulator trace_sha256                       MUST NOT MOVE

        source_workload_hash MAY MOVE (its authenticated parent workload
        artifact_hash   identity becomes the canonical-v2 identity)
        MemoryArtifact.artifact_hash  MAY MOVE for the same reason
        manifest source_memory_artifact_hash MAY MOVE

    Do NOT "preserve" a top-level hash by smuggling legacy identity into
    the new graph. Semantic continuity with honest new ancestry, not hash
    cosplay.
    """

    ROWS = [
        ("attention", "1000", "LOCAL", "2048", "LOCAL", "4096", "LOCAL",
         "2048", "ALLREDUCE:1,0", "2048", "BATCH_1"),
        ("mlp", "700", "LOCAL", "512", "LOCAL", "1024", "LOCAL", "512",
         "NONE", "0", "BATCH_1"),
    ]

    # captured from the CURRENT legacy implementation (migration evidence)
    REGION_TABLE_HASH = ("sha256:2091447e2f21aa7140f580ee8d0fe1d328697b9d"
                         "c11adcfe3cbeeec3c5c53266")
    ACCESS_STREAM_HASH = ("sha256:a2037d772e0a975917e3f588af8e939c70c7cc98"
                          "e0fbd6317eac9d981e0f1690")
    TRACE_SHA256 = ("sha256:001e5970f648080089983d2478f427f12b6eed743b65"
                    "6a77d7ec747b87abddc8")
    REGIONS = [
        ("comp-0.input", "ACTIVATION", 2048, 0, "HBM", "comp-0"),
        ("comp-0.output", "OUTPUT", 2048, 2048, "HBM", "comp-0"),
        ("comp-0.weight", "WEIGHT", 4096, 4096, "HBM", "comp-0"),
        ("comp-2.input", "ACTIVATION", 512, 8192, "HBM", "comp-2"),
        ("comp-2.output", "OUTPUT", 512, 8704, "HBM", "comp-2"),
        ("comp-2.weight", "WEIGHT", 1024, 9216, "HBM", "comp-2"),
    ]
    ACCESSES = [
        ("acc.comp-0.input", "comp-0.input", "READ", 2048, 1, ()),
        ("acc.comp-0.weight", "comp-0.weight", "READ", 4096, 1, ()),
        ("acc.comp-0.output", "comp-0.output", "WRITE", 2048, 1,
         ("acc.comp-0.input", "acc.comp-0.weight")),
        ("acc.comp-2.input", "comp-2.input", "READ", 512, 1,
         ("acc.comp-0.output",)),
        ("acc.comp-2.weight", "comp-2.weight", "READ", 1024, 1, ()),
        ("acc.comp-2.output", "comp-2.output", "WRITE", 512, 1,
         ("acc.comp-2.input", "acc.comp-2.weight")),
    ]

    def _resolved(self, *, issue_node=1, num_participants=2,
                  parallelism=None):
        from veritx_dse.workload.canonical import (
            Parallelism, artifact_from_trace_rows)
        wl = artifact_from_trace_rows(
            self.ROWS, workload_id="serve-test",
            parallelism=parallelism or Parallelism(),
            num_participants=num_participants)
        return wl, resolve_memory(wl, DESIGN, issue_node=issue_node)

    def test_regions_and_placements_are_pinned(self):
        _wl, res = self._resolved()
        got = [(r.region_id, r.object_type, r.size_bytes, r.base_address,
                r.placement.tier, r.source_op_id)
               for r in res.artifact.regions]
        assert got == self.REGIONS

    def test_access_stream_order_classification_and_deps_are_pinned(self):
        _wl, res = self._resolved()
        got = [(a.access_id, a.region_id, a.kind, a.size_bytes,
                a.source_node, a.dependencies)
               for a in res.artifact.accesses]
        assert got == self.ACCESSES

    def test_memory_semantic_hashes_must_not_move(self):
        """These are the seam invariants that survive 2c."""
        _wl, res = self._resolved()
        assert res.artifact.region_table_hash == self.REGION_TABLE_HASH
        assert res.artifact.access_stream_hash == self.ACCESS_STREAM_HASH

    def test_logical_bytes_and_attribution_are_pinned(self):
        _wl, res = self._resolved()
        assert res.workload_operand_bytes == 10240
        assert (res.region_bytes, res.read_bytes, res.write_bytes) == \
            (10240, 7680, 2560)
        assert {a.source_node for a in res.artifact.accesses} == {1}
        assert res.conserved()

    def test_ramulator_trace_bytes_must_not_move(self):
        """The trace is the backend input: byte identity is required."""
        import tempfile
        from pathlib import Path
        from veritx_dse.workload.memory_lowering import (
            hbm3_16gb_8hi_geometry, lower_to_ramulator_trace)
        _wl, res = self._resolved()
        with tempfile.TemporaryDirectory() as tmp:
            man = lower_to_ramulator_trace(
                res.artifact, hbm3_16gb_8hi_geometry(num_channels=1),
                out_path=Path(tmp) / "t.trace")
        assert man.to_dict()["trace_sha256"] == self.TRACE_SHA256

    def test_identity_may_move_but_is_derived_from_its_parent(self):
        """Documented, not hidden: these MAY change across 2c.

        Asserted as a RELATION (the parent hash is the workload's) rather
        than a frozen value, so the migration is free to move both
        together while any silent ancestry break still fails.
        """
        wl, res = self._resolved()
        assert res.artifact.source_workload_hash == wl.artifact_hash
        assert res.artifact.artifact_hash.startswith("sha256:")

    def test_memory_num_nodes_uses_participant_count_not_world_size(self):
        """The D ruling: never derive num_nodes from parallelism geometry.

        Two instances, tp=4: world_size = 8, participant_count = 4. The
        MemoryArtifact must use the PARTICIPANT namespace (4).
        """
        from veritx_dse.workload.canonical import (Parallelism,
                                                   build_compute_op,
                                                   WorkloadArtifact)
        para = Parallelism(tp=4, dp=2)
        world = para.tp * para.pp * para.ep * para.dp
        wl = WorkloadArtifact(
            workload_id="m", source_kind="test", parallelism=para,
            num_participants=4,
            ops=(build_compute_op("c0", 10, input_bytes=64),))
        res = resolve_memory(wl, DESIGN, issue_node=0)
        assert world == 8
        assert wl.num_participants == 4
        assert res.artifact.num_nodes == wl.num_participants
        assert res.artifact.num_nodes != world
