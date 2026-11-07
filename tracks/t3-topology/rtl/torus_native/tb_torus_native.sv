`timescale 1ns/1ps
module tb_torus_native;
  localparam int K=5, N=K*K, ID_W=$clog2(N), DATA_W=32, PACKETS=N*N;
  logic clk=0, rst=1;
  logic [N-1:0] inject_valid,inject_ready,inject_vc,eject_valid,eject_ready;
  logic [N-1:0][DATA_W-1:0] inject_data,eject_data;
  logic [N-1:0][ID_W-1:0] inject_dest;
  bit sent[0:PACKETS-1], received[0:PACKETS-1];
  int source_for[0:PACKETS-1], dest_for[0:PACKETS-1];
  int next_dest[N];
  int accepted=0, delivered=0, cycles=0;

  always #5 clk=~clk;
  torus_native_fabric #(.K(K),.DATA_W(DATA_W),.ID_W(ID_W)) dut(.*);

  initial begin
    inject_valid='0; inject_data='0; inject_dest='0; inject_vc='0; eject_ready='0;
    for (int s=0;s<N;s++) begin
      next_dest[s]=0;
      for(int d=0;d<N;d++) begin
        int id=s*N+d; source_for[id]=s; dest_for[id]=d;
      end
    end
    repeat(4) @(negedge clk); rst=0;
    while (delivered<PACKETS && cycles<20000) begin
      @(negedge clk); cycles++;
      // Deterministic destination-specific stalls, including full-output hold.
      for(int r=0;r<N;r++) eject_ready[r]=((cycles+r*3)%7 != 0);
      for(int s=0;s<N;s++) begin
        if (!inject_valid[s] || inject_ready[s]) begin
          if(next_dest[s]<N) begin
            int d,id;
            d=next_dest[s]; id=s*N+d;
            inject_valid[s]=1; inject_dest[s]=d; inject_data[s]=id+1;
            // canonical VC half: X phase uses src_x > dst_x; Y similarly.
            inject_vc[s]=((s%K)>(d%K));
            if((s%K)==(d%K)) inject_vc[s]=((s/K)>(d/K));
          end else inject_valid[s]=0;
        end
      end
      @(posedge clk);
      for(int s=0;s<N;s++) if(inject_valid[s]&&inject_ready[s]) begin
        int id; id=int'(inject_data[s])-1;
        if(id<0||id>=PACKETS||sent[id]||source_for[id]!=s) $fatal(1,"bad/duplicate injection id %0d",id);
        sent[id]=1; accepted++; next_dest[s]++;
      end
      for(int d=0;d<N;d++) if(eject_valid[d]&&eject_ready[d]) begin
        int id; id=int'(eject_data[d])-1;
        if(id<0||id>=PACKETS||!sent[id]||received[id]||dest_for[id]!=d) $fatal(1,"bad/duplicate/misdirected delivery id %0d at %0d",id,d);
        received[id]=1; delivered++;
      end
    end
    if(delivered!=PACKETS) $fatal(1,"timeout delivered=%0d/%0d",delivered,PACKETS);
    if(accepted!=PACKETS) $fatal(1,"accepted=%0d",accepted);
    // Drain and check no phantom or duplicate delivery.
    inject_valid='0; eject_ready='1;
    repeat(20) begin
      @(posedge clk);
      for(int d=0;d<N;d++) if(eject_valid[d]) $fatal(1,"post-drain extra flit");
    end
    $display("PASS K=%0d routers=%0d all_pairs=%0d packets=%0d cycles=%0d",K,N,PACKETS,delivered,cycles);
    $finish;
  end
endmodule
