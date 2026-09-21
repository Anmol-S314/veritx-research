"""tests/test_fabric_evaluator_prepare.py — P1B.4: prepare the slice.

Compilation → WorkloadGraph → logical → physical → sealed backend
input, with no backend spawn and no binary required. Preconditions
refuse before any lowering work.
"""
from __future__ import annotations

import dataclasses
import json
import sys
from pathlib import Path

import pytest

DSE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(DSE))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from veritx_dse.application.errors import (  # noqa: E402
    ControlPlaneError, ErrorCode,
)
from veritx_dse.application.fabric_compiler import (  # noqa: E402
    FabricCompiler,
)
from veritx_dse.application.fabric_evaluator import (  # noqa: E402
    EvaluationOptions, FabricEvaluator,
)
from veritx_dse.backend.projection import (  # noqa: E402
    prepare_physical_traffic_booksim, prepare_waved_booksim,
    render_physical_traffic_trace, render_waved_trace,
)
from veritx_dse.model.compile_model import CompileRequest  # noqa: E402
from veritx_dse.workload.intent_lowering import (  # noqa: E402
    lower_compile_workload,
)

REPO_EXAMPLE = (DSE.parent / "examples" / "llama_dense_64tiles.json")


def _compiled():
    req = CompileRequest.from_dict(json.loads(REPO_EXAMPLE.read_text()))
    comp = FabricCompiler().compile(req)
    assert comp.status == "COMPILED"
    return comp


class TestPrepare:
    def test_prepare_binds_every_layer(self):
        comp = _compiled()
        graph = lower_compile_workload(comp.request)
        prepped = FabricEvaluator().prepare(comp, graph)
        assert prepped.compilation is comp
        assert prepped.workload_graph is graph
        assert prepped.logical.message_artifact_id()
        assert prepped.traffic.physical_traffic_id()
        assert prepped.summary["num_packets"] == sum(
            len(t.packets) for t in prepped.traffic.traffic)
        assert prepped.summary["num_packets"] > 0
        assert prepped.prepared.manifest.backend_input_hash()
        assert prepped.prepared.config.backend_config_hash()

    def test_wrappers_delegate_to_single_implementation(self):
        comp = _compiled()
        prepped = FabricEvaluator().prepare(
            comp, lower_compile_workload(comp.request))
        pt = prepped.traffic
        assert render_physical_traffic_trace(pt) == render_waved_trace(pt)
        legacy_prepared, _ = prepare_waved_booksim(pt)
        assert prepped.prepared.manifest.backend_input_hash() == \
            legacy_prepared.manifest.backend_input_hash()

    def test_prepare_needs_no_backend_binary(self, monkeypatch):
        import veritx_dse.simulation.booksim as sim_bs
        monkeypatch.setattr(
            sim_bs, "find_booksim_bin",
            lambda *_a, **_k: (_ for _ in ()).throw(
                FileNotFoundError("no binary here")))
        comp = _compiled()
        prepped = FabricEvaluator().prepare(
            comp, lower_compile_workload(comp.request))
        assert prepped.summary["num_packets"] > 0


class TestPreparePreconditions:
    def test_non_compiled_refuses(self):
        comp = _compiled()
        bad = dataclasses.replace(comp, status="INVALID", bundle=None,
                                  certificate=None, error="injected")
        with pytest.raises(ControlPlaneError) as ei:
            FabricEvaluator().prepare(
                bad, lower_compile_workload(comp.request))
        assert ei.value.code == ErrorCode.INVALID_INTENT

    def test_failing_certificate_refuses(self):
        comp = _compiled()
        failing = dataclasses.replace(
            comp.certificate, overall="FAIL",
            obligations=tuple(
                dataclasses.replace(o, status="FAIL")
                if o.obligation == "DEADLOCK_FREE" else o
                for o in comp.certificate.obligations))
        bad = dataclasses.replace(comp, certificate=failing)
        with pytest.raises(ControlPlaneError) as ei:
            FabricEvaluator().prepare(
                bad, lower_compile_workload(comp.request))
        assert ei.value.code == ErrorCode.INVALID_INTENT

    def test_unknown_backend_refuses(self):
        comp = _compiled()
        with pytest.raises(ControlPlaneError) as ei:
            FabricEvaluator().prepare(
                comp, lower_compile_workload(comp.request),
                EvaluationOptions(backend="analytical"))
        assert ei.value.code == ErrorCode.UNSUPPORTED_SEMANTICS
