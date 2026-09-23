"""Contract tests for MemoryArtifact v1 (MEMORY-ROADMAP Phase 14a).

Schema + validation + hashing only: no Ramulator, no CLI, no resolver.
Every test maps to a Phase-14 gate checkbox.
"""
import sys
from pathlib import Path

import pytest

DSE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(DSE))

from veritx_dse.core.memory import (
    SCHEMA_VERSION,
    AddressMappingPolicy,
    MemoryAccess,
    MemoryArtifact,
    MemoryArtifactError,
    MemoryPlacement,
    MemoryRegion,
    allocate_regions,
    build_access,
    build_artifact,
    build_region,
)

WL_HASH = "sha256:" + "ab" * 32


def _hbm(device=0, stack=None):
    return MemoryPlacement(tier="HBM", device=device, stack=stack)


def _policy(**kw):
    d = {"name": "contiguous_aligned_v1", "version": 1,
         "alignment_bytes": 64, "parameters": {}}
    d.update(kw)
    return AddressMappingPolicy(**d)


def _region(rid="r.w", otype="WEIGHT", size=8192, base=0, source="op0",
            placement=None):
    return build_region(rid, otype, size, base,
                        placement or _hbm(), 64, source)


def _access(aid="a0", region="r.w", kind="READ", off=0, size=8192,
            node=0, deps=(), source="op0"):
    return build_access(aid, source, region, kind, off, size, node, deps)


def _artifact(**kw):
    d = {"name": "test", "source_workload_hash": WL_HASH, "num_nodes": 4,
         "regions": [_region()], "accesses": [_access()],
         "mapping_policy": _policy()}
    d.update(kw)
    return build_artifact(**d)


# ── schema / workload link ──────────────────────────────────────────────

class TestSchema:
    def test_schema_version_is_1(self):
        assert SCHEMA_VERSION == 1
        assert _artifact().schema_version == 1

    def test_source_workload_hash_mandatory(self):
        for bad in ("", "notahash", "md5:abc", None):
            with pytest.raises(MemoryArtifactError):
                _artifact(source_workload_hash=bad)

    def test_empty_regions_refused(self):
        with pytest.raises(MemoryArtifactError):
            _artifact(regions=[])

    def test_empty_accesses_allowed(self):
        # Placement-only artifact (demand placed, stream derived later) is
        # legal; accesses may arrive in a later revision. Demand with no
        # placed object is what refuses, not the reverse.
        art = _artifact(accesses=[])
        assert art.access_bytes_total() == 0


# ── typed placement ─────────────────────────────────────────────────────

class TestPlacement:
    def test_unknown_tier_refused(self):
        with pytest.raises(MemoryArtifactError):
            MemoryPlacement(tier="DDR5", device=0)

    def test_free_string_placement_refused(self):
        with pytest.raises(MemoryArtifactError):
            build_region("r", "WEIGHT", 64, 0, "HBM somewhere", 64, "op")

    def test_negative_device_or_stack_refused(self):
        with pytest.raises(MemoryArtifactError):
            MemoryPlacement(tier="HBM", device=-1)
        with pytest.raises(MemoryArtifactError):
            MemoryPlacement(tier="HBM", device=0, stack=-2)

    def test_stack_none_ok_explicit_stack_ok(self):
        assert _hbm(stack=None).stack is None
        assert _hbm(stack=2).stack == 2

    def test_placement_roundtrip(self):
        p = _hbm(device=1, stack=3)
        assert MemoryPlacement.from_dict(p.to_dict()) == p


# ── mapping policy ──────────────────────────────────────────────────────

class TestPolicy:
    def test_unknown_policy_refused(self):
        with pytest.raises(MemoryArtifactError):
            AddressMappingPolicy(name="random_addrs", version=1,
                                 alignment_bytes=64)

    def test_bad_version_and_alignment_refused(self):
        with pytest.raises(MemoryArtifactError):
            _policy(version=0)
        with pytest.raises(MemoryArtifactError):
            _policy(alignment_bytes=48)  # not a power of two
        with pytest.raises(MemoryArtifactError):
            _policy(alignment_bytes=0)

    def test_non_json_parameters_refused(self):
        with pytest.raises(MemoryArtifactError):
            _policy(parameters={"f": object()})

    def test_policy_change_changes_artifact_hash(self):
        a = _artifact()
        b = _artifact(mapping_policy=_policy(version=2))
        assert a.artifact_hash != b.artifact_hash


# ── deterministic allocation ────────────────────────────────────────────

class TestAllocation:
    def _specs(self):
        return [
            {"region_id": "b.weight", "object_type": "WEIGHT",
             "size_bytes": 8192, "placement": _hbm(), "source_op_id": "op1"},
            {"region_id": "a.input", "object_type": "ACTIVATION",
             "size_bytes": 1000, "placement": _hbm(), "source_op_id": "op0"},
        ]

    def test_input_order_irrelevant(self):
        fwd = allocate_regions(self._specs(), _policy())
        rev = allocate_regions(list(reversed(self._specs())), _policy())
        assert [(r.region_id, r.base_address) for r in fwd] == \
               [(r.region_id, r.base_address) for r in rev]

    def test_sorted_semantic_order_and_alignment(self):
        (a, b) = allocate_regions(self._specs(), _policy())
        assert (a.region_id, a.base_address) == ("a.input", 0)
        # 1000 aligned up to 64 → next base 1024
        assert (b.region_id, b.base_address) == ("b.weight", 1024)

    def test_repeatable(self):
        once = [(r.region_id, r.base_address)
                for r in allocate_regions(self._specs(), _policy())]
        twice = [(r.region_id, r.base_address)
                 for r in allocate_regions(self._specs(), _policy())]
        assert once == twice

    def test_duplicate_region_id_refused(self):
        specs = self._specs() + [dict(self._specs()[0])]
        with pytest.raises(MemoryArtifactError):
            allocate_regions(specs, _policy())

    def test_allocated_regions_build_clean_artifact(self):
        regions = allocate_regions(self._specs(), _policy())
        art = _artifact(regions=regions, accesses=[])
        assert art.region_bytes_total() == 9192


# ── region validation ───────────────────────────────────────────────────

class TestRegionValidation:
    def test_bad_sizes_refused(self):
        for bad in (-8, 0, 1.5, True, "64"):
            with pytest.raises(MemoryArtifactError):
                _region(size=bad)

    def test_unknown_object_type_refused(self):
        with pytest.raises(MemoryArtifactError):
            _region(otype="TENSOR_CORE")

    def test_other_allowed_without_inference(self):
        assert _region(otype="OTHER").object_type == "OTHER"

    def test_unaligned_base_refused(self):
        with pytest.raises(MemoryArtifactError):
            _region(base=32)  # alignment 64

    def test_empty_ids_refused(self):
        with pytest.raises(MemoryArtifactError):
            _region(rid="")
        with pytest.raises(MemoryArtifactError):
            _region(source="")

    def test_address_overflow_refused(self):
        with pytest.raises(MemoryArtifactError):
            _region(base=(1 << 64) - 8, size=64)

    def test_duplicate_region_ids_refused(self):
        with pytest.raises(MemoryArtifactError):
            _artifact(regions=[_region("r"), _region("r")])

    def test_overlap_same_scope_refused(self):
        with pytest.raises(MemoryArtifactError):
            _artifact(regions=[_region("a", base=0, size=1024),
                               _region("b", base=512, size=1024)])

    def test_same_addresses_different_scopes_allowed(self):
        art = _artifact(
            regions=[_region("a", base=0, size=1024),
                     _region("b", base=0, size=1024,
                             placement=_hbm(device=1))],
            accesses=[])
        assert art.region_bytes_total() == 2048


# ── access validation ───────────────────────────────────────────────────

class TestAccessValidation:
    def test_unknown_kind_refused(self):
        with pytest.raises(MemoryArtifactError):
            _access(kind="RMW")

    def test_zero_size_and_negative_fields_refused(self):
        with pytest.raises(MemoryArtifactError):
            _access(size=0)
        with pytest.raises(MemoryArtifactError):
            _access(off=-1)
        with pytest.raises(MemoryArtifactError):
            _access(node=-1)

    def test_unknown_region_refused(self):
        with pytest.raises(MemoryArtifactError):
            _artifact(accesses=[_access(region="nope")])

    def test_out_of_bounds_refused_never_clamped(self):
        with pytest.raises(MemoryArtifactError):
            _artifact(accesses=[_access(off=8000, size=512)])  # 8512 > 8192

    def test_edge_exact_fit_allowed(self):
        art = _artifact(accesses=[_access(off=8092, size=100)])
        assert art.access_bytes_total() == 100

    def test_source_node_range(self):
        with pytest.raises(MemoryArtifactError):
            _artifact(accesses=[_access(node=4)])  # num_nodes=4
        _artifact(accesses=[_access(node=3)])

    def test_duplicate_access_ids_refused(self):
        with pytest.raises(MemoryArtifactError):
            _artifact(accesses=[_access("a"), _access("a")])

    def test_self_dependency_refused(self):
        with pytest.raises(MemoryArtifactError):
            _access(aid="a", deps=("a",))

    def test_unknown_dependency_refused(self):
        with pytest.raises(MemoryArtifactError):
            _artifact(accesses=[_access(deps=("ghost",))])

    def test_dependency_cycle_refused(self):
        with pytest.raises(MemoryArtifactError):
            _artifact(accesses=[_access("a", deps=("b",)),
                                _access("b", deps=("a",))])

    def test_dependency_chain_allowed(self):
        art = _artifact(accesses=[_access("a"), _access("b", deps=("a",))])
        assert art.access_stream_hash.startswith("sha256:")

    def test_no_timing_fields_on_access(self):
        # Gate: no invented ready-cycle timing. The schema carries order
        # (dependencies), never issue cycles.
        assert set(_access().to_dict()) == {
            "access_id", "source_op_id", "region_id", "kind",
            "offset_bytes", "size_bytes", "source_node", "dependencies"}

    def test_no_backend_vectors_on_access(self):
        # Gate: no Ramulator channel/bank/row/col coordinates in canonical
        # accesses — the Phase-15 lowerer owns that mapping.
        blob = str(_access().to_dict())
        for banned in ("channel", "bank", "row", "column", "pseudo",
                       "stack_id", "sid"):
            assert banned not in blob


# ── hashing ─────────────────────────────────────────────────────────────

class TestHashing:
    def test_hashes_present_and_prefixed(self):
        art = _artifact()
        for h in (art.region_table_hash, art.access_stream_hash,
                  art.artifact_hash):
            assert h.startswith("sha256:")

    def test_deterministic_hashes(self):
        assert _artifact().artifact_hash == _artifact().artifact_hash

    def test_region_change_moves_region_and_artifact_hash_only(self):
        a = _artifact()
        b = _artifact(regions=[_region(size=4096)],
                      accesses=[_access(size=4096)])
        assert a.region_table_hash != b.region_table_hash
        assert a.access_stream_hash != b.access_stream_hash  # size covered
        assert a.artifact_hash != b.artifact_hash

    def test_access_reorder_moves_stream_hash_only(self):
        mk = lambda order: _artifact(
            regions=[_region("r1", size=64, base=0),
                     _region("r2", size=64, base=64)],
            accesses=[_access(f"a{i}", region=r, size=64)
                      for i, r in enumerate(order)])
        a = mk(["r1", "r2"])
        b = mk(["r2", "r1"])
        assert a.access_stream_hash != b.access_stream_hash
        assert a.region_table_hash == b.region_table_hash
        assert a.artifact_hash != b.artifact_hash

    def test_name_excluded_from_identity(self):
        a = _artifact(name="one")
        b = _artifact(name="two")
        assert a.artifact_hash == b.artifact_hash
        assert a.serialize()["name"] == "one"  # still roundtrips

    def test_roundtrip_preserves_hashes(self):
        art = _artifact()
        rt = MemoryArtifact.from_dict(art.to_dict())
        assert rt.artifact_hash == art.artifact_hash
        assert rt.region_table_hash == art.region_table_hash
        assert rt.access_stream_hash == art.access_stream_hash

    def test_tampered_region_detected(self):
        d = _artifact().to_dict()
        d["regions"][0]["size_bytes"] = 4096
        with pytest.raises(MemoryArtifactError):
            MemoryArtifact.from_dict(d)

    def test_tampered_access_detected(self):
        d = _artifact().to_dict()
        d["accesses"][0]["kind"] = "WRITE"
        with pytest.raises(MemoryArtifactError):
            MemoryArtifact.from_dict(d)

    def test_tampered_workload_link_detected(self):
        d = _artifact().to_dict()
        d["source_workload_hash"] = "sha256:" + "cd" * 32
        with pytest.raises(MemoryArtifactError):
            MemoryArtifact.from_dict(d)

    def test_schema_bump_refused(self):
        d = _artifact().to_dict()
        d["schema_version"] = 999
        with pytest.raises(MemoryArtifactError):
            MemoryArtifact.from_dict(d)


# ── workload conservation fixture ───────────────────────────────────────

class TestWorkloadConservation:
    """Gate: workload → memory-artifact byte conservation.

    Two COMPUTE ops with operand bytes; regions mirror each operand 1:1;
    placed bytes must equal workload operand bytes exactly, and full-region
    READ(truth)/WRITE(out) accesses must conserve by kind.
    """

    def _workload(self):
        from veritx_dse.workload.canonical import (
            Parallelism, WorkloadArtifact, build_compute_op)
        ops = (
            build_compute_op("op0", 100, input_bytes=1024,
                             weight_bytes=8192, output_bytes=512),
            build_compute_op("op1", 200, input_bytes=512,
                             weight_bytes=4096, output_bytes=256),
        )
        return WorkloadArtifact(
            workload_id="w", source_kind="test",
            parallelism=Parallelism(), num_participants=2, ops=ops)

    def test_operand_bytes_conserve_into_regions(self):
        wl = self._workload()
        expect = sum(v for op in wl.ops for v in
                     (op.input_bytes or 0, op.weight_bytes or 0,
                      op.output_bytes or 0))
        assert expect == 14592
        specs = [
            {"region_id": "op0.input", "object_type": "ACTIVATION",
             "size_bytes": 1024, "placement": _hbm(), "source_op_id": "op0"},
            {"region_id": "op0.weight", "object_type": "WEIGHT",
             "size_bytes": 8192, "placement": _hbm(), "source_op_id": "op0"},
            {"region_id": "op0.output", "object_type": "OUTPUT",
             "size_bytes": 512, "placement": _hbm(), "source_op_id": "op0"},
            {"region_id": "op1.input", "object_type": "ACTIVATION",
             "size_bytes": 512, "placement": _hbm(), "source_op_id": "op1"},
            {"region_id": "op1.weight", "object_type": "WEIGHT",
             "size_bytes": 4096, "placement": _hbm(), "source_op_id": "op1"},
            {"region_id": "op1.output", "object_type": "OUTPUT",
             "size_bytes": 256, "placement": _hbm(), "source_op_id": "op1"},
        ]
        regions = allocate_regions(specs, _policy())
        accesses = [
            build_access(f"acc.{r.region_id}", r.source_op_id,
                         r.region_id,
                         "WRITE" if r.object_type == "OUTPUT" else "READ",
                         0, r.size_bytes, 0)
            for r in regions
        ]
        art = build_artifact(
            name="conservation", source_workload_hash=wl.artifact_hash,
            num_nodes=2, regions=regions, accesses=accesses,
            mapping_policy=_policy())
        assert art.region_bytes_total() == expect
        assert art.access_bytes_total("READ") == 13824
        assert art.access_bytes_total("WRITE") == 768
        assert art.access_bytes_total() == expect
        # The artifact genuinely links its workload (not a placeholder).
        assert art.source_workload_hash == wl.artifact_hash
