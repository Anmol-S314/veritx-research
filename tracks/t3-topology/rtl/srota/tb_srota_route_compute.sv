`timescale 1ns/1ps

module tb_srota_route_compute;
  import srota_route_pkg::*;

  localparam int K = 16;
  localparam int C = 4;
  localparam int W = srota_clog2(K);
  localparam int P = srota_p(C);

  logic [W-1:0] hdr_dest_x, hdr_dest_y;
  logic [1:0] hdr_dest_tile;
  srota_path_shape_e hdr_path_shape;
  logic [W-1:0] hdr_valiant_x, hdr_valiant_y;
  logic [W-1:0] cfg_my_x, cfg_my_y;
  logic [P-1:0] rc_port_oh;
  logic rc_is_eject, rc_turn_taken, rc_valid;

  logic clk = 1'b0;
  logic rst_n, ch_vld, credit_avail;
  logic [15:0] ch_flit;
  logic [1:0] ch_dst_idx, cfg_my_idx;
  logic [3:0] ch_mcast_bmp;
  logic drop_vld, drop_credit_ok;
  logic [15:0] drop_flit;
  int checks = 0;

  always #5 clk = ~clk;

  srota_route_compute #(.K(K), .C(C)) route_dut (
    .hdr_dest_x, .hdr_dest_y, .hdr_dest_tile, .hdr_path_shape,
    .hdr_valiant_x, .hdr_valiant_y, .cfg_my_x, .cfg_my_y,
    .rc_port_oh, .rc_is_eject, .rc_turn_taken, .rc_valid
  );

  srota_drop_cell #(.K(4), .W(16)) drop_dut (
    .clk, .rst_n, .ch_vld, .ch_flit, .ch_dst_idx, .ch_mcast_bmp,
    .cfg_my_idx, .credit_avail, .drop_vld, .drop_flit, .drop_credit_ok
  );

  task automatic route_case(
    input string label,
    input logic [W-1:0] dest_x,
    input logic [W-1:0] dest_y,
    input logic [1:0] dest_tile,
    input srota_path_shape_e shape,
    input logic [W-1:0] via_x,
    input logic [W-1:0] via_y,
    input logic [W-1:0] here_x,
    input logic [W-1:0] here_y,
    input logic [P-1:0] expected_ports,
    input logic expected_eject,
    input logic expected_turn
  );
    hdr_dest_x = dest_x;
    hdr_dest_y = dest_y;
    hdr_dest_tile = dest_tile;
    hdr_path_shape = shape;
    hdr_valiant_x = via_x;
    hdr_valiant_y = via_y;
    cfg_my_x = here_x;
    cfg_my_y = here_y;
    #1;
    checks++;
    if (rc_port_oh !== expected_ports || rc_valid !== 1'b1 ||
        rc_is_eject !== expected_eject || rc_turn_taken !== expected_turn) begin
      $error("%s: ports=%h valid=%b eject=%b turn=%b; expected %h/1/%b/%b",
             label, rc_port_oh, rc_valid, rc_is_eject, rc_turn_taken,
             expected_ports, expected_eject, expected_turn);
      $fatal(1);
    end
    $display("PASS route: %s", label);
  endtask

  task automatic drop_cycle(input string label, input logic expected_vld,
                            input logic check_flit,
                            input logic [15:0] expected_flit);
    @(posedge clk);
    #1;
    checks++;
    if (drop_vld !== expected_vld) begin
      $error("%s: drop_vld=%b expected=%b", label, drop_vld, expected_vld);
      $fatal(1);
    end
    if (check_flit && drop_flit !== expected_flit) begin
      $error("%s: drop_flit=%h expected=%h", label, drop_flit, expected_flit);
      $fatal(1);
    end
    if (drop_credit_ok !== credit_avail) begin
      $error("%s: drop_credit_ok=%b expected passthrough=%b",
             label, drop_credit_ok, credit_avail);
      $fatal(1);
    end
    $display("PASS drop: %s", label);
    @(negedge clk);
  endtask

  initial begin
    // Combinational route tests: preview package uses P=2*C+8, row out=12,
    // column out=14, and local ejection ports C+tile. Not integrated router.
    route_case("row-first takes X before Y", 5, 7, 1, SROTA_ROW_FIRST,
               9, 9, 2, 3, 16'h1000, 0, 0);
    route_case("row-first turns to Y after X aligns", 2, 7, 1,
               SROTA_ROW_FIRST, 9, 9, 2, 3, 16'h4000, 0, 1);
    route_case("column-first takes Y before X", 5, 7, 1,
               SROTA_COLUMN_FIRST, 9, 9, 2, 3, 16'h4000, 0, 0);
    route_case("column-first turns to X after Y aligns", 5, 3, 1,
               SROTA_COLUMN_FIRST, 9, 9, 2, 3, 16'h1000, 0, 1);
    route_case("Valiant L1 targets intermediate X", 10, 11, 2,
               SROTA_VALIANT_L1, 6, 8, 2, 3, 16'h1000, 0, 0);
    route_case("Valiant L1 targets intermediate Y after X", 10, 11, 2,
               SROTA_VALIANT_L1, 6, 8, 6, 3, 16'h4000, 0, 1);
    route_case("destination eject selects tile 2 port", 2, 3, 2,
               SROTA_ROW_FIRST, 9, 9, 2, 3, 16'h0040, 1, 0);
     // Raw leaf behavior only; router staging rewrites a matching L1 header
     // before routing, as covered by tb_srota_router_valiant.
     route_case("raw route leaf: L1 intermediate eject selects destination tile", 2, 3, 3,
                SROTA_VALIANT_L1, 2, 3, 2, 3, 16'h0080, 1, 0);

    // Initialize drop inputs away from a clock edge.
    rst_n = 1'b0;
    ch_vld = 1'b0;
    ch_flit = '0;
    ch_dst_idx = '0;
    ch_mcast_bmp = '0;
    cfg_my_idx = 2'd2;
    credit_avail = 1'b1;
    drop_cycle("reset clears valid", 0, 0, '0);

    rst_n = 1'b1;
    ch_vld = 1'b1;
    ch_dst_idx = 2'd2;
    ch_mcast_bmp = '0;
    ch_flit = 16'h1234;
    drop_cycle("unicast equality captures flit", 1, 1, 16'h1234);

    ch_vld = 1'b0;
    ch_flit = 16'hffff;
    drop_cycle("invalid channel clears valid and holds data", 0, 1, 16'h1234);

    ch_vld = 1'b1;
    ch_dst_idx = 2'd1;
    ch_mcast_bmp = 4'b0100;
    ch_flit = 16'hbeef;
    credit_avail = 1'b0;
    drop_cycle("multicast selected bitmap bit captures", 1, 1, 16'hbeef);

    ch_dst_idx = 2'd0;
    ch_mcast_bmp = 4'b0100;
    ch_flit = 16'h5678;
    credit_avail = 1'b1;
    drop_cycle("multicast equality hazard: equality matches despite clear bit",
               1, 1, 16'h5678);

    ch_vld = 1'b0;
    drop_cycle("invalid multicast does not match", 0, 1, 16'h5678);

    // Reset controls drop_vld only; deliberately do not assert a value for
    // drop_flit here because the leaf RTL does not reset that register.
    rst_n = 1'b0;
    ch_vld = 1'b0;
    drop_cycle("reset clears valid without requiring flit reset", 0, 1,
               16'h5678);

    $display("PASS: %0d self-checks", checks);
    $finish;
  end
endmodule
