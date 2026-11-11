"""Endpoint-tag wiring must connect memory and initiators sharing a router."""
from __future__ import annotations

import json
import shutil
import zipfile

import pytest

from test_project_top_slice import _family_request
from veritx_dse.application.fabric_compiler import FabricCompiler
from veritx_dse.core.paths import REPO
from veritx_dse.model.topology_intent import (
    FatTreeIntent, FlyIntent, QTreeIntent, Tree4Intent,
)
from veritx_dse.product.project_top_rtl import (
    build_family_router, composed_family_params_from_request,
    render_family_project_top, run_composed_family,
)


FAMILIES = [
    pytest.param(FlyIntent(4, 3), id="fly"),
    pytest.param(QTreeIntent(4, 3), id="qtree"),
    pytest.param(Tree4Intent(4, 3), id="tree4"),
    pytest.param(FatTreeIntent(4, 2), id="fattree"),
]


@pytest.mark.parametrize("intent", FAMILIES)
def test_memory_seat_endpoint_wiring(intent):
    request = _family_request(intent)
    compiled = FabricCompiler().compile(request)
    assert compiled.status == "COMPILED", compiled.error
    endpoints = compiled.bundle.attachment.endpoints
    assert len({e.router_id for e in endpoints}) < len(endpoints)
    params = composed_family_params_from_request(request, compiled)
    top = render_family_project_top(params)
    router = build_family_router(params, compiled.bundle.topology)["router.sv"]
    assert "cmesh_concentrator #(" in top
    assert ".INIT_ENDPOINT(1)" in top
    assert ".TARGET_ENDPOINT(2)" in top
    assert ".DST_ENDPOINT(2)" in top
    assert ".req_flit(seat_2_noc_out_flit)" in top
    assert "seat_2_noc_noc" not in top
    for endpoint, _ingress, egress in params.endpoint_seats:
        assert f"{params.dst_field[1]}'d{endpoint}: return {egress};" in router
    assert top == render_family_project_top(params)


@pytest.mark.skipif(shutil.which("verilator") is None, reason="Verilator is not installed")
@pytest.mark.parametrize("intent", FAMILIES)
def test_memory_seat_composed_transactions(tmp_path, intent):
    request = _family_request(intent)
    result = run_composed_family(request.to_dict(), tmp_path, {"repo_root": str(REPO)})
    assert result["lint"] == "PASS", result
    assert result["sim"] == "PASS", result
    assert all(result["scenarios"].values()), result["scenarios"]
    for name in ("concurrent", "conservation", "drain", "backpressure_stall",
                 "backpressure_release", "ordering_stall", "ordering_inorder"):
        assert result["scenarios"][name]
    manifest = json.loads((tmp_path / "project-top-manifest.json").read_text())
    params = result["family_params"]
    active_routers = {row[key] for row in params["endpoint_seats"]
                      for key in ("ingress_router", "egress_router")}
    assert {row["router_id"] for row in manifest["concentrators"]} == active_routers
    assert all(row["module"] == "cmesh_concentrator" for row in manifest["concentrators"])
    meta = json.loads((tmp_path / "rtl" / "meta.json").read_text())
    assert "cmesh_concentrator.sv" in meta["files"]
    assert "cmesh_concentrator.sv" in {row["path"] for row in manifest["files"]}
    with zipfile.ZipFile(tmp_path / "project-top.zip") as archive:
        assert "rtl/cmesh_concentrator.sv" in archive.namelist()
