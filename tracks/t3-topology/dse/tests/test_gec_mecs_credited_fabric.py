from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

from veritx_dse.core.paths import REPO

FULL_SHAPE = dict(k=9, concentration=1, express_groups=1, taps_per_wire=8,
                   num_vcs=8, router_count=81, shared_wires=162, flit_w=64,
                   dest_w=7, ports=17, drop_field_lsb=57, drop_field_w=7)


def _params(**overrides):
    from veritx_dse.product.gec_mecs_scaled import ScaledMecsParams
    shape = dict(FULL_SHAPE)
    shape.update(overrides)
    return ScaledMecsParams(**shape)


def _write_split(work: Path, text: str) -> list[Path]:
    """Write the fabric, its router and the proven pool, one module per file."""
    from veritx_dse.product.gec_mecs_credited import render_credited_pool
    from veritx_dse.product.gec_mecs_scaled import split_scaled_fabric
    router, fabric = split_scaled_fabric(text)
    files = [work / "gec_mecs16_fabric.sv", work / "gec_mecs_router.sv",
             work / "tap_credit_pool.sv"]
    files[0].write_text(fabric)
    files[1].write_text(router)
    files[2].write_text(render_credited_pool())
    return files


def _emit(params, work: Path) -> tuple[Path, Path]:
    from veritx_dse.product.gec_mecs_scaled import (
        render_scaled_fabric, render_scaled_tb,
    )
    work.mkdir(parents=True, exist_ok=True)
    tb = work / "tb_gec_mecs16_fabric.sv"
    # One module per file: the fabric, its router and the proven pool.
    from veritx_dse.product.gec_mecs_credited import render_credited_pool
    from veritx_dse.product.gec_mecs_scaled import split_scaled_fabric
    router, fabric = split_scaled_fabric(render_scaled_fabric(params))
    files = [work / "gec_mecs16_fabric.sv", work / "gec_mecs_router.sv",
             work / "tap_credit_pool.sv"]
    files[0].write_text(fabric)
    files[1].write_text(router)
    files[2].write_text(render_credited_pool())
    tb.write_text(render_scaled_tb(params))
    return files, tb


@pytest.mark.skipif(shutil.which("verilator") is None,
                    reason="verilator not installed; cannot lint/sim the fabric")
def test_credited_shared_fabric_lints_and_simulates_the_full_shape(tmp_path):
    """The full-size shared fabric must lint and simulate with its credits.

    The pinned 81-router contract (162 shared wires, 8 taps per wire, 8 VCs)
    is the shape whose flow control was nominal; the credited fabric is the
    one that carries per-tap credit accounting.
    """
    files, tb = _emit(_params(), tmp_path)
    lint = subprocess.run(
        ["verilator", "--lint-only", "--timing", "-sv", "-Wall", "-Wno-fatal",
         "-Wno-WIDTH", "-Wno-PINNOTFOUND", "-Wno-UNOPTFLAT", "-Wno-DECLFILENAME",
         "-Wno-BLKSEQ", "--top-module", "gec_mecs16_fabric", *[f.name for f in files]],
        cwd=tmp_path, capture_output=True, text=True, timeout=900)
    assert lint.returncode == 0, (lint.stdout[-4000:] + lint.stderr[-4000:])
    build = subprocess.run(
        ["verilator", "--binary", "--timing", "-sv", "-Wall", "-Wno-fatal",
         "-Wno-WIDTH", "-Wno-PINNOTFOUND", "-Wno-UNOPTFLAT", "-Wno-DECLFILENAME",
         "-Wno-BLKSEQ", "--top-module", "tb_gec_mecs16_fabric", "--Mdir",
         "obj_shared", *[f.name for f in files], tb.name],
        cwd=tmp_path, capture_output=True, text=True, timeout=1800)
    assert build.returncode == 0, (build.stdout[-4000:] + build.stderr[-4000:])
    sim = subprocess.run(["./obj_shared/Vtb_gec_mecs16_fabric"], cwd=tmp_path,
                         capture_output=True, text=True, timeout=900)
    output = (sim.stdout or "") + (sim.stderr or "")
    assert "status: PASS" in output, output[-4000:]
    assert "PASS gec_mecs16 routers=81 shared_wires=162 taps_per_wire=8" in output, \
        output[-4000:]
    assert "FAIL" not in output, output[-4000:]


@pytest.mark.skipif(shutil.which("verilator") is None, reason="verilator not installed")
def test_physical_returns_preserve_every_flit_bit_and_vc(tmp_path):
    params = _params(k=3, taps_per_wire=2, num_vcs=2, router_count=9,
                     shared_wires=18, dest_w=4, ports=5,
                     drop_field_lsb=60, drop_field_w=4)
    files, tb = _emit(params, tmp_path)
    source = tb.read_text()
    source = source.replace("    oversubscribe(0, 1, 2);", '''
    repeat (40) @(negedge clk);
    for (int r = 0; r < N; r++) begin
      if (dut.row_outstanding[r] != 0 || dut.col_outstanding[r] != 0)
        $fatal(1, "initial credits have not drained router=%0d row=%0d col=%0d", r, dut.row_outstanding[r], dut.col_outstanding[r]);
    end
    oversubscribe(0, 1, 2);''')
    source = source.replace('    $display("status: PASS");', '''
    repeat (40) @(negedge clk);
    for (int r = 0; r < N; r++) begin
      if (dut.row_alias[r] || dut.col_alias[r] ||
          dut.row_outstanding[r] != 0 || dut.col_outstanding[r] != 0 ||
          dut.row_available[r] != (K-1)*NUM_VCS*CAPACITY ||
          dut.col_available[r] != (K-1)*NUM_VCS*CAPACITY)
        $fatal(1, "physical return credit imbalance router=%0d", r);
    end
    $display("status: PASS");''')
    tb.write_text(source)
    build = subprocess.run(
        ["verilator", "--binary", "--timing", "-sv", "-Wall", "-Wno-fatal",
         "-Wno-DECLFILENAME", "-Wno-BLKSEQ", "--top-module",
         "tb_gec_mecs16_fabric", "--Mdir", "obj_physical", *[f.name for f in files], tb.name],
        cwd=tmp_path, capture_output=True, text=True, timeout=180)
    log = build.stdout + build.stderr
    assert build.returncode == 0, log[-6000:]
    for structural in ("LATCH", "UNDRIVEN", "UNOPTFLAT"):
        assert f"%Warning-{structural}" not in log, log[-6000:]
    sim = subprocess.run(["./obj_physical/Vtb_gec_mecs16_fabric"], cwd=tmp_path,
                         capture_output=True, text=True, timeout=30)
    output = sim.stdout + sim.stderr
    assert sim.returncode == 0, output[-6000:]
    assert "status: PASS" in output, output[-6000:]


def test_compiled_packet_fields_and_endpoint_map_are_preserved(tmp_path):
    from veritx_dse.product.gec_mecs_scaled import render_scaled_fabric

    params = _params(k=4, taps_per_wire=3, num_vcs=3, router_count=16,
                     shared_wires=32, dest_w=4, ports=7,
                     drop_field_lsb=60, drop_field_w=4)
    text = render_scaled_fabric(
        params, destination_field=(58, 2), vc_field=(62, 2),
        endpoint_routers=(0, 1, 2))
    assert "localparam int DEST_LSB = 58;" in text
    assert "localparam int VC_LSB = 62;" in text
    assert "2'd0: return 0;" in text
    assert "2'd1: return 1;" in text
    assert "2'd2: return 2;" in text
    assert "default: return K*K;" in text
    assert "TAP_LSB" not in text
    assert "pop_tap_report" not in text
    files = _write_split(tmp_path, text)
    lint = subprocess.run(
        ["verilator", "--lint-only", "--timing", "-sv", "-Wno-fatal",
         "-Wno-WIDTH", "-Wno-PINNOTFOUND", "-Wno-UNOPTFLAT",
         "-Wno-DECLFILENAME", "--top-module", "gec_mecs16_fabric",
         *[f.name for f in files]],
        cwd=tmp_path, capture_output=True, text=True, timeout=120)
    assert lint.returncode == 0, lint.stdout + lint.stderr


@pytest.mark.skipif(shutil.which("verilator") is None, reason="verilator not installed")
def test_compiled_gec_field_map_routes_axially_and_restores_credits(tmp_path):
    from veritx_dse.product.gec_mecs_scaled import render_scaled_fabric

    params = _params(k=4, taps_per_wire=3, num_vcs=3, router_count=16,
                     shared_wires=32, dest_w=4, ports=7,
                     drop_field_lsb=60, drop_field_w=4)
    tb = tmp_path / "tb_compiled_gec.sv"
    files = _write_split(tmp_path, render_scaled_fabric(
        params, destination_field=(58, 2), vc_field=(62, 2),
        endpoint_routers=(0, 1, 2)))
    tb.write_text('''
`timescale 1ns/1ps
module tb_compiled_gec;
  localparam int N=16, W=64, K=4, NUM_VCS=3, CAPACITY=4;
  logic clk=0, rst_n=0;
  always #5 clk=~clk;
  logic [N-1:0] ep_in_valid='0, ep_in_ready;
  logic [N-1:0][W-1:0] ep_in_flit='0;
  logic [N-1:0] ep_out_valid, ep_out_ready='0;
  logic [N-1:0][W-1:0] ep_out_flit;
  int accepted=0, delivered=0, seq=0;
  logic [W-1:0] expected;
  gec_mecs16_fabric dut(.*);
  function automatic logic [W-1:0] packet(input int src, dst, vc, id);
    logic [W-1:0] f;
    f='1;
    f[0+:56]=56'(64'hd6e8_feb8_6659_fd93 ^ (64'(id)<<9) ^ 64'(src*17+dst));
    f[56+:2]=2'(src);
    f[58+:2]=2'(dst);
    f[62+:2]=2'(vc);
    return f;
  endfunction
  initial begin
    repeat(4) @(posedge clk);
    @(negedge clk); rst_n=1;
    for (int src=0; src<3; src++) begin
      for (int dst=0; dst<3; dst++) begin
        expected=packet(src,dst,seq%NUM_VCS,seq);
        @(negedge clk); ep_in_flit[src]=expected; ep_in_valid[src]=1;
        while (!ep_in_ready[src]) @(negedge clk);
        @(posedge clk); accepted++;
        @(negedge clk); ep_in_valid[src]=0;
        begin : wait_eject
          int cycles;
          cycles=0;
          while (!ep_out_valid[dst] && cycles<200) begin @(negedge clk); cycles++; end
          if (!ep_out_valid[dst]) $fatal(1,"route timeout src=%0d dst=%0d",src,dst);
          if (ep_out_flit[dst] !== expected)
            $fatal(1,"compiled-field packet corruption src=%0d dst=%0d got=%h exp=%h",src,dst,ep_out_flit[dst],expected);
          repeat(2) begin
            @(negedge clk);
            if (!ep_out_valid[dst] || ep_out_flit[dst] !== expected)
              $fatal(1,"stalled packet changed src=%0d dst=%0d",src,dst);
          end
        end
        ep_out_ready[dst]=1;
        @(posedge clk); delivered++;
        @(negedge clk); ep_out_ready[dst]=0;
        seq++;
      end
    end
    begin : wait_credits
      int cycles;
      bit drained;
      cycles=0; drained=0;
      while (!drained && cycles<2000) begin
        @(negedge clk); cycles++;
        drained=1;
        for (int r=0; r<N; r++)
          if (dut.row_outstanding[r]!=0 || dut.col_outstanding[r]!=0) drained=0;
      end
      if (!drained) $fatal(1,"credits did not drain");
    end
    for (int r=0; r<N; r++) begin
      if (dut.row_alias[r] || dut.col_alias[r] ||
          dut.row_available[r] != (K-1)*NUM_VCS*CAPACITY ||
          dut.col_available[r] != (K-1)*NUM_VCS*CAPACITY)
        $fatal(1,"credit imbalance router=%0d",r);
    end
    if (accepted!=9 || delivered!=9) $fatal(1,"transaction mismatch");
    $display("PASS compiled GEC field map packets=%0d VCs=%0d credits=restored",delivered,NUM_VCS);
    $finish;
  end
  initial begin #200000; $fatal(1,"timeout"); end
endmodule
''')
    build = subprocess.run(
        ["verilator", "--binary", "--timing", "-sv", "-Wno-fatal",
         "-Wno-WIDTH", "-Wno-UNOPTFLAT", "-Wno-DECLFILENAME",
         "--top-module", "tb_compiled_gec", "--Mdir", "obj_compiled",
         *[f.name for f in files], tb.name], cwd=tmp_path, capture_output=True, text=True,
        timeout=180)
    assert build.returncode == 0, (build.stdout + build.stderr)[-6000:]
    sim = subprocess.run(["./obj_compiled/Vtb_compiled_gec"], cwd=tmp_path,
                         capture_output=True, text=True, timeout=30)
    output = sim.stdout + sim.stderr
    assert sim.returncode == 0, output[-6000:]
    assert "PASS compiled GEC field map packets=9 VCs=3 credits=restored" in output


def test_compiled_field_map_refuses_overlap_or_bad_endpoint_identity():
    from veritx_dse.product.gec_mecs_scaled import render_scaled_fabric
    from veritx_dse.product.gec_mecs_credited import CreditedFabricError

    params = _params(k=4, taps_per_wire=3, num_vcs=3, router_count=16,
                     shared_wires=32, dest_w=4, ports=7,
                     drop_field_lsb=60, drop_field_w=4)
    with pytest.raises(CreditedFabricError, match="overlap"):
        render_scaled_fabric(params, destination_field=(58, 4), vc_field=(60, 2),
                             endpoint_routers=(0, 1, 2))
    with pytest.raises(CreditedFabricError, match="endpoint map"):
        render_scaled_fabric(params, destination_field=(58, 2), vc_field=(62, 2),
                             endpoint_routers=(0, 0, 2))


def test_the_credited_fabric_carries_the_proven_credit_pool():
    """The emitted fabric must carry the proven pool, not a copy of it."""
    from veritx_dse.product.gec_mecs_credited import render_credited_pool
    from veritx_dse.product.gec_mecs_scaled import render_scaled_fabric
    text = render_scaled_fabric(_params())
    # The pool travels in its own file, one module per file, so the
    # fabric instantiates it and the file that holds it is the proven
    # source verbatim.
    assert "tap_credit_pool #(" in text
    pool = render_credited_pool()
    proven = (REPO / "tracks" / "t3-topology" / "rtl" / "tap_credit" /
              "tap_credit_pool.sv").read_text()
    assert pool == proven, "the emitted pool is not the proven pool source"


def test_the_credit_transformation_refuses_a_template_it_does_not_know():
    """A template change must not silently drop the credit wiring."""
    from veritx_dse.product.gec_mecs_credited import (
        CreditedFabricError, render_credited_fabric,
    )
    with pytest.raises(CreditedFabricError):
        render_credited_fabric(
            template="module not_the_fabric; endmodule\n", module_name="x",
            k=9, flit_w=64, dest_w=7, num_vcs=8, taps_per_wire=8,
            capacity=4, wire_latency=1)


def test_the_historical_sixteen_router_fabric_is_untouched():
    """The pinned 16-router artifact must stay byte-identical."""
    from veritx_dse.product.project_top_rtl import GEC_MECS_FABRIC_SV
    assert "tap_credit_pool" not in GEC_MECS_FABRIC_SV
    assert "module tap_credit_pool" not in GEC_MECS_FABRIC_SV


def test_the_credit_wiring_names_the_tap_and_vc_domain():
    """The grant must claim a credit of the exact (tap, VC)."""
    from veritx_dse.product.gec_mecs_scaled import render_scaled_fabric
    text = render_scaled_fabric(_params())
    assert ".req_tap(row_req_tap), .req_vc(row_req_vc)" in text
    assert ".free_tap(pop_rel_row_tap), .free_vc(pop_rel_row_vc), .free_valid(pop_rel_row_valid)" in text
    assert "row_ret_arrivals[src]" in text
    assert "row_ret_count[src][t][v]" in text
    assert "row_credits[cand_tap][cand_vc] != '0" in text
