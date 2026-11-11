`timescale 1ns/1ps
module tb;
  localparam int N=64,W=80;
  logic clk=0,rst_n=0;
  always #5 clk=~clk;
  logic [N-1:0] iv,ir,ev,er;
  logic [N*W-1:0] inf,outf;
  int got;
  srota64_native dut(clk,rst_n,iv,ir,inf,ev,er,outf);
  always @(negedge clk) if(rst_n) begin
    int src,dst,sx,sy,dx,dy,axis,line,anchor,sign,drop,sid;
    for(int z=0;z<64;z++) if(dut.busy[z] && z!=dut.q[z][79:74]) begin
      src=z; dst=dut.q[z][79:74]; sx=src%8; sy=src/8; dx=dst%8; dy=dst/8;
      axis=(sx!=dx)?0:1;
      if(axis==0) begin line=sy; anchor=sx; sign=(dx>sx); drop=(dx>sx)?dx-sx-1:sx-dx-1; end
      else begin line=sx; anchor=sy; sign=(dy>sy); drop=(dy>sy)?dy-sy-1:sy-dy-1; end
      sid=dut.segid(axis,line,anchor,sign);
      if(!dut.seg_valid[sid] || dut.seg_src[sid]!==src || dut.seg_dst[sid]!==((axis==0)?sy*8+dx:dy*8+sx) || dut.seg_drop[sid]!==drop)
        $fatal(1,"RTL segment/drop mismatch src=%0d dst=%0d axis=%0d drop=%0d",src,dst,axis,drop);
    end
  end
  task automatic transact(input int src,input int dst,input logic [73:0] payload);
    logic [W-1:0] expected, held;
    begin
      expected={dst[5:0],payload};
      @(negedge clk); iv='0; inf='0; er[dst]=0; iv[src]=1; inf[src*W +:W]=expected;
      do @(posedge clk); while(!ir[src]);
      @(negedge clk); iv='0;
      // Wait for destination valid, then force backpressure and assert stability.
      wait(ev[dst]); @(negedge clk); er='0; held=outf[dst*W +:W];
      repeat(3) begin
        @(posedge clk); #1;
        if(!ev[dst] || outf[dst*W +:W] !== held) $fatal(1,"unstable under stall %0d->%0d",src,dst);
      end
      @(negedge clk); er[dst]=1;
      @(posedge clk);
      if(!ev[dst] || outf[dst*W +:W] !== expected) $fatal(1,"bad flit %0d->%0d",src,dst);
      got++;
      @(negedge clk); er='1;
    end
  endtask
  initial begin
    iv='0; er='1; inf='0; got=0;
    repeat(3) @(negedge clk); rst_n=1;
    for(int s=0;s<64;s++) for(int d=0;d<64;d++) transact(s,d,((s*64+d)^32'h5a17c0de));
    repeat(4) @(posedge clk);
    if(got!=4096 || dut.busy!='0) $fatal(1,"conservation/drain got=%0d busy=%h",got,dut.busy);
    // Explicit long express checks: each row segment has outward taps 0..6.
    if(dut.segid(0,0,0,1)!=1 || dut.segid(1,0,0,1)!=129) $fatal(1,"segment index mapping");
    $display("PASS pairs=4096 payload/dest exact, stable egress stall, drain; segment mapping checked");
    $finish;
  end
  initial begin #10000000; $fatal(1,"timeout"); end
endmodule
