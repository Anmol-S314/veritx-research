`ifndef ISLIP_SV
`define ISLIP_SV

// Single-iteration iSLIP, exactly as the fork implements it
// (booksim2 src/allocators/islip.cpp):
//   - grant phase:  each output grants the first requesting input at-or-after
//                   its pointer _gptrs[output] (round-robin, wrapping);
//   - accept phase: each input  accepts the first grant from its pointer
//                   _aptrs[input];
//   - pointers advance by one ONLY on a successful match:
//       _gptrs[o] = (in  + 1) % N ; _aptrs[i] = (out + 1) % N.
//
// Combinational on req (the router consumes the grant the same cycle it is
// produced); pointers are registered. Deterministic and seed-independent —
// that is what makes Gate R1 (per-flit cycle match) and Gate R2 (bit-identical
// FPGA) possible.

module islip #(
  parameter int N = 5          // inputs == outputs (square, as in the fork)
)(
  input  logic clk,
  input  logic rst_n,
  input  logic [N-1:0][N-1:0] req,   // req[in][out]
  output logic [N-1:0][N-1:0] grant  // grant[in][out], one-hot per row & col
);

  localparam int PW = $clog2(N);

  // round-robin "first at-or-after ptr" index within a column
  function automatic logic [PW-1:0] rr_pick(
    input logic [N-1:0]          col,
    input logic [PW-1:0]         ptr
  );
    logic [PW-1:0] best;
    logic found;
    best = '0;
    found = 1'b0;
    for (int k = 0; k < N; k++) begin
      int idx = (ptr + k) % N;
      if (col[idx] && !found) begin
        best  = idx[PW-1:0];
        found = 1'b1;
      end
    end
    rr_pick = best;
  endfunction

  // ---- grant phase: one winner per output ------------------------------
  logic [N-1:0][N-1:0] g_col_in;      // g_col_in[o][i] = req[i][o] (column o)
  logic [N-1:0][N-1:0] g_onehot;      // g_onehot[o][in]
  logic [N-1:0][PW-1:0] g_win;        // g_win[o] = winning input
  logic [N-1:0]        g_any;         // output o has a request
  logic [N-1:0][PW-1:0] gptr;

  for (genvar o = 0; o < N; o++) begin : gen_gcol
    for (genvar i = 0; i < N; i++) begin : gen_gcol_inner
      assign g_col_in[o][i] = req[i][o];
    end
  end

  for (genvar o = 0; o < N; o++) begin : gen_grant
    assign g_win[o] = rr_pick(g_col_in[o], gptr[o]);
    always_comb begin
      g_onehot[o] = '0;
      for (int i = 0; i < N; i++) begin
        if (g_col_in[o][i] && (i[PW-1:0] == g_win[o])) begin
          g_onehot[o][i] = 1'b1;
        end
      end
      g_any[o] = |g_col_in[o];
    end
  end

  // ---- accept phase: one winner per input ------------------------------
  logic [N-1:0][N-1:0] a_sel;         // a_sel[i][o]: input i would accept o
  logic [N-1:0][PW-1:0] a_win;        // a_win[i] = winning output
  logic [N-1:0][PW-1:0] aptr;

  // gather the grant column for each input across outputs
  logic [N-1:0][N-1:0] g_cols;        // g_cols[i][o] = g_onehot[o][i]
  for (genvar i = 0; i < N; i++) begin : gen_gcols
    for (genvar o = 0; o < N; o++) begin : gen_gcols_inner
      assign g_cols[i][o] = g_onehot[o][i];
    end
  end

  for (genvar i = 0; i < N; i++) begin : gen_accept2
    assign a_win[i] = rr_pick(g_cols[i], aptr[i]);
    always_comb begin
      a_sel[i] = '0;
      for (int o = 0; o < N; o++) begin
        if (g_cols[i][o] && (o[PW-1:0] == a_win[i])) begin
          a_sel[i][o] = 1'b1;
        end
      end
    end
  end

  // ---- matched pairs ----------------------------------------------------
  for (genvar i = 0; i < N; i++) begin : gen_match
    for (genvar o = 0; o < N; o++) begin : gen_match_inner
      assign grant[i][o] = a_sel[i][o] && g_onehot[o][i];
    end
  end

  // ---- pointer updates (only on the ACCEPTED pair, 1st-iteration rule) --
  always_ff @(posedge clk or negedge rst_n) begin
    if (!rst_n) begin
      for (int o = 0; o < N; o++) gptr[o] <= '0;
      for (int i = 0; i < N; i++) aptr[i] <= '0;
    end else begin
      for (int o = 0; o < N; o++) begin
        if (g_any[o] && grant[g_win[o]][o]) begin
          gptr[o] <= (g_win[o] + 1) % N;
        end
      end
      for (int i = 0; i < N; i++) begin
        if (|a_sel[i] && grant[i][a_win[i]]) begin
          aptr[i] <= (a_win[i] + 1) % N;
        end
      end
    end
  end

endmodule

`endif
