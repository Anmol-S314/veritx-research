// srota_credit_mgr.sv — Plane D credit counters and side-buffer wrapper.
//
// Extracted from SSM-UARCH-VC-002 rev 0.3 §6.2, §7.4, §8.1, §10.3, §11.1,
// §11.2. Structural wrapper: P saturating per-drop credit counters plus one
// shared srota_sidebuf instance.
//
// Assumptions:
//  * cfg_max_credit is static after configuration and equals the staging
//    depth (VC-002 §8.2). Reset loads it into every counter, never zero
//    (VC-002 §10.3).
//  * gnt_oh is one-hot; the two allocator stages are disjoint by construction
//    (VC-C2, VC-002 §4.1.2). This block consumes the OR-combined vector.
//  * credit_avail is the combinational zero-compare on the ST1 path; the
//    counter update is flopped and has a full cycle (VC-002 §9.1).
`default_nettype none

module srota_credit_mgr #(
  parameter int P             = 12,
  parameter int STAGING_DEPTH = 2,
  parameter int SB_DEPTH      = 8,
  parameter int W             = 64,
  localparam int W_CREDIT = $clog2(STAGING_DEPTH + 1),
  localparam int PW       = (P > 1) ? $clog2(P) : 1,
  localparam int OW       = $clog2(SB_DEPTH + 1)
) (
  input  logic                       clk,
  input  logic                       rst_n,
  input  logic [P-1:0]               credit_ret,
  input  logic [P-1:0]               gnt_oh,
  input  logic [W_CREDIT-1:0]        cfg_max_credit,
  output logic [P-1:0]               credit_avail,
  output logic [P-1:0][W_CREDIT-1:0] credit_cnt_dbg,
  input  logic [P-1:0]               alloc_loss,
  input  logic [W-1:0]               sb_wr_flit,
  input  logic [PW-1:0]              sb_wr_port,
  output logic                       sb_wr_ready,
  output logic                       sb_wr_accept,
  output logic                       sb_full,
  output logic [W-1:0]               sb_rd_flit,
  output logic [PW-1:0]              sb_rd_port,
  output logic                       sb_rd_vld,
  input  logic                       sb_rd_gnt,
  output logic [OW-1:0]              sb_occ,
  output logic [P-1:0]               sidebuf_pending,
  output logic [1:0]                 sb_state
);

  logic [P-1:0][W_CREDIT-1:0] credit_cnt;

  // One saturating expression per port. 2'b11 (grant and return together) is
  // a no-op because the two cancel exactly; decrement-then-increment would
  // transiently underflow at zero (§6.2, §11.1).
  always_ff @(posedge clk) begin
    if (!rst_n) begin
      for (int p = 0; p < P; p++) begin
        credit_cnt[p] <= cfg_max_credit;   // NOT zero — §10.3
      end
    end else begin
      for (int p = 0; p < P; p++) begin
        unique case ({gnt_oh[p], credit_ret[p]})
          2'b10: credit_cnt[p] <= (credit_cnt[p] == W_CREDIT'(0))
                                  ? W_CREDIT'(0)
                                  : credit_cnt[p] - W_CREDIT'(1);
          2'b01: credit_cnt[p] <= (credit_cnt[p] == cfg_max_credit)
                                  ? cfg_max_credit
                                  : credit_cnt[p] + W_CREDIT'(1);
          default: credit_cnt[p] <= credit_cnt[p];
        endcase
      end
    end
  end

  // Combinational zero-compare only; this is the ST1 critical path (§9.1).
  always_comb begin
    for (int p = 0; p < P; p++) begin
      credit_avail[p] = (credit_cnt[p] != W_CREDIT'(0));
    end
  end

  assign credit_cnt_dbg = credit_cnt;

  srota_sidebuf #(
    .P        (P),
    .SB_DEPTH (SB_DEPTH),
    .W        (W)
  ) u_sidebuf (
    .clk             (clk),
    .rst_n           (rst_n),
    .alloc_loss      (alloc_loss),
    .sb_wr_flit      (sb_wr_flit),
    .sb_wr_port      (sb_wr_port),
    .sb_wr_ready     (sb_wr_ready),
    .sb_wr_accept    (sb_wr_accept),
    .sb_full         (sb_full),
    .sb_rd_flit      (sb_rd_flit),
    .sb_rd_port      (sb_rd_port),
    .sb_rd_vld       (sb_rd_vld),
    .sb_rd_gnt       (sb_rd_gnt),
    .sb_occ          (sb_occ),
    .sidebuf_pending (sidebuf_pending),
    .sb_state        (sb_state)
  );

`ifndef SYNTHESIS
  generate
    for (genvar p = 0; p < P; p++) begin : g_credit_assert
      // Credit can never be granted against a zero count (§15.2).
      a_no_grant_wo_credit: assert property (@(posedge clk) disable iff (!rst_n)
        gnt_oh[p] |-> (credit_cnt[p] != W_CREDIT'(0)));

      // Counter must never exceed its ceiling (§15.2).
      a_credit_ceiling: assert property (@(posedge clk) disable iff (!rst_n)
        credit_cnt[p] <= cfg_max_credit);
    end
  endgenerate
`endif

endmodule

`default_nettype wire
