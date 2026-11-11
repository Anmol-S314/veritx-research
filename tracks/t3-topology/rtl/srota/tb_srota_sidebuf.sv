`timescale 1ns/1ps
`default_nettype none

module tb_srota_sidebuf;
  localparam int P = 4;
  localparam int DEPTH = 4;
  localparam int W = 16;
  localparam int OW = $clog2(DEPTH + 1);

  logic clk = 1'b0;
  logic rst_n = 1'b0;
  logic [P-1:0] alloc_loss = '0;
  logic [W-1:0] sb_wr_flit = '0;
  logic [$clog2(P)-1:0] sb_wr_port = '0;
  logic sb_wr_ready;
  logic sb_wr_accept;
  logic sb_full;
  logic [W-1:0] sb_rd_flit;
  logic [$clog2(P)-1:0] sb_rd_port;
  logic sb_rd_vld;
  logic sb_rd_gnt = 1'b0;
  logic [$clog2(DEPTH+1)-1:0] sb_occ;
  logic [P-1:0] sidebuf_pending;
  logic [1:0] sb_state;

  srota_sidebuf #(.P(P), .SB_DEPTH(DEPTH), .W(W)) dut (.*);

  always #5 clk = ~clk;

  task automatic write_and_check(
    input logic [P-1:0] request,
    input logic [W-1:0] flit,
    input logic [$clog2(P)-1:0] port,
    input logic expected_ready,
    input logic expected_accept
  );
    @(negedge clk);
    alloc_loss = request;
    sb_wr_flit = flit;
    sb_wr_port = port;
    #1;
    if (sb_wr_ready !== expected_ready || sb_wr_accept !== expected_accept)
      $fatal(1, "write handshake mismatch: ready=%b accept=%b expected=%b/%b",
             sb_wr_ready, sb_wr_accept, expected_ready, expected_accept);
    @(posedge clk);
    #1;
    alloc_loss = '0;
  endtask

  initial begin
    repeat (2) @(posedge clk);
    @(negedge clk);
    rst_n = 1'b1;

    // A multi-hot candidate is rejected without consuming the empty slot.
    write_and_check(4'b0011, 16'hdead, 2'd3, 1'b1, 1'b0);
    if (sb_occ != 0 || sb_full) $fatal(1, "multi-hot request changed occupancy");

    // The single request bit must match the stored port tag.
    write_and_check(4'b0001, 16'hbad1, 2'd1, 1'b1, 1'b0);
    if (sb_occ != 0 || sb_full) $fatal(1, "mismatched port tag was accepted");

    write_and_check(4'b0001, 16'h1001, 2'd0, 1'b1, 1'b1);
    write_and_check(4'b0010, 16'h1002, 2'd1, 1'b1, 1'b1);
    write_and_check(4'b0100, 16'h1003, 2'd2, 1'b1, 1'b1);
    write_and_check(4'b1000, 16'h1004, 2'd3, 1'b1, 1'b1);
    if (!sb_full || sb_occ != OW'(DEPTH)) $fatal(1, "buffer did not become full");

    // Full without a drain backpressures the candidate.
    write_and_check(4'b0001, 16'hbad0, 2'd0, 1'b0, 1'b0);
    if (sb_occ != OW'(DEPTH)) $fatal(1, "full-buffer rejection changed occupancy");

    // Full plus drain accepts the new flit; occupancy remains full.
    @(negedge clk);
    sb_rd_gnt = 1'b1;
    alloc_loss = 4'b0001;
    sb_wr_flit = 16'h2000;
    sb_wr_port = 2'd0;
    #1;
    if (!sb_wr_ready || !sb_wr_accept || !sb_rd_vld || sb_rd_flit != 16'h1001)
      $fatal(1, "full drain+fill handshake or pre-edge head was incorrect");
    @(posedge clk);
    #1;
    if (sb_occ != OW'(DEPTH) || !sb_full || sb_rd_flit != 16'h1002)
      $fatal(1, "simultaneous drain+fill did not preserve full occupancy/order");

    // Drain remaining old entries, then the replacement written into the freed slot.
    alloc_loss = '0;
    for (int i = 0; i < DEPTH; i++) begin
      logic [W-1:0] expected_flit;
      expected_flit = (i == DEPTH-1) ? 16'h2000 : 16'h1002 + W'(i);
      if (!sb_rd_vld || sb_rd_flit != expected_flit)
        $fatal(1, "FIFO order mismatch at drain %0d: got %h expected %h",
               i, sb_rd_flit, expected_flit);
      @(posedge clk);
      #1;
      if (sb_occ != OW'(DEPTH-1-i))
        $fatal(1, "drain occupancy mismatch at %0d: got %0d", i, sb_occ);
      @(negedge clk);
    end
    sb_rd_gnt = 1'b0;
    if (sb_occ != 0 || sb_rd_vld) $fatal(1, "buffer did not empty");

    $display("PASS: side-buffer request validation and full drain+fill");
    $finish;
  end
endmodule

`default_nettype wire
