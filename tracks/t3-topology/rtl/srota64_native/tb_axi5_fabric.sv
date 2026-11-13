`default_nettype none
`timescale 1ns/1ps
// AXI5 transaction suite through the real SROTA64 fabric.
//
// Every endpoint is an `axi5_srota_ep` bridge attached to one router of the
// `srota64_native` fabric. Each bridge owns a 16-word memory, so a write from
// endpoint S to endpoint D is a real AXI5 write-address, write-data and
// write-response handshake whose data crosses the fabric, and the read that
// follows is a real read-address and read-data handshake answered by D.
//
// Checks, in order:
//   1. All 4096 ordered endpoint pairs: write then read one word, with BID and
//      RID equal to the issued ids and read data equal to written data.
//   2. Byte strobes: a masked write must merge per lane, not replace the word.
//   3. Two independent transactions in flight at once on different pairs.
//   4. Fabric drains, with every router's slot empty at the end.
module tb_axi5_fabric;

  localparam int N = 64;
  localparam int W = 80;

  logic clk = 1'b0;
  always #5 clk = ~clk;
  logic rst_n = 1'b0;

  // AXI5 side, per endpoint.
  logic [63:0] awaddr  [N];
  logic [7:0]  awid    [N];
  logic        awvalid [N];
  logic        awready [N];
  logic [31:0] wdata   [N];
  logic [3:0]  wstrb   [N];
  logic        wlast   [N];
  logic        wvalid  [N];
  logic        wready  [N];
  logic [7:0]  bid     [N];
  logic        bvalid  [N];
  logic        bready  [N];
  logic [63:0] araddr  [N];
  logic [7:0]  arid    [N];
  logic        arvalid [N];
  logic        arready [N];
  logic [7:0]  rid     [N];
  logic [31:0] rdata   [N];
  logic        rvalid  [N];
  logic        rready  [N];

  // Fabric side.
  logic [N-1:0]         iv, ir, ev, er;
  logic [N*W-1:0]       ifl, ofl;

  srota64_native dut (
    .clk(clk), .rst_n(rst_n),
    .inj_valid(iv), .inj_ready(ir), .inj_flit(ifl),
    .eject_valid(ev), .eject_ready(er), .eject_flit(ofl)
  );

  for (genvar g = 0; g < N; g++) begin : ep
    axi5_srota_ep #(.EP(g), .W(W)) u (
      .clk(clk), .rst_n(rst_n),
      .awaddr(awaddr[g]), .awid(awid[g]), .awvalid(awvalid[g]), .awready(awready[g]),
      .wdata(wdata[g]), .wstrb(wstrb[g]), .wlast(wlast[g]), .wvalid(wvalid[g]), .wready(wready[g]),
      .bid(bid[g]), .bvalid(bvalid[g]), .bready(bready[g]),
      .araddr(araddr[g]), .arid(arid[g]), .arvalid(arvalid[g]), .arready(arready[g]),
      .rid(rid[g]), .rdata(rdata[g]), .rvalid(rvalid[g]), .rready(rready[g]),
      .inj_valid(iv[g]), .inj_ready(ir[g]), .inj_flit(ifl[g*W +: W]),
      .eject_valid(ev[g]), .eject_ready(er[g]), .eject_flit(ofl[g*W +: W])
    );
  end

  int n_pairs, n_strobe;

  task automatic axi_wr(input int s, input int d, input int word,
                        input logic [31:0] dat, input logic [3:0] strb,
                        input logic [7:0] id);
    int aw_done, w_done;
    begin
      @(negedge clk);
      awaddr[s]  = (64'(d) << 6) | (64'(word) << 2);
      awid[s]    = id;
      awvalid[s] = 1'b1;
      wdata[s]   = dat;
      wstrb[s]   = strb;
      wlast[s]   = 1'b1;
      wvalid[s]  = 1'b1;
      aw_done = 0; w_done = 0;
      while (!(aw_done && w_done)) begin
        @(posedge clk);
        if (awvalid[s] && awready[s]) aw_done = 1;
        if (wvalid[s]  && wready[s])  w_done  = 1;
        @(negedge clk);
        if (aw_done) awvalid[s] = 1'b0;
        if (w_done)  wvalid[s]  = 1'b0;
      end
      bready[s] = 1'b1;
      @(posedge clk);
      while (!(bvalid[s] && bready[s])) @(posedge clk);
      if (bid[s] !== id) $fatal(1, "BID mismatch %0d->%0d got %0d want %0d", s, d, bid[s], id);
      @(negedge clk);
      bready[s] = 1'b0;
    end
  endtask

  task automatic axi_rd(input int s, input int d, input int word,
                        input logic [7:0] id, output logic [31:0] got);
    begin
      @(negedge clk);
      araddr[s]  = (64'(d) << 6) | (64'(word) << 2);
      arid[s]    = id;
      arvalid[s] = 1'b1;
      @(posedge clk);
      while (!(arvalid[s] && arready[s])) @(posedge clk);
      @(negedge clk);
      arvalid[s] = 1'b0;
      rready[s]  = 1'b1;
      @(posedge clk);
      while (!(rvalid[s] && rready[s])) @(posedge clk);
      if (rid[s] !== id) $fatal(1, "RID mismatch %0d->%0d got %0d want %0d", s, d, rid[s], id);
      got = rdata[s];
      @(negedge clk);
      rready[s] = 1'b0;
    end
  endtask

  initial begin
    for (int i = 0; i < N; i++) begin
      awaddr[i] = '0; awid[i] = '0; awvalid[i] = 1'b0;
      wdata[i] = '0; wstrb[i] = '0; wlast[i] = 1'b0; wvalid[i] = 1'b0; bready[i] = 1'b0;
      araddr[i] = '0; arid[i] = '0; arvalid[i] = 1'b0; rready[i] = 1'b0;
    end
    n_pairs = 0; n_strobe = 0;
    repeat (3) @(negedge clk);
    rst_n = 1'b1;
    repeat (2) @(negedge clk);

    // 1. Every ordered pair: write then read one word.
    for (int s = 0; s < N; s++) begin
      for (int d = 0; d < N; d++) begin
        int word;
        logic [31:0] dat, got;
        logic [7:0] wid, ridx;
        word = (s + d) % 16;
        dat  = 32'hA000_0000 | (32'(s) << 8) | 32'(d);
        wid  = 8'((s * 64 + d) & 255);
        axi_wr(s, d, word, dat, 4'hF, wid);
        axi_rd(s, d, word, wid ^ 8'hFF, got);
        if (got !== dat) $fatal(1, "readback mismatch %0d->%0d word %0d got %h want %h", s, d, word, got, dat);
        n_pairs++;
      end
    end

    // 2. Partial byte strobes must merge, not replace.
    begin
      int s, d, word;
      logic [31:0] got;
      s = 5; d = 40; word = 3;
      axi_wr(s, d, word, 32'hFFFF_FFFF, 4'hF, 8'h11);
      axi_wr(s, d, word, 32'h0000_0000, 4'b1010, 8'h12);
      axi_rd(s, d, word, 8'h13, got);
      // strb 1010 zeroes bytes 1 and 3, bytes 0 and 2 keep 0xFF
      if (got !== 32'h00FF_00FF) $fatal(1, "strobe merge wrong: got %h want %h", got, 32'h00FF_00FF);
      axi_wr(s, d, word, 32'hA5A5_5A5A, 4'b0001, 8'h14);
      axi_rd(s, d, word, 8'h15, got);
      // strb 0001 writes byte 0 only, bytes 1..3 keep the previous merge
      if (got !== 32'h00FF_005A) $fatal(1, "strobe lane 0 wrong: got %h want %h", got, 32'h00FF_005A);
      n_strobe = 2;
    end

    // 3. Two independent transactions in flight at the same time.
    begin
      logic [31:0] a_got, b_got;
      fork
        begin
          axi_wr(1, 62, 1, 32'h1111_2222, 4'hF, 8'h21);
          axi_rd(1, 62, 1, 8'h22, a_got);
        end
        begin
          axi_wr(62, 1, 2, 32'h3333_4444, 4'hF, 8'h23);
          axi_rd(62, 1, 2, 8'h24, b_got);
        end
      join
      if (a_got !== 32'h1111_2222) $fatal(1, "concurrent pair A wrong: %h", a_got);
      if (b_got !== 32'h3333_4444) $fatal(1, "concurrent pair B wrong: %h", b_got);
    end

    // 4. Drain.
    repeat (8) @(posedge clk);
    if (dut.busy !== '0) $fatal(1, "fabric did not drain, busy=%h", dut.busy);
    if (iv !== '0 || ev !== '0) $fatal(1, "fabric still active iv=%h ev=%h", iv, ev);
    for (int i = 0; i < N; i++)
      if (bvalid[i] !== 1'b0 || rvalid[i] !== 1'b0)
        $fatal(1, "endpoint %0d left a reply outstanding", i);

    $display("PASS axi5-through-srota64 pairs=%0d strobe_cases=%0d concurrent_pairs=2 drained",
             n_pairs, n_strobe);
    $finish;
  end

  initial begin
    #5000000000;   // 5 ms at 10 ns per cycle = 500k cycles of headroom
    $fatal(1, "timeout");
  end
endmodule
`default_nettype wire
