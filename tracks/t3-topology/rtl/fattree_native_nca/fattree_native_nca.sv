`timescale 1ns/1ps
`default_nettype none

// Single-flit native k=4,n=2 BookSim FatTree NCA prototype.
// Router IDs 0..3 are top (depth 0); 4..7 are bottom (depth 1).
// Bottom router p has terminal ids 4*p..4*p+3. Bottom output ports
// 0..3 eject locally and ports 4..7 reach top routers 0..3.
// Top output ports 0..3 reach bottom routers 4..7 respectively.
module fattree_native_nca_router #(
  parameter int ID=0, DATA_W=32, DEST_W=4
)(
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
  logic [7:0] lock_valid;
  logic [2:0] lock_input [0:7];

  function automatic int route_port(input int dst);
    int bottom;
    begin
      if (ID < 4) begin
        bottom = dst / 4;
        route_port = bottom;
      end else if ((dst / 4) == (ID - 4)) begin
        route_port = dst % 4;
      end else begin
        // BookSim fattree_nca chooses gK + RandomInt(gK-1), i.e.
        // one of this bottom router's four top-level parent links.
        // This deterministic prototype uses the destination bottom index.
        route_port = 4 + (dst / 4);
      end
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
      p = route_port(int'(dest_q[i]));
      if (!valid_q[i]) in_ready[i] = 1'b1;
      if (valid_q[i] && p >= 0 && p < 8) request[p][i] = 1'b1;
    end
    for (int o=0; o<8; o++) begin
      int idx;
      idx = 0;
      if (lock_valid[o]) begin
        grant[o][lock_input[o]] = 1'b1;
        out_valid[o] = 1'b1;
        out_data[o] = data_q[lock_input[o]];
        out_dest[o] = dest_q[lock_input[o]];
      end else begin
        for (int step=0; step<8; step++) begin
          idx = (int'(rr[o]) + step) % 8;
          if ((grant[o] == '0) && request[o][idx]) begin
            grant[o][idx] = 1'b1;
            out_valid[o] = 1'b1;
            out_data[o] = data_q[idx];
            out_dest[o] = dest_q[idx];
          end
        end
      end
    end
  end

  always_ff @(posedge clk) begin
    if (rst) begin
      valid_q <= '0;
      lock_valid <= '0;
      for (int o=0; o<8; o++) begin
        rr[o] <= '0;
        lock_input[o] <= '0;
      end
    end else begin
      for (int o=0; o<8; o++) begin
        for (int i=0; i<8; i++) begin
          if (grant[o][i] && out_ready[o]) begin
            valid_q[i] <= 1'b0;
            rr[o] <= 3'((i+1)%8);
            lock_valid[o] <= 1'b0;
          end else if (grant[o][i] && !out_ready[o]) begin
            lock_valid[o] <= 1'b1;
            lock_input[o] <= 3'(i);
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

module fattree_native_nca_fabric #(
  parameter int DATA_W=32, DEST_W=4
)(
  input logic clk, rst,
  input logic [15:0] inject_valid,
  output logic [15:0] inject_ready,
  input logic [15:0][DATA_W-1:0] inject_data,
  input logic [15:0][DEST_W-1:0] inject_dest,
  output logic [15:0] eject_valid,
  input logic [15:0] eject_ready,
  output logic [15:0][DATA_W-1:0] eject_data
);
  logic [7:0][7:0] iv, ir, ov, ordy;
  logic [7:0][7:0][DATA_W-1:0] idata, odata;
  logic [7:0][7:0][DEST_W-1:0] idest, odest;

  // Complete bipartite inter-tier graph. Lower router p's upper output
  // 4+u connects to top router u's input 4+p.
  for (genvar p=0; p<4; p++) begin: bottom
    for (genvar u=0; u<4; u++) begin: parent
      assign iv[4+p][4+u] = ov[u][p];
      assign idata[4+p][4+u] = odata[u][p];
      assign idest[4+p][4+u] = odest[u][p];
      assign ordy[u][p] = ir[4+p][4+u];
      assign iv[u][4+p] = ov[4+p][4+u];
      assign idata[u][4+p] = odata[4+p][4+u];
      assign idest[u][4+p] = odest[4+p][4+u];
      assign ordy[4+p][4+u] = ir[u][4+p];
    end
  end

  for (genvar p=0; p<4; p++) begin: terminals
    for (genvar s=0; s<4; s++) begin: seat
      localparam int T = 4*p+s;
      assign iv[4+p][s] = inject_valid[T];
      assign idata[4+p][s] = inject_data[T];
      assign idest[4+p][s] = inject_dest[T];
      assign inject_ready[T] = ir[4+p][s];
      assign eject_valid[T] = ov[4+p][s];
      assign eject_data[T] = odata[4+p][s];
      assign ordy[4+p][s] = eject_ready[T];
    end
  end

  for (genvar r=0; r<8; r++) begin: routers
    // Terminal-facing unused ports at top, and unused downward outputs at
    // bottom, are tied off. Active traffic never requests these ports.
    if (r < 4) begin: top_unused
      for (genvar p=0; p<4; p++) begin: unused_port
        assign iv[r][p] = 1'b0;
        assign idata[r][p] = '0;
        assign idest[r][p] = '0;
        assign ordy[r][4+p] = 1'b0;
      end
    end
    fattree_native_nca_router #(.ID(r), .DATA_W(DATA_W), .DEST_W(DEST_W)) u_router(
      .clk, .rst, .in_valid(iv[r]), .in_ready(ir[r]), .in_data(idata[r]),
      .in_dest(idest[r]), .out_valid(ov[r]), .out_ready(ordy[r]),
      .out_data(odata[r]), .out_dest(odest[r]));
  end
endmodule
`default_nettype wire
