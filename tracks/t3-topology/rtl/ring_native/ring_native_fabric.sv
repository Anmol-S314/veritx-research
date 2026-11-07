`default_nettype none

// One-flit packet router for ring_native. Each physical input has one
// single-entry buffer per VC. At most one input-VC is granted per output per
// cycle, with round-robin arbitration. Port 0 is +1, port 1 -1, port 2 local.
module ring_native_router #(
  parameter int N=64, ID_W=$clog2(N), DATA_W=32,
  parameter int NODE_ID=0
)(
  input logic clk, rst,
  input logic [2:0] in_valid,
  output logic [2:0][1:0] in_ready,
  input logic [2:0][DATA_W-1:0] in_data,
  input logic [2:0][ID_W-1:0] in_dest,
  input logic [2:0] in_vc,
  output logic [2:0] out_valid,
  input logic [2:0][1:0] out_ready,
  output logic [2:0][DATA_W-1:0] out_data,
  output logic [2:0][ID_W-1:0] out_dest,
  output logic [2:0] out_vc
);
  logic [2:0][1:0] valid_q;
  logic [2:0][1:0][DATA_W-1:0] data_q;
  logic [2:0][1:0][ID_W-1:0] dest_q;
  logic [2:0] rr [0:2];
  logic [5:0] req [0:2];
  logic [2:0] winner [0:2];
  logic grant [0:2][0:5];

  always_comb begin
    int i, o, step, candidate, vc_idx;
    for (int out_idx=0;out_idx<3;out_idx++) begin
      o=out_idx;
      req[o]='0;
      winner[o]=0;
      for (int in_idx=0;in_idx<3;in_idx++) begin
        i=in_idx;
        for (int channel=0;channel<2;channel++) begin
          vc_idx=channel;
          candidate=i*2+vc_idx;
          if (valid_q[i][vc_idx]) begin
            if (int'(dest_q[i][vc_idx])==NODE_ID) req[2][candidate]=1'b1;
            else if (((int'(dest_q[i][vc_idx])+N-NODE_ID)%N)==N/2)
              req[(vc_idx != 0) ? 1 : 0][candidate]=1'b1;
            else if (((int'(dest_q[i][vc_idx])+N-NODE_ID)%N)<N/2)
              req[0][candidate]=1'b1;
            else req[1][candidate]=1'b1;
          end
        end
      end
      for (int req_idx=0;req_idx<6;req_idx++) grant[o][req_idx]=1'b0;
      for (int arb_step=0;arb_step<6;arb_step++) begin
        step=arb_step;
        candidate=(int'(rr[o])+step)%6;
        if (req[o][candidate] && out_ready[o][candidate%2] && !grant[o][0] && !grant[o][1] && !grant[o][2] && !grant[o][3] && !grant[o][4] && !grant[o][5]) begin
          winner[o]=candidate[2:0];
          grant[o][candidate]=1'b1;
        end
      end
    end
    out_valid='0; out_data='0; out_dest='0; out_vc='0;
    for (int out_idx=0;out_idx<3;out_idx++) begin
      for (int req_idx=0;req_idx<6;req_idx++) if (grant[out_idx][req_idx]) begin
        out_valid[out_idx]=1'b1; out_data[out_idx]=data_q[req_idx/2][req_idx%2];
        out_dest[out_idx]=dest_q[req_idx/2][req_idx%2]; out_vc[out_idx]=(req_idx%2)!=0;
      end
    end
    in_ready='0;
    for (int in_idx=0;in_idx<3;in_idx++)
      for (int channel=0;channel<2;channel++)
        in_ready[in_idx][channel]=!valid_q[in_idx][channel];
  end

  always_ff @(posedge clk) begin
    int i, o;
    if (rst) begin
      valid_q<='0;
      for (int out_idx=0;out_idx<3;out_idx++) rr[out_idx]<=0;
    end else begin
      for (int out_idx=0;out_idx<3;out_idx++) begin
        o=out_idx;
        for (int req_idx=0;req_idx<6;req_idx++) if (grant[o][req_idx] && out_ready[o][req_idx%2]) begin
          valid_q[req_idx/2][req_idx%2]<=1'b0;
          rr[o]<=winner[o]+3'd1;
        end
      end
      // Enqueue last so a same-cycle dequeue/enqueue of the same VC keeps
      // the newly accepted flit in the elastic slot.
      for (int in_idx=0;in_idx<3;in_idx++) begin
        i=in_idx;
        if (in_valid[i] && in_ready[i][in_vc[i]]) begin
          valid_q[i][in_vc[i]]<=1'b1; data_q[i][in_vc[i]]<=in_data[i]; dest_q[i][in_vc[i]]<=in_dest[i];
        end
      end
    end
  end
endmodule

// 64 routers, explicit ready/valid links. This minimal fabric is a single-flit
// packet protocol: one accepted flit is one complete packet, delivered exactly
// once to destination terminal. Router 2 is local injection/ejection.
module ring_native_fabric #(
  parameter int N=64, DATA_W=32, ID_W=$clog2(N)
)(
  input logic clk, rst,
  input logic [N-1:0] inject_valid,
  output logic [N-1:0] inject_ready,
  input logic [N-1:0][DATA_W-1:0] inject_data,
  input logic [N-1:0][ID_W-1:0] inject_dest,
  input logic [N-1:0] inject_vc,
  output logic [N-1:0] eject_valid,
  input logic [N-1:0] eject_ready,
  output logic [N-1:0][DATA_W-1:0] eject_data
);
  logic [N-1:0][1:0] link_valid;
  logic [N-1:0][1:0][1:0] link_ready;
  logic [N-1:0][1:0][DATA_W-1:0] link_data;
  logic [N-1:0][1:0][ID_W-1:0] link_dest;
  logic [N-1:0][1:0] link_vc;
  logic [N-1:0][2:0] iv,ov,ovc,ivc;
  logic [N-1:0][2:0][1:0] ir,ordy;
  logic [N-1:0][2:0][DATA_W-1:0] idata,odata;
  logic [N-1:0][2:0][ID_W-1:0] idest,odest;
  for (genvar r=0;r<N;r++) begin: routers
    assign iv[r][0]=link_valid[(r+N-1)%N][0];
    assign iv[r][1]=link_valid[(r+1)%N][1];
    assign iv[r][2]=inject_valid[r];
    assign idata[r][0]=link_data[(r+N-1)%N][0];
    assign idata[r][1]=link_data[(r+1)%N][1];
    assign idata[r][2]=inject_data[r];
    assign idest[r][0]=link_dest[(r+N-1)%N][0];
    assign idest[r][1]=link_dest[(r+1)%N][1];
    assign idest[r][2]=inject_dest[r];
    assign ivc[r][0]=link_vc[(r+N-1)%N][0];
    assign ivc[r][1]=link_vc[(r+1)%N][1];
    assign ivc[r][2]=inject_vc[r];
    // Port 0 sends to r+1, port 1 sends to r-1. Ready is returned
    // from the corresponding downstream input, not the upstream neighbor.
    assign link_ready[r][0]=ir[(r+1)%N][0];
    assign link_ready[r][1]=ir[(r+N-1)%N][1];
    assign inject_ready[r]=ir[r][2][inject_vc[r]];
    assign link_valid[r][0]=ov[r][0]; assign link_data[r][0]=odata[r][0];
    assign link_dest[r][0]=odest[r][0]; assign link_vc[r][0]=ovc[r][0];
    assign link_valid[r][1]=ov[r][1]; assign link_data[r][1]=odata[r][1];
    assign link_dest[r][1]=odest[r][1]; assign link_vc[r][1]=ovc[r][1];
    assign ordy[r][0]=link_ready[r][0]; assign ordy[r][1]=link_ready[r][1];
    assign ordy[r][2]={2{eject_ready[r]}};
    assign eject_valid[r]=ov[r][2]; assign eject_data[r]=odata[r][2];
    ring_native_router #(.N(N),.ID_W(ID_W),.DATA_W(DATA_W),.NODE_ID(r)) u_router(
      .clk,.rst,.in_valid(iv[r]),.in_ready(ir[r]),.in_data(idata[r]),.in_dest(idest[r]),.in_vc(ivc[r]),
      .out_valid(ov[r]),.out_ready(ordy[r]),.out_data(odata[r]),.out_dest(odest[r]),.out_vc(ovc[r]));
  end
endmodule

`default_nettype wire
