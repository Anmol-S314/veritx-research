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
  takes one VC from a per-router round-robin rotation at its HEAD/SINGLE; the
  same VC is stamped on every BODY/TAIL until the TAIL retires it. BODY/TAIL
  with no packet open increment `inject_error_q` and burn no rotation slot.
- **Pipelined wire model.** Each `(src, axis)` wire is a `WIRE_PIPE`-deep
  elastic valid/flit pipe (default 2), not a combinational net. Stage 0 fills
  from the router grant, stages shift when the next stage accepts, and the
  last stage exits into the addressed tap. Credits are claimed when a flit
  enters stage 0 and released at destination dequeue.

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

## Verification

- `tests/test_gec_mecs_scaled.py`: **5 passed**, including 3×3 and 6×6
  lint/simulation and the pinned full-size lint. The TB asserts
  `PASS gec_mecs16 multi_flit` (HEAD/BODY/TAIL ordered, one packet).
- `tests/test_gec_mecs_selected_seats.py`: the selected r02 contract derives
  74 endpoints on 74 unique routers (81 routers, 162 wires, 8 taps, 8 VCs,
  128-bit flits).
- Selected 74-seat campaign: `run_gec_mecs_shared` with
  `endpoint_seats=True`; results recorded under
  `runs/selected-r02-gec-mecs-seats-c4-20261112/` when the run completes.

## Honest limits

- VC allocation is round-robin per source router: fair per VC but it does not
  consult downstream pool state. It is **not iSLIP** and not starvation-free
  under adversarial traffic.
- The wire pipe is a fixed-depth elastic pipe; it is not a full wormhole
  network with arbitrary per-VC interleaving. The per-output packet lock holds
  one packet per wire at a time.
- Multicast, AXI/OrderingFSM/CDC composition, physical multidrop, STA, formal
  deadlock and cycle-accurate BookSim parity remain separate obligations.
- Physical signoff (C6/P9) remains operator-owned.
