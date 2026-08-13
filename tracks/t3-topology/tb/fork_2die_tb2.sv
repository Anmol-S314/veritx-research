`timescale 1ns/1ps
// VeritX — 2-die bridge fork test: node 0 (die A) -> far end 71 (die B row 0),
// copies at 65..70 (die B row 0). Bridge at col 0 (on-axis).
// Expect: 6 copies at die-B nodes 65-70 + stream at 71. One injection, 7 deliveries.

import noc_pkg::*;

module fork_2die_tb;
  parameter int VCS        = 1;
  parameter int X_DIM      = 8;
  parameter int Y_DIM      = 8;
  parameter int BRIDGE_COL = 0;
  parameter int BRIDGE_ROW = 0;

  logic clk = 1'b0;
  always #5 clk = ~clk;
  logic rst_n = 1'b0;

  link_f_t inj [2][Y_DIM][X_DIM];
  link_c_t injc[2][Y_DIM][X_DIM];
  link_c_t injce[2][Y_DIM][X_DIM];
  link_f_t ej  [2][Y_DIM][X_DIM];
  link_c_t ejc [2][Y_DIM][X_DIM];

  noc_2die #(.VCS(VCS), .X_DIM(X_DIM), .Y_DIM(Y_DIM),
             .BRIDGE_COL(BRIDGE_COL), .BRIDGE_ROW(BRIDGE_ROW)) u_noc (
    .clk(clk), .rst_n(rst_n),
    .inject(inj), .inject_credit(injc), .inject_credit_early(injce),
    .eject(ej), .eject_credit(ejc)
  );

  int tick = 0;
  always_ff @(posedge clk) tick <= tick + 1;

  int deliveries[2][Y_DIM][X_DIM];

  initial begin
    for (int d = 0; d < 2; d++)
      for (int y = 0; y < Y_DIM; y++)
        for (int x = 0; x < X_DIM; x++) begin
          inj[d][y][x] <= '0;
          ejc[d][y][x] <= '0;
          deliveries[d][y][x] = 0;
        end
    #20; rst_n = 1'b1; #20;

    // KV multicast stream: node 0 -> far end 71, copies at 65..70 (die B row 0)
    inj[0][0][0].valid <= 1'b1;
    inj[0][0][0].flit.head  <= 1'b1;
    inj[0][0][0].flit.tail  <= 1'b1;
    inj[0][0][0].flit.vc    <= '0;
    inj[0][0][0].flit.cl    <= '0;
    inj[0][0][0].flit.src   <= 8'd0;
    inj[0][0][0].flit.dst   <= 8'd71;
    inj[0][0][0].flit.pid   <= 16'd500;
    inj[0][0][0].flit.itime <= 32'd0;
    inj[0][0][0].flit.mcast    <= 1'b1;
    inj[0][0][0].flit.copy_lo  <= 8'd65;
    inj[0][0][0].flit.copy_hi  <= 8'd70;
    #10;
    inj[0][0][0].valid <= 1'b0;

    while (tick < 300) begin
      #10;
      // continuously grant eject credits (always ready to receive)
      for (int d = 0; d < 2; d++)
        for (int y = 0; y < Y_DIM; y++)
          for (int x = 0; x < X_DIM; x++) begin
            ejc[d][y][x].valid <= 1'b1;
            if (ej[d][y][x].valid) begin
              deliveries[d][y][x]++;
              $display("T%0d EJECT die%d node %0d pid %0d dst %0d",
                       tick, d, d * 64 + y * X_DIM + x,
                       ej[d][y][x].flit.pid, ej[d][y][x].flit.dst);
            end
          end
    end

    $display("\n=== 2-DIE FORK TEST ===");
    $display("die-B row-0 deliveries (nodes 64..71): %0d %0d %0d %0d %0d %0d %0d %0d",
             deliveries[1][0][0], deliveries[1][0][1], deliveries[1][0][2],
             deliveries[1][0][3], deliveries[1][0][4], deliveries[1][0][5],
             deliveries[1][0][6], deliveries[1][0][7]);
    $display("die-A deliveries: %0d", deliveries[0][0][0]);
    if (deliveries[1][0][1] == 1 && deliveries[1][0][2] == 1 &&
        deliveries[1][0][3] == 1 && deliveries[1][0][4] == 1 &&
        deliveries[1][0][5] == 1 && deliveries[1][0][6] == 1 &&
        deliveries[1][0][7] == 1)
      $display("2-DIE FORK PASS: 6 copies + stream delivered on die B row 0");
    else
      $display("2-DIE FORK FAIL");
    $finish;
  end
endmodule
