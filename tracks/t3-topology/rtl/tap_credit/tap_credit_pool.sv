`default_nettype none

// tap_credit_pool.sv — per-tap credit accounting for a shared, multi-tap
// wire.
//
// The composed family path today keeps one credit pool per (output port, VC):
// `cred[port][vc]`. That is not enough for a multidrop fabric. The pinned
// 74-agent contract is 162 shared wires of three taps each across 8 VCs, and
// every tap is a distinct destination: a credit returned on tap 1 must never
// release capacity on tap 0, and a VC must never borrow another VC's credit.
//
// This module is that accounting, isolated so it can be proven on its own:
//
//   * credits are held per (tap, VC) — there is no shared pool to alias
//     through;
//   * a grant consumes one credit of the exact (tap, VC) that was asked for;
//   * a returned credit is credited back to the exact (tap, VC) that produced
//     it, after the declared return latency;
//   * the invariant "credits held + credits outstanding == capacity per
//     (tap, VC)" holds at every cycle, and the per-tap sums are independent,
//     so a mis-routed return shows up immediately as a broken sum.
//
// The invariants are proved in tracks/t3-topology/rtl/tap_credit/
// tap_credit_formal.sby (bounded model check, smtbmc + z3).
module tap_credit_pool #(
  parameter int N_TAPS = 3,
  parameter int NUM_VCS = 8,
  parameter int CAPACITY = 8,
  parameter int CREDIT_W = 4,
  parameter int TAP_W = 2,
  parameter int VC_W = 3,
  parameter int LATENCY = 1
) (
  input  logic clk,
  input  logic rst_n,

  // Grant request: one (tap, VC) pair at a time.
  input  logic [TAP_W-1:0] req_tap,
  input  logic [VC_W-1:0]  req_vc,
  input  logic              req_valid,
  output logic              req_ready,
  output logic              req_grant,

  // Free notification: a slot became free on that exact tap and VC.
  input  logic [TAP_W-1:0] free_tap,
  input  logic [VC_W-1:0]  free_vc,
  input  logic              free_valid,

  // Per-(tap, VC) visibility (observation only). Packed arrays keep the
  // module inside the Verilog subset the formal engine reads.
  output logic [N_TAPS-1:0][NUM_VCS-1:0][CREDIT_W-1:0] credits,
  output logic [N_TAPS-1:0][NUM_VCS-1:0][CREDIT_W-1:0] outstanding,
  output logic alias_detected
);

  localparam int PIPE = (LATENCY > 0) ? LATENCY : 1;

  logic [N_TAPS-1:0][NUM_VCS-1:0][CREDIT_W-1:0] cred_q;
  logic [N_TAPS-1:0][NUM_VCS-1:0][CREDIT_W-1:0] out_q;
  logic [TAP_W-1:0] hist_tap [0:PIPE-1];
  logic [VC_W-1:0]  hist_vc  [0:PIPE-1];
  logic              hist_v   [0:PIPE-1];

  logic [N_TAPS-1:0][NUM_VCS-1:0][CREDIT_W-1:0] cred_next;
  logic [N_TAPS-1:0][NUM_VCS-1:0][CREDIT_W-1:0] out_next;

  // Loop counters are declared per loop. A shared module-scope counter is a
  // signal with a driver in every comb block that touches it, which is a
  // latch per block and, once two blocks write it, a conflicting driver.

  always @* begin
    for (int t = 0; t < N_TAPS; t = t + 1) begin
      for (int v = 0; v < NUM_VCS; v = v + 1) begin
        credits[t][v] = cred_q[t][v];
        outstanding[t][v] = out_q[t][v];
        cred_next[t][v] = cred_q[t][v];
        out_next[t][v] = out_q[t][v];
      end
    end
    // A pending return matures on the exact (tap, VC) that produced it.
    if (hist_v[PIPE-1]) begin
      for (int t = 0; t < N_TAPS; t = t + 1) begin
        for (int v = 0; v < NUM_VCS; v = v + 1) begin
          if (hist_tap[PIPE-1] == TAP_W'(t) && hist_vc[PIPE-1] == VC_W'(v)) begin
            cred_next[t][v] = cred_q[t][v] + 1'b1;
            out_next[t][v] = out_q[t][v] - 1'b1;
          end
        end
      end
    end
    // A grant consumes one credit of the exact (tap, VC) requested.
    if (req_valid && req_grant) begin
      for (int t = 0; t < N_TAPS; t = t + 1) begin
        for (int v = 0; v < NUM_VCS; v = v + 1) begin
          if (req_tap == TAP_W'(t) && req_vc == VC_W'(v)) begin
            // A matured return and a new grant may target the same pair in
            // one cycle; apply the grant to the already-adjusted next state.
            cred_next[t][v] = cred_next[t][v] - 1'b1;
            out_next[t][v] = out_next[t][v] + 1'b1;
          end
        end
      end
    end
  end

  // A grant is allowed only when that exact (tap, VC) has a credit.
  always @* begin
    req_ready = 1'b0;
    req_grant = 1'b0;
    if (req_valid) begin
      for (int t = 0; t < N_TAPS; t = t + 1) begin
        for (int v = 0; v < NUM_VCS; v = v + 1) begin
          if (req_tap == TAP_W'(t) && req_vc == VC_W'(v)) begin
            req_ready = (cred_q[t][v] != '0);
            req_grant = (cred_q[t][v] != '0);
          end
        end
      end
    end
  end

  // Alias detection: a matured return must correspond to an outstanding
  // credit on that exact (tap, VC); otherwise a return crossed taps.
  always @* begin
    alias_detected = 1'b0;
    if (hist_v[PIPE-1]) begin
      for (int t = 0; t < N_TAPS; t = t + 1) begin
        for (int v = 0; v < NUM_VCS; v = v + 1) begin
          if (hist_tap[PIPE-1] == TAP_W'(t) && hist_vc[PIPE-1] == VC_W'(v)) begin
            if (out_q[t][v] == '0) alias_detected = 1'b1;
          end
        end
      end
    end
  end

  always_ff @(posedge clk or negedge rst_n) begin
    if (!rst_n) begin
      for (int t = 0; t < N_TAPS; t = t + 1) begin
        for (int v = 0; v < NUM_VCS; v = v + 1) begin
          cred_q[t][v] <= CREDIT_W'(CAPACITY);
          out_q[t][v] <= '0;
        end
      end
      for (int t = 0; t < PIPE; t = t + 1) begin
        hist_tap[t] <= '0;
        hist_vc[t] <= '0;
        hist_v[t] <= 1'b0;
      end
    end else begin
      for (int t = 0; t < PIPE; t = t + 1) begin
        hist_tap[t] <= '0;
        hist_vc[t] <= '0;
        hist_v[t] <= 1'b0;
      end
      if (free_valid) begin
        hist_tap[0] <= free_tap;
        hist_vc[0] <= free_vc;
        hist_v[0] <= 1'b1;
      end
      for (int t = 1; t < PIPE; t = t + 1) begin
        hist_tap[t] <= hist_tap[t-1];
        hist_vc[t] <= hist_vc[t-1];
        hist_v[t] <= hist_v[t-1];
      end
      for (int t = 0; t < N_TAPS; t = t + 1) begin
        for (int v = 0; v < NUM_VCS; v = v + 1) begin
          cred_q[t][v] <= cred_next[t][v];
          out_q[t][v] <= out_next[t][v];
        end
      end
    end
  end

endmodule

`default_nettype wire
