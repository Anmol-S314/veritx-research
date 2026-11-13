`default_nettype none
`timescale 1ns/1ps

// Behavioural bank: one request at a time, random latency, response held until accepted.
// Request flit: [15:0] data, [19:16] word, [20] write, [41:40] bank, [63:48] tag.
// Response flit: [15:0] data, [41:40] ID of the bank that answered, [63:48] tag.
module bank_model #(parameter int ID = 0) (
  input  logic clk,
  input  logic rst_n,
  input  logic [63:0] req_flit,
  input  logic req_valid,
  output logic req_ready,
  output logic [63:0] rsp_flit,
  output logic rsp_valid,
  input  logic rsp_ready
);
  logic [15:0] mem [0:15];
  logic busy_q;
  logic [3:0] wait_q;
  logic [63:0] flit_q;
  logic [15:0] data_w;
  logic [3:0] word_w;
  logic write_w;

  assign data_w = req_flit[15:0];
  assign word_w = req_flit[19:16];
  assign write_w = req_flit[20];
  assign req_ready = !busy_q;
  assign rsp_flit = flit_q;
  assign rsp_valid = busy_q && (wait_q == 4'd0);

  initial for (int w = 0; w < 16; w++) mem[w] = 16'(ID * 256 + w);

  always_ff @(posedge clk or negedge rst_n) begin
    if (!rst_n) begin
      busy_q <= 1'b0;
      wait_q <= 4'd0;
      flit_q <= '0;
    end else if (!busy_q) begin
      if (req_valid) begin
        busy_q <= 1'b1;
        wait_q <= 4'($urandom_range(0, 5));
        if (write_w) mem[word_w] <= data_w;
        flit_q <= {req_flit[63:48], 6'd0, 2'(ID), 24'd0, write_w ? data_w : mem[word_w]};
      end
    end else if (wait_q != 4'd0) begin
      wait_q <= wait_q - 4'd1;
    end else if (rsp_ready) begin
      busy_q <= 1'b0;
    end
  end
endmodule

// One memory_banks instance with its banks.
module harness #(parameter int N = 4) (
  input  logic clk,
  input  logic rst_n,
  input  logic [63:0] req_flit,
  input  logic req_valid,
  output logic req_ready,
  output logic [63:0] rsp_flit,
  output logic rsp_valid,
  input  logic rsp_ready,
  output logic protocol_error
);
  logic [63:0] b_req_flit;
  logic b_req_valid [0:N-1];
  logic b_req_ready [0:N-1];
  logic [63:0] b_rsp_flit [0:N-1];
  logic b_rsp_valid [0:N-1];
  logic b_rsp_ready [0:N-1];

  memory_banks #(.N_BANKS(N), .FLIT_W(64), .BANK_LSB(40), .BANK_W(2)) dut (
    .clk(clk), .rst_n(rst_n),
    .req_flit(req_flit), .req_valid(req_valid), .req_ready(req_ready),
    .rsp_flit(rsp_flit), .rsp_valid(rsp_valid), .rsp_ready(rsp_ready),
    .bank_req_flit(b_req_flit), .bank_req_valid(b_req_valid), .bank_req_ready(b_req_ready),
    .bank_rsp_flit(b_rsp_flit), .bank_rsp_valid(b_rsp_valid), .bank_rsp_ready(b_rsp_ready),
    .protocol_error(protocol_error)
  );

  for (genvar k = 0; k < N; k++) begin : g_bank
    bank_model #(.ID(k)) u_bank (
      .clk(clk), .rst_n(rst_n),
      .req_flit(b_req_flit), .req_valid(b_req_valid[k]), .req_ready(b_req_ready[k]),
      .rsp_flit(b_rsp_flit[k]), .rsp_valid(b_rsp_valid[k]), .rsp_ready(b_rsp_ready[k])
    );
  end
endmodule

module tb_memory_banks;
  logic clk = 1'b0;
  logic rst_n = 1'b0;
  always #5 clk = ~clk;

  // 4-bank instance (all bank ids legal) and a 3-bank instance (id 3 is illegal).
  logic [63:0] req_flit4 = '0, rsp_flit4, req_flit3 = '0, rsp_flit3;
  logic req_valid4 = 1'b0, req_ready4, rsp_valid4, rsp_ready4 = 1'b1, perr4;
  logic req_valid3 = 1'b0, req_ready3, rsp_valid3, rsp_ready3 = 1'b1, perr3;
  harness #(.N(4)) h4 (.clk(clk), .rst_n(rst_n), .req_flit(req_flit4), .req_valid(req_valid4), .req_ready(req_ready4),
                       .rsp_flit(rsp_flit4), .rsp_valid(rsp_valid4), .rsp_ready(rsp_ready4), .protocol_error(perr4));
  harness #(.N(3)) h3 (.clk(clk), .rst_n(rst_n), .req_flit(req_flit3), .req_valid(req_valid3), .req_ready(req_ready3),
                       .rsp_flit(rsp_flit3), .rsp_valid(rsp_valid3), .rsp_ready(rsp_ready3), .protocol_error(perr3));

  // Reference memory and scoreboard, updated when a request is accepted.
  logic [15:0] ref_mem [0:3][0:15];
  int exp_bank [0:1023];
  logic [15:0] exp_data [0:1023];
  int seen [0:1023];
  int tag_n = 0;
  int issued = 0;
  int answered = 0;
  int wrong = 0;
  int unstable = 0;
  bit backpressure = 1'b0;

  initial for (int b = 0; b < 4; b++) for (int w = 0; w < 16; w++) ref_mem[b][w] = 16'(b * 256 + w);

  // Response monitor: attribution, data, exactly-once.
  always @(posedge clk) if (rsp_valid4 && rsp_ready4) begin
    automatic int t = int'(rsp_flit4[63:48]);
    answered <= answered + 1;
    seen[t] <= seen[t] + 1;
    if (int'(rsp_flit4[41:40]) != exp_bank[t] || rsp_flit4[15:0] != exp_data[t]) wrong <= wrong + 1;
  end

  // Stability: a held response must not change while the consumer is not ready.
  logic [63:0] prev_flit;
  logic prev_hold = 1'b0;
  always @(posedge clk) begin
    if (prev_hold && (!rsp_valid4 || rsp_flit4 != prev_flit)) unstable <= unstable + 1;
    prev_hold <= rsp_valid4 && !rsp_ready4;
    prev_flit <= rsp_flit4;
  end

  always @(posedge clk) if (backpressure) rsp_ready4 <= ($urandom_range(0, 1) == 1);

  task automatic send(input int bank, input int word, input bit wr, input logic [15:0] data);
    logic [15:0] expect_data;
    expect_data = wr ? data : ref_mem[bank][word];
    if (wr) ref_mem[bank][word] = data;
    exp_bank[tag_n] = bank;
    exp_data[tag_n] = expect_data;
    @(negedge clk);
    req_flit4 = {16'(tag_n), 6'd0, 2'(bank), 19'd0, wr, 4'(word), data};
    req_valid4 = 1'b1;
    do @(posedge clk); while (!req_ready4);
    @(negedge clk);
    req_valid4 = 1'b0;
    tag_n++;
    issued++;
  endtask

  task automatic drain(input int limit);
    int n = 0;
    while (answered < issued && n < limit) begin @(posedge clk); n++; end
  endtask

  int ok_all;
  initial begin
    repeat (4) @(posedge clk);
    rst_n = 1'b1;
    repeat (2) @(posedge clk);

    // S1: the same word index in every bank holds a different value; each read returns its own bank's value.
    for (int b = 0; b < 4; b++) send(b, 5, 1'b1, 16'(16'hA000 + b));
    for (int b = 0; b < 4; b++) send(b, 5, 1'b0, 16'd0);
    drain(500);
    if (answered == issued && wrong == 0) $display("PASS: S1 bank isolation: same word in 4 banks, each read returned its own bank's data");
    else $display("FAIL: S1 isolation answered=%0d issued=%0d wrong=%0d", answered, issued, wrong);

    // S2: random mix, random bank latency, random consumer back-pressure.
    backpressure = 1'b1;
    for (int i = 0; i < 400; i++) send($urandom_range(0, 3), $urandom_range(0, 15), ($urandom_range(0, 2) == 0), 16'($urandom));
    drain(20000);
    backpressure = 1'b0;
    rsp_ready4 = 1'b1;
    ok_all = 1;
    for (int t = 0; t < tag_n; t++) if (seen[t] != 1) ok_all = 0;
    if (answered == issued && wrong == 0 && ok_all == 1)
      $display("PASS: S2 conservation and attribution: %0d requests, one response each, correct bank and data", issued);
    else $display("FAIL: S2 answered=%0d issued=%0d wrong=%0d once=%0d", answered, issued, wrong, ok_all);

    if (unstable == 0) $display("PASS: S3 response stable while the consumer stalls");
    else $display("FAIL: S3 response changed %0d times while stalled", unstable);

    if (perr4 == 1'b0) $display("PASS: S4 no protocol error on legal bank ids");
    else $display("FAIL: S4 protocol error on legal traffic");

    // S5: an illegal bank id is consumed (no deadlock), latches the error, and the other banks keep working.
    @(negedge clk);
    req_flit3 = {16'd900, 6'd0, 2'd3, 19'd0, 1'b0, 4'd1, 16'd0};
    req_valid3 = 1'b1;
    do @(posedge clk); while (!req_ready3);
    @(negedge clk);
    req_valid3 = 1'b0;
    repeat (2) @(posedge clk);
    req_flit3 = {16'd901, 6'd0, 2'd1, 19'd0, 1'b0, 4'd2, 16'd0};
    req_valid3 = 1'b1;
    do @(posedge clk); while (!req_ready3);
    @(negedge clk);
    req_valid3 = 1'b0;
    repeat (30) @(posedge clk);
    if (perr3 == 1'b1) $display("PASS: S5 illegal bank id consumed and latched");
    else $display("FAIL: S5 illegal bank id not flagged");

    if (seen[0] >= 0) $display("status: %s", (answered == issued && wrong == 0 && ok_all == 1 && unstable == 0 && perr4 == 1'b0 && perr3 == 1'b1) ? "PASS" : "FAIL");
    $finish;
  end

  initial begin
    #5000000;
    $display("FAIL: timeout");
    $finish;
  end
endmodule
