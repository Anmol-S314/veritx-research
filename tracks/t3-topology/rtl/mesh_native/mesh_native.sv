`default_nettype none

// Native 4x4 one-endpoint-per-router mesh. Row-major router IDs; ports are
// local=0, east=1, west=2, south=3, north=4. One-entry input buffers and
// deterministic XY dimension-order routing (X before Y).
module mesh_native_router #(
  parameter int ID=0, K=4, DATA_W=32, ID_W=4
)(
  input logic clk, rst,
  input logic [4:0] in_valid,
  output logic [4:0] in_ready,
  input logic [4:0][DATA_W-1:0] in_data,
  input logic [4:0][ID_W-1:0] in_dest,
  output logic [4:0] out_valid,
  input logic [4:0] out_ready,
  output logic [4:0][DATA_W-1:0] out_data,
  output logic [4:0][ID_W-1:0] out_dest
);
  logic [4:0] valid_q;
  logic [4:0][DATA_W-1:0] data_q;
  logic [4:0][ID_W-1:0] dest_q;
  logic [4:0][2:0] rr;
  logic [4:0][4:0] req, grant;

  function automatic int route_port(input logic [ID_W-1:0] dest);
    int dx, dy;
    begin
      dx=int'(dest)%K; dy=int'(dest)/K;
      if (int'(dest)==ID) route_port=0;
      else if (dx>ID%K) route_port=1;
      else if (dx<ID%K) route_port=2;
      else if (dy>ID/K) route_port=3;
      else route_port=4;
    end
  endfunction

  always_comb begin
    int candidate, p;
    req='0; grant='0; out_valid='0; out_data='0; out_dest='0;
    in_ready='0; candidate=0; p=0;
    for (int i=0;i<5;i++) begin
      if (valid_q[i]) begin
        p=route_port(dest_q[i]);
        if ((p==0) || (p==1 && ID%K<K-1) || (p==2 && ID%K>0) ||
            (p==3 && ID/K<K-1) || (p==4 && ID/K>0)) req[p][i]=1'b1;
      end
    end
    for (int o=0;o<5;o++) begin
      for (int step=0;step<5;step++) begin
        candidate=(int'(rr[o])+step)%5;
        if (req[o][candidate] && out_ready[o] && !(|grant[o])) begin
          grant[o][candidate]=1'b1;
          out_valid[o]=1'b1;
          out_data[o]=data_q[candidate];
          out_dest[o]=dest_q[candidate];
        end
      end
    end
    for (int i=0;i<5;i++) in_ready[i]=!valid_q[i];
  end

  always_ff @(posedge clk) begin
    if (rst) begin valid_q<='0; rr<='0; end
    else begin
      for (int o=0;o<5;o++)
        for (int i=0;i<5;i++) if (grant[o][i] && out_ready[o]) begin
          valid_q[i]<=1'b0;
          rr[o]<=3'((i+1)%5);
        end
      for (int i=0;i<5;i++) if (in_valid[i] && in_ready[i]) begin
        valid_q[i]<=1'b1; data_q[i]<=in_data[i]; dest_q[i]<=in_dest[i];
      end
    end
  end
endmodule

module mesh_native #(
  parameter int K=4, DATA_W=32, ID_W=4, N=K*K
)(
  input logic clk, rst,
  input logic [N-1:0] inject_valid,
  output logic [N-1:0] inject_ready,
  input logic [N-1:0][DATA_W-1:0] inject_data,
  input logic [N-1:0][ID_W-1:0] inject_dest,
  output logic [N-1:0] eject_valid,
  input logic [N-1:0] eject_ready,
  output logic [N-1:0][DATA_W-1:0] eject_data
);
  logic [N-1:0][4:0] iv, ir, ov, ordy;
  logic [N-1:0][4:0][DATA_W-1:0] idata, odata;
  logic [N-1:0][4:0][ID_W-1:0] idest, odest;

  for (genvar r=0;r<N;r++) begin: routers
    assign iv[r][0]=inject_valid[r];
    assign idata[r][0]=inject_data[r];
    assign idest[r][0]=inject_dest[r];
    assign inject_ready[r]=ir[r][0];
    assign eject_valid[r]=ov[r][0];
    assign eject_data[r]=odata[r][0];
    assign ordy[r][0]=eject_ready[r];

    if (r%K<K-1) begin: east_link
      localparam int Q=r+1;
      assign iv[Q][2]=ov[r][1]; assign idata[Q][2]=odata[r][1]; assign idest[Q][2]=odest[r][1];
      assign ordy[r][1]=ir[Q][2];
    end else begin assign ordy[r][1]=1'b0; end
    if (r%K>0) begin: west_link
      localparam int Q=r-1;
      assign iv[Q][1]=ov[r][2]; assign idata[Q][1]=odata[r][2]; assign idest[Q][1]=odest[r][2];
      assign ordy[r][2]=ir[Q][1];
    end else begin assign ordy[r][2]=1'b0; end
    if (r/K<K-1) begin: south_link
      localparam int Q=r+K;
      assign iv[Q][4]=ov[r][3]; assign idata[Q][4]=odata[r][3]; assign idest[Q][4]=odest[r][3];
      assign ordy[r][3]=ir[Q][4];
    end else begin assign ordy[r][3]=1'b0; end
    if (r/K>0) begin: north_link
      localparam int Q=r-K;
      assign iv[Q][3]=ov[r][4]; assign idata[Q][3]=odata[r][4]; assign idest[Q][3]=odest[r][4];
      assign ordy[r][4]=ir[Q][3];
    end else begin assign ordy[r][4]=1'b0; end

    mesh_native_router #(.ID(r),.K(K),.DATA_W(DATA_W),.ID_W(ID_W)) router_i(
      .clk,.rst,.in_valid(iv[r]),.in_ready(ir[r]),.in_data(idata[r]),.in_dest(idest[r]),
      .out_valid(ov[r]),.out_ready(ordy[r]),.out_data(odata[r]),.out_dest(odest[r]));
  end
endmodule

`default_nettype wire
