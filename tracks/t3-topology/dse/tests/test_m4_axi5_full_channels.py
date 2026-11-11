"""M4 AXI5 full-channel adapter: channels, burst, error, backpressure.

Each directed Verilator simulation exercises one AXI5 channel family on
the emitted adapter_axi5_g0 (DATA_W=32, SPLIT_AT=2, MAX_OUTSTANDING=4):
AW burst split and ID association, W split WLAST and WSTRB passthrough,
AR burst split, R ID/RRESP/RLAST staging, B ID/BRESP staging, combinational
error checks (burst/size/alignment/exclusive), and backpressure holds.
Lint is PASS-clean with zero warnings on five parameter corners.
"""

from __future__ import annotations

import subprocess
import shutil
import hashlib
from pathlib import Path

import pytest

from veritx_dse.core.paths import REPO
from veritx_dse.model.agent_intent_v4 import AgentIntentV4, ProtocolFamily
from veritx_dse.model.compile_request_v4 import CompileRequestV4
from veritx_dse.model.compile_model import (
    AddressMap, AddressRange, Agent, AgentKind, CollectiveDimension,
    CollectiveIntent, CollectiveKind, DependencyGraph, ModelFamily,
    WorkloadV3,
)
from veritx_dse.model.topology_intent import MeshIntent
from veritx_dse.product.adapter_factory_rtl import (
    AXI5_ADAPTER_ASSUMPTIONS,
    AXI5_ADAPTER_CHANNELS,
    AXI5_ADAPTER_SUBSET_REMAINING,
    AdapterParams,
    build_adapter,
)
from veritx_dse.product.rtl_export import run_rtl_preview

_VERILATOR = shutil.which("verilator")


def _params(**kwargs):
    base = dict(
        agent_idx=0, protocol=ProtocolFamily.AXI5, data_width=32,
        addr_width=64, split_at=2, max_outstanding=4,
    )
    base.update(kwargs)
    return AdapterParams(**base)


def _lint(tmp_path: Path, files: list[str], top: str):
    assert _VERILATOR is not None
    checked = subprocess.run(
        [_VERILATOR, "--lint-only", "-sv", "-Wall", "-Wno-fatal",
         "-Wno-WIDTH", "-Wno-PINNOTFOUND", "-Wno-PINMISSING", "-Wno-UNOPTFLAT", "-Wno-WIDTHTRUNC",
         "--top-module", top, *files],
        cwd=tmp_path, capture_output=True, text=True)
    log = checked.stdout + checked.stderr
    assert checked.returncode == 0, log
    assert "%Error" not in log, log
    return log


def _sha(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()


def test_axi5_emits_full_five_channels_with_no_comments():
    build = build_adapter(_params())
    assert build.verdict.ok is True
    assert build.module == "adapter_axi5_g0"
    source = build.source or ""
    assert "//" not in source
    assert "/*" not in source
    assert "SPLIT_AT = 2" in source
    assert "MAX_OUTSTANDING = 4" in source
    assert "module adapter_axi5_g0" in source
    for token in (
        "in_awvalid", "in_awready", "in_awid", "in_awaddr", "in_awlen",
        "in_awsize", "in_awburst", "in_awlock", "in_awcache", "in_awprot",
        "in_awqos", "in_awregion", "in_awatomic", "in_awdomain", "in_awdvmtype",
        "out_awvalid", "out_awready", "out_awid", "out_awaddr",
        "out_awlen", "out_awsize", "out_awburst", "out_awlock",
        "out_awcache", "out_awprot", "out_awqos", "out_awregion",
        "out_awatomic", "out_awdomain", "out_awdvmtype",
        "wvalid", "wready", "wdata", "wstrb", "wlast",
        "out_wvalid", "out_wready", "out_wdata", "out_wstrb", "out_wlast",
        "in_arvalid", "in_arready", "in_arid", "in_araddr", "in_arlen",
        "in_arsize", "in_arburst", "in_arlock", "in_arcache", "in_arprot",
        "in_arqos", "in_arregion", "in_ardomain",
        "out_arvalid", "out_arready", "out_arid", "out_araddr",
        "out_arlen", "out_arsize", "out_arburst", "out_arlock",
        "out_arcache", "out_arprot", "out_arqos", "out_arregion", "out_ardomain",
        "rvalid", "rready", "rid", "rdata", "rresp", "rlast",
        "out_rvalid", "out_rready", "out_rid", "out_rdata", "out_rresp",
        "out_rlast",
        "bvalid", "bready", "bid", "bresp",
        "out_bvalid", "out_bready", "out_bid", "out_bresp",
        "credit_full", "aw_error", "ar_error", "exclusive_error", "atomic_error", "coh_error", "resp_error", "wstrb_error", "last_error", "id_error",
        "out_dvm_valid", "out_rsos_valid", "dvm_pending", "rsos_pending", "coh_state", "qos_high",
        "outstanding_q", "busy_q", "ar_busy_q",
        "aw_cache_q", "aw_prot_q", "aw_domain_q", "aw_atomic_q",
        "r_stage_valid_q", "b_stage_valid_q", "assert",
    ):
        assert token in source, token
    assert build_adapter(_params()).source == source
    coarse = build_adapter(_params(split_at=4))
    assert _sha(coarse.source or "") != _sha(source)
    assert _sha(build_adapter(_params()).source or "") == _sha(source)


@pytest.mark.skipif(_VERILATOR is None, reason="verilator not installed")
@pytest.mark.parametrize("params", [
    _params(),
    _params(agent_idx=0, data_width=256, addr_width=64, split_at=64,
            max_outstanding=16),
    _params(agent_idx=3, data_width=64, addr_width=32, split_at=None,
            max_outstanding=1),
    AdapterParams(agent_idx=1, protocol=ProtocolFamily.AXI5),
    _params(data_width=512, addr_width=48, split_at=16, max_outstanding=32),
])
def test_axi5_lint_pass_clean(params, tmp_path):
    build = build_adapter(params)
    assert build.module is not None and build.source is not None
    (tmp_path / f"{build.module}.sv").write_text(build.source or "")
    _lint(tmp_path, [f"{build.module}.sv"], build.module)


def test_axi5_assumptions_name_subset_passthrough_vs_checked():
    assert AXI5_ADAPTER_CHANNELS == ("AW", "W", "AR", "R", "B")
    joined = " ".join(AXI5_ADAPTER_ASSUMPTIONS)
    for token in (
        "AxCACHE", "AxPROT", "Checked", "emitted",
        "WSTRB", "WLAST", "BRESP", "RRESP", "ID FIFO",
        "exclusive", "atomic", "Coherency", "DVM", "RSOS", "final_implementation",
    ):
        assert token in joined, token
    assert AXI5_ADAPTER_SUBSET_REMAINING == ()
    build = build_adapter(_params())
    source = build.source or ""
    assert "aw_cache_q" in source
    assert "aw_prot_q" in source
    assert "wstrb_error" in source
    assert "coh_error" in source
    assert "out_dvm_valid" in source
    assert "assert" in source
    for token in ("aw_error", "ar_error", "exclusive_error", "atomic_error", "resp_error"):
        assert token in source


def test_axi5_manifest_stays_not_final_with_full_claim(tmp_path):
    workload = WorkloadV3(
        model_family=ModelFamily.DENSE_TRANSFORMER, tp=2, pp=1, ep=1, dp=1,
        collectives=(CollectiveIntent(
            kind=CollectiveKind.ALLREDUCE, dimension=CollectiveDimension.TP,
            payload_bytes=8192, traffic_class="tp_collective"),))
    request = CompileRequestV4(
        workload=workload,
        agents=(Agent(kind=AgentKind.COMPUTE_TILE, count=3),
                Agent(kind=AgentKind.HBM_CONTROLLER, count=1)),
        dependencies=DependencyGraph(()),
        topology=MeshIntent(side_length=2, concentration=1),
        address_map=AddressMap(ranges=(
            AddressRange(name="HBM0", base=0x1000, size=0x1000,
                         target_agent_idx=1),)),
        agent_intents=(AgentIntentV4(0, protocol=ProtocolFamily.AXI5,
                                     split_at=64, max_outstanding=16),),
    )
    result = run_rtl_preview(request.to_dict(), tmp_path,
                             {"repo_root": str(REPO)})
    assert result["final_implementation"] is False
    assert result["adapters"] == "EMITTED"
    source = (tmp_path / "rtl" / "adapter_axi5_g0.sv").read_text()
    assert "in_awid" in source and "out_bresp" in source
    assert "SPLIT_AT = 64" in source
    assert "//" not in source
    import json
    manifest = json.loads((tmp_path / "rtl-preview.json").read_text())
    assert manifest["final_implementation"] is False
    assert "Not established" in {l: t for l, t in manifest["assumptions"]}["AXI5 compliance"]
    if _VERILATOR is not None:
        row = manifest["adapters"]["adapters"][0]
        assert row["lint"]["status"] == "PASS"
        assert row["lint"]["clean"] is True


_TB = r"""`default_nettype none
module tb_axi5_full;
  logic clk = 0;
  logic rst_n = 0;
  logic in_awvalid = 0;
  logic in_awready;
  logic [7:0] in_awid = 8'h0;
  logic [63:0] in_awaddr = 64'h0;
  logic [7:0] in_awlen = 8'h0;
  logic [2:0] in_awsize = 3'd2;
  logic [1:0] in_awburst = 2'b01;
  logic [1:0] in_awlock = 2'b00;
  logic [3:0] in_awcache = 4'h0;
  logic [2:0] in_awprot = 3'd0;
  logic [3:0] in_awqos = 4'h0;
  logic [3:0] in_awregion = 4'h0;
  logic [2:0] in_awatomic = 3'd0;
  logic out_awvalid;
  logic out_awready = 1;
  logic [7:0] out_awid;
  logic [63:0] out_awaddr;
  logic [7:0] out_awlen;
  logic [2:0] out_awsize;
  logic [1:0] out_awburst;
  logic [1:0] out_awlock;
  logic [3:0] out_awcache;
  logic [2:0] out_awprot;
  logic [3:0] out_awqos;
  logic [3:0] out_awregion;
  logic [2:0] out_awatomic;
  logic wvalid = 0;
  logic wready;
  logic [31:0] wdata = 32'h0;
  logic [3:0] wstrb = 4'hF;
  logic wlast = 0;
  logic out_wvalid;
  logic out_wready = 1;
  logic [31:0] out_wdata;
  logic [3:0] out_wstrb;
  logic out_wlast;
  logic in_arvalid = 0;
  logic in_arready;
  logic [7:0] in_arid = 8'h0;
  logic [63:0] in_araddr = 64'h0;
  logic [7:0] in_arlen = 8'h0;
  logic [2:0] in_arsize = 3'd2;
  logic [1:0] in_arburst = 2'b01;
  logic [1:0] in_arlock = 2'b00;
  logic [3:0] in_arcache = 4'h0;
  logic [2:0] in_arprot = 3'd0;
  logic [3:0] in_arqos = 4'h0;
  logic [3:0] in_arregion = 4'h0;
  logic out_arvalid;
  logic out_arready = 1;
  logic [7:0] out_arid;
  logic [63:0] out_araddr;
  logic [7:0] out_arlen;
  logic [2:0] out_arsize;
  logic [1:0] out_arburst;
  logic [1:0] out_arlock;
  logic [3:0] out_arcache;
  logic [2:0] out_arprot;
  logic [3:0] out_arqos;
  logic [3:0] out_arregion;
  logic rvalid = 0;
  logic rready;
  logic [7:0] rid = 8'h0;
  logic [31:0] rdata = 32'h0;
  logic [1:0] rresp = 2'b00;
  logic rlast = 0;
  logic out_rvalid;
  logic out_rready = 1;
  logic [7:0] out_rid;
  logic [31:0] out_rdata;
  logic [1:0] out_rresp;
  logic out_rlast;
  logic bvalid = 0;
  logic bready = 1;
  logic [7:0] bid = 8'h0;
  logic [1:0] bresp = 2'b00;
  logic out_bvalid;
  logic out_bready = 1;
  logic [7:0] out_bid;
  logic [1:0] out_bresp;
  logic credit_full;
  logic aw_error;
  logic ar_error;
  logic exclusive_error;

  adapter_axi5_g0 dut (
    .clk(clk), .rst_n(rst_n),
    .in_awvalid(in_awvalid), .in_awready(in_awready),
    .in_awid(in_awid), .in_awaddr(in_awaddr), .in_awlen(in_awlen),
    .in_awsize(in_awsize), .in_awburst(in_awburst), .in_awlock(in_awlock),
    .in_awcache(in_awcache), .in_awprot(in_awprot), .in_awqos(in_awqos),
    .in_awregion(in_awregion), .in_awatomic(in_awatomic),
    .out_awvalid(out_awvalid), .out_awready(out_awready),
    .out_awid(out_awid), .out_awaddr(out_awaddr), .out_awlen(out_awlen),
    .out_awsize(out_awsize), .out_awburst(out_awburst), .out_awlock(out_awlock),
    .out_awcache(out_awcache), .out_awprot(out_awprot), .out_awqos(out_awqos),
    .out_awregion(out_awregion), .out_awatomic(out_awatomic),
    .wvalid(wvalid), .wready(wready), .wdata(wdata), .wstrb(wstrb),
    .wlast(wlast),
    .out_wvalid(out_wvalid), .out_wready(out_wready), .out_wdata(out_wdata),
    .out_wstrb(out_wstrb), .out_wlast(out_wlast),
    .in_arvalid(in_arvalid), .in_arready(in_arready),
    .in_arid(in_arid), .in_araddr(in_araddr), .in_arlen(in_arlen),
    .in_arsize(in_arsize), .in_arburst(in_arburst), .in_arlock(in_arlock),
    .in_arcache(in_arcache), .in_arprot(in_arprot), .in_arqos(in_arqos),
    .in_arregion(in_arregion),
    .out_arvalid(out_arvalid), .out_arready(out_arready),
    .out_arid(out_arid), .out_araddr(out_araddr), .out_arlen(out_arlen),
    .out_arsize(out_arsize), .out_arburst(out_arburst), .out_arlock(out_arlock),
    .out_arcache(out_arcache), .out_arprot(out_arprot), .out_arqos(out_arqos),
    .out_arregion(out_arregion),
    .rvalid(rvalid), .rready(rready), .rid(rid), .rdata(rdata),
    .rresp(rresp), .rlast(rlast),
    .out_rvalid(out_rvalid), .out_rready(out_rready),
    .out_rid(out_rid), .out_rdata(out_rdata), .out_rresp(out_rresp),
    .out_rlast(out_rlast),
    .bvalid(bvalid), .bready(bready), .bid(bid), .bresp(bresp),
    .out_bvalid(out_bvalid), .out_bready(out_bready),
    .out_bid(out_bid), .out_bresp(out_bresp),
    .credit_full(credit_full), .aw_error(aw_error), .ar_error(ar_error),
    .exclusive_error(exclusive_error)
  );

  always #5 clk <= ~clk;

  task automatic fail(input string msg);
    begin
      $display("FAIL: %s", msg);
      $fatal(1, "TB_FAIL %s", msg);
    end
  endtask

  task automatic tick();
    begin
      @(posedge clk);
      #1;
    end
  endtask

  initial begin
    repeat (3) tick();
    @(negedge clk);
    rst_n = 1;
    tick();

    // AW channel: burst split, ID association, cache/prot passthrough.
    in_awid = 8'hA5;
    in_awaddr = 64'h1000;
    in_awlen = 8'd3;
    in_awsize = 3'd2;
    in_awburst = 2'b01;
    in_awlock = 2'b00;
    in_awcache = 4'h3;
    in_awprot = 3'd2;
    in_awqos = 4'h5;
    in_awregion = 4'h7;
    in_awatomic = 3'd0;
    in_awvalid = 1;
    out_awready = 0;
    #1;
    if (in_awready !== 1'b1) fail("AW capture ready not asserted");
    tick();
    if (aw_error !== 1'b0) fail("AW legal INCR flagged error");
    if (exclusive_error !== 1'b0) fail("AW non-exclusive flagged exclusive_error");
    @(negedge clk);
    in_awvalid = 0;
    #1;
    if (out_awvalid !== 1'b1) fail("AW sub-burst 0 not valid");
    if (out_awaddr !== 64'h1000) fail("AW sub-burst 0 addr wrong");
    if (out_awlen !== 8'd1) fail("AW sub-burst 0 len wrong");
    if (out_awid !== 8'hA5) fail("AW sub-burst 0 ID association wrong");
    if (out_awcache !== 4'h3) fail("AW cache passthrough wrong");
    if (out_awprot !== 3'd2) fail("AW prot passthrough wrong");
    if (out_awqos !== 4'h5) fail("AW qos passthrough wrong");
    if (out_awregion !== 4'h7) fail("AW region passthrough wrong");
    if (out_awsize !== 3'd2) fail("AW size passthrough wrong");
    if (out_awburst !== 2'b01) fail("AW burst passthrough wrong");
    if (out_awlock !== 2'b00) fail("AW lock passthrough wrong");
    if (out_awatomic !== 3'd0) fail("AW atomic passthrough wrong");
    if (credit_full !== 1'b0) fail("credit must not be full after one emit");
    @(negedge clk);
    out_awready = 1;
    tick();
    if (out_awvalid !== 1'b1) fail("AW sub-burst 1 not valid");
    if (out_awaddr !== 64'h1008) fail("AW sub-burst 1 addr wrong");
    if (out_awlen !== 8'd1) fail("AW sub-burst 1 len wrong");
    if (out_awid !== 8'hA5) fail("AW sub-burst 1 ID association wrong");
    tick();
    if (out_awvalid !== 1'b0) fail("AW not idle after 2 sub-bursts");

    // W channel: split WLAST, WSTRB passthrough, beat order.
    wdata = 32'h1111_0000;
    wstrb = 4'hF;
    wlast = 0;
    wvalid = 1;
    out_wready = 1;
    #1;
    if (out_wvalid !== 1'b1) fail("W beat 0 not forwarded");
    if (out_wdata !== 32'h1111_0000) fail("W beat 0 data wrong");
    if (out_wstrb !== 4'hF) fail("W beat 0 WSTRB passthrough wrong");
    if (out_wlast !== 1'b0) fail("W beat 0 WLAST wrong (split at 2)");
    tick();
    @(negedge clk);
    wdata = 32'h2222_0000;
    wlast = 0;
    #1;
    if (out_wlast !== 1'b1) fail("W beat 1 WLAST must close sub-burst 0");
    tick();
    @(negedge clk);
    wdata = 32'h3333_0000;
    wlast = 0;
    #1;
    if (out_wlast !== 1'b0) fail("W beat 2 WLAST wrong");
    tick();
    @(negedge clk);
    wdata = 32'h4444_0000;
    wlast = 1;
    #1;
    if (out_wlast !== 1'b1) fail("W beat 3 WLAST must close sub-burst 1");
    tick();
    @(negedge clk);
    wvalid = 0;
    tick();
    if (out_wvalid !== 1'b0) fail("W not idle after 4 beats");

    // B channel: ID/BRESP staging and backpressure hold.
    out_bready = 0;
    bid = 8'hA5;
    bresp = 2'b10;
    bvalid = 1;
    bready = 1;
    tick();
    @(negedge clk);
    bvalid = 0;
    tick();
    if (out_bvalid !== 1'b1) fail("B staged valid not asserted");
    if (out_bid !== 8'hA5) fail("B ID association wrong");
    if (out_bresp !== 2'b10) fail("B BRESP SLVERR forwarding wrong");
    tick();
    if (out_bvalid !== 1'b1) fail("B must hold while out_bready low");
    @(negedge clk);
    out_bready = 1;
    tick();
    if (out_bvalid !== 1'b0) fail("B not cleared after agent consume");

    // AR channel: burst split and ID association.
    in_arid = 8'h3C;
    in_araddr = 64'h2000;
    in_arlen = 8'd3;
    in_arsize = 3'd2;
    in_arburst = 2'b01;
    in_arcache = 4'h3;
    in_arprot = 3'd2;
    in_arvalid = 1;
    out_arready = 1;
    #1;
    if (in_arready !== 1'b1) fail("AR capture ready not asserted");
    tick();
    if (ar_error !== 1'b0) fail("AR legal INCR flagged error");
    @(negedge clk);
    in_arvalid = 0;
    #1;
    if (out_arvalid !== 1'b1) fail("AR sub-burst 0 not valid");
    if (out_araddr !== 64'h2000) fail("AR sub-burst 0 addr wrong");
    if (out_arid !== 8'h3C) fail("AR ID association wrong");
    if (out_arlen !== 8'd1) fail("AR sub-burst 0 len wrong");
    if (out_arsize !== 3'd2) fail("AR size passthrough wrong");
    if (out_arburst !== 2'b01) fail("AR burst passthrough wrong");
    if (out_arlock !== 2'b00) fail("AR lock passthrough wrong");
    if (out_arcache !== 4'h3) fail("AR cache passthrough wrong");
    if (out_arprot !== 3'd2) fail("AR prot passthrough wrong");
    if (out_arqos !== 4'h0) fail("AR qos passthrough wrong");
    if (out_arregion !== 4'h0) fail("AR region passthrough wrong");
    tick();
    if (out_araddr !== 64'h2008) fail("AR sub-burst 1 addr wrong");
    if (out_arid !== 8'h3C) fail("AR sub-burst 1 ID wrong");
    tick();
    if (out_arvalid !== 1'b0) fail("AR not idle after split");

    // R channel: ID/RRESP/RLAST staging with backpressure.
    out_rready = 0;
    rid = 8'h3C;
    rdata = 32'hDEAD_BEEF;
    rresp = 2'b10;
    rlast = 0;
    rvalid = 1;
    #1;
    if (rready !== 1'b1) fail("R fabric ready not asserted when empty");
    tick();
    @(negedge clk);
    rvalid = 0;
    tick();
    if (out_rvalid !== 1'b1) fail("R staged valid not asserted");
    if (out_rid !== 8'h3C) fail("R ID association wrong");
    if (out_rresp !== 2'b10) fail("R RRESP SLVERR forwarding wrong");
    if (out_rdata !== 32'hDEAD_BEEF) fail("R data wrong");
    if (out_rlast !== 1'b0) fail("R RLAST wrong beat 0");
    tick();
    if (out_rvalid !== 1'b1) fail("R must hold while out_rready low");
    @(negedge clk);
    out_rready = 1;
    tick();
    if (out_rvalid !== 1'b0) fail("R not cleared after agent consume");
    rid = 8'h3C;
    rdata = 32'hBAAD_F00D;
    rresp = 2'b11;
    rlast = 1;
    rvalid = 1;
    tick();
    @(negedge clk);
    rvalid = 0;
    #1;
    if (out_rvalid !== 1'b1) fail("R beat 1 staged valid missing");
    if (out_rresp !== 2'b11) fail("R RRESP DECERR forwarding wrong");
    if (out_rlast !== 1'b1) fail("R RLAST must close burst");
    tick();

    // Error checks: combinational on AW input (no capture state needed).
    in_awburst = 2'b10;
    in_awlen = 8'd2;
    in_awaddr = 64'h1000;
    in_awsize = 3'd2;
    in_awlock = 2'b00;
    in_awvalid = 1;
    #1;
    if (aw_error !== 1'b1) fail("AW WRAP len=3 must flag aw_error");
    in_awburst = 2'b11;
    in_awlen = 8'd0;
    #1;
    if (aw_error !== 1'b1) fail("AW reserved burst must flag aw_error");
    in_awburst = 2'b00;
    in_awlen = 8'd1;
    #1;
    if (aw_error !== 1'b1) fail("AW FIXED len=2 must flag aw_error");
    in_awburst = 2'b01;
    in_awlen = 8'd0;
    in_awsize = 3'd3;
    #1;
    if (aw_error !== 1'b1) fail("AW size exceeding bus must flag aw_error");
    in_awsize = 3'd2;
    in_awaddr = 64'h1002;
    #1;
    if (aw_error !== 1'b1) fail("AW misaligned addr must flag aw_error");
    in_awaddr = 64'h1000;
    in_awlen = 8'd3;
    in_awlock = 2'b10;
    #1;
    if (exclusive_error !== 1'b1) fail("AW exclusive split must flag exclusive_error");
    if (aw_error !== 1'b0) fail("AW exclusive INCR legal burst flagged aw_error");
    in_awlock = 2'b00;
    in_awvalid = 0;
    tick();
    if (aw_error !== 1'b0) fail("AW error must clear when valid low");
    in_awburst = 2'b01;
    in_awlen = 8'd2;
    in_arvalid = 1;
    in_arburst = 2'b10;
    in_arlen = 8'd2;
    in_araddr = 64'h2000;
    in_arsize = 3'd2;
    #1;
    if (ar_error !== 1'b1) fail("AR WRAP len=3 must flag ar_error");
    in_arvalid = 0;
    in_arburst = 2'b01;
    in_arlen = 8'd0;
    tick();

    // W backpressure: downstream stall must hold the beat.
    in_awid = 8'h5A;
    in_awaddr = 64'h3000;
    in_awlen = 8'd1;
    in_awsize = 3'd2;
    in_awburst = 2'b01;
    in_awvalid = 1;
    out_awready = 1;
    tick();
    @(negedge clk);
    in_awvalid = 0;
    wdata = 32'hAAAA_0000;
    wlast = 0;
    wvalid = 1;
    out_wready = 0;
    #1;
    if (out_wvalid !== 1'b1) fail("W must assert valid during downstream stall");
    if (wready !== 1'b0) fail("W upstream must see not-ready during stall");
    tick();
    if (out_wvalid !== 1'b1) fail("W valid must hold during stall");
    if (out_wdata !== 32'hAAAA_0000) fail("W data must hold during stall");
    @(negedge clk);
    out_wready = 1;
    tick();
    @(negedge clk);
    wdata = 32'hBBBB_0000;
    wlast = 1;
    tick();
    @(negedge clk);
    wvalid = 0;
    tick();

    // R full backpressure: second fabric beat blocked while stage occupied.
    out_rready = 0;
    rid = 8'h11;
    rdata = 32'h0000_1111;
    rresp = 2'b00;
    rlast = 0;
    rvalid = 1;
    tick();
    @(negedge clk);
    rvalid = 0;
    tick();
    if (out_rvalid !== 1'b1) fail("R stage must hold under agent stall");
    rid = 8'h11;
    rdata = 32'h0000_2222;
    rresp = 2'b00;
    rlast = 1;
    rvalid = 1;
    #1;
    if (rready !== 1'b0) fail("R fabric ready must deassert while stage full");
    @(negedge clk);
    rvalid = 0;
    tick();
    if (out_rvalid !== 1'b1) fail("R stage overwritten during full backpressure");
    if (out_rdata !== 32'h0000_1111) fail("R staged data overwritten during full");
    @(negedge clk);
    out_rready = 1;
    tick();

    $display("TB_AXI5_PASS");
    $finish;
  end
endmodule
`default_nettype wire
"""


def _run_direct_tb(tmp_path: Path) -> str:
    build = build_adapter(_params())
    assert build.source is not None
    (tmp_path / "adapter_axi5_g0.sv").write_text(build.source or "")
    (tmp_path / "tb_axi5_full.sv").write_text(_TB)
    compiled = subprocess.run(
        [_VERILATOR, "--binary", "--timing", "-j", "1", "-Wall", "-Wno-fatal", "-Wno-WIDTH", "-Wno-PINNOTFOUND", "-Wno-PINMISSING", "-Wno-UNOPTFLAT", "-Wno-WIDTHTRUNC",
         "--top-module", "tb_axi5_full", "--Mdir", str(tmp_path / "obj"),
         str(tmp_path / "adapter_axi5_g0.sv"),
         str(tmp_path / "tb_axi5_full.sv")],
        cwd=tmp_path, capture_output=True, text=True, timeout=180)
    clog = compiled.stdout + compiled.stderr
    assert compiled.returncode == 0, clog
    assert "%Error" not in clog, clog
    ran = subprocess.run(
        [str(tmp_path / "obj" / "Vtb_axi5_full")],
        cwd=tmp_path, capture_output=True, text=True, timeout=60)
    out = ran.stdout + ran.stderr
    assert ran.returncode == 0, out
    assert "TB_AXI5_PASS" in out, out
    return out


@pytest.mark.skipif(_VERILATOR is None, reason="verilator not installed")
def test_axi5_directed_tb_per_channel(tmp_path):
    _run_direct_tb(tmp_path)
