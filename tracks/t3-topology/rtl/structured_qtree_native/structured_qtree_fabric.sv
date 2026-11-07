`default_nettype none
// Structured-family qtree: breadth-first k=4, tiers=2 tree, 21 routers.
// Unlike qtree_native, each router has one local terminal, ID == router ID.
// Each accepted flit is one complete packet; no multi-flit framing is claimed.
module structured_qtree_fabric #(parameter int ROUTERS=21, DATA_W=32, ID_W=$clog2(ROUTERS))(
 input logic clk,rst,
 input logic [ROUTERS-1:0] inject_valid,
 output logic [ROUTERS-1:0] inject_ready,
 input logic [ROUTERS-1:0][DATA_W-1:0] inject_data,
 input logic [ROUTERS-1:0][ID_W-1:0] inject_dest,
 output logic [ROUTERS-1:0] eject_valid,
 input logic [ROUTERS-1:0] eject_ready,
 output logic [ROUTERS-1:0][DATA_W-1:0] eject_data
);
 logic [ROUTERS-1:0][5:0] iv,ir,ov,ordy;
 logic [ROUTERS-1:0][5:0][DATA_W-1:0] idata,odata;
 logic [ROUTERS-1:0][5:0][ID_W-1:0] idest,odest;
 for(genvar r=0;r<ROUTERS;r++) begin: router_gen
  for(genvar p=0;p<6;p++) begin: port_gen
   if(r<5 && p<4) begin: child_link
    localparam int CHILD=4*r+1+p;
    assign iv[r][p]=ov[CHILD][4]; assign idata[r][p]=odata[CHILD][4];
    assign idest[r][p]=odest[CHILD][4]; assign ordy[r][p]=ir[CHILD][4];
   end else if(r>0 && p==4) begin: parent_link
    localparam int PARENT=(r-1)/4, CP=(r-1)%4;
    assign iv[r][p]=ov[PARENT][CP]; assign idata[r][p]=odata[PARENT][CP];
    assign idest[r][p]=odest[PARENT][CP]; assign ordy[r][p]=ir[PARENT][CP];
   end else if(p==5) begin: endpoint
    assign iv[r][p]=inject_valid[r]; assign idata[r][p]=inject_data[r];
    assign idest[r][p]=inject_dest[r]; assign ordy[r][p]=eject_ready[r];
    assign inject_ready[r]=ir[r][p]; assign eject_valid[r]=ov[r][p];
    assign eject_data[r]=odata[r][p];
   end else begin: unused_port
    assign iv[r][p]=0; assign idata[r][p]='0; assign idest[r][p]='0; assign ordy[r][p]=0;
   end
  end
  structured_qtree_router #(.ID_W(ID_W),.DATA_W(DATA_W),.ROUTER_ID(r)) u_router(
   .clk,.rst,.in_valid(iv[r]),.in_ready(ir[r]),.in_data(idata[r]),.in_dest(idest[r]),
   .out_valid(ov[r]),.out_ready(ordy[r]),.out_data(odata[r]),.out_dest(odest[r]));
 end
endmodule

module structured_qtree_router #(parameter int ID_W=5,DATA_W=32,ROUTER_ID=0)(
 input logic clk,rst, input logic [5:0] in_valid, output logic [5:0] in_ready,
 input logic [5:0][DATA_W-1:0] in_data, input logic [5:0][ID_W-1:0] in_dest,
 output logic [5:0] out_valid, input logic [5:0] out_ready,
 output logic [5:0][DATA_W-1:0] out_data, output logic [5:0][ID_W-1:0] out_dest
);
 logic [5:0] valid_q;
 logic [5:0][DATA_W-1:0] data_q;
 logic [5:0][ID_W-1:0] dest_q;
 logic [5:0][5:0] grant;
 logic [5:0] req[0:5];
 logic [5:0] route[0:5];
 logic [2:0] rr[0:5];
 always_comb begin
  int d,candidate,cursor,parent;
  grant='0; out_valid='0; out_data='0; out_dest='0; in_ready=~valid_q;
  for(int o=0;o<6;o++) req[o]='0;
  d=0; candidate=0; cursor=0; parent=0;
  for(int i=0;i<6;i++) begin
   route[i]=5; d=int'(dest_q[i]);
   if(d!=ROUTER_ID) begin
    cursor=d;
    while(cursor>ROUTER_ID) begin
     parent=(cursor-1)/4;
     if(parent==ROUTER_ID) begin
      route[i]=cursor-1-4*ROUTER_ID;
      cursor=ROUTER_ID;
     end else cursor=parent;
    end
    if(cursor!=ROUTER_ID) route[i]=4;
   end
  end
  for(int o=0;o<6;o++) begin
   for(int i=0;i<6;i++) if(valid_q[i] && route[i]==o) req[o][i]=1'b1;
  end
  for(int o=0;o<6;o++) begin
   for(int step=0;step<6;step++) begin
    candidate=(int'(rr[o])+step)%6;
    if(!( | grant[o]) && req[o][candidate]) begin
     grant[o][candidate]=1; out_valid[o]=1; out_data[o]=data_q[candidate]; out_dest[o]=dest_q[candidate];
    end
   end
  end
 end
 always_ff @(posedge clk) begin
  if(rst) begin valid_q<='0; for(int o=0;o<6;o++) rr[o]<=0; end
  else begin
   for(int o=0;o<6;o++) for(int i=0;i<6;i++) if(grant[o][i] && out_ready[o]) begin
    valid_q[i]<=0; rr[o]<=((i+1)%6);
   end
   for(int i=0;i<6;i++) if(in_valid[i] && in_ready[i]) begin
    valid_q[i]<=1; data_q[i]<=in_data[i]; dest_q[i]<=in_dest[i];
   end
  end
 end
endmodule
`default_nettype wire
