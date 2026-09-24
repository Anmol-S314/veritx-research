// VeritX Research — 3D Mesh Top-Level Interconnect (mesh_3d.sv)
// Connects 4x4x2 (32 nodes) 3D Stacked Logic/Memory Dies via 7-Port Routers & 3D TSV Links

import noc_3d_pkg::*;

module mesh_3d #(
  parameter int VCS = 1
) (
  input  logic    clk,
  input  logic    rst_n,

  // Local NIC Injection & Ejection Ports across all 3D nodes (X_DIM * Y_DIM * Z_DIM)
  input  link_f_t inject_flit  [Z_DIM][Y_DIM][X_DIM],
  input  link_c_t eject_credit [Z_DIM][Y_DIM][X_DIM],
  output link_f_t eject_flit   [Z_DIM][Y_DIM][X_DIM],
  output link_c_t inject_credit[Z_DIM][Y_DIM][X_DIM]
);

  localparam int TOTAL_NODES = X_DIM * Y_DIM * Z_DIM;

  // Inter-Router Flit & Credit Wires (7 Ports per Node)
  link_f_t r_flit_out  [TOTAL_NODES][NUM_PORTS];
  link_c_t r_credit_out[TOTAL_NODES][NUM_PORTS];
  link_f_t r_flit_in   [TOTAL_NODES][NUM_PORTS];
  link_c_t r_credit_in  [TOTAL_NODES][NUM_PORTS];

  // Instantiation of 3D Routers across X, Y, Z
  generate
    for (genvar z = 0; z < Z_DIM; z++) begin : gen_z
      for (genvar y = 0; y < Y_DIM; y++) begin : gen_y
        for (genvar x = 0; x < X_DIM; x++) begin : gen_x
          localparam int node_id = z * (X_DIM * Y_DIM) + y * X_DIM + x;

          router_3d #(
            .VCS(VCS),
            .NODE(node_id)
          ) u_router_3d (
            .clk(clk),
            .rst_n(rst_n),
            .flit_in(r_flit_in[node_id]),
            .credit_in(r_credit_in[node_id]),
            .flit_out(r_flit_out[node_id]),
            .credit_out(r_credit_out[node_id])
          );

          // Connect Local NIC to Port 6 (PORT_L)
          assign r_flit_in[node_id][PORT_L]    = inject_flit[z][y][x];
          assign r_credit_in[node_id][PORT_L]  = eject_credit[z][y][x];
          assign eject_flit[z][y][x]           = r_flit_out[node_id][PORT_L];
          assign inject_credit[z][y][x]        = r_credit_out[node_id][PORT_L];
        end
      end
    end
  endgenerate

  // ------------------------------------------------------------------
  // 3D Interconnect Wiring: Horizontal (2D) + Vertical (3D TSV Links)
  // ------------------------------------------------------------------
  generate
    for (genvar z = 0; z < Z_DIM; z++) begin : wire_z
      for (genvar y = 0; y < Y_DIM; y++) begin : wire_y
        for (genvar x = 0; x < X_DIM; x++) begin : wire_x
          localparam int curr = z * (X_DIM * Y_DIM) + y * X_DIM + x;

          // East / West (+X / -X) Horizontal 2D Links
          if (x < X_DIM - 1) begin : link_east
            localparam int east = z * (X_DIM * Y_DIM) + y * X_DIM + (x + 1);
            assign r_flit_in[east][PORT_W]   = r_flit_out[curr][PORT_E];
            assign r_credit_in[curr][PORT_E] = r_credit_out[east][PORT_W];
          end else begin : link_east_none
            assign r_flit_in[curr][PORT_E]   = '0;
            assign r_credit_in[curr][PORT_E] = '0;
          end

          if (x > 0) begin : link_west
            localparam int west = z * (X_DIM * Y_DIM) + y * X_DIM + (x - 1);
            assign r_flit_in[west][PORT_E]   = r_flit_out[curr][PORT_W];
            assign r_credit_in[curr][PORT_W] = r_credit_out[west][PORT_E];
          end else begin : link_west_none
            assign r_flit_in[curr][PORT_W]   = '0;
            assign r_credit_in[curr][PORT_W] = '0;
          end

          // North / South (+Y / -Y) Horizontal 2D Links
          if (y < Y_DIM - 1) begin : link_north
            localparam int north = z * (X_DIM * Y_DIM) + (y + 1) * X_DIM + x;
            assign r_flit_in[north][PORT_S]  = r_flit_out[curr][PORT_N];
            assign r_credit_in[curr][PORT_N] = r_credit_out[north][PORT_S];
          end else begin : link_north_none
            assign r_flit_in[curr][PORT_N]   = '0;
            assign r_credit_in[curr][PORT_N] = '0;
          end

          if (y > 0) begin : link_south
            localparam int south = z * (X_DIM * Y_DIM) + (y - 1) * X_DIM + x;
            assign r_flit_in[south][PORT_N]  = r_flit_out[curr][PORT_S];
            assign r_credit_in[curr][PORT_S] = r_credit_out[south][PORT_N];
          end else begin : link_south_none
            assign r_flit_in[curr][PORT_S]   = '0;
            assign r_credit_in[curr][PORT_S] = '0;
          end

          // ------------------------------------------------------------
          // Up / Down (+Z / -Z) Vertical 3D TSV Inter-Die Links!
          // ------------------------------------------------------------
          if (z < Z_DIM - 1) begin : link_up_tsv
            localparam int up_node = (z + 1) * (X_DIM * Y_DIM) + y * X_DIM + x;
            assign r_flit_in[up_node][PORT_D] = r_flit_out[curr][PORT_U];
            assign r_credit_in[curr][PORT_U]  = r_credit_out[up_node][PORT_D];
          end else begin : link_up_none
            assign r_flit_in[curr][PORT_U]   = '0;
            assign r_credit_in[curr][PORT_U] = '0;
          end

          if (z > 0) begin : link_down_tsv
            localparam int down_node = (z - 1) * (X_DIM * Y_DIM) + y * X_DIM + x;
            assign r_flit_in[down_node][PORT_U] = r_flit_out[curr][PORT_D];
            assign r_credit_in[curr][PORT_D]   = r_credit_out[down_node][PORT_U];
          end else begin : link_down_none
            assign r_flit_in[curr][PORT_D]   = '0;
            assign r_credit_in[curr][PORT_D] = '0;
          end

        end
      end
    end
  endgenerate

endmodule
