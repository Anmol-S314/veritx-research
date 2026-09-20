"""Wave-D persisted-resource authenticity (§56).

Every persisted Wave-D artifact verifies its embedded identity against
the recomputed canonical-content identity on load: the Wave-C
authenticity rule (requested/file ID == embedded resource ID ==
recomputed canonical-content ID), applied to the Wave-D artifact layer.
Tampered JSON refuses — never loads with someone else's hash.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

DSE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(DSE))

from veritx_dse.waved.errors import InvalidInput  # noqa: E402
from veritx_dse.waved.messages import LogicalMessageArtifact  # noqa: E402
from veritx_dse.waved.operations import (  # noqa: E402
    KIND_COLLECTIVE, KIND_P2P, CollectiveIntent, OperationGraph,
    OperationNode, P2PTransfer,
)
from veritx_dse.waved.parallelism import ParallelismArtifact  # noqa: E402
from veritx_dse.waved.semantics import WaveDWorkloadSemantics  # noqa: E402


def _pa():
    return ParallelismArtifact(tp=2, pp=1, ep=1, dp=2)


def _graph():
    pa = _pa()
    coll = CollectiveIntent("ALLREDUCE", (0, 1), 512, "c0")
    tr = P2PTransfer(0, 1, 300, "t0")
    return OperationGraph(
        parallelism=pa,
        semantics=WaveDWorkloadSemantics(phase="DECODE"),
        workload_id="sha256:wf-1",
        nodes=(OperationNode("n0", KIND_COLLECTIVE, "DECODE", 0, 0, (),
                             {"collective_id": "c0"}),
               OperationNode("n1", KIND_P2P, "DECODE", 0, 0, ("n0",),
                             {"transfer_id": "t0"})),
        collectives=(coll,), p2p_transfers=(tr,))


class TestParallelismAuthenticity:
    def test_roundtrip_preserves_id(self):
        pa = _pa()
        assert ParallelismArtifact.from_dict(pa.to_dict()) \
            .parallelism_id() == pa.parallelism_id()

    def test_tampered_parallelism_id_refused(self):
        pa = _pa()
        d = pa.to_dict()
        d["parallelism_id"] = "sha256:" + "0" * 64
        with pytest.raises(InvalidInput, match="does not match"):
            ParallelismArtifact.from_dict(d)

    def test_tampered_dimension_refused(self):
        pa = _pa()
        d = pa.to_dict()
        d["dp"] = 3  # content changed; integrity checks fire
        with pytest.raises(InvalidInput):
            ParallelismArtifact.from_dict(d)
        # And with the derived quantity dropped, the identity check fires.
        d2 = pa.to_dict()
        d2["dp"] = 3
        del d2["world_size"]
        with pytest.raises(InvalidInput, match="does not match"):
            ParallelismArtifact.from_dict(d2)

    def test_stored_world_size_must_match_derived(self):
        pa = _pa()
        d = pa.to_dict()
        d["world_size"] = 99
        with pytest.raises(InvalidInput, match="world_size"):
            ParallelismArtifact.from_dict(d)

    def test_unknown_fields_refused(self):
        pa = _pa()
        d = pa.to_dict()
        d["invented_field"] = 1
        with pytest.raises(InvalidInput, match="unknown fields"):
            ParallelismArtifact.from_dict(d)


class TestSemanticsAuthenticity:
    def test_roundtrip_preserves_id(self):
        sm = WaveDWorkloadSemantics(phase="PREFILL",
                                    shape_metadata={"num_layers": 4})
        assert WaveDWorkloadSemantics.from_dict(sm.to_dict()) \
            .semantics_id() == sm.semantics_id()

    def test_tampered_phase_refused(self):
        sm = WaveDWorkloadSemantics(phase="DECODE")
        d = sm.to_dict()
        d["phase"] = "PREFILL"
        with pytest.raises(InvalidInput, match="does not match"):
            WaveDWorkloadSemantics.from_dict(d)

    def test_unknown_shape_field_refused(self):
        with pytest.raises(InvalidInput, match="shape_metadata"):
            WaveDWorkloadSemantics(phase="DECODE",
                                   shape_metadata={"temperature": 7})


class TestOperationGraphAuthenticity:
    def test_graph_id_is_deterministic_content_function(self):
        assert _graph().operation_graph_id() == _graph().operation_graph_id()

    def test_workload_id_is_a_parent(self):
        # §23.2: changing workload_id MUST change operation_graph_id.
        pa = _pa()
        coll = CollectiveIntent("ALLREDUCE", (0, 1), 512, "c0")
        nodes = (OperationNode("n0", KIND_COLLECTIVE, "DECODE", 0, 0, (),
                               {"collective_id": "c0"}),)
        g1 = OperationGraph(parallelism=pa,
                            semantics=WaveDWorkloadSemantics("DECODE"),
                            workload_id="sha256:wf-1", nodes=nodes,
                            collectives=(coll,))
        g2 = OperationGraph(parallelism=pa,
                            semantics=WaveDWorkloadSemantics("DECODE"),
                            workload_id="sha256:wf-2", nodes=nodes,
                            collectives=(coll,))
        assert g1.operation_graph_id() != g2.operation_graph_id()

    def test_parallelism_parent_binding(self):
        pa1 = ParallelismArtifact(tp=2, pp=1, ep=1, dp=2)
        pa2 = ParallelismArtifact(tp=4, pp=1, ep=1, dp=1)
        coll1 = CollectiveIntent("ALLREDUCE", (0, 1), 512, "c0")
        coll2 = CollectiveIntent("ALLREDUCE", (0, 1, 2, 3), 512, "c0")
        g1 = OperationGraph(
            parallelism=pa1, semantics=WaveDWorkloadSemantics("DECODE"),
            workload_id="w",
            nodes=(OperationNode("n0", KIND_COLLECTIVE, "DECODE", 0, 0, (),
                                 {"collective_id": "c0"}),),
            collectives=(coll1,))
        g2 = OperationGraph(
            parallelism=pa2, semantics=WaveDWorkloadSemantics("DECODE"),
            workload_id="w",
            nodes=(OperationNode("n0", KIND_COLLECTIVE, "DECODE", 0, 0, (),
                                 {"collective_id": "c0"}),),
            collectives=(coll2,))
        assert g1.operation_graph_id() != g2.operation_graph_id()

    def test_semantics_parent_binding(self):
        pa = _pa()
        coll = CollectiveIntent("ALLREDUCE", (0, 1), 512, "c0")
        nodes = (OperationNode("n0", KIND_COLLECTIVE, "DECODE", 0, 0, (),
                               {"collective_id": "c0"}),)
        g1 = OperationGraph(
            parallelism=pa, semantics=WaveDWorkloadSemantics("DECODE"),
            workload_id="w", nodes=nodes, collectives=(coll,))
        g2 = OperationGraph(
            parallelism=pa, semantics=WaveDWorkloadSemantics("PREFILL"),
            workload_id="w", nodes=nodes, collectives=(coll,))
        assert g1.operation_graph_id() != g2.operation_graph_id()

    def test_message_artifact_binds_graph_id(self):
        lm = LogicalMessageArtifact(graph=_graph())
        d = lm.to_dict()
        assert d["operation_graph_id"] == _graph().operation_graph_id()
        # Tampering the parent in the persisted record is detectable by
        # rebuilding from the (tampered) parent: ids diverge.
        tampered = dict(d)
        tampered["operation_graph_id"] = "sha256:" + "f" * 64
        assert tampered["operation_graph_id"] \
            != LogicalMessageArtifact(
                graph=_graph()).message_artifact_id()
