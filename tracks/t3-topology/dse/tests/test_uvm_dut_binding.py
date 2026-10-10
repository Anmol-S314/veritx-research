"""Exercise generated native pins against the real mesh, without mocking UVM.

This qualifies only link-interface binding. UVM execution and compiled
packet-format equivalence remain separate, unsupported claims.

Lint scope: the emitted ``assertions.sv`` and ``noc_dut_binding.sv`` both
pass ``verilator --lint-only`` for the supported mesh case. The UVM sources
(``tb_noc.sv``, ``seq_lib.sv``, ``cov.sv``) are deliberately NOT linted: they
need ``uvm_pkg`` and no UVM library exists in this repository (the P9 audit
forbids vendoring one), and ``cov.sv`` additionally uses class-scoped
covergroups, which Verilator does not support with any library. What is
pinned for those sources is parse-readiness — the package import and the
``noc_tx`` declaration the sequences and coverpoints name.
"""
from __future__ import annotations

import shutil
import subprocess
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace

import pytest

from veritx_dse.application.fabric_compiler import FabricCompiler
from veritx_dse.application.presets import build_preset_request
from veritx_dse.model.compile_model import DependencyGraph
from veritx_dse.verification.uvm_gen import UvmGenerationError, generate_uvm_for_bundle

REPO = Path(__file__).resolve().parents[4]
RTL = REPO / "tracks/t3-topology/rtl/t3"

# Lint flags mirror tests/test_rtl_generation.py: the repository RTL has known
# width/timescale warnings, so -Wno-fatal keeps them non-fatal exactly as the
# emitter's own Makefile does. No error is suppressed.
_LINT_FLAGS = ("--lint-only", "-sv", "-Wno-fatal", "-Wno-TIMESCALEMOD",
               "-Wno-WIDTH", "-Wno-WIDTHEXPAND", "-Wno-WIDTHTRUNC",
               "-Wno-UNSIGNED", "-Wno-DECLFILENAME")
_LINT_RTL = ("noc_pkg.sv", "islip.sv", "router.sv", "mesh.sv")

SMOKE = """
`timescale 1ns/1ps
module tb_binding;
  import noc_pkg::*;
  logic clk = 0;
  logic rst_n = 0;
  always #5 clk = ~clk;
  link_f_t inject [4];
  link_c_t inject_credit [4];
  link_c_t inject_credit_early [4];
  link_f_t eject [4];
  link_c_t eject_credit [4];
  int injected = 0;
  int accepted = 0;
  bit [1:0] seen = 0;

  noc_dut_binding #(.K(2), .NUM_VCS(VC_COUNT)) binding (.*);
  for (genvar n = 0; n < 4; n++) begin
    assign eject_credit[n].valid = eject[n].valid;
    assign eject_credit[n].vc = eject[n].flit.vc;
  end

  always @(posedge clk) begin
    if (rst_n) begin
      for (int n = 0; n < 4; n++) begin
        if (inject[n].valid) injected++;
        if (eject[n].valid) begin
          if (eject[n].flit.dst != n || !eject[n].flit.head || !eject[n].flit.tail)
            $fatal(1, "wrong endpoint or framing");
          case (eject[n].flit.pid)
            16'd1: begin
              if (n != 3 || eject[n].flit.src != 0 || seen[0])
                $fatal(1, "packet 1 misrouted or duplicated");
              seen[0] = 1;
            end
            16'd2: begin
              if (n != 0 || eject[n].flit.src != 3 || seen[1])
                $fatal(1, "packet 2 misrouted or duplicated");
              seen[1] = 1;
            end
            default: $fatal(1, "undeclared packet");
          endcase
          accepted++;
        end
      end
    end
  end

  initial begin
    for (int n = 0; n < 4; n++) inject[n] = '0;
    repeat (4) @(negedge clk);
    rst_n = 1;
    repeat (2) @(negedge clk);
    // One flit on a freshly reset VC cannot exceed the input credit depth.
    inject[0].valid = 1;
    inject[0].flit.head = 1;
    inject[0].flit.tail = 1;
    inject[0].flit.dst = 3;
    inject[0].flit.pid = 1;
    inject[3].valid = 1;
    inject[3].flit.head = 1;
    inject[3].flit.tail = 1;
    inject[3].flit.src = 3;
    inject[3].flit.pid = 2;
    @(negedge clk);
    for (int n = 0; n < 4; n++) inject[n].valid = 0;
    repeat (100) @(negedge clk);
    if (injected != 2 || accepted != injected || seen != 2'b11)
      $fatal(1, "conservation failed: injected=%0d accepted=%0d", injected, accepted);
    $display("BINDING_PASS injected=%0d accepted=%0d", injected, accepted);
    $finish;
  end
endmodule
"""


def test_binding_refuses_vcs_beyond_native_rtl_capacity():
    bundle = FabricCompiler().compile(build_preset_request("mesh4")).bundle
    unsupported = SimpleNamespace(
        design=bundle.design, topology=bundle.topology,
        router_route=bundle.router_route, vc_assignment=SimpleNamespace(vc_count=5))
    with pytest.raises(UvmGenerationError, match="1..4 VCs"):
        generate_uvm_for_bundle(unsupported)


def _bundle(*, router_count=4, family="mesh", vc_count=2,
            routing=("DOR_XY",), side_length=None, concentration=None):
    """A minimal fabric record for the refusal paths of the canonical entry."""
    design = SimpleNamespace(
        topology=SimpleNamespace(side_length=side_length,
                                 concentration=concentration),
        noc_config=None)
    topology = SimpleNamespace(router_count=router_count,
                               family=SimpleNamespace(value=family))
    return SimpleNamespace(
        design=design, topology=topology,
        vc_assignment=SimpleNamespace(vc_count=vc_count),
        router_route=SimpleNamespace(routing_classes=tuple(
            SimpleNamespace(id=name) for name in routing)))


@pytest.mark.parametrize("reason,kwargs", [
    ("noc_mesh", dict(family="torus")),
    ("concentration=2", dict(router_count=9, side_length=3, concentration=2)),
    ("DOR_XY", dict(routing=("MIN_ADAPT",))),
    ("declares no routing classes", dict(routing=())),
    ("1..4 VCs", dict(vc_count=5)),
    ("at most 256 nodes", dict(router_count=289)),
    ("K >= 2", dict(router_count=1)),
    ("did not produce", dict(router_count=9, side_length=4)),
], ids=["non-mesh", "concentration-2", "non-dor", "no-routing-class",
        "five-vcs", "289-nodes", "single-router", "contradictory-grid"])
def test_generate_uvm_for_bundle_refuses_fabrics_it_cannot_describe(
        reason, kwargs):
    """Every fabric the collateral cannot honestly describe is a typed
    refusal, never a stretch of the emitted DUT."""
    with pytest.raises(UvmGenerationError, match=reason):
        generate_uvm_for_bundle(_bundle(**kwargs))


def _emit_mesh4(tmp_path):
    """Write the five emitted sources for the supported 2x2 mesh preset."""
    compilation = FabricCompiler().compile(build_preset_request("mesh4"))
    assert compilation.status == "COMPILED", compilation.error
    result = generate_uvm_for_bundle(compilation.bundle, revision_id="r-lint")
    written = {}
    for name, key in (("noc_dut_binding.sv", "dut_binding"),
                      ("assertions.sv", "assertions"),
                      ("tb_noc.sv", "tb_top"),
                      ("seq_lib.sv", "sequences"),
                      ("cov.sv", "coverage")):
        assert name in result["files"], name
        written[name] = tmp_path / name
        written[name].write_text(result[key])
    return result, written


@pytest.mark.parametrize("source", ["seq_lib.sv", "cov.sv"])
def test_the_uvm_sources_declare_what_they_reference(tmp_path, source):
    """The sequences and coverpoints can elaborate once a UVM library is
    present: the package import and the ``noc_tx`` they name are emitted.

    Neither source used to contain either one — ``noc_tx`` was an undefined
    class ("Package/class 'noc_tx' not found") and ``uvm_sequence`` was
    unresolvable (only the macro header was included, never imported).
    """
    _, written = _emit_mesh4(tmp_path)
    text = written[source].read_text()
    assert "import uvm_pkg::*;" in text
    assert "class noc_tx extends uvm_sequence_item;" in text
    assert "`include \"uvm_macros.svh\"" in text


def test_generated_assertions_lint_with_verilator(tmp_path):
    """The assertion file is legal SVA on the supported mesh case.

    It lints on its own: no UVM library and no repository RTL are needed to
    parse it (the F2/F8 local-variable-as-property declarations used to make
    Verilator abort the file with "Unsupported: property variable
    declaration" plus a syntax error on every property after them).
    """
    tool = shutil.which("verilator")
    if tool is None:
        pytest.skip("Verilator is required to lint the emitted assertions")
    _, written = _emit_mesh4(tmp_path)
    lint = subprocess.run(
        [tool, *_LINT_FLAGS, "--top-module", "noc_assertions",
         str(written["assertions.sv"])],
        capture_output=True, text=True, timeout=120)
    assert lint.returncode == 0, lint.stdout + lint.stderr


def test_generated_binding_lints_with_verilator(tmp_path):
    """The emitted native binding lints against the repository mesh."""
    tool = shutil.which("verilator")
    if tool is None:
        pytest.skip("Verilator is required to lint the emitted binding")
    _, written = _emit_mesh4(tmp_path)
    lint = subprocess.run(
        [tool, *_LINT_FLAGS, "--top-module", "noc_dut_binding",
         *[str(RTL / name) for name in _LINT_RTL],
         str(written["noc_dut_binding.sv"])],
        capture_output=True, text=True, timeout=300)
    assert lint.returncode == 0, lint.stdout + lint.stderr


@pytest.mark.parametrize("single_vc", [False, True])
def test_generated_binding_runs_against_repository_mesh(tmp_path, single_vc):
    tool = shutil.which("verilator")
    if tool is None:
        pytest.skip("Verilator is required for native DUT binding smoke")
    request = build_preset_request("mesh4")
    if single_vc:
        request = replace(request, dependencies=DependencyGraph(
            request.dependencies.dependencies[:1]))
    compilation = FabricCompiler().compile(request)
    assert compilation.status == "COMPILED", compilation.error
    result = generate_uvm_for_bundle(compilation.bundle)
    assert result["fabric"]["k"] == 2
    binding = tmp_path / "noc_dut_binding.sv"
    binding.write_text(result["dut_binding"])
    smoke = tmp_path / "tb_binding.sv"
    smoke.write_text(SMOKE.replace("VC_COUNT", str(result["fabric"]["vc_count"])))
    obj = tmp_path / "obj"
    command = [tool, "--binary", "--timing", "-j", "2", "-Wno-fatal",
               "--top-module", "tb_binding", "--Mdir", str(obj)]
    command += [str(RTL / name) for name in (
        "noc_pkg.sv", "islip.sv", "router.sv", "mesh.sv")]
    command += [str(binding), str(smoke)]
    built = subprocess.run(command, capture_output=True, text=True, timeout=120)
    assert built.returncode == 0, built.stdout + built.stderr
    ran = subprocess.run([str(obj / "Vtb_binding")], capture_output=True,
                         text=True, timeout=10)
    assert ran.returncode == 0, ran.stdout + ran.stderr
    assert "BINDING_PASS injected=2 accepted=2" in ran.stdout
