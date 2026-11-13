# Scope B — multicast on the composed shared-wire fabrics

Date: 2026-11-12
Scope: `COMPOSED_SROTA` and `COMPOSED_GEC_HYBRID` (16 routers), product path
`run_srota_shared` / `run_hybrid_shared`

## What changed

The two composed shared-wire fabrics carried a decoded unicast index only.
Scope B's multicast row required header and bitmap semantics. The current
source carries them:

- **Widened packet, payload kept.** `W` is 80 bits for the composed tops:
  `dest[79:76] src[75:72] type[71:70] bitmap[69:54] payload[53:0]`. The
  16-bit bitmap is one bit per router id (`K*K`). Payload bit positions are
  unchanged from the 64-bit layout; only dest/src/type moved up. The
  manifests record `emitted_packet_width_bits: 80` and
  `emitted_mcast_bitmap_bits: 16`.
- **Bitmap semantics (native primitive rule).** A zero bitmap is the
  historical decoded unicast, unchanged. A nonzero bitmap selects exactly
  its set bits. A flit driven onto a shared wire is seen by every tap of
  that wire; each selected tap drops one copy in the same slot, and
  unselected taps neither drop nor gate the slot.
- **All-or-nothing admission.** Every selected tap must be free before the
  wire is driven (SROTA: the elastic pipe exit ANDs the selected taps'
  readiness; GEC-hybrid: the router additionally requires every selected
  MECS tap's occupancy bit to be clear). A busy selected tap stalls the
  whole wire copy; no partial delivery is possible.
- **Cross-row/column fork.** Row-first: the source drives the row wire for
  every selected column on that side (whatever the destination's row); each
  tap whose column holds a selected bit drops its own copy and turns the
  column bits onto its column wire; the column wire broadcasts to its
  selected taps. The source also forks directly onto the column wire for
  bits in its own column. A flit stays in its input register until every
  target output has taken its copy (`fork_done` per input port and output);
  copies on different wires therefore take different slots, by construction.
  Copies are acquired in a fixed output order (local, then xneg/xpos, then
  yneg/ypos; hybrid: local, row, col), so two forked packets cannot each hold
  one output the other needs — a real lock cycle that a naive fork admits
  (a source injection and a turn packet can both target yneg and ypos).
- **GEC-hybrid policy.** Multicast is a shared-wire capability: it never
  takes a mesh channel. The fabric asserts that no mesh wire carries a
  bitmap flit. The UGAL mesh/MECS selector remains a unicast property.
- **SROTA class limit, refused not silent.** SROTA's island column is
  column-first. A bitmap containing an island-column bit is refused at
  injection, consumed, and counted (`mcast_refused`); it is never silently
  routed row-first. Mixed-class multicast is therefore not representable.

## Bugs found while integrating

1. **Row-wire direction keyed on the wrong set.** The first version asked
   "is there a selected bit in my row on that side?", which is right for a
   same-row multicast and wrong for every cross-row destination: the wire
   is needed toward the destination's *column*, whatever its row. The
   measured symptom was one local copy and no column forks. Fixed by
   keying the row-wire grant on column position.
2. **The hybrid's `*_credit` inputs are occupancy, not availability.** The
   hybrid model exposes `row_credit0..2`/`col_credit0..2` as 1 when the
   corresponding tap port holds a flit (the UGAL cost law consumes them as
   pressure). The multicast admission initially required those bits to be
   1, so every row copy was withheld at idle. It now requires the selected
   taps to be free, indexed by the tap's position in the row/column (not by
   the wire-tap index `row_tap()`).
3. **Testbench capture, not fabric.** A multicast copy's valid pulse can
   share its retirement edge with another fork of the same flit; negedge
   polling missed exactly those copies (measured: row set `{4,6,7}`
   delivered only `{6,7}`, then only `{4}` after the local copy retired
   first). The multicast capture is armed before injection and samples the
   handshake at the clock edge, the same correction the GEC-MECS contention
   TB needed.
4. **Fork lock order.** A naive fork takes each output lock as that output
   becomes ready. Two forked packets at one SROTA router (a source injection
   and a row-tap turn, both targeting yneg and ypos) can then hold one column
   output each and wait for the other. Copies are now acquired in a fixed
   output order (local, xneg, xpos, yneg, ypos; hybrid local, row, col), so
   the intra-router lock order is global and acyclic. This is an ordering
   argument, not a liveness proof: cross-router wire dependency cycles and
   formal starvation-freedom remain unestablished (recorded in the limits).
5. **Adjacent, pre-existing red.** Three renderer tests asserted that
   emitted RTL contains no `//`. The committed emitters deliberately carry
   explanatory comments (policy DEB-7 keeps comments), so the assertion was
   already false at HEAD. The stale assertion is removed; determinism is
   still checked.

## Verification (measured)

`tests/test_project_top_shared.py` — **16 passed**, including:

- SROTA `PASS srota_composed ... all_pairs=256 accepted=256 delivered=256
  stall_cycles=6 row_first=108 island=36 drop=384 multicast_flits=8
  multicast_copies=20 multicast_refused=2 drained=1`.
- Hybrid `PASS gec_hybrid16 ... all_pairs=256 accepted=260 delivered=260
  stall_cycles=18 mesh=1 mecs=387 drop=387 tie=387 multicast_flits=8
  multicast_copies=20 drained=1`.

Multicast scenarios (both fabrics): row `{4,6,7}` from 4 and from 6
(west+east fork), cross-row/col `{0,6,10,15}` from 0, column broadcast
`{4,8,12}`, one-tap header `{15}`, and a forked `HEAD/BODY/TAIL` packet to
`{0,15}`. Every copy is checked for payload, membership and uniqueness; 20
copies for 8 injected flits. SROTA additionally refuses two island-class
bitmaps and checks the counter. Hybrid's mesh assertion fired on no
multicast wire. Both fabrics lint with **0 warnings** and the unicast /
multi-flit / island / selector regressions are unchanged.

Manifest rows: the multicast criterion moved from
`*_SHARED_NOT_ESTABLISHED` to `*_SHARED_PROVEN`; the remaining limits are
recorded as `SROTA_MULTICAST_LIMITS` / `GEC_HYBRID_MULTICAST_LIMITS`. Both
scopes still report `final_implementation: false` because AXI/OrderingFSM/CDC
composition, the physical multidrop and STA/parity remain open.

## Honest limits

- Row-first only. SROTA island-class bits are refused (and counted), not
  routed. Hybrid multicast is MECS-only; the mesh is unicast-only.
- One wire slot per (source, wire) still delivers one flit per cycle. A
  multicast copies per wire, not per destination in one slot across wires.
- The hybrid's per-tap VC class is a unicast property; a multicast packet
  spanning classes shares the lowest selected tap's class on the row/col
  wire.
- Physical electrical multidrop, STA, formal deadlock/liveness and
  cycle-accurate BookSim parity remain not established. Statement
  starvation-freedom under adversarial traffic is not claimed.
- This closes the multicast row of the two Scope B claim lists only. It is
  not a product-level "hardware multicast supported" claim: the product
  intent registry still treats hardware multicast as NOT REPRESENTED.
