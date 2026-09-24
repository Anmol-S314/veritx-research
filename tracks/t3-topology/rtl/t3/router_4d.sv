// VeritX Research — 4D NoC Hypercube Router (9-Port: E, W, N, S, U, D, W4, E4, L)
// Implements 4D Dimension-Order Routing (X -> Y -> Z -> W 4D-DOR)

import noc_4d_pkg::*;

module router_4d #(
  parameter int VCS   = 1,
  parameter int NODE  = 0
) (
  input  logic         clk,
  input  logic         rst_n,

  // 9 input / output links
  input  link_f_t      flit_in[NUM_PORTS],
  input  link_c_t      credit_in[NUM_PORTS],
  output link_f_t      flit_out[NUM_PORTS],
  output link_c_t      credit_out[NUM_PORTS]
);

  // Derive 4D coordinates (X, Y, Z, W)
  localparam int X_CURR = NODE % X_DIM;
  localparam int Y_CURR = (NODE / X_DIM) % Y_DIM;
  localparam int Z_CURR = (NODE / (X_DIM * Y_DIM)) % Z_DIM;
  localparam int W_CURR = NODE / (X_DIM * Y_DIM * Z_DIM);

  // ------------------------------------------------------------------
  // 4D Dimension-Order Routing Function (X -> Y -> Z -> W 4D-DOR)
  // ------------------------------------------------------------------
  function automatic logic [3:0] route_4d(input logic [7:0] dst);
    int x_dst = int'(dst) % X_DIM;
    int y_dst = (int'(dst) / X_DIM) % Y_DIM;
    int z_dst = (int'(dst) / (X_DIM * Y_DIM)) % Z_DIM;
    int w_dst = int'(dst) / (X_DIM * Y_DIM * Z_DIM);

    if (x_dst > X_CURR)      return PORT_E[3:0];  // Step +X
    else if (x_dst < X_CURR) return PORT_W[3:0];  // Step -X
    else if (y_dst > Y_CURR) return PORT_N[3:0];  // Step +Y
    else if (y_dst < Y_CURR) return PORT_S[3:0];  // Step -Y
    else if (z_dst > Z_CURR) return PORT_U[3:0];  // Step +Z
    else if (z_dst < Z_CURR) return PORT_D[3:0];  // Step -Z
    else if (w_dst > W_CURR) return PORT_W4[3:0]; // Step +W (4th Dimension)
    else if (w_dst < W_CURR) return PORT_E4[3:0]; // Step -W (4th Dimension)
    else                     return PORT_L[3:0];  // Eject to Local NIC
  endfunction

  // ------------------------------------------------------------------
  // Router States & Input Buffers (9 Ports x VCS Virtual Channels)
  // ------------------------------------------------------------------
  typedef enum logic [2:0] {
    S_IDLE, S_VA_REQ, S_VA_WAIT, S_SA_HOLD, S_ACTIVE
  } state_e;

  localparam int VC_W = $clog2(VCS) > 0 ? $clog2(VCS) : 1;

  state_e          st        [NUM_PORTS][VCS];
  logic [3:0]      out_port  [NUM_PORTS][VCS];
  logic [VC_W-1:0] out_vc    [NUM_PORTS][VCS];

  // Credit Tracking per Downstream Output Port
  logic [3:0] cred_free[NUM_PORTS][VCS];

  always_ff @(posedge clk or negedge rst_n) begin
    if (!rst_n) begin
      for (int p = 0; p < NUM_PORTS; p++) begin
        for (int v = 0; v < VCS; v++) begin
          st[p][v] <= S_IDLE;
          cred_free[p][v] <= VC_BUF_DEF[3:0];
        end
      end
    end else begin
      for (int p = 0; p < NUM_PORTS; p++) begin
        if (credit_in[p].valid) begin
          cred_free[p][credit_in[p].vc] <= cred_free[p][credit_in[p].vc] + 1;
        end
      end
    end
  end

endmodule
