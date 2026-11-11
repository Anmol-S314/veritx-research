`timescale 1ns/1ps
`default_nettype none

module tb_srota_router_stall;
  import srota_route_pkg::*;

  localparam int K = 4;
  localparam int C = 2;
  localparam int P = srota_p(C);
  localparam int W = 64;
  localparam int CW = $clog2(K);
  localparam int CREDIT_W = $clog2(2 + 1);
  localparam int ROW_OUT = srota_row_out_port(C);

  logic clk = 1'b0;
  logic rst_n = 1'b0;
  logic [CW-1:0] my_x = '0, my_y = '0;
  logic [CREDIT_W-1:0] max_credit = CREDIT_W'(2);
  logic [P-1:0] credit_ret = '0;
  logic [P-1:0] in_valid = '0, in_ready;
  logic [P-1:0][W-1:0] in_flit = '0;
  logic [P-1:0] out_valid, out_ready = '0;
  logic [P-1:0][W-1:0] out_flit;

  always #5 clk = ~clk;

  srota_router_d #(.K(K), .C(C), .P(P), .W(W)) dut (
    .clk, .rst_n, .cfg_my_x(my_x), .cfg_my_y(my_y),
    .cfg_max_credit(max_credit), .credit_ret, .in_valid, .in_ready,
    .in_flit, .out_valid, .out_ready, .out_flit
  );

  function automatic logic [W-1:0] make_flit(input logic [7:0] payload);
    logic [W-1:0] f;
    f = '0;
    f[SROTA_HDR_DEST_X_LSB +: CW] = 2;
    f[SROTA_HDR_DEST_Y_LSB +: CW] = 0;
    f[SROTA_HDR_DEST_TILE_LSB +: $clog2(C)] = 0;
    f[SROTA_HDR_PATH_SHAPE_LSB +: 2] = SROTA_ROW_FIRST;
    f[W-1 -: 8] = payload;
    return f;
  endfunction

  initial begin
    repeat (2) @(negedge clk);
    rst_n = 1'b1;

    // Capture input 0, then stall the row output. The candidate must be valid
    // and stable while blocked.
    @(negedge clk);
    in_valid[0] = 1'b1;
    in_flit[0] = make_flit(8'hA0);
    if (!in_ready[0]) $fatal(1, "input 0 was unexpectedly not ready");
    @(posedge clk);
    #1;
    in_valid[0] = 1'b0;
    @(negedge clk);

    if (!out_valid[ROW_OUT] || out_flit[ROW_OUT] !== make_flit(8'hA0))
      $fatal(1, "first candidate was not presented while stalled");

    // A second same-output request arrives during the stall. RR state and the
    // locked winner must keep both valid and data stable.
    in_valid[1] = 1'b1;
    in_flit[1] = make_flit(8'hB1);
    if (!in_ready[1]) $fatal(1, "input 1 was unexpectedly not ready");
    @(posedge clk);
    #1;
    in_valid[1] = 1'b0;
    @(negedge clk);

    repeat (2) begin
      @(negedge clk);
      if (!out_valid[ROW_OUT] || out_flit[ROW_OUT] !== make_flit(8'hA0))
        $fatal(1, "stalled valid/data changed after a new request arrived");
    end

    // Accept the locked winner. The second request remains and is next.
    out_ready[ROW_OUT] = 1'b1;
    @(negedge clk);
    if (!out_valid[ROW_OUT] || out_flit[ROW_OUT] !== make_flit(8'hB1))
      $fatal(1, "second request did not follow the accepted first grant");

    $display("PASS: router holds ready/valid candidate through stall");
    $finish;
  end
endmodule

`default_nettype wire
