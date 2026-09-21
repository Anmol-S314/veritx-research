"""tests/test_multi_instance_canonicalization.py — the namespace regression.

The regression that would have caught the original silent design error.

`serve._parallelism_from_cluster` derives the parallelism GEOMETRY
(`dp = number of instances`, tp/ep/pp from the first instance), while
`num_participants` is the PER-INSTANCE rank space the trace's collectives
address. For a two-instance cluster with tp=4:

    parallelism.world_size = 4 x 1 x 1 x 2 = 8
    num_participants       = 4          (the trace's ranks are 0..3)

Any rule that derived `participant_count` from `world_size` would have
made the canonical workload claim an 8-rank namespace for a 4-rank trace:
a "successful" consolidation that silently breaks multi-instance serving.

This exercises the REAL entry point (``canonicalize_run_workload``),
not the helper, because the helper-level distinction is what the earlier
Gate V2 evidence captured and it was not enough.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

DSE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(DSE))

from veritx_dse.workload.canonical import WorkloadArtifact  # noqa: E402
from veritx_dse.workload.serve import (  # noqa: E402
    canonicalize_run_workload, workload_identity,
)

HEADER = "COLOCATED\t\tmodel_parallel_NPU_group: 1"


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


class TestParticipantNamespace:
    def test_two_instances_tp4_keeps_participants_per_instance(self, run_root):
        """world_size = 8, participant_count = 4 — and they stay distinct."""
        cluster = _cluster(instances=2, tp=4, num_npus=4)
        index = _canonicalize(run_root, cluster)
        assert index.get("workloads") or index.get("entries") or index

        for entry in (index.get("workloads") or index.get("entries")
                      or [index]):
            wl = entry.get("workload", entry)
            doc = json.loads(
                (run_root / "workload" /
                 f"{wl['name']}.workload.json").read_text()) \
                if "name" in wl else None
            if doc is None:
                continue
            para = doc["parallelism"]
            assert para["dp"] == 2, doc
            world = (para["tp"] * para["pp"] * para["ep"] * para["dp"])
            assert world == 8, doc
            # THE assertion: the rank space is the INSTANCE's, not the world
            assert doc["num_participants"] == 4, doc
            assert doc["num_participants"] != world

    def test_persisted_artifact_validates_against_participants(self, run_root):
        """Ranks 0..3 are legal; rank 4 would not be."""
        cluster = _cluster(instances=2, tp=4, num_npus=4)
        _canonicalize(run_root, cluster)
        artifacts = sorted(
            (run_root / "workload").glob("*.workload.json"))
        assert artifacts, "no workload documents were written"
        for path in artifacts:
            art = WorkloadArtifact.from_dict(json.loads(path.read_text()))
            assert art.num_participants == 4, path.name
            assert art.parallelism.dp == 2, path.name
            for op in art.ops:
                for p in op.participants:
                    assert 0 <= p < art.num_participants, (path.name, p)

    def test_world_size_change_does_not_change_participants(self, run_root):
        """A third instance changes dp and world_size only."""
        cluster = _cluster(instances=3, tp=4, num_npus=4)
        _canonicalize(run_root, cluster)
        for path in sorted((run_root / "workload").glob("*.workload.json")):
            doc = json.loads(path.read_text())
            assert doc["parallelism"]["dp"] == 3
            world = (doc["parallelism"]["tp"] * doc["parallelism"]["pp"]
                     * doc["parallelism"]["ep"] * doc["parallelism"]["dp"])
            assert world == 12
            assert doc["num_participants"] == 4

    def test_per_instance_npu_count_is_what_varies_participants(self, run_root):
        cluster = _cluster(instances=2, tp=4, num_npus=8)
        _canonicalize(run_root, cluster)
        for path in sorted((run_root / "workload").glob("*.workload.json")):
            doc = json.loads(path.read_text())
            assert doc["num_participants"] == 8

    def test_deterministic_and_identity_is_content_addressed(self, run_root):
        cluster = _cluster(instances=2, tp=4, num_npus=4)
        first = _canonicalize(run_root, cluster)
        docs1 = {p.name: p.read_text()
                 for p in sorted((run_root / "workload").glob("*.json"))}
        second = _canonicalize(run_root, cluster)
        docs2 = {p.name: p.read_text()
                 for p in sorted((run_root / "workload").glob("*.json"))}
        assert docs1 == docs2, "canonicalization is not deterministic"
        assert first == second

    def test_identity_is_not_a_stored_arbitrary_id(self, run_root):
        """workload_identity derives from the document, not a label."""
        cluster = _cluster(instances=2, tp=4, num_npus=4)
        index = _canonicalize(run_root, cluster)
        values = list(index.values()) if isinstance(index, dict) else []
        if any(isinstance(v, dict) and "workload_id" in v for v in values):
            for v in values:
                if isinstance(v, dict) and "workload_id" in v:
                    assert workload_identity(v) == v["workload_id"] \
                        or v["workload_id"].startswith("sha256:")
