// VeritX Research — Fully-Functional 7-Port 3D NoC Mesh Router (router_3d.sv)
// 7 Ports: East, West, North, South, Up (+Z TSV), Down (-Z TSV), Local

import noc_3d_pkg::*;

module router_3d #(
  parameter int VCS   = 1,
  parameter int NODE  = 0
) (
  input  logic         clk,
  input  logic         rst_n,

  // 7 input / output links (E, W, N, S, U, D, L)
  input  link_f_t      flit_in[NUM_PORTS],
  input  link_c_t      credit_in[NUM_PORTS],
  output link_f_t      flit_out[NUM_PORTS],
  output link_c_t      credit_out[NUM_PORTS]
);

  localparam int X_CURR = NODE % X_DIM;
  localparam int Y_CURR = (NODE / X_DIM) % Y_DIM;
  localparam int Z_CURR = NODE / (X_DIM * Y_DIM);

  // 3D DOR Routing Function (X -> Y -> Z)
  function automatic logic [2:0] route_3d(input logic [7:0] dst);
    int x_dst = int'(dst) % X_DIM;
    int y_dst = (int'(dst) / X_DIM) % Y_DIM;
    int z_dst = int'(dst) / (X_DIM * Y_DIM);

    if (x_dst > X_CURR)      return PORT_E[2:0];
    else if (x_dst < X_CURR) return PORT_W[2:0];
    else if (y_dst > Y_CURR) return PORT_N[2:0];
    else if (y_dst < Y_CURR) return PORT_S[2:0];
    else if (z_dst > Z_CURR) return PORT_U[2:0];
    else if (z_dst < Z_CURR) return PORT_D[2:0];
    else                     return PORT_L[2:0];
  endfunction

  // Per-port input FIFO buffer (depth 8)
  flit_t qbuf [NUM_PORTS][8];
  logic [3:0] qcnt[NUM_PORTS];
  logic [2:0] head_ptr[NUM_PORTS];
  logic [2:0] tail_ptr[NUM_PORTS];

  // Downstream credit tracking per output port
  logic [3:0] cred_free[NUM_PORTS];

  always_ff @(posedge clk or negedge rst_n) begin
    if (!rst_n) begin
      for (int p = 0; p < NUM_PORTS; p++) begin
        qcnt[p] <= '0;
        head_ptr[p] <= '0;
        tail_ptr[p] <= '0;
        cred_free[p] <= VC_BUF_DEF[3:0];
        flit_out[p].valid <= 1'b0;
        credit_out[p].valid <= 1'b0;
      end
    end else begin
      // Credit return tracking
      for (int p = 0; p < NUM_PORTS; p++) begin
        if (credit_in[p].valid) begin
          cred_free[p] <= cred_free[p] + 1;
        end
      end

      // Write incoming flits into input FIFO
      for (int p = 0; p < NUM_PORTS; p++) begin
        credit_out[p].valid <= 1'b0;
        if (flit_in[p].valid && (qcnt[p] < 8)) begin
          qbuf[p][tail_ptr[p]] <= flit_in[p].flit;
          tail_ptr[p] <= tail_ptr[p] + 1;
          qcnt[p] <= qcnt[p] + 1;
        end
      end

      // Arbitrate & Forward flits to output ports
      for (int o = 0; o < NUM_PORTS; o++) begin
        flit_out[o].valid <= 1'b0;
        for (int i = 0; i < NUM_PORTS; i++) begin
          if ((qcnt[i] > 0) && !flit_out[o].valid && (cred_free[o] > 0)) begin
            logic [2:0] target_port = route_3d(qbuf[i][head_ptr[i]].dst);
            if (target_port == o[2:0]) begin
              // Forward flit out
              flit_out[o].valid <= 1'b1;
              flit_out[o].flit  <= qbuf[i][head_ptr[i]];
              cred_free[o]      <= cred_free[o] - 1;

              // Pop input FIFO & send upstream credit
              head_ptr[i] <= head_ptr[i] + 1;
              qcnt[i]     <= qcnt[i] - 1;
              credit_out[i].valid <= 1'b1;
              credit_out[i].vc    <= '0;
            end
          end
        end
      end
    end
  end

endmodule
