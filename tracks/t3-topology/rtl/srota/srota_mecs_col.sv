// srota_mecs_col.sv — MECS column express channel (TOPO-003 rev 0.3 §7.1, §8.1).
//
// Structurally identical to the row channel; this wrapper keeps the two channel
// types distinct at fabric-top level without duplicating the logic.
`default_nettype none

module srota_mecs_col #(
  parameter int K = 4,
  parameter int W = 64
) (
  input  logic                 clk,
  input  logic                 rst_n,
  input  logic                 drv_vld,
  input  logic [W-1:0]         drv_flit,
  input  logic [$clog2(K)-1:0] drv_dst_idx,
  input  logic [K-1:0]         drv_mcast_bmp,
  output logic [K-1:0][W-1:0]  drop_flit,
  output logic [K-1:0]         drop_vld,
  input  logic [K-1:0]         drop_credit,
  output logic                 drv_credit_ok
);

  srota_mecs_row #(.K(K), .W(W)) u_row (
    .clk           (clk),
    .rst_n         (rst_n),
    .drv_vld       (drv_vld),
    .drv_flit      (drv_flit),
    .drv_dst_idx   (drv_dst_idx),
    .drv_mcast_bmp (drv_mcast_bmp),
    .drop_flit     (drop_flit),
    .drop_vld      (drop_vld),
    .drop_credit   (drop_credit),
    .drv_credit_ok (drv_credit_ok)
  );

endmodule
`default_nettype wire
