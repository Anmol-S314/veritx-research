from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

from veritx_dse.core.paths import REPO

TB = REPO / "tracks" / "t3-topology" / "rtl" / "axi5" / "tb_axi5_adapter.sv"

EXPECTED_LINES = (
    "PASS: S1 single-beat write with full AXI5 attribute forwarding and one B response",
    "PASS: S2 four-beat burst write with WLAST on the final beat",
    "PASS: S3 read address forwarded, one R beat with RLAST and the right ID",
    "PASS: S4 the adapter holds its write beat stable while the fabric stalls",
    "PASS: S5 the adapter refuses more addresses than MAX_OUTSTANDING",
    "PASS: S6 the B response carries the ID of the request that caused it",
    "status: PASS",
)


def _emitted_adapter(tmp_path: Path) -> Path:
    """The adapter exactly as the product emits it."""
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
    from veritx_dse.product import rtl_export
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
    request = CompileRequestV4(
        workload=workload, agents=agents, dependencies=DependencyGraph(()),
        topology=MeshIntent(side_length=2, concentration=1),
        address_map=AddressMap(ranges=(AddressRange(
            name="HBM0", base=0x1000, size=0x1000, target_agent_idx=1),)),
        physical=PhysicalContext(default_clock_freq_mhz=1000.0),
        agent_intents=intents)
    out = tmp_path / "preview"
    out.mkdir(parents=True)
    rtl_export.run_rtl_preview(request.to_dict(), out, {"repo_root": str(REPO)})
    adapter = out / "rtl" / "adapter_axi5_g0.sv"
    assert adapter.is_file(), sorted(p.name for p in (out / "rtl").iterdir())
    return adapter


@pytest.mark.skipif(shutil.which("verilator") is None,
                    reason="verilator not installed; cannot lint/sim the adapter")
def test_emitted_axi5_adapter_meets_its_feature_claims(tmp_path):
    """Directed AXI5 feature suite over the adapter the product emits.

    Proves the claims the product makes about this adapter: full AW
    attribute forwarding (ID, EXCLUSIVE, ATOMIC, DVM type, QoS), burst
    handling with WLAST, read data with RLAST, output stability under
    backpressure, the outstanding limit, and per-ID response attribution.
    It is a directed feature suite, not an ARM AXI5 VIP compliance run.
    """
    adapter = _emitted_adapter(tmp_path)
    work = tmp_path / "axi5"
    work.mkdir()
    shutil.copy(adapter, work / adapter.name)
    shutil.copy(TB, work / TB.name)
    lint = subprocess.run(
        ["verilator", "--lint-only", "--timing", "-sv", "-Wall", "-Wno-fatal",
         "-Wno-WIDTH", "-Wno-DECLFILENAME", "--top-module",
         "tb_axi5_adapter", adapter.name, TB.name],
        cwd=work, capture_output=True, text=True, timeout=600)
    assert lint.returncode == 0, (lint.stdout[-3000:] + lint.stderr[-3000:])
    build = subprocess.run(
        ["verilator", "--binary", "--timing", "-Wall", "-Wno-fatal", "-Wno-WIDTH",
         "-Wno-DECLFILENAME", "--top-module", "tb_axi5_adapter",
         "--Mdir", "obj", adapter.name, TB.name],
        cwd=work, capture_output=True, text=True, timeout=1200)
    assert build.returncode == 0, (build.stdout[-3000:] + build.stderr[-3000:])
    sim = subprocess.run(["./obj/Vtb_axi5_adapter"], cwd=work,
                         capture_output=True, text=True, timeout=300)
    output = (sim.stdout or "") + (sim.stderr or "")
    for line in EXPECTED_LINES:
        assert line in output, (line, output[-3000:])
    assert "FAIL:" not in output, output[-3000:]
