# Multi-seat concentrator — proposal (P3)

Date: 2026-11-10 · Status: **DRAFT — no RTL emitted, no gate re-run** · Owner lane: composed-family emission (`project_top_rtl.py`) · Milestone: P3-CONCENTRATOR

## 0. Scope, constraints, evidence discipline

This document proposes a *multi-seat concentrator* (`concentrator_*.sv`) so the composed-family
wrapper can host more than one endpoint seat per NoC router. Today every composed family whose
canonical attachment co-seats agents on a router refuses with `UNSUPPORTED_COMPOSED_FAMILY`.

- **No existing file is modified by this note.** No builds or Verilator runs were performed; every
  claim below is a static reading with `file:line` citations (taken 2026-11-10). Nothing here
  re-quotes the release matrix; the matrix rows for `cmesh/fly/qtree/tree4/fattree` remain
  typed-refused until this work lands and `families-lint` + the matrix are re-run.
- Constraint honoured: this file is the only artifact created.
- Out of scope: mesh/torus/flatfly (concentration = 1 — unaffected), SROTA/GEC hybrid (their own
  refusal ledgers), formal proof of the escape class, STA.

## 1. The blocker, exactly where it fires

`run_composed_family()` (`tracks/t3-topology/dse/veritx_dse/product/project_top_rtl.py:6376`) calls
`_require_single_endpoint_per_router(params)` (line 6389), which (lines 6367–6376) counts endpoints
per `router_id` from `params.seats` and raises

```
UNSUPPORTED_COMPOSED_FAMILY: multiple endpoint seats on one router are not yet connected by the
composed wrapper: {router: [endpoint, ...]}
```

refuse the emission before any file is written. Refused families today: `cmesh`, `fly`, `qtree`,
`tree4`, `fattree` — pinned in `docs/product/SEQUENTIAL-GATES.md:25` ("the open P3 item"),
`docs/product/P2-P3-EVIDENCE-20261110.md:31`, `docs/product/INTENT-TO-PLACED-RTL-P0-P1-STATUS.md:632,634`,
`docs/product/INTENT-TO-PLACED-RTL-20261110-AUDIT.md:106`. Tests pinning the refusal:
`tracks/t3-topology/dse/tests/test_project_top_slice.py:283–306` ("ConcentratedMeshIntent(2, 2)" → seats
[0,0,1]) and `:357–380` (the 12-family parametrize — multi-seat families refuse, others lint/sim).

**Why the emission cannot carry co-seated routers today.** The composed top gives the NoC *one
injection port per router* and nothing arbitrates it:

- `noc_top` (emitted by `_render_family_noc_top`, `project_top_rtl.py:5085`) emits exactly one
  `local_in_flit_{r} / local_in_valid_{r} / local_in_ready_{r}` per router and wires it to the
  `local_in_*` port of the per-router `router #(...)` instance (router instantiation lines 5256–5277,
  `local_in_flit_{r}` at 5249).
- `render_family_project_top` (line 5845) creates one `noc_in_flit_{r}` wire **per router** and
  connects *every* co-seated slice to it: `.noc_in_flit(noc_in_flit_r)` in each
  `initiator_slice` instance (line 5964) — i.e., N output ports drive one wire, and
  `noc_top` consumes that wire as `local_in_flit_{r}` (`u_noc` instantiation, lines 5978–5984). No mux, no arbiter.
- The slice drives that wire from its CDC-bypass tap: `assign noc_in_valid = cdc_out_valid; assign
  noc_in_flit = cdc_out_flit` (in `INIT_SLICE_TEMPLATE`, `project_top_rtl.py:1510`; family sibling at
  `_render_family_initiator_template`, line 5496).
- At the memory router there is an additional, frequently forgotten driver: the destination adapter's
  response, `assign noc_in_valid_{mem} = dest_rsp_valid_w; assign noc_in_flit_{mem} = dest_rsp_flit_w`
  (render_family_project_top, lines 5930–5933). So a co-seated memory router has **N+1
  injection sources**, not N.

Multiple always-driven drivers on `noc_in_flit_r` is a multi-driven net: Verilator flags
`MULTIDRIVEN`; in simulation it x-propagates; in synthesis it is a structural short. Even if a legal
mux were hand-wired in, the router's admission gate does not tolerate two same-cycle admitted heads
(§2.3–2.4). Hence the typed refusal rather than a silent corruption.

## 2. What the router does with an injected flit today

Two sibling implementations exist; both share the admission/arbitration skeleton:

(a) **Standalone htree router** — `tracks/t3-topology/rtl/mot_htree/router_template.sv` + generated
    `noc_pkg` (`gen_rtl_htree.py` `emit_pkg`; `--block-k` default 8 ⇒ `AGE_K = BLOCK_K*8 = 64`;
    the static `scripts/rtlgen/noc_pkg.sv` carries `BLOCK_K = 16` ⇒ 128). `AGE_K = noc_pkg::BLOCK_K*8`
    is computed in router_template.sv:74. BUF_DEPTH=8, NUM_VCS=2 (VC0=FREE, VC1=ESCAPE),
    QCNT_W = 4 bits.
(b) **Composed-family unified router** — `_UNIFIED_ROUTER_TEMPLATE` embedded in
    `project_top_rtl.py:4991`, emitted by `_render_family_router` (line 4994): NUM_VCS = compiled
    `vc_count`, BUF_DEPTH from `input_buffer_depth_flits_per_vc`, VC/type/dst/src/payload field
    positions from the compiled `packet_fields` binding, `ESC_YIELD_K = 4`, local VC index from the
    flit's `vc_id` field.

### 2.1 VC allocation at enqueue (injection)

There is no VC *arbiter* at injection; the **VC field of the flit is the VC**:

- mot_htree (`router_template.sv`): `lc = p2 * NUM_VCS + lv` where `lv = get_class(flit)` — bits
  `[CLASS_MSB:CLASS_LSB]` (CLASS_W=1) = the VC index (lines 705–712). For non-head flits whose
  effective queue is in escape mode, the class is **forced to the last VC** and the esc bits are
  set on the enqueued flit (`esc_forced`/`effective_esc`, lines 191–195, 231–234; S3c logic
  lines 714–723). A same-packet BODY/TAIL therefore never lands in a different VC class than its
  demoted head ("S3c fix … prevents VC split").
- Family (`_UNIFIED_ROUTER_TEMPLATE` → emission): `st_q = p * NUM_VCS + int'(get_vc(in_flit_all[p]))`;
  if a non-head and `esc_mode[st_q]`, the target queue is forced to `ESC_VC` (`st_cc = p*NUM_VCS +
  ESC_VC`). Class-forced escape likewise prevents VC split of mid-packet flits.
- Local port mapping: PORT `DEG` = `LOCAL_PORT = MAX_DEG` (`router_template.sv:39`; family template
  identical semantics, `LOCAL_PORT = MAX_DEG`, and `noc_top` instantiates `DEG = len(sorted(adj))`
  with the local bundle at index `DEG`).
- Per-queue wormhole exclusivity at enqueue: a HEAD/SINGLE is admitted **only into an empty
  effective-VC queue**; BODY/TAIL only need `q_cnt < BUF_DEPTH` (mot_htree lines 193–205 and
  235–241; family template analogous main_admit). This is the S3 invariant: a second packet may not
  interleave into a VC that holds any flit of an open packet — otherwise it is captured by the first
  packet's `rt_out` reservation and misrouted. `rt_alloc`/`rt_out` are set on head grant and cleared
  on tail transmission (lines 516–524, 556–564, 608–616); BODY/TAIL inherit nothing (route is
  memoryless per-flit — see R10 NOTE at lines 244–249).
- Credits: per (output port, VC), init `BUF_DEPTH`, `+1` on wire accept, `−1` on stage load
  (lines 90–93, 457, 498, 509, 538, 550). Local-port **injection consumes no credit** — credit
  pressure lives downstream of the local port, not at it.

### 2.2 Arbitration, and `esc_yield_q` after re-pipeline

mot_htree `router_template.sv` (the re-pipelined version):

1. **Grant stage A (combinational, lines 295–351).** Per output port `o` (skipped for `LOCAL_PORT`,
   line 309): escape candidates (VC 1..N−1) are scanned port-first `_p = 0..NUM_PORTS-1`, first-match
   wins (lines 311–322); the free-class candidate (VC 0) is scanned round-robin from `rr_ptr[o]`
   (lines 324–333). Grants are **per class, independent stages** — both classes can load the same
   cycle: `grant_valid`/`grant_sp`/`grant_sv` = ESC-preferred encoding, `grant_valid2`/`grant_sp2` =
   the other class (lines 334–350). `grant_valid[o] = esc_valid | free_valid`.
2. **Grant stage B (registered, lines 359–401).** The grant *decision itself* is a register bank
   (`grant_valid_r` …); all consumers (output-stage loads, ejection skip, enqueue race) read only the
   registered decision. Registering keeps one-cycle-old decisions consistent with the stable queue
   front. `esc_starve[o]` (4-bit, lines 111, 473–484) counts consecutive cycles where esc won while a
   free candidate was pending; after reaching `ESC_YIELD_K−1 = 3` it **arms `esc_yield_q[o]` for
   exactly one cycle** (lines 474–484).
3. **Wire mux (lines 223–230).** `show_vc[p] = 1` iff the esc stage is valid and NOT
   (`esc_yield_q[p] && free stage occupied`) — shallow logic over registered state only; escape owns
   the wire except for the one-window free grant.
4. **Ejection (LOCAL out, lines 572–625).** Separate esc-first pass then free pass (`pass2 = 1,0`),
   first matching queue with `dst == ID` wins; queues already dequeued by the grant path this cycle
   are skipped (`grant_deq_q`, line 590); the stage is held until accepted (S4 fix, lines 584–586);
   LOCAL latches `esc_stage_vc` for non-zero slots (R6 fix, lines 601–602).
5. Credits return on wire accept (lines 498, 537–538); demotion logic (`blk_cnt` cumulative packet
   age) exists at lines 644–702 (note: in this template the demotion block is **compiled out**,
   `if (0 && blk_cnt[c2] >= AGE_K[7:0])` at line 686 — R6 experiment — though `blk_cnt` still
   counts and the STUCK dump prints at ≥ 200). In the family template demotion is live:
   `q_age[c] >= AGE_K && get_vc(q[c][0]) == 0 ⇒ esc_mode[c] <= 1'b1`.

Family unified router (the code the composed families actually emit): the same esc-first/free/round-robin
policy is expressed combinationally at the grant: if both `esc_valid[o]` and `free_valid[o]`, the
esc-starves counter `esc_starve[o] >= ESC_YIELD_K` decides the winner for that cycle (free wins once,
counter resets); both winners still load in parallel via `grant_valid`/`grant_valid2`; the wire mux
(`show_vc_k`) is combinational off `out_valid_all` and `esc_starve[p] >= ESC_YIELD_K`. There is **no
`esc_yield_q` register** in the family template — `esc_yield_q` is the mot_htree formulation; same
policy, two implementations. (Both use `ESC_YIELD_K = 4`; see `router_template.sv:105`, `:110–111`;
family template lines at `_UNIFIED_ROUTER_TEMPLATE` search `ESC_YIELD_K`.)

### 2.3 The VC0 free-class admission gate — the contention point

Local-port acceptance for packet head or body/tail, from one (valid, ready) driver:

- mot_htree, lines 231–241:
  ```
  effective_esc_local = get_esc(flit) | (!is_head && esc_mode[LOCAL_PORT*NUM_VCS + (get_esc ? 1 : 0)])
  local_in_ready =
      (effective_esc_local ? q_cnt[LOCAL_PORT*NUM_VCS + 1] : q_cnt[LOCAL_PORT*NUM_VCS + 0]) < BUF_DEPTH
    && (!is_head(flit) || (effective_esc_local ? q_cnt[LOCAL_PORT*NUM_VCS + 1]
                                                : q_cnt[LOCAL_PORT*NUM_VCS + 0]) == 0)
  ```
- Family template: `in_ready_all[p] = (q_cnt[st_cc] < BUF_DEPTH) && (!is_head || q_cnt[st_cc] == 0)`.

So admission into the **VC0 free class** is: `q_cnt[local v0] < 8` AND (for HEAD/SINGLE)
`q_cnt[local v0] == 0`. Both are *unqualified-by-source* shared-queue predicates.

### 2.4 How multiple initiators contend at VC0 (and why it breaks)

If two or more co-seated slices drove `local_in_*` today (impossible legally — §1 — but consider a
hand-wired mux), the VC0 gate still breaks in six concrete ways:

1. **Multi-driver net** — §1; lint/x-propagation. Fatal before anything else.
2. **Broadcast ack** — `local_in_ready` is one signal; it would tell *both* seats "accepted"; both
   advance their FSMs; one slot is written; one flit vanishes (or the last write wins — silent
   corruption).
3. **Same-cycle head race vs. the empty-queue predicate** — both seats' heads observe
   `q_cnt == 0` combinationally; both pass; only one can be enqueued (one `q` write per cycle per
   queue). The loser is lost, or interleaved: violating S3/S3b (router_template.sv lines 698–752)
   and capturing the loser's body into the winner's `rt_out` route → misroute (the documented
   failure class the S3 fix was written for, lines 171–179).
4. **Per-queue cumulative age is not per-packet** — `blk_cnt` increments every occupied cycle of the
   (input,VC) queue regardless of owner; a co-seated packet could cross the demotion threshold
   *because of another seat's packet*, and `esc_mode[c2] <= 1'b1` flips the **whole queue**, forcing
   both seats' remaining flits onto the escape path (lines 644–702). In the family template the same
   happens via `q_age`. Cross-seat collateral demotion = loss of the FREE class for an innocent
   packet.
5. **VC split amplification** — multi-seat interleaving makes it likelier that
   head→(esc) at the next hop and body→(vc0) meet the S3c machinery; each instance of forced-class
   rewrites (lines 714–723) costs a cycle of enqueue latency and can strand a BODY behind a foreign
   packet (bounded, but it feeds back into (4)).
6. **Grant RR fairness assumes unique sources are fungible** — RR over input ports treats the local
   port as one candidate; once arbitration *inside* the local port is absent, which seat's head is at
   the queue front is a property of the (broken) driver mux, i.e. unbounded unfairness and potential
   livelock of one seat behind the other's packet train (each head waits for an empty VC0 queue that
   the other seat keeps refilling).

None of these is fixable inside the router. They define the concentrator's contract (§4).

### 2.5 Package/skew note (honest bookkeeping)

Three `noc_pkg` variants coexist: the **static** `mot_htree/noc_pkg.sv` (mesh-era: no `CLASS_W`,
`TYPE_W = 2` at [62:61], `flit_t{data, head, tail, …}` struct), the **generated** htree package
(`scripts/rtlgen/noc_pkg.sv` and `gen_rtl_htree.py:emit_pkg`: `CLASS_W`, per-gen `DST_W/CRED_W/…`),
and the **family** package (`_render_family_pkg`, `project_top_rtl.py:4942`: field offsets from the
compiled `packet_fields`, `FT_*` localparams, `flit_raw_t = logic [FLIT_W-1:0]`). The concentrator
must be parameterised on `TYPE_LSB/TYPE_MSB` (as the fabrics are) and must not hard-code [62:61].
`router_template.sv` compiles against the generated package, not the stale static one.

## 3. The adapter emission path — where a concentrator must sit

### 3.1 End-to-end path of one injected beat (family flow)

```
AXI init ──► adapter_axi5_g{0,1} (inside slice; outputs adap_out_awvalid/awlen/awsize/awaddr,
             adap_out_wdata/wvalid/wready, out_bvalid/credit_full, …)
        ──► slice capture FSM (S_IDLE→S_CAPW→S_AWRET→S_ISSUE; adap_out_* are CONSUMED HERE,
             internal to the slice — they never reach the fabric)
        ──► addr_decode → ordering_fsm (MAX_OUTSTANDING=4, STRONG ordering, VC binding)
        ──► cdc_bypass / cdc_slice_up/down (CDC_CROSSED)
        ──► noc_in_flit / noc_in_valid / noc_in_ready   ← slice's ONLY fabric-visible bundle
        ──► project_top wire noc_in_flit_{r}  (fan-in point: ONE wire per router TODAY)
        ──► noc_top port local_in_flit_{r}    ← router R's LOCAL_PORT index (DEG)
        ──► router admission: VC-class queue select, q_cnt<BUF_DEPTH, head⇒empty (§2.3)
```

`adap_out_awvalid` etc. are referenced throughout the slice template (e.g. `if (adap_out_awvalid)`,
`w_fire_w = adap_out_wvalid && adap_out_wready`, family copies at `project_top_rtl.py:5693–5810`).
There is no literal `_RENDER_ADAPTER` symbol in the file; the adapter-emission sites are
`INIT_SLICE_TEMPLATE` (line 1510, `adapter_axi5_g0/g1` instances), the widened re-render
(`_widened_slice_template`, line 1540) and the family re-render (`_render_family_initiator_template`,
line 5496, `.out_awvalid(adap_out_awvalid)…` at 5693–5762). The emission of the *network-visible*
bundle is what matters for the concentrator.

### 3.2 What a concentrator must sit between

**Between the per-seat injection bundles and the router's single local-port injection bundle** — i.e.,
in `project_top`, at the slice→`noc_top` boundary:

```
 slice_0 ── noc_in_flit_0 ┐
 slice_1 ── noc_in_flit_1 ├─► concentrator_R ── local_in_flit_R ──► noc_top.local_in_flit_{R} ─► router R LOCAL_PORT
 (u_dest ── dest_rsp_flit_w) ─┘        (exactly one driver to noc_top; R = this router)
```

Concretely, the emitter changes are confined to `render_family_project_top` (wire fan-in → per-seat
bundles + one concentrator instance per multi-seat router) and to a new emission function
`_render_seat_concentrator(...)`; `noc_top` port list and `router.sv` are **bit-identical** to the
single-seat build. The concentrator is **not**:

- **at `adap_out_*`** — those stops are inside each slice (pre-issue); placing the arbiter there would
  split the slice's own outstanding accounting and re-order the ADAPTER's W/AR streams against the
  per-slice FSM. The adapter groups' outputs are upstream of *everything* the fabric sees.
- **inside the slices** — the slices own MAX_OUTSTANDING ordering and CDC crossing; they must not be
  re-inked to know about siblings.
- **inside the router** — any arbiter in the router changes a certified-per-VC structure and forces a
  full re-qualification; zero router change is the goal.
- **inside `noc_top`** — it would duplicate per router and leak family specifics into the fabric top.

At a **memory-seated router** the source set is N slices **plus** `u_dest`'s response bundle
(`dest_rsp_flit_w`, driven by `render_family_project_top` when r == memory_router). The concentrator
therefore takes **N+1 inputs** there (or treats u_dest as seat N) — see §4.7 and §5.2.

### 3.3 The ejection side is equally broken (must be stated)

Co-seated slices also share `noc_out_flit_{r}` / `noc_out_valid_{r}` — every slice at router r taps
the same wire — and `noc_out_ready_{r}` is driven by **all co-seated slices**
(`noc_out_ready = noc_out_ready_tap`, `(state_q == S_WAIT_RSP)` in bypass mode). Two slices in
`S_WAIT_RSP` simultaneously both fire `eject_fire_w` on the *same* response flit: both advance to
`S_RESP`, both latch the same data, both increment `ej_q`; the **next** response then has no consumer
(`noc_out_ready_{r}` deasserts for everyone), the router's LOCAL output stage holds `out_valid=1`
forever → ejection stalls fabric-wide (all local ejections at r block; queues fill; global stall).
So the composed multi-seat design needs **two** blocks, not one. This proposal defines both:

1. **Injection concentrator** (primary, §4), and
2. **Response demux by per-seat seq window** (companion, §4.7) — minimal, required for any TB case
   with concurrent seats.

Alternative considered and rejected: strict global issue serialization in the bench (one seat
outstanding at a time) — it legitimises the composed top but never exercises arbitration and cannot
pass Case C (§6). Rejected for the same reason: min-seq global ordering of seats reorders across
seats, destroys the per-seat RR fairness theorem and is unnecessary — seq within a seat is only
needed to *demux responses*, windows are disjoint by construction.

## 4. Feasibility of an emitted `concentrator_*.sv`

### 4.1 Contract and parameters

```
concentrator_R #(
  parameter int N_SEATS    = 2,      // injection bundles (excluding optional dest adapter)
  parameter int DEST_INPUT = 1,      // 1 at the memory router's local port (u_dest rsp), else 0
  parameter int FLIT_W     = 64,     // family: params.flit_w (64 today)
  parameter int TYPE_LSB   = 61,     // family: from packet_fields; mot_htree: 61/TYPE_W=2
  parameter int TYPE_MSB   = 62,
  parameter int SEQ_LSB    = 32,     // beat seq field lsb ([44:32] today)
  parameter int SEQ_MSB    = 44,
  parameter int SEAT_ID_HI = 12,     // seq window [SEAT_ID_HI-SEAT_BITS+1 : SEAT_ID_HI] = seat id
  parameter int SEAT_BITS  = 2,      // ceil(log2(N_SEATS max))
  parameter int SEAT_PKT_CAP = 2,    // per-seat outstanding packet cap backstop (>=1)
  parameter int SEAT_FLIT_CAP = 4    // per-seat accepted-not-emitted flit cap backstop
)(
  input  logic clk, input logic rst_n,
  // seat side (per seat i): identical bundle shape to slice noc_in_*
  input  flit_raw_t [N_SEATS-1:0] seat_flit,
  input  logic      [N_SEATS-1:0] seat_valid,
  output logic      [N_SEATS-1:0] seat_ready,
  // local port of router R (exactly one driver):
  output flit_raw_t local_in_flit,
  output logic      local_in_valid,
  input  logic      local_in_ready,
  // response demux companion (§4.7) — same instance family, same file:
  input  flit_raw_t noc_out_flit,
  input  logic      noc_out_valid,
  output logic      noc_out_ready,
  output flit_raw_t [N_SEATS-1:0] seat_rsp_flit,
  output logic      [N_SEATS-1:0] seat_rsp_valid,
  input  logic      [N_SEATS-1:0] seat_rsp_ready,
  // debug/conservation (hierarchical probes for the TB):
  output logic [31:0] dbg_seat_acc_flit [N_SEATS],
  output logic [31:0] dbg_seat_emit_flit [N_SEATS],
  output logic [31:0] dbg_seat_acc_pkt  [N_SEATS],
  output logic [31:0] dbg_seat_emit_pkt [N_SEATS],
  output logic [$clog2(N_SEATS+1)-1:0] dbg_seat_outstanding_pkt [N_SEATS],
  output logic [2:0] dbg_lock_owner
);
```

(The response-demux half may ship as a second module `seat_rsp_demux.sv`; both are pure emission
artifacts of the same `_render_seat_concentrator` function.)

### 4.2 Architecture v1 — strict round-robin re-mux, zero storage

**STRICT round-robin by per-seat sequence counter.** One acceptance pointer `rr` (a mod-N counter
advanced only on accepted flits, never on idle cycles) plus per-seat counters `cnt_i` (count of
packets accepted from seat i). The arbitration theorem and its invariant:

- at most one seat's flit is presented to the router per cycle (out bundle is a plain mux);
- a seat whose bundle is valid is granted within **N−1 acceptances** (starvation-free round robin);
- for any two backlogged seats i, j: `|cnt_i − cnt_j| ≤ 1` at every acceptance boundary;
- within a seat, flits are presented strictly FIFO (single producer, no reorder path).

`rr` *is* the per-seat sequence counter — after every acceptance it rotates to the next seat index,
i.e. grant order is the global sequence of seat indices `i, i+1, ..., i, i+1, ...` over the accepted
stream. "STRICT" means: an eligible seat is never skipped past a higher-priority seat more than once
around the rotation; no age boost, no class preference at the CIN (class/VC policy belongs to the
router, untouched). A min-seq (oldest-global) policy was considered and rejected: it allows
unbounded skew between seats under asymmetric load and buys nothing — ordering is only needed *within*
a seat (per-slice FSMs already guarantee it) and *fairness across* seats (RR gives it for free).

```systemverilog
// sketch — emission-time constant, not committed RTL
always_ff @(posedge clk or negedge rst_n) begin
  if (!rst_n) begin rr <= '0; lock <= '0; lock_active <= 1'b0; end
  else begin
    // packet lock: a seat that won HEAD/SINGLE owns the port until TAIL/SINGLE beat accepted
    if (lock_active && accept_fire && is_head_or_tail(out_flit, lock)) begin
      lock_active <= 1'b0;                       // SINGLE clears immediately; TAIL clears here
    end else if (!lock_active && accept_fire && is_head(out_flit, sel)) begin
      lock_active <= 1'b1; lock <= sel;
    end
    if (accept_fire) rr <= next_rr(rr);
    for (i...) if (accept_fire && sel == i) begin cnt[i] <= cnt[i] + is_head; acc[i] <= acc[i]+1; emit[i] <= emit[i]+1; end
  end
end
assign local_in_valid = lock_active ? seat_valid[lock] : any_valid;
assign local_in_flit  = lock_active ? seat_flit[lock] : seat_flit[sel(rr)];
assign seat_ready     = one-hot(sel) & {N{local_in_ready}};
```

**Packet atomicity is mandatory, not optional.** The router's HEAD⇒empty-VC-queue admission rule
(§2.3) forbids any seat's head entering the local VC while another packet is mid-train in VC0; the
concentrator must therefore present each seat's packet as an indivisible unit at the port: grant HEAD
→ lock to that seat until its TAIL/SINGLE is accepted by the router (`local_in_ready` handshake). BODY
flits of the winning packet are never re-selected against other seats (`lock_active ? lock : rr`), so
no seat can inject into the transient reservation. In the current family emission every flit is
SINGLE-type (`ord_in_flit[62:61] = 2'b11` — see `_render_family_initiator_template` and the widen
map `_widen_family_initiator_src`, `project_top_rtl.py:5415`), i.e. the lock degenerates to
"grant one flit, unlock" — but the SINGLE case must not be special-cased away: the htree/multi-flit
siblings and any future multi-flit emission rely on it, and the unit TB (§6.4) covers HEAD/BODY/TAIL
explicitly.

**Registered-grant option.** v1 is combinational re-mux (zero added latency). The one risky path is
`local_in_ready → seat_ready` comb (router's `in_ready` depends on `q_cnt` of the selected class).
v1.5 adds a grant register (same discipline as the router's grant stage B): one idle cycle on grant
transitions, no throughput loss once pipelined, and `seat_ready` becomes glitch-free registered
one-hot. Both modes are emission-selectable; the TB runs both.

**Per-seat outstanding caps respected.** Three independent bounds, all assertable:

1. injection-side (CIN): `outstanding_i ≤ SEAT_FLIT_CAP` by construction (v1 holds ≤ 1 accepted-not-
   emitted flit per seat in the mux, plus optional 1-entry skid if SEAT_FLIT_CAP > 1);
   `outstanding_pkt_i ≤ SEAT_PKT_CAP`.
2. seat-internal (unchanged): each slice's `ordering_fsm` already enforces MAX_OUTSTANDING=4
   (`outstanding_full`); CIN never snoops it.
3. destination-side backstop (demux, §4.7): per-seat `exp_cnt_i` — incremented on every CIN grant of
   seat i's SINGLE flit (a request always generates exactly one response in this emission),
   decremented on every demux match to i; `exp_cnt_i == 0` at drain is a hard assertion;
   `exp_cnt_i ≤ MAX_OUTSTANDING` at all times.

A seat is never granted while its backstop is at cap (`seat_ready_i` gated); this can only add
sub-packet HOL delay, never a dependency cycle (the destination always eventually responds; the SRAM
adapter row is not congested — it is a leaf).

**Interaction with demotion / `esc_yield_q`.** None — by construction the concentrator presents whole
packets, preserves esc class bits verbatim (no bit rewriting — unlike S3c, no queue knowledge), and
never reorders; the router demotes a CIN-presented packet exactly as it would a direct-attached one.
`router.sv` stays bit-identical; the certified VC scheme, `esc_yield_q`, credit flow and ejection are
untouched. The concentrator must *not* peek at esc bits to "prioritise" escape traffic: class
priority is the router's policy, decided on VC-class queues, not at injection. (It may pass
`get_esc` through for debug only.)

### 4.3 Flit-atomicity / SINGLE-ness check

`is_head(f) := type ∈ {HEAD, SINGLE}`, `is_tail(f) := type ∈ {TAIL, SINGLE}` from
`(f[TYPE_MSB:TYPE_LSB])`. SINGLE clears lock in the same accept cycle; HEAD sets it; TAIL clears it.
No other flit resets the lock. On reset, `lock_active=0`. Overflow: none (modulo counters).

### 4.4 Required invariants the emitter must self-check at emission time

- `N_SEATS ≤ CIN_MAX` (hard cap 8; seq window `SEAT_BITS` derived); `SEAT_PKT_CAP ≥ 1`;
  `SEAT_FLIT_CAP ≥ SEAT_PKT_CAP`; `DEST_INPUT ∈ {0,1}`; at the memory router `DEST_INPUT=1`.
- emitted `concentrator_R.sv` registered with the file manifest (`files`/Merkle) — same discipline
  as `adapter_axi5_g*.sv`.
- refusal (`_refuse_family`) retained for: seats at one router exceeding CIN_MAX; missing
  `flit_type`/`vc_id`/`destination_endpoint` packet fields; unsupported `vc_count`; multi-seat
  routers that also exceed per-router `seat_capacity` (impossible by construction, but checked).

### 4.5 Why this is feasible (cost model)

Gates ≈ N×64-bit mux + one-hot select + mod-N counter + 2 FF stages + per-seat 32-bit x4 counters +
lock FFs: ≈ 500–900 gates, no SRAM, no loops, no vendor primitives — squarely in the same size class
as the existing adapter modules and CDC bypass; fully synthesizable with the same yosys/LibreLane
profile as the slice flow. Risks: (i) comb `local_in_ready→seat_ready` path (v1.5 grant register
mitigates); (ii) seq-window demux vs. harness driving seat-identical seq ranges (must be enforced by
the bench — see §6); (iii) emission-time name collisions (concentrator per multi-seat router,
`concentrator_{r}` instance naming); (iv) the ejection companion silently forgotten (loud failure
mode — §3.3 — must be an explicit manifest row, not an afterthought).

### 4.6 What the concentrator deliberately does NOT do

No VC allocation (router's job), no demotion (router's), no retransmission (fabric has none), no
request/ordering policy (slice's), no credit management (per output port, router's), no seq
re-issue (harness owns seq).

### 4.7 Companion: per-seat response demux (`seat_rsp_demux`)

*Required* because of §3.3. Minimal design: per-seat window check
`match_i := noc_out_valid && (seq_q-window == i) && exp_cnt_i > 0` (extract `seq` from payload bits
`[SEQ_MSB:SEQ_LSB] = [44:32]`, window `[SEAT_ID_HI : SEAT_ID_HI-SEAT_BITS+1] = [12:10]` for ≤8 seats,
leaving 10 bits per seat), drive `seat_rsp_valid[i] = match_i`, `noc_out_ready =
or_i(seat_rsp_ready[i] & match_i)`, per-seat `exp_cnt` incremented by a tap from the concentrator's
grant bus (count every SINGLE flit granted from seat i — one request ⇒ one response in this
emission). Wrong-seat delivery is then impossible by disjoint windows; deadlock is impossible
(exactly one match per response while any `exp_cnt_i>0`; stray responses assert an error flag, they do
not hang the port). The slice sees only its own responses, so `eject_fire_w` semantics are
restored per seat. TB asserts: no seat consumes a response whose seq window ≠ its own; `exp_cnt`==0
at drain for each seat; router LOCAL output never holds with all `noc_out_ready` deasserted while a
response is pending (covered by the hold-then-release case §6).

### 4.8 Latency/throughput

v1: 0-cycle re-mux, 1 flit/cycle max at the local port (unchanged ceiling). v1.5: +1 cycle on grant
switch only. Area/timing impact on the fabric: none outside the local-port mux tree.

## 5. Which family needs it first — and the order after

### 5.1 fattree `level_count=2 switch_radix=4` first (`FatTreeIntent(4, 2)`)

Canonical geometry (`fat_tree_graph(switch_radix=4, level_count=2)`,
`topology_artifact.py:1037`): `per_tier = 4^(2-1) = 4`, nodes = 2 tiers × 4 = **8 routers**: level 0
(edge/leaf, ids 0–3), level 1 (upper, ids 4–7). Every router carries `switch_radix = 4` seats
(intent materialization passes `seat_capacity=intent.switch_radix`, topology_artifact.py:1617–1619;
also `STRUCTURED_FAMILIES['fat_tree'] seat_capacity = radix`). Attachment is canonical
(`derive_attachment`, attachment.py:433–440): endpoints fill `seats = [(r, s) for r in routers for s in
range(cap)]` in order ⇒ the 3-agent family request (2 compute groups + 1 HBM,
`_family_agents`/`_family_request` in test_project_top_slice.py:240–266) lands **all three on router 0**
(compute0→(0,0), compute1→(0,1), memory→(0,2)) ⇒ today's refusal (test_project_top_slice.py:357–380;
the 12-family lint-and-sim gate). 5 agents: router 0 full (ports 0–3), memory at (1,0). 9 agents:
routers 0,1 full, memory at (2,0).

**Best testbed reasons**: (i) smallest routers (DEG=4, max_deg=4 ⇒ PORT_W=3; 8 nodes; 2 tiers — NCA/up-down
law exercises CIN in both a leaf and, with 9 agents, an upper router); (ii) the exact intent the DSE
matrix uses (`scripts/complete_design.py:28`, `FatTreeIntent(switch_radix=4, level_count=2)`);
(iii) leaf seats (4 per leaf router) give natural 2- and 4-seat concentrate cases; (iv) failing *right
now* — any green here converts one of the five typed `UNSUPPORTED_COMPOSED_FAMILY` rows into real
coverage.

**On "2 leaves per router"**: the canonical attachment cannot emit 2 seats per leaf (it fills router 0
first). The fattree testbed is defined two ways:

- **T-override (preferred):** bench-local seat override in the TB harness — 8 compute agents, two per
  edge router (`{a0,a1}→r0`, `{a2,a3}→r1`, `{a4,a5}→r2`, `{a6,a7}→r3`, `memory→r4` port 0, upper
  tier). This is a TB-layer knob only (agent→seat mapping in the bench's `project_top` instantiation
  data path, not an emitter change) and gives full-fabric 2-leaf-per-router routing with up→down
  traversal. It must be labelled a harness construct; it is not emission behavior.
- **T-canonical (no override):** the §6 cases below with the current canonical attachment — router-0
  co-location (3 agents) for the 2-seat smoke; 5 agents (4 seats router 0, memory router 1) for the
  4-seat routing case. Weaker (single router per case) but uses only today's emission.

### 5.2 Then the rest, in order

| # | family | geometry | seats per router | notes |
|---|--------|----------|------------------|-------|
| 1 | **fattree k=4 L=2** | 8 routers, DEG 4 | leaf seats 4 (upper seats unused today) | first; §5.1 |
| 2 | **cmesh 4×4 c=4** | `ConcentratedMeshIntent(4,4)` → 16 routers | all 16 seat 4 | highest seat density; mesh-class DOR already proves seat_capacity 2/4 (`topology_artifact.py:517,529–535`); easiest to reason about deadlock |
| 3 | **tree4 (native)** | `Tree4Intent(4,3)` / structured `tree4` | **leaves only** (level==levels−1, K=4); internal routers 0 seats | concentration only at leaves; NCA-ish law; response demux identical |
| 4 | **qtree (native)** | `QTreeIntent(4,3)` | **leaves only** (k=4, 21 routers: 1+4+16) | same leaf-only pattern; interchangeable with tree4 wrt CIN |
| 5 | **fly** | `FlyIntent(k,n)` / structured | ingress seats K at stage-0 routers; egress seats K at last stage (`fly_net.py:275–276`) | two-sided seating: needs **both** CIN at stage 0 and the response/ejection demux at the last stage; last because hardest |

(cmesh/fly/qtree/tree4 all typed-refused today — `_eligible_routers`, `project_top_rtl.py:4470`,
returns the seat holders; refusal is in `run_composed_family` via `_require_single_endpoint_per_router`.)
Second-order: flatfly stays concentration=1 (unaffected); SROTA/GEC stay on their own ledgers.

### 5.3 Sizing

fat-tree CIN-2: 2 seats (+1 u_dest at memory router 0) = 3 inputs. CIN-4: 4 (+1) = 5 inputs. Max CIN-8
(+1). Emission function emits exactly as many concentrators as multi-seat routers exist; routers with
1 source keep the direct wire (memory-only, upper-tier-only) — no needless churn.

## 6. Minimal 3-case seat TB — what proves it

Target: `tb_seat_concentrator.sv` (family emission) + a unit bench for multi-flit trains. Common
harness for Cases A/B/C: build with `run_composed_family` (lint+sim, Verilator, **reusing the family
TB style** — `render_family_tb`, `project_top_rtl.py:6028`), with the seat layout per §5.1
(T-canonical unless the override harness is approved). Each case asserts the common set (§6.2) plus
its specifics.

### 6.0 Directed traffic per case

- Seats: 2 (Case A) and 4 (Case B/C) compute agents; HBM memory agent.
- Per seat: AXI5 writes with seat-disjoint SRAM word windows (seat i owns words `[i*32, i*32+31]` of
  the 128-word window addressed by `word_w[6:0]`), `awlen=0` (single-beat) for the arbitration-stress
  pattern, and one 4-beat burst (`awlen=3`) for the SINGLE-flit multi-beat flow; read-after-write per
  seat interleaved with the other seat(s) concurrently outstanding (up to ordering_fsm
  MAX_OUTSTANDING=4).
- Full-load phase: all seats issue back-to-back with randomised `awvalid` gaps (directed, seeded);
  drain phase: idle.

### 6.1 Common harness

- DUT: `project_top` with the concentrator; hierarchical probes: `dut.u_noc.u_router_*` (q_cnt via
  `SIM_FORMAL`-independent hierarchical read — testbench-only), `dut.u_dest.sram`, per-slice
  `u_slice{i}.inj_q/ej_q/imm_q_cnt`, `dut.dbg_noc_injected/ejected`, `dut.dbg_dest_reqs/rsps/errors`,
  `dut.u_noc.local_in_valid_{r}` etc.
- Assertion style: `$fatal`/`$error` in clocked blocks; SVA `assert property` where the signal is a
  plain wire; final-block golden compare for SRAM; counters sampled at drain.

### 6.2 Common assertions (all cases, exact)

A1. **Driver discipline** — zero `MULTIDRIVEN`/zero-X on every `noc_in_flit_{r}`/`noc_out_flit_{r}`
    net at all times (lint gate + TB `!$isunknown`). The single-driver property is structural: only
    `concentrator_R` drives `local_in_*_{R}` for multi-seat r.

A2. **Conservation, per seat** — for each seat i, at every cycle and exactly at drain:
    `acc_flit[i] == emit_flit[i]`, `acc_pkt[i] == emit_pkt[i]`,
    `emit_pkt[i] == injected_beats_i` (slice `inj_q`),
    `ejected_beats_i == slice ej_q + imm_q` … per class: writes ⇒ `ej_q` counts B-resp; reads ⇒
    `ej_q` counts rdata beats. End-of-run: `Σ_i inj_i == dbg_dest_reqs`; `Σ_i ej_i == dbg_dest_rsps`;
    `dbg_noc_injected == dbg_noc_ejected`; `dbg_dest_errors == 0`.

A3. **Routing law via destination SRAM** — after drain, for every (seat, word, data) the seat wrote:
    `u_dest.sram[word[6:0]] == golden[seat][word]`. Disjoint word windows make the golden model
    unambiguous (no last-writer ambiguity). Read-after-write responses returned to each seat carry
    exactly the data in the SRAM word the seat addressed (per-beat `rdata` compare in the harness).
    Any misroute, duplication, loss, or wrong-seat delivery fails here.

A4. **Packet atomicity / lock** — monitor on the concentrator's `local_in_*` stream: once a
    HEAD/SINGLE of seat i is accepted, every subsequent flit until TAIL/SINGLE-of-i is accepted
    carries i's seq-window (and i's seat id bits); no other seat's HEAD may interpose. Formally:
    `accept(HEAD_i) |-> (next HEAD/SINGLE or TAIL on the port is from i)` until `accept(TAIL_i/SINGLE_i)`.

A5. **Fairness (strict RR)** — bounded-skew invariant `|cnt_i − cnt_j| ≤ 1` for every pair of
    backlogged seats, sampled at each acceptance (Case B: 4 seats); and a starvation bound: any seat
    with valid pending is accepted within N−1 acceptances (witness counter in TB; violation ⇒ $fatal).

A6. **Outstanding == 0 at drain** — per seat: `dbg_seat_outstanding_pkt[i] == 0`, demux `exp_cnt[i] == 0`,
    slice `dbg_outstanding_full[i] == 0`, ordering FSM in IDLE (probe `state_q == S_IDLE`), and all
    router queues empty: every `u_router_r.q_cnt[*] == 0` (hierarchical) — the fabric is *fully* drained,
    not merely "no more valids outstanding from the initiator's perspective".

A7. **Hold-then-release integrity (Case C only)** — see §6.3/C.

A8. **Wrong-seat response rejection** — no seat latches a response whose seq window ≠ its own
    (per-seat `$error` in the harness consume tap; equivalently demux `match` one-hot assertion).

A9. **No new demotions attributable to the CIN** — router `blk_cnt`/`q_age` traces at multi-seat
    routers show no packet crossing AGE_K/BLOCK_K threshold that a single-seat control build would not
    also cross (control = same traces from the pre-concentrator single-seat build with the same
    traffic seeds — reference sim, not a new RTL artifact).

A10. **Bit-identical fabric** — `router.sv` and `noc_top.sv` diff empty vs. the pre-concentrator
     build; the concentrator appears only as additional `concentrator_*.sv` files and a rewired
     `project_top.sv`. (Checked by the emitter, not the sim.)

### 6.3 Case definitions

**Case A — 2 seats (CIN-2 smoke, local hop).** FatTreeIntent(4,2); 3-agent request (2 compute + HBM);
canonical seats → router 0: seat0=(0,0), seat1=(0,1), memory=(0,2). Both computes issue concurrently;
u_dest co-seated (3rd source). Traffic is single-hop by construction (honest limitation — this case
proves arbitration, conservation, SRAM decode and the response demux; it does **not** prove multi-hop
routing).
Assertions: A1–A6, A8, A10; plus RR rotation witness: under both seats continuously valid, accepted
HEAD order alternates seat0,seat1 (initial rr=0) — exact check on the emitted stream trace.

**Case B — 4 seats (CIN-4 + real routing).** Same intent; 5 agents: computes 0–3 → router 0 ports 0–3
(canonical), memory agent 4 → router 1 port 0; route 0 → upper(4..7) → 1 (2 hops, up-down law).
All four seats concurrent, disjoint word windows (§6.0), 4-beat bursts included.
Assertions: A1–A6, A8, A10; A5 four-way skew bound; A3 SRAM golden compare for all four windows
including read-back; per-seat conservation pairwise (A2). Any cross-seat leakage fails A3/A8.
(Stretch: T-override layout — 8 computes two-per-leaf + memory at upper router 4 — same assertions,
full fabric coverage; only if the bench-local seat override is approved.)

**Case C — hold-then-release drain (backpressure to every boundary).** Case B binary. Two hold
points, applied in sequence mid-run:
  (i) **destination hold** — assert `dbg_hold=1` (u_dest `req_hold`; destination stops consuming
      requests; all fabric buffers fill toward router 0), run until each backlogged seat reaches
      `outstanding_full==1` and the concentrator refuses further grants (ready deasserts at CIN_CAP);
  (ii) **local-port hold** — additionally gate `local_in_ready` at router 0 (bench drives a CIN-input
      throttle) so the concentrator output stage backs up completely; verify zero flit motion;
  then **release** (`dbg_hold=0`, throttle removed) and run to drain.
Assertions: A1–A6, A8, A10; plus A7: at peak, per-seat `outstanding` counters equal the declared caps
(cover property); **after release, A6 must hold**; SRAM golden compare (A3) passes from the post-hold
state; conservation A2 across the hold boundary; no STUCK/`$error` from the router during the entire
hold window; no response consumed while any hold is active (A8 under hold).

### 6.4 Unit bench for the packet lock (synthetic)

`tb_seat_concentrator_unit.sv`: drive synthetic HEAD/BODY…/TAIL trains (A: seat0 train of 5 flits,
seat1 train of 3, concurrent) directly at the concentrator inputs; assert A4 exactly; verify single
cycle per flit, sustain 1 flit/cycle throughput when only one seat has data; verify lock release on
TAIL; verify SINGLE fast path; verify reset mid-packet; verify seat_ready one-hot under backpressure.
(This is the only TB that exercises multi-flit trains — the composed family emits SINGLE only.)

### 6.5 Pass/fail criteria

PASS = all assertions clean, `dbg_dest_errors==0`, full drain (A6), SRAM golden compare clean, zero
`MULTIDRIVEN` lint findings, `router.sv`/`noc_top.sv` diff empty. Any of: a lost/duplicated/misrouted
SRAM word; wrong-seat response consumption; outstanding ≠ 0 at drain; skew > 1 in Case B; deadlock or
STUCK print ⇒ FAIL. Explicitly **not** established by this TB: formal correctness, STA, multi-flit
through the real AXI path (only synthetic), mesh/torus, and the matrix re-run. Those remain separate
gates, re-run only after `families-lint` (this TB's home) is green.

## 7. Emission plan, refusal policy, and honest limits

1. New emission `_render_seat_concentrator(seats, params)` + `seat_rsp_demux`; wired in
   `render_family_project_top`; `_require_single_endpoint_per_router` narrows from "any co-seat ⇒
   refuse" to typed refusals only for the residual unsupported cases (CIN_MAX exceeded, missing packet
   fields, fly egress-plane seats before its demux lands). mesh/torus/flatfly byte-identical output.
2. `_print_refusal`/manifest: concentrator files appear in the manifest `files` list with hashes;
   `proven` rows gain "multi-seat concentrator (2/4 seats, fattree k4l2)"; `not_established` unchanged
   for STA/formal.
3. Matrix may be re-run only after this lands and `families-lint` is green for fattree first, then
   cmesh/tree4/qtree, fly last. **Do not** quote matrix verdicts before that re-run.
4. Open risks: response-demux deadlock if a seat never issues (exp_cnt stays 0, match never fires —
   safe); harness-driven seq windows overlapping (TB must assign disjoint windows — asserted); comb
   ready path timing (v1.5 registered grant); co-seated seats both re-issuing before any response
   returns (ordering caps + demux backstop bound it); T-override seating being mistaken for emission
   behavior (must be labelled in the manifest).
5. The ejection problem (§3.3) is part of this milestone's definition of done — a concentrator-only
   delivery that leaves co-seated responses to mis-consume would be worse than the refusal we have
   today.

## 8. Citations (all static, 2026-11-10)

- `tracks/t3-topology/rtl/mot_htree/router_template.sv` — 10–54 (module/params), 64–85 (queues,
  rt_alloc/rt_out/esc_mode), 90–93 (credits), 103–111 (rr_ptr, ESC_YIELD_K=4, esc_yield_q decl),
  220–230 (show_vc mux), 231–241 (local-port VC0 free-class admission), 244–266 (cand_out, R10),
  295–351 (grant stage A), 353–401 (grant stage B registered), 406–436 (grant_deq_q, ej scan),
  438–486 (starvation state FF), 486–570 (output stages, HOLD), 572–625 (ejection, S4/R6 fixes),
  626–702 (demotion, R6 `if (0 &&` at 686), 703–751 (enqueue, S3b/S3c).
- `tracks/t3-topology/rtl/mot_htree/noc_pkg.sv` — stale static package (no CLASS_W);
  `tracks/t3-topology/scripts/rtlgen/noc_pkg.sv` and `gen_rtl_htree.py:emit_pkg` — generated package.
- `tracks/t3-topology/dse/veritx_dse/product/project_top_rtl.py` — `INIT_SLICE_TEMPLATE` 1510;
  `_widened_slice_template` 1540; `_render_destination_adapter_*` 1233/1352/1497; `render_project_top`
  1621; `_UNIFIED_ROUTER_TEMPLATE` 4991; `_render_family_pkg` 4942; `_render_family_router` 4994;
  `_render_family_noc_top` 5085 (router instantiation 5256–5277); `_render_family_destination` 5279
  (SRAM + `init_w` latch + `rsp_flit[dst]=src_q` ≈ 5386–5396); `_render_family_initiator_template`
  5496 (flit build ≈ 5649–5667, SINGLE type, `INIT_ROUTER` src); `_render_family_project_top` 5845
  (memory-router special case lines 5930–5933; per-slice `.noc_in_flit` line 5964; `u_noc`
  instantiation lines 5978–5990); `render_family_tb` 6028; `_require_single_endpoint_per_router` 6367,
  call at 6389; `UNSUPPORTED_COMPOSED_FAMILY` 4114; `_refuse_family` 4125;
  `_require…` refusal text lines 6372–6376; `_eligible_routers` 4470; family binding
  `composed_family_params_from_request` 4571 (attachment seat order), `_require…` seats tuple 4772–4780.
- `tracks/t3-topology/dse/veritx_dse/model/topology_artifact.py` — `fat_tree_graph` 1037;
  `materialize_*` seats: cmesh/mesh concentration 630–720 (seat_capacity=concentration, line 661);
  fat-tree seat_capacity=radix 1617–1619; STRUCTURED_FAMILIES fat_tree seat_capacity 1200–1216;
  mesh concentration proof comment 517–535.
- `tracks/t3-topology/dse/veritx_dse/model/attachment.py` — canonical seat order, `seats = [(r,s) for
  r in routers for s in range(cap)]` (derive_attachment, ≈ 433–470).
- `tracks/t3-topology/dse/veritx_dse/model/indirect_tree.py` — qtree leaf-only seats (level==levels−1);
  `tree4_net.py` — tree4 leaf seats K; `fly_net.py:275–276` — fly stage-0 ingress seats K / last-stage
  egress seats K.
- `tracks/t3-topology/dse/tests/test_project_top_slice.py` — refusal tests 283–306, 357–380; family
  request agents 240–266; `_family_request` 240.
- `tracks/t3-topology/dse/tests/test_family_bad_design.py` — 54-test refusal/binding ledger
  (INTENT-TO-PLACED-RTL-P0-P1-STATUS.md:632).
- `docs/product/SEQUENTIAL-GATES.md:25,31–33`; `docs/product/P2-P3-EVIDENCE-20261110.md:31,34`;
  `docs/product/INTENT-TO-PLACED-RTL-20261110-AUDIT.md:106`; `docs/product/INTENT-TO-PLACED-RTL-P0-P1-STATUS.md:187,632,634`.

---

## MEASURED — 2026-11-10 (main session): the arbiter + response demux exists and is proven

Built as standalone, product-packaged RTL with its own testbench, while the shared emitter was under another session's edit:

| Artifact | Path | Status |
|---|---|---|
| Arbiter + per-seat response demux | `tracks/t3-topology/rtl/multi_seat/seat_concentrator.sv` | lints clean (Verilator 5.032, `-Wall`), **simulated PASS** |
| Testbench | `tracks/t3-topology/rtl/multi_seat/tb_seat_concentrator.sv` | 5 scenarios, all PASS |
| Gate test | `tracks/t3-topology/dse/tests/test_seat_concentrator.py` | **3/3 passed** (lint clean + behaviour + packaging) |

Proven behaviours (verbatim from the sim log):

```
PASS: S1 round-robin fairness over 2 seats, 8 grants, skew <= 1
PASS: S2 conservation: seat0 sent 4 recv 4, seat1 sent 4 recv 4
PASS: S3 multi-flit packet HEAD/BODY/TAIL kept the wire (no interleaving)
PASS: S4 per-seat response routing: every beat returned to its own seat
PASS: S5 no protocol error
status: PASS
```

Design decisions and their honest cost:

- **One outstanding beat across the concentrator.** The composed fabric returns one response per beat and carries **no seat tag**, so a response can only be attributed if at most one beat is outstanding. The concentrator therefore serialises the shared wire: a seat's next beat is offered only after its previous response. This does not slow an individual seat (the slice already issues one beat at a time and waits), but it does serialise several seats that could otherwise have beats in flight together. **Per-seat pipelining would need a seat tag in the flit** — a fabric-format change, not an RTL-only change.
- **Strict round-robin between seats**, so a backlogged seat waits at most N_SEATS−1 grants (fairness asserted: skew ≤ 1 with both seats backlogged).
- **Packet atomicity**: a HEAD..BODY..TAIL packet keeps the wire; another seat cannot interleave (asserted).
- **Response demux** routes the fabric response to the owning seat and rejects a response that no seat owns (no seat has ready asserted outside S_WAIT_RSP).

What is still missing to close the multi-seat families: the **wiring** — the composed emitter must place this module between the per-seat slices and the router local port (the per-endpoint slice instantiation is specified separately in `multi-instance-emitter-patch.md`), and the family TB must drive N seats. Until that lands, the five multi-seat families keep their typed refusal; this artefact removes the *primitive* gap, not the *integration* gap.

---

## Integration conflict — two concentrator designs, one file (2026-11-10, recorded for whoever picks this up)

The composed-family path has **two independent multi-seat implementations** in flight, and they are **not compatible**:

| | Tagless concentrator (main session) | Endpoint-tagged concentrator (parallel session) |
|---|---|---|
| Artifact | `tracks/t3-topology/rtl/multi_seat/seat_concentrator.sv` (+ `veritx_dse/product/seat_concentrator_rtl.py`) | `veritx_dse/product/cmesh_rtl.py` (`cmesh_concentrator`, `render_cmesh_attachment`) |
| Response attribution | by **ownership**: one outstanding beat at a time, the reply goes to the seat that owns it | by **destination field**: the reply's dst must equal the seat's endpoint id (`ENDPOINT_IDS`) |
| Addressing it needs | router-addressed flits (dst/src = router ids) — matches the family router's router-indexed routing tables | endpoint-addressed flits (dst/src = endpoint ids) — the router's tables are **router-indexed**, so an endpoint-id dst does not resolve |
| Proven | standalone: 5 scenarios PASS, gate test 3/3; co-seated **initiator-only** design lints+sims PASS 13/13 | not proven end-to-end: on the return path the reply carries the *destination* endpoint id, which matches no seat on the *source* router, so the reply is dropped and the router stalls |
| Cost | serialises seats (one beat in flight across the concentrator); per-seat pipelining needs a seat tag in a reserved flit field | allows per-seat overlap, but needs the seat id to ride in the flit and the router tables to accept endpoint ids |

**Why this matters for the composed path:** the family router's routing tables are built over `params.n_routers` (router-indexed). Any design that puts an *endpoint* id in the dst/src fields needs those tables re-indexed by endpoint — a fabric-format change, not a wiring change, and the single decision that unblocks the tag-based concentrator.

**State after the main session's unification (2026-11-10 ~19:0x):** the composed family path emits the **tagless** concentrator (`seat_concentrator.sv`), the seat nets are named `seat_<endpoint>_noc_{in,out}_{flit,valid,ready}`, the flits stay **router-addressed**, and the family path writes `seat_concentrator.sv` into the build and adds it to the Verilator file list. The parallel session's `cmesh_concentrator` module and `render_cmesh_attachment` remain in the tree as **unused** code — deliberately not deleted (it belongs to another session) but also not wired, so exactly one wiring reaches the emitted top.

**Named remaining work for the co-seated families (fly, qtree, tree4, fattree):** they still refuse, because only `concentrated_mesh` has a wired concentrator today. The wiring is family-agnostic (per-router instance, per-seat nets), so extending it means allowing co-seating for those families in `CONCENTRATOR_FAMILIES` — but each family's own seat law (fly's injection/ejection split, qtree/tree4 depth, fattree level count) must be re-verified with the concentrator in place before its refusal is lifted. **Do not lift a refusal on the strength of the wiring alone.**

### Incident — 2026-11-10 ~19:0x–19:4x (main session): the shared emitter file was damaged and rebuilt

Honest record, because the file is untracked and has no git baseline:

- While reconciling the two concentrator designs in `veritx_dse/product/project_top_rtl.py` (a file another session was editing concurrently), a scripted "remove the empty `if` branch" repair of mine matched **Verilog template text** as well as Python — it deleted **45 chunks** (101 lines) across the shared/srota/hybrid/mesh fabric templates, and separately deleted two Python `if` guards in the slice path.
- Recovery: the file was rebuilt mechanically as *snapshot (18:26) + only the intended inserts/replaces*, restoring all 101 deleted lines and leaving the multi-instance, seat-planner and concentrator-wiring changes in place. The rebuilt file parses and the affected suites re-run green (composed families 11/11, composed slice lock, multi-instance/concentrator regression files 17/17, co-seated concentrator case PASS).
- **Consequence to state plainly:** the parallel session's edits to *that one file* between 18:26 and the rebuild were reverted (their `cmesh_concentrator` wiring of 19:0x–19:3x). Their work in other files (topology artifact, tests, the `cmesh_rtl.py` module itself) is untouched. The `cmesh_rtl.py` module and `render_cmesh_attachment` are still present in the tree, unwired by the composed family path.
- **Lesson recorded for the next session:** never run a text-transform script over a file that another session may be editing, and never over Verilog embedded in Python strings; verify with `ast.parse` *and* a diff against a snapshot before writing.
