"""STAGE 1 compiler refusals + verdict wiring + RTL realization (M1/M3/M4).

Every refusal names an owner stage (stopped_at_stage) and carries the M1–M4
verdicts on the Compilation. M1 permission windows are realized in the
emitted ``addr_decode.sv`` (functional: content differs on window change,
Verilator lint clean); M3 crossings compile when every named point is
covered by a CdcCell; M4 axi5 adapters are realized by AdapterFactory.
M2 ordering/VC-reassignment demands and chi/tilelink/custom adapters (no
repo wrapper) fail closed at emission with the typed
``UNSUPPORTED_STAGE1_REALIZATION`` code — never a silent pass.
"""
from __future__ import annotations

import json
import shutil
import subprocess
from dataclasses import replace
from pathlib import Path

import pytest

from veritx_dse.application.fabric_compiler import FabricCompiler
from veritx_dse.core.paths import REPO
from veritx_dse.model.address_decode import (
    AddressDecodeArtifact, AddressDecodeEntry, AddressTransform,
    UnmatchedAddressPolicy,
)
from veritx_dse.model.agent_intent_v4 import (
    AgentIntentV4, OrderingMode, PermissionWindow, ProtocolFamily,
    TrafficClassVC, TrafficPolicyV4,
)
from veritx_dse.model.compile_model import (
    AddressMap, AddressRange, Agent, AgentKind, CollectiveDimension,
    CollectiveIntent, CollectiveKind, DependencyGraph, ModelFamily,
    TrafficProfile, WorkloadV3,
)
from veritx_dse.model.compile_request_v4 import CompileRequestV4
from veritx_dse.model.topology_intent import MeshIntent
from veritx_dse.product.addr_decode_rtl import render_addr_decode
from veritx_dse.product.catalog_evaluation import (
    RTL_UNSUPPORTED_STAGE1_REALIZATION, rtl_support,
)
from veritx_dse.product.rtl_export import run_rtl_preview


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


def _compile(request) -> object:
    return FabricCompiler().compile(request)


def test_clean_request_compiles_with_four_ok_verdicts():
    compilation = _compile(_request())
    assert compilation.status == "COMPILED"
    assert compilation.error is None
    assert [v["module"] for v in compilation.stage1_verdicts] == [
        "address_permission", "ordering_vc",
        "clock_power_cdc", "protocol_adapter"]
    assert all(v["ok"] for v in compilation.stage1_verdicts)
    unowned = [f for f in compilation.findings if "AGENT_PROTOCOL_UNOWNED" in f]
    assert len(unowned) == 1
    assert not any("AGENT_PROTOCOL_UNOWNED" not in f for f in compilation.findings)


def test_permission_mismatch_is_invalid_at_address_decode():
    workload = replace(_request().workload, traffic_profiles=(
        TrafficProfile(src_rank=0, dst_rank=1, traffic_class="write",
                       payload_bytes=64),))
    compilation = _compile(_request(
        workload=workload,
        agent_intents=(AgentIntentV4(1, permission_windows=(
            PermissionWindow("HBM0", readable=True, writable=False),)),)))
    assert compilation.status == "INVALID"
    assert compilation.stopped_at_stage == "ADDRESS_DECODE"
    assert compilation.bundle is None
    assert "read-only" in compilation.error
    failing = [v for v in compilation.stage1_verdicts if not v["ok"]]
    assert len(failing) == 1
    assert failing[0]["module"] == "address_permission"


def test_vc_mismatch_is_invalid_at_vc():
    compilation = _compile(_request(traffic_policy=TrafficPolicyV4(
        traffic_class_vcs=(TrafficClassVC("tp_collective", 3),))))
    assert compilation.status == "INVALID"
    assert compilation.stopped_at_stage == "VC"
    assert "only 1 VC" in compilation.error


def test_unknown_desired_class_is_invalid_at_vc():
    compilation = _compile(_request(traffic_policy=TrafficPolicyV4(
        traffic_class_vcs=(TrafficClassVC("nope", 0),))))
    assert compilation.status == "INVALID"
    assert compilation.stopped_at_stage == "VC"
    assert "not in the derived assignment" in compilation.error


def test_split_at_on_chi_is_invalid_at_packet_format():
    compilation = _compile(_request(agent_intents=(
        AgentIntentV4(0, protocol=ProtocolFamily.CHI, split_at=64),)))
    assert compilation.status == "INVALID"
    assert compilation.stopped_at_stage == "PACKET_FORMAT"
    assert "only axi5" in compilation.error


def test_intent_domain_mismatch_is_invalid_at_attachment():
    compilation = _compile(_request(agent_intents=(
        AgentIntentV4(0, clock_domain="other_clk"),)))
    assert compilation.status == "INVALID"
    assert compilation.stopped_at_stage == "ATTACHMENT"
    assert "must exist and equal" in compilation.error


def test_multi_clock_compiles_with_named_cdc_points_covered():
    # M3 CdcCell: a multi-domain fabric compiles when every named crossing
    # gets a cell; the missing-cell refusal fires at the M3 gate itself
    # (see test_stage3_cdc_adapters::test_missing_cell_is_compile_refusal).
    compilation = _compile(_request(agents=(
        Agent(kind=AgentKind.COMPUTE_TILE, count=3, clock_domain="a"),
        Agent(kind=AgentKind.HBM_CONTROLLER, count=1, clock_domain="b"))))
    assert compilation.status == "COMPILED", compilation.error
    assert compilation.bundle is not None
    assert any("group0(a)" in finding and "group1(b)" in finding
               for finding in compilation.findings)
    m3 = next(v for v in compilation.stage1_verdicts
              if v["module"] == "clock_power_cdc")
    assert m3["ok"] is True


def test_overlap_names_both_ranges_at_address_decode():
    compilation = _compile(_request(address_map=AddressMap(ranges=(
        AddressRange(name="A", base=0x1000, size=0x2000, target_agent_idx=0,
                     target_instance_index=0, selection_policy="FIXED_INSTANCE"),
        AddressRange(name="B", base=0x2000, size=0x1000, target_agent_idx=0,
                     target_instance_index=0, selection_policy="FIXED_INSTANCE")))))
    assert compilation.status == "INVALID"
    assert compilation.stopped_at_stage == "ADDRESS_DECODE"
    assert "'A'" in compilation.error and "'B'" in compilation.error


def test_multi_instance_range_without_policy_is_invalid():
    compilation = _compile(_request(address_map=AddressMap(ranges=(
        AddressRange(name="A", base=0x1000, size=0x1000,
                     target_agent_idx=0),))))
    assert compilation.status == "INVALID"
    assert compilation.stopped_at_stage == "ADDRESS_DECODE"
    assert "FIXED_INSTANCE or STRIPED" in compilation.error


def test_max_outstanding_without_ordering_warns_but_compiles():
    compilation = _compile(_request(agent_intents=(
        AgentIntentV4(0, max_outstanding=16),)))
    assert compilation.status == "COMPILED"
    assert any("no ordering promise is invented" in finding
               for finding in compilation.findings)


# --- M1 realized in RTL (functional) --------------------------------------

def _artifact() -> AddressDecodeArtifact:
    return AddressDecodeArtifact(
        attachment_hash="a" * 64,
        entries=(
            AddressDecodeEntry(name="HBM0", base=0x1000, size=0x1000,
                               target_agent_group=0, target_endpoint_id=0),
            AddressDecodeEntry(name="KV", base=0x8000_0000, size=0x4000,
                               target_agent_group=0, target_endpoint_id=1),
        ),
        address_transform=AddressTransform.IDENTITY,
        unmatched_address_policy=UnmatchedAddressPolicy.ERROR,
        schema_version=3)


def test_permission_windows_change_the_emitted_verilog():
    artifact = _artifact()
    plain = render_addr_decode(artifact)
    readonly = render_addr_decode(artifact, windows=(
        PermissionWindow("HBM0", readable=True, writable=False),))
    writeonly = render_addr_decode(artifact, windows=(
        PermissionWindow("HBM0", readable=False, writable=True),))
    assert readonly != plain and writeonly != plain and readonly != writeonly
    # Byte-identical historical output without windows (compat).
    assert "perm_violation" not in plain and "req_write" not in plain
    # The gate itself: req_write selects the denied side; target_oh is
    # suppressed on denial; unwindowed entries stay fully allowed.
    assert "input  logic                   req_write," in readonly
    assert "assign entry_allow[0] = entry_hit[0] && (req_write ? 1'b0 : 1'b1);" in readonly
    assert "assign entry_allow[1] = entry_hit[1];" in readonly
    assert "if (entry_allow[0]) begin" in readonly
    assert "if (entry_allow[1]) begin" in readonly  # unwindowed: allow==hit
    assert "entry_hit[1]" in readonly and "if (entry_hit[1])" not in readonly
    assert "assign perm_violation = hit && !allow;" in readonly
    assert "req_write ? 1'b1 : 1'b0" in writeonly
    # Fail closed at emission too: a window naming no range refuses.
    with pytest.raises(ValueError, match="unknown address range"):
        render_addr_decode(artifact, windows=(PermissionWindow("NOPE"),))


def test_gated_decoder_lints_clean(tmp_path):
    if shutil.which("verilator") is None:
        pytest.skip("verilator not installed; cannot lint the decoder")
    source = render_addr_decode(_artifact(), windows=(
        PermissionWindow("HBM0", readable=True, writable=False),))
    path = tmp_path / "addr_decode.sv"
    path.write_text(source)
    checked = subprocess.run(
        ["verilator", "--lint-only", "-sv", "-Wall", "-Wno-fatal",
         "--top-module", "addr_decode", "addr_decode.sv"],
        cwd=tmp_path, capture_output=True, text=True)
    log = checked.stdout + checked.stderr
    assert checked.returncode == 0, log
    assert "%Warning" not in log, log


def test_permission_windows_realized_end_to_end_in_the_preview(tmp_path):
    request = _request(agent_intents=(AgentIntentV4(1, permission_windows=(
        PermissionWindow("HBM0", readable=True, writable=False),)),))
    result = run_rtl_preview(request.to_dict(), tmp_path,
                             {"repo_root": str(REPO)})
    assert result["address_decode"] == "EMITTED"
    source = (tmp_path / "rtl" / "addr_decode.sv").read_text()
    assert "perm_violation" in source
    assert "req_write" in source
    if shutil.which("verilator") is not None:
        assert result["address_decode_lint"] == "PASS"
        assert result["address_decode_lint_clean"] is True
    manifest = json.loads((tmp_path / "rtl-preview.json").read_text())
    assert manifest["address_decode"]["permission_realization"] == "ADDR_DECODE_GATE"
    assert manifest["address_decode"]["permission_windows"] == [
        {"agent_idx": 1, "address_range": "HBM0", "readable": True,
         "writable": False, "atomic": False}]
    assert [v["module"] for v in manifest["stage1_verdicts"]] == [
        "address_permission", "ordering_vc",
        "clock_power_cdc", "protocol_adapter"]
    # The manifest names what the preview still does not realize (no silent pass).
    assert any("permission" in line for line in manifest["limitations"])


# --- M2–M4 fail closed at emission (no silent pass) ------------------------

def test_axi5_intent_is_realized_by_the_adapter_factory(tmp_path):
    request = _request(agent_intents=(
        AgentIntentV4(0, protocol=ProtocolFamily.AXI5, split_at=64,
                      max_outstanding=16),))
    assert _compile(request).status == "COMPILED"  # intent is legal
    from veritx_dse.application.views import topology_view
    compilation = _compile(request)
    assert rtl_support(request, topology_view(compilation)).supported is True
    result = run_rtl_preview(request.to_dict(), tmp_path,
                             {"repo_root": str(REPO)})
    assert result["adapters"] == "EMITTED"
    assert result["adapter_count"] == 1
    assert result["final_implementation"] is False
    source = (tmp_path / "rtl" / "adapter_axi5_g0.sv").read_text()
    assert "SPLIT_AT = 64" in source
    manifest = json.loads((tmp_path / "rtl-preview.json").read_text())
    assert manifest["adapters"]["adapters"][0]["module"] == "adapter_axi5_g0"
    assert manifest["adapters"]["adapters"][0]["sha256"]
    if shutil.which("verilator") is not None:
        row = manifest["adapters"]["adapters"][0]
        assert row["lint"]["status"] == "PASS" and row["lint"]["clean"] is True


def test_chi_intent_is_realized_at_emission(tmp_path):
    request = _request(agent_intents=(
        AgentIntentV4(0, protocol=ProtocolFamily.CHI),))
    assert _compile(request).status == "COMPILED"  # intent is legal
    from veritx_dse.application.views import topology_view
    support = rtl_support(request, topology_view(_compile(request)))
    assert support.supported is True, support.reason
    result = run_rtl_preview(request.to_dict(), tmp_path,
                             {"repo_root": str(REPO)})
    assert result["adapters"] == "EMITTED"
    assert result["adapter_count"] == 1
    assert result["final_implementation"] is False
    assert (tmp_path / "rtl" / "adapter_chi_g0.sv").is_file()
    manifest = json.loads((tmp_path / "rtl-preview.json").read_text())
    assert manifest["adapters"]["adapters"][0]["module"] == "adapter_chi_g0"
    assert manifest["adapters"]["adapters"][0]["sha256"]
    assumptions = {label: text for label, text in manifest["assumptions"]}
    assert "Not established" in assumptions["CHI compliance"]


def test_desired_vcs_are_realized_by_the_ordering_fsm(tmp_path):
    request = _request(traffic_policy=TrafficPolicyV4(
        traffic_class_vcs=(TrafficClassVC("tp_collective", 0),)))
    assert _compile(request).status == "COMPILED"
    from veritx_dse.application.views import topology_view
    assert rtl_support(request, topology_view(_compile(request))).supported is True
    result = run_rtl_preview(request.to_dict(), tmp_path,
                             {"repo_root": str(REPO)})
    assert result["ordering_fsm"] == "EMITTED"
    source = (tmp_path / "rtl" / "ordering_fsm.sv").read_text()
    assert "assign assigned_vc = vc_of_class;" in source
    assert "default: vc_of_class = 1'b0;" in source
    manifest = json.loads((tmp_path / "rtl-preview.json").read_text())
    assert manifest["ordering_fsm"]["vc_assignment"] == [{
        "traffic_class": "tp_collective", "vc": 0,
        "route_table": "RT_MIN(free)"}]
    assert manifest["ordering_fsm"]["realization"] == "ORDERING_FSM"
    assert manifest["parity"]["status"] == "NOT_RUN"
    if shutil.which("verilator") is not None:
        assert result["ordering_fsm_lint"] == "PASS"
        assert result["ordering_fsm_lint_clean"] is True


def test_ordering_and_outstanding_are_realized_by_the_ordering_fsm(tmp_path):
    from veritx_dse.application.views import topology_view
    for index, request in enumerate((
            _request(agent_intents=(
                AgentIntentV4(0, ordering=OrderingMode.STRONG),)),
            _request(agent_intents=(AgentIntentV4(0, max_outstanding=16),)))):
        support = rtl_support(request, topology_view(_compile(request)))
        assert support.supported is True, support.reason
        result = run_rtl_preview(request.to_dict(), tmp_path / f"out{index}",
                                 {"repo_root": str(REPO)})
        assert result["ordering_fsm"] == "EMITTED"
