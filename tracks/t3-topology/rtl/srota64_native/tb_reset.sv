`timescale 1ns/1ps
// Reset-under-traffic witness for the SROTA64 native prototype.
//
// Scope: asynchronous reset asserted while flits are live in router slots and
// while upstream drives valid. It checks three properties the pair-sweep
// testbench cannot see:
//   1. While rst_n is low, the fabric must not claim acceptance (inj_ready must
//      be low). A ready assertion during reset silently discards an upstream
//      beat, because the reset branch of the flop wins over the accept branch.
//   2. While rst_n is low, no egress may be valid and no output may be X.
//   3. After reset release, all state must be clear and the complete 4096-pair
//      sweep must still deliver exactly, then drain.
module tb_reset;
  localparam int N=64,W=80;
  logic clk=0,rst_n=0;
  always #5 clk=~clk;
  logic [N-1:0] iv,ir,ev,er;
  logic [N*W-1:0] inf,outf;
  int got,cycle_in_reset;
  srota64_native dut(clk,rst_n,iv,ir,inf,ev,er,outf);

  task automatic check(
    input logic [N-1:0] ir_now, ev_now, input logic [N*W-1:0] outf_now,
    input int tag);
    begin
      if(ir_now !== '0)
        $fatal(1,"reset-under-traffic: inj_ready claimed acceptance during reset (tag=%0d ir=%h)",tag,ir_now);
      if(ev_now !== '0)
        $fatal(1,"reset-under-traffic: egress valid during reset (tag=%0d ev=%h)",tag,ev_now);
      if(^outf_now === 1'bx)
        $fatal(1,"reset-under-traffic: unknown egress data during reset (tag=%0d)",tag);
    end
  endtask

  task automatic transact(input int src,input int dst,input logic [73:0] payload);
    logic [W-1:0] expected, held;
    begin
      expected={dst[5:0],payload};
      @(negedge clk); iv='0; inf='0; er[dst]=0; iv[src]=1; inf[src*W +:W]=expected;
      do @(posedge clk); while(!ir[src]);
      @(negedge clk); iv='0;
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
    iv='0; er='1; inf='0; got=0; cycle_in_reset=0;

    // Phase A: normal reset.
    repeat(3) @(negedge clk); rst_n=1;

    // Phase B: put flits into flight on eight routers, all pointing far away so
    // they sit in express segments rather than ejecting immediately.
    @(negedge clk);
    iv='0; inf='0;
    for(int s=0;s<8;s++) begin
      logic [5:0] dd; logic [W-1:0] fl;
      dd = 6'(63-s);
      fl = {dd, 74'd0};
      fl[73:0] = 74'(s) + 74'h1000;
      iv[s]=1'b1;
      inf[s*W +:W]=fl;
    end
    // Acknowledge some of them, so slots are definitely occupied.
    repeat(2) begin @(posedge clk); end
    @(negedge clk);
    if(dut.busy === '0) $fatal(1,"reset-under-traffic: no live traffic before reset");
    // Keep upstream driving valid across the reset edge: this is the case that
    // exposes a reset-time acceptance claim.
    iv='1;

    // Phase C: assert reset with traffic live and valid asserted.
    rst_n=0;
    for(int i=0;i<4;i++) begin
      @(negedge clk);
      cycle_in_reset++;
      check(ir,ev,outf,cycle_in_reset);
      if(dut.busy !== '0) $fatal(1,"reset-under-traffic: busy slots survived reset (tag=%0d busy=%h)",cycle_in_reset,dut.busy);
    end
    for(int z=0;z<64;z++)
      if(dut.q[z] !== '0) $fatal(1,"reset-under-traffic: payload register %0d not cleared by reset (q=%h)",z,dut.q[z]);

    // Phase D: release reset and prove the fabric is fully functional again.
    @(negedge clk); iv='0; rst_n=1;
    @(negedge clk);
    if(dut.busy !== '0 || ev !== '0) $fatal(1,"reset-under-traffic: fabric not idle after reset release");
    for(int s=0;s<64;s++) for(int d=0;d<64;d++) transact(s,d,((s*64+d)^32'h5a17c0de));
    repeat(4) @(posedge clk);
    if(got!=4096 || dut.busy!='0) $fatal(1,"post-reset conservation/drain got=%0d busy=%h",got,dut.busy);
    if(dut.segid(0,0,0,1)!=1 || dut.segid(1,0,0,1)!=129) $fatal(1,"post-reset segment index mapping");
    $display("PASS reset-under-traffic: no acceptance claim during reset, idle egress, state cleared, 4096/4096 pairs after release");
    $finish;
  end
  initial begin #20000000; $fatal(1,"timeout"); end
endmodule
