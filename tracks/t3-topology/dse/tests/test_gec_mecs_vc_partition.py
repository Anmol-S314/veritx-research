"""GEC-MECS: the route's per-tap VC partition and the VC stage must agree.

This is the soundness crux of the whole shared-wire line for MECS. A hop's
eligible VCs are the slice its TAP owns (``vcs_lo = drop * num_vcs / d``).
If the route declares one partition map and the design's VC assignment
implements another, the dependency proof is about a network that was never
built — and it would still print PASS.

The agreement is structural rather than negotiated: the VC count is derived
from the fabric (``vcs_from_multidrop`` -> num_vcs = d), so each tap owns
exactly ONE VC and the map is a function of the tap index alone. Neither
stage has to run first, and neither can disagree with the other.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

DSE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(DSE))


def _compile(k: int, o: int, d: int, *, concentration: int = 1):
    from veritx_dse.application.fabric_compiler import FabricCompiler
    from veritx_dse.application.presets import _typed_workload
    from veritx_dse.model.compile_model import (
        Agent, AgentKind, DependencyGraph,
    )
    from veritx_dse.model.compile_request_v4 import CompileRequestV4
    from veritx_dse.model.noc_controls import NocControls
    from veritx_dse.model.topology_intent import (
        GecMode, GecTopologyIntent,
    )
    intent = GecTopologyIntent(
        mode=GecMode.MULTIDROP, grid_side_length=k, concentration=concentration,
        express_channel_groups_per_dimension=o,
        destinations_per_express_channel=d)
    n = k * k * concentration
    request = CompileRequestV4(
        workload=_typed_workload(n, payload_bytes=n * 128),
        dependencies=DependencyGraph(()),
        agents=(Agent(kind=AgentKind.COMPUTE_TILE, count=n, protocol="AXI",
                      data_width=256, addr_width=64),),
        topology=intent, noc_controls=NocControls())
    return FabricCompiler().compile(request)


def test_the_vc_count_follows_the_multidrop_degree():
    """One VC per tap: the source's per-drop split needs d disjoint slices."""
    from veritx_dse.model.compile_model import derive_vc_assignment_v3
    for d in (2, 3, 5):
        compilation = _compile(k=d + 1, o=1, d=d)
        assert compilation.status == "COMPILED", compilation.error
        assert compilation.bundle.vc_assignment.vc_count == d


@pytest.mark.parametrize("k,o,d", [(4, 1, 3), (6, 1, 5)])
def test_the_route_partition_map_equals_the_vc_assignment(k, o, d):
    compilation = _compile(k=k, o=o, d=d)
    assert compilation.status == "COMPILED", compilation.error
    route = compilation.bundle.router_route
    vc_count = compilation.bundle.vc_assignment.vc_count
    assert dict(route.partition_to_vcs) == {t: (t,) for t in range(vc_count)}, (
        "the route's per-tap slices must be the VCs the design actually "
        "has, or the dependency proof is about a different network")
    # Every shared hop declares the tap it leaves by, and that tap is its
    # partition.
    for decision in route.decisions.values():
        if decision.resource.is_shared:
            assert decision.tap is not None
            assert decision.vc_partition == decision.tap


def test_the_materialized_wire_count_and_the_route_agree():
    compilation = _compile(k=4, o=1, d=3)
    bundle = compilation.bundle
    assert len(bundle.topology.shared_links) == 32
    assert bundle.router_route.shared_resource_count == 32
    assert bundle.topology.channel_count == 0


def test_the_deadlock_obligation_is_discharged_for_mecs():
    compilation = _compile(k=4, o=1, d=3)
    by_name = {o.obligation: o for o in compilation.certificate.obligations}
    deadlock = by_name["DEADLOCK_FREE"]
    assert deadlock.status == "PASS"
    assert deadlock.method == "shared-resource-cdg/v1"
    assert deadlock.evidence["nodes"] > 0 and deadlock.evidence["edges"] > 0


def test_mecs_renders_and_executes_under_its_own_surface():
    """The renderer landed; only a shipped preset is missing."""
    from veritx_dse.application.capability_truth import derive_family_stages
    stages = derive_family_stages("gec_multidrop")
    assert stages.stages["VERIFIABLE"] == "YES"
    assert stages.stages["PROJECTABLE"] == "YES"
    assert stages.stages["EXECUTABLE"] == "YES"
    assert stages.stages["QUALIFIED"] == "YES"
    assert stages.stages["PRODUCT_WIRED"] == "YES"
    assert "gec_mecs16" in stages.authority["PRODUCT_WIRED"]
