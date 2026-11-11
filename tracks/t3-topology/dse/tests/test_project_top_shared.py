from __future__ import annotations
import json
import shutil
from dataclasses import replace
import pytest
from veritx_dse.model.agent_intent_v4 import AgentIntentV4, OrderingMode, PermissionWindow, ProtocolFamily
from veritx_dse.model.compile_model import AddressMap, AddressRange, Agent, AgentKind, CollectiveDimension, CollectiveIntent, CollectiveKind, DependencyGraph, ModelFamily, WorkloadV3
from veritx_dse.model.compile_request_v4 import CompileRequestV4
from veritx_dse.model.topology_intent import GecMode, GecTopologyIntent
from veritx_dse.model.srota_intent import SrotaIntent
from veritx_dse.application.fabric_compiler import FabricCompiler
from veritx_dse.core.paths import REPO
from veritx_dse.product.project_top_rtl import check_gec_mecs_shared_profile, check_hybrid_shared_profile, check_srota_shared_profile, render_gec_mecs_shared_fabric, render_gec_mecs_shared_tb, render_srota_shared_fabric, render_srota_shared_tb, render_hybrid_shared_fabric, render_hybrid_shared_tb, run_gec_mecs_shared, run_hybrid_shared, run_srota_shared, hybrid_selector, native_hybrid_selector, gec_hybrid_differential_cases, gec_hybrid_check_differential, gec_hybrid_credit_bindings, hybrid_shared_params_from_request
from veritx_dse.product.clock_power_cdc import hybrid_used_credit, hybrid_credit_visible_cycle, gec_hybrid_credit_pin, GEC_HYBRID_NUM_VCS, GEC_HYBRID_FLITS_PER_VC, GEC_HYBRID_BUFFER_FLITS, GEC_HYBRID_CREDIT_RETURN_LATENCY_CYCLES
_VERILATOR = shutil.which("verilator") is not None
def _workload():
    return WorkloadV3(model_family=ModelFamily.DENSE_TRANSFORMER, tp=2, pp=1, ep=1, dp=1, collectives=(CollectiveIntent(kind=CollectiveKind.ALLREDUCE, dimension=CollectiveDimension.TP, payload_bytes=8192, traffic_class="tp_collective"),))
def _agents():
    return (Agent(kind=AgentKind.COMPUTE_TILE, count=1, data_width=32, addr_width=64, protocol="AXI", clock_domain="noc_clk", power_domain="pd0"), Agent(kind=AgentKind.COMPUTE_TILE, count=1, data_width=32, addr_width=64, protocol="AXI", clock_domain="noc_clk", power_domain="pd0"), Agent(kind=AgentKind.HBM_CONTROLLER, count=1, data_width=32, addr_width=64, protocol="AXI", clock_domain="noc_clk", power_domain="pd0"))
def _intents():
    return (AgentIntentV4(0, protocol=ProtocolFamily.AXI5, ordering=OrderingMode.STRONG, max_outstanding=4, permission_windows=(PermissionWindow("HBM0", readable=True, writable=True, atomic=False),)), AgentIntentV4(1, protocol=ProtocolFamily.AXI5, ordering=OrderingMode.STRONG, max_outstanding=4, permission_windows=(PermissionWindow("HBM0", readable=True, writable=False, atomic=False),)), AgentIntentV4(2))
def _request(topology):
    agents = _agents()
    return CompileRequestV4(workload=_workload(), agents=agents, dependencies=DependencyGraph(()), topology=topology, address_map=AddressMap(ranges=(AddressRange(name="HBM0", base=0x1000, size=0x1000, target_agent_idx=2),)), agent_intents=_intents())
def _gec_mecs_request():
    return _request(GecTopologyIntent(mode=GecMode.MULTIDROP, grid_side_length=4, concentration=1, express_channel_groups_per_dimension=1, destinations_per_express_channel=3))
def _gec_hybrid_request():
    return _request(GecTopologyIntent(mode=GecMode.HYBRID, grid_side_length=4, concentration=1, express_channel_groups_per_dimension=1, destinations_per_express_channel=3))
def _srota_request():
    return _request(SrotaIntent(side_length=4, concentration=1, mecs_row=True, mecs_col=True, drop_latency=1, planes=frozenset({"d"}), island_columns=(1,), path_shapes=frozenset({"row", "column"}), vc_policy="shape", sidebuf_enable=False, sidebuf_watermark=None, tel_period=4, tel_latency=8))
def test_gec_mecs_renderers_are_deterministic():
    assert render_gec_mecs_shared_fabric() == render_gec_mecs_shared_fabric()
    assert render_gec_mecs_shared_tb() == render_gec_mecs_shared_tb()
    fab = render_gec_mecs_shared_fabric()
    tb = render_gec_mecs_shared_tb()
    assert "module gec_mecs16_fabric" in fab
    assert "module gec_mecs_router" in fab
    assert "module tb_gec_mecs16_fabric" in tb
    assert "row_valid" in fab
    assert "col_valid" in fab
    assert "row_dest" in fab
    assert "row_vc" in fab
    assert "row_tap" in fab
    assert "same_destination_contention" in tb
    assert "PASS gec_mecs16" in tb
    assert (chr(47) * 2) not in fab
    assert (chr(47) * 2) not in tb
def test_gec_mecs_profile_compiles_and_passes_guard():
    request = _gec_mecs_request()
    compiled = FabricCompiler().compile(request)
    assert compiled.status == "COMPILED", compiled.error
    check_gec_mecs_shared_profile(request, compiled)
    assert len(compiled.bundle.topology.routers) == 16
    assert len(compiled.bundle.topology.shared_links) == 32
    assert len(compiled.bundle.topology.channels) == 0
@pytest.mark.skipif(not _VERILATOR, reason="verilator not installed")
def test_gec_mecs_composed_lints_and_sims_on_the_top(tmp_path):
    request = _gec_mecs_request()
    result = run_gec_mecs_shared(request.to_dict(), tmp_path, {"repo_root": str(REPO)})
    assert result["scope"] == "COMPOSED_GEC_MECS"
    assert result["development_milestone"] is True
    assert result["final_implementation"] is False
    assert result["lint"] == "PASS"
    assert result["sim"] == "PASS"
    assert result["family"] == "gec_mecs"
    scenarios = result["scenarios"]
    assert scenarios["same_row_drop"] is True
    assert scenarios["same_col_drop"] is True
    assert scenarios["concurrency"] is True
    assert scenarios["backpressure"] is True
    assert scenarios["conservation"] is True
    assert scenarios["epsilon"] is True
    assert scenarios["drain"] is True
    assert all(scenarios.values()), scenarios
    manifest = json.loads((tmp_path / "project-top-manifest.json").read_text())
    assert manifest["scope"] == "COMPOSED_GEC_MECS"
    assert manifest["lint"]["status"] == "PASS"
    assert manifest["sim"]["status"] == "PASS"
    assert manifest["family_profile"]["shared_wires"] == 32
    assert manifest["family_params"]["taps_per_wire"] == 3
    assert manifest["family_params"]["k"] == 4
    assert "PASS gec_mecs16" in manifest["sim"]["log"]
    assert "accepted=258" in manifest["sim"]["log"]
    assert "delivered=258" in manifest["sim"]["log"]
    assert "drained=1" in manifest["sim"]["log"]
    fab = (tmp_path / "rtl" / "gec_mecs16_fabric.sv").read_text()
    assert "gec_mecs16_fabric" in fab
    assert "row_valid" in fab
    assert "noc_top" not in fab
    assert (tmp_path / "project-top.zip").is_file()
    pool = (tmp_path / "rtl" / "tap_credit_pool.sv").read_text()
    assert "module tap_credit_pool #(\n" in pool
    assert result["scenarios"]["credit_balance"] is True
    assert "PASS gec_mecs16 credits" in manifest["sim"]["log"]
@pytest.mark.skipif(not _VERILATOR, reason="verilator not installed")
def test_gec_mecs_scaled_manifest_reports_the_compiled_router_count(tmp_path):
    request = _request(GecTopologyIntent(
        mode=GecMode.MULTIDROP, grid_side_length=3, concentration=1,
        express_channel_groups_per_dimension=1,
        destinations_per_express_channel=2))
    result = run_gec_mecs_shared(request.to_dict(), tmp_path, {"repo_root": str(REPO)})
    manifest = json.loads((tmp_path / "project-top-manifest.json").read_text())
    assert result["family_params"]["router_count"] == 9
    assert manifest["family_profile"]["n_routers"] == 9
    assert manifest["hierarchy"][1]["role"].startswith("9 shared-wire routers")

def test_srota_renderers_are_deterministic():
    assert render_srota_shared_fabric() == render_srota_shared_fabric()
    assert render_srota_shared_tb() == render_srota_shared_tb()
    fab = render_srota_shared_fabric()
    tb = render_srota_shared_tb()
    assert "module srota_composed_fabric" in fab
    assert "module srota_composed_router" in fab
    assert "module tb_srota_composed" in tb
    assert "ISLAND_MASK" in fab
    assert "xneg_valid" in fab
    assert "xpos_valid" in fab
    assert "yneg_valid" in fab
    assert "ypos_valid" in fab
    assert "row-first" not in fab.lower() or "row_first" in tb
    assert "island" in tb.lower()
    assert "PASS srota_composed" in tb
    assert (chr(47) * 2) not in fab
    assert (chr(47) * 2) not in tb
def test_srota_profile_compiles_and_passes_guard():
    request = _srota_request()
    compiled = FabricCompiler().compile(request)
    assert compiled.status == "COMPILED", compiled.error
    check_srota_shared_profile(request, compiled)
    assert len(compiled.bundle.topology.routers) == 16
    assert len(compiled.bundle.topology.shared_links) == 48
    assert len(compiled.bundle.topology.channels) == 0
@pytest.mark.skipif(not _VERILATOR, reason="verilator not installed")
def test_srota_composed_lints_and_sims_on_the_top(tmp_path):
    request = _srota_request()
    result = run_srota_shared(request.to_dict(), tmp_path, {"repo_root": str(REPO)})
    assert result["scope"] == "COMPOSED_SROTA"
    assert result["development_milestone"] is True
    assert result["final_implementation"] is False
    assert result["lint"] == "PASS"
    assert result["sim"] == "PASS"
    assert result["family"] == "srota"
    scenarios = result["scenarios"]
    assert scenarios["row_first"] is True
    assert scenarios["dest_drop"] is True
    assert scenarios["island_rule"] is True
    assert scenarios["backpressure"] is True
    assert scenarios["conservation"] is True
    assert scenarios["epsilon"] is True
    assert scenarios["drain"] is True
    assert all(scenarios.values()), scenarios
    manifest = json.loads((tmp_path / "project-top-manifest.json").read_text())
    assert manifest["scope"] == "COMPOSED_SROTA"
    assert manifest["lint"]["status"] == "PASS"
    assert manifest["sim"]["status"] == "PASS"
    assert manifest["family_profile"]["shared_wires"] == 48
    assert manifest["family_params"]["island_columns"] == [1]
    assert "PASS srota_composed" in manifest["sim"]["log"]
    assert "accepted=256" in manifest["sim"]["log"]
    assert "delivered=256" in manifest["sim"]["log"]
    assert "drained=1" in manifest["sim"]["log"]
    fab = (tmp_path / "rtl" / "srota_fabric.sv").read_text()
    assert "srota_composed_fabric" in fab
    assert "ISLAND_MASK" in fab
    assert "noc_top" not in fab
    assert (tmp_path / "project-top.zip").is_file()
    not_est = " ".join(manifest["not_established"])
    assert "SROTA_SIDEBUT_NOT_MODELED" in not_est
    assert "SROTA_TELEMETRY_NOT_MODELED" in not_est
    assert "SROTA_VALIANT_RANK_NOT_MODELED" in not_est
    # Scope B claims its own criteria, so its verdict names them: a clean
    # lint is one closed criterion, not a closure of the scope.
    verdict = manifest["final_implementation_verdict"]
    assert verdict["scope"] == "COMPOSED_SROTA"
    assert verdict["final_implementation"] is False
    assert len(verdict["rows"]) == (len(manifest["proven"])
                                    + len(manifest["not_established"]))
    closed = [r for r in verdict["rows"] if r["status"] == "CLOSED"]
    assert len(closed) == len(manifest["proven"])
    assert verdict["open_rows"], "a Scope B claim with no open row is not Scope B"
    assert any("SIDEBUT" in r["requirement"] for r in verdict["rows"]
               if r["status"] == "OPEN")
def test_srota_refused_features_are_typed(tmp_path):
    base = _srota_request()
    cases = [
        ("sidebuf", replace(base, topology=replace(base.topology, sidebuf_enable=True, sidebuf_watermark=6)), "SROTA_SIDEBUT_NOT_MODELED"),
        ("telemetry", replace(base, topology=replace(base.topology, planes=frozenset({"d", "t"}))), "SROTA_TELEMETRY_NOT_MODELED"),
        ("valiant", replace(base, topology=replace(base.topology, path_shapes=frozenset({"row", "column", "valiant"}), vc_policy="rank")), "SROTA_VALIANT_RANK_NOT_MODELED"),
        ("rank", replace(base, topology=replace(base.topology, vc_policy="rank")), "SROTA_VALIANT_RANK_NOT_MODELED"),
    ]
    for name, request, blocker in cases:
        compiled = FabricCompiler().compile(request)
        with pytest.raises(ValueError, match="UNSUPPORTED_COMPOSED_FAMILY") as exc:
            check_srota_shared_profile(request, compiled)
        assert blocker in str(exc.value), (name, str(exc.value))
        assert "ProjectTop" in str(exc.value)
        out = tmp_path / name
        with pytest.raises(ValueError, match="UNSUPPORTED_COMPOSED_FAMILY"):
            run_srota_shared(request.to_dict(), out, {"repo_root": str(REPO)})
        assert not (out / "project-top-manifest.json").exists()
def test_hybrid_renderers_are_deterministic():
    assert render_hybrid_shared_fabric() == render_hybrid_shared_fabric()
    assert render_hybrid_shared_tb() == render_hybrid_shared_tb()
    fab = render_hybrid_shared_fabric()
    tb = render_hybrid_shared_tb()
    assert "module gec_hybrid16_fabric" in fab
    assert "module gec_hybrid_router" in fab
    assert "module tb_gec_hybrid16_fabric" in tb
    assert "west_credit" in fab
    assert "row_credit0" in fab
    assert "col_credit0" in fab
    assert "mesh_east_valid" in fab
    assert "row_valid" in fab
    assert "col_valid" in fab
    assert "row_dest" in fab
    assert "row_vc" in fab
    assert "col_vc" in fab
    assert "mesh_west_vc" in fab
    assert "PASS gec_hybrid16" in tb
    assert "same_destination_contention" in tb
    assert (chr(47) * 2) not in fab
    assert (chr(47) * 2) not in tb
def test_hybrid_profile_compiles_and_passes_guard():
    request = _gec_hybrid_request()
    compiled = FabricCompiler().compile(request)
    assert compiled.status == "COMPILED", compiled.error
    check_hybrid_shared_profile(request, compiled)
    params = hybrid_shared_params_from_request(request, compiled)
    assert params.k == 4 and params.c == 1 and params.o == 1 and params.d == 3
    assert params.num_vcs == 6
    assert params.flits_per_vc == 8
    assert params.buffer_flits == 48
    assert params.credit_return_latency == 1
    assert params.router_count == 16
    assert params.shared_wires == 32
    assert params.mesh_channels == 48
    assert len(compiled.bundle.topology.routers) == 16
    assert len(compiled.bundle.topology.shared_links) == 32
    assert len(compiled.bundle.topology.channels) == 48
    assert compiled.bundle.vc_assignment.vc_count == 6
    assert compiled.bundle.router_behavior.input_buffer_depth_flits_per_vc == 8
    assert compiled.bundle.router_behavior.credit_return_latency_cycles == 1
    pin = gec_hybrid_credit_pin()
    assert pin.num_vcs == GEC_HYBRID_NUM_VCS == 6
    assert pin.flits_per_vc == GEC_HYBRID_FLITS_PER_VC == 8
    assert pin.buffer_flits == GEC_HYBRID_BUFFER_FLITS == 48
    assert pin.credit_return_latency_cycles == GEC_HYBRID_CREDIT_RETURN_LATENCY_CYCLES == 1
    assert pin.to_dict()["num_vcs"] == 6
    bindings = gec_hybrid_credit_bindings()
    assert len(bindings) == 160
    assert (0, "mesh_west", -1, 0, 2) in bindings
    assert (0, "row_mecs", 0, 0, 0) in bindings
    assert (0, "col_mecs", 0, 3, 3) in bindings
    assert (15, "col_mecs", 2, 5, 5) in bindings
def test_hybrid_selector_differential_matches_native():
    assert gec_hybrid_check_differential() is True
    cases = gec_hybrid_differential_cases()
    assert len(cases) > 200
    assert (0, 0, 1) in cases
    assert (0, 0, 3) in cases
    assert (1, 1, 1) in cases
    assert (2, 2, 1) in cases
    assert (1, 2, 2) in cases
    assert (8, 8, 1) in cases
    assert (8, 8, 2) in cases
    assert (48, 48, 1) in cases
    for mesh_credit, mecs_credit, mesh_hops in cases:
        assert hybrid_selector(mesh_credit, mecs_credit, mesh_hops) == native_hybrid_selector(mesh_credit, mecs_credit, mesh_hops)
    assert hybrid_selector(0, 0, 1) == "mecs"
    assert hybrid_selector(0, 0, 3) == "mecs"
    assert hybrid_selector(1, 1, 1) == "mecs"
    assert hybrid_selector(2, 2, 1) == "mecs"
    assert hybrid_selector(1, 2, 2) == "mecs"
    assert hybrid_selector(0, 1, 3) == "mesh"
    assert hybrid_selector(1, 5, 3) == "mesh"
    assert hybrid_selector(2, 5, 3) == "mecs"
    assert hybrid_selector(0, 0, 2) == "mecs"
    assert hybrid_selector(3, 3, 2) == "mecs"
    assert hybrid_selector(1, 3, 2) == "mesh"
    assert hybrid_selector(1, 2, 3) == "mecs"
    assert hybrid_selector(1, 4, 3) == "mesh"
    assert hybrid_selector(2, 3, 3) == "mecs"
    assert hybrid_selector(0, 48, 3) == "mesh"
    assert hybrid_selector(48, 0, 1) == "mecs"
    for mesh_credit, mecs_credit, mesh_hops in ((0, 0, 1), (1, 1, 1), (2, 4, 2), (4, 8, 2), (8, 8, 1)):
        assert mesh_credit * mesh_hops == mecs_credit
        assert hybrid_selector(mesh_credit, mecs_credit, mesh_hops) == "mecs"
def test_hybrid_credit_occupancy_accounting():
    assert hybrid_used_credit((0, 0, 0, 0, 0, 0)) == 0
    assert hybrid_used_credit((1, 0, 0, 0, 0, 0)) == 1
    assert hybrid_used_credit((8, 8, 8, 8, 8, 8)) == 48
    assert hybrid_used_credit((4, 4, 0, 0, 0, 0)) == 8
    with pytest.raises(ValueError):
        hybrid_used_credit((8, 8, 8, 8, 8, 9))
    with pytest.raises(ValueError):
        hybrid_used_credit((-1, 0, 0, 0, 0, 0))
    assert hybrid_credit_visible_cycle(7) == 8
    assert hybrid_credit_visible_cycle(7) == 7 + GEC_HYBRID_CREDIT_RETURN_LATENCY_CYCLES
def test_hybrid_wrong_shape_stays_typed_refused(tmp_path):
    wrong = _request(GecTopologyIntent(mode=GecMode.HYBRID, grid_side_length=6, concentration=1, express_channel_groups_per_dimension=1, destinations_per_express_channel=5))
    compiled = FabricCompiler().compile(wrong)
    assert compiled.status == "COMPILED", compiled.error
    with pytest.raises(ValueError, match="UNSUPPORTED_COMPOSED_FAMILY") as exc:
        check_hybrid_shared_profile(wrong, compiled)
    assert "GEC_HYBRID_CREDIT_OBSERVABILITY_CONTRACT_UNVERIFIED" in str(exc.value)
    assert "missing contract" in str(exc.value)
    assert "ProjectTop" in str(exc.value)
    assert "GetUsedCredit" in str(exc.value)
    out = tmp_path / "hybrid-wrong"
    with pytest.raises(ValueError, match="UNSUPPORTED_COMPOSED_FAMILY") as exc2:
        run_hybrid_shared(wrong.to_dict(), out, {"repo_root": str(REPO)})
    assert "GEC_HYBRID_CREDIT_OBSERVABILITY_CONTRACT_UNVERIFIED" in str(exc2.value)
    assert not (out / "project-top-manifest.json").exists()
@pytest.mark.skipif(not _VERILATOR, reason="verilator not installed")
def test_hybrid_composed_lints_and_sims_on_the_top(tmp_path):
    request = _gec_hybrid_request()
    result = run_hybrid_shared(request.to_dict(), tmp_path, {"repo_root": str(REPO)})
    assert result["scope"] == "COMPOSED_GEC_HYBRID"
    assert result["development_milestone"] is True
    assert result["final_implementation"] is False
    assert result["lint"] == "PASS"
    assert result["sim"] == "PASS"
    assert result["family"] == "gec_hybrid"
    scenarios = result["scenarios"]
    assert scenarios["all_pairs"] is True
    assert scenarios["contention"] is True
    assert scenarios["backpressure"] is True
    assert scenarios["conservation"] is True
    assert scenarios["epsilon"] is True
    assert scenarios["drain"] is True
    assert scenarios["mesh_mecs"] is True
    assert scenarios["selector_tie"] is True
    assert scenarios["drop_vc"] is True
    assert all(scenarios.values()), scenarios
    manifest = json.loads((tmp_path / "project-top-manifest.json").read_text())
    assert manifest["scope"] == "COMPOSED_GEC_HYBRID"
    assert manifest["lint"]["status"] == "PASS"
    assert manifest["sim"]["status"] == "PASS"
    assert manifest["family_profile"]["shared_wires"] == 32
    assert manifest["family_profile"]["mesh_channels"] == 48
    assert manifest["family_params"]["num_vcs"] == 6
    assert manifest["family_params"]["flits_per_vc"] == 8
    assert manifest["family_params"]["buffer_flits"] == 48
    assert manifest["family_params"]["credit_return_latency"] == 1
    assert "PASS gec_hybrid16" in manifest["sim"]["log"]
    assert "accepted=260" in manifest["sim"]["log"]
    assert "delivered=260" in manifest["sim"]["log"]
    assert "drained=1" in manifest["sim"]["log"]
    fab = (tmp_path / "rtl" / "gec_hybrid16_fabric.sv").read_text()
    assert "gec_hybrid16_fabric" in fab
    assert "west_credit" in fab
    assert "noc_top" not in fab
    assert (tmp_path / "project-top.zip").is_file()
    # The Scope B verdict names every claimed criterion, so a reader can see
    # which one holds the claim instead of a bare false.
    verdict = manifest["final_implementation_verdict"]
    assert verdict["scope"] == "COMPOSED_GEC_HYBRID"
    assert verdict["final_implementation"] is False
    assert len(verdict["rows"]) == (len(manifest["proven"])
                                    + len(manifest["not_established"]))
    assert len([r for r in verdict["rows"] if r["status"] == "CLOSED"]) == len(
        manifest["proven"])
    assert verdict["open_rows"], "a Scope B claim with no open row is not Scope B"
    assert any("MULTIFLIT" in r["requirement"] for r in verdict["rows"]
               if r["status"] == "OPEN")


def test_shared_shapes_refuse_typed(tmp_path):
    # A declared shape that does not match the compiled bundle must refuse.
    # (A self-consistent shape is emittable now: the shared fabric scales with
    # the declared grid side and tap count.)
    gec_declared = _request(GecTopologyIntent(mode=GecMode.MULTIDROP, grid_side_length=6, concentration=1, express_channel_groups_per_dimension=1, destinations_per_express_channel=5))
    gec_other = _request(GecTopologyIntent(mode=GecMode.MULTIDROP, grid_side_length=4, concentration=1, express_channel_groups_per_dimension=1, destinations_per_express_channel=3))
    compiled = FabricCompiler().compile(gec_other)
    with pytest.raises(ValueError, match="UNSUPPORTED_COMPOSED_FAMILY"):
        check_gec_mecs_shared_profile(gec_declared, compiled)
    srota_wrong = _request(SrotaIntent(side_length=4, concentration=2, mecs_row=True, mecs_col=True, drop_latency=1, planes=frozenset({"d"}), island_columns=(1,), path_shapes=frozenset({"row", "column"}), vc_policy="shape", sidebuf_enable=False, sidebuf_watermark=None, tel_period=4, tel_latency=8))
    compiled = FabricCompiler().compile(srota_wrong)
    with pytest.raises(ValueError, match="UNSUPPORTED_COMPOSED_FAMILY"):
        check_srota_shared_profile(srota_wrong, compiled)
