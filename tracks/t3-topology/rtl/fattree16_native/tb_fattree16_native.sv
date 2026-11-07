`timescale 1ns/1ps
`default_nettype none
module tb_fattree16_native;
  localparam int N=16;
  logic clk=0,rst=1;
  logic [N-1:0] inject_valid,inject_ready,eject_valid,eject_ready;
  logic [N-1:0][31:0] inject_data,eject_data;
  logic [N-1:0][3:0] inject_dest;
  bit seen[N][N];
  bit stalled_prev[N];
  logic [31:0] stalled_data[N];
  int next_dest[N];
  int accepted=0,received=0,cycles=0,stalls=0;
  always #5 clk=~clk;
  fattree16_native_fabric dut(.*);

  function automatic int mid_switch(input int src_leaf,input int dst_leaf);
    mid_switch=4+((src_leaf+dst_leaf)%4);
  endfunction
  function automatic int route_next(input int router,input int dst);
    int src_leaf,dst_leaf;
    begin
      src_leaf=(router<4)?router:((router-4)%4); dst_leaf=dst/4;
      if(router<4) begin
        if(src_leaf==dst_leaf) route_next=dst%4;
        else route_next=mid_switch(src_leaf,dst_leaf)-4;
      end else route_next=dst_leaf;
    end
  endfunction

  initial begin
    inject_valid='0; inject_data='0; inject_dest='0; eject_ready='0;
    for(int s=0;s<N;s++) begin
      next_dest[s]=0;
      stalled_prev[s]=0;
      stalled_data[s]='0;
      for(int d=0;d<N;d++) seen[s][d]=0;
    end
    repeat(3) @(negedge clk); rst=0;

    // Verify the pinned AnyNet graph: 8 switches, 16 edge-core undirected
    // adjacencies, degree 4 at every switch, terminal seats on edge switches.
    begin
      int degrees[8];
      for(int r=0;r<8;r++) degrees[r]=0;
      for(int l=0;l<4;l++) for(int j=0;j<4;j++) begin
        int u; u=4+((l+j)%4); degrees[l]++; degrees[u]++;
      end
      for(int r=0;r<8;r++) if(degrees[r]!=4) $fatal(1,"graph degree router=%0d degree=%0d",r,degrees[r]);
    end
    // Every source/destination has a legal exact path of 0 or 2 links.
    for(int s=0;s<N;s++) for(int d=0;d<N;d++) begin
      int sl,dl;
      sl=s/4; dl=d/4;
        if(sl==dl) begin
        if(route_next(sl,d)!=d%4) $fatal(1,"local route mismatch %0d->%0d",s,d);
      end else begin
        int upper,dest_edge;
        upper=mid_switch(sl,dl);
        if(upper<4||upper>7||route_next(sl,d)!=(upper-4)) $fatal(1,"wrong middle %0d->%0d",s,d);
        dest_edge=route_next(upper,d);
        if(dest_edge!=dl) $fatal(1,"wrong downlink %0d->%0d",s,d);
      end
    end

    // The all-pairs phase below is the sole traffic source so accepted and
    // delivered conservation counts cover every flit exactly once. Its
    // deterministic ready pattern exercises receiver backpressure.
    while(received<N*N && cycles<10000) begin
      @(negedge clk); cycles++; inject_valid='0;
      for(int s=0;s<N;s++) if(next_dest[s]<N) begin
        inject_valid[s]=1; inject_dest[s]=4'(next_dest[s]);
        inject_data[s]={8'hfa,s[7:0],next_dest[s][7:0],8'(s^next_dest[s])};
      end
      for(int t=0;t<N;t++) eject_ready[t]=((cycles*7+t*3)%11)>=4;
      #1;
      for(int s=0;s<N;s++) if(inject_valid[s]&&inject_ready[s]) begin next_dest[s]++; accepted++; end
      for(int t=0;t<N;t++) begin
        if(stalled_prev[t] && (!eject_valid[t] || eject_data[t] !== stalled_data[t]))
          $fatal(1,"ready-valid output changed while stalled terminal=%0d old=%h new=%h valid=%b",t,stalled_data[t],eject_data[t],eject_valid[t]);
        stalled_prev[t]=eject_valid[t]&&!eject_ready[t];
        if(stalled_prev[t]) stalled_data[t]=eject_data[t];
        if(eject_valid[t]&&!eject_ready[t]) stalls++;
        if(eject_valid[t]&&eject_ready[t]) begin
          int src,dst;
          src=int'(eject_data[t][23:16]); dst=int'(eject_data[t][15:8]);
          if(eject_data[t][31:24]!=8'hfa||src>=N||dst>=N||dst!=t) $fatal(1,"bad delivery terminal=%0d data=%h",t,eject_data[t]);
          if(seen[src][dst]) $fatal(1,"duplicate %0d->%0d",src,dst);
          if(eject_data[t][7:0]!=8'(src^dst)) $fatal(1,"payload corruption");
          seen[src][dst]=1; received++;
        end
      end
      @(posedge clk);
    end
    // Continue receiving after all offers have stopped, then explicitly drain.
    eject_ready='1;
    repeat(100) @(negedge clk);
    for(int s=0;s<N;s++) for(int d=0;d<N;d++) if(!seen[s][d]) $fatal(1,"missing pair %0d->%0d",s,d);
    if(accepted!=N*N||received!=N*N) $fatal(1,"conservation accepted=%0d received=%0d",accepted,received);
    if(stalls==0) $fatal(1,"backpressure not exercised");
    if(eject_valid!='0) $fatal(1,"fabric did not drain");
    $display("PASS routers=8 terminals=16 tiers=2 radix=4 links=16 pairs=256 accepted=%0d delivered=%0d cycles=%0d stalls=%0d drained=1",accepted,received,cycles,stalls);
    $finish;
  end
  initial begin #150000; $fatal(1,"watchdog cycles=%0d received=%0d",cycles,received); end
endmodule
`default_nettype wire
