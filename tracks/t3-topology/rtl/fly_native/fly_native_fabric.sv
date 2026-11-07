`timescale 1ns/1ps
`default_nettype none

// Four-ary, three-stage BookSim fly, reduced to a one-flit packet protocol.
// Each physical input has one elastic slot. Fixed destination-tag route, no
// adaptive routing, VCs, packet tails, or multi-flit framing are modeled.
module fly_native_router #(
  parameter int DATA_W=32, TERM_W=6, ROUTER_ID=0
)(
  input logic clk, rst,
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
  logic [3:0][1:0] rr;
  logic [3:0][3:0] request, grant;
  logic [3:0][1:0] winner;

  always_comb begin : route_and_arbitrate
    int stage, addr, dest_router, port, candidate;
    stage=ROUTER_ID/16;
    addr=ROUTER_ID%16;
    dest_router=0; port=-1; candidate=0;
    request='0; grant='0; winner='0;
    for (int i=0;i<4;i++) begin
      if (valid_q[i]) begin
        dest_router=int'(dest_q[i])/4;
        if (stage==0) port=dest_router/4;
        else if (stage==1 && addr/4==dest_router/4) port=dest_router%4;
        else if (stage==2 && addr==dest_router) port=int'(dest_q[i])%4;
        else port=-1;
        if (port>=0 && port<4) request[port][i]=1'b1;
      end
    end
    for (int o=0;o<4;o++) begin
      for (int step=0;step<4;step++) begin
        candidate=(int'(rr[o])+step)%4;
        if (request[o][candidate] && !grant[o][0] && !grant[o][1] &&
            !grant[o][2] && !grant[o][3]) begin
          grant[o][candidate]=1'b1;
          winner[o]=candidate[1:0];
        end
      end
    end
    out_valid='0; out_data='0; out_dest='0;
    for (int o=0;o<4;o++) for (int i=0;i<4;i++) if (grant[o][i]) begin
      out_valid[o]=1'b1; out_data[o]=data_q[i]; out_dest[o]=dest_q[i];
    end
    in_ready=~valid_q;
  end

  always_ff @(posedge clk) begin
    if (rst) begin valid_q<='0; rr<='0; end
    else begin
      for (int i=0;i<4;i++) begin
        if (valid_q[i]) for (int o=0;o<4;o++)
          if (grant[o][i] && out_ready[o]) begin
            valid_q[i]<=1'b0;
            rr[o]<=winner[o]+2'd1;
          end
        if (in_valid[i] && in_ready[i]) begin
          valid_q[i]<=1'b1; data_q[i]<=in_data[i]; dest_q[i]<=in_dest[i];
        end
      end
    end
  end
endmodule

// Fixed 48-router graph and 128 explicit directed interstage ready/valid links.
// Terminals inject at stage-0 router t/4, port t%4; eject at stage-2 router
// 32+t/4, port t%4. These are intentionally different attachment points.
module fly_native_fabric #(
  parameter int DATA_W=32
)(
  input logic clk, rst,
  input logic [63:0] inject_valid,
  output logic [63:0] inject_ready,
  input logic [63:0][DATA_W-1:0] inject_data,
  input logic [63:0][5:0] inject_dest,
  output logic [63:0] eject_valid,
  input logic [63:0] eject_ready,
  output logic [63:0][DATA_W-1:0] eject_data
);
  logic [127:0] link_valid, link_ready;
  logic [127:0][DATA_W-1:0] link_data;
  logic [127:0][5:0] link_dest;
  logic [47:0][3:0] iv, ir, ov, ordy;
  logic [47:0][3:0][DATA_W-1:0] idata, odata;
  logic [47:0][3:0][5:0] idest, odest;

  for (genvar s=0;s<2;s++) begin: stages
    for (genvar a=0;a<16;a++) begin: addresses
      for (genvar p=0;p<4;p++) begin: ports
        localparam int SHIFT=(s==0)?4:1;
        localparam int ZERO=(a/SHIFT)%4;
        localparam int DST_ADDR=a-ZERO*SHIFT+p*SHIFT;
        localparam int SRC_ID=s*16+a;
        localparam int DST_ID=(s+1)*16+DST_ADDR;
        localparam int SRC_PORT=p;
        localparam int DST_PORT=ZERO;
        localparam int LINK=s*64+a*4+p;
        assign link_valid[LINK]=ov[SRC_ID][SRC_PORT];
        assign link_data[LINK]=odata[SRC_ID][SRC_PORT];
        assign link_dest[LINK]=odest[SRC_ID][SRC_PORT];
        assign link_ready[LINK]=ir[DST_ID][DST_PORT];
        assign iv[DST_ID][DST_PORT]=link_valid[LINK];
        assign idata[DST_ID][DST_PORT]=link_data[LINK];
        assign idest[DST_ID][DST_PORT]=link_dest[LINK];
        assign ordy[SRC_ID][SRC_PORT]=link_ready[LINK];
      end
    end
  end
  for (genvar r=0;r<48;r++) begin: router_instances
    localparam int STAGE=r/16;
    for (genvar p=0;p<4;p++) begin: terminal_ports
      if (STAGE==0) begin: ingress_attach
        assign iv[r][p]=inject_valid[r*4+p];
        assign idata[r][p]=inject_data[r*4+p];
        assign idest[r][p]=inject_dest[r*4+p];
        assign inject_ready[r*4+p]=ir[r][p];
      end else if (STAGE==2) begin: egress_attach
        assign ordy[r][p]=eject_ready[(r-32)*4+p];
        assign eject_valid[(r-32)*4+p]=ov[r][p];
        assign eject_data[(r-32)*4+p]=odata[r][p];
      end
    end
    fly_native_router #(.DATA_W(DATA_W),.ROUTER_ID(r)) u_router(
      .clk,.rst,.in_valid(iv[r]),.in_ready(ir[r]),.in_data(idata[r]),
      .in_dest(idest[r]),.out_valid(ov[r]),.out_ready(ordy[r]),
      .out_data(odata[r]),.out_dest(odest[r]));
  end
endmodule
`default_nettype wire
