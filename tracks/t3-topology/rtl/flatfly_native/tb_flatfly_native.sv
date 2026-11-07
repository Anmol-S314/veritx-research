`timescale 1ns/1ps
module tb_flatfly_native;
  logic clk=0, rst=1;
  logic [15:0] inject_valid, inject_ready, eject_valid, eject_ready;
  logic [15:0][31:0] inject_data, eject_data;
  logic [15:0][3:0] inject_dest;
  flatfly_native_fabric dut(.*);
  always #5 clk<=~clk;

  bit sent[16][16];
  int next_dest[16];
  int accepted=0, delivered=0, cycles=0;
  initial begin
    inject_valid='0; inject_data='0; inject_dest='0; eject_ready='0;
    for (int s=0;s<16;s++) for (int d=0;d<16;d++) sent[s][d]=0;
    repeat (3) @(posedge clk);
    rst=0;
    // Every source sends one complete one-flit packet to every destination.
    while (delivered<256 && cycles<10000) begin
      @(negedge clk);
      cycles++;
      inject_valid='0;
      for (int s=0;s<16;s++) if (next_dest[s]<16) begin
        inject_valid[s]=1;
        inject_dest[s]=next_dest[s][3:0];
        inject_data[s]={28'(s),4'(next_dest[s])};
      end
      // Bounded periodic stalls exercise the ready/valid hold behavior.
      for (int d=0;d<16;d++) eject_ready[d]=((cycles+d*5)%9<5);
      #1;
      for (int s=0;s<16;s++) if (inject_valid[s] && inject_ready[s]) begin
        next_dest[s]++; accepted++;
      end
      for (int d=0;d<16;d++) if (eject_valid[d] && eject_ready[d]) begin
        int payload, src, dst;
        payload=eject_data[d]; src=(payload>>4)&15; dst=payload&15;
        if (src>=16 || dst>=16 || dst!=d || eject_data[d]!=={28'(src),4'(dst)} || sent[src][dst])
          $fatal(1,"bad/duplicate packet src=%0d dst=%0d egress=%0d",src,dst,d);
        sent[src][dst]=1; delivered++;
      end
      @(posedge clk);
    end
    if (accepted!=256 || delivered!=256) $fatal(1,"count mismatch accepted=%0d delivered=%0d",accepted,delivered);
    @(negedge clk); inject_valid='0; eject_ready='1;
    repeat (12) @(posedge clk);
    for (int s=0;s<16;s++) for (int d=0;d<16;d++)
      if (!sent[s][d]) $fatal(1,"missing packet %0d -> %0d",s,d);
    if (|eject_valid) $fatal(1,"fabric failed to drain");
    $display("PASS flatfly k=4 n=2 c=1, 16 routers/endpoints; all 256 ordered pairs delivered exactly once under stalls; accepted=%0d delivered=%0d cycles=%0d drain=PASS",accepted,delivered,cycles);
    $finish;
  end
endmodule
