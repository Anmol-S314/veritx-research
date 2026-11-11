"""OrderingFSM ready/valid handshake directed regression.

Counterexample from audit §3: ``in_ready = out_ready && !full && permits``
while ``out_valid = in_valid`` lets a held beat be consumed downstream
while upstream sees blocked. The fix shares one ``fwd_permits`` signal on
both sides. This module checks the equations, the defined sequence /
outstanding / split semantics in the emitted header, lint with zero
warnings, and simulated counterexample behaviour on Verilator and iverilog.
The FSM is exercised in isolation (not wired into ``noc_top`` here).
"""
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

_OLD_BLOCK = (
    "  assign in_ready = out_ready && !outstanding_full\n"
    "                    && ((ORDERING_MODE != 1) || in_order);\n"
    "  assign out_valid = in_valid;"
)
_NEW_BLOCK = (
    "  assign fwd_permits = !full_sel\n"
    "                     && ((ORDERING_MODE != 1) || in_order);\n"
    "  assign in_ready = out_ready && fwd_permits;\n"
    "  assign out_valid = in_valid && fwd_permits;"
)


def _policy(ordering: str, max_out: int | None) -> OrderingPolicy:
    return OrderingPolicy(
        ordering=ordering, max_outstanding=max_out, traffic_class_vcs=_CLASSES
    )


def test_handshake_equations_are_shared_and_match_header_defs():
    for ordering, max_out in (("strong", 4), ("relaxed", 8), ("raw", None)):
        source = render_ordering_fsm(_policy(ordering, max_out))
        # Fixed equations: one permission governs both sides.
        assert "assign fwd_permits" in source
        assert "assign in_ready = out_ready && fwd_permits;" in source
        assert "assign out_valid = in_valid && fwd_permits;" in source
        # Old buggy unconditional out_valid must be gone (exact line).
        assert "assign out_valid = in_valid;" not in source
        assert "assign out_valid = in_valid && fwd_permits;" in source
        # Wrap-aware forward distance (mod-8192 unsigned gap).
        assert "assign fwd_gap = seq_in - expected_seq_sel;" in source
        for token in (
            "expected_seq_arr[dom_sel]",
            "N_DOMAINS",
            "initiator_in",
            "complete_tagged",
            "complete_mismatch",
            "burst_journal_remaining[burst_head_idx]",
            "burst_journal_overflow",
            "outstanding_arr[dom_sel]",
            "split_cnt_arr[dom_sel]",
            "split_required",
            "2'd2",
            "2'd0",
            "fwd_permits",
        ):
            assert token in source, token
        # Hash-diff vs old buggy output: reconstruct the buggy source by
        # swapping in the audit-§3 lines; the fixed source must differ.
        buggy = source.replace(_NEW_BLOCK, _OLD_BLOCK)
        assert buggy != source
        assert hashlib.sha256(source.encode()).hexdigest() != hashlib.sha256(
            buggy.encode()
        ).hexdigest()
        assert "assign out_valid = in_valid;" in buggy


def _lint_source(source: str, tmp_sub: Path) -> None:
    tmp_sub.mkdir(parents=True, exist_ok=True)
    path = tmp_sub / "ordering_fsm.sv"
    path.write_text(source)
    checked = subprocess.run(
        ["verilator", "--lint-only", "-sv", "-Wall", "-Wno-fatal",
         "--top-module", "ordering_fsm", path.name],
        cwd=tmp_sub, capture_output=True, text=True, timeout=60,
    )
    log = checked.stdout + checked.stderr
    assert checked.returncode == 0, log
    assert "%Warning" not in log, log


@pytest.mark.parametrize(
    "ordering,max_out,split",
    [("strong", 4, None), ("relaxed", 8, None), ("raw", None, None),
     ("strong", None, 64), ("strong", 2, 3)],
)
def test_render_variants_lint_zero_warnings(ordering, max_out, split, tmp_path):
    if shutil.which("verilator") is None:
        pytest.skip("Verilator absent: lint unavailable")
    policy = OrderingPolicy(
        ordering=ordering, max_outstanding=max_out,
        split_at=split, traffic_class_vcs=_CLASSES,
    )
    _lint_source(render_ordering_fsm(policy), tmp_path / "lint")


# --- directed simulation TB (SystemVerilog, runs on both simulators) ------

_TB_TEMPLATE = r"""`default_nettype none
module tb_ordering_fsm;
  localparam int MODE = __MODE__;
  logic clk = 0;
  logic rst_n = 0;
  logic in_valid = 0;
  logic in_ready;
  logic [63:0] in_flit = 64'h0;
  logic [0:0] class_in = 1'b0;
  logic complete_pulse = 0;
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
    .class_in(class_in), .complete_pulse(complete_pulse),
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
    input logic [63:0] f,
    input logic r,
    input logic c,
    input logic exp_ir,
    input logic exp_ov,
    input logic exp_viol
  );
    begin
      @(negedge clk);
      in_valid = v;
      in_flit = f;
      out_ready = r;
      complete_pulse = c;
      #1;
      if (in_ready !== exp_ir) $fatal(1, "cycle in_ready got=%b exp=%b v=%b", in_ready, exp_ir, v);
      if (out_valid !== exp_ov) $fatal(1, "cycle out_valid got=%b exp=%b v=%b", out_valid, exp_ov, v);
      if (order_violation !== exp_viol) $fatal(1, "cycle viol got=%b exp=%b", order_violation, exp_viol);
      if (complete_mismatch !== 1'b0) $fatal(1, "cycle mismatch got=%b", complete_mismatch);
      if (burst_journal_overflow !== 1'b0) $fatal(1, "cycle overflow got=%b", burst_journal_overflow);
      if (in_valid && in_ready) up_count = up_count + 1;
      if (out_valid && out_ready) down_count = down_count + 1;
      @(posedge clk);
      #1;
    end
  endtask

  initial begin
    logic [63:0] blocked;
    int before_up;
    int before_down;
    repeat (3) @(posedge clk);
    @(negedge clk);
    rst_n = 1;
    #1;
    if (MODE == 1) begin
      // STRONG gap counterexample: expected 0, present 1, out_ready=1.
      // Fixed: in_ready=0 and out_valid=0 together, zero downstream accepts.
      blocked = mkflit(13'd1, 2'b01);
      before_up = up_count;
      before_down = down_count;
      cycle(1'b1, blocked, 1'b1, 1'b0, 1'b0, 1'b0, 1'b1);
      if (in_flit !== blocked || in_valid !== 1'b1) $fatal(1, "blocked beat not held stable c1");
      cycle(1'b1, blocked, 1'b1, 1'b0, 1'b0, 1'b0, 1'b1);
      if (in_flit !== blocked || in_valid !== 1'b1) $fatal(1, "blocked beat not held stable c2");
      cycle(1'b1, blocked, 1'b1, 1'b0, 1'b0, 1'b0, 1'b1);
      if (in_flit !== blocked || in_valid !== 1'b1) $fatal(1, "blocked beat not held stable c3");
      if (up_count != before_up) $fatal(1, "upstream accepted while blocked");
      if (down_count != before_down) $fatal(1, "downstream accepted while blocked down=%0d before=%0d", down_count, before_down);
      // Resume proves expected_seq never advanced on blocked cycles.
      cycle(1'b1, mkflit(13'd0, 2'b01), 1'b1, 1'b0, 1'b1, 1'b1, 1'b0);
      cycle(1'b1, mkflit(13'd1, 2'b01), 1'b1, 1'b0, 1'b1, 1'b1, 1'b0);
      if (up_count != before_up + 2) $fatal(1, "resume up mismatch");
      if (down_count != before_down + 2) $fatal(1, "resume down mismatch");
      // Drain two outstanding units (idle completes; not full so in_ready=1).
      cycle(1'b0, mkflit(13'd2, 2'b01), 1'b1, 1'b1, 1'b1, 1'b0, 1'b0);
      cycle(1'b0, mkflit(13'd2, 2'b01), 1'b1, 1'b1, 1'b1, 1'b0, 1'b0);
      // Fill to MAX=4 with in-order seq 2..5.
      cycle(1'b1, mkflit(13'd2, 2'b01), 1'b1, 1'b0, 1'b1, 1'b1, 1'b0);
      cycle(1'b1, mkflit(13'd3, 2'b01), 1'b1, 1'b0, 1'b1, 1'b1, 1'b0);
      cycle(1'b1, mkflit(13'd4, 2'b01), 1'b1, 1'b0, 1'b1, 1'b1, 1'b0);
      cycle(1'b1, mkflit(13'd5, 2'b01), 1'b1, 1'b0, 1'b1, 1'b1, 1'b0);
      if (outstanding_full !== 1'b1) $fatal(1, "expected full after 4 accepts");
      // Outstanding-full counterexample: next in-order seq 6 also blocks both sides.
      blocked = mkflit(13'd6, 2'b01);
      before_up = up_count;
      before_down = down_count;
      cycle(1'b1, blocked, 1'b1, 1'b0, 1'b0, 1'b0, 1'b0);
      if (in_flit !== blocked || in_valid !== 1'b1) $fatal(1, "full beat not held");
      cycle(1'b1, blocked, 1'b1, 1'b0, 1'b0, 1'b0, 1'b0);
      if (up_count != before_up || down_count != before_down) $fatal(1, "accepted while full");
      // Free one slot while idle, then the same held beat accepts.
      cycle(1'b0, blocked, 1'b1, 1'b1, 1'b0, 1'b0, 1'b0);
      cycle(1'b1, blocked, 1'b1, 1'b0, 1'b1, 1'b1, 1'b0);
      if (up_count != before_up + 1 || down_count != before_down + 1) $fatal(1, "did not resume after free");
      if (assigned_vc !== 1'b0) $fatal(1, "assigned_vc wrong");
      if (split_required !== 1'b0) $fatal(1, "split_required wrong");
      if (out_flit[31:0] !== 32'h1234_0006) $fatal(1, "out_flit payload not forwarded %h", out_flit);
      if (up_count != down_count) $fatal(1, "final up/down mismatch up=%0d down=%0d", up_count, down_count);
    end else if (MODE == 2) begin
      // RELAXED (MAX=8): gaps forward; violation only beyond the window.
      cycle(1'b1, mkflit(13'd0, 2'b01), 1'b1, 1'b0, 1'b1, 1'b1, 1'b0);
      // Gap 1 within window: forwards, no violation. Expected becomes 3.
      cycle(1'b1, mkflit(13'd2, 2'b01), 1'b1, 1'b0, 1'b1, 1'b1, 1'b0);
      // Forward gap 9 beyond window: still forwards, flagged. Expected 13.
      cycle(1'b1, mkflit(13'd12, 2'b01), 1'b1, 1'b0, 1'b1, 1'b1, 1'b1);
      // Duplicate behind (2 vs expected 13): wrap-aware gap is large, flagged, forwards.
      cycle(1'b1, mkflit(13'd2, 2'b01), 1'b1, 1'b0, 1'b1, 1'b1, 1'b1);
      // Expected is 3 after last accept; in-order again, no violation.
      cycle(1'b1, mkflit(13'd3, 2'b01), 1'b1, 1'b0, 1'b1, 1'b1, 1'b0);
      // Fill remaining 3 to reach MAX=8, then full blocks both sides.
      cycle(1'b1, mkflit(13'd4, 2'b01), 1'b1, 1'b0, 1'b1, 1'b1, 1'b0);
      cycle(1'b1, mkflit(13'd5, 2'b01), 1'b1, 1'b0, 1'b1, 1'b1, 1'b0);
      cycle(1'b1, mkflit(13'd6, 2'b01), 1'b1, 1'b0, 1'b1, 1'b1, 1'b0);
      if (outstanding_full !== 1'b1) $fatal(1, "relaxed expected full");
      blocked = mkflit(13'd7, 2'b01);
      before_up = up_count;
      before_down = down_count;
      cycle(1'b1, blocked, 1'b1, 1'b0, 1'b0, 1'b0, 1'b0);
      if (up_count != before_up || down_count != before_down) $fatal(1, "relaxed accepted while full");
      cycle(1'b0, blocked, 1'b1, 1'b1, 1'b0, 1'b0, 1'b0);
      cycle(1'b1, blocked, 1'b1, 1'b0, 1'b1, 1'b1, 1'b0);
      if (assigned_vc !== 1'b0) $fatal(1, "assigned_vc wrong");
      if (split_required !== 1'b0) $fatal(1, "split_required wrong");
      if (up_count != down_count) $fatal(1, "relaxed up/down mismatch up=%0d down=%0d", up_count, down_count);
    end else if (MODE == 0) begin
      // RAW: every gap forwards, never a violation, never full (no cap).
      cycle(1'b1, mkflit(13'd5, 2'b01), 1'b1, 1'b0, 1'b1, 1'b1, 1'b0);
      cycle(1'b1, mkflit(13'd0, 2'b01), 1'b1, 1'b0, 1'b1, 1'b1, 1'b0);
      cycle(1'b1, mkflit(13'd1, 2'b01), 1'b1, 1'b0, 1'b1, 1'b1, 1'b0);
      // Blocked downstream (out_ready=0): in_ready=0 so no upstream fire,
      // and downstream fire (out_valid && out_ready) is likewise zero even
      // though out_valid itself stays asserted (valid is ready-independent).
      blocked = mkflit(13'd2, 2'b01);
      before_up = up_count;
      before_down = down_count;
      cycle(1'b1, blocked, 1'b0, 1'b0, 1'b0, 1'b1, 1'b0);
      cycle(1'b1, blocked, 1'b0, 1'b0, 1'b0, 1'b1, 1'b0);
      if (up_count != before_up || down_count != before_down) $fatal(1, "raw accepted while out_ready=0");
      cycle(1'b1, blocked, 1'b1, 1'b0, 1'b1, 1'b1, 1'b0);
      if (outstanding_full !== 1'b0) $fatal(1, "raw must never be full (no cap)");
      if (assigned_vc !== 1'b0) $fatal(1, "assigned_vc wrong");
      if (split_required !== 1'b0) $fatal(1, "split_required wrong");
      if (up_count != down_count) $fatal(1, "raw up/down mismatch");
    end else begin
      $fatal(1, "unknown MODE %0d", MODE);
    end
    $display("TB_PASS up=%0d down=%0d", up_count, down_count);
    $finish;
  end
endmodule
`default_nettype wire
"""


def _tb_source(mode: int) -> str:
    return _TB_TEMPLATE.replace("__MODE__", str(mode))


def _write_case(tmp_path: Path, ordering: str, max_out: int | None, mode: int
                ) -> tuple[Path, Path]:
    work = tmp_path / f"case_{ordering}"
    work.mkdir(parents=True, exist_ok=True)
    dut = work / "ordering_fsm.sv"
    dut.write_text(render_ordering_fsm(_policy(ordering, max_out)))
    tb = work / "tb_ordering_fsm.sv"
    tb.write_text(_tb_source(mode))
    return work, dut


def _run_verilator(work: Path, dut: Path, tb: Path) -> str:
    if shutil.which("verilator") is None:
        pytest.skip("Verilator absent: simulation unavailable")
    build = subprocess.run(
        ["verilator", "--binary", "--timing", "-j", "1", "-Wall", "-Wno-fatal",
         "--top-module", "tb_ordering_fsm", "--Mdir", str(work / "obj"),
         str(dut), str(tb)],
        cwd=work, capture_output=True, text=True, timeout=120,
    )
    log = build.stdout + build.stderr
    assert build.returncode == 0, log
    assert "%Warning" not in log, log
    assert "%Error" not in log, log
    run = subprocess.run(
        [str(work / "obj" / "Vtb_ordering_fsm")],
        cwd=work, capture_output=True, text=True, timeout=30,
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
        cwd=work, capture_output=True, text=True, timeout=30,
    )
    output = run.stdout + run.stderr
    assert run.returncode == 0, output
    assert "TB_PASS" in output, output
    return output


@pytest.mark.parametrize(
    "ordering,max_out,mode",
    [("strong", 4, 1), ("relaxed", 8, 2), ("raw", None, 0)],
)
def test_handshake_tb_verilator(ordering, max_out, mode, tmp_path):
    work, dut = _write_case(tmp_path, ordering, max_out, mode)
    out = _run_verilator(work, dut, work / "tb_ordering_fsm.sv")
    assert "TB_PASS" in out


@pytest.mark.parametrize(
    "ordering,max_out,mode",
    [("strong", 4, 1), ("relaxed", 8, 2), ("raw", None, 0)],
)
def test_handshake_tb_iverilog(ordering, max_out, mode, tmp_path):
    work, dut = _write_case(tmp_path, ordering, max_out, mode)
    out = _run_iverilog(work, dut, work / "tb_ordering_fsm.sv")
    assert "TB_PASS" in out
