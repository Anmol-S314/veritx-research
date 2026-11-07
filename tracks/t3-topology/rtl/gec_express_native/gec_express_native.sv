`default_nettype none

// Single-flit GEC Express prototype. KxK grid, C terminals/router.
// Express outputs are grouped exactly as BookSim GEC: local terminals,
// ascending peers in this row, then ascending peers in this column.
module gec_express_native_router #(
  parameter int K=4, C=1, N=K*K, VCS=2, DATA_W=32,
  parameter int ID_W=$clog2(N*C), ROUTER_ID=0, DEG=C+2*(K-1)
)(
  input logic clk, rst,
  input logic [DEG-1:0] in_valid,
  output logic [DEG-1:0][VCS-1:0] in_ready,
  input logic [DEG-1:0][DATA_W-1:0] in_data,
  input logic [DEG-1:0][ID_W-1:0] in_dest,
  input logic [DEG-1:0] in_vc,
  output logic [DEG-1:0] out_valid,
  input logic [DEG-1:0][VCS-1:0] out_ready,
  output logic [DEG-1:0][DATA_W-1:0] out_data,
  output logic [DEG-1:0][ID_W-1:0] out_dest,
  output logic [DEG-1:0] out_vc
);
  localparam int INPUTS=DEG*VCS;
  logic [DEG-1:0][VCS-1:0] valid_q;
  logic [DEG-1:0][VCS-1:0][DATA_W-1:0] data_q;
  logic [DEG-1:0][VCS-1:0][ID_W-1:0] dest_q;
  logic [DEG-1:0][VCS-1:0] vc_q;
  logic [INPUTS-1:0] req[0:DEG-1], grant[0:DEG-1];
  logic [3:0] winner[0:DEG-1];
  logic [3:0] rr[0:DEG-1];
  logic [DEG-1:0] route_port[0:DEG-1][0:INPUTS-1];

  always_comb begin : route_and_arbitrate
    int dx,dy,dest_router,peer_idx,cand;
    dx=0; dy=0; dest_router=0; peer_idx=0; cand=0;
    for (int o=0;o<DEG;o++) begin
      req[o]='0; grant[o]='0; winner[o]='0;
      for (int i=0;i<DEG;i++) for (int v=0;v<VCS;v++) begin
        cand=i*VCS+v;
        route_port[o][cand]='0;
        if(valid_q[i][v]) begin
          dest_router=int'(dest_q[i][v])/C;
          dx=dest_router%K;
          dy=dest_router/K;
          if(dest_router==ROUTER_ID) route_port[o][cand]=DEG'(int'(dest_q[i][v])%C);
          else if((ROUTER_ID%K)!=dx) begin
            peer_idx=(dx<(ROUTER_ID%K))?dx:dx-1;
            route_port[o][cand]=DEG'(C+peer_idx);
          end else begin
            peer_idx=(dy<(ROUTER_ID/K))?dy:dy-1;
            route_port[o][cand]=DEG'(C+(K-1)+peer_idx);
          end
          if(int'(route_port[o][cand])==o) req[o][cand]=1'b1;
        end
      end
      for(int s=0;s<INPUTS;s++) begin
        cand=(int'(rr[o])+s)%INPUTS;
        if(grant[o]=='0 && req[o][cand] && out_ready[o][vc_q[cand/VCS][cand%VCS]]) begin
          grant[o][cand]=1'b1;
          winner[o]=cand[3:0];
        end
      end
    end
    out_valid='0; out_data='0; out_dest='0; out_vc='0;
    in_ready='0;
    for(int i=0;i<DEG;i++) for(int v=0;v<VCS;v++)
      in_ready[i][v]=!valid_q[i][v];
    for(int o=0;o<DEG;o++) for(int c=0;c<INPUTS;c++) if(grant[o][c]) begin
      out_valid[o]=1'b1;
      out_data[o]=data_q[c/VCS][c%VCS];
      out_dest[o]=dest_q[c/VCS][c%VCS];
      out_vc[o]=vc_q[c/VCS][c%VCS];
    end
  end

  always_ff @(posedge clk) begin
    if(rst) begin
      valid_q<='0;
      for(int o=0;o<DEG;o++) rr[o]<=0;
    end else begin
      for(int o=0;o<DEG;o++) for(int c=0;c<INPUTS;c++) if(grant[o][c]) begin
        valid_q[c/VCS][c%VCS]<=1'b0;
        rr[o]<=winner[o]+1'b1;
      end
      for(int i=0;i<DEG;i++) for(int v=0;v<VCS;v++)
        if(in_valid[i] && in_ready[i][in_vc[i]] && int'(in_vc[i])==v) begin
          valid_q[i][v]<=1'b1; data_q[i][v]<=in_data[i];
          dest_q[i][v]<=in_dest[i]; vc_q[i][v]<=in_vc[i];
        end
    end
  end
endmodule

module gec_express_native_fabric #(
  parameter int K=4,C=1,N=K*K,TERMS=N*C,VCS=2,DATA_W=32,
  parameter int ID_W=$clog2(TERMS), DEG=C+2*(K-1)
)(
  input logic clk,rst,
  input logic [TERMS-1:0] inject_valid,
  output logic [TERMS-1:0] inject_ready,
  input logic [TERMS-1:0][DATA_W-1:0] inject_data,
  input logic [TERMS-1:0][ID_W-1:0] inject_dest,
  input logic [TERMS-1:0] inject_vc,
  output logic [TERMS-1:0] eject_valid,
  input logic [TERMS-1:0] eject_ready,
  output logic [TERMS-1:0][DATA_W-1:0] eject_data
);
  logic [N-1:0][DEG-1:0] iv,ov;
  logic [N-1:0][DEG-1:0][VCS-1:0] ir,ordy;
  logic [N-1:0][DEG-1:0][DATA_W-1:0] idata,odata;
  logic [N-1:0][DEG-1:0][ID_W-1:0] idest,odest;
  logic [N-1:0][DEG-1:0] ivc,ovc;
  for(genvar r=0;r<N;r++) begin: routers
    for(genvar p=0;p<DEG;p++) begin: ports
      if(p<C) begin: local_port
        localparam int TERM=r*C+p;
        assign iv[r][p]=inject_valid[TERM];
        assign idata[r][p]=inject_data[TERM];
        assign idest[r][p]=inject_dest[TERM];
        assign ivc[r][p]=inject_vc[TERM];
        assign ordy[r][p]={VCS{eject_ready[TERM]}};
        assign inject_ready[TERM]=ir[r][p][inject_vc[TERM]];
        assign eject_valid[TERM]=ov[r][p];
        assign eject_data[TERM]=odata[r][p];
      end else begin: express_port
        localparam int E=p-C;
        if(E<K-1) begin: row_port
          localparam int X=r%K,Y=r/K;
          localparam int PEER=(E<X)?E:E+1;
          localparam int SRC=Y*K+PEER;
          localparam int PEER_INDEX=(X<PEER)?X:X-1;
          localparam int SRC_PORT=C+PEER_INDEX;
          assign iv[r][p]=ov[SRC][SRC_PORT];
          assign idata[r][p]=odata[SRC][SRC_PORT];
          assign idest[r][p]=odest[SRC][SRC_PORT];
          assign ivc[r][p]=ovc[SRC][SRC_PORT];
          assign ordy[SRC][SRC_PORT]=ir[r][p];
        end else begin: col_port
          localparam int Y=r/K,X=r%K,CE=E-(K-1);
          localparam int PEER=(CE<Y)?CE:CE+1;
          localparam int SRC=PEER*K+X;
          localparam int PEER_INDEX=(Y<PEER)?Y:Y-1;
          localparam int SRC_PORT=C+(K-1)+PEER_INDEX;
          assign iv[r][p]=ov[SRC][SRC_PORT];
          assign idata[r][p]=odata[SRC][SRC_PORT];
          assign idest[r][p]=odest[SRC][SRC_PORT];
          assign ivc[r][p]=ovc[SRC][SRC_PORT];
          assign ordy[SRC][SRC_PORT]=ir[r][p];
        end
      end
    end
    gec_express_native_router #(.K(K),.C(C),.N(N),.VCS(VCS),.DATA_W(DATA_W),.ID_W(ID_W),.ROUTER_ID(r)) u_router(
      .clk,.rst,.in_valid(iv[r]),.in_ready(ir[r]),.in_data(idata[r]),.in_dest(idest[r]),.in_vc(ivc[r]),
      .out_valid(ov[r]),.out_ready(ordy[r]),.out_data(odata[r]),.out_dest(odest[r]),.out_vc(ovc[r]));
  end
endmodule
`default_nettype wire
