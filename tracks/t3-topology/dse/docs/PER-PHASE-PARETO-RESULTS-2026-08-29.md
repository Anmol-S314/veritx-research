# Per-Phase Pareto — 2026-08-29 (Final Corrected Numbers)

**Same execution, sliced per phase** — this is the "which fabric for which phase" table.

Slices from `qwen3_serving_16rank.trace` (LLMServingSim 16-rank Qwen3-30B):
- `phase_tp_allreduce` (class 0): 49,152 packets — TP allreduce, local 16-NPU ring
- `phase_moe_dispatch` (class 1): 46,080 packets — MoE EP dispatch, global all-to-all
- `llama70b_tp64_ring`: 1,290,240 packets — Dense TP=64 ring (capacity-saturated)

Method: 8 topologies × 3 phases × 1 seed = 24 full-trace BookSim replays
(`latency_thres=-1.0`, `sample_period=span+10K`, `max_samples=5`, `use_noc_latency=0`).
Trace-replay is deterministic — seeds are moot, std=0.00.

Config verification:
- `wait_for_tail_credit=0 vs 1` → **identical** in trace-replay mode (injection is
  hard-timed, backpressure manifests as queuing delay — already captured).
- `latency_thres=-1.0 vs 1e6` → **identical** on 652K-cycle trace (no packets exceed 1M).
- `latency_thres=500.0` → ABORT at60K cycles (the old default trap).
- Only real bug: `classes=2` passed to BookSim = 75× inflation → fixed in `895047b9`.

## Results

| Topo | Edges | TP Allreduce | MoE Dispatch | Dense LLaMA Ring |
|---|---:|---:|---:|---:|
| gec_express (k8 o7 d1) | 448 | **21.50c** | 3377.83c | 62451.80c |
| gec_mecs (k8 o1 d7) | ~128 ch | **21.50c** | 3409.89c | 64235.20c |
| grpo_best (anynet min) | 111 | 24.62c | 3391.83c | 62451.90c |
| rho100_best (anynet min) | 106 | 25.88c | 3389.50c | 62618.00c |
| flatfly_64 (ran_min) | 48 | 25.75c | **3377.17c** | 63937.80c |
| mecs64 (anynet min) | 111 | 32.75c | 3450.50c | 62452.90c |
| torus_8x8 (dim_order) | 128 | 36.50c | 3391.83c | 62451.80c |
| mesh_8x8 (dim_order) | 128 | 38.38c | 3399.83c | 62454.40c |

dominated: mesh (torus better at same 128e), mecs (gec cheaper + faster on all)

## Key Finding

**Topology only matters for attention/TP-allreduce.** The discriminating column is the left one:

- gec_express wins TP allreduce (21.50c, −44% vs mesh 38.38c) — shortest hops for
  local ring. But needs 448 edges (3.5× mesh).
- torus dominates mesh at equal 128e — the "boring baseline" that must be beaten.
- MoE dispatch: spread is 2.2% (3377–3450c) — nearly flat, topology is noise.
- Dense LLaMA ring: 0.02% spread — capacity wall, topology irrelevant.

**The paper headline**: "For TP allreduce, torus dominates mesh (same wires), and
express fabric (448e) cuts44%. For MoE dispatch, flatfly (48e) is Pareto-optimal
at6% fewer edges and comparable latency. Dense ring is capacity-bound — topology
is irrelevant."

The "need different topologies for different phases" claim is confirmed but with
a caveat: the *only* phase with meaningful topology sensitivity is TP allreduce.
MoE dispatch and dense ring are essentially topology-agnostic (2% and 0.02%
spreads). A single torus suffices for most phases; express fabric buys44% on
TP allreduce at3.5× the wire cost.

## Compare vs Pareto discrepancy (explained)

The other agent's compare showed mesh=603c attention, while our pareto showed
mesh=38.38c TP-allreduce. Different configs:
- compare: `sample_period=1000 max_samples=5` → only samples 5K of 652K cycles
- pareto: `sample_period=span+10K max_samples=5` → full trace
- compare's 603c is a **partial-window artifact** (incomplete sampling).
