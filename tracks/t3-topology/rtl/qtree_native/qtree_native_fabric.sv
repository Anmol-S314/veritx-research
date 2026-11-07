`default_nettype none

// Topology-faithful 21-router QTree k=4,n=3 slice. The canonical model has
// 64 terminals (four at every leaf); this RTL slice uses canonical terminal
// IDs 0..15, which occupy ports 0..3 on leaves 5..8. Inter-router ports retain
// canonical order: children 0..3, parent 4.
// Protocol: each accepted injection is one complete, single-flit packet.
// No packet framing, wormhole flow control, or multi-flit behavior is claimed.
module qtree_native_fabric #(
  parameter int TERMINALS = 64,
  parameter int DATA_W = 32,
  parameter int TERM_W = $clog2(TERMINALS)
) (
  input  logic clk,
  input  logic rst,
  input  logic [TERMINALS-1:0] inject_valid,
  output logic [TERMINALS-1:0] inject_ready,
  input  logic [TERMINALS-1:0][DATA_W-1:0] inject_data,
  input  logic [TERMINALS-1:0][TERM_W-1:0] inject_dest,
  output logic [TERMINALS-1:0] eject_valid,
  input  logic [TERMINALS-1:0] eject_ready,
  output logic [TERMINALS-1:0][DATA_W-1:0] eject_data
);
  localparam int ROUTERS=21;
  // [router][port], port 0..3 child direction, port 4 parent direction.
  logic [ROUTERS-1:0][4:0] iv,ir,ov,ordy;
  logic [ROUTERS-1:0][4:0][DATA_W-1:0] idata,odata;
  logic [ROUTERS-1:0][4:0][TERM_W-1:0] idest,odest;
  logic [ROUTERS-1:0][4:0][3:0] i_src_leaf, o_src_leaf;
  logic [ROUTERS-1:0][4:0][TERM_W-1:0] i_dst_leaf, o_dst_leaf;
  logic [ROUTERS-1:0][4:0][3:0] i_next_port, o_next_port;
  logic [ROUTERS-1:0][4:0] i_eject, o_eject;

  for (genvar r=0;r<ROUTERS;r++) begin: routers
    localparam int LEVEL = r < 1 ? 0 : (r < 5 ? 1 : 2);
    localparam int POS = LEVEL == 0 ? 0 : (LEVEL == 1 ? r-1 : r-5);
    for (genvar p=0;p<5;p++) begin: ports
      if (LEVEL < 2 && p < 4) begin: child_link
        localparam int CHILD = LEVEL == 0 ? 1+p : 5+4*POS+p;
        assign iv[r][p]=ov[CHILD][4];
        assign idata[r][p]=odata[CHILD][4];
        assign idest[r][p]=odest[CHILD][4];
        assign i_src_leaf[r][p]=o_src_leaf[CHILD][4];
        assign i_dst_leaf[r][p]=o_dst_leaf[CHILD][4];
        assign i_next_port[r][p]=o_next_port[CHILD][4];
        assign i_eject[r][p]=o_eject[CHILD][4];
        assign ordy[r][p]=ir[CHILD][4];
      end else if (LEVEL > 0 && p == 4) begin: parent_link
        localparam int PARENT = LEVEL == 1 ? 0 : 1+(POS/4);
        assign iv[r][p]=ov[PARENT][POS%4];
        assign idata[r][p]=odata[PARENT][POS%4];
        assign idest[r][p]=odest[PARENT][POS%4];
        assign i_src_leaf[r][p]=o_src_leaf[PARENT][POS%4];
        assign i_dst_leaf[r][p]=o_dst_leaf[PARENT][POS%4];
        assign i_next_port[r][p]=o_next_port[PARENT][POS%4];
        assign i_eject[r][p]=o_eject[PARENT][POS%4];
        assign ordy[r][p]=ir[PARENT][POS%4];
      end else if (LEVEL == 2 && p < 4) begin: terminal_attachment
        // Canonical terminals 0..63 map as leaf 5+terminal/4, seat terminal%4.
        if (POS < 16) begin: selected_terminal
          localparam int T = 4*POS+p;
          assign iv[r][p]=inject_valid[T];
          assign idata[r][p]=inject_data[T];
          assign idest[r][p]=inject_dest[T];
          assign i_src_leaf[r][p]=POS;
          assign i_dst_leaf[r][p]=inject_dest[T];
          assign i_next_port[r][p]=0;
          assign i_eject[r][p]=1'b0;
          assign inject_ready[T]=ir[r][p];
          assign ordy[r][p]=eject_ready[T];
          assign eject_valid[T]=ov[r][p];
          assign eject_data[T]=odata[r][p];
        end else begin: unused_leaf_seat
          assign iv[r][p]=1'b0;
          assign idata[r][p]='0;
          assign idest[r][p]='0;
          assign i_src_leaf[r][p]='0;
          assign i_dst_leaf[r][p]='0;
          assign i_next_port[r][p]='0;
          assign i_eject[r][p]=1'b0;
          assign ordy[r][p]=1'b0;
        end
      end else begin: unused_port
        assign iv[r][p]=1'b0;
        assign idata[r][p]='0;
        assign idest[r][p]='0;
        assign i_src_leaf[r][p]='0;
        assign i_dst_leaf[r][p]='0;
        assign i_next_port[r][p]='0;
        assign i_eject[r][p]=1'b0;
        assign ordy[r][p]=1'b0;
      end
    end

    qtree_native_router #(.DATA_W(DATA_W),.TERM_W(TERM_W),.LEVEL(LEVEL),.POS(POS)) u_router(
      .clk,.rst,.in_valid(iv[r]),.in_ready(ir[r]),.in_data(idata[r]),.in_dest(idest[r]),
      .in_src_leaf(i_src_leaf[r]),.in_dst_leaf(i_dst_leaf[r]),.in_next_port(i_next_port[r]),.in_eject(i_eject[r]),
      .out_valid(ov[r]),.out_ready(ordy[r]),.out_data(odata[r]),.out_dest(odest[r]),
      .out_src_leaf(o_src_leaf[r]),.out_dst_leaf(o_dst_leaf[r]),.out_next_port(o_next_port[r]),.out_eject(o_eject[r]));
  end
endmodule

module qtree_native_router #(
  parameter int DATA_W=32, TERM_W=4, LEVEL=0, POS=0
)(
  input logic clk,rst,
  input logic [4:0] in_valid,
  output logic [4:0] in_ready,
  input logic [4:0][DATA_W-1:0] in_data,
  input logic [4:0][TERM_W-1:0] in_dest,
  input logic [4:0][3:0] in_src_leaf,in_next_port,
  input logic [4:0][TERM_W-1:0] in_dst_leaf,
  input logic [4:0] in_eject,
  output logic [4:0] out_valid,
  input logic [4:0] out_ready,
  output logic [4:0][DATA_W-1:0] out_data,
  output logic [4:0][TERM_W-1:0] out_dest,
  output logic [4:0][3:0] out_src_leaf,out_next_port,
  output logic [4:0][TERM_W-1:0] out_dst_leaf,
  output logic [4:0] out_eject
);
  logic [4:0] valid_q;
  logic [4:0][DATA_W-1:0] data_q;
  logic [4:0][TERM_W-1:0] dest_q;
  logic [4:0][3:0] src_leaf_q;
  logic [4:0][TERM_W-1:0] dst_leaf_q;
  logic [4:0] eject_q;
  logic [4:0] req [0:4];
  logic [4:0] winner [0:4];
  logic [4:0][4:0] grant;
  logic [2:0] rr [0:4];
  always_comb begin
    int output_port, candidate, destination_position;
    for (int o=0;o<5;o++) begin
      req[o]='0; winner[o]='0; grant[o]='0;
      for (int i=0;i<5;i++) if (valid_q[i]) begin
        destination_position=int'(dst_leaf_q[i])/4;
        output_port=4;
        if (LEVEL==2 && POS==destination_position) output_port=int'(dst_leaf_q[i])%4;
        else if (destination_position/4**(2-LEVEL)==POS) begin
          if (LEVEL==2) output_port=0;
          else output_port=destination_position/(4**(1-LEVEL))-4*POS;
        end else output_port=4;
        if (output_port==o) req[o][i]=1'b1;
      end
      for (int step=0;step<5;step++) begin
        candidate=(int'(rr[o])+step)%5;
        if (req[o][candidate] && !(|grant[o])) begin
          winner[o]=candidate[2:0]; grant[o][candidate]=1'b1;
        end
      end
    end
    out_valid='0; out_data='0; out_dest='0; out_src_leaf='0; out_dst_leaf='0; out_next_port='0; out_eject='0;
    for (int o=0;o<5;o++) for (int i=0;i<5;i++) if (grant[o][i]) begin
      out_valid[o]=1'b1; out_data[o]=data_q[i]; out_dest[o]=dest_q[i];
      out_src_leaf[o]=src_leaf_q[i]; out_dst_leaf[o]=dst_leaf_q[i];
      out_eject[o]=(LEVEL==2 && POS==int'(dst_leaf_q[i])/4);
      if (LEVEL==2 && POS==int'(dst_leaf_q[i])/4) out_next_port[o]=int'(dst_leaf_q[i])%4;
      else if ((int'(dst_leaf_q[i])/4)/4**(2-LEVEL)==POS)
        out_next_port[o]=LEVEL==2 ? int'(dst_leaf_q[i])%4 : (int'(dst_leaf_q[i])/4)/(4**(1-LEVEL))-4*POS;
      else out_next_port[o]=4;
    end
    in_ready='0;
    for (int i=0;i<5;i++) in_ready[i]=!valid_q[i];
    destination_position=0;
    output_port=0;
    candidate=0;
  end

  always_ff @(posedge clk) begin
    if (rst) begin
      valid_q<='0;
      for (int o=0;o<5;o++) rr[o]<=0;
    end else begin
      for (int o=0;o<5;o++) for (int i=0;i<5;i++) if (grant[o][i] && out_ready[o]) begin
        valid_q[i]<=1'b0; rr[o]<=winner[o]+3'd1;
      end
      for (int i=0;i<5;i++) if (in_valid[i] && in_ready[i]) begin
        valid_q[i]<=1'b1; data_q[i]<=in_data[i]; dest_q[i]<=in_dest[i];
        src_leaf_q[i]<=in_src_leaf[i]; dst_leaf_q[i]<=in_dst_leaf[i]; eject_q[i]<=in_eject[i];
      end
    end
  end
endmodule

`default_nettype wire
