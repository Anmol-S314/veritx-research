`timescale 1ns/1ps
module tb_gec_mecs16_fabric;
  localparam int N = 16;
  localparam int W = 64;
  logic clk = 1'b0;
  logic rst_n = 1'b0;
  logic [N-1:0] ep_in_valid = '0;
  logic [N-1:0] ep_in_ready;
  logic [N-1:0][W-1:0] ep_in_flit = '0;
  logic [N-1:0] ep_out_valid;
  logic [N-1:0] ep_out_ready = '1;
  logic [N-1:0][W-1:0] ep_out_flit;
  int accepted = 0;
  int delivered = 0;
  int stall_cycles = 0;

  always #5 clk = ~clk;

  gec_mecs16_fabric dut (.*);

  function automatic logic [W-1:0] make_flit(input int src, input int dst, input int seq);
    logic [W-1:0] value;
    value = '0;
    value[63:60] = 4'(dst);
    value[59:56] = 4'(src);
    value[55:0] = 56'h6d65_6373_000000 ^ (56'(seq) << 8) ^ 56'(src * 17 + dst);
    return value;
  endfunction

  task automatic send_pair(input int src, input int dst, input bit force_stall);
    logic [W-1:0] expected;
    bit found;
    int timeout;
    expected = make_flit(src, dst, src*N + dst);
    found = 1'b0;
    timeout = 0;

    @(negedge clk);
    ep_out_ready = '0;
    ep_in_flit[src] = expected;
    ep_in_valid[src] = 1'b1;
    while (!ep_in_ready[src]) @(negedge clk);
    @(posedge clk);
    if (ep_in_ready[src]) accepted++;
    @(negedge clk);
    ep_in_valid[src] = 1'b0;

    while (!found && timeout < 80) begin
      @(negedge clk);
      timeout++;
      for (int r = 0; r < N; r++) begin
        if (dut.row_valid[r]) begin
          int dx;
          int rx;
          dx = int'(dut.row_dest[r]) % 4;
          rx = r % 4;
          if (int'(dut.row_vc[r]) != ((dx < rx) ? dx : dx - 1))
            $fatal(1, "row VC/drop mismatch router=%0d dest=%0d vc=%0d", r, dut.row_dest[r], dut.row_vc[r]);
        end
        if (dut.col_valid[r]) begin
          int dy;
          int ry;
          dy = int'(dut.col_dest[r]) / 4;
          ry = r / 4;
          if (int'(dut.col_vc[r]) != ((dy < ry) ? dy : dy - 1))
            $fatal(1, "column VC/drop mismatch router=%0d dest=%0d vc=%0d", r, dut.col_dest[r], dut.col_vc[r]);
        end
      end
      for (int n = 0; n < N; n++) begin
        if (ep_out_valid[n]) begin
          if (n != dst) $fatal(1, "wrong destination: expected %0d saw %0d", dst, n);
          if (ep_out_flit[n] !== expected)
            $fatal(1, "payload mismatch src=%0d dst=%0d got=%h expected=%h", src, dst, ep_out_flit[n], expected);
          found = 1'b1;
        end
      end
    end
    if (!found) begin
      $display("DBG src=%0d dst=%0d n0q=%b n1q=%b n5q=%b n0row=%b n1col=%b n1col_dest=%0d n1col_vc=%0d n1col_ready=%b", src, dst, dut.g_router[0].u_router.valid_q, dut.g_router[1].u_router.valid_q, dut.g_router[5].u_router.valid_q, dut.row_valid[0], dut.col_valid[1], dut.col_dest[1], dut.col_vc[1], dut.col_ready[1]);
      $fatal(1, "timeout src=%0d dst=%0d", src, dst);
    end

    if (force_stall) begin
      repeat (6) begin
        @(negedge clk);
        if (!ep_out_valid[dst] || ep_out_flit[dst] !== expected)
          $fatal(1, "valid/payload changed under egress stall src=%0d dst=%0d", src, dst);
        stall_cycles++;
      end
    end
    ep_out_ready = '1;
    @(posedge clk);
    if (!ep_out_valid[dst] || ep_out_flit[dst] !== expected)
      $fatal(1, "delivery handshake mismatch src=%0d dst=%0d", src, dst);
    delivered++;
    @(negedge clk);
    if (ep_out_valid[dst]) $fatal(1, "duplicate delivery src=%0d dst=%0d", src, dst);
  endtask

  task automatic same_destination_contention;
    logic [W-1:0] flit_a;
    logic [W-1:0] flit_b;
    logic [1:0] seen;
    int cycles;
    flit_a = make_flit(0, 15, 32'h00007a01);
    flit_b = make_flit(4, 15, 32'h00007a02);
    seen = '0;
    cycles = 0;

    @(negedge clk);
    ep_out_ready = '0;
    ep_in_flit[0] = flit_a;
    ep_in_flit[4] = flit_b;
    ep_in_valid[0] = 1'b1;
    ep_in_valid[4] = 1'b1;
    while (!(ep_in_ready[0] && ep_in_ready[4])) @(negedge clk);
    @(posedge clk);
    if (!(ep_in_ready[0] && ep_in_ready[4])) $fatal(1, "concurrent injection not accepted atomically");
    accepted += 2;
    @(negedge clk);
    ep_in_valid[0] = 1'b0;
    ep_in_valid[4] = 1'b0;

    while (!ep_out_valid[15] && cycles < 80) begin
      @(negedge clk);
      cycles++;
    end
    if (!ep_out_valid[15]) $fatal(1, "concurrent destination did not receive a packet");
    if (ep_out_flit[15] !== flit_a && ep_out_flit[15] !== flit_b)
      $fatal(1, "unexpected first concurrent payload %h", ep_out_flit[15]);
    repeat (6) begin
      @(negedge clk);
      if (!ep_out_valid[15]) $fatal(1, "held egress valid dropped during contention");
      if (ep_out_flit[15] !== flit_a && ep_out_flit[15] !== flit_b)
        $fatal(1, "held egress payload changed during contention");
      stall_cycles++;
    end

    ep_out_ready = '1;
    cycles = 0;
    while (seen != 2'b11 && cycles < 80) begin
      @(posedge clk);
      cycles++;
      for (int n = 0; n < N; n++) begin
        if (ep_out_valid[n] && ep_out_ready[n]) begin
          if (n != 15) $fatal(1, "contended packet misrouted to endpoint %0d", n);
          if (ep_out_flit[n] == flit_a) begin
            if (seen[0]) $fatal(1, "duplicate concurrent packet A");
            seen[0] = 1'b1;
          end else if (ep_out_flit[n] == flit_b) begin
            if (seen[1]) $fatal(1, "duplicate concurrent packet B");
            seen[1] = 1'b1;
          end else $fatal(1, "unknown concurrent payload %h", ep_out_flit[n]);
          delivered++;
        end
      end
    end
    if (seen != 2'b11) $fatal(1, "contention did not drain both packets, seen=%b", seen);
    @(negedge clk);
    if (ep_out_valid[15]) $fatal(1, "duplicate output after concurrent drain");
  endtask

  initial begin
    repeat (4) @(posedge clk);
    @(negedge clk);
    rst_n = 1'b1;
    for (int src = 0; src < N; src++)
      for (int dst = 0; dst < N; dst++)
        send_pair(src, dst, src == 0 && dst == 15);
    same_destination_contention();

    if (accepted != N*N + 2 || delivered != N*N + 2)
      $fatal(1, "conservation failure accepted=%0d delivered=%0d", accepted, delivered);
    if (stall_cycles < 6) $fatal(1, "backpressure was not exercised");
    repeat (4) @(posedge clk);
    if (ep_out_valid != '0) $fatal(1, "network did not drain");
    $display("PASS gec_mecs16 routers=16 shared_wires=32 taps_per_wire=3 all_pairs=%0d accepted=%0d delivered=%0d stall_cycles=%0d drained=1", N*N, accepted, delivered, stall_cycles);
    $finish;
  end

  initial begin
    #500000;
    $fatal(1, "global watchdog");
  end
endmodule
