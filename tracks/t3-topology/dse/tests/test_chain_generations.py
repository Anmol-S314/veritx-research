"""tests/test_chain_generations.py — slice 2c.4a.

The semantic-parent cutover's additive half: a canonical WorkloadGraph
resource, two explicitly versioned chain generations, and per-generation
schema closure.

Nothing here switches writers: new plans/results still emit chain v1, so
every historical contract keeps verifying while the v2 machinery becomes
testable. v1 proves the Wave-D ancestry it actually has; v2 proves the
canonical parent, and must never need the ghosts of deleted authorities.
"""
from __future__ import annotations

import copy
import json
import sys
from pathlib import Path

import pytest

DSE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(DSE))

from veritx_dse.application.errors import ControlPlaneError  # noqa: E402
from veritx_dse.application.waved_resources import (  # noqa: E402
    CHAIN_SCHEMA_VERSION_V2, PLAN_CHAIN_KEYS_V1, PLAN_CHAIN_KEYS_V2,
    RESULT_WAVE_D_KEYS_V1, RESULT_WAVE_D_KEYS_V2, chain_version,
    plan_chain_keys, result_wave_d_keys, validate_plan_chain_shape,
)
from veritx_dse.model.parallelism import ParallelismArtifact  # noqa: E402
from veritx_dse.workload.canonical_graph import (  # noqa: E402
    KIND_COLLECTIVE, OperationNode, WorkloadGraph, WorkloadSemantics,
    collective_detail,
)

PARALLELISM = ParallelismArtifact(tp=4, pp=1, ep=1, dp=1)


def _graph() -> WorkloadGraph:
    node = OperationNode("c0", KIND_COLLECTIVE, (), collective_detail(
        collective_kind="ALLREDUCE", participants=(0, 1, 2, 3),
        payload_bytes=1024, participant_count=4, scope=None))
    return WorkloadGraph(parallelism=PARALLELISM, participant_count=4,
                         operations=(node,),
                         semantics=WorkloadSemantics(),
                         provenance={"source": "test"})


def _v1_block() -> dict:
    return {key: f"value-{key}" for key in PLAN_CHAIN_KEYS_V1}


def _v2_block(**over) -> dict:
    block = {key: f"value-{key}" for key in PLAN_CHAIN_KEYS_V2}
    block["chain_schema_version"] = CHAIN_SCHEMA_VERSION_V2
    block.update(over)
    return block


class TestChainGenerationDispatch:
    def test_absence_of_version_means_v1(self):
        assert chain_version(_v1_block()) == 1

    def test_explicit_v2_is_recognised(self):
        assert chain_version(_v2_block()) == CHAIN_SCHEMA_VERSION_V2

    def test_unknown_version_refuses(self):
        with pytest.raises(ControlPlaneError, match="unknown chain_schema"):
            chain_version({"chain_schema_version": 99})

    def test_key_sets_are_per_generation(self):
        assert plan_chain_keys(1) == PLAN_CHAIN_KEYS_V1
        assert plan_chain_keys(CHAIN_SCHEMA_VERSION_V2) == PLAN_CHAIN_KEYS_V2
        with pytest.raises(ControlPlaneError, match="unknown chain version"):
            plan_chain_keys(7)

    def test_v1_exact_field_set_accepted(self):
        assert validate_plan_chain_shape(_v1_block()) == 1

    def test_v2_exact_field_set_accepted(self):
        assert validate_plan_chain_shape(_v2_block()) \
            == CHAIN_SCHEMA_VERSION_V2

    def test_v1_no_longer_carries_wave_d_runtime_ids_in_v2(self):
        """v2 must not smuggle the authorities being deleted."""
        for forbidden in ("waved_workload_id", "wave_d_semantics_id",
                          "operation_graph_id"):
            assert forbidden in PLAN_CHAIN_KEYS_V1
            assert forbidden not in PLAN_CHAIN_KEYS_V2

    def test_v2_authenticates_the_canonical_parent(self):
        assert "workload_graph_id" in PLAN_CHAIN_KEYS_V2
        assert "parallelism_id" in PLAN_CHAIN_KEYS_V2

    def test_mixed_keys_refuse_in_both_directions(self):
        """The classic transplant: v2 fields under a v1 doc, or the
        reverse, must not pass either generation's closure."""
        mixed = dict(_v1_block())
        mixed["workload_graph_id"] = "sha256:" + "a" * 64
        with pytest.raises(ControlPlaneError, match="does not match its "
                                                   "field set"):
            validate_plan_chain_shape(mixed)
        mixed2 = _v2_block()
        del mixed2["workload_graph_id"]
        mixed2["operation_graph_id"] = "sha256:" + "b" * 64
        with pytest.raises(ControlPlaneError, match="does not match its "
                                                   "field set"):
            validate_plan_chain_shape(mixed2)

    def test_missing_field_refuses_per_generation(self):
        broken = _v1_block()
        broken.pop("operation_graph_id")
        with pytest.raises(ControlPlaneError, match="field set"):
            validate_plan_chain_shape(broken)
        broken2 = _v2_block()
        broken2.pop("workload_graph_id")
        with pytest.raises(ControlPlaneError, match="field set"):
            validate_plan_chain_shape(broken2)

    def test_result_key_sets_follow_the_generation(self):
        assert result_wave_d_keys(1) == RESULT_WAVE_D_KEYS_V1
        assert result_wave_d_keys(CHAIN_SCHEMA_VERSION_V2) == \
            RESULT_WAVE_D_KEYS_V2
        assert set(PLAN_CHAIN_KEYS_V2) < set(RESULT_WAVE_D_KEYS_V2)
        with pytest.raises(ControlPlaneError, match="unknown chain version"):
            result_wave_d_keys(3)


class TestCanonicalWorkloadResource:
    """The WorkloadGraph resource is self-contained: no Wave-D parents."""

    @pytest.fixture
    def cp(self, tmp_path):
        from veritx_dse.application.service import SrotaControlPlane
        return SrotaControlPlane(store_root=tmp_path / "store",
                                 repo_root=DSE.parent.parent.parent)

    def test_roundtrip_through_the_verified_loader(self, cp):
        from veritx_dse.application.waved_resources import (
            load_verified_workload_graph, workload_graph_record,
        )
        graph = _graph()
        cp.store.put("workloadgraph", graph.workload_id(),
                     workload_graph_record(graph))
        loaded = load_verified_workload_graph(cp.store, graph.workload_id())
        assert loaded.workload_id() == graph.workload_id()
        assert loaded.to_dict() == graph.to_dict()

    def test_resource_id_is_the_content_identity(self, cp):
        from veritx_dse.application.waved_resources import (
            workload_graph_record,
        )
        graph = _graph()
        record = workload_graph_record(graph)
        assert graph.workload_id().startswith("sha256:")

    def test_tampered_document_refuses(self, cp):
        from veritx_dse.application.waved_resources import (
            load_verified_workload_graph, workload_graph_record,
        )
        graph = _graph()
        record = workload_graph_record(graph)
        doc = json.loads(json.dumps(record))
        doc["artifact"]["operations"][0]["detail"]["payload_bytes"] = 1
        cp.store.put("workloadgraph", graph.workload_id(), doc)
        with pytest.raises(ControlPlaneError):
            load_verified_workload_graph(cp.store, graph.workload_id())

    def test_transplanted_identity_refuses(self, cp):
        """A valid graph stored under another graph's id must refuse."""
        from veritx_dse.application.waved_resources import (
            load_verified_workload_graph, workload_graph_record,
        )
        other = WorkloadGraph(
            parallelism=PARALLELISM, participant_count=4,
            operations=(OperationNode("c0", KIND_COLLECTIVE, (),
                                      collective_detail(
                                          collective_kind="ALLGATHER",
                                          participants=(0, 1, 2, 3),
                                          payload_bytes=8,
                                          participant_count=4)),),
            semantics=WorkloadSemantics())
        graph = _graph()
        cp.store.put("workloadgraph", graph.workload_id(),
                     workload_graph_record(other))
        with pytest.raises(ControlPlaneError):
            load_verified_workload_graph(cp.store, graph.workload_id())

    def test_the_resource_needs_no_wave_d_parents(self, cp):
        """Loading it must not consult wavedworkload/semantics/opgraph."""
        from veritx_dse.application.waved_resources import (
            load_verified_workload_graph, workload_graph_record,
        )
        graph = _graph()
        cp.store.put("workloadgraph", graph.workload_id(),
                     workload_graph_record(graph))
        # the store contains ONLY the canonical resource
        assert load_verified_workload_graph(
            cp.store, graph.workload_id()).workload_id() == \
            graph.workload_id()
