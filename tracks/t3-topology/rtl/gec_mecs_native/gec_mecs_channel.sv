// gec_mecs_channel.sv -- GEC shared multidrop-channel primitive.
// One transmitter drives one channel observed by passive indexed taps.
`default_nettype none
module gec_mecs_channel #(
  parameter integer K = 4,
  parameter integer W = 64,
  parameter integer IDX_W = (K <= 1) ? 1 : $clog2(K)
) (
  input logic clk,
  input logic rst_n,
  input logic tx_valid,
  input logic [W-1:0] tx_payload,
  input logic [IDX_W-1:0] tx_dst_idx,
  input logic [K-1:0] tx_mcast_bitmap,
  input logic [K-1:0] tap_credit,
  output logic tx_credit_ok,
  output logic [K-1:0] tap_valid,
  output logic [K-1:0][W-1:0] tap_payload
);
  logic [K-1:0] selected;
  logic [K-1:0] fire;

  // The GEC tap selector is explicit: zero bitmap means decoded unicast;
  // nonzero bitmap means exactly its set bits. Do not OR dst_idx into it.
  always_comb begin
    selected = '0;
    if (tx_mcast_bitmap != '0)
      selected = tx_mcast_bitmap;
    else if (int'(tx_dst_idx) < K)
      selected[tx_dst_idx] = 1'b1;
  end

  // Atomic shared-channel admission. Credits at unselected taps are ignored.
  assign tx_credit_ok = &(tap_credit | ~selected);
  assign fire = {K{tx_valid & tx_credit_ok}} & selected;

  always_ff @(posedge clk) begin
    if (!rst_n) begin
      tap_valid <= '0;
    end else begin
      tap_valid <= fire;
      for (integer j = 0; j < K; j = j + 1)
        if (fire[j]) tap_payload[j] <= tx_payload;
    end
  end
endmodule
`default_nettype wire
