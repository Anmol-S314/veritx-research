# Memory leg scaling — bounded, costed, never a hang

The DRAM leg runs Ramulator2, which replays **one request per tick in a
single thread**. Wall-clock time is therefore *linear in transaction count*,
and a realistic model blows straight past any sane timeout.

Measured on this tree, Llama-3.1-8B at TP2 (6.98 GB of weights):

| quantity | value |
|---|---|
| transactions | **109,068,288** |
| trace on disk | 3.4 GB |
| capacity (1-channel HBM3 geometry) | 17.18 GB — **fits** |
| previous behaviour | 600 s timeout, run FAILED |
| new behaviour | refusal in ~4 s, costed |

Two facts follow, and they are the point of this document:

1. **It is not a capacity or memory problem.** The trace fits the modelled
   geometry, and the lowering already streams (peak RSS is O(1) per
   transaction — a 1.94 GB trace lowers in 12 MiB). It is a **time**
   problem, and no amount of streaming fixes it.
2. **It is not a row-conflict problem either.** The same trace shows 99.6%
   row hits — bulk weight streaming is near-ideal. Simulating 109 M
   transactions buys almost nothing over simulating the first few thousand.

## The fix

### 1. Estimate before building

`memory_lowering.estimate_trace_cost(artifact, geometry)` is pass 1 of the
lowering as a standalone query: it counts transactions, bytes and capacity
fit **without writing a trace**. It reuses the one span authority
(`access_tx_range`), and a test pins that its counts equal the manifest the
real lowering produces.

### 2. Bound, and refuse with the cost

`RamulatorAdapter.execute` consults a budget (`max_transactions` on the run
options, default `DEFAULT_MAX_TRANSACTIONS = 20_000_000`). Over budget it
**refuses immediately**, having written `trace-cost.json` as evidence:

```
memory artifact exceeds the cycle-accurate budget: traffic needs
109,068,288 transactions (6.98 GB) but the cycle-accurate budget is
20,000,000 — Ramulator replays serially, so this would not finish in the
configured timeout; bandwidth-model bound (NOT cycle-accurate):
136.335 ms at peak, assuming the trace streams with no queueing or
row-conflict loss
```

A costed refusal in four seconds is worth more than a ten-minute silence.

### 3. A differently-labelled bound

`bandwidth_model_stream_ns(cost, geometry)` gives the streaming time at
**peak bus bandwidth**: `data_rate (MT/s) x bus_width (bytes) x channels`,
derived only from audited timing presets. An unknown preset **refuses** —
a guessed rate is worse than no rate.

This number is fidelity `MEMORY_BANDWIDTH_MODEL`, **never** `DRAM_TIMING`.
It assumes the trace streams at peak with no queueing, row-conflict or
refresh loss, so it is a **lower bound**, and it is labelled as one
wherever it appears.

## The geometry is now selectable — and the interleave was the other half

The certified geometry was **one HBM3 channel**: 6400 MT/s x 8 B = 51.2 GB/s.
Streaming 6.98 GB of weights across it takes **>= 136 ms** — a hard floor
before any inefficiency. One channel cannot feed an 8B model.

Two audited profiles now exist (`backend/ramulator_adapter.py`):

| profile | channels | peak | capacity |
|---|---|---|---|
| `CERTIFIED_RAMULATOR_HBM3_V1` | 1 | 51.2 GB/s | 17.2 GB |
| `CERTIFIED_RAMULATOR_HBM3_8CH_V1` | 8 | 409.6 GB/s | 137.4 GB |

A profile is a **declared envelope with its own id**, carried into the
capability limitation text, the qualification profile and the backend config
hash. It is never a performance flag on an existing result.

### Adding channels is necessary but NOT sufficient

Making the driver emit eight controllers changed the numbers by **nothing**:
completion cycles moved 1,031,343 -> 1,026,219. The reason is the address
order. `sequential_bankstriped_v1` places **channel almost last**, so a
streaming workload fills channel 0 for a whole 1 MB block before touching
channel 1 — the channels are used **sequentially in time**, and N channels
are N sequential segments.

Measured on an identical 131,072-transaction trace (same row-hit count):

| layout | channels | max cycles |
|---|---|---|
| `sequential_bankstriped_v1` | 8 | 1,026,219 |
| `channel_interleaved_v1` | 8 | **128,539** |
| `sequential_bankstriped_v1` | 1 | 1,031,343 |

That is a **8.0x** speedup — exactly the channel count — bought entirely by
the interleave. Real HBM interleaves at cacheline granularity for this exact
reason.

So the multi-channel profile carries `channel_interleaved_v1` (channel
varies fastest), the single-channel profile keeps the frozen sequential
order, and both are inside the audited envelope. An unaudited channel count
(2, 4, 16, ...) or an unaudited mapping **refuses** rather than producing an
unvetted number.

## Enabling it

```python
ProductConfig(..., ramulator_geometry_profile="CERTIFIED_RAMULATOR_HBM3_8CH_V1")
```

The trace frontend also had to change: it injected **one request per tick**,
which made the replay *cadence* the bottleneck rather than DRAM (completion
time tracked transaction count, so channels could not help). It now injects
until backpressure, so the controllers' queues actually fill. This is
measured-neutral for the single-channel profile (identical cycles).

## What is still not done

- **No per-channel parallelism.** Ramulator ticks its controllers serially
  in one process, so eight channels cost the same wall clock as one. The
  simulated answer is 8x better; the simulation is not 8x faster.
- **The interleave is 64 B granularity** (one transaction), finer than real
  HBM's ~256 B-4 KB. Fine enough to demonstrate the effect, not a calibrated
  system model.
- **No coalescing or reuse model.** A single forward pass reads every weight
  byte once; real serving reuses weights across a batch, so the cost above
  is the worst case.
- **The transaction budget should tighten.** 7.87 M transactions took ~600 s
  of cycle-accurate Ramulator, so the practical budget is nearer 2 M than the
  current 20 M default.
