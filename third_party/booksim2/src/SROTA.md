# Srota NoC in BookSim

A BookSim model of the Srota Plane D data plane: concentrated mesh with a
MECS express layer, O1TURN-XY routing, and an injection-time
telemetry-adaptive overlay.

Implements, at the level a network simulator can represent:

| Spec | rev | What is modeled |
|---|---|---|
| SSM-UARCH-TOPO-003 | 0.3 | Concentrated mesh, MECS express channels, island placement, drop latency |
| SSM-UARCH-ROUTE-001 | 0.3 | O1TURN-XY, three path shapes, FIU path selection, flow-epoch cache, Valiant |
| SSM-UARCH-VC-002 | 0.3 | Per-drop credit granularity (buffer model only — see Departures) |
| SSM-UARCH-TEL-004 | 0.3 | Plane T as bounded-staleness per-column/row load vectors |
| SSM-UARCH-PKT-008 | 0.3 | Header fields that routing consumes: dest, path_shape, valiant intermediate, flow_hash |

Source: [networks/srota.hpp](networks/srota.hpp) (design note and the full
spec mapping), [networks/srota.cpp](networks/srota.cpp).

---

## Quick start

```sh
cd third_party/booksim2/src
make -j$(nproc)

./booksim examples/srota_reference.config   # 16x16, c=4, all three shapes
./booksim examples/srota_rtr7.config        # the RT-R7 deadlock experiment
./booksim examples/srota_mecs_off.config    # MECS-off ablation baseline

python3 srota_validate.py                   # full validation suite
```

Every run prints its topology, its ROUTE_PATH_EN and VC policy, the result
of the F1 channel-dependency-graph check, and the result of the TP-V2
island-placement check, before any traffic moves.

---

## Three findings this model produced

### 1. RT-R7 is real, and the minimal cycle is four channels, not two

ROUTE-001 §4.5.4 asks for one specific run: the §4.4 model check on the
4×4 abstraction at `ROUTE_PATH_EN = 0b111`. That run is now
[`examples/srota_rtr7.config`](examples/srota_rtr7.config), and the check
happens at elaboration on every Srota run.

**The hazard is confirmed.** With both direct shapes enabled and no VC
separation, the channel dependency graph has a cycle:

```
router(0,0) X+  --[row-first]-->
router(1,0) Y+  --[column-first]-->
router(1,1) X-  --[row-first]-->
router(0,1) Y-  --[column-first]-->  (back to the first)
```

Of §4.5.4's three possible outcomes — "passes", "has not been run", "was
run with only row-first enabled" — the answer is none of them. The check
runs, at the shipping default, and finds a cycle. §4.3 is not incomplete;
it is wrong about the conclusion, exactly as rev 0.3's own correction note
suspected.

**But the shape of the cycle differs from §4.5.1's prediction.** That
section posits a *two-node* cycle, `row[0] → col[0] → row[0]`, and §4.5.4
says it "is a two-node cycle needing only two flows." On the actual MECS
structure it cannot be two nodes. A channel is a *driven segment* — one
driver, one direction (§7.2: "exactly one driver per segment per
direction"). A packet that drops off router (0,0)'s X+ channel at (1,0)
then drives router **(1,0)**'s Y+ channel, not router (0,0)'s. There is no
edge back to the first channel from two hops away, so the shortest cycle
closes only after going around all four corners of a 2×2 square: four
channels, four flows.

Consequence for §16.3's directed test: it specifies "one flow row-first
through row r into column c, one flow column-first through column c into
row r." **Two flows cannot reproduce this.** The directed pattern needs
four flows around a 2×2 router square, alternating shape. A two-flow test
would pass and be read as evidence the hazard is not real.

### 2. Row-first routing structurally violates I-ISL

TOPO-003 §7.3 wraps *every* router in an island column (`K × |island_cols|`
island-wrapped routers). ROUTE-001's row-first path turns at
`(dest_col, source_row)` — which is *inside the destination's island
column* — and then rides that column to the resource.

So a row-first route to any island-column resource passes through **two**
island routers whenever the source is not already in the destination's
row. That is §4.1.2's "two or more islands on a path": the second
regulator shapes traffic the first already shaped, the composed rate is
the product of the two bounds rather than the intended bound, and
bandwidth is lost with no error indication.

At the reference configuration (16×16, island columns 1 and 8) the model
reports **7,200 of 8,160** row-first (tile, resource) routes violating
I-ISL. Column-first violates only 480 — and those only because the
*source* sits in an island column, a residue that vanishes if island
columns host no ordinary tiles.

ROUTE-001 §13.1 already asserts that routing "must not admit a path that
violates I-ISL" but does not say what rule achieves that. This is the
concrete rule it needs: **island-bound traffic must use column-first**, or
islands must become a per-router property at the attach point rather than
a whole-column one. TP-V2 as specified would catch this at generation
time; it is worth running before the island map is frozen.

---

### 3. The injection-time overlay captures about half of what it is worth — and a fabric-wide constant does as well

ROUTE-001 §15 lists "reduced hot-column load under MoE skew" as
*simulation-pending (M1)*. It is now measurable, using
`tracks/t3-topology/scripts/moe_traffic.py` to build the §6.1 scenario
directly: Mixtral-8x7B expert-parallel all-to-all, Zipf expert popularity,
hot experts placed in one mesh column (27.9× destination-load imbalance).

k=16, c=4, `num_vcs=8`, `vc_policy=rank`. Mean packet latency, **stable
region only** — everything at rate ≥ 0.004 is past saturation and its
numbers mean nothing:

| rate | row-first | column-first | adaptive overlay | oneshape (§4.5.3 opt 1) |
|---|---|---|---|---|
| 0.0015 | 23.61 | **22.43** | 23.61 | 23.01 |
| 0.002 | 25.70 | **23.66** | 25.70 | 24.82 |
| 0.0025 | 29.99 | **25.73** | 29.49 | 27.60 |
| 0.003 | 38.85 | **31.35** | 34.78 | 34.50 |

Balanced all-to-all (skew=0) is the control: all four policies land within
0.02% of each other at every rate, as they should when no candidate is
hotter than another.

Three things follow.

**The overlay works, but under-delivers.** At low load it is byte-identical
to row-first (nothing is congested, so nothing switches — correct). As
congestion rises it does move toward column-first, but at rate 0.003 it
recovers only ~54% of the gap between the two fixed shapes (38.85 → 34.78,
where column-first reaches 31.35).

**Simply forcing column-first beats it everywhere.** Per-flow adaptivity is
*worse than a fabric-wide constant* here, because a per-flow decision is
greedy and local: whenever the overlay lets some flows keep row-first,
those flows ride the hot column for a whole segment and re-congest it for
everyone. The globally best policy on this pattern is "nobody rides the
hot column", which no per-flow rule reaches.

**That reframes §4.5.3's cost argument.** Option 1 (one shape per epoch,
fabric-wide) is dismissed there as losing per-flow diversity — presented as
a performance price paid to buy deadlock freedom. On this workload per-flow
diversity has *negative* value: `oneshape` matches or beats the adaptive
overlay at every rate (34.50 vs 34.78 at 0.003) while costing zero VCs and
resolving RT-R7 outright. Option 1 may be the right choice on performance
grounds alone, not merely the cheapest.

Caveat on scope: one workload, one placement, one fabric size. It does not
show the overlay is useless — it shows the overlay's value is not
established by the case the spec itself puts forward as its motivation, and
that the M1 claim should not be quoted until a pattern is found where
per-flow choice beats a constant.

### A spec ambiguity this surfaced: TEL-004 §2.2 does not define the aggregation

Getting the above to mean anything required fixing the telemetry model
twice, and both failures were silent — they disabled the overlay rather
than erroring.

TEL-004 §2.2 specifies a 4-bit "coarse buffer/queue occupancy" per router
and §4 a per-column "load vector over all routers in that column". Neither
says how to reduce many buffers to one nibble, or many nibbles to one
vector entry, and the choice decides whether the signal is usable at all:

- **Raw sum over input ports, clamped at 15** — reads 0 when idle and pins
  at 15 under any load. An interior router here has c + 2(k−1) = 34 inputs,
  so the sum passes 15 at under 1% utilisation. No threshold can
  discriminate.
- **Mean over input ports** — fails the other way. Most of a router's inputs
  are express taps that are idle at any instant, so the mean sits below any
  useful threshold even when the router is a real bottleneck.
- **Peak over input ports** (what this model now uses) — one saturated queue
  is a bottleneck regardless of how many idle taps sit beside it.

And at the line level, **max** is wrong for the same structural reason the
overlay needs to avoid: under a hot-destination pattern the hottest router
in the line is the packet's own destination, which *every* shape must
reach, so both candidates read "congested" for the same unavoidable reason
and the comparison carries no information. **Mean over the line** measures
the segment, which is the part the choice of shape can actually change.

§5.1's selection rule needs the same treatment. Read literally as two
independent threshold tests ("row-first when the destination column is
below thresh; column-first when the row-first candidate is congested and
the column path is not") it degenerates whenever both candidates fall on
the same side of the threshold — which is most of the time, because both
segments terminate at the same destination. This model uses the threshold
only to decide whether to escape to Valiant, and picks between the two
direct shapes by comparing their candidate loads. That is the reading
§5.1's own wording implies ("...is congested; the column path is not"), but
it is not what the text literally says, and the difference is the
difference between an overlay that fires and one that never does.

## The VC policy axis

Plane D carries no VC arrays (VC-002 §2.1), which is why §4.5.3 finds
every standard defence unavailable. `srota_vc_policy` selects the
mechanism so the candidate resolutions can be compared on identical
traffic:

| Policy | VC sets | Shapes it can carry | Corresponds to |
|---|---|---|---|
| `none` | 1 | row-first alone | spec-literal Plane D — the RT-R7 reproducer |
| `oneshape` | 1 | both direct, one per epoch | §4.5.3 option 1 |
| `shape` | 2 | both direct | §4.5.3 option 2 (O1TURN's own answer) |
| `rank` | 2, or 4 with Valiant | all three | *not in §4.5.3's table* |

Measured verdicts (static CDG check, 4×4 abstraction):

```
policy=none     path_en=1 -> acyclic     policy=rank     path_en=1 -> acyclic
policy=none     path_en=3 -> CYCLE       policy=rank     path_en=3 -> acyclic
policy=none     path_en=7 -> CYCLE       policy=rank     path_en=7 -> acyclic
policy=shape    path_en=3 -> acyclic     policy=oneshape path_en=3 -> acyclic
policy=shape    path_en=7 -> refused     policy=oneshape path_en=7 -> refused
```

**A note on `rank`, offered back to §4.5.3.** It splits VCs by hop rank —
leg-and-turn position, which increases strictly along every route — rather
than by dimension order. It is the only policy that keeps all three shapes
concurrently live and provably acyclic. §4.5.3's option table lists "two
VC sets on Plane D" and dismisses it as reversing VC-002's central
decision; splitting by rank costs the same 2 VCs for the direct shapes,
also covers Valiant (at 4), and does not care how many shapes are enabled.
It is still a VC mechanism, so it still reverses VC-002 §2.1 — the point
is narrower: if the architecture concedes VCs on Plane D at all, rank is
the cheaper way to spend them, and the cost comparison should say so
before option 1 is chosen on cost grounds.

Two further results worth recording, both enforced as config errors:

- **`shape` cannot carry Valiant.** A Valiant path turns twice (row→col
  reaching the intermediate, then col→row starting the second leg), so it
  contributes a column→row edge to the XY set and breaks the very
  separation the policy provides. "Valiant is internally row-first" makes
  it look safe; it is not.
- **`oneshape` cannot carry Valiant either**, for the same reason — Valiant
  closes a cycle on its own, so it cannot be the fabric-wide shape.

---

## Reach

TOPO-003 §14 claims "up to 15× fewer hops (2 vs up to 30)". Measured:

| Configuration | Max network hops | Mean network hops (uniform) |
|---|---|---|
| k=16, c=4, MECS on | 2 | 1.88 |
| k=16, c=4, MECS off | 30 | 10.59 |

The 2-hop bound holds exactly, by construction. The 15× figure is a
worst-case ratio; the mean-hop reduction under uniform traffic is **5.6×**,
and the end-to-end latency reduction at low load is larger still (21
cycles vs 410) because hops that do not happen also do not queue.

---

## Configuration reference

Names track the spec's register names.

| Key | Default | Spec | Meaning |
|---|---|---|---|
| `srota_mecs` | 3 | TOPO_MECS_ENABLE | bit0 row express, bit1 column express; 0 = ablation baseline |
| `srota_drop_latency` | 1 | TOPO_DROP_LATENCY | 1, or 2 for the repeatered fallback (§6.2) |
| `srota_island_col_map` | 0 | TOPO_ISLAND_COL_MAP | island column bitmap; requires MECS on both dims (§4.4) |
| `srota_path_en` | 7 | ROUTE_PATH_EN | bit0 row-first (mandatory), bit1 column-first, bit2 Valiant |
| `srota_cong_thresh` | 8 | ROUTE_CONGESTION_THRESH | Plane-T occupancy above which a candidate is congested |
| `srota_epoch_len` | 1024 | ROUTE_EPOCH_LEN | flow-epoch length in cycles |
| `srota_force_shape` | -1 | ROUTE_DEBUG_FORCE_SHAPE | -1 off, else force shape 0..3 |
| `srota_vc_policy` | `rank` | §4.5.3 | `none` \| `shape` \| `rank` \| `oneshape` |
| `srota_flow_cache_size` | 64 | §10.4 | flow-epoch cache entries per FIU |
| `srota_tel_period` | 4 | TEL-004 §2.1 | Plane-T sample period in Plane-D cycles |
| `srota_tel_latency` | 8 | TEL-004 §3 | Plane-T publication delay, constant by construction |
| `srota_cdg_radix` | 4 | ROUTE-001 §4.4 | abstraction radix for the F1 check; 0 disables |

Three-level arbiter (ROUTE-001 §11.2), selected with
`sw_allocator = srota_arb`:

| Key | Default | Meaning |
|---|---|---|
| `srota_arb_l0_golden` | 1 | golden-rotation mask, Level 0 (F3) |
| `srota_arb_l1_slack` | 1 | slack-class mask, Level 1 |
| `srota_arb_l2_stc` | 1 | STC batch-epoch mask, Level 2 (F4) |
| `srota_arb_golden_epoch` | 64 | cycles per golden window |
| `srota_arb_golden_windows` | 16 | windows in the rotation |

Required: `routing_function = o1turn`, `use_noc_latency = 0`,
`routing_delay > 0` (MECS taps defeat BookSim's lookahead routing).

---

## Modeling departures — read before quoting a number

Full detail is in the design note in [networks/srota.hpp](networks/srota.hpp);
the load-bearing ones:

1. **Express channel granularity.** §7.3 counts 2K express channels; this
   model builds up to 4 per router (one per direction per dimension),
   because that is what §7.2's "one driver per segment per direction"
   requires and what keeps an eastbound and a westbound flit off the same
   wire. Channel *count* figures are not comparable with §7.3's table.
   Hops, reach and contention are unaffected.

2. **No side buffer, no staging latch.** VC-002's Plane D router has a
   2-flit staging latch and one shared 8-flit side buffer, and no VC
   arrays. BookSim's IQRouter is a per-input VC-buffered router and
   cannot represent "shared buffer that only allocation losers enter."
   Anything depending on side-buffer behaviour — `VC_SIDEBUF_WATERMARK`,
   the Plane-T hint it raises, VC-R1's 4–16 flit capacity sweep — is out
   of reach here.

3. **VCs exist here; on Plane D they do not.** Only `none` and `oneshape`
   correspond to a shippable Plane D. Treat `shape` and `rank` as
   measurements of what a VC-equipped Plane D would buy — input to the
   RT-R7 decision, not models of the current design.

4. **Per-tap VC sub-ranges are not allocated.** A directional Srota
   channel has up to k−1 taps; splitting would need k−1 VCs per rank. The
   consequence is conservative, not wrong: BookSim sometimes serialises
   two packets bound for different drops of one channel that hardware
   would overlap. Per-drop `BufferState` is still tracked, so credit
   accounting stays per-drop as VC-002 §5.1 requires.

5. **Multicast is not routed.** §9.3's simultaneous multi-drop accept —
   the mechanism behind the ~16× weight-broadcast claim — needs the
   multicast fork path. `srota_o1turn` routes unicast only.

6. **Arbitration: the three levels are modelled, the two stages are
   not.** The golden/slack/STC-batch cascade (§11.2) is implemented as
   `sw_allocator = srota_arb`, so measurable claim M3 (§16.4) is
   answerable — see
   [SROTA-M3-ARBITER.md](../../../tracks/t3-topology/docs/SROTA-M3-ARBITER.md).
   What is absent is TOPO-003 §7.3's two coupled ≤6-port allocators and
   rev 0.3's `out_busy_mask` handshake (RT-R9): BookSim's IQRouter drives
   one flat allocator, so that mask is identically zero here. Closing it
   needs a custom Router subclass — the same one the side buffer needs.

---

## Not yet implemented

In rough order of value:

- **Two-stage allocator coupling** (TOPO-003 §7.3, RT-R9). The three
  arbitration levels now exist as `sw_allocator = srota_arb`; the mesh and
  express stages and their `out_busy_mask` handshake do not.
- **Directed RT-R7 pattern** — four flows around a 2×2 square, per the
  finding above, to observe the cycle dynamically rather than only
  statically.
- **Multicast over MECS** (TOPO-003 §9.3) using the existing
  `Flit::mcast` fork path, to measure the ~16× broadcast claim and the
  `TOPO_CNT_MCAST_BLOCK` cost of the credit AND-reduction (§9.2).
- **Side-buffer router model** (VC-002 §2.3) — a custom Router subclass;
  needed for VC-R1 and for anything reading side-buffer occupancy.
- **Island rate regulators** (TOPO-003 §7.5) — currently islands affect
  placement checking only, not traffic shaping.
