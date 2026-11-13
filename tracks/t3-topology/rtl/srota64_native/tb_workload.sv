`timescale 1ns/1ps
// Workload replay driver for the SROTA64 native prototype.
//
// Stimulus file, one packet per line, sorted by send cycle:
//     <send_cycle> <src> <dst> <packet_id>
// Delivery file, one line per accepted egress beat:
//     <packet_id> <inject_router> <eject_router> <dst_field> <inject_cycle> <eject_cycle>
//
// The driver injects strictly in trace order (head-of-line, one injection per
// cycle, waiting while the head packet's source router is busy) and accepts
// every egress beat immediately. The sink is therefore always ready, and the
// head-of-line discipline is a property of this driver, not of the fabric.
// Packet identity travels in payload bits [73:58]; bits [57:54] carry a
// redundant destination tag that the DUT must preserve unmodified.
module tb_workload;
  localparam int N=64,W=80,MAXP=8192;
  logic clk=0,rst_n=0;
  always #5 clk=~clk;
  logic [N-1:0] iv,ir,ev,er;
  logic [N*W-1:0] inf,outf;

  int   send_cyc[MAXP];
  int   src_idx[MAXP];
  int   dst_idx[MAXP];
  int   pkt_id[MAXP];
  int   inject_cyc[65536];
  int   inject_src[65536];
  bit   seen[65536];

  int fd_in, fd_out, n_seq, pkt_total, next_idx, n_delivered, max_lat, sum_lat;
  int stop;
  string stim_path, deliv_path;

  srota64_native dut(clk,rst_n,iv,ir,inf,ev,er,outf);

  function automatic logic [W-1:0] make_flit(input int dst, input int id);
    logic [W-1:0] f;
    f        = '0;
    f[79:74] = 6'(dst);
    f[73:58] = 16'(id);
    f[57:54] = 4'(dst[5:2]);
    return f;
  endfunction

  initial begin
    if(!$value$plusargs("stimulus=%s",stim_path))    $fatal(1,"missing +stimulus");
    if(!$value$plusargs("deliveries=%s",deliv_path)) $fatal(1,"missing +deliveries");
    if(!$value$plusargs("packets=%d",pkt_total))     $fatal(1,"missing +packets");
    fd_in=$fopen(stim_path,"r");
    if(fd_in==0) $fatal(1,"cannot open stimulus %s",stim_path);
    n_seq=0; stop=0;
    while(!stop && !$feof(fd_in) && n_seq<MAXP) begin
      int sc,s,d,i,rc;
      rc=$fscanf(fd_in,"%d %d %d %d\n",sc,s,d,i);
      if(rc!=4) stop=1;
      else begin
        if(s<0||s>=N||d<0||d>=N) $fatal(1,"bad endpoint in stimulus s=%0d d=%0d",s,d);
        if(n_seq>0 && sc<send_cyc[n_seq-1]) $fatal(1,"stimulus not sorted by send cycle at record %0d",n_seq);
        send_cyc[n_seq]=sc; src_idx[n_seq]=s; dst_idx[n_seq]=d; pkt_id[n_seq]=i; n_seq++;
      end
    end
    $fclose(fd_in);
    if(n_seq!=pkt_total) $fatal(1,"stimulus holds %0d packets, expected %0d",n_seq,pkt_total);
    fd_out=$fopen(deliv_path,"w");
    if(fd_out==0) $fatal(1,"cannot open %s",deliv_path);
    iv='0; er='1; inf='0;
    next_idx=0; n_delivered=0; max_lat=0; sum_lat=0;
    for(int i=0;i<65536;i++) begin inject_cyc[i]=-1; inject_src[i]=-1; end
    repeat(3) @(negedge clk); rst_n=1;
  end

  always @(negedge clk) if(rst_n) begin
    int cycle, id, dst;
    logic [W-1:0] f;
    cycle=$time/10;
    iv='0;
    for(int z=0;z<N;z++) if(ev[z] && er[z]) begin
      f   = outf[z*W +:W];
      id  = f[73:58];
      dst = f[79:74];
      if(seen[id]) $fatal(1,"duplicate delivery of packet id %0d",id);
      if(f[57:54] !== 4'(dst[5:2]))
        $fatal(1,"payload tag corrupted on id %0d at router %0d",id,z);
      if(id>=pkt_total) $fatal(1,"delivered unknown packet id %0d",id);
      seen[id]=1'b1;
      $fdisplay(fd_out,"%0d %0d %0d %0d %0d %0d",id,inject_src[id],z,dst,inject_cyc[id],cycle);
      n_delivered++;
      if(cycle-inject_cyc[id]>max_lat) max_lat=cycle-inject_cyc[id];
      sum_lat+=cycle-inject_cyc[id];
    end
    if(next_idx<n_seq && send_cyc[next_idx]<=cycle && ir[src_idx[next_idx]]) begin
      iv[src_idx[next_idx]]=1'b1;
      inf[src_idx[next_idx]*W +:W]=make_flit(dst_idx[next_idx],pkt_id[next_idx]);
      inject_cyc[pkt_id[next_idx]]=cycle;
      inject_src[pkt_id[next_idx]]=src_idx[next_idx];
      next_idx++;
    end
    if(n_delivered==pkt_total) begin
      $fclose(fd_out);
      $display("REPLAY_DONE packets=%0d delivered=%0d max_latency=%0d mean_latency_x100=%0d cycles=%0d",
               pkt_total,n_delivered,max_lat,(sum_lat*100)/pkt_total,cycle);
      $finish;
    end
    if(cycle>2000000) begin
      $fdisplay(fd_out,"%0d","STALLED");
      $fclose(fd_out);
      $fatal(1,"replay stalled: %0d of %0d delivered, injected %0d of %0d",n_delivered,pkt_total,next_idx,n_seq);
    end
  end
endmodule
