"""M3 CdcCell + M4 AdapterFactory RTL: builders, typed failures, lint, CDC.

Kernel of STAGE 3 §3.6/§3.1-3.2: each deep module takes one frozen param
struct and returns (module, verdict). Every refusal is typed in place
(CDC_CELL_MISSING / ADAPTER_UNSUPPORTED:<family>), never a pass-through
stub. Per-cell/per-adapter hashes are content-derived (hash-diff), every
emitted module is Verilator-linted, and each CdcCell passes the CDC
structural check (nominal DEPTH=16 async FIFO instance with net usable
depth 8 stated + synchronizer chain + reset alignment + MTBF estimate
state).
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
from veritx_dse.model.agent_intent_v4 import (
    AgentIntentV4, ProtocolFamily,
)
from veritx_dse.model.clock_power_cdc import (
    ClockPowerInput, EndpointDomain, check_clock_power_cdc, cdc_cells_for,
    crossing_points,
)
from veritx_dse.model.compile_model import (
    AddressMap, AddressRange, Agent, AgentKind, CollectiveDimension,
    CollectiveIntent, CollectiveKind, DependencyGraph, ModelFamily,
    WorkloadV3,
)
from veritx_dse.model.compile_request_v4 import CompileRequestV4
from veritx_dse.model.topology_intent import MeshIntent
from veritx_dse.product.adapter_factory_rtl import (
    ADAPTER_UNSUPPORTED, AdapterParams, build_adapter,
)
from veritx_dse.product.cdc_cell_rtl import (
    CdcParams, build_cdc_cell, check_cdc_cell_source, gray_sequence_ok,
    sanitize_module_name,
)
from veritx_dse.product.catalog_evaluation import rtl_support
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


def _multi_clock_request(**kwargs) -> CompileRequestV4:
    return _request(agents=(
        Agent(kind=AgentKind.COMPUTE_TILE, count=3, clock_domain="a"),
        Agent(kind=AgentKind.HBM_CONTROLLER, count=1, clock_domain="b")),
        **kwargs)


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


# --- M3: builder ------------------------------------------------------


def test_cdc_cell_params_shape_and_module_naming():
    params = CdcParams(
        insertion_point="cdc:attach:group0(a)->group1(b)",
        src_domain="a", dst_domain="b", src_group=0, dst_group=1)
    build = build_cdc_cell(params)
    assert build.verdict.ok is True
    assert build.module == sanitize_module_name(
        "cdc:attach:group0(a)->group1(b)")
    assert build.source is not None
    assert "module cdc_cell_" in build.source
    assert "cdc_fifo" in build.source            # reused async FIFO instance
    assert "DEPTH = 16" in build.source
    assert "USABLE_DEPTH = 8" in build.source
    assert "SYNC_STAGES = 3" in build.source     # synchronizer chain depth
    # Pure: same struct twice -> identical output.
    assert build_cdc_cell(params).source == build.source


def test_cdc_cell_rejects_same_domain_and_bad_insertion_point():
    same = build_cdc_cell(CdcParams(
        insertion_point="cdc:attach:group0(a)->group1(a)",
        src_domain="a", dst_domain="a", src_group=0, dst_group=1))
    assert same.verdict.ok is False
    assert same.verdict.blocker_id == "CDC_INVALID_PARAMS"
    assert same.module is None and same.source is None
    bad = build_cdc_cell(CdcParams(
        insertion_point="group0->group1", src_domain="a", dst_domain="b"))
    assert bad.verdict.ok is False and bad.source is None


def test_cdc_cell_structure_check_passes_and_catches_broken_source():
    build = build_cdc_cell(CdcParams(
        insertion_point="cdc:attach:group0(a)->group1(b)",
        src_domain="a", dst_domain="b", src_group=0, dst_group=1))
    assert check_cdc_cell_source(build.source) == ()
    assert len(check_cdc_cell_source(
        build.source.replace("SYNC_STAGES = 3", "SYNC_STAGES = 1"))) > 0
    # Gray sequence property (FIFO pointer code).
    assert gray_sequence_ok(8) is True
    assert gray_sequence_ok(16) is True


def test_cdc_cell_per_cell_hash_diff():
    a = build_cdc_cell(CdcParams(
        insertion_point="cdc:attach:group0(a)->group1(b)",
        src_domain="a", dst_domain="b", src_group=0, dst_group=1))
    b = build_cdc_cell(CdcParams(
        insertion_point="cdc:attach:group0(a)->group2(c)",
        src_domain="a", dst_domain="c", src_group=0, dst_group=2))
    assert a.module != b.module
    assert _sha(a.source) != _sha(b.source)
    assert _sha(build_cdc_cell(CdcParams(
        insertion_point="cdc:attach:group0(a)->group1(b)",
        src_domain="a", dst_domain="b", src_group=0, dst_group=1)).source) \
        == _sha(a.source)


@pytest.mark.skipif(_VERILATOR is None, reason="verilator not installed")
def test_cdc_cell_lints_clean_with_reused_fifo(tmp_path):
    build = build_cdc_cell(CdcParams(
        insertion_point="cdc:attach:group0(a)->group1(b)",
        src_domain="a", dst_domain="b", src_group=0, dst_group=1))
    fifo = Path(REPO) / "tracks/t3-topology/rtl/cdc/cdc_fifo.sv"
    assert fifo.is_file()
    (tmp_path / "cdc_fifo.sv").write_text(
        fifo.read_text() if fifo.read_text().endswith("\n")
        else fifo.read_text() + "\n")
    assert build.module is not None
    (tmp_path / f"{build.module}.sv").write_text(build.source)
    _lint(tmp_path, ["cdc_fifo.sv", f"{build.module}.sv"], build.module)


# --- M4: AdapterFactory -----------------------------------------------


def test_adapter_axi5_burst_split_and_credit_shape():
    build = build_adapter(AdapterParams(
        agent_idx=0, protocol=ProtocolFamily.AXI5, split_at=64,
        max_outstanding=16))
    assert build.verdict.ok is True
    assert build.module == "adapter_axi5_g0"
    source = build.source or ""
    assert "SPLIT_AT = 64" in source             # burst-split knob
    assert "MAX_OUTSTANDING = 16" in source      # outstanding-credit table
    assert "module adapter_axi5_g0" in source
    # Pure.
    assert build_adapter(AdapterParams(
        agent_idx=0, protocol=ProtocolFamily.AXI5, split_at=64,
        max_outstanding=16)).source == source


def test_adapter_per_adapter_hash_diff():
    coarse = build_adapter(AdapterParams(
        agent_idx=0, protocol=ProtocolFamily.AXI5, split_at=64,
        max_outstanding=16))
    fine = build_adapter(AdapterParams(
        agent_idx=0, protocol=ProtocolFamily.AXI5, split_at=32,
        max_outstanding=16))
    assert _sha(coarse.source) != _sha(fine.source)
    assert _sha(build_adapter(AdapterParams(
        agent_idx=0, protocol=ProtocolFamily.AXI5, split_at=64,
        max_outstanding=16)).source) == _sha(coarse.source)


@pytest.mark.skipif(_VERILATOR is None, reason="verilator not installed")
def test_adapter_axi5_lints_clean(tmp_path):
    for params in (
            AdapterParams(agent_idx=0, protocol=ProtocolFamily.AXI5,
                          split_at=64, max_outstanding=16),
            AdapterParams(agent_idx=1, protocol=ProtocolFamily.AXI5)):
        build = build_adapter(params)
        assert build.module is not None
        (tmp_path / f"{build.module}.sv").write_text(build.source)
        _lint(tmp_path, [f"{build.module}.sv"], build.module)


@pytest.mark.parametrize("family", [ProtocolFamily.CHI,
                                    ProtocolFamily.TILELINK])
def test_adapter_chi_tilelink_emit_real_shims(family):
    # CHI and TileLink wrappers are real shims emitted by AdapterFactory —
    # never a pass-through stub. The module header names the scope; the
    # source carries the family framing logic.
    build = build_adapter(AdapterParams(agent_idx=0, protocol=family))
    assert build.verdict.ok is True
    assert build.module == f"adapter_{family.value}_g0"
    source = build.source or ""
    assert f"module adapter_{family.value}_g0" in source
    assert "MAX_OUTSTANDING" in source
    # Real logic, not a stub: state + credit + framing (adapted from
    # rtl/t3/nic.sv head/tail + AXI5 credit patterns, not wholesale copy).
    assert "busy_q" in source and "outstanding_q" in source
    if family == ProtocolFamily.CHI:
        for token in ("REQ", "RSP", "SNP", "DAT", "SIZE", "channel",
                      "aligned", "Full-Profile", "CT/legacy",
                      "DVM", "RSOS", "P_CREDIT_MAX"):
            assert token in source, token
        assert "final_implementation" in source
    else:
        for token in ("in_a_opcode", "out_a_head", "out_a_tail",
                      "in_d_opcode", "out_d_head", "out_d_tail"):
            assert token in source, token
        assert "TileLink-UL" in source
    # Pure.
    assert build_adapter(
        AdapterParams(agent_idx=0, protocol=family)).source == source


def test_adapter_custom_bare_is_invalid_never_a_stub():
    # Custom without a declared burst (split_at) or ordering param is
    # INVALID (no hidden defaults) — never an emitted default shim.
    build = build_adapter(AdapterParams(agent_idx=0, protocol=ProtocolFamily.CUSTOM))
    assert build.verdict.ok is False
    assert build.verdict.status == "INVALID"
    assert build.verdict.blocker_id == "ADAPTER_INVALID_PARAMS"
    assert "burst" in (build.verdict.reason or "")
    assert "ordering" in (build.verdict.reason or "")
    assert "hidden" in (build.verdict.reason or "")
    assert build.module is None and build.source is None
    # With a declared burst or ordering param the shim emits.
    for params in (
            AdapterParams(agent_idx=0, protocol=ProtocolFamily.CUSTOM,
                          split_at=64),
            AdapterParams(agent_idx=0, protocol=ProtocolFamily.CUSTOM,
                          ordering="strong")):
        ok = build_adapter(params)
        assert ok.verdict.ok is True, ok.verdict.reason
        assert ok.module == "adapter_custom_g0"
        source = ok.source or ""
        assert "BURST_AT" in source or "ORDERING_MODE" in source
        assert "Not established" in source or "burst" in source.lower()


# --- M3 + M4 through the compiler / preview ----------------------------


def test_multi_clock_compile_succeeds_with_named_cells():
    compilation = FabricCompiler().compile(_multi_clock_request())
    assert compilation.status == "COMPILED", compilation.error
    assert compilation.bundle is not None
    assert any("group0(a)" in finding and "group1(b)" in finding
               for finding in compilation.findings)
    m3 = next(v for v in compilation.stage1_verdicts
              if v["module"] == "clock_power_cdc")
    assert m3["ok"] is True


def test_missing_cell_is_compile_refusal_not_a_warning():
    endpoints = (
        EndpointDomain(0, "a", None, None, None),
        EndpointDomain(1, "b", None, None, None))
    # No cells at all.
    refused = check_clock_power_cdc(ClockPowerInput(endpoints=endpoints))
    assert refused.ok is False and refused.status == "UNSUPPORTED"
    assert "CDC_CELL_MISSING" in (refused.reason or "")
    # Partial coverage: the uncovered point is named in the refusal.
    points = cdc_cells_for(ClockPowerInput(endpoints=endpoints))
    assert points
    partial = check_clock_power_cdc(ClockPowerInput(
        endpoints=endpoints, cdc_cells=points[:-1]))
    assert partial.ok is False
    assert "CDC_CELL_MISSING" in (partial.reason or "")
    # Full coverage compiles.
    full = check_clock_power_cdc(ClockPowerInput(
        endpoints=endpoints, cdc_cells=points))
    assert full.ok is True
    names = [point.insertion_point for point in crossing_points(
        ClockPowerInput(endpoints=endpoints))]
    assert names == list(points)


def test_axi5_preview_emits_adapter_and_cells_in_the_manifest(tmp_path):
    request = _multi_clock_request(agent_intents=(
        AgentIntentV4(0, protocol=ProtocolFamily.AXI5, split_at=64,
                      max_outstanding=16),))
    assert FabricCompiler().compile(request).status == "COMPILED"
    result = run_rtl_preview(request.to_dict(), tmp_path,
                             {"repo_root": str(REPO)})
    assert result["final_implementation"] is False
    assert result["cdc_cells"] == "EMITTED" and result["cdc_cell_count"] >= 1
    assert result["adapters"] == "EMITTED" and result["adapter_count"] == 1
    manifest = json.loads((tmp_path / "rtl-preview.json").read_text())
    assert manifest["final_implementation"] is False
    # Read-only summary on top.
    assert manifest["summary"]["insertion_points"] == [
        row["insertion_point"] for row in manifest["cdc_cells"]["cells"]]
    # Emitted-module manifest below: module + hash for every emission.
    modules = {row["module"] for row in manifest["emitted_modules"]}
    assert "addr_decode" in modules
    assert manifest["adapters"]["adapters"][0]["module"] == "adapter_axi5_g0"
    assert manifest["adapters"]["adapters"][0]["sha256"]
    for row in manifest["cdc_cells"]["cells"]:
        assert row["module"] and row["sha256"] and row["insertion_point"]
        assert row["cdc_checks"] == []
        assert (tmp_path / "rtl" / row["file"]).is_file()
    assert (tmp_path / "rtl" / "adapter_axi5_g0.sv").is_file()
    assert (tmp_path / "rtl" / "cdc_fifo.sv").is_file()
    assert manifest["cdc_cells"]["cdc_fifo"]["module"] == "cdc_fifo"
    if _VERILATOR is not None:
        for row in manifest["cdc_cells"]["cells"]:
            assert row["lint"]["status"] == "PASS", row["lint"].get("log")
            assert row["lint"]["clean"] is True, row["lint"].get("log")
        for row in manifest["adapters"]["adapters"]:
            assert row["lint"]["status"] == "PASS"
            assert row["lint"]["clean"] is True
    # Assumptions carry the unestablished rows.
    assumptions = {label: text for label, text in manifest["assumptions"]}
    assert "Not established" in assumptions["Timing closure (STA)"]
    assert "Not established" in assumptions["Power-domain isolation (PTS)"]
    # MTBF: preview requests declare no per-domain rates => NOT_CALCULATED
    # with reason (never substituted from the global clock default).
    assert "NOT_CALCULATED" in assumptions["CDC MTBF"]
    assert "UNDECLARED" in assumptions["CDC MTBF"]
    for row in manifest["cdc_cells"]["cells"]:
        assert row["mtbf"]["status"] == "NOT_CALCULATED"
        assert row["mtbf"]["years"] is None
        assert "UNDECLARED" in row["mtbf"]["reason"]


def test_chi_intent_is_realized_by_the_adapter_factory(tmp_path):
    request = _request(agent_intents=(
        AgentIntentV4(0, protocol=ProtocolFamily.CHI),))
    assert FabricCompiler().compile(request).status == "COMPILED"
    # rtl_support no longer refuses chi once the wrapper exists.
    from veritx_dse.application.views import topology_view
    compilation = FabricCompiler().compile(request)
    support = rtl_support(request, topology_view(compilation))
    assert support.supported is True, support.reason
    result = run_rtl_preview(request.to_dict(), tmp_path,
                             {"repo_root": str(REPO)})
    assert result["adapters"] == "EMITTED"
    assert result["adapter_count"] == 1
    assert result["final_implementation"] is False
    source = (tmp_path / "rtl" / "adapter_chi_g0.sv").read_text()
    assert "MAX_SIZE" in source and "out_req_ch" in source
    manifest = json.loads((tmp_path / "rtl-preview.json").read_text())
    assert manifest["final_implementation"] is False
    row = manifest["adapters"]["adapters"][0]
    assert row["module"] == "adapter_chi_g0" and row["sha256"]
    # Typed BookSim smoke is recorded, never silent.
    assert row["booksim_smoke"]["status"] == "NOT_RUN"
    assert row["booksim_smoke"]["code"] == "ADAPTER_BOOKSIM_NOT_RUN"
    assumptions = {label: text for label, text in manifest["assumptions"]}
    assert "Not established" in assumptions["CHI compliance"]
    if _VERILATOR is not None:
        assert row["lint"]["status"] == "PASS"
        assert row["lint"]["clean"] is True


def test_all_m4_families_are_realized_by_the_adapter_factory():
    # Every closed-vocabulary family now has a wrapper: rtl_support
    # refuses none of them for the adapter (M2 slice still applies).
    cases = (
        AgentIntentV4(0, protocol=ProtocolFamily.AXI5, split_at=64,
                      max_outstanding=16),
        AgentIntentV4(0, protocol=ProtocolFamily.CHI),
        AgentIntentV4(0, protocol=ProtocolFamily.TILELINK),
        AgentIntentV4(0, protocol=ProtocolFamily.CUSTOM, split_at=64),
        AgentIntentV4(0, protocol=ProtocolFamily.CUSTOM,
                      ordering="strong"),
    )
    for intent in cases:
        request = _request(agent_intents=(intent,))
        support = rtl_support(request)
        assert "AdapterFactory" not in (support.reason or "")
        assert "ADAPTER_UNSUPPORTED" not in (support.reason or "")
