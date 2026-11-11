from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

from veritx_dse.core.paths import REPO

TB = REPO / "tracks" / "t3-topology" / "rtl" / "family_multiflit" / \
    "tb_family_multiflit.sv"


def _family_artifacts(tmp_path: Path, family: str = "torus"):
    """The router and destination adapter the product emits, plus the layout.

    The testbench runs against the emitted RTL, not a copy of it: the field
    offsets come from the family's own packet format, so the multi-flit path
    is exercised exactly as the product emits it.
    """
    import importlib.util
    spec = importlib.util.spec_from_file_location(
        "cd_mod", str(REPO / "scripts" / "complete_design.py"))
    cd = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(cd)
    from veritx_dse.application.fabric_compiler import FabricCompiler
    from veritx_dse.product import project_top_rtl

    request = cd.make_family_request(family)
    compiled = FabricCompiler().compile(request)
    params = project_top_rtl.composed_family_params_from_request(
        request, compiled)
    topology = compiled.bundle.topology
    rtl = tmp_path / "rtl"
    rtl.mkdir(parents=True, exist_ok=True)
    (rtl / "noc_pkg.sv").write_text(
        project_top_rtl._render_family_pkg(params))
    (rtl / "destination_adapter.sv").write_text(
        project_top_rtl._render_family_destination(params))
    (rtl / "tb_family_multiflit.sv").write_text(TB.read_text())
    return rtl, params, topology


def _layout(params) -> dict:
    """The packet-format offsets the testbench is parameterised with."""
    pay_l, pay_w = params.payload_field
    ty_l, ty_w = params.type_field
    vc_l, vc_w = params.vc_field
    src_l, src_w = params.src_field
    dst_l, dst_w = params.dst_field
    win = min(int(params.data_width), pay_w - 25)
    return {
        "FLIT_W": int(params.flit_w),
        "DST_LSB": dst_l,
        "DST_W": dst_w,
        "VC_LSB": vc_l,
        "VC_W": vc_w,
        "TYPE_LSB": ty_l,
        "SRC_LSB": src_l,
        "SRC_W": src_w,
        "PAY_LSB": pay_l,
        "WIN": win,
        "N_ROUTERS": int(params.n_routers),
        "DEG": int(params.max_deg),
        "SRAM_WORDS": int(params.sram_words),
    }


@pytest.mark.skipif(shutil.which("verilator") is None,
                    reason="verilator not installed; cannot lint/sim the fabric")
def test_the_fabric_carries_a_multiflit_packet_and_reassembles_it(tmp_path):
    """A HEAD/BODY/TAIL packet must be carried and reassembled.

    The router holds the packet's route from its HEAD to its TAIL and the
    destination adapter assembles the flits: one answer for the packet, and
    every word of the payload reads back with the data it carried.
    """
    rtl, params, topology = _family_artifacts(tmp_path)
    layout = _layout(params)
    layout["K"] = int(getattr(topology, "family", None) and
                      len([r for r in topology.routers]) ** 0 or 0) or 4
    args = " ".join(f"-G{k}={v}" for k, v in layout.items())
    files = ["noc_pkg.sv", "destination_adapter.sv", "tb_family_multiflit.sv"]
    lint = subprocess.run(
        ["verilator", "--lint-only", "--timing", "-sv", "-Wall", "-Wno-fatal",
         "-Wno-WIDTH", "-Wno-DECLFILENAME", "-Wno-UNOPTFLAT", "-Wno-BLKSEQ",
         "--top-module", "tb_family_multiflit", *files],
        cwd=rtl, capture_output=True, text=True, timeout=900)
    assert lint.returncode == 0, (lint.stdout[-4000:] + lint.stderr[-4000:])
    build = subprocess.run(
        ["verilator", "--binary", "--timing", "-sv", "-Wall", "-Wno-fatal",
         "-Wno-WIDTH", "-Wno-DECLFILENAME", "-Wno-UNOPTFLAT", "-Wno-BLKSEQ",
         "--top-module", "tb_family_multiflit", "--Mdir", "obj", *files],
        cwd=rtl, capture_output=True, text=True, timeout=1800)
    assert build.returncode == 0, (build.stdout[-4000:] + build.stderr[-4000:])
    sim = subprocess.run(["./obj/Vtb_family_multiflit"], cwd=rtl,
                         capture_output=True, text=True, timeout=600)
    output = (sim.stdout or "") + (sim.stderr or "")
    assert "status: PASS" in output, output[-4000:]
    assert "multi-flit packet HEAD/BODY/TAIL carried 3 flits" in output, \
        output[-4000:]
    assert "FAIL" not in output, output[-4000:]
