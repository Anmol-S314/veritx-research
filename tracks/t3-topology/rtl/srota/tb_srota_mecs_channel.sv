`timescale 1ns/1ps

module tb_srota_mecs_channel;
  localparam int K = 4;
  localparam int W = 16;
  localparam int IDX_W = $clog2(K);

  logic clk = 1'b0;
  logic rst_n;
  logic drv_vld;
  logic [W-1:0] drv_flit;
  logic [IDX_W-1:0] drv_dst_idx;
  logic [K-1:0] drv_mcast_bmp;
  logic [K-1:0][W-1:0] row_flit, col_flit;
  logic [K-1:0] row_vld, col_vld;
  logic [K-1:0] drop_credit;
  logic row_credit_ok, col_credit_ok;
  int checks = 0;

  always #5 clk = ~clk;

  srota_mecs_row #(.K(K), .W(W)) row_dut (
    .clk, .rst_n, .drv_vld, .drv_flit, .drv_dst_idx, .drv_mcast_bmp,
    .drop_flit(row_flit), .drop_vld(row_vld), .drop_credit,
    .drv_credit_ok(row_credit_ok)
  );

  srota_mecs_col #(.K(K), .W(W)) col_dut (
    .clk, .rst_n, .drv_vld, .drv_flit, .drv_dst_idx, .drv_mcast_bmp,
    .drop_flit(col_flit), .drop_vld(col_vld), .drop_credit,
    .drv_credit_ok(col_credit_ok)
  );

  task automatic step(
    input string label,
    input logic expected_credit_ok,
    input logic [K-1:0] expected_vld,
    input int check_idx,
    input logic [W-1:0] expected_flit
  );
    #1;
    checks++;
    if (row_credit_ok !== expected_credit_ok ||
        col_credit_ok !== expected_credit_ok) begin
      $error("%s: row/col credit=%b/%b expected=%b", label,
             row_credit_ok, col_credit_ok, expected_credit_ok);
      $fatal(1);
    end
    @(posedge clk);
    #1;
    checks++;
    if (row_vld !== expected_vld || col_vld !== expected_vld) begin
      $error("%s: row/col drop_vld=%b/%b expected=%b", label,
             row_vld, col_vld, expected_vld);
      $fatal(1);
    end
    if (check_idx >= 0 &&
        (row_flit[check_idx] !== expected_flit ||
         col_flit[check_idx] !== expected_flit)) begin
      $error("%s: row/col flit[%0d]=%h/%h expected=%h", label,
             check_idx, row_flit[check_idx], col_flit[check_idx],
             expected_flit);
      $fatal(1);
    end
    $display("PASS MECS channel: %s", label);
    @(negedge clk);
  endtask

  initial begin
    rst_n = 1'b0;
    drv_vld = 1'b0;
    drv_flit = '0;
    drv_dst_idx = '0;
    drv_mcast_bmp = '0;
    drop_credit = '0;
    @(posedge clk);
    #1;
    checks++;
    if (row_vld !== '0 || col_vld !== '0) begin
      $error("reset did not clear row/column drop valid");
      $fatal(1);
    end
    @(negedge clk);
    rst_n = 1'b1;

    // Unicast target 2 has credit. Other drops have no credit, but are not
    // selected and therefore must not block the single-driver channel.
    drv_vld = 1'b1;
    drv_flit = 16'h1234;
    drv_dst_idx = 2'd2;
    drv_mcast_bmp = '0;
    drop_credit = 4'b0100;
    step("unicast ignores unselected drop credits", 1'b1,
         4'b0100, 2, 16'h1234);

    // A missing credit at the selected unicast tap stalls the whole channel.
    drv_flit = 16'hbeef;
    drop_credit = '0;
    step("unicast selected tap blocks issue", 1'b0, '0, -1, '0);

    // Use a valid multicast encoding with dst_idx in the bitmap. The bitmap
    // selects drops 1 and 3, and both credits are required before issue.
    drv_dst_idx = 2'd1;
    drv_mcast_bmp = 4'b1010;
    drv_flit = 16'h5678;
    drop_credit = 4'b0010;
    step("multicast waits for every selected drop", 1'b0, '0, -1, '0);

    drop_credit = 4'b1010;
    step("multicast reaches selected bitmap taps", 1'b1,
         4'b1010, 1, 16'h5678);

    drv_vld = 1'b0;
    drv_mcast_bmp = '0;
    drop_credit = '1;
    step("invalid driver suppresses all drops", 1'b1, '0, -1, '0);

    $display("PASS: %0d MECS row/column channel checks", checks);
    $finish;
  end
endmodule
