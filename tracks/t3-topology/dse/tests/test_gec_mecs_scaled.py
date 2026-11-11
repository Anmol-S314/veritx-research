from __future__ import annotations

import shutil
import subprocess
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
from veritx_dse.application.fabric_compiler import FabricCompiler
from veritx_dse.product import gec_mecs_scaled as scaled


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


def _shape(k: int, taps: int):
    request = _request(k, taps)
    compiled = FabricCompiler().compile(request)
    assert compiled.status == "COMPILED", compiled.error
    return request, compiled, scaled.scaled_mecs_params(request, compiled)


def test_scaled_shape_comes_from_the_bundle_not_from_a_constant():
    _, compiled, params = _shape(3, 2)
    assert params.router_count == 9
    assert params.shared_wires == 18
    assert params.taps_per_wire == 2
    assert params.dest_w == 4
    assert params.ports == 1 + 2 * (3 - 1)
    assert scaled.pair_count(params) == params.router_count ** 2


def test_pinned_full_size_shape_is_derivable():
    _, compiled, params = _shape(9, 8)
    assert params.router_count == 81
    assert params.shared_wires == 162
    assert params.taps_per_wire == 8
    assert params.dest_w == 7
    assert params.ports == 17


@pytest.mark.parametrize(("k", "taps"), [(3, 2), (6, 5)])
def test_scaled_fabric_lints_and_simulates(tmp_path, k, taps):
    if shutil.which("verilator") is None:
        pytest.skip("verilator not installed; cannot lint/sim the scaled fabric")
    _, compiled, params = _shape(k, taps)
    assert params.router_count == k * k
    assert params.shared_wires == 2 * k * k
    assert params.taps_per_wire == taps
    assert params.num_vcs == taps
    out = tmp_path / "rtl"
    out.mkdir(parents=True)
    (out / "fabric.sv").write_text(scaled.render_scaled_fabric(params))
    (out / "tb.sv").write_text(scaled.render_scaled_tb(params))
    # The proven credit pool travels in its own file: the fabric instantiates
    # it, so a lint of the fabric alone cannot resolve the module.
    from veritx_dse.product.gec_mecs_credited import render_credited_pool
    (out / "tap_credit_pool.sv").write_text(render_credited_pool())
    lint = subprocess.run(
        ["verilator", "--lint-only", "--timing", "-sv", "-Wall", "-Wno-fatal",
         "-Wno-WIDTH", "-Wno-PINNOTFOUND", "-Wno-UNOPTFLAT", "-Wno-DECLFILENAME",
         "--top-module", "tb_%s" % scaled.MODULE_NAME, "fabric.sv", "tb.sv",
         "tap_credit_pool.sv"],
        cwd=out, capture_output=True, text=True, timeout=900)
    assert lint.returncode == 0, (lint.stdout[-3000:] + lint.stderr[-3000:])
    warnings = lint.stdout + lint.stderr
    assert "%Warning-LATCH" not in warnings, warnings[-3000:]
    assert "%Warning-UNDRIVEN" not in warnings, warnings[-3000:]
    build = subprocess.run(
        ["verilator", "--binary", "--timing", "-Wall", "-Wno-fatal", "-Wno-WIDTH",
         "-Wno-DECLFILENAME", "--top-module", "tb_%s" % scaled.MODULE_NAME,
         "--Mdir", "obj", "fabric.sv", "tb.sv", "tap_credit_pool.sv"],
        cwd=out, capture_output=True, text=True, timeout=1800)
    assert build.returncode == 0, (build.stdout[-3000:] + build.stderr[-3000:])
    sim = subprocess.run(["./obj/Vtb_%s" % scaled.MODULE_NAME], cwd=out,
                         capture_output=True, text=True, timeout=600)
    output = (sim.stdout or "") + (sim.stderr or "")
    assert "status: PASS" in output, output[-2000:]
    assert "PASS gec_mecs16" in output, output[-2000:]
    assert f"all_pairs={params.router_count ** 2}" in output, output[-2000:]
    assert "row_then_col=" in output, output[-2000:]
    # C4: HEAD/BODY/TAIL must arrive in order and count as one packet;
    # contention and reset recovery are part of the same framing contract.
    assert "PASS gec_mecs16 multi_flit" in output, output[-2000:]
    if params.taps_per_wire >= 3:
        assert "PASS gec_mecs16 multi_flit_contention" in output, output[-2000:]
        assert "PASS gec_mecs16 reset_recovery" in output, output[-2000:]
    assert "credit_accounting" in output, output[-2000:]
    assert "simultaneous_row_returns" in output, output[-2000:]
    assert "FAIL:" not in output, output[-2000:]


def test_pinned_shape_lints_at_full_size(tmp_path):
    if shutil.which("verilator") is None:
        pytest.skip("verilator not installed; cannot lint the scaled fabric")
    _, compiled, params = _shape(9, 8)
    out = tmp_path / "rtl"
    out.mkdir(parents=True)
    (out / "fabric.sv").write_text(scaled.render_scaled_fabric(params))
    from veritx_dse.product.gec_mecs_credited import render_credited_pool
    (out / "tap_credit_pool.sv").write_text(render_credited_pool())
    lint = subprocess.run(
        ["verilator", "--lint-only", "--timing", "-sv", "-Wall", "-Wno-fatal",
         "-Wno-WIDTH", "-Wno-PINNOTFOUND", "-Wno-UNOPTFLAT", "-Wno-DECLFILENAME",
         "--top-module", scaled.MODULE_NAME, "fabric.sv", "tap_credit_pool.sv"],
        cwd=out, capture_output=True, text=True, timeout=1800)
    assert lint.returncode == 0, (lint.stdout[-3000:] + lint.stderr[-3000:])


def test_credit_admission_stalls_when_first_hop_pools_are_empty(tmp_path):
    """The injection allocator refuses a packet with no first-hop credit.

    Rendered with capacity 1 (the one setting where the wire path depth
    lets a (tap, VC) pool provably reach zero while the destination is
    stalled). The scenario injects NUM_VCS*CAPACITY flits to one
    destination, verifies further flits are NOT admitted while every
    first-hop (tap, VC) pool is empty, then releases the destination and
    requires the held flit to drain with no injection errors.
    """
    if shutil.which("verilator") is None:
        pytest.skip("verilator not installed; cannot lint/sim the scaled fabric")
    _, compiled, params = _shape(3, 2)
    assert params.num_vcs == 2
    out = tmp_path / "rtl"
    out.mkdir(parents=True)
    (out / "fabric.sv").write_text(
        scaled.render_scaled_fabric(params, credit_capacity=1))
    (out / "tb.sv").write_text(
        scaled.render_scaled_tb(params, credit_capacity=1, admission_scenario=True))
    from veritx_dse.product.gec_mecs_credited import render_credited_pool
    (out / "tap_credit_pool.sv").write_text(render_credited_pool())
    lint = subprocess.run(
        ["verilator", "--lint-only", "--timing", "-sv", "-Wall", "-Wno-fatal",
         "-Wno-WIDTH", "-Wno-PINNOTFOUND", "-Wno-UNOPTFLAT", "-Wno-DECLFILENAME",
         "--top-module", "tb_%s" % scaled.MODULE_NAME, "fabric.sv", "tb.sv",
         "tap_credit_pool.sv"],
        cwd=out, capture_output=True, text=True, timeout=900)
    assert lint.returncode == 0, (lint.stdout[-3000:] + lint.stderr[-3000:])
    build = subprocess.run(
        ["verilator", "--binary", "--timing", "-Wall", "-Wno-fatal", "-Wno-WIDTH",
         "-Wno-DECLFILENAME", "--top-module", "tb_%s" % scaled.MODULE_NAME,
         "--Mdir", "obj", "fabric.sv", "tb.sv", "tap_credit_pool.sv"],
        cwd=out, capture_output=True, text=True, timeout=1800)
    assert build.returncode == 0, (build.stdout[-3000:] + build.stderr[-3000:])
    sim = subprocess.run(["./obj/Vtb_%s" % scaled.MODULE_NAME], cwd=out,
                         capture_output=True, text=True, timeout=600)
    output = (sim.stdout or "") + (sim.stderr or "")
    assert "PASS gec_mecs16 credit_admission" in output, output[-2000:]
    assert "FAIL:" not in output, output[-2000:]
