`default_nettype none

// Canonical structured tree4: radix=4, tiers=2, breadth-first router IDs
// 0..20. Routers 0..4 are internal and 5..20 are leaves. One terminal is
// attached to each leaf, terminal t at router 5+t. This is a single-root
// balanced tree, distinct from the four-root tree4_native fabric.
// Each flit is one complete packet; packet fragmentation/reassembly is absent.
module structured_tree4_fabric #(
  parameter int DATA_W=32, TERM_W=4
)(
  input logic clk, rst,
  input logic [15:0] inject_valid,
  output logic [15:0] inject_ready,
  input logic [15:0][DATA_W-1:0] inject_data,
  input logic [15:0][TERM_W-1:0] inject_dest,
  output logic [15:0] eject_valid,
  input logic [15:0] eject_ready,
  output logic [15:0][DATA_W-1:0] eject_data
);
  localparam int N=21;
  logic [N-1:0] valid_q;
  logic [N-1:0][DATA_W-1:0] data_q;
  logic [N-1:0][TERM_W-1:0] dest_q;
  logic [N-1:0] move, grant;
  logic [N-1:0][N-1:0] requests;
  logic [N-1:0] target_ready;

  function automatic int route_next(input int node, input int dest);
    int leaf, walk, child;
    begin
      leaf=5+dest;
      if (node==leaf) route_next=-1;
      else begin
        walk=leaf;
        while (walk>0 && walk!=node) walk=(walk-1)/4;
        if (walk==node) begin
          // Destination is below this router. Find the child immediately
          // below node on the unique path to destination leaf.
          child=leaf;
          while ((child-1)/4!=node) child=(child-1)/4;
          route_next=child;
        end
        else begin
          route_next=(node-1)/4;
        end
      end
    end
  endfunction

  always_comb begin
    requests='0; grant='0; move='0; target_ready='0;
    inject_ready='0; eject_valid='0; eject_data='0;
    for (int t=0;t<16;t++) begin
      int leaf;
      leaf=5+t;
      eject_valid[t]=valid_q[leaf] && dest_q[leaf]==t;
      eject_data[t]=data_q[leaf];
      inject_ready[t]=!valid_q[leaf] || (eject_valid[t] && eject_ready[t]);
    end
    for (int n=0;n<N;n++) begin
      if (valid_q[n]) begin
        if (route_next(n,int'(dest_q[n]))<0) begin
          int t;
          t=int'(dest_q[n]);
          if (n==5+t && eject_ready[t]) move[n]=1'b1;
        end else begin
          requests[route_next(n,int'(dest_q[n]))][n]=1'b1;
        end
      end
    end
    // Pick the lowest-ID requester for each destination. A router slot accepts
    // a transfer only when empty or when its current packet ejects.
    for (int d=0;d<N;d++) begin
      int winner;
      winner=-1;
      for (int s=0;s<N;s++) if (requests[d][s] && winner<0) winner=s;
      if (winner>=0 && (!valid_q[d] || move[d])) grant[winner]=1'b1;
    end
    for (int n=0;n<N;n++) begin
      if (valid_q[n] && route_next(n,int'(dest_q[n]))>=0 && grant[n]) move[n]=1'b1;
      target_ready[n]=!valid_q[n] || move[n];
    end
    for (int t=0;t<16;t++) begin
      int leaf;
      leaf=5+t;
      // Injection enters the source terminal's attached leaf router.
      if (inject_valid[t] && inject_ready[t]) begin end
    end
  end

  always_ff @(posedge clk) begin
    if (rst) valid_q<='0;
    else begin
      for (int n=0;n<N;n++) if (move[n]) valid_q[n]<=1'b0;
      for (int s=0;s<N;s++) if (grant[s]) begin
        int d;
        d=route_next(s,int'(dest_q[s]));
        valid_q[d]<=1'b1; data_q[d]<=data_q[s]; dest_q[d]<=dest_q[s];
      end
      for (int t=0;t<16;t++) begin
        int leaf;
        leaf=5+t;
        if (inject_valid[t] && inject_ready[t]) begin
          valid_q[leaf]<=1'b1; data_q[leaf]<=inject_data[t];
          dest_q[leaf]<=inject_dest[t];
        end
      end
    end
  end
endmodule
`default_nettype wire
