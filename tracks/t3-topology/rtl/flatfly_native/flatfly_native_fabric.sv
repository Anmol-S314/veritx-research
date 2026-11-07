`timescale 1ns/1ps
`default_nettype none

// Canonical flatfly k=4, n=2, concentration=1: six direct dimension links
// and one local terminal per router.
module flatfly_native_router #(
  parameter int DATA_W=32, ROUTER_ID=0
)(
  input logic clk, rst,
  input logic [6:0] in_valid,
  output logic [6:0] in_ready,
  input logic [6:0][DATA_W-1:0] in_data,
  input logic [6:0][3:0] in_dest,
  output logic [6:0] out_valid,
  input logic [6:0] out_ready,
  output logic [6:0][DATA_W-1:0] out_data,
  output logic [6:0][3:0] out_dest
);
  logic [6:0] valid_q;
  logic [6:0][DATA_W-1:0] data_q;
  logic [6:0][3:0] dest_q;
  logic [6:0][2:0] rr;
  logic [6:0] grant_locked;
  logic [6:0][2:0] locked_winner;
  logic [6:0][6:0] request, grant;
  logic [6:0][2:0] winner;

  always_comb begin : route_and_arbitrate
    int x, y, dx, dy, dest_router, port, candidate;
    request='0; grant='0; winner='0;
    x=ROUTER_ID%4; y=ROUTER_ID/4;
    dx=0; dy=0; dest_router=0; port=0; candidate=0;
    for (int i=0;i<7;i++) begin
      if (valid_q[i]) begin
        dest_router=int'(dest_q[i]);
        dx=dest_router%4; dy=dest_router/4;
        if (x!=dx) port=(dx<x)?dx:dx-1;
        else if (y!=dy) port=3+((dy<y)?dy:dy-1);
        else port=6;
        request[port][i]=1'b1;
      end
    end
    for (int o=0;o<7;o++) begin
      if (grant_locked[o]) begin
        grant[o][locked_winner[o]]=1'b1;
        winner[o]=locked_winner[o];
      end else begin
        for (int step=0;step<7;step++) begin
          candidate=(int'(rr[o])+step)%7;
          if (request[o][candidate] && !(|grant[o])) begin
            grant[o][candidate]=1'b1;
            winner[o]=candidate[2:0];
          end
        end
      end
    end
    out_valid='0; out_data='0; out_dest='0;
    for (int o=0;o<7;o++) for (int i=0;i<7;i++) if (grant[o][i]) begin
      out_valid[o]=1'b1; out_data[o]=data_q[i]; out_dest[o]=dest_q[i];
    end
    in_ready=~valid_q;
  end

  always_ff @(posedge clk) begin
    if (rst) begin valid_q<='0; rr<='0; grant_locked<='0; locked_winner<='0; end
    else begin
      for (int o=0;o<7;o++) begin
        if (out_valid[o] && !out_ready[o]) begin
          grant_locked[o]<=1'b1;
          locked_winner[o]<=winner[o];
        end else if (out_valid[o] && out_ready[o]) begin
          grant_locked[o]<=1'b0;
          rr[o]<=winner[o]+3'd1;
        end
      end
      for (int i=0;i<7;i++) begin
        if (valid_q[i]) for (int o=0;o<7;o++)
          if (grant[o][i] && out_ready[o]) begin
            valid_q[i]<=1'b0;
          end
        if (in_valid[i] && in_ready[i]) begin
          valid_q[i]<=1'b1; data_q[i]<=in_data[i]; dest_q[i]<=in_dest[i];
        end
      end
    end
  end
endmodule

// A clique along each coordinate: every router has direct bidirectional links
// to the other three routers in its x row and y column. Router ID is x+4*y.
module flatfly_native_fabric #(
  parameter int DATA_W=32
)(
  input logic clk, rst,
  input logic [15:0] inject_valid,
  output logic [15:0] inject_ready,
  input logic [15:0][DATA_W-1:0] inject_data,
  input logic [15:0][3:0] inject_dest,
  output logic [15:0] eject_valid,
  input logic [15:0] eject_ready,
  output logic [15:0][DATA_W-1:0] eject_data
);
  logic [111:0] in_v, in_r, out_v, out_r;
  logic [111:0][DATA_W-1:0] in_d, out_d;
  logic [111:0][3:0] in_dest, out_dest;

  for (genvar r=0;r<16;r++) begin: routers
    localparam int X=r%4, Y=r/4;
    for (genvar p=0;p<6;p++) begin: neighbor_ports
      localparam int DIM=(p<3)?0:1;
      localparam int PEER_INDEX=(p<3)?p:p-3;
      localparam int DIGIT=(DIM==0)?X:Y;
      localparam int PEER=(PEER_INDEX<DIGIT)?PEER_INDEX:PEER_INDEX+1;
      localparam int STRIDE=(DIM==0)?1:4;
      localparam int PEER_ROUTER=r+(PEER-DIGIT)*STRIDE;
      localparam int THEIR_DIGIT=(DIM==0)?(PEER_ROUTER%4):(PEER_ROUTER/4);
      localparam int THEIR_PORT=(DIM==0?0:3)+((DIGIT<THEIR_DIGIT)?DIGIT:DIGIT-1);
      assign in_v[r*7+p]=out_v[PEER_ROUTER*7+THEIR_PORT];
      assign in_d[r*7+p]=out_d[PEER_ROUTER*7+THEIR_PORT];
      assign in_dest[r*7+p]=out_dest[PEER_ROUTER*7+THEIR_PORT];
      assign out_r[r*7+p]=in_r[PEER_ROUTER*7+THEIR_PORT];
    end
    assign in_v[r*7+6]=inject_valid[r];
    assign in_d[r*7+6]=inject_data[r];
    assign in_dest[r*7+6]=inject_dest[r];
    assign inject_ready[r]=in_r[r*7+6];
    assign eject_valid[r]=out_v[r*7+6];
    assign eject_data[r]=out_d[r*7+6];
    assign out_r[r*7+6]=eject_ready[r];
    flatfly_native_router #(.DATA_W(DATA_W),.ROUTER_ID(r)) u_router(
      .clk,.rst,.in_valid(in_v[r*7 +: 7]),.in_ready(in_r[r*7 +: 7]),
      .in_data(in_d[r*7 +: 7]),.in_dest(in_dest[r*7 +: 7]),
      .out_valid(out_v[r*7 +: 7]),.out_ready(out_r[r*7 +: 7]),
      .out_data(out_d[r*7 +: 7]),.out_dest(out_dest[r*7 +: 7]));
  end
endmodule
`default_nettype wire
