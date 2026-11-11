// srota_arb.sv — parameterized three-level allocator.
// ROUTE-001 rev 0.3 §8.3 (ports), §11.2 (masks), §7.3/§7.6 (coupling).
// Instanced twice: mesh and express, same RTL (§7.2).
`default_nettype none

module srota_arb #(
  parameter int N = 6,
  parameter int SLACK_W = 2,
  parameter int BATCH_W = 4,
  parameter int GOLDEN_W = 4
) (
  input  logic                        clk,
  input  logic                        rst_n,
  input  logic [N-1:0]                req_vec,
  input  logic [N-1:0][SLACK_W-1:0]   req_slack,
  input  logic [N-1:0][BATCH_W-1:0]   req_batch,
  input  logic [N-1:0][GOLDEN_W-1:0]  req_golden_id,
  input  logic [N-1:0]                credit_avail,
  input  logic [N-1:0]                out_busy_mask,
  input  logic                        prec_first,
  input  logic [GOLDEN_W-1:0]         cfg_golden_id,
  input  logic                        gnt_ready,
  output logic [N-1:0]                out_busy_out,
  output logic [N-1:0]                gnt_oh,
  output logic                        gnt_vld,
  output logic [((N > 1) ? $clog2(N) : 1)-1:0] rr_ptr
);
  localparam int PTR_W = (N > 1) ? $clog2(N) : 1;

  logic [N-1:0] elig;
  logic [N-1:0] golden_match;
  logic [N-1:0] m0, m1, m2;

  logic [PTR_W-1:0] gnt_idx;
  logic             found;
  logic             lock_valid;
  logic [N-1:0]     lock_oh;

  // Rev 0.3 coupling: remove outputs already claimed by the other stage
  // before arbitration (§7.3, RT-R9).
  assign elig = req_vec & credit_avail & ~out_busy_mask;

  generate
    for (genvar i = 0; i < N; i++) begin : g_golden
      assign golden_match[i] = (req_golden_id[i] == cfg_golden_id);
    end
  endgenerate

  srota_arb_l0_golden #(.N(N)) u_l0 (
    .elig         (elig),
    .golden_match (golden_match),
    .m0           (m0)
  );

  srota_arb_l1_slack #(.N(N), .SLACK_W(SLACK_W)) u_l1 (
    .m0        (m0),
    .req_slack (req_slack),
    .m1        (m1)
  );

  srota_arb_l2_stc #(.N(N), .BATCH_W(BATCH_W)) u_l2 (
    .m1        (m1),
    .req_batch (req_batch),
    .m2        (m2)
  );

  // Round-robin tiebreak over Level-2 survivors. A stalled candidate is held
  // until accepted so changing requests cannot change the crossbar selection.
  always_comb begin
    gnt_oh  = '0;
    gnt_idx = '0;
    found   = 1'b0;

    for (int k = 0; k < N; k++) begin
      int idx;
      idx = int'(rr_ptr) + k;
      if (idx >= N)
        idx = idx - N;

      if (!found && m2[idx]) begin
        gnt_oh[idx] = 1'b1;
        gnt_idx     = idx[PTR_W-1:0];
        found       = 1'b1;
      end
    end

    if (lock_valid) begin
      gnt_oh = lock_oh;
      for (int i = 0; i < N; i++) begin
        if (lock_oh[i])
          gnt_idx = PTR_W'(i);
      end
    end
  end

  assign gnt_vld      = |gnt_oh;
  assign out_busy_out = (prec_first && gnt_vld && gnt_ready) ? gnt_oh : '0;

  // rr_ptr advances only for an accepted grant; remember a stalled candidate.
  always_ff @(posedge clk) begin
    if (!rst_n) begin
      rr_ptr <= '0;
      lock_valid <= 1'b0;
      lock_oh <= '0;
    end else begin
      if (gnt_vld && gnt_ready) begin
        rr_ptr <= (gnt_idx == PTR_W'(N-1)) ? '0 : (gnt_idx + 1'b1);
        lock_valid <= 1'b0;
      end else if (gnt_vld && !gnt_ready && !lock_valid) begin
        lock_valid <= 1'b1;
        lock_oh <= gnt_oh;
      end
    end
  end

endmodule

`default_nettype wire
