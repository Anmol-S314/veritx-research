"""Execute the emitted standalone F3 checker; no UVM/DUT proof is claimed."""
from pathlib import Path
import shutil
import subprocess

import pytest

from veritx_dse.model.compile_model import (
    Agent, AgentKind, CompileRequest, DependencyGraph, ModelFamily,
    NocConfig, TopologyFamily, Workload,
)
from veritx_dse.verification.uvm_gen import generate_uvm


def _collateral():
    cr = CompileRequest(
        workload=Workload(model_family=ModelFamily.CUSTOM), requirements=(),
        agents=(Agent(AgentKind.COMPUTE_TILE, 4),),
        dependencies=DependencyGraph([]),
        noc_config=NocConfig(topology_family=TopologyFamily.MESH))
    return generate_uvm(cr, n_nodes=4, k=2)


def test_f3_is_explicitly_external_not_fabricated_tb_verification():
    collateral = _collateral()
    assert "noc_assertions.sv is EXTERNAL collateral" in collateral["tb_top"]
    assert "check_drained()" in collateral["tb_top"]
    assert "not loss freedom" in collateral["assertions"]
    assert "task automatic check_drained()" in collateral["assertions"]


@pytest.fixture(scope="module")
def checker_binary(tmp_path_factory):
    verilator = shutil.which("verilator")
    if not verilator:
        pytest.skip("Verilator absent: standalone SVA runtime proof unavailable")
    work = tmp_path_factory.mktemp("f3-sv")
    assertions = work / "noc_assertions.sv"
    assertions.write_text(_collateral()["assertions"])
    harness = work / "checker_tb.sv"
    harness.write_text('''module checker_tb;
  logic clk = 0;
  logic rst_n = 0;
  logic [1:0] inj = 0, comp = 0;
  int mode;
  always #5 clk = ~clk;
  noc_assertions #(.NUM_NODES(2)) dut(clk, rst_n, inj, comp);
  task automatic tick(input logic [1:0] i, c);
    @(negedge clk); inj = i; comp = c;
    @(posedge clk); #1;
  endtask
  initial begin
    if (!$value$plusargs("CASE=%d", mode)) $fatal(1, "CASE required");
    #12; rst_n = 1;
    if (mode == 2) begin
      tick(0, 1); // Overcompletion must fail at this sampled edge.
      $fatal(1, "overcompletion was missed");
    end
    tick(2'b11, 0);
    if (dut.total_injected != 2 || dut.total_completed != 0)
      $fatal(1, "simultaneous injection undercounted");
    if (mode == 0) begin
      tick(0, 1); // Legal delayed flight.
      tick(1, 1); // Simultaneous injection and completion.
      tick(0, 1);
      if (dut.total_injected != 3 || dut.total_completed != 3)
        $fatal(1, "incorrect count");
      tick(2'b11, 2'b11); // Multiple simultaneous completions, too.
      if (dut.total_injected != 5 || dut.total_completed != 5)
        $fatal(1, "simultaneous completion undercounted");
    end
    tick(0, 0);
    tick(0, 0);
    // Authored end of this bounded scenario, not inferred from idle pulses.
    // Mode 1 deliberately loses the two accepted flits. Prefix safety alone
    // must permit the delay; only this final boundary detects the mismatch.
    $display("REACHED_AUTHORED_DRAIN");
    dut.check_drained();
    $display("F3_OK");
    $finish;
  end
endmodule
''')
    build = subprocess.run([
        verilator, "--binary", "--assert", "--timing", "-j", "1",
        "-Wno-fatal", "--top-module", "checker_tb", "--Mdir", str(work / "obj"),
        str(assertions), str(harness),
    ], cwd=work, capture_output=True, text=True, timeout=90)
    (work / "build.log").write_text(build.stdout + build.stderr)
    assert build.returncode == 0, build.stdout + build.stderr
    return work / "obj/Vchecker_tb"


@pytest.mark.parametrize("mode,error", [(0, None), (1, "Authored drain count mismatch"), (2, "Overcompletion")])
def test_emitted_f3_runtime(checker_binary, mode, error):
    run = subprocess.run([str(checker_binary), f"+CASE={mode}"],
                         cwd=checker_binary.parent, capture_output=True,
                         text=True, timeout=5)
    output = run.stdout + run.stderr
    (checker_binary.parent / f"case-{mode}.log").write_text(output)
    if error is None:
        assert run.returncode == 0, output
        assert "F3_OK" in output
    else:
        assert run.returncode != 0, output
        assert error in output
        assert "F3_OK" not in output
        assert ("REACHED_AUTHORED_DRAIN" in output) == (mode == 1)
