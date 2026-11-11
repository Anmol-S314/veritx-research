from __future__ import annotations

import hashlib
import shutil
import subprocess
from pathlib import Path
from types import SimpleNamespace

import pytest

from veritx_dse.model.address_decode import (
    AddressDecodeArtifact, AddressDecodeEntry, AddressTransform,
    UnmatchedAddressPolicy,
)
from veritx_dse.product.addr_decode_rtl import render_addr_decode


def _artifact(entries):
    versions = 4 if any(getattr(e, "selection_policy", None) is not None
                        for e in entries) else 3
    return AddressDecodeArtifact(
        attachment_hash="a" * 64, entries=entries,
        address_transform=AddressTransform.IDENTITY,
        unmatched_address_policy=UnmatchedAddressPolicy.ERROR,
        schema_version=versions)


def _entries():
    return (
        AddressDecodeEntry(name="HBM0", base=0x1000, size=0x1000,
                           target_agent_group=0, target_endpoint_id=0),
        AddressDecodeEntry(name="KV", base=0x8000_0000, size=0x4000,
                           target_agent_group=0, target_endpoint_id=1),
    )


def _pol(agent, rng, r=True, w=True, a=False, inst=None):
    row = dict(agent_idx=agent, address_range=rng, readable=r,
               writable=w, atomic=a)
    if inst is not None:
        row["instance_idx"] = inst
    return SimpleNamespace(**row)


def test_instance_policy_renders_inst_identity_and_declared_timing():
    source = render_addr_decode(_artifact(_entries()), initiator_policies=(
        _pol(0, "HBM0", r=True, w=True),
        _pol(0, "HBM0", r=True, w=False, inst=0),
        _pol(1, "HBM0", r=False, w=True),
        _pol(1, "HBM0", r=False, w=True, inst=0),
        _pol(1, "HBM0", r=False, w=True, inst=1),
    ))
    assert "module addr_decode" in source
    assert "REQ_INST_W" in source
    assert "input  logic" in source and "req_inst" in source
    assert "entry_inst_perm_ok" in source
    assert "PERM_VIOLATION_TIMING_SIDE_CHANNEL_DECLARED" in source
    assert "timing_side_channel_declared" in source
    assert "wire_req_id" in source
    assert "wire_identity_mismatch" in source


def test_instance_hash_diff_vs_group_only():
    group_only = render_addr_decode(_artifact(_entries()), initiator_policies=(
        _pol(0, "HBM0", r=True, w=True),
        _pol(1, "HBM0", r=False, w=True),
    ))
    with_inst = render_addr_decode(_artifact(_entries()), initiator_policies=(
        _pol(0, "HBM0", r=True, w=True),
        _pol(1, "HBM0", r=False, w=True),
        _pol(1, "HBM0", r=False, w=False, inst=0),
    ))
    assert group_only != with_inst
    assert hashlib.sha256(group_only.encode()).hexdigest() != hashlib.sha256(
        with_inst.encode()).hexdigest()
    assert "REQ_INST_W" not in group_only
    assert "wire_req_inst" not in group_only
    assert "perm_violation" in group_only
    assert "timing_side_channel_declared" in group_only


def test_instance_widen_refuses():
    with pytest.raises(ValueError, match="widens"):
        render_addr_decode(_artifact(_entries()), initiator_policies=(
            _pol(0, "HBM0", r=True, w=False),
            _pol(0, "HBM0", r=True, w=True, inst=0),
        ))


def test_instance_without_group_refuses():
    with pytest.raises(ValueError, match="no group policy"):
        render_addr_decode(_artifact(_entries()), initiator_policies=(
            _pol(0, "HBM0", r=True, w=True, inst=0),
            _pol(0, "KV", r=True, w=True),
        ))


def test_instance_duplicate_refuses():
    with pytest.raises(ValueError, match="duplicate initiator"):
        render_addr_decode(_artifact(_entries()), initiator_policies=(
            _pol(0, "HBM0", r=True, w=True),
            _pol(0, "HBM0", r=True, w=False, inst=0),
            _pol(0, "HBM0", r=True, w=True, inst=0),
        ))


_TB = r"""`timescale 1ns/1ps
module tb;
  logic [63:0] addr;
  logic [1:0] req_id;
  logic req_write;
  logic [1:0] req_inst;
  logic [1:0] wire_req_id;
  logic [1:0] wire_req_inst;
  logic [15:0] burst_len;
  logic [1:0] target_oh;
  logic hit, miss, overlap, allow, perm_violation, burst_violation;
  logic wire_identity_mismatch;
  logic timing_side_channel_declared;
  addr_decode dut(
    .addr(addr), .req_id(req_id), .req_write(req_write),
    .req_inst(req_inst), .wire_req_id(wire_req_id),
    .wire_req_inst(wire_req_inst), .burst_len(burst_len),
    .target_oh(target_oh), .hit(hit), .miss(miss), .overlap(overlap),
    .allow(allow), .perm_violation(perm_violation),
    .wire_identity_mismatch(wire_identity_mismatch),
    .timing_side_channel_declared(timing_side_channel_declared),
    .burst_violation(burst_violation));
  integer errors;
  integer test_no;
  task automatic check(input logic exp_allow, input logic exp_perm, input logic exp_mismatch, input logic [1:0] exp_target);
    begin
      if (allow !== exp_allow) begin $display("FAIL t%0d allow exp %b got %b", test_no, exp_allow, allow); errors = errors + 1; end
      if (perm_violation !== exp_perm) begin $display("FAIL t%0d perm exp %b got %b", test_no, exp_perm, perm_violation); errors = errors + 1; end
      if (wire_identity_mismatch !== exp_mismatch) begin $display("FAIL t%0d mismatch exp %b got %b", test_no, exp_mismatch, wire_identity_mismatch); errors = errors + 1; end
      if (target_oh !== exp_target) begin $display("FAIL t%0d target exp %b got %b", test_no, exp_target, target_oh); errors = errors + 1; end
      if (timing_side_channel_declared !== 1'b1) begin $display("FAIL t%0d side-channel declared", test_no); errors = errors + 1; end
    end
  endtask
  initial begin
    errors = 0;
    test_no = 0;
    addr = 64'h1000;
    test_no = 1;
    req_id = 2'd0; req_inst = 2'd1; req_write = 1'b1; burst_len = 16'd0;
    wire_req_id = 2'd0; wire_req_inst = 2'd1;
    #10;
    check(1'b1, 1'b0, 1'b0, 2'b01);
    test_no = 2;
    req_inst = 2'd0;
    wire_req_inst = 2'd0;
    #10;
    check(1'b0, 1'b1, 1'b0, 2'b00);
    test_no = 3;
    req_write = 1'b0;
    #10;
    check(1'b1, 1'b0, 1'b0, 2'b01);
    test_no = 4;
    wire_req_id = 2'd1;
    wire_req_inst = 2'd0;
    #10;
    check(1'b1, 1'b0, 1'b1, 2'b01);
    test_no = 5;
    req_write = 1'b1;
    wire_req_id = 2'd0;
    #10;
    check(1'b0, 1'b1, 1'b0, 2'b00);
    if (errors == 0) $display("TB_PASS %0d", test_no);
    else $display("TB_FAIL %0d", errors);
  end
endmodule
"""


def _simulate(tmp_path: Path, source: str, tb: str) -> str:
    (tmp_path / "addr_decode.sv").write_text(source)
    (tmp_path / "tb.sv").write_text(tb)
    sim = tmp_path / "sim.vvp"
    c = subprocess.run(
        ["iverilog", "-g2012", "-o", str(sim),
         str(tmp_path / "addr_decode.sv"), str(tmp_path / "tb.sv")],
        capture_output=True, text=True, timeout=30)
    assert c.returncode == 0, c.stdout + c.stderr
    r = subprocess.run(["vvp", str(sim)], capture_output=True, text=True, timeout=10)
    assert r.returncode == 0, r.stdout + r.stderr
    return r.stdout


def test_tb_instance_and_wire_spoof(tmp_path):
    if shutil.which("iverilog") is None:
        pytest.skip("iverilog not installed; cannot run HDL testbench")
    source = render_addr_decode(_artifact(_entries()), initiator_policies=(
        _pol(0, "HBM0", r=True, w=True),
        _pol(0, "HBM0", r=True, w=False, inst=0),
        _pol(1, "HBM0", r=False, w=True),
        _pol(1, "HBM0", r=False, w=True, inst=1),
    ))
    assert "REQ_INST_W" in source
    out = _simulate(tmp_path, source, _TB)
    assert "TB_PASS" in out, out


def test_instance_decoder_lints_clean(tmp_path):
    if shutil.which("verilator") is None:
        pytest.skip("verilator not installed; cannot lint the decoder")
    source = render_addr_decode(_artifact(_entries()), initiator_policies=(
        _pol(0, "HBM0", r=True, w=True),
        _pol(0, "HBM0", r=True, w=False, inst=0),
        _pol(1, "HBM0", r=False, w=True),
        _pol(1, "HBM0", r=False, w=True, inst=1),
    ))
    path = tmp_path / "addr_decode.sv"
    path.write_text(source)
    checked = subprocess.run(
        ["verilator", "--lint-only", "-sv", "-Wall", "-Wno-fatal",
         "--top-module", "addr_decode", "addr_decode.sv"],
        cwd=tmp_path, capture_output=True, text=True)
    log = checked.stdout + checked.stderr
    assert checked.returncode == 0, log
    assert "%Warning" not in log, log
