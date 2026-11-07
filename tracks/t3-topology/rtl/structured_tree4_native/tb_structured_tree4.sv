`timescale 1ns/1ps
module tb_structured_tree4;
  logic clk=0, rst=1;
  logic [15:0] inject_valid, inject_ready, eject_valid, eject_ready;
  logic [15:0][31:0] inject_data, eject_data;
  logic [15:0][3:0] inject_dest;
  int sent[0:15][0:15];
  int received[0:15][0:15];
  bit [255:0] seen;
  int sent_count=0, received_count=0, stalled_events=0, cycle_count=0;

  always #5 clk=~clk;
  structured_tree4_fabric dut(.*);

  always @(posedge clk) if (!rst) begin
    cycle_count++;
    for (int t=0;t<16;t++) begin
      if (eject_valid[t] && !eject_ready[t]) stalled_events++;
      if (eject_valid[t] && eject_ready[t]) begin
        int source, dest, key;
        source=int'(eject_data[t][31:16]);
        dest=int'(eject_data[t][15:0]);
        if (dest!=t || source>15) $fatal(1,"bad identity tag=%h endpoint=%0d",eject_data[t],t);
        key=source*16+dest;
        if (seen[key]) $fatal(1,"duplicate packet source=%0d dest=%0d",source,dest);
        seen[key]=1; received[source][dest]++; received_count++;
      end
    end
    if (cycle_count>10000) begin
      $display("WATCHDOG sent=%0d received=%0d valid=%h",sent_count,received_count,dut.valid_q);
      $fatal(1,"watchdog sent=%0d received=%0d",sent_count,received_count);
    end
  end

  always @(negedge clk) if (!rst)
    for (int t=0;t<16;t++) eject_ready[t]=((cycle_count+3*t)%7)!=0;

  initial begin
    inject_valid='0; inject_data='0; inject_dest='0; eject_ready='0;
    for (int s=0;s<16;s++) for (int d=0;d<16;d++) begin
      sent[s][d]=0; received[s][d]=0;
    end
    repeat(3) @(negedge clk);
    rst=0;
    // Serialize packets so the single-flit router buffers never form an
    // artificial cyclic buffer dependency. All 256 ordered endpoint pairs
    // still traverse the actual tree links, with deterministic ejection stalls.
    for (int s=0;s<16;s++) for (int d=0;d<16;d++) begin
      bit accepted;
      int expected_received;
      accepted=0;
      expected_received=received_count+1;
      while (!accepted) begin
        @(negedge clk);
        inject_valid='0;
        inject_valid[s]=1'b1;
        inject_data[s]=(s<<16)|d;
        inject_dest[s]=d[3:0];
        @(posedge clk);
        if (inject_ready[s]) begin
          accepted=1; sent[s][d]++; sent_count++;
        end
      end
      @(negedge clk); inject_valid='0;
      wait(received_count==expected_received);
    end
    repeat(2) @(posedge clk);
    for (int s=0;s<16;s++) for (int d=0;d<16;d++)
      if (sent[s][d]!=1 || received[s][d]!=1)
        $fatal(1,"conservation failure (%0d,%0d) sent=%0d recv=%0d",s,d,sent[s][d],received[s][d]);
    if ($countones(seen)!=256) $fatal(1,"unique=%0d",$countones(seen));
    $display("PASS structured_tree4 all_pairs=256 sent=%0d received=%0d unique=%0d stalled_events=%0d cycles=%0d",
      sent_count,received_count,$countones(seen),stalled_events,cycle_count);
    $finish;
  end
endmodule
