`default_nettype none

// tb_tap_credit_pool.sv — behaviour of the per-tap credit accounting.
//
// The scenarios are the ones the shared-wire contract depends on:
//   S1 a grant consumes a credit of exactly the (tap, VC) requested
//   S2 a credit on one tap never releases capacity on another tap
//   S3 a freed credit returns to its own (tap, VC), after the declared
//      return latency
//   S4 a (tap, VC) that is exhausted refuses further grants
//   S5 taps and VCs are fully independent of each other
module tb_tap_credit_pool;

  localparam int N_TAPS = 3;
  localparam int NUM_VCS = 8;
  localparam int CAPACITY = 4;
  localparam int CREDIT_W = 4;
  localparam int TAP_W = 2;
  localparam int VC_W = 3;
  localparam int LATENCY = 3;

  logic clk = 1'b0;
  always #5 clk = ~clk;
  logic rst_n = 1'b0;

  logic [TAP_W-1:0] req_tap;
  logic [VC_W-1:0] req_vc;
  logic req_valid;
  logic req_ready;
  logic req_grant;

  logic [TAP_W-1:0] free_tap;
  logic [VC_W-1:0] free_vc;
  logic free_valid;

  logic [N_TAPS-1:0][NUM_VCS-1:0][CREDIT_W-1:0] credits;
  logic [N_TAPS-1:0][NUM_VCS-1:0][CREDIT_W-1:0] outstanding;
  logic alias_detected;

  tap_credit_pool #(
    .N_TAPS(N_TAPS), .NUM_VCS(NUM_VCS), .CAPACITY(CAPACITY),
    .CREDIT_W(CREDIT_W), .TAP_W(TAP_W), .VC_W(VC_W), .LATENCY(LATENCY)
  ) dut (
    .clk(clk), .rst_n(rst_n),
    .req_tap(req_tap), .req_vc(req_vc), .req_valid(req_valid),
    .req_ready(req_ready), .req_grant(req_grant),
    .free_tap(free_tap), .free_vc(free_vc), .free_valid(free_valid),
    .credits(credits), .outstanding(outstanding),
    .alias_detected(alias_detected)
  );

  task automatic fail_msg(input string m);
    $display("FAIL: %s", m);
    $fatal(1);
  endtask

  task automatic do_grant(input int tap, input int vc);
    logic [CREDIT_W-1:0] was_credits;
    begin
      was_credits = credits[tap][vc];
      req_tap = TAP_W'(tap);
      req_vc = VC_W'(vc);
      req_valid = 1'b1;
      while (credits[tap][vc] == was_credits) @(posedge clk);
      req_valid = 1'b0;
      @(posedge clk);
    end
  endtask

  task automatic do_free(input int tap, input int vc);
    begin
      @(posedge clk);
      free_tap = TAP_W'(tap);
      free_vc = VC_W'(vc);
      free_valid = 1'b1;
      @(posedge clk);
      free_valid = 1'b0;
    end
  endtask

  integer i;
  integer taps_before;

  initial begin
    req_tap = '0;
    req_vc = '0;
    req_valid = 1'b0;
    free_tap = '0;
    free_vc = '0;
    free_valid = 1'b0;
    repeat (4) @(posedge clk);
    rst_n <= 1'b1;
    repeat (2) @(posedge clk);

    // S1: a grant consumes one credit of exactly that (tap, VC).
    if (credits[0][0] !== CREDIT_W'(CAPACITY)) fail_msg("initial credits are not the capacity");
    do_grant(0, 0);
    if (credits[0][0] !== CREDIT_W'(CAPACITY - 1)) fail_msg("grant did not consume the requested credit");
    if (outstanding[0][0] !== 1) fail_msg("grant did not record the outstanding slot");
    $display("PASS: S1 a grant consumes a credit of exactly the (tap, VC) requested");

    // S2: another tap's credit is untouched.
    if (credits[1][0] !== CREDIT_W'(CAPACITY)) fail_msg("a grant on tap0 changed tap1's credits");
    if (credits[0][1] !== CREDIT_W'(CAPACITY)) fail_msg("a grant on vc0 changed vc1's credits");
    $display("PASS: S2 no cross-tap and no cross-VC credit movement");

    // S3: the freed credit comes back to its own (tap, VC), after LATENCY.
    do_free(0, 0);
    repeat (LATENCY - 1) @(posedge clk);
    if (credits[0][0] !== CREDIT_W'(CAPACITY - 1)) fail_msg("credit returned before the declared latency");
    @(posedge clk);
    repeat (2) @(posedge clk);
    if (credits[0][0] !== CREDIT_W'(CAPACITY)) fail_msg("credit did not return to its own (tap, VC)");
    if (outstanding[0][0] !== 0) fail_msg("outstanding slot was not cleared");
    $display("PASS: S3 a freed credit returns to its own (tap, VC) after the declared latency");

    // S4: exhaustion refuses further grants on that pair.
    for (i = 0; i < CAPACITY; i = i + 1) do_grant(2, 3);
    if (credits[2][3] !== 0) fail_msg("pair did not reach exhaustion");
    req_tap = TAP_W'(2);
    req_vc = VC_W'(3);
    req_valid = 1'b1;
    @(posedge clk);
    if (req_grant) fail_msg("an exhausted pair granted another credit");
    req_valid = 1'b0;
    if (credits[2][4] !== CREDIT_W'(CAPACITY)) fail_msg("an exhausted pair disturbed another VC");
    $display("PASS: S4 an exhausted (tap, VC) refuses further grants and disturbs no other pair");

    // S5: full independence across taps and VCs.
    taps_before = 0;
    for (i = 0; i < NUM_VCS; i = i + 1) taps_before = taps_before + 1;
    do_grant(1, 5);
    if (credits[1][5] !== CREDIT_W'(CAPACITY - 1)) fail_msg("grant on (1,5) did not consume its credit");
    for (i = 0; i < N_TAPS; i = i + 1) begin
      if (i != 1 && credits[i][5] !== CREDIT_W'(CAPACITY)) fail_msg("tap credit changed on an unrelated tap");
    end
    if (alias_detected) fail_msg("alias detected on a well-formed sequence");
    $display("PASS: S5 taps and VCs are independent, and no alias is reported");

    // S6: a matured return and a new grant for the same pair must both apply.
    do_grant(1, 6);
    @(negedge clk);
    free_tap = TAP_W'(1);
    free_vc = VC_W'(6);
    free_valid = 1'b1;
    @(negedge clk);
    free_valid = 1'b0;
    repeat (LATENCY - 1) @(negedge clk);
    req_tap = TAP_W'(1);
    req_vc = VC_W'(6);
    req_valid = 1'b1;
    @(negedge clk);
    req_valid = 1'b0;
    if (credits[1][6] !== CREDIT_W'(CAPACITY - 1)) fail_msg("simultaneous return and grant lost the returned credit");
    if (outstanding[1][6] !== 1) fail_msg("simultaneous return and grant corrupted outstanding count");
    do_free(1, 6);
    repeat (LATENCY + 1) @(posedge clk);
    if (credits[1][6] !== CREDIT_W'(CAPACITY)) fail_msg("final credit did not return after simultaneous reuse");
    if (outstanding[1][6] !== 0) fail_msg("final outstanding count did not clear after simultaneous reuse");
    $display("PASS: S6 a matured return and same-pair grant are both accounted");

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
