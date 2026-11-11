# Shared fabric on the project's real seats, and the selected-project emit — 2026-11-11

This records one session's work on the selected 74-agent project
(`p-fd7e5e31be77-r02`). It complements
`docs/reports/FINAL-IMPLEMENTATION-HANDOFF-20261111.md`, which covers the
composed-family scope; that document and this one were written against the
same tree and both are current.

## 1. The selected project's fabric now runs on its own agent seats

**Before**, the shared GEC-MECS fabric treated its **routers** as the traffic
endpoints: the generated testbench drove every ordered *router* pair. The
project's 74 declared agent seats were not the endpoints of any run.

**Now**, the shared fabric can run on the project's real seats, and it has
been measured on them at the pinned shape:

```
PASS gec_mecs16 routers=81 shared_wires=162 taps_per_wire=8
     all_pairs=5476 accepted=5476 delivered=5476 stall_cycles=12 drained=1
PASS gec_mecs16 routing: local=74 same_row=578 same_col=536 row_then_col=4288
PASS gec_mecs16 credit_accounting: capacity bounded, alias-free, drained
PASS gec_mecs16 simultaneous_row_returns: both tap credits restored
status: PASS
```

`all_pairs=5476` is 74x74 — every ordered pair of the project's **agent
seats**, not the 6,561 router pairs. `local=74` is one local delivery per
seat. Lint PASS, sim PASS, all nine scenarios true, at 81 routers / 162
shared wires / 8 taps / 8 VCs / 128 bits. The same request without
`endpoint_seats` still runs the router pairs (lint PASS, sim PASS), so the
seat mode is additive rather than a replacement.

Evidence: `runs/selected-r02-seats-20261111/` — both modes' SystemVerilog, the
credit pool, every lint/build/sim log, and a manifest with per-file digests
and the explicit list of what the run does and does not prove.

- `run_gec_mecs_shared(request, out, {"repo_root": ..., "endpoint_seats": True})`
  derives the seat map from the compiled bundle's attachment: endpoint id ->
  owning router.
- The fabric carries **endpoint ids on the wire** and decodes them to routers
  (`route_destination`), so the packets the run injects name agents, not
  routers.
- The generated testbench drives every ordered **endpoint** pair and reports
  the routing split over the seats' routers.
- The seat map is **refused** when two seats share a router: the fabric has
  one local port per router and could not deliver both. It is refused rather
  than collapsed.
- The seat map is also **refused on the pinned historical 4x4 shape**
  `(k=4, c=1, o=1, d=3)`. That shape keeps its pinned testbench, which drives
  router pairs, so asking for seats there would silently run the wrong
  traffic. A scalable shape is required for seat mode.
- The **router mode is unchanged** — the same request without `endpoint_seats`
  still drives every ordered router pair, and the emitted artifact is the
  same as before apart from the seat map.

Tests: `tracks/t3-topology/dse/tests/test_gec_mecs_endpoint_seats.py` pins
the derivation, the refusal, the decode and the run.

## 2. Two real bugs found on the way

### 2.1 The shared path emitted a fabric that referenced a module it did not provide

`run_gec_mecs_shared` wrote `gec_mecs16_fabric.sv` and the testbench, but the
proven credit pool travels in its own file (`tap_credit_pool.sv`, one module
per file, as the composed family path emits it) and the shared path neither
wrote nor compiled it. Verilator refused the artifact:

```
%Error: gec_mecs16_fabric.sv:272:3: Cannot find file containing module: 'tap_credit_pool'
```

**Fixed**: the shared path now writes `tap_credit_pool.sv` and puts it in the
lint, build and simulation file lists, so it is listed in the manifest
(`files`) and in the archive like the other slice files.

`tests/test_gec_mecs_scaled.py` assumed the pool was inlined into the fabric
file and linted the fabric alone, so it failed with the same
`Cannot find file containing module` once the pool moved to its own file. It
now writes and lints the pool alongside, matching the composed family path
(`build_family_router`), which has always emitted the pool as its own file.

### 2.2 The shared testbench had a multi-driver race on the captured delivery

`last_dst`, `last_src` and `last_flit` were written by **both** the delivery
monitor and the `send_pair` task, which reset them to `-1` before each pair.
When the monitor's write and the task's reset landed in the wrong order, the
task saw `-1` and the run failed with

```
%Fatal: tb_gec_mecs16_fabric.send_pair: wrong destination: expected 0 got -1
```

even though the fabric had delivered the correct flit — the router's own
output was `0028feb86659fd93` while the testbench latched zero. The reset is
unnecessary, because the wait loop already detects "no delivery"; the monitor
is now the **only** writer. This was a testbench defect, not a fabric
defect, and it is fixed at the source rather than worked around with
simulator flags.

## 3. The selected-project emit: root cause found and measured

The 81-router Chisel credit preview OOMed (attempt 4: Java heap OOM after
1,634 s at `-Xmx6G`). The cause is **structural**, so a bigger heap cannot
reach it.

**The route interface was `lanes x slots` wide.** The credit router carried
its route table as a one-hot legal mask over every slot, plus a per-slot tag
vector, **per lane**. At the selected shape that is 2,966,784 bits across the
router boundary and 2,998,768 FIRRTL reduction nodes — about **8.5x** the
36-router baseline that does elaborate.

**The cost driver is the FIRRTL IR, not the Verilog.** For the 36-router
baseline the emitted IR is **302.8 MB of text in 2,174,947 statements** while
the Verilog beside it is 25.6 MB. 70.5 % of statements are primitive `node`
operations, so the cost is node count, and every statement carries a
source-location annotation. By module family: `CreditRouter` x36 = 54.4 %,
`CreditMatch` x72 = 33.6 %, `Queue` x3952 = 5.7 %.

**Measured thresholds on this host at `-Xmx3G`:** 36 routers emits (spending
85-90 % of its time in GC), **49 routers OOMs**, 81 routers needs > 6 GiB.

### Changes made (ChiselTest suite 24/24 after each)

1. **Route interface compaction.** The route is now a **slot index + `valid`
   + tag** instead of a one-hot mask plus a per-slot tag vector. The compiled
   contract resolves every destination to exactly one slot per VC, so this is
   the same information in 10 bits per lane rather than 256. The route
   interface drops to 97,744 bits and the reduction nodes to 374,846.
2. **Reduction refactor.** The three `lanes x slots` loops (credit
   reservation, stage reservation, output selection) reduce over **input
   ports** instead of lanes, because only the VC the allocator picked for an
   input port can hold a grant. `CreditRouter`'s IR fell from 169.5 MB to
   90.2 MB per 36 routers (**-47 %**).
3. **`CreditMatch` hoisting.** The "already used" factors depend on the input
   or the output, not on the pair, so they are hoisted out of the pair loop.

Together the IR fell from 302.8 MB / 2,174,947 statements to **225.2 MB /
1,681,527 statements (-27.7 %)**, the 36-router emit time fell from 171 s to
**116 s**, and the 36-router credit preview now emits at `-Xmx3G`, where the
historical baseline needed a 6-GiB heap.

Measured per family, 36 routers:

| family | before | after | change |
|---|---|---|---|
| `CreditRouter` x36 | 169.5 MB (54.4 %) | 90.2 MB (40.0 %) | **-47 %** |
| `CreditMatch` x72 | 104.6 MB (33.6 %) | 97.8 MB (43.4 %) | -6.5 % |
| `Queue` x3952 | 17.7 MB | 17.7 MB | unchanged |
| total IR | 311.4 MB | 225.2 MB | **-27.7 %** |

**This does not close the 81-router emit.** `CreditRouter` halved, but
`CreditMatch` is now the largest single term and its cost is
`O(inputs x outputs)` pairs — that is the matching structure, not a mistake
in it. Scaling the measured node count to the selected shape gives about
**8.8 M statements** (from 11.4 M), which on this host still needs on the
order of 15 GiB against a 14 GB machine. Raising the heap is not available
here and would not scale anyway.

**The path that would close it is hierarchical emission, not more
micro-optimisation:** emit the parameterised `CreditRouter` module once and
generate the 81-instance top-level wiring as Verilog text. That puts one
router's IR (about 90.2 MB / 36 = 2.5 MB) plus the top's wiring into FIRRTL
instead of 81 expanded router bodies, and the top's wires carry no logic
beyond the route decode. This is a change to the emitter, not to the router.

**The emitted artifact is deliberately no longer byte-identical** to the
historical 36-router one (Verilog 28,640,272 -> 25,309,728 bytes). The
reason is recorded rather than hidden.

## 4. Scope C4 — multi-flit framing and per-VC allocation, now established

The claim list said the VC dimension was already established and only the
**packet framing** was missing. Both are now in place:

- **The framing lives in the shared fabric template itself** — the two-bit
  **type** field (HEAD / BODY / TAIL / SINGLE) sits directly below the VC
  field, so the destination and VC offsets — and the C5 credit evidence — are
  unchanged. `flit_is_head` / `flit_is_tail` and the **per-output packet
  locks** are template code, with their resets.
- **A router allocates the virtual channel itself at injection.** The
  producer's VC field is not trusted: a HEAD or SINGLE takes the router's next
  round-robin VC, and BODY/TAIL inherit the packet VC pinned at the HEAD.
  A BODY/TAIL with no packet open is counted as an error and burns no
  rotation slot.
- **A per-output packet lock** is taken when a HEAD is sent and released when
  a TAIL is sent, so only the port that owns the packet may be granted that
  output. A SINGLE takes and releases it in one cycle, and the lock clears on
  reset.
- **The generated testbench proves all three**: a three-flit HEAD/BODY/TAIL
  packet is reassembled **in order**; **two packets contending for one
  destination** are counted by source switches at the destination — a locked
  fabric switches **exactly once**, an unlocked one interleaves; and a
  **reset in mid-packet** leaves every output idle with no stuck lock and the
  fabric carries a new transfer afterwards. Flits in flight at the reset are
  discarded by design, so conservation is not asserted across the reset —
  only recovery.

Measured, both modes, at a 25-router / 50-wire / 4-tap / 4-VC shape:

```
PASS gec_mecs16 multi_flit: flits=3 packets=1 ordered=1
PASS gec_mecs16 multi_flit_contention: delivered=6 source_switches=1
PASS gec_mecs16 reset_recovery: outputs idle after reset, post-reset transfer delivered
```

And at the selected shape, on the project's 74 seats:

```
PASS gec_mecs16 routers=81 shared_wires=162 taps_per_wire=8
     all_pairs=5476 accepted=5476 delivered=5476 stall_cycles=12 drained=1
PASS gec_mecs16 routing: local=74 same_row=578 same_col=536 row_then_col=4288
PASS gec_mecs16 credit_accounting: capacity bounded, alias-free, drained
PASS gec_mecs16 simultaneous_row_returns: both tap credits restored
PASS gec_mecs16 multi_flit: flits=3 packets=1 ordered=1
PASS gec_mecs16 multi_flit_contention: delivered=6 source_switches=1
status: PASS
```

The 81-router run above predates the reset check, so its manifest does not
claim `reset_recovery`; the scenario is computed from each artifact's own log,
so an artifact only ever claims what it ran.

**The honest limit, stated in the claim list:** the wire still delivers one
flit per wire per cycle, so this is **per-hop packet locking, not wormhole
interleaving across virtual channels**. Framing, ordering, contention
serialisation, per-VC allocation and reset recovery are established;
cross-VC wormhole sharing on a pipelined wire is not.

## 5. Scope C6 — physical, and why no code change can close it

C6 is **not a code gap**. The operator has already recorded a scope-out
decision (`docs/product/evidence/physical-scope-out.json`, 2026-11-11, scope
`COMPOSED_FAMILY`) and the code **consumes** it:
`project_top_rtl._physical_scope_out_decision()` reads the file,
`scope_evidence` applies it, and `final_implementation.SCOPEOUT_ELIGIBLE`
includes `A11`, `A12` and `C6`. So for the composed-family claim those rows
are SCOPED_OUT rather than silently open.

What remains is genuinely operator-owned: a PDK, a declared clock, die/core
bounds and a pinout (`docs/product/PDK-DECISION-REQUIRED.md`). Until those
exist, no physical signoff is claimed for the selected project either, and
the shared-fabric manifest names that limit explicitly.

## 6. New tools

- `tracks/t3-topology/dse/veritx_dse/product/gec_rtl_cost.py` — a cost model
  for the router shape **and** `measure_firrtl()`, which reads a real emitted
  IR and reports the per-family cost. This is how the diagnosis above was
  produced; it is a tool, not a claim.
  Tests: `tests/test_gec_rtl_cost.py` — 7 passed.
- `scripts/check_chipyard_gec_credit_preview.sh` — makes the credit-preview
  emit reproducible in-repo, with the heap cap and the emitted size and
  digest reported.

## 5. What is still open

- **The 81-router Chisel credit preview still does not emit.** The remaining
  terms are the `lanes x slots` reductions inside `CreditRouter` and
  `CreditMatch`. Neither is a heap problem; both are structural.
- **Scope C4** — **closed on this wire model** (section 4): framing,
  ordering, per-VC allocation, contention serialisation and reset recovery
  are measured, with cross-VC wormhole sharing on a pipelined wire stated as
  the remaining limit rather than claimed.
- **Scope C5** — the end-to-end run of the selected contract with
  conservation, credit and reset accounting over the 74 seats. The seats are
  now the traffic endpoints of the shared-fabric run; the accounting rows are
  not yet proven over them.
- **Scope C6** — physical signoff. Operator-scoped: PDK, clock, die bounds,
  pins.
- The Chisel credit router's own multi-flit and iSLIP machinery is what C4
  needs, so closing the 81-router emit is also the path to C4.
- `final_implementation` stays `false` on every artifact this session
  touched.
