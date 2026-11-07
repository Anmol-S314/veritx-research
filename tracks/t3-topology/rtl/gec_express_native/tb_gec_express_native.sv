`timescale 1ns/1ps
module tb_gec_express_native;
  localparam int K=4,N=K*K,TERMS=N,DEG=1+2*(K-1),PACKETS=TERMS*TERMS;
  logic clk=0,rst=1;
  logic [TERMS-1:0] inject_valid,inject_ready,inject_vc,eject_valid,eject_ready;
  logic [TERMS-1:0][31:0] inject_data,eject_data;
  logic [TERMS-1:0][3:0] inject_dest;
  bit sent[0:PACKETS-1],received[0:PACKETS-1];
  int source_for[0:PACKETS-1],dest_for[0:PACKETS-1];
  int next_dest[TERMS], accepted=0,delivered=0,cycles=0;
  bit channel_seen[N][DEG];

  always #5 clk=~clk;
  gec_express_native_fabric #(.K(K),.C(1),.VCS(2),.DATA_W(32),.ID_W(4)) dut(.*);

  initial begin
    inject_valid='0; inject_data='0; inject_dest='0; inject_vc='0; eject_ready='0;
    for(int s=0;s<TERMS;s++) begin
      next_dest[s]=0;
      for(int d=0;d<TERMS;d++) begin
        int id; id=s*TERMS+d; source_for[id]=s; dest_for[id]=d;
      end
    end
    for(int r=0;r<N;r++) begin
      int x,y;
      x=r%K; y=r/K;
      for(int d=0;d<TERMS;d++) if(d!=r) begin
        int dr,dx,dy,p;
        dr=d; dx=dr%K; dy=dr/K;
        if(x!=dx) begin
          int peer_idx; peer_idx=(dx<x)?dx:dx-1; p=1+peer_idx;
        end else begin
          int peer_idx; peer_idx=(dy<y)?dy:dy-1; p=1+(K-1)+peer_idx;
        end
        channel_seen[r][p]=1;
      end
    end
    for(int r=0;r<N;r++) for(int p=1;p<DEG;p++)
      if(!channel_seen[r][p]) $fatal(1,"express output channel uncovered router=%0d port=%0d",r,p);

    repeat(4) @(negedge clk); rst=0;
    while(delivered<PACKETS && cycles<20000) begin
      @(negedge clk); cycles++;
      // Sustained destination-specific backpressure, with open phases for progress.
      for(int d=0;d<TERMS;d++) eject_ready[d]=((cycles+d*3)%7 != 0);
      for(int s=0;s<TERMS;s++) if(!inject_valid[s] || inject_ready[s]) begin
        if(next_dest[s]<TERMS) begin
          int d,id; d=next_dest[s]; id=s*TERMS+d;
          inject_valid[s]=1; inject_dest[s]=d; inject_data[s]=id+1;
          inject_vc[s]=((s%K)>(d%K));
          if((s%K)==(d%K)) inject_vc[s]=((s/K)>(d/K));
        end else inject_valid[s]=0;
      end
      @(posedge clk);
      for(int s=0;s<TERMS;s++) if(inject_valid[s]&&inject_ready[s]) begin
        int id; id=int'(inject_data[s])-1;
        if(id<0||id>=PACKETS||sent[id]||source_for[id]!=s) $fatal(1,"bad/duplicate injection %0d",id);
        sent[id]=1; accepted++; next_dest[s]++;
      end
      for(int d=0;d<TERMS;d++) if(eject_valid[d]&&eject_ready[d]) begin
        int id; id=int'(eject_data[d])-1;
        if(id<0||id>=PACKETS||!sent[id]||received[id]||dest_for[id]!=d)
          $fatal(1,"bad/duplicate/misdirected delivery id=%0d at=%0d",id,d);
        received[id]=1; delivered++;
      end
    end
    if(delivered!=PACKETS) $fatal(1,"timeout delivered=%0d/%0d",delivered,PACKETS);
    if(accepted!=PACKETS) $fatal(1,"accepted=%0d/%0d",accepted,PACKETS);
    inject_valid='0; eject_ready='1;
    repeat(30) begin
      @(posedge clk);
      for(int d=0;d<TERMS;d++) if(eject_valid[d]) $fatal(1,"post-drain extra flit");
    end
    $display("PASS GEC_EXPRESS K=%0d C=1 routers=%0d directed_express_channels=%0d all_pairs=%0d accepted=%0d delivered=%0d backpressure=enabled drain_cycles=30 cycles=%0d",K,N,N*2*(K-1),PACKETS,accepted,delivered,cycles);
    $finish;
  end
endmodule
