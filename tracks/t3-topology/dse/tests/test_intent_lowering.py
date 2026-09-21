"""tests/test_intent_lowering.py — P1B.2: intent → WorkloadGraph.

The first product workload lowerer: narrow, explicit, refusal-typed.
It knows nothing about BookSim (AST-enforced); every refusal is
UnsupportedSemantics, never a guessed rank set, scope, or phase.
"""
from __future__ import annotations

import ast
import dataclasses
import sys
from pathlib import Path

import pytest

DSE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(DSE))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from veritx_dse.core.artifact import thaw  # noqa: E402
from veritx_dse.core.errors import UnsupportedSemantics  # noqa: E402
from veritx_dse.model.compile_model import (  # noqa: E402
    CollectiveKind, CollectiveOp, CompileRequest, ModelFamily, Workload,
)
from veritx_dse.workload.intent_lowering import (  # noqa: E402
    LOWERER_VERSION, lower_compile_workload,
)

from test_fabric_artifact import build_chain  # noqa: E402


def _request(**kw) -> CompileRequest:
    base = build_chain(tp=8, pp=1, ep=1, dp=1, n_agents=8).cr
    wl = dataclasses.replace(
        base.workload, model_family=ModelFamily.DENSE_TRANSFORMER,
        collectives=(CollectiveOp(kind=CollectiveKind.ALLREDUCE,
                                  group_size=8, payload_bytes=65536),))
    req = dataclasses.replace(base, workload=wl)
    if kw:
        req = dataclasses.replace(req, **kw)
    return req


def _workload(**kw) -> Workload:
    base = _request().workload
    return dataclasses.replace(base, **kw)


class TestLowerHappyPath:
    def test_single_allreduce_lowers_to_one_collective_op(self):
        graph = lower_compile_workload(_request())
        assert graph.participant_count == 8
        assert (graph.parallelism.tp, graph.parallelism.pp,
                graph.parallelism.ep, graph.parallelism.dp) == (8, 1, 1, 1)
        assert len(graph.operations) == 1
        op = graph.operations[0]
        assert op.operation_id == "collective-0"
        assert op.kind == "COLLECTIVE"
        assert op.deps == ()
        assert op.phase is None
        assert thaw(op.detail)["collective_kind"] == "ALLREDUCE"
        assert tuple(thaw(op.detail)["participants"]) == tuple(range(8))
        assert thaw(op.detail)["payload_bytes"] == 65536
        assert thaw(op.detail)["scope"] is None
        assert thaw(op.detail)["source"] is None
        assert graph.semantics.phase is None

    def test_lowering_is_deterministic(self):
        req = _request()
        assert lower_compile_workload(req).workload_id() == \
            lower_compile_workload(req).workload_id()

    def test_provenance_names_lowerer_and_design(self):
        req = _request()
        graph = lower_compile_workload(req)
        assert thaw(graph.provenance)["lowerer"] == LOWERER_VERSION
        assert thaw(graph.provenance)["design_hash"] == req.design_hash()

    def test_bytes_per_element_never_leaks_into_payload(self):
        req = _request()
        assert req.workload.collectives[0].bytes_per_element == 2048
        graph = lower_compile_workload(req)
        assert thaw(graph.operations[0].detail)["payload_bytes"] == 65536

    @pytest.mark.parametrize("kind", ["allgather", "reducescatter",
                                      "alltoall"])
    def test_supported_kinds_lower(self, kind):
        wl = _workload(collectives=(
            CollectiveOp(kind=CollectiveKind(kind), group_size=8,
                         payload_bytes=4096),))
        graph = lower_compile_workload(dataclasses.replace(
            _request(), workload=wl))
        assert thaw(graph.operations[0].detail)["collective_kind"] == \
            kind.upper()


class TestLowerRefusals:
    def test_moe_is_unsupported(self):
        wl = _workload(model_family=ModelFamily.MOE)
        with pytest.raises(UnsupportedSemantics, match="model_family"):
            lower_compile_workload(dataclasses.replace(
                _request(), workload=wl))

    def test_trace_path_is_unsupported(self):
        wl = _workload(trace_path="runs/traces/x.trace")
        with pytest.raises(UnsupportedSemantics, match="trace_path"):
            lower_compile_workload(dataclasses.replace(
                _request(), workload=wl))

    def test_no_collective_is_unsupported(self):
        wl = _workload(collectives=())
        with pytest.raises(UnsupportedSemantics, match="exactly one"):
            lower_compile_workload(dataclasses.replace(
                _request(), workload=wl))

    def test_two_collectives_are_unsupported(self):
        c = CollectiveOp(kind=CollectiveKind.ALLREDUCE, group_size=8,
                         payload_bytes=65536)
        wl = _workload(collectives=(c, c))
        with pytest.raises(UnsupportedSemantics, match="exactly one"):
            lower_compile_workload(dataclasses.replace(
                _request(), workload=wl))

    def test_broadcast_is_unsupported_without_root(self):
        wl = _workload(collectives=(
            CollectiveOp(kind=CollectiveKind.BROADCAST, group_size=8,
                         payload_bytes=65536),))
        with pytest.raises(UnsupportedSemantics, match="BROADCAST"):
            lower_compile_workload(dataclasses.replace(
                _request(), workload=wl))

    def test_subset_group_is_unsupported(self):
        wl = _workload(collectives=(
            CollectiveOp(kind=CollectiveKind.ALLREDUCE, group_size=4,
                         payload_bytes=65536),))
        with pytest.raises(UnsupportedSemantics, match="group_size"):
            lower_compile_workload(dataclasses.replace(
                _request(), workload=wl))

    def test_single_rank_collective_is_unsupported(self):
        wl = _workload(tp=1, collectives=(
            CollectiveOp(kind=CollectiveKind.ALLREDUCE, group_size=1,
                         payload_bytes=65536),))
        with pytest.raises(UnsupportedSemantics, match="single-rank"):
            lower_compile_workload(dataclasses.replace(
                _request(), workload=wl))

    def test_undeclared_payload_is_unsupported(self):
        wl = _workload(collectives=(
            CollectiveOp(kind=CollectiveKind.ALLREDUCE, group_size=8),))
        with pytest.raises(UnsupportedSemantics, match="payload_bytes"):
            lower_compile_workload(dataclasses.replace(
                _request(), workload=wl))


class TestLowererKnowsNoBackend:
    def test_no_backend_import(self):
        src = (DSE / "veritx_dse" / "workload" / "intent_lowering.py"
               ).read_text()
        tree = ast.parse(src)
        imported = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imported.update(a.name.split(".")[0] for a in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module:
                imported.add(node.module.split(".")[0])
        assert "veritx_dse" in imported  # self-package only by full path
        mods = [a for n in ast.walk(tree)
                for a in ([n.module] if isinstance(n, ast.ImportFrom)
                          else []) if a]
        assert not any(m.startswith("veritx_dse.backend") for m in mods), \
            f"lowerer imports backend: {mods}"
        assert not any("booksim" in (m or "") for m in mods), \
            f"lowerer imports booksim: {mods}"
