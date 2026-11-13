`timescale 1ns/1ps
// Experimental K=8 SROTA row+column express graph.
// Explicit segment slots indexed by (axis,line,anchor,direction); each slot
// has one source driver and ordered passive taps. Fixed row-first routing.
module srota64_native #(
  parameter int K=8, N=64, W=80, SEG=256
)(
  input logic clk, rst_n,
  input logic [N-1:0] inj_valid,
  output logic [N-1:0] inj_ready,
  input logic [N*W-1:0] inj_flit,
  output logic [N-1:0] eject_valid,
  input logic [N-1:0] eject_ready,
  output logic [N*W-1:0] eject_flit
);
  // Flit [79:74] is destination router, [73:0] is opaque payload.
  logic [N-1:0] busy, ejected, sent;
  logic [W-1:0] q[N];
  logic [SEG-1:0] seg_valid;
  logic [W-1:0] seg_data[SEG];
  logic [3:0] seg_drop[SEG];
  logic [5:0] seg_src[SEG], seg_dst[SEG];
  logic [N-1:0] reserved;

  function automatic int segid(input int axis,input int line,input int anchor,input int sign);
    // Slots 0..255; 224 are valid directed source/direction segments.
    // Function-name assignment rather than `return`, so synthesizers that do not
    // implement the SystemVerilog return statement can read this file too.
    segid = (((axis*8+line)*8+anchor)*2+sign);
  endfunction
  always_comb begin : route_and_tap
    int x,y,dx,dy,axis,line,anchor,sign,drop,dst,sid,source;
    seg_valid='0; eject_valid='0; eject_flit='0;
    ejected='0; sent='0; reserved='0; inj_ready='0;
    for(int z=0;z<SEG;z++) begin seg_data[z]='0; seg_drop[z]='0; seg_src[z]='0; seg_dst[z]='0; end
    // Every active router is the unique driver of exactly one directed
    // segment. The selected passive sink is tap[drop], where drop=distance-1.
    for(int z=0;z<N;z++) if(busy[z]) begin
      dx=q[z][79:74]%8; dy=q[z][79:74]/8; x=z%8; y=z/8;
      eject_flit[z*W +: W]=q[z];
      if(z==q[z][79:74]) begin
        eject_valid[z]=1'b1;
        if(eject_ready[z]) ejected[z]=1'b1;
      end else begin
        axis=(x!=dx)?0:1;
        if(axis==0) begin line=y; anchor=x; sign=(dx>x); drop=(dx>x)?dx-x-1:x-dx-1; dst=y*8+dx; end
        else begin line=x; anchor=y; sign=(dy>y); drop=(dy>y)?dy-y-1:y-dy-1; dst=dy*8+x; end
        sid=segid(axis,line,anchor,sign);
        // One source router drives at most one directed segment. Segment
        // identity includes its unique source anchor and direction.
        seg_valid[sid]=1'b1; seg_data[sid]=q[z]; seg_drop[sid]=drop[3:0];
        seg_src[sid]=z[5:0]; seg_dst[sid]=dst[5:0];
      end
    end
    // Passive tap acceptance: each segment drives at most its selected drop.
    // If multiple segments request one peer input, fixed slot-order priority
    // grants one. A peer becoming free by ejection can accept immediately.
    for(int sid=0;sid<SEG;sid++) if(seg_valid[sid]) begin
      dst=seg_dst[sid]; source=seg_src[sid];
      if((!busy[dst] || ejected[dst]) && !reserved[dst]) begin
        reserved[dst]=1'b1; sent[source]=1'b1;
      end
    end
    // Segment arrival wins over injection at a shared one-entry router slot.
    // Existing flit replacement after ejection or successful forwarding is
    // otherwise allowed when no incoming segment has reserved the slot.
    // Ready must be suppressed during reset: the reset branch of the flop wins
    // over the accept branch, so asserting ready here silently discards an
    // upstream beat instead of holding it. Found by tb_reset.sv.
    for(int z=0;z<N;z++) inj_ready[z]=rst_n && (!busy[z] || ejected[z] || sent[z]) && !reserved[z];
  end
  always_ff @(posedge clk or negedge rst_n) begin
    if(!rst_n) begin busy<='0; for(int z=0;z<N;z++) q[z]<='0; end
    else begin
      for(int z=0;z<N;z++) begin
        if(ejected[z] || sent[z]) busy[z]<=1'b0;
        if(inj_valid[z] && inj_ready[z]) begin busy[z]<=1'b1; q[z]<=inj_flit[z*W +: W]; end
      end
      for(int sid=0;sid<SEG;sid++) if(seg_valid[sid] && sent[seg_src[sid]]) begin
        busy[seg_dst[sid]]<=1'b1; q[seg_dst[sid]]<=seg_data[sid];
      end
    end
  end
endmodule
