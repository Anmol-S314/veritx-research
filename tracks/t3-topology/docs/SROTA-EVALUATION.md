# Srota NoC — T3 evaluation

Where the Srota fabric lands against the other topologies in this track, on
what traffic, and what the numbers can and cannot support.

Companion documents:

| Document | Covers |
|---|---|
| [`third_party/booksim2/src/SROTA.md`](../../../third_party/booksim2/src/SROTA.md) | The model itself — spec-to-code mapping, deadlock findings, modelling departures |
| [`networks/srota.hpp`](../../../third_party/booksim2/src/networks/srota.hpp) | Design note: port map, MECS construction, VC policies |
| This file | Cross-topology results, energy, workload analysis |

Run date 2026-09-08, against the rebuilt tools image. Raw data in
`results/srota_cmp/topology_sweep.json`.

---

## 1. Headline

| Workload | Srota rank | Note |
|---|---|---|
| Timeloop matrix, low load | 6th of 8 | 18.09 cyc; best is `cmesh16` at 15.54 |
| Timeloop matrix, near saturation | 3rd of 8 | 37.96 cyc at rate 0.03 |
| MoE hot-expert, under load | **1st of 7** | 48.44 cyc vs 55.8–92.4 for the rest |

Srota is mid-pack on locality-heavy traffic and first under all-to-all load.
Its advantages are reach and contention headroom, and a 4×4 grid carrying
nearest-neighbour traffic exercises neither.

---

## 2. Cross-topology comparison

16 nodes, Timeloop-derived traffic matrix, `use_noc_latency=0` applied to
every arm. Latency in cycles; hops and energy at rate 0.02.

| topology | 0.002 | 0.005 | 0.01 | 0.02 | 0.03 | hops | pJ/pkt |
|---|---|---|---|---|---|---|---|
| cmesh16 | **15.54** | **15.46** | **16.00** | **18.15** | 38.99 | **1.807** | **48.78** |
| fattree16 | 15.96 | 16.22 | 17.05 | 19.43 | **36.68** | 2.022 | 54.60 |
| ftree | 15.96 | 16.22 | 17.05 | 19.43 | 36.68 | 2.022 | 54.60 |
| fly4 | 16.14 | 16.42 | 16.85 | 19.38 | 40.97 | 2.000 | 54.00 |
| flatfly16 | 18.09 | 18.48 | 18.90 | 20.87 | 38.43 | 2.404 | 64.91 |
| **srota16** | 18.09 | 18.48 | 18.91 | 20.82 | 37.96 | 2.404 | 64.91 |
| torus4x4 | 19.25 | 19.71 | 19.77 | 21.84 | 42.38 | 2.647 | 71.48 |
| mesh4x4 | 23.53 | 23.68 | 24.33 | 25.81 | 43.40 | 3.457 | 93.34 |

Rate 0.03 is the knee — every arm jumps to 36–43 cycles there.

### 2.1 Srota and flatfly16 are the same curve

Both report **2.404 average hops** and land within 0.05 cycles of each other
at every rate. This is structural, not coincidence: at k=4 with express on
both dimensions, every router reaches every row-mate and column-mate in one
hop, which is exactly a flattened butterfly.

**At 16 nodes MECS has no reach advantage left to express**, because there is
none to win — a 4×4 grid is at most 3 mesh hops wide to begin with. Srota is
paying for express hardware the workload cannot use. Any conclusion about
MECS drawn from a 16-node sweep is a conclusion about grid size.

### 2.2 `ftree` is not an independent arm

`fattree16` and `ftree` are the same topology with the same k, n, routing
function, VC count, buffer depth and packet size — the configs differ only in
comments and `print_activity`. They return byte-identical results at every
rate, occupy two of the eight slots, and double-weight the fat-tree in any
average taken across arms.

---

## 3. The traffic model decides the answer

The matrix above comes from `timeloop_to_matrix.py`, whose spatial model its
own docstring marks a **"PLACEHOLDER"**: 60% nearest-neighbour ring, 40% to
node 0. That rewards locality, which is precisely what an express layer gives
up.

Srota's own MECS on/off ablation at 1024 nodes — identical routers,
concentration and routing, only the express layer differs:

| traffic | MECS on | MECS off | verdict |
|---|---|---|---|
| placeholder | 81.5 cyc · 1.41 hops | 63.0 cyc · 2.02 hops | express **loses** |
| MoE all-to-all | **20.5 cyc · 2.87 hops** | 65.3 cyc · 11.63 hops | express wins **3.2×** |

The express layer goes from losing to a 3.2× win purely on the traffic model.
Fewer hops with worse latency, in the top row, is the signature: the shared
multidrop channels concentrate traffic that a mesh spreads, and on
nearest-neighbour traffic there are no hops to save.

### 3.1 MoE traffic

`scripts/moe_traffic.py` generates what the fabric is designed for:
expert-parallel all-to-all with Zipf expert popularity, topology-aware
placement of hot experts into a chosen mesh column, and weight broadcast.
Grounded in a real Mixtral-8×7B config rather than invented parameters.

Latency at rate 0.04, MoE hot-expert traffic, 3.73× destination imbalance:

| topology | cycles |
|---|---|
| **srota16** | **48.44** |
| flatfly16 | 55.75 |
| fly4 | 63.37 |
| torus4x4 | 75.08 |
| fattree16 / ftree | 81.67 |
| mesh4x4 | 92.39 |

`cmesh16` was unstable at this rate and is excluded — past saturation only
completed packets are counted, so an unstable arm can read lower than a
slower stable one.

---

## 4. Energy

`noc_energy.json` reports 5.4 pJ/hop, split router 4.2 / link 1.2, and
energy per packet is `hops_avg × packet_size × pj_per_hop`.

**The Accelergy model behind that number is a placeholder.** From
`results/baseline/accelergy/`:

| File | What it says |
|---|---|
| `ART_summary.yaml` | `primitive_estimations: dummy`, area **1.0** for both router and link |
| `ERT_summary.yaml` | `estimator: N/A` against hand-set round numbers — router traversal 2.5, buffer read 0.8, buffer write 0.9, link transfer 1.2 |
| `action_counts.yaml` | every count is **1** |
| `flattened_architecture.yaml` | 45nm, `n_instances: 1`, `area_scale: 1.0` |

So energy here is `hops × 5 × 5.4` — a linear restatement of the hop column,
carrying no independent information. **There is no energy-versus-latency
trade visible in this data, and there cannot be until the estimator is real.**
The bridge itself is wired correctly end to end; it is waiting on a
technology model, not on plumbing.

---

## 5. The N72 spatial run

`results/llama_7b_hf_config_N72/` is the Megatron-TP pipeline: Llama-7B, seq
2048, 72 tiles, 464 op instances over 7 templates collapsed to 14 unique
Timeloop shape runs. Six per-stage matrices, each **73×73** — 72 tiles plus a
DRAM node at index 72.

### 5.1 It is a star workload, not a fabric workload

Share of each stage's traffic that is tile-to-tile rather than tile↔DRAM:

| stage | tile↔tile | reading |
|---|---|---|
| qkv_proj | 0.0% | column-parallel, no reduction — correctly zero |
| gate_up_proj | 0.0% | same |
| full_layer | 0.2% | everything combined |
| attention | 0.3% | head-group all-reduce |
| down_proj | 0.4% | TP-global all-reduce |
| out_proj | 1.7% | TP-global all-reduce, the largest share |

The DRAM node carries **32.4×** the mean tile's row. Any topology driven by
this is bottlenecked at one node's ejection port, so the arms would rank
nearly identically — the fabric is not what gets measured.

The zeros are correct, incidentally: `qkv_proj` and `gate_up_proj` are
column-parallel with no reduction, so they *should* have no cross-tile edges.
The mapping is working as designed.

### 5.2 Its collectives are nearest-neighbour

Every tile-to-tile edge sits at offset ±1 — `ring_allreduce_pairs` doing
exactly what it should. But in tile-id space offset +1 is the *adjacent
router* under row-major layout, so the little cross-tile traffic that exists
favours a mesh, for the same reason the placeholder matrix does.

### 5.3 No config can consume it

The matrices are 73 nodes. Every config in `configs/` is 16, 64 or 72 —
`dragonfly16` at 72 misses by exactly the DRAM node. The spatial pipeline
emits **N+1** while every config is sized to N.

Neither `llama_7b_hf_config_N16` nor `_N72` contains a `topology_sweep.json`,
consistent with these never having been run through BookSim.

**Fix:** fold the DRAM node onto a tile, add an `--nodes N` mode that emits
N-sized matrices, or add an N+1-sized config (`anynet` reads an arbitrary
graph and could).

---

## 6. What the Srota model implements

Topology `srota`, routing function `o1turn`, in
`third_party/booksim2/src/networks/srota.{cpp,hpp}`. Each item names the spec
section it implements. Full detail in
[`SROTA.md`](../../../third_party/booksim2/src/SROTA.md).

| Feature | Spec | Summary |
|---|---|---|
| Concentrated mesh | TOPO-003 §2, §10 | k×k routers, c tiles each; router `y·k+x`, terminal `n·c+t` |
| MECS express layer | TOPO-003 §3.1, §7.4, §11.1 | One MultiDropChannel per (driver, direction); out-degree c+4 independent of k, in-degree c+2(k−1) |
| MECS-off ablation | TOPO-003 §5 | Express disableable per dimension; reverts to nearest-neighbour links |
| O1TURN-XY routing | ROUTE-001 §3, §11.1 | Row-first and column-first, each dimension-ordered; route compute takes no congestion argument |
| Valiant third shape | ROUTE-001 §5.1, §13.4 | Random intermediate, shape rewrite confined to the intermediate router |
| Injection-time overlay | ROUTE-001 §2, §5, §10 | Shape chosen once per flow-epoch at the FIU, from Plane-T state |
| Flow-epoch cache | ROUTE-001 §10.4, §5.4 | Hash-keyed, lazy epoch invalidation; stores shape **and** Valiant intermediate (the RT-R8 fix) |
| Plane-T telemetry | TEL-004 §2, §3, §4 | Peak queue pressure per router as a 4-bit nibble, mean over each line, fixed publication delay |
| F1 deadlock check | ROUTE-001 §4.2, §4.4 | Static CDG construction and cycle detection at elaboration, exhaustive over shapes and intermediates |
| Four VC policies | ROUTE-001 §4.5.3 | `none`, `oneshape`, `shape`, and `rank` — the last not in the spec's option table |
| TP-V2 island check | TOPO-003 §4.1, §15 | I-ISL verified by route enumeration, reported per shape |
| Configuration surface | TOPO-003 §13, ROUTE-001 §14 | Twelve `srota_*` keys; §14.3 validity rules enforced as errors |

### 6.1 Not implemented

| Gap | Spec | Consequence |
|---|---|---|
| Two-stage allocator coupling | TOPO-003 §7.3, RT-R9 | The three arbitration *levels* now exist (`sw_allocator = srota_arb`); the two coupled ≤6-port *stages* and their `out_busy_mask` handshake do not. M3 is answered, with that caveat — see [SROTA-M3-ARBITER.md](SROTA-M3-ARBITER.md). |
| Side buffer / staging latch | VC-002 §2.1–2.3 | BookSim's per-input VC router cannot express a shared buffer only losers enter; VC-R1 out of reach |
| Multicast over MECS | TOPO-003 §9.3 | The ~16× broadcast claim is unmeasurable here |
| Island rate regulators | TOPO-003 §7.5 | Islands affect placement checking, not shaping |

Modelled differently, and load-bearing when reading results:

- **VCs exist in the model; Plane D has none.** Only `none` and `oneshape`
  correspond to a shippable configuration. Read `shape` and `rank` as input
  to the RT-R7 decision, not as models of the current design.
- **Channel granularity.** §7.3 counts 2K express channels; this builds up to
  4 per router per §7.2's single-driver-per-direction rule. Channel *counts*
  are not comparable with that table; hops and contention are.
- **No per-tap VC sub-ranges.** Conservative, not wrong — sometimes
  serialises packets hardware would overlap. Per-drop credit accounting stays
  correct.

---

## 7. Reproducing

```sh
# the cross-topology comparison
cd tracks/t3-topology
TRAFFIC_MATRIX=results/traffic_matrix.txt BOOKSIM_EXTRA="use_noc_latency=0" \
RATES="0.002,0.005,0.01,0.02,0.03" CONFIG=srota_cmp \
  python3 scripts/run_experiments.py

# the MoE arm
python3 scripts/moe_traffic.py -n 16 --grid-k 4 --grid-c 1 \
    --pattern a2a --skew 1.2 --hot-column 2 -o results/moe16.txt
TRAFFIC_MATRIX=results/moe16.txt BOOKSIM_EXTRA="use_noc_latency=0" \
RATES="0.01,0.02,0.04" CONFIG=moe_cmp python3 scripts/run_experiments.py

# Srota's own checks — F1 and TP-V2 run before any flit moves
cd ../../third_party/booksim2/src
python3 srota_validate.py                  # 19 checks
python3 srota_sweep.py --compare vc_policy # the RT-R7 resolutions
```

`BOOKSIM_EXTRA="use_noc_latency=0"` is **not optional** for a cross-topology
comparison. Without it the arms price channel latency differently — `srota16`
sets it to 0 itself while most other configs inherit BookSim's default of 1 —
and the ranking is not measuring topology. Measured spread at rate 0.01:
`cmesh16` 16.82 → 16.00, `torus4x4` 21.44 → 19.77, `mesh4x4` unchanged.

---

## 8. Recommended next steps

Ordered by what unblocks the most.

1. **A 1024-node comparison set.** The only configuration where MECS reach
   is exercised. Currently Srota-versus-itself; needs matching `cmesh`,
   `flatfly` and `mesh` configs at that size.
2. **Fix the N+1 node-count mismatch** in the spatial pipeline, so the
   Megatron-TP matrices can drive any topology at all.
3. **A real Accelergy technology model**, so energy stops being a restatement
   of hop count and a Pareto trade becomes visible.
4. **The two-stage allocator coupling**, which is what remains of M3 after
   [SROTA-M3-ARBITER.md](SROTA-M3-ARBITER.md). It shares a custom Router
   subclass with the side buffer, so the two are one piece of work.
5. **Retire or differentiate `ftree`**, and correct the node counts implied
   by the names `qtree16` and `tree4` (both 64 nodes).
