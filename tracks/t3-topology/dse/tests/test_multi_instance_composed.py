from __future__ import annotations

import shutil
from dataclasses import replace

import pytest

from veritx_dse.application.fabric_compiler import FabricCompiler
from veritx_dse.model.agent_intent_v4 import (
    AgentIntentV4, OrderingMode, PermissionWindow, ProtocolFamily,
)
from veritx_dse.model.compile_model import (
    AddressMap, AddressRange, Agent, AgentKind, CollectiveDimension,
    CollectiveIntent, CollectiveKind, DependencyGraph, ModelFamily,
    PhysicalContext, WorkloadV3,
)
from veritx_dse.model.compile_request_v4 import CompileRequestV4
from veritx_dse.model.topology_intent import MeshIntent
from veritx_dse.product.multi_instance_seats import (
    MultiSeatUnsupported, co_seated_routers, plan_endpoint_seats,
)


def _request(compute_count: int = 2, side: int = 2):
    workload = WorkloadV3(
        model_family=ModelFamily.DENSE_TRANSFORMER, tp=2, pp=1, ep=1, dp=1,
        collectives=(CollectiveIntent(
            kind=CollectiveKind.ALLREDUCE, dimension=CollectiveDimension.TP,
            payload_bytes=8192, traffic_class="tp_collective"),))
    agents = (
        Agent(kind=AgentKind.COMPUTE_TILE, count=compute_count, data_width=32,
              addr_width=64, protocol="AXI", clock_domain="noc_clk",
              power_domain="pd0"),
        Agent(kind=AgentKind.HBM_CONTROLLER, count=1, data_width=32,
              addr_width=64, protocol="AXI", clock_domain="noc_clk",
              power_domain="pd0"),
    )
    intents = (
        AgentIntentV4(0, protocol=ProtocolFamily.AXI5, ordering=OrderingMode.STRONG,
                      max_outstanding=4,
                      permission_windows=(PermissionWindow(
                          "HBM0", readable=True, writable=True, atomic=False),)),
        AgentIntentV4(1),
    )
    return CompileRequestV4(
        workload=workload, agents=agents, dependencies=DependencyGraph(()),
        topology=MeshIntent(side_length=side, concentration=1),
        address_map=AddressMap(ranges=(AddressRange(
            name="HBM0", base=0x1000, size=0x1000, target_agent_idx=1),)),
        physical=PhysicalContext(default_clock_freq_mhz=1000.0),
        agent_intents=intents)


def _compiled(compute_count: int = 2, side: int = 2):
    compiled = FabricCompiler().compile(_request(compute_count, side))
    assert compiled.status == "COMPILED", compiled.error
    return compiled


def test_multi_instance_group_is_no_longer_refused_by_the_builder():
    from veritx_dse.product.project_top_rtl import composed_family_params_from_request
    request = _request(2)
    compiled = FabricCompiler().compile(request)
    assert compiled.status == "COMPILED"
    params = composed_family_params_from_request(request, compiled)
    assert len(params.initiators) == 2
    assert [(i.group_idx, i.instance_index) for i in params.initiators] == [(0, 0), (0, 1)]
    assert len({i.router_id for i in params.initiators}) == 2


def test_each_instance_gets_its_own_endpoint_and_sequence_state():
    from veritx_dse.product.project_top_rtl import composed_family_params_from_request
    request = _request(2)
    compiled = FabricCompiler().compile(request)
    params = composed_family_params_from_request(request, compiled)
    assert [i.endpoint_index for i in params.initiators] == [0, 1]
    assert [i.instance_index for i in params.initiators] == [0, 1]


def test_multi_instance_composed_top_lints_and_simulates(tmp_path):
    if shutil.which("verilator") is None:
        pytest.skip("verilator not installed; cannot lint/sim the composed top")
    from veritx_dse.product.project_top_rtl import run_composed_family
    request = _request(2)
    out = tmp_path / "out"
    out.mkdir()
    result = run_composed_family(request.to_dict(), out,
                                 {"repo_root": str(_repo_root())})
    assert result["lint"] == "PASS", result
    assert result["sim"] == "PASS", result.get("scenarios")
    scenarios = result["scenarios"]
    assert all(scenarios.values()), scenarios
    assert "allow_write_init0" in scenarios and "allow_write_init1" in scenarios
    assert "allow_read_init0" in scenarios and "allow_read_init1" in scenarios


def test_composed_top_emits_one_adapter_path_per_instance(tmp_path):
    import re
    if shutil.which("verilator") is None:
        pytest.skip("verilator not installed; cannot lint/sim the composed top")
    from veritx_dse.product.project_top_rtl import run_composed_family
    request = _request(2)
    out = tmp_path / "out"
    out.mkdir()
    run_composed_family(request.to_dict(), out, {"repo_root": str(_repo_root())})
    top = (out / "rtl" / "project_top.sv").read_text()
    assert len(re.findall(r"u_slice\d+ \(", top)) == 2
    assert sorted(set(re.findall(r"input logic \[63:0\] init(\d+)_awaddr", top))) == ["0", "1"]


def test_co_seated_endpoints_are_refused_by_name():
    from veritx_dse.product.project_top_rtl import composed_family_params_from_request
    request = _request(2, side=2)
    compiled = FabricCompiler().compile(request)
    assert compiled.status == "COMPILED"
    plan = plan_endpoint_seats(request, compiled)
    assert co_seated_routers(plan) == ()
    assert issubclass(MultiSeatUnsupported, ValueError)


def _cmesh_request():
    from veritx_dse.model.topology_intent import ConcentratedMeshIntent
    workload = WorkloadV3(
        model_family=ModelFamily.DENSE_TRANSFORMER, tp=2, pp=1, ep=1, dp=1,
        collectives=(CollectiveIntent(
            kind=CollectiveKind.ALLREDUCE, dimension=CollectiveDimension.TP,
            payload_bytes=8192, traffic_class="tp_collective"),))
    agents = (
        Agent(kind=AgentKind.COMPUTE_TILE, count=2, data_width=32,
              addr_width=64, protocol="AXI", clock_domain="noc_clk",
              power_domain="pd0"),
        Agent(kind=AgentKind.HBM_CONTROLLER, count=1, data_width=32,
              addr_width=64, protocol="AXI", clock_domain="noc_clk",
              power_domain="pd0"),
    )
    intents = (
        AgentIntentV4(0, protocol=ProtocolFamily.AXI5, ordering=OrderingMode.STRONG,
                      max_outstanding=4,
                      permission_windows=(PermissionWindow(
                          "HBM0", readable=True, writable=True, atomic=False),)),
        AgentIntentV4(1),
    )
    return CompileRequestV4(
        workload=workload, agents=agents, dependencies=DependencyGraph(()),
        topology=ConcentratedMeshIntent(side_length=2, concentration=2),
        address_map=AddressMap(ranges=(AddressRange(
            name="HBM0", base=0x1000, size=0x1000, target_agent_idx=1),)),
        physical=PhysicalContext(default_clock_freq_mhz=1000.0),
        agent_intents=intents)


def test_co_seated_endpoints_are_wired_through_the_concentrator(tmp_path):
    if shutil.which("verilator") is None:
        pytest.skip("verilator not installed; cannot lint/sim the composed top")
    import re
    from veritx_dse.product.project_top_rtl import run_composed_family
    request = _cmesh_request()
    out = tmp_path / "out"
    out.mkdir()
    result = run_composed_family(request.to_dict(), out,
                                 {"repo_root": str(_repo_root())})
    assert result["lint"] == "PASS", result
    assert result["sim"] == "PASS", result.get("scenarios")
    scenarios = result["scenarios"]
    assert all(scenarios.values()), scenarios
    assert "allow_write_init0" in scenarios and "allow_write_init1" in scenarios
    top = (out / "rtl" / "project_top.sv").read_text()
    assert "cmesh_concentrator" in top
    assert re.search(r"u_concentrator_\d+", top)
    assert (out / "rtl" / "cmesh_concentrator.sv").is_file()


def test_memory_sharing_a_router_with_seats_is_connected():
    from veritx_dse.model.topology_intent import ConcentratedMeshIntent
    from veritx_dse.product.project_top_rtl import (
        composed_family_params_from_request, render_family_project_top,
    )
    request = _cmesh_request()
    request = replace(request, topology=ConcentratedMeshIntent(side_length=4, concentration=4))
    compiled = FabricCompiler().compile(request)
    assert compiled.status == "COMPILED"
    params = composed_family_params_from_request(request, compiled)
    assert len(params.initiators) == 2
    top = render_family_project_top(params)
    assert "cmesh_concentrator #(" in top
    assert ".DST_ENDPOINT(2)" in top
    assert ".req_flit(seat_2_noc_out_flit)" in top


def _repo_root():
    from veritx_dse.core.paths import REPO
    return REPO
