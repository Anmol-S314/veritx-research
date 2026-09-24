`ifndef NOC_MESH_SV
`define NOC_MESH_SV

// 4x4 mesh of noc_router + NICs. Link = 2 register stages in each direction
// (flit and credit), matching the measured BookSim channel behavior:
// send at T -> receive at T+2 (RTL-ARC.md, "Channel latency").
// Node id = y*X_DIM + x (row-major, y first) -- verified against the fork's
// kncube numbering via the 2x2 watch trace.

import noc_pkg::*;

module noc_mesh #(
  parameter int VCS   = 4,
  parameter int X_DIM = 4,
  parameter int Y_DIM = 4
)(
  input  logic clk,
  input  logic rst_n,
  // NIC side: node (x,y) injects/ejects via these (1 flit per node per cycle)
  input  link_f_t inject [Y_DIM][X_DIM],   // NIC -> router local port
  output link_c_t inject_credit [Y_DIM][X_DIM],
  output link_c_t inject_credit_early [Y_DIM][X_DIM],  // injc_st1 (1-cycle-early)
  output link_f_t eject  [Y_DIM][X_DIM],   // router local port -> NIC
  input  link_c_t eject_credit [Y_DIM][X_DIM],
  output logic [31:0] router_pop [Y_DIM][X_DIM][NUM_PORTS],
  output logic [31:0] router_recv [Y_DIM][X_DIM][NUM_PORTS],
  output dbg_router_t router_dbg [Y_DIM][X_DIM]
);

  localparam int N = X_DIM * Y_DIM;

  // inter-router channel stage registers (ports E/W/N/S)
  link_f_t f_st1 [N][4];
  link_f_t f_st2 [N][4];
  link_c_t c_st1 [N][4];
  link_c_t c_st2 [N][4];

  // local-port channels (inject: NIC->router; eject: router->NIC)
  link_f_t inj_st1 [N]; link_f_t inj_st2 [N];
  link_f_t ej_st1  [N]; link_f_t ej_st2  [N];
  link_c_t ejc_st1 [N]; link_c_t ejc_st2 [N];   // NIC eject credit -> router
  link_c_t injc_st1[N]; link_c_t injc_st2[N];   // router pop credit -> NIC

  // router ports
  link_f_t rf_in [N][NUM_PORTS];
  link_c_t rc_in [N][NUM_PORTS];
  link_c_t rc_early_in[N][NUM_PORTS];   // stage-1 credit (read-at-T view)
  link_f_t rf_out[N][NUM_PORTS];
  link_c_t rc_out[N][NUM_PORTS];

  logic [31:0] r_pop[N][NUM_PORTS];
  logic [31:0] r_recv[N][NUM_PORTS];
  dbg_router_t r_dbg[N];

  for (genvar y = 0; y < Y_DIM; y++) begin : gen_router_row
    for (genvar x = 0; x < X_DIM; x++) begin : gen_router_col
      localparam int n = y * X_DIM + x;
      noc_router #(
        .VCS(VCS), .X(x), .Y(y), .X_DIM(X_DIM), .Y_DIM(Y_DIM)
      ) u_router (
        .clk(clk), .rst_n(rst_n),
        .flit_in(rf_in[n]), .credit_in(rc_in[n]),
        .credit_in_early(rc_early_in[n]),
        .flit_out(rf_out[n]), .credit_out(rc_out[n]),
        .tick(), .recv_cnt(r_recv[n]), .send_cnt(), .pop_cnt(r_pop[n]),
        .dbg(r_dbg[n])
      );
      always_comb begin
        for (int p = 0; p < NUM_PORTS; p++) router_pop[y][x][p] = r_pop[n][p];
        for (int p = 0; p < NUM_PORTS; p++) router_recv[y][x][p] = r_recv[n][p];
        router_dbg[y][x] = r_dbg[n];
      end
    end
  end

  // channel stages
  always_ff @(posedge clk or negedge rst_n) begin
    if (!rst_n) begin
      for (int e = 0; e < N; e++) begin
        for (int p = 0; p < 4; p++) begin
          f_st1[e][p].valid <= 1'b0; f_st2[e][p].valid <= 1'b0;
          c_st1[e][p].valid <= 1'b0; c_st2[e][p].valid <= 1'b0;
        end
        inj_st1[e].valid <= 1'b0; inj_st2[e].valid <= 1'b0;
        ej_st1[e].valid  <= 1'b0; ej_st2[e].valid  <= 1'b0;
        ejc_st1[e].valid <= 1'b0; ejc_st2[e].valid <= 1'b0;
        injc_st1[e].valid <= 1'b0; injc_st2[e].valid <= 1'b0;
      end
    end else begin
      for (int e = 0; e < N; e++) begin
        for (int p = 0; p < 4; p++) begin
          f_st1[e][p] <= rf_out[e][p];
          f_st2[e][p] <= f_st1[e][p];
          c_st1[e][p] <= rc_out[e][p];
          c_st2[e][p] <= c_st1[e][p];
        end
        inj_st1[e]  <= inject[e / X_DIM][e % X_DIM];
        inj_st2[e]  <= inj_st1[e];
        ej_st1[e]   <= rf_out[e][PORT_L];
        ej_st2[e]   <= ej_st1[e];
        ejc_st1[e]  <= eject_credit[e / X_DIM][e % X_DIM];
        ejc_st2[e]  <= ejc_st1[e];
        injc_st1[e] <= rc_out[e][PORT_L];
        injc_st2[e] <= injc_st1[e];
      end
    end
  end

  // static wiring (E/W/N/S) + local port hookup
  always_comb begin
    for (int y = 0; y < Y_DIM; y++) begin
      for (int x = 0; x < X_DIM; x++) begin
        int n = y * X_DIM + x;
        for (int p = 0; p < NUM_PORTS; p++) begin
          rf_in[n][p].valid = 1'b0;
          rc_in[n][p].valid = 1'b0;
          rc_early_in[n][p].valid = 1'b0;
          rf_in[n][p].flit = '0;
          rc_in[n][p].vc = '0;
          rc_early_in[n][p].vc = '0;
        end
        if (x + 1 < X_DIM) begin
          int nb = y * X_DIM + (x + 1);
          rf_in[n][PORT_E] = f_st2[nb][PORT_W];
          rc_in[n][PORT_E] = c_st2[nb][PORT_W];
          rc_early_in[n][PORT_E] = c_st1[nb][PORT_W];
        end
        if (x - 1 >= 0) begin
          int nb = y * X_DIM + (x - 1);
          rf_in[n][PORT_W] = f_st2[nb][PORT_E];
          rc_in[n][PORT_W] = c_st2[nb][PORT_E];
          rc_early_in[n][PORT_W] = c_st1[nb][PORT_E];
        end
        if (y + 1 < Y_DIM) begin
          int nb = (y + 1) * X_DIM + x;
          rf_in[n][PORT_N] = f_st2[nb][PORT_S];
          rc_in[n][PORT_N] = c_st2[nb][PORT_S];
          rc_early_in[n][PORT_N] = c_st1[nb][PORT_S];
        end
        if (y - 1 >= 0) begin
          int nb = (y - 1) * X_DIM + x;
          rf_in[n][PORT_S] = f_st2[nb][PORT_N];
          rc_in[n][PORT_S] = c_st2[nb][PORT_N];
          rc_early_in[n][PORT_S] = c_st1[nb][PORT_N];
        end
        rf_in[n][PORT_L]      = inj_st2[n];
        rc_in[n][PORT_L]      = ejc_st2[n];
        rc_early_in[n][PORT_L] = ejc_st1[n];
        eject[y][x]           = ej_st2[n];
        inject_credit[y][x]   = injc_st2[n];
        inject_credit_early[y][x] = injc_st1[n];
      end
    end
  end

endmodule

`endif
