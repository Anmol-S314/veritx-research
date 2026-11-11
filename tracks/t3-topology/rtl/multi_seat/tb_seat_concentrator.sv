`default_nettype none

module tb_seat_concentrator;

  localparam int N_SEATS = 2;
  localparam int FLIT_W = 64;
  localparam int TYPE_W = 2;
  localparam int TYPE_LSB = 61;
  localparam int SEAT_W = 2;
  localparam int SEQ_W = 13;
  localparam int DELAY = 3;
  localparam int MAXQ = 8;

  localparam logic [TYPE_W-1:0] FT_HEAD = 2'd0;
  localparam logic [TYPE_W-1:0] FT_BODY = 2'd1;
  localparam logic [TYPE_W-1:0] FT_TAIL = 2'd2;
  localparam logic [TYPE_W-1:0] FT_SINGLE = 2'd3;

  logic clk = 1'b0;
  always #5 clk = ~clk;
  logic rst_n = 1'b0;

  logic [FLIT_W-1:0] in_flit [0:N_SEATS-1];
  logic in_valid [0:N_SEATS-1];
  logic in_ready [0:N_SEATS-1];
  logic [FLIT_W-1:0] out_flit;
  logic out_valid;
  logic out_ready;
  logic [FLIT_W-1:0] rsp_flit;
  logic rsp_valid;
  logic rsp_ready;
  logic [FLIT_W-1:0] seat_rsp_flit [0:N_SEATS-1];
  logic seat_rsp_valid [0:N_SEATS-1];
  logic seat_rsp_ready [0:N_SEATS-1];
  logic [SEAT_W-1:0] grant_seat;
  logic protocol_error;

  seat_concentrator #(
    .N_SEATS(N_SEATS), .FLIT_W(FLIT_W), .TYPE_W(TYPE_W),
    .TYPE_LSB(TYPE_LSB), .SEAT_W(SEAT_W), .SEQ_W(SEQ_W)
  ) dut (
    .clk(clk), .rst_n(rst_n),
    .in_flit(in_flit), .in_valid(in_valid), .in_ready(in_ready),
    .out_flit(out_flit), .out_valid(out_valid), .out_ready(out_ready),
    .rsp_flit(rsp_flit), .rsp_valid(rsp_valid), .rsp_ready(rsp_ready),
    .seat_rsp_flit(seat_rsp_flit), .seat_rsp_valid(seat_rsp_valid),
    .seat_rsp_ready(seat_rsp_ready),
    .grant_seat(grant_seat), .protocol_error(protocol_error)
  );

  task automatic fail_msg(input string m);
    $display("FAIL: %s", m);
    $fatal(1);
  endtask

  logic [FLIT_W-1:0] pipe [0:DELAY-1];
  logic pipe_v [0:DELAY-1];

  always_ff @(posedge clk) begin
    if (!rst_n) begin
      rsp_flit <= '0;
      rsp_valid <= 1'b0;
      for (int i = 0; i < DELAY; i = i + 1) begin
        pipe[i] <= '0;
        pipe_v[i] <= 1'b0;
      end
    end else if (!(rsp_valid && !rsp_ready)) begin
      rsp_flit <= pipe[DELAY-1];
      rsp_valid <= pipe_v[DELAY-1];
      for (int i = DELAY-1; i > 0; i = i - 1) begin
        pipe[i] <= pipe[i-1];
        pipe_v[i] <= pipe_v[i-1];
      end
      pipe[0] <= out_flit;
      pipe_v[0] <= out_valid && out_ready;
    end
  end

  assign out_ready = 1'b1;

  logic rec_clear = 1'b0;
  logic [1:0] q_type [0:N_SEATS-1][0:MAXQ-1];
  logic [31:0] q_data [0:N_SEATS-1][0:MAXQ-1];
  int q_cnt [0:N_SEATS-1];
  int q_head [0:N_SEATS-1];
  int q_sent [0:N_SEATS-1];
  int q_recv [0:N_SEATS-1];

  genvar g;
  generate
    for (g = 0; g < N_SEATS; g = g + 1) begin : g_seat
      always_ff @(posedge clk) begin
        if (rec_clear) begin
          in_valid[g] <= 1'b0;
          in_flit[g] <= '0;
          q_head[g] <= 0;
          q_sent[g] <= 0;
          q_recv[g] <= 0;
        end else if (!rst_n) begin
          in_valid[g] <= 1'b0;
          in_flit[g] <= '0;
          q_head[g] <= 0;
          q_sent[g] <= 0;
          q_recv[g] <= 0;
        end else begin
          if (q_head[g] < q_cnt[g] && !in_valid[g]) begin
            in_flit[g] <= {1'b0, q_type[g][q_head[g]], 29'd0, q_data[g][q_head[g]]};
            in_valid[g] <= 1'b1;
          end else if (in_valid[g] && in_ready[g]) begin
            q_head[g] <= q_head[g] + 1;
            q_sent[g] <= q_sent[g] + 1;
            in_valid[g] <= 1'b0;
          end
          if (seat_rsp_valid[g] && seat_rsp_ready[g]) begin
            if (q_recv[g] >= q_cnt[g]) fail_msg("response beyond the seat's sent beats");
            if (seat_rsp_flit[g][31:0] !== q_data[g][q_recv[g]])
              fail_msg("response payload does not match the seat's own beat");
            q_recv[g] <= q_recv[g] + 1;
          end
        end
      end
      assign seat_rsp_ready[g] = 1'b1;
    end
  endgenerate

  int grants [0:63];
  int n_grants = 0;

  always_ff @(posedge clk) begin
    if (rec_clear) begin
      n_grants <= 0;
    end else if (rst_n && out_valid && out_ready) begin
      if (n_grants < 64) grants[n_grants] = int'(grant_seat);
      n_grants <= n_grants + 1;
    end
  end

  task automatic push_beat(input int s, input logic [1:0] t, input logic [31:0] d);
    q_type[s][q_cnt[s]] = t;
    q_data[s][q_cnt[s]] = d;
    q_cnt[s] = q_cnt[s] + 1;
  endtask

  int i;
  initial begin
    for (i = 0; i < N_SEATS; i = i + 1) begin
      q_cnt[i] = 0;
    end
    repeat (4) @(posedge clk);
    rst_n <= 1'b1;
    repeat (2) @(posedge clk);

    for (i = 0; i < 4; i = i + 1) begin
      push_beat(0, FT_SINGLE, 32'h1000 + i);
      push_beat(1, FT_SINGLE, 32'h2000 + i);
    end

    wait (q_sent[0] == 4 && q_sent[1] == 4);
    repeat (DELAY + 4) @(posedge clk);
    wait (q_recv[0] == 4 && q_recv[1] == 4);

    if (n_grants != 8) fail_msg("grant count is not 8");
    for (i = 0; i < 8; i = i + 1) begin
      if (grants[i] != (i % 2)) fail_msg("round-robin service is not alternating (skew > 1)");
    end
    $display("PASS: S1 round-robin fairness over 2 seats, 8 grants, skew <= 1");
    $display("PASS: S2 conservation: seat0 sent 4 recv 4, seat1 sent 4 recv 4");

    q_cnt[0] = 0; q_cnt[1] = 0;
    rec_clear <= 1'b1;
    @(posedge clk);
    rec_clear <= 1'b0;
    repeat (2) @(posedge clk);

    push_beat(0, FT_HEAD, 32'hAA00);
    push_beat(0, FT_BODY, 32'hAA01);
    push_beat(0, FT_TAIL, 32'hAA02);
    push_beat(1, FT_SINGLE, 32'hBB00);
    push_beat(1, FT_SINGLE, 32'hBB01);

    wait (q_sent[0] == 3 && q_sent[1] == 2);
    repeat (DELAY + 6) @(posedge clk);
    wait (q_recv[0] == 3 && q_recv[1] == 2);

    if (grants[0] != 0 || grants[1] != 0 || grants[2] != 0)
      fail_msg("a multi-flit packet was interleaved by another seat");
    if (grants[3] != 1 || grants[4] != 1)
      fail_msg("the other seat did not get the wire after the packet closed");
    $display("PASS: S3 multi-flit packet HEAD/BODY/TAIL kept the wire (no interleaving)");
    $display("PASS: S4 per-seat response routing: every beat returned to its own seat");

    if (protocol_error) fail_msg("protocol_error asserted");
    $display("PASS: S5 no protocol error");
    $display("status: PASS");
    $finish;
  end

  initial begin
    #200000;
    $display("FAIL: timeout");
    $fatal(1);
  end

endmodule

`default_nettype wire
