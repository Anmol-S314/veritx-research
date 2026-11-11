from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest

from veritx_dse.product.project_top_rtl import (
    SLICE_BUF,
    UNREALIZED_ROUTER_CONTROLS,
    render_tb_project_top,
    run_rtl_slice,
)
from veritx_dse.core.paths import REPO

from test_project_top_slice import _slice_request

EXPECTED_18 = (
    "allow_write_init0", "allow_read_init0", "deny_write_init1",
    "allow_read_init1", "error_miss_decerr", "error_slave_slverr",
    "ordering_stall", "ordering_inorder", "backpressure_stall",
    "backpressure_release", "concurrent", "burst_allowed",
    "burst_crossing_denied", "wstrb_enforcement", "burst_backpressure",
    "id_isolation", "conservation", "drain",
)


@pytest.fixture(scope="module")
def slice_build(tmp_path_factory):
    if shutil.which("verilator") is None:
        pytest.skip("verilator not installed; cannot lint/sim the composed top")
    out = tmp_path_factory.mktemp("p8_mesh2x2") / "out"
    request = _slice_request()
    result = run_rtl_slice(request.to_dict(), out, {"repo_root": str(REPO)})
    return result, out


@pytest.fixture(scope="module")
def declared_depth_build(tmp_path_factory):
    if shutil.which("verilator") is None:
        pytest.skip("verilator not installed; cannot lint/sim the composed top")
    import dataclasses
    out = tmp_path_factory.mktemp("p8_mesh2x2_declared") / "out"
    request = _slice_request()
    request = dataclasses.replace(
        request,
        noc_controls=dataclasses.replace(
            request.noc_controls, input_buffer_depth_flits_per_vc=SLICE_BUF))
    result = run_rtl_slice(request.to_dict(), out, {"repo_root": str(REPO)})
    return result, out


def test_p8_tb_render_is_deterministic():
    assert render_tb_project_top() == render_tb_project_top()
    assert SLICE_BUF == 8


def test_p8_existing_18_scenarios_still_pass(slice_build):
    result, _ = slice_build
    assert result["scenarios"], result
    assert set(result["scenarios"]) == set(EXPECTED_18)
    assert all(result["scenarios"].values()), result["scenarios"]
    assert result["sim"] == "PASS"
    assert result["lint"] == "PASS"


def test_p8_manifest_declares_buffer_depth(slice_build):
    _, out = slice_build
    manifest = json.loads((out / "project-top-manifest.json").read_text())
    assert manifest["slice_params"]["buf_depth_per_vc"] == [SLICE_BUF, SLICE_BUF]
    assert "depth 8 per VC (2 VCs)" in manifest["slice_profile"]["buffers"]
    assert "stay single-flit" in manifest["slice_profile"]["multi_flit_policy"]


def test_p8_manifest_declared_input_buffer_depth_from_request(declared_depth_build):
    result, out = declared_depth_build
    manifest = json.loads((out / "project-top-manifest.json").read_text())
    assert manifest["source_controls"]["input_buffer_depth_flits_per_vc"] == SLICE_BUF
    assert manifest["slice_params"]["buf_depth_per_vc"] == [SLICE_BUF, SLICE_BUF]
    assert result["sim"] == "PASS"
    assert all(result["scenarios"].values()), result["scenarios"]


def test_p8_credit_return_latency_cycles_is_refused_unrealized():
    assert "credit_return_latency_cycles" in UNREALIZED_ROUTER_CONTROLS
    assert "credit_return_latency_cycles" not in _slice_request().noc_controls.to_dict()
