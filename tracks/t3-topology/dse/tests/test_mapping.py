"""MappingArtifact contracts (Wave B, audit #11/#25)."""
import pytest

from veritx_dse.core.mapping import MappingError, mapping_from_workload_index


def _index(pairs):
    return {"artifacts": [
        {"trace": t, "artifact_hash": h, "name": t} for t, h in pairs]}


def test_same_assignment_same_hash():
    a = mapping_from_workload_index(
        _index([("trace/instance0_batch1.txt", "sha256:aaa")]),
        "single_tp2_ep2")
    b = mapping_from_workload_index(
        _index([("trace/instance0_batch1.txt", "sha256:aaa")]),
        "single_tp2_ep2")
    assert a.mapping_hash == b.mapping_hash
    assert a.entries[0]["node"] == 0
    assert a.entries[0]["rank"] == 0


def test_swapped_ranks_change_hash():
    ab = mapping_from_workload_index(
        _index([("trace/instance0_batch1.txt", "sha256:aaa"),
                ("trace/instance1_batch1.txt", "sha256:bbb")]),
        "multi_dp_tp")
    ba = mapping_from_workload_index(
        _index([("trace/instance0_batch1.txt", "sha256:bbb"),
                ("trace/instance1_batch1.txt", "sha256:aaa")]),
        "multi_dp_tp")
    assert ab.mapping_hash != ba.mapping_hash


def test_missing_instance_marker_refuses():
    with pytest.raises(MappingError, match="no instance rank"):
        mapping_from_workload_index(
            _index([("trace/batch1.txt", "sha256:aaa")]), "single_tp2_ep2")


def test_rank_outside_cluster_refuses():
    with pytest.raises(MappingError, match="outside cluster"):
        mapping_from_workload_index(
            _index([("trace/instance9_batch1.txt", "sha256:aaa")]),
            "single_tp2_ep2")


def test_empty_index_refuses():
    with pytest.raises(MappingError):
        mapping_from_workload_index({"artifacts": []}, "single_tp2_ep2")
