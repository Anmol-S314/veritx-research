# Wave D Scientific Contract — Distributed Semantics (D0)

Status: **DRAFT FOR AUDIT** (D0 is a scientific-design pass; it adds no
production behavior).

Base: Wave C-SEAL.1 `8455c0450e27486ae034028b76c9a05b94f2ea72`
(branch `wave-d/distributed-semantics`).

This document is the normative contract for Wave D. Every ruling uses the
decision format from §79 of the D0 brief:

```
DECISION / SUPPORTED DOMAIN / RATIONALE / CONSEQUENCE /
ALTERNATIVES REJECTED / PROOF OBLIGATION
```

Evidence is cited as `file:symbol` (line numbers drift; symbols do not).
Where a claim cannot be established from repository code it is marked
`EXTERNAL-CONTRACT-NEEDED` rather than guessed.

Wave D answers **WHAT** happens. Wave E answers **WHEN** and **HOW LONG**.
Nothing in this document assigns durations.

---

## 1. Scope and non-goals

In scope (future D1–D-FINAL):

```
workload intent → logical ranks → physical placement → communication
groups → operations → messages → packets → flits → backend traffic
```

Non-goals (explicitly out of Wave D):

- compute/memory/network **timing** models (Wave E);
- area/power/energy/Pareto/BO/MILP optimization (Wave F);
- RTL/UVM/formal (stays `NOT_RUN`; B3.6R/B3.8-HW re-entry only);
- serving **execution** (stays BLOCKED);
- training backward passes, 1F1B, interleaved PP (unsupported, §12).

D0 itself adds only: this document, `docs/wave-d-contract.json`, and a
small pinned-behavior test (`dse/tests/test_wave_d_contract.py`) that
executes the contradiction evidence.

## 2. Existing semantic authorities

Wave D inherits two sealed authorities and must not duplicate them:

| Authority | Location | Owns |
|---|---|---|
| Rank/placement | `model/placement.py` (`ParallelismShape`, `rank_of`, `coords_of`, `build_inventory`), `model/mapping.py` (`MappingArtifact`) | logical rank namespace, rank→agent placement |
| Fabric/route/VC/packet-format | `model/fabric_artifact.py`, `model/resolved_fabric.py`, `core/route_artifact.py`, `model/vc_assignment.py`, `model/packet_format.py`, `model/router_behavior.py` | endpoints, routes, VC assignment, wire field layout, flit width |
| Workload operations | `workload/canonical.py` (`WorkloadArtifact`, `WorkloadOp`, `check_conservation`), `workload/lowering.py` (rows, ET, `LoweringManifest`, `et_readback_conservation`) | operation kinds, logical bytes, participants, scope, conservation |
| Backend evidence | `backend/*` (Wave B3.7/B3.8) | config/input identity, route proof, execution qualification |

Wave D adds **no** second rank space, **no** second VC mapping, **no**
second packet-format authority. It extends the operation/message layer
that today lives only partially in `workload/canonical.py`.

### 2.1 Semantic authority ledger

`producers`/`consumers` are symbol-level. `authority` is the D0 ruling.

| Concept | Current definitions | Producers | Consumers | Observed semantics | Contradiction | D0 authority | Migration |
|---|---|---|---|---|---|---|---|
| world size | `tp·pp·ep·dp`; `tp·pp` (serving); fabric node count (ASTRA) | `presets.parallel_world_size`, `ParallelismShape.world_size`, `config_builder._resolve_parallelism` | `placement.build_inventory`, `mapping.derive_mapping`, serving `_compute_network_dims`, `astrasim_adapter` | three different numbers | D0-C001 | `TP·PP·EP·DP` | §17 |
| logical rank | `(t,p,e,d)` bijection | `placement.rank_of` | `mapping.RankPlacement`, `address_decode`, traces | canonical order | D0-C002 | `placement.rank_of` | reuse |
| node | fabric router; BookSim node; physical host | `fabric_artifact`, `presets.topo_size` | `resolved_fabric`, BookSim cfg | overloaded word | — | fabric router (never a rank) | §5 naming |
| instance | agent instance; serving model instance; simulation run | `placement.AgentInstance`, serving cluster JSON | `mapping`, `core/serving.expected_cluster_fabric` | two meanings | D0-C007 | `AgentInstance` in Srota; serving `Instance` is external | §5 |
| accelerator/NPU | `AgentInstance(kind=COMPUTE_TILE)`; ASTRA npu; serving num_npus | `placement.build_inventory`, serving `_resolve_parallelism` | `mapping`, `astrasim_adapter` | 1 npu per node in ASTRA | — | compute agent | §8 |
| network endpoint | attachment endpoint (routing unit) | `attachment.AgentAttachmentArtifact` | `resolved_route`, `packet_format`, VC | 1 endpoint/agent v1 | — | attachment authority | reuse |
| TP | tensor parallel size | `Workload.tp`, `Parallelism.tp` | placement, groups, chakra dims | multiplies ranks | — | independent dimension | §6 |
| PP | pipeline parallel size | `Workload.pp` | placement, PP stage, chakra (dormant) | stage partition | D0-C002 | independent dimension | §12 |
| EP | expert parallel size | `Workload.ep` | placement, MoE markers | multiplies ranks here, shares GPUs externally | D0-C001 | independent dimension | §13 |
| DP | data parallel size | `Workload.dp` | placement, serving dp_group | multiplies ranks | — | independent dimension | §6 |
| collective group | participants tuple; chakra `involved_dim`; ASTRA logical dims | `workload.canonical`, chakra generator, `astrasim_adapter` | lowering, ASTRA | three encodings | D0-C002 | §9 group families | §9 |
| collective payload | `WorkloadOp.bytes`; `CollectiveOp.bytes_per_element`; chakra `comm_size`; trace flits | canonical, compile_model, chakra, traces | lowering, ASTRA, BookSim | bytes vs unconsumed vs flits | D0-C008 | `logical_bytes_per_rank` | §18 |
| prefill | `ServingMode.PREFILL_HEAVY` label; serving flag | `compile_model`, `core/serving.serve_args` | reports, serving | label only | D0-C010 | semantic phase with shape | §11 |
| decode | `ServingMode.DECODE_HEAVY` label; serving flag | same | same | label only | D0-C010 | semantic phase per step | §11 |
| pipeline transfer | dormant chakra `P2P_SEND`; artifact SEND/RECV | chakra generator, canonical | none today | unlowerable | D0-C006 | explicit P2P op | §12/§34 |
| MoE routing | EXPERT markers; `num_experts % ep_size` (serving) | canonical, serving | lowering | structural markers only | — | explicit policy | §13 |
| KV ownership | trace rows; `pd_type` doubling | canonical (refuses inference), serving | none | no transfer model | D0-C006/C007 | `(layer, phase, owner, bytes)` | §14 |
| logical message | `WorkloadOp` comm op | canonical | lowering | no message layer yet | — | §16 | D3 |
| packet | DSE trace flits column; BookSim packet | traces, BookSim | BookSim | flits, unit-ambiguous cfg | D0-C004 | §18 units | D4 |
| flit | `flit_width_bits` + `max_packet_flits`; 64 B per flit in traces | `packet_format`, `traces.matrix_to_trace` | BookSim, VC | width from channels vs literal 64 | D0-C004 | packet_format authority | D4 |
| multicast | `mcast_groups` budget; comment "workload lowering only" | `compile_model`, `packet_format` | validation warnings | no traffic transformation | D0-C009 | source replication | §17 |
| physical placement | `MappingArtifact` rank→agent | `mapping.derive_mapping` | experiment, bundle | injective v1 | — | mapping authority | reuse |
| memory placement | `MemoryPlacement`/`AddressMappingPolicy`; trace location columns | `core/memory`, canonical | ASTRA remote mem | affinity undeclared | — | Wave E scope | defer |

## 3. Contradiction ledger

Each entry names two or more incompatible interpretations present in the
tree today. `P0` = changes scientific results if consumed silently;
`P1` = changes semantics/identity or can hide a claim; `P2` = cosmetic.

Severity tally: **4 × P0 (C001–C004) + 5 × P1 (C005–C009) + 2 × P2
(C010–C011) = 11**. The machine-readable contract carries the same
tally.

### D0-C001 (P0) world-size / EP multiplication

- A: `model/presets.py:parallel_world_size` → `tp × pp × ep × dp`
  (also `model/placement.py:ParallelismShape.world_size`).
- B: vendored serving `serving/core/config_builder.py:_resolve_parallelism`
  → `num_npus = tp_size * pp_size`; for MoE `ep_size` defaults to
  `tp_size` **sharing the same GPUs**; `ep_size <= tp_size` unless
  `dp_group` is set; `num_experts % ep_size == 0`.
- Counterexample: `tp=8, pp=8, ep=8, dp=1`. A → 512 ranks. B → 64 NPUs.
- Consequence: rank count, collective groups, trace rank space and
  topology sizing diverge by a factor of EP.
- Resolution: §6/§17 (Srota design rank space multiplies; the serving
  convention is an *external* convention that must be mapped explicitly,
  never adopted).
- Compatibility: serving execution is BLOCKED, so no sealed artifact is
  reinterpreted. Historical serving JSON keeps its own semantics.

### D0-C002 (P0) rank enumeration order

- A: `model/placement.py:rank_of` — tp fastest, then ep, then dp, then pp
  slowest: `rank = ((pp·DP + dp)·EP + ep)·TP + tp`.
- B: vendored serving `config_builder.py:_compute_network_dims` documents
  "vLLM's DP x PP x TP rank layout" for topology dims.
- C: `simulation/astrasim_adapter.py:generate_astrasim_logical_topology_json`
  emits `[tp, pp]` **only when** `tp*pp == num_nodes`, else `[num_nodes]`.
- Counterexample: `tp=2, pp=2, num_nodes=4` → dims `[2,2]`; the same
  workload with `num_nodes=8` → dims `[8]`, silently erasing TP/PP.
- Consequence: the same logical communication can address different
  physical ranks depending on subsystem; ASTRA logical dims can lose
  parallelism without any error.
- Resolution: §7/§9 (one canonical bijection; ASTRA dim derivation must
  refuse, never degrade to `[num_nodes]`).

### D0-C003 (P0) trace vs intent authority

- A: `model/compile_model.py:Workload` docstring — "If both are present,
  trace_path is the ground truth for simulation".
- B: `workload/canonical.py` + `workload/lowering.py` — the artifact is
  the semantic source and lowering is conservation-checked
  (`check_conservation`, `et_readback_conservation`).
- C: Wave B3.7 `backend/booksim.py` — trace records are the packet
  authority; config field names are never route evidence.
- Counterexample: intent declares `tp=4` while the bound trace addresses
  8 ranks. A silently simulates 8; B/C have no rule.
- Resolution: §21/§44 (intent semantics + trace binding must agree;
  disagreement refuses; derived traces are never a second authority).

### D0-C004 (P0) `packet_size` units

- A: BookSim cfg `packet_size` is **flits** —
  `third_party/booksim2/src/booksim_config.cpp` (`_int_map["packet_size"]`),
  `tracetrafficmanager.hpp` (`int packet_size; // flits`).
- B: `synthesis/evaluator.py` emits `packet_size = 8` with no unit; the
  DSE `.trace` 5th column is flits (`simulation/traces.py:matrix_to_trace`,
  `traces.py` header "timestamp,src,dst,type,packet_size").
- C: Chakra/ASTRA `comm_size` is **bytes**
  (`scripts/generate_chakra_trace.py:build_model_trace`).
- D: Wave B `model/packet_format.py` uses `flit_width_bits` +
  `max_packet_flits` (payload bits), and `backend/booksim.py` derives
  flit bytes as `bits // 8` exactly.
- Consequence: "8" can mean 8 flits (32 B at 32-bit flits) or 8 bytes.
- Resolution: §18/§83 (unit-suffixed names only; `packet_size` is never
  a Wave-D field).

### D0-C005 (P1) collective algorithm and byte accounting

- A: `simulation/astrasim_adapter.py:generate_astrasim_system_json`
  hardcodes `all-reduce-implementation: [ring]`, all-gather/reduce-scatter
  `ring`, all-to-all `direct`, `collective-optimization: localBWAware`.
- B: `simulation/model_to_trace.py:ring_allreduce_packets` — ring with
  `pkt_flits=4` default, 64 B per flit, `accurate=True` scales flits.
- C: `scripts/collectives.py:ring_allreduce_pairs` — float arithmetic,
  `2(k-1)` steps, aggregated edge bytes.
- D: `workload/canonical.py` records logical bytes only; no algorithm.
- Counterexample: `k=4, B=64 KiB` — A/B/C agree on 2(k−1) steps but
  disagree on per-step bytes, packet count and units (float vs int).
- Consequence: message counts and wire traffic are not reproducible
  across subsystems.
- Resolution: §10/§19–21 (CollectiveIntent vs CollectiveSchedule; one
  supported algorithm per kind; integer reference equations).

### D0-C006 (P1) KV movement representable but not lowerable

- A: `workload/canonical.py:canonicalize` refuses `comm_type NONE` with
  nonzero size ("P/D KV send … endpoints cannot be inferred").
- B: `workload/lowering.py:rows_from_artifact` refuses standalone
  `SEND`/`RECV` ("converter synthesizes P/D pairs from adjacent layer
  sizes with matching comm_tag").
- Consequence: KV transfer can exist in the artifact but cannot be
  lowered to the production row projection → currently unsupported,
  and must be declared so rather than silently dropped.
- Resolution: §14/§27 (KV movement requires an explicit SEND/RECV
  artifact op; row lowering must refuse, not synthesize).

### D0-C007 (P1) first-instance / representative collapse

- A: vendored serving `config_builder.py:_resolve_dp_groups` and
  `_compute_network_dims` read `members[0]`/`first_group` for tp/pp/ep.
- B: `config_builder.py:_compute_network_dims` doubles NPU/PP counts for
  `pd_type == "prefill"` instances.
- Assessment: A is *validated* representative use (all members must
  agree, per comment and `ValueError` paths) — semantically valid, not a
  silent collapse. B is a P/D disaggregation accounting convention
  belonging to the external serving model.
- Resolution: §22/§46 (representative reads are legal only behind an
  explicit all-members-agree proof; P/D doubling is DEFERRED and must
  never be inferred by Srota).

### D0-C008 (P1) `bytes_per_element` is a declared-but-unconsumed payload

- `model/compile_model.py:CollectiveOp.bytes_per_element` (default 2048)
  is serialized (`reports/reports.py`) but **no** message/packet
  consumer reads it. The canonical workload uses `WorkloadOp.bytes`
  (logical bytes).
- Consequence: an author can believe they declared payload size while
  the simulation uses something else.
- Resolution: §18 (rename to an explicit per-rank logical byte field in
  Wave D; refuse to treat the legacy name as payload authority).

### D0-C009 (P1) multicast has three different meanings

- A: `model/compile_model.py:noc_config.mcast_groups` — hardware group
  budget; excess "falls back to unicast" (warning, not error).
- B: `model/packet_format.py` header comment — "multicast workload
  lowering only in v1" (no lowering exists yet).
- C: `scripts/generate_chakra_trace.py` — `involved_dim: [True]` single
  logical dim; no multicast node kind.
- Consequence: "multicast" today is a budget knob, a plan, and a
  dimension flag — not a defined traffic transformation.
- Resolution: §17 (logical multicast is defined; hardware acceleration
  is a *schedule* property; unicast fallback must be an explicit
  declared loss, not a warning).

### D0-C010 (P2) prefill/decode are labels, not phases

- `model/compile_model.py:ServingMode` = `PREFILL_HEAVY`, `DECODE_HEAVY`,
  `MIXED` — traffic-mix labels with no operation semantics; no
  `sequence_length`/`batch_size`→operation derivation exists in the
  product path.
- Resolution: §11/§22 (labels are display-only and excluded from
  identity; phases are defined semantically and require explicit shape
  metadata).

### D0-C011 (P2) `total_npus` legacy alias

- `model/compile_model.py:Workload.total_npus` was `tp×ep` (MoE) /
  `tp` (dense); it is now aliased to `world_size` with a deprecation
  note. `NodeInventory.rank_count` is the intended authority.
- Resolution: §17 (`total_npus` is removed in Wave D; only
  `world_size`/`rank_count` survive).

## 4. Logical system ontology

```
Request          one workload submission (phase + shape + parallelism)
Phase            PREFILL | DECODE                      (semantic, §11)
Operation        COMPUTE | COLLECTIVE | P2P | KV_* | EXPERT_*   (§15)
LogicalRank      (tp, pp, ep, dp) coordinate            (§6/§7)
ParallelDim      TP | PP | EP | DP                      (§6)
CommunicationGroup  a set of ranks sharing one dimension index  (§9)
Collective       (kind, participants, logical bytes)    (§10/§18)
PointToPoint     (src, dst, logical bytes)              (§16/§34)
KVObject         (layer, owner_rank, phase, bytes)      (§14)
```

The words `node`, `instance`, `rank` and `agent` are **not**
interchangeable (§5).

## 5. Physical system ontology

```
PhysicalNode      a book-keeping grouping of accelerators (no fabric
                  semantics of its own)
Instance          one software model instance = a resolved {tp,pp,ep,dp}
                  group living on accelerators (serving vocabulary;
                  DEFERRED for Wave-D v1 execution)
Accelerator/NPU   one compute agent; `AgentInstance(kind=COMPUTE_TILE)`
                  in Wave-B vocabulary
NetworkEndpoint   one attachment endpoint (`AgentAttachmentArtifact`);
                  the unit of routing/VC/packet addressing
MemoryEndpoint    one memory attachment (`core/memory.py`
                  `MemoryPlacement`); affinity is Wave-E scope
```

Ruling: Wave-D v1 speaks only `LogicalRank → AgentInstance →
NetworkEndpoint`. `PhysicalNode` and `Instance` appear only where an
external format requires them (ASTRA `npus-per-node`, serving clusters)
and never carry Srota semantics.

## 6. Parallelism semantics

| Dim | Meaning | Owns | Varies within group |
|---|---|---|---|
| TP | tensor parallel | sharded weights/activations | `tp_index` |
| PP | pipeline parallel | layer ranges (stages) | stage id = `pp_index` |
| EP | expert parallel | contiguous expert shard | `ep_index` |
| DP | data parallel | independent replica | `dp_index` |

Ruling (D0-C001 resolution): all four are **independent** dimensions of
the Srota design rank space. EP is not "shared with TP"; a rank owns a
disjoint expert shard and the EP dimension multiplies rank count. The
serving convention (`ep_size ≤ tp_size`, shared GPUs) is an external
encoding that a future adapter must *map onto* the design space (or
refuse), never redefine it.

## 7. Rank-space mathematics

```
Coordinate:  c = (t, p, e, d),  0 ≤ t < TP, 0 ≤ p < PP, 0 ≤ e < EP, 0 ≤ d < DP
Cardinality: R = TP · PP · EP · DP
Bijection:   rank(c) = ((p·DP + d)·EP + e)·TP + t
Inverse:     t = r mod TP;  e = (r div TP) mod EP;
             d = (r div (TP·EP)) mod DP;  p = r div (TP·EP·DP)
```

Requirement: `coords_of(rank_of(c)) == c` and `rank_of(coords_of(r)) == r`
for every `r ∈ [0, R)`. Degenerate cases: `TP=PP=EP=DP=1 → R=1`,
`rank=0`. Empty rank sets are impossible (each size ≥ 1).

Enumeration order is **semantic** because AddressRange/agent indexing
and ASTRA dim vectors observe it; it must never be derived from a
dictionary iteration order.

## 8. Mapping semantics

`MappingArtifact` (Wave B) is the authority: `LogicalRank → AgentInstance`.

Supported v1 domain:

```
one rank  → one COMPUTE_TILE agent  (injective, contiguous, complete)
```

Every other shape is UNSUPPORTED:

```
multiple ranks per accelerator        UNSUPPORTED
one rank spanning accelerators        UNSUPPORTED
multiple network endpoints per agent  DEFERRED (Wave E/HW)
shared network endpoint across agents DEFERRED (Wave E/HW)
memory affinity per rank              DEFERRED (Wave E)
```

## 9. Collective group semantics

```
TP group(r): varies t, fixes (p,e,d)   size TP,  count R/TP
EP group(r): varies e, fixes (t,p,d)   size EP,  count R/EP
DP group(r): varies d, fixes (t,p,e)   size DP,  count R/DP
PP stage(p): fixes p, varies (t,e,d)   size R/PP, count PP
```

Laws: every rank belongs to exactly one group per family; groups are
disjoint within a family; `Σ group sizes = R` per family; each group is
totally ordered by the §7 rank order (ordering is semantic only where a
schedule observes it — §32).

## 10. Collective algorithm semantics

`CollectiveIntent = (kind, participants, payload)` where **the meaning of
`B` is per-kind** (below). `CollectiveSchedule = (kind, algorithm)` fixes
message count, message size and per-rank bytes. Wave-D v1 supports
exactly these pairs; anything else refuses.

Common notation: `k = |participants|` (integer ≥ 2), `B` = the per-kind
payload defined below (integer bytes), `C = B / k`.

### 10.1 Per-kind payload meaning and exact equations

| kind | `B` means | divisibility | steps | messages | message bytes | per-rank sent | aggregate network payload |
|---|---|---|---|---|---|---|---|
| ALLREDUCE / ring | input tensor bytes **per rank** | `B % k == 0` | `2(k−1)` | `2k(k−1)` | `C` | `2(k−1)C` | `2(k−1)B` |
| REDUCESCATTER / ring | input tensor bytes **per rank** | `B % k == 0` | `k−1` | `k(k−1)` | `C` | `(k−1)C` | `(k−1)B` |
| ALLGATHER / ring | local contribution bytes **per rank** | none | `k−1` | `k(k−1)` | `B` | `(k−1)B` | `k(k−1)B` |
| ALLTOALL / direct | total input bytes **per rank**, equal split over `k` destinations | `B % k == 0` | `1` | `k(k−1)` | `C` | `(k−1)C` | `(k−1)B` |
| BROADCAST / root fan-out | **root** payload bytes | none | `1` | `k−1` | `B` | `(k−1)B` (root only) | `(k−1)B` |

Additional per-kind facts:

- ALLREDUCE: each rank ends with a `B`-byte reduced result.
- REDUCESCATTER: output payload per rank is `B/k`.
- ALLGATHER: gathered result per rank is `kB`.
- ALLTOALL: the self-chunk (`C`) does not enter the network.
- BROADCAST: non-root ranks send zero. It is the one asymmetric
  schedule: `aggregate = root_sent`, **not** `k × root_sent`.
- Symmetric schedules (ALLREDUCE, REDUCESCATTER, ALLGATHER, ALLTOALL)
  satisfy `aggregate = k × per_rank_sent` exactly.

All quantities are integers. Aggregate network payload is the **primary**
conservation invariant; per-rank traffic is asserted only where the v1
equal-chunk schedule makes it exact (all rows above). Average per-rank
traffic is never presented as an individual-rank quantity.

### 10.2 Divisibility refusal

Equal-partition v1 schedules (ALLREDUCE, REDUCESCATTER, ALLTOALL) require
`B % k == 0`; otherwise the operation is **UNSUPPORTED** and refuses.
Uneven chunk partitioning is a future extension, not a D0 invention.

### 10.3 Singleton normalization

The canonical workload builder requires ≥ 2 participants
(`build_collective_op`); that authority is preserved. Wave-D ruling:

```
dimension size == 1  → no collective operation is generated
                     → zero messages, zero network bytes
explicit k < 2       → invalid, refuses
```

A one-member `CollectiveIntent` is never represented. `TP=1`, `DP=1` or
`EP=1` therefore produce **no** collective for that dimension rather than
a degenerate no-op object.

### 10.4 Pinned reference example (`k=4`, `B=1024`)

| kind | messages | message bytes | per-rank sent | aggregate |
|---|---|---|---|---|
| ALLREDUCE | 24 | 256 | 1536 | 6144 |
| REDUCESCATTER | 12 | 256 | 768 | 3072 |
| ALLGATHER | 12 | 1024 | 3072 | 12288 |
| ALLTOALL | 12 | 256 | 768 | 3072 |
| BROADCAST | 3 | 1024 | 3072 (root) | 3072 |

These values are pinned by audit tests, independent of any future
production implementation.

Unsupported pairs (tree allreduce, recursive doubling, halving doubling,
one-ring, …) refuse — never silently substituted.

`EXTERNAL-CONTRACT-NEEDED`: ASTRA's `ring`/`direct` byte accounting must
be shown equal to §10.1 before any cross-backend exactness claim; until
then ASTRA traffic is `DIFFERENTIALLY_VALIDATED`.

## 11. Prefill/decode semantics (narrowed v1 scope)

Wave-D v1 rules:

```
phase tagging (PREFILL / DECODE):                      EXACT
explicit workload operations + declared comm bytes:    EXACT
automatic synthesis of per-layer compute/communication
  operations from model shape alone:                   DEFERRED
```

A PREFILL or DECODE workload is exact when the canonical workload
artifact **explicitly contains** the operations and their communication
bytes. D2/D5 must not invent communication from `hidden_size`,
`sequence_length`, `batch_size` or `num_layers`; those fields may be
recorded as declared shape metadata but are not an operation generator.

Shape metadata authority (§10 of the D0.1 brief): model-shape values
(`num_layers`, `hidden_size`, `bytes_per_elem`, `num_experts`, `top_k`,
`decode_steps`) must come from either an explicit versioned Wave-D
workload document or a named immutable model descriptor whose **content
hash is bound into** Wave-D workload identity. Implicit preset lookup by
name is refused (a preset can change underneath an identity). Missing
required shape information refuses.

`ServingMode` labels (`PREFILL_HEAVY`/`DECODE_HEAVY`/`MIXED`) are
traffic-mix labels, not phases. They remain **identity-bearing in the
frozen CompileRequest `design_hash`** (§9/§16) and are excluded from
Wave-D phase semantics.

Continuous batching, chunked prefill, sub-batch interleaving: UNSUPPORTED
in v1 (external serving flags exist — `core/serving.py:serve_args` — and
are not Srota semantics).

## 12. PP semantics

- Stage `p` owns a contiguous layer range; stages are disjoint and
  ordered by `p`.
- Inference only; forward transfers only. Training backward, 1F1B,
  interleaved/virtual PP: UNSUPPORTED.
- A PP transfer is one canonical `P2PTransfer` (§13.1) with
  `src=(t,p,e,d)`, `dst=(t,p+1,e,d)`; legacy SEND/RECV pairs are paired
  by an explicit shared identifier during ingestion, never inferred
  from adjacency (§34).
- `PP=1` → zero inter-stage transfers (metamorphic law, §29).

## 13. EP/MoE semantics

- An EP rank owns a contiguous expert shard; `num_experts % EP == 0`
  (mirrors the external constraint, adopted as a Srota validation).
- Dispatch/combine are explicit collective or P2P ops in the artifact;
  `EXPERT_BEGIN`/`EXPERT_END` markers are structural and optionally
  carry one collective (`workload/canonical.py`).
- Top-k routing policy for v1: `EXPLICIT_TRACE` only (routing carried
  in the trace/artifact). `DETERMINISTIC_BALANCED` is **DEFERRED** until
  token→expert assignment, top-k ordering, remainder handling and tie
  rules are specified mathematically. Uniform-random routing without a
declared seed policy: UNSUPPORTED.
- Token dropping: UNSUPPORTED in v1. Conservation (no drop):
  `assignments = tokens × k`, and for every phase
  `assignments_sent == assignments_received`.
- Whether expert routing crosses TP groups: YES (EP groups vary `e`
  holding `t,p,d`), so an expert on another `e` is reached by an
  explicit EP op. No implicit cross-group traffic.

## 14. KV semantics

```
KVObject = (layer, phase, owner_rank, logical_bytes)
```

- v1 models pipeline-local KV residency (a stage owns the KV it
  produced). Cross-rank movement requires one canonical `P2PTransfer`
  (§13.1) with declared src/dst; a SEND/RECV pair is one transfer, not
  two.
- Prefill/decode disaggregation (KV moved between separate prefill and
  decode instances): DEFERRED. The external serving `pd_type` doubling
  (D0-C007) is not adopted.
- Conservation: `produced = resident + transferred + discarded`, integer
  bytes; logical bytes ≠ physical replicated bytes when a transfer has
  more than one destination (multicast, §17).

## 15. Operation graph semantics

`OperationGraph` = immutable DAG. Each node:

```
operation_id  content-derived (§23)
kind          COMPUTE | COLLECTIVE | P2P | KV_READ | KV_WRITE | EXPERT_*
phase         PREFILL | DECODE
owner         rank or group (exactly one of: rank, group family+index)
deps          tuple of operation_ids
```

Laws: acyclic (§24); every dependency references an existing node; the
graph contains every operation the workload declares and nothing else;
per-layer structure is positionally ordered (matching
`workload/lowering.py` conservation).

### 15.1 Canonical point-to-point transfer

One semantic network transfer is one object — never a SEND plus a RECV:

```
P2PTransfer
    transfer_id
    phase
    src_rank
    dst_rank
    logical_payload_bytes
    dependencies
```

One `P2PTransfer` generates exactly one logical message. Legacy formats
that record SEND and RECV separately must be paired into one
`P2PTransfer` by an **explicit shared identifier** (transfer/comm tag)
during ingestion. If no unambiguous shared identifier exists, ingestion
**refuses** — pairing by adjacent rows, equal byte counts or source
order is forbidden. This rule prevents the double-counting failure mode
where both halves of a pair generate traffic.

## 16. Logical message semantics

```
LogicalMessage = {
  message_id, operation_id, phase,
  src_rank, dst_rank | multicast_group,
  logical_payload_bytes, traffic_class, order_key
}
```

Message identity covers exactly those fields; `order_key` is included
only for operations whose schedule declares order semantic (ring steps,
pipeline order). Physical endpoints come from the mapping, never stored
independently.

## 17. Multicast semantics

Definitions:

```
logical multicast: one payload, N declared destinations
source replication: the source issues N unicast messages (schedule)
network replication: the fabric duplicates one injected packet (schedule)
destination copies: N delivered copies (outcome)
```

`LogicalMulticastIntent` (payload, destination set) is separate from
`ReplicationSchedule`. Wave-D v1 supports exactly:

```
SOURCE_REPLICATION   EXACT for the selected schedule
HARDWARE_REPLICATION UNSUPPORTED / DEFERRED
```

Accounting for `SOURCE_REPLICATION` (integers, per operation):

```
logical_bytes   = payload_bytes
injected_bytes  = payload_bytes × N
wire_bytes      = injected_bytes (+ per-hop overhead, Wave E)
delivered_bytes = payload_bytes × N
```

This is **exact for the chosen schedule**, not a fidelity approximation.
If a caller explicitly requests hardware/network replication, Wave D
**refuses** rather than silently substituting source replication or
labelling it an approximation. Fidelity loss is reserved for cases where
the model cannot represent what was requested.

## 18. Packetization semantics (bit-exact)

Authority: `model/packet_format.py` (`PacketFormatArtifact`,
`canonical_field_layout`, `max_packet_flits`). Wire accounting is done in
**bits**, because Wave-B permits flit widths that are not byte-aligned
(only a positive channel width is required).

Notation (all integers):

```
message_bits               = logical_payload_bytes × 8
F  = flit_width_bits
H  = header_width_bits     = F − payload_width_bits
Q  = payload_width_bits    = F − H
L  = max_packet_flits
packet_payload_capacity_bits = Q × L
```

Packetization:

```
N_packets = ceil(message_bits / packet_payload_capacity_bits)
sum(packet_payload_bits) == message_bits          (exact)
```

The tail packet carries the remainder; zero-byte messages are refused
upstream (`_check_bytes` requires ≥ 1).

Per packet `i` carrying `P_i` useful payload bits:

```
n_i             = ceil(P_i / Q)        flit count
padding_i       = n_i × Q − P_i        0 ≤ padding_i < Q
header_bits_i   = n_i × H
transmitted_bits_i = n_i × F
transmitted_bits_i == header_bits_i + P_i + padding_i   (exact)
```

No byte-aligned `packet_wire_bytes` field exists in Wave D: byte
conversion is only legal where byte alignment is separately proven.

Rules: payload capacity derives from the Wave-B artifact, never from a
config literal; `packet_size` (unqualified) is banned (D0-C004); the
legacy `bytes_per_element` is not a payload authority (D0-C008).

## 19. Flit semantics

- `flit_width_bits` = physical channel width; v1 requires exactly one
  flit per channel beat and homogeneous channel widths
  (`packet_format.py` validation). Byte alignment is **not** required.
- Flit types: `SINGLE | HEAD | BODY | TAIL`; header metadata repeats in
  every flit (hence `header_bits_i = n_i × H`).
- Terminology is fixed: *logical payload bytes*, *logical payload bits*,
  *packet payload capacity bits*, *header bits*, *padding bits*,
  *transmitted wire bits*, *flit count*. Padding bits are transmitted —
  they are part of `transmitted_bits_i`, never an add-on to it.
- BookSim mapping: the cfg `packet_size` is **flits**
  (EXTERNAL-CONTRACT-NEEDED to confirm the fork's per-packet override
  path); Srota passes packet sizes through trace records, not config
  names (Wave B ruling preserved).

## 20. Traffic-class / VC relationship

Wave B owns VC semantics (`model/vc_assignment.py`:
`traffic_class_to_vcs`, `vc_to_routing_class`). Wave D **consumes** it:
each `LogicalMessage` carries a traffic-class name that must exist in the
VC assignment; unknown class → refuse. Wave D creates no second mapping.
Operation kind → traffic class is declared per workload, not inferred.

## 21. Trace authority

Classification of current formats:

| Format | Carries | Class |
|---|---|---|
| DSE `.trace` (5-col) | timestamp, src, dst, class, packet_size_flits | SEMANTIC_SOURCE (packet-level), LOSSY (no operation id/phase) |
| Chakra ET | op graph, comm_size bytes, deps | DERIVED_ARTIFACT (from the artifact) |
| ASTRA system/network/logical JSON | implementations, npus-per-node, dims | DERIVED_ARTIFACT |
| serving cluster JSON | instances, tp/pp/ep, pd_type | SEMANTIC_SOURCE (external, serving-only) |
| `*.anynet` | router adjacency | FABRIC (Wave B) |

Rule: a derived trace is never a second semantic authority; only the
canonical workload artifact and an explicitly bound source trace carry
semantics.

## 22. Serving relationship

Serving is a **workload event source**, not a competing rank/fabric
authority. Its cluster JSON may supply `(tp, pp, ep, dp, pd_type)`, which
must be mapped into the design rank space with an explicit, checkable
rule; unmappable configurations refuse. Serving execution remains
BLOCKED (`capabilities.py` registry: `SERVING_BOOKSIM2.execution =
BLOCKED`); nothing in Wave D unblocks it.

## 23. Identity hierarchy

```
workload_id        workload/canonical.py content hash (ops+parallelism)
parallelism_id     H(tp, pp, ep, dp)                      [new, D1]
mapping_hash       model/mapping.py                        [existing]
operation_graph_id H(workload_id, parallelism_id, phase structure) [new, D2]
message_artifact_id H(operation_graph_id, schedules)       [new, D3]
packetization_id   H(message_artifact_id, packet_payload_capacity_bits) [new, D4]
traffic_id         H(packetization_id, flit_width_bits, replication schedule) [new, D4]
wave_d_semantics_id H(WaveDWorkloadSemantics version + declared fields
                      + model descriptor content hash)      [new, D1]
```

Dependencies: changing the mapping changes `mapping_hash` and everything
downstream of it, but not `workload_id`. Changing the packet payload
capacity changes `packetization_id`/`traffic_id` only. Output paths,
labels and JSON ordering never change any identity (Wave C rule
preserved).

### 23.1 Frozen CompileRequest identity

Wave D does **not** reinterpret the frozen Wave-B/C `design_hash`
(`model/compile_model.py:CompileRequest.design_hash`). Its
`canonical_dict` includes `workload.serving_mode`, so `serving_mode`
remains identity-bearing there. Wave D keeps the current CompileRequest
schema and compiler semantics unchanged; any future removal or
reinterpretation of a CompileRequest field requires an explicit
schema/compiler-semantics version bump, after which old documents retain
their original meaning.

### 23.2 Wave-D semantic version boundary

Wave D introduces its own versioned boundary — `WaveDWorkloadSemantics`
v1 — separate from CompileRequest identity. It owns only the fields an
implemented slice actually needs:

```
phase                 PREFILL | DECODE
shape metadata        num_layers, hidden_size, bytes_per_elem,
                      decode_steps, num_experts, top_k
routing policy        EXPLICIT_TRACE (DETERMINISTIC_BALANCED deferred)
collective payload    per-kind meaning (§10.1)
model descriptor      name + content hash (never a bare name lookup)
```

### 23.3 Identity mutation table

| Mutation | IDs that change | IDs that do not change |
|---|---|---|
| rename display label | none | all |
| move workload/trace file | none | all |
| change trace bytes | workload_id and downstream | — |
| change explicit phase | wave_d_semantics_id, operation_graph_id+ | workload_id, mapping_hash |
| change model descriptor content | wave_d_semantics_id+ | mapping_hash |
| change TP/PP/EP/DP | parallelism_id, mapping_hash+ | workload_id |
| change physical mapping | mapping_hash+ | workload_id, parallelism_id |
| change collective schedule | message_artifact_id+ | workload_id, mapping_hash |
| change collective payload | message_artifact_id+ | mapping_hash |
| change P2P transfer id/src/dst/bytes | operation_graph_id, message_artifact_id+ | mapping_hash |
| change packet payload capacity / flit width | packetization_id, traffic_id | everything above |
| change replication schedule | traffic_id | everything above |
| change output directory | none | all |
| change legacy `CompileRequest.serving_mode` | frozen `design_hash` (historical semantics) | no Wave-D phase is fabricated by this change |

## 24. Conservation laws

| Law | Input | Output | Relation | Proof | Domain |
|---|---|---|---|---|---|
| L1 rank cardinality | TP,PP,EP,DP | R | `R = TP·PP·EP·DP` | PROVED_EXACT | all valid |
| L2 rank bijection | coords | rank | `coords(rank(c)) = c` | BOUNDED_EXHAUSTIVE | sizes ≤ 4 |
| L3 mapping completeness | R ranks | placements | `len = R`, injective, contiguous | PROVED_EXACT | v1 mapping |
| L4 group membership | R ranks | groups | each rank in exactly one group per family; `Σ sizes = R` | PROVED_EXACT | all valid |
| L5 collective participants | intent | schedule | `participants(schedule) = participants(intent)` | PROPERTY | §10.1 |
| L6 MoE assignments | tokens, k | assignments | `= tokens × k`; sent = received | PROVED_EXACT | EXPLICIT_TRACE, no drop |
| L7 message payload | op logical bytes | `Σ message payload` | equal, integers | PROVED_EXACT | all |
| L8 packet payload | message_bits | packets | `N = ceil(message_bits / (Q·L))`, `Σ payload_bits = message_bits` | PROVED_EXACT | bits, any F |
| L9 transmitted bits | packet `P_i`, Q, H, F | `transmitted_bits_i` | `n_i·F = n_i·H + P_i + padding_i` | PROVED_EXACT | bits, any F |
| L10 flit padding | `P_i`, Q | `padding_i` | `padding_i = n_i·Q − P_i`, `0 ≤ padding_i < Q` | PROVED_EXACT | bits, any F |
| L10b collective aggregate | per-kind `B`, `k` | aggregate network payload | §10.1 table (primary invariant) | PROVED_EXACT | `B % k == 0` where required |
| L11 multicast delivery | payload, N | delivered | `= payload × N` | PROVED_EXACT | SOURCE_REPLICATION |
| L12 KV ownership | produced | resident+transferred+discarded | equality, integers | PROVED_EXACT | v1 local |
| L13 quiescence | submitted | completed | equal (or explicit cancel/drop/fail) | DIFFERENTIAL | backend exact only |

## 25. Proof classes

`PROVED_EXACT` (algebraic, no sampling) · `BOUNDED_EXHAUSTIVE` (finite
domain enumerated) · `PROPERTY_VALIDATED` (generated inputs) ·
`DIFFERENTIALLY_VALIDATED` (independent implementation/oracle) ·
`EMPIRICALLY_CALIBRATED` (measured fit — never called proof) ·
`OBSERVED` (single run) · `NOT_RUN` · `UNSUPPORTED`.

## 26. Independent oracle plan

Required oracles (pure, no production calls):

```
ref_rank(coords) / ref_coords(rank)          (integer closed form)
ref_group_members(family, sizes, coords)
ref_collective(kind, k, B) -> (steps, messages, message_bytes,
                               per_rank_sent, aggregate)   §10.1 table
ref_packetize(message_bits, Q, L) -> packet payload bits
ref_flitize(P_i, Q, H, F) -> (n_i, padding_i, transmitted_bits_i)
ref_multicast(payload, N)
```

Forbidden: `expected = production(input); actual = production(input)`.

## 27. Property-based test plan

Hypothesis properties (constraints: sizes 1–4, `R ≤ 64`; message_bits
1–524288; Q ∈ {1,8,64,256,1024}; F ∈ {16,32,64,65,128,256}; H < F;
L ≥ 1):

rank bijection; group disjointness/coverage; mapping injectivity;
collective aggregate conservation (§10.1); message payload conservation;
packet payload conservation in bits; flit padding conservation with
non-byte-aligned widths; identity path-independence; declared-nonsemantic
permutations preserve identity.

## 28. Bounded exhaustive test plan

```
TP,PP,EP,DP ∈ [1,4]  (all 256 combinations; R ≤ 64 → all pass)
message_bits ∈ {8,16,504,512,520,2040,2048,2056,32760,32768,32776}
Q ∈ {1,8,64,256,1024}   (payload width bits)
F ∈ {16,32,64,65,128,256}   (65 exercises the non-byte-aligned path)
L ∈ [1,8]
N ∈ [1,8]
k ∈ [2,8]   (collective participants; k=1 is not represented, §10.3)
```

## 29. Metamorphic test plan

| Transformation | Expected effect | Assumption |
|---|---|---|
| move workload file | identical identity | path not semantic |
| reorder non-semantic input | identical identity | order declared nonsemantic |
| double payload | double logical/message bytes | integer |
| increase packet payload capacity | packet count non-increasing | message_bits fixed |
| increase F | flit count non-increasing | payload/header widths fixed |
| TP=1 | no TP collective operation is generated | §10.3 singleton rule |
| PP=1 | zero PP transfers | §12 |
| EP=1 | no EP routing collective is generated | §10.3 |
| DP=1 | no DP collective operation is generated | §10.3 |

(A one-member collective object is never produced, so “identity/no-op”
statements apply to *operation generation*, not to a degenerate object.)

## 30. Mutation/adversarial test plan

| Mutation | Must fail |
|---|---|
| delete/duplicate/swap rank | L1/L2/L3 |
| two ranks → one agent | L3 injectivity |
| nonexistent endpoint | L3 |
| drop/duplicate collective participant | L5 |
| delete/duplicate message | L7 |
| ±1 byte payload | L7 |
| wrong src/dst | message identity |
| drop/duplicate tail packet | L8 |
| wrong packet payload bits | L8 |
| drop/duplicate flit; wrong width/padding | L9/L10 |
| non-divisible collective chunk (`B % k != 0`) | §10.2 refusal |
| duplicate a SEND/RECV half as two transfers | §15.1 |
| change dependency / introduce cycle | §15 acyclicity |
| change KV owner; drop KV transfer | L12 |
| change expert assignment | L6 |

## 31. Unsupported matrix

| Capability | Status |
|---|---|
| inference | EXACT (v1 scope) |
| training / backward / 1F1B | UNSUPPORTED |
| endpoint-level rank→fabric mapping | EXACT |
| physical-node-aware semantics | DEFERRED (PhysicalNode is bookkeeping only, §5) |
| multi-instance (serving) | DEFERRED |
| TP / PP / DP | EXACT |
| EP | EXACT (no drop) |
| MoE top-k routing | EXACT with EXPLICIT_TRACE only |
| DETERMINISTIC_BALANCED routing | DEFERRED (underdefined) |
| token dropping | UNSUPPORTED |
| continuous batching | UNSUPPORTED |
| static batching | EXACT |
| phase tagging (PREFILL / DECODE) | EXACT |
| explicit workload ops + declared comm bytes | EXACT |
| automatic model-shape → operation synthesis | DEFERRED |
| P/D disaggregation | DEFERRED |
| KV transfer across ranks | UNSUPPORTED in row lowering; canonical `P2PTransfer` only |
| multiple ranks per accelerator | UNSUPPORTED |
| multiple endpoints per accelerator | DEFERRED |
| multicast (SOURCE_REPLICATION) | EXACT for the selected schedule |
| multicast (HARDWARE_REPLICATION) | UNSUPPORTED / DEFERRED (refuse, do not substitute) |
| non-ring collective algorithms | UNSUPPORTED |
| uneven collective chunks (`B % k != 0`) | UNSUPPORTED |
| serving execution | BLOCKED |
| analytical execution | UNSUPPORTED |
| RTL/UVM/formal | NOT_RUN |

## 32. Assumption ledger

| id | assumption | scope | why | if false | fidelity | removal |
|---|---|---|---|---|---|---|
| A1 | one rank per accelerator | v1 | injective placement | oversubscription semantics undefined | PHYSICAL_MAPPING | Wave E |
| A2 | SOURCE_REPLICATION is the selected multicast schedule | v1 | no hardware model yet | hardware replication must be refused (not substituted) | MULTICAST_REPLICATION | Wave E/HW |
| A3 | ring allreduce / direct alltoall | v1 | single algorithm per kind | traffic changes | MESSAGE_PAYLOAD | later |
| A4 | no token dropping | v1 | conservation clarity | assignments change | MOE_ROUTING | later |
| A5 | static batching | v1 | decode defined per step | schedule changes | OPERATION_GRAPH | later |
| A6 | header repeats in every flit | v1 | Wave-B layout | transmitted bits change | FLITIZATION | later |
| A7 | pipeline-local KV | v1 | no P/D model | KV transfers missing | KV_PLACEMENT | Wave D5+ |
| A8 | homogeneous channel width | v1 | Wave-B validation | flit width undefined | FLITIZATION | later |
| A9 | equal collective chunks (`B % k == 0`) | v1 | exact integer arithmetic | uneven partition policy needed | MESSAGE_PAYLOAD | later |
| A10 | explicit workload ops (no shape-derived synthesis) | v1 | avoid invented science | operation generator needed | OPERATION_GRAPH | later |

## 33. Migration plan

| Subsystem | Action |
|---|---|
| `workload/canonical.py` | REUSE (extend with phases/graph) |
| `workload/lowering.py` | EXTEND (refuse unrepresentable, keep conservation) |
| `model/placement.py`, `model/mapping.py` | REUSE (authority) |
| `model/packet_format.py`, `model/vc_assignment.py` | REUSE (authority) |
| `simulation/model_to_trace.py` | ADAPT (integer reference semantics, explicit units) |
| `simulation/astrasim_adapter.py` | ADAPT (logical dims must refuse, not degrade) |
| `simulation/traces.py` | LEGACY (packet-level, lossy; keep as source format) |
| serving stack (`core/serving.py`, `experiment_serving.py`) | DEFER (BLOCKED) |
| `synthesis/evaluator.py` `packet_size=8` | LEGACY (legacy CLI, blocked) |
| `scripts/collectives.py`, `generate_chakra_trace.py` | LEGACY (research scripts) |
| `CompileRequest.Workload.total_npus` | REMOVE (alias to `world_size`) |
| `bytes_per_element` | REMOVE from payload use; explicit field in Wave D |

## 34. Implementation slices

| Slice | Invariant |
|---|---|
| D1 | Every logical rank has one deterministic identity and one valid supported placement; TP/PP/EP/DP groups derive from that authority. |
| D2 | Every supported workload becomes one deterministic causal operation graph with exact rank/group ownership; unsupported behavior refuses. |
| D3 | Every communication operation lowers to exactly the mathematically expected logical messages and payload bytes. |
| D4 | Every logical payload byte is accounted for through packetization and flitization with exact overhead/padding. |
| D5 | Prefill, decode, pipeline, expert routing, multicast and supported KV movement compose without violating rank, causality or conservation. |
| D-FINAL | Nothing can be added, removed, duplicated, reassigned or silently approximated between intent and backend traffic without identity change, declared fidelity loss, or refusal. |

Each slice DoD: algebraic invariants + independent oracle + property
tests + mutation suite, all checked in.

## 35. Wave-D final seal conditions

```
every requested rank/group/message/packet/flit law has a proof class
no supported operation lacks an independent oracle
no unsupported operation can be silently approximated
identity hierarchy respected (mapping/MTU/width changes move exactly
  the expected IDs)
cross-backend traffic claims carry DIFFERENTIALLY_VALIDATED or better
all Wave-B/Wave-C invariants unchanged
```

## 36. External contract questions

| id | system | question |
|---|---|---|
| EXT-1 | ASTRA-Sim | Do `ring`/`direct` match §10 byte accounting exactly? |
| EXT-2 | BookSim | Is cfg `packet_size` fully overridden by trace packet sizes, and is flit width the channel width? |
| EXT-3 | Chakra | Semantics of `involved_dim` and `comm_size` (bytes) per node type? |
| EXT-4 | LLMServingSim | Exact mapping of `(tp_size, pp_size, ep_size, dp_group, pd_type)` onto a Cartesian rank space? |
| EXT-5 | Ramulator | Memory timing contract (Wave E scope). |
