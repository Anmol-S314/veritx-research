`timescale 1ns/1ps
`default_nettype none

module tb_srota_router_valiant;
  import srota_route_pkg::*;

  localparam int K = 4;
  localparam int C = 2;
  localparam int P = srota_p(C);
  localparam int W = 64;
  localparam int CW = $clog2(K);
  localparam int TW = $clog2(C);
  localparam int CREDIT_W = $clog2(2 + 1);
  localparam int ROW_OUT = srota_row_out_port(C);

  logic clk = 1'b0;
  logic rst_n;
  logic [CW-1:0] my_x, my_y;
  logic [CREDIT_W-1:0] max_credit;
  logic [P-1:0] credit_ret, in_valid, in_ready, out_valid, out_ready;
  logic [P-1:0][W-1:0] in_flit, out_flit;

  always #5 clk = ~clk;

  srota_router_d #(.K(K), .C(C), .P(P), .W(W)) dut (
    .clk, .rst_n, .cfg_my_x(my_x), .cfg_my_y(my_y),
    .cfg_max_credit(max_credit), .credit_ret, .in_valid, .in_ready,
    .in_flit, .out_valid, .out_ready, .out_flit
  );

  task automatic reset_router;
    rst_n = 1'b0;
    in_valid = '0;
    in_flit = '0;
    credit_ret = '0;
    out_ready = '1;
    max_credit = 2;
    repeat (2) @(negedge clk);
    rst_n = 1'b1;
    @(negedge clk);
  endtask

  task automatic send_valiant(input logic [CW-1:0] router_x,
                              input logic [CW-1:0] router_y,
                              input logic [1:0] expected_shape);
    logic [W-1:0] flit;
    my_x = router_x;
    my_y = router_y;
    flit = '0;
    flit[SROTA_HDR_DEST_X_LSB +: CW] = 3;
    flit[SROTA_HDR_DEST_Y_LSB +: CW] = 1;
    flit[SROTA_HDR_DEST_TILE_LSB +: TW] = 1;
    flit[SROTA_HDR_PATH_SHAPE_LSB +: 2] = SROTA_VALIANT_L1;
    flit[SROTA_HDR_VALIANT_X_LSB +: CW] = 1;
    flit[SROTA_HDR_VALIANT_Y_LSB +: CW] = 1;

    in_flit[0] = flit;
    in_valid[0] = 1'b1;
    do @(negedge clk); while (!in_ready[0]);
    in_valid[0] = 1'b0;

    if (!out_valid[ROW_OUT] || out_flit[ROW_OUT][SROTA_HDR_PATH_SHAPE_LSB +: 2] !== expected_shape)
      $fatal(1, "unexpected Valiant output: valid=%b shape=%b expected=%b",
             out_valid[ROW_OUT], out_flit[ROW_OUT][SROTA_HDR_PATH_SHAPE_LSB +: 2], expected_shape);
    if (out_flit[ROW_OUT][SROTA_HDR_VALIANT_X_LSB +: CW] !== 1 ||
        out_flit[ROW_OUT][SROTA_HDR_VALIANT_Y_LSB +: CW] !== 1)
      $fatal(1, "cached intermediate fields were not preserved");
  endtask

  initial begin
    reset_router();
    // At the cached intermediate, shape changes and the staged flit routes
    // toward the final destination (row output), not local destination ejection.
    send_valiant(1, 1, SROTA_ROW_FIRST);

    reset_router();
    // Away from the cached intermediate, the shape remains Valiant leg 1.
    send_valiant(0, 0, SROTA_VALIANT_L1);

    $display("PASS: router Valiant transition and non-match preservation");
    $finish;
  end
endmodule

`default_nettype wire
