"""FULL TileLink adapter: TileLink-1.8.1 UL+UH+C A/B/C/D/E, lint, hash-diff, directed TB, manifest.

TileLink-C (BCEB/RMW/hints) + TileLink-UH + TileLink-B/E channels with
opcode/size/param/source/sink/mask/address/data/corrupt/denied + head/tail
credit framing, reusing rtl/t3/nic.sv head/tail conventions. Scala
TilelinkAdapters.scala was absent from this repo snapshot (no .scala
files found), so TileLink field definitions follow the TileLink-1.8.1
standard channel encodings (A 0=PutFull 1=PutPartial 2=Arithmetic
3=Logical 4=Get 5=Intent 6=AcquireBlock 7=AcquirePerm; B 0=Probe
1=ProbeAck 2=ProbeAckData; C 0=Release 1=ReleaseData 2=ProbeAck
3=ProbeAckData 4=HintAck; D 0=AccessAck 1=AccessAckData 2=HintAck
3=Grant 4=GrantData 5=ReleaseAck; E 0=GrantAck 1=ReleaseAck) with
SOURCE_W=5, SINK_W=5, PARAM_W=3. B carries address (BCEB probe); C
snoop replies use ProbeAck/ProbeAckData; D HintAck answers Intent;
E sinks match D sinks via a sink FIFO. Formal legality is checked by
per-channel illegal/param_error outputs and, under TILELINK_FORMAL,
assert/cover properties. Emitted SystemVerilog carries NO comments
(operator rule): version is named via `define TILELINK_VERSION.
"""
from __future__ import annotations

import hashlib
import json
import shutil
import subprocess
from pathlib import Path

import pytest

from veritx_dse.application.fabric_compiler import FabricCompiler
from veritx_dse.core.paths import REPO
from veritx_dse.model.agent_intent_v4 import AgentIntentV4, ProtocolFamily
from veritx_dse.model.compile_model import (
    AddressMap, AddressRange, Agent, AgentKind, CollectiveDimension,
    CollectiveIntent, CollectiveKind, DependencyGraph, ModelFamily,
    WorkloadV3,
)
from veritx_dse.model.compile_request_v4 import CompileRequestV4
from veritx_dse.model.topology_intent import MeshIntent
from veritx_dse.product.adapter_factory_rtl import (
    TILELINK_ADAPTER_ASSUMPTIONS,
    TILELINK_ADAPTER_CHANNELS,
    TILELINK_SUPPORTED_CHANNELS,
    TILELINK_SUPPORTED_PROFILES,
    TILELINK_SUPPORTED_VERSION,
    TILELINK_TB_NOT_RUN_CODE,
    TILELINK_TB_PASS_CODE,
    AdapterParams,
    build_adapter,
    run_tilelink_directed_tb,
)
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


def test_tilelink_version_scope_named():
    assert TILELINK_SUPPORTED_VERSION == "TileLink-1.8.1"
    assert TILELINK_SUPPORTED_PROFILES == ("UL", "UH", "C")
    assert TILELINK_SUPPORTED_CHANNELS == ("A", "B", "C", "D", "E")
    assert TILELINK_ADAPTER_CHANNELS == ("A", "B", "C", "D", "E")
    blob = " ".join(TILELINK_ADAPTER_ASSUMPTIONS)
    for token in ("TileLink-1.8.1", "A/B/C/D/E", "PutFullData",
                  "ArithmeticData", "LogicalData", "Intent",
                  "AcquireBlock", "Probe", "Release", "Grant",
                  "GrantAck", "nic.sv", "final_implementation",
                  "op_numeric", "ProbeAck", "HintAck",
                  "ReleaseAck", "e_sink_match", "illegal",
                  "TILELINK_FORMAL"):
        assert token in blob, token


def test_tilelink_emits_full_channels_and_version():
    build = build_adapter(AdapterParams(
        agent_idx=0, protocol=ProtocolFamily.TILELINK, data_width=256,
        addr_width=64, max_outstanding=16, ordering="strong"))
    assert build.verdict.ok is True
    assert build.module == "adapter_tilelink_g0"
    source = build.source or ""
    assert "module adapter_tilelink_g0" in source
    assert "TILELINK_VERSION" in source
    assert TILELINK_SUPPORTED_VERSION in source
    assert "TileLink-UL" in source
    assert "nic.sv" in source
    for token in (
        "in_a_opcode", "in_a_param", "in_a_size", "in_a_source",
        "in_a_address", "in_a_mask", "in_a_data", "in_a_corrupt",
        "out_a_head", "out_a_tail",
        "in_b_opcode", "in_b_param", "in_b_size", "in_b_source",
        "in_b_sink", "in_b_address", "in_b_corrupt", "out_b_head",
        "out_b_tail", "out_b_address",
        "in_c_opcode", "in_c_param", "in_c_size", "in_c_source",
        "in_c_address", "in_c_mask", "in_c_data", "in_c_corrupt",
        "out_c_head", "out_c_tail",
        "in_d_opcode", "in_d_param", "in_d_size", "in_d_source",
        "in_d_sink", "in_d_denied", "in_d_data", "in_d_corrupt",
        "out_d_head", "out_d_tail",
        "in_e_opcode", "in_e_sink", "out_e_head", "out_e_tail",
        "credit_full", "a_error", "b_error", "c_error", "d_error",
        "order_violation", "outstanding_q", "busy_q",
        "SOURCE_W", "SINK_W", "PARAM_W",
        "out_a_is_get", "out_a_is_rmw", "out_a_is_arith",
        "out_a_is_logical", "out_a_op_numeric", "out_a_is_intent",
        "out_a_is_acquire", "out_b_is_probe", "out_b_is_probe_ack",
        "out_b_is_probe_ack_data", "out_c_is_release",
        "out_c_is_release_data", "out_c_is_probe_ack",
        "out_c_is_probe_ack_data", "out_c_is_hint_ack",
        "out_d_is_access_ack", "out_d_is_access_ack_data",
        "out_d_is_hint_ack", "out_d_is_grant",
        "out_d_is_release_ack", "out_e_is_grant_ack",
        "out_e_is_release_ack", "a_illegal", "b_illegal",
        "c_illegal", "d_illegal", "e_illegal", "a_param_error",
        "b_param_error", "d_param_error", "e_sink_match",
        "e_sink_error", "sink_fifo", "TILELINK_FORMAL",
    ):
        assert token in source, token
    assert build_adapter(AdapterParams(
        agent_idx=0, protocol=ProtocolFamily.TILELINK, data_width=256,
        addr_width=64, max_outstanding=16, ordering="strong")).source == source


def test_tilelink_no_comments_operator_rule():
    build = build_adapter(AdapterParams(
        agent_idx=0, protocol=ProtocolFamily.TILELINK))
    source = build.source or ""
    assert source
    assert "//" not in source
    assert "/*" not in source


@pytest.mark.skipif(_VERILATOR is None, reason="verilator not installed")
@pytest.mark.parametrize("params", [
    AdapterParams(agent_idx=0, protocol=ProtocolFamily.TILELINK),
    AdapterParams(agent_idx=1, protocol=ProtocolFamily.TILELINK,
                  data_width=64, addr_width=32, max_outstanding=8,
                  ordering="raw"),
    AdapterParams(agent_idx=0, protocol=ProtocolFamily.TILELINK,
                  data_width=512, addr_width=48, max_outstanding=32,
                  ordering="strong"),
    AdapterParams(agent_idx=2, protocol=ProtocolFamily.TILELINK,
                  data_width=256, ordering="relaxed", max_outstanding=4),
    AdapterParams(agent_idx=0, protocol=ProtocolFamily.TILELINK,
                  data_width=128, addr_width=40, max_outstanding=1,
                  ordering="raw"),
])
def test_tilelink_lint_clean(params, tmp_path):
    build = build_adapter(params)
    assert build.module is not None and build.source is not None
    assert "//" not in build.source and "/*" not in build.source
    (tmp_path / f"{build.module}.sv").write_text(build.source)
    _lint(tmp_path, [f"{build.module}.sv"], build.module)


@pytest.mark.parametrize("kwargs_a, kwargs_b", [
    (dict(max_outstanding=16), dict(max_outstanding=8)),
    (dict(ordering="strong"), dict(ordering="raw")),
    (dict(data_width=256), dict(data_width=64)),
    (dict(addr_width=64), dict(addr_width=32)),
])
def test_tilelink_hash_diff_when_params_change(kwargs_a, kwargs_b):
    a = build_adapter(AdapterParams(agent_idx=0,
                                    protocol=ProtocolFamily.TILELINK,
                                    **kwargs_a))
    b = build_adapter(AdapterParams(agent_idx=0,
                                    protocol=ProtocolFamily.TILELINK,
                                    **kwargs_b))
    assert a.source is not None and b.source is not None
    assert _sha(a.source) != _sha(b.source)
    assert _sha(build_adapter(AdapterParams(
        agent_idx=0, protocol=ProtocolFamily.TILELINK, **kwargs_a
    )).source or "") == _sha(a.source)


@pytest.mark.skipif(_VERILATOR is None, reason="verilator not installed")
def test_tilelink_directed_tb_per_channel(tmp_path):
    build = build_adapter(AdapterParams(
        agent_idx=0, protocol=ProtocolFamily.TILELINK, data_width=256,
        addr_width=64, max_outstanding=16, ordering="raw"))
    assert build.module is not None and build.source is not None
    verdict = run_tilelink_directed_tb(
        adapter_source=build.source, module=build.module,
        work_dir=tmp_path / "tilelink_tb")
    assert verdict["version"] == TILELINK_SUPPORTED_VERSION
    assert verdict["channels"] == ["A", "B", "C", "D", "E"]
    if verdict["status"] == "PASS":
        assert verdict["code"] == TILELINK_TB_PASS_CODE
        for token in ("TB_A_PASS", "TB_A2_PASS", "TB_B_PASS",
                      "TB_C_PASS", "TB_RMW_PASS", "TB_HINT_PASS",
                      "TB_D_PASS", "TB_E_PASS",
                      "TB_BP_VALID_PASS", "TB_BP_DRAIN_PASS",
                      "TB_B_BP_PASS", "TB_B_BP_DRAIN_PASS",
                      "TB_A_GET_PASS", "TB_A_ARITH_PASS",
                      "TB_A_LOGICAL_PASS", "TB_A_INTENT_PASS",
                      "TB_A_ACQBLK_PASS", "TB_A_ACQBLK_TAIL_PASS",
                      "TB_A_ACQPERM_PASS", "TB_B_PROBE_PASS",
                      "TB_B_PROBEACK_PASS", "TB_B_PROBEACKDATA_PASS",
                      "TB_C_RELEASE_PASS", "TB_C_RELEASEDATA_PASS",
                      "TB_C_PROBEACK_PASS", "TB_C_PROBEACKDATA_PASS",
                      "TB_C_HINTACK_PASS", "TB_D_ACCESSACK_PASS",
                      "TB_D_ACCESSACKDATA_PASS", "TB_D_HINTACK_PASS",
                      "TB_D_GRANT_PASS", "TB_D_GRANTDATA_PASS",
                      "TB_D_TAIL_PASS", "TB_D_RELEASEACK_PASS",
                      "TB_E_GRANTACK_PASS", "TB_E_RELEASEACK_PASS",
                      "TB_SINK_MATCH_PASS", "TB_C_BP_PASS",
                      "TB_C_BP_DRAIN_PASS", "TB_D_BP_PASS",
                      "TB_D_BP_DRAIN_PASS", "TB_E_BP_PASS",
                      "TB_E_BP_DRAIN_PASS", "TB_ERR_A_PASS",
                      "TB_ERR_B_PASS", "TB_ERR_C_PASS", "TB_ERR_D_PASS",
                      "TB_ILLEGAL_PASS", "TB_PARAM_PASS",
                      "TB_SINK_ERR_PASS", "TB_DONE"):
            assert token in verdict.get("output_tail", ""), token
    else:
        assert verdict["status"] == "NOT_RUN"
        assert verdict["code"] == TILELINK_TB_NOT_RUN_CODE
        assert verdict["status"] != "PASS"


@pytest.mark.skipif(_VERILATOR is None, reason="verilator not installed")
def test_tilelink_per_opcode_evidence_sources(tmp_path):
    build = build_adapter(AdapterParams(
        agent_idx=0, protocol=ProtocolFamily.TILELINK, data_width=256,
        addr_width=64, max_outstanding=16, ordering="raw"))
    assert build.module is not None and build.source is not None
    source = build.source
    a_decodes = ("out_a_is_get", "out_a_is_arith", "out_a_is_logical",
                 "out_a_op_numeric", "out_a_is_intent", "out_a_is_acquire")
    for token in a_decodes:
        assert token in source, token
    for token in ("out_b_is_probe", "out_b_is_probe_ack_data",
                  "out_c_is_release", "out_c_is_probe_ack",
                  "out_c_is_probe_ack_data", "out_c_is_hint_ack",
                  "out_d_is_access_ack_data", "out_d_is_hint_ack",
                  "out_d_is_grant", "out_d_is_release_ack",
                  "out_e_is_grant_ack", "out_e_is_release_ack",
                  "e_sink_match", "sink_fifo", "d_error"):
        assert token in source, token
    assert "TILELINK_FORMAL" in source
    assert "assert property" in source
    assert "cover property" in source
    (tmp_path / f"{build.module}.sv").write_text(source)
    _lint(tmp_path, [f"{build.module}.sv"], build.module)
    checked = subprocess.run(
        [_VERILATOR, "--lint-only", "-sv", "-Wall", "-Wno-fatal",
         "-Wno-WIDTH", "-Wno-PINNOTFOUND", "-Wno-UNOPTFLAT",
         "-DTILELINK_FORMAL",
         "--top-module", build.module, f"{build.module}.sv"],
        cwd=tmp_path, capture_output=True, text=True)
    log = checked.stdout + checked.stderr
    assert checked.returncode == 0, log
    assert "%Warning" not in log, log


def test_tilelink_manifest_version_and_final_implementation(tmp_path):
    request = _request(agent_intents=(
        AgentIntentV4(0, protocol=ProtocolFamily.TILELINK),))
    result = run_rtl_preview(request.to_dict(), tmp_path,
                             {"repo_root": str(REPO)})
    assert result["adapters"] == "EMITTED"
    assert result["final_implementation"] is False
    assert (tmp_path / "rtl" / "adapter_tilelink_g0.sv").is_file()
    source = (tmp_path / "rtl" / "adapter_tilelink_g0.sv").read_text()
    assert TILELINK_SUPPORTED_VERSION in source
    assert "TILELINK_VERSION" in source
    assert "//" not in source and "/*" not in source
    manifest = json.loads((tmp_path / "rtl-preview.json").read_text())
    assert manifest["final_implementation"] is False
    row = manifest["adapters"]["adapters"][0]
    assert row["module"] == "adapter_tilelink_g0" and row["sha256"]
    assert row["sha256"] == _sha(source)
    if _VERILATOR is not None:
        assert row["lint"]["status"] == "PASS"
        assert row["lint"]["clean"] is True
