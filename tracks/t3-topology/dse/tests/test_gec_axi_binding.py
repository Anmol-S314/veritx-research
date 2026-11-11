"""The completion path must deliver credited AXI RTL, not a flit-only substitute."""
from dataclasses import replace
import sys

import pytest

from veritx_dse.application.fabric_compiler import FabricCompiler
from veritx_dse.core.paths import REPO
from veritx_dse.product import project_top_rtl

sys.path.insert(0, str(REPO))
from scripts.complete_design import generate_hardware, make_family_request


def _compiled():
    request = make_family_request("gec_mecs")
    compiled = FabricCompiler().compile(request)
    assert compiled.status == "COMPILED", compiled.error
    params = project_top_rtl.composed_family_params_from_request(request, compiled)
    return request, compiled, params


def test_completion_dispatches_gec_to_connected_axi_without_smoke_fallback(tmp_path, monkeypatch):
    request = make_family_request("gec_mecs")
    calls = []

    def connected(doc, out, config):
        calls.append((doc, out, config))
        return {"scope": "COMPOSED_FAMILY", "family": "gec_mecs"}

    def forbidden(*args, **kwargs):
        pytest.fail("completion must not substitute the flit-only GEC smoke runner")

    monkeypatch.setattr(project_top_rtl, "run_composed_family", connected)
    monkeypatch.setattr(project_top_rtl, "run_gec_mecs_shared", forbidden)
    assert generate_hardware(request, "gec_mecs", tmp_path)["scope"] == "COMPOSED_FAMILY"
    assert calls == [(request.to_dict(), tmp_path, {"repo_root": str(REPO)})]


def test_bridge_refuses_missing_wire_wrong_latency_and_payload_truncation():
    _request, compiled, params = _compiled()
    assert "gec_mecs16_fabric.sv" in project_top_rtl.build_family_router(params, compiled.bundle.topology)
    mutations = [replace(params, resources=params.resources[:-1])]
    resource = list(params.resources[0])
    resource[-1] = 2
    mutations.append(replace(params, resources=(tuple(resource), *params.resources[1:])))
    mutations.append(replace(params, data_width=64))
    for mutated in mutations:
        with pytest.raises(ValueError, match="credited GEC bridge|full AXI data"):
            project_top_rtl.build_family_router(mutated, compiled.bundle.topology)


def test_emitted_binding_checks_design_hash_and_every_slice_seat(tmp_path):
    request, _compiled_artifact, params = _compiled()
    rtl = project_top_rtl.render_family_project_top(params)
    (tmp_path / "project_top.sv").write_text(rtl)
    row = project_top_rtl._family_binding_gate(params, tmp_path, request)
    assert row["status"] == "CLOSED"
    assert all(row["measured"]["checks"].values())

    stale = project_top_rtl._family_binding_gate(
        replace(params, design_hash="0" * 64), tmp_path, request)
    assert stale["status"] == "OPEN"
    assert not stale["measured"]["checks"]["design_hash_matches"]

    corrupted = rtl.replace(".INIT_ROUTER(0)", ".INIT_ROUTER(1)", 1)
    (tmp_path / "project_top.sv").write_text(corrupted)
    row = project_top_rtl._family_binding_gate(params, tmp_path, request)
    assert row["status"] == "OPEN"
    assert not row["measured"]["checks"]["u_slice0_bound"]


def test_cross_domain_slice_emits_both_cdc_directions_and_async_tb_clock():
    request = make_family_request("gec_mecs")
    agents = list(request.agents)
    agents[0] = replace(agents[0], clock_domain="compute_clk")
    request = replace(request, agents=tuple(agents))
    compiled = FabricCompiler().compile(request)
    assert compiled.status == "COMPILED", compiled.error
    params = project_top_rtl.composed_family_params_from_request(request, compiled)

    cells = project_top_rtl._cdc_cells_for_params(params)
    assert {cell.direction for cell in cells} == {"up", "down"}
    assert all(cell.module and cell.filename for cell in cells)
    top = project_top_rtl.render_family_project_top(params)
    tb = project_top_rtl.render_family_tb(params)
    wrappers = project_top_rtl.render_cdc_slice_wrappers(params, cells)
    down = wrappers.split("module cdc_slice_down_0", 1)[1]
    assert ".src_clk(src_clk), .src_rst_n(src_rst_n)" in down
    assert ".dst_clk(dst_clk), .dst_rst_n(dst_rst_n)" in down
    assert "always_ff @(posedge src_clk or negedge src_rst_n)" in down
    assert "always_ff @(posedge dst_clk or negedge dst_rst_n)" in down
    # The crossing is signalled by the slice's fabric clock port; the
    # CDC cells live in the slice's own file.
    slice_src = project_top_rtl.render_family_initiator_slice(params)
    assert ".fabric_clk(clk)" in top
    assert "cdc_slice_up_0" in slice_src and "cdc_slice_down_0" in slice_src
    assert "clk_d0" in tb and ".init0_clk(clk_d0)" in tb
    assert "forever #7 clk_d0 = ~clk_d0" in tb
    assert "S8 CDC reset flushed in-flight transaction without stale B" in tb
    assert "while (!init0_awready && timeout < 100) begin" in tb
    assert "@(negedge clk_d0); timeout = timeout + 1;" in tb
    assert "@(posedge clk_d0); @(negedge clk_d0);" in tb


def test_attachment_mutation_is_refused_without_mutating_original():
    request, compiled, _params = _compiled()
    attachment = replace(compiled.bundle.attachment,
                         endpoints=compiled.bundle.attachment.endpoints[:-1])
    with pytest.raises(ValueError, match="attachment_hash|endpoint count|seat|instance"):
        corrupt = replace(compiled, bundle=replace(compiled.bundle, attachment=attachment))
        project_top_rtl.composed_family_params_from_request(request, corrupt)
    assert len(compiled.bundle.attachment.endpoints) == 3
