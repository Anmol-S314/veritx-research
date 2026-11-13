from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest

from veritx_dse.model.agent_intent_v4 import (
    AgentIntentV4, OrderingMode, PermissionWindow, ProtocolFamily,
)
from veritx_dse.model.compile_model import (
    AddressMap, AddressRange, Agent, AgentKind, CollectiveDimension,
    CollectiveIntent, CollectiveKind, DependencyGraph, ModelFamily,
    WorkloadV3, PhysicalContext,
)
from veritx_dse.model.compile_request_v4 import CompileRequestV4
from veritx_dse.model.topology_intent import MeshIntent
from veritx_dse.product.project_top_rtl import (
    SLICE_DUT_FILES, SLICE_TB_FILES, check_slice_profile,
    render_cdc_bypass, render_destination_adapter, render_project_top,
    render_tb_project_top, run_rtl_slice,
)
from veritx_dse.application.fabric_compiler import FabricCompiler
from veritx_dse.core.paths import REPO


def _slice_request() -> CompileRequestV4:
    workload = WorkloadV3(
        model_family=ModelFamily.DENSE_TRANSFORMER, tp=2, pp=1, ep=1, dp=1,
        collectives=(CollectiveIntent(
            kind=CollectiveKind.ALLREDUCE, dimension=CollectiveDimension.TP,
            payload_bytes=8192, traffic_class="tp_collective"),))
    agents = (
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
    intents = (
        AgentIntentV4(0, protocol=ProtocolFamily.AXI5,
                      ordering=OrderingMode.STRONG, max_outstanding=4,
                      permission_windows=(PermissionWindow(
                          "HBM0", readable=True, writable=True, atomic=False),)),
        AgentIntentV4(1, protocol=ProtocolFamily.AXI5,
                      ordering=OrderingMode.STRONG, max_outstanding=4,
                      permission_windows=(PermissionWindow(
                          "HBM0", readable=True, writable=False, atomic=False),)),
        AgentIntentV4(2),
    )
    return CompileRequestV4(
        workload=workload, agents=agents,
        dependencies=DependencyGraph(()),
        topology=MeshIntent(side_length=2, concentration=1),
        address_map=AddressMap(ranges=(
            AddressRange(name="HBM0", base=0x1000, size=0x1000,
                         target_agent_idx=2),)),
        agent_intents=intents)


def test_slice_renderers_are_deterministic():
    assert render_cdc_bypass() == render_cdc_bypass()
    assert render_destination_adapter() == render_destination_adapter()
    assert render_project_top() == render_project_top()
    assert render_tb_project_top() == render_tb_project_top()
    assert "module cdc_bypass" in render_cdc_bypass()
    assert "assign out_flit = in_flit" in render_cdc_bypass()
    assert "assign out_valid = in_valid" in render_cdc_bypass()
    assert "cdc_fifo" not in render_cdc_bypass()
    assert "module destination_adapter" in render_destination_adapter()
    assert "module project_top" in render_project_top()
    assert "module initiator_slice" in render_project_top()
    assert "module tb_project_top" in render_tb_project_top()
    assert "noc_top u_noc" in render_project_top()
    assert "addr_decode u_decode" in render_project_top()
    assert "ordering_fsm u_ordering" in render_project_top()
    assert "cdc_bypass u_cdc" in render_project_top()
    assert "destination_adapter" in render_project_top()
    assert "awid_in" in render_project_top()
    assert "wstrb_in" in render_project_top()
    assert "arlen_in" in render_project_top()
    assert "S_CAPW" in render_project_top()
    assert "S_AWRET" in render_project_top()
    assert "burst_len" in render_project_top().lower() or "burst_len" in render_project_top()
    assert "do_burst_write0" in render_tb_project_top()
    assert "do_burst_read0" in render_tb_project_top()


def test_slice_profile_compiles_and_passes_guard():
    request = _slice_request()
    compiled = FabricCompiler().compile(request)
    assert compiled.status == "COMPILED", compiled.error
    check_slice_profile(request, compiled)


def test_slice_refuses_non_slice_profiles(tmp_path):
    from dataclasses import replace
    base = _slice_request()
    cases = []
    cases.append(("mesh surface", replace(base, topology=MeshIntent(side_length=9, concentration=1))))
    cases.append(("protocol", _slice_request_and_chi(base)))
    cases.append(("atomic", _slice_request_and_atomic(base)))
    cases.append(("router pipeline", _slice_request_and_pipe_ctl(base)))
    cases.append(("arb islip", _slice_request_and_arb(base)))
    cases.append(("region", replace(base, address_map=AddressMap(ranges=(
        AddressRange(name="HBM0", base=0x2000, size=0x1000, target_agent_idx=2),)))))
    for name, request in cases:
        compiled = FabricCompiler().compile(request)
        with pytest.raises(ValueError, match="UNSUPPORTED_SLICE_PROFILE") as exc:
            check_slice_profile(request, compiled)
        assert "RTL generation" in str(exc.value)
        assert "ProjectTop" in str(exc.value)
        out = tmp_path / name.replace(" ", "_")
        with pytest.raises(ValueError, match="UNSUPPORTED_SLICE_PROFILE"):
            run_rtl_slice(request.to_dict(), out, {"repo_root": str(REPO)})
        assert not (out / "project-top-manifest.json").exists()


def _slice_request_and_multiclock(base):
    from dataclasses import replace
    return replace(base, agents=(
        base.agents[0],
        replace(base.agents[1], clock_domain="other_clk"),
        base.agents[2],
    ))


def _slice_request_and_chi(base):
    from dataclasses import replace
    intents = (
        replace(base.agent_intents[0], protocol=ProtocolFamily.CHI),
        base.agent_intents[1], base.agent_intents[2],
    )
    return replace(base, agent_intents=intents)


def _slice_request_and_atomic(base):
    from dataclasses import replace
    intents = (
        base.agent_intents[0],
        replace(base.agent_intents[1], permission_windows=(
            PermissionWindow("HBM0", readable=True, writable=False, atomic=True),)),
        base.agent_intents[2],
    )
    return replace(base, agent_intents=intents)


def _slice_request_and_pipe_ctl(base):
    from dataclasses import replace
    return replace(base, noc_controls=replace(
        base.noc_controls, credit_return_latency_cycles=3))


def _slice_request_and_arb(base):
    from dataclasses import replace
    return replace(base, noc_controls=replace(
        base.noc_controls, arbitration="islip"))


def test_composed_slice_lints_and_sims_on_the_top(tmp_path):
    if shutil.which("verilator") is None:
        pytest.skip("verilator not installed; cannot lint/sim the composed top")
    request = _slice_request()
    result = run_rtl_slice(request.to_dict(), tmp_path, {"repo_root": str(REPO)})
    assert result["scope"] == "COMPOSED_SLICE"
    assert result["development_milestone"] is True
    assert result["final_implementation"] is False
    assert result["lint"] == "PASS"
    manifest = json.loads((tmp_path / "project-top-manifest.json").read_text())
    assert result["sim"] == "PASS", manifest["sim"].get("log", result["scenarios"])
    assert len(result["scenarios"]) == 18, result["scenarios"]
    assert all(result["scenarios"].values()), result["scenarios"]
    router_src = (tmp_path / "rtl" / "router.sv").read_text()
    assert '`include "noc_pkg.sv"' not in router_src
    assert "automatic bit ej_done_mark;" in router_src
    assert "automatic int c2;" in router_src
    assert "automatic int fsp;" in router_src
    assert "automatic int esp;" in router_src
    # An initialised declaration inside a block is split: the declaration
    # moves to the block top and the initialiser stays where it stood, which
    # is the form a synthesis front-end accepts.
    assert "automatic int lv;" in router_src
    assert "lv = get_class(" in router_src
    top_src = (tmp_path / "rtl" / "project_top.sv").read_text()
    assert "beat_idx_q[12:0]" not in top_src
    assert "cap_seq_q + {4'b0, beat_idx_q}" in top_src
    assert ".in_awburst(2'b01)" in top_src
    assert result["scenarios"].get("burst_allowed") is True
    assert result["scenarios"].get("burst_crossing_denied") is True
    assert result["scenarios"].get("wstrb_enforcement") is True
    assert result["scenarios"].get("burst_backpressure") is True
    assert result["scenarios"].get("id_isolation") is True
    assert result["preview_scope"] == "TOPOLOGY_ONLY_PREVIEW"
    preview_manifest = json.loads((tmp_path / "rtl-preview.json").read_text())
    assert preview_manifest["scope"] == "TOPOLOGY_ONLY_PREVIEW"
    assert preview_manifest["final_implementation"] is False
    assert (tmp_path / "rtl" / "noc_top.sv").is_file()
    assert (tmp_path / "rtl" / "addr_decode.sv").is_file()
    assert (tmp_path / "rtl" / "project_top.sv").is_file()
    assert manifest["scope"] == "COMPOSED_SLICE"
    assert manifest["lint"]["status"] == "PASS"
    assert manifest["sim"]["status"] == "PASS"
    assert manifest["lint"]["clean"] == (manifest["lint"]["warning_count"] == 0)
    assert manifest["lint"]["warning_count"] > 0
    lint_log = manifest["lint"]["log"]
    for banned in ("LATCH", "MODDUP", "SELRANGE"):
        assert banned not in lint_log, banned
    assert manifest["final_implementation"] is False
    modules = {row["module"] for row in manifest["hierarchy"]}
    assert len(modules) >= 6, modules
    hierarchy_text = " ".join(manifest["hierarchy"][i]["instance"] for i in range(len(manifest["hierarchy"])))
    assert "project_top" in hierarchy_text and "u_noc" in hierarchy_text
    assert manifest["sidecar"]["scope"] == "TOPOLOGY_ONLY_PREVIEW"
    assert "STA" in " ".join(manifest["not_established"])
    assert "Formal" in " ".join(manifest["not_established"]) or "formal" in " ".join(manifest["not_established"])
    assert manifest["proven"], "proven rows must be non-empty"
    for row in manifest["files"]:
        assert row["path"] in SLICE_TB_FILES
        assert (tmp_path / "rtl" / row["path"]).is_file()
        assert len(row["sha256"]) == 64
    makefile = (tmp_path / "rtl" / "Makefile").read_text()
    assert "lint-slice:" in makefile
    assert "project_top" in makefile
    for name in SLICE_DUT_FILES:
        assert name in makefile or name in manifest["files"][0].__str__()
    assert manifest["iverilog"]["status"] in ("NOT_RUN", "PASS")
    if manifest["iverilog"]["status"] == "NOT_RUN":
        assert "router" in manifest["iverilog"]["reason"] or "iverilog" in manifest["iverilog"]["reason"].lower()
    assert (tmp_path / "project-top.zip").is_file()
    assert (tmp_path / "topology-rtl-preview.zip").is_file()
def _family_agents():
    from veritx_dse.model.compile_model import Agent, AgentKind
    agents = (Agent(kind=AgentKind.COMPUTE_TILE, count=1, data_width=32, addr_width=64, protocol="AXI", clock_domain="noc_clk", power_domain="pd0"), Agent(kind=AgentKind.COMPUTE_TILE, count=1, data_width=32, addr_width=64, protocol="AXI", clock_domain="noc_clk", power_domain="pd0"), Agent(kind=AgentKind.HBM_CONTROLLER, count=1, data_width=32, addr_width=64, protocol="AXI", clock_domain="noc_clk", power_domain="pd0"))
    return agents
def _family_intents():
    from veritx_dse.model.agent_intent_v4 import AgentIntentV4, OrderingMode, PermissionWindow, ProtocolFamily
    intents = (AgentIntentV4(0, protocol=ProtocolFamily.AXI5, ordering=OrderingMode.STRONG, max_outstanding=4, permission_windows=(PermissionWindow("HBM0", readable=True, writable=True, atomic=False),)), AgentIntentV4(1, protocol=ProtocolFamily.AXI5, ordering=OrderingMode.STRONG, max_outstanding=4, permission_windows=(PermissionWindow("HBM0", readable=True, writable=False, atomic=False),)), AgentIntentV4(2))
    return intents
def _family_request(intent):
    from veritx_dse.model.compile_model import AddressMap, AddressRange, CollectiveDimension, CollectiveIntent, CollectiveKind, DependencyGraph, ModelFamily, WorkloadV3
    from veritx_dse.model.compile_request_v4 import CompileRequestV4
    workload = WorkloadV3(model_family=ModelFamily.DENSE_TRANSFORMER, tp=2, pp=1, ep=1, dp=1, collectives=(CollectiveIntent(kind=CollectiveKind.ALLREDUCE, dimension=CollectiveDimension.TP, payload_bytes=8192, traffic_class="tp_collective"),))
    return CompileRequestV4(workload=workload, agents=_family_agents(), dependencies=DependencyGraph(()), topology=intent, address_map=AddressMap(ranges=(AddressRange(name="HBM0", base=0x1000, size=0x1000, target_agent_idx=2),)), physical=PhysicalContext(default_clock_freq_mhz=1000), agent_intents=_family_intents())
def _family_intents_for(intent):
    from veritx_dse.model.topology_intent import ConcentratedMeshIntent, FatTreeIntent, FlatFlyIntent, FlyIntent, GecTopologyIntent, GecMode, MeshIntent, QTreeIntent, RingIntent, StructuredTopologyIntent, TorusIntent, Tree4Intent
    table = []
    table.append(("torus", intent if getattr(intent, "kind", None) == "torus" else TorusIntent(3, 1)))
    return table
@pytest.mark.parametrize("group_idx", (0, 1))
def test_composed_family_never_drops_agent_instances(tmp_path, monkeypatch, group_idx):
    from dataclasses import replace
    from veritx_dse.product.project_top_rtl import (
        UNSUPPORTED_COMPOSED_FAMILY, composed_family_params_from_request,
        run_composed_family,
    )
    from veritx_dse.product import rtl_export

    base = _family_request(MeshIntent(4, 1))
    agents = tuple(replace(agent, count=2) if idx == group_idx else agent
                   for idx, agent in enumerate(base.agents))
    request = replace(base, agents=agents)
    compiled = FabricCompiler().compile(request)
    assert compiled.status == "COMPILED", compiled.error
    assert len(compiled.bundle.attachment.endpoints) == 4

    def forbidden(*args, **kwargs):
        pytest.fail("Lossy endpoint mapping must be refused before preview emission")

    monkeypatch.setattr(rtl_export, "run_rtl_preview", forbidden)
    params = composed_family_params_from_request(request, compiled)
    doubled = [i for i in params.initiators if i.group_idx == group_idx]
    assert len(doubled) == 2, params.initiators
    assert sorted(i.instance_index for i in doubled) == [0, 1]
    assert len({i.router_id for i in doubled}) == 2
    assert len(params.initiators) == 3


def test_family_router_interface_deterministic():
    from veritx_dse.model.topology_intent import TorusIntent
    from veritx_dse.application.fabric_compiler import FabricCompiler
    from veritx_dse.product.project_top_rtl import build_family_router, composed_family_params_from_request
    req = _family_request(TorusIntent(3, 1))
    compiled = FabricCompiler().compile(req)
    assert compiled.status == "COMPILED"
    params = composed_family_params_from_request(req, compiled)
    files = build_family_router(params, compiled.bundle.topology)
    assert set(files.keys()) == {"noc_pkg.sv", "router.sv", "noc_top.sv"}
    assert "module router" in files["router.sv"]
    assert "module noc_top" in files["noc_top.sv"]
    assert "package noc_pkg" in files["noc_pkg.sv"]
    assert "N_ROUTERS = 9" in files["noc_pkg.sv"]
    files2 = build_family_router(params, compiled.bundle.topology)
    assert files == files2
    assert params.family == "torus"
    assert params.routing_law == "DOR_TORUS_XY"
    assert params.n_routers == 9
def test_family_destination_adapter_retains_request_source_endpoint():
    from veritx_dse.model.topology_intent import MeshIntent
    from veritx_dse.product.project_top_rtl import (
        _render_family_destination, composed_family_params_from_request,
    )

    request = _family_request(MeshIntent(3, 1))
    compiled = FabricCompiler().compile(request)
    assert compiled.status == "COMPILED", compiled.error
    params = composed_family_params_from_request(request, compiled)
    source = _render_family_destination(params)
    assert "src_q <= init_w;" in source
    assert "init_q" not in source


def test_non_slice_mesh_profile_has_composed_family_contract():
    from veritx_dse.model.topology_intent import MeshIntent
    from veritx_dse.application.fabric_compiler import FabricCompiler
    from veritx_dse.product.project_top_rtl import check_composed_family_profile, composed_family_params_from_request
    req = _family_request(MeshIntent(3, 1))
    compiled = FabricCompiler().compile(req)
    assert compiled.status == "COMPILED"
    check_composed_family_profile(req, compiled)
    params = composed_family_params_from_request(req, compiled)
    assert params.family == "mesh"
    assert params.n_routers == 9
@pytest.mark.parametrize("fam_name,intent_maker", [("torus", "torus"), ("cmesh", "cmesh"), ("mesh", "mesh8"), ("ring", "ring"), ("flatfly", "flatfly"), ("fly", "fly"), ("qtree", "qtree"), ("tree4", "tree4"), ("dragonflynew", "dragonfly"), ("gec_express", "gec"), ("gec_mecs", "gec_mecs"), ("fattree", "fattree")])
def test_composed_family_lints_and_sims(tmp_path, fam_name, intent_maker):
    if shutil.which("verilator") is None:
        pytest.skip("verilator not installed")
    from veritx_dse.model.topology_intent import ConcentratedMeshIntent, FatTreeIntent, FlatFlyIntent, FlyIntent, GecTopologyIntent, GecMode, MeshIntent, QTreeIntent, RingIntent, StructuredTopologyIntent, TorusIntent, Tree4Intent
    from veritx_dse.product.project_top_rtl import (
        composed_family_params_from_request, run_composed_family,
    )
    from veritx_dse.core.paths import REPO as _REPO
    intents = {"torus": TorusIntent(3, 1), "cmesh": ConcentratedMeshIntent(4, 4), "mesh8": MeshIntent(3, 1), "ring": RingIntent(64), "flatfly": FlatFlyIntent(4, 2, 1), "fly": FlyIntent(4, 3), "qtree": QTreeIntent(4, 3), "tree4": Tree4Intent(4, 3), "dragonfly": StructuredTopologyIntent("dragonfly", {"radix": 4, "group_count": 3}), "gec": GecTopologyIntent(GecMode.EXPRESS, 2, 1, 1, 1), "gec_mecs": GecTopologyIntent(GecMode.MULTIDROP, 4, 1, 1, 3), "fattree": FatTreeIntent(4, 2)}
    intent = intents[intent_maker]
    req = _family_request(intent)
    compiled = FabricCompiler().compile(req)
    assert compiled.status == "COMPILED", compiled.error
    _seats = [(int(e.endpoint_id), int(e.agent.group_index),
               int(getattr(e.agent, "instance_index", 0)), int(e.router_id),
               int(getattr(e, "port_id", 0)))
              for e in compiled.bundle.attachment.endpoints]
    from veritx_dse.product.project_top_rtl import ENDPOINT_TAGGED_FAMILIES
    if (len({s[3] for s in _seats}) != len(_seats)
            and fam_name not in ENDPOINT_TAGGED_FAMILIES and fam_name != "cmesh"):
        with pytest.raises(ValueError, match="multiple endpoint seats on one router|shares its router with initiator seats"):
            composed_family_params_from_request(req, compiled)
        with pytest.raises(ValueError, match="multiple endpoint seats on one router|shares its router with initiator seats"):
            run_composed_family(req.to_dict(), tmp_path, {"repo_root": str(_REPO)})
        assert not (tmp_path / "project-top-manifest.json").exists()
        return
    params = composed_family_params_from_request(req, compiled)
    result = run_composed_family(req.to_dict(), tmp_path, {"repo_root": str(_REPO)})
    assert result["scope"] == "COMPOSED_FAMILY"
    assert result["family"] == params.family
    assert result["lint"] == "PASS"
    assert result["lint_clean"] == True
    assert result["lint_warning_count"] == 0
    manifest = json.loads((tmp_path / "project-top-manifest.json").read_text())
    preview_manifest = json.loads((tmp_path / "rtl-preview.json").read_text())
    assert preview_manifest["source_topology"] == manifest["source_topology"]
    if fam_name == "fly":
        assert preview_manifest["status"] == "NOT_EMITTED"
        assert not (tmp_path / "preview_dummy").exists()
        meta = json.loads((tmp_path / "rtl" / "meta.json").read_text())
        assert meta["source_topology"] == manifest["source_topology"]
        assert meta["n_routers"] == manifest["family_params"]["n_routers"]
        assert "anynet" not in meta
    assert result["sim"] == "PASS", manifest["sim"].get("log", result["sim"])
    assert len(result["scenarios"]) >= 10
    assert all(result["scenarios"].values()), manifest["sim"].get("log", result["scenarios"])
    assert manifest["scope"] == "COMPOSED_FAMILY"
    assert manifest["lint"]["status"] == "PASS"
    assert manifest["sim"]["status"] == "PASS"
    assert manifest["family_params"]["family"] == params.family
    assert manifest["emitted_packet_width_bits"] == manifest["family_params"]["flit_w"]
    assert manifest["emitted_vcs"] == manifest["family_params"]["vc_count"]
    if fam_name == "gec_mecs":
        assert result["final_implementation"] is False
        assert all(result["scenarios"].values())
        assert manifest["ordering_realization"]["requested_max_outstanding_per_initiator"] == 4
        assert manifest["ordering_realization"]["effective_max_outstanding_per_initiator"] == 4
        # The limit is measured by the emitted S15 probe, not declared: the
        # manifest must carry the observed value next to the declared one.
        assert manifest["ordering_realization"]["declared_max_outstanding_per_initiator"] == 4
        assert manifest["ordering_realization"]["measured_max_outstanding_per_initiator"] == 4
        assert "MEASURE: max_outstanding_per_initiator=4" in manifest["sim"]["log"]
        assert any(row["module"] == "gec_mecs16_fabric" for row in manifest["hierarchy"])
        assert "%Warning-UNDRIVEN" not in manifest["lint"].get("log", "")
    mods = {row["module"] for row in manifest["hierarchy"]}
    assert "project_top" in mods
    assert "noc_top" in mods
    assert "initiator_slice" in mods
    assert "destination_adapter" in mods
    text = " ".join(row["instance"] for row in manifest["hierarchy"])
    assert "u_noc" in text
    makefile = (tmp_path / "rtl" / "Makefile").read_text()
    assert "lint-slice:" in makefile
    assert "project_top" in makefile
    assert (tmp_path / "project-top.zip").is_file()


def _param_request(topology, buf=8, data_width=32, deps=None, policy=None, agents=None):
    from veritx_dse.model.agent_intent_v4 import TrafficPolicyV4
    from veritx_dse.model.noc_controls import NocControls
    workload = WorkloadV3(
        model_family=ModelFamily.DENSE_TRANSFORMER, tp=2, pp=1, ep=1, dp=1,
        collectives=(CollectiveIntent(
            kind=CollectiveKind.ALLREDUCE, dimension=CollectiveDimension.TP,
            payload_bytes=8192, traffic_class="tp_collective"),))
    if agents is None:
        agents = (
            Agent(kind=AgentKind.COMPUTE_TILE, count=1, data_width=data_width,
                  addr_width=64, protocol="AXI", clock_domain="noc_clk",
                  power_domain="pd0"),
            Agent(kind=AgentKind.COMPUTE_TILE, count=1, data_width=data_width,
                  addr_width=64, protocol="AXI", clock_domain="noc_clk",
                  power_domain="pd0"),
            Agent(kind=AgentKind.HBM_CONTROLLER, count=1, data_width=data_width,
                  addr_width=64, protocol="AXI", clock_domain="noc_clk",
                  power_domain="pd0"),
        )
    intents = (
        AgentIntentV4(0, protocol=ProtocolFamily.AXI5,
                      ordering=OrderingMode.STRONG, max_outstanding=4,
                      permission_windows=(PermissionWindow(
                          "HBM0", readable=True, writable=True, atomic=False),)),
        AgentIntentV4(1, protocol=ProtocolFamily.AXI5,
                      ordering=OrderingMode.STRONG, max_outstanding=4,
                      permission_windows=(PermissionWindow(
                          "HBM0", readable=True, writable=False, atomic=False),)),
        AgentIntentV4(2),
    )
    return CompileRequestV4(
        workload=workload, agents=agents,
        dependencies=deps if deps is not None else DependencyGraph(()),
        topology=topology,
        address_map=AddressMap(ranges=(
            AddressRange(name="HBM0", base=0x1000, size=0x1000,
                         target_agent_idx=2),)),
        agent_intents=intents,
        traffic_policy=policy if policy is not None else TrafficPolicyV4(),
        noc_controls=NocControls(input_buffer_depth_flits_per_vc=buf))


def test_parameterized_sizes_params_deterministic_and_mutating():
    from hashlib import sha256 as _sha256
    from veritx_dse.model.topology_intent import MeshIntent, RingIntent, TorusIntent
    from veritx_dse.product.project_top_rtl import (
        composed_family_params_from_request, render_family_project_top,
        render_family_tb, slice_params_from_request,
    )
    cases = []
    for side in (2, 3, 4, 5, 6, 7, 8):
        cases.append((f"mesh{side}", MeshIntent(side, 1), side * side))
    for side in (3, 5, 8):
        cases.append((f"torus{side}", TorusIntent(side, 1), side * side))
    for count in (4, 8, 16, 32, 64):
        cases.append((f"ring{count}", RingIntent(count), count))
    seen_top = set()
    for name, topo, n in cases:
        req = _param_request(topo)
        compiled = FabricCompiler().compile(req)
        assert compiled.status == "COMPILED", (name, compiled.error)
        params = slice_params_from_request(req, compiled)
        assert params.n_routers == n, name
        assert params.topo_side == (getattr(topo, "side_length", getattr(topo, "router_count", None)))
        assert params.data_width == 32
        assert params.vc_count == 2
        assert params.flit_w == 64
        assert params.dst_w == max(1, (n - 1).bit_length())
        assert len(params.spare_routers) == n - params.num_initiators - 1
        assert params.to_dict()["n_routers"] == n
        assert params.to_dict()["buf_depth_per_vc"] == [8, 8]
        family_params = composed_family_params_from_request(req, compiled)
        top1 = render_family_project_top(family_params)
        top2 = render_family_project_top(family_params)
        assert top1 == top2, name
        tb1 = render_family_tb(family_params)
        tb2 = render_family_tb(family_params)
        assert tb1 == tb2, name
        seen_top.add(_sha256(top1.encode()).hexdigest())
    assert len(seen_top) > 1, "top must mutate with size"


def test_parameterized_buf_and_vc_params():
    from veritx_dse.model.compile_model import Dependency, DepKind, DependencyGraph
    from veritx_dse.model.agent_intent_v4 import TrafficClassVC, TrafficPolicyV4
    from veritx_dse.model.topology_intent import MeshIntent
    from veritx_dse.product.project_top_rtl import (
        composed_family_params_from_request, render_family_project_top,
        slice_params_from_request,
    )
    topo = MeshIntent(4, 1)
    for buf in (4, 8, 16):
        req = _param_request(topo, buf=buf)
        compiled = FabricCompiler().compile(req)
        assert compiled.status == "COMPILED", compiled.error
        params = slice_params_from_request(req, compiled)
        assert params.buf_depth == buf
        assert params.to_dict()["buf_depth_per_vc"] == [buf, buf]
        family_params = composed_family_params_from_request(req, compiled)
        assert render_family_project_top(family_params) == render_family_project_top(family_params)
    deps1 = DependencyGraph((
        Dependency(source="a", target="b", kind=DepKind.BLOCKING),
        Dependency(source="b", target="a", kind=DepKind.BLOCKING),
    ))
    pol1 = TrafficPolicyV4(traffic_class_vcs=(
        TrafficClassVC("a", 1), TrafficClassVC("b", 0)))
    req1 = _param_request(topo, deps=deps1, policy=pol1)
    compiled1 = FabricCompiler().compile(req1)
    assert compiled1.status == "COMPILED", compiled1.error
    p1 = slice_params_from_request(req1, compiled1)
    assert p1.vc_count == 2
    assert p1.bound_vc == 1
    assert p1.traffic_class == "a"
    family_p1 = composed_family_params_from_request(req1, compiled1)
    assert render_family_project_top(family_p1) == render_family_project_top(family_p1)
    req0 = _param_request(topo)
    compiled0 = FabricCompiler().compile(req0)
    assert compiled0.status == "COMPILED", compiled0.error
    p0 = slice_params_from_request(req0, compiled0)
    assert p0.vc_count == 2
    assert p0.bound_vc == 0
    assert p0.to_dict() != p1.to_dict()
    assert p0.bound_vc != p1.bound_vc
    family_p0 = composed_family_params_from_request(req0, compiled0)
    assert render_family_project_top(family_p0) == render_family_project_top(family_p0)
    from veritx_dse.product.ordering_fsm_rtl import build_ordering_fsm, policy_from_request
    _pol0 = policy_from_request(req0)
    _pol1 = policy_from_request(req1)
    _em0 = build_ordering_fsm(_pol0, emitted_vcs=2, shared_wires=0)
    _em1 = build_ordering_fsm(_pol1, emitted_vcs=2, shared_wires=0)
    assert _em0.sv_source is not None and _em1.sv_source is not None
    assert _em0.sv_source != _em1.sv_source


def test_parameterized_width_and_vc4_composes(tmp_path):
    from veritx_dse.model.compile_model import Dependency, DepKind, DependencyGraph
    from veritx_dse.model.agent_intent_v4 import TrafficClassVC, TrafficPolicyV4
    from veritx_dse.model.topology_intent import MeshIntent
    from veritx_dse.product.project_top_rtl import render_destination_adapter, render_tb_project_top, slice_params_from_request
    for w, exp_flit in ((64, 96), (128, 160)):
        req = _param_request(MeshIntent(2, 1), data_width=w)
        compiled = FabricCompiler().compile(req)
        assert compiled.status == "COMPILED", compiled.error
        params = slice_params_from_request(req, compiled)
        assert params.data_width == w
        assert params.flit_w == exp_flit
        top = render_project_top(params)
        assert f"DATA_W_IN({w})" in top
        dest = render_destination_adapter(params)
        assert f"logic [{w - 1}:0] sram" in dest
        tb = render_tb_project_top(params)
        assert f"[{w - 1}:0] init0_wdata" in tb or f"[{w - 1}:0]" in tb
        if shutil.which("verilator") is not None:
            result = run_rtl_slice(req.to_dict(), tmp_path / f"w{w}", {"repo_root": str(REPO)})
            assert result["lint"] == "PASS"
            assert result["sim"] == "PASS", result["scenarios"]
            assert all(result["scenarios"].values()), result["scenarios"]
            manifest_src = (tmp_path / f"w{w}" / "rtl" / "noc_pkg.sv").read_text()
            assert f"FLIT_W      = {exp_flit}" in manifest_src
            assert "NUM_VCS     = 2" in manifest_src
    deps4 = DependencyGraph((
        Dependency(source="a", target="b", kind=DepKind.BLOCKING),
        Dependency(source="b", target="a", kind=DepKind.BLOCKING),
        Dependency(source="c", target="d", kind=DepKind.BLOCKING),
        Dependency(source="d", target="c", kind=DepKind.BLOCKING),
        Dependency(source="e", target="f", kind=DepKind.BLOCKING),
        Dependency(source="f", target="e", kind=DepKind.BLOCKING),
    ))
    pol4 = TrafficPolicyV4(traffic_class_vcs=(
        TrafficClassVC("a", 1), TrafficClassVC("b", 0),
        TrafficClassVC("c", 2), TrafficClassVC("d", 0),
        TrafficClassVC("e", 3), TrafficClassVC("f", 0),
        TrafficClassVC("tp_collective", 0)))
    req4 = _param_request(MeshIntent(2, 1), deps=deps4, policy=pol4)
    compiled4 = FabricCompiler().compile(req4)
    assert compiled4.status == "COMPILED", compiled4.error
    p4 = slice_params_from_request(req4, compiled4)
    assert p4.vc_count == 4
    assert p4.vcw == 2
    assert p4.flit_w == 65
    top4 = render_project_top(p4)
    assert "VC_W(2)" in top4
    if shutil.which("verilator") is not None:
        result4 = run_rtl_slice(req4.to_dict(), tmp_path / "vc4", {"repo_root": str(REPO)})
        assert result4["lint"] == "PASS"
        assert result4["sim"] == "PASS", result4["scenarios"]
        shp = tmp_path / "vc4" / "rtl"
        assert "NUM_VCS     = 4" in (shp / "noc_pkg.sv").read_text()
        assert "FLIT_W      = 65" in (shp / "noc_pkg.sv").read_text()
        router_src = (shp / "router.sv").read_text()
        assert "show_vc [0:NUM_PORTS-1]" in router_src
        assert "(c % NUM_VCS) != 0" in router_src
        assert "^in_class === 1'bx" in router_src
        assert "VC_W" in (shp / "ordering_fsm.sv").read_text() or "vc_of_class" in (shp / "ordering_fsm.sv").read_text()


def test_parameterized_multiclock_large_composes(tmp_path):
    from dataclasses import replace
    from veritx_dse.model.topology_intent import MeshIntent
    from veritx_dse.product.project_top_rtl import (
        composed_family_params_from_request, render_family_initiator_slice,
        render_family_project_top, run_composed_family,
        slice_params_from_request,
    )
    base = _param_request(MeshIntent(4, 1))
    agents = (
        base.agents[0],
        replace(base.agents[1], clock_domain="other_clk"),
        base.agents[2],
    )
    req = replace(base, agents=agents)
    compiled = FabricCompiler().compile(req)
    assert compiled.status == "COMPILED", compiled.error
    params = slice_params_from_request(req, compiled)
    assert params.crossed_groups == (1,)
    family_params = composed_family_params_from_request(req, compiled)
    top = render_family_project_top(family_params)
    slice_src = render_family_initiator_slice(family_params)
    # The crossed group's CDC cells are in the slice's own file.
    assert "cdc_slice_up_1" in slice_src and "cdc_slice_down_1" in slice_src
    if shutil.which("verilator") is not None:
        result = run_composed_family(req.to_dict(), tmp_path, {"repo_root": str(REPO)})
        assert result["lint"] == "PASS"
        manifest = json.loads((tmp_path / "project-top-manifest.json").read_text())
        assert result["sim"] == "PASS", manifest["sim"].get("log", result["scenarios"])
        tb_src = (tmp_path / "rtl" / "tb_project_top.sv").read_text()
        assert "clk_d0" in tb_src


@pytest.mark.parametrize("side", [(4, "mesh4")])
def test_parameterized_mesh4_buf4_lints_and_sims(tmp_path, side):
    if shutil.which("verilator") is None:
        pytest.skip("verilator not installed")
    from veritx_dse.model.topology_intent import MeshIntent
    from veritx_dse.product.project_top_rtl import run_composed_family
    req = _param_request(MeshIntent(4, 1), buf=4)
    result = run_composed_family(req.to_dict(), tmp_path, {"repo_root": str(REPO)})
    manifest = json.loads((tmp_path / "project-top-manifest.json").read_text())
    assert result["lint"] == "PASS"
    assert result["sim"] == "PASS", manifest["sim"].get("log", result["scenarios"])
    assert all(result["scenarios"].values()), result["scenarios"]
    assert manifest["family_params"]["n_routers"] == 16
    assert manifest["family_params"]["buf_depth"] == 4


@pytest.mark.parametrize("side", [(4, "mesh4")])
def test_parameterized_mesh4_buf16_lints_and_sims(tmp_path, side):
    if shutil.which("verilator") is None:
        pytest.skip("verilator not installed")
    from veritx_dse.model.topology_intent import MeshIntent
    from veritx_dse.product.project_top_rtl import run_composed_family
    req = _param_request(MeshIntent(4, 1), buf=16)
    result = run_composed_family(req.to_dict(), tmp_path, {"repo_root": str(REPO)})
    manifest = json.loads((tmp_path / "project-top-manifest.json").read_text())
    assert result["lint"] == "PASS"
    assert result["sim"] == "PASS", manifest["sim"].get("log", result["scenarios"])
    assert all(result["scenarios"].values()), result["scenarios"]
    assert manifest["family_params"]["buf_depth"] == 16


def test_parameterized_torus5_and_ring16_lint_and_sim(tmp_path):
    if shutil.which("verilator") is None:
        pytest.skip("verilator not installed")
    from veritx_dse.model.topology_intent import RingIntent, TorusIntent
    from veritx_dse.product.project_top_rtl import run_composed_family
    for topo, n in ((TorusIntent(5, 1), 25), (RingIntent(16), 16)):
        sub = tmp_path / f"{getattr(topo, 'kind')}_{n}"
        req = _param_request(topo)
        result = run_composed_family(req.to_dict(), sub, {"repo_root": str(REPO)})
        manifest = json.loads((sub / "project-top-manifest.json").read_text())
        assert result["lint"] == "PASS"
        assert result["sim"] == "PASS", manifest["sim"].get("log", result["scenarios"])
        assert all(result["scenarios"].values()), result["scenarios"]
        assert manifest["family_params"]["n_routers"] == n


def _kncube_adjacency():
    k = 3
    n = 2
    def powi(a, b):
        v = 1
        for _ in range(b):
            v *= a
        return v
    def left_node(node, dim):
        k_to_dim = powi(k, dim)
        loc = (node // k_to_dim) % k
        return node + (k - 1) * k_to_dim if loc == 0 else node - k_to_dim
    def right_node(node, dim):
        k_to_dim = powi(k, dim)
        loc = (node // k_to_dim) % k
        return node - (k - 1) * k_to_dim if loc == k - 1 else node + k_to_dim
    return {u: sorted({left_node(u, d) for d in range(n)} | {right_node(u, d) for d in range(n)}) for u in range(k ** n)}


def _kncube_params_and_topology():
    from veritx_dse.model.topology_intent import StructuredTopologyIntent
    from veritx_dse.application.fabric_compiler import FabricCompiler
    from veritx_dse.product.project_top_rtl import composed_family_params_from_request
    req = _family_request(StructuredTopologyIntent(
        "kncube", {"radix": 3, "dimensions": 2, "wrap": True}))
    compiled = FabricCompiler().compile(req)
    assert compiled.status == "COMPILED", compiled.error
    kparams = composed_family_params_from_request(req, compiled)
    assert kparams.family == "kncube"
    return kparams, compiled.bundle.topology


def test_kncube_family_id_and_saved_request_binding():
    from veritx_dse.model.topology_intent import StructuredTopologyIntent, TorusIntent
    from veritx_dse.application.fabric_compiler import FabricCompiler
    from veritx_dse.product.project_top_rtl import (
        check_composed_family_profile, _family_id_from_topology,
    )
    intent = StructuredTopologyIntent(
        "kncube", {"radix": 3, "dimensions": 2, "wrap": True})
    request = _family_request(intent)
    compiled = FabricCompiler().compile(request)
    assert compiled.status == "COMPILED", compiled.error
    assert _family_id_from_topology(intent) == "kncube"
    assert _family_id_from_topology(TorusIntent(3, 1)) == "torus"
    assert check_composed_family_profile(request, compiled) is None
    changed = _family_request(StructuredTopologyIntent(
        "kncube", {"radix": 3, "dimensions": 2, "wrap": False}))
    with pytest.raises(ValueError, match="saved topology intent|does not match"):
        check_composed_family_profile(changed, compiled)


def test_kncube_params_native_wrap_and_dor():
    from veritx_dse.product.project_top_rtl import (
        FAMILY_EXPECTED_ROUTERS, SUPPORTED_COMPOSED_FAMILIES,
        _family_adjacency, _family_port_tables, build_family_router,
    )
    assert "kncube" in SUPPORTED_COMPOSED_FAMILIES
    assert FAMILY_EXPECTED_ROUTERS["kncube"] == 9
    assert FAMILY_EXPECTED_ROUTERS["dragonflynew"] == 36
    kparams, topology = _kncube_params_and_topology()
    assert kparams.family == "kncube"
    assert kparams.routing_law == "DOR_TORUS_XY"
    assert kparams.n_routers == 9
    assert kparams.max_deg == 4
    assert len(kparams.initiators) == 2
    assert kparams.memory_router == 2  # inherited from the torus compile fixture
    kn = _kncube_adjacency()
    assert {i: list(kparams.adjacency[i]) for i in range(9)} == kn
    for node in range(9):
        assert len(kn[node]) == 4
    assert 2 in kn[0] and 6 in kn[0]
    assert 0 in kn[2] and 0 in kn[6]
    assert _family_adjacency(topology) == kn
    rt_min, _rt_esc = _family_port_tables(kparams, topology)
    k = 3
    n = 2
    def powi(a, b):
        v = 1
        for _ in range(b):
            v *= a
        return v
    def left_node(node, dim):
        k_to_dim = powi(k, dim)
        loc = (node // k_to_dim) % k
        return node + (k - 1) * k_to_dim if loc == 0 else node - k_to_dim
    def right_node(node, dim):
        k_to_dim = powi(k, dim)
        loc = (node // k_to_dim) % k
        return node - (k - 1) * k_to_dim if loc == k - 1 else node + k_to_dim
    def dor_port(cur, dest):
        c, d = cur, dest
        for dim in range(n):
            if c % k == d % k:
                c //= k
                d //= k
                continue
            cc, dd = c % k, d % k
            dist2 = k - 2 * ((dd - cc + k) % k)
            return 2 * dim if dist2 > 0 else 2 * dim + 1
        return 2 * n
    for src in range(9):
        nbrs = kn[src]
        for dst in range(9):
            if src == dst:
                continue
            port = dor_port(src, dst)
            nxt = right_node(src, port // 2) if port % 2 == 0 else left_node(src, port // 2)
            assert rt_min[(src, dst)] == nbrs.index(nxt), (src, dst)
    files = build_family_router(kparams, topology)
    assert set(files.keys()) == {"noc_pkg.sv", "router.sv", "noc_top.sv"}
    assert "N_ROUTERS = 9" in files["noc_pkg.sv"]
    assert files == build_family_router(kparams, topology)


def test_kncube_renderers_deterministic():
    from veritx_dse.product.project_top_rtl import (
        render_cdc_bypass, render_destination_adapter,
        render_family_initiator_slice, render_family_project_top,
        render_family_tb,
    )
    kparams, _topology = _kncube_params_and_topology()
    top1 = render_family_project_top(kparams)
    slice1 = render_family_initiator_slice(kparams)
    tb1 = render_family_tb(kparams)
    assert top1 == render_family_project_top(kparams)
    assert tb1 == render_family_tb(kparams)
    assert render_destination_adapter(kparams) == render_destination_adapter(kparams)
    assert render_cdc_bypass() == render_cdc_bypass()
    assert "module project_top" in top1
    assert "module initiator_slice" in slice1
    assert "module tb_project_top" in tb1
    assert "noc_top u_noc" in top1
    assert "destination_adapter" in top1
    assert "u_slice0" in top1 and "u_slice1" in top1
    assert top1.count("  initiator_slice #(") == 2
    assert "PASS: S7 OOO stalled" in tb1
    assert "PASS: conservation injected==ejected" in tb1
    assert "PASS: drain dest_req==dest_rsp" in tb1


@pytest.mark.parametrize("dw", [64, 128])
def test_family_data_width_refuses_narrow_compiled_flits(tmp_path, dw):
    from veritx_dse.model.topology_intent import MeshIntent
    from veritx_dse.product.project_top_rtl import run_composed_family
    req = _param_request(MeshIntent(4, 1), data_width=dw)
    with pytest.raises(ValueError, match="flit too narrow for data width"):
        run_composed_family(req.to_dict(), tmp_path, {"repo_root": str(REPO)})
    assert not (tmp_path / "project-top-manifest.json").exists()
    assert not (tmp_path / "rtl").exists()


@pytest.mark.skipif(shutil.which("verilator") is None, reason="verilator not installed")
def test_vc4_cycles_ejection(tmp_path):
    import subprocess
    from dataclasses import replace as _rp
    from veritx_dse.model.compile_model import Dependency, DepKind, DependencyGraph
    from veritx_dse.model.agent_intent_v4 import TrafficClassVC, TrafficPolicyV4
    from veritx_dse.model.topology_intent import MeshIntent
    from veritx_dse.product.ordering_fsm_rtl import OrderingPolicy
    from veritx_dse.product.project_top_rtl import (
        apply_noc_pkg_widening, apply_ordering_widening, apply_router_widening,
        render_cdc_bypass, render_destination_adapter, render_project_top,
        render_tb_project_top, slice_params_from_request,
    )
    from veritx_dse.product.rtl_export import run_rtl_preview
    deps4 = DependencyGraph((
        Dependency(source="a", target="b", kind=DepKind.BLOCKING),
        Dependency(source="b", target="a", kind=DepKind.BLOCKING),
        Dependency(source="c", target="d", kind=DepKind.BLOCKING),
        Dependency(source="d", target="c", kind=DepKind.BLOCKING),
        Dependency(source="e", target="f", kind=DepKind.BLOCKING),
        Dependency(source="f", target="e", kind=DepKind.BLOCKING),
    ))
    pol4 = TrafficPolicyV4(traffic_class_vcs=(
        TrafficClassVC("a", 1), TrafficClassVC("b", 0),
        TrafficClassVC("c", 2), TrafficClassVC("d", 0),
        TrafficClassVC("e", 3), TrafficClassVC("f", 0),
        TrafficClassVC("tp_collective", 0)))
    base_req = _param_request(MeshIntent(2, 1), deps=deps4, policy=pol4)
    compiled = FabricCompiler().compile(base_req)
    assert compiled.status == "COMPILED", compiled.error
    base_params = slice_params_from_request(base_req, compiled)
    for vc in (0, 1, 2, 3):
        sub = tmp_path / f"vc{vc}"
        sub.mkdir(parents=True, exist_ok=True)
        _dummy = _rp(base_req, traffic_policy=TrafficPolicyV4(), dependencies=DependencyGraph(()))
        preview = run_rtl_preview(_dummy.to_dict(), sub, {"repo_root": str(REPO)})
        target = sub / "rtl"
        man = _rp(base_params, bound_vc=vc, class_id=0, class_w=1, traffic_class="a")
        _pol = OrderingPolicy(ordering="strong", max_outstanding=4, split_at=None, traffic_class_vcs=(("a", vc),), agent_indices=(0, 1, 2))
        _pkg = target / "noc_pkg.sv"
        _pkg.write_text(apply_noc_pkg_widening(_pkg.read_text(), man))
        _ord = target / "ordering_fsm.sv"
        if _ord.is_file():
            _t = _ord.read_text()
            try:
                from veritx_dse.product.project_top_rtl import apply_ordering_frontend_fix
                _t = apply_ordering_frontend_fix(_t)
            except ValueError:
                pass
            _ord.write_text(apply_ordering_widening(_t, man, _pol))
        _rtr = target / "router.sv"
        _rtr.write_text(apply_router_widening(_rtr.read_text(), man))
        (target / "cdc_bypass.sv").write_text(render_cdc_bypass(man))
        (target / "destination_adapter.sv").write_text(render_destination_adapter(man))
        (target / "project_top.sv").write_text(render_project_top(man))
        (target / "tb_project_top.sv").write_text(render_tb_project_top(man))
        _dut = ["noc_pkg.sv", "router.sv", "noc_top.sv", "addr_decode.sv", "ordering_fsm.sv",
                *[f"adapter_axi5_g{ini.group_idx}.sv" for ini in man.initiators],
                "cdc_bypass.sv", "destination_adapter.sv", "project_top.sv"]
        _dut = list(dict.fromkeys(_dut))
        _tb = _dut + ["tb_project_top.sv"]
        _chk = subprocess.run([shutil.which("verilator"), "--lint-only", "-sv", "-Wall", "-Wno-fatal", "-Wno-WIDTH", "-Wno-PINNOTFOUND", "-Wno-UNOPTFLAT", "--top-module", "project_top", *_dut], cwd=target, capture_output=True, text=True, timeout=120)
        assert _chk.returncode == 0, f"vc{vc} lint: " + (_chk.stdout + _chk.stderr)[-6000:]
        _bld = subprocess.run([shutil.which("verilator"), "--binary", "--timing", "-Wall", "-Wno-fatal", "-Wno-WIDTH", "-Wno-PINNOTFOUND", "-Wno-UNOPTFLAT", "-Wno-DECLFILENAME", "--top-module", "tb_project_top", "--Mdir", f"obj_vc{vc}", *_tb], cwd=target, capture_output=True, text=True, timeout=300)
        assert _bld.returncode == 0, f"vc{vc} build: " + (_bld.stdout + _bld.stderr)[-6000:]
        _run = subprocess.run([f"./obj_vc{vc}/Vtb_project_top"], cwd=target, capture_output=True, text=True, timeout=120)
        _out = (_run.stdout or "") + (_run.stderr or "")
        assert "status: PASS" in _out and _run.returncode == 0, f"vc{vc} sim: " + _out[-6000:]
        assert "PASS: conservation injected==ejected" in _out
        assert "PASS: drain dest_req==dest_rsp" in _out
    router_src = (tmp_path / "vc3" / "rtl" / "router.sv").read_text()
    assert "show_vc [0:NUM_PORTS-1]" in router_src
    assert "(c % NUM_VCS) != 0" in router_src
    assert "^in_class === 1'bx" in router_src


@pytest.mark.skipif(shutil.which("verilator") is None, reason="verilator not installed")
def test_composed_family_refuses_narrow_flits_and_simulates_multiclock(tmp_path):
    from veritx_dse.model.topology_intent import TorusIntent
    from veritx_dse.product.project_top_rtl import run_composed_family
    for dw in (64, 128):
        agents = (
            Agent(kind=AgentKind.COMPUTE_TILE, count=1, data_width=dw, addr_width=64, protocol="AXI", clock_domain="noc_clk", power_domain="pd0"),
            Agent(kind=AgentKind.COMPUTE_TILE, count=1, data_width=dw, addr_width=64, protocol="AXI", clock_domain="noc_clk", power_domain="pd0"),
            Agent(kind=AgentKind.HBM_CONTROLLER, count=1, data_width=dw, addr_width=64, protocol="AXI", clock_domain="noc_clk", power_domain="pd0"),
        )
        wl = WorkloadV3(model_family=ModelFamily.DENSE_TRANSFORMER, tp=2, pp=1, ep=1, dp=1, collectives=(CollectiveIntent(kind=CollectiveKind.ALLREDUCE, dimension=CollectiveDimension.TP, payload_bytes=8192, traffic_class="tp_collective"),))
        req = CompileRequestV4(workload=wl, agents=agents, dependencies=DependencyGraph(()), topology=TorusIntent(3, 1), address_map=AddressMap(ranges=(AddressRange(name="HBM0", base=0x1000, size=0x1000, target_agent_idx=2),)), agent_intents=_family_intents())
        sub = tmp_path / f"dw{dw}"
        with pytest.raises(ValueError, match="flit too narrow for data width"):
            run_composed_family(req.to_dict(), sub, {"repo_root": str(REPO)})
        assert not sub.exists()

    agents_mc = (
        Agent(kind=AgentKind.COMPUTE_TILE, count=1, data_width=32, addr_width=64, protocol="AXI", clock_domain="noc_clk", power_domain="pd0"),
        Agent(kind=AgentKind.COMPUTE_TILE, count=1, data_width=32, addr_width=64, protocol="AXI", clock_domain="other_clk", power_domain="pd0"),
        Agent(kind=AgentKind.HBM_CONTROLLER, count=1, data_width=32, addr_width=64, protocol="AXI", clock_domain="noc_clk", power_domain="pd0"),
    )
    intents_mc = _family_intents()
    wl2 = WorkloadV3(model_family=ModelFamily.DENSE_TRANSFORMER, tp=2, pp=1, ep=1, dp=1, collectives=(CollectiveIntent(kind=CollectiveKind.ALLREDUCE, dimension=CollectiveDimension.TP, payload_bytes=8192, traffic_class="tp_collective"),))
    req_mc = CompileRequestV4(workload=wl2, agents=agents_mc, dependencies=DependencyGraph(()), topology=TorusIntent(3, 1), address_map=AddressMap(ranges=(AddressRange(name="HBM0", base=0x1000, size=0x1000, target_agent_idx=2),)), agent_intents=intents_mc)
    result_mc = run_composed_family(req_mc.to_dict(), tmp_path / "mc", {"repo_root": str(REPO)})
    assert result_mc["lint"] == "PASS"
    manifest_mc = json.loads((tmp_path / "mc" / "project-top-manifest.json").read_text())
    assert result_mc["sim"] == "PASS", manifest_mc["sim"].get("log", result_mc["scenarios"])
    assert "clk_d0" in (tmp_path / "mc" / "rtl" / "tb_project_top.sv").read_text()


@pytest.mark.skipif(shutil.which("verilator") is None, reason="verilator not installed")
def test_kncube_composed_top_lints_and_sims(tmp_path):
    import subprocess
    from veritx_dse.application.fabric_compiler import FabricCompiler
    from veritx_dse.model.topology_intent import StructuredTopologyIntent
    from veritx_dse.product.project_top_rtl import (
        build_family_router, render_cdc_bypass, render_destination_adapter,
        render_family_initiator_slice, render_family_project_top,
        render_family_tb,
    )
    from veritx_dse.product.rtl_export import run_rtl_preview
    kparams, topology = _kncube_params_and_topology()
    req = _family_request(StructuredTopologyIntent(
        "kncube", {"radix": 3, "dimensions": 2, "wrap": True}))
    compiled = FabricCompiler().compile(req)
    assert compiled.status == "COMPILED", compiled.error
    preview = run_rtl_preview(req.to_dict(), tmp_path, {"repo_root": str(REPO)})
    assert preview.get("scope") is not None
    target = tmp_path / "rtl"
    fam_files = build_family_router(kparams, topology)
    for _name, _content in fam_files.items():
        (target / _name).write_text(_content)
    (target / "cdc_bypass.sv").write_text(render_cdc_bypass())
    (target / "destination_adapter.sv").write_text(render_destination_adapter(kparams))
    (target / "initiator_slice.sv").write_text(render_family_initiator_slice(kparams))
    (target / "project_top.sv").write_text(render_family_project_top(kparams))
    (target / "tb_project_top.sv").write_text(render_family_tb(kparams))
    dut_files = ["noc_pkg.sv", "router.sv", "noc_top.sv", "addr_decode.sv", "ordering_fsm.sv"]
    for ini in kparams.initiators:
        dut_files.append("adapter_axi5_g" + str(ini.group_idx) + ".sv")
    dut_files.append("cdc_bypass.sv")
    dut_files.append("destination_adapter.sv")
    dut_files.append("initiator_slice.sv")
    dut_files.append("project_top.sv")
    dut_files = list(dict.fromkeys(dut_files))
    tb_files = list(dut_files) + ["tb_project_top.sv"]
    checked = subprocess.run([shutil.which("verilator"), "--lint-only", "-sv", "-Wall", "-Wno-fatal", "-Wno-WIDTH", "-Wno-PINNOTFOUND", "-Wno-UNOPTFLAT", "--top-module", "project_top", *dut_files], cwd=target, capture_output=True, text=True, timeout=120)
    assert checked.returncode == 0, (checked.stdout + checked.stderr)[-6000:]
    build = subprocess.run([shutil.which("verilator"), "--binary", "--timing", "-Wall", "-Wno-fatal", "-Wno-WIDTH", "-Wno-PINNOTFOUND", "-Wno-UNOPTFLAT", "-Wno-DECLFILENAME", "--top-module", "tb_project_top", "--Mdir", "obj_kncube", *tb_files], cwd=target, capture_output=True, text=True, timeout=300)
    assert build.returncode == 0, (build.stdout + build.stderr)[-6000:]
    run = subprocess.run(["./obj_kncube/Vtb_project_top"], cwd=target, capture_output=True, text=True, timeout=120)
    output = (run.stdout or "") + (run.stderr or "")
    assert "status: PASS" in output and run.returncode == 0, output[-6000:]
    expected = [
        ("allow_write_init0", "PASS: init0 write bresp=0" in output),
        ("deny_write_init1", "PASS: init1 write bresp=3" in output),
        ("allow_read_init0", "PASS: init0 read rresp=0" in output),
        ("allow_read_init1", "PASS: init1 read rresp=0" in output),
        ("error_miss", "PASS: init0 write bresp=3" in output),
        ("error_slv", "PASS: init0 read rresp=2" in output),
        ("ordering_stall", "PASS: S7 OOO stalled" in output),
        ("ordering_inorder", "PASS: S7 in-order completed" in output),
        ("backpressure_stall", "PASS: S8 stalled under hold" in output),
        ("backpressure_release", "PASS: S8 completed after release" in output),
        ("concurrent", "PASS: S9 concurrent OKAY + readback" in output or "SKIP: S9 concurrent" in output),
        ("conservation", "PASS: conservation injected==ejected" in output),
        ("drain", "PASS: drain dest_req==dest_rsp" in output),
    ]
    assert all(ok for _name, ok in expected), expected
    top_src = (target / "project_top.sv").read_text()
    assert "u_noc" in top_src
    assert kparams.topology_id == "kncube"
    assert kparams.design_hash == req.design_hash()
    assert len(kparams.adjacency) == len(topology.routers) == 9


def test_mesh2x2_contention_patterns_render():
    tb = render_tb_project_top()
    assert tb == render_tb_project_top()
    for tag in (
        "hotspot_to_single_output",
        "same_output_competition",
        "permutation_stride2",
        "SLICE_MULTI_DEST",
        "NOT_RUN: permutation_stride2",
        "PASS: hotspot_to_single_output seed=",
        "PASS: same_output_competition hold=0 seed=",
        "PASS: same_output_competition hold=1 seed=",
        "outstanding==0 at drain accepted==delivered",
    ):
        assert tag in tb, tag
    for marker in (
        "(sd == 0) ? 32'd1 : (sd == 1) ? 32'd7 : 32'd42",
        "len = (seed == 32'd1) ? 2 : (seed == 32'd7) ? 5 : 9",
        "64'h1240",
        "64'h1320",
        "64'h1380",
        "p8_acc0",
        "addr_q",
    ):
        assert tb.count(marker) >= 1, marker


@pytest.mark.skipif(shutil.which("verilator") is None, reason="verilator not installed")
def test_mesh2x2_contention_patterns_sim(tmp_path):
    request = _slice_request()
    result = run_rtl_slice(request.to_dict(), tmp_path, {"repo_root": str(REPO)})
    assert result["scope"] == "COMPOSED_SLICE"
    assert result["lint"] == "PASS"
    manifest = json.loads((tmp_path / "project-top-manifest.json").read_text())
    assert result["sim"] == "PASS", manifest["sim"].get("log", result["scenarios"])
    assert len(result["scenarios"]) == 18, result["scenarios"]
    assert all(result["scenarios"].values()), result["scenarios"]
    assert result["scenarios"]["conservation"] is True
    assert result["scenarios"]["drain"] is True
    log = manifest["sim"]["log"]
    for tag in [
        "PASS: same_output_competition hold=1 seed=42 len=9 drained after release",
        "PASS: same_output_competition hold=1 seed=42 len=9 outstanding==0 at drain accepted==delivered",
        "PASS: S27 no ordering violation under same-output competition",
        "NOT_RUN: permutation_stride2",
        "SLICE_MULTI_DEST",
        "PASS: conservation injected==ejected",
        "PASS: drain dest_req==dest_rsp",
        "status: PASS",
    ]:
        assert tag in log, tag
    assert "status: FAIL" not in log
    tb = render_tb_project_top()
    assert "outstanding==0 at drain accepted==delivered" in tb
    assert "hotspot_to_single_output" in tb
    assert "same_output_competition" in tb
    assert "permutation_stride2" in tb
