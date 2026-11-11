// srota_arb_l0_golden.sv — Level-0 golden-rotation mask.
// ROUTE-001 rev 0.3 §11.2. Combinational; no state (§12.1).
`default_nettype none

module srota_arb_l0_golden #(
  parameter int N = 6
) (
  input  logic [N-1:0] elig,
  input  logic [N-1:0] golden_match,
  output logic [N-1:0] m0
);
  logic [N-1:0] golden_elig;

  assign golden_elig = elig & golden_match;

  // Fallback is a correctness requirement: golden must never block progress
  // when no golden-window request exists (§11.2, F3).
  assign m0 = (|golden_elig) ? golden_elig : elig;

endmodule

`default_nettype wire
