`timescale 1ns/1ps
// VeritX — RTL multicast fork unit test: one stream from node 0 (row 0) to
// far end 3, copies at nodes 1..2 (copy_lo=1, copy_hi=2). Expect: node 1 and
// node 2 each eject one copy; node 3 ejects the stream. 4x4 mesh.

import noc_pkg::*;

module fork_tb;
  parameter int VCS   = 1;
  parameter int X_DIM = 4;
  parameter int Y_DIM = 4;
  localparam int N    = X_DIM * Y_DIM;

  logic clk = 1'b0;
  always #5 clk = ~clk;
  logic rst_n = 1'b0;

  link_f_t inj  [Y_DIM][X_DIM];
  link_c_t injc [Y_DIM][X_DIM];
  link_c_t injce[Y_DIM][X_DIM];
  link_f_t ej   [Y_DIM][X_DIM];
  link_c_t ejc  [Y_DIM][X_DIM];
  logic [31:0] rpop  [Y_DIM][X_DIM][NUM_PORTS];
  logic [31:0] rrecv [Y_DIM][X_DIM][NUM_PORTS];
  dbg_router_t rdbg  [Y_DIM][X_DIM];

  noc_mesh #(.VCS(VCS), .X_DIM(X_DIM), .Y_DIM(Y_DIM)) u_mesh (
    .clk(clk), .rst_n(rst_n),
    .inject(inj), .inject_credit(injc), .inject_credit_early(injce),
    .eject(ej), .eject_credit(ejc),
    .router_pop(rpop), .router_recv(rrecv), .router_dbg(rdbg)
  );

  int tick = 0;
  always_ff @(posedge clk) tick <= tick + 1;

  int got1 = 0, got2 = 0, got3 = 0;
  int e1 = 0, e2 = 0, e3 = 0;

  initial begin
    for (int y = 0; y < Y_DIM; y++)
      for (int x = 0; x < X_DIM; x++) begin
        inj[y][x] <= '0;
        ejc[y][x] <= '0;
      end
    #20; rst_n = 1'b1; #20;

    // One multicast stream: node 0 -> far end 3, copies at 1..2
    inj[0][0].valid <= 1'b1;
    inj[0][0].flit.head  <= 1'b1;
    inj[0][0].flit.tail  <= 1'b1;
    inj[0][0].flit.vc    <= '0;
    inj[0][0].flit.cl    <= '0;
    inj[0][0].flit.src   <= 8'd0;
    inj[0][0].flit.dst   <= 8'd3;
    inj[0][0].flit.pid   <= 16'd100;
    inj[0][0].flit.itime <= 32'd0;
    inj[0][0].flit.mcast    <= 1'b1;
    inj[0][0].flit.copy_lo  <= 8'd1;
    inj[0][0].flit.copy_hi  <= 8'd2;
    #10;
    inj[0][0].valid <= 1'b0;

    // credit the eject ports whenever a delivery shows up
    while (tick < 100) begin
      #10;
      for (int y = 0; y < Y_DIM; y++)
        for (int x = 0; x < X_DIM; x++) begin
          if (ej[y][x].valid) begin
            int n = y * X_DIM + x;
            if (n == 1) e1++;
            if (n == 2) e2++;
            if (n == 3) e3++;
            $display("T%0d EJECT node %0d pid %0d dst %0d mcast %b",
                     tick, n, ej[y][x].flit.pid, ej[y][x].flit.dst,
                     ej[y][x].flit.mcast);
            ejc[y][x].valid <= 1'b1;
            #10;
            ejc[y][x].valid <= 1'b0;
          end
        end
    end

    got1 = e1; got2 = e2; got3 = e3;
    $display("\n=== FORK TEST: node1=%0d node2=%0d node3=%0d ===", got1, got2, got3);
    if (got1 == 1 && got2 == 1 && got3 == 1)
      $display("FORK PASS: stream forked to 3 nodes");
    else
      $display("FORK FAIL: expected 1 delivery at each of nodes 1,2,3");
    $finish;
  end
endmodule
