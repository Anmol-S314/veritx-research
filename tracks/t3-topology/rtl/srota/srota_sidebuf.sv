// srota_sidebuf.sv — shared Plane D side buffer.
//
// Extracted from SSM-UARCH-VC-002 rev 0.3 §2.3, §6.1, §10, §11.2.
//
// Assumptions:
//  * One write port and one drain port. The standalone block folds in the
//    drain-candidate selection that VC-002 §7.1 assigns to srota_sidebuf_arb;
//    it drains in capture order (oldest first). That preserves F6 when more
//    than one flit of a port is buffered. A separate arbiter can replace this
//    policy when the full router is assembled.
//  * FULL is a decode of occupancy == SB_DEPTH. The 2-bit state uses only
//    2'b00/2'b01/2'b10; 2'b11 is reserved and never assigned (VC-002 §10.1).
//    DRAIN is an action, not a fourth state — it can coincide with a fill
//    (§10.2), so the FILLING state carries the self-transition.
//  * This one-write-port extension accepts one candidate per cycle: alloc_loss
//    must be one-hot, and sb_wr_flit/sb_wr_port identify that candidate. A
//    multi-bit request is not captured or acknowledged; upstream must retain
//    and retry every loser, serializing them as needed.
//  * sb_wr_accept acknowledges storage, not merely a request. sb_wr_ready and
//    sb_full expose backpressure; a full buffer may accept when a same-cycle
//    drain frees a slot (VC-002 §6.1 drain-before-fill). The enclosing staging
//    logic must hold an unaccepted loser (VC-002 §6.4, §10.1; selection/holding
//    is unspecified).
`default_nettype none

module srota_sidebuf #(
  parameter int P        = 12,
  parameter int SB_DEPTH = 8,
  parameter int W        = 64,
  localparam int PW = (P > 1) ? $clog2(P) : 1,
  localparam int OW = $clog2(SB_DEPTH + 1),
  localparam int IW = (SB_DEPTH > 1) ? $clog2(SB_DEPTH) : 1
) (
  input  logic                 clk,
  input  logic                 rst_n,
  input  logic [P-1:0]         alloc_loss,
  input  logic [W-1:0]         sb_wr_flit,
  input  logic [PW-1:0]        sb_wr_port,
  output logic                 sb_wr_ready,
  output logic                 sb_wr_accept,
  output logic                 sb_full,
  output logic [W-1:0]         sb_rd_flit,
  output logic [PW-1:0]        sb_rd_port,
  output logic                 sb_rd_vld,
  input  logic                 sb_rd_gnt,
  output logic [OW-1:0]        sb_occ,
  output logic [P-1:0]         sidebuf_pending,
  output logic [1:0]           sb_state
);

  // §10.1 state encoding. 2'b11 is reserved and never driven.
  localparam logic [1:0] SB_EMPTY   = 2'b00;
  localparam logic [1:0] SB_FILLING = 2'b01;
  localparam logic [1:0] SB_FULL    = 2'b10;

  logic [W-1:0]        sb_flit [SB_DEPTH];
  logic [PW-1:0]       sb_port [SB_DEPTH];
  logic [SB_DEPTH-1:0] sb_vld;
  logic [IW-1:0]       wr_ptr;
  logic [IW-1:0]       rd_ptr;
  logic [OW-1:0]       occ_q;
  logic [1:0]          state_q;

  logic                do_drain;
  logic                do_fill;
  logic                candidate_match;
  logic [OW-1:0]       occ_after_drain;
  logic                fill_accept;
  logic [OW-1:0]       occ_next;
  logic [1:0]          state_next;

  // Wrap the circular pointers at SB_DEPTH, not at 2**IW, so non-power-of-two
  // capacities are legal (VC-002 §13.6 allows 4–16 flits).
  function automatic logic [IW-1:0] sb_next_ptr(input logic [IW-1:0] ptr);
    if (ptr == IW'(SB_DEPTH - 1)) sb_next_ptr = IW'(0);
    else                          sb_next_ptr = ptr + IW'(1);
  endfunction

  assign do_drain = sb_rd_vld & sb_rd_gnt;

  // The one-hot request must identify the same input as the stored tag.
  always_comb begin
    candidate_match = 1'b0;
    for (int p = 0; p < P; p++) begin
      if (alloc_loss[p] && (sb_wr_port == PW'(p)))
        candidate_match = 1'b1;
    end
  end

  assign do_fill = $onehot(alloc_loss) && candidate_match;

  // Apply the drain before the fill, allowing a full buffer to reuse the
  // drained slot in the same cycle.
  assign occ_after_drain = occ_q - (do_drain ? OW'(1) : OW'(0));
  assign sb_full         = (occ_q == OW'(SB_DEPTH));
  assign sb_wr_ready     = !sb_full || do_drain;
  assign sb_wr_accept    = do_fill & sb_wr_ready;
  assign fill_accept     = sb_wr_accept;
  assign occ_next        = occ_after_drain + (fill_accept ? OW'(1) : OW'(0));

  // The oldest buffered entry is offered for re-injection (§2.3).
  assign sb_rd_vld  = (occ_q != OW'(0));
  assign sb_rd_flit = sb_flit[rd_ptr];
  assign sb_rd_port = sb_port[rd_ptr];
  assign sb_occ     = occ_q;
  assign sb_state   = state_q;

  // State tracks the occupancy being registered, so state and sb_occ never
  // disagree by a cycle. Only the three legal encodings are assigned.
  always_comb begin
    if (occ_next == OW'(0))             state_next = SB_EMPTY;
    else if (occ_next == OW'(SB_DEPTH)) state_next = SB_FULL;
    else                                state_next = SB_FILLING;
  end

  always_ff @(posedge clk) begin
    if (!rst_n) begin
      sb_vld  <= '0;
      occ_q   <= '0;
      state_q <= SB_EMPTY;
      wr_ptr  <= '0;
      rd_ptr  <= '0;
    end else begin
      // Drain and accepted fill can proceed together, including at full.
      if (do_drain) begin
        sb_vld[rd_ptr] <= 1'b0;
        rd_ptr         <= sb_next_ptr(rd_ptr);
      end
      if (fill_accept) begin
        sb_flit[wr_ptr] <= sb_wr_flit;
        sb_port[wr_ptr] <= sb_wr_port;
        sb_vld[wr_ptr]  <= 1'b1;
        wr_ptr          <= sb_next_ptr(wr_ptr);
      end
      occ_q   <= occ_next;
      state_q <= state_next;
    end
  end

  // Bypass-inhibit term consumed by SSM-UARCH-ROUTE-001 §9.4: a newer flit
  // must not overtake an older buffered flit of the same port (F6).
  always_comb begin
    for (int p = 0; p < P; p++) begin
      sidebuf_pending[p] = 1'b0;
      for (int i = 0; i < SB_DEPTH; i++) begin
        if (sb_vld[i] && (sb_port[i] == PW'(p))) begin
          sidebuf_pending[p] = 1'b1;
        end
      end
    end
  end

`ifndef SYNTHESIS
  a_sb_no_overflow: assert property (@(posedge clk) disable iff (!rst_n)
    sb_occ <= OW'(SB_DEPTH));

  a_sb_state_legal: assert property (@(posedge clk) disable iff (!rst_n)
    sb_state != 2'b11);

  a_sb_occ_vld: assert property (@(posedge clk) disable iff (!rst_n)
    (sb_occ == OW'(0)) == (sb_vld == {SB_DEPTH{1'b0}}));

  a_sb_full_without_drain_blocks: assert property (@(posedge clk) disable iff (!rst_n)
    (sb_full && !do_drain) |-> (!sb_wr_ready && !sb_wr_accept));

  a_sb_ready_when_drain_frees_slot: assert property (@(posedge clk) disable iff (!rst_n)
    (sb_full && do_drain) |-> sb_wr_ready);

  a_sb_accept_is_single_candidate: assert property (@(posedge clk) disable iff (!rst_n)
    sb_wr_accept |-> $onehot(alloc_loss));

  a_sb_accept_tag_matches_request: assert property (@(posedge clk) disable iff (!rst_n)
    sb_wr_accept |-> candidate_match);

  a_sb_accept_requires_ready: assert property (@(posedge clk) disable iff (!rst_n)
    sb_wr_accept |-> sb_wr_ready);

  // Registered occupancy reflects exactly the prior accepted write and drain.
  a_sb_accepted_count: assert property (@(posedge clk) disable iff (!rst_n)
    sb_occ == $past(occ_q) - ($past(do_drain) ? OW'(1) : OW'(0)) +
              ($past(sb_wr_accept) ? OW'(1) : OW'(0)));
`endif

endmodule

`default_nettype wire
