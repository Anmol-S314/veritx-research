// srota_route_compute.sv — per-input-port next-hop resolver.
// ROUTE-001 rev 0.3 §11.1, port list §8.2.
// Purely combinational: no clk, no rst, no congestion input (§2, §12.1).
`default_nettype none

module srota_route_compute #(
  parameter int K = 16,
  parameter int C = 4,
  parameter int P = srota_route_pkg::srota_p(C),
  parameter int W = srota_route_pkg::srota_clog2(K)
) (
  input  logic [W-1:0] hdr_dest_x,
  input  logic [W-1:0] hdr_dest_y,
  input  logic [((C > 1) ? srota_route_pkg::srota_clog2(C) : 1)-1:0] hdr_dest_tile,
  input  srota_route_pkg::srota_path_shape_e hdr_path_shape,
  input  logic [W-1:0] hdr_valiant_x,
  input  logic [W-1:0] hdr_valiant_y,
  input  logic [W-1:0] cfg_my_x,
  input  logic [W-1:0] cfg_my_y,
  output logic [P-1:0] rc_port_oh,
  output logic         rc_is_eject,
  output logic         rc_turn_taken,
  output logic         rc_valid
);
  import srota_route_pkg::*;

  logic [W-1:0] tgt_x, tgt_y;
  logic         row_first;

  // Valiant leg 1 retargets to the cached intermediate (§5.4, §11.1).
  assign tgt_x = (hdr_path_shape == SROTA_VALIANT_L1) ? hdr_valiant_x : hdr_dest_x;
  assign tgt_y = (hdr_path_shape == SROTA_VALIANT_L1) ? hdr_valiant_y : hdr_dest_y;

  // Both row-first and Valiant leg 1 use row-then-column order (§11.1).
  assign row_first = (hdr_path_shape == SROTA_ROW_FIRST) ||
                     (hdr_path_shape == SROTA_VALIANT_L1);

  assign rc_is_eject = (tgt_x == cfg_my_x) && (tgt_y == cfg_my_y);
  assign rc_valid    = |rc_port_oh;

  always_comb begin
    rc_port_oh    = '0;
    rc_turn_taken = 1'b0;

    if (rc_is_eject) begin
      // Eject uses the header tile, not the Valiant intermediate (§11.1).
      // hdr_dest_tile is assumed valid (0 .. C-1), as in §8.2.
      rc_port_oh[srota_local_eject_port(int'(hdr_dest_tile), C)] = 1'b1;
    end else if (row_first) begin
      if (tgt_x != cfg_my_x) begin
        rc_port_oh[srota_row_out_port(C)] = 1'b1;
      end else begin
        rc_port_oh[srota_col_out_port(C)] = 1'b1;
        rc_turn_taken = 1'b1;
      end
    end else begin
      // Column-first. RESERVED follows the doc's else branch (§11.1).
      if (tgt_y != cfg_my_y) begin
        rc_port_oh[srota_col_out_port(C)] = 1'b1;
      end else begin
        rc_port_oh[srota_row_out_port(C)] = 1'b1;
        rc_turn_taken = 1'b1;
      end
    end
  end

endmodule

`default_nettype wire
