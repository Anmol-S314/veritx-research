"""Adaptive Product compilation: MIN_ADAPT_MESH through FabricCompiler.

The adaptive science existed but no Product path reached it: compile()
takes an explicit RoutingPolicyDefinition (never a raw routing_function
string — routing stays LOCKED) and derives the relation, escape
partition, binding, realization and adaptive fabric alongside the
byte-identical deterministic bundle + certificate, gated by the
escape-subfunction qualification. UGAL/Valiant/Chaos stay refused.
"""
from __future__ import annotations

import copy
import dataclasses
import sys
from pathlib import Path

import pytest

DSE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(DSE))

from veritx_dse.application.fabric_compiler import FabricCompiler  # noqa: E402
from veritx_dse.application.preset_certification import (  # noqa: E402
    _load_preset_doc,
)
from veritx_dse.model.compile_model import CompileRequestV3  # noqa: E402
from veritx_dse.model.routing_relation_materialize import (  # noqa: E402
    min_adapt_mesh_policy,
)


def _request_2vc():
    """Dense mesh design whose dependency cycle derives 2 VCs (escape room)."""
    doc = copy.deepcopy(_load_preset_doc("dense-1b-16tiles"))
    doc["dependencies"] = [
        {"source": "X", "target": "Y", "kind": "blocking"},
        {"source": "Y", "target": "X", "kind": "blocking"},
    ]
    return CompileRequestV3.from_dict(doc)


def test_adaptive_mesh_compiles_qualified():
    compilation = FabricCompiler().compile(
        _request_2vc(), routing_policy=min_adapt_mesh_policy())
    assert compilation.status == "COMPILED", compilation.error
    assert compilation.certificate.overall == "PASS"
    overlay = compilation.adaptive
    assert overlay is not None
    assert overlay.qualification.verdict == "QUALIFIED"
    assert overlay.policy.id == "min_adapt_mesh"
    assert overlay.qualification.escape_vcs == (0,)
    assert overlay.qualification.adaptive_vcs == (1,)
    assert overlay.fabric is not None
    assert overlay.resolved_fabric is not None


def test_deterministic_path_byte_identical():
    req = _request_2vc()
    plain = FabricCompiler().compile(req)
    assert plain.adaptive is None
    again = FabricCompiler().compile(req)
    assert (plain.bundle.design.design_hash()
            == again.bundle.design.design_hash())
    assert (plain.bundle.topology.topology_hash()
            == again.bundle.topology.topology_hash())
    with_policy = FabricCompiler().compile(
        req, routing_policy=min_adapt_mesh_policy())
    # The deterministic bundle + certificate are unchanged by the overlay.
    assert (with_policy.bundle.topology.topology_hash()
            == plain.bundle.topology.topology_hash())
    assert with_policy.certificate.overall == "PASS"


def test_raw_routing_function_string_refused():
    with pytest.raises(TypeError, match="LOCKED"):
        FabricCompiler().compile(_request_2vc(), routing_policy="min_adapt")


@pytest.mark.parametrize("algorithm", ["ugal_flatfly", "valiant_mesh",
                                       "chaos_mesh"])
def test_non_min_adapt_algorithms_stay_refused(algorithm):
    policy = dataclasses.replace(min_adapt_mesh_policy(),
                                 algorithm=algorithm, id=algorithm,
                                 policy_hash="")
    compilation = FabricCompiler().compile(_request_2vc(),
                                           routing_policy=policy)
    assert compilation.status == "UNSUPPORTED", compilation.status


def test_single_vc_design_has_no_escape_room():
    doc = copy.deepcopy(_load_preset_doc("dense-1b-16tiles"))
    req = CompileRequestV3.from_dict(doc)
    compilation = FabricCompiler().compile(
        req, routing_policy=min_adapt_mesh_policy())
    assert compilation.status == "UNSUPPORTED", compilation.status
    assert compilation.bundle is None
    assert compilation.staged is not None


def test_non_mesh_topology_refused():
    from veritx_dse.model.compile_model import TopologyFamily  # noqa: E402

    base = _load_preset_doc("dense-1b-16tiles")
    doc = copy.deepcopy(base)
    doc["dependencies"] = [
        {"source": "X", "target": "Y", "kind": "blocking"},
        {"source": "Y", "target": "X", "kind": "blocking"},
    ]
    req = CompileRequestV3.from_dict(doc)
    req = dataclasses.replace(
        req, noc_config=dataclasses.replace(req.noc_config,
                                            topology_family=None))
    # Explicit custom graph + adaptive policy: relation contract is
    # mesh-only, so this refuses rather than approximating.
    import veritx_dse.model.topology_ir as tir  # noqa: E402

    graph = tir.from_dict({"kind": "custom", "name": "quad",
                           "nodes": 4,
                           "links": [[0, 1], [1, 2], [2, 3], [3, 0]],
                           "link_attrs": {"bandwidth_GBs": 50.0,
                                          "latency_ns": 0.5}})
    req = dataclasses.replace(req, explicit_topology=graph)
    compilation = FabricCompiler().compile(
        req, routing_policy=min_adapt_mesh_policy())
    assert compilation.status in ("UNSUPPORTED", "INVALID"), \
        compilation.status
