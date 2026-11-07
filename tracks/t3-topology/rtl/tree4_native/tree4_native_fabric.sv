`default_nettype none

// Canonical Tree4: roots 0..3, middles 4..11, leaves 12..27.
// Leaf seat t%4 attaches terminal t to router 12+t/4. Each accepted flit is
// one complete packet. The network retains the physical redundant parent
// links and legal upward choices; routing deterministically selects one legal
// choice (lowest numbered port) for this synthesizable slice.
module tree4_native_fabric #(
  parameter int DATA_W=32,
  parameter int TERM_W=6
)(
  input logic clk, rst,
  input logic [63:0] inject_valid,
  output logic [63:0] inject_ready,
  input logic [63:0][DATA_W-1:0] inject_data,
  input logic [63:0][TERM_W-1:0] inject_dest,
  output logic [63:0] eject_valid,
  input logic [63:0] eject_ready,
  output logic [63:0][DATA_W-1:0] eject_data
);
  localparam int ROUTERS=28;
  logic [ROUTERS-1:0][7:0] iv,ir,ov,ordy;
  logic [ROUTERS-1:0][7:0][DATA_W-1:0] idata,odata;
  logic [ROUTERS-1:0][7:0][TERM_W-1:0] idest,odest;

  for (genvar r=0;r<ROUTERS;r++) begin: routers
    localparam int LEVEL=(r<4)?0:((r<12)?1:2);
    localparam int POS=(LEVEL==0)?r:((LEVEL==1)?r-4:r-12);
    for (genvar p=0;p<8;p++) begin: ports
      if (LEVEL==0 && p<8) begin: root_down
        localparam int CHILD=4+p;
        localparam int CHILD_UP_PORT=4+r;
        assign iv[r][p]=ov[CHILD][CHILD_UP_PORT];
        assign idata[r][p]=odata[CHILD][CHILD_UP_PORT];
        assign idest[r][p]=odest[CHILD][CHILD_UP_PORT];
        assign ordy[r][p]=ir[CHILD][CHILD_UP_PORT];
      end else if (LEVEL==1 && p<4) begin: middle_down
        localparam int CHILD=12+4*(POS/2)+p;
        assign iv[r][p]=ov[CHILD][4+(POS%2)];
        assign idata[r][p]=odata[CHILD][4+(POS%2)];
        assign idest[r][p]=odest[CHILD][4+(POS%2)];
        assign ordy[r][p]=ir[CHILD][4+(POS%2)];
      end else if (LEVEL==1 && p>=4) begin: middle_up
        localparam int PARENT=p-4;
        localparam int ROOT_DOWN_PORT=POS;
        assign iv[r][p]=ov[PARENT][ROOT_DOWN_PORT];
        assign idata[r][p]=odata[PARENT][ROOT_DOWN_PORT];
        assign idest[r][p]=odest[PARENT][ROOT_DOWN_PORT];
        assign ordy[r][p]=ir[PARENT][ROOT_DOWN_PORT];
      end else if (LEVEL==2 && p>=4 && p<6) begin: leaf_up
        localparam int PARENT=4+2*(POS/4)+(p-4);
        assign iv[r][p]=ov[PARENT][POS%4];
        assign idata[r][p]=odata[PARENT][POS%4];
        assign idest[r][p]=odest[PARENT][POS%4];
        assign ordy[r][p]=ir[PARENT][POS%4];
      end else if (LEVEL==2 && p<4) begin: seats
        localparam int T=4*POS+p;
        assign iv[r][p]=inject_valid[T];
        assign idata[r][p]=inject_data[T];
        assign idest[r][p]=inject_dest[T];
        assign inject_ready[T]=ir[r][p];
        assign ordy[r][p]=eject_ready[T];
        assign eject_valid[T]=ov[r][p];
        assign eject_data[T]=odata[r][p];
      end else begin: unused
        assign iv[r][p]=1'b0;
        assign idata[r][p]='0;
        assign idest[r][p]='0;
        assign ordy[r][p]=1'b0;
      end
    end
    tree4_native_router #(.DATA_W(DATA_W),.TERM_W(TERM_W),.LEVEL(LEVEL),.POS(POS)) u_router(
      .clk,.rst,.in_valid(iv[r]),.in_ready(ir[r]),.in_data(idata[r]),.in_dest(idest[r]),
      .out_valid(ov[r]),.out_ready(ordy[r]),.out_data(odata[r]),.out_dest(odest[r]));
  end
endmodule

module tree4_native_router #(
  parameter int DATA_W=32, TERM_W=6, LEVEL=0, POS=0
)(
  input logic clk,rst,
  input logic [7:0] in_valid,
  output logic [7:0] in_ready,
  input logic [7:0][DATA_W-1:0] in_data,
  input logic [7:0][TERM_W-1:0] in_dest,
  output logic [7:0] out_valid,
  input logic [7:0] out_ready,
  output logic [7:0][DATA_W-1:0] out_data,
  output logic [7:0][TERM_W-1:0] out_dest
);
  logic [7:0] valid_q;
  logic [7:0][DATA_W-1:0] data_q;
  logic [7:0][TERM_W-1:0] dest_q;
  logic [7:0][2:0] route_q;
  logic [3:0] rr[0:7];
  logic [7:0] req[0:7], grant[0:7];

  function automatic int route_port(input int input_port,input int destination);
    int group_id, leaf_id;
    begin
      group_id=destination/16;
      leaf_id=destination/4;
      if (LEVEL==0) route_port=2*group_id + ((input_port+destination)%2);
      else if (LEVEL==1) begin
        if (group_id==POS/2) route_port=(destination/4)-(4*(POS/2));
        else route_port=4 + ((input_port+destination)%4);
      end else begin
        if (leaf_id==POS) route_port=destination%4;
        else route_port=4 + ((input_port+destination)%2);
      end
    end
  endfunction

  always_comb begin
    int candidate;
    for (int i=0;i<8;i++) in_ready[i]=!valid_q[i];
    for (int j=0;j<8;j++) begin req[j]='0; grant[j]='0; end
    out_valid='0; out_data='0; out_dest='0;
    for (int i=0;i<8;i++) if (valid_q[i]) req[route_q[i]][i]=1'b1;
    for (int j=0;j<8;j++) begin
      for (int step=0;step<8;step++) begin
        candidate=(int'(rr[j])+step)%8;
        if (req[j][candidate] && !(|grant[j])) grant[j][candidate]=1'b1;
      end
      for (int i=0;i<8;i++) if (grant[j][i]) begin
        out_valid[j]=1'b1; out_data[j]=data_q[i]; out_dest[j]=dest_q[i];
      end
    end
  end

  always_ff @(posedge clk) begin
    if (rst) begin valid_q<='0; for(int j=0;j<8;j++) rr[j]<=0; end
    else begin
      for(int j=0;j<8;j++) for(int i=0;i<8;i++) if(grant[j][i]&&out_ready[j]) begin
        valid_q[i]<=1'b0; rr[j]<=i[2:0]+3'd1;
      end
      for(int i=0;i<8;i++) if(in_valid[i]&&in_ready[i]) begin
        valid_q[i]<=1'b1; data_q[i]<=in_data[i]; dest_q[i]<=in_dest[i];
        route_q[i]<=route_port(i,int'(in_dest[i]));
      end
    end
  end
endmodule
`default_nettype wire
