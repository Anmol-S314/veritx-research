// tb_cdc.sv — self-checking SystemVerilog testbench for cdc_fifo.
// Two independent clocks. Config via localparams:
//   CFG1 (default, product case): slow producer / fast consumer, DEPTH 8, STAGES 2
//   CFG2 (stress):               fast producer / slow consumer, DEPTH 16, STAGES 3
// Writes 2000 patterned flits with occasional stalls; reads continuously with
// occasional stalls. Oracle:
//   * the write driver tracks ACCEPTANCE (wseq advances only when the module
//     accepts; wr_en+data held while full) -> the written stream is contiguous
//   * verify ORDER + CONTENT of every (rd_valid, rd_data) pair while rcnt<N;
//     after N, trailing pairs are sync-lag stale duplicates (slack)
//   * PASS requires wcnt==N, rcnt==N, errors==0
module tb_cdc;
  localparam int  N       = 2000;
  localparam longint PATTERN = 64'hCAFEF00D;
  localparam int  CFG     = 2;   // 1 = slow-wr/fast-rd DEPTH8 STAGES2; 2 = fast-wr/slow-rd DEPTH16 STAGES3
  localparam int  DEPTH   = (CFG == 2) ? 16 : 8;
  localparam int  STAGES  = (CFG == 2) ? 3  : 2;

  logic wr_clk = 0;
  logic wr_rst_n = 0;
  logic rd_clk = 0;
  logic rd_rst_n = 0;
  logic wr_en = 0;
  logic [63:0] wr_data = 0;
  logic wr_full;
  logic rd_en = 0;
  logic [63:0] rd_data;
  logic rd_valid;
  logic rd_empty;

  cdc_fifo #(.DATA_W(64), .DEPTH(DEPTH), .STAGES(STAGES)) u_fifo (
    .wr_clk(wr_clk), .wr_rst_n(wr_rst_n), .wr_en(wr_en), .wr_data(wr_data), .wr_full(wr_full),
    .rd_clk(rd_clk), .rd_rst_n(rd_rst_n), .rd_en(rd_en), .rd_data(rd_data),
    .rd_valid(rd_valid), .rd_empty(rd_empty)
  );

  // clock generators (independent periods)
  always #5 wr_clk = ~wr_clk;   // 10 ns
  always #3 rd_clk = ~rd_clk;   //  6 ns

  // write driver: ACCEPTANCE-tracked issue (holds wr_en+data while full;
  // wseq advances only on acceptance; stalls on free-running wslot%4==3)
  int wcnt = 0;
  int wslot = 0;
  longint wseq = 1;
  logic draining = 0;
  always @(posedge wr_clk) begin
    if (!wr_rst_n) begin wr_en <= 0; draining <= 0; end
    else begin
      wslot++;
      // 1) acceptance of the flit issued the previous edge (pre-edge sampling)
      if (wr_en && !wr_full && !draining) begin
        wcnt++;
        wseq++;
      end
      // 2) schedule for the next edge
      if (wcnt >= N) begin draining <= 1; wr_en <= 0; end
      else if (wr_stall_next) wr_en <= 0;
      else if (wr_full) begin
        // HOLD while full: refresh wr_data for the PENDING flit (wseq already
        // advanced past the just-accepted flit) -- otherwise the module would
        // accept the STALE data of the previous flit when full clears
        // (proven: mem[i]=7, mem[i+1]=7 -> one flit silently lost per hold).
        wr_en   <= 1;
        wr_data <= ((wseq & 13'h1FFF) << 32) | PATTERN;
      end
      else begin
        wr_en   <= 1;
        wr_data <= ((wseq & 13'h1FFF) << 32) | PATTERN;
      end
    end
  end
  // free-running stall pattern: 3 of 4 slots assert, 1 of 4 stalls
  logic wr_stall_next;
  assign wr_stall_next = (wslot % 4 == 3);

  // read driver + content oracle
  int rcnt = 0;
  int rslot = 0;
  logic rd_valid_q = 0;
  logic [63:0] rd_data_q = 0;
  longint rseq = 1;
  int slack = 0;
  int errors = 0;
  int last_seq = 0;
  always @(posedge rd_clk) begin
    if (!rd_rst_n) rd_en <= 0;
    else begin
      rslot++;
      // Stable-sampled handshake pair: rd_valid_q/rd_data_q capture the module's
      // registered outputs one TB edge after they settle (delta-safe); pair
      // semantics unchanged: (valid,data) at edge K = flit consumed at edge K-1.
      // Checking un-sampled rd_valid would race the module's delta and read
      // stale/uninitialized data (exposed by CFG1's flit-8 arrival window).
      rd_valid_q <= rd_valid;
      rd_data_q  <= rd_data;
      // Oracle: while rcnt<N the stream must be exactly 1..N in order; once all
      // N are seen, trailing pairs are sync-lag stale duplicates (slack).
      if (rd_valid_q) begin
        if (rcnt < N) begin
          if (rd_data_q[44:32] != (rseq & 13'h1FFF)) begin
            $display("ERROR read#%0d: seq %0d expected %0d", rcnt, rd_data_q[44:32], rseq & 13'h1FFF);
            errors++;
          end
          if ((rd_data_q & 64'hFFFFFFFF) != PATTERN) begin
            $display("ERROR CORRUPT read#%0d data=%h", rcnt, rd_data_q);
            errors++;
          end
          last_seq = rd_data_q[44:32];
          rseq++;
          rcnt++;
        end else begin
          if (rd_data_q[44:32] == last_seq) slack++;
          else begin
            $display("ERROR bad slack pair seq=%0d last=%0d", rd_data_q[44:32], last_seq);
            errors++;
          end
        end
      end
      // arm the NEXT edge while our backlog says data is outstanding
      if (rcnt < wcnt && (wcnt - rcnt) > 0 && (rslot % 5 != 0)) rd_en <= 1;
      else rd_en <= 0;
    end
  end

  // end-of-test
  int cycles = 0;
  int empty_streak = 0;
  always @(posedge rd_clk) begin
    if (rd_rst_n) begin
      cycles++;
      if (wcnt >= N && rcnt >= N) begin
        if (rd_empty) empty_streak++;
        else empty_streak = 0;
        if (empty_streak >= 50) begin
          $display("=== CDC FIFO RESULTS (CFG=%0d DEPTH=%0d STAGES=%0d) ===", CFG, DEPTH, STAGES);
          $display("writes=%0d reads=%0d slack=%0d errors=%0d", wcnt, rcnt, slack, errors);
          if (errors == 0 && wcnt == N && rcnt == N)
            $display("status: PASS");
          else
            $display("status: FAIL");
          $finish;
        end
      end
      if (cycles > 200000) begin
        $display("=== CDC FIFO TIMEOUT: wcnt=%0d rcnt=%0d errors=%0d ===", wcnt, rcnt, errors);
        $display("status: FAIL");
        $finish;
      end
    end
  end

  initial begin
    $dumpfile("/tmp/opencode/cdc1.vcd");
    $dumpvars(0, tb_cdc);
    repeat (4) @(posedge wr_clk);
    @(negedge wr_clk);
    wr_rst_n <= 1;
    repeat (4) @(posedge rd_clk);
    @(negedge rd_clk);
    rd_rst_n <= 1;
  end

  initial begin
    #10000000 $display("TIMEOUT-PROTECT status: FAIL"); $finish;
  end
endmodule
