from __future__ import annotations

import hashlib
import shutil
import subprocess
from pathlib import Path

import pytest

from veritx_dse.product.ordering_fsm_rtl import (
    OrderingPolicy,
    render_ordering_fsm,
)

_CLASSES = (("control", 0), ("data", 1))


def _policy(ordering: str, max_out: int | None, split: int | None = None) -> OrderingPolicy:
    return OrderingPolicy(
        ordering=ordering, max_outstanding=max_out, split_at=split,
        traffic_class_vcs=_CLASSES,
    )


def test_source_banks_domains_and_tags_completions():
    source = render_ordering_fsm(_policy("strong", 4))
    assert "expected_seq_arr[dom_sel]" in source
    assert "outstanding_arr[dom_sel]" in source
    assert "split_cnt_arr[dom_sel]" in source
    assert "dom_sel = {initiator_in, class_in}" in source
    assert "cmp_dom_sel = {complete_initiator, complete_class}" in source
    assert "complete_tagged" in source
    assert "journal_head_match" in source
    assert "assign complete_mismatch" in source
    assert "assign burst_journal_overflow" in source
    assert "logic [12:0] expected_seq;" not in source
    assert "assign expected_seq_sel = expected_seq_arr[dom_sel];" in source


def test_domain_widening_changes_source():
    a = render_ordering_fsm(_policy("strong", 4))
    b = render_ordering_fsm(_policy("strong", 8))
    assert a != b
    assert hashlib.sha256(a.encode()).hexdigest() != hashlib.sha256(
        b.encode()).hexdigest()
    solo = render_ordering_fsm(OrderingPolicy(ordering="strong",
                                              max_outstanding=4))
    assert solo != a


_TB_HEAD = r"""`default_nettype none
module tb_ordering_x;
  logic clk = 0;
  logic rst_n = 0;
  logic in_valid = 0;
  logic in_ready;
  logic [63:0] in_flit = 64'h0;
  logic [1:0] initiator_in = 2'b00;
  logic [0:0] class_in = 1'b0;
  logic complete_pulse = 0;
  logic complete_tagged = 0;
  logic [12:0] complete_seq = 13'd0;
  logic [1:0] complete_initiator = 2'b00;
  logic [0:0] complete_class = 1'b0;
  logic out_valid;
  logic out_ready = 0;
  logic [63:0] out_flit;
  logic [0:0] assigned_vc;
  logic order_violation;
  logic outstanding_full;
  logic split_required;
  logic complete_mismatch;
  logic burst_journal_overflow;

  ordering_fsm dut (
    .clk(clk), .rst_n(rst_n),
    .in_valid(in_valid), .in_ready(in_ready), .in_flit(in_flit),
    .initiator_in(initiator_in), .class_in(class_in),
    .complete_pulse(complete_pulse), .complete_tagged(complete_tagged),
    .complete_seq(complete_seq), .complete_initiator(complete_initiator),
    .complete_class(complete_class),
    .out_valid(out_valid), .out_ready(out_ready), .out_flit(out_flit),
    .assigned_vc(assigned_vc), .order_violation(order_violation),
    .outstanding_full(outstanding_full), .split_required(split_required),
    .complete_mismatch(complete_mismatch),
    .burst_journal_overflow(burst_journal_overflow)
  );

  always #5 clk <= ~clk;

  int up_count = 0;
  int down_count = 0;

  function automatic logic [63:0] mkflit(input logic [12:0] seq, input logic [1:0] typ);
    logic [63:0] f;
    begin
      f = 64'h0;
      f[62:61] = typ;
      f[44:32] = seq;
      f[31:0] = 32'h1234_0000 | {19'h0, seq};
      mkflit = f;
    end
  endfunction

  task automatic cycle(
    input logic v,
    input logic [1:0] ini,
    input logic cls,
    input logic [63:0] f,
    input logic r,
    input logic c,
    input logic tg,
    input logic [12:0] cseq,
    input logic [1:0] cini,
    input logic ccls,
    input logic exp_ir,
    input logic exp_ov,
    input logic exp_viol,
    input logic [1:0] exp_typ,
    input logic exp_split
  );
    begin
      @(negedge clk);
      in_valid = v;
      initiator_in = ini;
      class_in = cls;
      in_flit = f;
      out_ready = r;
      complete_pulse = c;
      complete_tagged = tg;
      complete_seq = cseq;
      complete_initiator = cini;
      complete_class = ccls;
      #1;
      if (in_ready !== exp_ir) $fatal(1, "cycle in_ready got=%b exp=%b", in_ready, exp_ir);
      if (out_valid !== exp_ov) $fatal(1, "cycle out_valid got=%b exp=%b", out_valid, exp_ov);
      if (order_violation !== exp_viol) $fatal(1, "cycle viol got=%b exp=%b", order_violation, exp_viol);
      if (exp_typ != 2'b11 && out_flit[62:61] !== exp_typ) $fatal(1, "cycle typ got=%b exp=%b", out_flit[62:61], exp_typ);
      if (split_required !== exp_split) $fatal(1, "cycle split got=%b exp=%b", split_required, exp_split);
      if (complete_mismatch !== 1'b0) $fatal(1, "cycle mismatch got=%b", complete_mismatch);
      if (burst_journal_overflow !== 1'b0) $fatal(1, "cycle overflow got=%b", burst_journal_overflow);
      if (assigned_vc !== class_in) $fatal(1, "assigned vc got=%b class=%b", assigned_vc, class_in);
      if (^out_flit === 1'bx) $fatal(1, "out_flit unknown");
      if (outstanding_full !== 1'b0 && outstanding_full !== 1'b1) $fatal(1, "full unknown");
      if (in_valid && in_ready) up_count = up_count + 1;
      if (out_valid && out_ready) down_count = down_count + 1;
      @(posedge clk);
      #1;
    end
  endtask

  task automatic idle_complete(
    input logic [12:0] cseq,
    input logic [12:0] dseq,
    input logic [1:0] cini,
    input logic ccls,
    input logic exp_ir
  );
    begin
      cycle(1'b0, 2'b00, 1'b0, mkflit(dseq, 2'b01), 1'b1, 1'b1, 1'b1, cseq, cini, ccls,
            exp_ir, 1'b0, 1'b0, 2'b11, 1'b0);
    end
  endtask
"""

_WRAP_BODY = r"""
  int i;
  int before_up;
  int before_down;
  logic [12:0] seq_v;
  initial begin
    repeat (3) @(posedge clk);
    @(negedge clk);
    rst_n = 1;
    #1;
    seq_v = 13'd0;
    for (i = 0; i <= 8191; i = i + 1) begin
      cycle(1'b1, 2'b00, 1'b0, mkflit(seq_v, 2'b01), 1'b1, 1'b0, 1'b0, 13'd0, 2'b00, 1'b0,
            1'b1, 1'b1, 1'b0, 2'b01, 1'b0);
      idle_complete(seq_v, seq_v + 13'd1, 2'b00, 1'b0, 1'b1);
      seq_v = seq_v + 13'd1;
    end
    if (up_count != 8192 || down_count != 8192) $fatal(1, "wrap counts up=%0d down=%0d", up_count, down_count);
    cycle(1'b1, 2'b00, 1'b0, mkflit(13'd0, 2'b01), 1'b1, 1'b0, 1'b0, 13'd0, 2'b00, 1'b0,
          1'b1, 1'b1, 1'b0, 2'b01, 1'b0);
    idle_complete(13'd0, 13'd1, 2'b00, 1'b0, 1'b1);
    cycle(1'b1, 2'b00, 1'b0, mkflit(13'd1, 2'b01), 1'b1, 1'b0, 1'b0, 13'd0, 2'b00, 1'b0,
          1'b1, 1'b1, 1'b0, 2'b01, 1'b0);
    idle_complete(13'd1, 13'd2, 2'b00, 1'b0, 1'b1);
    if (up_count != 8194 || down_count != 8194) $fatal(1, "post-wrap counts up=%0d down=%0d", up_count, down_count);
    before_up = up_count;
    before_down = down_count;
    cycle(1'b1, 2'b00, 1'b0, mkflit(13'd1, 2'b01), 1'b1, 1'b0, 1'b0, 13'd0, 2'b00, 1'b0,
          1'b0, 1'b0, 1'b1, 2'b01, 1'b0);
    cycle(1'b1, 2'b00, 1'b0, mkflit(13'd1, 2'b01), 1'b1, 1'b0, 1'b0, 13'd0, 2'b00, 1'b0,
          1'b0, 1'b0, 1'b1, 2'b01, 1'b0);
    if (up_count != before_up || down_count != before_down) $fatal(1, "duplicate accepted after wrap");
    cycle(1'b1, 2'b00, 1'b0, mkflit(13'd2, 2'b01), 1'b1, 1'b0, 1'b0, 13'd0, 2'b00, 1'b0,
          1'b1, 1'b1, 1'b0, 2'b01, 1'b0);
    if (up_count != before_up + 1 || down_count != before_down + 1) $fatal(1, "seq2 did not accept after dup reject");
    $display("TB_PASS up=%0d down=%0d", up_count, down_count);
    $finish;
  end
"""

_MULTI_BODY = r"""
  int before_up;
  int before_down;
  initial begin
    repeat (3) @(posedge clk);
    @(negedge clk);
    rst_n = 1;
    #1;
    cycle(1'b1, 2'b00, 1'b0, mkflit(13'd0, 2'b01), 1'b1, 1'b0, 1'b0, 13'd0, 2'b00, 1'b0, 1'b1, 1'b1, 1'b0, 2'b01, 1'b0);
    cycle(1'b1, 2'b01, 1'b0, mkflit(13'd0, 2'b01), 1'b1, 1'b0, 1'b0, 13'd0, 2'b00, 1'b0, 1'b1, 1'b1, 1'b0, 2'b01, 1'b0);
    cycle(1'b1, 2'b00, 1'b1, mkflit(13'd0, 2'b01), 1'b1, 1'b0, 1'b0, 13'd0, 2'b00, 1'b0, 1'b1, 1'b1, 1'b0, 2'b01, 1'b0);
    cycle(1'b1, 2'b01, 1'b1, mkflit(13'd0, 2'b01), 1'b1, 1'b0, 1'b0, 13'd0, 2'b00, 1'b0, 1'b1, 1'b1, 1'b0, 2'b01, 1'b0);
    cycle(1'b1, 2'b00, 1'b0, mkflit(13'd1, 2'b01), 1'b1, 1'b0, 1'b0, 13'd0, 2'b00, 1'b0, 1'b1, 1'b1, 1'b0, 2'b01, 1'b0);
    cycle(1'b1, 2'b01, 1'b0, mkflit(13'd1, 2'b01), 1'b1, 1'b0, 1'b0, 13'd0, 2'b00, 1'b0, 1'b1, 1'b1, 1'b0, 2'b01, 1'b0);
    if (up_count != 6 || down_count != 6) $fatal(1, "multi counts up=%0d down=%0d", up_count, down_count);
    before_up = up_count;
    before_down = down_count;
    cycle(1'b1, 2'b00, 1'b0, mkflit(13'd4, 2'b01), 1'b1, 1'b0, 1'b0, 13'd0, 2'b00, 1'b0, 1'b0, 1'b0, 1'b1, 2'b01, 1'b0);
    cycle(1'b1, 2'b00, 1'b0, mkflit(13'd4, 2'b01), 1'b1, 1'b0, 1'b0, 13'd0, 2'b00, 1'b0, 1'b0, 1'b0, 1'b1, 2'b01, 1'b0);
    cycle(1'b1, 2'b00, 1'b0, mkflit(13'd4, 2'b01), 1'b1, 1'b0, 1'b0, 13'd0, 2'b00, 1'b0, 1'b0, 1'b0, 1'b1, 2'b01, 1'b0);
    if (up_count != before_up || down_count != before_down) $fatal(1, "blocked multi counted");
    cycle(1'b1, 2'b00, 1'b0, mkflit(13'd2, 2'b01), 1'b1, 1'b0, 1'b0, 13'd0, 2'b00, 1'b0, 1'b1, 1'b1, 1'b0, 2'b01, 1'b0);
    cycle(1'b1, 2'b00, 1'b0, mkflit(13'd3, 2'b01), 1'b1, 1'b0, 1'b0, 13'd0, 2'b00, 1'b0, 1'b1, 1'b1, 1'b0, 2'b01, 1'b0);
    cycle(1'b1, 2'b00, 1'b0, mkflit(13'd4, 2'b01), 1'b1, 1'b0, 1'b0, 13'd0, 2'b00, 1'b0, 1'b1, 1'b1, 1'b0, 2'b01, 1'b0);
    if (up_count != before_up + 3 || down_count != before_down + 3) $fatal(1, "blocked beat not accepted exactly once up=%0d", up_count);
    before_up = up_count;
    before_down = down_count;
    cycle(1'b1, 2'b00, 1'b0, mkflit(13'd4, 2'b01), 1'b1, 1'b0, 1'b0, 13'd0, 2'b00, 1'b0, 1'b0, 1'b0, 1'b1, 2'b01, 1'b0);
    cycle(1'b1, 2'b00, 1'b0, mkflit(13'd4, 2'b01), 1'b1, 1'b0, 1'b0, 13'd0, 2'b00, 1'b0, 1'b0, 1'b0, 1'b1, 2'b01, 1'b0);
    if (up_count != before_up || down_count != before_down) $fatal(1, "duplicate accepted multi");
    cycle(1'b1, 2'b00, 1'b0, mkflit(13'd5, 2'b01), 1'b1, 1'b0, 1'b0, 13'd0, 2'b00, 1'b0, 1'b1, 1'b1, 1'b0, 2'b01, 1'b0);
    if (up_count != before_up + 1 || down_count != before_down + 1) $fatal(1, "seq5 did not accept");
    if (up_count != down_count) $fatal(1, "multi up/down mismatch");
    $display("TB_PASS up=%0d down=%0d", up_count, down_count);
    $finish;
  end
"""

_BURST_BODY = r"""
  initial begin
    repeat (3) @(posedge clk);
    @(negedge clk);
    rst_n = 1;
    #1;
    cycle(1'b1, 2'b00, 1'b0, mkflit(13'd0, 2'b01), 1'b1, 1'b0, 1'b0, 13'd0, 2'b00, 1'b0, 1'b1, 1'b1, 1'b0, 2'b01, 1'b0);
    cycle(1'b1, 2'b00, 1'b0, mkflit(13'd1, 2'b01), 1'b1, 1'b0, 1'b0, 13'd0, 2'b00, 1'b0, 1'b1, 1'b1, 1'b0, 2'b01, 1'b0);
    cycle(1'b1, 2'b00, 1'b0, mkflit(13'd2, 2'b01), 1'b1, 1'b0, 1'b0, 13'd0, 2'b00, 1'b0, 1'b1, 1'b1, 1'b0, 2'b10, 1'b1);
    if (outstanding_full !== 1'b1) $fatal(1, "not full after first burst of 3");
    cycle(1'b1, 2'b00, 1'b0, mkflit(13'd3, 2'b01), 1'b1, 1'b0, 1'b0, 13'd0, 2'b00, 1'b0, 1'b0, 1'b0, 1'b0, 2'b00, 1'b0);
    @(negedge clk);
    complete_pulse = 1'b1;
    complete_tagged = 1'b1;
    complete_seq = 13'd3;
    complete_initiator = 2'b00;
    complete_class = 1'b0;
    #1;
    if (complete_mismatch !== 1'b1) $fatal(1, "out-of-order burst completion not flagged");
    if (outstanding_full !== 1'b1) $fatal(1, "mismatch freed credit");
    @(posedge clk);
    #1;
    @(negedge clk);
    complete_pulse = 1'b1;
    complete_tagged = 1'b1;
    complete_seq = 13'd0;
    complete_initiator = 2'b00;
    complete_class = 1'b0;
    #1;
    if (complete_mismatch !== 1'b0) $fatal(1, "head burst completion flagged");
    @(posedge clk);
    #1;
    cycle(1'b1, 2'b00, 1'b0, mkflit(13'd3, 2'b01), 1'b1, 1'b0, 1'b0, 13'd0, 2'b00, 1'b0, 1'b1, 1'b1, 1'b0, 2'b00, 1'b0);
    cycle(1'b1, 2'b00, 1'b0, mkflit(13'd4, 2'b01), 1'b1, 1'b0, 1'b0, 13'd0, 2'b00, 1'b0, 1'b1, 1'b1, 1'b0, 2'b01, 1'b0);
    cycle(1'b1, 2'b00, 1'b0, mkflit(13'd5, 2'b01), 1'b1, 1'b0, 1'b0, 13'd0, 2'b00, 1'b0, 1'b1, 1'b1, 1'b0, 2'b10, 1'b1);
    if (outstanding_full !== 1'b1) $fatal(1, "not full after second burst of 3");
    idle_complete(13'd3, 13'd6, 2'b00, 1'b0, 1'b0);
    cycle(1'b1, 2'b00, 1'b0, mkflit(13'd6, 2'b01), 1'b1, 1'b0, 1'b0, 13'd0, 2'b00, 1'b0, 1'b1, 1'b1, 1'b0, 2'b00, 1'b0);
    cycle(1'b1, 2'b00, 1'b0, mkflit(13'd7, 2'b01), 1'b1, 1'b0, 1'b0, 13'd0, 2'b00, 1'b0, 1'b1, 1'b1, 1'b0, 2'b01, 1'b0);
    cycle(1'b1, 2'b00, 1'b0, mkflit(13'd8, 2'b01), 1'b1, 1'b0, 1'b0, 13'd0, 2'b00, 1'b0, 1'b1, 1'b1, 1'b0, 2'b10, 1'b1);
    if (up_count != 9 || down_count != 9) $fatal(1, "burst counts up=%0d down=%0d", up_count, down_count);
    $display("TB_PASS up=%0d down=%0d", up_count, down_count);
    $finish;
  end
"""

_TB_TAIL = r"""
endmodule
`default_nettype wire
"""


def _tb(body: str) -> str:
    return _TB_HEAD + body + _TB_TAIL


def _write_case(tmp_path: Path, name: str, policy: OrderingPolicy, body: str) -> tuple[Path, Path]:
    work = tmp_path / name
    work.mkdir(parents=True, exist_ok=True)
    dut = work / "ordering_fsm.sv"
    dut.write_text(render_ordering_fsm(policy))
    tb = work / "tb_ordering_x.sv"
    tb.write_text(_tb(body))
    return work, dut


def _run_verilator(work: Path, dut: Path, tb: Path) -> str:
    if shutil.which("verilator") is None:
        pytest.skip("Verilator absent: simulation unavailable")
    build = subprocess.run(
        ["verilator", "--binary", "--timing", "-j", "1", "-Wall", "-Wno-fatal",
         "--top-module", "tb_ordering_x", "--Mdir", str(work / "obj"),
         str(dut), str(tb)],
        cwd=work, capture_output=True, text=True, timeout=120,
    )
    log = build.stdout + build.stderr
    assert build.returncode == 0, log
    assert "%Warning" not in log, log
    assert "%Error" not in log, log
    run = subprocess.run(
        [str(work / "obj" / "Vtb_ordering_x")],
        cwd=work, capture_output=True, text=True, timeout=60,
    )
    output = run.stdout + run.stderr
    assert run.returncode == 0, output
    assert "TB_PASS" in output, output
    assert "%Warning" not in output, output
    return output


def _run_iverilog(work: Path, dut: Path, tb: Path) -> str:
    if shutil.which("iverilog") is None or shutil.which("vvp") is None:
        pytest.skip("iverilog absent: simulation unavailable")
    build = subprocess.run(
        ["iverilog", "-g2012", "-Wall", "-o", str(work / "sim_iv"),
         str(dut), str(tb)],
        cwd=work, capture_output=True, text=True, timeout=60,
    )
    log = build.stdout + build.stderr
    assert build.returncode == 0, log
    assert "warning:" not in log.lower(), log
    run = subprocess.run(
        ["vvp", str(work / "sim_iv")],
        cwd=work, capture_output=True, text=True, timeout=60,
    )
    output = run.stdout + run.stderr
    assert run.returncode == 0, output
    assert "TB_PASS" in output, output
    return output


_CASES = [
    ("wrap", _policy("strong", None), _WRAP_BODY),
    ("multi", _policy("strong", 16), _MULTI_BODY),
    ("burst", _policy("strong", 3, 3), _BURST_BODY),
]


@pytest.mark.parametrize("name,policy,body", _CASES, ids=[c[0] for c in _CASES])
def test_multidomain_tb_verilator(name, policy, body, tmp_path):
    work, dut = _write_case(tmp_path, f"vl_{name}", policy, body)
    assert "TB_PASS" in _run_verilator(work, dut, work / "tb_ordering_x.sv")


@pytest.mark.parametrize("name,policy,body", _CASES, ids=[c[0] for c in _CASES])
def test_multidomain_tb_iverilog(name, policy, body, tmp_path):
    work, dut = _write_case(tmp_path, f"iv_{name}", policy, body)
    assert "TB_PASS" in _run_iverilog(work, dut, work / "tb_ordering_x.sv")
