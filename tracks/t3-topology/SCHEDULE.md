# T3 — Multicast-aware KV schedule for GQA decode

The constructive output of the track. [CONCLUSION.md](CONCLUSION.md) shows on-chip
topology is not the lever and on-chip **multicast** is (up to ~5.4× decode throughput,
[scripts/serving_multicast.py](scripts/serving_multicast.py)). This is the concrete
mapping that realises it, validated against the pinned Wormhole grid
([scripts/schedule.py](scripts/schedule.py), `--selfcheck`).

## The problem in one paragraph

GQA decode: `n_q` query heads share `n_kv` KV heads in groups of `g = n_q/n_kv`. The KV
cache (the whole context history, per head) is the dominant DRAM read in long-context
decode. The shipped kernel spreads a group's `g` query heads across cores and each one
**re-reads the same KV head from DRAM** — a `g`-fold waste on the one resource that is
the bottleneck (decode is DRAM-bound: [decode_roofline.py](scripts/decode_roofline.py)).

## The idea: attention factors into two primitives a 2D fabric already has

```
            columns  →   query heads of a group   (or context chunks, long ctx)
          ┌─────────────────────────────────────────────┐
   rows   │   KV head 0 : q0 q1 q2 q3 q4 q5 q6 q7        │  ← read KV head 0 from DRAM
    ↓     │   KV head 1 : q8 q9 …                        │    ONCE, MULTICAST along row
  KV      │   KV head 2 : …                             │
 heads    │   …                                         │  ← combine context chunks
          └─────────────────────────────────────────────┘    DOWN a column (reduce)
              ▲ DRAM feeds each row from interior col x=5
```

- **Rows = KV groups.** The `g` query heads that share a KV head sit on one physical row.
  The KV head is read from DRAM **once** and **multicast along the row** to all `g` cores.
  *This is the g-fold DRAM saving.*
- **Columns = query heads** (short context) **or sequence chunks** (long context). When
  the KV cache is too big for one core, split the context down the column and combine the
  partial attentions with an **online-softmax reduce**.

`share-with-group = row-multicast`, `combine-context = column-reduce`. **Both are native
mesh/torus operations.** That is *why* the topology never needed to be exotic — the
schedule uses the fabric's built-in primitives, and the fabric is idle anyway (4× NoC
headroom, [decode_roofline.py](scripts/decode_roofline.py)).

## Placed on the real Wormhole grid

From the pinned SoC descriptor ([scripts/wormhole.py](scripts/wormhole.py)): 80 Tensix in
8 columns × 10 rows, DRAM in **interior** columns x∈{0,5}.

- `core(col, row)` → KV head = `row`, query head = `row·g + col`.
- KV head `row` is fed from the DRAM endpoint at x=5 **inside** its row, so the multicast
  fans out **both directions** and the span halves. (Interior DRAM, which looked like a
  complication in the memory-fabric study, is an *advantage* here.)
- 8 KV heads × 8 query heads = **64 of 80 cores**; the 2 spare rows take context-split or
  a second batch element.

## Validated traffic (per layer per decode step, BF16, `scripts/schedule.py`)

| context | DRAM (schedule) | DRAM (naive re-fetch) | DRAM cut | NoC vs naive |
|---|---|---|---|---|
| 8K | 33.6 MB | 268.4 MB | **8×** | **0.40×** |
| 32K | 134.2 MB | 1073.7 MB | **8×** | **0.40×** |
| 128K | 536.9 MB | 4295.0 MB | **8×** | **0.40×** |

Two results, both asserted in the selfcheck:

1. **DRAM traffic falls exactly `g`× (8× here)** — each KV head crosses the memory bus
   once, not once per query head. This is precisely the reduction that produced the 5.4×
   throughput in [serving_multicast.py](scripts/serving_multicast.py); this file is where
   that number physically comes from.
2. **The NoC cost is negative.** The multicast tree moves **0.40×** the hop-bytes of `g`
   independent DRAM pulls, because the group shares links instead of each pulling its own
   path. So multicast is not a NoC *cost* offset against a DRAM *saving* — it is **less**
   traffic on **both** networks. The idle NoC absorbs it with room to spare.

## Streaming, not resident

At long context the KV cache dwarfs a Tensix's 1.5 MB L1 (one head at 128K ≈ 64 MB), so
it is **streamed** from DRAM in tiles — each tile read once, multicast to its row,
consumed online (FlashAttention-decode style). L1 holds only a working window; DRAM
bandwidth is the wall, and the schedule's whole job is to not waste it on redundant reads.

**REQUIREMENT — store the KV cache per-head-contiguous.** Because DRAM bandwidth *is* the
wall, the read pattern that hits it matters, and we measured it (Ramulator2, GDDR6,
[scripts/dram_efficiency.py](scripts/dram_efficiency.py)): a per-head-contiguous KV head
reads as a clean stream at **91%** of peak (the 9% is refresh), but a vLLM-style
`[block, heads, dim]` layout — where reading every 1 KV head strides past the other `g−1` —
thrashes the row buffer down to **66%**. Multicast reads each KV head *once*, so this is
exactly the layout it must have; adopting the multicast schedule without fixing the layout
throws back ~28% of the bandwidth it just saved. (The g-fold multicast-vs-naive *ratio* is
unaffected — same layout both ways — but the absolute tokens/sec in
[serving_multicast.py](scripts/serving_multicast.py) is derated by this 0.91, not peak.)

**REQUIREMENT — run the row-multicast on NoC0, not NoC1 (silicon-measured).** The on-chip
multicast delivery is *not* free in fanout in general — it depends on which NoC instance
and where the sender sits relative to the write-ACK path. This is now backed by Tenstorrent's
own measured plots ([scripts/mcast_measured.py](scripts/mcast_measured.py), extracted from
the multicast-schemes study in `tt-low-level-documentation`, the closed #22519 deliverable):
a row-multicast with the sender excluded on **NoC0** stays **30.59 → 29.79 B/cyc** from 2×2
to 7×7 destinations — flat in fanout (~2.6% total) and 2.0× clear of the schedule's 14.6
GB/s row feed. The same study shows the **misconfigured pairings collapse up to ~15%**
(≥8.5 GB/s lost): row-shared on NoC1 or column-shared on NoC0 route the write-ACKs back over
the congested multicast path (a self-interference loop). Our readers default to RISCV_0
→ NoC0, so this is a design *rule*, not a change: keep the KV row-multicast on NoC0 with a
row-shared sender placement. The **NoC is no longer load-bearing** — it is flat-headedroom
and never binds — but it now carries a citable placement constraint instead of an assumption.

## Where this sits, what is validated, and what is open

- **Where multicast pays** (from [compression_stack.py](scripts/compression_stack.py)):
  throughput serving and/or long context. It is invariant to lossless KV compression at
  the capacity-limited operating point, and orthogonal to it. It erodes only in the
  small-batch, short-context, heavily-compressed corner.
- **Cycle-accurate validation — the two obstacles we started from.** Driving BookSim2
  (standalone, off TOGSim) with the schedule's traffic hit two walls first, both found by
  checking the tool before trusting it — and both shaped the two-pass approach below:

  1. **BookSim2 mainline has no multicast.** Grep of `/opt/booksim2/src` for
     `multicast`/`mcast`/`multi_dest` returns nothing; every traffic pattern is unicast.
     So the multicast tree — the whole point — cannot be simulated without patching the
     router to replicate flits. Naively "injecting the multicast traffic" would expand it
     into `g` unicasts, i.e. re-simulate the naive case and call it validation.
  2. **BookSim's `hotspot` is the wrong direction.** It concentrates *destinations*; the
     schedule's heavy flow concentrates *sources* (18 DRAM → 102 compute). A first
     accidental run funnelled 121→18 and saturated at inj≈0.02 (hotspot node pinned at
     0.975 flit/cyc) — real, but it is the compute→DRAM **write/request** path (minor in
     decode), and it saturates for the generic reason that few memory ports throttle many
     writers, not because of anything in our schedule.

- **Cycle-accurate validation, in two passes.** First a *proxy* on the existing traffic
  pattern; then the *real* flit-fork patch that removed the proxy's confound and confirmed
  the win. Both are kept — the proxy is *where the confound was caught*, and that is the
  transferable lesson.

  **Pass 1 — far-end proxy (`scripts/mcast_validate.py --run`).** A row-broadcast's network
  link load equals a unicast to the far end of the row (DOR crosses each row link once), so
  we simulated that on an 8×8 torus. It confirms one thing a roofline cannot: at the
  schedule's 16 GB/s DRAM-bound load (injection 0.10) the torus is **stable — unsaturated**,
  cycle-accurate. But it is *not* a clean multicast-vs-naive comparison, for a precise,
  proven reason (`--ejtest`): BookSim's `matrix` pattern makes **every** node inject (a zero
  row → a *self-packet* routed straight to the eject port, `dor_next_mesh`: `cur==dest →
  2·gN`), and that port is a real **1 flit/cyc** resource (the `--ejtest` knee sits exactly
  at `inj·packet_size = 1.0`). So the row's terminus node **double-loads** — its stream (0.5
  flit/cyc at schedule load) *plus* its own idle self-packet (0.5) = 1.0 — and multicast
  *appears* to saturate early (≈0.14). An artifact of the every-node-injects model, not
  physics; it even falsified an inline claim in that file that "ejection is never the
  bottleneck" (**PITFALLS §15**). The schedule-load stability conclusion survives it.

  **Pass 2 — real flit-fork multicast (`scripts/mcast_flitfork.py`, `third_party/booksim2`).**
  We built it. The `Flit` carries pre-registered single-flit copies, `iq_router` forks each
  to the eject port as the stream transits a row core, and the `TrafficManager` injects one
  stream per row with **receivers suppressed** — so the every-node-injects pollution is gone.
  On an 8×8 **mesh** (a torus would let the stream take the 1-hop wraparound and miss the
  middle cores, so mesh is the conservative linear-path model):
    - **Fork is exact** — the known-answer gate: one injection → **7.0 deliveries** = g−1.
    - **The g-fold win is confirmed, confound-free:** multicast sustains **≥7.1×** the useful
      KV-delivery rate of naive re-fetch before saturating (0.875 vs 0.123 deliveries/cyc),
      latency **flat** while naive's detonates at injection 0.20. The group shares the row
      links; naive's near link carries all g streams and saturates first. This is the
      network-side (g−1) counterpart of the g-fold DRAM saving
      ([serving_multicast.py](scripts/serving_multicast.py)), now cycle-accurate. The surgery
      *confirmed* the analytic result — it did not overturn it, exactly as expected, which is
      why the DRAM-side analysis was always the load-bearing evidence.

- **The second primitive — column-reduce, and both together (`scripts/schedule_fabric.py`).**
  The multicast was only half the schedule; the other half is the online-softmax
  **column-reduce** that combines partial attentions when a head's context is split down a
  column. The modelling point that makes it cheap: the combine is **in-core compute**, so the
  network only *relays* a partial one hop up the column to its parent — an ordinary unicast,
  no fork and no merge, so it needed no extra router surgery (the same `reduce_col` path in
  `multicast.patch`). Three results:
    - **Reduce is a pure 1-hop relay** — the known-answer gate: accepted/injected = **1.0**
      (no fork), and it stays cheap (stable to inj 0.60, latency ~12) because each column
      link carries just one small partial.
    - **Both primitives fit the fabric at once.** At the schedule's DRAM-bound operating load
      (inj 0.10), multicast, reduce, and the **combined** run are all stable with headroom
      (combined latency ~20 cyc), and combined is still stable at 2× that load.
    - **Stated conservatism:** we inject reduce partials as fast as the KV stream, whereas the
      reduce really fires *once per decode step*. So the equal-rate combined saturation is an
      over-driven floor far above the operating point — the realistic reduce is lighter still.
- **Both engines on ONE operating point — the composition, earned not assumed
  (`scripts/decode_e2e.py`).** The results above are each cycle-accurate *on their own* but
  composed only on paper. This pins the Ramulator DRAM and the BookSim NoC to a **single**
  decode operating point derived from first principles: Wormhole feeds `288 GB/s ÷ 18 endpoints
  = 16 GB/s` per DRAM endpoint (one KV-group row), Ramulator keeps `× 0.91` of it (measured
  live, the per-head-contiguous read above), and the established `32 GB/s = 1 flit/cyc` bridge
  turns that into **0.456 flit/cyc** at the row source. BookSim's real flit-fork multicast is
  then run at exactly that injection. At that DRAM-dictated load multicast is **stable**
  (latency 27) while naive is **saturated** (latency 701); **DRAM is the binding stage** (14.6
  GB/s vs NoC 32, compute 925 — NoC 2.2× clear, compute 63×); and the per-die model aggregates
  back to the **4608 GB/s QuietBox** headline. Four gates, all pass (fork-exact 7.01,
  loop-closes, DRAM-binds, composes-to-headline). It is a **staged DRAM→NoC hand-off**, not a
  full co-simulator: no NoC→DRAM backpressure, which is unnecessary for a one-way DRAM-bound
  feed — and the loop-closes gate *checks* the NoC keeps up rather than assuming it. Compute
  stays analytic (PyTorchSim is not wired in; at 63× headroom it cannot be the binding stage).
  This closes the one seam that was purely analytic — DRAM↔NoC.
- **Honest bound:** `g` is the ceiling, realised when a group is spread across cores (the
  low-batch / many-core regime). A pure context-parallel mapping reaches low DRAM traffic
  a different way (cross-core reduction instead of multicast); this schedule's advantage
  is getting there **without** a per-step reduction on the group axis — one DRAM read and
  one row-broadcast, no all-reduce.

## The claim's envelope: the die-to-die fabric (`scripts/fabric_sweep.py`)

The 5.4× is an **intra-die** result: the KV head crosses a die's own NoC. A sequence whose
KV exceeds one die's share of the box (12 GB of 192 GB at 16 dies ≈ 37K tokens at 32K/BF16
rates) must pull KV from *other* dies over the Ethernet fabric — and that layer is
separately checked, with a quantified verdict:

- **Mechanism holds at die scale:** the same switch-replicated multicast (BookSim, 4×4 die
  mesh, one stream per KV shard) forks exactly and beats naive re-fetch by ~fanout — the
  primitive transfers to the die array. A measured topology finding: on a **torus**,
  dim-order routing takes the 1-hop wraparound and **skips the middle dies**, so
  replication coverage requires mesh.
- **Capacity does not:** sharding KV across 16 dies sends ~15/16 of every KV read — **~2.5
  TB/s** at the 5.4× operating point — over a fabric whose 4×4 mesh of 100GbE links has
  ~50 GB/s bisection. That is **~50× short** (per-die egress ~3× short); even 800GbE
  ports leave bisection ~6× short. Multicast's 15× win covers the naive gap *within* the
  fabric, not the absolute deficit. No near-term Ethernet closes it.
- **Therefore the envelope is KV-locality:** batch-split placement (each die serves its own
  sequences) keeps KV 100% local — zero fabric KV traffic, 5.4× untouched — at the price of
  a ~37K-token context ceiling per sequence. Beyond that, KV must shard, and the fabric
  loses regardless of topology. **The Ethernet-NoC topology question only becomes
  first-order at ~10× today's fabric** — the answer at QuietBox scale is "keep KV off the
  fabric", not "which fabric".
