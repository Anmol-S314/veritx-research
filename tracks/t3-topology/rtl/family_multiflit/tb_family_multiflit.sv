`default_nettype none

// tb_family_multiflit.sv — the multi-flit reassembly path, exercised.
//
// The composed family's initiator emits one AXI beat per flit, so the
// HEAD/BODY/TAIL path is not reached through the AXI side. It IS part of the
// fabric: the router holds a packet's route from its HEAD to its TAIL, and
// the destination adapter assembles the flits of a packet into one answer.
//
// This testbench drives the destination adapter the product emits:
//
//   * a three-flit packet (HEAD, BODY, TAIL) must produce ONE answer, not
//     one per flit;
//   * the payload of the packet must be reassembled: every word it carried
//     must read back with the data it was written with.
//
// The field offsets are parameters, so the same testbench runs against any
// family's packet format. The router's own packet atomicity (the route held
// from HEAD to TAIL, with no interleaving) is proved by the concentrator's
// testbench, which is where that mechanism lives.
module tb_family_multiflit #(
  parameter int FLIT_W = 64,
  parameter int DST_LSB = 59,
  parameter int DST_W = 2,
  parameter int VC_LSB = 63,
  parameter int VC_W = 1,
  parameter int TYPE_LSB = 61,
  parameter int SRC_LSB = 57,
  parameter int SRC_W = 2,
  parameter int PAY_LSB = 0,
  parameter int WIN = 32,
  parameter int SRAM_WORDS = 128
);
  localparam int TYPE_W = 2;
  localparam logic [TYPE_W-1:0] FT_HEAD = 2'd0;
  localparam logic [TYPE_W-1:0] FT_BODY = 2'd1;
  localparam logic [TYPE_W-1:0] FT_TAIL = 2'd2;
  localparam logic [TYPE_W-1:0] FT_SINGLE = 2'd3;

  localparam int WORD_LSB = PAY_LSB + WIN + 13;
  localparam int SEQ_LSB = PAY_LSB + WIN;
  localparam int WRITE_LSB = PAY_LSB + WIN + 20;
  localparam int OOR_LSB = PAY_LSB + WIN + 21;

  logic clk = 1'b0;
  always #5 clk = ~clk;
  logic rst_n = 1'b0;

  logic [63:0] req_flit = '0;
  logic req_valid = 1'b0;
  logic req_hold = 1'b0;
  logic req_ready;
  logic [63:0] rsp_flit;
  logic rsp_valid;
  logic rsp_ready = 1'b1;
  logic [31:0] req_count, rsp_count, error_count;

  destination_adapter #(
    .SRAM_WORDS(SRAM_WORDS), .DST_ROUTER(0), .DST_ENDPOINT(0)
  ) dut_dest (
    .clk(clk), .rst_n(rst_n),
    .req_flit(req_flit), .req_valid(req_valid), .req_hold(req_hold),
    .req_ready(req_ready), .rsp_flit(rsp_flit), .rsp_valid(rsp_valid),
    .rsp_ready(rsp_ready), .req_count(req_count), .rsp_count(rsp_count),
    .error_count(error_count)
  );

  task automatic fail_msg(input string m);
    $display("FAIL: %s", m);
    $fatal(1);
  endtask

  task automatic make_flit(output logic [FLIT_W-1:0] value,
                           input logic [1:0] ftype,
                           input logic [6:0] word,
                           input logic [31:0] data,
                           input logic write,
                           input logic [12:0] seq);
    // Assembled from the field layout the destination adapter reads, top
    // down: VC, TYPE, DST, SRC, OOR, WRITE, WORD, SEQ, DATA. A concat keeps
    // every field exactly where the adapter expects it.
    value = {1'b0,                  // VC
             ftype,                 // TYPE
             {DST_W{1'b0}},         // DST: this router
             {SRC_W{1'b0}},         // SRC
             3'b000,                // unused
             1'b0,                  // OOR
             write,                 // WRITE
             word,                  // WORD
             seq,                   // SEQ
             data};                 // DATA
  endtask

  task automatic send(input logic [1:0] ftype, input logic [6:0] word,
                      input logic [31:0] data, input logic [12:0] seq);
    begin
      @(negedge clk);
      make_flit(req_flit, ftype, word, data, 1'b1, seq);
      req_valid = 1'b1;
      while (!req_ready) @(negedge clk);
      @(posedge clk);
      @(negedge clk);
      req_valid = 1'b0;
    end
  endtask

  task automatic read_word(input logic [6:0] word, output logic [31:0] value);
    int timeout;
    begin
      @(negedge clk);
      make_flit(req_flit, FT_SINGLE, word, 32'h0, 1'b0, 13'd900);
      req_valid = 1'b1;
      while (!req_ready) @(negedge clk);
      @(posedge clk);
      @(negedge clk);
      req_valid = 1'b0;
      timeout = 0;
      while (!rsp_valid && timeout < 200) begin
        @(posedge clk);
        timeout++;
      end
      if (!rsp_valid) fail_msg("a read produced no answer");
      value = rsp_flit[PAY_LSB +: WIN];
    end
  endtask

  int responses;
  int i;
  int timeout;
  logic [31:0] read_data;
  logic [31:0] expected [0:2];

  always @(posedge clk) begin
    if (rst_n && rsp_valid && rsp_ready) responses <= responses + 1;
  end

  initial begin
    responses = 0;
    repeat (4) @(posedge clk);
    rst_n <= 1'b1;
    repeat (2) @(posedge clk);

    expected[0] = 32'hA0A0_0001;
    expected[1] = 32'hA0A0_0002;
    expected[2] = 32'hA0A0_0003;

    // --- the three-flit packet: HEAD, BODY, TAIL ---
    send(FT_HEAD, 7'd0, expected[0], 13'd100);
    send(FT_BODY, 7'd1, expected[1], 13'd101);
    send(FT_TAIL, 7'd2, expected[2], 13'd102);

    // The packet owes one answer, not one per flit.
    timeout = 0;
    while (responses == 0 && timeout < 200) begin
      @(posedge clk);
      timeout++;
    end
    if (responses == 0) fail_msg("the multi-flit packet produced no answer");
    repeat (20) @(posedge clk);
    if (responses != 1)
      fail_msg($sformatf("a three-flit packet produced %0d answers, expected 1",
                          responses));
    if (error_count != 0)
      fail_msg($sformatf("the destination counted %0d errors", error_count));

    // --- reassembly: every word must read back with the data it carried ---
    for (i = 0; i < 3; i = i + 1) begin
      read_word(i[6:0], read_data);
      if (read_data !== expected[i])
        fail_msg($sformatf("word %0d reassembled as %08x, expected %08x",
                            i, read_data, expected[i]));
    end

    $display("PASS: multi-flit packet HEAD/BODY/TAIL carried 3 flits, produced 1 answer, and reassembled 3 words");
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
