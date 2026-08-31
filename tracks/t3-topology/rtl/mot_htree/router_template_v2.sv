// router.sv — Single-class DOR wormhole router with LockIn arbitration
// Architecture: multi-plane physical networks (FlooNoC-inspired)
//
// Key properties:
//   - Per-flit DOR routing: every flit computes its own next port from dst
//   - NO rt_alloc/rt_out: route inheritance removed (proven to cause Bug A)
//   - LockIn arbiter: once a head wins an output, it locks until tail
//     or LOCK_TIMEOUT cycles of no progress
//   - Credit-based flow control: per output port, BUF_DEPTH credits
//   - Output stage holds flit until downstream accepts (backpressure safe)
//
`include "noc_pkg.sv"

module router #(
  parameter int ID = 0,
  parameter int DEG = 1,
  parameter logic [noc_pkg::PORT_W*noc_pkg::N_ROUTERS-1:0] RT_MIN = '0
) (
  input  logic clk,
  input  logic rst_n,
  input  noc_pkg::flit_raw_t [0:DEG-1] n_in_flit,
  input  logic      [0:DEG-1] n_in_valid,
  output logic      [0:DEG-1] n_in_ready,
  output noc_pkg::flit_raw_t [0:DEG-1] n_out_flit,
  output logic      [0:DEG-1] n_out_valid,
  input  logic      [0:DEG-1] n_out_ready,
  input  noc_pkg::flit_raw_t local_in_flit,
  input  logic       local_in_valid,
  output logic       local_in_ready,
  output noc_pkg::flit_raw_t local_out_flit,
  output logic       local_out_valid,
  input  logic       local_out_ready
);

  // ── Geometry from package ──
  localparam int NUM_PORTS  = noc_pkg::MAX_DEG + 1;
  localparam int LOCAL_PORT = noc_pkg::MAX_DEG;
  localparam int BUF_DEPTH  = noc_pkg::BUF_DEPTH;
  localparam int DST_W      = noc_pkg::DST_W;
  localparam int PORT_W     = noc_pkg::PORT_W;
  localparam int TYPE_W     = noc_pkg::TYPE_W;
  localparam int CRED_W     = noc_pkg::CRED_W;
  localparam int QIDX_W     = $clog2(BUF_DEPTH) > 0 ? $clog2(BUF_DEPTH) : 1;

  localparam logic [TYPE_W-1:0] FT_HEAD   = 2'd0;
  localparam logic [TYPE_W-1:0] FT_BODY   = 2'd1;
  localparam logic [TYPE_W-1:0] FT_TAIL   = 2'd2;
  localparam logic [TYPE_W-1:0] FT_SINGLE = 2'd3;

  localparam int LOCK_TIMEOUT = 16;

  // ── Flit field accessors ──
  function automatic logic [DST_W-1:0] get_dst(input noc_pkg::flit_raw_t f);
    return f[48 +: DST_W];
  endfunction
  function automatic logic [TYPE_W-1:0] get_type(input noc_pkg::flit_raw_t f);
    return f[noc_pkg::TYPE_MSB:noc_pkg::TYPE_LSB];
  endfunction
  function automatic logic [PORT_W-1:0] get_rt_min(input int dst);
    return RT_MIN[dst*PORT_W +: PORT_W];
  endfunction

  // ════════════════════════════════════════════════════════════════════════
  // STATE
  // ════════════════════════════════════════════════════════════════════════

  // Per-input ring FIFO
  noc_pkg::flit_raw_t q [0:NUM_PORTS-1][0:BUF_DEPTH-1];
  logic [QIDX_W-1:0] q_head [0:NUM_PORTS-1];
  logic [QIDX_W-1:0] q_tail [0:NUM_PORTS-1];
  logic [$clog2(BUF_DEPTH+1)-1:0] q_cnt [0:NUM_PORTS-1];

  // Per-output credits
  logic [CRED_W-1:0] cred [0:NUM_PORTS-1];

  // Per-output LockIn state
  logic [PORT_W-1:0] lock_owner [0:NUM_PORTS-1];
  logic              lock_active [0:NUM_PORTS-1];
  logic [3:0]        lock_cnt    [0:NUM_PORTS-1];

  // Per-output round-robin pointer
  logic [$clog2(NUM_PORTS)-1:0] rr [0:NUM_PORTS-1];

  // Output stage: flit held until downstream accepts
  noc_pkg::flit_raw_t out_flit [0:NUM_PORTS-1];
  logic               out_valid [0:NUM_PORTS-1];

  // ════════════════════════════════════════════════════════════════════════
  // COMBINATIONAL: candidates + arbitration + admission
  // ════════════════════════════════════════════════════════════════════════

  logic [PORT_W-1:0] cand [0:NUM_PORTS-1];
  logic               cand_v [0:NUM_PORTS-1];
  logic [PORT_W-1:0] best [0:NUM_PORTS-1];
  logic               best_v [0:NUM_PORTS-1];
  logic [0:NUM_PORTS-1] grant;
  logic [PORT_W-1:0] grant_idx [0:NUM_PORTS-1];
  logic [0:NUM_PORTS-1] in_ready_c;

  always_comb begin
    // ── Candidate outputs: per-flit DOR (no rt_alloc/rt_out) ──
    // Each input computes its own next port from its head flit's dst.
    // The grant scan below resolves conflicts (multiple inputs → same output).
    for (int p = 0; p < NUM_PORTS; p++) begin
      cand_v[p] = 1'b0;
      cand[p] = '0;
      if (q_cnt[p] > 0) begin
        automatic noc_pkg::flit_raw_t f = q[p][q_head[p]];
        automatic logic [DST_W-1:0] d = get_dst(f);
        if (d == ID[DST_W-1:0]) begin
          cand[p] = LOCAL_PORT[PORT_W-1:0];
          cand_v[p] = 1'b1;
        end else begin
          cand[p] = get_rt_min(d);
          cand_v[p] = 1'b1;
        end
      end
    end

    // ── Per-output arbitration: LockIn-aware round-robin ──
    for (int i = 0; i < NUM_PORTS; i++) begin
      best_v[i] = 1'b0;
      best[i] = '0;
      // Grant requires: credits available AND output slot free
      if (cred[i] > 0 && !out_valid[i]) begin
        if (lock_active[i]) begin
          // LockIn: only the owner can use this output
          automatic int owner = lock_owner[i];
          if (cand_v[owner] && cand[owner] == i[PORT_W-1:0]) begin
            best[i] = owner[PORT_W-1:0];
            best_v[i] = 1'b1;
          end
          // else: owner has no data → lock will timeout
        end else begin
          // No lock: round-robin scan over all inputs
          for (int s = 0; s < NUM_PORTS; s++) begin
            automatic int idx = int'(rr[i] + s) % NUM_PORTS;
            if (cand_v[idx] && cand[idx] == i[PORT_W-1:0]) begin
              best[i] = idx[PORT_W-1:0];
              best_v[i] = 1'b1;
              break;
            end
          end
        end
      end
    end

    // ── Resolve: each input grants to at most one output ──
    for (int p = 0; p < NUM_PORTS; p++) begin
      grant[p] = 1'b0;
      grant_idx[p] = '0;
    end
    for (int i = 0; i < NUM_PORTS; i++) begin
      if (best_v[i]) begin
        automatic int p = best[i];
        if (!grant[p]) begin
          grant[p] = 1'b1;
          grant_idx[p] = i[PORT_W-1:0];
        end
      end
    end

    // ── Admission: buffer not full ──
    for (int p = 0; p < NUM_PORTS; p++)
      in_ready_c[p] = (q_cnt[p] < BUF_DEPTH);
  end

  // Drive output ports
  assign n_in_ready = in_ready_c[LOCAL_PORT-1:0];
  assign local_in_ready = in_ready_c[LOCAL_PORT];

  for (genvar i = 0; i < DEG; i++) begin : gen_nout
    assign n_out_flit[i]  = out_flit[i];
    assign n_out_valid[i] = out_valid[i];
  end
  assign local_out_flit  = out_flit[LOCAL_PORT];
  assign local_out_valid = out_valid[LOCAL_PORT];

  // ════════════════════════════════════════════════════════════════════════
  // SEQUENTIAL: state update
  // ════════════════════════════════════════════════════════════════════════

  always_ff @(posedge clk or negedge rst_n) begin
    if (!rst_n) begin
      for (int p = 0; p < NUM_PORTS; p++) begin
        q_cnt[p] <= '0;
        q_head[p] <= '0;
        q_tail[p] <= '0;
      end
      for (int i = 0; i < NUM_PORTS; i++) begin
        cred[i] <= BUF_DEPTH[CRED_W-1:0];
        lock_owner[i] <= '0;
        lock_active[i] <= 1'b0;
        lock_cnt[i] <= '0;
        rr[i] <= '0;
        out_valid[i] <= 1'b0;
      end
    end else begin

      // ── 1. Output stage: accept or hold ──
      for (int i = 0; i < NUM_PORTS; i++) begin
        automatic logic rdy;
        if (i == LOCAL_PORT) rdy = local_out_ready;
        else                 rdy = n_out_ready[i];
        if (out_valid[i] && rdy) begin
          out_valid[i] <= 1'b0;
          cred[i] <= cred[i] + 1;
        end
      end

      // ── 2. Network input injection ──
      for (int p = 0; p < LOCAL_PORT; p++) begin
        if (in_ready_c[p] && n_in_valid[p]) begin
          q[p][q_tail[p]] <= n_in_flit[p];
          q_tail[p] <= (q_tail[p] + 1) % BUF_DEPTH;
          q_cnt[p] <= q_cnt[p] + 1;
        end
      end

      // ── 3. Local injection ──
      if (in_ready_c[LOCAL_PORT] && local_in_valid) begin
        q[LOCAL_PORT][q_tail[LOCAL_PORT]] <= local_in_flit;
        q_tail[LOCAL_PORT] <= (q_tail[LOCAL_PORT] + 1) % BUF_DEPTH;
        q_cnt[LOCAL_PORT] <= q_cnt[LOCAL_PORT] + 1;
      end

      // ── 4. Grant: dequeue + load output + LockIn ──
      for (int p = 0; p < NUM_PORTS; p++) begin
        if (grant[p] && q_cnt[p] > 0) begin
          automatic noc_pkg::flit_raw_t f = q[p][q_head[p]];
          automatic int outp = grant_idx[p];

          // Dequeue
          q_head[p] <= (q_head[p] + 1) % BUF_DEPTH;
          q_cnt[p] <= q_cnt[p] - 1;

          // Load output stage + consume credit
          out_flit[outp] <= f;
          out_valid[outp] <= 1'b1;
          cred[outp] <= cred[outp] - 1;

          // LockIn: head grants lock the output to this input
          if (get_type(f) == FT_HEAD || get_type(f) == FT_SINGLE) begin
            lock_owner[outp] <= p[PORT_W-1:0];
            lock_active[outp] <= 1'b1;
            lock_cnt[outp] <= '0;
          end

          // Tail releases lock
          if (get_type(f) == FT_TAIL || get_type(f) == FT_SINGLE) begin
            lock_active[outp] <= 1'b0;
          end

          // Update round-robin
          rr[outp] <= (p[$clog2(NUM_PORTS)-1:0] + 1) % NUM_PORTS;
        end
      end

      // ── 5. Lock timeout ──
      for (int i = 0; i < NUM_PORTS; i++) begin
        if (lock_active[i]) begin
          if (!out_valid[i]) begin
            automatic int owner = lock_owner[i];
            if (cand_v[owner] && cand[owner] == i[PORT_W-1:0]) begin
              lock_cnt[i] <= '0;
            end else begin
              lock_cnt[i] <= lock_cnt[i] + 1;
              if (lock_cnt[i] == LOCK_TIMEOUT[3:0])
                lock_active[i] <= 1'b0;
            end
          end else begin
            lock_cnt[i] <= '0;
          end
        end
      end

    end
  end

endmodule
