#!/usr/bin/env python3
"""Exhaustively simulate native 64-node ring routing outputs in Verilator."""
from pathlib import Path
import subprocess
import tempfile

HERE = Path(__file__).resolve().parent

BENCH = r'''module tb;
  logic [5:0] router_id, destination, source;
  logic tie_choice;
  wire eject;
  wire [1:0] legal_ports;
  wire out_port, vc_half;
  int forward_distance, expected_eject, expected_legal, expected_half;
  int cases;

  ring_native_route dut(.*);

  initial begin
    cases=0;
    for (int r=0;r<64;r++) begin
      for (int d=0;d<64;d++) begin
        for (int tie=0;tie<2;tie++) begin
          router_id=r;
          destination=d;
          source=(r*17+d*7)%64;
          tie_choice=tie;
          forward_distance=(d-r+64)%64;
          if (r==d) begin expected_eject=1; expected_legal=0; end
          else if (forward_distance==32) begin expected_eject=0; expected_legal=3; end
          else if (forward_distance<32) begin expected_eject=0; expected_legal=1; end
          else begin expected_eject=0; expected_legal=2; end
          expected_half=(source>d);
          #1;
          if (eject !== expected_eject[0] || legal_ports !== expected_legal[1:0] ||
              vc_half !== expected_half[0] || (!eject && !legal_ports[out_port]))
            $fatal(1,"route mismatch router=%0d destination=%0d tie=%0d",r,d,tie);
          cases++;
        end
      end
    end
    $display("PASS route cases=%0d router-destination pairs=4096 antipode choices covered",cases);
    $finish;
  end
endmodule
'''


def main() -> None:
    with tempfile.TemporaryDirectory(prefix="ring-route-") as temp:
        temp_path = Path(temp)
        bench = temp_path / "tb.sv"
        bench.write_text(BENCH)
        subprocess.run([
            "verilator", "--binary", "--timing", "--top-module", "tb", "-Wno-fatal",
            str(HERE / "ring_native_route.sv"), str(bench), "--Mdir", str(temp_path / "obj"),
        ], check=True)
        subprocess.run([str(temp_path / "obj" / "Vtb")], check=True)


if __name__ == "__main__":
    main()
