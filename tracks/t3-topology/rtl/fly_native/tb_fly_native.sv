`timescale 1ns/1ps
module tb_fly_native;
  logic clk=0, rst=1;
  logic [63:0] inject_valid, inject_ready, eject_valid, eject_ready;
  logic [63:0][31:0] inject_data, eject_data;
  logic [63:0][5:0] inject_dest;
  fly_native_fabric dut(.*);
  always #5 clk<=~clk;

  int expected[64][64];
  bit sent[64][64];
  int delivered=0, accepted=0, cycles=0;
  int next_dest[64];

  initial begin
    inject_valid='0; inject_data='0; inject_dest='0; eject_ready='0;
    for (int s=0;s<64;s++) for (int d=0;d<64;d++) begin
      expected[s][d]=(s<<12)|d;
      sent[s][d]=0;
    end
    repeat (3) @(posedge clk);
    rst=0;
    // All 4096 pairs, each source emits one packet per destination in order.
    // Every terminal injects simultaneously on every available opportunity.
    while (delivered<4096 && cycles<50000) begin
      @(negedge clk);
      cycles++;
      inject_valid='0;
      for (int s=0;s<64;s++) begin
        if (next_dest[s]<64) begin
          inject_valid[s]=1;
          inject_dest[s]=next_dest[s][5:0];
          inject_data[s]=expected[s][next_dest[s]];
        end
      end
      // Deterministic periodic backpressure, including long but finite stalls.
      for (int d=0;d<64;d++) eject_ready[d]=((cycles+d*7)%11<7);
      #1;
      for (int s=0;s<64;s++) if (inject_valid[s] && inject_ready[s]) begin
        next_dest[s]++;
        accepted++;
      end
      for (int d=0;d<64;d++) if (eject_valid[d] && eject_ready[d]) begin
        int data, src, dst;
        data=eject_data[d]; src=(data>>12)&63; dst=data&63;
        if (dst!=d || data!=expected[src][dst] || sent[src][dst]) $fatal(1,"bad/duplicate delivery src=%0d dst=%0d egress=%0d",src,dst,d);
        sent[src][dst]=1; delivered++;
      end
      @(posedge clk);
    end
    if (accepted!=4096 || delivered!=4096) $fatal(1,"count mismatch accepted=%0d delivered=%0d",accepted,delivered);
    // Keep egress ready until fabric is quiescent and prove exact conservation.
    @(negedge clk); inject_valid='0; eject_ready='1;
    repeat (8) @(posedge clk);
    for (int s=0;s<64;s++) for (int d=0;d<64;d++) if (!sent[s][d]) $fatal(1,"loss %0d -> %0d",s,d);
    $display("PASS all 4096 source/destination packets; exact delivery, no loss/duplication; deterministic backpressure; drained in %0d cycles",cycles);
    $finish;
  end
endmodule
