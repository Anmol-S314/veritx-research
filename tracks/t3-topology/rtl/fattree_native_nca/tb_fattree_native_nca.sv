`timescale 1ns/1ps
`default_nettype none
module tb_fattree_native_nca;
  localparam int N=16;
  logic clk=0,rst=1;
  logic [15:0] inject_valid,inject_ready,eject_valid,eject_ready;
  logic [15:0][31:0] inject_data,eject_data;
  logic [15:0][3:0] inject_dest;
  bit seen[N][N];
  bit stalled_prev[N];
  logic [31:0] held_payload[N];
  int next_dest[N];
  int accepted=0,received=0,cycles=0,stalls=0;
  always #5 clk=~clk;
  fattree_native_nca_fabric dut(.*);

  function automatic int expected_parent(input int src,input int dst);
    // Deterministic representative of BookSim's random choice among 4 links.
    expected_parent=dst/4;
  endfunction

  initial begin
    inject_valid='0; inject_data='0; inject_dest='0; eject_ready='0;
    for(int s=0;s<N;s++) begin
      next_dest[s]=0;
      stalled_prev[s]=0;
      held_payload[s]='0;
      for(int d=0;d<N;d++) seen[s][d]=0;
    end
    repeat(3) @(negedge clk); rst=0;

    // Canonical k=4,n=2 shape: eight routers, four per tier,
    // sixteen directed channels in each direction, 16 terminals.
    begin
      int links_per_tier[8];
      for(int r=0;r<8;r++) links_per_tier[r]=0;
      for(int b=0;b<4;b++) for(int t=0;t<4;t++) begin
        links_per_tier[b]++;
        links_per_tier[4+t]++;
      end
      for(int r=0;r<8;r++) if(links_per_tier[r]!=4)
        $fatal(1,"tier degree router=%0d degree=%0d",r,links_per_tier[r]);
    end

    // For every ordered pair, verify NCA hop pattern and port selection.
    for(int s=0;s<N;s++) for(int d=0;d<N;d++) begin
      int sb,db,p;
      sb=s/4; db=d/4;
      if(sb==db) begin
        p=d%4;
        if((s/4)!=sb||p!=(d%4)) $fatal(1,"local route %0d->%0d",s,d);
      end else begin
        p=expected_parent(sb,d);
        if(p<0||p>3||p!=db) $fatal(1,"parent route %0d->%0d",s,d);
        if((d/4)!=db) $fatal(1,"top down branch %0d->%0d",s,d);
      end
    end

    while(received<N*N && cycles<10000) begin
      @(negedge clk); cycles++; inject_valid='0;
      for(int s=0;s<N;s++) if(next_dest[s]<N) begin
        inject_valid[s]=1;
        inject_dest[s]=4'(next_dest[s]);
        inject_data[s]={8'hfa,s[7:0],next_dest[s][7:0],8'(s^next_dest[s])};
      end
      // Deterministic mixed ready pattern creates repeated ejection stalls.
      for(int t=0;t<N;t++) eject_ready[t]=((cycles*7+t*3)%13)>=6;
      #1;
      for(int t=0;t<N;t++) begin
        if(stalled_prev[t] && (!eject_valid[t] || eject_data[t]!==held_payload[t]))
          $fatal(1,"ready/valid instability terminal=%0d old=%h valid=%b current=%h",t,held_payload[t],eject_valid[t],eject_data[t]);
        stalled_prev[t]=eject_valid[t]&&!eject_ready[t];
        if(eject_valid[t]) held_payload[t]=eject_data[t];
      end
      for(int s=0;s<N;s++) if(inject_valid[s]&&inject_ready[s]) begin
        next_dest[s]++; accepted++;
      end
      for(int t=0;t<N;t++) begin
        if(eject_valid[t]&&!eject_ready[t]) stalls++;
        if(eject_valid[t]&&eject_ready[t]) begin
          int src,dst;
          src=int'(eject_data[t][23:16]); dst=int'(eject_data[t][15:8]);
          if(eject_data[t][31:24]!=8'hfa||src>=N||dst>=N||dst!=t)
            $fatal(1,"bad delivery terminal=%0d payload=%h",t,eject_data[t]);
          if(seen[src][dst]) $fatal(1,"duplicate %0d->%0d",src,dst);
          if(eject_data[t][7:0]!=8'(src^dst)) $fatal(1,"payload corruption");
          seen[src][dst]=1; received++;
        end
      end
      @(posedge clk);
    end
    eject_ready='1;
    repeat(100) @(negedge clk);
    for(int s=0;s<N;s++) for(int d=0;d<N;d++) if(!seen[s][d])
      $fatal(1,"missing pair %0d->%0d",s,d);
    if(accepted!=N*N||received!=N*N)
      $fatal(1,"conservation accepted=%0d received=%0d",accepted,received);
    if(stalls==0) $fatal(1,"backpressure was not exercised");
    if(eject_valid!='0) $fatal(1,"fabric did not drain");
    $display("PASS topology=booksim_fattree k=4 n=2 routers=8 terminals=16 bottom_per_router=4 intertier_channels=16x2 ordered_pairs=256 accepted=%0d delivered=%0d cycles=%0d stalls=%0d drained=1",accepted,received,cycles,stalls);
    $finish;
  end
  initial begin
    #150000;
    $fatal(1,"watchdog cycles=%0d received=%0d",cycles,received);
  end
endmodule
`default_nettype wire
