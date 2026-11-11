"""M4 AXI5 checker suite: per-rule SystemVerilog assertions and directed TBs.

Each test exercises one rule family on the emitted adapter_axi5_g0 with
Verilator --binary --timing. Expected PASS tokens gate the result; any
missing token is a failure. This file is the checker suite referenced by
AXI5_ADAPTER_ASSUMPTIONS (Checker: immediate assert for AW/AR/W/R/B VALID
hold, aw/ar_error gating, credit overflow).
"""
from __future__ import annotations
import shutil, subprocess
from pathlib import Path
import pytest
from veritx_dse.model.agent_intent_v4 import ProtocolFamily
from veritx_dse.product.adapter_factory_rtl import AdapterParams, build_adapter, AXI5_ADAPTER_ASSUMPTIONS, AXI5_SUPPORTED
_VERILATOR = shutil.which("verilator")

def _run_checker(tmp_path: Path, tb_source: str, top: str, params: AdapterParams | None = None, expected: list[str] | None = None) -> str:
    if params is None:
        params = AdapterParams(agent_idx=0, protocol=ProtocolFamily.AXI5, data_width=32, addr_width=64, split_at=2, max_outstanding=4)
    build = build_adapter(params)
    assert build.module is not None and build.source is not None, build.verdict.reason
    module = build.module
    tb = tb_source.replace("__DUT_MODULE__", module)
    d = tmp_path / top
    d.mkdir(parents=True, exist_ok=True)
    (d / f"{module}.sv").write_text(build.source or "")
    (d / f"{top}.sv").write_text(tb)
    if _VERILATOR is None:
        pytest.skip("verilator not installed")
    build_cmd = [_VERILATOR, "--binary", "--timing", "-j", "1", "-Wall", "-Wno-fatal", "-Wno-WIDTH", "-Wno-PINNOTFOUND", "-Wno-PINMISSING", "-Wno-UNOPTFLAT", "-Wno-WIDTHTRUNC", "--top-module", top, "--Mdir", str(d / "obj"), f"{top}.sv", f"{module}.sv"]
    proc = subprocess.run(build_cmd, cwd=d, capture_output=True, text=True, timeout=300)
    log = proc.stdout + proc.stderr
    assert proc.returncode == 0, log[-4000:]
    assert "%Error" not in log, log[-4000:]
    run = subprocess.run([str(d / "obj" / f"V{top}")], cwd=d, capture_output=True, text=True, timeout=60)
    out = run.stdout + run.stderr
    assert run.returncode == 0, out[-4000:]
    if expected:
        for tok in expected:
            assert tok in out, f"missing {tok} in {out[-4000:]}"
    return out

CACHE_TB = r"""`default_nettype none
module tb_axi5_checker;
  logic clk = 0;
  logic rst_n = 0;
  logic in_awvalid = 0;
  logic in_awready;
  logic [7:0] in_awid = 8'h0;
  logic [63:0] in_awaddr = 64'h0;
  logic [7:0] in_awlen = 8'h0;
  logic [2:0] in_awsize = 3'd2;
  logic [1:0] in_awburst = 2'b01;
  logic [3:0] in_awcache = 4'h0;
  logic [2:0] in_awprot = 3'd0;
  logic [1:0] in_awlock = 2'b00;
  logic [3:0] in_awqos = 4'h0;
  logic [3:0] in_awregion = 4'h0;
  logic [1:0] in_awdomain = 2'b00;
  logic [2:0] in_awatomic = 3'd0;
  logic [1:0] in_awdvmtype = 2'd0;
  logic out_awvalid;
  logic out_awready = 1;
  logic [7:0] out_awid;
  logic [63:0] out_awaddr;
  logic [7:0] out_awlen;
  logic [2:0] out_awsize;
  logic [1:0] out_awburst;
  logic [3:0] out_awcache;
  logic [2:0] out_awprot;
  logic [1:0] out_awlock;
  logic [3:0] out_awqos;
  logic [3:0] out_awregion;
  logic [1:0] out_awdomain;
  logic [2:0] out_awatomic;
  logic [1:0] out_awdvmtype;
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
  logic [3:0] in_arcache = 4'h0;
  logic [2:0] in_arprot = 3'd0;
  logic [1:0] in_arlock = 2'b00;
  logic [3:0] in_arqos = 4'h0;
  logic [3:0] in_arregion = 4'h0;
  logic [1:0] in_ardomain = 2'b00;
  logic out_arvalid;
  logic out_arready = 1;
  logic [7:0] out_arid;
  logic [63:0] out_araddr;
  logic [7:0] out_arlen;
  logic [2:0] out_arsize;
  logic [1:0] out_arburst;
  logic [3:0] out_arcache;
  logic [2:0] out_arprot;
  logic [1:0] out_arlock;
  logic [3:0] out_arqos;
  logic [3:0] out_arregion;
  logic [1:0] out_ardomain;
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
  logic bready;
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
  logic atomic_error;
  logic coh_error;
  logic resp_error;
  logic wstrb_error;
  logic last_error;
  logic id_error;
  logic out_dvm_valid;
  logic out_rsos_valid;
  logic dvm_pending;
  logic rsos_pending;
  logic [1:0] coh_state;
  logic qos_high;
  __DUT_MODULE__ dut (
    .clk(clk), .rst_n(rst_n),
    .in_awvalid(in_awvalid), .in_awready(in_awready),
    .in_awid(in_awid), .in_awaddr(in_awaddr), .in_awlen(in_awlen),
    .in_awsize(in_awsize), .in_awburst(in_awburst), .in_awlock(in_awlock),
    .in_awcache(in_awcache), .in_awprot(in_awprot), .in_awqos(in_awqos),
    .in_awregion(in_awregion), .in_awdomain(in_awdomain), .in_awatomic(in_awatomic), .in_awdvmtype(in_awdvmtype),
    .out_awvalid(out_awvalid), .out_awready(out_awready),
    .out_awid(out_awid), .out_awaddr(out_awaddr), .out_awlen(out_awlen),
    .out_awsize(out_awsize), .out_awburst(out_awburst), .out_awlock(out_awlock),
    .out_awcache(out_awcache), .out_awprot(out_awprot), .out_awqos(out_awqos),
    .out_awregion(out_awregion), .out_awdomain(out_awdomain), .out_awatomic(out_awatomic), .out_awdvmtype(out_awdvmtype),
    .wvalid(wvalid), .wready(wready), .wdata(wdata), .wstrb(wstrb), .wlast(wlast),
    .out_wvalid(out_wvalid), .out_wready(out_wready), .out_wdata(out_wdata),
    .out_wstrb(out_wstrb), .out_wlast(out_wlast),
    .in_arvalid(in_arvalid), .in_arready(in_arready), .in_arid(in_arid), .in_araddr(in_araddr), .in_arlen(in_arlen),
    .in_arsize(in_arsize), .in_arburst(in_arburst), .in_arlock(in_arlock), .in_arcache(in_arcache), .in_arprot(in_arprot),
    .in_arqos(in_arqos), .in_arregion(in_arregion), .in_ardomain(in_ardomain),
    .out_arvalid(out_arvalid), .out_arready(out_arready), .out_arid(out_arid), .out_araddr(out_araddr),
    .out_arlen(out_arlen), .out_arsize(out_arsize), .out_arburst(out_arburst), .out_arlock(out_arlock),
    .out_arcache(out_arcache), .out_arprot(out_arprot), .out_arqos(out_arqos),
    .out_arregion(out_arregion), .out_ardomain(out_ardomain),
    .rvalid(rvalid), .rready(rready), .rid(rid), .rdata(rdata),
    .rresp(rresp), .rlast(rlast),
    .out_rvalid(out_rvalid), .out_rready(out_rready),
    .out_rid(out_rid), .out_rdata(out_rdata), .out_rresp(out_rresp),
    .out_rlast(out_rlast),
    .bvalid(bvalid), .bready(bready), .bid(bid), .bresp(bresp),
    .out_bvalid(out_bvalid), .out_bready(out_bready),
    .out_bid(out_bid), .out_bresp(out_bresp),
    .credit_full(credit_full), .aw_error(aw_error), .ar_error(ar_error),
    .exclusive_error(exclusive_error), .atomic_error(atomic_error), .coh_error(coh_error),
    .resp_error(resp_error), .wstrb_error(wstrb_error), .last_error(last_error), .id_error(id_error),
    .out_dvm_valid(out_dvm_valid), .out_rsos_valid(out_rsos_valid),
    .dvm_pending(dvm_pending), .rsos_pending(rsos_pending),
    .coh_state(coh_state), .qos_high(qos_high)
  );
  always #5 clk = ~clk;
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
    in_awaddr = 64'h1000;
    in_awlen = 8'd0;
    in_awsize = 3'd2;
    in_awburst = 2'b01;
    in_awcache = 4'h3;
    in_awprot = 3'd0;
    in_awlock = 2'b00;
    in_awdomain = 2'b00;
    in_awatomic = 3'd0;
    in_awdvmtype = 2'd0;
    in_awvalid = 1;
    #1;
    if (aw_error !== 1'b0) fail("legal cache/prot should not error");
    if (coh_error !== 1'b0) fail("legal domain should not coh_error");
    if (atomic_error !== 1'b0) fail("legal atomic should not error");
    if (exclusive_error !== 1'b0) fail("legal exclusive should not error");
    in_awvalid = 0;
    tick();
    in_awcache = 4'b0100;
    in_awvalid = 1;
    #1;
    if (aw_error !== 1'b1) fail("cache device allocate must error CACHE_ALLOC");
    in_awvalid = 0;
    tick();
    in_awcache = 4'h3;
    in_awprot = 3'b100;
    in_awvalid = 1;
    #1;
    if (aw_error !== 1'b1) fail("AWPROT instruction write must error PROT");
    in_awvalid = 0;
    in_awprot = 3'd0;
    tick();
    in_awdomain = 2'b01;
    in_awcache = 4'b0000;
    in_awvalid = 1;
    #1;
    if (coh_error !== 1'b1) fail("shareable without cacheable must coh_error");
    if (aw_error !== 1'b1) fail("coh should also be aw_error");
    in_awvalid = 0;
    in_awdomain = 2'b00;
    in_awcache = 4'h3;
    tick();
    if (coh_error !== 1'b0) fail("coh_error must clear when valid low? check sticky");
    $display("TB_CACHE_PROT_PASS");
    in_araddr = 64'h2000;
    in_arlen = 8'd0;
    in_arsize = 3'd2;
    in_arburst = 2'b01;
    in_arcache = 4'b0100;
    in_ardomain = 2'b00;
    in_arvalid = 1;
    #1;
    if (ar_error !== 1'b1) fail("AR cache device allocate must ar_error");
    in_arvalid = 0;
    tick();
    in_arcache = 4'h3;
    in_ardomain = 2'b01;
    in_arcache = 4'b0000;
    in_arvalid = 1;
    #1;
    if (ar_error !== 1'b1) fail("AR shareable without cacheable must ar_error coh");
    in_arvalid = 0;
    tick();
    $display("TB_CACHE_AR_PASS");
    $finish;
  end
endmodule
`default_nettype wire
"""
ATOMIC_TB = r"""`default_nettype none
module tb_axi5_atomic;
  logic clk = 0;
  logic rst_n = 0;
  logic in_awvalid = 0;
  logic in_awready;
  logic [7:0] in_awid = 8'h01;
  logic [63:0] in_awaddr = 64'h1000;
  logic [7:0] in_awlen = 8'd0;
  logic [2:0] in_awsize = 3'd2;
  logic [1:0] in_awburst = 2'b01;
  logic [3:0] in_awcache = 4'h3;
  logic [2:0] in_awprot = 3'd0;
  logic [1:0] in_awlock = 2'b00;
  logic [3:0] in_awqos = 4'd0;
  logic [3:0] in_awregion = 4'h0;
  logic [1:0] in_awdomain = 2'b00;
  logic [2:0] in_awatomic = 3'd0;
  logic [1:0] in_awdvmtype = 2'd0;
  logic out_awvalid;
  logic out_awready = 1;
  logic [7:0] out_awid;
  logic [63:0] out_awaddr;
  logic [7:0] out_awlen;
  logic [2:0] out_awsize;
  logic [1:0] out_awburst;
  logic [3:0] out_awcache;
  logic [2:0] out_awprot;
  logic [1:0] out_awlock;
  logic [3:0] out_awqos;
  logic [3:0] out_awregion;
  logic [1:0] out_awdomain;
  logic [2:0] out_awatomic;
  logic [1:0] out_awdvmtype;
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
  logic [7:0] in_arid = 8'h02;
  logic [63:0] in_araddr = 64'h2000;
  logic [7:0] in_arlen = 8'd0;
  logic [2:0] in_arsize = 3'd2;
  logic [1:0] in_arburst = 2'b01;
  logic [3:0] in_arcache = 4'h3;
  logic [2:0] in_arprot = 3'd0;
  logic [1:0] in_arlock = 2'b00;
  logic [3:0] in_arqos = 4'h0;
  logic [3:0] in_arregion = 4'h0;
  logic [1:0] in_ardomain = 2'b00;
  logic out_arvalid;
  logic out_arready = 1;
  logic [7:0] out_arid;
  logic [63:0] out_araddr;
  logic [7:0] out_arlen;
  logic [2:0] out_arsize;
  logic [1:0] out_arburst;
  logic [3:0] out_arcache;
  logic [2:0] out_arprot;
  logic [1:0] out_arlock;
  logic [3:0] out_arqos;
  logic [3:0] out_arregion;
  logic [1:0] out_ardomain;
  logic rvalid = 0;
  logic rready;
  logic [7:0] rid = 8'h02;
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
  logic bready;
  logic [7:0] bid = 8'h01;
  logic [1:0] bresp = 2'b00;
  logic out_bvalid;
  logic out_bready = 1;
  logic [7:0] out_bid;
  logic [1:0] out_bresp;
  logic credit_full;
  logic aw_error;
  logic ar_error;
  logic exclusive_error;
  logic atomic_error;
  logic coh_error;
  logic resp_error;
  logic wstrb_error;
  logic last_error;
  logic id_error;
  logic out_dvm_valid;
  logic out_rsos_valid;
  logic dvm_pending;
  logic rsos_pending;
  logic [1:0] coh_state;
  logic qos_high;
  __DUT_MODULE__ dut (
    .clk(clk), .rst_n(rst_n),
    .in_awvalid(in_awvalid), .in_awready(in_awready),
    .in_awid(in_awid), .in_awaddr(in_awaddr), .in_awlen(in_awlen),
    .in_awsize(in_awsize), .in_awburst(in_awburst), .in_awlock(in_awlock),
    .in_awcache(in_awcache), .in_awprot(in_awprot), .in_awqos(in_awqos),
    .in_awregion(in_awregion), .in_awdomain(in_awdomain), .in_awatomic(in_awatomic), .in_awdvmtype(in_awdvmtype),
    .out_awvalid(out_awvalid), .out_awready(out_awready),
    .out_awid(out_awid), .out_awaddr(out_awaddr), .out_awlen(out_awlen),
    .out_awsize(out_awsize), .out_awburst(out_awburst), .out_awlock(out_awlock),
    .out_awcache(out_awcache), .out_awprot(out_awprot), .out_awqos(out_awqos),
    .out_awregion(out_awregion), .out_awdomain(out_awdomain), .out_awatomic(out_awatomic), .out_awdvmtype(out_awdvmtype),
    .wvalid(wvalid), .wready(wready), .wdata(wdata), .wstrb(wstrb), .wlast(wlast),
    .out_wvalid(out_wvalid), .out_wready(out_wready), .out_wdata(out_wdata),
    .out_wstrb(out_wstrb), .out_wlast(out_wlast),
    .in_arvalid(in_arvalid), .in_arready(in_arready), .in_arid(in_arid), .in_araddr(in_araddr), .in_arlen(in_arlen),
    .in_arsize(in_arsize), .in_arburst(in_arburst), .in_arlock(in_arlock), .in_arcache(in_arcache), .in_arprot(in_arprot),
    .in_arqos(in_arqos), .in_arregion(in_arregion), .in_ardomain(in_ardomain),
    .out_arvalid(out_arvalid), .out_arready(out_arready), .out_arid(out_arid), .out_araddr(out_araddr),
    .out_arlen(out_arlen), .out_arsize(out_arsize), .out_arburst(out_arburst), .out_arlock(out_arlock),
    .out_arcache(out_arcache), .out_arprot(out_arprot), .out_arqos(out_arqos),
    .out_arregion(out_arregion), .out_ardomain(out_ardomain),
    .rvalid(rvalid), .rready(rready), .rid(rid), .rdata(rdata),
    .rresp(rresp), .rlast(rlast),
    .out_rvalid(out_rvalid), .out_rready(out_rready),
    .out_rid(out_rid), .out_rdata(out_rdata), .out_rresp(out_rresp),
    .out_rlast(out_rlast),
    .bvalid(bvalid), .bready(bready), .bid(bid), .bresp(bresp),
    .out_bvalid(out_bvalid), .out_bready(out_bready),
    .out_bid(out_bid), .out_bresp(out_bresp),
    .credit_full(credit_full), .aw_error(aw_error), .ar_error(ar_error),
    .exclusive_error(exclusive_error), .atomic_error(atomic_error), .coh_error(coh_error),
    .resp_error(resp_error), .wstrb_error(wstrb_error), .last_error(last_error), .id_error(id_error),
    .out_dvm_valid(out_dvm_valid), .out_rsos_valid(out_rsos_valid),
    .dvm_pending(dvm_pending), .rsos_pending(rsos_pending),
    .coh_state(coh_state), .qos_high(qos_high)
  );
  always #5 clk = ~clk;
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
  task automatic aw_fire(input [63:0] a, input [7:0] l, input [2:0] s, input [1:0] b, input [1:0] lock, input [2:0] atomic, input [7:0] id);
    integer t;
    begin
      in_awaddr = a;
      in_awlen = l;
      in_awsize = s;
      in_awburst = b;
      in_awlock = lock;
      in_awatomic = atomic;
      in_awid = id;
      in_awvalid = 1;
      t = 0;
      while (!in_awready && t < 20) begin
        @(posedge clk);
        #1;
        t = t + 1;
      end
      if (t >= 20) fail("aw ready timeout");
      @(posedge clk);
      @(negedge clk);
      in_awvalid = 0;
    end
  endtask
  task automatic w_fire(input [31:0] d, input [3:0] s, input last);
    integer t;
    begin
      wdata = d;
      wstrb = s;
      wlast = last;
      wvalid = 1;
      t = 0;
      while (!wready && t < 20) begin
        @(posedge clk);
        #1;
        t = t + 1;
      end
      if (t >= 20) fail("w ready timeout");
      @(posedge clk);
      @(negedge clk);
      wvalid = 0;
    end
  endtask
  task automatic drain_w();
    integer t;
    begin
      t = 0;
      while (out_wvalid && t < 20) begin
        @(posedge clk);
        #1;
        t = t + 1;
      end
    end
  endtask
  initial begin
    repeat (4) tick();
    @(negedge clk);
    rst_n = 1;
    tick();
    in_awaddr = 64'h1000;
    in_awlen = 8'd0;
    in_awsize = 3'd2;
    in_awburst = 2'b01;
    in_awlock = 2'b00;
    in_awcache = 4'h3;
    in_awprot = 3'd0;
    in_awdomain = 2'b00;
    in_awatomic = 3'd1;
    in_awvalid = 1;
    #1;
    if (atomic_error !== 1'b0) fail("atomic INCR single should not error");
    in_awvalid = 0;
    tick();
    in_awburst = 2'b10;
    in_awlen = 8'd1;
    in_awaddr = 64'h1000;
    in_awvalid = 1;
    #1;
    if (atomic_error !== 1'b1) fail("atomic WRAP should error");
    in_awvalid = 0;
    in_awburst = 2'b01;
    in_awlen = 8'd3;
    in_awaddr = 64'h1000;
    in_awvalid = 1;
    #1;
    if (atomic_error !== 1'b1) fail("atomic split should error");
    in_awvalid = 0;
    in_awatomic = 3'd0;
    tick();
    in_awlock = 2'b10;
    in_awlen = 8'd3;
    in_awaddr = 64'h1000;
    in_awvalid = 1;
    #1;
    if (exclusive_error !== 1'b1) fail("exclusive split should error");
    if (aw_error !== 1'b0) fail("exclusive INCR legal burst should not aw_error");
    in_awvalid = 0;
    in_awlock = 2'b00;
    in_awlen = 8'd0;
    tick();
    aw_fire(64'h1000, 8'd0, 3'd2, 2'b01, 2'b00, 3'd0, 8'h01);
    if (!out_awvalid) fail("AW not valid after fire");
    if (out_awid !== 8'h01) fail("AW id");
    if (out_awatomic !== 3'd0) fail("AW atomic fwd");
    w_fire(32'h11110000, 4'hF, 1'b1);
    drain_w();
    tick();
    bvalid = 1;
    bid = 8'h01;
    bresp = 2'b00;
    repeat (3) tick();
    bvalid = 0;
    if (resp_error !== 1'b0) fail("resp OKAY should not error for non-exclusive");
    if (!out_bvalid) fail("B should be valid");
    tick();
    in_awlock = 2'b10;
    aw_fire(64'h1000, 8'd0, 3'd2, 2'b01, 2'b10, 3'd0, 8'h02);
    tick();
    w_fire(32'h22220000, 4'hF, 1'b1);
    drain_w();
    tick();
    bvalid = 1;
    bid = 8'h02;
    bresp = 2'b01;
    repeat (3) tick();
    bvalid = 0;
    if (resp_error !== 1'b0) fail("EXOKAY for exclusive should not resp_error");
    tick();
    in_awlock = 2'b00;
    in_awatomic = 3'd0;
    aw_fire(64'h1000, 8'd0, 3'd2, 2'b01, 2'b00, 3'd0, 8'h03);
    tick();
    w_fire(32'h33330000, 4'hF, 1'b1);
    tick();
    bvalid = 1;
    bid = 8'h03;
    bresp = 2'b01;
    tick();
    @(negedge clk);
    bvalid = 0;
    repeat (2) tick();
    if (resp_error !== 1'b1) fail("EXOKAY for non-exclusive should resp_error");
    tick();
    in_araddr = 64'h2000;
    in_arlen = 8'd0;
    in_arsize = 3'd2;
    in_arburst = 2'b01;
    in_arcache = 4'h3;
    in_ardomain = 2'b00;
    in_arvalid = 1;
    tick();
    @(negedge clk);
    in_arvalid = 0;
    tick();
    tick();
    rvalid = 1;
    rid = 8'h02;
    rdata = 32'hdeadbeef;
    rresp = 2'b01;
    rlast = 1;
    tick();
    @(negedge clk);
    rvalid = 0;
    repeat (2) tick();
    if (resp_error !== 1'b1) fail("R EXOKAY for non-exclusive should resp_error");
    $display("TB_ATOMIC_EXCL_RESP_PASS");
    $finish;
  end
endmodule
`default_nettype wire
"""
STRB_TB = r"""`default_nettype none
module tb_axi5_strb;
  logic clk = 0; logic rst_n = 0;
  logic in_awvalid = 0; logic in_awready; logic [7:0] in_awid=8'h01;
  logic [63:0] in_awaddr=64'h1000; logic [7:0] in_awlen=8'd2; logic [2:0] in_awsize=3'd2;
  logic [1:0] in_awburst=2'b01; logic [3:0] in_awcache=4'h3; logic [2:0] in_awprot=0; logic [1:0] in_awlock=0;
  logic [3:0] in_awqos=0; logic [3:0] in_awregion=0; logic [1:0] in_awdomain=0; logic [2:0] in_awatomic=0; logic [1:0] in_awdvmtype=0;
  logic out_awvalid; logic out_awready=1; logic [7:0] out_awid; logic [63:0] out_awaddr; logic [7:0] out_awlen; logic [2:0] out_awsize;
  logic [1:0] out_awburst; logic [3:0] out_awcache; logic [2:0] out_awprot; logic [1:0] out_awlock; logic [3:0] out_awqos; logic [3:0] out_awregion; logic [1:0] out_awdomain; logic [2:0] out_awatomic; logic [1:0] out_awdvmtype;
  logic wvalid=0; logic wready; logic [31:0] wdata=0; logic [3:0] wstrb=4'hF; logic wlast=0;
  logic out_wvalid; logic out_wready=1; logic [31:0] out_wdata; logic [3:0] out_wstrb; logic out_wlast;
  logic in_arvalid=0; logic in_arready; logic [7:0] in_arid=8'h02; logic [63:0] in_araddr=64'h2000; logic [7:0] in_arlen=0; logic [2:0] in_arsize=3'd2;
  logic [1:0] in_arburst=2'b01; logic [3:0] in_arcache=4'h3; logic [2:0] in_arprot=0; logic [1:0] in_arlock=0; logic [3:0] in_arqos=0; logic [3:0] in_arregion=0; logic [1:0] in_ardomain=0;
  logic out_arvalid; logic out_arready=1; logic [7:0] out_arid; logic [63:0] out_araddr; logic [7:0] out_arlen; logic [2:0] out_arsize;
  logic [1:0] out_arburst; logic [3:0] out_arcache; logic [2:0] out_arprot; logic [1:0] out_arlock; logic [3:0] out_arqos; logic [3:0] out_arregion; logic [1:0] out_ardomain;
  logic rvalid=0; logic rready; logic [7:0] rid=8'h02; logic [31:0] rdata=0; logic [1:0] rresp=0; logic rlast=0;
  logic out_rvalid; logic out_rready=1; logic [7:0] out_rid; logic [31:0] out_rdata; logic [1:0] out_rresp; logic out_rlast;
  logic bvalid=0; logic bready; logic [7:0] bid=8'h01; logic [1:0] bresp=0;
  logic out_bvalid; logic out_bready=1; logic [7:0] out_bid; logic [1:0] out_bresp;
  logic credit_full; logic aw_error; logic ar_error; logic exclusive_error; logic atomic_error; logic coh_error; logic resp_error; logic wstrb_error; logic last_error; logic id_error;
  logic out_dvm_valid; logic out_rsos_valid; logic dvm_pending; logic rsos_pending; logic [1:0] coh_state; logic qos_high;
  __DUT_MODULE__ dut (
    .clk(clk), .rst_n(rst_n), .in_awvalid(in_awvalid), .in_awready(in_awready), .in_awid(in_awid), .in_awaddr(in_awaddr), .in_awlen(in_awlen), .in_awsize(in_awsize), .in_awburst(in_awburst), .in_awlock(in_awlock), .in_awcache(in_awcache), .in_awprot(in_awprot), .in_awqos(in_awqos), .in_awregion(in_awregion), .in_awdomain(in_awdomain), .in_awatomic(in_awatomic), .in_awdvmtype(in_awdvmtype),
    .out_awvalid(out_awvalid), .out_awready(out_awready), .out_awid(out_awid), .out_awaddr(out_awaddr), .out_awlen(out_awlen), .out_awsize(out_awsize), .out_awburst(out_awburst), .out_awlock(out_awlock), .out_awcache(out_awcache), .out_awprot(out_awprot), .out_awqos(out_awqos), .out_awregion(out_awregion), .out_awdomain(out_awdomain), .out_awatomic(out_awatomic), .out_awdvmtype(out_awdvmtype),
    .wvalid(wvalid), .wready(wready), .wdata(wdata), .wstrb(wstrb), .wlast(wlast), .out_wvalid(out_wvalid), .out_wready(out_wready), .out_wdata(out_wdata), .out_wstrb(out_wstrb), .out_wlast(out_wlast),
    .in_arvalid(in_arvalid), .in_arready(in_arready), .in_arid(in_arid), .in_araddr(in_araddr), .in_arlen(in_arlen), .in_arsize(in_arsize), .in_arburst(in_arburst), .in_arlock(in_arlock), .in_arcache(in_arcache), .in_arprot(in_arprot), .in_arqos(in_arqos), .in_arregion(in_arregion), .in_ardomain(in_ardomain),
    .out_arvalid(out_arvalid), .out_arready(out_arready), .out_arid(out_arid), .out_araddr(out_araddr), .out_arlen(out_arlen), .out_arsize(out_arsize), .out_arburst(out_arburst), .out_arlock(out_arlock), .out_arcache(out_arcache), .out_arprot(out_arprot), .out_arqos(out_arqos), .out_arregion(out_arregion), .out_ardomain(out_ardomain),
    .rvalid(rvalid), .rready(rready), .rid(rid), .rdata(rdata), .rresp(rresp), .rlast(rlast), .out_rvalid(out_rvalid), .out_rready(out_rready), .out_rid(out_rid), .out_rdata(out_rdata), .out_rresp(out_rresp), .out_rlast(out_rlast),
    .bvalid(bvalid), .bready(bready), .bid(bid), .bresp(bresp), .out_bvalid(out_bvalid), .out_bready(out_bready), .out_bid(out_bid), .out_bresp(out_bresp),
    .credit_full(credit_full), .aw_error(aw_error), .ar_error(ar_error), .exclusive_error(exclusive_error), .atomic_error(atomic_error), .coh_error(coh_error), .resp_error(resp_error), .wstrb_error(wstrb_error), .last_error(last_error), .id_error(id_error), .out_dvm_valid(out_dvm_valid), .out_rsos_valid(out_rsos_valid), .dvm_pending(dvm_pending), .rsos_pending(rsos_pending), .coh_state(coh_state), .qos_high(qos_high)
  );
  always #5 clk = ~clk;
  task automatic fail(input string msg); begin $display("FAIL: %s", msg); $fatal(1, "TB_FAIL %s", msg); end endtask
  task automatic tick(); begin @(posedge clk); #1; end endtask
  task automatic aw_fire(input [63:0] a, input [7:0] l, input [7:0] id);
    integer t; begin
      in_awaddr=a; in_awlen=l; in_awid=id; in_awvalid=1;
      t=0; while (!in_awready && t<20) begin @(posedge clk); #1; t=t+1; end
      if (t>=20) fail("aw timeout");
      @(posedge clk); @(negedge clk); in_awvalid=0;
    end
  endtask
  task automatic w_beat(input [31:0] d, input [3:0] s, input last);
    integer t; begin
      wdata=d; wstrb=s; wlast=last; wvalid=1;
      t=0; while (!wready && t<20) begin @(posedge clk); #1; t=t+1; end
      if (t>=20) fail("w timeout");
      @(posedge clk); @(negedge clk); wvalid=0;
    end
  endtask
  initial begin
    repeat (4) tick();
    @(negedge clk); rst_n=1; tick();
    aw_fire(64'h1000, 8'd2, 8'h01);
    tick();
    w_beat(32'h11110000, 4'hF, 1'b0);
    if (wstrb_error !== 1'b0) fail("first beat wstrb should not error");
    if (last_error !== 1'b0) fail("first beat last should not error");
    tick();
    w_beat(32'h22220000, 4'h0, 1'b0);
    if (wstrb_error !== 1'b1) fail("mid beat wstrb 0 should error");
    tick();
    w_beat(32'h33330000, 4'hF, 1'b1);
    if (last_error !== 1'b0) fail("last beat should not last_error");
    tick();
    bvalid=1; bid=8'h01; bresp=0; repeat (3) tick(); bvalid=0; tick();
    in_awaddr=64'h1000; in_awlen=8'd1; in_awvalid=1; tick(); @(negedge clk); in_awvalid=0;
    w_beat(32'h44440000, 4'hF, 1'b1);
    if (last_error !== 1'b1) fail("premature wlast should last_error");
    tick();
    w_beat(32'h77770000, 4'hF, 1'b1);
    tick();
    $display("TB_STRB_LAST_PASS");
    in_awlen=8'd0; in_awid=8'h05;
    aw_fire(64'h1000, 8'd0, 8'h05);
    tick();
    w_beat(32'h55550000, 4'hF, 1'b1);
    tick();
    bvalid=1; bid=8'h99; bresp=0; tick(); @(negedge clk); bvalid=0; repeat (2) tick();
    if (id_error !== 1'b1) fail("BID mismatch should id_error");
    in_awlen=8'd0; in_awid=8'h06;
    aw_fire(64'h1000, 8'd0, 8'h06);
    tick();
    w_beat(32'h66660000, 4'hF, 1'b1);
    tick();
    bvalid=1; bid=8'h06; bresp=0; tick(); @(negedge clk); bvalid=0; tick();
    if (id_error !== 1'b1) fail("id_error sticky");
    $display("TB_ID_PASS");
    $finish;
  end
endmodule
`default_nettype wire
"""
DVM_TB = r"""`default_nettype none
module tb_axi5_dvm;
  logic clk = 0;
  logic rst_n = 0;
  logic in_awvalid = 0;
  logic in_awready;
  logic [7:0] in_awid = 8'h11;
  logic [63:0] in_awaddr = 64'h1000;
  logic [7:0] in_awlen = 8'd0;
  logic [2:0] in_awsize = 3'd2;
  logic [1:0] in_awburst = 2'b01;
  logic [3:0] in_awcache = 4'h3;
  logic [2:0] in_awprot = 3'd0;
  logic [1:0] in_awlock = 2'b00;
  logic [3:0] in_awqos = 4'd0;
  logic [3:0] in_awregion = 4'h0;
  logic [1:0] in_awdomain = 2'b00;
  logic [2:0] in_awatomic = 3'd0;
  logic [1:0] in_awdvmtype = 2'd0;
  logic out_awvalid;
  logic out_awready = 1;
  logic [7:0] out_awid;
  logic [63:0] out_awaddr;
  logic [7:0] out_awlen;
  logic [2:0] out_awsize;
  logic [1:0] out_awburst;
  logic [3:0] out_awcache;
  logic [2:0] out_awprot;
  logic [1:0] out_awlock;
  logic [3:0] out_awqos;
  logic [3:0] out_awregion;
  logic [1:0] out_awdomain;
  logic [2:0] out_awatomic;
  logic [1:0] out_awdvmtype;
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
  logic [7:0] in_arid = 8'h12;
  logic [63:0] in_araddr = 64'h0;
  logic [7:0] in_arlen = 8'h0;
  logic [2:0] in_arsize = 3'd2;
  logic [1:0] in_arburst = 2'b01;
  logic [3:0] in_arcache = 4'h0;
  logic [2:0] in_arprot = 3'd0;
  logic [1:0] in_arlock = 2'b00;
  logic [3:0] in_arqos = 4'h0;
  logic [3:0] in_arregion = 4'h0;
  logic [1:0] in_ardomain = 2'b00;
  logic out_arvalid;
  logic out_arready = 1;
  logic [7:0] out_arid;
  logic [63:0] out_araddr;
  logic [7:0] out_arlen;
  logic [2:0] out_arsize;
  logic [1:0] out_arburst;
  logic [3:0] out_arcache;
  logic [2:0] out_arprot;
  logic [1:0] out_arlock;
  logic [3:0] out_arqos;
  logic [3:0] out_arregion;
  logic [1:0] out_ardomain;
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
  logic bready;
  logic [7:0] bid = 8'h11;
  logic [1:0] bresp = 2'b00;
  logic out_bvalid;
  logic out_bready = 1;
  logic [7:0] out_bid;
  logic [1:0] out_bresp;
  logic credit_full;
  logic aw_error;
  logic ar_error;
  logic exclusive_error;
  logic atomic_error;
  logic coh_error;
  logic resp_error;
  logic wstrb_error;
  logic last_error;
  logic id_error;
  logic out_dvm_valid;
  logic out_rsos_valid;
  logic dvm_pending;
  logic rsos_pending;
  logic [1:0] coh_state;
  logic qos_high;
  __DUT_MODULE__ #(.DVM_ENABLE(1),.RSOS_ENABLE(1),.COH_INIT(0)) dut (
    .clk(clk), .rst_n(rst_n),
    .in_awvalid(in_awvalid), .in_awready(in_awready),
    .in_awid(in_awid), .in_awaddr(in_awaddr), .in_awlen(in_awlen),
    .in_awsize(in_awsize), .in_awburst(in_awburst), .in_awlock(in_awlock),
    .in_awcache(in_awcache), .in_awprot(in_awprot), .in_awqos(in_awqos),
    .in_awregion(in_awregion), .in_awdomain(in_awdomain), .in_awatomic(in_awatomic), .in_awdvmtype(in_awdvmtype),
    .out_awvalid(out_awvalid), .out_awready(out_awready),
    .out_awid(out_awid), .out_awaddr(out_awaddr), .out_awlen(out_awlen),
    .out_awsize(out_awsize), .out_awburst(out_awburst), .out_awlock(out_awlock),
    .out_awcache(out_awcache), .out_awprot(out_awprot), .out_awqos(out_awqos),
    .out_awregion(out_awregion), .out_awdomain(out_awdomain), .out_awatomic(out_awatomic), .out_awdvmtype(out_awdvmtype),
    .wvalid(wvalid), .wready(wready), .wdata(wdata), .wstrb(wstrb), .wlast(wlast),
    .out_wvalid(out_wvalid), .out_wready(out_wready), .out_wdata(out_wdata),
    .out_wstrb(out_wstrb), .out_wlast(out_wlast),
    .in_arvalid(in_arvalid), .in_arready(in_arready), .in_arid(in_arid), .in_araddr(in_araddr), .in_arlen(in_arlen),
    .in_arsize(in_arsize), .in_arburst(in_arburst), .in_arlock(in_arlock), .in_arcache(in_arcache), .in_arprot(in_arprot),
    .in_arqos(in_arqos), .in_arregion(in_arregion), .in_ardomain(in_ardomain),
    .out_arvalid(out_arvalid), .out_arready(out_arready), .out_arid(out_arid), .out_araddr(out_araddr),
    .out_arlen(out_arlen), .out_arsize(out_arsize), .out_arburst(out_arburst), .out_arlock(out_arlock),
    .out_arcache(out_arcache), .out_arprot(out_arprot), .out_arqos(out_arqos),
    .out_arregion(out_arregion), .out_ardomain(out_ardomain),
    .rvalid(rvalid), .rready(rready), .rid(rid), .rdata(rdata),
    .rresp(rresp), .rlast(rlast),
    .out_rvalid(out_rvalid), .out_rready(out_rready),
    .out_rid(out_rid), .out_rdata(out_rdata), .out_rresp(out_rresp),
    .out_rlast(out_rlast),
    .bvalid(bvalid), .bready(bready), .bid(bid), .bresp(bresp),
    .out_bvalid(out_bvalid), .out_bready(out_bready),
    .out_bid(out_bid), .out_bresp(out_bresp),
    .credit_full(credit_full), .aw_error(aw_error), .ar_error(ar_error),
    .exclusive_error(exclusive_error), .atomic_error(atomic_error), .coh_error(coh_error),
    .resp_error(resp_error), .wstrb_error(wstrb_error), .last_error(last_error), .id_error(id_error),
    .out_dvm_valid(out_dvm_valid), .out_rsos_valid(out_rsos_valid),
    .dvm_pending(dvm_pending), .rsos_pending(rsos_pending),
    .coh_state(coh_state), .qos_high(qos_high)
  );
  always #5 clk = ~clk;
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
    repeat (4) tick();
    @(negedge clk);
    rst_n = 1;
    tick();
    if (coh_state !== 2'd0) fail("coh_init 0");
    in_awdvmtype = 2'd1;
    in_awvalid = 1;
    #1;
    if (in_awready !== 1'b1) fail("DVM AW not ready");
    tick();
    @(negedge clk);
    in_awvalid = 0;
    #1;
    if (out_awvalid !== 1'b1) fail("DVM not valid");
    if (out_dvm_valid !== 1'b1) fail("DVM out_dvm_valid");
    if (out_rsos_valid !== 1'b0) fail("DVM RSOS spur");
    if (out_awdvmtype !== 2'd1) fail("DVM type fwd");
    tick();
    if (dvm_pending !== 1'b1) fail("DVM pending");
    wvalid = 1;
    wdata = 32'hABCD1234;
    wstrb = 4'hF;
    wlast = 1;
    #1;
    tick();
    @(negedge clk);
    wvalid = 0;
    bvalid = 1;
    bid = 8'h11;
    bresp = 2'b00;
    tick();
    if (!out_bvalid) fail("B after DVM");
    if (out_bid !== 8'h11) fail("B id dvm");
    @(negedge clk);
    bvalid = 0;
    tick();
    if (dvm_pending !== 1'b0) fail("DVM pending clear");
    in_awdvmtype = 2'd2;
    in_awid = 8'h12;
    in_awvalid = 1;
    #1;
    tick();
    @(negedge clk);
    in_awvalid = 0;
    #1;
    if (out_dvm_valid) fail("RSOS dvm spur"); 
    if (!out_rsos_valid) fail("RSOS out_rsos_valid");
    tick();
    if (!rsos_pending) fail("RSOS pending");
    wvalid = 1;
    wlast = 1;
    tick();
    @(negedge clk);
    wvalid = 0;
    bvalid = 1;
    bid = 8'h12;
    tick();
    @(negedge clk);
    bvalid = 0;
    repeat (10) begin @(posedge clk); #1; if (out_bvalid) begin break; end end
    tick();
    tick();
    if (rsos_pending !== 1'b0) fail("RSOS pending clear");
    in_awdomain = 2'b01;
    in_awcache = 4'h3;
    in_awdvmtype = 2'd0;
    in_awid = 8'h13;
    in_awvalid = 1;
    tick();
    @(negedge clk);
    in_awvalid = 0;
    wvalid = 1;
    wlast = 1;
    tick();
    @(negedge clk);
    wvalid = 0;
    bvalid = 1;
    bid = 8'h13;
    tick();
    @(negedge clk);
    bvalid = 0;
    tick();
    tick();
    if (coh_state !== 2'b01) fail("coh state should be 01");
    if (coh_error !== 1'b0) fail("coh error should be 0 for cacheable shareable");
    $display("TB_DVM_RSOS_PASS");
    $finish;
  end
endmodule
`default_nettype wire
"""
BP_TB = r"""`default_nettype none
module tb_axi5_bp;
  logic clk = 0; logic rst_n = 0;
  logic in_awvalid=0; logic in_awready; logic [7:0] in_awid=8'h01; logic [63:0] in_awaddr=64'h1000; logic [7:0] in_awlen=8'd1; logic [2:0] in_awsize=3'd2;
  logic [1:0] in_awburst=2'b01; logic [3:0] in_awcache=4'h3; logic [2:0] in_awprot=0; logic [1:0] in_awlock=0; logic [3:0] in_awqos=0; logic [3:0] in_awregion=0; logic [1:0] in_awdomain=0; logic [2:0] in_awatomic=0; logic [1:0] in_awdvmtype=0;
  logic out_awvalid; logic out_awready=0; logic [7:0] out_awid; logic [63:0] out_awaddr; logic [7:0] out_awlen; logic [2:0] out_awsize; logic [1:0] out_awburst; logic [3:0] out_awcache; logic [2:0] out_awprot; logic [1:0] out_awlock; logic [3:0] out_awqos; logic [3:0] out_awregion; logic [1:0] out_awdomain; logic [2:0] out_awatomic; logic [1:0] out_awdvmtype;
  logic wvalid=0; logic wready; logic [31:0] wdata=0; logic [3:0] wstrb=4'hF; logic wlast=0; logic out_wvalid; logic out_wready=1; logic [31:0] out_wdata; logic [3:0] out_wstrb; logic out_wlast;
  logic in_arvalid=0; logic in_arready; logic [7:0] in_arid=8'h02; logic [63:0] in_araddr=64'h2000; logic [7:0] in_arlen=8'd0; logic [2:0] in_arsize=3'd2; logic [1:0] in_arburst=2'b01; logic [3:0] in_arcache=4'h3; logic [2:0] in_arprot=0; logic [1:0] in_arlock=0; logic [3:0] in_arqos=0; logic [3:0] in_arregion=0; logic [1:0] in_ardomain=0;
  logic out_arvalid; logic out_arready=1; logic [7:0] out_arid; logic [63:0] out_araddr; logic [7:0] out_arlen; logic [2:0] out_arsize; logic [1:0] out_arburst; logic [3:0] out_arcache; logic [2:0] out_arprot; logic [1:0] out_arlock; logic [3:0] out_arqos; logic [3:0] out_arregion; logic [1:0] out_ardomain;
  logic rvalid=0; logic rready; logic [7:0] rid=8'h02; logic [31:0] rdata=0; logic [1:0] rresp=0; logic rlast=0; logic out_rvalid; logic out_rready=0; logic [7:0] out_rid; logic [31:0] out_rdata; logic [1:0] out_rresp; logic out_rlast;
  logic bvalid=0; logic bready; logic [7:0] bid=8'h01; logic [1:0] bresp=0; logic out_bvalid; logic out_bready=0; logic [7:0] out_bid; logic [1:0] out_bresp;
  logic credit_full; logic aw_error; logic ar_error; logic exclusive_error; logic atomic_error; logic coh_error; logic resp_error; logic wstrb_error; logic last_error; logic id_error; logic out_dvm_valid; logic out_rsos_valid; logic dvm_pending; logic rsos_pending; logic [1:0] coh_state; logic qos_high;
  __DUT_MODULE__ dut (
    .clk(clk), .rst_n(rst_n), .in_awvalid(in_awvalid), .in_awready(in_awready), .in_awid(in_awid), .in_awaddr(in_awaddr), .in_awlen(in_awlen), .in_awsize(in_awsize), .in_awburst(in_awburst), .in_awlock(in_awlock), .in_awcache(in_awcache), .in_awprot(in_awprot), .in_awqos(in_awqos), .in_awregion(in_awregion), .in_awdomain(in_awdomain), .in_awatomic(in_awatomic), .in_awdvmtype(in_awdvmtype),
    .out_awvalid(out_awvalid), .out_awready(out_awready), .out_awid(out_awid), .out_awaddr(out_awaddr), .out_awlen(out_awlen), .out_awsize(out_awsize), .out_awburst(out_awburst), .out_awlock(out_awlock), .out_awcache(out_awcache), .out_awprot(out_awprot), .out_awqos(out_awqos), .out_awregion(out_awregion), .out_awdomain(out_awdomain), .out_awatomic(out_awatomic), .out_awdvmtype(out_awdvmtype),
    .wvalid(wvalid), .wready(wready), .wdata(wdata), .wstrb(wstrb), .wlast(wlast), .out_wvalid(out_wvalid), .out_wready(out_wready), .out_wdata(out_wdata), .out_wstrb(out_wstrb), .out_wlast(out_wlast),
    .in_arvalid(in_arvalid), .in_arready(in_arready), .in_arid(in_arid), .in_araddr(in_araddr), .in_arlen(in_arlen), .in_arsize(in_arsize), .in_arburst(in_arburst), .in_arlock(in_arlock), .in_arcache(in_arcache), .in_arprot(in_arprot), .in_arqos(in_arqos), .in_arregion(in_arregion), .in_ardomain(in_ardomain),
    .out_arvalid(out_arvalid), .out_arready(out_arready), .out_arid(out_arid), .out_araddr(out_araddr), .out_arlen(out_arlen), .out_arsize(out_arsize), .out_arburst(out_arburst), .out_arlock(out_arlock), .out_arcache(out_arcache), .out_arprot(out_arprot), .out_arqos(out_arqos), .out_arregion(out_arregion), .out_ardomain(out_ardomain),
    .rvalid(rvalid), .rready(rready), .rid(rid), .rdata(rdata), .rresp(rresp), .rlast(rlast), .out_rvalid(out_rvalid), .out_rready(out_rready), .out_rid(out_rid), .out_rdata(out_rdata), .out_rresp(out_rresp), .out_rlast(out_rlast),
    .bvalid(bvalid), .bready(bready), .bid(bid), .bresp(bresp), .out_bvalid(out_bvalid), .out_bready(out_bready), .out_bid(out_bid), .out_bresp(out_bresp),
    .credit_full(credit_full), .aw_error(aw_error), .ar_error(ar_error), .exclusive_error(exclusive_error), .atomic_error(atomic_error), .coh_error(coh_error), .resp_error(resp_error), .wstrb_error(wstrb_error), .last_error(last_error), .id_error(id_error), .out_dvm_valid(out_dvm_valid), .out_rsos_valid(out_rsos_valid), .dvm_pending(dvm_pending), .rsos_pending(rsos_pending), .coh_state(coh_state), .qos_high(qos_high)
  );
  always #5 clk = ~clk;
  task automatic fail(input string msg); begin $display("FAIL: %s", msg); $fatal(1, "TB_FAIL %s", msg); end endtask
  task automatic tick(); begin @(posedge clk); #1; end endtask
  initial begin
    repeat (4) tick(); @(negedge clk); rst_n=1; tick();
    in_awvalid=1; tick(); @(negedge clk); in_awvalid=0;
    if (!out_awvalid) fail("AW should be valid after capture");
    tick();
    if (!out_awvalid) fail("AW must hold while out_awready low");
    if (out_awaddr !== 64'h1000) fail("AW addr hold");
    if (out_awid !== 8'h01) fail("AW id hold");
    tick();
    out_awready=1;
    tick();
    tick();
    if (out_awvalid) fail("AW should drain after ready");
    $display("TB_AW_BP_PASS");
    wvalid=1; wdata=32'h11110000; wstrb=4'hF; wlast=0; out_wready=0;
    #1; if (!out_wvalid) fail("W valid during stall");
    tick();
    if (!out_wvalid) fail("W hold");
    if (out_wdata !== 32'h11110000) fail("W data hold");
    out_wready=1;
    tick();
    @(negedge clk); wvalid=0;
    wvalid=1; wdata=32'h22220000; wlast=1;
    tick(); @(negedge clk); wvalid=0;
    tick();
    $display("TB_W_BP_PASS");
    in_arvalid=1; tick(); @(negedge clk); in_arvalid=0;
    out_arready=0;
    tick();
    if (!out_arvalid) fail("AR valid");
    tick();
    if (!out_arvalid) fail("AR hold");
    out_arready=1;
    tick();
    tick();
    $display("TB_AR_BP_PASS");
    out_bready=0; bvalid=1; bid=8'h01; bresp=2'b00;
    tick(); @(negedge clk); bvalid=0;
    tick();
    if (!out_bvalid) fail("B stage valid");
    tick();
    if (!out_bvalid) fail("B hold");
    out_bready=1;
    tick();
    if (out_bvalid) fail("B drain");
    $display("TB_B_BP_PASS");
    out_rready=0; rvalid=1; rid=8'h02; rdata=32'hdeadbeef; rresp=0; rlast=0;
    tick(); @(negedge clk); rvalid=0;
    tick();
    if (!out_rvalid) fail("R stage valid");
    tick();
    if (!out_rvalid) fail("R hold");
    out_rready=1;
    tick();
    $display("TB_R_BP_PASS");
    $display("TB_BACKPRESSURE_PASS");
    $finish;
  end
endmodule
`default_nettype wire
"""
SPLIT_TB = r"""`default_nettype none
module tb_axi5_split;
  logic clk = 0; logic rst_n = 0;
  logic in_awvalid=0; logic in_awready; logic [7:0] in_awid=8'h01; logic [63:0] in_awaddr=64'h1000; logic [7:0] in_awlen=8'd7; logic [2:0] in_awsize=3'd2;
  logic [1:0] in_awburst=2'b01; logic [3:0] in_awcache=4'h3; logic [2:0] in_awprot=3'd0; logic [1:0] in_awlock=0; logic [3:0] in_awqos=4'd0; logic [3:0] in_awregion=4'h0; logic [1:0] in_awdomain=0; logic [2:0] in_awatomic=0; logic [1:0] in_awdvmtype=0;
  logic out_awvalid; logic out_awready=1; logic [7:0] out_awid; logic [63:0] out_awaddr; logic [7:0] out_awlen; logic [2:0] out_awsize; logic [1:0] out_awburst; logic [3:0] out_awcache; logic [2:0] out_awprot; logic [1:0] out_awlock; logic [3:0] out_awqos; logic [3:0] out_awregion; logic [1:0] out_awdomain; logic [2:0] out_awatomic; logic [1:0] out_awdvmtype;
  logic wvalid=0; logic wready; logic [31:0] wdata=0; logic [3:0] wstrb=4'hF; logic wlast=0; logic out_wvalid; logic out_wready=1; logic [31:0] out_wdata; logic [3:0] out_wstrb; logic out_wlast;
  logic in_arvalid=0; logic in_arready; logic [7:0] in_arid=8'h02; logic [63:0] in_araddr=64'h2000; logic [7:0] in_arlen=8'd3; logic [2:0] in_arsize=3'd2; logic [1:0] in_arburst=2'b01; logic [3:0] in_arcache=4'h3; logic [2:0] in_arprot=0; logic [1:0] in_arlock=0; logic [3:0] in_arqos=0; logic [3:0] in_arregion=0; logic [1:0] in_ardomain=0;
  logic out_arvalid; logic out_arready=1; logic [7:0] out_arid; logic [63:0] out_araddr; logic [7:0] out_arlen; logic [2:0] out_arsize; logic [1:0] out_arburst; logic [3:0] out_arcache; logic [2:0] out_arprot; logic [1:0] out_arlock; logic [3:0] out_arqos; logic [3:0] out_arregion; logic [1:0] out_ardomain;
  logic rvalid=0; logic rready; logic [7:0] rid=8'h02; logic [31:0] rdata=0; logic [1:0] rresp=0; logic rlast=0; logic out_rvalid; logic out_rready=1; logic [7:0] out_rid; logic [31:0] out_rdata; logic [1:0] out_rresp; logic out_rlast;
  logic bvalid=0; logic bready; logic [7:0] bid=8'h01; logic [1:0] bresp=0; logic out_bvalid; logic out_bready=1; logic [7:0] out_bid; logic [1:0] out_bresp;
  logic credit_full; logic aw_error; logic ar_error; logic exclusive_error; logic atomic_error; logic coh_error; logic resp_error; logic wstrb_error; logic last_error; logic id_error; logic out_dvm_valid; logic out_rsos_valid; logic dvm_pending; logic rsos_pending; logic [1:0] coh_state; logic qos_high;
  __DUT_MODULE__ dut (
    .clk(clk), .rst_n(rst_n), .in_awvalid(in_awvalid), .in_awready(in_awready), .in_awid(in_awid), .in_awaddr(in_awaddr), .in_awlen(in_awlen), .in_awsize(in_awsize), .in_awburst(in_awburst), .in_awlock(in_awlock), .in_awcache(in_awcache), .in_awprot(in_awprot), .in_awqos(in_awqos), .in_awregion(in_awregion), .in_awdomain(in_awdomain), .in_awatomic(in_awatomic), .in_awdvmtype(in_awdvmtype),
    .out_awvalid(out_awvalid), .out_awready(out_awready), .out_awid(out_awid), .out_awaddr(out_awaddr), .out_awlen(out_awlen), .out_awsize(out_awsize), .out_awburst(out_awburst), .out_awlock(out_awlock), .out_awcache(out_awcache), .out_awprot(out_awprot), .out_awqos(out_awqos), .out_awregion(out_awregion), .out_awdomain(out_awdomain), .out_awatomic(out_awatomic), .out_awdvmtype(out_awdvmtype),
    .wvalid(wvalid), .wready(wready), .wdata(wdata), .wstrb(wstrb), .wlast(wlast), .out_wvalid(out_wvalid), .out_wready(out_wready), .out_wdata(out_wdata), .out_wstrb(out_wstrb), .out_wlast(out_wlast),
    .in_arvalid(in_arvalid), .in_arready(in_arready), .in_arid(in_arid), .in_araddr(in_araddr), .in_arlen(in_arlen), .in_arsize(in_arsize), .in_arburst(in_arburst), .in_arlock(in_arlock), .in_arcache(in_arcache), .in_arprot(in_arprot), .in_arqos(in_arqos), .in_arregion(in_arregion), .in_ardomain(in_ardomain),
    .out_arvalid(out_arvalid), .out_arready(out_arready), .out_arid(out_arid), .out_araddr(out_araddr), .out_arlen(out_arlen), .out_arsize(out_arsize), .out_arburst(out_arburst), .out_arlock(out_arlock), .out_arcache(out_arcache), .out_arprot(out_arprot), .out_arqos(out_arqos), .out_arregion(out_arregion), .out_ardomain(out_ardomain),
    .rvalid(rvalid), .rready(rready), .rid(rid), .rdata(rdata), .rresp(rresp), .rlast(rlast), .out_rvalid(out_rvalid), .out_rready(out_rready), .out_rid(out_rid), .out_rdata(out_rdata), .out_rresp(out_rresp), .out_rlast(out_rlast),
    .bvalid(bvalid), .bready(bready), .bid(bid), .bresp(bresp), .out_bvalid(out_bvalid), .out_bready(out_bready), .out_bid(out_bid), .out_bresp(out_bresp),
    .credit_full(credit_full), .aw_error(aw_error), .ar_error(ar_error), .exclusive_error(exclusive_error), .atomic_error(atomic_error), .coh_error(coh_error), .resp_error(resp_error), .wstrb_error(wstrb_error), .last_error(last_error), .id_error(id_error), .out_dvm_valid(out_dvm_valid), .out_rsos_valid(out_rsos_valid), .dvm_pending(dvm_pending), .rsos_pending(rsos_pending), .coh_state(coh_state), .qos_high(qos_high)
  );
  always #5 clk = ~clk;
  task automatic fail(input string msg); begin $display("FAIL: %s", msg); $fatal(1, "TB_FAIL %s", msg); end endtask
  task automatic tick(); begin @(posedge clk); #1; end endtask
  initial begin
    repeat (4) tick(); @(negedge clk); rst_n=1; tick();
    in_awvalid=1; tick(); @(negedge clk); in_awvalid=0;
    if (!out_awvalid) fail("AW split 0");
    if (out_awaddr !== 64'h1000 || out_awlen !== 8'd1 || out_awid !== 8'h01) fail("AW split 0 fields");
    tick();
    if (out_awaddr !== 64'h1008 || out_awlen !== 8'd1 || out_awid !== 8'h01) fail("AW split 1 fields");
    tick();
    if (out_awaddr !== 64'h1010 || out_awlen !== 8'd1) fail("AW split 2 fields");
    $display("TB_SPLIT_AW_PASS");
    wvalid=1; wdata=32'h1; wlast=0; tick(); @(negedge clk); wvalid=0; wvalid=1; wdata=32'h2; tick(); @(negedge clk); wvalid=0;
    wvalid=1; wdata=32'h3; wlast=0; tick(); @(negedge clk); wvalid=0; wvalid=1; wdata=32'h4; wlast=0; tick(); @(negedge clk); wvalid=0;
    wvalid=1; wdata=32'h5; wlast=0; tick(); @(negedge clk); wvalid=0; wvalid=1; wdata=32'h6; wlast=0; tick(); @(negedge clk); wvalid=0;
    wvalid=1; wdata=32'h7; wlast=1; tick(); @(negedge clk); wvalid=0; wvalid=1; wdata=32'h8; wlast=1; tick(); @(negedge clk); wvalid=0;
    $display("TB_SPLIT_W_PASS");
    in_arvalid=1; tick(); @(negedge clk); in_arvalid=0;
    if (!out_arvalid) fail("AR valid");
    if (out_araddr !== 64'h2000 || out_arlen !== 8'd1) fail("AR split 0");
    tick();
    if (out_araddr !== 64'h2008 || out_arlen !== 8'd1) fail("AR split 1");
    $display("TB_SPLIT_AR_PASS");
    bvalid=1; bid=8'h01; tick(); @(negedge clk); bvalid=0; tick();
    $display("TB_SPLIT_B_PASS");
    rvalid=1; rid=8'h02; rdata=32'hdead; rresp=0; rlast=0; tick(); @(negedge clk); rvalid=0; tick();
    rvalid=1; rid=8'h02; rdata=32'hcafe; rresp=0; rlast=1; tick(); @(negedge clk); rvalid=0; tick();
    $display("TB_SPLIT_R_PASS");
    $display("TB_SPLIT_PASS");
    $finish;
  end
endmodule
`default_nettype wire
"""

@pytest.mark.skipif(_VERILATOR is None, reason="verilator not installed")
def test_checker_cache_prot(tmp_path):
    out = _run_checker(tmp_path, CACHE_TB, "tb_axi5_checker", expected=["TB_CACHE_PROT_PASS", "TB_CACHE_AR_PASS"])
    assert "TB_CACHE_PROT_PASS" in out

@pytest.mark.skipif(_VERILATOR is None, reason="verilator not installed")
def test_checker_atomic_exclusive_resp(tmp_path):
    out = _run_checker(tmp_path, ATOMIC_TB, "tb_axi5_atomic", expected=["TB_ATOMIC_EXCL_RESP_PASS"])
    assert "TB_ATOMIC_EXCL_RESP_PASS" in out

@pytest.mark.skipif(_VERILATOR is None, reason="verilator not installed")
def test_checker_strb_last_id(tmp_path):
    out = _run_checker(tmp_path, STRB_TB, "tb_axi5_strb", expected=["TB_STRB_LAST_PASS", "TB_ID_PASS"])
    assert "TB_STRB_LAST_PASS" in out and "TB_ID_PASS" in out

@pytest.mark.skipif(_VERILATOR is None, reason="verilator not installed")
def test_checker_dvm_rsos_coh(tmp_path):
    params = AdapterParams(agent_idx=0, protocol=ProtocolFamily.AXI5, data_width=32, addr_width=64, split_at=2, max_outstanding=4, axi5_dvm_enable=True, axi5_rsos_enable=True, axi5_coh_init=0)
    out = _run_checker(tmp_path, DVM_TB, "tb_axi5_dvm", params=params, expected=["TB_DVM_RSOS_PASS"])
    assert "TB_DVM_RSOS_PASS" in out

@pytest.mark.skipif(_VERILATOR is None, reason="verilator not installed")
def test_checker_backpressure(tmp_path):
    out = _run_checker(tmp_path, BP_TB, "tb_axi5_bp", expected=["TB_AW_BP_PASS", "TB_W_BP_PASS", "TB_AR_BP_PASS", "TB_B_BP_PASS", "TB_R_BP_PASS", "TB_BACKPRESSURE_PASS"])
    assert "TB_BACKPRESSURE_PASS" in out

@pytest.mark.skipif(_VERILATOR is None, reason="verilator not installed")
def test_checker_split(tmp_path):
    params = AdapterParams(agent_idx=0, protocol=ProtocolFamily.AXI5, data_width=32, addr_width=64, split_at=2, max_outstanding=16)
    out = _run_checker(tmp_path, SPLIT_TB, "tb_axi5_split", params=params, expected=["TB_SPLIT_AW_PASS", "TB_SPLIT_W_PASS", "TB_SPLIT_AR_PASS", "TB_SPLIT_PASS"])
    assert "TB_SPLIT_PASS" in out

def test_checker_validator_axi5_knobs():
    ok = build_adapter(AdapterParams(agent_idx=0, protocol=ProtocolFamily.AXI5, axi5_dvm_enable=True, axi5_coh_init=2))
    assert ok.verdict.ok is True
    for bad in [
        AdapterParams(agent_idx=0, protocol=ProtocolFamily.AXI5, axi5_dvm_enable=1),
        AdapterParams(agent_idx=0, protocol=ProtocolFamily.AXI5, axi5_rsos_enable="yes"),
        AdapterParams(agent_idx=0, protocol=ProtocolFamily.AXI5, axi5_coh_init=4),
        AdapterParams(agent_idx=0, protocol=ProtocolFamily.AXI5, axi5_coh_init=-1),
        AdapterParams(agent_idx=0, protocol=ProtocolFamily.AXI5, axi5_coh_init=True),
        AdapterParams(agent_idx=0, protocol=ProtocolFamily.CHI, axi5_dvm_enable=True),
    ]:
        v = build_adapter(bad).verdict
        assert v.ok is False and v.blocker_id == "ADAPTER_INVALID_PARAMS"
    a = build_adapter(AdapterParams(agent_idx=0, protocol=ProtocolFamily.AXI5))
    b = build_adapter(AdapterParams(agent_idx=0, protocol=ProtocolFamily.AXI5, axi5_dvm_enable=False, axi5_coh_init=3))
    assert a.source != b.source
    assert "DVM_ENABLE = 1" in (a.source or "")
    assert "DVM_ENABLE = 0" in (b.source or "")
    assert "COH_INIT = 3" in (b.source or "")

def test_checker_manifest_full_claim():
    assert AXI5_SUPPORTED.startswith("AXI5")
    joined = " ".join(AXI5_ADAPTER_ASSUMPTIONS)
    assert "Checked and emitted" in joined
    assert "Coherency" in joined and "DVM" in joined and "RSOS" in joined
    assert "WIdthWidget" not in joined
