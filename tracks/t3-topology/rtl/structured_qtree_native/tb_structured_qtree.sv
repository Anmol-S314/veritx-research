`default_nettype none
module tb_structured_qtree;
  localparam int N=21;
  logic clk=0, rst=1;
  logic [N-1:0] inject_valid, inject_ready, eject_valid, eject_ready;
  logic [N-1:0][31:0] inject_data, eject_data;
  logic [N-1:0][4:0] inject_dest;
  int accepted[0:N-1][0:N-1], delivered[0:N-1][0:N-1];
  int cycles=0, stalls=0;
  int accepted_total=0, delivered_total=0;
  structured_qtree_fabric dut(.*);
  always #5 clk=~clk;
  initial begin #1000000; $fatal(1,"watchdog cycle=%0d accepted=%0d",cycles,accepted_total); end

  always @(posedge clk) if (!rst) begin
    cycles++;
    for (int t=0;t<N;t++) if (eject_valid[t]) begin
      if (!eject_ready[t]) stalls++;
      else begin
        int s,d;
        s=(eject_data[t] >> 8) & 'hff;
        d=eject_data[t] & 'hff;
        if (s>=N || d>=N || t!=d || (eject_data[t]&32'hffff0000)!=32'h72000000)
          $fatal(1,"bad ejection terminal=%0d payload=%h",t,eject_data[t]);
        delivered[s][d]++;
        delivered_total++;
        if (delivered[s][d]>1) $fatal(1,"duplicate delivery %0d->%0d",s,d);
      end
    end
  end

  initial begin
    inject_valid='0; inject_data='0; inject_dest='0; eject_ready='0;
    foreach (accepted[s,d]) begin accepted[s][d]=0; delivered[s][d]=0; end
    repeat (3) @(posedge clk);
    @(negedge clk); rst=0;
    // One destination wave at a time. Hold valid/data stable through every
    // rising-edge transfer; sample ready in the active region before NBA.
    for (int d=0;d<N;d++) begin
      logic [N-1:0] pending;
      pending='1;
      for (int s=0;s<N;s++) begin
        inject_dest[s]=5'(d);
        inject_data[s]=32'h72000000 | (s<<8) | d;
      end
      @(negedge clk); inject_valid=pending;
      while (pending!='0) begin
        @(posedge clk);
        for (int s=0;s<N;s++) if (pending[s] && inject_ready[s]) begin
          accepted[s][d]++;
          accepted_total++;
          pending[s]=1'b0;
        end
        if (pending!='0 && d==6 && (cycles%1000)==0)
          $display("stuck d6 pending=%h ready=%h rootvalid=%b rootdata=%h p4valid=%b p4data=%h p1valid=%b p1data=%h",pending,inject_ready,dut.ov[0],dut.odata[0],dut.ov[5],dut.odata[5],dut.ov[2],dut.odata[2]);
        @(negedge clk);
        inject_valid=pending;
        for (int t=0;t<N;t++) eject_ready[t]=((cycles+t)%7)>=3;
      end
      @(negedge clk); inject_valid='0;
    end

    $display("INJECTION COMPLETE accepted=%0d cycles=%0d",accepted_total,cycles);
    // Drain under deterministic stalls, then remove stalls to complete.
    for (int timeout=0;timeout<10000;timeout++) begin
      @(negedge clk);
      for (int t=0;t<N;t++) eject_ready[t]=((cycles+t)%7)>=3;
      @(posedge clk);
      begin
        bit done;
        done=1;
        for (int s=0;s<N;s++) for (int d=0;d<N;d++)
          if (accepted[s][d]!=1) done=0;
        if (done) break;
      end
    end
    @(negedge clk); inject_valid='0; eject_ready='1;
    begin
      bit all_delivered;
      all_delivered=0;
      for (int timeout=0;timeout<10000 && !all_delivered;timeout++) begin
        @(posedge clk);
        all_delivered=1;
        for (int s=0;s<N;s++) for (int d=0;d<N;d++)
          if (delivered[s][d]!=1) all_delivered=0;
      end
      if (!all_delivered) $fatal(1,"delivery timeout accepted=%0d delivered=%0d",accepted_total,delivered[0][0]);
    end
    @(negedge clk);
    if (eject_valid!='0) $fatal(1,"egress did not drain");
    for (int s=0;s<N;s++) for (int d=0;d<N;d++) begin
      if (accepted[s][d]!=1 || delivered[s][d]!=1)
        $fatal(1,"conservation %0d->%0d accepted=%0d delivered=%0d",s,d,accepted[s][d],delivered[s][d]);
    end
    if (stalls==0) $fatal(1,"test did not apply egress backpressure");
    if (accepted_total!=N*N || delivered_total!=N*N)
      $fatal(1,"total conservation accepted=%0d delivered=%0d expected=%0d",accepted_total,delivered_total,N*N);
    $display("PASS structured_qtree pairs=%0d accepted=%0d delivered=%0d stalls=%0d cycles=%0d drained=1",
      N*N,accepted_total,delivered_total,stalls,cycles);
    $finish;
  end
endmodule
`default_nettype wire
