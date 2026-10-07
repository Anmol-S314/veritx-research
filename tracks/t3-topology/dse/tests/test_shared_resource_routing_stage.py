"""SROTA now compiles end to end, with the shared-resource deadlock proof.

This test file started life asserting where the fabrication chain STOPPED.
It no longer stops: the v3 route is derived, expanded into an endpoint table,
carried through VC assignment and composition, and certified — with the
deadlock obligation discharged over the shared-resource graph rather than
the (channel, vc) graph that cannot describe a shared wire.

What is pinned here:

  * the route and the materializer agree on how many wires the fabric has
    (two independent constructions of one design);
  * the certificate's DEADLOCK_FREE obligation runs under the shared-resource
    method, not the point-to-point one, and passes;
  * the refusals that SHOULD remain do remain, and say why.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

DSE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(DSE))

from veritx_dse.application.capability_truth import (  # noqa: E402
    derive_family_stages,
)
from veritx_dse.model.route_artifact_v3 import RouteArtifactV3  # noqa: E402


def _srota_request(*, path_shapes=("row",), side_length=4, concentration=2,
                   mecs_row=True, mecs_col=True, vc_policy="none"):
    from veritx_dse.application.presets import _typed_workload
    from veritx_dse.model.compile_model import (
        Agent, AgentKind, DependencyGraph,
    )
    from veritx_dse.model.compile_request_v4 import CompileRequestV4
    from veritx_dse.model.noc_controls import NocControls
    from veritx_dse.model.topology_intent import topology_intent_from_dict
    intent = topology_intent_from_dict({
        "kind": "srota", "side_length": side_length,
        "concentration": concentration, "mecs_row": mecs_row,
        "mecs_col": mecs_col, "drop_latency": 1, "planes": ["d", "t"],
        "island_columns": [], "path_shapes": list(path_shapes),
        "vc_policy": vc_policy, "sidebuf_enable": True,
        "sidebuf_watermark": 6, "tel_period": 4, "tel_latency": 8,
    })
    endpoints = side_length ** 2 * concentration
    return CompileRequestV4(
        workload=_typed_workload(endpoints, payload_bytes=8000),
        dependencies=DependencyGraph(()),
        agents=(Agent(kind=AgentKind.COMPUTE_TILE, count=endpoints,
                      protocol="AXI", data_width=256, addr_width=64),),
        topology=intent, noc_controls=NocControls())


def _compile(request):
    from veritx_dse.application.fabric_compiler import FabricCompiler
    return FabricCompiler().compile(request)


def test_srota_compiles_with_a_pass_certificate():
    compilation = _compile(_srota_request())
    assert compilation.status == "COMPILED", compilation.error
    assert compilation.certificate is not None
    assert compilation.certificate.overall == "PASS", [
        (o.obligation, o.status, o.detail if hasattr(o, "detail") else "")
        for o in compilation.certificate.obligations
        if o.status != "PASS"]


def test_the_deadlock_obligation_uses_the_shared_resource_method():
    """Not the point-to-point certifier, which cannot read a shared wire."""
    compilation = _compile(_srota_request())
    by_name = {o.obligation: o for o in compilation.certificate.obligations}
    deadlock = by_name["DEADLOCK_FREE"]
    assert deadlock.status == "PASS"
    assert deadlock.method == "shared-resource-cdg/v1", (
        "a shared-wire fabric must be proved by the shared-resource method; "
        f"got {deadlock.method!r}")
    assert deadlock.evidence["verdict"] == "PASS"
    assert deadlock.evidence["nodes"] > 0 and deadlock.evidence["edges"] > 0, (
        "an acyclic verdict over an empty graph would be vacuous")


def test_the_route_uses_exactly_the_wires_the_topology_declared():
    """Two independent constructions of one fabric must agree."""
    compilation = _compile(_srota_request())
    staged = compilation.staged if compilation.staged is not None else None
    bundle = compilation.bundle
    route = bundle.router_route
    assert isinstance(route, RouteArtifactV3)
    topology = bundle.topology
    assert len(topology.shared_links) == route.shared_resource_count
    assert len(topology.shared_links) == 48, "4k(k-1) at k=4, both dimensions"
    # The route's own parent check is the same claim, recomputed.
    route.validate_against(topology)
    del staged


def test_the_capability_row_moves_on_that_evidence():
    stages = derive_family_stages("srota")
    for stage in ("AUTHORABLE", "MATERIALIZABLE", "ROUTABLE", "VERIFIABLE"):
        assert stages.stages[stage] == "YES", (stage, stages.as_dict())


def test_two_shape_srota_now_compiles_through_the_union():
    """Row+column with the 'shape' partition runs the union obligation."""
    from veritx_dse.model.route_artifact_v3 import ShapePolicyRoute
    compilation = _compile(_srota_request(path_shapes=("row", "column"),
                                          vc_policy="shape"))
    assert compilation.status == "COMPILED", compilation.error
    assert compilation.certificate.overall == "PASS"
    assert isinstance(compilation.bundle.router_route, ShapePolicyRoute)
    assert compilation.bundle.vc_assignment.vc_count == 2
    by_name = {o.obligation: o for o in compilation.certificate.obligations}
    assert by_name["DEADLOCK_FREE"].method == "shared-resource-cdg/v1"


def test_a_plain_dimension_fabric_refuses_rather_than_get_a_fake_tap():
    """A dimension without express has no taps, so the express rule cannot
    describe its hops."""
    compilation = _compile(_srota_request(mecs_col=False))
    assert compilation.status == "UNSUPPORTED"
    assert compilation.stopped_at_stage == "ROUTING"


def test_gec_mecs_is_product_wired_after_qualification():
    stages = derive_family_stages("gec_multidrop")
    for stage in ("MATERIALIZABLE", "ROUTABLE", "VERIFIABLE", "PROJECTABLE",
                  "EXECUTABLE", "QUALIFIED", "PRODUCT_WIRED"):
        assert stages.stages[stage] == "YES", (stage, stages.as_dict())
    assert stages.stopped_at_stage is None


def test_the_point_to_point_certifier_still_refuses_shared_wires():
    """The two certifiers must not quietly converge on each other."""
    from veritx_dse.verification.channel_vc_cdg import CDGError, CDGError as E
    from veritx_dse.verification.channel_vc_cdg import build_channel_vc_cdg
    compilation = _compile(_srota_request())
    bundle = compilation.bundle
    with pytest.raises((CDGError, E)):
        build_channel_vc_cdg(
            topology=bundle.topology, router_route=bundle.router_route,
            vc_assignment=bundle.vc_assignment)
