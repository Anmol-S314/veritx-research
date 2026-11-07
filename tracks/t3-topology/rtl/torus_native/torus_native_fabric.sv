`default_nettype none

// Single-flit packet torus. Router id r has coordinates (r%K,r/K).
// Ports are +x, -x, +y, -y, local in that order. Each physical input has
// one slot for each of the two dateline VCs.
module torus_native_router #(
  parameter int K=5, N=K*K, ID_W=$clog2(N), DATA_W=32, NODE_ID=0
)(
  input logic clk, rst,
  input logic [4:0] in_valid,
  output logic [4:0][1:0] in_ready,
  input logic [4:0][DATA_W-1:0] in_data,
  input logic [4:0][ID_W-1:0] in_dest,
  input logic [4:0] in_vc,
  output logic [4:0] out_valid,
  input logic [4:0][1:0] out_ready,
  output logic [4:0][DATA_W-1:0] out_data,
  output logic [4:0][ID_W-1:0] out_dest,
  output logic [4:0] out_vc
);
  logic [4:0][1:0] valid_q;
  logic [4:0][1:0][DATA_W-1:0] data_q;
  logic [4:0][1:0][ID_W-1:0] dest_q;
  logic [2:0] rr[0:4];
  logic [9:0] req[0:4];
  logic [9:0] grant[0:4];
  logic [3:0] winner[0:4];
  logic [4:0] route_port[0:4][0:9];
  logic [4:0] route_vc[0:4][0:9];

  always_comb begin
    int x,y,dx,dy,fx,bx,fy,by,o,candidate,step;
    for (int oi=0;oi<5;oi++) begin
      o=oi; req[o]='0; winner[o]='0;
      for (int ii=0;ii<5;ii++) for (int v=0;v<2;v++) begin
        candidate=ii*2+v; route_port[o][candidate]=0; route_vc[o][candidate]=v[0];
        if (valid_q[ii][v]) begin
          x=NODE_ID%K; y=NODE_ID/K;
          dx=int'(dest_q[ii][v])%K; dy=int'(dest_q[ii][v])/K;
          fx=(dx-x+K)%K; bx=(x-dx+K)%K;
          fy=(dy-y+K)%K; by=(y-dy+K)%K;
          if (int'(dest_q[ii][v])==NODE_ID) begin route_port[o][candidate]=4; end
          else if (x!=dx) begin
            route_port[o][candidate]=(fx<=bx)?0:1;
            route_vc[o][candidate]=v[0] || ((fx<=bx) ? (x==K-1) : (x==0));
          end else begin
            route_port[o][candidate]=(fy<=by)?2:3;
            route_vc[o][candidate]=v[0] || ((fy<=by) ? (y==K-1) : (y==0));
          end
          if (route_port[o][candidate]==o) req[o][candidate]=1'b1;
        end
      end
      grant[o]='0;
      for (int s=0;s<10;s++) begin
        step=s; candidate=(int'(rr[o])+step)%10;
        if (grant[o]=='0 && req[o][candidate] && out_ready[o][route_vc[o][candidate]]) begin
          grant[o][candidate]=1'b1; winner[o]=candidate[3:0];
        end
      end
    end
    out_valid='0; out_data='0; out_dest='0; out_vc='0;
    for (int op=0;op<5;op++) for (int c=0;c<10;c++) if (grant[op][c]) begin
      out_valid[op]=1'b1; out_data[op]=data_q[c/2][c%2];
      begin
        out_dest[op]=dest_q[c/2][c%2];
        out_vc[op]=route_vc[op][c];
      end
    end
    in_ready='0;
    for (int i=0;i<5;i++) for (int v=0;v<2;v++) in_ready[i][v]=!valid_q[i][v];
  end

  always_ff @(posedge clk) begin
    if (rst) begin
      valid_q<='0;
      for (int o=0;o<5;o++) rr[o]<=0;
    end else begin
      for (int o=0;o<5;o++) for (int c=0;c<10;c++) if (grant[o][c] && out_ready[o][route_vc[o][c]]) begin
        valid_q[c/2][c%2]<=1'b0; rr[o]<=winner[o]+1'b1;
      end
      for (int i=0;i<5;i++) if (in_valid[i] && in_ready[i][in_vc[i]]) begin
        valid_q[i][in_vc[i]]<=1'b1; data_q[i][in_vc[i]]<=in_data[i]; dest_q[i][in_vc[i]]<=in_dest[i];
      end
    end
  end
endmodule

module torus_native_fabric #(
  parameter int K=5, N=K*K, DATA_W=32, ID_W=$clog2(N)
)(
  input logic clk,rst,
  input logic [N-1:0] inject_valid,
  output logic [N-1:0] inject_ready,
  input logic [N-1:0][DATA_W-1:0] inject_data,
  input logic [N-1:0][ID_W-1:0] inject_dest,
  input logic [N-1:0] inject_vc,
  output logic [N-1:0] eject_valid,
  input logic [N-1:0] eject_ready,
  output logic [N-1:0][DATA_W-1:0] eject_data
);
  logic [N-1:0][4:0] iv,ov,ivc,ovc;
  logic [N-1:0][4:0][1:0] ir,ordy;
  logic [N-1:0][4:0][DATA_W-1:0] idata,odata;
  logic [N-1:0][4:0][ID_W-1:0] idest,odest;
  for (genvar r=0;r<N;r++) begin: routers
    localparam int X=r%K, Y=r/K;
    localparam int XP=Y*K+(X+1)%K, XM=Y*K+(X+K-1)%K;
    localparam int YP=((Y+1)%K)*K+X, YM=((Y+K-1)%K)*K+X;
    assign iv[r][0]=ov[XM][0]; assign idata[r][0]=odata[XM][0]; assign idest[r][0]=odest[XM][0]; assign ivc[r][0]=ovc[XM][0];
    assign iv[r][1]=ov[XP][1]; assign idata[r][1]=odata[XP][1]; assign idest[r][1]=odest[XP][1]; assign ivc[r][1]=ovc[XP][1];
    assign iv[r][2]=ov[YM][2]; assign idata[r][2]=odata[YM][2]; assign idest[r][2]=odest[YM][2]; assign ivc[r][2]=ovc[YM][2];
    assign iv[r][3]=ov[YP][3]; assign idata[r][3]=odata[YP][3]; assign idest[r][3]=odest[YP][3]; assign ivc[r][3]=ovc[YP][3];
    assign iv[r][4]=inject_valid[r]; assign idata[r][4]=inject_data[r]; assign idest[r][4]=inject_dest[r]; assign ivc[r][4]=inject_vc[r];
    assign ordy[r][0]=ir[XP][0]; assign ordy[r][1]=ir[XM][1]; assign ordy[r][2]=ir[YP][2]; assign ordy[r][3]=ir[YM][3];
    assign ordy[r][4]={2{eject_ready[r]}};
    assign inject_ready[r]=ir[r][4][inject_vc[r]];
    assign eject_valid[r]=ov[r][4]; assign eject_data[r]=odata[r][4];
    torus_native_router #(.K(K),.N(N),.DATA_W(DATA_W),.ID_W(ID_W),.NODE_ID(r)) u_router(
      .clk,.rst,.in_valid(iv[r]),.in_ready(ir[r]),.in_data(idata[r]),.in_dest(idest[r]),.in_vc(ivc[r]),
      .out_valid(ov[r]),.out_ready(ordy[r]),.out_data(odata[r]),.out_dest(odest[r]),.out_vc(ovc[r]));
  end
endmodule
`default_nettype wire
