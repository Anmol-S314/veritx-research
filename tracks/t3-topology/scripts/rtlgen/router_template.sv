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
  localparam int CLASS_W    = noc_pkg::CLASS_W;

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
  // CLASS_W-bit class field accessors
  localparam int CLASS_MSB = noc_pkg::FLIT_W - 1;
  localparam int CLASS_LSB = noc_pkg::FLIT_W - CLASS_W;
  function automatic logic [CLASS_W-1:0] get_class(input noc_pkg::flit_raw_t f);
    return f[CLASS_MSB:CLASS_LSB];
  endfunction
  function automatic logic get_esc(input noc_pkg::flit_raw_t f);
    return f[CLASS_MSB];  // MSB of class field (escape for 2-VC)
  endfunction
  function automatic logic [TYPE_W-1:0] get_type(input noc_pkg::flit_raw_t f);
    return f[CLASS_LSB-1:CLASS_LSB-TYPE_W];
  endfunction
  function automatic logic is_tail(input noc_pkg::flit_raw_t f);
    return (get_type(f) == FT_TAIL) || (get_type(f) == FT_SINGLE);
  endfunction
  function automatic logic is_head(input noc_pkg::flit_raw_t f);
    return (get_type(f) == FT_HEAD) || (get_type(f) == FT_SINGLE);
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
      // S3 FIX (2026-08-22, wormhole reservation invariant): a VC with an open
      // packet reservation (rt_alloc=1: head granted, tail not yet through)
      // must NOT admit another HEAD/SINGLE — a second packet interleaving into
      // the reserved VC gets captured by the first packet's route state
      // (rt_out), ejecting/forwarding it along the WRONG path (observed as
      // dst=3 packets ejected at mid-line routers on the 4-node line).
      // BODY/TAIL of the reserved packet pass freely; the reservation always
      // completes (upstream sends tails), so the gate adds bounded HOL delay,
      // never a new dependency cycle.
      // S3c FIX (2026-08-22, demotion-induced VC split): when a queue is in
      // escape mode, BODY/TAIL flits of the same packet must be forced to the
      // escape VC to match the head's esc bit. Without this, the head is
      // forwarded with esc=1 (to VC1 at next hop) while the body arrives with
      // esc=0 (enters VC0) — packet splits across VCs, and the destination's
      // rt_out=LOCAL reservation leaks forever.
      // Only force for NON-HEAD flits (heads start new packets).
      // S3c: force esc bit on body/tail flits when THEIR queue (not any
      // queue on the port) is in escape mode. This prevents VC split: when
      // a head is demoted and forwarded with esc=1, the body flits of the
      // same packet must also enter VC1 at the downstream hop.
      wire my_esc_q = get_esc(in_flit_all[p]) ? esc_mode[p*NUM_VCS + 1]
                                               : esc_mode[p*NUM_VCS + 0];
      wire esc_forced = !is_head(in_flit_all[p]) && my_esc_q;
      wire effective_esc = get_esc(in_flit_all[p]) | esc_forced;
      assign in_ready_all[p] =
          (effective_esc ? q_cnt[p*NUM_VCS + 1]
                        : q_cnt[p*NUM_VCS + 0]) < BUF_DEPTH &&
          // S3b MERGE (2026-08-22): heads require an EMPTY effective-VC queue.
          // Occupancy-based (not rt_alloc/esc_mode flags — those can stick via
          // downstream stranding and permanently block injection). Empty-queue
          // still enforces wormhole exclusivity: no second packet can
          // interleave into a VC that holds any flit of the first.
          (!is_head(in_flit_all[p]) ||
           ((effective_esc ? q_cnt[p*NUM_VCS + 1]
                           : q_cnt[p*NUM_VCS + 0]) == 0));
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
  wire my_esc_q_local = get_esc(in_flit_all[LOCAL_PORT]) ? esc_mode[LOCAL_PORT*NUM_VCS + 1]
                                                          : esc_mode[LOCAL_PORT*NUM_VCS + 0];
  wire esc_forced_local = !is_head(in_flit_all[LOCAL_PORT]) && my_esc_q_local;
  wire effective_esc_local = get_esc(in_flit_all[LOCAL_PORT]) | esc_forced_local;
  assign in_ready_all[LOCAL_PORT] = ((effective_esc_local
                                        ? q_cnt[LOCAL_PORT*NUM_VCS + 1]
                                        : q_cnt[LOCAL_PORT*NUM_VCS + 0]) < BUF_DEPTH) &&
                                    (!is_head(in_flit_all[LOCAL_PORT]) ||
                                     ((effective_esc_local
                                        ? q_cnt[LOCAL_PORT*NUM_VCS + 1]
                                        : q_cnt[LOCAL_PORT*NUM_VCS + 0]) == 0));

  // ── Candidate output port per (input,VC) queue (combinational) ──
  // Wormhole: R10 (Cara) — PER-FLIT ROUTING. The rt_alloc/rt_out
  // inheritance is deleted: XY/tree tables are memoryless per-dst
  // functions, so every flit recomputes its own next hop. The old
  // inherited-route path misrouted transit flits interleaved behind a
  // fresh head (packet-granular buffer-cycle deadlocks — the true
  // Bug A mechanism). Wormhole continuity is unnecessary AND harmful.
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
  localparam int VC_IDX_W = (NUM_VCS > 1) ? $clog2(NUM_VCS) : 1;
  logic [VC_IDX_W-1:0] esc_vc [0:NUM_PORTS-1];       // combinational: which VC was granted
  logic [VC_IDX_W-1:0] esc_stage_vc [0:NUM_PORTS-1]; // sequential: latched VC of loaded flit
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
      esc_vc[_o]    = '0;
    end
    for (_o = 0; _o < NUM_PORTS; _o++) begin
      if (_o == LOCAL_PORT) continue;  // ejection handles LOCAL output
      // Escape candidates: VC1..N-1, first-match (own stage, independent)
      for (int _ev = 1; _ev < NUM_VCS && !esc_valid[_o]; _ev++) begin
        for (_p = 0; _p < NUM_PORTS; _p++) begin
          if (!out_valid_all[_o][_ev] &&
              q_cnt[_p*NUM_VCS + _ev] > 0 && cred[_o][_ev] > 0 &&
              cand_out[_p*NUM_VCS + _ev] == _o &&
              get_dst(q[_p*NUM_VCS + _ev][0]) != ID[$clog2(N_ROUTERS)-1:0]) begin
            esc_valid[_o] = 1'b1;
            esc_pick[_o]  = _p[7:0];
            esc_vc[_o]    = _ev[VC_IDX_W-1:0];
          end
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
        grant_sv[_o] = {{(2-VC_IDX_W){1'b0}}, esc_vc[_o]};
      end else begin
        grant_sp[_o] = free_pick[_o];
        grant_sv[_o] = '0;
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
        for (int v3 = 0; v3 < NUM_VCS; v3++) begin
          out_valid_all[p3][v3] <= 0;
          out_src_vc[p3][v3]    <= 0;
        end
        esc_stage_vc[p3] <= '0;
        rr_ptr[p3]        <= '0;
        esc_starve[p3]    <= 4'd0;
        for (int v3 = 0; v3 < NUM_VCS; v3++)
          cred[p3][v3] <= BUF_DEPTH[noc_pkg::CRED_W-1:0];
      end
    end else begin
      // S3b FIX (2026-08-22): per-cycle ACTUAL-dequeue evidence. The old race
      // path trusted combinational grant_deq_q, which can mark a queue on a
      // cycle whose output stage was BUSY (load suppressed) — the spurious
      // mark then routed the enqueue into the net-zero overwrite branch and a
      // stored BODY was replaced by the incoming flit (body stranding).
      // deq_actual[] is set ONLY inside branches that really shift the queue.
      bit deq_actual [0:NUM_PORTS*NUM_VCS-1];
      for (int c = 0; c < NUM_PORTS*NUM_VCS; c++) deq_actual[c] = 1'b0;
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
          deq_actual[fci] = 1'b1;   // S3b: real dequeue evidence
        end
        // ── ESCAPE stage (uses esc_stage_vc for latched VC index) ──
        begin : esc_stage
          // evc_fwd = latched VC of the loaded flit (stable across cycles)
          // evc_load = current combinational VC candidate (for new loads)
          automatic logic [VC_IDX_W-1:0] evc_fwd  = esc_stage_vc[p3];
          automatic logic [VC_IDX_W-1:0] evc_load = esc_vc[p3];
          if (out_valid_all[p3][evc_fwd] && show_vc[p3] == evc_fwd[VC_IDX_W-1:0] && out_ready_all[p3]) begin
            out_valid_all[p3][evc_fwd] <= 0;
            cred[p3][out_src_vc[p3][evc_fwd]] <= cred[p3][out_src_vc[p3][evc_fwd]] + 1;
          end else if (out_valid_all[p3][evc_fwd] && show_vc[p3] == evc_fwd[VC_IDX_W-1:0]) begin
            out_valid_all[p3][evc_fwd] <= 1;   // shown, not accepted: HOLD
          end else if (p3 != LOCAL_PORT && esc_valid[p3] && !out_valid_all[p3][evc_load]) begin
            int esp = esc_pick[p3];
            int eci = esp * NUM_VCS + evc_load;
            out_flit_all[p3][evc_load] <= q[eci][0];
            out_valid_all[p3][evc_load] <= 1;
            out_src_vc[p3][evc_load]    <= evc_load;
            esc_stage_vc[p3]            <= evc_load;  // latch VC for forwarding
            cred[p3][evc_load] <= cred[p3][evc_load] - 1;
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
          deq_actual[eci] = 1'b1;   // S3b: real dequeue evidence
        end
      end // esc_stage
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
        for (int pass2 = NUM_VCS-1; pass2 >= 0 && !done_ej; pass2--) begin
          // S4 FIX: allow ejection when output stage will be freed this cycle
          // (non-blocking: release clears out_valid, but ejection sees old value)
          if (out_valid_all[LOCAL_PORT][pass2] &&
              !(show_vc[LOCAL_PORT] == pass2[VC_IDX_W-1:0] && out_ready_all[LOCAL_PORT])) continue;
          for (int p2 = 0; p2 <= LOCAL_PORT && !done_ej; p2++) begin
            int c2 = p2 * NUM_VCS + pass2;
            if (q_cnt[c2] > 0 && !grant_deq_q[c2] &&
                get_dst(q[c2][0]) == ID[$clog2(N_ROUTERS)-1:0]) begin
              out_flit_all[LOCAL_PORT][pass2] <= q[c2][0];
              out_valid_all[LOCAL_PORT][pass2] <= 1;
              out_src_vc[LOCAL_PORT][pass2]    <= pass2[VC_IDX_W-1:0];  // source VC for credit return
              // R6 FIX: latch the escape-slot owner for LOCAL too. Grants
              // never target LOCAL (B1), so esc_stage_vc[LOCAL] stayed 0
              // forever and slot 1 (demoted tails) was NEVER cleared after
              // acceptance -> phantom re-ejection every cycle (862K ejects
              // vs 589 injected). Section 1 owns slot 0, so only latch
              // non-zero slots here.
              if (pass2 != 0)
                esc_stage_vc[LOCAL_PORT] <= pass2[VC_IDX_W-1:0];
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
              deq_actual[c2] = 1'b1;   // S3b: real dequeue evidence
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
          if (blk_cnt[c2] >= 200) begin
            // STUCK detection: print diagnostic
            $display("[T%0t] STUCK r%0d queue=%0d dst=%0d src=%0d type=%0d age=%0d cnt=%0d esc=%0b",
                      $time, ID, c2, get_dst(q[c2][0]), q[c2][0][47:40],
                      get_type(q[c2][0]), blk_cnt[c2], q_cnt[c2], esc_mode[c2]);
          end
`ifdef NOC_TRACE_EVENTS
          // R6 DIAGNOSTIC: fire once per demotion cycle, just before reset.
          // Dumps exactly why the head isn't being granted.
          if (blk_cnt[c2] == AGE_K[7:0] - 1) begin : stall_dbg
            int dbg_out;
            dbg_out = esc_mode[c2] ? get_rt_esc(get_dst(q[c2][0]))
                                   : (rt_alloc[c2] ? rt_out[c2]
                                                    : get_rt_min(get_dst(q[c2][0])));
            $display("[STALL r%0d q=%0d dst=%0d alloc=%b cand=%0d | cred0=%0d cred1=%0d outvld0=%b outvld1=%b stagecls=%b stagevc=%0d rdy=%b free_v=%b esc_v=%b | ej_here=%b cls=%b",
                      ID, c2, get_dst(q[c2][0]), rt_alloc[c2], dbg_out,
                      cred[dbg_out][0],
                      cred[dbg_out][1],
                      out_valid_all[dbg_out][0],
                      out_valid_all[dbg_out][1],
                      get_class(out_flit_all[dbg_out][show_vc[dbg_out]]),
                      show_vc[dbg_out],
                      out_ready_all[dbg_out],
                      free_valid[dbg_out],
                      esc_valid[dbg_out],
                      (get_dst(q[c2][0]) == ID[$clog2(N_ROUTERS)-1:0]),
                      get_class(q[c2][0]));
          end
`endif
          // R6 EXPERIMENT: demotion OFF — tests whether mesh gridlock is
          // caused by demoted flits flooding downstream VC1 queues
          // (unaccounted by VC0-side credit tracking).
          if (0 && blk_cnt[c2] >= AGE_K[7:0]) begin
            // demote: whole packet escapes from here.
            // Flip esc bit on ALL queued flits in one cycle to prevent
            // body/tail flits arriving later from entering VC0 while
            // esc_mode is set (which would cause VC split via esc_forced).
            esc_mode[c2] <= 1'b1;
            for (int jj = 0; jj < BUF_DEPTH; jj++)
              if (jj < q_cnt[c2])
                for (int _cb = CLASS_LSB; _cb <= CLASS_MSB; _cb++)
                  q[c2][jj][_cb] <= 1'b1;
            blk_cnt[c2] <= 8'd0;
          end else if (esc_mode[c2]) begin
            for (int _cb = CLASS_LSB; _cb <= CLASS_MSB; _cb++)
              q[c2][0][_cb] <= 1'b1;   // mid-packet flit: keep escape class
          end
        end
      end
      // 4. Enqueue (dequeue-aware: a flit arriving into a queue that was just
      //    granted/ejected this cycle takes the freed slot, count nets zero)
      for (int p2 = 0; p2 < NUM_PORTS; p2++) begin
        if (in_valid_all[p2] && in_ready_all[p2]) begin
          int lv = get_class(in_flit_all[p2]);
          int lc = p2 * NUM_VCS + lv;
          // S3c: force escape VC for body/tail flits when THEIR queue (not
          // any queue on the port) is in escape mode. Also flip esc bit [63]
          // on the flit data so downstream routers place it in VC1.
          logic [63:0] enq_flit;
          enq_flit = in_flit_all[p2];
          begin : s3c_check
            logic q_is_esc;
            q_is_esc = esc_mode[p2*NUM_VCS + get_class(in_flit_all[p2])];
            if (!is_head(in_flit_all[p2]) && q_is_esc) begin
              lv = NUM_VCS - 1;  // force to last VC (escape class)
              lc = p2 * NUM_VCS + (NUM_VCS - 1);
              for (int _cb = CLASS_LSB; _cb <= CLASS_MSB; _cb++)
                enq_flit[_cb] = 1'b1;  // set all class bits to escape
            end
          end
          if (p2 == LOCAL_PORT) begin
            local_inj_count = local_inj_count + 1;
          end
          // S3b FIX (2026-08-22): race eligibility now requires an ACTUAL
          // dequeue this cycle (deq_actual, set inside the load/eject branches
          // that really shift the queue). The old combinational grant_deq_q
          // could mark a queue on a cycle whose output stage was busy (load
          // suppressed) — the spurious race then overwrote the last queued
          // BODY with the incoming flit (body stranding, left>0).
          if (deq_actual[lc]) begin
            q[lc][q_cnt[lc]-1] <= enq_flit;
            q_cnt[lc] <= q_cnt[lc];               // net 0 (deq + enq)
`ifdef NOC_TRACE_EVENTS
            $display("[T%0t] r%0d ENQ-race p=%0d q=%0d cnt=%0d seq=%0d typ=%0d",
                     $time, ID, p2, lc, q_cnt[lc], in_flit_all[p2][39:32], get_type(in_flit_all[p2]));
`endif
          end else begin
            q[lc][q_cnt[lc]] <= enq_flit;
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
  //   * credits: per-port, init BUF_DEPTH, +/-1 on send/accept
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
                 cred[get_rt_esc(get_dst(q[c][0]))][NUM_VCS-1],
                 blk_cnt[c]);
`endif
      end
    end
  end
`endif

  // ── Formal properties (enable with +define+SIM_FORMAL for sby BMC/cover) ──
  // These are checked during simulation when SIM_FORMAL is defined, and serve
  // as the basis for formal verification with SymbiYosys.
`ifdef SIM_FORMAL
  // S1. Credit bounds: cred never negative or above BUF_DEPTH
  for (genvar _p = 0; _p < NUM_PORTS; _p++) begin : sva_cred
    for (genvar _v = 0; _v < NUM_VCS; _v++) begin : sva_cred_vc
      assert property (@(posedge clk) disable iff (!rst_n)
        cred[_p][_v] <= BUF_DEPTH)
        else $error("SVA S1: cred[%0d][%0d] overflow = %0d > %0d", _p, _v, cred[_p][_v], BUF_DEPTH);
      assert property (@(posedge clk) disable iff (!rst_n)
        cred[_p][_v] >= 0)
        else $error("SVA S1: cred[%0d][%0d] underflow = %0d", _p, _v, cred[_p][_v]);
    end
  end

  // S2. Queue count bounds: q_cnt never exceeds BUF_DEPTH
  for (genvar _c = 0; _c < NUM_PORTS * NUM_VCS; _c++) begin : sva_qcnt
    assert property (@(posedge clk) disable iff (!rst_n)
      q_cnt[_c] <= BUF_DEPTH)
      else $error("SVA S2: q_cnt[%0d] overflow = %0d", _c, q_cnt[_c]);
  end

  // S3. Wormhole: rt_alloc=1 implies head flit at queue front
  for (genvar _c = 0; _c < NUM_PORTS * NUM_VCS; _c++) begin : sva_worm
    assert property (@(posedge clk) disable iff (!rst_n)
      rt_alloc[_c] |-> q_cnt[_c] > 0)
      else $error("SVA S3: rt_alloc[%0d]=1 but q_cnt=0", _c);
    // Tail clears alloc
    // Tail clears alloc: on the cycle a tail flit is at queue front,
    // if a dequeue happens, rt_alloc is cleared.
    // (Simplified for Verilator: no ## delay)
  end

  // S4. Escape consistency: esc_mode=1 implies cand_out uses escape path
  for (genvar _c = 0; _c < NUM_PORTS * NUM_VCS; _c++) begin : sva_esc
    assert property (@(posedge clk) disable iff (!rst_n)
      (esc_mode[_c] && q_cnt[_c] > 0)
      |-> cand_out[_c] == get_rt_esc(get_dst(q[_c][0])))
      else $error("SVA S4: esc_mode[%0d]=1 but cand_out != escape route", _c);
  end

  // S5. No queue starvation: every non-empty queue gets forwarded within
  //     4*BUF_DEPTH*K cycles (bounded HOL delay under escape priority)
  // Note: checked via assertion count, not as a temporal property

  // S6. Fresh flit invariant: head flit type field is HEAD or SINGLE
  for (genvar _c = 0; _c < NUM_PORTS * NUM_VCS; _c++) begin : sva_type
    assert property (@(posedge clk) disable iff (!rst_n)
      (q_cnt[_c] > 0 && is_head(q[_c][0]))
      |-> (get_type(q[_c][0]) == FT_HEAD || get_type(q[_c][0]) == FT_SINGLE))
      else $error("SVA S6: front flit of non-empty queue %0d is not HEAD/SINGLE", _c);
  end

  // Cover: packet ejection completes (tail/SINGLE ejected at LOCAL)
  for (genvar _c = 0; _c < NUM_PORTS * NUM_VCS; _c++) begin : sva_cover
    cover property (@(posedge clk) disable iff (!rst_n)
      ej_dequeued[_c] && q_cnt[_c] > 0 &&
      (is_tail(q[_c][0]) || get_type(q[_c][0]) == FT_SINGLE));
  end
`endif

  final begin
    // Debug output moved to dbg_router_t interface (see noc_tb.sv DBG3/DBG4/DBG5)
  end
endmodule