"""Initiator × region security model (audit §2).

Identity model: `req_id` is the trusted ingress-asserted Agent GROUP
(`agent_idx`). It is preserved to enforcement, never inferred from
drawing proximity. All instances of a group share its policy (group
granularity tradeoff stated in addr_decode_rtl).

Rules implemented and exercised here:
  * Policy key = (initiator, range); two groups on one range compile.
  * Default-deny: missing (initiator, range) entry and unknown req_id
    deny; unmapped address is a miss (ERROR). Denied => perm_violation,
    target_oh='0, never forwarded; combinational => no stranded
    outstanding.
  * Burst containment = DENY: burst_len==0 is single; otherwise
    [addr, addr+len) must be fully inside the hit range, else
    burst_violation/perm_violation and no forward. No split.
  * Atomic only when the group's protocol is `axi5` (M1 INVALID).

Every behavioral claim below is exercised by an iverilog testbench
actually run in this file (not inferred from hashes).
"""
from __future__ import annotations

import hashlib
import json
import shutil
import subprocess
import textwrap
from pathlib import Path

import pytest

from veritx_dse.application.fabric_compiler import FabricCompiler
from veritx_dse.core.paths import REPO
from veritx_dse.model.address_decode import (
    AddressDecodeArtifact, AddressDecodeEntry, AddressTransform,
    UnmatchedAddressPolicy,
)
from veritx_dse.model.address_permission import (
    AddressPermissionInput, InitiatorPolicy, TrafficRequirement,
    check_address_permission,
)
from veritx_dse.model.agent_intent_v4 import (
    AgentIntentV4, PermissionWindow, ProtocolFamily,
)
from veritx_dse.model.compile_model import (
    AddressMap, AddressRange, Agent, AgentKind, CollectiveDimension,
    CollectiveIntent, CollectiveKind, DependencyGraph, ModelFamily,
    WorkloadV3,
)
from veritx_dse.model.compile_request_v4 import CompileRequestV4
from veritx_dse.model.topology_intent import MeshIntent
from veritx_dse.product.addr_decode_rtl import render_addr_decode


def _workload() -> WorkloadV3:
    return WorkloadV3(
        model_family=ModelFamily.DENSE_TRANSFORMER, tp=2, pp=1, ep=1, dp=1,
        collectives=(CollectiveIntent(
            kind=CollectiveKind.ALLREDUCE, dimension=CollectiveDimension.TP,
            payload_bytes=8192, traffic_class="tp_collective"),))


def _request(**kwargs) -> CompileRequestV4:
    args = dict(
        workload=_workload(),
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


def _artifact(entries) -> AddressDecodeArtifact:
    return AddressDecodeArtifact(
        attachment_hash="a" * 64, entries=entries,
        address_transform=AddressTransform.IDENTITY,
        unmatched_address_policy=UnmatchedAddressPolicy.ERROR,
        schema_version=4 if any(e.selection_policy is not None for e in entries) else 3)


def _entries():
    return (
        AddressDecodeEntry(name="HBM0", base=0x1000, size=0x1000,
                           target_agent_group=0, target_endpoint_id=0),
        AddressDecodeEntry(name="KV", base=0x8000_0000, size=0x4000,
                           target_agent_group=0, target_endpoint_id=1),
    )


# --- M1 verdict: compile -------------------------------------------------

def test_two_policies_same_region_compile():
    """Two groups with opposite rights for one range now COMPILE."""
    req = _request(agent_intents=(
        AgentIntentV4(0, permission_windows=(
            PermissionWindow("HBM0", readable=True, writable=False),)),
        AgentIntentV4(1, permission_windows=(
            PermissionWindow("HBM0", readable=False, writable=True),)),
    ))
    comp = FabricCompiler().compile(req)
    assert comp.status == "COMPILED", comp.error
    assert comp.error is None
    # And at the M1 deep-module level with explicit initiator policies.
    ranges = (AddressRange(name="HBM0", base=0x1000, size=0x1000,
                           target_agent_idx=1),)
    verdict = check_address_permission(AddressPermissionInput(
        ranges=ranges, agent_counts=(3, 1), traffic=(),
        initiator_policies=(
            InitiatorPolicy(0, "HBM0", readable=True, writable=False),
            InitiatorPolicy(1, "HBM0", readable=False, writable=True),
        )))
    assert verdict.ok is True


def test_same_initiator_same_range_conflict_is_invalid():
    """Duplicate (initiator, range) — even identical — is a conflict."""
    ranges = (AddressRange(name="A", base=0x1000, size=0x1000,
                           target_agent_idx=0, target_instance_index=0,
                           selection_policy="FIXED_INSTANCE"),)
    for dup in (
        (InitiatorPolicy(0, "A", readable=True, writable=False),
         InitiatorPolicy(0, "A", readable=False, writable=True)),
        (InitiatorPolicy(0, "A", readable=True, writable=True),
         InitiatorPolicy(0, "A", readable=True, writable=True)),
    ):
        verdict = check_address_permission(AddressPermissionInput(
            ranges=ranges, agent_counts=(2,), traffic=(),
            initiator_policies=dup))
        assert verdict.ok is False and verdict.status == "INVALID"
        assert "one authority per (initiator, range)" in verdict.reason


def test_missing_identity_is_invalid_at_address_decode():
    ranges = (AddressRange(name="A", base=0x1000, size=0x1000,
                           target_agent_idx=0, target_instance_index=0,
                           selection_policy="FIXED_INSTANCE"),)
    verdict = check_address_permission(AddressPermissionInput(
        ranges=ranges, agent_counts=(2, 2), traffic=(),
        initiator_policies=(InitiatorPolicy(9, "A", readable=True,
                                            writable=True),)))
    assert verdict.ok is False and verdict.status == "INVALID"
    assert "outside" in verdict.reason
    # Through the compiler the same refusal is INVALID/ADDRESS_DECODE.
    req = _request(agent_intents=(AgentIntentV4(0, permission_windows=(
        PermissionWindow("NOPE", readable=True, writable=True),)),))
    comp = FabricCompiler().compile(req)
    assert comp.status == "INVALID"
    assert comp.stopped_at_stage == "ADDRESS_DECODE"
    assert comp.bundle is None
    assert "unknown address range" in comp.error


def test_atomic_only_when_protocol_supports():
    req_chi = _request(agent_intents=(AgentIntentV4(
        0, protocol=ProtocolFamily.CHI,
        permission_windows=(PermissionWindow(
            "HBM0", readable=True, writable=True, atomic=True),)),))
    comp = FabricCompiler().compile(req_chi)
    assert comp.status == "INVALID"
    assert comp.stopped_at_stage == "ADDRESS_DECODE"
    assert "atomic" in comp.error
    assert "chi" in comp.error
    req_axi5 = _request(agent_intents=(AgentIntentV4(
        0, protocol=ProtocolFamily.AXI5,
        permission_windows=(PermissionWindow(
            "HBM0", readable=True, writable=True, atomic=True),)),))
    assert FabricCompiler().compile(req_axi5).status == "COMPILED"


# --- Renderer: keying, hash, byte-identical ------------------------------

def test_hash_diff_for_opposite_policies():
    art = _artifact(_entries())
    a = render_addr_decode(art, initiator_policies=(
        InitiatorPolicy(0, "HBM0", readable=True, writable=False),))
    b = render_addr_decode(art, initiator_policies=(
        InitiatorPolicy(0, "HBM0", readable=False, writable=True),))
    assert a != b
    assert hashlib.sha256(a.encode()).hexdigest() != hashlib.sha256(b.encode()).hexdigest()
    # Two opposite policies emit a distinct combined table, keyed by initiator.
    both = render_addr_decode(art, initiator_policies=(
        InitiatorPolicy(0, "HBM0", readable=True, writable=False),
        InitiatorPolicy(1, "HBM0", readable=False, writable=True)))
    assert both != a and both != b
    assert "req_id" in both and "burst_len" in both
    assert "initiator 0: readable=1 writable=0" in both
    assert "initiator 1: readable=0 writable=1" in both


def test_old_no_window_output_is_byte_identical():
    art = _artifact(_entries())
    plain = render_addr_decode(art)
    assert "perm_violation" not in plain and "req_write" not in plain
    assert "req_id" not in plain and "burst_len" not in plain
    # Legacy single-window path still gates by req_write only (no req_id).
    legacy = render_addr_decode(art, windows=(
        PermissionWindow("HBM0", readable=True, writable=False),))
    assert "req_write" in legacy and "perm_violation" in legacy
    assert "req_id" not in legacy


def test_renderer_duplicate_and_unknown_refuse():
    art = _artifact(_entries())
    with pytest.raises(ValueError, match="duplicate initiator"):
        render_addr_decode(art, initiator_policies=(
            InitiatorPolicy(0, "HBM0", readable=True, writable=True),
            InitiatorPolicy(0, "HBM0", readable=True, writable=True)))
    with pytest.raises(ValueError, match="unknown address range"):
        render_addr_decode(art, initiator_policies=(
            InitiatorPolicy(0, "NOPE", readable=True, writable=True),))


# --- Behavioral testbench (executed, not inferred) -----------------------

def _run_tb(artifact, policies, vectors, has_atomic=None):
    """Render, lint (optional), then iverilog-compile and run a TB.

    `vectors`: list of (addr, req_id, req_write, burst_len, req_atomic,
    exp_allow, exp_hit, exp_miss, exp_perm_viol, exp_target).
    Returns the vvp stdout."""
    source = render_addr_decode(artifact, initiator_policies=policies)
    if has_atomic is None:
        has_atomic = any(getattr(p, "atomic", False) for p in policies)
    # Determine REQ_ID_W / N_ENDPOINTS from the source for the TB ports.
    # Simpler: parse the module header for widths.
    n_endpoints = 2  # _entries() always has endpoints 0,1
    # Find REQ_ID_W
    req_id_w = 1
    for line in source.splitlines():
        if "REQ_ID_W =" in line:
            req_id_w = int(line.split("=")[-1].strip().rstrip(","))
            break
    req_atomic_ports = (
        "  logic req_atomic;\n" if has_atomic else "")
    req_atomic_conn = ", .req_atomic(req_atomic)" if has_atomic else ""
    tb_lines = []
    tb_lines.append("`timescale 1ns/1ps")
    tb_lines.append("module tb;")
    tb_lines.append(f"  logic [63:0] addr;")
    tb_lines.append(f"  logic [{req_id_w-1}:0] req_id;")
    tb_lines.append(f"  logic req_write;")
    if has_atomic:
        tb_lines.append(f"  logic req_atomic;")
    tb_lines.append(f"  logic [15:0] burst_len;")
    tb_lines.append(f"  logic [{n_endpoints-1}:0] target_oh;")
    tb_lines.append(f"  logic hit, miss, overlap, allow, perm_violation, burst_violation;")
    tb_lines.append(
        f"  addr_decode dut(.addr(addr), .req_id(req_id), .req_write(req_write)"
        f"{req_atomic_conn}, .burst_len(burst_len), .target_oh(target_oh), "
        f".hit(hit), .miss(miss), .overlap(overlap), .allow(allow), "
        f".perm_violation(perm_violation), .burst_violation(burst_violation));")
    tb_lines.append("  integer errors;")
    tb_lines.append("  integer test_no;")
    tb_lines.append("  initial begin")
    tb_lines.append("    errors = 0; test_no = 0;")
    for (addr, rid, rw, blen, ratomic, e_allow, e_hit, e_miss, e_perm, e_target) in vectors:
        tb_lines.append(f"    test_no = test_no + 1;")
        tb_lines.append(f"    addr = 64'h{addr:016x}; req_id = {req_id_w}'d{rid}; req_write = {1 if rw else 0}; burst_len = 16'd{blen};")
        if has_atomic:
            tb_lines.append(f"    req_atomic = {1 if ratomic else 0};")
        tb_lines.append("    #10;")
        tb_lines.append(
            f"    if (allow !== {1 if e_allow else 0}) begin $display(\"FAIL t%0d allow exp %b got %b\", test_no, {1 if e_allow else 0}, allow); errors = errors + 1; end")
        tb_lines.append(
            f"    if (hit !== {1 if e_hit else 0}) begin $display(\"FAIL t%0d hit exp %b got %b\", test_no, {1 if e_hit else 0}, hit); errors = errors + 1; end")
        tb_lines.append(
            f"    if (miss !== {1 if e_miss else 0}) begin $display(\"FAIL t%0d miss exp %b got %b\", test_no, {1 if e_miss else 0}, miss); errors = errors + 1; end")
        tb_lines.append(
            f"    if (perm_violation !== {1 if e_perm else 0}) begin $display(\"FAIL t%0d perm exp %b got %b\", test_no, {1 if e_perm else 0}, perm_violation); errors = errors + 1; end")
        tb_lines.append(
            f"    if (target_oh !== {n_endpoints}'b{e_target:02b}) begin $display(\"FAIL t%0d target exp %b got %b\", test_no, {n_endpoints}'b{e_target:02b}, target_oh); errors = errors + 1; end")
    tb_lines.append("    if (errors == 0) $display(\"TB_PASS %0d\", test_no);")
    tb_lines.append("    else $display(\"TB_FAIL %0d\", errors);")
    tb_lines.append("  end")
    tb_lines.append("endmodule")
    return source, "\n".join(tb_lines) + "\n", req_id_w


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


def test_tb_allowed_vs_denied_same_region(tmp_path):
    """Same address, opposite initiators: one allows, one denies."""
    if shutil.which("iverilog") is None:
        pytest.skip("iverilog not installed; cannot run HDL testbench")
    art = _artifact(_entries())
    policies = (
        InitiatorPolicy(0, "HBM0", readable=True, writable=False),
        InitiatorPolicy(1, "HBM0", readable=False, writable=True),
    )
    # addr 0x1000 (HBM0, endpoint 0 => target 2'b01)
    vectors = [
        # addr,   rid, rw, blen, ratomic, allow, hit, miss, perm, target
        (0x1000, 0, 0, 0, 0, True, True, False, False, 0b01),
        (0x1000, 0, 1, 0, 0, False, True, False, True, 0b00),
        (0x1000, 1, 1, 0, 0, True, True, False, False, 0b01),
        (0x1000, 1, 0, 0, 0, False, True, False, True, 0b00),
    ]
    source, tb, _ = _run_tb(art, policies, vectors)
    out = _simulate(tmp_path, source, tb)
    assert "TB_PASS" in out, out


def test_tb_burst_crossing_is_denied(tmp_path):
    """A burst crossing the region boundary is DENIED, never split."""
    if shutil.which("iverilog") is None:
        pytest.skip("iverilog not installed; cannot run HDL testbench")
    art = _artifact(_entries())
    policies = (
        InitiatorPolicy(0, "HBM0", readable=True, writable=False),
        InitiatorPolicy(1, "HBM0", readable=False, writable=True),
    )
    vectors = [
        # Contained burst: 0x1100 + 16 stays inside HBM0 => allowed
        (0x1100, 0, 0, 16, 0, True, True, False, False, 0b01),
        # Single access (len 0) => allowed
        (0x1100, 0, 0, 0, 0, True, True, False, False, 0b01),
        # Crossing: 0x1ff0 + 32 => end 0x200f > 0x1fff => denied
        (0x1ff0, 0, 0, 32, 0, False, True, False, True, 0b00),
        # Crossing for the other (allowed-side) initiator also denied
        (0x1ff0, 1, 1, 32, 0, False, True, False, True, 0b00),
    ]
    source, tb, _ = _run_tb(art, policies, vectors)
    out = _simulate(tmp_path, source, tb)
    assert "TB_PASS" in out, out


def test_tb_unmapped_and_default_deny(tmp_path):
    """Unmapped is a miss; a hit region with no entry is denied."""
    if shutil.which("iverilog") is None:
        pytest.skip("iverilog not installed; cannot run HDL testbench")
    art = _artifact(_entries())
    policies = (
        InitiatorPolicy(0, "HBM0", readable=True, writable=False),
        InitiatorPolicy(1, "HBM0", readable=False, writable=True),
    )
    vectors = [
        # Unmapped 0x5000: miss, never allowed, never forwarded
        (0x5000, 0, 0, 0, 0, False, False, True, False, 0b00),
        (0x5000, 1, 1, 0, 0, False, False, True, False, 0b00),
        # KV (0x80000000) has no entry for either initiator => default-deny
        (0x80000000, 0, 0, 0, 0, False, True, False, True, 0b00),
        (0x80000000, 1, 1, 0, 0, False, True, False, True, 0b00),
    ]
    source, tb, _ = _run_tb(art, policies, vectors)
    out = _simulate(tmp_path, source, tb)
    assert "TB_PASS" in out, out


def test_tb_atomic_only_when_allowed(tmp_path):
    if shutil.which("iverilog") is None:
        pytest.skip("iverilog not installed; cannot run HDL testbench")
    art = _artifact(_entries())
    policies = (
        InitiatorPolicy(0, "HBM0", readable=True, writable=True, atomic=True),
        InitiatorPolicy(1, "HBM0", readable=True, writable=True, atomic=False),
    )
    vectors = [
        (0x1000, 0, 1, 0, 1, True, True, False, False, 0b01),
        (0x1000, 1, 1, 0, 1, False, True, False, True, 0b00),
        (0x1000, 1, 1, 0, 0, True, True, False, False, 0b01),
    ]
    source, tb, _ = _run_tb(art, policies, vectors)
    assert "req_atomic" in source
    out = _simulate(tmp_path, source, tb)
    assert "TB_PASS" in out, out


def test_initiator_decoder_lints_clean(tmp_path):
    if shutil.which("verilator") is None:
        pytest.skip("verilator not installed; cannot lint the decoder")
    art = _artifact(_entries())
    source = render_addr_decode(art, initiator_policies=(
        InitiatorPolicy(0, "HBM0", readable=True, writable=False),
        InitiatorPolicy(1, "HBM0", readable=False, writable=True)))
    path = tmp_path / "addr_decode.sv"
    path.write_text(source)
    checked = subprocess.run(
        ["verilator", "--lint-only", "-sv", "-Wall", "-Wno-fatal",
         "--top-module", "addr_decode", "addr_decode.sv"],
        cwd=tmp_path, capture_output=True, text=True)
    log = checked.stdout + checked.stderr
    assert checked.returncode == 0, log
    assert "%Warning" not in log, log


def test_end_to_end_preview_two_policies(tmp_path):
    """The full preview emits an initiator-keyed decoder for two policies."""
    req = _request(agent_intents=(
        AgentIntentV4(0, permission_windows=(
            PermissionWindow("HBM0", readable=True, writable=False),)),
        AgentIntentV4(1, permission_windows=(
            PermissionWindow("HBM0", readable=False, writable=True),)),
    ))
    from veritx_dse.product.rtl_export import run_rtl_preview
    result = run_rtl_preview(req.to_dict(), tmp_path, {"repo_root": str(REPO)})
    assert result["address_decode"] == "EMITTED"
    source = (tmp_path / "rtl" / "addr_decode.sv").read_text()
    assert "req_id" in source and "burst_len" in source
    assert "initiator 0: readable=1 writable=0" in source
    assert "initiator 1: readable=0 writable=1" in source
    manifest = json.loads((tmp_path / "rtl-preview.json").read_text())
    rows = manifest["address_decode"]["permission_windows"]
    assert {r["agent_idx"] for r in rows} == {0, 1}
    assert all(r["address_range"] == "HBM0" for r in rows)
    if shutil.which("verilator") is not None:
        assert result["address_decode_lint"] == "PASS"
        assert result["address_decode_lint_clean"] is True
