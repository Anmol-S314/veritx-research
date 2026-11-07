`default_nettype none
module tb_qtree_native;
  localparam int N=64;
  logic clk=0, rst=1;
  logic [N-1:0] inject_valid,inject_ready,eject_valid,eject_ready;
  logic [N-1:0][31:0] inject_data,eject_data;
  logic [N-1:0][5:0] inject_dest;
  int seen [0:N-1][0:N-1];
  int accepted [0:N-1][0:N-1];
  int cycles=0;
  int backpressure_cycles=0;
  qtree_native_fabric dut(.*);
  always #5 clk=~clk;
  initial begin
    #100000;
    $fatal(1,"global simulation watchdog expired at cycle %0d",cycles);
  end

  // Scoreboard observes every transfer, including while the driver overlaps
  // waves. Ready is deliberately withdrawn in a deterministic rotating pattern.
  always @(posedge clk) if (!rst) begin
    cycles++;
    for (int t=0;t<N;t++) begin
      if (eject_valid[t] && eject_ready[t]) begin
        int src,dst;
        src=(eject_data[t]>>8)&'hff; dst=eject_data[t]&'hff;
        if (src>=N || dst>=N || ((eject_data[t]&32'hffff0000)!=32'h51000000)) $fatal(1,"bad payload %h",eject_data[t]);
        if (t!=dst) $fatal(1,"packet %0d->%0d ejected at %0d",src,dst,t);
        seen[src][dst]++;
      end else if (eject_valid[t] && !eject_ready[t]) backpressure_cycles++;
    end
  end

  initial begin
    inject_valid='0; inject_data='0; inject_dest='0; eject_ready='0;
    foreach(seen[s,d]) begin seen[s][d]=0; accepted[s][d]=0; end
    repeat(3) @(posedge clk);
    @(negedge clk); rst=0;

    // Sixteen overlapping waves. All sources inject simultaneously, each wave
    // targets one terminal, exercising arbitration and shared-tree contention.
    for (int d=0;d<N;d++) begin
      $display("inject wave destination=%0d",d);
      @(negedge clk);
      inject_valid='1;
      for (int s=0;s<N;s++) begin
        inject_dest[s]=d;
        inject_data[s]=32'h51000000 | (s<<8) | d;
      end
      begin
        logic [N-1:0] pending;
        pending='1;
        while (pending!='0) begin
          @(posedge clk);
          for (int s=0;s<N;s++) if (pending[s] && inject_ready[s]) begin
            accepted[s][d]++;
            pending[s]=1'b0;
          end
          @(negedge clk);
          inject_valid=pending;
          // Egress stalls for 3 of every 8 cycles, phase-shifted per terminal.
          for (int t=0;t<N;t++) eject_ready[t]=((cycles+t)%8)>=3;
        end
      end
      @(negedge clk); inject_valid='0;
    end

    // Keep applying bounded backpressure until every pair is delivered once.
    for (int timeout=0;timeout<3000;timeout++) begin
      @(negedge clk);
      for (int t=0;t<N;t++) eject_ready[t]=((cycles+t)%8)>=3;
      @(posedge clk);
      begin
        bit done;
        done=1;
        for (int s=0;s<N;s++) for (int d=0;d<N;d++) begin
          if (accepted[s][d]!=1 || seen[s][d]!=1) done=0;
        end
        if(done) begin
          @(negedge clk); eject_ready='1;
          repeat(5) @(posedge clk);
          for (int s=0;s<N;s++) for (int d=0;d<N;d++)
            if(accepted[s][d]!=1 || seen[s][d]!=1) $fatal(1,"conservation failure %0d->%0d accepted=%0d seen=%0d",s,d,accepted[s][d],seen[s][d]);
          if(eject_valid!='0) $fatal(1,"fabric failed to drain");
          if(backpressure_cycles==0) $fatal(1,"test failed to exercise egress backpressure");
          $display("PASS: 4096/4096 pairs accepted and delivered exactly once; identity preserved; backpressure cycles=%0d; drain complete",backpressure_cycles);
          $finish;
        end
      end
    end
    $fatal(1,"timeout: pairs missing or duplicated");
  end
endmodule
`default_nettype wire
