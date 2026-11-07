`default_nettype none

// Concentrated 4x4 mesh: 16 routers, 4 terminal slots/router, 64 terminals.
// Router ids are row-major; terminal id t attaches to router t/4, local slot
// t%4. Router ports 0..3 are local slots. Ports 4..7 are E,W,S,N. The
// materializer densely numbers only present links in ascending-neighbor order;
// these fixed RTL direction slots preserve exactly that neighbor relation.
// Contract: each accepted flit is one complete packet. No packet assembly,
// multi-flit framing, VC allocation, or project-level packet/VC semantics.
module concentrated_mesh_router #(
  parameter int K=4, C=4, DATA_W=32, TERM_W=$clog2(K*K*C),
  parameter int ROUTER_ID=0, PORTS=C+4
)(
  input logic clk, rst,
  input logic [PORTS-1:0] in_valid,
  output logic [PORTS-1:0] in_ready,
  input logic [PORTS-1:0][DATA_W-1:0] in_data,
  input logic [PORTS-1:0][TERM_W-1:0] in_dest,
  output logic [PORTS-1:0] out_valid,
  input logic [PORTS-1:0] out_ready,
  output logic [PORTS-1:0][DATA_W-1:0] out_data,
  output logic [PORTS-1:0][TERM_W-1:0] out_dest
);
  logic [PORTS-1:0] valid_q;
  logic [PORTS-1:0][DATA_W-1:0] data_q;
  logic [PORTS-1:0][TERM_W-1:0] dest_q;
  localparam int RR_W=(PORTS<=2)?1:$clog2(PORTS);
  logic [PORTS-1:0][RR_W-1:0] rr;
  logic [PORTS-1:0][PORTS-1:0] req, grant;

  // Deterministic XY dimension-order route: first move horizontally, then
  // vertically. Missing boundary directions never receive requests.
  function automatic int route_port(input logic [TERM_W-1:0] dest);
    int dst_router, sx, sy, dx, dy;
    begin
      dst_router=int'(dest)/C;
      sx=ROUTER_ID%K; sy=ROUTER_ID/K;
      dx=dst_router%K; dy=dst_router/K;
      if (dst_router==ROUTER_ID) route_port=int'(dest)%C;
      else if (dx>sx) route_port=C+0;
      else if (dx<sx) route_port=C+1;
      else if (dy>sy) route_port=C+2;
      else route_port=C+3;
    end
  endfunction

  always_comb begin
    int candidate, outp;
    req='0; grant='0; out_valid='0; out_data='0; out_dest='0;
    in_ready='0; candidate=0; outp=0;
    for (int i=0;i<PORTS;i++) begin
      if (valid_q[i]) begin
        outp=route_port(dest_q[i]);
        if (outp<PORTS && ((outp<C) ||
            (outp==C+0 && ROUTER_ID%K<K-1) ||
            (outp==C+1 && ROUTER_ID%K>0) ||
            (outp==C+2 && ROUTER_ID/K<K-1) ||
            (outp==C+3 && ROUTER_ID/K>0))) req[outp][i]=1'b1;
      end
    end
    for (int o=0;o<PORTS;o++) begin
      for (int step=0;step<PORTS;step++) begin
        candidate=(int'(rr[o])+step)%PORTS;
        if (req[o][candidate] && out_ready[o] && !(|grant[o])) begin
          grant[o][candidate]=1'b1;
          out_valid[o]=1'b1;
          out_data[o]=data_q[candidate];
          out_dest[o]=dest_q[candidate];
        end
      end
    end
    for (int i=0;i<PORTS;i++) in_ready[i]=!valid_q[i];
  end

  always_ff @(posedge clk) begin
    if (rst) begin
      valid_q<='0; rr<='0;
    end else begin
      for (int o=0;o<PORTS;o++)
        for (int i=0;i<PORTS;i++) if (grant[o][i] && out_ready[o]) begin
          valid_q[i]<=1'b0;
          rr[o]<=RR_W'((i+1)%PORTS);
        end
      // Enqueue wins over simultaneous dequeue in the same input slot.
      for (int i=0;i<PORTS;i++) if (in_valid[i] && in_ready[i]) begin
        valid_q[i]<=1'b1; data_q[i]<=in_data[i]; dest_q[i]<=in_dest[i];
      end
    end
  end
endmodule

// Four local endpoints per router on a row-major 4x4 mesh. The physical
// neighbor relation and terminal attachment match the canonical materializer
// for endpoint_count=64, concentration=4, radix=4. Handshake links are
// zero-cycle combinational ready/valid with a one-entry buffer at each input.
module concentrated_mesh_native #(parameter int K=4,C=4,DATA_W=32,
  parameter int TERMS=K*K*C,TERM_W=$clog2(TERMS),PORTS=C+4)(
  input logic clk,rst,
  input logic [TERMS-1:0] inject_valid,
  output logic [TERMS-1:0] inject_ready,
  input logic [TERMS-1:0][DATA_W-1:0] inject_data,
  input logic [TERMS-1:0][TERM_W-1:0] inject_dest,
  output logic [TERMS-1:0] eject_valid,
  input logic [TERMS-1:0] eject_ready,
  output logic [TERMS-1:0][DATA_W-1:0] eject_data
);
  localparam int ROUTERS=K*K;
  logic [ROUTERS-1:0][PORTS-1:0] iv,ir,ov,ordy;
  logic [ROUTERS-1:0][PORTS-1:0][DATA_W-1:0] idata,odata;
  logic [ROUTERS-1:0][PORTS-1:0][TERM_W-1:0] idest,odest;
  for (genvar r=0;r<ROUTERS;r++) begin: router
    for (genvar s=0;s<C;s++) begin: local_input
      localparam int T=r*C+s;
      assign iv[r][s]=inject_valid[T];
      assign idata[r][s]=inject_data[T];
      assign idest[r][s]=inject_dest[T];
      assign inject_ready[T]=ir[r][s];
      assign eject_valid[T]=ov[r][s];
      assign eject_data[T]=odata[r][s];
      assign ordy[r][s]=eject_ready[T];
    end
    // Fixed router ports: east=C, west=C+1, south=C+2, north=C+3.
    if (r%K<K-1) begin
      localparam int NBR=r+1, P=C+0, NP=C+1;
      assign iv[NBR][NP]=ov[r][P]; assign idata[NBR][NP]=odata[r][P]; assign idest[NBR][NP]=odest[r][P];
      assign ordy[r][P]=ir[NBR][NP];
    end else begin assign ordy[r][C+0]=1'b0; end
    if (r%K>0) begin
      localparam int NBR=r-1, P=C+1, NP=C+0;
      assign iv[NBR][NP]=ov[r][P]; assign idata[NBR][NP]=odata[r][P]; assign idest[NBR][NP]=odest[r][P];
      assign ordy[r][P]=ir[NBR][NP];
    end else begin assign ordy[r][C+1]=1'b0; end
    if (r/K<K-1) begin
      localparam int NBR=r+K, P=C+2, NP=C+3;
      assign iv[NBR][NP]=ov[r][P]; assign idata[NBR][NP]=odata[r][P]; assign idest[NBR][NP]=odest[r][P];
      assign ordy[r][P]=ir[NBR][NP];
    end else begin assign ordy[r][C+2]=1'b0; end
    if (r/K>0) begin
      localparam int NBR=r-K, P=C+3, NP=C+2;
      assign iv[NBR][NP]=ov[r][P]; assign idata[NBR][NP]=odata[r][P]; assign idest[NBR][NP]=odest[r][P];
      assign ordy[r][P]=ir[NBR][NP];
    end else begin assign ordy[r][C+3]=1'b0; end
    concentrated_mesh_router #(.K(K),.C(C),.DATA_W(DATA_W),.TERM_W(TERM_W),.ROUTER_ID(r),.PORTS(PORTS)) u_router(
      .clk,.rst,.in_valid(iv[r]),.in_ready(ir[r]),.in_data(idata[r]),.in_dest(idest[r]),
      .out_valid(ov[r]),.out_ready(ordy[r]),.out_data(odata[r]),.out_dest(odest[r]));
  end
endmodule

`default_nettype wire
