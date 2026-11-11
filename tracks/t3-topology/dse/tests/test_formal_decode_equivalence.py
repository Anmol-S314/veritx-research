from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

from veritx_dse.core.paths import REPO

FORMAL_DIR = REPO / "tracks" / "t3-topology" / "rtl" / "formal"
HARNESS = FORMAL_DIR / "addr_decode_formal.sv"
SBY = FORMAL_DIR / "addr_decode_formal.sby"


def _emitted_decoder(tmp_path: Path) -> Path:
    from veritx_dse.model.compile_model import (
        AddressMap, AddressRange, Agent, AgentKind, CollectiveDimension,
        CollectiveIntent, CollectiveKind, DependencyGraph, ModelFamily,
        PhysicalContext, WorkloadV3,
    )
    from veritx_dse.model.compile_request_v4 import CompileRequestV4
    from veritx_dse.model.topology_intent import MeshIntent
    from veritx_dse.model.agent_intent_v4 import (
        AgentIntentV4, OrderingMode, PermissionWindow, ProtocolFamily,
    )
    from veritx_dse.application.fabric_compiler import FabricCompiler
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
    compiled = FabricCompiler().compile(request)
    assert compiled.status == "COMPILED", compiled.error
    out = tmp_path / "preview"
    out.mkdir(parents=True)
    rtl_export.run_rtl_preview(request.to_dict(), out, {"repo_root": str(REPO)})
    return out / "rtl" / "addr_decode.sv"


@pytest.mark.skipif(shutil.which("sby") is None or shutil.which("yosys") is None
                    or shutil.which("z3") is None,
                    reason="formal toolchain (sby/yosys/z3) not installed")
def test_emitted_decoder_is_proven_equivalent_to_the_compiled_contract(tmp_path):
    decoder = _emitted_decoder(tmp_path)
    assert decoder.is_file(), decoder
    work = tmp_path / "formal"
    work.mkdir()
    shutil.copy(decoder, work / "addr_decode.sv")
    shutil.copy(HARNESS, work / "addr_decode_formal.sv")
    shutil.copy(SBY, work / "addr_decode_formal.sby")
    run = subprocess.run(["sby", "-f", "addr_decode_formal.sby"], cwd=work,
                         capture_output=True, text=True, timeout=1800)
    assert run.returncode == 0, (run.stdout[-4000:] + run.stderr[-4000:])
    assert "DONE (PASS" in run.stdout, run.stdout[-2000:]
