`ifndef NOC_NIC_SV
`define NOC_NIC_SV

// NIC: injector + ejector + generators + latency measurement.
// Contract: RTL-ARC.md §5 (stimulus) + §6 (instrumentation) + the TM
// injection rules pinned 2026-08-08:
//   - at most ONE flit injected per node per cycle;
//   - class served = first in rotation from last_class with a pending packet
//     (equal prios => strict rotation);
//   - head: VC selected rotating from per-class last_vc, requires local-VC
//     not-in-use AND free > 0; bodies: free > 0 only; tail frees the VC at
//     injection (wait_for_tail_credit = 0);
//   - a packet generated at cycle T injects its first flit at T+1
//     (matches BookSim enqueue@T -> first flit out@T+1);
//   - flits inject 1/cycle while the packet is pending (credit-gated).
//
// Generators (mode):
//   0 = idle, 1 = LFSR burst (class 0: Bernoulli(rate0) bursts of burst_len
//       flits to a diagonal NIC; class 1: Bernoulli(rate1) 1-flit control to
//       uniform dest), 2 = trace replay from an in-NIC BRAM
//       (class-0 entries {cycle[31:0], dst, size}: head injects when
//       tick >= entry.cycle; dump = BookSim enqueue cycle).
// Eject: flit read at cycle T, eject credit sent the same cycle (2-stage
// link back to the router). Tail: latency = tick - itime recorded per class.

import noc_pkg::*;

module noc_nic #(
  parameter int VCS     = 4,
  parameter int X       = 0,
  parameter int Y       = 0,
  parameter int X_DIM   = 4,
  parameter int Y_DIM   = 4,
  parameter int DIE_BASE = 0,  // 0 = die A, N = die B (2-die bridge mode)
  parameter int T_DEPTH = 2048,
  parameter int T_W     = 11
)(
  input  logic clk,
  input  logic rst_n,
  output link_f_t inject,
  input  link_c_t inject_credit,
  input  link_c_t inject_credit_early,   // 1-cycle-early (injc_st1) credit view
  input  link_f_t eject,
  output link_c_t eject_credit,
  // generator control
  input  logic [1:0]   gen_mode,      // 0 idle, 1 lfsr, 2 trace
  input  logic [31:0]  burst_len,     // LFSR: class-0 burst length B (flits)
  input  logic [31:0]  rate0,         // LFSR: class-0 packet rate (Q24)
  input  logic [31:0]  rate1,         // LFSR: class-1 packet rate (Q24)
  input  logic [31:0]  seed,
  // trace memory write port (BRAM init in TB)
  input  logic         trace_we,
  input  logic [T_W-1:0] trace_addr,
  input  logic [63:0]  trace_data,
  // instrumentation
  output logic [31:0] tick,
  output logic [31:0] injected_cnt,     // flits injected
  output logic [31:0] ejected_cnt,      // flits ejected
  output logic [31:0] lat_sum [4],      // per-class latency sums
  output logic [31:0] lat_cnt [4],      // per-class completed packets
  output logic [63:0] dbg_trace0,       // debug: trace_mem[0]
  output logic [31:0] dbg_tptr,         // debug: replay pointer
  output logic        dbg_pending       // debug: pkt[0].pending
);

  localparam int VC_W = $clog2(VCS);
  localparam int CLS  = 2;

  // ===================================================================
  // PART 1: SYNTHESIZABLE SILICON CORE DATA STRUCTURES & ARBITRATION
  // (Credit tracking, VC allocation, flit framing, class round-robin)
  // ===================================================================
  logic [31:0] lfsr;

  function automatic logic bernoulli(input logic [31:0] rate_q24);
    return lfsr[23:0] < rate_q24[23:0];      // uniform u in [0,1) Q24
  endfunction

  function automatic logic [7:0] uniform_node();
    return lfsr[7:0] % (X_DIM * Y_DIM);      // unbiased: 256 % N == 0
  endfunction

  function automatic logic [7:0] diagonal_dest();
    return (lfsr[7:0] % X_DIM) * (X_DIM + 1); // node d*(X_DIM+1) = (d,d)
  endfunction

  // ------------------------------------------------------------------
  // trace memory (reset to all-1s = empty)
  // ------------------------------------------------------------------
  logic [63:0] trace_mem [T_DEPTH];
  logic [T_W-1:0] tptr;

  always_ff @(posedge clk or negedge rst_n) begin
    if (!rst_n) begin
      for (int i = 0; i < T_DEPTH; i++) trace_mem[i] <= '1;
    end else if (trace_we) begin
      trace_mem[trace_addr] <= trace_data;
    end
  end

  // ------------------------------------------------------------------
  // per-class pending packets
  // ------------------------------------------------------------------
  typedef struct packed {
    logic        pending;
    logic [2:0]  vc;
    logic [7:0]  dst;
    logic [15:0] pid;
    logic [31:0] remaining;   // flits left to inject
    logic [31:0] size;        // original packet size (head detection)
    logic        mcast;       // VeritX fork stream: inject with copy range
    logic [7:0]  fork_lo;     // copies eject at nodes in [fork_lo, fork_hi]
    logic [7:0]  fork_hi;
  } pkt_t;

  pkt_t pkt [CLS];
  logic [VC_W-1:0] last_vc [CLS];
  logic [1:0] last_class;
  // trace-replay: the entry at tptr+1 was already fired (consumed) while
  // the tptr entry defers -- see the reordered-pair consumption below
  logic consumed1;

  // local-VC mirror (the router's local input buffer, TM-side view)
  logic [3:0] free [VCS];     // init VC_BUF_DEF
  logic       in_use[VCS];

  // ------------------------------------------------------------------
  // serve: class that injects this cycle (strict rotation, equal prios)
  // ------------------------------------------------------------------
  logic [1:0] serve;

  function automatic logic pkt_ready(input logic [1:0] c);
    // same-cycle credit visibility: a credit landing this cycle frees a slot
    // immediately (BookSim processes credits in-cycle at ReadCredit; the
    // free[] mirror only updates at the next posedge).
    return pkt[c].pending &&
           (free[pkt[c].vc] > 0 ||
            (inject_credit.valid && (inject_credit.vc == pkt[c].vc)));
  endfunction

  always_comb begin
    serve = 2'b00;
    for (int i = 0; i < CLS; i++) begin
      int c = (last_class + 1 + i) % CLS;
      if (pkt_ready(c)) begin
        serve = c[1:0];
        break;
      end
    end
  end

  // ------------------------------------------------------------------
  // injection
  // ------------------------------------------------------------------
  logic inject_valid;
  flit_t inject_flit;
  logic [VC_W-1:0] inject_vc;

  always_comb begin
    inject_valid = pkt_ready(serve);
    inject_flit  = '0;
    inject_vc    = pkt[serve].vc;
    if (inject_valid) begin
      inject_flit.head  = (pkt[serve].remaining == pkt[serve].size);
      inject_flit.tail  = (pkt[serve].remaining == 1);
      inject_flit.vc    = pkt[serve].vc;
      inject_flit.cl    = serve;
      inject_flit.src   = DIE_BASE + Y * X_DIM + X;
      inject_flit.dst   = pkt[serve].dst;
      inject_flit.pid   = pkt[serve].pid;
      inject_flit.mcast    = pkt[serve].mcast;
      inject_flit.copy_lo  = pkt[serve].fork_lo;
      inject_flit.copy_hi  = pkt[serve].fork_hi;
      // BookSim: f->itime = _time, per flit, at the inject wire cycle
      inject_flit.itime = tick_r;
`ifdef R1_MODE
      if (inject_flit.head)
        $display("VC n%0d pid=%0d vc=%0d tick=%0d", Y * X_DIM + X,
                 pkt[serve].pid, pkt[serve].vc, tick_r);
`endif
    end
  end

  assign inject.valid = inject_valid;
  assign inject.flit  = inject_flit;

  // eject credit: same cycle the flit is read
  assign eject_credit.valid = eject.valid;
  assign eject_credit.vc    = eject.flit.vc;

  logic [31:0] tick_r, inj_cnt, ejc_cnt;
  logic [31:0] lsum [CLS];
  logic [31:0] lcnt [CLS];

  // VC selection for a fresh packet: first free VC rotating from last_vc.
  // Returns VCS as the "no VC available this cycle" sentinel -- the caller
  // must NOT fire the packet then (BookSim: a VC holds one packet at a
  // time; starting a new packet in an in_use VC would interleave two
  // packets in one VC and corrupt the router's per-VC state machine).
  // freeing = VC freed this cycle by a tail inject (its in_use clears at
  // this posedge and its free is decremented, so it is pickable with the
  // post-tail free count -- BookSim wait_for_tail_credit=0 semantics).
  //
  // A pending multi-flit packet owns its VC from the cycle it FIRED until
  // its tail injects -- one inject edge longer than the in_use mirror
  // reflects (the mirror sets on the head's inject edge; a packet that
  // fired last cycle injects its head THIS cycle). A fire deferred to this
  // cycle by its own class's pending packet would otherwise read the stale
  // mirror, grab the same VC, and interleave its head into the pending
  // packet's stream (PITFALL-21 family: the same-cycle claimed exclusion
  // below cannot see a fire from a previous cycle). The freeing VC (a tail
  // injecting this very cycle) stays exempt: wait_for_tail_credit=0
  // releases it at this edge.
  function automatic logic vc_owned(input int v);
    for (int cc = 0; cc < CLS; cc++)
      if (pkt[cc].pending && (pkt[cc].size > 1) && (pkt[cc].vc == v))
        return 1'b1;
    return 1'b0;
  endfunction

  // The freeing exemption below may only release the freeing VC with
  // respect to the freeing packet itself (pkt[serve], whose tail is on the
  // wire this cycle): any OTHER pending multi-flit packet still owns it.
  // Two packets can share one VC only as the corruption this guard exists
  // to prevent -- the R3,2 INTLV at t=69620 was exactly this: pid43 took
  // vc0 via v==freeing while pid42 (pending, size 10) owned it, and its
  // h1t1 landed mid-stream, one cycle before pid42's tail (PITFALLS 23).
  // NB: owner_cl is serve BY CONSTRUCTION -- injection is strictly one
  // flit per cycle from serve, so the tail on the wire this cycle always
  // belongs to pkt[serve]. If injection ever becomes multi-class per
  // cycle, the owner must be derived from the tail's actual class, not
  // passed as serve.
  function automatic logic vc_owned_other(input int v, input int owner_cl);
    for (int cc = 0; cc < CLS; cc++)
      if ((cc != owner_cl) && pkt[cc].pending && (pkt[cc].size > 1) &&
          (pkt[cc].vc == v))
        return 1'b1;
    return 1'b0;
  endfunction

  function automatic logic [VC_W:0] pick_vc(input int c, input int freeing,
                                            input int exclude = -1);
    for (int i = 0; i < VCS; i++) begin
      int v = (last_vc[c] + i) % VCS;
`ifdef R1_MODE
      if ((freeing >= 0) && (v == freeing) && in_use[v])
        $display("EXEMPT n%0d cl=%0d vc=%0d free=%0d", Y * X_DIM + X, c, v, free[v]);
`endif
      // A multi-flit head injecting this same cycle occupies its VC from
      // this edge -- the in_use mirror only updates at this edge, so the
      // mirror alone would let a same-cycle fire grab the same VC and
      // interleave two packets (a 1-flit h1t1 inject is exempt: it is the
      // freeing tail, so the VC is released this cycle).
      // A credit in the channel (injc_st1) lands at the NIC next cycle and
      // BookSim processes a read credit the cycle it reads it, so a packet
      // whose buffer is exactly full may start one cycle early. The freeing
      // VC (tail injecting this cycle) is pickable with one slot of
      // headroom or a credit in flight (the head injects next cycle, after
      // the tail's decrement and the credit's landing).
      if (((!in_use[v]) || (v == freeing)) &&
          ((free[v] > (v == freeing ? 1 : 0)) ||
           (inject_credit_early.valid && (inject_credit_early.vc == v))) &&
          !(inject_valid && inject_flit.head && !inject_flit.tail &&
            (inject_vc == v)) &&
          ((v == freeing) ? !vc_owned_other(v, serve) : !vc_owned(v)) &&
          (v != exclude))
        return v;
    end
    return VCS;
  endfunction

  always_ff @(posedge clk or negedge rst_n) begin
    if (!rst_n) begin
      tick_r <= '0;
      inj_cnt <= '0; ejc_cnt <= '0;
      tptr <= '0;
      consumed1 <= 1'b0;
      last_class <= '0;
      lfsr <= seed;
      for (int c = 0; c < CLS; c++) begin
        pkt[c].pending <= 1'b0;
        last_vc[c] <= '0;
        lsum[c] <= '0; lcnt[c] <= '0;
      end
      for (int v = 0; v < VCS; v++) begin
        free[v] <= VC_BUF_DEF[3:0];
        in_use[v] <= 1'b0;
      end
    end else begin
      tick_r <= tick_r + 1;
      lfsr <= lfsr_next(lfsr);

      // credits from the router (local pop at T-2) and the inject decrement
      // are applied as a single net per VC: a same-cycle inject+credit
      // collision must not drop the +1 (two nonblocking writes to the same
      // variable would let the last one win and ratchet the free count down),
      // and the count saturates at [0, VC_BUF_DEF] per RTL-ARC.md (the
      // BookSim BufferState invariant: 0 <= credit <= buffer_depth)
      for (int v = 0; v < VCS; v++) begin
        int delta = ((inject_credit.valid && (inject_credit.vc == v)) ? 1 : 0)
                  - ((inject_valid && (inject_vc == v)) ? 1 : 0);
        if ((int'(free[v]) + delta) < 0)
          free[v] <= '0;
        else if ((int'(free[v]) + delta) > int'(VC_BUF_DEF))
          free[v] <= VC_BUF_DEF[3:0];
        else
          free[v] <= free[v] + delta;
      end
      // ejection
      if (eject.valid) begin
        ejc_cnt <= ejc_cnt + 1;
        if (eject.flit.tail) begin
          lsum[eject.flit.cl] <= lsum[eject.flit.cl] + (tick_r - eject.flit.itime);
          lcnt[eject.flit.cl] <= lcnt[eject.flit.cl] + 1;
        end
      end

      // injection
      if (inject_valid) begin
        inj_cnt <= inj_cnt + 1;
        if (inject_flit.head) begin
          in_use[inject_vc] <= 1'b1;
          last_vc[serve] <= (inject_vc + 1) % VCS;
        end
        if (inject_flit.tail) in_use[inject_vc] <= 1'b0;
        last_class <= serve;
        if (inject_flit.tail) begin
          pkt[serve].pending <= 1'b0;
        end else begin
          pkt[serve].remaining <= pkt[serve].remaining - 1;
        end
      end

      // ===============================================================
      // PART 2: GENERATORS & GATE R1 CO-SIMULATION SHIM
      //   gen_mode == 2'd0: Idle
      //   gen_mode == 2'd1: LFSR Burst Generator (Synthesizable PRBS)
      //   gen_mode == 2'd2: Gate R1 Trace-Replay Driver (Co-Sim Shim)
      // ===============================================================
      if (gen_mode == 2'd1) begin
        int claimed = -1;
        if (!pkt[0].pending && bernoulli(rate0)) begin
          logic [VC_W:0] pv0 = pick_vc(0, -1, claimed);
          if (pv0 < VCS) begin
            pkt[0].pending   <= 1'b1;
            pkt[0].dst       <= diagonal_dest();
            pkt[0].pid       <= lfsr[31:16];
            pkt[0].remaining <= burst_len;
            pkt[0].size      <= burst_len;
            pkt[0].vc        <= pv0;
            // same-cycle class-1 fire must not share this VC (its head
            // injects next cycle, before the in_use mirror updates)
            if (burst_len > 1) claimed = int'(pv0);
          end
        end
        if (!pkt[1].pending && bernoulli(rate1)) begin
          logic [VC_W:0] pv1 = pick_vc(1, -1, claimed);
          if (pv1 < VCS) begin
            pkt[1].pending   <= 1'b1;
            pkt[1].dst       <= uniform_node();
            pkt[1].pid       <= lfsr[15:0];
            pkt[1].remaining <= 32'd1;
            pkt[1].size      <= 32'd1;
            pkt[1].vc        <= pv1;
          end
        end
      end else if (gen_mode == 2'd2) begin
        // class comes from the trace entry; fire when the tick that will
        // be visible on the inject wire reaches the entry's cycle. A
        // back-to-back packet may fire the same cycle its class's tail
        // injects (the TM's per-class flit queue empties that cycle).
        // Two same-cycle entries fire together, ordered by the class
        // round-robin (last_class+1 first): BookSim serves one flit per
        // node-cycle with the classes in rotation, so a 1-flit control
        // queued at the same cycle as a burst takes the slot ahead of the
        // burst's first flit.
        int ord[2] = '{0, 1};
        int freeing = (inject_valid && inject_flit.tail) ? int'(inject_vc) : -1;
        // VC claimed by a multi-flit head fired EARLIER in this same cycle.
        // Its head injects NEXT cycle, so the in_use mirror (updated at the
        // inject edge) is still stale here -- without this exclusion a
        // same-cycle double-fire (two trace entries, same cycle field) can
        // pick the same VC and interleave a second head into a pending
        // packet's stream, which deadlocks the router's per-VC state machine
        // (the interleaved head parks in VA_REQ: the output VC it needs is
        // self-held by the first packet, whose tail is stuck behind it).
        int claimed = -1;
        bit f0, f1;                    // fired: entry at tptr, entry at tptr+1
        bit fired_c[CLS];              // per-edge: class already fired this edge
        // Per-edge reset: block-scoped vars are STATIC in SV (Verilator
        // retains them across edges), so without this a stale f0=1 from an
        // earlier edge advances tptr every cycle without a fire -- skipping
        // entries whose cycle has not arrived yet, then walking through the
        // '1 padding to wrap the pointer and re-fire trace_mem[0] (the
        // OOB read at tptr=1023+idx=1024, PITFALLS 24).
        f0 = 1'b0; f1 = 1'b0;
        for (int cc = 0; cc < CLS; cc++) fired_c[cc] = 1'b0;
        // Structural OOB guard (PITFALLS 24): tptr must stay strictly inside
        // the BRAM or the tptr+1 reorder read aliases trace_mem[0] via the
        // 10-bit wrap. The stale-f0 walk proved the pointer CAN reach the
        // padding; the guard makes the invariant structural, not incidental
        // (fires require non-'1 entries, but a defensive check is cheaper
        // than a second wrap).
        if (!consumed1 && (tptr < (T_DEPTH - 1)) &&
            (trace_mem[tptr + 1] != '1) &&
            // Rotation collision (BookSim "time >= qtime" test at the
            // current tick, applied to both entries): the TM serves one
            // flit/node-cycle in rotation from last_class+1, so at the
            // first tick where BOTH packets are due, the rotation-next
            // class wins the slot and the other defers one cycle -- the
            // trace's generation order must be reversed. Scope is the
            // HEAD edge only: both classes must be pending-free (a
            // mid-flight packet pins its class; without this guard the
            // swap re-fires every edge of a burst and embeds the control
            // flit inside it). "Due at this tick" is the exact boundary:
            // a future tptr+1 entry (NIC-17: cl1 due 1256 vs burst due
            // 1255) must NOT reorder (its qtime hasn't passed; the burst's
            // in_use then releases it at tail+1, generation order), while
            // a credit-held tptr entry (src 58: burst due 3442 held to
            // 3444 by the previous burst's in_use, cl1 due 3444) releases
            // onto the same edge as the cl1, where the rotation serves the
            // cl1 first. A pick-failed (W-chain backlog) tptr entry needs
            // no swap at all: idx=1 fires through f0=0 that edge.
            //
            // F15 fix (2026-08-14): reorder ONLY when the tptr entry's
            // class is ALREADY pending (deferred-unblock, bounded). The
            // pre-F2 behavior. The F2-era anticipatory swap (both classes
            // pending-free, both due this tick) created a VC lockout on
            // burst cells: it fires tptr+1 (multi-flit, claims the VC),
            // then tptr's pick is excluded from that VC and — at VCS=1
            // per class — tptr has NO other VC, so it defers forever via
            // consumed1 (pend=1, tptr parked, corpus stalls: b5_vc1
            // 2327 injected / 346 ejected). The tptr-pending gate makes
            // the swap free (tptr can't fire this edge anyway) and
            // bounded (the deferred entry unblocks when its VC frees).
            pkt[trace_mem[tptr][31:24]].pending &&
            (trace_mem[tptr + 1] != '1) &&
            (trace_mem[tptr + 1][63:32] != '0) &&
            (trace_mem[tptr + 1][31:24] < CLS) &&
            !pkt[trace_mem[tptr + 1][31:24]].pending &&
            (tick_r >= trace_mem[tptr][63:32]) &&
            (tick_r >= trace_mem[tptr + 1][63:32]) &&
            (trace_mem[tptr][31:24] != trace_mem[tptr + 1][31:24]) &&
            (((inject_valid ? int'(serve) : int'(last_class)) + 1) % CLS ==
             trace_mem[tptr + 1][31:24])) begin
          ord = '{1, 0};
        end
        for (int i = 0; i < 2; i++) begin
          int idx = ord[i];
          int c;
          logic [VC_W:0] pv;
          if (consumed1 && (idx == 1)) continue;   // consumed on an earlier edge
          if ((tptr + idx) >= T_DEPTH) continue;   // structural OOB guard (PITFALLS 24)
          c = trace_mem[tptr + idx][31:24];
          pv = pick_vc(c, freeing, claimed);
          // Entries fire in strict order. ord={0,1} (generation order): the
          // tptr+1 entry only fires once the tptr entry has (cycles are
          // non-decreasing, so a lone tptr+1 fire is impossible without
          // the tptr-lost + re-fire corruption of PITFALLS 24). Reordered
          // {1,0}: the first-served tptr+1 entry fires first, and the tptr
          // entry only once it has (its pick is VC-blocked by the claimed
          // exclusion, so it retries next edge).
          //
          // ONE FIRE PER CLASS PER EDGE (PITFALLS 25): the NIC holds a
          // single pkt[c] struct per class, so two same-class fires in one
          // edge would have their NBAs collide and the second (tptr+1)
          // silently clobber the first -- the first packet never injects
          // (the 90-flit loss at VCS=2: src47 lost pid23 when tptr=23,
          // VC-deferred, became due at the same tick as tptr=24; src8
          // lost pids 18 AND 65 in the same way). The ord={1,0} reorder
          // only ever pairs different classes, so this guard is specific
          // to the {0,1} path, but a deferred entry can collide with a
          // same-class follower at any VC count. The skipped entry stays
          // at the pointer and retries next edge -- pending-blocked until
          // the first packet's tail injects, exactly BookSim's per-class
          // flit queue.
          if ((pv < VCS) &&
              ((i == 0) || (idx == 1 ? f0 : f1)) &&
              !fired_c[c] &&
              (!pkt[c].pending ||
               (inject_valid && inject_flit.tail && (serve == c))) &&
              (trace_mem[tptr + idx] != '1) &&
              // range words (cycle==0) are not packet entries
              (trace_mem[tptr + idx][63:32] != '0) &&
              ((tick_r + 1) >= trace_mem[tptr + idx][63:32])) begin
            if (idx == 0) f0 = 1'b1; else f1 = 1'b1;
            fired_c[c] = 1'b1;
`ifdef R1_MODE
            $display("FIRE n%0d tptr=%0d cl=%0d cycle=%0d tick=%0d dst=%0d sz=%0d",
                     Y * X_DIM + X, tptr + idx, c, trace_mem[tptr + idx][63:32],
                     tick_r, trace_mem[tptr + idx][23:16],
                     trace_mem[tptr + idx][15:0]);
`endif
            pkt[c].pending   <= 1'b1;
            pkt[c].dst       <= trace_mem[tptr + idx][23:16];
            // stream pid: tptr for unicast; mcast streams live in the
            // (tptr<<3) space so their copies (stream_pid|offset, offset
            // in [1..7]) can never collide with a later stream's pid
            // F13 (ee61): {8'h00, tptr+idx} truncated the 11-bit tptr to
            // 8 bits — pids wrapped at 256 on VCS>=4 traces (tptr>=256,
            // 65/135 (src,pid) pairs reused). Unicast now lives in the
            // 0x8000+ space, ABOVE the mcast space (stream (word<<4),
            // copies base+offset, max 32767) — disjoint by construction.
            pkt[c].pid       <= {1'b1, 4'h0, tptr + idx};
            pkt[c].remaining <= {16'h0000, trace_mem[tptr + idx][15:0]};
            // VeritX fork: a range word follows the entry word; its zero
            // cycle field + non-'1 pattern marks a mcast stream. Range
            // layout matches the entry format: {cycle=0, cl=lo, dst=hi}.
            pkt[c].mcast   <= 1'b0;
            pkt[c].fork_lo <= '0;
            pkt[c].fork_hi <= '0;
            if ((tptr + idx + 1) < T_DEPTH &&
                trace_mem[tptr + idx + 1] != '1 &&
                trace_mem[tptr + idx + 1][63:32] == '0) begin
              pkt[c].mcast   <= 1'b1;
              pkt[c].fork_lo <= trace_mem[tptr + idx + 1][31:24];
              pkt[c].fork_hi <= trace_mem[tptr + idx + 1][23:16];
              pkt[c].pid     <= {tptr + idx, 4'b0000};
            end
            pkt[c].size      <= {16'h0000, trace_mem[tptr + idx][15:0]};
            pkt[c].vc        <= pv;
            // a multi-flit head fired here claims its VC from the NEXT edge
            // (its head injects next cycle) -- exclude it from the second
            // same-cycle entry's pick
            if (trace_mem[tptr + idx][15:0] > 1)
              claimed = int'(pv);
            // A 1-flit fired at i==0 must NOT hand its VC to a same-cycle
            // follower. The follower's injection order is decided by serve at
            // T+1, which rotates from the POST-edge last_class -- while this
            // ord/reorder was computed from the PRE-edge value. A flit
            // injecting during cycle T moves last_class, so the two can
            // disagree: if the multi's head then hits the wire before the
            // 1-flit, the 1-flit lands embedded in the multi's stream (the
            // R3,2 INTLV at t=69620, PITFALLS 23). Claim the VC instead: the
            // follower defers one cycle and picks it cleanly behind the
            // 1-flit's h1t1 -- the exact wire order BookSim's one-flit-per-
            // cycle serving produces, at identical injection timing.
            if ((i == 0) && (trace_mem[tptr + idx][15:0] == 1))
              claimed = int'(pv);
          end
        end
`ifdef R1_MODE
        if (X == 4 && Y == 6 && tick_r >= 65536 && tick_r < 65610)
          $display("TP52 t=%0d tp=%0d c1=%b f0=%b f1=%b ord=%0d inj=%b", tick_r,
                   tptr, consumed1, f0, f1, ord[0], inject_valid);
`endif
        // Consume in generation order. If the reordered pair fired the
        // tptr+1 entry while the tptr entry deferred (its pick was
        // VC-blocked), hold tptr on the deferred entry and latch consumed1
        // so the fired entry is not re-read; once the deferred entry fires,
        // advance past both. The latch (not a BRAM write) keeps tptr from
        // ever walking into the end-of-trace '1 padding and wrapping the
        // 10-bit pointer to replay the trace (PITFALLS 24).
        //
        // F2 fix: the range-word skip is computed once from the trace
        // content (a range word has cycle==0), for whichever entry fired --
        // the tptr entry normally, or the tptr+1 entry in the reorder case.
        // The consumed1 reorder advance previously skipped +2 blindly and
        // never consumed the range word of a reorder-fired mcast entry,
        // leaving tptr parked on the range word forever (replay deadlock).
        begin
          logic fired_mcast_skip;
          if (consumed1 && f0) begin
            // the deferred tptr entry fired now. The deferred entry cannot
            // itself be mcast (its range word would occupy tptr+1, which is
            // the fired real entry), so only the tptr+1 entry's range word
            // (at tptr+2) needs skipping. A range word has cycle==0.
            fired_mcast_skip =
              ((tptr + 2) < T_DEPTH &&
               trace_mem[tptr + 2] != '1 &&
               trace_mem[tptr + 2][63:32] == '0);
            tptr <= tptr + 2 + (fired_mcast_skip ? 1 : 0);
            consumed1 <= 1'b0;
          end else if (consumed1) begin
            tptr <= tptr;                 // deferred entry still blocked
          end else if ((ord[0] == 1) && f1 && !f0) begin
            consumed1 <= 1'b1;            // tptr unchanged: retry the deferred entry
          end else begin
            // normal path: fired tptr entry (f0) and/or tptr+1 (f1); the
            // range word after a fired entry has cycle==0
            tptr <= tptr + f0 + f1 +
                    ((f0 && (tptr + 1) < T_DEPTH &&
                      trace_mem[tptr + 1] != '1 &&
                      trace_mem[tptr + 1][63:32] == '0) ? 1 : 0);
          end
        end
      end
    end
  end

  function automatic logic [31:0] lfsr_next(input logic [31:0] s);
    s ^= s << 13;
    s ^= s >> 17;
    s ^= s << 5;
    return s;
  endfunction

  assign tick        = tick_r;
  assign injected_cnt = inj_cnt;
  assign ejected_cnt = ejc_cnt;
  assign dbg_trace0  = trace_mem[0];
  assign dbg_tptr    = tptr;
  assign dbg_pending = pkt[0].pending;
  for (genvar c = 0; c < CLS; c++) begin : gen_lat
    assign lat_sum[c] = lsum[c];
    assign lat_cnt[c] = lcnt[c];
  end
  for (genvar c = CLS; c < 4; c++) begin : gen_lat_hi
    assign lat_sum[c] = '0;
    assign lat_cnt[c] = '0;
  end

endmodule

`endif
