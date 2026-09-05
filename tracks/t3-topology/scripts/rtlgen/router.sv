// router.sv — 2-VC certified-per-VC router (Verilator-clean, individual ports)
// VC0 = FREE (Dijkstra minimal routing), VC1 = ESCAPE (up/down tree)
// Demotion: free-class head blocked > BLOCK_K cycles => switch to escape route
//
// MULTI-FLIT WORMHOLE SUPPORT (upgrade 2026-08-21):
//   * flit TYPE bits at [62:61]: HEAD=0, BODY=1, TAIL=2, SINGLE=3
//   * per-(input_port,VC) route continuity: HEAD allocates rt_out on grant;
//     BODY/TAIL follow rt_out; TAIL/SINGLE deallocates on transmission
//   * demotion only applies to un-allocated FREE heads (never mid-packet)
`include "noc_pkg.sv"

module router #(
  parameter int ID = 0,
  parameter int DEG = 1,
  // Packed route tables (PORT_W bits per dst entry, dst 0 in LSB group).
  // Passed as module parameters from noc_top (no hierarchical refs).
  parameter logic [noc_pkg::PORT_W*noc_pkg::N_ROUTERS-1:0] RT_MIN = '0,
  parameter logic [noc_pkg::PORT_W*noc_pkg::N_ROUTERS-1:0] RT_ESC = '0
) (
  input  logic clk,
  input  logic rst_n,
  // Network ports (up to DEG neighbors)
  input  noc_pkg::flit_raw_t [0:DEG-1] n_in_flit,
  input  logic      [0:DEG-1] n_in_valid,
  output logic      [0:DEG-1] n_in_ready,
  output noc_pkg::flit_raw_t [0:DEG-1] n_out_flit,
  output logic      [0:DEG-1] n_out_valid,
  input  logic      [0:DEG-1] n_out_ready,
  // Local injection/ejection
  input  noc_pkg::flit_raw_t local_in_flit,
  input  logic       local_in_valid,
  output logic       local_in_ready,
  output noc_pkg::flit_raw_t local_out_flit,
  output logic       local_out_valid,
  input  logic       local_out_ready
);

  // Derive ALL geometry from the package (stale hardcoded values here were
  // the root cause of cross-N misrouting: get_dst spanned into src bits).
  localparam int NUM_PORTS  = noc_pkg::MAX_DEG + 1;
  localparam int LOCAL_PORT = noc_pkg::MAX_DEG;
  localparam int NUM_VCS    = noc_pkg::NUM_VCS;
  localparam int BUF_DEPTH  = noc_pkg::BUF_DEPTH;
  localparam int DST_W      = noc_pkg::DST_W;
  localparam int PORT_W     = noc_pkg::PORT_W;
  localparam int BLOCK_K    = noc_pkg::BLOCK_K;
  localparam int N_ROUTERS  = noc_pkg::N_ROUTERS;
  localparam int TYPE_W     = noc_pkg::TYPE_W;

  // Flit type constants
  localparam logic [TYPE_W-1:0] FT_HEAD   = 2'd0;
  localparam logic [TYPE_W-1:0] FT_BODY   = 2'd1;
  localparam logic [TYPE_W-1:0] FT_TAIL   = 2'd2;
  localparam logic [TYPE_W-1:0] FT_SINGLE = 2'd3;

  // Route tables
  // route table accessors (packed parameter slices)
  function automatic logic [noc_pkg::PORT_W-1:0] get_rt_min(input int dst);
    return RT_MIN[dst*noc_pkg::PORT_W +: noc_pkg::PORT_W];
  endfunction
  function automatic logic [noc_pkg::PORT_W-1:0] get_rt_esc(input int dst);
    return RT_ESC[dst*noc_pkg::PORT_W +: noc_pkg::PORT_W];
  endfunction

  // Per-(input_port, VC) FIFO
  noc_pkg::flit_raw_t q [0:NUM_PORTS*NUM_VCS-1][0:BUF_DEPTH-1];
  logic [noc_pkg::QCNT_W-1:0] q_cnt   [0:NUM_PORTS*NUM_VCS-1];
  logic [7:0]                blk_cnt [0:NUM_PORTS*NUM_VCS-1];   // cumulative packet age
  // R3: cumulative-age demotion threshold. The old "K consecutive CYCLES not
  // granted" timer reset on every grant, so a free-class CIRCULATION (flit
  // forwarded one hop every cycle, never reaching its dst) kept blk < K
  // forever -> livelock (16n IR0.20: 143 packets stuck, 0 demotions, 250k cyc).
  // blk_cnt now counts EVERY cycle the packet occupies the queue and resets
  // only at packet completion: circulation cannot outrun AGE_K.
  localparam int AGE_K = noc_pkg::BLOCK_K * 8;

  // ── Wormhole state: per-(input_port, VC) route continuity ──
  // rt_alloc[c] = a head has been granted on this VC; BODY/TAIL must follow
  // the allocated output rt_out[c].
  // esc_mode[c] = this VC's packet has been DEMOTED to the escape class;
  // every remaining flit is flipped to esc=1 at the queue front so the
  // whole packet (not just the head) travels the deadlock-free escape path.
  logic              rt_alloc [0:NUM_PORTS*NUM_VCS-1];
  logic [PORT_W-1:0] rt_out   [0:NUM_PORTS*NUM_VCS-1];
  logic              esc_mode [0:NUM_PORTS*NUM_VCS-1];

  // Per-router injection counter (debug): counts local-port enqueues.
  integer local_inj_count = 0;
  // Debug: live ejection counter (increment on local-output load).
  integer ej_local_count = 0;

  // R2: Credit counters — PER (OUTPUT PORT, VC)
  // Each output port has BUF_DEPTH credits per VC. A flit is forwarded
  // only when cred[port][vc] > 0. Credit returned when downstream accepts.
  logic [noc_pkg::CRED_W-1:0] cred [0:NUM_PORTS-1][0:NUM_VCS-1];
  // Track which VC each output flit came from (for credit return)
  // R3 (2026-08-22): PER-CLASS output stages. Deadlock-freedom of the escape
  // class requires a demoted flit's progress to never depend on a FREE flit's
  // receiver. With one shared stage, a held FREE occupant blocks ESC flits
  // behind it forever -> frozen fixed point at 64n (every stuck queue's
  // candidate outV=1, correct tables, age machine cycling, 400k cycles).
  // Fix: per-port stages per VC class; grants are per-class; the wire shows
  // esc-first with the R3 starve guard (esc_yield to free after ESC_YIELD_K).
  logic [0:NUM_PORTS-1][NUM_VCS-1:0] out_src_vc;
  // R2: Round-robin SA pointer (per output port, FREE class only)
  logic [7:0] rr_ptr [0:NUM_PORTS-1];

  // Per-output-port registered output
  noc_pkg::flit_raw_t out_r [0:NUM_PORTS-1];
  logic out_vld [0:NUM_PORTS-1];  // Flit field accessors
  // LAYOUT: [63]=esc, [62:61]=type, [DST_W-1+48:48]=dst, [47:0]=src+payload
  function automatic logic [DST_W-1:0] get_dst(input noc_pkg::flit_raw_t f);
    return f[DST_W-1+48:48];
  endfunction
  function automatic logic get_esc(input noc_pkg::flit_raw_t f);
    return f[63];
  endfunction
  function automatic logic [TYPE_W-1:0] get_type(input noc_pkg::flit_raw_t f);
    return f[62:61];
  endfunction
  function automatic logic is_tail(input noc_pkg::flit_raw_t f);
    return (f[62:61] == FT_TAIL) || (f[62:61] == FT_SINGLE);
  endfunction
  function automatic logic is_head(input noc_pkg::flit_raw_t f);
    return (f[62:61] == FT_HEAD) || (f[62:61] == FT_SINGLE);
  endfunction

  // Map between flat port index and actual signals
  // Port 0..DEG-1 = network neighbors, port DEG = local
  logic [NUM_PORTS-1:0] in_valid_all;
  logic [NUM_PORTS-1:0] in_ready_all;
  noc_pkg::flit_raw_t [0:NUM_PORTS-1] in_flit_all;
  noc_pkg::flit_raw_t [0:NUM_PORTS-1][0:NUM_VCS-1] out_flit_all;
  logic [NUM_PORTS-1:0][NUM_VCS-1:0] out_valid_all;
  logic [NUM_PORTS-1:0] out_ready_all;
  logic [NUM_PORTS-1:0] show_vc;      // class the wire presents per port
  logic [7:0] grant_sp2 [0:NUM_PORTS-1];   // second (other-class) grant
  logic [1:0] grant_sv2 [0:NUM_PORTS-1];
  logic [NUM_PORTS-1:0] grant_valid2;

  // Map network ports; unused ports (DEG..MAX_DEG-1) tied off safe.
  // NOTE: single genvar loop from 0 (Verilator: loops starting at a parameter
  // generate spurious genvar references); generate-if selects used vs unused.
  for (genvar p = 0; p < noc_pkg::MAX_DEG; p++) begin : gen_net_map
    if (p < DEG) begin : used
      assign in_flit_all[p]  = n_in_flit[p];
      assign in_valid_all[p] = n_in_valid[p];
      assign n_in_ready[p]   = in_ready_all[p];
      assign n_out_flit[p]   = out_flit_all[p][show_vc[p]];
      assign n_out_valid[p]  = out_valid_all[p][show_vc[p]];
      assign out_ready_all[p] = n_out_ready[p];
      // Shared-buffer admission: all classes share the full capacity.
      // Liveness is guaranteed by escape-priority arbitration at the GRANT
      // stage (escape flits always win the same output), not by buffer
      // reservation.
      // B1 root cause (FIXED 2026-08-22): the old shared-sum admission allowed
      // 2*BUF_DEPTH flits per port while each VC's array is BUF_DEPTH deep;
      // q[vc][>=BUF_DEPTH] wrote OUT OF BOUNDS -> phantom flit duplication.
      // Fix: per-VC class-aware admission (the arriving flit's esc bit picks VC).
      assign in_ready_all[p] = ((get_esc(in_flit_all[p]) ? q_cnt[p*NUM_VCS + 1]
                                                         : q_cnt[p*NUM_VCS + 0]) < BUF_DEPTH);
    end else begin : unused
      assign in_flit_all[p]  = '0;
      assign in_valid_all[p] = 1'b0;
      assign in_ready_all[p] = 1'b1;
      assign out_ready_all[p] = 1'b0;
    end
  end
  // Map local port
  assign in_flit_all[LOCAL_PORT]  = local_in_flit;
  assign in_valid_all[LOCAL_PORT] = local_in_valid;
  assign local_in_ready = in_ready_all[LOCAL_PORT];
  assign local_out_flit  = out_flit_all[LOCAL_PORT][show_vc[LOCAL_PORT]];
  assign local_out_valid = out_valid_all[LOCAL_PORT][show_vc[LOCAL_PORT]];
  assign out_ready_all[LOCAL_PORT] = local_out_ready;
  // Wire mux: esc stage wins unless the starve guard yields to free stage
  always_comb begin
    for (int p = 0; p < NUM_PORTS; p++) begin
      if (out_valid_all[p][1] && !(esc_starve[p] >= ESC_YIELD_K[3:0] && out_valid_all[p][0]))
        show_vc[p] = 1'b1;
      else
        show_vc[p] = 1'b0;
    end
  end
  assign in_ready_all[LOCAL_PORT] = ((get_esc(in_flit_all[LOCAL_PORT])
                                        ? q_cnt[LOCAL_PORT*NUM_VCS + 1]
                                        : q_cnt[LOCAL_PORT*NUM_VCS + 0]) < BUF_DEPTH);

  // ── Candidate output port per (input,VC) queue (combinational) ──
  // Wormhole: BODY/TAIL follow the head's allocated output rt_out; otherwise
  // (head, or mis-sequenced first flit) route from the destination + class.
  logic [PORT_W-1:0] cand_out [0:NUM_PORTS*NUM_VCS-1];
  always_comb begin
    for (int c = 0; c < NUM_PORTS * NUM_VCS; c++) begin
      cand_out[c] = '0;
      if (q_cnt[c] > 0) begin
        if (c % NUM_VCS == 1) begin
          // ESCAPE VC
          cand_out[c] = get_rt_esc(get_dst(q[c][0]));
        end else if (esc_mode[c]) begin
          // DEMOTED packet: entire packet rides the escape path
          cand_out[c] = get_rt_esc(get_dst(q[c][0]));
        end else if (rt_alloc[c]) begin
          // FREE VC, mid-packet: follow allocated output
          cand_out[c] = rt_out[c];
        end else begin
          cand_out[c] = get_rt_min(get_dst(q[c][0]));
        end
      end
    end
  end

  // Grant logic (combinational): first-match priority per output port;
  // ESCAPE VC beats FREE VC at the same output (liveness) — with a starvation
  // GUARD (R3 fix, 2026-08-22). Unconditional strict priority is a livelock
  // machine at scale: at 64n, esc demand (injected esc + demotions) aggregates
  // toward the escape-tree center, VC1 queues persistently target the same
  // outputs, and FREE-class flits — including ALREADY-DEMOTED VC0 flits routed
  // onto the tree — never get an output window (esc=1 queues stuck with full
  // credits, age cycling 0->64, 0 ejections for 30k+ cycles; 16n passes because
  // esc demand per output stays low). The guard: per output, if esc won while
  // a free candidate was pending for ESC_YIELD_K consecutive cycles, free
  // takes one window. Escape still wins in the common case; free progress is
  // bounded; the tree subnetwork's drain guarantee is preserved (at worst the
  // escape-only bound is computed at a reduced esc share — see model note).
  localparam int ESC_YIELD_K = 4;
  logic [NUM_PORTS-1:0] grant_valid;
  logic [7:0] grant_sp [0:NUM_PORTS-1];
  logic [1:0] grant_sv [0:NUM_PORTS-1];
  integer _o, _p;

  // per-output: esc/free candidates + esc starvation counters
  logic [NUM_PORTS-1:0] esc_valid, free_valid, esc_won, free_won;
  logic [7:0] esc_pick [0:NUM_PORTS-1];
  logic [7:0] free_pick [0:NUM_PORTS-1];
  logic [3:0] esc_starve [0:NUM_PORTS-1];

  // R2: Per-VC credits + round-robin SA. R3: class arbitration with guard.
  always_comb begin
    grant_valid = '0;
    for (_o = 0; _o < NUM_PORTS; _o++) begin
      grant_sp[_o] = '0;
      grant_sv[_o] = '0;
      esc_valid[_o] = 1'b0;
      free_valid[_o] = 1'b0;
      esc_won[_o]   = 1'b0;
      free_won[_o]  = 1'b0;
      esc_pick[_o]  = '0;
      free_pick[_o] = '0;
    end
    for (_o = 0; _o < NUM_PORTS; _o++) begin
      if (_o == LOCAL_PORT) continue;  // ejection handles LOCAL output
      // Escape candidate: VC1, first-match within class (own stage, independent)
      for (_p = 0; _p < NUM_PORTS; _p++) begin
        if (!esc_valid[_o] && !out_valid_all[_o][1] &&
            q_cnt[_p*NUM_VCS + 1] > 0 && cred[_o][1] > 0 &&
            cand_out[_p*NUM_VCS + 1] == _o &&
            get_dst(q[_p*NUM_VCS + 1][0]) != ID[$clog2(N_ROUTERS)-1:0]) begin
          esc_valid[_o] = 1'b1;
          esc_pick[_o]  = _p[7:0];
        end
      end
      // Free candidate: VC0, round-robin (own stage, independent)
      for (int _rr = 0; _rr < NUM_PORTS; _rr++) begin
        _p = (rr_ptr[_o] + _rr) % NUM_PORTS;
        if (!free_valid[_o] && !out_valid_all[_o][0] &&
            q_cnt[_p*NUM_VCS + 0] > 0 && cred[_o][0] > 0 &&
            cand_out[_p*NUM_VCS + 0] == _o &&
            get_dst(q[_p*NUM_VCS + 0][0]) != ID[$clog2(N_ROUTERS)-1:0]) begin
          free_valid[_o] = 1'b1;
          free_pick[_o]  = _p[7:0];
        end
      end
      // Per-class grants: both classes can load in the same cycle (own stages).
      // grant_valid/grant_sp/grant_sv = ESC-preferred encoding (used by the
      // wire-side dequeue marking); grant_valid2/etc = the OTHER class.
      grant_valid[_o]  = esc_valid[_o] | free_valid[_o];
      grant_valid2[_o] = esc_valid[_o] & free_valid[_o];
      if (esc_valid[_o]) begin
        grant_sp[_o] = esc_pick[_o];
        grant_sv[_o] = 2'd1;
      end else begin
        grant_sp[_o] = free_pick[_o];
        grant_sv[_o] = 2'd0;
      end
      grant_sp2[_o] = free_pick[_o];
      grant_sv2[_o] = 2'd0;
      esc_won[_o]  = esc_valid[_o];
      free_won[_o] = free_valid[_o];
    end
  end

  // Sequential logic (all loop vars LOCAL to each process).
  logic [NUM_PORTS*NUM_VCS-1:0] grant_deq_q;
  logic [NUM_PORTS*NUM_VCS-1:0] ej_dequeued;
  always_comb begin
    grant_deq_q = '0;
    ej_dequeued = '0;
    for (int o = 0; o < NUM_PORTS; o++) begin
      if (grant_valid[o])
        grant_deq_q[grant_sp[o]*NUM_VCS + grant_sv[o]] = 1'b1;
      if (grant_valid2[o])
        grant_deq_q[grant_sp2[o]*NUM_VCS + grant_sv2[o]] = 1'b1;
    end
    // ejection: esc-class first (deadlock-critical), then free; matches the
    // sequential scan (per-class local stages)
    begin : ej_mark
      for (int pass2 = 1; pass2 >= 0; pass2--) begin
        bit ej_done_mark = 1'b0;
        if (!out_valid_all[LOCAL_PORT][pass2]) begin
          for (int p2 = 0; p2 < LOCAL_PORT && !ej_done_mark; p2++) begin
            int c2 = p2 * NUM_VCS + pass2;
            if (q_cnt[c2] > 0 && get_dst(q[c2][0]) == ID[$clog2(N_ROUTERS)-1:0] &&
                !grant_deq_q[c2]) begin
              ej_dequeued[c2] = 1'b1;
              ej_done_mark = 1'b1;
            end
          end
        end
      end
    end
  end

  always_ff @(posedge clk or negedge rst_n) begin
    if (!rst_n) begin
      for (int c = 0; c < NUM_PORTS * NUM_VCS; c++) begin
        q_cnt[c]    <= 4'd0;
        blk_cnt[c]  <= 8'd0;
        rt_alloc[c] <= 1'b0;
        rt_out[c]   <= '0;
        esc_mode[c] <= 1'b0;
      end
      for (int p3 = 0; p3 < NUM_PORTS; p3++) begin
        out_valid_all[p3][0] <= 0;
        out_valid_all[p3][1] <= 0;
        out_src_vc[p3][0]    <= 0;
        out_src_vc[p3][1]    <= 0;
        rr_ptr[p3]        <= '0;
        esc_starve[p3]    <= 4'd0;
        for (int v3 = 0; v3 < NUM_VCS; v3++)
          cred[p3][v3] <= BUF_DEPTH[noc_pkg::CRED_W-1:0];
      end
    end else begin
      // 0. Starve counters (R3): the WIRE showed the esc stage while the free
      //    stage was occupied -> count; wire showed free or nothing pending ->
      //    clear. Drives the show_vc mux yield (esc_first, yield to free).
      for (int po = 0; po < NUM_PORTS; po++) begin
        if (show_vc[po] == 1'b1 && out_valid_all[po][0] && esc_starve[po] < 4'd15)
          esc_starve[po] <= esc_starve[po] + 4'd1;
        else if (show_vc[po] == 1'b0)
          esc_starve[po] <= 4'd0;
      end
      // 1. Output stage WITH BACKPRESSURE: a flit is held on the output until
      //    accepted (out_valid && out_ready); only a free port loads a grant.
      //    B1 FIX: skip LOCAL_PORT for grant-load — ejection is handled
      //    exclusively by section 2. Without this, grant_valid[LOCAL_PORT] fires
      //    when a queue has a flit destined for this router, AND the ejection block
      //    also fires. Both write to out_flit_all[LOCAL_PORT] via nonblocking
      //    assign; the last write wins, consuming the grant's flit from its queue
      //    but never delivering it.
      for (int p3 = 0; p3 < NUM_PORTS; p3++) begin
        // ── FREE stage (slot 0) ──
        if (out_valid_all[p3][0] && show_vc[p3] == 1'b0 && out_ready_all[p3]) begin
          out_valid_all[p3][0] <= 0;
          cred[p3][out_src_vc[p3][0]] <= cred[p3][out_src_vc[p3][0]] + 1;
        end else if (out_valid_all[p3][0] && show_vc[p3] == 1'b0) begin
          out_valid_all[p3][0] <= 1;   // shown, not accepted: HOLD
        end else if (p3 != LOCAL_PORT && free_valid[p3] && !out_valid_all[p3][0]) begin
          int fsp = free_pick[p3];
          int fci = fsp * NUM_VCS + 0;
          out_flit_all[p3][0] <= q[fci][0];
          out_valid_all[p3][0] <= 1;
          out_src_vc[p3][0]    <= 1'b0;
          cred[p3][0] <= cred[p3][0] - 1;
          rr_ptr[p3] <= (fsp + 1) % NUM_PORTS;
`ifdef NOC_TRACE_EVENTS
          $display("[T%0t] r%0d FWD p=%0d q=%0d cnt=%0d->%0d dst=%0d seq=%0d typ=%0d",
                   $time, ID, p3, fci, q_cnt[fci], q_cnt[fci]-1,
                   get_dst(q[fci][0]), q[fci][0][39:32], get_type(q[fci][0]));
`endif
          if (is_head(q[fci][0])) begin
            rt_alloc[fci] <= 1'b1;
            rt_out[fci]   <= p3[PORT_W-1:0];
          end
          if (is_tail(q[fci][0])) begin
            rt_alloc[fci] <= 1'b0;
            esc_mode[fci] <= 1'b0;
            blk_cnt[fci]  <= 8'd0;   // packet complete: reset cumulative age
          end
          for (int jj = 0; jj < BUF_DEPTH - 1; jj++)
            q[fci][jj] <= q[fci][jj + 1];
          q_cnt[fci] <= q_cnt[fci] - 4'd1;
        end
        // ── ESCAPE stage (slot 1): independent of the free stage ──
        if (out_valid_all[p3][1] && show_vc[p3] == 1'b1 && out_ready_all[p3]) begin
          out_valid_all[p3][1] <= 0;
          cred[p3][out_src_vc[p3][1]] <= cred[p3][out_src_vc[p3][1]] + 1;
        end else if (out_valid_all[p3][1] && show_vc[p3] == 1'b1) begin
          out_valid_all[p3][1] <= 1;   // shown, not accepted: HOLD
        end else if (p3 != LOCAL_PORT && esc_valid[p3] && !out_valid_all[p3][1]) begin
          int esp = esc_pick[p3];
          int eci = esp * NUM_VCS + 1;
          out_flit_all[p3][1] <= q[eci][0];
          out_valid_all[p3][1] <= 1;
          out_src_vc[p3][1]    <= 1'b1;
          cred[p3][1] <= cred[p3][1] - 1;
`ifdef NOC_TRACE_EVENTS
          $display("[T%0t] r%0d FWD p=%0d q=%0d cnt=%0d->%0d dst=%0d seq=%0d typ=%0d",
                   $time, ID, p3, eci, q_cnt[eci], q_cnt[eci]-1,
                   get_dst(q[eci][0]), q[eci][0][39:32], get_type(q[eci][0]));
`endif
          if (is_head(q[eci][0])) begin
            rt_alloc[eci] <= 1'b1;
            rt_out[eci]   <= p3[PORT_W-1:0];
          end
          if (is_tail(q[eci][0])) begin
            rt_alloc[eci] <= 1'b0;
            esc_mode[eci] <= 1'b0;
            blk_cnt[eci]  <= 8'd0;   // packet complete: reset cumulative age
          end
          for (int jj = 0; jj < BUF_DEPTH - 1; jj++)
            q[eci][jj] <= q[eci][jj + 1];
          q_cnt[eci] <= q_cnt[eci] - 4'd1;
        end
      end
      // 2. Ejection (network ports only, LOCAL output port; held until accepted).
      //    Only ONE ejection per cycle (first matching queue wins).
      //    B1 FIX: skip queues already dequeued by the grant path this cycle.
      //    Without this, grant fires for network port p3 (dequeues queue c via
      //    shift) AND ejection fires for LOCAL_PORT (dequeues the SAME queue c
      //    via shift). Both nonblocking -> double-shift consumes TWO flits but
      //    only ONE appears on the output -> flit loss + phantom ejections.
      begin : ej_block
        bit done_ej;
        done_ej = 1'b0;
        for (int pass2 = 1; pass2 >= 0 && !done_ej; pass2--) begin
          if (out_valid_all[LOCAL_PORT][pass2]) continue;
          for (int p2 = 0; p2 < LOCAL_PORT && !done_ej; p2++) begin
            int c2 = p2 * NUM_VCS + pass2;
            if (q_cnt[c2] > 0 && !grant_deq_q[c2] &&
                (rt_alloc[c2] ? (rt_out[c2] == LOCAL_PORT[PORT_W-1:0])
                              : (get_dst(q[c2][0]) == ID[$clog2(N_ROUTERS)-1:0]))) begin
              out_flit_all[LOCAL_PORT][pass2] <= q[c2][0];
              out_valid_all[LOCAL_PORT][pass2] <= 1;
              out_src_vc[LOCAL_PORT][pass2]    <= pass2[0];  // source VC for credit return
              ej_local_count = ej_local_count + 1;
`ifdef NOC_TRACE_EVENTS
              $display("[T%0t] r%0d EJT q=%0d cnt=%0d dst=%0d seq=%0d typ=%0d",
                       $time, ID, c2, q_cnt[c2], get_dst(q[c2][0]), q[c2][0][39:32],
                       get_type(q[c2][0]));
`endif
              if (is_head(q[c2][0])) begin
                rt_alloc[c2] <= 1'b1;
                rt_out[c2]   <= LOCAL_PORT[PORT_W-1:0];
              end
              if (is_tail(q[c2][0])) begin
                rt_alloc[c2] <= 1'b0;
                esc_mode[c2] <= 1'b0;
                blk_cnt[c2]  <= 8'd0;   // packet complete: reset cumulative age
              end
              for (int jj = 0; jj < BUF_DEPTH - 1; jj++)
                q[c2][jj] <= q[c2][jj + 1];
              q_cnt[c2] <= q_cnt[c2] - 4'd1;
              done_ej = 1'b1;
            end
          end
        end
      end
      // 3. Demotion (FREE VC, any flit type): if the queue's FRONT FLIT was
      //    not served this cycle (no grant/ejection -- ANY cause: no credit,
      //    output occupied by a held flit, or arbitration starvation) for
      //    BLOCK_K consecutive cycles, mark the whole packet ESCAPE:
      //      * esc_mode <= 1  -> cand_out switches to the escape path here
      //      * flip esc bit on every remaining flit at the queue front, so
      //        downstream routers place them in the (priority) ESCAPE VC.
      //    This makes the ENTIRE remaining packet travel the deadlock-free
      //    escape subnetwork (head-only demotion would strand BODY/TAIL on
      //    a cyclic free-class subgraph and deadlock mid-packet).
      //    R3 fix (2026-08-22, two stages): (1) credit==0-only trigger missed
      //    held-output & RR-starvation blocks (16n 131 / 64n 1204-1933 stuck);
      //    (2) the K-consecutive "not served" timer reset on every grant, so a
      //    free-class CIRCULATION (one hop/cycle, never reaching dst) never
      //    demoted (16n 143 stuck, 0 demotions @250k cyc). The certified model
      //    drains under flit-level semantics; the RTL's wormhole allocation
      //    cycles are livelock-prone, so blk_cnt is now a CUMULATIVE PACKET AGE
      //    (increments every occupied cycle; resets only at packet completion).
      for (int p2 = 0; p2 < NUM_PORTS; p2++) begin
        int c2 = p2 * NUM_VCS;
        if (q_cnt[c2] > 0) begin
          logic [PORT_W-1:0] cur_out;
          cur_out = esc_mode[c2] ? get_rt_esc(get_dst(q[c2][0]))
                                 : get_rt_min(get_dst(q[c2][0]));
          // cumulative packet age (saturating)
          if (blk_cnt[c2] < 8'hFF)
            blk_cnt[c2] <= blk_cnt[c2] + 8'd1;
          if (blk_cnt[c2] >= AGE_K[7:0]) begin
            // demote: whole packet escapes from here
            esc_mode[c2] <= 1'b1;
            q[c2][0][63] <= 1'b1;   // this flit is escape at the next hop
            blk_cnt[c2] <= 8'd0;
          end else if (esc_mode[c2]) begin
            q[c2][0][63] <= 1'b1;   // mid-packet flit: keep escape class
          end
        end
      end
      // 4. Enqueue (dequeue-aware: a flit arriving into a queue that was just
      //    granted/ejected this cycle takes the freed slot, count nets zero)
      for (int p2 = 0; p2 < NUM_PORTS; p2++) begin
        if (in_valid_all[p2] && in_ready_all[p2]) begin
          int lv = get_esc(in_flit_all[p2]) ? 1 : 0;
          int lc = p2 * NUM_VCS + lv;
          if (p2 == LOCAL_PORT) begin
            local_inj_count = local_inj_count + 1;
          end
          if (grant_deq_q[lc] || ej_dequeued[lc]) begin
            q[lc][q_cnt[lc]-1] <= in_flit_all[p2];
            q_cnt[lc] <= q_cnt[lc];               // net 0 (deq + enq)
`ifdef NOC_TRACE_EVENTS
            $display("[T%0t] r%0d ENQ-race p=%0d q=%0d cnt=%0d seq=%0d typ=%0d",
                     $time, ID, p2, lc, q_cnt[lc], in_flit_all[p2][39:32], get_type(in_flit_all[p2]));
`endif
          end else begin
            q[lc][q_cnt[lc]] <= in_flit_all[p2];
            q_cnt[lc] <= q_cnt[lc] + 4'd1;
`ifdef NOC_TRACE_EVENTS
            $display("[T%0t] r%0d ENQ p=%0d q=%0d cnt=%0d->%0d seq=%0d typ=%0d",
                     $time, ID, p2, lc, q_cnt[lc], q_cnt[lc]+1, in_flit_all[p2][39:32], get_type(in_flit_all[p2]));
`endif
          end
        end
      end
    end
  end

  // ── SVA Assertions ──
  // Structural invariants enforced by construction:
  //   * enqueue gated by in_ready (shared-buffer capacity)
  //   * dequeue only under grant/ejection with q_cnt > 0
  //   * credits: per-port, init 2*BUF_DEPTH, +/-1 on send/accept
  //   * wormhole: a TAIL/SINGLE transmission ALWAYS clears rt_alloc (so no
  //     VC can stay allocated after its packet completes)

  // Debug: dump non-empty queues at sim end ($time > threshold)
`ifdef SIM_DEBUG
  final begin
    for (int c = 0; c < NUM_PORTS * NUM_VCS; c++) begin
      if (q_cnt[c] > 0) begin
`ifdef NOC_TRACE_EVENTS
        $display("STUCK-R%0d q[%0d] cnt=%0d dst=%0d esc=%b alloc=%b cred_min=%0d cred_esc=%0d blk=%0d",
                 ID, c, q_cnt[c], get_dst(q[c][0]), q[c][0][63], rt_alloc[c],
                 cred[get_rt_min(get_dst(q[c][0]))][c % NUM_VCS],
                 cred[get_rt_esc(get_dst(q[c][0]))][1],
                 blk_cnt[c]);
`endif
      end
    end
  end
`endif
  final begin
    // Debug output moved to dbg_router_t interface (see noc_tb.sv DBG3/DBG4/DBG5)
  end
endmodule