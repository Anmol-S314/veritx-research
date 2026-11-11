from __future__ import annotations

import json
import shutil
import subprocess

import pytest

from test_project_top_slice import _family_request
from veritx_dse.application.fabric_compiler import FabricCompiler
from veritx_dse.core.paths import REPO
from veritx_dse.model.topology_intent import ConcentratedMeshIntent
from veritx_dse.product.project_top_rtl import (
    build_family_router, composed_family_params_from_request,
    render_family_project_top, run_composed_family,
)


@pytest.mark.parametrize("concentration", [2, 4])
def test_cmesh_connects_endpoint_ids_not_router_ids(concentration):
    request = _family_request(ConcentratedMeshIntent(2, concentration))
    compiled = FabricCompiler().compile(request)
    params = composed_family_params_from_request(request, compiled)
    top = render_family_project_top(params)
    router = build_family_router(params, compiled.bundle.topology)["router.sv"]
    assert "u_concentrator_0" in top
    assert ".INIT_ENDPOINT(1)" in top
    assert ".TARGET_ENDPOINT(2)" in top
    assert ".DST_ENDPOINT(2)" in top
    assert "cmesh_concentrator #(" in top
    assert "seat_2_noc_out_flit" in top
    assert "seat_2_noc_noc" not in top
    assert "2'd1: return 0;" in router
    assert f"2'd2: return {1 if concentration == 2 else 0};" in router
    assert top == render_family_project_top(params)


def test_cmesh_concentrator_arbitration_demux_and_reset(tmp_path):
    if not shutil.which("iverilog") or not shutil.which("vvp"):
        pytest.skip("Icarus Verilog is not installed")
    from veritx_dse.product.cmesh_rtl import render_cmesh_concentrator

    source = tmp_path / "concentrator.sv"
    source.write_text(render_cmesh_concentrator() + r'''
module tb;
  reg clk = 0;
  always #5 clk = ~clk;
  reg rst_n = 0;
  reg [2:0][7:0] seat_in_flit;
  reg [2:0] seat_in_valid;
  wire [2:0] seat_in_ready;
  wire [7:0] noc_in_flit;
  wire noc_in_valid;
  reg noc_in_ready;
  reg [7:0] noc_out_flit;
  reg noc_out_valid;
  wire noc_out_ready;
  wire [2:0][7:0] seat_out_flit;
  wire [2:0] seat_out_valid;
  reg [2:0] seat_out_ready;
  cmesh_concentrator #(.W(8), .SEATS(3), .DST_LSB(0), .DST_W(2),
                        .ENDPOINT_IDS({2'd2, 2'd1, 2'd0})) dut (.*);
  initial begin
    seat_in_flit = {8'hA2, 8'hB1, 8'hC0};
    seat_in_valid = 3'b010;
    noc_in_ready = 0;
    noc_out_valid = 0;
    noc_out_flit = 0;
    seat_out_ready = 0;
    repeat (2) @(negedge clk);
    rst_n = 1;
    @(negedge clk);
    if (!noc_in_valid || noc_in_flit !== 8'hB1 || seat_in_ready !== 0)
      $fatal(1, "initial stalled grant");
    // A new lower-numbered contender must not change a stalled grant.
    seat_in_valid = 3'b111;
    repeat (4) begin
      @(negedge clk);
      if (!noc_in_valid || noc_in_flit !== 8'hB1 || seat_in_ready !== 0)
        $fatal(1, "grant changed under backpressure");
    end
    noc_in_ready = 1;
    #1;
    if (seat_in_ready !== 3'b010) $fatal(1, "multiple injection winners");
    @(negedge clk);
    if (seat_in_ready !== 3'b100 || noc_in_flit !== 8'hA2)
      $fatal(1, "round robin missed seat 2");
    @(negedge clk);
    if (seat_in_ready !== 3'b001 || noc_in_flit !== 8'hC0)
      $fatal(1, "round robin missed seat 0");
    seat_in_valid = 0;
    // Equal-router destinations are distinguished by endpoint, not sequence.
    noc_out_valid = 1;
    noc_out_flit = 8'hA1;
    seat_out_ready = 3'b101;
    #1;
    if (seat_out_valid !== 3'b010 || noc_out_ready !== 0 ||
        seat_out_flit[1] !== 8'hA1) $fatal(1, "wrong ejection seat");
    repeat (3) @(negedge clk);
    seat_out_ready = 3'b010;
    #1;
    if (!noc_out_ready) $fatal(1, "selected ejection seat blocked");
    noc_out_flit = 8'hA3;
    #1;
    if (seat_out_valid !== 0 || noc_out_ready !== 0)
      $fatal(1, "unknown endpoint consumed");
    noc_out_valid = 0;
    seat_in_valid = 3'b100;
    noc_in_ready = 0;
    @(negedge clk);
    rst_n = 0;
    @(negedge clk);
    seat_in_valid = 3'b001;
    rst_n = 1;
    #1;
    if (noc_in_flit !== 8'hC0) $fatal(1, "stale reset grant");
    $display("PASS: arbitration stability fairness demux reset");
    $finish;
  end
endmodule
''')
    built = subprocess.run(["iverilog", "-g2012", "-s", "tb", "-o",
                            str(tmp_path / "sim"), str(source)],
                           capture_output=True, text=True, timeout=20)
    assert built.returncode == 0, built.stdout + built.stderr
    run = subprocess.run(["vvp", str(tmp_path / "sim")],
                         capture_output=True, text=True, timeout=10)
    assert run.returncode == 0, run.stdout + run.stderr
    assert "PASS: arbitration stability fairness demux reset" in run.stdout


@pytest.mark.parametrize("concentration", [2, 4])
def test_cmesh_composed_transactions(tmp_path, concentration):
    if not shutil.which("verilator"):
        pytest.skip("Verilator is not installed")
    request = _family_request(ConcentratedMeshIntent(2, concentration))
    result = run_composed_family(request.to_dict(), tmp_path,
                                 {"repo_root": str(REPO)})
    assert result["lint"] == "PASS"
    assert result["sim"] == "PASS", result
    assert all(result["scenarios"].values()), result["scenarios"]
    assert result["scenarios"]["concurrent"]
    assert result["scenarios"]["conservation"]
    assert result["scenarios"]["drain"]
    manifest = json.loads(
        (tmp_path / "project-top-manifest.json").read_text())
    assert sum(len(row["endpoint_ids"]) for row in manifest["concentrators"]) == 3
    assert all(row["module"] == "cmesh_concentrator"
               for row in manifest["concentrators"])
