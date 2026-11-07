`timescale 1ns/1ps
`default_nettype none

// Single-flit complete-packet router for canonical fattree16_anynet.
// Inputs 0..3 are terminal injection lanes at edge routers. Inputs 4..7 are
// transit lanes, indexed by the neighboring lower-tier router. Outputs 0..3
// are transit lanes (edge: upper-router index; upper: destination edge index).
// Outputs 4..7 are terminal ejection lanes at edge routers. Upper routers have
// no terminal endpoints. This is a one-entry-per-input, single-flit prototype,
// not the project's multi-flit packet / multi-VC router contract.
module fattree16_router #(parameter int ID=0, DATA_W=32, DEST_W=4)(
  input logic clk, rst,
  input logic [7:0] in_valid,
  output logic [7:0] in_ready,
  input logic [7:0][DATA_W-1:0] in_data,
  input logic [7:0][DEST_W-1:0] in_dest,
  output logic [7:0] out_valid,
  input logic [7:0] out_ready,
  output logic [7:0][DATA_W-1:0] out_data,
  output logic [7:0][DEST_W-1:0] out_dest
);
  logic [7:0] valid_q;
  logic [7:0][DATA_W-1:0] data_q;
  logic [7:0][DEST_W-1:0] dest_q;
  logic [7:0][7:0] request, grant;
  logic [2:0] rr [0:7];

  function automatic int route_port(input int dst);
    int leaf, dst_leaf;
    begin
      route_port = 0;
      leaf = (ID < 4) ? ID : -1;
      dst_leaf = dst / 4;
      if (ID < 4) begin
        if (leaf == dst_leaf) route_port = 4 + (dst % 4);
        else route_port = (leaf + dst_leaf) % 4;
      end else route_port = dst_leaf;
    end
  endfunction

  always_comb begin
    request = '0;
    grant = '0;
    out_valid = '0;
    out_data = '0;
    out_dest = '0;
    in_ready = '0;
    for (int i=0; i<8; i++) begin
      int p;
      p = 0;
      if (!valid_q[i]) in_ready[i] = 1'b1;
      if (valid_q[i]) begin
        p = route_port(int'(dest_q[i]));
        if (p >= 0 && p < 8) request[p][i] = 1'b1;
      end
    end
    for (int o=0; o<8; o++) begin
      for (int step=0; step<8; step++) begin
        if ((grant[o] == '0) && request[o][(int'(rr[o]) + step) % 8]) begin
          grant[o][(int'(rr[o]) + step) % 8] = 1'b1;
          out_valid[o] = 1'b1;
          out_data[o] = data_q[(int'(rr[o]) + step) % 8];
          out_dest[o] = dest_q[(int'(rr[o]) + step) % 8];
        end
      end
    end
  end

  always_ff @(posedge clk) begin
    if (rst) begin
      valid_q <= '0;
      for (int o=0; o<8; o++) rr[o] <= '0;
    end else begin
      for (int o=0; o<8; o++) begin
        for (int i=0; i<8; i++) begin
          if (grant[o][i] && out_ready[o]) begin
            valid_q[i] <= 1'b0;
            rr[o] <= 3'((i+1)%8);
          end
        end
      end
      for (int i=0; i<8; i++) begin
        if (in_valid[i] && in_ready[i]) begin
          valid_q[i] <= 1'b1;
          data_q[i] <= in_data[i];
          dest_q[i] <= in_dest[i];
        end
      end
    end
  end
endmodule

module fattree16_native_fabric #(parameter int TERMINALS=16, DATA_W=32, DEST_W=4)(
  input logic clk, rst,
  input logic [TERMINALS-1:0] inject_valid,
  output logic [TERMINALS-1:0] inject_ready,
  input logic [TERMINALS-1:0][DATA_W-1:0] inject_data,
  input logic [TERMINALS-1:0][DEST_W-1:0] inject_dest,
  output logic [TERMINALS-1:0] eject_valid,
  input logic [TERMINALS-1:0] eject_ready,
  output logic [TERMINALS-1:0][DATA_W-1:0] eject_data
);
  logic [7:0][7:0] iv, ir, ov, ordy;
  logic [7:0][7:0][DATA_W-1:0] idata, odata;
  logic [7:0][7:0][DEST_W-1:0] idest, odest;

  // Canonical graph law: edge l connects to upper 4+((l+j)%4).
  // The edge's transit output j reaches that upper router's input lane 4+l.
  // Upper output l returns to edge l, using that link's matching input lane.
  for (genvar l=0; l<4; l++) begin: edge_core
    for (genvar j=0; j<4; j++) begin: link
      localparam int U = 4 + ((l+j)%4);
      localparam int EDGE_INPUT = 4+j;
      assign iv[l][EDGE_INPUT] = ov[U][l];
      assign idata[l][EDGE_INPUT] = odata[U][l];
      assign idest[l][EDGE_INPUT] = odest[U][l];
      assign ordy[U][l] = ir[l][EDGE_INPUT];
      // Upper-router transit input lanes are indexed by the source edge
      // router, not by the edge router's local upper-link output port.
      assign iv[U][4+l] = ov[l][j];
      assign idata[U][4+l] = odata[l][j];
      assign idest[U][4+l] = odest[l][j];
      assign ordy[l][j] = ir[U][4+l];
    end
  end

  for (genvar l=0; l<4; l++) begin: terminal
    for (genvar s=0; s<4; s++) begin: seat
      localparam int T = l*4+s;
      assign iv[l][s] = inject_valid[T];
      assign idata[l][s] = inject_data[T];
      assign idest[l][s] = inject_dest[T];
      assign inject_ready[T] = ir[l][s];
      assign eject_valid[T] = ov[l][4+s];
      assign eject_data[T] = odata[l][4+s];
      assign ordy[l][4+s] = eject_ready[T];
    end
  end

  for (genvar u=4; u<8; u++) begin: upper_unused
    for (genvar s=0; s<4; s++) begin: terminal_inputs
      assign iv[u][s] = 1'b0;
      assign idata[u][s] = '0;
      assign idest[u][s] = '0;
    end
    for (genvar p=4; p<8; p++) begin: terminal_outputs
      assign ordy[u][p] = 1'b0;
    end
  end

  for (genvar r=0; r<8; r++) begin: routers
    fattree16_router #(.ID(r), .DATA_W(DATA_W), .DEST_W(DEST_W)) u_router(
      .clk, .rst, .in_valid(iv[r]), .in_ready(ir[r]), .in_data(idata[r]),
      .in_dest(idest[r]), .out_valid(ov[r]), .out_ready(ordy[r]),
      .out_data(odata[r]), .out_dest(odest[r]));
  end
endmodule
`default_nettype wire
