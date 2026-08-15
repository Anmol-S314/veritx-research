`ifndef NOC_2DIE_SV
`define NOC_2DIE_SV

// VeritX — two 8x8 meshes joined by ONE bridge link (UCIe-class).
// Die A nodes 0-63, die B nodes 64-127 (row-major, y first per die).
// Bridge: die-A edge router (Y=7,X=BRIDGE_COL) EAST out -> die-B (Y=0, BRIDGE_COL)
// WEST in, and back. Port mapping on both sides uses the E/W slots so the
// router's DOR sees a straight line across the boundary.

import noc_pkg::*;

module noc_2die #(
  parameter int VCS        = 4,
  parameter int X_DIM      = 8,
  parameter int Y_DIM      = 8,
  parameter int BRIDGE_COL = 0,
  parameter int BRIDGE_ROW = 0
)(
  input  logic clk,
  input  logic rst_n,
  input  link_f_t inject [2][Y_DIM][X_DIM],
  output link_c_t inject_credit [2][Y_DIM][X_DIM],
  output link_c_t inject_credit_early [2][Y_DIM][X_DIM],
  output link_f_t eject  [2][Y_DIM][X_DIM],
  input  link_c_t eject_credit [2][Y_DIM][X_DIM],
  // F9 (889f): debug/audit outputs — were dangling (all-zero readout in
  // TWO_DIE mode, DBG2/3/5 dead). Same wiring as noc_mesh.
  output logic [31:0] router_pop [2][Y_DIM][X_DIM][NUM_PORTS],
  output logic [31:0] router_recv [2][Y_DIM][X_DIM][NUM_PORTS],
  output dbg_router_t router_dbg [2][Y_DIM][X_DIM]
);

  localparam int N = X_DIM * Y_DIM;

  // per-die router links (5 ports), same wiring as noc_mesh
  link_f_t rf_in [2][N][NUM_PORTS];
  link_c_t rc_in [2][N][NUM_PORTS];
  link_c_t rc_early_in[2][N][NUM_PORTS];
  link_f_t rf_out[2][N][NUM_PORTS];
  link_c_t rc_out[2][N][NUM_PORTS];

  // channel stage regs
  link_f_t f_st1 [2][N][4], f_st2 [2][N][4];
  link_c_t c_st1 [2][N][4], c_st2 [2][N][4];
  link_f_t inj_st1 [2][N], inj_st2 [2][N];
  link_f_t ej_st1  [2][N], ej_st2  [2][N];
  link_c_t ejc_st1 [2][N], ejc_st2 [2][N];
  link_c_t injc_st1[2][N], injc_st2[2][N];

  // bridge channel stages (link latency 2, like every other link)
  // Dave 2026-08-15: depth 2 -> 3 per the CreditBased minimum-FIFO rule
  // (Leone/Colagrande/Benini, arXiv 2607.01430 §III-3): with registered
  // credit return, a 2-deep downstream FIFO loses up to 33% throughput and
  // starves one direction under bidirectional contention (measured: A->B
  // 11% vs B->A 82% on the 2-deep bridge). Depth 3 absorbs the credit-
  // return latency and sustains full bandwidth in both directions.
  link_f_t br_f1, br_f2, br_f3, br_f1b, br_f2b, br_f3b;
  link_c_t br_c1, br_c2, br_c1b, br_c2b;

  // F9: per-die debug mirrors (same role as noc_mesh's r_pop/r_recv/r_dbg)
  logic [31:0] r_pop [2][N][NUM_PORTS];
  logic [31:0] r_recv [2][N][NUM_PORTS];
  dbg_router_t r_dbg [2][N];

  for (genvar d = 0; d < 2; d++) begin : gen_die
    for (genvar y = 0; y < Y_DIM; y++) begin : gen_row
      for (genvar x = 0; x < X_DIM; x++) begin : gen_col
        localparam int n = y * X_DIM + x;
        noc_router #(
          .VCS(VCS), .X(x), .Y(y), .X_DIM(X_DIM), .Y_DIM(Y_DIM),
          .DIE_BASE(d * 64), .BRIDGE_COL(BRIDGE_COL), .BRIDGE_ROW(BRIDGE_ROW)
        ) u_router (
          .clk(clk), .rst_n(rst_n),
          .flit_in(rf_in[d][n]), .credit_in(rc_in[d][n]),
          .credit_in_early(rc_early_in[d][n]),
          .flit_out(rf_out[d][n]), .credit_out(rc_out[d][n]),
          .tick(), .recv_cnt(r_recv[d][n]), .send_cnt(), .pop_cnt(r_pop[d][n]),
          .dbg(r_dbg[d][n])
        );
      end
    end
  end

  for (genvar d = 0; d < 2; d++) begin : gen_dbg_map
    for (genvar y = 0; y < Y_DIM; y++) begin : gen_dbg_row
      for (genvar x = 0; x < X_DIM; x++) begin : gen_dbg_col
        localparam int n = y * X_DIM + x;
        assign router_pop[d][y][x] = r_pop[d][n];
        assign router_recv[d][y][x] = r_recv[d][n];
        assign router_dbg[d][y][x] = r_dbg[d][n];
      end
    end
  end

  always_ff @(posedge clk or negedge rst_n) begin
    if (!rst_n) begin
      for (int d = 0; d < 2; d++)
        for (int e = 0; e < N; e++) begin
          for (int p = 0; p < 4; p++) begin
            f_st1[d][e][p].valid <= 1'b0; f_st2[d][e][p].valid <= 1'b0;
            c_st1[d][e][p].valid <= 1'b0; c_st2[d][e][p].valid <= 1'b0;
          end
          inj_st1[d][e].valid <= 1'b0; inj_st2[d][e].valid <= 1'b0;
          ej_st1[d][e].valid  <= 1'b0; ej_st2[d][e].valid  <= 1'b0;
          ejc_st1[d][e].valid <= 1'b0; ejc_st2[d][e].valid <= 1'b0;
          injc_st1[d][e].valid <= 1'b0; injc_st2[d][e].valid <= 1'b0;
        end
      br_f1.valid <= 1'b0; br_f2.valid <= 1'b0; br_f3.valid <= 1'b0;
      br_f1b.valid <= 1'b0; br_f2b.valid <= 1'b0; br_f3b.valid <= 1'b0;
      br_c1.valid <= 1'b0; br_c2.valid <= 1'b0;
      br_c1b.valid <= 1'b0; br_c2b.valid <= 1'b0;
    end else begin
      for (int d = 0; d < 2; d++)
        for (int e = 0; e < N; e++) begin
          for (int p = 0; p < 4; p++) begin
            // the bridge-column edge router's EAST (die A) and the bridge
            // entry's WEST (die B) feed the bridge, not a mesh channel stage
            if (!(d == 0 && e == (Y_DIM-1) * X_DIM + BRIDGE_COL && p == PORT_E) &&
                !(d == 1 && e == BRIDGE_ROW * X_DIM + BRIDGE_COL && p == PORT_W)) begin
              f_st1[d][e][p] <= rf_out[d][e][p];
              f_st2[d][e][p] <= f_st1[d][e][p];
              c_st1[d][e][p] <= rc_out[d][e][p];
              c_st2[d][e][p] <= c_st1[d][e][p];
            end
          end
          inj_st1[d][e]  <= inject[d][e / X_DIM][e % X_DIM];
          inj_st2[d][e]  <= inj_st1[d][e];
          ej_st1[d][e]   <= rf_out[d][e][PORT_L];
          ej_st2[d][e]   <= ej_st1[d][e];
          ejc_st1[d][e]  <= eject_credit[d][e / X_DIM][e % X_DIM];
          ejc_st2[d][e]  <= ejc_st1[d][e];
          injc_st1[d][e] <= rc_out[d][e][PORT_L];
          injc_st2[d][e] <= injc_st1[d][e];
        end
      // bridge channels (both directions, 3-stage: CreditBased min-FIFO)
      br_f1  <= rf_out[0][(Y_DIM-1) * X_DIM + BRIDGE_COL][PORT_E];
      br_f2  <= br_f1;
      br_f3  <= br_f2;
      br_f1b <= rf_out[1][BRIDGE_ROW * X_DIM + BRIDGE_COL][PORT_W];
      br_f2b <= br_f1b;
      br_f3b <= br_f2b;
      br_c1  <= rc_out[1][BRIDGE_ROW * X_DIM + BRIDGE_COL][PORT_W];
      br_c2  <= br_c1;
      br_c1b <= rc_out[0][(Y_DIM-1) * X_DIM + BRIDGE_COL][PORT_E];
      br_c2b <= br_c1b;
    end
  end

  // static wiring (mesh within die + bridge at the boundary column)
  always_comb begin
    for (int d = 0; d < 2; d++) begin
      for (int y = 0; y < Y_DIM; y++) begin
        for (int x = 0; x < X_DIM; x++) begin
          int n = y * X_DIM + x;
          for (int p = 0; p < NUM_PORTS; p++) begin
            rf_in[d][n][p].valid = 1'b0;
            rc_in[d][n][p].valid = 1'b0;
            rc_early_in[d][n][p].valid = 1'b0;
            rf_in[d][n][p].flit = '0;
            rc_in[d][n][p].vc = '0;
            rc_early_in[d][n][p].vc = '0;
          end
          // die A: the bridge column's edge router uses EAST for the bridge,
          // so its normal mesh east link is suppressed (no duplicate path)
          if (x + 1 < X_DIM &&
              !(d == 0 && y == Y_DIM-1 && x == BRIDGE_COL)) begin
            int nb = y * X_DIM + (x + 1);
            rf_in[d][n][PORT_E] = f_st2[d][nb][PORT_W];
            rc_in[d][n][PORT_E] = c_st2[d][nb][PORT_W];
            rc_early_in[d][n][PORT_E] = c_st1[d][nb][PORT_W];
          end
          // die B: the bridge entry router's WEST is the bridge input, so its
          // normal mesh west link is suppressed (no duplicate return path)
          if (x - 1 >= 0 &&
              !(d == 1 && y == BRIDGE_ROW && x == BRIDGE_COL)) begin
            int nb = y * X_DIM + (x - 1);
            rf_in[d][n][PORT_W] = f_st2[d][nb][PORT_E];
            rc_in[d][n][PORT_W] = c_st2[d][nb][PORT_E];
            rc_early_in[d][n][PORT_W] = c_st1[d][nb][PORT_E];
          end
          if (y + 1 < Y_DIM) begin
            int nb = (y + 1) * X_DIM + x;
            rf_in[d][n][PORT_N] = f_st2[d][nb][PORT_S];
            rc_in[d][n][PORT_N] = c_st2[d][nb][PORT_S];
            rc_early_in[d][n][PORT_N] = c_st1[d][nb][PORT_S];
          end
          if (y - 1 >= 0) begin
            int nb = (y - 1) * X_DIM + x;
            rf_in[d][n][PORT_S] = f_st2[d][nb][PORT_N];
            rc_in[d][n][PORT_S] = c_st2[d][nb][PORT_N];
            rc_early_in[d][n][PORT_S] = c_st1[d][nb][PORT_N];
          end
          rf_in[d][n][PORT_L]      = inj_st2[d][n];
          rc_in[d][n][PORT_L]      = ejc_st2[d][n];
          rc_early_in[d][n][PORT_L] = ejc_st1[d][n];
          eject[d][y][x]           = ej_st2[d][n];
          inject_credit[d][y][x]   = injc_st2[d][n];
          inject_credit_early[d][y][x] = injc_st1[d][n];
        end
      end
    end
    // bridge: die-A (Y_DIM-1, BRIDGE_COL) EAST <-> die-B (0, BRIDGE_COL) WEST
    begin
      int a = (Y_DIM-1) * X_DIM + BRIDGE_COL;
      int b = BRIDGE_ROW * X_DIM + BRIDGE_COL;
      rf_in[0][a][PORT_E] = br_f3b;         // die A sees die-B's west out (3-stage)
      rc_in[0][a][PORT_E] = br_c2;          // die-A E credit-in = die-B W credit-out
      rc_early_in[0][a][PORT_E] = br_c1;
      rf_in[1][b][PORT_W] = br_f3;          // die B sees die-A's east out (3-stage)
      rc_in[1][b][PORT_W] = br_c2b;         // die-B W credit-in = die-A E credit-out
      rc_early_in[1][b][PORT_W] = br_c1b;
    end
  end

endmodule

`endif
