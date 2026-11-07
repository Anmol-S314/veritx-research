`timescale 1ns/1ps
`default_nettype none
module tb_fat_tree_native;
  localparam int N=4;
  logic clk=0,rst=1;
  logic [N-1:0] inject_valid,inject_ready,eject_valid,eject_ready;
  logic [N-1:0][31:0] inject_data,eject_data;
  logic [N-1:0][1:0] inject_dest;
  int accepted[0:N-1][0:N-1], delivered[0:N-1][0:N-1];
  int cycles=0,stalls=0;
  fat_tree_native_fabric dut(.*);
  always #5 clk=~clk;
  function automatic int tb_route_port(input int rid,input int dst);
    int leaf;
    begin
      leaf=dst/2;
      if(rid<2) begin
        if(leaf==rid) tb_route_port=dst%2;
        else tb_route_port=2+leaf;
      end else begin
        tb_route_port=2+leaf;
      end
    end
  endfunction
  initial begin #200000; $fatal(1,"watchdog cycles=%0d",cycles); end
  always @(posedge clk) if(!rst) begin
    cycles++;
    for(int t=0;t<N;t++) begin
      if(eject_valid[t] && eject_ready[t]) begin
        int s,d;
        s=(eject_data[t]>>8)&255; d=eject_data[t]&255;
        if(s>=N || d>=N || (eject_data[t]&32'hffff0000)!=32'hfa7e0000) $fatal(1,"bad payload %h",eject_data[t]);
        if(d!=t) $fatal(1,"misroute %0d->%0d ejected at %0d",s,d,t);
        delivered[s][d]++;
      end else if(eject_valid[t] && !eject_ready[t]) stalls++;
    end
  end
  initial begin
    inject_valid='0; inject_data='0; inject_dest='0; eject_ready='0;
    foreach(accepted[s,d]) begin accepted[s][d]=0; delivered[s][d]=0; end
    repeat(3) @(posedge clk);
    @(negedge clk); rst=0;
    // Exhaustively walk the modeled route and actual canonical neighbor ports.
    for(int s=0;s<N;s++) for(int d=0;d<N;d++) begin
      int r,p;
      r=s/2;
      if(r==d/2) begin
        p=tb_route_port(r,d);
        if(p!=d%2) $fatal(1,"local seat route mismatch");
      end else begin
        p=tb_route_port(r,d);
        if(p<2 || p>3) $fatal(1,"illegal lower transit port");
        // The canonical lower neighbor at port p is upper router p.
        r=p;
        if(r!=2+d/2) $fatal(1,"wrong upper router for %0d->%0d",s,d);
        p=tb_route_port(r,d);
        if(p<2 || p>3) $fatal(1,"illegal upper transit port");
        r=p-2;
        if(r!=d/2) $fatal(1,"wrong lower router after upper hop");
        p=tb_route_port(r,d);
        if(p!=d%2) $fatal(1,"wrong terminal seat at ejection");
      end
    end
    $display("PASS: exhaustive route checks for all 16 pairs");
    for(int d=0;d<N;d++) begin
      logic [N-1:0] pending;
      pending='1;
      @(negedge clk);
      for(int s=0;s<N;s++) begin inject_dest[s]=2'(d); inject_data[s]=32'hfa7e0000|(s<<8)|d; end
      inject_valid=pending;
      while(pending!='0) begin
        @(posedge clk);
        for(int s=0;s<N;s++) if(pending[s] && inject_ready[s]) begin accepted[s][d]++; pending[s]=0; end
        @(negedge clk);
        inject_valid=pending;
        for(int t=0;t<N;t++) eject_ready[t]=((cycles+3*t)%7)>=3;
      end
      @(negedge clk); inject_valid='0;
    end
    for(int timeout=0;timeout<1000;timeout++) begin
      @(negedge clk);
      for(int t=0;t<N;t++) eject_ready[t]=((cycles+3*t)%7)>=3;
      @(posedge clk);
      begin
        bit done;
        done=1;
        for(int s=0;s<N;s++) for(int d=0;d<N;d++) if(accepted[s][d]!=1 || delivered[s][d]!=1) done=0;
        if(done) begin
          @(negedge clk); eject_ready='1;
          repeat(8) @(posedge clk);
          for(int s=0;s<N;s++) for(int d=0;d<N;d++) if(accepted[s][d]!=1 || delivered[s][d]!=1)
            $fatal(1,"conservation failed %0d->%0d",s,d);
          if(eject_valid!='0) $fatal(1,"fabric failed to drain");
          if(stalls==0) $fatal(1,"backpressure not exercised");
          $display("PASS: 16/16 pairs accepted/delivered exactly once, stalls=%0d, drain complete",stalls);
          $finish;
        end
      end
    end
    $fatal(1,"traffic timeout");
  end
endmodule
`default_nettype wire
