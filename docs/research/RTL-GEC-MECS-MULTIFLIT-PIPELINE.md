# GEC-MECS shared fabric — multi-flit framing and pipelined wire

Date: 2026-11-12
Scope: the selected r02 fabric (`ab7bce8f…`), product path
`run_gec_mecs_shared`

## What changed

The shared fabric was single-flit: every transfer was one flit, the wire was
combinational, and the producer's VC field was trusted. C4 required packet
framing, per-VC allocation and a credit pipeline. The current source has:

- **Packet framing.** A 2-bit `flit_type` sits below the VC field:
  `payload | type | vc | src | dest`. `HEAD/BODY/TAIL` are carried in order;
  `SINGLE` is one-flit. The router's `flit_is_head`/`flit_is_tail` and the
  per-output packet lock stop two packets interleaving on one wire.
- **Injection-side VC allocation.** The producer's VC is not trusted. A packet
  takes one VC at its HEAD/SINGLE; the same VC is stamped on every BODY/TAIL
  until the TAIL retires it. BODY/TAIL with no packet open increment
  `inject_error_q` and burn no rotation slot.
- **Pipelined wire model.** Each `(src, axis)` wire is a `WIRE_PIPE`-deep
  elastic valid/flit pipe (default 2), not a combinational net. Stage 0 fills
  from the router grant, stages shift when the next stage accepts, and the
  last stage exits into the addressed tap. Credits are claimed when a flit
  enters stage 0 and released at destination dequeue.
- **Per-VC packet locks (limits follow-up, 2026-11-12).** The packet lock on
  every output (local/row/col) is indexed by the packet's VC, not exclusive
  per output. Two packets on different VCs may hold one output concurrently.
  Same-VC HEAD→TAIL ordering is unchanged; a packet still cannot overtake
  another on one wire. Measured: two contending packets delivered interleaved
  on VC3/VC1 (source switched 3 times, per-source order preserved); two
  packets on the same VC still serialize (source switched exactly once).
- **Credit-aware injection admission (limits follow-up, 2026-11-12).** The VC
  for a HEAD/SINGLE is the round-robin-earliest VC whose *first-hop*
  (tap, VC) pool still holds a credit (each router exports a per-(tap, VC)
  zero test; local/no-wire packets keep the plain rotation). A packet whose
  first-hop pools are all exhausted is **not admitted** — the endpoint holds
  `valid`, the fabric withholds `ready`, no rotation slot burns — instead of
  injecting a packet that cannot move. A HEAD/SINGLE addressed outside the
  router range is consumed at the port and counted in `inject_error_q`
  instead of wedging a router port forever.

## Two real bugs fixed during integration

1. **Stage 0 was not elastic.** It was written as
   `pipe_v[0] <= valid && stage_ready`, which clears the occupant on every
   stalled cycle. It now holds when the next stage cannot accept.
2. **The pipe driver compared the final destination to the tap.** A row hop to
   an intermediate router never fired (`pd == dst` where `pd` is the final
   endpoint), so multi-hop routes timed out. The driver now derives the
   intermediate same-row/same-column router from the final destination and the
   source coordinate.

The transform also had to pass `.WIRE_PIPE(WIRE_PIPE)` to the router (it was
still passing the removed `WIRE_LATENCY` parameter).

## Two more bugs found while working the honest limits

3. **The TB's oversubscribe scenario phantom-accepted flits.** It injected
   `CAPACITY + 2` same-destination flits while holding the destination
   stalled indefinitely; the path holds fewer flits than that (single-entry
   source port + two-stage pipe + single-entry tap port), so the injection
   wait simply timed out and the TB counted the un-admitted flits as
   `accepted` without ever delivering them — silent loss, no delivery check,
   and the conservation number was fiction. The scenario now fills the path
   until the fabric backpressures (measured at 6×6/5 VCs: stall after 3 fill
   flits), treats a missing stall as a failure, then releases the
   destination and asserts `delivered == accepted` for the whole scenario.
4. **The contention scenario polled after injecting.** Deliveries that landed
   mid-injection were invisible to the poll, so a BODY could be read as the
   first observed flit ("packet B order violated at flit 0") — a testbench
   capture artifact that was misread as a fabric VC-selection residual. The
   TB now arms a module-scope capture block before the first flit is
   injected; per-source HEAD/BODY/TAIL order and per-packet VC stability are
   checked for the whole scenario, and the same-VC case asserts exactly one
   source switch.

## Verification

- `tests/test_gec_mecs_scaled.py`: **6 passed** — 3×3 and 6×6 lint/simulation,
  the pinned full-size lint, and the new credit-admission test
  (`test_credit_admission_stalls_when_first_hop_pools_are_empty`).
  The TB asserts `PASS gec_mecs16 multi_flit` (HEAD/BODY/TAIL ordered, one
  packet) and `PASS gec_mecs16 multi_flit_contention` (both contended
  packets delivered; per-source order and VC stability either way; same VC
  ⇒ exactly one source switch).
- 6×6/5-VC simulation (current source): `all_pairs=1296 accepted=1296
  delivered=1296 stall_cycles=12 drained=1`, `row_then_col=900`,
  `PASS gec_mecs16 oversubscribe: backpressure after 3 fill flits, released,
  drained, delivered=1300 accepted=1300`,
  `PASS gec_mecs16 multi_flit_contention: delivered=6 source_switches=3
  vc_a=3 vc_b=1`.
- Credit admission (capacity 1, 3×3/2-VC): the scenario fills every first-hop
  (tap, VC) pool while the destination is stalled, the next flit is refused
  (`ep_in_ready` low), the destination is released, and the held flit drains
  with `inject_error_q` clear:
  `PASS gec_mecs16 credit_admission: pools exhausted, admission withheld,
  drained=3`.
- `tests/test_gec_mecs_selected_seats.py`: the selected r02 contract derives
  74 endpoints on 74 unique routers (81 routers, 162 wires, 8 taps, 8 VCs,
  128-bit flits).
- Selected 74-seat campaign: `run_gec_mecs_shared` with
  `endpoint_seats=True`. The first completed run
  (`runs/selected-r02-gec-mecs-seats-c4-20261112/`, lint 0 warnings, sim
  PASS, 12/12 scenarios, 5,476/5,476 flows, credits drained, design hash
  `ab7bce8f…`) was rendered from source **before** the credit-aware
  injection and per-VC locks landed, and carries the pre-change allocator —
  it does not qualify the current RTL. A re-run from the current source was
  started (`/home/datavex/veritx-tmp/selected-r02-seats-c4-final3-*`) but was
  interrupted mid-build (the operator's parallel session is re-qualifying
  the same composed top now). What does stand for the current source: the
  81-router fabric lints with **zero warnings**, and the same TB generator
  is green at the 6×6/5-tap shape, which exercises every scenario the seats
  run carries (routing, conservation, credit accounting, multiflit,
  contention, reset) at a smaller scale. Until the 74-seat re-run completes,
  do not quote "12/12 scenarios on the selected contract" for the current
  RTL.

## Honest limits

- VC allocation is round-robin per source router, **gated by first-hop pool
  state** (above). It is fair per VC and refuses to admit a packet with no
  first-hop credit, but it is **not iSLIP** (no two-phase grant/accept
  matching), it consults pools only on the first hop, and formal
  starvation-freedom under adversarial traffic is **not established** — only
  bounded outstanding state and eventual drain under the regression's
  traffic. A packet whose first-hop pools are full is withheld, not
  re-ordered; a packet can still block mid-path behind congestion.
- The wire pipe is a fixed-depth elastic pipe; it is not a full wormhole
  network. The per-output packet lock is now **per (output, VC)**: two
  different-VC packets may hold one output concurrently, but every wire
  still delivers one flit per cycle to one destination, the destination
  buffer is single-entry, and endpoint-side reassembly of interleaved
  packets is a consumer contract, not a modeled block. Arbitrary per-VC
  flit-level interleaving is permitted between VCs, not forced, and the
  order of grant/interleave depends on arbitration and pipe timing.
- Contention/reset are exercised at the **selected 8-tap envelope** and at
  the **6×6/5-tap shape** in the TB (gated on `taps_per_wire >= 3` in both
  the TB and the assertion; the 3×3/2-tap shape is a framing smoke only).
- The earlier "packet B order violated" report at 6×6 was a testbench capture
  bug, not a fabric residual: with the capture armed before injection the
  same shape delivers both contended packets with per-source order and
  stable per-packet VCs (`vc_a=3 vc_b=1`). The one qualification kept:
  **when both contended packets land on the same VC, they serialize** —
  which is the property the lock exists to provide, and the seats run
  measures exactly that (`source_switches=1`).
- Multicast, AXI/OrderingFSM/CDC composition, physical multidrop, STA, formal
  deadlock and cycle-accurate BookSim parity remain separate obligations.
- Physical signoff (C6/P9) remains operator-owned.
