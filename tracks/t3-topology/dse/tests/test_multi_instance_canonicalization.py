"""tests/test_multi_instance_canonicalization.py — the namespace regression.

The regression that would have caught the original silent design error.

`serve._parallelism_from_cluster` derives the parallelism GEOMETRY
(`dp = number of instances`, tp/ep/pp from the first instance), while
`num_participants` is the PER-INSTANCE rank space the trace's collectives
address. For a two-instance cluster with tp=4:

    parallelism.world_size = 4 x 1 x 1 x 2 = 8
    num_participants       = 4          (the trace's ranks are 0..3)

Any rule deriving `participant_count` from `world_size` would make the
canonical workload claim an 8-rank namespace for a 4-rank trace: a
"successful" consolidation that silently breaks multi-instance serving.

Tightened after audit: this file asserts the ACTUAL return contract of
``canonicalize_run_workload`` (schema_version / source_kind /
cluster_sha256 / artifacts) instead of walking generic fallbacks, and the
identity test pins ``workload_identity`` exactly. A regression that can
walk around an API change is not a regression.
"""
from __future__ import annotations

import copy
import hashlib
import json
import sys
from pathlib import Path

import pytest

DSE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(DSE))

from veritx_dse.workload.canonical import (  # noqa: E402
    WorkloadArtifact, WorkloadError,
)
from veritx_dse.workload.serve import (  # noqa: E402
    canonicalize_run_workload, workload_identity,
)

HEADER = "COLOCATED\t\tmodel_parallel_NPU_group: 1"

# the exact artifact-entry contract written by canonicalize_run_workload
ENTRY_KEYS = {"name", "trace", "artifact_hash", "file", "parallelism",
              "num_participants", "comm_bytes_total", "op_count"}


def _layer_row(name, comp_ns, inp, wt, out, comm="NONE", size=0,
               tag="BATCH_1"):
    return (f"{name}  {comp_ns}  LOCAL {inp}  LOCAL {wt}  LOCAL {out}  "
            f"{comm} {size}  {tag}")


def _write_trace(path: Path, rows: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join([HEADER, str(len(rows)), *rows]) + "\n")


def _cluster(*, instances: int, tp: int, num_npus: int) -> dict:
    return {
        "nodes": [
            {"instances": [
                {"tp_size": tp, "ep_size": 1, "pp_size": 1,
                 "num_npus": num_npus}
                for _ in range(instances)]}
        ]
    }


@pytest.fixture
def run_root(tmp_path: Path) -> Path:
    """A two-instance run: tp=4 per instance, 4 NPUs per instance."""
    root = tmp_path / "run"
    _write_trace(
        root / "inputs" / "trace" / "h100" / "llama" / "instance0_batch1.txt",
        [_layer_row("attention", 1000, 2048, 4096, 2048,
                    comm="ALLREDUCE:1,0", size=2048),
         _layer_row("o_proj", 500, 1024, 2048, 1024)])
    _write_trace(
        root / "inputs" / "trace" / "h100" / "llama" / "instance1_batch1.txt",
        [_layer_row("attention", 1000, 2048, 4096, 2048),
         _layer_row("o_proj", 500, 1024, 2048, 1024)])
    return root


def _canonicalize(run_root: Path, cluster: dict) -> dict:
    cpath = run_root / "cluster.json"
    cpath.write_text(json.dumps(cluster))
    return canonicalize_run_workload(run_root, cpath)


def _load(run_root: Path, entry: dict) -> dict:
    """Read the artifact through the entry's OWN file field."""
    path = run_root / "workload" / entry["file"]
    assert path.is_file(), f"index entry points at a missing file: {path}"
    return json.loads(path.read_text())


class TestIndexContract:
    """The real return shape, asserted exactly."""

    def test_index_shape_is_exact(self, run_root):
        index = _canonicalize(
            run_root, _cluster(instances=2, tp=4, num_npus=4))
        assert index["schema_version"] == 1
        assert index["source_kind"] == "llmservingsim"
        assert set(index) == {"schema_version", "source_kind",
                              "cluster_sha256", "artifacts"}
        assert index["cluster_sha256"] == hashlib.sha256(
            (run_root / "cluster.json").read_bytes()).hexdigest()
        # one entry per saved trace, exactly
        assert len(index["artifacts"]) == 2
        for entry in index["artifacts"]:
            assert ENTRY_KEYS <= set(entry), sorted(entry)
            assert entry["file"].endswith(".workload.json")
            assert entry["artifact_hash"].startswith("sha256:")
            assert entry["op_count"] >= 1

    def test_missing_trace_directory_refuses(self, tmp_path):
        with pytest.raises(WorkloadError, match="no trace directory"):
            canonicalize_run_workload(tmp_path / "nothing",
                                      tmp_path / "cluster.json")


class TestParticipantNamespace:
    def test_two_instances_tp4_keeps_participants_per_instance(self, run_root):
        """world_size = 8, participant_count = 4 — and they stay distinct."""
        index = _canonicalize(
            run_root, _cluster(instances=2, tp=4, num_npus=4))
        for entry in index["artifacts"]:          # no skip, no fallback
            doc = _load(run_root, entry)
            para = doc["parallelism"]
            assert (para["tp"], para["pp"], para["ep"], para["dp"]) == \
                (4, 1, 1, 2), doc
            world = (para["tp"] * para["pp"] * para["ep"] * para["dp"])
            assert world == 8
            assert doc["num_participants"] == 4, doc
            assert doc["num_participants"] != world
            # the entry and the document must agree
            assert entry["parallelism"] == para
            assert entry["num_participants"] == doc["num_participants"]

    def test_persisted_artifact_validates_against_participants(self, run_root):
        """Ranks 0..3 are legal; the artifact validates against 4, not 8."""
        index = _canonicalize(
            run_root, _cluster(instances=2, tp=4, num_npus=4))
        for entry in index["artifacts"]:
            art = WorkloadArtifact.from_dict(_load(run_root, entry))
            assert art.num_participants == 4, entry["name"]
            assert art.parallelism.dp == 2, entry["name"]
            for op in art.ops:
                for p in op.participants:
                    assert 0 <= p < art.num_participants, (entry["name"], p)

    def test_world_size_change_does_not_change_participants(self, run_root):
        """A third instance changes dp and world_size only."""
        index = _canonicalize(
            run_root, _cluster(instances=3, tp=4, num_npus=4))
        for entry in index["artifacts"]:
            doc = _load(run_root, entry)
            para = doc["parallelism"]
            assert para["dp"] == 3
            assert (para["tp"] * para["pp"] * para["ep"] * para["dp"]) == 12
            assert doc["num_participants"] == 4

    def test_per_instance_npu_count_is_what_varies_participants(self, run_root):
        index = _canonicalize(
            run_root, _cluster(instances=2, tp=4, num_npus=8))
        for entry in index["artifacts"]:
            assert _load(run_root, entry)["num_participants"] == 8

    def test_canonicalization_is_deterministic(self, run_root):
        cluster = _cluster(instances=2, tp=4, num_npus=4)
        first = _canonicalize(run_root, cluster)
        files1 = {p.name: p.read_text()
                  for p in sorted((run_root / "workload").glob("*.json"))}
        second = _canonicalize(run_root, cluster)
        files2 = {p.name: p.read_text()
                  for p in sorted((run_root / "workload").glob("*.json"))}
        assert first == second
        assert files1 == files2


class TestWorkloadIdentityContract:
    """Pin `workload_identity` exactly — one implementation, one contract.

        hashes = sorted(a["artifact_hash"] for a in artifacts)
        len == 0  -> WorkloadError
        len == 1  -> that hash (already "sha256:...")
        else      -> "sha256:" + sha256(json.dumps(hashes))
    """

    def test_two_artifacts_composite_identity(self, run_root):
        index = _canonicalize(
            run_root, _cluster(instances=2, tp=4, num_npus=4))
        hashes = sorted(a["artifact_hash"] for a in index["artifacts"])
        assert len(hashes) == 2
        expected = "sha256:" + hashlib.sha256(
            json.dumps(hashes, sort_keys=True).encode()).hexdigest()
        assert workload_identity(index) == expected

    def test_display_fields_do_not_move_identity(self, run_root):
        index = _canonicalize(
            run_root, _cluster(instances=2, tp=4, num_npus=4))
        before = workload_identity(index)
        mutated = copy.deepcopy(index)
        for i, entry in enumerate(mutated["artifacts"]):
            entry["name"] = f"renamed{i}"
            entry["trace"] = f"elsewhere/{i}.txt"
        mutated["cluster_sha256"] = "0" * 64
        assert workload_identity(mutated) == before

    def test_changing_one_artifact_hash_changes_identity(self, run_root):
        index = _canonicalize(
            run_root, _cluster(instances=2, tp=4, num_npus=4))
        before = workload_identity(index)
        mutated = copy.deepcopy(index)
        mutated["artifacts"][0]["artifact_hash"] = "sha256:" + "a" * 64
        assert workload_identity(mutated) != before

    def test_single_artifact_identity_is_the_artifact_hash(self, run_root):
        index = _canonicalize(
            run_root, _cluster(instances=2, tp=4, num_npus=4))
        single = {"artifacts": [index["artifacts"][0]]}
        assert workload_identity(single) == \
            index["artifacts"][0]["artifact_hash"]

    def test_empty_artifacts_refuses(self):
        with pytest.raises(WorkloadError, match="no artifacts"):
            workload_identity({"artifacts": []})
        with pytest.raises(WorkloadError, match="no artifacts"):
            workload_identity({})
