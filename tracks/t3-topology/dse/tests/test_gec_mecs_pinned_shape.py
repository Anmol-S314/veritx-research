from __future__ import annotations

import shutil
from pathlib import Path

import pytest

from veritx_dse.core.paths import REPO
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


def _request(k: int, taps: int):
    workload = WorkloadV3(
        model_family=ModelFamily.DENSE_TRANSFORMER, tp=1, pp=1, ep=1, dp=1,
        collectives=(CollectiveIntent(
            kind=CollectiveKind.ALLREDUCE, dimension=CollectiveDimension.TP,
            payload_bytes=8192, traffic_class="tp_collective"),))
    agents = (
        Agent(kind=AgentKind.COMPUTE_TILE, count=1, data_width=32, addr_width=64,
              protocol="AXI", clock_domain="noc_clk", power_domain="pd0"),
        Agent(kind=AgentKind.HBM_CONTROLLER, count=1, data_width=32, addr_width=64,
              protocol="AXI", clock_domain="noc_clk", power_domain="pd0"),
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
        topology=GecTopologyIntent(mode=GecMode.MULTIDROP, grid_side_length=k,
                                   concentration=1,
                                   express_channel_groups_per_dimension=1,
                                   destinations_per_express_channel=taps),
        address_map=AddressMap(ranges=(AddressRange(
            name="HBM0", base=0x1000, size=0x1000, target_agent_idx=1),)),
        physical=PhysicalContext(default_clock_freq_mhz=1000.0),
        agent_intents=intents)


@pytest.mark.skipif(shutil.which("verilator") is None,
                    reason="verilator not installed; cannot lint/sim the shared top")
def test_product_shared_path_emits_the_pinned_full_size_shape(tmp_path):
    from veritx_dse.product import project_top_rtl
    request = _request(9, 8)
    out = tmp_path / "shared"
    out.mkdir(parents=True)
    result = project_top_rtl.run_gec_mecs_shared(
        request.to_dict(), out, {"repo_root": str(REPO)})
    assert result["lint"] == "PASS", result
    assert result["sim"] == "PASS", result.get("scenarios")
    scenarios = result["scenarios"]
    assert all(scenarios.values()), scenarios
    params = result["family_params"]
    assert params["router_count"] == 81
    assert params["shared_wires"] == 162
    assert params["taps_per_wire"] == 8
    assert params["num_vcs"] == 8
