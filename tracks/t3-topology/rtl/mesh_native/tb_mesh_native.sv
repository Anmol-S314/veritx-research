`timescale 1ns/1ps
`default_nettype none
module tb_mesh_native;
  localparam int N=16, TOTAL=N*N, DATA_W=16;
  logic clk=0, rst=1;
  always #5 clk=~clk;
  logic [N-1:0] inject_valid, inject_ready, eject_valid, eject_ready;
  logic [N-1:0][DATA_W-1:0] inject_data;
  logic [N-1:0][3:0] inject_dest;
  logic [N-1:0][DATA_W-1:0] eject_data;
  bit sent[N][N], received[N][N];
  int sent_count=0, recv_count=0;
  int cycle=0;
  mesh_native #(.DATA_W(DATA_W)) dut(.*);

  initial begin
    inject_valid='0; inject_data='0; inject_dest='0; eject_ready='0;
    repeat (4) @(negedge clk);
    rst=0;
    while (recv_count<TOTAL && cycle<3000) begin
      @(negedge clk);
      cycle++;
      for (int s=0;s<N;s++) begin
        // Every source emits to every destination, including itself, in a
        // fixed permutation. Injection holds the same flit until accepted.
        if (!sent[s][(cycle-1)%N]) begin
          inject_valid[s]=1;
          inject_dest[s]=4'((cycle-1)%N);
          inject_data[s]=DATA_W'((s<<8)|((cycle-1)%N));
        end else inject_valid[s]=0;
        // Repeatable endpoint backpressure with non-identical phase per sink.
        eject_ready[s]=((cycle+3*s)%7)!=0;
      end
      @(posedge clk);
      for (int s=0;s<N;s++) begin
        if (inject_valid[s] && inject_ready[s]) begin
          int d;
          d=int'(inject_dest[s]);
          if (sent[s][d]) $fatal(1,"duplicate injection src=%0d dst=%0d",s,d);
          sent[s][d]=1; sent_count++;
        end
        if (eject_valid[s] && eject_ready[s]) begin
          int src,dst;
          src=int'(eject_data[s][15:8]); dst=int'(eject_data[s][7:0]);
          if (src>=N || dst>=N) $fatal(1,"bad payload %h",eject_data[s]);
          if (s!=dst) $fatal(1,"wrong sink got=%0d expected=%0d payload=%h",s,dst,eject_data[s]);
          if (!sent[src][dst]) $fatal(1,"ejected before accepted src=%0d dst=%0d",src,dst);
          if (received[src][dst]) $fatal(1,"duplicate ejection src=%0d dst=%0d",src,dst);
          received[src][dst]=1; recv_count++;
        end
      end
    end
    @(negedge clk);
    inject_valid='0;
    if (recv_count!=TOTAL) $fatal(1,"timeout cycle=%0d sent=%0d received=%0d expected=%0d",cycle,sent_count,recv_count,TOTAL);
    if (sent_count!=TOTAL) $fatal(1,"conservation mismatch sent=%0d received=%0d",sent_count,recv_count);
    for (int s=0;s<N;s++) for (int d=0;d<N;d++)
      if (!sent[s][d] || !received[s][d]) $fatal(1,"missing pair %0d -> %0d",s,d);
    repeat (3) @(posedge clk);
    for (int s=0;s<N;s++) if (eject_valid[s]) $fatal(1,"not drained at endpoint %0d",s);
    $display("PASS mesh_native all_pairs=%0d injected=%0d ejected=%0d cycles=%0d drained=1",TOTAL,sent_count,recv_count,cycle);
    $finish;
  end
endmodule
`default_nettype wire
