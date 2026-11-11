"""M4 CHI / TileLink / custom adapters: real RTL, lint, hash-diff, smoke.

Each family ships a real FULL shim from AdapterFactory —
never a pass-through stub. Checks per family: Verilator lint PASS-clean,
hash-diff on param change, BookSim-side smoke (PASS or typed NOT_RUN,
never silent), rtl_support no longer refuses the family, and FULL
limits recorded in the preview manifest with final_implementation=False.
Custom without a declared burst/ordering param is INVALID at compile.
"""
from __future__ import annotations

import hashlib
import json
import shutil
import subprocess
from pathlib import Path

import pytest

from veritx_dse.application.fabric_compiler import FabricCompiler
from veritx_dse.application.views import topology_view
from veritx_dse.core.paths import REPO
from veritx_dse.model.agent_intent_v4 import (
    AgentIntentV4, OrderingMode, ProtocolFamily,
)
from veritx_dse.model.compile_model import (
    AddressMap, AddressRange, Agent, AgentKind, CollectiveDimension,
    CollectiveIntent, CollectiveKind, DependencyGraph, ModelFamily,
    WorkloadV3,
)
from veritx_dse.model.compile_request_v4 import CompileRequestV4
from veritx_dse.model.topology_intent import MeshIntent
from veritx_dse.product.adapter_factory_rtl import (
    AdapterParams, build_adapter, run_adapter_booksim_smoke,
)
from veritx_dse.product.catalog_evaluation import rtl_support
from veritx_dse.product.rtl_export import run_rtl_preview

_VERILATOR = shutil.which("verilator")


def _request(**kwargs) -> CompileRequestV4:
    workload = WorkloadV3(
        model_family=ModelFamily.DENSE_TRANSFORMER, tp=2, pp=1, ep=1, dp=1,
        collectives=(CollectiveIntent(
            kind=CollectiveKind.ALLREDUCE, dimension=CollectiveDimension.TP,
            payload_bytes=8192, traffic_class="tp_collective"),))
    args = dict(
        workload=workload,
        agents=(Agent(kind=AgentKind.COMPUTE_TILE, count=3),
                Agent(kind=AgentKind.HBM_CONTROLLER, count=1)),
        dependencies=DependencyGraph(()),
        topology=MeshIntent(side_length=2, concentration=1),
        address_map=AddressMap(ranges=(
            AddressRange(name="HBM0", base=0x1000, size=0x1000,
                         target_agent_idx=1),)),
    )
    args.update(kwargs)
    return CompileRequestV4(**args)


def _sha(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()


def _lint(tmp_path: Path, files: list[str], top: str):
    assert _VERILATOR is not None
    checked = subprocess.run(
        [_VERILATOR, "--lint-only", "-sv", "-Wall", "-Wno-fatal",
         "-Wno-WIDTH", "-Wno-PINNOTFOUND", "-Wno-UNOPTFLAT",
         "--top-module", top, *files],
        cwd=tmp_path, capture_output=True, text=True)
    log = checked.stdout + checked.stderr
    assert checked.returncode == 0, log
    assert "%Warning" not in log, log


# --- emission shape ------------------------------------------------------


def test_chi_emits_full_profile_named_scope():
    build = build_adapter(AdapterParams(
        agent_idx=0, protocol=ProtocolFamily.CHI, data_width=256,
        addr_width=64, max_outstanding=16, ordering="strong"))
    assert build.verdict.ok is True
    assert build.module == "adapter_chi_g0"
    source = build.source or ""
    assert "module adapter_chi_g0" in source
    # Full-Profile scope named in the header (supported vs CT/legacy).
    for token in ("REQ", "RSP", "SNP", "DAT", "MAX_SIZE", "out_req_ch",
                  "aligned", "Srota Native Stream", "Full-Profile",
                  "CT/legacy", "not claimed", "final_implementation"):
        assert token in source, token
    # Implemented Full-Profile features (real logic, never a stub).
    for token in ("DVM", "RSOS", "QoS", "P_CREDIT_MAX", "P-Credit",
                  "coheren", "out_dvm_valid", "out_rsos_valid",
                  "out_req_qos", "out_req_c", "pcredit_count",
                  "pcredit_full", "coh_state", "coh_error",
                  "DWT", "Expiry", "dwt_active", "expiry_fired",
                  "qos_high", "dvm_pending", "rsos_pending",
                  "QOS_THRESHOLD", "DWT_TIMEOUT", "EXPIRY_TIMEOUT",
                  "COH_INIT", "DVM_ENABLE", "RSOS_ENABLE"):
        assert token in source, token
    # Real logic (state + credit), not a stub.
    assert "busy_q" in source and "outstanding_q" in source
    assert "pass-through" not in source.lower() or "NOT" in source
    assert build_adapter(AdapterParams(
        agent_idx=0, protocol=ProtocolFamily.CHI, data_width=256,
        addr_width=64, max_outstanding=16, ordering="strong")).source == source


def test_chi_full_profile_defaults_and_knob_rendering():
    default = build_adapter(AdapterParams(
        agent_idx=0, protocol=ProtocolFamily.CHI))
    assert default.verdict.ok is True
    source = default.source or ""
    for token in ("P_CREDIT_MAX = 16", "QOS_THRESHOLD = 8",
                  "DWT_TIMEOUT = 64", "EXPIRY_TIMEOUT = 64",
                  "COH_INIT = 0", "DVM_ENABLE = 1", "RSOS_ENABLE = 1"):
        assert token in source, token
    tuned = build_adapter(AdapterParams(
        agent_idx=0, protocol=ProtocolFamily.CHI, chi_qos=12,
        chi_pcredit_max=4, chi_dwt_timeout=8, chi_expiry_timeout=9,
        chi_coh_init=2, chi_dvm_enable=False, chi_rsos_enable=False))
    assert tuned.verdict.ok is True
    tuned_source = tuned.source or ""
    for token in ("P_CREDIT_MAX = 4", "QOS_THRESHOLD = 12",
                  "DWT_TIMEOUT = 8", "EXPIRY_TIMEOUT = 9",
                  "COH_INIT = 2", "DVM_ENABLE = 0", "RSOS_ENABLE = 0"):
        assert token in tuned_source, token
    assert _sha(source) != _sha(tuned_source)


def test_chi_invalid_params_are_typed_never_clamped():
    cases = [
        AdapterParams(agent_idx=0, protocol=ProtocolFamily.CHI, chi_qos=16),
        AdapterParams(agent_idx=0, protocol=ProtocolFamily.CHI, chi_qos=-1),
        AdapterParams(agent_idx=0, protocol=ProtocolFamily.CHI,
                      chi_pcredit_max=0),
        AdapterParams(agent_idx=0, protocol=ProtocolFamily.CHI,
                      chi_pcredit_max=257),
        AdapterParams(agent_idx=0, protocol=ProtocolFamily.CHI,
                      chi_dwt_timeout=0),
        AdapterParams(agent_idx=0, protocol=ProtocolFamily.CHI,
                      chi_expiry_timeout=0),
        AdapterParams(agent_idx=0, protocol=ProtocolFamily.CHI,
                      chi_coh_init=5),
        AdapterParams(agent_idx=0, protocol=ProtocolFamily.CHI,
                      chi_coh_init=-1),
        AdapterParams(agent_idx=0, protocol=ProtocolFamily.CHI,
                      chi_dvm_enable=1),
        AdapterParams(agent_idx=0, protocol=ProtocolFamily.CHI,
                      chi_rsos_enable="yes"),
        AdapterParams(agent_idx=0, protocol=ProtocolFamily.AXI5,
                      split_at=64, chi_qos=8),
    ]
    for params in cases:
        build = build_adapter(params)
        assert build.verdict.ok is False, params
        assert build.verdict.status == "INVALID"
        assert build.verdict.blocker_id == "ADAPTER_INVALID_PARAMS"
        assert build.module is None and build.source is None


def test_tilelink_emits_ul_framing_per_nic_conventions():
    build = build_adapter(AdapterParams(
        agent_idx=0, protocol=ProtocolFamily.TILELINK, data_width=256,
        addr_width=64, max_outstanding=16, ordering="strong"))
    assert build.verdict.ok is True
    assert build.module == "adapter_tilelink_g0"
    source = build.source or ""
    assert "TileLink-UL" in source
    # A/D framing + nic.sv head/tail conventions.
    for token in ("in_a_opcode", "in_a_size", "in_a_mask", "out_a_head",
                  "out_a_tail", "in_d_opcode", "out_d_head", "out_d_tail"):
        assert token in source, token
    assert "nic.sv" in source
    assert "busy_q" in source and "outstanding_q" in source


def test_custom_emits_only_declared_burst_or_ordering():
    burst = build_adapter(AdapterParams(
        agent_idx=0, protocol=ProtocolFamily.CUSTOM, split_at=64))
    assert burst.verdict.ok is True
    assert "BURST_AT = 64" in (burst.source or "")
    assert "burst declared only" in (burst.source or "")
    ordering = build_adapter(AdapterParams(
        agent_idx=0, protocol=ProtocolFamily.CUSTOM, ordering="strong"))
    assert ordering.verdict.ok is True
    assert "ORDERING_MODE = 1" in (ordering.source or "")
    assert "ordering declared only" in (ordering.source or "")
    both = build_adapter(AdapterParams(
        agent_idx=0, protocol=ProtocolFamily.CUSTOM, split_at=32,
        ordering="relaxed", max_outstanding=8))
    assert both.verdict.ok is True
    assert "BURST_AT = 32" in (both.source or "")
    assert "ORDERING_MODE = 2" in (both.source or "")


def test_custom_without_params_is_invalid_never_a_default():
    build = build_adapter(AdapterParams(
        agent_idx=0, protocol=ProtocolFamily.CUSTOM))
    assert build.verdict.ok is False
    assert build.verdict.status == "INVALID"
    assert build.verdict.blocker_id == "ADAPTER_INVALID_PARAMS"
    assert "burst" in (build.verdict.reason or "")
    assert build.module is None and build.source is None
    # Compile enforces the same INVALID at PACKET_FORMAT.
    compilation = FabricCompiler().compile(_request(agent_intents=(
        AgentIntentV4(0, protocol=ProtocolFamily.CUSTOM),)))
    assert compilation.status == "INVALID"
    assert compilation.stopped_at_stage == "PACKET_FORMAT"
    assert "burst" in (compilation.error or "")


def test_chi_tilelink_split_at_is_invalid_custom_split_at_is_burst():
    chi = FabricCompiler().compile(_request(agent_intents=(
        AgentIntentV4(0, protocol=ProtocolFamily.CHI, split_at=64),)))
    assert chi.status == "INVALID"
    assert chi.stopped_at_stage == "PACKET_FORMAT"
    tl = FabricCompiler().compile(_request(agent_intents=(
        AgentIntentV4(0, protocol=ProtocolFamily.TILELINK, split_at=64),)))
    assert tl.status == "INVALID"
    assert tl.stopped_at_stage == "PACKET_FORMAT"
    custom = FabricCompiler().compile(_request(agent_intents=(
        AgentIntentV4(0, protocol=ProtocolFamily.CUSTOM, split_at=64),)))
    assert custom.status == "COMPILED"


# --- lint + hash-diff ----------------------------------------------------


@pytest.mark.skipif(_VERILATOR is None, reason="verilator not installed")
@pytest.mark.parametrize("params", [
    AdapterParams(agent_idx=0, protocol=ProtocolFamily.CHI),
    AdapterParams(agent_idx=0, protocol=ProtocolFamily.CHI, data_width=64,
                  addr_width=32, max_outstanding=1, ordering="raw"),
    AdapterParams(agent_idx=2, protocol=ProtocolFamily.CHI, data_width=512,
                  addr_width=48, max_outstanding=32, ordering="relaxed"),
    AdapterParams(agent_idx=0, protocol=ProtocolFamily.CHI, data_width=64,
                  addr_width=32, ordering="raw", chi_qos=12,
                  chi_pcredit_max=4, chi_dwt_timeout=8,
                  chi_expiry_timeout=8, chi_coh_init=2,
                  chi_dvm_enable=False, chi_rsos_enable=False),
    AdapterParams(agent_idx=1, protocol=ProtocolFamily.CHI, data_width=128,
                  addr_width=40, ordering="strong", chi_qos=0,
                  chi_pcredit_max=256, chi_dwt_timeout=1,
                  chi_expiry_timeout=1024, chi_coh_init=4,
                  chi_dvm_enable=True, chi_rsos_enable=True),
    AdapterParams(agent_idx=0, protocol=ProtocolFamily.CHI,
                  chi_reorder_depth=1, chi_ct_enable=False),
    AdapterParams(agent_idx=0, protocol=ProtocolFamily.CHI,
                  chi_reorder_depth=16, chi_ct_enable=True,
                  ordering="strong"),
    AdapterParams(agent_idx=0, protocol=ProtocolFamily.TILELINK),
    AdapterParams(agent_idx=1, protocol=ProtocolFamily.TILELINK,
                  data_width=64, addr_width=32, max_outstanding=8,
                  ordering="raw"),
    AdapterParams(agent_idx=0, protocol=ProtocolFamily.TILELINK,
                  data_width=512, ordering="relaxed", max_outstanding=4),
    AdapterParams(agent_idx=0, protocol=ProtocolFamily.CUSTOM, split_at=64),
    AdapterParams(agent_idx=0, protocol=ProtocolFamily.CUSTOM,
                  ordering="strong"),
    AdapterParams(agent_idx=0, protocol=ProtocolFamily.CUSTOM, split_at=32,
                  ordering="relaxed", max_outstanding=8, data_width=128),
])
def test_new_adapters_lint_clean(params, tmp_path):
    build = build_adapter(params)
    assert build.module is not None and build.source is not None
    (tmp_path / f"{build.module}.sv").write_text(build.source)
    _lint(tmp_path, [f"{build.module}.sv"], build.module)


@pytest.mark.parametrize("family, kwargs_a, kwargs_b", [
    (ProtocolFamily.CHI, dict(max_outstanding=16), dict(max_outstanding=8)),
    (ProtocolFamily.CHI, dict(ordering="strong"), dict(ordering="raw")),
    (ProtocolFamily.CHI, dict(chi_qos=8), dict(chi_qos=12)),
    (ProtocolFamily.CHI, dict(chi_pcredit_max=16),
     dict(chi_pcredit_max=4)),
    (ProtocolFamily.CHI, dict(chi_dwt_timeout=64),
     dict(chi_dwt_timeout=8)),
    (ProtocolFamily.CHI, dict(chi_expiry_timeout=64),
     dict(chi_expiry_timeout=9)),
    (ProtocolFamily.CHI, dict(chi_coh_init=0), dict(chi_coh_init=2)),
    (ProtocolFamily.CHI, dict(chi_dvm_enable=True),
     dict(chi_dvm_enable=False)),
    (ProtocolFamily.CHI, dict(chi_rsos_enable=True),
     dict(chi_rsos_enable=False)),
    (ProtocolFamily.CHI, dict(chi_reorder_depth=4),
     dict(chi_reorder_depth=2)),
    (ProtocolFamily.CHI, dict(chi_ct_enable=True),
     dict(chi_ct_enable=False)),
    (ProtocolFamily.TILELINK, dict(max_outstanding=16),
     dict(max_outstanding=8)),
    (ProtocolFamily.CUSTOM, dict(split_at=64), dict(split_at=32)),
    (ProtocolFamily.CUSTOM, dict(ordering="strong"),
     dict(ordering="raw")),
])
def test_hash_diff_when_params_change(family, kwargs_a, kwargs_b):
    a = build_adapter(AdapterParams(agent_idx=0, protocol=family,
                                    **kwargs_a))
    b = build_adapter(AdapterParams(agent_idx=0, protocol=family,
                                    **kwargs_b))
    assert a.source is not None and b.source is not None
    assert _sha(a.source) != _sha(b.source)
    assert _sha(build_adapter(AdapterParams(
        agent_idx=0, protocol=family, **kwargs_a)).source or "") \
        == _sha(a.source)


# --- directed TB per channel (Verilator --binary --timing) ---------------

_CHI_FULL_BUILD_PARAMS = dict(
    data_width=64, addr_width=32, max_outstanding=16, ordering="raw",
    chi_qos=8, chi_pcredit_max=4, chi_dwt_timeout=8, chi_expiry_timeout=8,
    chi_coh_init=0, chi_dvm_enable=True, chi_rsos_enable=True)


def _run_chi_tb(tmp_path: Path, build, tb_source: str, top: str) -> str:
    assert build.module is not None and build.source is not None
    (tmp_path / f"{build.module}.sv").write_text(build.source)
    (tmp_path / f"{top}.sv").write_text(tb_source)
    checked = subprocess.run(
        [_VERILATOR, "--binary", "--timing", "-Wall", "-Wno-fatal",
         "-Wno-WIDTH", "-Wno-PINNOTFOUND", "-Wno-UNOPTFLAT",
         "-Wno-DECLFILENAME", "--top-module", top, "--Mdir", "obj_chi",
         f"{top}.sv", f"{build.module}.sv"],
        cwd=tmp_path, capture_output=True, text=True, timeout=300)
    assert checked.returncode == 0, (checked.stdout + checked.stderr)[-6000:]
    run = subprocess.run(
        [f"./obj_chi/V{top}"], cwd=tmp_path,
        capture_output=True, text=True, timeout=120)
    log = run.stdout + run.stderr
    assert "status: PASS" in log, log[-8000:]
    return log


_CHI_FULL_TB = r"""
`default_nettype none
module tb_chi_full;
  logic clk;
  logic rst_n;
  logic [31:0] in_req_addr;
  logic [2:0] in_req_size;
  logic [3:0] in_req_opcode;
  logic in_req_valid;
  logic in_req_ready;
  logic [31:0] out_req_addr;
  logic [2:0] out_req_size;
  logic [3:0] out_req_opcode;
  logic [1:0] out_req_ch;
  logic out_req_valid;
  logic out_req_ready;
  logic [63:0] in_dat_data;
  logic [7:0] in_dat_be;
  logic in_dat_valid;
  logic in_dat_ready;
  logic [63:0] out_dat_data;
  logic [7:0] out_dat_be;
  logic out_dat_valid;
  logic out_dat_ready;
  logic rsp_valid;
  logic rsp_ready;
  logic out_rsp_valid;
  logic out_rsp_ready;
  logic [3:0] out_rsp_opcode;
  logic out_snp_valid;
  logic out_snp_ready;
  logic [31:0] out_snp_addr;
  logic credit_full;
  logic size_error;
  logic order_violation;
  logic [3:0] in_req_qos;
  logic in_req_c;
  logic in_req_dwt;
  logic in_req_expiry;
  logic [2:0] in_req_comp_state;
  logic [3:0] rsp_opcode;
  logic rsp_pcredit;
  logic [2:0] rsp_comp_state;
  logic out_dvm_ready;
  logic out_rsos_ready;
  logic [3:0] out_req_qos;
  logic out_req_c;
  logic out_req_dwt;
  logic out_req_expiry;
  logic [2:0] out_req_comp_state;
  logic [2:0] out_rsp_comp_state;
  logic out_dvm_valid;
  logic out_rsos_valid;
  logic [8:0] pcredit_count;
  logic pcredit_full;
  logic pcredit_overflow;
  logic pcredit_underflow;
  logic [2:0] coh_state;
  logic coh_error;
  logic dwt_active;
  logic dwt_cancel;
  logic dwt_error;
  logic expiry_active;
  logic expiry_fired;
  logic qos_high;
  logic dvm_pending;
  logic rsos_pending;

  adapter_chi_g0 dut (
    .clk(clk), .rst_n(rst_n),
    .in_req_addr(in_req_addr), .in_req_size(in_req_size),
    .in_req_opcode(in_req_opcode), .in_req_valid(in_req_valid),
    .in_req_ready(in_req_ready),
    .out_req_addr(out_req_addr), .out_req_size(out_req_size),
    .out_req_opcode(out_req_opcode), .out_req_ch(out_req_ch),
    .out_req_valid(out_req_valid), .out_req_ready(out_req_ready),
    .in_dat_data(in_dat_data), .in_dat_be(in_dat_be),
    .in_dat_valid(in_dat_valid), .in_dat_ready(in_dat_ready),
    .out_dat_data(out_dat_data), .out_dat_be(out_dat_be),
    .out_dat_valid(out_dat_valid), .out_dat_ready(out_dat_ready),
    .rsp_valid(rsp_valid), .rsp_ready(rsp_ready),
    .out_rsp_valid(out_rsp_valid), .out_rsp_ready(out_rsp_ready),
    .out_rsp_opcode(out_rsp_opcode),
    .out_snp_valid(out_snp_valid), .out_snp_ready(out_snp_ready),
    .out_snp_addr(out_snp_addr),
    .credit_full(credit_full), .size_error(size_error),
    .order_violation(order_violation),
    .in_req_qos(in_req_qos), .in_req_c(in_req_c),
    .in_req_dwt(in_req_dwt), .in_req_expiry(in_req_expiry),
    .in_req_comp_state(in_req_comp_state), .rsp_opcode(rsp_opcode),
    .rsp_pcredit(rsp_pcredit), .rsp_comp_state(rsp_comp_state),
    .out_dvm_ready(out_dvm_ready), .out_rsos_ready(out_rsos_ready),
    .out_req_qos(out_req_qos), .out_req_c(out_req_c),
    .out_req_dwt(out_req_dwt), .out_req_expiry(out_req_expiry),
    .out_req_comp_state(out_req_comp_state),
    .out_rsp_comp_state(out_rsp_comp_state),
    .out_dvm_valid(out_dvm_valid), .out_rsos_valid(out_rsos_valid),
    .pcredit_count(pcredit_count), .pcredit_full(pcredit_full),
    .pcredit_overflow(pcredit_overflow),
    .pcredit_underflow(pcredit_underflow), .coh_state(coh_state),
    .coh_error(coh_error), .dwt_active(dwt_active),
    .dwt_cancel(dwt_cancel), .dwt_error(dwt_error),
    .expiry_active(expiry_active), .expiry_fired(expiry_fired),
    .qos_high(qos_high), .dvm_pending(dvm_pending),
    .rsos_pending(rsos_pending)
  );

  always #5 clk = ~clk;
  integer errors;
  integer cycles;
  always @(posedge clk) cycles = cycles + 1;

  task fail_msg;
    input [8*64-1:0] msg;
    begin
      errors = errors + 1;
      $display("FAIL: %0s (cycle %0d)", msg, cycles);
    end
  endtask

  task do_reset;
    begin
      @(negedge clk);
      rst_n = 1'b0;
      repeat (10) @(posedge clk);
      @(negedge clk);
      rst_n = 1'b1;
      repeat (5) @(posedge clk);
    end
  endtask

  task do_req_capture;
    input [31:0] addr;
    input [2:0] size;
    input [3:0] opcode;
    input [3:0] qos;
    input c;
    input dwt;
    input expiry;
    input [2:0] comp;
    integer timeout;
    begin
      @(negedge clk);
      in_req_addr = addr; in_req_size = size; in_req_opcode = opcode;
      in_req_qos = qos; in_req_c = c; in_req_dwt = dwt;
      in_req_expiry = expiry; in_req_comp_state = comp;
      in_req_valid = 1'b1;
      timeout = 0;
      while (!in_req_ready && timeout < 100) begin
        @(posedge clk); timeout = timeout + 1;
        @(negedge clk);
      end
      if (timeout >= 100) fail_msg("do_req_capture timeout");
      @(posedge clk);
      @(negedge clk);
      in_req_valid = 1'b0;
    end
  endtask

  task do_req_emit;
    integer timeout;
    begin
      @(negedge clk);
      out_req_ready = 1'b1;
      timeout = 0;
      while (!out_req_valid && timeout < 100) begin
        @(posedge clk); timeout = timeout + 1;
        @(negedge clk);
      end
      if (timeout >= 100) fail_msg("do_req_emit timeout");
      @(posedge clk);
      @(negedge clk);
      out_req_ready = 1'b0;
    end
  endtask

  task do_rsp;
    input [3:0] opcode;
    input pcredit;
    input [2:0] comp;
    begin
      @(negedge clk);
      rsp_opcode = opcode; rsp_pcredit = pcredit; rsp_comp_state = comp;
      rsp_valid = 1'b1;
      @(posedge clk);
      @(negedge clk);
      rsp_valid = 1'b0;
    end
  endtask

  task do_dat;
    input [63:0] data;
    input [7:0] be;
    begin
      @(negedge clk);
      in_dat_data = data; in_dat_be = be; in_dat_valid = 1'b1;
      @(posedge clk);
      @(negedge clk);
    end
  endtask

  initial begin
    clk = 0; rst_n = 0; errors = 0; cycles = 0;
    in_req_addr = 0; in_req_size = 0; in_req_opcode = 0; in_req_valid = 0;
    in_req_qos = 0; in_req_c = 0; in_req_dwt = 0; in_req_expiry = 0;
    in_req_comp_state = 0;
    out_req_ready = 0; in_dat_data = 0; in_dat_be = 0; in_dat_valid = 0;
    out_dat_ready = 1'b1; rsp_valid = 0; rsp_ready = 1'b1;
    out_rsp_ready = 1'b1; out_snp_ready = 1'b1;
    rsp_opcode = 0; rsp_pcredit = 0; rsp_comp_state = 0;
    out_dvm_ready = 1'b1; out_rsos_ready = 1'b1;
    $display("=== tb_chi_full start ===");
    do_reset;
    if (pcredit_count !== 9'd4) fail_msg("reset pcredit != 4");
    else $display("PASS: reset pcredit=4");
    if (coh_state !== 3'd0) fail_msg("reset coh != 0");
    else $display("PASS: reset coh=0");

    $display("REQ channel: aligned + QoS/C/comp fields");
    do_req_capture(32'h1001, 3'd2, 4'h0, 4'd9, 1'b1, 1'b0, 1'b0, 3'd1);
    @(negedge clk);
    if (!out_req_valid) fail_msg("REQ out_req_valid low");
    else if (out_req_addr !== 32'h1000) fail_msg("REQ aligned addr");
    else $display("PASS: REQ aligned addr=0x1000 ch=0");
    if (out_req_size !== 3'd2) fail_msg("REQ size");
    else $display("PASS: REQ size=2");
    if (out_req_ch !== 2'd0) fail_msg("REQ ch != 0");
    if (out_req_qos !== 4'd9) fail_msg("REQ qos");
    else $display("PASS: REQ QoS=9 qos_high=1");
    if (!qos_high) fail_msg("REQ qos_high low");
    if (out_req_c !== 1'b1) fail_msg("REQ C");
    else $display("PASS: REQ C=1 comp=1");
    if (out_req_comp_state !== 3'd1) fail_msg("REQ comp");
    if (out_dvm_valid || out_rsos_valid) fail_msg("REQ DVM/RSOS spur");
    do_req_emit;
    if (pcredit_count !== 9'd3) fail_msg("REQ emit pcredit != 3");
    else $display("PASS: REQ emit pcredit 4->3");
    do_rsp(4'h1, 1'b1, 3'd2);
    if (pcredit_count !== 9'd4) fail_msg("RSP grant pcredit != 4");
    else $display("PASS: RSP grant pcredit 3->4");
    if (coh_state !== 3'd2) fail_msg("RSP coh != 2");
    else $display("PASS: RSP coh=2 ack=2");
    if (out_rsp_comp_state !== 3'd2) fail_msg("RSP comp ack");

    $display("REQ channel: over-granule SIZE clamp");
    do_req_capture(32'h2000, 3'd7, 4'h0, 4'd0, 1'b0, 1'b0, 1'b0, 3'd0);
    if (out_req_size !== 3'd3) fail_msg("REQ clamp size != 3");
    else $display("PASS: REQ clamp size=3");
    if (!size_error) fail_msg("REQ size_error low");
    else $display("PASS: REQ size_error=1");
    do_req_emit;
    do_rsp(4'h1, 1'b1, 3'd0);

    $display("SNP channel: opcode ch=2");
    do_req_capture(32'h3000, 3'd2, 4'h2, 4'd0, 1'b0, 1'b0, 1'b0, 3'd0);
    if (out_req_ch !== 2'd2) fail_msg("SNP ch != 2");
    else $display("PASS: SNP ch=2");
    if (!out_snp_valid) fail_msg("SNP out_snp_valid low");
    else $display("PASS: SNP out_snp_valid=1");
    if (out_snp_addr !== 32'h3000) fail_msg("SNP addr");
    if (out_rsp_valid) fail_msg("SNP RSP spur");
    do_req_emit;
    do_rsp(4'h1, 1'b1, 3'd0);

    $display("RSP channel: opcode ch=1");
    do_req_capture(32'h4000, 3'd2, 4'h1, 4'd0, 1'b0, 1'b0, 1'b0, 3'd0);
    if (out_req_ch !== 2'd1) fail_msg("RSP ch != 1");
    else $display("PASS: RSP ch=1");
    if (!out_rsp_valid) fail_msg("RSP out_rsp_valid low");
    else $display("PASS: RSP out_rsp_valid=1");
    if (out_rsp_opcode !== 4'h1) fail_msg("RSP opcode");
    if (out_snp_valid) fail_msg("RSP SNP spur");
    do_req_emit;
    do_rsp(4'h1, 1'b1, 3'd1);
    if (coh_state !== 3'd1) fail_msg("RSP coh ack != 1");
    else $display("PASS: RSP coh ack=1");

    $display("DAT channel: BE filter by SIZE=0 (1B mask)");
    do_req_capture(32'h5000, 3'd0, 4'h0, 4'd0, 1'b0, 1'b0, 1'b0, 3'd0);
    do_dat(64'h1122334455667788, 8'hFF);
    if (out_dat_data !== 64'h1122334455667788) fail_msg("DAT data");
    else $display("PASS: DAT data fwd");
    if (out_dat_be !== 8'h01) fail_msg("DAT BE filter");
    else $display("PASS: DAT BE masked to 0x01");
    if (!out_dat_valid) fail_msg("DAT valid low");
    in_dat_valid = 1'b0;
    do_req_emit;
    do_rsp(4'h1, 1'b1, 3'd0);

    $display("DVM class: opcode[3:2]=1 pending/ack");
    do_req_capture(32'h6000, 3'd2, 4'h4, 4'd0, 1'b0, 1'b0, 1'b0, 3'd0);
    if (!out_dvm_valid) fail_msg("DVM out_dvm_valid low");
    else $display("PASS: DVM out_dvm_valid=1");
    if (out_rsos_valid) fail_msg("DVM RSOS spur");
    if (dvm_pending) fail_msg("DVM pending pre-emit");
    do_req_emit;
    if (!dvm_pending) fail_msg("DVM pending post-emit");
    else $display("PASS: DVM pending=1");
    do_rsp(4'h5, 1'b1, 3'd1);
    if (dvm_pending) fail_msg("DVM pending post-ack");
    else $display("PASS: DVM ack clears pending");

    $display("RSOS class: opcode[3:2]=2 pending/ack");
    do_req_capture(32'h7000, 3'd2, 4'h8, 4'd0, 1'b0, 1'b0, 1'b0, 3'd0);
    if (!out_rsos_valid) fail_msg("RSOS out_rsos_valid low");
    else $display("PASS: RSOS out_rsos_valid=1");
    if (out_dvm_valid) fail_msg("RSOS DVM spur");
    do_req_emit;
    if (!rsos_pending) fail_msg("RSOS pending post-emit");
    else $display("PASS: RSOS pending=1");
    do_rsp(4'h9, 1'b1, 3'd1);
    if (rsos_pending) fail_msg("RSOS pending post-ack");
    else $display("PASS: RSOS ack clears pending");

    $display("Coherency: reserved comp state flags error");
    do_req_capture(32'h8000, 3'd2, 4'h0, 4'd0, 1'b0, 1'b0, 1'b0, 3'd7);
    if (!coh_error) fail_msg("coh reserved low");
    else $display("PASS: coh_error reserved=1");
    do_req_emit;
    do_rsp(4'h1, 1'b1, 3'd0);

    $display("C/DWT/Expiry: watchdogs fire at timeout");
    do_req_capture(32'h9000, 3'd2, 4'h0, 4'd0, 1'b0, 1'b1, 1'b1, 3'd0);
    @(negedge clk);
    if (!dwt_active) fail_msg("DWT not active");
    else $display("PASS: DWT active=1");
    if (!expiry_active) fail_msg("Expiry not active");
    repeat (12) @(posedge clk);
    @(negedge clk);
    if (!dwt_cancel) fail_msg("DWT cancel low");
    else $display("PASS: DWT cancel=1");
    if (!dwt_error) fail_msg("DWT error low");
    if (!expiry_fired) fail_msg("Expiry fired low");
    else $display("PASS: Expiry fired=1");
    do_req_emit;
    do_rsp(4'h1, 1'b1, 3'd0);
    @(negedge clk);
    if (dwt_cancel || expiry_fired) fail_msg("watchdog clear");
    else $display("PASS: watchdogs cleared on RSP");

    $display("P-Credit: deplete stalls, grant resumes");
    do_reset;
    do_req_capture(32'hA000, 3'd2, 4'h0, 4'd0, 1'b0, 1'b0, 1'b0, 3'd0);
    do_req_emit;
    do_req_capture(32'hA004, 3'd2, 4'h0, 4'd0, 1'b0, 1'b0, 1'b0, 3'd0);
    do_req_emit;
    do_req_capture(32'hA008, 3'd2, 4'h0, 4'd0, 1'b0, 1'b0, 1'b0, 3'd0);
    do_req_emit;
    do_req_capture(32'hA00C, 3'd2, 4'h0, 4'd0, 1'b0, 1'b0, 1'b0, 3'd0);
    do_req_emit;
    if (!pcredit_full) fail_msg("pcredit full low");
    else $display("PASS: P-Credit full=1");
    if (pcredit_count !== 9'd0) fail_msg("pcredit != 0");
    do_req_capture(32'hA010, 3'd2, 4'h0, 4'd0, 1'b0, 1'b0, 1'b0, 3'd0);
    @(negedge clk);
    out_req_ready = 1'b1;
    repeat (4) @(posedge clk);
    @(negedge clk);
    if (out_req_valid) fail_msg("pcredit stall lifted");
    else $display("PASS: P-Credit stall out_req_valid=0");
    out_req_ready = 1'b0;
    do_rsp(4'h1, 1'b1, 3'd0);
    if (pcredit_count !== 9'd1) fail_msg("grant pcredit != 1");
    else $display("PASS: P-Credit grant 0->1");
    do_req_emit;
    $display("PASS: P-Credit resume");

    in_dat_valid = 1'b0;
    repeat (5) @(posedge clk);
    if (errors == 0) $display("status: PASS");
    else $display("status: FAIL errors=%0d", errors);
    $finish;
  end

  initial begin
    #200000;
    $display("FAIL: global timeout");
    $finish;
  end
endmodule
`default_nettype wire
"""

_CHI_QOS_TB = r"""
`default_nettype none
module tb_chi_qos;
  logic clk;
  logic rst_n;
  logic [31:0] in_req_addr;
  logic [2:0] in_req_size;
  logic [3:0] in_req_opcode;
  logic in_req_valid;
  logic in_req_ready;
  logic [31:0] out_req_addr;
  logic [2:0] out_req_size;
  logic [3:0] out_req_opcode;
  logic [1:0] out_req_ch;
  logic out_req_valid;
  logic out_req_ready;
  logic [63:0] in_dat_data;
  logic [7:0] in_dat_be;
  logic in_dat_valid;
  logic in_dat_ready;
  logic [63:0] out_dat_data;
  logic [7:0] out_dat_be;
  logic out_dat_valid;
  logic out_dat_ready;
  logic rsp_valid;
  logic rsp_ready;
  logic out_rsp_valid;
  logic out_rsp_ready;
  logic [3:0] out_rsp_opcode;
  logic out_snp_valid;
  logic out_snp_ready;
  logic [31:0] out_snp_addr;
  logic credit_full;
  logic size_error;
  logic order_violation;
  logic [3:0] in_req_qos;
  logic in_req_c;
  logic in_req_dwt;
  logic in_req_expiry;
  logic [2:0] in_req_comp_state;
  logic [3:0] rsp_opcode;
  logic rsp_pcredit;
  logic [2:0] rsp_comp_state;
  logic out_dvm_ready;
  logic out_rsos_ready;
  logic [3:0] out_req_qos;
  logic out_req_c;
  logic out_req_dwt;
  logic out_req_expiry;
  logic [2:0] out_req_comp_state;
  logic [2:0] out_rsp_comp_state;
  logic out_dvm_valid;
  logic out_rsos_valid;
  logic [8:0] pcredit_count;
  logic pcredit_full;
  logic pcredit_overflow;
  logic pcredit_underflow;
  logic [2:0] coh_state;
  logic coh_error;
  logic dwt_active;
  logic dwt_cancel;
  logic dwt_error;
  logic expiry_active;
  logic expiry_fired;
  logic qos_high;
  logic dvm_pending;
  logic rsos_pending;

  adapter_chi_g0 dut (
    .clk(clk), .rst_n(rst_n),
    .in_req_addr(in_req_addr), .in_req_size(in_req_size),
    .in_req_opcode(in_req_opcode), .in_req_valid(in_req_valid),
    .in_req_ready(in_req_ready),
    .out_req_addr(out_req_addr), .out_req_size(out_req_size),
    .out_req_opcode(out_req_opcode), .out_req_ch(out_req_ch),
    .out_req_valid(out_req_valid), .out_req_ready(out_req_ready),
    .in_dat_data(in_dat_data), .in_dat_be(in_dat_be),
    .in_dat_valid(in_dat_valid), .in_dat_ready(in_dat_ready),
    .out_dat_data(out_dat_data), .out_dat_be(out_dat_be),
    .out_dat_valid(out_dat_valid), .out_dat_ready(out_dat_ready),
    .rsp_valid(rsp_valid), .rsp_ready(rsp_ready),
    .out_rsp_valid(out_rsp_valid), .out_rsp_ready(out_rsp_ready),
    .out_rsp_opcode(out_rsp_opcode),
    .out_snp_valid(out_snp_valid), .out_snp_ready(out_snp_ready),
    .out_snp_addr(out_snp_addr),
    .credit_full(credit_full), .size_error(size_error),
    .order_violation(order_violation),
    .in_req_qos(in_req_qos), .in_req_c(in_req_c),
    .in_req_dwt(in_req_dwt), .in_req_expiry(in_req_expiry),
    .in_req_comp_state(in_req_comp_state), .rsp_opcode(rsp_opcode),
    .rsp_pcredit(rsp_pcredit), .rsp_comp_state(rsp_comp_state),
    .out_dvm_ready(out_dvm_ready), .out_rsos_ready(out_rsos_ready),
    .out_req_qos(out_req_qos), .out_req_c(out_req_c),
    .out_req_dwt(out_req_dwt), .out_req_expiry(out_req_expiry),
    .out_req_comp_state(out_req_comp_state),
    .out_rsp_comp_state(out_rsp_comp_state),
    .out_dvm_valid(out_dvm_valid), .out_rsos_valid(out_rsos_valid),
    .pcredit_count(pcredit_count), .pcredit_full(pcredit_full),
    .pcredit_overflow(pcredit_overflow),
    .pcredit_underflow(pcredit_underflow), .coh_state(coh_state),
    .coh_error(coh_error), .dwt_active(dwt_active),
    .dwt_cancel(dwt_cancel), .dwt_error(dwt_error),
    .expiry_active(expiry_active), .expiry_fired(expiry_fired),
    .qos_high(qos_high), .dvm_pending(dvm_pending),
    .rsos_pending(rsos_pending)
  );

  always #5 clk = ~clk;
  integer errors;
  integer cycles;
  integer i;
  always @(posedge clk) cycles = cycles + 1;

  task fail_msg;
    input [8*64-1:0] msg;
    begin
      errors = errors + 1;
      $display("FAIL: %0s (cycle %0d)", msg, cycles);
    end
  endtask

  task do_req_capture;
    input [31:0] addr;
    input [2:0] size;
    input [3:0] opcode;
    input [3:0] qos;
    integer timeout;
    begin
      @(negedge clk);
      in_req_addr = addr; in_req_size = size; in_req_opcode = opcode;
      in_req_qos = qos; in_req_c = 1'b0; in_req_dwt = 1'b0;
      in_req_expiry = 1'b0; in_req_comp_state = 3'd0;
      in_req_valid = 1'b1;
      timeout = 0;
      while (!in_req_ready && timeout < 100) begin
        @(posedge clk); timeout = timeout + 1;
        @(negedge clk);
      end
      if (timeout >= 100) fail_msg("do_req_capture timeout");
      @(posedge clk);
      @(negedge clk);
      in_req_valid = 1'b0;
    end
  endtask

  task do_req_emit;
    integer timeout;
    begin
      @(negedge clk);
      out_req_ready = 1'b1;
      timeout = 0;
      while (!out_req_valid && timeout < 100) begin
        @(posedge clk); timeout = timeout + 1;
        @(negedge clk);
      end
      if (timeout >= 100) fail_msg("do_req_emit timeout");
      @(posedge clk);
      @(negedge clk);
      out_req_ready = 1'b0;
    end
  endtask

  task do_rsp;
    begin
      @(negedge clk);
      rsp_opcode = 4'h1; rsp_pcredit = 1'b1; rsp_comp_state = 3'd0;
      rsp_valid = 1'b1;
      @(posedge clk);
      @(negedge clk);
      rsp_valid = 1'b0;
    end
  endtask

  initial begin
    clk = 0; rst_n = 0; errors = 0; cycles = 0;
    in_req_addr = 0; in_req_size = 0; in_req_opcode = 0; in_req_valid = 0;
    in_req_qos = 0; in_req_c = 0; in_req_dwt = 0; in_req_expiry = 0;
    in_req_comp_state = 0;
    out_req_ready = 0; in_dat_data = 0; in_dat_be = 0; in_dat_valid = 0;
    out_dat_ready = 1'b1; rsp_valid = 0; rsp_ready = 1'b1;
    out_rsp_ready = 1'b1; out_snp_ready = 1'b1;
    rsp_opcode = 0; rsp_pcredit = 0; rsp_comp_state = 0;
    out_dvm_ready = 1'b1; out_rsos_ready = 1'b1;
    repeat (10) @(posedge clk);
    @(negedge clk);
    rst_n = 1'b1;
    repeat (5) @(posedge clk);
    $display("=== tb_chi_qos start ===");
    do_req_capture(32'h1000, 3'd2, 4'h0, 4'd0);
    do_req_emit;
    do_rsp;
    $display("QoS: low-QoS out-of-order stalls (strong)");
    @(negedge clk);
    in_req_addr = 32'h2000; in_req_size = 3'd2; in_req_opcode = 4'h0;
    in_req_qos = 4'd0; in_req_c = 1'b0; in_req_dwt = 1'b0;
    in_req_expiry = 1'b0; in_req_comp_state = 3'd0;
    in_req_valid = 1'b1;
    @(negedge clk);
    repeat (3) @(posedge clk);
    @(negedge clk);
    if (!order_violation) fail_msg("QoS low violation low");
    else $display("PASS: QoS low order_violation=1");
    if (in_req_ready) fail_msg("QoS low ready high");
    else $display("PASS: QoS low stalled ready=0");
    $display("QoS: high-QoS bypasses stall");
    @(negedge clk);
    in_req_qos = 4'd15;
    repeat (3) @(posedge clk);
    @(negedge clk);
    in_req_valid = 1'b0;
    if (!out_req_valid) fail_msg("QoS high no capture");
    else $display("PASS: QoS high ready=1");
    if (!qos_high) fail_msg("QoS high flag low");
    else $display("PASS: QoS high qos_high=1");
    do_req_emit;
    do_rsp;
    repeat (5) @(posedge clk);
    if (errors == 0) $display("status: PASS");
    else $display("status: FAIL errors=%0d", errors);
    $finish;
  end

  initial begin
    #200000;
    $display("FAIL: global timeout");
    $finish;
  end
endmodule
`default_nettype wire
"""


@pytest.mark.skipif(_VERILATOR is None, reason="verilator not installed")
def test_chi_directed_req_channel(tmp_path):
    build = build_adapter(AdapterParams(
        agent_idx=0, protocol=ProtocolFamily.CHI, **_CHI_FULL_BUILD_PARAMS))
    assert build.verdict.ok is True, build.verdict.reason
    log = _run_chi_tb(tmp_path, build, _CHI_FULL_TB, "tb_chi_full")
    assert "PASS: REQ aligned addr=0x1000" in log
    assert "PASS: REQ clamp size=3" in log
    assert "PASS: REQ QoS=9" in log


@pytest.mark.skipif(_VERILATOR is None, reason="verilator not installed")
def test_chi_directed_rsp_channel(tmp_path):
    build = build_adapter(AdapterParams(
        agent_idx=0, protocol=ProtocolFamily.CHI, **_CHI_FULL_BUILD_PARAMS))
    assert build.verdict.ok is True, build.verdict.reason
    log = _run_chi_tb(tmp_path, build, _CHI_FULL_TB, "tb_chi_full")
    assert "PASS: RSP ch=1" in log
    assert "PASS: RSP grant pcredit 3->4" in log
    assert "PASS: RSP coh=2" in log


@pytest.mark.skipif(_VERILATOR is None, reason="verilator not installed")
def test_chi_directed_snp_channel(tmp_path):
    build = build_adapter(AdapterParams(
        agent_idx=0, protocol=ProtocolFamily.CHI, **_CHI_FULL_BUILD_PARAMS))
    assert build.verdict.ok is True, build.verdict.reason
    log = _run_chi_tb(tmp_path, build, _CHI_FULL_TB, "tb_chi_full")
    assert "PASS: SNP ch=2" in log
    assert "PASS: SNP out_snp_valid=1" in log


@pytest.mark.skipif(_VERILATOR is None, reason="verilator not installed")
def test_chi_directed_dat_channel(tmp_path):
    build = build_adapter(AdapterParams(
        agent_idx=0, protocol=ProtocolFamily.CHI, **_CHI_FULL_BUILD_PARAMS))
    assert build.verdict.ok is True, build.verdict.reason
    log = _run_chi_tb(tmp_path, build, _CHI_FULL_TB, "tb_chi_full")
    assert "PASS: DAT data fwd" in log
    assert "PASS: DAT BE masked to 0x01" in log


@pytest.mark.skipif(_VERILATOR is None, reason="verilator not installed")
def test_chi_full_profile_extended_channels(tmp_path):
    build = build_adapter(AdapterParams(
        agent_idx=0, protocol=ProtocolFamily.CHI, **_CHI_FULL_BUILD_PARAMS))
    assert build.verdict.ok is True, build.verdict.reason
    log = _run_chi_tb(tmp_path, build, _CHI_FULL_TB, "tb_chi_full")
    assert "PASS: DVM out_dvm_valid=1" in log
    assert "PASS: DVM ack clears pending" in log
    assert "PASS: RSOS out_rsos_valid=1" in log
    assert "PASS: RSOS ack clears pending" in log
    assert "PASS: coh_error reserved=1" in log
    assert "PASS: DWT cancel=1" in log
    assert "PASS: Expiry fired=1" in log
    assert "PASS: P-Credit full=1" in log
    assert "PASS: P-Credit resume" in log


@pytest.mark.skipif(_VERILATOR is None, reason="verilator not installed")
def test_chi_qos_ordering_bypass(tmp_path):
    params = dict(_CHI_FULL_BUILD_PARAMS)
    params.update(ordering="strong", chi_pcredit_max=16,
                  chi_dwt_timeout=64, chi_expiry_timeout=64)
    build = build_adapter(AdapterParams(
        agent_idx=0, protocol=ProtocolFamily.CHI, **params))
    assert build.verdict.ok is True, build.verdict.reason
    log = _run_chi_tb(tmp_path, build, _CHI_QOS_TB, "tb_chi_qos")
    assert "PASS: QoS low order_violation=1" in log
    assert "PASS: QoS low stalled ready=0" in log
    assert "PASS: QoS high ready=1" in log
    assert "PASS: QoS high qos_high=1" in log


# --- rtl_support + preview manifest --------------------------------------


@pytest.mark.parametrize("intent", [
    AgentIntentV4(0, protocol=ProtocolFamily.CHI),
    AgentIntentV4(0, protocol=ProtocolFamily.TILELINK),
    AgentIntentV4(0, protocol=ProtocolFamily.CUSTOM, split_at=64),
    AgentIntentV4(0, protocol=ProtocolFamily.CUSTOM,
                  ordering=OrderingMode.STRONG),
])
def test_rtl_support_no_longer_refuses(intent):
    request = _request(agent_intents=(intent,))
    compilation = FabricCompiler().compile(request)
    assert compilation.status == "COMPILED", compilation.error
    support = rtl_support(request, topology_view(compilation))
    assert support.supported is True, support.reason
    assert "AdapterFactory" not in (support.reason or "")
    assert "ADAPTER_UNSUPPORTED" not in (support.reason or "")


@pytest.mark.parametrize("protocol, kwargs, module, assumption", [
    (ProtocolFamily.CHI, {}, "adapter_chi_g0", "CHI compliance"),
    (ProtocolFamily.TILELINK, {}, "adapter_tilelink_g0",
     "TileLink compliance"),
    (ProtocolFamily.CUSTOM, dict(split_at=64), "adapter_custom_g0",
     "Custom scope"),
])
def test_preview_emits_manifest_with_full_limits(
        tmp_path, protocol, kwargs, module, assumption):
    request = _request(agent_intents=(
        AgentIntentV4(0, protocol=protocol, **kwargs),))
    result = run_rtl_preview(request.to_dict(), tmp_path,
                             {"repo_root": str(REPO)})
    assert result["adapters"] == "EMITTED"
    assert result["final_implementation"] is False
    assert (tmp_path / "rtl" / f"{module}.sv").is_file()
    manifest = json.loads((tmp_path / "rtl-preview.json").read_text())
    assert manifest["final_implementation"] is False
    row = manifest["adapters"]["adapters"][0]
    assert row["module"] == module and row["sha256"]
    # Typed BookSim smoke (never silent); lint is PASS when verilator runs.
    assert row["booksim_smoke"]["status"] == "NOT_RUN"
    assert row["booksim_smoke"]["code"] == "ADAPTER_BOOKSIM_NOT_RUN"
    assumptions = {label: text for label, text in manifest["assumptions"]}
    assert "Not established" in assumptions[assumption]
    if _VERILATOR is not None:
        assert row["lint"]["status"] == "PASS"
        assert row["lint"]["clean"] is True


# --- BookSim smoke (typed, never skipped) ---------------------------------


def test_booksim_smoke_passes_or_names_missing_harness(tmp_path):
    request = _request(agent_intents=(
        AgentIntentV4(0, protocol=ProtocolFamily.CHI),))
    run_rtl_preview(request.to_dict(), tmp_path, {"repo_root": str(REPO)})
    verdict = run_adapter_booksim_smoke(
        rtl_dir=tmp_path / "rtl",
        anynet=tmp_path / "selected-topology.anynet")
    if verdict["status"] == "PASS":
        assert verdict["code"] == "ADAPTER_BOOKSIM_PASS"
        assert verdict["booksim"]["delivered"] == 5
    else:
        assert verdict["status"] == "NOT_RUN"
        assert verdict["code"] == "ADAPTER_BOOKSIM_NOT_RUN"
        assert verdict["status"] != "PASS"


def test_booksim_smoke_with_missing_binary_is_typed(tmp_path):
    verdict = run_adapter_booksim_smoke(
        rtl_dir=tmp_path / "rtl", anynet=tmp_path / "x.anynet",
        booksim_bin=Path(tmp_path / "no-booksim"))
    assert verdict["status"] == "NOT_RUN"
    assert verdict["code"] == "ADAPTER_BOOKSIM_NOT_RUN"
    assert "BookSim" in (verdict["reason"] or "")

# --- FULL CHI: multi-transaction reorder + CT/legacy + coh FSM --------------


def test_chi_reorder_and_ct_emission_shape():
    build = build_adapter(AdapterParams(
        agent_idx=0, protocol=ProtocolFamily.CHI, data_width=64,
        addr_width=32, max_outstanding=16, ordering="raw",
        chi_reorder_depth=4, chi_ct_enable=True))
    assert build.verdict.ok is True
    source = build.source or ""
    for token in ("REORDER_DEPTH = 4", "CT_ENABLE = 1",
                  "reorder_count", "reorder_full", "hol_bypass",
                  "outstanding_ch0", "outstanding_ch1",
                  "outstanding_ch2", "outstanding_ch3",
                  "dvm_outstanding", "rsos_outstanding",
                  "busy_q", "outstanding_q",
                  "in_ct_valid", "in_ct_opcode", "in_ct_profile",
                  "in_ct_addr", "in_ct_size", "in_ct_qos",
                  "in_ct_c", "in_ct_dwt", "in_ct_expiry",
                  "in_ct_comp_state", "in_ct_ready",
                  "out_ct_opcode", "out_ct_profile",
                  "out_req_ct_legacy", "ct_unsupported",
                  "coh_illegal", "coh_q", "elig_q",
                  "rn_fn_signoff", "RN/FN", "final_implementation",
                  "CT/legacy", "not claimed", "Srota Native Stream"):
        assert token in source, token
    default = build_adapter(AdapterParams(
        agent_idx=0, protocol=ProtocolFamily.CHI))
    assert "REORDER_DEPTH = 4" in (default.source or "")
    assert "CT_ENABLE = 1" in (default.source or "")
    tuned = build_adapter(AdapterParams(
        agent_idx=0, protocol=ProtocolFamily.CHI, chi_reorder_depth=2,
        chi_ct_enable=False))
    assert tuned.verdict.ok is True
    assert "REORDER_DEPTH = 2" in (tuned.source or "")
    assert "CT_ENABLE = 0" in (tuned.source or "")
    assert _sha(default.source or "") != _sha(tuned.source or "")


def test_chi_reorder_and_ct_invalid_params_are_typed():
    cases = [
        AdapterParams(agent_idx=0, protocol=ProtocolFamily.CHI,
                      chi_reorder_depth=0),
        AdapterParams(agent_idx=0, protocol=ProtocolFamily.CHI,
                      chi_reorder_depth=17),
        AdapterParams(agent_idx=0, protocol=ProtocolFamily.CHI,
                      chi_reorder_depth="4"),
        AdapterParams(agent_idx=0, protocol=ProtocolFamily.CHI,
                      chi_reorder_depth=True),
        AdapterParams(agent_idx=0, protocol=ProtocolFamily.CHI,
                      chi_ct_enable=1),
        AdapterParams(agent_idx=0, protocol=ProtocolFamily.CHI,
                      chi_ct_enable="yes"),
    ]
    for params in cases:
        build = build_adapter(params)
        assert build.verdict.ok is False, params
        assert build.verdict.status == "INVALID"
        assert build.verdict.blocker_id == "ADAPTER_INVALID_PARAMS"
        assert build.module is None and build.source is None


_CHI_REORDER_BUILD_PARAMS = dict(
    data_width=64, addr_width=32, max_outstanding=16, ordering="raw",
    chi_qos=8, chi_pcredit_max=64, chi_dwt_timeout=8, chi_expiry_timeout=8,
    chi_coh_init=0, chi_dvm_enable=True, chi_rsos_enable=True,
    chi_reorder_depth=4, chi_ct_enable=True)

_CHI_REORDER_TB = r"""
`default_nettype none
module tb_chi_reorder;
  logic clk;
  logic rst_n;
  logic [31:0] in_req_addr;
  logic [2:0] in_req_size;
  logic [3:0] in_req_opcode;
  logic in_req_valid;
  logic in_req_ready;
  logic [31:0] out_req_addr;
  logic [2:0] out_req_size;
  logic [3:0] out_req_opcode;
  logic [1:0] out_req_ch;
  logic out_req_valid;
  logic out_req_ready;
  logic [63:0] in_dat_data;
  logic [7:0] in_dat_be;
  logic in_dat_valid;
  logic in_dat_ready;
  logic [63:0] out_dat_data;
  logic [7:0] out_dat_be;
  logic out_dat_valid;
  logic out_dat_ready;
  logic rsp_valid;
  logic rsp_ready;
  logic out_rsp_valid;
  logic out_rsp_ready;
  logic [3:0] out_rsp_opcode;
  logic out_snp_valid;
  logic out_snp_ready;
  logic [31:0] out_snp_addr;
  logic credit_full;
  logic size_error;
  logic order_violation;
  logic [3:0] in_req_qos;
  logic in_req_c;
  logic in_req_dwt;
  logic in_req_expiry;
  logic [2:0] in_req_comp_state;
  logic [3:0] rsp_opcode;
  logic rsp_pcredit;
  logic [2:0] rsp_comp_state;
  logic out_dvm_ready;
  logic out_rsos_ready;
  logic [3:0] out_req_qos;
  logic out_req_c;
  logic out_req_dwt;
  logic out_req_expiry;
  logic [2:0] out_req_comp_state;
  logic [2:0] out_rsp_comp_state;
  logic out_dvm_valid;
  logic out_rsos_valid;
  logic [8:0] pcredit_count;
  logic pcredit_full;
  logic pcredit_overflow;
  logic pcredit_underflow;
  logic [2:0] coh_state;
  logic coh_error;
  logic dwt_active;
  logic dwt_cancel;
  logic dwt_error;
  logic expiry_active;
  logic expiry_fired;
  logic qos_high;
  logic dvm_pending;
  logic rsos_pending;
  logic in_ct_valid;
  logic [3:0] in_ct_opcode;
  logic [1:0] in_ct_profile;
  logic [31:0] in_ct_addr;
  logic [2:0] in_ct_size;
  logic [3:0] in_ct_qos;
  logic in_ct_c;
  logic in_ct_dwt;
  logic in_ct_expiry;
  logic [2:0] in_ct_comp_state;
  logic in_ct_ready;
  logic [3:0] out_ct_opcode;
  logic [1:0] out_ct_profile;
  logic out_req_ct_legacy;
  logic ct_unsupported;
  logic [8:0] reorder_count;
  logic reorder_full;
  logic hol_bypass;
  logic [8:0] outstanding_ch0;
  logic [8:0] outstanding_ch1;
  logic [8:0] outstanding_ch2;
  logic [8:0] outstanding_ch3;
  logic [8:0] dvm_outstanding;
  logic [8:0] rsos_outstanding;
  logic rn_fn_signoff;

  adapter_chi_g0 dut (
    .clk(clk), .rst_n(rst_n),
    .in_req_addr(in_req_addr), .in_req_size(in_req_size),
    .in_req_opcode(in_req_opcode), .in_req_valid(in_req_valid),
    .in_req_ready(in_req_ready),
    .out_req_addr(out_req_addr), .out_req_size(out_req_size),
    .out_req_opcode(out_req_opcode), .out_req_ch(out_req_ch),
    .out_req_valid(out_req_valid), .out_req_ready(out_req_ready),
    .in_dat_data(in_dat_data), .in_dat_be(in_dat_be),
    .in_dat_valid(in_dat_valid), .in_dat_ready(in_dat_ready),
    .out_dat_data(out_dat_data), .out_dat_be(out_dat_be),
    .out_dat_valid(out_dat_valid), .out_dat_ready(out_dat_ready),
    .rsp_valid(rsp_valid), .rsp_ready(rsp_ready),
    .out_rsp_valid(out_rsp_valid), .out_rsp_ready(out_rsp_ready),
    .out_rsp_opcode(out_rsp_opcode),
    .out_snp_valid(out_snp_valid), .out_snp_ready(out_snp_ready),
    .out_snp_addr(out_snp_addr),
    .credit_full(credit_full), .size_error(size_error),
    .order_violation(order_violation),
    .in_req_qos(in_req_qos), .in_req_c(in_req_c),
    .in_req_dwt(in_req_dwt), .in_req_expiry(in_req_expiry),
    .in_req_comp_state(in_req_comp_state), .rsp_opcode(rsp_opcode),
    .rsp_pcredit(rsp_pcredit), .rsp_comp_state(rsp_comp_state),
    .out_dvm_ready(out_dvm_ready), .out_rsos_ready(out_rsos_ready),
    .out_req_qos(out_req_qos), .out_req_c(out_req_c),
    .out_req_dwt(out_req_dwt), .out_req_expiry(out_req_expiry),
    .out_req_comp_state(out_req_comp_state),
    .out_rsp_comp_state(out_rsp_comp_state),
    .out_dvm_valid(out_dvm_valid), .out_rsos_valid(out_rsos_valid),
    .pcredit_count(pcredit_count), .pcredit_full(pcredit_full),
    .pcredit_overflow(pcredit_overflow),
    .pcredit_underflow(pcredit_underflow), .coh_state(coh_state),
    .coh_error(coh_error), .dwt_active(dwt_active),
    .dwt_cancel(dwt_cancel), .dwt_error(dwt_error),
    .expiry_active(expiry_active), .expiry_fired(expiry_fired),
    .qos_high(qos_high), .dvm_pending(dvm_pending),
    .rsos_pending(rsos_pending),
    .in_ct_valid(in_ct_valid), .in_ct_opcode(in_ct_opcode),
    .in_ct_profile(in_ct_profile), .in_ct_addr(in_ct_addr),
    .in_ct_size(in_ct_size), .in_ct_qos(in_ct_qos),
    .in_ct_c(in_ct_c), .in_ct_dwt(in_ct_dwt),
    .in_ct_expiry(in_ct_expiry), .in_ct_comp_state(in_ct_comp_state),
    .in_ct_ready(in_ct_ready), .out_ct_opcode(out_ct_opcode),
    .out_ct_profile(out_ct_profile),
    .out_req_ct_legacy(out_req_ct_legacy),
    .ct_unsupported(ct_unsupported), .reorder_count(reorder_count),
    .reorder_full(reorder_full), .hol_bypass(hol_bypass),
    .outstanding_ch0(outstanding_ch0), .outstanding_ch1(outstanding_ch1),
    .outstanding_ch2(outstanding_ch2), .outstanding_ch3(outstanding_ch3),
    .dvm_outstanding(dvm_outstanding),
    .rsos_outstanding(rsos_outstanding),
    .rn_fn_signoff(rn_fn_signoff)
  );

  always #5 clk = ~clk;
  integer errors;
  integer cycles;
  always @(posedge clk) cycles = cycles + 1;

  task fail_msg;
    input [8*64-1:0] msg;
    begin
      errors = errors + 1;
      $display("FAIL: %0s (cycle %0d)", msg, cycles);
    end
  endtask

  task do_req_capture;
    input [31:0] addr;
    input [2:0] size;
    input [3:0] opcode;
    input [3:0] qos;
    integer timeout;
    begin
      @(negedge clk);
      in_req_addr = addr; in_req_size = size; in_req_opcode = opcode;
      in_req_qos = qos; in_req_c = 1'b0; in_req_dwt = 1'b0;
      in_req_expiry = 1'b0; in_req_comp_state = 3'd0;
      in_req_valid = 1'b1;
      timeout = 0;
      while (!in_req_ready && timeout < 100) begin
        @(posedge clk); timeout = timeout + 1;
        @(negedge clk);
      end
      if (timeout >= 100) fail_msg("do_req_capture timeout");
      @(posedge clk);
      @(negedge clk);
      in_req_valid = 1'b0;
    end
  endtask

  task do_req_emit;
    integer timeout;
    begin
      @(negedge clk);
      out_req_ready = 1'b1;
      timeout = 0;
      while (!out_req_valid && timeout < 100) begin
        @(posedge clk); timeout = timeout + 1;
        @(negedge clk);
      end
      if (timeout >= 100) fail_msg("do_req_emit timeout");
      @(posedge clk);
      @(negedge clk);
      out_req_ready = 1'b0;
    end
  endtask

  task do_rsp;
    input [3:0] opcode;
    input [2:0] comp;
    begin
      @(negedge clk);
      rsp_opcode = opcode; rsp_pcredit = 1'b1; rsp_comp_state = comp;
      rsp_valid = 1'b1;
      @(posedge clk);
      @(negedge clk);
      rsp_valid = 1'b0;
    end
  endtask

  task do_ct_capture;
    input [31:0] addr;
    input [3:0] opcode;
    input [1:0] profile;
    input ok;
    integer timeout;
    begin
      @(negedge clk);
      in_ct_addr = addr; in_ct_size = 3'd2; in_ct_opcode = opcode;
      in_ct_profile = profile; in_ct_qos = 4'd0;
      in_ct_c = 1'b0; in_ct_dwt = 1'b0; in_ct_expiry = 1'b0;
      in_ct_comp_state = 3'd0;
      in_ct_valid = 1'b1;
      #1;
      timeout = 0;
      while (!in_ct_ready && timeout < 8) begin
        @(posedge clk); timeout = timeout + 1;
        @(negedge clk);
      end
      if (ok && timeout >= 8) fail_msg("do_ct_capture timeout");
      if (ok && !in_ct_ready) fail_msg("do_ct_capture not ready");
      if (!ok && in_ct_ready) fail_msg("ct capture ready when blocked");
      @(posedge clk);
      @(negedge clk);
      in_ct_valid = 1'b0;
    end
  endtask

  initial begin
    clk = 0; rst_n = 0; errors = 0; cycles = 0;
    in_req_addr = 0; in_req_size = 0; in_req_opcode = 0; in_req_valid = 0;
    in_req_qos = 0; in_req_c = 0; in_req_dwt = 0; in_req_expiry = 0;
    in_req_comp_state = 0;
    out_req_ready = 0; in_dat_data = 0; in_dat_be = 0; in_dat_valid = 0;
    out_dat_ready = 1'b1; rsp_valid = 0; rsp_ready = 1'b1;
    out_rsp_ready = 1'b1; out_snp_ready = 1'b1;
    rsp_opcode = 0; rsp_pcredit = 0; rsp_comp_state = 0;
    out_dvm_ready = 1'b1; out_rsos_ready = 1'b1;
    in_ct_valid = 0; in_ct_opcode = 0; in_ct_profile = 0;
    in_ct_addr = 0; in_ct_size = 0; in_ct_qos = 0;
    in_ct_c = 0; in_ct_dwt = 0; in_ct_expiry = 0;
    in_ct_comp_state = 0;
    $display("=== tb_chi_reorder start ===");
    repeat (10) @(posedge clk);
    rst_n = 1'b1;
    repeat (5) @(posedge clk);
    if (reorder_count !== 9'd0) fail_msg("reset reorder != 0");
    else $display("PASS: reset reorder=0");
    if (reorder_full) fail_msg("reset reorder_full");
    if (rn_fn_signoff !== 1'b0) fail_msg("RN/FN sign-off claimed");
    else $display("PASS: RN/FN sign-off not claimed");

    $display("Reorder: QoS arbitration among 4 concurrent transactions");
    do_req_capture(32'h0000, 3'd2, 4'h0, 4'd0);
    do_req_capture(32'h1004, 3'd2, 4'h0, 4'd5);
    do_req_capture(32'h2008, 3'd2, 4'h0, 4'd2);
    do_req_capture(32'h300C, 3'd2, 4'h0, 4'd15);
    @(negedge clk);
    if (reorder_count !== 9'd4) fail_msg("reorder_count != 4");
    else $display("PASS: reorder_count=4");
    if (!reorder_full) fail_msg("reorder_full low");
    else $display("PASS: reorder_full=1");
    @(negedge clk);
    if (out_req_addr !== 32'h300C) fail_msg("arb first != 0x300C");
    else $display("PASS: arb 1st is QoS15 0x300C");
    if (out_req_qos !== 4'd15) fail_msg("arb first qos");
    do_req_emit;
    @(negedge clk);
    if (out_req_addr !== 32'h1004) fail_msg("arb 2nd != 0x1004");
    else $display("PASS: arb 2nd is QoS5 0x1004");
    do_req_emit;
    @(negedge clk);
    if (out_req_addr !== 32'h2008) fail_msg("arb 3rd != 0x2008");
    else $display("PASS: arb 3rd is QoS2 0x2008");
    do_req_emit;
    @(negedge clk);
    if (out_req_addr !== 32'h0000) fail_msg("arb 4th != 0x0000");
    else $display("PASS: arb 4th is QoS0 0x0000");
    do_req_emit;
    @(negedge clk);
    if (reorder_count !== 9'd0) fail_msg("reorder after drain != 0");
    else $display("PASS: reorder drained");
    if (outstanding_ch0 !== 9'd4) fail_msg("outstanding_ch0 != 4");
    else $display("PASS: outstanding_ch0=4");
    do_rsp(4'h1, 3'd0);
    do_rsp(4'h1, 3'd0);
    do_rsp(4'h1, 3'd0);
    do_rsp(4'h1, 3'd0);
    if (outstanding_ch1 !== 9'd0) fail_msg("outstanding_ch1 != 0");
    else $display("PASS: outstanding_ch1=0 (guarded)");

    $display("Reorder: head-of-line bypass (blocked DVM head)");
    out_dvm_ready = 1'b0;
    do_req_capture(32'h6000, 3'd2, 4'h4, 4'd0);
    do_req_capture(32'h6004, 3'd2, 4'h0, 4'd0);
    @(negedge clk);
    if (!hol_bypass) fail_msg("hol_bypass low");
    else $display("PASS: hol_bypass=1");
    if (out_dvm_valid) fail_msg("blocked head DVM valid");
    if (out_req_addr !== 32'h6004) fail_msg("HOL first != 0x6004");
    else $display("PASS: HOL younger entry emitted first");
    do_req_emit;
    out_dvm_ready = 1'b1;
    @(negedge clk);
    if (out_req_addr !== 32'h6000) fail_msg("HOL second != 0x6000");
    else $display("PASS: HOL head emitted after gate opens");
    if (!out_dvm_valid) fail_msg("DVM out_dvm_valid low");
    do_req_emit;
    @(negedge clk);
    if (!dvm_pending) fail_msg("DVM pending low");
    else $display("PASS: DVM pending=1");
    if (dvm_outstanding !== 9'd1) fail_msg("dvm_outstanding != 1");
    else $display("PASS: dvm_outstanding=1");
    do_rsp(4'h1, 3'd0);
    do_rsp(4'h5, 3'd0);
    if (dvm_pending) fail_msg("DVM pending post-ack");
    else $display("PASS: DVM ack clears pending");

    $display("DAT: BE filtered by head entry SIZE=2 (4B mask)");
    do_req_capture(32'h7000, 3'd2, 4'h0, 4'd0);
    @(negedge clk);
    in_dat_data = 64'hAABBCCDDEEFF0011; in_dat_be = 8'hFF;
    in_dat_valid = 1'b1;
    @(posedge clk);
    @(negedge clk);
    if (out_dat_be !== 8'h0F) fail_msg("DAT reorder BE mask");
    else $display("PASS: DAT BE masked to 0x0F");
    in_dat_valid = 1'b0;
    do_req_emit;
    do_rsp(4'h1, 3'd0);

    $display("Coherency FSM: I->UC->UD legal, UD->SD illegal");
    do_req_capture(32'h8000, 3'd2, 4'h0, 4'd0);
    do_req_emit;
    do_rsp(4'h1, 3'd2);
    @(negedge clk);
    if (coh_state !== 3'd2) fail_msg("coh != 2 after UC ack");
    else $display("PASS: coh=2 (UC)");
    do_req_capture(32'h8004, 3'd2, 4'h0, 4'd0);
    do_req_emit;
    do_rsp(4'h1, 3'd3);
    @(negedge clk);
    if (coh_state !== 3'd3) fail_msg("coh != 3 after UD ack");
    else $display("PASS: coh=3 (UD)");
    if (coh_error) fail_msg("coh_error on legal path");
    do_req_capture(32'h8008, 3'd2, 4'h0, 4'd0);
    do_req_emit;
    do_rsp(4'h1, 3'd4);
    @(negedge clk);
    if (!coh_error) fail_msg("UD->SD not flagged");
    else $display("PASS: UD->SD coh_error=1");
    if (coh_state !== 3'd3) fail_msg("coh moved on illegal transition");
    else $display("PASS: coh holds 3 on illegal transition");

    $display("Multi DWT: second transaction still counts after first RSP");
    @(negedge clk);
    in_req_addr = 32'h9000; in_req_size = 3'd2; in_req_opcode = 4'h0;
    in_req_qos = 4'd0; in_req_c = 1'b0; in_req_dwt = 1'b1;
    in_req_expiry = 1'b0; in_req_comp_state = 3'd0;
    in_req_valid = 1'b1;
    @(posedge clk);
    @(negedge clk);
    in_req_valid = 1'b0;
    in_req_addr = 32'h9004; in_req_qos = 4'd0;
    in_req_valid = 1'b1;
    @(posedge clk);
    @(negedge clk);
    in_req_valid = 1'b0;
    if (!dwt_active) fail_msg("multi DWT not active");
    do_req_emit;
    do_req_emit;
    do_rsp(4'h1, 3'd0);
    repeat (12) @(posedge clk);
    if (!dwt_cancel) fail_msg("multi DWT cancel low");
    else $display("PASS: multi DWT cancel under load=1");
    do_rsp(4'h1, 3'd0);
    if (dwt_cancel) fail_msg("multi DWT clear");
    else $display("PASS: multi DWT cleared on last RSP");

    $display("CT/legacy: CHI.B capture, reserved class, profile mismatch");
    do_ct_capture(32'hB000, 4'h0, 2'd0, 1'b1);
    if (!in_ct_ready) fail_msg("ct CHI.B ready low (pre-edge)");
    @(negedge clk);
    if (out_ct_opcode !== 4'h0) fail_msg("ct opcode translate");
    else $display("PASS: CT CHI.B opcode translated 0x0");
    if (out_ct_profile !== 2'd0) fail_msg("ct profile echo");
    do_req_emit;
    @(negedge clk);
    if (!out_req_ct_legacy) fail_msg("ct legacy flag low");
    else $display("PASS: CT entry carries out_req_ct_legacy=1");
    if (out_req_addr !== 32'hB000) fail_msg("ct addr");
    do_rsp(4'h1, 3'd0);
    do_ct_capture(32'hB004, 4'hC, 2'd0, 1'b0);
    if (!ct_unsupported) fail_msg("ct reserved class not unsupported");
    else $display("PASS: CT reserved class ct_unsupported=1");
    do_ct_capture(32'hB008, 4'h0, 2'd1, 1'b0);
    if (!ct_unsupported) fail_msg("ct profile mismatch not unsupported");
    else $display("PASS: CT profile mismatch still unsupported=1");
    do_ct_capture(32'hB00C, 4'h8, 2'd2, 1'b1);
    if (out_ct_opcode !== 4'h8) fail_msg("ct CHI.T opcode translate");
    else $display("PASS: CT CHI.T opcode translated 0x8");
    @(negedge clk);
    if (!out_rsos_valid) fail_msg("ct RSOS-class out_rsos_valid low");
    else $display("PASS: CT CHI.T drives out_rsos_valid=1");
    do_req_emit;
    do_rsp(4'h9, 3'd0);

    in_dat_valid = 1'b0;
    repeat (5) @(posedge clk);
    if (errors == 0) $display("status: PASS");
    else $display("status: FAIL errors=%0d", errors);
    $finish;
  end

  initial begin
    #200000;
    $display("FAIL: global timeout");
    $finish;
  end
endmodule
`default_nettype wire
"""


_CHI_CT_DISABLED_TB = r"""
`default_nettype none
module tb_chi_ct_disabled;
  logic clk;
  logic rst_n;
  logic in_ct_valid;
  logic [3:0] in_ct_opcode;
  logic [1:0] in_ct_profile;
  logic [31:0] in_ct_addr;
  logic [2:0] in_ct_size;
  logic [3:0] in_ct_qos;
  logic in_ct_c;
  logic in_ct_dwt;
  logic in_ct_expiry;
  logic [2:0] in_ct_comp_state;
  logic in_ct_ready;
  logic [3:0] out_ct_opcode;
  logic [1:0] out_ct_profile;
  logic out_req_ct_legacy;
  logic ct_unsupported;
  logic [31:0] in_req_addr;
  logic [2:0] in_req_size;
  logic [3:0] in_req_opcode;
  logic in_req_valid;
  logic in_req_ready;
  logic [31:0] out_req_addr;
  logic [2:0] out_req_size;
  logic [3:0] out_req_opcode;
  logic [1:0] out_req_ch;
  logic out_req_valid;
  logic out_req_ready;
  logic [63:0] in_dat_data;
  logic [7:0] in_dat_be;
  logic in_dat_valid;
  logic in_dat_ready;
  logic [63:0] out_dat_data;
  logic [7:0] out_dat_be;
  logic out_dat_valid;
  logic out_dat_ready;
  logic rsp_valid;
  logic rsp_ready;
  logic out_rsp_valid;
  logic out_rsp_ready;
  logic [3:0] out_rsp_opcode;
  logic out_snp_valid;
  logic out_snp_ready;
  logic [31:0] out_snp_addr;
  logic credit_full;
  logic size_error;
  logic order_violation;
  logic [3:0] in_req_qos;
  logic in_req_c;
  logic in_req_dwt;
  logic in_req_expiry;
  logic [2:0] in_req_comp_state;
  logic [3:0] rsp_opcode;
  logic rsp_pcredit;
  logic [2:0] rsp_comp_state;
  logic out_dvm_ready;
  logic out_rsos_ready;
  logic [3:0] out_req_qos;
  logic out_req_c;
  logic out_req_dwt;
  logic out_req_expiry;
  logic [2:0] out_req_comp_state;
  logic [2:0] out_rsp_comp_state;
  logic out_dvm_valid;
  logic out_rsos_valid;
  logic [8:0] pcredit_count;
  logic pcredit_full;
  logic pcredit_overflow;
  logic pcredit_underflow;
  logic [2:0] coh_state;
  logic coh_error;
  logic dwt_active;
  logic dwt_cancel;
  logic dwt_error;
  logic expiry_active;
  logic expiry_fired;
  logic qos_high;
  logic dvm_pending;
  logic rsos_pending;
  logic [8:0] reorder_count;
  logic reorder_full;
  logic hol_bypass;
  logic [8:0] outstanding_ch0;
  logic [8:0] outstanding_ch1;
  logic [8:0] outstanding_ch2;
  logic [8:0] outstanding_ch3;
  logic [8:0] dvm_outstanding;
  logic [8:0] rsos_outstanding;
  logic rn_fn_signoff;

  adapter_chi_g0 dut (
    .clk(clk), .rst_n(rst_n),
    .in_req_addr(in_req_addr), .in_req_size(in_req_size),
    .in_req_opcode(in_req_opcode), .in_req_valid(in_req_valid),
    .in_req_ready(in_req_ready),
    .out_req_addr(out_req_addr), .out_req_size(out_req_size),
    .out_req_opcode(out_req_opcode), .out_req_ch(out_req_ch),
    .out_req_valid(out_req_valid), .out_req_ready(out_req_ready),
    .in_dat_data(in_dat_data), .in_dat_be(in_dat_be),
    .in_dat_valid(in_dat_valid), .in_dat_ready(in_dat_ready),
    .out_dat_data(out_dat_data), .out_dat_be(out_dat_be),
    .out_dat_valid(out_dat_valid), .out_dat_ready(out_dat_ready),
    .rsp_valid(rsp_valid), .rsp_ready(rsp_ready),
    .out_rsp_valid(out_rsp_valid), .out_rsp_ready(out_rsp_ready),
    .out_rsp_opcode(out_rsp_opcode),
    .out_snp_valid(out_snp_valid), .out_snp_ready(out_snp_ready),
    .out_snp_addr(out_snp_addr),
    .credit_full(credit_full), .size_error(size_error),
    .order_violation(order_violation),
    .in_req_qos(in_req_qos), .in_req_c(in_req_c),
    .in_req_dwt(in_req_dwt), .in_req_expiry(in_req_expiry),
    .in_req_comp_state(in_req_comp_state), .rsp_opcode(rsp_opcode),
    .rsp_pcredit(rsp_pcredit), .rsp_comp_state(rsp_comp_state),
    .out_dvm_ready(out_dvm_ready), .out_rsos_ready(out_rsos_ready),
    .out_req_qos(out_req_qos), .out_req_c(out_req_c),
    .out_req_dwt(out_req_dwt), .out_req_expiry(out_req_expiry),
    .out_req_comp_state(out_req_comp_state),
    .out_rsp_comp_state(out_rsp_comp_state),
    .out_dvm_valid(out_dvm_valid), .out_rsos_valid(out_rsos_valid),
    .pcredit_count(pcredit_count), .pcredit_full(pcredit_full),
    .pcredit_overflow(pcredit_overflow),
    .pcredit_underflow(pcredit_underflow), .coh_state(coh_state),
    .coh_error(coh_error), .dwt_active(dwt_active),
    .dwt_cancel(dwt_cancel), .dwt_error(dwt_error),
    .expiry_active(expiry_active), .expiry_fired(expiry_fired),
    .qos_high(qos_high), .dvm_pending(dvm_pending),
    .rsos_pending(rsos_pending),
    .in_ct_valid(in_ct_valid), .in_ct_opcode(in_ct_opcode),
    .in_ct_profile(in_ct_profile), .in_ct_addr(in_ct_addr),
    .in_ct_size(in_ct_size), .in_ct_qos(in_ct_qos),
    .in_ct_c(in_ct_c), .in_ct_dwt(in_ct_dwt),
    .in_ct_expiry(in_ct_expiry), .in_ct_comp_state(in_ct_comp_state),
    .in_ct_ready(in_ct_ready), .out_ct_opcode(out_ct_opcode),
    .out_ct_profile(out_ct_profile),
    .out_req_ct_legacy(out_req_ct_legacy),
    .ct_unsupported(ct_unsupported), .reorder_count(reorder_count),
    .reorder_full(reorder_full), .hol_bypass(hol_bypass),
    .outstanding_ch0(outstanding_ch0), .outstanding_ch1(outstanding_ch1),
    .outstanding_ch2(outstanding_ch2), .outstanding_ch3(outstanding_ch3),
    .dvm_outstanding(dvm_outstanding),
    .rsos_outstanding(rsos_outstanding),
    .rn_fn_signoff(rn_fn_signoff)
  );

  always #5 clk = ~clk;
  integer errors;
  always @(posedge clk) begin
    if (errors == 0) begin
      errors = 0;
    end
  end

  initial begin
    clk = 0; rst_n = 0; errors = 0;
    in_req_addr = 0; in_req_size = 0; in_req_opcode = 0; in_req_valid = 0;
    in_req_qos = 0; in_req_c = 0; in_req_dwt = 0; in_req_expiry = 0;
    in_req_comp_state = 0;
    out_req_ready = 0; in_dat_data = 0; in_dat_be = 0; in_dat_valid = 0;
    out_dat_ready = 0; rsp_valid = 0; rsp_ready = 0;
    out_rsp_ready = 0; out_snp_ready = 0;
    rsp_opcode = 0; rsp_pcredit = 0; rsp_comp_state = 0;
    out_dvm_ready = 0; out_rsos_ready = 0;
    in_ct_valid = 0; in_ct_opcode = 0; in_ct_profile = 0;
    in_ct_addr = 0; in_ct_size = 0; in_ct_qos = 0;
    in_ct_c = 0; in_ct_dwt = 0; in_ct_expiry = 0;
    in_ct_comp_state = 0;
    $display("=== tb_chi_ct_disabled start ===");
    repeat (10) @(posedge clk);
    rst_n = 1'b1;
    repeat (5) @(posedge clk);
    @(negedge clk);
    in_ct_addr = 32'hC000; in_ct_size = 3'd2; in_ct_opcode = 4'h0;
    in_ct_profile = 2'd0; in_ct_valid = 1'b1;
    #1;
    repeat (3) @(posedge clk);
    @(negedge clk);
    if (in_ct_ready === 1'b1) begin
      errors = errors + 1;
      $display("FAIL: CT ready while CT_ENABLE=0");
    end else $display("PASS: CT_ENABLE=0 blocks legacy capture");
    in_ct_valid = 1'b0;
    if (ct_unsupported !== 1'b1) begin
      errors = errors + 1;
      $display("FAIL: CT disabled attempt not typed unsupported");
    end else $display("PASS: CT disabled ct_unsupported=1");
    if (reorder_count !== 9'd0) begin
      errors = errors + 1;
      $display("FAIL: CT disabled capture leaked into reorder");
    end else $display("PASS: nothing captured while CT_ENABLE=0");
    if (errors == 0) $display("status: PASS");
    else $display("status: FAIL errors=%0d", errors);
    $finish;
  end

  initial begin
    #100000;
    $display("FAIL: global timeout");
    $finish;
  end
endmodule
`default_nettype wire
"""


@pytest.mark.skipif(_VERILATOR is None, reason="verilator not installed")
def test_chi_reorder_qos_arbitration(tmp_path):
    build = build_adapter(AdapterParams(
        agent_idx=0, protocol=ProtocolFamily.CHI,
        **_CHI_REORDER_BUILD_PARAMS))
    assert build.verdict.ok is True, build.verdict.reason
    log = _run_chi_tb(tmp_path, build, _CHI_REORDER_TB, "tb_chi_reorder")
    assert "PASS: reorder_count=4" in log
    assert "PASS: reorder_full=1" in log
    assert "PASS: arb 1st is QoS15 0x300C" in log
    assert "PASS: arb 2nd is QoS5 0x1004" in log
    assert "PASS: arb 3rd is QoS2 0x2008" in log
    assert "PASS: arb 4th is QoS0 0x0000" in log
    assert "PASS: outstanding_ch0=4" in log
    assert "PASS: outstanding_ch1=0 (guarded)" in log


@pytest.mark.skipif(_VERILATOR is None, reason="verilator not installed")
def test_chi_hol_bypass_and_dvm(tmp_path):
    build = build_adapter(AdapterParams(
        agent_idx=0, protocol=ProtocolFamily.CHI,
        **_CHI_REORDER_BUILD_PARAMS))
    assert build.verdict.ok is True, build.verdict.reason
    log = _run_chi_tb(tmp_path, build, _CHI_REORDER_TB, "tb_chi_reorder")
    assert "PASS: hol_bypass=1" in log
    assert "PASS: HOL younger entry emitted first" in log
    assert "PASS: HOL head emitted after gate opens" in log
    assert "PASS: DVM pending=1" in log
    assert "PASS: dvm_outstanding=1" in log
    assert "PASS: DVM ack clears pending" in log
    assert "PASS: DAT BE masked to 0x0F" in log


@pytest.mark.skipif(_VERILATOR is None, reason="verilator not installed")
def test_chi_coh_fsm_and_multi_watchdog(tmp_path):
    build = build_adapter(AdapterParams(
        agent_idx=0, protocol=ProtocolFamily.CHI,
        **_CHI_REORDER_BUILD_PARAMS))
    assert build.verdict.ok is True, build.verdict.reason
    log = _run_chi_tb(tmp_path, build, _CHI_REORDER_TB, "tb_chi_reorder")
    assert "PASS: coh=2 (UC)" in log
    assert "PASS: coh=3 (UD)" in log
    assert "PASS: UD->SD coh_error=1" in log
    assert "PASS: coh holds 3 on illegal transition" in log
    assert "PASS: multi DWT cancel under load=1" in log
    assert "PASS: multi DWT cleared on last RSP" in log
    assert "PASS: RN/FN sign-off not claimed" in log


@pytest.mark.skipif(_VERILATOR is None, reason="verilator not installed")
def test_chi_ct_legacy_translation(tmp_path):
    build = build_adapter(AdapterParams(
        agent_idx=0, protocol=ProtocolFamily.CHI,
        **_CHI_REORDER_BUILD_PARAMS))
    assert build.verdict.ok is True, build.verdict.reason
    log = _run_chi_tb(tmp_path, build, _CHI_REORDER_TB, "tb_chi_reorder")
    assert "PASS: CT CHI.B opcode translated 0x0" in log
    assert "PASS: CT entry carries out_req_ct_legacy=1" in log
    assert "PASS: CT reserved class ct_unsupported=1" in log
    assert "PASS: CT profile mismatch still unsupported=1" in log
    assert "PASS: CT CHI.T opcode translated 0x8" in log


@pytest.mark.skipif(_VERILATOR is None, reason="verilator not installed")
def test_chi_ct_disabled_is_typed(tmp_path):
    params = dict(_CHI_REORDER_BUILD_PARAMS)
    params.update(chi_ct_enable=False)
    build = build_adapter(AdapterParams(
        agent_idx=0, protocol=ProtocolFamily.CHI, **params))
    assert build.verdict.ok is True, build.verdict.reason
    log = _run_chi_tb(tmp_path, build, _CHI_CT_DISABLED_TB,
                      "tb_chi_ct_disabled")
    assert "PASS: CT_ENABLE=0 blocks legacy capture" in log
    assert "PASS: CT disabled ct_unsupported=1" in log
    assert "PASS: nothing captured while CT_ENABLE=0" in log


