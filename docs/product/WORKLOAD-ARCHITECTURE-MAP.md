# Workload → Architecture Map — release-workloads-20261110

**Date:** 2026-11-10 · **Scope:** the 17 approved entries in
`docs/product/evidence/release-workloads-20261110.json` (approval_id
`release-workloads-20261110`, `approved_on: 2026-11-10`, `approved_by:
"operator directive: finish P0-P11 of docs/product/INTENT-TO-PLACED-RTL-COMPLETION-PLAN.md"`,
`selection_rule`: only workloads already present in the checkout are approved;
nothing is resized, sampled down or invented) `[PROVEN: docs/product/evidence/release-workloads-20261110.json:1-6]`.

**Honesty law for this document**

- Every factual claim is tagged:
  - `[PROVEN: path:line]` — read in the file at that line.
  - `[COMPUTED]` — recomputed from file bytes during this pass (2026-11-10); the
    command is reproducible and the arithmetic is shown.
  - `[INFERRED]` — reasoned from read files but not directly stated by any one
    of them. Inference chains state their premises.
  - `[ABSENT]` — looked for, not present. Absence is recorded, never papered over.
  - `[OPEN]` — not resolvable with the files in this checkout.
- No number in this document was invented. Where a value does not exist
  anywhere in the tree, the text says so.
- `docs/product/MILESTONE-14-PRODUCTION-RTL-20261110.md` is untracked and was
  observed to change on 2026-11-10 (mtime 15:07); the figures cited here are
  from the 15:07 read. `docs/product/evidence/release-workloads-20261110.json`
  and all 17 entry files were byte-checked this pass against the pin's
  sha256s: all 17 match.

## 0. The pinned full-size acceptance case (not one of the 17 — the target they all serve)

`release-workloads-20261110.json:7-15` pins the full-size acceptance case:
revision `p-fd7e5e31be77-r02`, `design_hash sha256:ab7bce8f71b5ed4fde4101ee80a60b6c69c16989d966f0f9096dd6d76ad392f0`,
74 agents / 81 routers / 8 VCs / 162 shared links, evidence dir
`docs/product/evidence/mixtral-74-81-8-162/`
`[PROVEN: docs/product/evidence/release-workloads-20261110.json:7-15]`.
`RTL-FINAL-CLOSEOUT-STATUS.md:10` records the same pin (128-bit flits) and
keeps P2 OPEN `[PROVEN: docs/product/RTL-FINAL-CLOSEOUT-STATUS.md:10,38]`.
The pin file itself notes the audit D-06 correction: an earlier doc said
"16 approved workloads"; the JSON on disk says **17**
`[PROVEN: docs/product/INTENT-TO-PLACED-RTL-20261110-AUDIT.md:55,160]`.

The two evidence files were read in full this pass:

**Revision `revision-p-fd7e5e31be77-r02.json`** (single-line JSON, cited
`revision:1`):

- `design.agents`: 64 `compute_tile` + 8 `hbm_controller` + 2 `nic` = **74** `[PROVEN: revision:1]`
- `workload`: `model_family: mixture_of_experts`, `model_name: moe-8x7b`,
  `parallelism {dp:1, ep:8, pp:1, tp:8}`, `serving_mode: mixed`
  `[PROVEN: revision:1]`
- `locked_derived`: `certificate_overall: PASS`, `routing: DOR_GEC_MECS`,
  `vc_count: 8` `[PROVEN: revision:1]`
- `requirements` (traffic classes, declared on the design):
  - `tp_collective` — `qos_class: latency_critical`, `latency_ceiling_cycles:
    100000.0`, `bandwidth_floor_gbps: null`, **`binding: true`** `[PROVEN: revision:1]`
  - `ep_dispatch` — `qos_class: bandwidth`, `bandwidth_floor_gbps: 25.0`,
    `latency_ceiling_cycles: null`, `binding: false` `[PROVEN: revision:1]`
- Certificate obligations all PASS, including `DEADLOCK_FREE` via
  `shared-resource-cdg/v1`: 1,944 nodes / 648 edges, no cycle in the concrete
  (resource, VC) dependency graph, `routing_class: DOR_GEC_MECS`;
  `ROUTE_COMPLETE` 6,561 entries over 81 routers; `FABRIC_DAG_VALID`;
  `PACKET_FORMAT_VALID` (128-bit flits, VC 8) `[PROVEN: revision:1]`
- `compilation.compiled_system.scopes` marks `domain_execution: NOT_MODELED`,
  `transactions: NOT_MATERIALIZED`, `normalization_refusal`: "legacy route
  transit transitions differ from the VC-assignment projection … must be
  resolved in Phase B, never guessed" `[PROVEN: revision:1]` — i.e. the pin is a
  compiled *design* certificate, not an RTL qualification.

**Topology `topology-p-fd7e5e31be77-r02.json`** (single-line JSON, cited
`topology:1`):

- `family: gec_mecs`, `counts {endpoints:74, routers:81, seats:81,
  shared_links:162, channels:0}`, `planes: ["d"]`, `island_columns: []`
  `[PROVEN: topology:1]`
- 81 routers, every `seat_capacity: 1` `[COMPUTED]`
- 74 endpoints: compute tiles on routers 0–63, HBM controllers on routers
  64–71, NICs on routers 72–73; **routers 74–80 carry no endpoint**
  `[COMPUTED]`
- **162 shared links, every one 128-bit, every one tapped to exactly 8
  destinations, every one with `latency_cycles: 1`**; exactly 2 shared links
  originate at each of the 81 routers; total taps = 1,296 = 162 × 8
  `[COMPUTED; arithmetic 2·o·k² = 162 for o=1, k=9, d=k−1=8 destinations —
  matches `tracks/t3-topology/dse/tests/test_chipyard_gec.py` assertions quoted
  in `[PROVEN: docs/product/INTENT-TO-PLACED-RTL-P0-P1-STATUS.md:212]`]`
- Raw file sha256 (computed this pass, not in the pin):
  revision `51ebbc5429011b5f394cd216554d2cfc4022b3d5ae884facbdc4ca52380fef4a`,
  topology `4315ad69bab4035251ca1bb3fec6c2219fcc6ad0132452c4684269298d5d9a82`
  `[COMPUTED]`. The pin's own `design_hash` for the revision is
  `ab7bce8f…` and the two evidence files are the bytes hashed there
  `[PROVEN: docs/product/evidence/release-workloads-20261110.json:9,14]`.

### 0.1 The `tp_collective` / `payload_bytes=8192` question — exact finding

The brief asked for collectives "from `tp_collective` traffic class
`payload_bytes=8192` lines in the pinned mixtral-74-81-8-162 evidence **if
relevant**". Searched, with this result:

- `docs/product/evidence/mixtral-74-81-8-162/revision-p-fd7e5e31be77-r02.json`
  — **0 occurrences of `8192`**; the design declares the *class* binding
  (`tp_collective`, latency-critical, ≤ 100,000 cycles, binding) but the
  embedded `workload` block declares **no `collectives` array at all** — no
  kinds, no payloads, no dimensions `[PROVEN: revision:1; grep for `8192` →
  0 hits]`.
- `docs/product/evidence/mixtral-74-81-8-162/topology-p-fd7e5e31be77-r02.json`
  — **0 occurrences of `8192`** `[PROVEN: topology:1; grep → 0 hits]`.
- The only `payload_bytes=8192, traffic_class="tp_collective"` pairs in the
  checkout are in **debug tooling, not the pin**:
  `[PROVEN: scripts/complete_design.py:172]` (a `DENSE_TRANSFORMER`, tp=2,
  pp=1, ep=1, dp=1 `WorkloadV3` smoke request inside `make_family_request`)
  and `[PROVEN: scripts/reproduce_slice.py:31]` (the same request bound to
  `MeshIntent(side_length=2)` for a slice reproduction). Neither is the
  Mixtral workload; neither is the release; both are 2-tile debug shapes
  `[PROVEN: scripts/complete_design.py:146-173; scripts/reproduce_slice.py:17-36]`.
- The nearest real **8,192-byte payload** in approved material is in a
  *pinned approved entry*: `llama31-8b-tp4-collectives` reports decode
  all-reduce `tensor_shape_per_rank [1,4096]`,
  `payload_bytes_per_rank_per_call: 8192` (prefill: 65 all-reduces @ 1,048,576
  B; decode: 8,255 all-reduces @ 8,192 B; gathers 1 + 127 @ 64,128 B,
  dtype-assumed) `[PROVEN: tracks/t3-topology/data/public-inference/llama31-8b-tp4/collectives.json:1]`.
  The capture carries no `traffic_class` field of its own; binding it to
  class `tp_collective` rests on the lowering law below plus the dense-family
  pattern, and is **[INFERRED]**, not a field of the file.
  Its `element_size_bytes: 2` basis and the count interpretation are recorded
  in that file's `count_scope_verification` block `[PROVEN: same file:1]`.
- Lowering law if/when a MoE/dense workload declares its collectives:
  `ALLREDUCE → RING`, `ALLGATHER → RING`, `REDUCESCATTER → RING`,
  `ALLTOALL → DIRECT`, `BROADCAST → ROOT_FANOUT`
  `[PROVEN: tracks/t3-topology/dse/veritx_dse/workload/collectives.py:13-19]`;
  family patterns derive `tp_collective` (dense, MoE), `ep_dispatch`
  (MoE, all-to-all), `ep_combine` (MoE, all-to-all), `activation_gather`
  (diffusion), `halo_exchange` (CNN) — `custom` declares nothing by design
  `[PROVEN: tracks/t3-topology/dse/veritx_dse/workload/family_collectives.py:87-107]`;
  `trace_to_v3` refuses to *infer* `model_family`, `dimension`, or
  `traffic_class` — they must be declared `[PROVEN:
  tracks/t3-topology/dse/veritx_dse/workload/trace_to_v3.py:26-40 (docstring
  law) and :185-198 (enforced by required arguments/refusals)]`.
- None of the 17 approved entries is an LLMServingSim trace, so
  `trace_to_v3.workload_v3_from_trace` applies to **zero** of them
  `[INFERRED: types — the adapter consumes canonical trace artifacts from
  LLMServingSim-dialect rows; the pinned captures are CSVs/JSONL events with
  no `comm_ops()` rows; checked both directories]`.

**Net:** the Mixtral pin carries class-level bindings (`tp_collective`
ceiling 100,000 cycles, binding; `ep_dispatch` 25 GB/s floor, non-binding) and
a GEC-MECS route/VC certificate; it does **not** carry collective payload
bytes, and the string `8192` does not occur in it. The 8192 figure is real but
belongs to the Llama-3.1-8B TP=4 capture (decode all-reduce), not to the
Mixtral revision.

## 1. Topology-family quick reference (stage authority)

Stage claims below are quoted from the registry; `QUALIFIED=YES` is qualified
*per its note*, not a blanket release claim.

| Family | Role | Authorable | Materializable | Qualified note | [PROVEN] |
|---|---|---|---|---|---|
| mesh | USER_FAMILY | YES | YES (MESH→MESH) | mesh-DOR single-class, MC multi-class, class-VC subsets | `docs/product/topology-family-registry.yaml:53-65` |
| torus | USER_FAMILY | YES | YES | native 2-VC odd-side DOR only; even sides refused (midpoint ties); dateline VC floor derived even for cycle-free requests | `docs/product/topology-family-registry.yaml:66-78` |
| concentrated_mesh | USER_FAMILY | YES | YES (c=2/c=4, DOR_XY, square) | qualified envelope: square k×k, uniform seats 2 or 4, no express links | `docs/product/topology-family-registry.yaml:79-91` |
| gec (mesh mode) | RESEARCH | YES | **NO** (plain gec row) | gec_mesh64 runs CERTIFIED_BOOKSIM_MESH_DOR_XY_V1; EXPRESS product-wired via AnyNet | `docs/product/topology-family-registry.yaml:108-124` |
| gec_mecs | RESEARCH | YES | YES | **READY**: renders CERTIFIED_BOOKSIM_GEC_MECS_V1, live flit conservation, measured latency; multi-class binds full tap/VC envelope | `docs/product/topology-family-registry.yaml:138-150` |
| gec_express | RESEARCH | YES | YES | p2p express; AnyNet profile; o=k−1 groups, d=1 | `docs/product/topology-family-registry.yaml:164-176` |
| gec_hybrid | RESEARCH | YES | YES | 4×4 c=1 o=1 d=3 six-VC probe; candidate-union proof, **not** an escape theorem | `docs/product/topology-family-registry.yaml:151-163` |
| srota | RESEARCH | YES | YES | shipped srota32 preset compiles/certifies; row-first hop rule differentially qualified | `docs/product/topology-family-registry.yaml:177-189` |
| fat_tree | USER_FAMILY | YES | YES | graph-backed CUSTOM; ANYNET_MIN_HOPS; fattree16_anynet conserved; WIRED YES | `docs/product/topology-family-registry.yaml:125-137` |
| flatfly | USER_FAMILY | YES | YES | FLATFLY_MIN sealed; k=4/n=2 k/n solved from artifact; WIRED PARTIAL | `docs/product/topology-family-registry.yaml:190-205` |
| ring_native | USER_FAMILY | YES | YES | RingIntent(64); RING_DATELINE 2 VCs; 4032-pair legal-choice union | `docs/product/topology-family-registry.yaml:230-242` |
| tree4_native | USER_FAMILY | YES | YES | Tree4Intent(4,3); 28 routers; TREE4_NCA union | `docs/product/topology-family-registry.yaml:243-255` |
| fly_native | USER_FAMILY | YES | YES | FlyIntent(4,3); 48 routers staging law | `docs/product/topology-family-registry.yaml:256-268` |
| qtree_native | USER_FAMILY | YES | YES | QTreeIntent(4,3); 21 routers; NCA differential | `docs/product/topology-family-registry.yaml:269-281` |
| ring (fixture) | TEST_FIXTURE | **NO** | YES | minimal 4-node graph fixture; not user intent | `docs/product/topology-family-registry.yaml:92-107` |
| dragonfly | RESEARCH | **NO** | **NO** | config only (`dragonfly16.cfg`, `booksim: dragonflynew`); PARTIAL projection; not RTL-bindable | `docs/product/topology-family-registry.yaml:218-229` |
| tree4_native / qtree (structured) | RESEARCH | YES | YES | structured graph + AnyNet; not native BookSim Tree4 | `docs/product/topology-family-registry.yaml:282-309` |
| custom | USER_FAMILY | YES | YES | TopologyIR explicit graph; ROUTABLE/QUALIFIED PARTIAL | `docs/product/topology-family-registry.yaml:310-323` |

RTL reality check (this tree, this date): L3 (workload-driven RTL qualification
with the 17 pinned workloads) is **✗ for all 14 families**; L0/L1 exist for 8;
L2 graph-binding witnesses exist for 13 (KNCube unbound); none of the 17 pinned
entries has ever carried a pinned workload through RTL
`[PROVEN: docs/product/MILESTONE-14-PRODUCTION-RTL-20261110.md:20-37]`.
Research-lane single-flit prototypes that pass all-pairs include mesh, torus
K=5/K=8, ring, flatfly, fat_tree4, fattree16_anynet, GEC Express, GEC MECS16
(shared-wire unicast; **no multicast packet-header semantics**), Tree4-native,
Fly-native, QTree-native, structured dragonfly4, and native dragonflynew
k=2,n=1 (centralized, single-flit) `[PROVEN: docs/research/RTL-TOPOLOGY-ACCEPTANCE-MATRIX.md:70]`.

## 2. The 17 approved entries, one row each

Legend: **tp/pp/ep/dp** are read from the request document when present, else
"—" (not declared; captures carry no parallelism fields). **Collectives** are
quoted with kind/dimension/payload where declared. **Bytes/class** are
`[COMPUTED]` from the file's `traffic_profiles`/rows. **Sha256** is the pin's
value, verbatim, and was re-verified against the file bytes this pass.

### 2.1 `gr00t-n16-h100-measured` — request — sha256 `18eeaed2d18ea857b7db5b353f1301b6abd390ee90c2fb13bda3c5c38506654f` (`release-workloads-20261110.json:35-41`)

- File: `tracks/t3-topology/examples/gr00t_n16_h100_measured-v4.json` (verified byte-identical)
- Questions / limits: network time; topology sensitivity — "measured host capture; not an end-to-end application runtime" `[PROVEN: docs/product/evidence/release-workloads-20261110.json:38-40]`
- Model family/name: `custom` / `gr00t-n1.6-h100-measured`; computed stage durations are the **measured H100 80GB** notebook outputs (data prep 4.72±0.72 ms, backbone 37.96±2.80 ms, action head 94.28±5.95 ms; TensorRT E2E 54.59 ms; torch.compile 69.38 ms; n1d6 branch) `[PROVEN: tracks/t3-topology/examples/gr00t_n16_h100_measured-v4.json:2]`
- tp/pp/ep/dp: **tp=8, pp=1, ep=1, dp=1** `[PROVEN: same file:6-10]`
- Collectives: **none declared** (`collectives: []`) `[PROVEN: same file:12]`
- Bytes/class `[COMPUTED]`: camera_ingest 1 row 196,608 B (rank 0→1);
  vision_tokens 4 rows 65,536 B each = 262,144 B (rank 1→2,3,4,5);
  action_tokens 4 rows 20,480 B each = 81,920 B (ranks 2,3,4,5→6);
  total 540,672 B; no class requirement, no QoS binding `[PROVEN: file:14-24; requirements: [] — same file]`
- Agents: 8 compute_tile + 1 hbm_controller; 256-bit AXI; 1 GHz; 4 nm
  `[PROVEN: same file:26-28,32,35,37]`
- Topology intended: **mesh 3×3, concentration 1, link_width 256** (authored, not derived) `[PROVEN: same file:31, answers "topology sensitivity" by direct substitution]`
- Would serve / resolution: **RESOLVED → mesh (built-in, USER_FAMILY, all stages YES)**. VLA-like TP workloads map to the built-in mesh/torus family — grounding: the authored fabric *is* a 3×3 mesh (`file:31`; byte-identical topology/noc block to the sibling N1.7 VLA template, which the flagship robotics guide compiles to PASS on a 3×3 mesh, 256-bit links, 1 GHz, 4 nm, and proposes ring/crossbar/4×4-mesh as fabric-change knobs) `[PROVEN: docs/product/nvidia-robotics-use-case.md:90-100,158-181; tracks/t3-topology/examples/gr00t_vla_robotics-v4.json:35,38-43]`; torus is the only other qualified built-in (odd-side 2-VC envelope) `[PROVEN: docs/product/topology-family-registry.yaml:66-78]`. GEC-MECS could accelerate the 1→4 vision fan-out as multidrop taps but is not what the template declares `[INFERRED; premises: alt map below + registry:138-150]`.

### 2.2 `gr00t-vla-robotics` — request — sha256 `bb7cc4078689d5433f79be0c5626e0b09b12a4b69bf17ee3e300de57640ac7f6` (`release-workloads-20261110.json:43-49`)

- File: `tracks/t3-topology/examples/gr00t_vla_robotics-v4.json` (verified)
- Questions / limits: network time; topology sensitivity — "modeled request; no fabricated measured score" `[PROVEN: docs/product/evidence/release-workloads-20261110.json:46-48]`
- Model family/name: `custom` / `gr00t-n1.7-vla-pipeline`; stage durations **modeled from the GR00T N1.7 Thor model card** (8.21 / 28.89 / 56.64 ms split into 4×14.16 ms; TensorRT bf16, 1 camera, 4 denoise steps); the 8-rank fabric, ranks, profiles and 1 kHz control stage are AUTHORED `[PROVEN: tracks/t3-topology/examples/gr00t_vla_robotics-v4.json:2]`
- tp/pp/ep/dp: **tp=8, pp=1, ep=1, dp=1** `[PROVEN: same file:8-11]`
- Collectives: **none declared** `[PROVEN: same file:12]`
- Bytes/class `[COMPUTED]`: camera_ingest 196,608 B (0→1); vision_tokens
  262,144 B (1→{2,3,4,5} ×65,536); action_tokens 81,920 B ({2..5}→6 ×20,480);
  control_out 128 B (6→7); total 540,800 B `[PROVEN: same file:14-24]`
- Binding requirements: `control_out` — `latency_critical`, ceiling
  **1,000,000 cycles** (1 ms @ 1 GHz), **binding**; `camera_ingest` —
  `bandwidth`, ceiling 33,000,000 cycles, floor **0.005 GB/s**, **binding**
  `[PROVEN: same file:31-33,35-41]`
- Topology intended: **mesh 3×3, concentration 1, link 256b, 1 GHz, 4 nm** `[PROVEN: same file:35-41]`
- Would serve / resolution: **RESOLVED → mesh (built-in); torus (built-in, qualified, odd side ✓ 3)**. The 1 kHz control deadline (control_out ≤ 1 ms) is the binding class; mesh-DOR is the qualified, lowest-risk RTL path; the measured 5-mix sweep ties mesh/torus (mixed 8,170/8,160; hotspot saturated tie) and puts mesh ahead of cmesh/fat-tree everywhere except saturation `[PROVEN: docs/product/traffic-profiles.md:153-168; docs/product/calibration.md:49-61]`. RTL status: composed mesh passed L0/L1 (38/38; 8×8: 13 scenarios) `[PROVEN: docs/product/MILESTONE-14-PRODUCTION-RTL-20261110.md:22]`; torus 3×3 L0/L1 ✓ `[PROVEN: same file:23]`; the flagship robotics demo compiles this exact VLA template to PASS on the 3×3 mesh `[PROVEN: docs/product/nvidia-robotics-use-case.md:158-181]` (note: that doc's prose cites a camera_ingest floor of 0.5 GB/s, while the template on disk declares 0.005 GB/s and a 33,000,000-cycle ceiling — the template file is the authority) `[PROVEN: tracks/t3-topology/examples/gr00t_vla_robotics-v4.json:32]`.
- Flagship entry (see §4).

### 2.3 `qwen3-moe-tp2-ep4-16tiles` — request — sha256 `f7df8bc5a210cd2b63d844ab3d955ea21450a61e7a541e80bac8621f7f24ec05` (`release-workloads-20261110.json:51-57`)

- File: `tracks/t3-topology/examples/qwen3_moe_tp2_ep4_16tiles-v4.json` (verified)
- Questions / limits: network time; collective schedule exposure — "request only; measured kernel slowdowns live in the public-inference capture" `[PROVEN: docs/product/evidence/release-workloads-20261110.json:54-56]`
- Model family/name: **`mixture_of_experts` / `Qwen/Qwen3-30B-A3B-Instruct-2507`** (its own `_comment`: "CANONICAL FULL-STACK ACCEPTANCE WORKLOAD (v4) … DECLARED compute … 48 layers … activation-only … pool assignment device = owner // 2 … Compute is DECLARED, not modelled") `[PROVEN: tracks/t3-topology/examples/qwen3_moe_tp2_ep4_16tiles-v4.json:2]`
- tp/pp/ep/dp: **tp=2, pp=1, ep=4, dp=1** (8 ranks) `[PROVEN: same file:1166-1172]`
- Collectives (declared, with payloads) `[PROVEN: same file:1143-1164]`:
  - TP **allreduce**, dimension TP, **payload 4,096 B**, class `tp_collective`
  - EP **alltoall**, dimension EP, **payload 2,048 B**, class `ep_dispatch`
  - EP **alltoall**, dimension EP, **payload 2,048 B**, class `ep_combine`
  - Lowering: ALLREDUCE→RING, ALLTOALL→DIRECT `[PROVEN: collectives.py:13-19]`;
    family pattern derives exactly these three classes for MoE
    `[PROVEN: family_collectives.py:94-107]`
- Binding requirement: `tp_collective` — `latency_critical`, ceiling
  **50,000 cycles**, **binding** `[PROVEN: same file:1127-1134]`
- Agents: 16 compute_tile + 4 hbm_controller + 2 nic = **22 endpoints**, 256-bit AXI tiles, 1 GHz, **7 nm**, link_width **64** `[PROVEN: same file:10,19,28,1112,1122,1125]`
- Migration provenance: `frozen_v3_autosize(endpoints=22,concentration=1) → side_length=5`, source `noc_config.topology_family=mesh`; source hash `95510ce4…` `[PROVEN: same file:1097-1108]` — the 5×5 mesh is a *derived* mesh, not hand-picked
- Memory demand: per-layer activation I/O only (4,096 B × 2 per layer-stage per
  owner; 96 stage rows over owners 0–7, `LOCAL:<pool>` pins, `device = owner // 2`);
  weights consumed as resident, deliberately NOT declared `[COMPUTED; premise PROVEN: same file:2 and stages throughout]`
- Topology intended: **mesh 5×5, concentration 1** (derived) `[PROVEN: same file:1139-1141]`
- Measured/projected execution (this exact fixture class): the Qwen3-30B-A3B
  TP2+EP4 acceptance ran **BookSim MC profile: 2,805 cycles**; **ASTRA TP2+EP4:
  3,050 cycles**; run QUALIFIED, LIMITED to schedule-window exposure (absolute
  latency NOT_ESTABLISHED); multi-class TP+EP classes both PASS (tp_collective;
  ep_dispatch + ep_combine); Ramulator PASS on the v4 declared compute
  (activation demand, **101,875 cycles**); COMPUTE: NOT MODELED; serving
  BLOCKED (no compatible design×cluster pair) `[PROVEN: docs/product/FULL-STACK-TRUTH-CLOSURE.md:52,54,82-89]`
  — note this evidence is the *acceptance program's* Qwen run, not a pinned
  re-run from this checkout this pass.
- Would serve / resolution: **RESOLVED → mesh (PROVEN executed) ; GEC-MECS
  (INFERRED best MoE match) ; torus (qualified, 5 ODD ✓)**. The Mixtral pin
  shows the release's own full-size MoE (moe-8x7b, tp=8 ep=8) certified on
  **GEC-MECS** with EP-dispatch binding (25 GB/s floor) `[PROVEN: revision:1 §0]`;
  `gec_mecs` is the only multidrop family with a READY row (live flit
  conservation; per-class tap/VC envelope) `[PROVEN: registry:138-150]`;
  dragonfly express wires are **NOT available** (`RECOGNIZED YES, AUTHORABLE NO,
  MATERIALIZABLE NO`) `[PROVEN: registry:218-229]`.
- Flagship entry (see §4).

### 2.4 `pi0-thor-modeled` — request — sha256 `4d15960793ecbd85c97d51f6ad557c04335ef56bde7b61c1eab0951787dbdf70` (`release-workloads-20261110.json:59-65`)

- File: `tracks/t3-topology/examples/pi0_thor_modeled-v4.json` (verified)
- Questions / limits: network time — "modeled request; not measured on Thor hardware" `[PROVEN: docs/product/evidence/release-workloads-20261110.json:62-64]`
- Model family/name: `custom` / `pi0-thor-modeled`; durations **MODELED by
  VLA-Perf** (pinned commit `1e2b9a7ef9d4188c7e1e2befbdc758222c60d760`): vision
  6.062 ms, VLM 20.303 ms, action 26.200 ms (10 flow steps × 2,619,993 ns),
  **E2E 52.565 ms**; all three stages **Mem-bound** `[PROVEN:
  tracks/t3-topology/examples/pi0_thor_modeled-v4.json:2;
  tracks/t3-topology/data/vla-perf/pi0_family_e2e_perf.csv (Thor row:
  6.062347412109375 / 20.303090413411457 / 26.199926932652797 /
  52.56536475817363, Mem/Mem/Mem) `[COMPUTED row lookup]]`
- tp/pp/ep/dp: **tp=8, pp=1, ep=1, dp=1** `[PROVEN: same file:8-11]`
- Collectives: **none declared** `[PROVEN: same file:12]`
- Bytes/class `[COMPUTED]`: camera_ingest 150,528 B (0→1); vision_tokens
  1,048,576 B (4×262,144, rank 1→2,3,4,5); action_latents 3,200 B (4×800,
  ranks 2,3,4,5→6); total 1,202,304 B `[PROVEN: same file:14-24]`; no class
  requirements declared `[PROVEN: same file: requirements []]`
- Topology intended: **mesh 3×3, concentration 1, link 256b, 1 GHz, 4 nm** `[PROVEN: same file:31,35-41]`
- Would serve / resolution: **RESOLVED → mesh (built-in); torus (built-in)**.
  Same VLA-like shape as §2.2 — the Thor-class modeled pipeline compiled to
  the same 3×3 mesh authored here; vla-perf confirms the model is
  memory/roofline-bound, not interconnect-bound, so fabric choice is a
  latency/p99 question, not a bandwidth question
  `[PROVEN: pi0_thor_modeled-v4.json:2; data/vla-perf/README.md (Thor rows Mem/Mem/Mem) `[COMPUTED]`]` `[INFERRED: mapping to built-in families — premises as in §2.2]`.

### 2.5 `switch-gen6-class` — request — sha256 `c2e7658187f6a48457ee3c6a05c69090dfaea13ae821437591451250cd3a92fd` (`release-workloads-20261110.json:67-73`)

- File: `tracks/t3-topology/examples/switch_gen6_class-v4.json` (verified)
- Questions / limits: network time; topology sensitivity — "class-level request; no device measurement" `[PROVEN: docs/product/evidence/release-workloads-20261110.json:70-72]`
- Model family/name: `custom` / `gen6-class-switch-fabric`; **AUTHORED
  HYPOTHETICAL** Gen-6-class 16-port switch (NOT a Switchtec model, NOT PCIe);
  ranks 0–7 host-port proxies, 8–15 SSD-port proxies; 16 compute_tile agents
  are fabric PORT endpoints; incast pair to SSD port 0 (rank 8);
  "multicast-equivalent duplicate-unicast fan-out"; 70/30 read/write by
  injected payload bytes `[PROVEN: same file:2]`
- tp/pp/ep/dp: **tp=16** (port index, not tensor parallelism — the schema has
  no switch role field, so ports occupy `tp`), pp=1, ep=1, dp=1
  `[PROVEN: same file:8]`
- Collectives: **none declared** `[PROVEN: same file:14]`
- Bytes/class `[COMPUTED]`: read_256k 56 rows = 14,680,064 B; read_4k 56 rows
  = 229,376 B; write_256k 24 rows = 6,291,456 B; write_4k 24 rows = 98,304 B;
  **read = 14,909,440 B, write = 6,389,760 B, read ratio = 0.700 exactly**;
  incast_ssd0 2 rows = 524,288 B (ranks 0,1→8, 262,144 B each);
  multicast_equiv 8 rows = 524,288 B (rank 0→ranks 8–15, 65,536 B each);
  grand total 22,347,776 B `[PROVEN: same file:19-973 (read/write rows), 979-1039
  (incast/multicast rows); ratio COMPUTED]`
- Binding requirements: `incast_ssd0` — `latency_critical`, ceiling
  **10,000,000 cycles**, binding; `multicast_equiv` — `bandwidth`, ceiling
  10,000,000 cycles, floor **0.001 GB/s**, binding `[PROVEN: same file:1040-1052]`
- Topology intended: **mesh 4×4, concentration 1, link 256b, 1 GHz, 4 nm**
  (16 routers, exact 16-seat fit) `[PROVEN: same file:1066-1081]`
- Would serve / resolution: **RESOLVED → mesh (authored, exact seat fit);
  torus is DISQUALIFIED at 4×4 (even side refused); GEC-MECS is the only
  express/multidrop candidate for `multicast_equiv` but RTL has *not*
  established multicast packet-header semantics on MECS**
  `[PROVEN: docs/product/topology-family-registry.yaml:66-78 (even-side
  refusal), :138-150 (MECS READY)]; [PROVEN: docs/research/RTL-TOPOLOGY-ACCEPTANCE-MATRIX.md:70 ("does not establish … multicast packet-header semantics")]`.
  Hotspot/saturation behavior (incast to one destination): all four swept
  topologies within 1.5% — topology barely matters at saturation
  `[PROVEN: docs/product/traffic-profiles.md:155-167]`.
- Flagship entry (see §4).

### 2.6 `cal26-qwen3-30b-ep4-kernel-slowdowns` — capture — sha256 `cf34869fb9cc26364c1821c35e30f2510d7120994fc84c4c9ffabb8126975960` (`release-workloads-20261110.json:75-81`)

- File: `tracks/t3-topology/data/public-inference/cal26-qwen3-30b-ep4/inference-kernel-slowdowns.csv` (verified; 469 rows + header)
- Questions / limits: kernel slowdown distribution — "public capture; source attribution in adjacent README" `[PROVEN: docs/product/evidence/release-workloads-20261110.json:78-80]`
- Model/deployment: **Qwen3-30B DeepEP inference, `EP=4 vLLM` (group
  `DeepEP(20)`), kernel classes o_proj GEMM (339), MoE GEMM (16),
  FA3 132 SM (22), FA3 104 SM (22), Elementwise (70)**; workload=inference
  for all 469 rows `[COMPUTED; columns PROVEN: file:1]`
- Measured distribution `[COMPUTED]`: slowdown n=469, min **1.0141**, max
  **1.5183**, mean **1.2189**, median **1.2291**
- Parallelism visible in capture: **EP=4** only (no tp/pp/dp fields) `[PROVEN: file column "parallelism"="EP=4 vLLM" ×469]`
- Collectives: none (per-kernel slowdowns, not message events) `[PROVEN: file header row]`
- tp/pp/ep/dp: ep=4 extractable; tp/pp/dp **[ABSENT]**
- Would serve / resolution: **UNRESOLVABLE as a fabric workload — no topology
  appears in the capture** (it is SM/kernel timing on one node; the adjacent
  README attributes source to CAL26-NCCL-GEMM-data / Zenodo v1.0.0 CC-BY-4.0)
  `[PROVEN: tracks/t3-topology/data/public-inference/README.md]`. The
  underlying inference shape is Qwen3-30B **EP4** → same family reasoning as
  §2.3 for any fabric study built on it `[INFERRED: premise = §2.3 + capture
  EP=4 string]`. Not eligible for `trace_to_v3` (no comm rows) `[INFERRED]`.
- RTL: irrelevant to routing law; would only enter via an EP4 serving model
  `[INFERRED]`.

### 2.7 `cal26-qwen3-30b-ep4-nvlink-counters` — capture — sha256 `be275dec0c90b98c68a73e147dce2d1fad467254abd75ec5a62b3bb3030b7810` (`release-workloads-20261110.json:83-89`)

- File: `tracks/t3-topology/data/public-inference/cal26-qwen3-30b-ep4/nvlink-counter-samples.csv` (verified; 350 rows + header)
- Questions / limits: link counter samples — "public capture; **not a topology-specific measurement**" `[PROVEN: docs/product/evidence/release-workloads-20261110.json:86-88]`
- Model/deployment: same CAL26 DeepEP Qwen3-30B EP=4 vLLM run; panels:
  GEMM alone (51), Attn alone (43), Attn 104 SM (51), GEMM 112 SM (46),
  DeepEP alone (40), Attn ∥ DEP (53), GEMM ∥ DEP (66) `[COMPUTED]`
- Measured `nvlink_GBps` is of order **1e-12 … 6.2e-07** (DeepEP alone
  1.03e-07…4.59e-07, mean 3.99e-07; Attn ∥ DEP mean 3.59e-07, max 6.19e-07;
  GEMM ∥ DEP mean 3.02e-07, max 5.77e-07) `[COMPUTED]` — and the adjacent README states the upstream
  exporter divides its nvlink column by 1e9 and the raw unit/scale is
  **unresolved**; these values must not be used as a calibrated bandwidth
  target `[PROVEN: tracks/t3-topology/data/public-inference/README.md]`
- Parallelism: EP=4 implied by panel names (DeepEP); tp/pp/dp **[ABSENT]**
- Collectives: none (CUPTI counters, not message events) `[PROVEN: file header row]`
- Would serve / resolution: **UNRESOLVABLE as a fabric workload** (host
  NVLink counters; no NoC hop graph, no classes, no VC data). The MoE/EP4
  shape maps to §2.3 reasoning only by analogy `[INFERRED]`. The pin itself
  limits it to "not a topology-specific measurement" — binding it to any RTL
  family would be fabrication `[PROVEN: release-workloads-20261110.json:86-88]`.

### 2.8 `llama31-8b-tp4-collectives` — capture — sha256 `761dc54d764c360dcadccbc80c8a8c7624b1addeb140008bb177fc498446cef0` (`release-workloads-20261110.json:91-97`)

- File: `tracks/t3-topology/data/public-inference/llama31-8b-tp4/collectives.json` (verified)
- Questions / limits: collective size distribution — "public capture; projection method recorded in projection-results.md" `[PROVEN: docs/product/evidence/release-workloads-20261110.json:94-96]`
- Model family/name: **Llama-3.1-8B** (`dense_transformer` in the codebase's
  `ModelFamily` enum — that mapping is [INFERRED] from "Llama-3.1-8B"; the
  capture itself states only the model name); vLLM 0.8.5.post1,
  PyTorch 2.6, NCCL 2.21.5, custom allreduce disabled; H100 94 GB ×4,
  intra-node NVLink, OSC Cardinal; 1 request, prefill 128 / decode 128
  `[PROVEN: tracks/t3-topology/data/public-inference/llama31-8b-tp4/collectives.json:1]`
- Parallelism: **tensor_parallel, world_size 4, ranks [0..3]**; strategy
  `tensor_parallel` → tp=4; pp/ep/dp not stated — dp=1 implied by
  world_size=4 with tp=4 but **not declared** `[PROVEN: same file:1; dp=1 INFERRED]`
- Collectives (paper-reported counts, Table III/IV of arXiv:2507.14392;
  count interpretation supported by the paper's TP-invariance statement, but
  **no raw rank events**; Gather dtype assumed) `[PROVEN: same file:1]`:
  - prefill all_reduce ×**65**, shape [128,4096], **1,048,576 B/call**
  - decode all_reduce ×**8,255**, shape [1,4096], **8,192 B/call** ← the only pinned 8192 payload
  - prefill gather ×1, [32064], 64,128 B/call (dtype assumed)
  - decode gather ×127, same shape/bytes (dtype assumed)
  - Lowering law: ALLREDUCE→RING, ALLGATHER→RING `[PROVEN: collectives.py:13-16]`
- Would serve / resolution: **UNRESOLVABLE as an on-package fabric workload —
  the captured fabric is host NVLink, out of the 14 RTL families' scope.**
  The only run recorded is a *synthetic projection* on a **2×2 BookSim mesh,
  DOR, 256-bit channels, 2 VCs**: 1,639,584 packets, avg flit latency
  **16.7592 cycles** (min 12, max 203), avg hops **2.49508**, ~0.9191 flits/cyc;
  execution-smoke only, **not a topology ranking** `[PROVEN: tracks/t3-topology/data/public-inference/llama31-8b-tp4/projection-results.md]`.
  For any RTL binding, dense TP all-reduce lowers to a ring world
  (`ring_native`, 64-router RING_DATELINE qualified — size mismatch here) or a
  mesh catalog path (llama-dense-8b-64tiles: mesh-DOR EVALUATED)
  `[PROVEN: docs/product/CAPABILITY-CLOSURE-2026-09.md:105-112]`; binding
  *this capture* to either would be invention.
- RTL: none applicable to the capture itself `[PROVEN: same projection-results.md]`.

### 2.9 `gr00t-g1-apple-to-plate-events` — capture — sha256 `0e4001d4554ae9d0519b336e5bdf2085b571ce5a6f4039c66daa7c2b4c7d8a96` (`release-workloads-20261110.json:99-105`)

- File: `tracks/t3-topology/data/public-robotics/gr00t-g1-apple-to-plate/episode_000000.events.jsonl` (verified; 684 rows)
- Questions / limits: episode event timing — "public capture; upstream requirements in requirements-source.txt" `[PROVEN: docs/product/evidence/release-workloads-20261110.json:102-104]`
- Content: Unitree G1, subset `unitree_g1.LMPnPAppleToPlateDC`, episode 0;
  **683 frames + 1 metadata row**; 50 Hz, **13.64 s**; state/action 43×float64
  = **344 raw value bytes each**; 683 H.264 demux packets; task "pick up the
  apple, walk left, and place the apple on the plate" `[PROVEN: file:1 and row counts COMPUTED]`
- Model family: **not stated** (robotics dataset ledger, not a model) `[PROVEN: file:1 `evidence_boundary`]`
- Parallelism: **none** · Collectives: **none** · Traffic classes: none
- Would serve / resolution: **UNRESOLVABLE — no network is modeled.** The
  ledger says so itself: "No endpoints, packetization, network timing, or
  hardware performance are claimed" `[PROVEN: file:1]`. A bounded diagnostic
  BookSim run exists in the pipeline (`gr00t_pipeline.py … run-booksim`,
  authored hypothetical placement camera 0→1, state 2→1, action 1→3, 32-byte
  flits, ≤16-flit packets, legacy mesh) — a smoke projection, **not** a
  certified fabric model `[PROVEN: tracks/t3-topology/data/public-robotics/gr00t-g1-apple-to-plate/README.md]`.
- RTL: not applicable `[PROVEN: same README]`.

### 2.10 `lerobot-smolvla-trace` — capture — sha256 `5d91310c6fd84de191bb33ef7ca4cccf1b06d232033dd9733d88804af60052fa` (`release-workloads-20261110.json:107-113`)

- File: `tracks/t3-topology/data/lerobot/smolvla_trace.jsonl` (verified; 8 rows)
- Questions / limits: trace replay timing — "public capture; model notes in SMOLVLA.md" `[PROVEN: docs/product/evidence/release-workloads-20261110.json:110-112]`
- Content: **real CPU run** (not synthetic): LeRobot 0.6.1 SmolVLAPolicy,
  `lerobot/smolvla_base`, SmolVLM2-500M-Video-Instruct backbone, 450,046,176
  params, 10 flow-matching denoise steps, chunk 50, 3 cameras, CPU-only
  (Ryzen 7 7445HS); 2 timed calls × 4 stages `{preprocessing, policy,
  postprocessing, total}`; policy median 2,628.07 ms over the 2 timed calls
  (call 1: 2,794.36 ms), policy ≈ 99.98% of total `[PROVEN:
  tracks/t3-topology/data/lerobot/SMOLVLA.md:174-179; file:2; row counts COMPUTED]`
- Model family: SmolVLA = VLM backbone + flow-matching action expert;
  **not** `mixture_of_experts`, no TP/EP/PP/DP declared → **family fields
  ABSENT**
- Parallelism: **none declared** · Collectives: **none** · Bytes/row payload
  2,359,296 B (image 256×256, chunk 50) `[PROVEN: file:1]`
- Would serve / resolution: **UNRESOLVABLE — no fabric, no ranks, no
  parallelism.** Single-node CPU policy invocation. Any fabric assignment
  would be invented `[PROVEN: SMOLVLA.md; file:1]`.
- RTL: not applicable `[PROVEN: SMOLVLA.md]`.

### 2.11 `lerobot-smolvla-vla-trace` — capture — sha256 `eea4d4f59fbe6d63d3a508df2b31059c611ac790e0f88b50227f2b48de444a94` (`release-workloads-20261110.json:115-121`)

- File: `tracks/t3-topology/data/lerobot/smolvla_vla_trace.jsonl` (verified; 15 rows)
- Questions / limits: trace replay timing — "public capture; model notes in SMOLVLA_VLA.md" `[PROVEN: docs/product/evidence/release-workloads-20261110.json:118-120]`
- Content: same checkpoint/host as §2.10, **stage split**: vision_encoder
  1,102.66 ms (×3 cameras embedded), vlm_prefill 151.94 ms,
  action_denoise_step_0..9 (10 rows), action_denoise_total, policy_total ≈
  2,794 ms; one timed call × 15 stages `[PROVEN:
  tracks/t3-topology/data/lerobot/SMOLVLA_VLA.md; file:1]`
- Parallelism: **none declared** · Collectives: **none** · Payload 2,359,296 B
  (file:1) · `num_denoise_steps: 10`
- Would serve / resolution: **UNRESOLVABLE — no fabric, no ranks.** Same
  conclusion as §2.10 `[PROVEN: same SMOLVLA_VLA.md]`.
- RTL: not applicable.

### 2.12 `lerobot-act-pusht-trace` — capture — sha256 `eb3f58a144796079b7d49f9613f816819b5935a3c9b64a81399bdee71bafb7ed` (`release-workloads-20261110.json:123-129`)

- File: `tracks/t3-topology/data/lerobot/act_pusht_trace.jsonl` (verified; 8 rows)
- Questions / limits: trace replay timing — "public capture" `[PROVEN: docs/product/evidence/release-workloads-20261110.json:126-128]`
- Content: real CPU run, LeRobot 0.6.1 **ACTPolicy**, PushT-shaped synthetic
  observation, 96×96, chunk 100; 2 timed calls × 4 stages (preprocessing
  0.115 ms, policy 30.65 ms, postprocessing, total); policy ≈ 99% of wall
  time; CPU-only host `[PROVEN: tracks/t3-topology/data/lerobot/README.md; row counts COMPUTED]`
- Model family: ACT (action-chunking transformer); **no TP/EP/PP/DP** →
  **family fields ABSENT** · Collectives: **none** · Payload 110,592 B
  `[PROVEN: file:1]`
- Would serve / resolution: **UNRESOLVABLE — no fabric, no ranks, no
  parallelism** `[PROVEN: README; file:1]`.
- RTL: not applicable.

### 2.13 `vla-perf-network-latency-kvcache` — capture — sha256 `8c90e5c478235943b980d2b524b7250d1ed66f7c8a577e56b6807be2cca40a8f` (`release-workloads-20261110.json:131-137`)

- File: `tracks/t3-topology/data/vla-perf/network_latency_bidirectional_kvcache.csv` (verified; 66 rows + header)
- Questions / limits: network latency — "public capture; license in LICENSE-vla-perf" `[PROVEN: docs/product/evidence/release-workloads-20261110.json:134-136]`
- Content: VLA-Perf analytical model (pinned commit `1e2b9a7e…`, MIT subtree;
  README labels these **MODELED, not measured**); 11 network profiles
  (4G LTE, 5G NR SA, WiFi 5/6/6E/7, DC 1/10/25/100/400GbE) × return types
  (Pi0 Gemma-2B, Pi0.6 Gemma-3-4B, OpenVLA-7B) × 2 image configs (224/512,
  0.1× compressed); robot→server image upload + server→robot KV-cache
  download; Pi0 kvcache download = **4,718,592 B** (Gemma-2B, seq 256, fp16)
  `[PROVEN: tracks/t3-topology/data/vla-perf/README.md; file:2 row; COMPUTED row sweep: 66 rows, 11 networks × 3 models × 2 configs]`
- Parallelism: **none** (WAN client→server) · Collectives: **none** · Model:
  π0 / π0.6 / OpenVLA — VLA family, but no NoC
- Would serve / resolution: **UNRESOLVABLE / NOT APPLICABLE — this is a
  wide-area-network latency model, not an on-package/on-chip fabric.** None of
  the 14 RTL families carries WAN semantics; the rows say nothing about hops,
  VCs, or endpoints-to-routers. License: MIT (subtree) / Apache-2.0 (root)
  `[PROVEN: tracks/t3-topology/data/vla-perf/README.md; LICENSE-vla-perf]`.
- RTL: not applicable — **do not bind**.

### 2.14 `vla-perf-network-latency-images` — capture — sha256 `96ac194c1627de6541f342ad01d0e4379ecb4d18b2c5c25b0978b3588cafbf74` (`release-workloads-20261110.json:139-145`)

- File: `tracks/t3-topology/data/vla-perf/network_latency_images.csv` (verified; 88 rows + header)
- Questions / limits: network latency — "public capture; license in LICENSE-vla-perf" `[PROVEN: docs/product/evidence/release-workloads-20261110.json:142-144]`
- Content: same provenance; 11 networks × 4 resolutions (224/384/512/1024) ×
  raw/compressed; 224×224 uint8 = **150,528 B** (0.1× → 15,052 B); effective
  size inflates ×1.05 (150,528 → 158,054.4 B) — i.e. the table *models*
  ~5% transport overhead explicitly `[PROVEN: same README; file:2 row; COMPUTED]`
- Parallelism: **none** · Collectives: **none** · Model: generic π0-class VLA
- Would serve / resolution: **UNRESOLVABLE / NOT APPLICABLE — WAN image
  upload model, no on-package fabric content** `[PROVEN: README; file rows]`.
- RTL: not applicable — **do not bind**.

### 2.15 `vla-perf-validation` — capture — sha256 `f807142651a81bea49b7fbb06fcf0fd3d6a9549b4fe9252b3dc02c6a6128f2d9` (`release-workloads-20261110.json:147-153`)

- File: `tracks/t3-topology/data/vla-perf/perf_validation_vs_realtime_vla.csv` (verified; 6 rows + header)
- Questions / limits: validation against realtime VLA — "public capture; license in LICENSE-vla-perf" `[PROVEN: docs/product/evidence/release-workloads-20261110.json:150-152]`
- Content: VLA-Perf's own roofline-vs-realtime check: RTX_4090 and RTX_5090,
  1–3 views, bf16, seq 256; roofline 14.67–22.48 ms vs real 20.0–27.3 ms;
  roofline achieves 73.3–82.3% of real
  `[PROVEN: file:2-4; COMPUTED]`
- Parallelism: **none declared** (single-GPU rows) · Collectives: **none**
- Would serve / resolution: **UNRESOLVABLE / NOT APPLICABLE — single-device
  roofline validation, no fabric** `[PROVEN: file rows; README]`.
- RTL: not applicable.

### 2.16 `vla-perf-pi0-denoising` — capture — sha256 `6addcecbbd4b88303fdede36ded833b4d0aaa8472c7b12c10ceb4ec2d6cdfb63` (`release-workloads-20261110.json:155-161`)

- File: `tracks/t3-topology/data/vla-perf/pi0_denoising_steps_action_lengths.csv` (verified; 75 rows + header)
- Questions / limits: denoising step shape — "public capture; license in LICENSE-vla-perf" `[PROVEN: docs/product/evidence/release-workloads-20261110.json:158-160]`
- Content: π0 sweep — **denoising steps 1/5/10/20/50 × action chunk
  5/25/50/100/250**, on B100 (25), Jetson_AGX_Thor (25), RTX_4090 (25), bf16;
  Thor 10-step × chunk-50 row: action 26.19993 ms, E2E 52.56536 ms,
  19.02 Hz — the row the `pi0-thor-modeled` template splits into 10 steps
  `[PROVEN: file row; tracks/t3-topology/examples/pi0_thor_modeled-v4.json:2; README]`
- Parallelism: **none declared** · Collectives: **none** · Model: π0
  (Gemma-2B VLM + flow-matching action expert)
- Would serve / resolution: **UNRESOLVABLE / NOT APPLICABLE — chip roofline
  sweep, no interconnect content** `[PROVEN: file; README]`. It *sizes* the
  π0 stage structure the VLA templates declare, nothing more.
- RTL: not applicable.

### 2.17 `vla-perf-pi0-family` — capture — sha256 `68e70df3ca4c7f1b8a5cb62acaa6e4d9f1b85a48c2ab1cd47b823561e2286206` (`release-workloads-20261110.json:163-169`)

- File: `tracks/t3-topology/data/vla-perf/pi0_family_e2e_perf.csv` (verified; 55 rows + header)
- Questions / limits: family end-to-end performance — "public capture; license in LICENSE-vla-perf" `[PROVEN: docs/product/evidence/release-workloads-20261110.json:166-168]`
- Content: π0 E2E roofline, **55 rows: A100_80GB (12), B100 (15), H100 (15),
  Jetson_AGX_Thor (10), RTX_4090 (3)** × chips 1/2/4 × batch 1..128;
  Comm-bound rows exist for multi-chip A100 (e.g. A100 80GB, 2 chips, batch 1:
  vision 2.0535 ms, **Comm**/Comp/Comm boundness) `[PROVEN: file rows; COMPUTED sweep]`
- Parallelism: chips column only (1/2/4); no tp/ep/pp/dp declared → **ABSENT
  as declared fields** (num_chips ≠ declared parallelism law) `[PROVEN: file header]`
- Collectives: **none** (roofline boundness labels, not message counts)
- Would serve / resolution: **UNRESOLVABLE as a fabric workload — no topology
  content; num_chips is a roofline axis, not a rank map.** The captured facts
  bound π0 as memory/comm-limbo per-chip, not any on-package fabric law
  `[PROVEN: file; README]`. License: MIT (subtree)
  `[PROVEN: LICENSE-vla-perf]`.
- RTL: not applicable.

### 2.18 Summary table — what resolves and what does not

| # | Entry | kind | Family fields | Collectives | Parallelism | Sha256 (verbatim) | Resolution |
|---|---|---|---|---|---|---|---|
| 1 | gr00t-n16-h100-measured | request | custom | none | tp8 pp1 ep1 dp1 | 18eeaed2d18ea857b7db5b353f1301b6abd390ee90c2fb13bda3c5c38506654f | mesh (authored) |
| 2 | gr00t-vla-robotics | request | custom | none | tp8 pp1 ep1 dp1 | bb7cc4078689d5433f79be0c5626e0b09b12a4b69bf17ee3e300de57640ac7f6 | mesh (authored) |
| 3 | qwen3-moe-tp2-ep4-16tiles | request | mixture_of_experts | allreduce/TP 4096 B; alltoall/EP 2048 + 2048 B | tp2 pp1 ep4 dp1 | f7df8bc5a210cd2b63d844ab3d955ea21450a61e7a541e80bac8621f7f24ec05 | mesh (derived, executed); gec_mecs (MoE) |
| 4 | pi0-thor-modeled | request | custom | none | tp8 pp1 ep1 dp1 | 4d15960793ecbd85c97d51f6ad557c04335ef56bde7b61c1eab0951787dbdf70 | mesh (authored) |
| 5 | switch-gen6-class | request | custom | none | tp16 pp1 ep1 dp1 (ports) | c2e7658187f6a48457ee3c6a05c69090dfaea13ae821437591451250cd3a92fd | mesh (authored); torus ✗ (even) |
| 6 | cal26-…-kernel-slowdowns | capture | Qwen3-30B EP4 (DeepEP) | none (kernels) | ep4 | cf34869fb9cc26364c1821c35e30f2510d7120994fc84c4c9ffabb8126975960 | ✗ unresolvable (no fabric) |
| 7 | cal26-…-nvlink-counters | capture | same EP4 run | none (counters) | ep4 | be275dec0c90b98c68a73e147dce2d1fad467254abd75ec5a62b3bb3030b7810 | ✗ unresolvable; scale unresolved |
| 8 | llama31-8b-tp4-collectives | capture | dense_transformer (Llama-3.1-8B) | 65+8255 allreduce; 1+127 gather | tp4 (NVLink host) | 761dc54d764c360dcadccbc80c8a8c7624b1addeb140008bb177fc498446cef0 | ✗ unresolvable; projection = 2×2 mesh smoke |
| 9 | gr00t-g1-apple-to-plate-events | capture | dataset ledger | none | none | 0e4001d4554ae9d0519b336e5bdf2085b571ce5a6f4039c66daa7c2b4c7d8a96 | ✗ unresolvable (no network) |
| 10 | lerobot-smolvla-trace | capture | SmolVLA (real CPU) | none | none | 5d91310c6fd84de191bb33ef7ca4cccf1b06d232033dd9733d88804af60052fa | ✗ unresolvable |
| 11 | lerobot-smolvla-vla-trace | capture | SmolVLA stage split | none | none | eea4d4f59fbe6d63d3a508df2b31059c611ac790e0f88b50227f2b48de444a94 | ✗ unresolvable |
| 12 | lerobot-act-pusht-trace | capture | ACT (real CPU) | none | none | eb3f58a144796079b7d49f9613f816819b5935a3c9b64a81399bdee71bafb7ed | ✗ unresolvable |
| 13 | vla-perf-network-latency-kvcache | capture | π0/OpenVLA (roofline) | none | none | 8c90e5c478235943b980d2b524b7250d1ed66f7c8a577e56b6807be2cca40a8f | ✗ WAN model — not NoC |
| 14 | vla-perf-network-latency-images | capture | generic VLA (roofline) | none | none | 96ac194c1627de6541f342ad01d0e4379ecb4d18b2c5c25b0978b3588cafbf74 | ✗ WAN model — not NoC |
| 15 | vla-perf-validation | capture | RTX 4090/5090 roofline | none | none | f807142651a81bea49b7fbb06fcf0fd3d6a9549b4fe9252b3dc02c6a6128f2d9 | ✗ single-chip — not NoC |
| 16 | vla-perf-pi0-denoising | capture | π0 roofline sweep | none | none | 6addcecbbd4b88303fdede36ded833b4d0aaa8472c7b12c10ceb4ec2d6cdfb63 | ✗ single-chip — not NoC |
| 17 | vla-perf-pi0-family | capture | π0 roofline family table | none | num_chips 1/2/4 (not parallelism) | 68e70df3ca4c7f1b8a5cb62acaa6e4d9f1b85a48c2ab1cd47b823561e2286206 | ✗ no fabric content |

Entries that cannot be resolved to a family, explicitly: **6, 7, 8, 9, 10, 11,
12, 13, 14, 15, 16, 17** (12 of 17). The five request documents resolve — and
in all five cases the resolution is the authored-or-derived `mesh`, with the
alternative candidates analysed in §4.

## 3. Mapping rules (grounded)

**R1 — VLA-like TP workloads → built-in mesh (torus bounded).**
Templates authored on mesh 3×3; the flagship robotics path compiles them
[PROVEN: gr00t_vla_robotics-v4.json:35; gr00t_n16_h100_measured-v4.json:31;
pi0_thor_modeled-v4.json:31; docs/product/nvidia-robotics-use-case.md:165];
mesh is the only family with every stage YES and WIRED YES
`[PROVEN: registry:53-65]`; torus only within its 2-VC odd-side envelope
`[PROVEN: registry:66-78]`. Multi-camera fanout at rank 1→{2..5} and
action fan-in {2..5}→6 are short-range patterns DOR serves with no wrap
`[INFERRED: 3×3 seat geometry + file profiles]`.

**R2 — MoE expert-parallel all-to-all → GEC-MECS multidrop (or plain mesh);
dragonfly express wires are NOT an available target.**
The release's own full-size MoE acceptance design (moe-8x7b, tp=8 ep=8) is
certified on **GEC-MECS** (DOR_GEC_MECS, 162 shared wires, taps=8, 8 VCs,
certificate PASS, DEADLOCK_FREE) `[PROVEN: revision:1, topology:1, §0]`;
`gec_mecs` is READY with live flit conservation and binds every canonical
class to the full tap/VC envelope `[PROVEN: registry:138-150]`; `gec_express`
is the point-to-point alternative (p2p, product-wired via AnyNet, o=k−1, d=1)
`[PROVEN: registry:164-176]`. Multidrop/express wires do **not** dedupe an
all-to-all's distinct shards (each EP rank sends different 2,048 B shards to
each peer); they shorten the *path* each disjoint DIRECT p2p pair takes,
which is where a hop penalty is removed `[INFERRED: premises = collectives.py:17
(ALLTOALL→DIRECT) + family_collectives.py:100-107 (ep_dispatch/ep_combine
patterns) + registry:122,138-150 (multidrop mechanics/READY row)]`. No
multicast claim is made anywhere on MECS RTL
`[PROVEN: docs/research/RTL-TOPOLOGY-ACCEPTANCE-MATRIX.md:70]`.
**Dragonfly express wires: recognized only — AUTHORABLE NO, MATERIALIZABLE
NO, QUALIFIED NO, WIRED NO; the pinned `dragonfly` row is a config-only
backend spelling (`dragonflynew`) with PARTIAL projection** — it cannot serve
any pinned entry as RTL today `[PROVEN: registry:218-229]`. Treating
"MoE all-to-all → dragonfly" as available would be the one mapping the
registry forbids.

**R3 — Dense TP all-reduce → RING lowering; ring_native or mesh.**
ALLREDUCE/ALLGATHER/REDUCESCATTER all lower to RING
`[PROVEN: collectives.py:13-16]`; the shipped dense catalog entries
(llama-dense-8b-64tiles, dense-1b-16tiles, dense-4b-32tiles-conc4) are
EVALUATED on mesh (cmesh for conc4) `[PROVEN: CAPABILITY-CLOSURE-2026-09.md:105-112]`.

**R4 — Incast/hotspot (one destination) → topology choice is near-irrelevant.**
Swept at 9×9 anynet min-hop, 5,000-packet traces: hotspot 32,086–32,339 cycles
across mesh/torus/cmesh/fat-tree (all within 1.5%)
`[PROVEN: traffic-profiles.md:155-167]`; at saturation the fabric is the
bottleneck, not the router graph `[PROVEN: same lines]`.

**R5 — Multicast-equivalent duplicate-unicast ≠ multicast.**
No family exposes a broadcast primitive for these workloads;
`multicast_equiv` is authored as 8 duplicate unicasts and stays correct on any
connected fabric; MECS taps would change transfer *count* only if multicast
packet-header semantics existed, which the RTL evidence explicitly does not
establish `[PROVEN: docs/research/RTL-TOPOLOGY-ACCEPTANCE-MATRIX.md:70; file
switch_gen6_class-v4.json:991-1039 rows]`.

**R6 — RAW captures with no message events (counters, kernel rows, roofline
CSVs, dataset ledgers, CPU-run stage timings) resolve to NO fabric family.**
Binding them to one would violate the pin's own limits
`[PROVEN: release-workloads-20261110.json:78-80,86-88,102-104,110-112,118-120,126-128,134-136,142-144,150-152,158-160,166-168]`.

**R7 — VC counts, not demand shape, dominate the mesh/torus ranking.**
Measured: mesh DOR 18,387→11,054→8,661 cycles as VCs 1→2→4 (buf 8); torus DOR
needs 2 dateline VCs (1-VC run fails); mesh wins DOR at matched VCs (8,661 vs
11,496 at 4 VCs; 11,054 vs 19,633 at 2 VCs, buf 8); min-hop mesh/torus tie
(8,170/8,160 at 4 VCs); the collective catalog's 11,720-vs-11,694 near-tie was
a VC-count artifact (mesh at 1 VC vs torus at 2)
`[PROVEN: docs/product/calibration.md:7-36,63-70]`. Any family ranking below
carries this caveat.

**R8 — "Fastest on RTL" does not exist yet for any pinned entry.**
All 14 families are L3-✗ (zero pinned workloads through RTL)
`[PROVEN: docs/product/MILESTONE-14-PRODUCTION-RTL-20261110.md:37]`; running
them would be the L3 gate itself. Every ranking in §4 is therefore an
*architecture* ranking: (a) qualified RTL stage reached (L0/L1/L2), (b) hop
penalty for the declared traffic classes, (c) deadlock/VC proof availability,
(d) calibration evidence at matched VC counts. No claim of "RTL-fastest" on
measured cycles is made or possible today.

## 4. Ranked: which family makes THIS workload fastest on RTL — the three flagship entries

**Flagship selection, stated honestly:** the pin defines no `flagship` tag
(the word appears once in the tree, in `docs/OPEN-PROBLEMS.md:290`, about CI).
The pin does mark exactly three entries as *binding* — each carries at least
one `requirements[]` row with `binding: true` on a named traffic class:
**§2.2 gr00t-vla-robotics** (control_out + camera_ingest), **§2.3
qwen3-moe-tp2-ep4-16tiles** (tp_collective), **§2.5 switch-gen6-class**
(incast_ssd0 + multicast_equiv) `[PROVEN: gr00t_vla_robotics-v4.json:31-33;
qwen3_moe_tp2_ep4_16tiles-v4.json:1127-1134; switch_gen6_class-v4.json:1040-1052]`.
A flagship release workload is one whose deadline is contractually checkable;
that is the criterion applied here `[INFERRED: selection criterion; not a
release-pin fact]`. If the operator intended the VLA robotics trio instead
(gr00t-n16-h100-measured, gr00t-vla-robotics, pi0-thor-modeled — the set
presented as the flagship in `docs/product/nvidia-robotics-use-case.md:90-115`),
the §2.2 ranking applies to all three with bytes rescaled; that reading is
noted, not silently swapped in.

Every line below is `[INFERRED]` on top of the `[PROVEN]` evidence cited; the
controlling facts are: **L3=✗ for every family** (§R8) — so "fastest on RTL"
== "the fastest family that can legally and traceably bind this workload on
composed RTL with the declared traffic classes and VCs".

### Flagship 1 — `gr00t-vla-robotics` (custom VLA pipeline, tp=8)

**Exact traffic-class evidence** `[PROVEN: file:14-33]` / `[COMPUTED]`:

| class | rows | bytes | route | requirement |
|---|---|---|---|---|
| camera_ingest | 1 | 196,608 | 0→1 | bandwidth, ≥0.005 GB/s, ≤33,000,000 cyc, **binding** |
| vision_tokens | 4 | 65,536/row (262,144) | 1→{2,3,4,5} | none |
| action_tokens | 4 | 20,480/row (81,920) | {2,3,4,5}→6 | none |
| control_out | 1 | 128 | 6→7 | latency_critical, ≤**1,000,000 cyc (1 ms @ 1 GHz)**, **binding** |

Total 540,800 B; no collectives; no VC-class binding declared; authored fabric 3×3 mesh / 256b / 1 GHz / 4 nm; 9 seats fit 9 agents exactly.

| Rank | Family | Why (premises) | RTL status |
|---|---|---|---|
| 1 | **mesh 3×3 (built-in, DOR)** | Authored fabric (`file:35`); qualified (single-class mesh-DOR, MC, class-VC) `[PROVEN: registry:53-65]`; L1 38/38; 8×8 13 scenarios pass; L2 mutation witness ✓ `[PROVEN: MILESTONE:22]`; mesh wins or ties every demand mix at matched VCs, DOR 8,661 vs torus 11,496 (4 VC buf 8) and 11,054 vs 19,633 (2 VC) `[PROVEN: calibration.md:7-36,63-70]`; 1 kHz control deadline needs only ≤1e6 cycles — hundreds of hops fit trivially | L0/L1/L2 ✓ · L3 ✗ |
| 2 | **torus 3×3 (built-in, 2 dateline VCs)** | Only other qualified built-in; odd side ✓; dateline floor derived; multi-class rides full 2-VC envelope; L1 ✓ `[PROVEN: registry:66-78; MILESTONE:23]`; min-hop tie with mesh (8,160/8,170); DOR loses at matched VCs — hence rank 2, not 1 | L0/L1/L2 ✓ · L3 ✗ |
| 3 | **GEC-MECS (multidrop taps)** | One multidrop express wire could carry the rank-1 vision fan-out 1→{2,3,4,5} over a single tapped path (one injection per destination on one wire, instead of four separate mesh paths); the action fan-in {2,3,4,5}→6 is four *distinct* payloads and does NOT collapse onto one wire (tapped unicast ≠ broadcast) `[INFERRED; premises: R2/R5 + registry:108-124 (multidrop note) and registry:138-150 (READY row) + research matrix (no multicast semantics on MECS RTL)]`; composed MECS L0/L1 ✓ shared path; L2 tap-identity witness ✓ `[PROVEN: MILESTONE:26]`; **cost:** shared-wire credit/RTT complexity, tap arbitration, 128 B control class gains nothing | L0/L1/L2 ✓ · L3 ✗ |
| 4 | **flatfly (k=4,n=2)** | Point-to-point 16 routers vs 9-seat need; wire fanouts are rich, but k=4/n=2 grid≠3×3; only 4×2 composed top and FLATFLY_MIN sealed class exist `[PROVEN: registry:190-205 (WIRED PARTIAL); RTL-TOPOLOGY-ACCEPTANCE-MATRIX.md:28,44,54 (65-cycle single-flit prototype)]` | L0/L1/L2 ✓ (4×2 only) · L3 ✗ |
| 5 | **ring_native (64 routers)** | Qualified, but ring is lower bisection and the pinned VLA shape is not a ring; size mismatch (9 agents ≠ 64) — ruled out | L2 ✓ · L3 ✗ |
| ✗ | **fat_tree / AnyNet** | Qualified backend path (CERTIFIED_BOOKSIM_ANYNET_V1, fattree16_anynet conserved preset) `[PROVEN: registry:125-137]` but the 3×3 VLA shape gains nothing, and the composed fat-tree top is a typed refusal at L0 `[PROVEN: MILESTONE:33]` | L0 ✗ |
| ✗ | **dragonfly / flattened-butterfly** | Dragonfly not authorable/materializable (registry NO/NO) `[PROVEN: registry:218-229]`; flattened_butterfly has no materializer `[PROVEN: registry:206-217]` | ✗ |
| ✗ | **srota / gec_hybrid** | No VLA-relevant evidence; SROTA L2 strongest but different design law (valiant/telemetry) and unproven for this pin; gec_hybrid is a candidate-union proof, not an escape theorem `[PROVEN: registry:177-189,151-163]` | partial |

**Answer:** mesh 3×3 (rank 1). Torus is an honest tie on 4 VC min-hop and absorbs the control deadline equally; mesh carries DOR evidence and the authored seat map, so it binds first.

### Flagship 2 — `qwen3-moe-tp2-ep4-16tiles` (Qwen3-30B-A3B, mixture_of_experts, tp=2 ep=4)

**Exact traffic-class evidence** `[PROVEN: file:1143-1164]` / `[COMPUTED]`:

| class | kind / dim | payload | requirement |
|---|---|---|---|
| tp_collective | allreduce / TP | 4,096 B | latency_critical, ≤**50,000 cyc**, **binding** |
| ep_dispatch | alltoall / EP | 2,048 B | none (bandwidth class, ceiling null) |
| ep_combine | alltoall / EP | 2,048 B | none |

22 endpoints (16 compute / 4 HBM / 2 NIC), derived 5×5 mesh (frozen_v3_autosize,
§2.3), 64b links, 7 nm; compute is DECLARED (activation-only; weights resident,
never declared); pool assignment `device = owner // 2`, `LOCAL:<pool>` pins.

| Rank | Family | Why | RTL status |
|---|---|---|---|
| 1 | **GEC-MECS (multidrop taps; tap degree configurable — the MoE pin used d=8)** | The release's own full-size MoE (moe-8x7b, tp=8 ep=8) is certified on DOR_GEC_MECS at 74/81/8/162 — the *exact* class combination here (`tp_collective` + EP `ep_dispatch`) `[PROVEN: revision:1, topology:1]`; EP all-to-all among 4 EP ranks (ep_dispatch 2,048 B) is DIRECT lowering `[PROVEN: collectives.py:17]` = disjoint rank pairs; multidrop express wires remove mesh hops from those pairs but do **not** dedupe distinct shards (tapped unicast ≠ broadcast) `[INFERRED; premises R2/R5 + registry:138-150]`; `gec_mecs` READY, live flit conservation, per-class full tap/VC envelope, VC≥2 for multi-class `[PROVEN: registry:138-150]`; DEADLOCK_FREE proof exists (shared-resource-cdg/v1, 1,944 nodes/648 edges) on the released MoE design `[PROVEN: revision:1 §0]`; composed MECS L0/L1/L2 ✓ (tap-identity witness) `[PROVEN: MILESTONE:26]` | L0/L1/L2 ✓ · L3 ✗ |
| 2 | **mesh 5×5 (derived; executed)** | The only family with *executed* evidence for this exact fixture class: BookSim MC 2,805 cyc, ASTRA TP2+EP4 3,050 cyc, run QUALIFIED (schedule-window only; absolute latency NOT_ESTABLISHED); both classes PASS; Ramulator v4 declared compute 101,875 cyc; COMPUTE NOT MODELED `[PROVEN: FULL-STACK-TRUTH-CLOSURE.md:52,54,82-89]`; mesh catalog 4/4 static workloads EVALUATED (llama-dense, dense-1b-16tiles, dense-4b-conc4, moe-8x7b multi-class) `[PROVEN: CAPABILITY-CLOSURE-2026-09.md:105-112]`; L1 38/38; L2 ✓ `[PROVEN: MILESTONE:22]`; **cost:** all-to-all pays DOR multi-hop without taps; 64-bit link is narrow (mixed evidence — keep link_width as authored) | L0/L1/L2 ✓ · L3 ✗ |
| 3 | **torus 5×5 (2 dateline VCs)** | Odd side ✓; qualified only within the 2-VC dateline envelope (must carry both classes on the full half envelope) `[PROVEN: registry:66-78]`; at matched VCs loses DOR to mesh (11,496 vs 8,661 at 4 VCs; 19,633 vs 11,054 at 2 VCs, buf 8); min-hop tie (§R7) — no executed EP all-to-all evidence | L0/L1/L2 ✓ · L3 ✗ |
| 4 | **fat_tree / AnyNet (graph)** | Qualified CERTIFIED_BOOKSIM_ANYNET_V1 + MC profile; ANYNET_MIN_HOPS; fattree16_anynet graph conserved; library ranking (traffic-profiles.md:153-167) puts fat-tree behind on non-hotspot mixes (20,155 mixed/write/uniform; 24,130 uniform) `[PROVEN: registry:125-137; traffic-profiles.md:155-159]`; composed fat-tree top = L0 typed refusal today `[PROVEN: MILESTONE:33]` | L0 ✗ · L3 ✗ |
| 5 | **gec_hybrid** | 4×4 c=1 o=1 d=3 six-VC probe only; oversized d=7 needs 14 VCs → typed refusal; candidate-union proof, **not** escape theorem; no EP evidence `[PROVEN: registry:151-163]` | L0/L1/L2 ✓ (probe) · L3 ✗ |
| ✗ | **dragonfly** | Not authorable, not materializable, config-only (`dragonflynew`) `[PROVEN: registry:218-229]`; even if it were, no RTL for this size and no class binding | ✗ |
| ✗ | **concentrated_mesh** | 22 endpoints not square-uniform at c=2/4; c=4 4×4 refuses (current) `[PROVEN: registry:79-91; MILESTONE:24]` | L0 ✗ |

**Answer:** GEC-MECS (rank 1) for the EP all-to-all path, with mesh as rank 2 and the *only family with executed numbers* (2,805/3,050 cycles, §2.3) — if the selection bar is "carries RTL L3 next", mesh binds first; if the bar is "makes the declared MoE traffic classes fastest", MECS wins on wire count and proof. Neither answer is measured on RTL today; writing either as a fact would break §R8 and the pin's own limits.

### Flagship 3 — `switch-gen6-class` (authored Gen-6-class 16-port switch)

**Exact traffic-class evidence** `[PROVEN: file rows; COMPUTED]`:

| class | rows | bytes | route | requirement |
|---|---|---|---|---|
| read_256k | 56 | 14,680,064 | 0-7 → 9-15-ish fan | none |
| read_4k | 56 | 229,376 | same | none |
| write_256k | 24 | 6,291,456 | same | none |
| write_4k | 24 | 98,304 | same | none |
| incast_ssd0 | 2 | 524,288 (2×262,144) | {0,1}→8 | latency_critical, ≤**10,000,000 cyc**, **binding** |
| multicast_equiv | 8 | 524,288 (8×65,536) | 0→{8..15} | bandwidth, ≥**0.001 GB/s**, ≤10,000,000 cyc, **binding** |

Total 22,347,776 B; read:write = **0.700 exactly** (14,909,440 vs 6,389,760);
no collectives; authored fabric 4×4 mesh / 256b / 1 GHz / 4 nm; ranks 8–15 are
SSD-port proxies; the incast destination is a single port (rank 8).

| Rank | Family | Why | RTL status |
|---|---|---|---|
| 1 | **mesh 4×4 (authored)** | Exact 16-seat fit (`file:1066`); hotspot verdict: **all four swept topologies within 1.5% at saturation** — incast to one SSD port is saturated, so topology cannot lose; mesh DOR is the qualified, L1-green path and ties torus everywhere here `[PROVEN: traffic-profiles.md:155-167; calibration.md:49-61; registry:53-65; MILESTONE:22]`; 70/30 read/write mix matches the "read-heavy" bucket where mesh wins by 2.6% `[PROVEN: traffic-profiles.md:163]` `[INFERRED: bucket assignment — read 14909440 B vs write 6389760 B matches the read-heavy row, 9,461 (mesh) vs 9,710 (torus) cycles, mesh wins by 2.6%]` | L0/L1/L2 ✓ · L3 ✗ |
| 2 | **torus — DISQUALIFIED at 4×4** | **Even side length ⇒ not in the qualified envelope** (the BookSim fork randomizes midpoint ties) `[PROVEN: registry:66-78]`; a 4×4 torus cannot legally serve this authored shape; nearest legal (5×5) changes seat geometry and breaks the 16-port proxy map | ✗ (qualified envelope) |
| 3 | **GEC-MECS** | `multicast_equiv` is 8× *identical* 65,536 B (rank 0→{8..15}) — the one pattern here that could, in principle, be carried by one tapped injection with per-address tap ejection; RTL establishes shared-wire **unicast** (GEC MECS16 passes all 256 ordered pairs) but explicitly does **not** establish multicast packet-header semantics, so the dedup win is unproven `[PROVEN: RTL-TOPOLOGY-ACCEPTANCE-MATRIX.md:70]`; `incast_ssd0` gains nothing (single destination); composed MECS L0/L1/L2 ✓ `[PROVEN: MILESTONE:26]`; VC count unpinned for multi-class | L0/L1/L2 ✓ · L3 ✗ |
| 4 | **fat_tree / AnyNet (16 leaves)** | Contention-free crossbar-ish bisection for host↔SSD; fattree16_anynet graph executes conserved; ANYNET_MIN_HOPS; but gains nothing over mesh for single-port incast (saturated), loses on 70/30 uniform flows (§traffic-profiles), and the composed top is an L0 typed refusal `[PROVEN: registry:125-137; MILESTONE:33; traffic-profiles.md:153-159]` | L0 ✗ · L3 ✗ |
| ✗ | **dragonfly** | Host↔SSD is exactly dragonfly's global-link story, but dragonfly is AUTHORABLE NO / MATERIALIZABLE NO / QUALIFIED NO — config-only (`dragonflynew`) `[PROVEN: registry:218-229]`; a native BookSim `dragonflynew` k=2,n=1 (72 terminals) behavioral fabric exists — centralized, single-flit, not explicit physical-link/router RTL `[PROVEN: RTL-TOPOLOGY-ACCEPTANCE-MATRIX.md:55,70; MILESTONE:34]`; wrong size, wrong signal — excluded | RTL partial (non-target) |
| ✗ | **concentrated_mesh** | 16 ports ⇒ c=2 → 8 routers (not 4×4), c=4 → 4 routers — geometry mismatch; square k×k seat law unmet; c=4 4×4 refuses today `[PROVEN: registry:79-91; MILESTONE:24]` | L0 ✗ |

**Answer:** mesh 4×4 (rank 1) — the hotspot saturation tie makes the incast class
topology-agnostic, the 70/30 read-heavy bias favors mesh-DOR, and the authored
seat map requires exactly 16 ports on a 4×4. MECS wins *only* on the
multicast_equiv class in the limit of tap-delivery semantics the RTL does not
yet claim; count it as the L3 experiment to run, not the selection.

### Cross-flagship observation (evidence-limited)

- All three rankings are `[INFERRED]` above `[PROVEN]` files; **no RTL cycle
  number exists for any of them** `[PROVEN: MILESTONE:37]`. The strongest
  executed evidence anywhere in this map is the *BookSim/ASTRA* 2,805/3,050-cycle
  pair for the Qwen fixture class (§2.3) — simulation, not RTL, and not on a
  GEC-MECS fabric `[PROVEN: FULL-STACK-TRUTH-CLOSURE.md:52]`.
- If VC count is freed (all three favor it), order can flip toward torus
  min-hop or mesh DOR depending on routing law; the ranking above pins the
  authored/derived fabrics and the qualified envelopes only
  `[PROVEN: calibration.md:58-70, R7]`.
- The two remaining *request* entries carry no binding requirement; for
  completeness under the VLA reading, gr00t-n16-h100-measured and
  pi0-thor-modeled take the same mesh-first ranking as §2.2 (§2.1, §2.4); their
  binding=NONE status does not change hop counts, only the checkable deadline.

## 5. What would change every ranking above (open work, in pin order)

1. **L3 — workload-driven RTL qualification**: feed these three (and all 17)
   through composed tops with credit/reset/conservation invariants
   `[PROVEN: MILESTONE:43; P2/P3 in INTENT-TO-PLACED-RTL-COMPLETION-PLAN.md]`;
   until then §4 is architecture, not measurement.
2. **P2** — workload evaluation trustworthiness; P3 — all 14 compiler-to-hardware
   bindings (multi-seat concentrators, per-instance adapters, 74-agent target)
   `[PROVEN: INTENT-TO-PLACED-RTL-COMPLETION-PLAN.md:112-155; RTL-FINAL-CLOSEOUT-STATUS.md:22,38]`.
3. **Calibrated VC/buffer configuration** — the single largest measured lever
   (2.1× on mesh DOR) `[PROVEN: calibration.md:27-34]`.
4. **Release eligibility** — dirty tree, no tag; 0/14 production-ready; the
   pinned Mixtral design has never compiled to hardware
   `[PROVEN: MILESTONE:37,44; INTENT-TO-PLACED-RTL-20261110-AUDIT.md:186; RTL-FINAL-CLOSEOUT-STATUS.md:31-38]`.

## 6. Appendix — sha256 per approved entry (verbatim from the pin; re-verified 2026-11-10)

| id | sha256 (verbatim) | kind | path |
|---|---|---|---|
| gr00t-n16-h100-measured | 18eeaed2d18ea857b7db5b353f1301b6abd390ee90c2fb13bda3c5c38506654f | request | tracks/t3-topology/examples/gr00t_n16_h100_measured-v4.json |
| gr00t-vla-robotics | bb7cc4078689d5433f79be0c5626e0b09b12a4b69bf17ee3e300de57640ac7f6 | request | tracks/t3-topology/examples/gr00t_vla_robotics-v4.json |
| qwen3-moe-tp2-ep4-16tiles | f7df8bc5a210cd2b63d844ab3d955ea21450a61e7a541e80bac8621f7f24ec05 | request | tracks/t3-topology/examples/qwen3_moe_tp2_ep4_16tiles-v4.json |
| pi0-thor-modeled | 4d15960793ecbd85c97d51f6ad557c04335ef56bde7b61c1eab0951787dbdf70 | request | tracks/t3-topology/examples/pi0_thor_modeled-v4.json |
| switch-gen6-class | c2e7658187f6a48457ee3c6a05c69090dfaea13ae821437591451250cd3a92fd | request | tracks/t3-topology/examples/switch_gen6_class-v4.json |
| cal26-qwen3-30b-ep4-kernel-slowdowns | cf34869fb9cc26364c1821c35e30f2510d7120994fc84c4c9ffabb8126975960 | capture | tracks/t3-topology/data/public-inference/cal26-qwen3-30b-ep4/inference-kernel-slowdowns.csv |
| cal26-qwen3-30b-ep4-nvlink-counters | be275dec0c90b98c68a73e147dce2d1fad467254abd75ec5a62b3bb3030b7810 | capture | tracks/t3-topology/data/public-inference/cal26-qwen3-30b-ep4/nvlink-counter-samples.csv |
| llama31-8b-tp4-collectives | 761dc54d764c360dcadccbc80c8a8c7624b1addeb140008bb177fc498446cef0 | capture | tracks/t3-topology/data/public-inference/llama31-8b-tp4/collectives.json |
| gr00t-g1-apple-to-plate-events | 0e4001d4554ae9d0519b336e5bdf2085b571ce5a6f4039c66daa7c2b4c7d8a96 | capture | tracks/t3-topology/data/public-robotics/gr00t-g1-apple-to-plate/episode_000000.events.jsonl |
| lerobot-smolvla-trace | 5d91310c6fd84de191bb33ef7ca4cccf1b06d232033dd9733d88804af60052fa | capture | tracks/t3-topology/data/lerobot/smolvla_trace.jsonl |
| lerobot-smolvla-vla-trace | eea4d4f59fbe6d63d3a508df2b31059c611ac790e0f88b50227f2b48de444a94 | capture | tracks/t3-topology/data/lerobot/smolvla_vla_trace.jsonl |
| lerobot-act-pusht-trace | eb3f58a144796079b7d49f9613f816819b5935a3c9b64a81399bdee71bafb7ed | capture | tracks/t3-topology/data/lerobot/act_pusht_trace.jsonl |
| vla-perf-network-latency-kvcache | 8c90e5c478235943b980d2b524b7250d1ed66f7c8a577e56b6807be2cca40a8f | capture | tracks/t3-topology/data/vla-perf/network_latency_bidirectional_kvcache.csv |
| vla-perf-network-latency-images | 96ac194c1627de6541f342ad01d0e4379ecb4d18b2c5c25b0978b3588cafbf74 | capture | tracks/t3-topology/data/vla-perf/network_latency_images.csv |
| vla-perf-validation | f807142651a81bea49b7fbb06fcf0fd3d6a9549b4fe9252b3dc02c6a6128f2d9 | capture | tracks/t3-topology/data/vla-perf/perf_validation_vs_realtime_vla.csv |
| vla-perf-pi0-denoising | 6addcecbbd4b88303fdede36ded833b4d0aaa8472c7b12c10ceb4ec2d6cdfb63 | capture | tracks/t3-topology/data/vla-perf/pi0_denoising_steps_action_lengths.csv |
| vla-perf-pi0-family | 68e70df3ca4c7f1b8a5cb62acaa6e4d9f1b85a48c2ab1cd47b823561e2286206 | capture | tracks/t3-topology/data/vla-perf/pi0_family_e2e_perf.csv |

Verification this pass (2026-11-10): `sha256sum` over all 17 paths — all 17
digests equal the pin's values; 0 mismatches. Full-size acceptance pin
(`release-workloads-20261110.json:7-15`): revision `p-fd7e5e31be77-r02`,
`design_hash sha256:ab7bce8f71b5ed4fde4101ee80a60b6c69c16989d966f0f9096dd6d76ad392f0`,
agents 74 / routers 81 / vcs 8 / shared_links 162 — all confirmed against the
evidence JSONs (revision:1, topology:1) and by the audit's D-06/C-01 reruns
`[PROVEN: docs/product/INTENT-TO-PLACED-RTL-20261110-AUDIT.md:55,99,160]`.
The pin's `excluded` block names exactly one excluded input (the Mixtral
ablation trace) and it is not part of the 17
`[PROVEN: docs/product/evidence/release-workloads-20261110.json:171-176]`;
`tests/test_release_workload_approval.py` pins the approval file
`[PROVEN: tracks/t3-topology/dse/tests/test_release_workload_approval.py:8]`.

**Files written:** this document only. No source, no evidence, no JSON was
modified. `docs/product/MILESTONE-14-PRODUCTION-RTL-20261110.md` was observed
to change under this session (mtime 15:07; untracked); figures above are from
the 15:07 read and must be re-checked on the release re-pin.
