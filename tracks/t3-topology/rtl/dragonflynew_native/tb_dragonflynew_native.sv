`timescale 1ns/1ps
`default_nettype none
module tb_dragonflynew_native;
  logic clk=0;
  logic rst=1;
  logic [71:0] inject_valid;
  wire [71:0] inject_ready;
  logic [71:0][31:0] inject_data;
  logic [71:0][6:0] inject_dest;
  wire [71:0] eject_valid;
  logic [71:0] eject_ready;
  wire [71:0][31:0] eject_data;
  wire [71:0][6:0] eject_dest;
  int accepted=0;
  int delivered=0;
  bit seen[0:71][0:71];

  always #5 clk=~clk;
  dragonflynew_native dut(.*);

  task automatic send_pair(input int src, input int dst);
    int cycles;
    bit got;
    begin
      got=0;
      cycles=0;
      @(negedge clk); #1;
      inject_valid='0;
      inject_valid[src]=1'b1;
      inject_dest[src]=7'(dst);
      inject_data[src]=32'hdf000000 | (src<<8) | dst;
      while (!inject_ready[src] && cycles<8) begin
        @(negedge clk); #1;
        cycles++;
      end
      if (!inject_ready[src]) $fatal(1,"injection timeout src=%0d dst=%0d",src,dst);
      @(posedge clk); #1;
      accepted++;
      @(negedge clk); #1;
      inject_valid='0;
      cycles=0;
      while (!got && cycles<20) begin
        if (eject_valid[dst] && eject_ready[dst]) begin
          if (eject_dest[dst] !== 7'(dst)) $fatal(1,"destination mismatch src=%0d dst=%0d got=%0d",src,dst,eject_dest[dst]);
          if (eject_data[dst] !== (32'hdf000000 | (src<<8) | dst)) $fatal(1,"payload mismatch src=%0d dst=%0d",src,dst);
          if (seen[src][dst]) $fatal(1,"duplicate delivery src=%0d dst=%0d",src,dst);
          seen[src][dst]=1'b1;
          got=1;
          @(posedge clk); #1;
          delivered++;
        end else begin
          @(negedge clk); #1;
          cycles++;
        end
      end
      if (!got) $fatal(1,"delivery timeout src=%0d dst=%0d",src,dst);
    end
  endtask

  initial begin
    inject_valid='0;
    inject_data='0;
    inject_dest='0;
    eject_ready='1;
    repeat (3) @(posedge clk);
    @(negedge clk); #1; rst=0;

    // Exhaust every endpoint pair, including local-router and inter-group paths.
    for (int src=0; src<72; src++) begin
      for (int dst=0; dst<72; dst++) begin
        send_pair(src,dst);
      end
    end
    if (accepted!=5184 || delivered!=5184) $fatal(1,"all-pairs count mismatch accepted=%0d delivered=%0d",accepted,delivered);
    for (int src=0; src<72; src++)
      for (int dst=0; dst<72; dst++)
        if (!seen[src][dst]) $fatal(1,"missing pair src=%0d dst=%0d",src,dst);

    // Hold a three-hop inter-group path at its destination ejection.
    @(negedge clk); #1;
    eject_ready[71]=1'b0;
    inject_valid='0;
    inject_valid[0]=1'b1;
    inject_dest[0]=7'd71;
    inject_data[0]=32'hfeed1234;
    while (!inject_ready[0]) @(negedge clk);
    @(posedge clk); #1; accepted++;
    @(negedge clk); #1; inject_valid='0;
    begin
      int wait_cycles;
      wait_cycles=0;
      while (!eject_valid[71] && wait_cycles<12) begin
        @(negedge clk); #1;
        wait_cycles++;
      end
      if (!eject_valid[71]) $fatal(1,"timeout reaching stalled endpoint");
    end
    repeat (4) begin
      @(negedge clk); #1;
      if (!eject_valid[71] || eject_ready[71] || eject_data[71]!==32'hfeed1234 || eject_dest[71]!==7'd71)
        $fatal(1,"egress payload/valid changed under backpressure");
    end
    eject_ready[71]=1'b1;
    #1;
    if (!(eject_valid[71] && eject_ready[71])) $fatal(1,"stalled packet not valid after release");
    @(posedge clk); #1;
    delivered++;
    @(negedge clk); #1;
    if (accepted!=5185 || delivered!=5185 || dut.valid_q!='0)
      $fatal(1,"not drained accepted=%0d delivered=%0d valid=%h",accepted,delivered,dut.valid_q);
    $display("PASS dragonflynew k=2 n=1 routers=36 terminals=72 all_pairs=5184 backpressure=PASS accepted=delivered=5185 drained=1");
    $finish;
  end

  initial begin
    #2000000;
    $fatal(1,"global simulation timeout");
  end
endmodule
`default_nettype wire
