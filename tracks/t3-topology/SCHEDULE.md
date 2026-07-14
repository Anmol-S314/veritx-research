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

## Where this sits, and what is not yet done

- **Where multicast pays** (from [compression_stack.py](scripts/compression_stack.py)):
  throughput serving and/or long context. It is invariant to lossless KV compression at
  the capacity-limited operating point, and orthogonal to it. It erodes only in the
  small-batch, short-context, heavily-compressed corner.
- **Not yet done:** this is a mapping and its traffic accounting, checked against a real
  floorplan and a calibrated bottleneck model. It is **not** a cycle-accurate run — the
  next step would be to drive BookSim2 with this exact multicast/reduce traffic (now
  unblocked, since we are off TOGSim) and confirm the end-to-end decode speedup lands
  where the roofline predicts. That is a bounded, well-specified experiment rather than
  the open-ended topology sweep the track started with.
- **Honest bound:** `g` is the ceiling, realised when a group is spread across cores (the
  low-batch / many-core regime). A pure context-parallel mapping reaches low DRAM traffic
  a different way (cross-core reduction instead of multicast); this schedule's advantage
  is getting there **without** a per-step reduction on the group axis — one DRAM read and
  one row-broadcast, no all-reduce.
