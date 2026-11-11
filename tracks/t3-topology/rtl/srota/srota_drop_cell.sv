// srota_drop_cell.sv — MECS passive drop tap (TOPO-003 rev 0.3 §9, §11.2).
//
// One compare plus one bitmap bit-select on the channel; the flit register is
// an enabled flop so non-matching drops hold (and do not clock) W bits of
// state. credit_avail is passed through to drop_credit_ok — README item 3.
`default_nettype none

module srota_drop_cell #(
  parameter int K = 4,
  parameter int W = 64
) (
  input  logic                 clk,
  input  logic                 rst_n,
  input  logic                 ch_vld,
  input  logic [W-1:0]         ch_flit,
  input  logic [$clog2(K)-1:0] ch_dst_idx,
  input  logic [K-1:0]         ch_mcast_bmp,
  input  logic [$clog2(K)-1:0] cfg_my_idx,
  input  logic                 credit_avail,
  output logic                 drop_vld,
  output logic [W-1:0]         drop_flit,
  output logic                 drop_credit_ok
);

  // §9.1: unicast equality OR multicast bit, gated by channel valid.
  // Equality stays live during multicast: do not park dst_idx on an
  // unselected drop index when the bitmap is non-zero.
  logic match;
  assign match = ch_vld & ((ch_dst_idx == cfg_my_idx) |
                           ch_mcast_bmp[cfg_my_idx]);

  // §12.3: only drop_vld is reset; drop_flit is deliberately not reset.
  always_ff @(posedge clk) begin
    if (!rst_n) drop_vld <= 1'b0;
    else        drop_vld <= match;
  end

  // §11.2 / §12.2: enabled flop; no toggle on a non-matching drop.
  always_ff @(posedge clk) begin
    if (match) drop_flit <= ch_flit;
  end

  // §8.2: staging-room indication returned to the row reduction.
  assign drop_credit_ok = credit_avail;

endmodule
`default_nettype wire
