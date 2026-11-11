// srota_arb_l1_slack.sv — Level-1 minimum-slack mask.
// ROUTE-001 rev 0.3 §11.2. Combinational; narrows m0, never widens it.
`default_nettype none

module srota_arb_l1_slack #(
  parameter int N = 6,
  parameter int SLACK_W = 2
) (
  input  logic [N-1:0]               m0,
  input  logic [N-1:0][SLACK_W-1:0]  req_slack,
  output logic [N-1:0]               m1
);
  logic [SLACK_W-1:0] best_slack;

  always_comb begin
    best_slack = {SLACK_W{1'b1}};
    for (int i = 0; i < N; i++) begin
      if (m0[i] && (req_slack[i] < best_slack))
        best_slack = req_slack[i];
    end

    for (int i = 0; i < N; i++)
      m1[i] = m0[i] && (req_slack[i] == best_slack);
  end

endmodule

`default_nettype wire
