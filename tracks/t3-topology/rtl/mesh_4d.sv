// VeritX Research — 4D Mesh Top-Level Interconnect (mesh_4d.sv)
// Connects 2x2x2x2 (16 nodes) or 4x4x4x4 (256 nodes) 4D Hypercube / Multi-Plane NoCs via 9-Port Routers

import noc_4d_pkg::*;

module mesh_4d #(
  parameter int VCS = 1
) (
  input  logic    clk,
  input  logic    rst_n,

  // Local NIC Injection & Ejection Ports across 4D space [W][Z][Y][X]
  input  link_f_t inject_flit  [W_DIM][Z_DIM][Y_DIM][X_DIM],
  input  link_c_t eject_credit [W_DIM][Z_DIM][Y_DIM][X_DIM],
  output link_f_t eject_flit   [W_DIM][Z_DIM][Y_DIM][X_DIM],
  output link_c_t inject_credit[W_DIM][Z_DIM][Y_DIM][X_DIM]
);

  localparam int TOTAL_NODES = X_DIM * Y_DIM * Z_DIM * W_DIM;

  // Inter-Router Flit & Credit Wires (9 Ports per Node)
  link_f_t r_flit_out  [TOTAL_NODES][NUM_PORTS];
  link_c_t r_credit_out[TOTAL_NODES][NUM_PORTS];
  link_f_t r_flit_in   [TOTAL_NODES][NUM_PORTS];
  link_c_t r_credit_in  [TOTAL_NODES][NUM_PORTS];

  // Instantiation of 4D Routers across X, Y, Z, W
  generate
    for (genvar w = 0; w < W_DIM; w++) begin : gen_w
      for (genvar z = 0; z < Z_DIM; z++) begin : gen_z
        for (genvar y = 0; y < Y_DIM; y++) begin : gen_y
          for (genvar x = 0; x < X_DIM; x++) begin : gen_x
            localparam int node_id = w * (X_DIM * Y_DIM * Z_DIM) + z * (X_DIM * Y_DIM) + y * X_DIM + x;

            router_4d #(
              .VCS(VCS),
              .NODE(node_id)
            ) u_router_4d (
              .clk(clk),
              .rst_n(rst_n),
              .flit_in(r_flit_in[node_id]),
              .credit_in(r_credit_in[node_id]),
              .flit_out(r_flit_out[node_id]),
              .credit_out(r_credit_out[node_id])
            );

            // Connect Local NIC to Port 8 (PORT_L)
            assign r_flit_in[node_id][PORT_L]    = inject_flit[w][z][y][x];
            assign r_credit_in[node_id][PORT_L]  = eject_credit[w][z][y][x];
            assign eject_flit[w][z][y][x]        = r_flit_out[node_id][PORT_L];
            assign inject_credit[w][z][y][x]     = r_credit_out[node_id][PORT_L];
          end
        end
      end
    end
  endgenerate

  // ------------------------------------------------------------------
  // 4D Interconnect Wiring: X, Y, Z, W Dimensions
  // ------------------------------------------------------------------
  generate
    for (genvar w = 0; w < W_DIM; w++) begin : wire_w
      for (genvar z = 0; z < Z_DIM; z++) begin : wire_z
        for (genvar y = 0; y < Y_DIM; y++) begin : wire_y
          for (genvar x = 0; x < X_DIM; x++) begin : wire_x
            localparam int curr = w * (X_DIM * Y_DIM * Z_DIM) + z * (X_DIM * Y_DIM) + y * X_DIM + x;

            // X-Dimension Links
            if (x < X_DIM - 1) begin : link_east
              localparam int east = w * (X_DIM * Y_DIM * Z_DIM) + z * (X_DIM * Y_DIM) + y * X_DIM + (x + 1);
              assign r_flit_in[east][PORT_W]   = r_flit_out[curr][PORT_E];
              assign r_credit_in[curr][PORT_E] = r_credit_out[east][PORT_W];
            end else begin : link_east_none
              assign r_flit_in[curr][PORT_E]   = '0;
              assign r_credit_in[curr][PORT_E] = '0;
            end

            if (x > 0) begin : link_west
              localparam int west = w * (X_DIM * Y_DIM * Z_DIM) + z * (X_DIM * Y_DIM) + y * X_DIM + (x - 1);
              assign r_flit_in[west][PORT_E]   = r_flit_out[curr][PORT_W];
              assign r_credit_in[curr][PORT_W] = r_credit_out[west][PORT_E];
            end else begin : link_west_none
              assign r_flit_in[curr][PORT_W]   = '0;
              assign r_credit_in[curr][PORT_W] = '0;
            end

            // Y-Dimension Links
            if (y < Y_DIM - 1) begin : link_north
              localparam int north = w * (X_DIM * Y_DIM * Z_DIM) + z * (X_DIM * Y_DIM) + (y + 1) * X_DIM + x;
              assign r_flit_in[north][PORT_S]  = r_flit_out[curr][PORT_N];
              assign r_credit_in[curr][PORT_N] = r_credit_out[north][PORT_S];
            end else begin : link_north_none
              assign r_flit_in[curr][PORT_N]   = '0;
              assign r_credit_in[curr][PORT_N] = '0;
            end

            if (y > 0) begin : link_south
              localparam int south = w * (X_DIM * Y_DIM * Z_DIM) + z * (X_DIM * Y_DIM) + (y - 1) * X_DIM + x;
              assign r_flit_in[south][PORT_N]  = r_flit_out[curr][PORT_S];
              assign r_credit_in[curr][PORT_S] = r_credit_out[south][PORT_N];
            end else begin : link_south_none
              assign r_flit_in[curr][PORT_S]   = '0;
              assign r_credit_in[curr][PORT_S] = '0;
            end

            // Z-Dimension Links
            if (z < Z_DIM - 1) begin : link_up
              localparam int up_node = w * (X_DIM * Y_DIM * Z_DIM) + (z + 1) * (X_DIM * Y_DIM) + y * X_DIM + x;
              assign r_flit_in[up_node][PORT_D] = r_flit_out[curr][PORT_U];
              assign r_credit_in[curr][PORT_U]  = r_credit_out[up_node][PORT_D];
            end else begin : link_up_none
              assign r_flit_in[curr][PORT_U]   = '0;
              assign r_credit_in[curr][PORT_U] = '0;
            end

            if (z > 0) begin : link_down
              localparam int down_node = w * (X_DIM * Y_DIM * Z_DIM) + (z - 1) * (X_DIM * Y_DIM) + y * X_DIM + x;
              assign r_flit_in[down_node][PORT_U] = r_flit_out[curr][PORT_D];
              assign r_credit_in[curr][PORT_D]   = r_credit_out[down_node][PORT_U];
            end else begin : link_down_none
              assign r_flit_in[curr][PORT_D]   = '0;
              assign r_credit_in[curr][PORT_D] = '0;
            end

            // W-Dimension (4th Dimension Hypercube Links!)
            if (w < W_DIM - 1) begin : link_w4
              localparam int w4_node = (w + 1) * (X_DIM * Y_DIM * Z_DIM) + z * (X_DIM * Y_DIM) + y * X_DIM + x;
              assign r_flit_in[w4_node][PORT_E4] = r_flit_out[curr][PORT_W4];
              assign r_credit_in[curr][PORT_W4]  = r_credit_out[w4_node][PORT_E4];
            end else begin : link_w4_none
              assign r_flit_in[curr][PORT_W4]   = '0;
              assign r_credit_in[curr][PORT_W4] = '0;
            end

            if (w > 0) begin : link_e4
              localparam int e4_node = (w - 1) * (X_DIM * Y_DIM * Z_DIM) + z * (X_DIM * Y_DIM) + y * X_DIM + x;
              assign r_flit_in[e4_node][PORT_W4] = r_flit_out[curr][PORT_E4];
              assign r_credit_in[curr][PORT_E4]  = r_credit_out[e4_node][PORT_W4];
            end else begin : link_e4_none
              assign r_flit_in[curr][PORT_E4]   = '0;
              assign r_credit_in[curr][PORT_E4] = '0;
            end

          end
        end
      end
    end
  endgenerate

endmodule
