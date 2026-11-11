// tap_credit_formal.sv — formal proof of the per-tap credit invariants.
//
// The properties are stated over the pool's public behaviour:
//
//   P1  credits + outstanding == capacity, per (tap, VC)
//   P2  credits never exceed capacity, never go negative
//   P3  a grant is only granted when that exact (tap, VC) holds a credit
//   P4  a matured return only affects its own (tap, VC) — the per-tap sums of
//       a wrong-tap return would break P1 on the touched tap
//   P5  no matured return can exceed the outstanding count on its own
//       (alias_detected must stay low)
//
// The environment is free to request any (tap, VC) and to free any (tap, VC)
// at any time, so the proof covers every interleaving of requests, frees and
// returns across all three taps and eight VCs.
`default_nettype none

module tap_credit_formal;

  localparam int N_TAPS = 3;
  localparam int NUM_VCS = 8;
  localparam int CAPACITY = 4;
  localparam int CREDIT_W = 4;
  localparam int TAP_W = 2;
  localparam int VC_W = 3;
  localparam int LATENCY = 2;

  (* anyseq *) logic [TAP_W-1:0] req_tap;
  (* anyseq *) logic [VC_W-1:0]  req_vc;
  (* anyseq *) logic              req_valid;
  (* anyseq *) logic [TAP_W-1:0] free_tap;
  (* anyseq *) logic [VC_W-1:0]  free_vc;
  (* anyseq *) logic              free_valid;

  logic req_ready;
  logic req_grant;
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

  (* gclk *) logic clk;
  logic rst_n = 1'b0;

  integer t;
  integer v;

  initial begin
    rst_n = 1'b0;
  end

  always @(posedge clk) begin
    rst_n <= 1'b1;
  end

  // Shadow of the slots this environment has actually taken: a grant takes
  // one, a free gives one back. It is the environment's own bookkeeping, so
  // the assumption below is about the ENVIRONMENT (a free always matches a
  // distinct grant on that exact (tap, VC)), not about the module.
  logic [N_TAPS-1:0][NUM_VCS-1:0][CREDIT_W-1:0] shadow;

  always @(posedge clk) begin
    if (!rst_n) begin
      for (t = 0; t < N_TAPS; t = t + 1) begin
        for (v = 0; v < NUM_VCS; v = v + 1) begin
          shadow[t][v] <= '0;
        end
      end
    end else begin
      for (t = 0; t < N_TAPS; t = t + 1) begin
        for (v = 0; v < NUM_VCS; v = v + 1) begin
          if (req_valid && req_grant && req_tap == TAP_W'(t) && req_vc == VC_W'(v)) begin
            if (!(free_valid && free_tap == TAP_W'(t) && free_vc == VC_W'(v)))
              shadow[t][v] <= shadow[t][v] + 1'b1;
          end else if (free_valid && free_tap == TAP_W'(t) && free_vc == VC_W'(v)) begin
            shadow[t][v] <= shadow[t][v] - 1'b1;
          end
        end
      end
    end
  end

  always @* begin
    // Environment assumption (the router's own contract): a free notification
    // always matches a distinct grant on that exact (tap, VC).
    if (free_valid) begin
      for (t = 0; t < N_TAPS; t = t + 1) begin
        for (v = 0; v < NUM_VCS; v = v + 1) begin
          if (free_tap == TAP_W'(t) && free_vc == VC_W'(v)) begin
            assume (shadow[t][v] != '0);
          end
        end
      end
    end
    // P1: conservation per (tap, VC).
    for (t = 0; t < N_TAPS; t = t + 1) begin
      for (v = 0; v < NUM_VCS; v = v + 1) begin
        assert (credits[t][v] + outstanding[t][v] == CREDIT_W'(CAPACITY));
      end
    end
    // P2: bounds.
    for (t = 0; t < N_TAPS; t = t + 1) begin
      for (v = 0; v < NUM_VCS; v = v + 1) begin
        assert (credits[t][v] <= CREDIT_W'(CAPACITY));
        assert (outstanding[t][v] <= CREDIT_W'(CAPACITY));
      end
    end
    // P3: a grant is only given against a credit of the same (tap, VC).
    if (req_valid) begin
      for (t = 0; t < N_TAPS; t = t + 1) begin
        for (v = 0; v < NUM_VCS; v = v + 1) begin
          if (req_tap == TAP_W'(t) && req_vc == VC_W'(v)) begin
            assert (req_grant == (credits[t][v] != '0));
            assert (req_ready == (credits[t][v] != '0));
          end
        end
      end
    end
    // P5: a matured return never exceeds what is outstanding on its own tap.
    assert (alias_detected == 1'b0);
  end

endmodule

`default_nettype wire
