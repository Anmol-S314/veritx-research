`timescale 1ns/1ps
`default_nettype none
module tb_dragonfly4_native;
  logic clk=0, rst=1;
  always #5 clk=~clk;
  logic [3:0] inject_valid;
  logic [3:0] inject_ready;
  logic [3:0][31:0] inject_data;
  logic [3:0][1:0] inject_dest;
  wire [3:0] eject_valid;
  logic [3:0] eject_ready;
  wire [3:0][31:0] eject_data;
  wire [3:0][1:0] eject_dest;
  int accepted, delivered;
  bit seen[0:3][0:3];
  dragonfly4_native dut(.*);

  task automatic tick;
    @(posedge clk); #1;
  endtask

  initial begin
    accepted=0; delivered=0;
    inject_valid='0; inject_data='0; inject_dest='0; eject_ready='1;
    repeat (2) @(posedge clk);
    @(negedge clk);
    rst=0;
    // Serialize all 16 ordered pairs to isolate each exact route and payload.
    for (int src=0; src<4; src++) begin
      for (int dst=0; dst<4; dst++) begin
        int cycles;
        bit got;
        got=0; cycles=0;
        @(negedge clk); #1;
        inject_valid='0;
        inject_dest='0;
        inject_data='0;
        inject_valid[src]=1'b1;
        inject_dest[src]=2'(dst);
        inject_data[src]=32'hd4000000 | (src<<8) | dst;
        @(posedge clk);
        #1;
        accepted++;
        @(negedge clk); #1;
        inject_valid='0;
        while (!got && cycles<20) begin
          if (eject_valid[dst] && eject_ready[dst]) begin
            if (eject_dest[dst] !== 2'(dst)) $fatal(1,"dest mismatch %0d->%0d",src,dst);
            if (eject_data[dst] !== (32'hd4000000 | (src<<8) | dst)) $fatal(1,"payload mismatch %0d->%0d",src,dst);
            if (seen[src][dst]) $fatal(1,"duplicate %0d->%0d",src,dst);
            seen[src][dst]=1; got=1;
            delivered++;
            @(posedge clk);
          end else begin @(posedge clk); cycles++; #1; end
        end
        if (!got) $fatal(1,"timeout %0d->%0d",src,dst);
      end
    end
    if (accepted != 16 || delivered != 16) $fatal(1,"count mismatch accepted=%0d delivered=%0d",accepted,delivered);
    for (int s=0;s<4;s++) for (int d=0;d<4;d++) if (!seen[s][d]) $fatal(1,"missing pair");

    // Deterministic output backpressure: hold destination 3, then prove stable.
    @(negedge clk); #1; eject_ready='1; eject_ready[3]=0;
    inject_valid='0;
    @(negedge clk); #1;
    inject_valid[0]=1'b1; inject_dest[0]=2'd3; inject_data[0]=32'hfeed1234;
    while (!inject_ready[0]) @(negedge clk);
    @(posedge clk); #1; accepted++;
    @(negedge clk); #1; inject_valid='0;
    begin
      int wait_cycles;
      wait_cycles=0;
      while (!eject_valid[3] && wait_cycles<8) begin
        @(negedge clk); #1;
        wait_cycles++;
      end
      if (!eject_valid[3]) $fatal(1,"timeout waiting for backpressured flit to reach ejection");
    end
    repeat (4) begin
      @(negedge clk); #1;
      if (!eject_valid[3] || eject_ready[3] || eject_data[3] !== 32'hfeed1234 || eject_dest[3] !== 2'd3)
        $fatal(1,"flit not stable under output backpressure: valid=%b ready=%b data=%h dest=%h q=%b",eject_valid[3],eject_ready[3],eject_data[3],eject_dest[3],dut.valid_q);
    end
    eject_ready[3]=1;
    @(posedge clk);
    if (!(eject_valid[3] && eject_ready[3])) $fatal(1,"expected final transfer");
    delivered++;
    #1;
    @(negedge clk); #1;
    if (eject_valid[3]) $fatal(1,"did not drain after ready");
    if (accepted != delivered) $fatal(1,"accepted=%0d delivered=%0d",accepted,delivered);
    if (eject_valid[3] || eject_ready[3] !== 1'b1 || inject_ready !== 4'b1111)
      $fatal(1,"fabric not drained or ready state wrong");
    $display("PASS dragonfly4_native: 16/16 ordered pairs, backpressure stability, accepted=delivered=%0d, drained",accepted);
    $finish;
  end
endmodule
`default_nettype wire
