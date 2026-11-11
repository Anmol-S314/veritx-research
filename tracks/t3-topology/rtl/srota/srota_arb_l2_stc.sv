// srota_arb_l2_stc.sv — Level-2 minimum-batch mask.
// ROUTE-001 rev 0.3 §11.2. Combinational; narrows m1, never widens it.
`default_nettype none

module srota_arb_l2_stc #(
  parameter int N = 6,
  parameter int BATCH_W = 4
) (
  input  logic [N-1:0]               m1,
  input  logic [N-1:0][BATCH_W-1:0]  req_batch,
  output logic [N-1:0]               m2
);
  logic [BATCH_W-1:0] best_batch;

  always_comb begin
    best_batch = {BATCH_W{1'b1}};
    for (int i = 0; i < N; i++) begin
      if (m1[i] && (req_batch[i] < best_batch))
        best_batch = req_batch[i];
    end

    for (int i = 0; i < N; i++)
      m2[i] = m1[i] && (req_batch[i] == best_batch);
  end

endmodule

`default_nettype wire
