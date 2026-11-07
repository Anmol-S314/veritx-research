`timescale 1ns/1ps
module tb_concentrated_mesh_native;
  localparam int K=4,C=4,N=64,ID_W=6;
  logic clk=0,rst=1;
  logic [N-1:0] inject_valid,inject_ready,eject_valid,eject_ready;
  logic [N-1:0][31:0] inject_data,eject_data;
  logic [N-1:0][ID_W-1:0] inject_dest;
  int next_dest[N];
  int expected_dest[N][N];
  bit seen[N][N];
  int accepted=0,received=0,cycles=0,stalls=0,contention_cycles=0,blocked_cycles=0;
  int src,dst;
  bit contention_mode=0;
  always #5 clk=~clk;
  concentrated_mesh_native dut(.*);
  initial begin
    inject_valid='0; inject_data='0; inject_dest='0; eject_ready='0;
    for(int s=0;s<N;s++) next_dest[s]=0;
    repeat(3) @(negedge clk); rst=0;
    // Complete all 64x64 pairs, including local delivery.
    while(received<N*N && cycles<20000) begin
      @(negedge clk); cycles++; inject_valid='0;
      for(int s=0;s<N;s++) if(next_dest[s]<N) begin
        inject_valid[s]=1;
        inject_dest[s]=next_dest[s][ID_W-1:0];
        expected_dest[s][next_dest[s]]=inject_dest[s];
        inject_data[s]={s[5:0],inject_dest[s],20'(s*N+next_dest[s])};
      end
      for(int t=0;t<N;t++) eject_ready[t]=((cycles*13+t*7)%9)!=0;
      #1;
      for(int s=0;s<N;s++) if(inject_valid[s]&&inject_ready[s]) begin
        next_dest[s]++; accepted++;
      end
      for(int t=0;t<N;t++) begin
        if(eject_valid[t]&&eject_ready[t]) begin
          int seq_dst;
          src=eject_data[t][31:26]; dst=eject_data[t][25:20];
          seq_dst=eject_data[t][19:0]%N;
          if(dst!=t||src>=N||seq_dst>=N||seen[src][seq_dst]||expected_dest[src][seq_dst]!=dst) $fatal(1,"bad/duplicate packet src=%0d encoded-dst=%0d terminal=%0d seq=%0d",src,dst,t,seq_dst);
          seen[src][seq_dst]=1; received++;
        end
      end
      @(posedge clk);
    end
    if(accepted!=N*N) $fatal(1,"incomplete accepted=%0d",accepted);
    // Force sustained contention at one output and hold ejection backpressure.
    contention_mode=1;
    for(int s=0;s<N;s++) begin
      inject_valid[s]=1; inject_dest[s]=ID_W'(32);
      inject_data[s]={s[5:0],6'd32,20'(s*N+32)};
    end
    eject_ready='0;
    repeat(10) begin
      @(negedge clk); blocked_cycles++;
      for(int t=0;t<N;t++) begin
        if(eject_valid[t]) stalls++;
      end
      if(inject_valid[32] && !inject_ready[32]) stalls++;
      if(inject_valid[33] && !inject_ready[33]) contention_cycles++;
    end
    if(stalls==0) $fatal(1,"backpressure was not observed");
    inject_valid='0; eject_ready='1;
    repeat(200) @(negedge clk);
    contention_mode=0;
    rst=1; eject_ready='0; repeat(3) @(negedge clk); rst=0;
    accepted=0; received=0; cycles=0;
    for(int s=0;s<N;s++) begin next_dest[s]=0; for(int d=0;d<N;d++) seen[s][d]=0; end
    while(received<N*N && cycles<30000) begin
      @(negedge clk); cycles++; inject_valid='0;
      for(int s=0;s<N;s++) if(next_dest[s]<N) begin
        inject_valid[s]=1; inject_dest[s]=ID_W'(next_dest[s]);
        expected_dest[s][next_dest[s]]=inject_dest[s];
        inject_data[s]={s[5:0],inject_dest[s],20'(s*N+next_dest[s])};
      end
      for(int t=0;t<N;t++) eject_ready[t]=((cycles*13+t*7)%9)!=0;
      #1;
      for(int s=0;s<N;s++) if(inject_valid[s]&&inject_ready[s]) begin next_dest[s]++; accepted++; end
      for(int t=0;t<N;t++) if(eject_valid[t]&&eject_ready[t]) begin
        int seq_dst;
        src=int'(eject_data[t][31:26]); dst=int'(eject_data[t][25:20]); seq_dst=int'(eject_data[t][19:0])%N;
        if(dst!=t||src>=N||seen[src][seq_dst]||expected_dest[src][seq_dst]!=dst) $fatal(1,"bad/duplicate packet");
        seen[src][seq_dst]=1; received++;
      end
      @(posedge clk);
    end
    if(accepted!=N*N||received!=N*N) $fatal(1,"all-pairs incomplete accepted=%0d received=%0d",accepted,received);
    eject_ready='0; repeat(5) @(negedge clk); blocked_cycles+=5; eject_ready='1;
    repeat(200) @(negedge clk);
    for(int s=0;s<N;s++) for(int d=0;d<N;d++) if(!seen[s][d]) $fatal(1,"missing %0d->%0d",s,d);
    if(stalls==0) $fatal(1,"backpressure was not observed");
    if(received!=N*N) $fatal(1,"drain incomplete received=%0d",received);
    $display("PASS routers=16 mesh=4x4 concentration=4 endpoints=64 pairs=%0d accepted=%0d received=%0d cycles=%0d contention_cycles=%0d blocked_cycles=%0d stalls=%0d drained=1",N*N,accepted,received,cycles,contention_cycles,blocked_cycles,stalls);
    $finish;
  end
  initial begin #250000; $fatal(1,"timeout"); end
endmodule
