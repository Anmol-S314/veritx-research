`ifndef NOC_ROUTER_SV
`define NOC_ROUTER_SV

// 5-port mesh router replicating BookSim's iq_router + islip (fork 2026-08-08).
// Contract: RTL-ARC.md §3 "Request formation" + "Measured cycle model".
//
// Pipeline per hop (all four delays = 1, so requests resolve in-cycle):
//   recv T        -> flit written into VC buffer; head: XY route computed the
//                    same cycle; VA request presented at T+1.
//   VA grant T+1  -> output VC TakeBuffer (in_use), VC -> SA_HOLD (request
//                    presented at T+2 -- NOT T+1; the SA push lands after the
//                    same-cycle SW evaluate).
//   SA grant T+2  -> front flit popped (credit sent upstream the SAME cycle),
//                    downstream occupancy reserved (SendingFlit), tail releases
//                    the output VC (wait_for_tail_credit = 0). XT at T+3.
//   XT T+3        -> crossbar + flit on the output wire.
//   recv T+5      -> downstream (2-cycle link).
// Body flits into an ACTIVE VC present SA the same cycle they are written and
// pop at T -> XT T+1 -> recv T+3 (steady state 1 flit/cycle/VC).
//
// SA granularity: one request per (input port, output port); VCs at one input
// requesting the same output merge, winner = RR from _sw_rr_offset[input]
// (prios are all 0); offset advances to (winner+1)%VCS only on a real grant.
// VA granularity: per (input,VC) -> (output,VC) iSLIP, VC range [0, VCS-1],
// eligibility = output VC not in-use ONLY (_vc_busy_when_full = 0).
// SA eligibility = downstream credit > 0. Two distinct gates.

module noc_router #(
  parameter int VCS     = 4,
  parameter int X       = 0,
  parameter int Y       = 0,
  parameter int X_DIM   = 4,
  parameter int Y_DIM   = 4,
  parameter int DIE_BASE = 0,   // 0 = die A, 64 = die B (2-die bridge mode)
  parameter int BRIDGE_COL = 0  // bridge column on die A (die B: entry col)
)(
  input  logic            clk,
  input  logic            rst_n,
  input  noc_pkg::link_f_t         flit_in  [NUM_PORTS],
  input  noc_pkg::link_c_t         credit_in[NUM_PORTS],
  input  noc_pkg::link_c_t         credit_in_early[NUM_PORTS],
  output noc_pkg::link_f_t         flit_out [NUM_PORTS],
  output noc_pkg::link_c_t         credit_out[NUM_PORTS],
  output logic [31:0] tick,
  output logic [31:0] recv_cnt[NUM_PORTS],
  output logic [31:0] send_cnt[NUM_PORTS],
  output logic [31:0] pop_cnt[NUM_PORTS],
  output noc_pkg::dbg_router_t dbg
);

  import noc_pkg::*;

  localparam int VC_W = $clog2(VCS);
  // occ must count 0..VC_BUF_DEF (a full buffer holds VC_BUF_DEF flits), so it
  // needs $clog2(VC_BUF_DEF)+1 bits; hp/tp are ring pointers (mod VC_BUF_DEF)
  localparam int PT_W = $clog2(VC_BUF_DEF) + 1;

  // node id (row-major, y first) — matches the fork's kncube numbering and the
  // mcast copy range encoding (copy at node n iff copy_lo <= n <= copy_hi);
  // die-B routers add DIE_BASE (64) so copy ranges in 64..127 match.
  localparam int MY_ID = DIE_BASE + Y * X_DIM + X;
  localparam int my_id = MY_ID;

  typedef enum logic [2:0] {
    S_IDLE    = 3'd0,
    S_VA_REQ  = 3'd1,   // head at front; VA request presented every cycle
    S_ROUTE   = 3'd2,   // head behind a just-popped tail; route stage (BS parity)
    S_SA_HOLD = 3'd3,   // SA request presented (first cycle after VA grant)
    S_ACTIVE  = 3'd4    // SA request presented every cycle while non-empty
  } vc_state_t;

  // ------------------------------------------------------------------
  // per (input, VC) storage
  // ------------------------------------------------------------------
  flit_t      qbuf     [NUM_PORTS][VCS][VC_BUF_DEF];
  logic [PT_W-1:0] hp [NUM_PORTS][VCS];
  logic [PT_W-1:0] tp [NUM_PORTS][VCS];
  logic [PT_W-1:0] occ[NUM_PORTS][VCS];
  vc_state_t  st      [NUM_PORTS][VCS];
  logic [2:0] out_port[NUM_PORTS][VCS];
  logic [VC_W-1:0] out_vc [NUM_PORTS][VCS];

  // per (output, VC) downstream mirror
  logic [3:0] credit_free[NUM_PORTS][VCS];   // init VC_BUF_DEF
  logic       in_use     [NUM_PORTS][VCS];
  logic [31:0] pop_cnt_o [NUM_PORTS][VCS];   // audit: flits popped to output
  logic [31:0] ack_cnt_o [NUM_PORTS][VCS];   // audit: credits arrived at input

  // SA merge offset, one per input port
  logic [VC_W-1:0] sw_rr_offset[NUM_PORTS];

  logic [31:0] tick_r;
  logic [3:0]  cfL_prev;   // SA63 debug: prior-cycle LOCAL-output credit
  logic        in_use_prev [NUM_PORTS][VCS];
`ifdef R1_MODE
  // [DBG-a4f2] zombie + parked-head latch support
  logic [31:0] empty_cyc    [NUM_PORTS][VCS];
  logic        zombie_logged[NUM_PORTS][VCS];
  logic [31:0] park_cyc     [NUM_PORTS][VCS];
  logic        park_logged  [NUM_PORTS][VCS];
`endif

  // ------------------------------------------------------------------
  // recv: write flits into VC buffers at cycle T
  // ------------------------------------------------------------------
  logic [VC_W-1:0] wr_vc[NUM_PORTS];
  for (genvar i = 0; i < NUM_PORTS; i++) begin : gen_wrvc
    assign wr_vc[i] = flit_in[i].flit.vc[VC_W-1:0];
  end

  // effective front flit: buffer front, or the just-written flit when the
  // buffer was empty and a write arrives this cycle (same-cycle SA case)
  flit_t  front      [NUM_PORTS][VCS];
  logic   front_valid[NUM_PORTS][VCS];

  for (genvar i = 0; i < NUM_PORTS; i++) begin : gen_front
    for (genvar v = 0; v < VCS; v++) begin : gen_front_vc
      assign front[i][v] =
        (occ[i][v] == '0) ? flit_in[i].flit : qbuf[i][v][hp[i][v]];
      assign front_valid[i][v] =
        (occ[i][v] != '0) ||
        (flit_in[i].valid && (wr_vc[i] == v));
    end
  end

  // ------------------------------------------------------------------
  // XY dimension-order routing (computed at recv for heads)
  // ------------------------------------------------------------------
  // 2-die (DIE_BASE>0): dst<64 = local die, dst>=64 = the other die.
  // Die A routes remote traffic to (BRIDGE_COL, Y_DIM-1) then EAST (bridge);
  // die B receives at (0, BRIDGE_COL) WEST and DORs locally on (dst-64).
  function automatic logic [2:0] xy_dor(
    input logic [7:0] x, y, dx, dy
  );
    if (dx != x) return (dx > x) ? PORT_E : PORT_W;
    else if (dy != y) return (dy > y) ? PORT_N : PORT_S;
    else return PORT_L;
  endfunction

  function automatic logic [2:0] route2d(
    input logic [7:0] dst
  );
    logic [7:0] lx, ly;
    logic [7:0] bx, by;
    bx = 8'(BRIDGE_COL);
    by = 8'(Y_DIM - 1);
    if (DIE_BASE == 0) begin
      // die A: remote targets route to the bridge, then cross EAST
      if (dst >= 8'h40) begin
        if ((Y == Y_DIM-1) && (X == BRIDGE_COL)) return PORT_E;
        return xy_dor(X[7:0], Y[7:0], bx, by);
      end
      return xy_dor(X[7:0], Y[7:0], dst % X_DIM, dst / X_DIM);
    end else begin
      // die B: local targets only. Y-first DOR: climb to the multicast row
      // (row 0 = ly) BEFORE routing east, matching the BookSim off-axis path
      // (up the entry column, then along the row -- the measured placement
      // penalty of (BRIDGE_ROW) hops). PORT_S is toward lower y (row 0);
      // PORT_N is toward higher y. On-axis (BRIDGE_ROW=0) degrades to
      // plain east-along-row-0.
      lx = (dst - 8'h40) % X_DIM;
      ly = (dst - 8'h40) / X_DIM;
      if (Y != ly) return (Y > ly) ? PORT_S : PORT_N;
      return xy_dor(X[7:0], Y[7:0], lx, ly);
    end
  endfunction

  // ------------------------------------------------------------------
  // VA: per (input,VC) -> (output,VC) iSLIP, range [0,VCS-1], not-in-use
  // ------------------------------------------------------------------
  logic [NUM_PORTS*VCS-1:0][NUM_PORTS*VCS-1:0] va_req;
  logic [NUM_PORTS*VCS-1:0][NUM_PORTS*VCS-1:0] va_grant;
  logic [VC_W-1:0] va_gnt_vc[NUM_PORTS][VCS];

  for (genvar i = 0; i < NUM_PORTS; i++) begin : gen_va_req
    for (genvar v = 0; v < VCS; v++) begin : gen_va_req_vc
      for (genvar o = 0; o < NUM_PORTS; o++) begin : gen_va_req_o
        logic row_req;
        assign row_req = (st[i][v] == S_VA_REQ) && (o == out_port[i][v]);
        for (genvar ov = 0; ov < VCS; ov++) begin : gen_va_req_ov
          assign va_req[i*VCS+v][o*VCS+ov] = row_req && !in_use[o][ov];
        end
      end
    end
  end

  islip #(.N(NUM_PORTS*VCS)) va_islip (
    .clk(clk), .rst_n(rst_n),
    .req(va_req), .grant(va_grant)
  );

  for (genvar i = 0; i < NUM_PORTS; i++) begin : gen_va_gnt
    for (genvar v = 0; v < VCS; v++) begin : gen_va_gnt_vc
      always_comb begin
        va_gnt_vc[i][v] = '0;
        for (int ov = 0; ov < VCS; ov++) begin
          if (va_grant[i*VCS+v][out_port[i][v]*VCS+ov]) begin
            va_gnt_vc[i][v] = ov[VC_W-1:0];
          end
        end
      end
    end
  end

  // ------------------------------------------------------------------
  // SA: (input port, output port), VCs merged, credit-gated
  // ------------------------------------------------------------------
  logic [NUM_PORTS-1:0][NUM_PORTS-1:0] sa_req;
  logic [NUM_PORTS-1:0][NUM_PORTS-1:0] sa_grant;
  logic [VC_W-1:0] sa_win_vc[NUM_PORTS][NUM_PORTS];

  for (genvar i = 0; i < NUM_PORTS; i++) begin : gen_sa
    for (genvar o = 0; o < NUM_PORTS; o++) begin : gen_sa_o
      always_comb begin
        logic found;
        logic [VC_W-1:0] best;
        logic [VC_W-1:0] d;
        found = 1'b0; best = '0; d = '0;
        for (int v = 0; v < VCS; v++) begin
          if ((st[i][v] == S_SA_HOLD || st[i][v] == S_ACTIVE) &&
              front_valid[i][v] &&
              (out_port[i][v] == o) &&
              cred_avail[o][out_vc[i][v]]) begin
            d = (v - sw_rr_offset[i] + VCS) % VCS;
            if (!found || (d < (best - sw_rr_offset[i] + VCS) % VCS)) begin
              best = v[VC_W-1:0];
              found = 1'b1;
            end
          end
        end
        sa_req[i][o]    = found;
        sa_win_vc[i][o] = best;
      end
    end
  end

  islip #(.N(NUM_PORTS)) sa_islip (
    .clk(clk), .rst_n(rst_n),
    .req(sa_req), .grant(sa_grant)
  );

  // per-(input,VC) SA pop: this VC is the merge winner at its output
  logic sa_pop[NUM_PORTS][VCS];
  for (genvar i = 0; i < NUM_PORTS; i++) begin : gen_sa_pop
    for (genvar v = 0; v < VCS; v++) begin : gen_sa_pop_vc
      assign sa_pop[i][v] =
        (st[i][v] == S_SA_HOLD || st[i][v] == S_ACTIVE) &&
        front_valid[i][v] &&
        cred_avail[out_port[i][v]][out_vc[i][v]] &&
        sa_grant[i][out_port[i][v]] &&
        (sa_win_vc[i][out_port[i][v]] == v);
    end
  end

  // ------------------------------------------------------------------
  // credits out: emitted on pop for the INPUT vc (same cycle as the pop)
  // ------------------------------------------------------------------
  always_comb begin
    for (int i = 0; i < NUM_PORTS; i++) begin
      credit_out[i].valid = 1'b0;
      credit_out[i].vc    = '0;
      for (int v = 0; v < VCS; v++) begin
        if (sa_pop[i][v]) begin
          credit_out[i].valid = 1'b1;
          credit_out[i].vc    = v[VC_W-1:0];
        end
      end
    end
  end

  // ------------------------------------------------------------------
  // XT stage: popped flit held one cycle, driven on the wire next cycle
  // ------------------------------------------------------------------
  flit_t xt_flit [NUM_PORTS];
  logic  xt_valid[NUM_PORTS];

  // ---- F1 fix: eject FIFO for the multicast fork ----
  // The local-port XT slot has TWO potential writers: a genuine local eject
  // (sa_pop to PORT_L) and a fork copy (mcast head popping to a network port
  // whose node is in the copy range). BookSim's eject output buffer accepts
  // both in one cycle and is unbounded by default (output_buffer_size=-1), so
  // a fork copy is NEVER lost or delayed in the reference. The RTL's single
  // XT slot cannot hold two writes in one cycle, so fork copies go through a
  // small FIFO (eject_fifo), drained 1/cycle into PORT_L. Under the
  // single-stream gate cells the FIFO is always empty when a copy arrives
  // (the NIC drains 1/cycle and copies arrive >= 5 cycles apart), so
  // atime parity with BookSim is preserved exactly; under contention the
  // FIFO queues copies that BookSim also queues (its output buffer), so
  // delivery is preserved and timing matches BookSim's own queueing.
  // Genuine local ejects take PORT_L directly (the FIFO defers one cycle if
  // it would collide -- order of the two PORT_L writers is not observable by
  // the diff, which sorts by pid).
  localparam int EJECT_FIFO_DEPTH = 4;
  flit_t  eject_fifo [EJECT_FIFO_DEPTH];
  logic   eject_fifo_occ [EJECT_FIFO_DEPTH];   // occupancy bitmap
  logic   [3:0] eject_fifo_head;
  logic   [3:0] eject_fifo_tail;
  logic   [3:0] eject_fifo_cnt;
  logic        fork_copy_pending;   // the scan found a copy this cycle
  flit_t       fork_copy_flit;      // that copy (bypass/drain path)
  logic        local_eject_cyc;     // a genuine sa_pop to PORT_L this cycle

  always_ff @(posedge clk or negedge rst_n) begin
    if (!rst_n) begin
      for (int o = 0; o < NUM_PORTS; o++) xt_valid[o] <= 1'b0;
      eject_fifo_cnt <= '0;
      eject_fifo_head <= '0;
      eject_fifo_tail <= '0;
      for (int i = 0; i < EJECT_FIFO_DEPTH; i++)
        eject_fifo_occ[i] <= 1'b0;
    end else begin
      // PORT_L (local eject) is written by exactly one source per cycle:
      // a genuine eject (sa_pop to PORT_L) when one fires, else the FIFO
      // head (drain). Fork copies never write PORT_L directly -- they go
      // through the eject FIFO.
      for (int o = 0; o < NUM_PORTS; o++) begin
        xt_valid[o] <= 1'b0;
        for (int i = 0; i < NUM_PORTS; i++) begin
          for (int v = 0; v < VCS; v++) begin
            if (sa_pop[i][v] && (out_port[i][v] == o)) begin
              xt_valid[o] <= 1'b1;
              xt_flit[o]  <= front[i][v];
              xt_flit[o].vc <= out_vc[i][v];
            end
          end
        end
      end

      // ---- VeritX multicast fork: push copies into the eject FIFO ----
      // A mcast stream transits this router to its next hop (the sa_pop
      // above); if this node is in the stream's copy range, the stream's
      // copy is pushed to the local eject FIFO (BookSim: copy pushed to the
      // eject output buffer while the stream continues -- iq_router.cpp
      // fork, one copy per node). At most one copy per node per cycle (one
      // mcast stream per source per cycle), so the scan finds <= 1.
      local_eject_cyc = 1'b0;
      for (int i = 0; i < NUM_PORTS; i++) begin
        for (int v = 0; v < VCS; v++) begin
          if (sa_pop[i][v] && (out_port[i][v] == PORT_L))
            local_eject_cyc = 1'b1;
        end
      end
      begin
        logic found_copy;
        flit_t copy_flit;
        found_copy = 1'b0;
        copy_flit  = '0;
        for (int i = 0; i < NUM_PORTS; i++) begin
          for (int v = 0; v < VCS; v++) begin
            if (!found_copy &&
                sa_pop[i][v] && (out_port[i][v] != PORT_L) &&
                front[i][v].mcast && front[i][v].head &&
                (my_id >= front[i][v].copy_lo) && (my_id <= front[i][v].copy_hi)) begin
              found_copy = 1'b1;
              copy_flit = front[i][v];
              copy_flit.dst = my_id[7:0];
              copy_flit.pid = {front[i][v].pid[15:4],
                               4'(my_id - front[i][v].copy_lo + 1)};
              copy_flit.vc  = '0;      // copy marker: no credit return
              copy_flit.mcast = 1'b0;
              copy_flit.copy_lo = '0;
              copy_flit.copy_hi = '0;
            end
          end
        end
        if (found_copy) begin
          // blocking: the delivery block below reads these same-cycle
          // (NBA would not be visible until the next edge)
          fork_copy_pending = 1'b1;
          fork_copy_flit    = copy_flit;
          if (eject_fifo_cnt == EJECT_FIFO_DEPTH[3:0]) begin
            $display("F1 GUARD: eject FIFO overflow (my_id=%0d)", my_id);
            $fatal(1, "eject FIFO overflow");
          end else if (eject_fifo_cnt > 0) begin
            // FIFO already has queued copies: push
            eject_fifo[eject_fifo_tail[1:0]] <= copy_flit;
            eject_fifo_occ[eject_fifo_tail[1:0]] <= 1'b1;
            eject_fifo_tail <= eject_fifo_tail + 1;
            eject_fifo_cnt <= eject_fifo_cnt + 1;
          end else if (local_eject_cyc) begin
            // cnt==0 but a genuine eject wins PORT_L this cycle: the copy
            // cannot drain via the bypass, so it queues for next cycle
            eject_fifo[eject_fifo_tail[1:0]] <= copy_flit;
            eject_fifo_occ[eject_fifo_tail[1:0]] <= 1'b1;
            eject_fifo_tail <= eject_fifo_tail + 1;
            eject_fifo_cnt <= eject_fifo_cnt + 1;
          end
          // cnt==0 && !local_eject: drains this cycle through the bypass
        end else begin
          fork_copy_pending = 1'b0;
        end
      end

      // ---- PORT_L delivery: genuine eject wins, else FIFO head ----
      // A fork copy pushed into an empty FIFO this cycle bypasses the
      // FIFO (drains immediately) -- the FIFO read port cannot see a
      // same-cycle write, so without the bypass a single copy would be
      // delayed one cycle and the single-stream gate cells would fail
      // atime parity.
      begin
        logic local_eject_cyc2;
        logic drain_copy;         // the fork's copy_flit from the block above
        local_eject_cyc2 = local_eject_cyc;
        drain_copy = fork_copy_pending && (eject_fifo_cnt == 0) &&
                     !local_eject_cyc2;        if (local_eject_cyc2) begin
          // (1) genuine eject: the generic loop wrote it this cycle
          xt_valid[PORT_L] <= 1'b1;
        end else if (drain_copy) begin
          // (2a) the just-pushed copy drains immediately
          xt_valid[PORT_L] <= 1'b1;
          xt_flit[PORT_L]  <= fork_copy_flit;
        end else if (eject_fifo_cnt > 0) begin
          // (2b) FIFO head drains into the slot
          xt_valid[PORT_L] <= 1'b1;
          xt_flit[PORT_L]  <= eject_fifo[eject_fifo_head[1:0]];
          eject_fifo_occ[eject_fifo_head[1:0]] <= 1'b0;
          eject_fifo_head <= eject_fifo_head + 1;
          eject_fifo_cnt <= eject_fifo_cnt - 1;
        end else begin
          // nothing fired: slot stays clear
          xt_valid[PORT_L] <= 1'b0;
        end
      end
    end
  end

  for (genvar o = 0; o < NUM_PORTS; o++) begin : gen_fout
    assign flit_out[o].valid = xt_valid[o];
    assign flit_out[o].flit  = xt_flit[o];
  end

  // ------------------------------------------------------------------
  // next-state: buffers, pointers, credits, in-use, VC state, offsets
  // ------------------------------------------------------------------
  logic credit_inc[NUM_PORTS][VCS];   // credit arrived from downstream
  logic credit_dec[NUM_PORTS][VCS];   // SA grant reserved a slot
  logic va_grab    [NUM_PORTS][VCS];  // VA grant takes the output VC
  logic tail_rel   [NUM_PORTS][VCS];  // tail SA grant releases the output VC

  // SA gating sees a credit the cycle it reaches the router's input
  // (credit_in, 2 mesh stages out from the downstream pop) and grants the
  // same cycle: BookSim's read at T is processed in _OutputQueuing at T --
  // after the allocators -- and gates the SA grant at T+1; the RTL's 2-stage
  // credit channel lands 1 cycle later than the fork's 1-cycle channel, so
  // landing-at-C == read-at-(C-1) == grant-at-C.
  logic cred_avail[NUM_PORTS][VCS];
  always_comb begin
    for (int i = 0; i < NUM_PORTS; i++)
      for (int v = 0; v < VCS; v++)
        cred_avail[i][v] = (credit_free[i][v] > 0) ||
                           (credit_in[i].valid && (credit_in[i].vc == v));
  end

  always_comb begin
    for (int i = 0; i < NUM_PORTS; i++)
      for (int v = 0; v < VCS; v++)
        credit_inc[i][v] = credit_in[i].valid && (credit_in[i].vc == v);
  end

  // credit_dec: any pop on output port i, VC v
  always_comb begin
    for (int i = 0; i < NUM_PORTS; i++)
      for (int v = 0; v < VCS; v++)
        credit_dec[i][v] = 1'b0;
    for (int i = 0; i < NUM_PORTS; i++)
      for (int v = 0; v < VCS; v++)
        if (sa_pop[i][v])
          credit_dec[out_port[i][v]][out_vc[i][v]] = 1'b1;
  end

  always_comb begin
    for (int o = 0; o < NUM_PORTS; o++)
      for (int v = 0; v < VCS; v++)
        va_grab[o][v] = 1'b0;
    for (int i = 0; i < NUM_PORTS; i++)
      for (int v = 0; v < VCS; v++)
        if ((st[i][v] == S_VA_REQ) && (|va_grant[i*VCS+v]))
          va_grab[out_port[i][v]][va_gnt_vc[i][v]] = 1'b1;
  end

  always_comb begin
    for (int o = 0; o < NUM_PORTS; o++)
      for (int v = 0; v < VCS; v++)
        tail_rel[o][v] = 1'b0;
    for (int i = 0; i < NUM_PORTS; i++)
      for (int v = 0; v < VCS; v++)
        if (sa_pop[i][v] && front[i][v].tail)
          tail_rel[out_port[i][v]][out_vc[i][v]] = 1'b1;
  end

  always_ff @(posedge clk or negedge rst_n) begin
    if (!rst_n) begin
      tick_r <= '0;
      for (int i = 0; i < NUM_PORTS; i++) begin
        sw_rr_offset[i] <= '0;
        recv_cnt[i] <= '0; send_cnt[i] <= '0; pop_cnt[i] <= '0;
        for (int v = 0; v < VCS; v++) begin
          hp[i][v] <= '0; tp[i][v] <= '0; occ[i][v] <= '0;
          st[i][v] <= S_IDLE;
          out_port[i][v] <= PORT_L;
          out_vc[i][v] <= '0;
`ifdef R1_MODE
          empty_cyc[i][v] <= '0;
          zombie_logged[i][v] <= 1'b0;
          park_cyc[i][v] <= '0;
          park_logged[i][v] <= 1'b0;
`endif
        end
        for (int o = 0; o < NUM_PORTS; o++) begin
          for (int v = 0; v < VCS; v++) begin
            credit_free[o][v] <= VC_BUF_DEF[3:0];
            in_use[o][v] <= 1'b0;
          end
        end
      end
    end else begin
      tick_r <= tick_r + 1;
      cfL_prev <= credit_free[4][0];
      for (int pp = 0; pp < NUM_PORTS; pp++)
        for (int vv = 0; vv < VCS; vv++)
          in_use_prev[pp][vv] <= in_use[pp][vv];

      for (int i = 0; i < NUM_PORTS; i++) begin
        if (flit_in[i].valid) recv_cnt[i] <= recv_cnt[i] + 1;
        if (flit_out[i].valid) send_cnt[i] <= send_cnt[i] + 1;
      end

      // ---- [DBG-2die] fork stream tracer (small nets only, R1_MODE off)
      if (tick_r < 300 && ((my_id >= 56 && my_id <= 71) || my_id == 120 ||
                           my_id == 112 || my_id == 104 || my_id == 96)) begin
        for (int o = 0; o < NUM_PORTS; o++)
          if (flit_out[o].valid)
            $display("T%0d R%0d XTO o%0d p%0d d%0d", tick_r, my_id, o,
                     flit_out[o].flit.pid, flit_out[o].flit.dst);
      end

      // credit counters: inc (arrival) and dec (reservation) may collide;
      // saturate at [0, VC_BUF_DEF] per the BufferState invariant
      for (int o = 0; o < NUM_PORTS; o++) begin
        for (int v = 0; v < VCS; v++) begin
          if (credit_inc[o][v]) ack_cnt_o[o][v] <= ack_cnt_o[o][v] + 1;
          if (credit_dec[o][v]) pop_cnt_o[o][v] <= pop_cnt_o[o][v] + 1;
          if (credit_inc[o][v] && credit_dec[o][v])
            credit_free[o][v] <= credit_free[o][v];
          else if (credit_inc[o][v])
            credit_free[o][v] <= credit_free[o][v] +
                                 ((credit_free[o][v] < VC_BUF_DEF[3:0]) ? 1 : 0);
          else if (credit_dec[o][v])
            credit_free[o][v] <= credit_free[o][v] -
                                 ((credit_free[o][v] > 0) ? 1 : 0);
        end
      end

      // in-use: VA grab and tail release never collide on the same (o,v)
      for (int o = 0; o < NUM_PORTS; o++) begin
        for (int v = 0; v < VCS; v++) begin
          if (tail_rel[o][v]) in_use[o][v] <= 1'b0;
          else if (va_grab[o][v]) in_use[o][v] <= 1'b1;
        end
      end

      for (int i = 0; i < NUM_PORTS; i++) begin
        for (int v = 0; v < VCS; v++) begin
          logic do_write, do_pop;
          do_write = flit_in[i].valid && (wr_vc[i] == v);
          do_pop   = sa_pop[i][v];
`ifdef R1_MODE
`ifndef R1_DEBUG
          if (X == 2 && Y == 6 && (do_write || do_pop))
            $display("R62 t=%0d %s p%d i%d v%d h=%b t=%b d=%0d o=%0d st=%0d",
                     tick_r, do_write ? "W" : "P", flit_in[i].flit.pid, i, v,
                     do_write ? flit_in[i].flit.head : front[i][v].head,
                     do_write ? flit_in[i].flit.tail : front[i][v].tail,
                     do_write ? flit_in[i].flit.dst  : front[i][v].dst,
                     occ[i][v], st[i][v]);
          if (X == 7 && Y == 7 && tick_r >= 65536 && tick_r < 81407)
            if (sa_pop[i][v] && (out_port[i][v] == 4))
              $display("E63 t=%0d POPi%d v%d d=%0d cfL%d", tick_r, i, v,
                       front[i][v].dst, credit_free[4][v]);
          if (X == 7 && Y == 7 && i == 1 && v == 0 && tick_r >= 65536 &&
              tick_r < 81407 && (tick_r % 1000 == 0 || sa_pop[1][0] ||
               credit_free[4][0] != cfL_prev))
            $display("SA63 t=%0d st=%0d fv=%b req=%b grt=%b win=%0d pop=%b cfL=%0d",
                     tick_r, st[1][0], front_valid[1][0], sa_req[1][4],
                     sa_grant[1][4], sa_win_vc[1][4], sa_pop[1][0],
                     credit_free[4][0]);
          if (X == 0 && Y == 0 && i == 0 && tick_r >= 65536 && tick_r < 66000)
            if (do_write || do_pop)
              $display("N0E t=%0d %s p%d d=%0d v%d st=%0d op=%0d oc=%0d cf=%0d",
                       tick_r, do_write ? "W" : "P", flit_in[i].flit.pid,
                       do_write ? flit_in[i].flit.dst : front[i][v].dst, v,
                       st[i][v], out_port[i][v], occ[i][v], credit_free[out_port[i][v]][out_vc[i][v]]);
          if (X == 7 && Y == 7 && tick_r >= 65630 && tick_r < 65800) begin
            int ws, wv;
            ws = st[1][0]; wv = st[3][0];
            if (i == 0 && v == 0)
              $display("R77 t=%0d iuL%d tr%d vg%d Wst%d Wop%d Woc%d Sst%d Sop%d Soc%d",
                       tick_r, in_use[4][0], tail_rel[4][0], va_grab[4][0],
                       ws, out_port[1][0], occ[1][0], wv, out_port[3][0], occ[3][0]);
          end
          if (X == 4 && Y == 4 && tick_r >= 65536 && tick_r < 65620)
            if (i == 0 && v == 0) begin
              for (int ii = 0; ii < NUM_PORTS; ii++)
                for (int vv = 0; vv < VCS; vv++)
                  if (st[ii][vv] != S_IDLE || occ[ii][vv] != 0)
                    $display("R44 t=%0d iuL%d tr%d vg%d I%dV%d st%d op%d ov%d oc%d h%b t%b p%d d%d cfL%d",
                             tick_r, in_use[4][0], tail_rel[4][0], va_grab[4][0],
                             ii, vv, st[ii][vv], out_port[ii][vv], out_vc[ii][vv],
                             occ[ii][vv], front[ii][vv].head, front[ii][vv].tail,
                             front[ii][vv].pid, front[ii][vv].dst, credit_free[4][0]);
            end
          if (X == 4 && Y == 3 && tick_r >= 65560 && tick_r < 65640)
            if (i == 0 && v == 0) begin
              for (int ii = 0; ii < NUM_PORTS; ii++)
                for (int vv = 0; vv < VCS; vv++)
                  if (st[ii][vv] != S_IDLE || occ[ii][vv] != 0)
                    $display("R43 t=%0d iuN%d trN%d vgN%d cfN%d I%dV%d st%d op%d ov%d oc%d h%b t%b p%d d%d",
                             tick_r, in_use[2][0], tail_rel[2][0], va_grab[2][0],
                             credit_free[2][0],
                             ii, vv, st[ii][vv], out_port[ii][vv], out_vc[ii][vv],
                             occ[ii][vv], front[ii][vv].head, front[ii][vv].tail,
                             front[ii][vv].pid, front[ii][vv].dst);
            end
          if (X == 4 && Y == 2 && tick_r >= 65550 && tick_r < 65640)
            if (i == 0 && v == 0) begin
              for (int ii = 0; ii < NUM_PORTS; ii++)
                for (int vv = 0; vv < VCS; vv++)
                  if (st[ii][vv] != S_IDLE || occ[ii][vv] != 0)
                    $display("R42 t=%0d iuN%d trN%d vgN%d cfN%d I%dV%d st%d op%d ov%d oc%d h%b t%b p%d d%d",
                             tick_r, in_use[2][0], tail_rel[2][0], va_grab[2][0],
                             credit_free[2][0],
                             ii, vv, st[ii][vv], out_port[ii][vv], out_vc[ii][vv],
                             occ[ii][vv], front[ii][vv].head, front[ii][vv].tail,
                             front[ii][vv].pid, front[ii][vv].dst);
              if (flit_in[4].valid)
                $display("R42in t=%0d V%d p%d d%d h%b t%b",
                         tick_r, wr_vc[4], flit_in[4].flit.pid, flit_in[4].flit.dst,
                         flit_in[4].flit.head, flit_in[4].flit.tail);
            end
          if ((X == 2 && Y == 6 || X == 3 && Y == 6) && i == 0 && v == 0) begin
            logic in_use_chg;
            in_use_chg = (in_use[0][0] != in_use_prev[0][0]) || tick_r < 60;
            if (in_use_chg || (sa_pop[0][0] && front[0][0].tail))
              $display("R%0d%0d t=%0d iuE%d trE%d vgE%d cfE%d o0st%d o0oc%d o1st%d o1oc%d o4st%d o4oc%d h%b t%b p%d d%d",
                       X, Y, tick_r, in_use[0][0], tail_rel[0][0], va_grab[0][0],
                       credit_free[0][0], st[0][0], occ[0][0], st[1][0], occ[1][0],
                       st[4][0], occ[4][0], front[0][0].head, front[0][0].tail,
                       front[0][0].pid, front[0][0].dst);
          end
          if (X == 2 && Y == 6 && tick_r >= 65640 && tick_r < 65900 && i == 0 && v == 0) begin
            for (int q = 0; q < NUM_PORTS; q++) begin
              if (st[q][0] != S_IDLE || occ[q][0] != 0 || flit_in[q].valid)
                $display("D26 t=%0d p%0d st%d oc%d op%d iu%d vg%d tr%d wr%b h%b t%b p%d d%d",
                         tick_r, q, st[q][0], occ[q][0], out_port[q][0],
                         in_use[out_port[q][0]][out_vc[q][0]], va_grab[out_port[q][0]][out_vc[q][0]],
                         tail_rel[out_port[q][0]][out_vc[q][0]], flit_in[q].valid,
                         flit_in[q].flit.head, flit_in[q].flit.tail,
                         flit_in[q].flit.pid, flit_in[q].flit.dst);
            end
          end

          // ---- [DBG-a4f2] global smoke detectors: flit loss / VC theft / zombie
          if (do_write && (occ[i][v] >= VC_BUF_DEF))
            $display("OVF t=%0d R%0d%0d i%0d v%0d oc%0d p%d d%d h%b t%b",
                     tick_r, X, Y, i, v, occ[i][v],
                     flit_in[i].flit.pid, flit_in[i].flit.dst,
                     flit_in[i].flit.head, flit_in[i].flit.tail);
          // ---- [DBG-a4f2] interleave detector: a HEAD written into a VC
          // whose PREVIOUS write slot is NOT a tail = two packets sharing one
          // VC buffer (corruption). The naive "front not a tail" test is a
          // false positive: in the legit wait_for_tail_credit=0 handoff the
          // new head is written directly behind the old tail (write order),
          // while the tail is still 2+ slots from the front -- S_ROUTE
          // handles that. Only the slot-immediately-before-the-write
          // discriminates: it is the tail in the handoff, a body/head in a
          // real interleave (PITFALLS 23).
          if (do_write && flit_in[i].flit.head && (occ[i][v] > 0) &&
              !qbuf[i][v][(tp[i][v] - 1) % VC_BUF_DEF].tail)
            $display("INTLV t=%0d R%0d%0d i%0d v%0d oc%0d fp%0d fd%0d ft%b np%0d nd%0d nt%b",
                     tick_r, X, Y, i, v, occ[i][v],
                     qbuf[i][v][(tp[i][v] - 1) % VC_BUF_DEF].pid,
                     qbuf[i][v][(tp[i][v] - 1) % VC_BUF_DEF].dst,
                     qbuf[i][v][(tp[i][v] - 1) % VC_BUF_DEF].tail,
                     flit_in[i].flit.pid, flit_in[i].flit.dst,
                     flit_in[i].flit.tail);
          for (int o = 0; o < NUM_PORTS; o++)
            for (int vv = 0; vv < VCS; vv++)
              if (tail_rel[o][vv] && va_grab[o][vv])
                $display("TRVG t=%0d R%0d%0d o%0d v%0d", tick_r, X, Y, o, vv);

          // ---- [DBG-a4f2] zombie latch: ACTIVE VC, empty buffer, no flit in
          // flight, persisting > 8 cycles (legit gaps are <= 2 cycles)
          for (int pp = 0; pp < NUM_PORTS; pp++) begin
            for (int vv = 0; vv < VCS; vv++) begin
              if (st[pp][vv] == S_ACTIVE && occ[pp][vv] == 0 &&
                  !flit_in[pp].valid) begin
                if (empty_cyc[pp][vv] >= 32'd8 && !zombie_logged[pp][vv]) begin
                  zombie_logged[pp][vv] <= 1'b1;
                  $display("ZOMB t=%0d R%0d%0d i%0d v%0d op%0d ov%0d cf%0d iu%0d",
                           tick_r, X, Y, pp, vv, out_port[pp][vv], out_vc[pp][vv],
                           credit_free[out_port[pp][vv]][out_vc[pp][vv]],
                           in_use[out_port[pp][vv]][out_vc[pp][vv]]);
                end
                empty_cyc[pp][vv] <= empty_cyc[pp][vv] + 1;
              end else begin
                empty_cyc[pp][vv] <= '0;
              end
            end
          end

          // ---- [DBG-a4f2] parked-head latch: S_SA_HOLD holding an in_use
          // output VC with no pop progress for >8 cycles. This is the ghost
          // the ZOMB latch cannot see (ZOMB only fires on ACTIVE+empty); the
          // first PARK line in the log is the earliest parked head = the seed.
          for (int pp = 0; pp < NUM_PORTS; pp++) begin
            for (int vv = 0; vv < VCS; vv++) begin
              if ((st[pp][vv] == S_SA_HOLD) &&
                  in_use[out_port[pp][vv]][out_vc[pp][vv]]) begin
                if (park_cyc[pp][vv] >= 32'd8 && !park_logged[pp][vv]) begin
                  park_logged[pp][vv] <= 1'b1;
                  $display("PARK t=%0d R%0d%0d i%0d v%0d op%0d ov%0d cf%0d iu%0d p%0d d%0d",
                           tick_r, X, Y, pp, vv, out_port[pp][vv], out_vc[pp][vv],
                           credit_free[out_port[pp][vv]][out_vc[pp][vv]],
                           in_use[out_port[pp][vv]][out_vc[pp][vv]],
                           front[pp][vv].pid, front[pp][vv].dst);
                end
                park_cyc[pp][vv] <= park_cyc[pp][vv] + 1;
              end else begin
                park_cyc[pp][vv] <= '0;
              end
            end
          end

          // ---- [DBG-a4f2] dense trace: R1,1 N-input + L output (the root
          // zombie) and R1,2 N-input + S output (its tail source)
          if (tick_r >= 69500 && tick_r < 70600) begin
            if (X == 1 && Y == 1 && i == 2 && v == 0)
              $display("D11 t=%0d Nst%0d Noc%0d W%b P%b h%b t%b p%0d d%0d iuL%0d trL%0d vgL%0d cfL%0d",
                       tick_r, st[2][0], occ[2][0], flit_in[2].valid, sa_pop[2][0],
                       flit_in[2].flit.head, flit_in[2].flit.tail,
                       flit_in[2].flit.pid, flit_in[2].flit.dst,
                       in_use[4][0], tail_rel[4][0], va_grab[4][0],
                       credit_free[4][0]);
            if (X == 1 && Y == 2 && i == 2 && v == 0)
              $display("D12N t=%0d st%0d oc%0d W%b P%b h%b t%b p%0d d%0d iuS%0d trS%0d vgS%0d cfS%0d",
                       tick_r, st[2][0], occ[2][0], flit_in[2].valid, sa_pop[2][0],
                       flit_in[2].flit.head, flit_in[2].flit.tail,
                       flit_in[2].flit.pid, flit_in[2].flit.dst,
                       in_use[3][0], tail_rel[3][0], va_grab[3][0],
                       credit_free[3][0]);
            if (X == 1 && Y == 2 && i == 3 && v == 0)
              $display("D12S t=%0d st%0d oc%0d W%b P%b h%b t%b p%0d d%0d",
                       tick_r, st[3][0], occ[3][0], flit_in[3].valid, sa_pop[3][0],
                       flit_in[3].flit.head, flit_in[3].flit.tail,
                       flit_in[3].flit.pid, flit_in[3].flit.dst);
          end

          // ---- [DBG-a4f2c] R1,6 seed-ghost trace: full VC state + S/N gates
          if (tick_r >= 66360 && tick_r < 66460 && X == 1 && Y == 6 &&
              i == 0 && v == 0) begin
            $display("D16 t=%0d iuS%d trS%d vgS%d cfS%d iuN%d trN%d vgN%d cfN%d",
                     tick_r, in_use[3][0], tail_rel[3][0], va_grab[3][0],
                     credit_free[3][0], in_use[2][0], tail_rel[2][0],
                     va_grab[2][0], credit_free[2][0]);
            for (int q = 0; q < NUM_PORTS; q++) begin
              if (st[q][0] != S_IDLE || occ[q][0] != 0 || flit_in[q].valid)
                $display("D16v t=%0d p%0d st%0d oc%0d op%0d ov%0d hp%0d tp%0d fh%b ft%b fp%0d fd%0d wr%b wh%b wt%b wp%0d wd%0d",
                         tick_r, q, st[q][0], occ[q][0], out_port[q][0],
                         out_vc[q][0], hp[q][0], tp[q][0],
                         front[q][0].head, front[q][0].tail,
                         front[q][0].pid, front[q][0].dst,
                         flit_in[q].valid, flit_in[q].flit.head,
                         flit_in[q].flit.tail, flit_in[q].flit.pid,
                         flit_in[q].flit.dst);
            end
            if (sa_pop[2][0])
              $display("D16p t=%0d p2 popped fh%b ft%b fp%0d fd%0d n2h%b n2p%0d n2d%0d",
                       tick_r, front[2][0].head, front[2][0].tail,
                       front[2][0].pid, front[2][0].dst,
                       qbuf[2][0][(hp[2][0] + 1) % VC_BUF_DEF].head,
                       qbuf[2][0][(hp[2][0] + 1) % VC_BUF_DEF].pid,
                       qbuf[2][0][(hp[2][0] + 1) % VC_BUF_DEF].dst);
          end
          if (tick_r >= 66220 && tick_r < 66460 && X == 1 && Y == 5 &&
              i == 0 && v == 0) begin
            $display("D15 t=%0d iuS%d trS%d vgS%d cfS%d",
                     tick_r, in_use[3][0], tail_rel[3][0], va_grab[3][0],
                     credit_free[3][0]);
            for (int q = 0; q < NUM_PORTS; q++) begin
              if (st[q][0] != S_IDLE || occ[q][0] != 0 || flit_in[q].valid)
                $display("D15v t=%0d p%0d st%0d oc%0d op%0d ov%0d hp%0d tp%0d fh%b ft%b fp%0d fd%0d wr%b wh%b wt%b wp%0d wd%0d",
                         tick_r, q, st[q][0], occ[q][0], out_port[q][0],
                         out_vc[q][0], hp[q][0], tp[q][0],
                         front[q][0].head, front[q][0].tail,
                         front[q][0].pid, front[q][0].dst,
                         flit_in[q].valid, flit_in[q].flit.head,
                         flit_in[q].flit.tail, flit_in[q].flit.pid,
                         flit_in[q].flit.dst);
            end
            if (sa_pop[2][0])
              $display("D15p t=%0d p2 popped fh%b ft%b fp%0d fd%0d n2h%b n2p%0d n2d%0d",
                       tick_r, front[2][0].head, front[2][0].tail,
                       front[2][0].pid, front[2][0].dst,
                       qbuf[2][0][(hp[2][0] + 1) % VC_BUF_DEF].head,
                       qbuf[2][0][(hp[2][0] + 1) % VC_BUF_DEF].pid,
                       qbuf[2][0][(hp[2][0] + 1) % VC_BUF_DEF].dst);
          end
          if (tick_r >= 66360 && tick_r < 66460 && X == 1 && Y == 7 &&
              i == 2 && v == 0) begin
            $display("D17 t=%0d st%0d oc%0d op%0d ov%0d fh%b ft%b fp%0d fd%0d pop%b iuS%d cfS%d wr%b wp%0d wd%0d",
                     tick_r, st[2][0], occ[2][0], out_port[2][0], out_vc[2][0],
                     front[2][0].head, front[2][0].tail, front[2][0].pid,
                     front[2][0].dst, sa_pop[2][0], in_use[3][0],
                     credit_free[3][0], flit_in[2].valid, flit_in[2].flit.pid,
                     flit_in[2].flit.dst);
          end

          // ---- [DBG-a4f2d] pid-130 watcher: flit_in arrivals + pops of the
          // late control packet (src 51 -> dst 22), every router, whole net
          if (tick_r >= 74450 && tick_r < 74650 && i == 0 && v == 0) begin
            for (int q = 0; q < NUM_PORTS; q++) begin
              if (flit_in[q].valid && flit_in[q].flit.pid == 16'd130)
                $display("P130 t=%0d R%0d%0d i%0d v%0d h%b t%b cl%0d cfl%0d st%0d oc%0d op%0d cfS%0d iuS%d",
                         tick_r, X, Y, q, flit_in[q].flit.vc,
                         flit_in[q].flit.head, flit_in[q].flit.tail,
                         flit_in[q].flit.cl, credit_free[q][0],
                         st[q][flit_in[q].flit.vc], occ[q][flit_in[q].flit.vc],
                         out_port[q][flit_in[q].flit.vc],
                         credit_free[3][0], in_use[3][0]);
            end
            if (X == 3 && Y == 6 && i == 0 && v == 0)
              $display("P130L t=%0d st%0d oc%0d op%0d iuW%d cfW%d sa%0d fh%b ft%b fp%0d fd%0d wr%b wp%0d wd%0d",
                       tick_r, st[4][0], occ[4][0], out_port[4][0],
                       in_use[1][0], credit_free[1][0], sa_pop[4][0],
                       front[4][0].head, front[4][0].tail, front[4][0].pid,
                       front[4][0].dst, flit_in[4].valid, flit_in[4].flit.pid,
                       flit_in[4].flit.dst);
          end

          // ---- [DBG-a4f2] dense trace: row-3 W chain (R2,3..R7,3 W output
          // vc0 claim + pops) and R6,3 ghost
          if (tick_r >= 66000 && tick_r < 66800 && Y == 3 && X >= 2) begin
            if (X == 6) begin
              if (i == 0 && v == 0)
                $display("D63 t=%0d iuW%0d trW%0d vgW%0d cfW%0d p0:st%0d oc%0d op%0d p1:st%0d oc%0d op%0d p2:st%0d oc%0d op%0d p3:st%0d oc%0d op%0d p4:st%0d oc%0d op%0d",
                         tick_r, in_use[1][0], tail_rel[1][0], va_grab[1][0],
                         credit_free[1][0], st[0][0], occ[0][0], out_port[0][0],
                         st[1][0], occ[1][0], out_port[1][0],
                         st[2][0], occ[2][0], out_port[2][0],
                         st[3][0], occ[3][0], out_port[3][0],
                         st[4][0], occ[4][0], out_port[4][0]);
            end else if (X == 5 && tick_r >= 66198 && tick_r < 66250 &&
                 i == 0 && v == 0) begin
              // [DBG-a4f2b] R5,3 E-input vc0 per-cycle: front vs incoming flit
              // (pid/dst), pop, and the W0 claim. Discriminates signature 1
              // (p4's head pops here then blocks on an orphaned W0 in_use)
              // from signature 3 (front flit destroyed by a full-buffer
              // overwrite, tp wrapping onto hp).
              $display("D53 t=%0d st%0d oc%0d op%0d ov%0d fh%b ft%b fp%0d fd%0d win%b wh%b wt%b wp%0d wd%0d pop%b iuW%0d cfW%0d",
                       tick_r, st[0][0], occ[0][0], out_port[0][0], out_vc[0][0],
                       front[0][0].head, front[0][0].tail, front[0][0].pid,
                       front[0][0].dst, flit_in[0].valid, flit_in[0].flit.head,
                       flit_in[0].flit.tail, flit_in[0].flit.pid,
                       flit_in[0].flit.dst, sa_pop[0][0],
                       in_use[1][0], credit_free[1][0]);
            end else if (i == 0 && v == 0 && (in_use[1][0] != in_use_prev[1][0] ||
                 sa_pop[0][0] || flit_in[0].valid))
              $display("D%0d3 t=%0d iuW%0d trW%0d vgW%0d cfW%0d E:st%0d oc%0d op%0d h%b t%b p%0d d%0d W:st%0d oc%0d L:st%0d oc%0d",
                       X, tick_r, in_use[1][0], tail_rel[1][0], va_grab[1][0],
                       credit_free[1][0], st[0][0], occ[0][0], out_port[0][0],
                       flit_in[0].flit.head, flit_in[0].flit.tail,
                       flit_in[0].flit.pid, flit_in[0].flit.dst,
                       st[1][0], occ[1][0], st[4][0], occ[4][0]);
          end
`endif
`endif

          // buffer occupancy: write and pop may collide
          if (do_write && do_pop)       occ[i][v] <= occ[i][v];
          else if (do_write)            occ[i][v] <= occ[i][v] + 1;
          else if (do_pop)              occ[i][v] <= occ[i][v] - 1;

          if (do_write) begin
            qbuf[i][v][tp[i][v]] <= flit_in[i].flit;
            tp[i][v] <= (tp[i][v] + 1) % VC_BUF_DEF;
          end
          if (do_pop) begin
            hp[i][v] <= (hp[i][v] + 1) % VC_BUF_DEF;
            pop_cnt[i] <= pop_cnt[i] + 1;
          end

          if (do_pop) begin
            sw_rr_offset[i] <= (v + 1) % VCS;
          end

          case (st[i][v])
            S_IDLE: begin
              if (do_write && flit_in[i].flit.head) begin
                st[i][v] <= S_VA_REQ;
                out_port[i][v] <= route2d(flit_in[i].flit.dst);
              end else if ((occ[i][v] > 0) && front[i][v].head) begin
                // defensive: a head left buffered in an idle VC
                st[i][v] <= S_VA_REQ;
                out_port[i][v] <= route2d(front[i][v].dst);
              end
            end
            S_VA_REQ: begin
              if (|va_grant[i*VCS+v]) begin
                st[i][v] <= S_SA_HOLD;
                out_vc[i][v] <= va_gnt_vc[i][v];
              end
            end
            S_ROUTE: begin
              st[i][v] <= S_VA_REQ;
            end
            S_SA_HOLD, S_ACTIVE: begin
              if (do_pop) begin
                if (front[i][v].tail) begin
                  if (occ[i][v] > 1) begin
                    // a new packet's head is already buffered behind the
                    // tail (the NIC reuses the VC as soon as credits allow):
                    // take a routing stage (the BookSim fork pushes the new
                    // head's route request after the tail's grant, so it
                    // completes one cycle later) before presenting the VA
                    // request
                    st[i][v] <= S_ROUTE;
                    out_port[i][v] <= xy_dor(
                      X[7:0], Y[7:0],
                      qbuf[i][v][(hp[i][v] + 1) % VC_BUF_DEF].dst % X_DIM,
                      qbuf[i][v][(hp[i][v] + 1) % VC_BUF_DEF].dst / X_DIM);
                  end else begin
                    st[i][v] <= S_IDLE;
                  end
                end else if (occ[i][v] > 1) begin
                  // next flit already buffered: head -> VA next cycle
                  if (qbuf[i][v][(hp[i][v] + 1) % VC_BUF_DEF].head) begin
                    st[i][v] <= S_VA_REQ;
                    out_port[i][v] <= xy_dor(
                      X[7:0], Y[7:0],
                      qbuf[i][v][(hp[i][v] + 1) % VC_BUF_DEF].dst % X_DIM,
                      qbuf[i][v][(hp[i][v] + 1) % VC_BUF_DEF].dst / X_DIM);
                  end else begin
                    st[i][v] <= S_ACTIVE;
                  end
                end else begin
                  st[i][v] <= S_ACTIVE;
                end
              end
            end
            default: st[i][v] <= S_IDLE;
          endcase
        end
      end
    end

`ifdef R1_MODE
`ifndef R1_DEBUG
    // cycle-by-cycle freeze-window trace: full VC state + the gates that move it
    if (X == 7 && Y == 7 && tick_r >= 65600 && tick_r <= 65860)
      for (int p = 0; p < NUM_PORTS; p++) begin
        for (int v = 0; v < VCS; v++) begin
          if (st[p][v] != S_IDLE || occ[p][v] != 0 || flit_in[p].valid)
            $display("TR77 t=%0d p%0d v%0d st%0d oc%0d op%0d ov%0d iu%0d w%0d sa%0d va%0d wr%0d h%b t%b p%0d d%0d cfl%0d",
                     tick_r, p, v, st[p][v], occ[p][v], out_port[p][v], out_vc[p][v],
                     in_use[4][0], flit_in[p].valid, sa_pop[p][v],
                     |va_grant[p*VCS+v], wr_vc[p], front[p][v].head, front[p][v].tail,
                     front[p][v].pid, front[p][v].dst, credit_free[4][0]);
        end
      end
    if (X == 4 && Y == 4 && tick_r >= 65600 && tick_r <= 65860)
      for (int p = 0; p < NUM_PORTS; p++) begin
        for (int v = 0; v < VCS; v++) begin
          if (st[p][v] != S_IDLE || occ[p][v] != 0 || flit_in[p].valid)
            $display("TR44 t=%0d p%0d v%0d st%0d oc%0d op%0d ov%0d iu%0d w%0d sa%0d va%0d wr%0d h%b t%b p%0d d%0d cfl%0d",
                     tick_r, p, v, st[p][v], occ[p][v], out_port[p][v], out_vc[p][v],
                     in_use[4][0], flit_in[p].valid, sa_pop[p][v],
                     |va_grant[p*VCS+v], wr_vc[p], front[p][v].head, front[p][v].tail,
                     front[p][v].pid, front[p][v].dst, credit_free[4][0]);
        end
      end
`endif
`endif
  end

  assign tick = tick_r;

  for (genvar i = 0; i < NUM_PORTS; i++) begin : gen_dbg
    for (genvar v = 0; v < VCS; v++) begin : gen_dbg_vc
      assign dbg.st[i][v]          = st[i][v];
      assign dbg.out_port[i][v]    = out_port[i][v];
      assign dbg.out_vc[i][v]      = out_vc[i][v];
      assign dbg.credit_free[i][v] = credit_free[i][v];
      assign dbg.in_use[i][v]      = in_use[i][v];
      assign dbg.occ[i][v]         = occ[i][v];
      assign dbg.pop_o[i][v]       = pop_cnt_o[i][v];
      assign dbg.ack_o[i][v]       = ack_cnt_o[i][v];
    end
  end

endmodule

`endif
