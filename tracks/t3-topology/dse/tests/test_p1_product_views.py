"""Stage-7 gateway tests: projector outputs validate + honest absence."""
from __future__ import annotations

import json

import jsonschema
import pytest

from veritx_dse.application.fabric_compiler import FabricCompiler
from veritx_dse.application.views import compilation_view, design_view
from veritx_dse.core.paths import REPO
from veritx_dse.model.compile_model import (
    CompileRequest,
    CompileRequestV3,
)


def _schema(name):
    return json.loads(
        (REPO / "contracts" / "srota" / "v1" / name).read_text())


def _v3():
    doc = json.loads(
        (REPO / "tracks/t3-topology/examples/llama_dense_64tiles-v3.json")
        .read_text())
    return CompileRequestV3.from_dict(doc)


def test_compilation_view_validates_and_prefixes():
    comp = FabricCompiler().compile(_v3())
    assert comp.status == "COMPILED"
    view = compilation_view(comp)
    jsonschema.validate(view, _schema("compilation.view.schema.json"))
    assert view["design_hash"].startswith("sha256:")
    assert view["resolved_fabric_hash"].startswith("sha256:")
    assert len(view["obligations"]) == 10


def test_compilation_view_refusal_carries_no_bundle():
    from veritx_dse.model.compile_model import TopologyFamily
    import dataclasses
    req = _v3()
    torus = dataclasses.replace(
        req, noc_config=dataclasses.replace(
            req.noc_config, topology_family=TopologyFamily.TORUS))
    comp = FabricCompiler().compile(torus)
    assert comp.status in ("INVALID", "UNSUPPORTED")
    view = compilation_view(comp)
    jsonschema.validate(view, _schema("compilation.view.schema.json"))
    assert "resolved_fabric_hash" not in view


def test_design_view_v2_and_v3_validate():
    v2 = CompileRequest.from_dict(json.loads(
        (REPO / "tracks/t3-topology/examples/llama_dense_64tiles.json")
        .read_text()))
    comp2 = FabricCompiler().compile(v2)
    assert comp2.status == "COMPILED"
    for req, comp in ((_v3(), FabricCompiler().compile(_v3())), (v2, comp2)):
        view = design_view(req, comp)
        jsonschema.validate(view, _schema("design.view.schema.json"))
        assert view["locked_derived"]["routing"] == "DOR_XY"
        assert view["locked_derived"]["certificate_overall"] == "PASS"
        # No turn-restriction list survives in the artifact world:
        # omitted, never fabricated.
        assert "turn_restrictions" not in view["locked_derived"]
    bare = design_view(_v3())
    assert bare["locked_derived"] is None
    assert "workload_source_ref" not in bare["workload"]


def test_design_view_refuses_cross_design_compilation():
    """RT-8: a compilation for another request can never fill
    locked_derived (cross-design locked-state transplant)."""
    req_a = _v3()
    comp_a = FabricCompiler().compile(req_a)
    assert comp_a.status == "COMPILED"
    v2 = CompileRequest.from_dict(json.loads(
        (REPO / "tracks/t3-topology/examples/llama_dense_64tiles.json")
        .read_text()))
    comp_b = FabricCompiler().compile(v2)
    assert comp_b.status == "COMPILED"
    assert req_a.design_hash() != v2.design_hash()
    with pytest.raises(ValueError) as excinfo:
        design_view(v2, comp_a)
    message = str(excinfo.value)
    assert req_a.design_hash() in message
    assert v2.design_hash() in message
    # The same compilation for the matching request still fills the
    # derived block.
    matched = design_view(req_a, comp_a)
    assert matched["locked_derived"] is not None
    assert matched["locked_derived"]["certificate_overall"] == "PASS"


def test_design_view_refuses_non_compilation():
    with pytest.raises(ValueError):
        design_view(_v3(), {"status": "COMPILED"})


def test_design_view_refuses_same_geometry_cross_design():
    """B4: identical TP/PP/EP/DP is not identity — a compilation for a
    same-geometry request with different semantics can never fill
    another request's locked_derived, and a mismatch raises rather than
    silently projecting locked_derived=None."""
    import dataclasses
    req_a = _v3()
    req_b = dataclasses.replace(
        req_a,
        workload=dataclasses.replace(
            req_a.workload,
            collectives=(dataclasses.replace(
                req_a.workload.collectives[0], payload_bytes=4096),)))
    comp_a = FabricCompiler().compile(req_a)
    comp_b = FabricCompiler().compile(req_b)
    assert comp_a.status == "COMPILED"
    assert comp_b.status == "COMPILED"
    assert (req_a.workload.tp, req_a.workload.pp, req_a.workload.ep,
            req_a.workload.dp) == (
        req_b.workload.tp, req_b.workload.pp, req_b.workload.ep,
        req_b.workload.dp)
    assert req_a.design_hash() != req_b.design_hash()
    with pytest.raises(ValueError) as excinfo:
        design_view(req_b, comp_a)
    message = str(excinfo.value)
    assert req_a.design_hash() in message
    assert req_b.design_hash() in message
    with pytest.raises(ValueError):
        design_view(req_a, comp_b)
    matched = design_view(req_b, comp_b)
    assert matched["locked_derived"] is not None
    assert matched["locked_derived"]["certificate_overall"] == "PASS"
