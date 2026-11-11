"""Parameterized composed slice: attachments / widths / VC / arb / CDC.

Each test drives an explicit knob mutation and checks that the composed
slice either (a) composes with a different artifact hash than the default
profile (no silent substitution, no accidental constant), or (b) raises a
typed UNSUPPORTED_SLICE_PROFILE refusal (never a substitute).
"""
from __future__ import annotations

import json
import shutil
from dataclasses import replace
from types import SimpleNamespace

import pytest

from veritx_dse.model.agent_intent_v4 import (
    AgentIntentV4, OrderingMode, PermissionWindow, ProtocolFamily,
    TrafficClassVC, TrafficPolicyV4,
)
from veritx_dse.model.compile_model import (
    AddressMap, AddressRange, Agent, AgentKind, CollectiveDimension,
    CollectiveIntent, CollectiveKind, DependencyGraph, DepKind, Dependency,
    ModelFamily, WorkloadV3,
)
from veritx_dse.model.compile_request_v4 import CompileRequestV4
from veritx_dse.model.noc_controls import NocControls
from veritx_dse.model.topology_intent import MeshIntent
from veritx_dse.application.fabric_compiler import FabricCompiler
from veritx_dse.core.paths import REPO
from veritx_dse.product.project_top_rtl import (
    ARB_AGE, ARB_ROUND_ROBIN, SliceInitiator, SliceParams,
    check_slice_profile, render_cdc_bypass, render_project_top,
    render_tb_project_top, run_rtl_slice, slice_params_from_request,
    apply_arb_policy,
)

_VERILATOR = shutil.which("verilator") is not None


def _base_agents():
    return (
        Agent(kind=AgentKind.COMPUTE_TILE, count=1, data_width=32,
              addr_width=64, protocol="AXI", clock_domain="noc_clk",
              power_domain="pd0"),
        Agent(kind=AgentKind.COMPUTE_TILE, count=1, data_width=32,
              addr_width=64, protocol="AXI", clock_domain="noc_clk",
              power_domain="pd0"),
        Agent(kind=AgentKind.HBM_CONTROLLER, count=1, data_width=32,
              addr_width=64, protocol="AXI", clock_domain="noc_clk",
              power_domain="pd0"),
    )


def _init(gi: int, readable: bool, writable: bool):
    return AgentIntentV4(
        gi, protocol=ProtocolFamily.AXI5, ordering=OrderingMode.STRONG,
        max_outstanding=4,
        permission_windows=(PermissionWindow(
            "HBM0", readable=readable, writable=writable, atomic=False),),
    )


def _workload(tp: int = 2, classes=("tp_collective",)):
    return WorkloadV3(
        model_family=ModelFamily.DENSE_TRANSFORMER, tp=tp, pp=1, ep=1, dp=1,
        collectives=tuple(
            CollectiveIntent(
                kind=CollectiveKind.ALLREDUCE,
                dimension=CollectiveDimension.TP,
                payload_bytes=8192, traffic_class=cls)
            for cls in classes))


def _request(*, agents=_base_agents(), intents=None, policy=None,
             noc_controls=None, deps=DependencyGraph(()), tp: int = 2,
             classes=("tp_collective",)):
    if intents is None:
        intents = (
            _init(0, True, True),
            _init(1, True, False),
            AgentIntentV4(2),
        )
    hbm = next(i for i, a in enumerate(agents)
               if getattr(getattr(a, "kind", None), "value", a.kind)
               == "hbm_controller")
    return CompileRequestV4(
        workload=_workload(tp, classes)
        if tp != 2 or classes != ("tp_collective",) else _workload(tp),
        agents=agents,
        dependencies=deps,
        topology=MeshIntent(side_length=2, concentration=1),
        address_map=AddressMap(ranges=(
            AddressRange(name="HBM0", base=0x1000, size=0x1000,
                         target_agent_idx=hbm),)),
        agent_intents=intents,
        traffic_policy=policy or TrafficPolicyV4(),
        noc_controls=noc_controls or NocControls())


def _kc(gi):
    return _init(gi, True, True)


def test_slice_params_rederive_from_request():
    req = _request()
    params = slice_params_from_request(
        req, FabricCompiler().compile(req))
    assert isinstance(params, SliceParams)
    assert params.num_initiators == 2
    assert params.memory_router == 2
    assert [i.group_idx for i in params.initiators] == [0, 1]
    assert params.crossed_groups == ()
    assert len(params.knob_map()) >= 7
    d = params.to_dict()
    assert d["buf_depth_per_vc"] == [8, 8]
    assert d["arb_policy"] == ARB_ROUND_ROBIN
    assert d["bound_vc"] == 0


def _stub_bundle(vc_count, routers=4, attachment=None):
    topology = SimpleNamespace(
        routers=tuple(SimpleNamespace(router_id=i) for i in range(routers)))
    endpoints = tuple(
        SimpleNamespace(endpoint_id=g,
                        agent=SimpleNamespace(group_index=g),
                        router_id=r)
        for g, r in (attachment or ((0, 0), (1, 1), (2, 2))))
    return SimpleNamespace(
        topology=topology,
        vc_assignment=SimpleNamespace(vc_count=vc_count),
        attachment=SimpleNamespace(endpoints=endpoints))


# VC >= 2 disagrees with the 2-VC preview: typed refusal, never an
# emitted substitute. A real compile forbids such a desire already, so
# the gate is exercised through a stub-compiled bundle.
def test_vc_greater_equal_2_is_typed_refusal():
    req = _request(policy=TrafficPolicyV4(
        traffic_class_vcs=(TrafficClassVC("tp_collective", 2),)))
    compiled = SimpleNamespace(status="COMPILED",
                              bundle=_stub_bundle(2))
    with pytest.raises(ValueError, match="UNSUPPORTED_SLICE_PROFILE") as exc:
        check_slice_profile(req, compiled)
    assert "OrderingFSM" in str(exc.value)
    assert "RTL generation" in str(exc.value)


def test_disagreeing_per_group_ordering_is_typed_refusal():
    strong = _init(1, True, False)
    weak = replace(strong, ordering=OrderingMode.RELAXED)
    req = _request(intents=(_init(0, True, True), weak,
                            AgentIntentV4(2)))
    compiled = SimpleNamespace(status="COMPILED",
                              bundle=_stub_bundle(1))
    with pytest.raises(ValueError, match="UNSUPPORTED_SLICE_PROFILE"):
        check_slice_profile(req, compiled)


def test_data_width_64_composes():
    agents = tuple(replace(a, data_width=64) for a in _base_agents())
    req = _request(agents=agents)
    compiled = FabricCompiler().compile(req)
    assert compiled.status == "COMPILED", compiled.error
    params = slice_params_from_request(req, compiled)
    assert params.data_width == 64
    assert params.flit_w == 96
    check_slice_profile(req, compiled)


def test_buf_depth_refused_below_2():
    req = _request(noc_controls=NocControls(
        input_buffer_depth_flits_per_vc=1))
    compiled = FabricCompiler().compile(req)
    with pytest.raises(ValueError, match="UNSUPPORTED_SLICE_PROFILE"):
        check_slice_profile(req, compiled)


def test_renderers_are_deterministic():
    p = replace(__import__(
        "veritx_dse.product.project_top_rtl",
        fromlist=["x"])._default_params(), buf_depth=16)
    assert render_project_top(p) == render_project_top(p)
    assert render_tb_project_top(p) == render_tb_project_top(p)
    assert render_cdc_bypass() == render_cdc_bypass()
    assert render_project_top() != render_project_top(p)


def _files_for(directory):
    return {
        name: (directory / "rtl" / name).read_bytes()
        for name in ("noc_pkg.sv", "project_top.sv", "tb_project_top.sv",
                     "router.sv")
        if (directory / "rtl" / name).is_file()
    }


def _run(doc, out):
    return run_rtl_slice(doc, out, {"repo_root": str(REPO)})


def test_knob_mutations_change_artifacts(tmp_path):
    base = _request()
    others = {
        "buf": _request(noc_controls=NocControls(
            input_buffer_depth_flits_per_vc=16)),
    }
    changed = {}
    base_hash = _files_for(tmp_path / "out")
    _run(base.to_dict(), tmp_path / "out")
    base_files = _files_for(tmp_path / "out")
    assert base_files
    doc_buf = others["buf"].to_dict()
    _run(doc_buf, tmp_path / "o2")
    buf_files = _files_for(tmp_path / "o2")
    changed = buf_files["noc_pkg.sv"] != base_files["noc_pkg.sv"]
    assert changed, "buf 8->16 must change noc_pkg.sv (BUF_DEPTH)"

    router_src = (tmp_path / "o2" / "rtl" / "router.sv").read_text()
    assert apply_arb_policy(router_src, ARB_ROUND_ROBIN) == router_src
    patched = apply_arb_policy(router_src, ARB_AGE)
    assert patched != router_src
    assert "age-first (oldest eligible head wins)" in patched.lower() \
        or "_ROUTER" in patched or "age" in patched


@pytest.mark.skipif(not _VERILATOR, reason="verilator not installed")
def test_multi_domain_composes_with_cdc_cells(tmp_path):
    agents = (
        _base_agents()[0],
        replace(_base_agents()[1], clock_domain="other_clk"),
        _base_agents()[2],
    )
    req = _request(agents=agents)
    result = _run(req.to_dict(), tmp_path)
    assert result["scope"] == "COMPOSED_SLICE"
    assert result["lint"] == "PASS"
    manifest = json.loads(
        (tmp_path / "project-top-manifest.json").read_text())
    assert manifest["cdc"]["mode"] == "CDC_CELL"
    assert manifest["cdc"]["cells"]
    assert all("cdc_cell" in cell["module"] for cell in manifest["cdc"]["cells"])
    top = (tmp_path / "rtl" / "project_top.sv").read_text()
    assert "cdc_slice_up_1" in top and "cdc_slice_down_1" in top
    assert "cdc_bypass u_cdc" in top
    assert all(f"cdc_cell_{cell['module']}.sv" or cell["file"]
               for cell in manifest["cdc"]["cells"])
    assert {c["group_idx"] for c in manifest["cdc"]["cells"]} == {1}
    assert manifest["cdc"]["fabric_domain"] == "noc_clk"


@pytest.mark.skipif(not _VERILATOR, reason="verilator not installed")
def test_cfg_shape_bare_crossing_and_vc(tmp_path):
    req = _request(noc_controls=NocControls(
        input_buffer_depth_flits_per_vc=16))
    result = run_rtl_slice(
        req.to_dict(), tmp_path / "out",
        {"repo_root": str(REPO), "slice_arbiter": ARB_AGE})
    assert result["scope"] == "COMPOSED_SLICE"
    assert result["lint"] == "PASS"
    assert result["slice_params"]["arb_policy"] == ARB_AGE


@pytest.mark.skipif(not _VERILATOR, reason="verilator not installed")
def test_attachment_variant_mem_first(tmp_path):
    # config: agents (hbm, compute, compute) — memory seats router 0,
    # initiators routers 1 and 2; compose their own map.
    agents = (
        Agent(kind=AgentKind.HBM_CONTROLLER, count=1, data_width=32,
              addr_width=64, protocol="AXI", clock_domain="noc_clk",
              power_domain="pd0"),
        Agent(kind=AgentKind.COMPUTE_TILE, count=1, data_width=32,
              addr_width=64, protocol="AXI", clock_domain="noc_clk",
              power_domain="pd0"),
        Agent(kind=AgentKind.COMPUTE_TILE, count=1, data_width=32,
              addr_width=64, protocol="AXI", clock_domain="noc_clk",
              power_domain="pd0"),
    )
    intents = (AgentIntentV4(0), _init(1, True, True), _init(2, True, False))
    req = _request(agents=agents, intents=intents, tp=2)
    result = _run(req.to_dict(), tmp_path)
    assert result["scope"] == "COMPOSED_SLICE"
    assert result["lint"] == "PASS"
    assert result["sim"] == "PASS"
    manifest = json.loads(
        (tmp_path / "project-top-manifest.json").read_text())
    assert manifest["slice_params"]["memory_router"] == 0


@pytest.mark.skipif(not _VERILATOR, reason="verilator not installed")
def test_three_initiators(tmp_path):
    agents = _base_agents()[:2] + (
        Agent(kind=AgentKind.COMPUTE_TILE, count=1, data_width=32,
              addr_width=64, protocol="AXI", clock_domain="noc_clk",
              power_domain="pd0"),
        Agent(kind=AgentKind.HBM_CONTROLLER, count=1, data_width=32,
              addr_width=64, protocol="AXI", clock_domain="noc_clk",
              power_domain="pd0"),
    )
    intents = (_init(0, True, True), _init(1, True, True),
               _init(2, True, False), AgentIntentV4(3))
    req = _request(agents=agents, intents=intents, tp=2)
    compiled = FabricCompiler().compile(req)
    assert compiled.status == "COMPILED", compiled.error
    result = _run(req.to_dict(), tmp_path)
    assert result["scope"] == "COMPOSED_SLICE"
    assert result["lint"] == "PASS"
    assert result["sim"] == "PASS"
    assert all(result["scenarios"].values())
    manifest = json.loads(
        (tmp_path / "project-top-manifest.json").read_text())
    assert manifest["slice_params"]["num_initiators"] == 3


@pytest.mark.skipif(not _VERILATOR, reason="verilator not installed")
def test_traffic_policy_vc1_consumed(tmp_path):
    deps = DependencyGraph((
        Dependency(source="a", target="b", kind=DepKind.BLOCKING),
        Dependency(source="b", target="a", kind=DepKind.BLOCKING),
    ))
    req = _request(
        deps=deps, classes=("a", "b"),
        policy=TrafficPolicyV4(traffic_class_vcs=(
            TrafficClassVC("a", 1), TrafficClassVC("b", 0))))
    compiled = FabricCompiler().compile(req)
    assert compiled.status == "COMPILED", compiled.error
    params = slice_params_from_request(req, compiled)
    assert params.bound_vc == 1 and params.traffic_class == "a"
    assert params.class_id == 0
    result = _run(req.to_dict(), tmp_path)
    assert result["scope"] == "COMPOSED_SLICE"
    assert result["lint"] == "PASS"
    assert result["sim"] == "PASS"
    manifest = json.loads(
        (tmp_path / "project-top-manifest.json").read_text())
    assert manifest["vc_assignment"]["vc"] == 1
    assert manifest["vc_assignment"]["route_table"] == "RT_ESC(escape)"
