"""The shared GEC-MECS fabric must be able to run on the project's real seats.

The historical shared-fabric run treats the routers as the traffic
endpoints.  When the compiled bundle declares endpoint seats, the fabric must
instead carry endpoint ids on the wire and decode them to routers, so the run
exercises the project's declared agents rather than the router set.

These tests pin that behaviour at a small shape, and pin the refusals: two
seats on one router cannot both be delivered by a fabric with one local port
per router.
"""

from __future__ import annotations

import json
import re
import shutil
from pathlib import Path

import pytest

from veritx_dse.model.agent_intent_v4 import (
    AgentIntentV4, OrderingMode, PermissionWindow, ProtocolFamily,
)
from veritx_dse.model.compile_model import (
    AddressMap, AddressRange, Agent, AgentKind, CollectiveDimension,
    CollectiveIntent, CollectiveKind, DependencyGraph, ModelFamily,
    PhysicalContext, WorkloadV3,
)
from veritx_dse.model.compile_request_v4 import CompileRequestV4
from veritx_dse.model.topology_intent import GecMode, GecTopologyIntent

VERILATOR = shutil.which("verilator")


def _request(k: int, taps: int, agents: int):
    workload = WorkloadV3(
        model_family=ModelFamily.DENSE_TRANSFORMER, tp=1, pp=1, ep=1, dp=1,
        collectives=(CollectiveIntent(
            kind=CollectiveKind.ALLREDUCE, dimension=CollectiveDimension.TP,
            payload_bytes=8192, traffic_class="tp_collective"),))
    kinds = [AgentKind.COMPUTE_TILE, AgentKind.HBM_CONTROLLER]
    declared = tuple(
        Agent(kind=kinds[index % len(kinds)], count=1, data_width=32,
              addr_width=64, protocol="AXI", clock_domain="noc_clk",
              power_domain="pd0")
        for index in range(agents))
    intents = tuple(
        AgentIntentV4(index, protocol=ProtocolFamily.AXI5,
                      ordering=OrderingMode.STRONG, max_outstanding=4,
                      permission_windows=(PermissionWindow(
                          "HBM0", readable=True, writable=True,
                          atomic=False),))
        if index % 2 == 0 else AgentIntentV4(index)
        for index in range(agents))
    return CompileRequestV4(
        workload=workload, agents=declared, dependencies=DependencyGraph(()),
        topology=GecTopologyIntent(mode=GecMode.MULTIDROP, grid_side_length=k,
                                   concentration=1,
                                   express_channel_groups_per_dimension=1,
                                   destinations_per_express_channel=taps),
        address_map=AddressMap(ranges=(AddressRange(
            name="HBM0", base=0x1000, size=0x1000, target_agent_idx=1),)),
        physical=PhysicalContext(default_clock_freq_mhz=1000.0),
        agent_intents=intents)


def _run(request, tmp_path: Path, endpoint_seats: bool):
    from veritx_dse.core.paths import REPO
    from veritx_dse.product import project_top_rtl
    out = tmp_path / ("seats" if endpoint_seats else "routers")
    out.mkdir(parents=True, exist_ok=True)
    return project_top_rtl.run_gec_mecs_shared(
        request.to_dict(), out,
        {"repo_root": str(REPO), "endpoint_seats": endpoint_seats})


def test_endpoint_seats_are_derived_from_the_compiled_bundle(tmp_path):
    from veritx_dse.product.project_top_rtl import (
        gec_mecs_shared_params_from_request,
    )
    from veritx_dse.application.fabric_compiler import FabricCompiler
    request = _request(5, 4, 6)
    compiled = FabricCompiler().compile(request)
    assert compiled.status == "COMPILED", compiled.error
    params = gec_mecs_shared_params_from_request(
        request, compiled, endpoint_seats=True)
    seats = params.endpoint_routers
    assert len(seats) == 6
    # Each seat owns a router of its own; two seats on one router could not
    # both be delivered by a fabric with one local port per router.
    assert len(set(seats)) == len(seats)
    assert all(0 <= seat < params.router_count for seat in seats)
    assert params.router_count == 25
    # The router-mode parameters declare no seats at all.
    plain = gec_mecs_shared_params_from_request(request, compiled)
    assert plain.endpoint_routers == ()


def test_the_fabric_decodes_endpoint_ids_when_seats_are_declared(tmp_path):
    """With seats the destination field is an endpoint id; without, a router id."""
    from veritx_dse.product.gec_mecs_scaled import (
        render_scaled_fabric, render_scaled_tb,
    )
    from veritx_dse.product.project_top_rtl import (
        gec_mecs_shared_params_from_request, _scaled_params_of,
    )
    from veritx_dse.application.fabric_compiler import FabricCompiler
    request = _request(5, 4, 6)
    compiled = FabricCompiler().compile(request)

    plain = _scaled_params_of(gec_mecs_shared_params_from_request(
        request, compiled, endpoint_seats=False))
    seated = _scaled_params_of(gec_mecs_shared_params_from_request(
        request, compiled, endpoint_seats=True))

    router_mode = render_scaled_fabric(plain)
    seat_mode = render_scaled_fabric(seated)
    field_w = plain.dest_w
    # Without seats the destination field is the router id, directly.
    assert f"return int'(flit[DEST_LSB +: {field_w}])" in router_mode
    assert "case (flit[DEST_LSB" not in router_mode
    # With seats it decodes an endpoint id to the router that owns it.
    assert f"case (flit[DEST_LSB +: {field_w}])" in seat_mode
    assert "default: return K*K;" in seat_mode
    # Only the destination decode differs.
    assert seat_mode != router_mode
    assert render_scaled_tb(plain) != render_scaled_tb(seated)


def test_the_seat_map_reaches_the_emitted_fabric(tmp_path):
    """The emitted fabric must carry the endpoint-to-router decode."""
    from veritx_dse.product.project_top_rtl import (
        _gec_mecs_endpoint_seats,
    )
    from veritx_dse.application.fabric_compiler import FabricCompiler
    request = _request(4, 3, 4)
    compiled = FabricCompiler().compile(request)
    assert compiled.status == "COMPILED", compiled.error
    seats = _gec_mecs_endpoint_seats(compiled.bundle, 16)
    assert len(seats) == 4


@pytest.mark.skipif(VERILATOR is None,
                    reason="verilator not installed; cannot lint/sim the fabric")
def test_the_fabric_runs_on_the_project_seats(tmp_path):
    # (4,1,1,3) is the pinned historical shape and refuses seats, so this
    # uses a scalable shape with the same seat geometry.
    result = _run(_request(5, 4, 6), tmp_path, endpoint_seats=True)
    assert result["lint"] == "PASS", result.get("lint")
    assert result["sim"] == "PASS", result.get("sim")
    params = result["family_params"]
    assert params["router_count"] == 25
    assert params["shared_wires"] == 50
    assert params["endpoint_seats"] == 6
    scenarios = result["scenarios"]
    assert all(scenarios.values()), scenarios
    # Four seats give sixteen ordered pairs, not the sixteen routers squared.
    log = (tmp_path / "seats" / "rtl" / "logs" / "verilator-sim.log").read_text()
    match = re.search(r"all_pairs=(\d+)", log)
    assert match, log
    assert int(match.group(1)) == 36  # 6 x 6 ordered seat pairs
    assert "local=6" in log, log


def test_the_pinned_historical_shape_refuses_endpoint_seats():
    """Its testbench is pinned and drives router pairs, so seats must refuse."""
    from veritx_dse.product.project_top_rtl import (
        gec_mecs_shared_params_from_request,
    )
    from veritx_dse.application.fabric_compiler import FabricCompiler
    request = _request(4, 3, 4)
    compiled = FabricCompiler().compile(request)
    with pytest.raises(ValueError):
        gec_mecs_shared_params_from_request(request, compiled,
                                           endpoint_seats=True)
    # Router mode still works on the pinned shape.
    params = gec_mecs_shared_params_from_request(request, compiled)
    assert params.endpoint_routers == ()
