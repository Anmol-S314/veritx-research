from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

from veritx_dse.model.agent_intent_v4 import ProtocolFamily
from veritx_dse.product.adapter_factory_rtl import (
    AdapterParams,
    build_adapter,
    tilelink_directed_tb_source,
)

_VERILATOR = shutil.which("verilator")
_IVERILOG = shutil.which("iverilog")
_VVP = shutil.which("vvp")

_AXI_TB = r"""`default_nettype none
module tb_axi;
  localparam int DATA_W_IN = __INW__;
  localparam int DATA_W_OUT = __OUTW__;
  logic clk = 0;
  logic rst_n = 0;
  logic [63:0] in_awaddr = 64'h0;
  logic [7:0] in_awlen = 8'd0;
  logic [2:0] in_awsize = 3'd2;
  logic [1:0] in_awburst = 2'b01;
  logic [3:0] in_awcache = 4'b0011;
  logic [2:0] in_awprot = 3'd0;
  logic [1:0] in_awlock = 2'b00;
  logic [3:0] in_awqos = 4'd5;
  logic [3:0] in_awregion = 4'd0;
  logic [1:0] in_awdomain = 2'b00;
  logic [2:0] in_awatomic = 3'd0;
  logic [1:0] in_awdvmtype = 2'd0;
  logic [7:0] in_awid = 8'd0;
  logic in_awvalid = 0;
  logic in_awready;
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
  logic [7:0] out_awid;
  logic out_awvalid;
  logic out_awready = 0;
  logic [7:0] in_arlen = 8'd0;
  logic [2:0] in_arsize = 3'd2;
  logic [1:0] in_arburst = 2'b01;
  logic [3:0] in_arcache = 4'b0011;
  logic [2:0] in_arprot = 3'd0;
  logic [1:0] in_arlock = 2'b00;
  logic [3:0] in_arqos = 4'd0;
  logic [3:0] in_arregion = 4'd0;
  logic [1:0] in_ardomain = 2'b00;
  logic [63:0] in_araddr = 64'h0;
  logic [7:0] in_arid = 8'd0;
  logic in_arvalid = 0;
  logic in_arready;
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
  logic [7:0] out_arid;
  logic out_arvalid;
  logic out_arready = 0;
  logic [DATA_W_IN-1:0] wdata = '0;
  logic [DATA_W_IN/8-1:0] wstrb = '0;
  logic wlast = 0;
  logic wvalid = 0;
  logic wready;
  logic [DATA_W_OUT-1:0] out_wdata;
  logic [DATA_W_OUT/8-1:0] out_wstrb;
  logic out_wlast;
  logic out_wvalid;
  logic out_wready = 0;
  logic bvalid = 0;
  logic [1:0] bresp = 2'b00;
  logic [7:0] bid = 8'd0;
  logic bready;
  logic out_bvalid;
  logic [1:0] out_bresp;
  logic [7:0] out_bid;
  logic out_bready = 0;
  logic [DATA_W_OUT-1:0] rdata = '0;
  localparam int WOUT = __WOUT__;
  localparam int WPER = __WPER__;
  localparam int WEXP = __WBEATS__;
  logic [7:0] rid = 8'd0;
  logic [1:0] rresp = 2'b00;
  logic rlast = 0;
  logic rvalid = 0;
  logic rready;
  logic [DATA_W_OUT-1:0] out_rdata;
  logic [7:0] out_rid;
  logic [1:0] out_rresp;
  logic out_rlast;
  logic out_rvalid;
  logic out_rready = 0;
  logic credit_full;
  logic aw_error;
  logic ar_error;
  logic exclusive_error;
  __DUT_MODULE__ dut (
    .clk(clk), .rst_n(rst_n),
    .in_awaddr(in_awaddr), .in_awlen(in_awlen), .in_awsize(in_awsize),
    .in_awburst(in_awburst), .in_awcache(in_awcache), .in_awprot(in_awprot),
    .in_awlock(in_awlock), .in_awqos(in_awqos), .in_awregion(in_awregion),
    .in_awdomain(in_awdomain), .in_awatomic(in_awatomic), .in_awdvmtype(in_awdvmtype),
    .in_awid(in_awid), .in_awvalid(in_awvalid), .in_awready(in_awready),
    .out_awaddr(out_awaddr), .out_awlen(out_awlen), .out_awsize(out_awsize),
    .out_awburst(out_awburst), .out_awcache(out_awcache), .out_awprot(out_awprot),
    .out_awlock(out_awlock), .out_awqos(out_awqos), .out_awregion(out_awregion),
    .out_awdomain(out_awdomain), .out_awatomic(out_awatomic), .out_awdvmtype(out_awdvmtype),
    .out_awid(out_awid), .out_awvalid(out_awvalid), .out_awready(out_awready),
    .in_araddr(in_araddr), .in_arlen(in_arlen), .in_arsize(in_arsize),
    .in_arburst(in_arburst), .in_arcache(in_arcache), .in_arprot(in_arprot),
    .in_arlock(in_arlock), .in_arqos(in_arqos), .in_arregion(in_arregion),
    .in_ardomain(in_ardomain),
    .in_arid(in_arid), .in_arvalid(in_arvalid), .in_arready(in_arready),
    .out_araddr(out_araddr), .out_arlen(out_arlen), .out_arsize(out_arsize),
    .out_arburst(out_arburst), .out_arcache(out_arcache), .out_arprot(out_arprot),
    .out_arlock(out_arlock), .out_arqos(out_arqos), .out_arregion(out_arregion),
    .out_ardomain(out_ardomain),
    .out_arid(out_arid), .out_arvalid(out_arvalid), .out_arready(out_arready),
    .wdata(wdata), .wstrb(wstrb), .wlast(wlast), .wvalid(wvalid), .wready(wready),
    .out_wdata(out_wdata), .out_wstrb(out_wstrb), .out_wlast(out_wlast),
    .out_wvalid(out_wvalid), .out_wready(out_wready),
    .bvalid(bvalid), .bresp(bresp), .bid(bid), .bready(bready),
    .out_bvalid(out_bvalid), .out_bresp(out_bresp), .out_bid(out_bid), .out_bready(out_bready),
    .rdata(rdata), .rid(rid), .rresp(rresp), .rlast(rlast), .rvalid(rvalid), .rready(rready),
    .out_rdata(out_rdata), .out_rid(out_rid), .out_rresp(out_rresp),
    .out_rlast(out_rlast), .out_rvalid(out_rvalid), .out_rready(out_rready),
    .credit_full(credit_full), .aw_error(aw_error), .ar_error(ar_error), .exclusive_error(exclusive_error)
  );
  always #5 clk = ~clk;
  int n_aw = 0;
  int n_w = 0;
  int n_b = 0;
  int n_ar = 0;
  int n_r = 0;
  always @(posedge clk) begin
    if (rst_n && out_awvalid && out_awready) n_aw = n_aw + 1;
    if (rst_n && out_wvalid && out_wready) n_w = n_w + 1;
    if (rst_n && out_bvalid && out_bready) n_b = n_b + 1;
    if (rst_n && out_arvalid && out_arready) n_ar = n_ar + 1;
    if (rst_n && out_rvalid && out_rready) n_r = n_r + 1;
  end
  int wj = 0;
  always @(negedge clk) begin
    #2;
    if (rst_n && out_wvalid && out_wready) begin
      wj = wj + 1;
      if (out_wlast !== (((wj % WPER) == 0) || (wj == WOUT)))
        $fatal(1, "wlast beat %0d got=%b", wj, out_wlast);
      ratio = (DATA_W_IN > DATA_W_OUT) ? (DATA_W_IN / DATA_W_OUT) : 1;
      in_k = (wj - 1) / ratio;
      lane = (wj - 1) % ratio;
      exp_data = DATA_W_OUT'((64'h100 + in_k + 1) >> (lane * DATA_W_OUT));
      if (out_wdata !== exp_data)
        $fatal(1, "wdata beat %0d got=%h exp=%h", wj, out_wdata, exp_data);
    end
  end
  int in_k;
  int lane;
  int ratio;
  logic [DATA_W_OUT-1:0] exp_data;
  task automatic send_aw(input logic [63:0] addr, input logic [7:0] len, input logic [2:0] size, input logic [7:0] id);
    begin
      @(negedge clk);
      in_awaddr = addr;
      in_awlen = len;
      in_awsize = size;
      in_awid = id;
      in_awvalid = 1'b1;
      #1;
      if (!in_awready) $fatal(1, "aw not ready");
      @(posedge clk);
      @(negedge clk);
      in_awvalid = 1'b0;
    end
  endtask
  task automatic wbeat(input logic [63:0] data, input logic [7:0] str, input logic last);
    int tries;
    begin
      @(negedge clk);
      wdata = DATA_W_IN'(data);
      wstrb = (DATA_W_IN/8)'(str);
      wlast = last;
      wvalid = 1'b1;
      tries = 0;
      #1;
      while (!wready) begin
        @(negedge clk);
        #1;
        tries = tries + 1;
        if (tries > 8) $fatal(1, "w not ready");
      end
      @(posedge clk);
      @(negedge clk);
      wvalid = 1'b0;
    end
  endtask
  initial begin
    int i;
    int w_expect;
    repeat (4) @(posedge clk);
    @(negedge clk);
    rst_n = 1;
    out_awready = 1;
    out_wready = 1;
    out_arready = 1;
    out_rready = 1;
    out_bready = 1;
    send_aw(64'h1000, 8'd7, 3'd2, 8'd7);
    #1;
    if (!out_awvalid) $fatal(1, "aw1 not valid");
    if (out_awaddr !== 64'h1000) $fatal(1, "aw1 addr %h", out_awaddr);
    if (out_awlen !== __AWL1__) $fatal(1, "aw1 len %0d", out_awlen);
    if (out_awsize !== __AWS1__) $fatal(1, "aw1 size %0d", out_awsize);
    if (out_awid !== 8'd7) $fatal(1, "aw1 id %0d", out_awid);
    if (out_awcache !== 4'b0011) $fatal(1, "aw cache %h", out_awcache);
    if (out_awqos !== 4'd5) $fatal(1, "aw qos %0d", out_awqos);
    @(posedge clk);
    #1;
    if (out_awaddr !== 64'h100c) $fatal(1, "aw2 addr %h", out_awaddr);
    if (out_awlen !== __AWL2__) $fatal(1, "aw2 len %0d", out_awlen);
    if (out_awid !== 8'd7) $fatal(1, "aw2 id %0d", out_awid);
    @(posedge clk);
    #1;
    if (out_awaddr !== 64'h1018) $fatal(1, "aw3 addr %h", out_awaddr);
    if (out_awlen !== __AWL3__) $fatal(1, "aw3 len %0d", out_awlen);
    if (out_awid !== 8'd7) $fatal(1, "aw3 id %0d", out_awid);
    @(posedge clk);
    #1;
    @(negedge clk);
    w_expect = __WBEATS__;
    for (i = 1; i <= w_expect; i = i + 1) begin
      wbeat(64'h100 + i, 8'hff, (i == w_expect));
    end
    @(negedge clk);
    wvalid = 1'b0;
    while (n_w < WOUT) @(posedge clk);
    #1;
    if (n_w != WOUT) $fatal(1, "w out count %0d exp %0d", n_w, WOUT);
    @(negedge clk);
    out_bready = 1'b0;
    @(negedge clk);
    bvalid = 1'b1;
    bresp = 2'b10;
    bid = 8'd7;
    #1;
    @(posedge clk);
    #1;
    @(negedge clk);
    bvalid = 1'b0;
    @(negedge clk);
    if (!out_bvalid) $fatal(1, "b hold not valid");
    if (out_bid !== 8'd7) $fatal(1, "b id %0d", out_bid);
    if (out_bresp !== 2'b10) $fatal(1, "b resp %b", out_bresp);
    out_bready = 1'b1;
    @(posedge clk);
    #1;
    @(negedge clk);
    out_bready = 1'b0;
    @(negedge clk);
    bvalid = 1'b1;
    bid = 8'd7;
    @(posedge clk);
    #1;
    @(negedge clk);
    bvalid = 1'b0;
    @(negedge clk);
    if (out_bid !== 8'd7) $fatal(1, "b id2 %0d", out_bid);
    out_bready = 1'b1;
    @(posedge clk);
    #1;
    @(negedge clk);
    out_bready = 1'b0;
    @(negedge clk);
    bvalid = 1'b1;
    bid = 8'd7;
    @(posedge clk);
    #1;
    @(negedge clk);
    bvalid = 1'b0;
    @(negedge clk);
    if (out_bid !== 8'd7) $fatal(1, "b id3 %0d", out_bid);
    out_bready = 1'b1;
    @(posedge clk);
    #1;
    @(negedge clk);
    out_bready = 1'b0;
    @(negedge clk);
    in_araddr = 64'h2000;
    in_arlen = 8'd3;
    in_arsize = 3'd2;
    in_arid = 8'd5;
    in_arvalid = 1'b1;
    @(posedge clk);
    #1;
    @(negedge clk);
    in_arvalid = 1'b0;
    if (!out_arvalid) $fatal(1, "ar not valid");
    if (out_araddr !== 64'h2000 || out_arid !== 8'd5)
      $fatal(1, "ar fields addr=%h id=%0d", out_araddr, out_arid);
    if (DATA_W_IN > DATA_W_OUT) begin
      if (out_arlen !== 8'd5 || out_arsize !== 3'd1) $fatal(1, "ar down len/size addr=%h len=%0d size=%0d", out_araddr, out_arlen, out_arsize);
    end else begin
      if (out_arlen !== 8'd2 || out_arsize !== 3'd2) $fatal(1, "ar len/size addr=%h len=%0d size=%0d", out_araddr, out_arlen, out_arsize);
    end
    @(posedge clk);
    #1;
    if (out_araddr !== 64'h200c || out_arid !== 8'd5)
      $fatal(1, "ar2 fields addr=%h id=%0d", out_araddr, out_arid);
    if (DATA_W_IN < DATA_W_OUT) begin
      if (out_arlen !== 8'd0) $fatal(1, "ar2 up len %0d", out_arlen);
    end else if (DATA_W_IN > DATA_W_OUT) begin
      if (out_arlen !== 8'd1) $fatal(1, "ar2 down len %0d", out_arlen);
    end else begin
      if (out_arlen !== 8'd0) $fatal(1, "ar2 len %0d", out_arlen);
    end
    @(posedge clk);
    #1;
    rdata = DATA_W_OUT'(64'hdead_beef);
    rid = 8'd5;
    rresp = 2'b01;
    rlast = 1'b0;
    rvalid = 1'b1;
    @(posedge clk);
    #1;
    @(negedge clk);
    rvalid = 1'b0;
    if (!out_rvalid) $fatal(1, "r not valid");
    if (out_rdata !== DATA_W_OUT'(64'hdead_beef) || out_rid !== 8'd5 || out_rresp !== 2'b01 || out_rlast !== 1'b0)
      $fatal(1, "r fields");
    @(posedge clk);
    #1;
    @(negedge clk);
    rdata = DATA_W_OUT'(64'hcafe_f00d);
    rlast = 1'b1;
    rvalid = 1'b1;
    @(posedge clk);
    #1;
    @(negedge clk);
    rvalid = 1'b0;
    @(posedge clk);
    #1;
    if (credit_full !== 1'b0) $fatal(1, "credit not returned");
    if (!rready) $fatal(1, "rready not returned");
    $display("TB_PASS n_aw=%0d n_w=%0d n_ar=%0d n_r=%0d", n_aw, n_w, n_ar, n_r);
    $finish;
  end
endmodule
`default_nettype wire
"""


def _axi_tb(in_w: int, out_w: int, wbeats: int, wper: int, wout: int) -> str:
    tb = _AXI_TB
    tb = tb.replace("__INW__", str(in_w)).replace("__OUTW__", str(out_w))
    tb = tb.replace("__WBEATS__", str(wbeats)).replace("__WPER__", str(wper))
    tb = tb.replace("__WOUT__", str(wout))
    factor = max(in_w, out_w) // min(in_w, out_w)
    aw1, aw2, aw3 = 2, 2, 1
    if out_w < in_w:
        aw1, aw2, aw3 = 5, 5, 3
    tb = tb.replace("__AWL1__", f"8'd{aw1}").replace("__AWL2__", f"8'd{aw2}").replace("__AWL3__", f"8'd{aw3}")
    tb = tb.replace("__AWS1__", f"3'd{2 if out_w >= in_w else 1}")
    return tb


_CHI_TB = r"""`default_nettype none
module tb_chi;
  logic clk = 0;
  logic rst_n = 0;
  logic [63:0] in_req_addr = 64'h0;
  logic [2:0] in_req_size = 3'd0;
  logic [3:0] in_req_opcode = 4'd0;
  logic in_req_valid = 0;
  logic in_req_ready;
  logic [63:0] out_req_addr;
  logic [2:0] out_req_size;
  logic [3:0] out_req_opcode;
  logic [1:0] out_req_ch;
  logic out_req_valid;
  logic out_req_ready = 0;
  logic [255:0] in_dat_data = '0;
  logic [31:0] in_dat_be = '0;
  logic in_dat_valid = 0;
  logic in_dat_ready;
  logic [255:0] out_dat_data;
  logic [31:0] out_dat_be;
  logic out_dat_valid;
  logic out_dat_ready = 0;
  logic rsp_valid = 0;
  logic rsp_ready = 0;
  logic out_rsp_valid;
  logic out_rsp_ready = 0;
  logic [3:0] out_rsp_opcode;
  logic out_snp_valid;
  logic out_snp_ready = 0;
  logic [63:0] out_snp_addr;
  logic credit_full;
  logic size_error;
  logic order_violation;
  __DUT_MODULE__ dut (
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
    .order_violation(order_violation)
  );
  always #5 clk = ~clk;
  initial begin
    repeat (4) @(posedge clk);
    @(negedge clk);
    rst_n = 1;
    out_req_ready = 1;
    in_req_addr = 64'h1003;
    in_req_size = 3'd2;
    in_req_opcode = 4'b0000;
    in_req_valid = 1'b1;
    #1;
    if (!in_req_ready) $fatal(1, "req not ready");
    @(posedge clk);
    @(negedge clk);
    in_req_valid = 1'b0;
    if (!out_req_valid) $fatal(1, "req2 not valid");
    if (out_req_addr !== 64'h1000) $fatal(1, "aligned addr %h", out_req_addr);
    if (out_req_size !== 3'd2) $fatal(1, "size %0d", out_req_size);
    if (out_req_ch !== 2'd0) $fatal(1, "req ch %0d", out_req_ch);
    if (size_error !== 1'b1) $fatal(1, "size_error expected for unaligned");
    @(posedge clk);
    @(negedge clk);
    rsp_valid = 1'b1;
    rsp_ready = 1'b1;
    @(posedge clk);
    @(negedge clk);
    rsp_valid = 1'b0;
    in_req_addr = 64'h2000;
    in_req_size = 3'd1;
    in_req_opcode = 4'b0001;
    in_req_valid = 1'b1;
    @(posedge clk);
    @(negedge clk);
    in_req_valid = 1'b0;
    if (!out_rsp_valid) $fatal(1, "rsp not valid");
    if (out_rsp_opcode !== 4'b0001) $fatal(1, "rsp opcode");
    @(posedge clk);
    @(negedge clk);
    rsp_valid = 1'b1;
    rsp_ready = 1'b1;
    @(posedge clk);
    @(negedge clk);
    rsp_valid = 1'b0;
    in_req_addr = 64'h3000;
    in_req_size = 3'd1;
    in_req_opcode = 4'b0010;
    in_req_valid = 1'b1;
    @(posedge clk);
    @(negedge clk);
    in_req_valid = 1'b0;
    if (!out_snp_valid) $fatal(1, "snp not valid");
    if (out_snp_addr !== 64'h3000) $fatal(1, "snp addr");
    @(posedge clk);
    @(negedge clk);
    rsp_valid = 1'b1;
    rsp_ready = 1'b1;
    @(posedge clk);
    @(negedge clk);
    rsp_valid = 1'b0;
    in_dat_data = 256'hffff_ffff_ffff_ffff_0000_0000_0000_0000;
    in_dat_be = 32'h0000_ffff;
    in_dat_valid = 1'b1;
    out_dat_ready = 1'b1;
    @(posedge clk);
    @(negedge clk);
    if (!out_dat_valid) $fatal(1, "dat not valid");
    if (out_dat_data !== 256'hffff_ffff_ffff_ffff_0000_0000_0000_0000) $fatal(1, "dat data");
    if (out_dat_be !== 32'h0000_0003) $fatal(1, "dat be masked %h", out_dat_be);
    @(posedge clk);
    @(negedge clk);
    in_dat_valid = 1'b0;
    if (credit_full !== 1'b0) $fatal(1, "credit not returned");
    $display("TB_PASS chi");
    $finish;
  end
endmodule
`default_nettype wire
"""




_CU_TB = r"""`default_nettype none
module tb_custom;
  logic clk = 0;
  logic rst_n = 0;
  logic [63:0] in_addr = 64'h0;
  logic [255:0] in_data = '0;
  logic [12:0] in_seq = 13'd0;
  logic in_valid = 0;
  logic in_ready;
  logic [63:0] out_addr;
  logic [255:0] out_data;
  logic [12:0] out_seq;
  logic out_valid;
  logic out_ready = 0;
  logic complete_pulse = 0;
  logic burst_required;
  logic order_violation;
  logic outstanding_full;
  __DUT_MODULE__ dut (
    .clk(clk), .rst_n(rst_n),
    .in_addr(in_addr), .in_data(in_data), .in_seq(in_seq),
    .in_valid(in_valid), .in_ready(in_ready),
    .out_addr(out_addr), .out_data(out_data), .out_seq(out_seq),
    .out_valid(out_valid), .out_ready(out_ready),
    .complete_pulse(complete_pulse), .burst_required(burst_required),
    .order_violation(order_violation), .outstanding_full(outstanding_full)
  );
  always #5 clk = ~clk;
  task automatic beat(input logic [12:0] s, input logic exp_ready, input logic exp_burst, input logic exp_viol);
    begin
      @(negedge clk);
      in_seq = s;
      in_valid = 1'b1;
      out_ready = 1'b1;
      #1;
      if (in_ready !== exp_ready) $fatal(1, "ready got=%b exp=%b seq=%0d", in_ready, exp_ready, s);
      if (burst_required !== exp_burst) $fatal(1, "burst got=%b exp=%b seq=%0d", burst_required, exp_burst, s);
      if (order_violation !== exp_viol) $fatal(1, "viol got=%b exp=%b", order_violation, exp_viol);
      @(posedge clk);
      #1;
      @(negedge clk);
      in_valid = 1'b0;
    end
  endtask
  initial begin
    repeat (4) @(posedge clk);
    @(negedge clk);
    rst_n = 1;
    beat(13'd0, 1'b1, 1'b0, 1'b0);
    beat(13'd1, 1'b1, 1'b1, 1'b0);
    beat(13'd2, 1'b1, 1'b0, 1'b0);
    beat(13'd4, 1'b0, 1'b1, 1'b1);
    beat(13'd3, 1'b1, 1'b1, 1'b0);
    beat(13'd4, 1'b1, 1'b0, 1'b0);
    @(negedge clk);
    complete_pulse = 1'b1;
    @(posedge clk);
    #1;
    @(negedge clk);
    complete_pulse = 1'b0;
    if (outstanding_full !== 1'b0) $fatal(1, "not drained after complete");
    $display("TB_PASS custom");
    $finish;
  end
endmodule
`default_nettype wire
"""


def _build(tmp_path: Path, name: str, params: AdapterParams, tb: str) -> str:
    module = build_adapter(params).module
    source = build_adapter(params).source
    assert module is not None and source is not None
    tb = tb.replace("__DUT_MODULE__", module)
    assert module in tb
    d = tmp_path / name
    d.mkdir(parents=True, exist_ok=True)
    (d / f"{module}.sv").write_text(source)
    top = tb.split("module ", 1)[1].split(";", 1)[0].strip()
    (d / f"{top}.sv").write_text(tb)
    return module


def _run(d: Path, module: str, top: str, iverilog: bool = True) -> str:
    verilator_out = None
    if _VERILATOR is not None:
        build = subprocess.run(
            [_VERILATOR, "--binary", "--timing", "-j", "1", "-Wall", "-Wno-fatal",
             "-Wno-WIDTH", "-Wno-PINNOTFOUND", "-Wno-UNOPTFLAT",
             "--top-module", top, "--Mdir", str(d / "obj"),
             f"{module}.sv", f"{top}.sv"],
            cwd=d, capture_output=True, text=True, timeout=300)
        log = build.stdout + build.stderr
        assert build.returncode == 0, log
        assert "%Error" not in log, log
        run = subprocess.run(
            [str(d / "obj" / f"V{top}")],
            cwd=d, capture_output=True, text=True, timeout=60)
        out = run.stdout + run.stderr
        assert run.returncode == 0, out
        verilator_out = out
    if iverilog and _IVERILOG is not None and _VVP is not None:
        build = subprocess.run(
            [_IVERILOG, "-g2012", "-Wall", "-o", str(d / "sim_iv"),
             str(d / f"{module}.sv"), str(d / f"{top}.sv")],
            cwd=d, capture_output=True, text=True, timeout=120)
        log = build.stdout + build.stderr
        assert build.returncode == 0, log
        assert "warning:" not in log.lower(), f"iverilog warnings: {log}"
        run = subprocess.run(
            [_VVP, str(d / "sim_iv")],
            cwd=d, capture_output=True, text=True, timeout=60)
        out = run.stdout + run.stderr
        assert run.returncode == 0, out
        if verilator_out is None:
            assert "TB_PASS" in out, out
        return out
    assert _VERILATOR is not None or _IVERILOG is not None
    return verilator_out or ""


@pytest.mark.parametrize("in_w,out_w,wbeats,wper,wout", [(32, 32, 8, 3, 8), (32, 64, 8, 3, 8), (64, 32, 8, 6, 16)])
def test_axi5_directed_tb(tmp_path, in_w, out_w, wbeats, wper, wout):
    module = _build(tmp_path, f"axi_{in_w}_{out_w}",
                    AdapterParams(agent_idx=0, protocol=ProtocolFamily.AXI5,
                                  in_data_width=in_w, out_data_width=out_w,
                                  data_width=256, split_at=3,
                                  max_outstanding=16),
                    _axi_tb(in_w, out_w, wbeats, wper, wout))
    out = _run(tmp_path / f"axi_{in_w}_{out_w}", module, "tb_axi", iverilog=False)
    assert "TB_PASS" in out, out


def test_chi_directed_tb(tmp_path):
    module = _build(tmp_path, "chi",
                    AdapterParams(agent_idx=0, protocol=ProtocolFamily.CHI,
                                  data_width=256, addr_width=64,
                                  max_outstanding=16, ordering="raw"),
                    _CHI_TB)
    out = _run(tmp_path / "chi", module, "tb_chi", iverilog=False)
    assert "TB_PASS" in out, out


def test_tilelink_directed_tb(tmp_path):
    build = build_adapter(AdapterParams(
        agent_idx=0, protocol=ProtocolFamily.TILELINK, data_width=256,
        addr_width=64, max_outstanding=16, ordering="raw"))
    assert build.module is not None and build.source is not None
    module = build.module
    tb = tilelink_directed_tb_source(module)
    d = tmp_path / "tl"
    d.mkdir(parents=True, exist_ok=True)
    (d / f"{module}.sv").write_text(build.source)
    (d / "tb_tilelink.sv").write_text(tb)
    if _VERILATOR is None:
        pytest.skip("verilator not installed")
    sim = subprocess.run(
        [_VERILATOR, "--binary", "--timing", "-j", "1", "-Wall", "-Wno-fatal",
         "-Wno-WIDTH", "-Wno-PINNOTFOUND", "-Wno-UNOPTFLAT",
         "--top-module", "tb_tilelink", "--Mdir", str(d / "obj"),
         f"{module}.sv", "tb_tilelink.sv"],
        cwd=d, capture_output=True, text=True, timeout=300)
    assert sim.returncode == 0, sim.stdout + sim.stderr
    run = subprocess.run(
        [str(d / "obj" / "Vtb_tilelink")],
        cwd=d, capture_output=True, text=True, timeout=60)
    out = run.stdout + run.stderr
    assert run.returncode == 0, out
    assert "TB_A_PASS" in out, out
    assert "TB_B_PASS" in out, out
    assert "TB_C_PASS" in out, out
    assert "TB_D_PASS" in out, out
    assert "TB_E_PASS" in out, out
    assert "TB_DONE" in out, out


def test_custom_directed_tb(tmp_path):
    module = _build(tmp_path, "cu",
                    AdapterParams(agent_idx=0, protocol=ProtocolFamily.CUSTOM,
                                  split_at=2, ordering="strong",
                                  max_outstanding=8),
                    _CU_TB)
    out = _run(tmp_path / "cu", module, "tb_custom")
    assert "TB_PASS" in out, out
