from __future__ import annotations

import hashlib
import shutil
import subprocess
from pathlib import Path

import pytest

from veritx_dse.core.paths import REPO
from veritx_dse.product.cdc_cell_rtl import (
    CdcParams,
    build_cdc_cell,
    check_cdc_cell_source,
    emitted_fifo_depth,
    net_usable_depth,
)

_FIFO = Path(REPO) / "tracks/t3-topology/rtl/cdc/cdc_fifo.sv"
_VERILATOR = shutil.which("verilator")


def _params(depth: int = 8) -> CdcParams:
    return CdcParams(
        insertion_point="cdc:declared:a->b", src_domain="a",
        dst_domain="b", depth=depth)


def test_usable_depth_emits_doubled_nominal():
    assert net_usable_depth(8) == 8
    assert emitted_fifo_depth(8) == 16
    build = build_cdc_cell(_params(8))
    assert build.verdict.ok is True
    assert "USABLE_DEPTH = 8" in (build.source or "")
    assert "DEPTH = 16" in (build.source or "")
    assert ".DEPTH(DEPTH)" in (build.source or "")


def test_hash_diff_proves_full_usable_not_half():
    small = build_cdc_cell(_params(8))
    big = build_cdc_cell(_params(16))
    assert small.source is not None and big.source is not None
    assert hashlib.sha256(small.source.encode()).hexdigest() != hashlib.sha256(
        big.source.encode()).hexdigest()
    assert "DEPTH = 32" in big.source
    assert "USABLE_DEPTH = 16" in big.source
    assert check_cdc_cell_source(small.source or "", depth=8) == ()
    assert check_cdc_cell_source(big.source or "", depth=16) == ()
    assert check_cdc_cell_source(small.source or "", depth=16) != ()


_TB = r"""`timescale 1ns/1ps
`default_nettype none
module tb_cdc_skew;
  logic src_clk = 0;
  logic dst_clk = 0;
  logic src_rst_n = 0;
  logic dst_rst_n = 0;
  logic src_req_toggle = 0;
  logic src_ack_sync_toggle;
  logic wr_en = 0;
  logic [63:0] wr_data = 64'h0;
  logic wr_full;
  logic dst_req_sync_toggle;
  logic dst_req_valid;
  logic dst_ack_toggle = 0;
  logic rd_en = 1;
  logic [63:0] rd_data;
  logic rd_valid;
  logic rd_empty;

  cdc_cell_cdc_declared_a_b_00000000 u_cell (
    .src_clk(src_clk), .src_rst_n(src_rst_n),
    .src_req_toggle(src_req_toggle),
    .src_ack_sync_toggle(src_ack_sync_toggle),
    .wr_en(wr_en), .wr_data(wr_data), .wr_full(wr_full),
    .dst_clk(dst_clk), .dst_rst_n(dst_rst_n),
    .dst_req_sync_toggle(dst_req_sync_toggle),
    .dst_req_valid(dst_req_valid),
    .dst_ack_toggle(dst_ack_toggle),
    .rd_en(rd_en), .rd_data(rd_data), .rd_valid(rd_valid),
    .rd_empty(rd_empty)
  );

  always #3 src_clk = ~src_clk;
  always #5 dst_clk = ~dst_clk;

  int wr_accepts = 0;
  int rd_valids = 0;
  logic [63:0] wr_seen [0:63];
  logic [63:0] rd_seen [0:63];
  logic live = 0;

  always @(negedge src_clk) begin
    #2;
    if (live && src_rst_n && dst_rst_n && wr_en && !wr_full) begin
      if (wr_accepts >= 64) $fatal(1, "wr overflow");
      wr_seen[wr_accepts] = wr_data;
      wr_accepts = wr_accepts + 1;
    end
  end

  always @(negedge dst_clk) begin
    #2;
    if (live && rd_valid) begin
      if (rd_valids >= 64) $fatal(1, "rd overflow");
      rd_seen[rd_valids] = rd_data;
      rd_valids = rd_valids + 1;
    end
    if (!src_rst_n || !dst_rst_n) begin
      if (rd_valid) $fatal(1, "rd_valid during reset");
    end
  end

  task automatic write_one(input logic [63:0] value);
    begin
      @(negedge src_clk);
      wr_data = value;
      wr_en = 1'b1;
      @(negedge src_clk);
      wr_en = 1'b0;
    end
  endtask

  task automatic settle(input int ncycles);
    int k;
    begin
      for (k = 0; k < ncycles; k = k + 1) @(dst_clk);
    end
  endtask

  initial begin
    int i;
    int j;
    int held_reads;
    #7;
    src_rst_n = 1;
    #14;
    dst_rst_n = 1;
    if (!wr_full || !rd_empty) $fatal(1, "interface not held during reset alignment");
    live = 1;
    wr_data = 64'hDEAD_BEEF_0000_0000;
    wr_en = 1'b1;
    repeat (2) @(posedge src_clk);
    if (!wr_full) $fatal(1, "writer released before reset alignment");
    wr_en = 1'b0;
    settle(12);
    write_one(64'h1111_1111_0000_0001);
    write_one(64'h2222_2222_0000_0002);
    write_one(64'h3333_3333_0000_0003);
    write_one(64'h4444_4444_0000_0004);
    settle(30);
    if (wr_accepts != 4) $fatal(1, "phase1 wr=%0d exp4", wr_accepts);
    if (rd_valids != 4) $fatal(1, "phase1 rd=%0d exp4", rd_valids);
    for (i = 0; i < 4; i = i + 1) begin
      if (rd_seen[i] !== wr_seen[i]) $fatal(1, "phase1 order i=%0d", i);
    end
    if (rd_empty !== 1'b1) $fatal(1, "not drained before skew");
    @(negedge src_clk);
    wr_data = 64'h5555_5555_0000_0005;
    wr_en = 1'b1;
    #3;
    src_rst_n = 0;
    #1;
    if (rd_valid || !rd_empty || !wr_full)
      $fatal(1, "remote reset assertion did not immediately gate CDC interfaces");
    #8;
    dst_rst_n = 0;
    #13;
    if (rd_valid) $fatal(1, "rd_valid during skew reset");
    if (wr_full !== 1'b1) $fatal(1, "writer not backpressured during reset");
    #6;
    dst_rst_n = 1;
    #17;
    src_rst_n = 1;
    settle(10);
    @(negedge src_clk);
    wr_en = 1'b0;
    settle(20);
    write_one(64'h6666_6666_0000_0006);
    write_one(64'h7777_7777_0000_0007);
    settle(40);
    if (wr_accepts < 7) $fatal(1, "total wr=%0d exp>=7", wr_accepts);
    if (rd_valids > wr_accepts) $fatal(1, "rd exceeds wr rd=%0d wr=%0d", rd_valids, wr_accepts);
    if (wr_accepts > 40) $fatal(1, "too many held accepts wr=%0d", wr_accepts);
    j = 0;
    held_reads = 0;
    for (i = 0; i < rd_valids; i = i + 1) begin
      if (rd_seen[i] === 64'h5555_5555_0000_0005) held_reads = held_reads + 1;
      while (j < wr_accepts && wr_seen[j] !== rd_seen[i]) j = j + 1;
      if (j >= wr_accepts) $fatal(1, "reorder/phantom read i=%0d val=%h", i, rd_seen[i]);
      j = j + 1;
    end
    if (held_reads == 0) $fatal(1, "held value never read");
    if (rd_empty !== 1'b1) $fatal(1, "not drained after skew");
    $display("TB_PASS wr=%0d rd=%0d", wr_accepts, rd_valids);
    $finish;
  end
endmodule
`default_nettype wire
"""


@pytest.mark.skipif(_VERILATOR is None, reason="verilator not installed")
def test_reset_skew_tb(tmp_path):
    build = build_cdc_cell(_params(8))
    assert build.module is not None and build.source is not None
    module = build.module
    tb = _TB.replace("cdc_cell_cdc_declared_a_b_00000000", module)
    assert module in tb
    (tmp_path / "cdc_fifo.sv").write_text(_FIFO.read_text())
    (tmp_path / f"{module}.sv").write_text(build.source)
    (tmp_path / "tb_cdc_skew.sv").write_text(tb)
    sim = subprocess.run(
        [_VERILATOR, "--binary", "--timing", "-j", "1", "-Wall", "-Wno-fatal",
         "-Wno-WIDTH", "-Wno-PINNOTFOUND", "-Wno-UNOPTFLAT",
         "--top-module", "tb_cdc_skew", "--Mdir", str(tmp_path / "obj"),
         "cdc_fifo.sv", f"{module}.sv", "tb_cdc_skew.sv"],
        cwd=tmp_path, capture_output=True, text=True, timeout=300)
    log = sim.stdout + sim.stderr
    assert sim.returncode == 0, log
    assert "%Error" not in log, log
    run = subprocess.run(
        [str(tmp_path / "obj" / "Vtb_cdc_skew")],
        cwd=tmp_path, capture_output=True, text=True, timeout=60)
    out = run.stdout + run.stderr
    assert run.returncode == 0, out
    assert "TB_PASS" in out, out
