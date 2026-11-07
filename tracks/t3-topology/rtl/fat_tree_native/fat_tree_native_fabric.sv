`timescale 1ns/1ps
`default_nettype none

// Canonical fat_tree4 from application/presets.py: radix=2, tiers=2,
// 4 routers, 4 terminals, 2 terminal seats/router. Canonical links: lower
// router 0->{2,3}, 1->{3,2}; endpoints router-major/seat-major: 0,1 at
// router 0 and 2,3 at router 1. One accepted item is one full flit only.
// Packet framing, multi-flit wormhole semantics, VCs, and full simulator
// packet/VC compatibility are explicitly not implemented.
module fat_tree_native_fabric #(
  parameter int TERMINALS=4, DATA_W=32, TERM_W=$clog2(TERMINALS)
)(
  input logic clk,rst,
  input logic [TERMINALS-1:0] inject_valid,
  output logic [TERMINALS-1:0] inject_ready,
  input logic [TERMINALS-1:0][DATA_W-1:0] inject_data,
  input logic [TERMINALS-1:0][TERM_W-1:0] inject_dest,
  output logic [TERMINALS-1:0] eject_valid,
  input logic [TERMINALS-1:0] eject_ready,
  output logic [TERMINALS-1:0][DATA_W-1:0] eject_data
);
  logic [3:0][3:0] iv,ir,ov,ordy;
  logic [3:0][3:0][DATA_W-1:0] idata,odata;
  logic [3:0][3:0][TERM_W-1:0] idest,odest;

  // Two independent ready/valid channels per physical edge, one per direction.
  for(genvar l=0;l<2;l++) begin: lower_router
    for(genvar u=0;u<2;u++) begin: uplink
      localparam int U=2+((l+u)%2), LP=2+((l+u)%2), UP=2+l;
      assign iv[l][LP]=ov[U][UP];
      assign idata[l][LP]=odata[U][UP];
      assign idest[l][LP]=odest[U][UP];
      assign ordy[l][LP]=ir[U][UP];
      assign iv[U][UP]=ov[l][LP];
      assign idata[U][UP]=odata[l][LP];
      assign idest[U][UP]=odest[l][LP];
      assign ordy[U][UP]=ir[l][LP];
    end
  end

  for(genvar r=0;r<4;r++) begin: routers
    for(genvar p=0;p<4;p++) begin: ports
      if(r<2 && p<2) begin: terminal
        localparam int T=2*r+p;
        assign iv[r][p]=inject_valid[T]; assign idata[r][p]=inject_data[T];
        assign idest[r][p]=inject_dest[T]; assign ordy[r][p]=eject_ready[T];
        assign inject_ready[T]=ir[r][p]; assign eject_valid[T]=ov[r][p];
        assign eject_data[T]=odata[r][p];
      end else if(r>=2 && p<2) begin: unused_seat
        assign iv[r][p]=1'b0; assign idata[r][p]='0; assign idest[r][p]='0;
        assign ordy[r][p]=1'b0;
      end else if(r<2 && p>=2) begin: unused_lower_input
        // Lower transit input slots are supplied by corresponding upper outputs.
        // No tieoff: each slot's input is wired in the corresponding uplink block.
      end
    end
    fat_tree_native_router #(.DATA_W(DATA_W),.TERM_W(TERM_W),.ROUTER_ID(r)) u_router(
      .clk,.rst,.in_valid(iv[r]),.in_ready(ir[r]),.in_data(idata[r]),.in_dest(idest[r]),
      .out_valid(ov[r]),.out_ready(ordy[r]),.out_data(odata[r]),.out_dest(odest[r]));
  end
endmodule

module fat_tree_native_router #(
  parameter int DATA_W=32, TERM_W=2, ROUTER_ID=0
)(
  input logic clk,rst,
  input logic [3:0] in_valid,
  output logic [3:0] in_ready,
  input logic [3:0][DATA_W-1:0] in_data,
  input logic [3:0][TERM_W-1:0] in_dest,
  output logic [3:0] out_valid,
  input logic [3:0] out_ready,
  output logic [3:0][DATA_W-1:0] out_data,
  output logic [3:0][TERM_W-1:0] out_dest
);
  logic [3:0] valid_q;
  logic [3:0][DATA_W-1:0] data_q;
  logic [3:0][TERM_W-1:0] dest_q;
  logic [3:0][3:0] request,grant;
  logic [1:0] rr[0:3];

  function automatic int route_port(input int router_id,input int dst);
    int leaf;
    begin
      leaf=dst/2;
      if(router_id<2) begin
        if(leaf==router_id) route_port=dst%2;
        else route_port=2+leaf;
      end else begin
        // Upper-tier routers have no terminal seats; always descend to the
        // edge router whose index equals the destination leaf index.
        route_port=2+leaf;
      end
    end
  endfunction

  always_comb begin
    request='0; grant='0; out_valid='0; out_data='0; out_dest='0;
    for(int i=0;i<4;i++) if(valid_q[i]) request[route_port(ROUTER_ID,int'(dest_q[i]))][i]=1'b1;
    for(int o=0;o<4;o++) begin
      for(int step=0;step<4;step++) begin
        int candidate;
        candidate=(int'(rr[o])+step)%4;
        if(request[o][candidate] && !(|grant[o])) begin
          grant[o][candidate]=1'b1; out_valid[o]=1'b1;
          out_data[o]=data_q[candidate]; out_dest[o]=dest_q[candidate];
        end
      end
    end
    for(int i=0;i<4;i++) in_ready[i]=!valid_q[i];
  end

  always_ff @(posedge clk) begin
    if(rst) begin
      valid_q<='0;
      for(int o=0;o<4;o++) rr[o]<='0;
    end else begin
      for(int o=0;o<4;o++) for(int i=0;i<4;i++) if(grant[o][i] && out_ready[o]) begin
        valid_q[i]<=1'b0; rr[o]<=i[1:0]+2'd1;
      end
      for(int i=0;i<4;i++) if(in_valid[i] && in_ready[i]) begin
        valid_q[i]<=1'b1; data_q[i]<=in_data[i]; dest_q[i]<=in_dest[i];
      end
    end
  end
endmodule
`default_nettype wire
