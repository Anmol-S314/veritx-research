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
