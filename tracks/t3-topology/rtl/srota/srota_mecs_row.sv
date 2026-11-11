// srota_mecs_row.sv — MECS row express channel (TOPO-003 rev 0.3 §7.4, §8.1, §11.1).
//
// One driver, K passive taps. A transaction is issued only when every selected
// drop has credit (§9.2); the taps never gate the channel themselves.
`default_nettype none

module srota_mecs_row #(
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

  // §11.1: multicast bitmap if non-zero, otherwise the decoded unicast target.
  logic [K-1:0] sel;
  assign sel = (|drv_mcast_bmp) ? drv_mcast_bmp
                                : (K'(1) << drv_dst_idx);

  // §9.2: all-or-nothing issue; unselected drops are masked out of the AND.
  assign drv_credit_ok = &(drop_credit | ~sel);

  /* verilator lint_off PINCONNECTEMPTY */
  genvar i;
  generate
    for (i = 0; i < K; i++) begin : g_drop
      srota_drop_cell #(.K(K), .W(W)) u_drop (
        .clk            (clk),
        .rst_n          (rst_n),
        .ch_vld         (drv_vld & drv_credit_ok),
        .ch_flit        (drv_flit),
        .ch_dst_idx     (drv_dst_idx),
        .ch_mcast_bmp   (drv_mcast_bmp),
        .cfg_my_idx     (i[$clog2(K)-1:0]),   // tied to position — §7.2
        .credit_avail   (drop_credit[i]),
        .drop_vld       (drop_vld[i]),
        .drop_flit      (drop_flit[i]),
        .drop_credit_ok ()                    // pass-through unused here
      );
    end
  endgenerate
  /* verilator lint_on PINCONNECTEMPTY */

endmodule
`default_nettype wire
