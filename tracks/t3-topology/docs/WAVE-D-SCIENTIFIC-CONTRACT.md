# Wave D Scientific Contract — Distributed Semantics (D0 → D-SEAL)

Status: **SEALED v1 supported domain** — the D0 design rulings below are
backed by production modules in `dse/veritx_dse/waved/`, persisted as
first-class resources (`wavedworkload`, `parallelism`, `wavedsemantics`,
`opgraph`, `messages`, `traffic`) with verified loaders, and consumed by
the single product control plane (`SrotaControlPlane`) for Wave-D
semantic workloads. Proof suites:

```
dse/tests/test_wave_d_semantics.py       collective/P2P/multicast laws
dse/tests/test_wave_d_physical.py        packet/flit/identity + real runs
dse/tests/test_wave_d_authenticity.py    parent binding + mutation matrix
dse/tests/test_wave_d_contract.py        contract/D0 audit pins
dse/tests/test_wave_d_seal.py            immutability, geometry seam,
                                         strict loaders, transplant
                                         attacks, product E2E + tamper
```

The D0 text is preserved as the normative ruling set. Every §31 row
carries its implementation status; §23.2's identity DAG and §37's
closure items are executed code, not plan.

Base: Wave C-SEAL.1 `8455c0450e27486ae034028b76c9a05b94f2ea72`
(branch `wave-d/distributed-semantics`). D-SEAL closes on top of the
D0.2 freeze candidate `75452bd34c0673303a51da83b0d0871fc9623acb`.

This document is the normative contract for Wave D. Every ruling uses the
decision format of the D0 brief (§38 maps brief sections onto this
document):

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

In scope (D1–D-FINAL):

```
workload intent → logical ranks → physical placement → communication
groups → operations → messages → packets → flits → backend traffic
```

Implementation status (v1, this revision):

| Stage | Module | Status |
|---|---|---|
| rank space + groups | `waved/parallelism.py` | EXACT (bounded exhaustive [1,4]^4 + oracle) |
| semantic envelope | `waved/semantics.py` | EXACT (versioned, content-bound descriptor) |
| operation graph | `waved/operations.py` | EXACT (DAG laws enforced) |
| schedules/messages | `waved/messages.py` | EXACT (differential vs oracle) |
| packets/flits | `waved/traffic.py` | EXACT (bit-exact, Wave-B PacketFormat) |
| conservation ledger | `waved/traffic.py` | EXACT (per-class laws, fail closed) |
| backend projection | `waved/backend.py` | VALIDATED (qualified BookSim, quiescence proven) |

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
- Resolution: §22/§21 (representative reads are legal only behind an
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
- Conservation (state, not traffic): `produced_logical_kv =
  currently_resident_logical_kv + explicitly_discarded_logical_kv`,
  integer bytes, within the pipeline-local residency model. No discard
  operation exists in v1, so the law narrows to `produced = resident` for
  the modeled lifetime.
- Transfers are **events**, not state: cross-rank KV movement, when
  supported, is accounted by the P2P law (one `P2PTransfer` → one
  message, §24 L7). Cumulative transfer traffic is never added to a
  residency bucket. MOVE-vs-COPY ownership semantics are not pre-invented
  in Wave D.

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

## 23. Identity hierarchy (explicit parent DAG)

**Fundamental rule.** Every derived content-addressed Wave-D artifact
includes the identities of its **direct semantic parents** plus its own
canonical semantic contents. No dependency is expressed only as prose
("X changes and everything downstream changes") — the parent list below
is the mechanical guarantee.

### 23.1 Existing artifacts (frozen Wave-B/C semantics)

```
workload_id     = WorkloadArtifact content hash over
                  {schema_version, num_participants, parallelism, ops}
                  (workload/canonical.py:_identity_dict) — includes
                  parallelism AND every operation's kind/bytes/
                  participants/src/dst/scope
design_hash     = CompileRequest.design_hash() (frozen; includes
                  workload.serving_mode)
mapping_hash    = MappingArtifact.mapping_hash() over rank → AgentInstance
                  placements ONLY (no tp/pp/ep/dp coordinates)
fabric_hash     = FabricArtifact hardware identity
resolved_fabric_hash = H(design_hash, mapping_hash, fabric_hash)
                  (model/resolved_fabric.py)
packet_format_hash   = PacketFormatArtifact content identity
```

### 23.2 Wave-D artifact parent DAG

```
parallelism_id = H(parallelism_schema_version, TP, PP, EP, DP)
    parents: none (pure parallelism geometry)

wave_d_semantics_id = H(WaveDWorkloadSemantics version, declared
                        semantic fields, model descriptor content hash)
    parents: none (pure Wave-D semantic envelope)

operation_graph_id = H(workload_id, parallelism_id, wave_d_semantics_id,
                       canonical operation nodes, canonical dependency
                       edges)
    parents: workload_id, parallelism_id, wave_d_semantics_id

message_artifact_id = H(operation_graph_id, collective schedule
                        identities, replication intent where it expands
                        logical messages, canonical LogicalMessage
                        contents)
    parents: operation_graph_id

physical_traffic_id = H(message_artifact_id, resolved_fabric_hash,
                        packet_format_hash, replication schedule,
                        canonical physical packet/flit contents)
    parents: message_artifact_id, resolved_fabric_hash,
             packet_format_hash
```

One physical traffic artifact is sufficient; no extra ID ladder is
introduced. Names may follow project vocabulary; the **parent binding** is
normative.

### 23.3 Logical vs physical separation

```
logical workload → operation graph → logical messages
                                        │
                     ResolvedFabric ────┴──→ physical traffic
                     PacketFormat
```

Logical messages use logical rank IDs and are **independent of physical
placement**. A mapping change does not alter `operation_graph_id` or
`message_artifact_id`; it alters `mapping_hash`, `resolved_fabric_hash`
and therefore `physical_traffic_id`.

The physical binding seam is the existing Wave-B `ResolvedFabric` plus
`PacketFormatArtifact`; `ResolvedFabric.validate_against()` already
proves design parallelism, canonical rank namespace, mapping placements,
agent attachment, the fabric child DAG, packet format, VC semantics,
routes and address decode. Wave D consumes that seam and invents no
second rank→endpoint authority.

### 23.4 Frozen CompileRequest identity

Wave D does **not** reinterpret the frozen Wave-B/C `design_hash`
(`model/compile_model.py:CompileRequest.design_hash`). Its
`canonical_dict` includes `workload.serving_mode`, so `serving_mode`
remains identity-bearing there. Wave D keeps the current CompileRequest
schema and compiler semantics unchanged; any future removal or
reinterpretation of a CompileRequest field requires an explicit
schema/compiler-semantics version bump, after which old documents retain
their original meaning.

### 23.5 Wave-D semantic version boundary

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

### 23.6 Identity mutation table (mechanical)

Every row lists **exact direct consequences**. `—` = unaffected.

| Mutation | workload_id | parallelism_id | wave_d_semantics_id | mapping_hash | resolved_fabric_hash | operation_graph_id | message_artifact_id | physical_traffic_id |
|---|---|---|---|---|---|---|---|---|
| rename display label | — | — | — | — | — | — | — | — |
| move workload/trace file | — | — | — | — | — | — | — | — |
| change trace bytes | CHANGES | — | — | — | CHANGES | CHANGES | CHANGES | CHANGES |
| change source op payload (kind/bytes/participants/scope) | CHANGES | — | — | — | CHANGES | CHANGES | CHANGES | CHANGES |
| change canonical P2P src/dst/bytes | CHANGES | — | — | — | CHANGES | CHANGES | CHANGES | CHANGES |
| change TP/PP/EP/DP | CHANGES | CHANGES | only if it carries such fields | CHANGES iff rank→agent placements change | CHANGES | CHANGES | CHANGES | CHANGES |
| change phase / model descriptor (Wave-D envelope) | — | — | CHANGES | — | — | CHANGES where graph semantics depend on it | CHANGES | CHANGES |
| change physical mapping only | — | — | — | CHANGES | CHANGES | — | — | CHANGES |
| change attachment / fabric / packet format only | — | — | — | — | CHANGES per Wave-B | — | — | CHANGES |
| change collective algorithm (not a source workload field) | — | — | — | — | — | — | CHANGES | CHANGES |
| change replication schedule | — | — | — | — | — | — | CHANGES | CHANGES |
| change output directory | — | — | — | — | — | — | — | — |
| change legacy `CompileRequest.serving_mode` | — (Wave-D workload artifact unchanged) | — | — | — | design_hash CHANGES (historical) | — | — | — |

Two audit-relevant facts this table encodes:

- **Parallelism is already inside `workload_id`** (the canonical artifact
  hashes `parallelism`), so a parallelism mutation cannot leave
  `workload_id` stable. `parallelism_id` exists for independently
  referencable rank/group geometry; the redundancy is intentional and the
  frozen workload hash is not modified during Wave D.
- **`mapping_hash` does not necessarily change when parallelism changes.**
  `MappingArtifact` hashes `rank integer → AgentInstance`, not
  coordinates. `TP=4,PP=1,EP=1,DP=1` and `TP=2,PP=2,EP=1,DP=1` both have
  ranks `0..3`; if those ranks map to the same four agents, the mapping
  content is identical and `mapping_hash` legitimately stays equal.
  `ResolvedFabric.validate_against()` remains the authority proving a
  mapping is compatible with a particular design parallelism.

## 24. Conservation laws (split by operation class)

No law may use a quantity that means different things across operation
types. In particular there is **no** generic
`Σ message payload == op logical bytes` law: it is false for collectives
and for source-replicated multicast.

Notation: `B` = the per-kind payload of §10.1; `k` = participant count;
`N` = destination count.

| Law | Class | Input | Output | Relation | Proof | Domain |
|---|---|---|---|---|---|---|
| L1 rank cardinality | rank space | TP,PP,EP,DP | R | `R = TP·PP·EP·DP` | PROVED_EXACT | all valid |
| L2 rank bijection | rank space | coords | rank | `coords(rank(c)) = c` | BOUNDED_EXHAUSTIVE | sizes ≤ 4 |
| L3 mapping completeness | mapping | R ranks | placements | `len = R`, injective, contiguous | PROVED_EXACT | v1 mapping |
| L4 group membership | rank space | R ranks | groups | one group per family per rank; `Σ sizes = R` | PROVED_EXACT | all valid |
| L5 collective participants | collective | intent | schedule | `participants(schedule) = participants(intent)` | PROPERTY_VALIDATED | §10.1 |
| L6 collective scheduled aggregate payload | collective | kind, k, B | `Σ message payload bytes` | equals the §10.1 aggregate: ALLREDUCE `2(k−1)B`, REDUCESCATTER `(k−1)B`, ALLGATHER `k(k−1)B`, ALLTOALL `(k−1)B`, BROADCAST `(k−1)B` | PROVED_EXACT | divisibility rules |
| L7 P2P message payload | P2P | one `P2PTransfer` payload `B` | messages | exactly one message; `Σ message payload == B` | PROVED_EXACT | canonical P2P |
| L8 multicast source/delivery | multicast | payload `B`, `N` | messages / delivered | `Σ message payload == N·B`; `delivered == N·B`; source logical payload is `B` (one copy) | PROVED_EXACT | SOURCE_REPLICATION |
| L9 MoE assignments | MoE | tokens, k | assignments | `= tokens × k`; sent = received | PROVED_EXACT | EXPLICIT_TRACE, no drop |
| L10 packet payload bits | packet | `message_bits` | packets | `N = ceil(message_bits/(Q·L))`; `Σ payload_bits = message_bits` | PROVED_EXACT | bits, any F |
| L11 transmitted-bit identity | packet/flit | `P_i`, Q, H, F | `transmitted_bits_i` | `n_i·F = n_i·H + P_i + padding_i` | PROVED_EXACT | bits, any F |
| L12 flit padding | flit | `P_i`, Q | `padding_i` | `padding_i = n_i·Q − P_i`; `0 ≤ padding_i < Q` | PROVED_EXACT | bits, any F |
| L13 KV residency state | KV | produced | resident, discarded | `produced = resident + discarded` (no transfer term) | PROVED_EXACT | pipeline-local v1 |
| L14 backend quiescence | backend | submitted | completed | equal (or explicit cancel/drop/fail) | DIFFERENTIALLY_VALIDATED | backend exact only |

KV transfer traffic is **not** a state bucket: when cross-rank KV becomes
supported it is accounted by L7 (one `P2PTransfer` per move), never by
adding cumulative traffic to residency.

### 24.1 Conservation-ledger quantity classes

The future cross-layer ledger records **distinct named quantities**; a
single `bytes` field is forbidden because its meaning depends on the
operation/schedule class.

| Quantity | Meaning | Filled by |
|---|---|---|
| `source_logical_payload_bytes` | one-copy semantic payload of the operation/transfer | D2 |
| `aggregate_scheduled_message_bytes` | `Σ` logical message payload after the schedule (collective/multicast expansion) | D3 |
| `packet_payload_bits` | `Σ` packet payload bits | D4 |
| `transmitted_wire_bits` | `Σ n_i·F` including headers and padding | D4 |
| `delivered_payload_bytes` | payload delivered to destinations | D3/D5 |
| `packet_count`, `flit_count` | integer counts | D4 |
| `backend_injections`, `backend_retirements` | backend-observed counts | D-FINAL |

Relationships (class-dependent, all integers):

```
P2P:          aggregate_scheduled_message_bytes == source_logical_payload_bytes
collective:   aggregate_scheduled_message_bytes == §10.1 aggregate (L6)
multicast:    aggregate_scheduled_message_bytes == N · source_logical_payload_bytes
packet:       Σ packet_payload_bits == 8 · aggregate_scheduled_message_bytes
flit:         transmitted_wire_bits == header_bits + packet_payload_bits + padding_bits
```


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

## 27. Property-based test plan — IMPLEMENTED

Hypothesis properties (constraints: sizes 1–4, `R ≤ 64`; message_bits
1–524288; Q ∈ {1,8,64,256,1024}; F ∈ {16,32,64,65,128,256}; H < F;
L ≥ 1):

| property | status | where |
|---|---|---|
| rank bijection | IMPLEMENTED | `test_wave_d_semantics.py::TestRankBijection` |
| group disjointness / coverage | IMPLEMENTED | `TestGroupLaws` |
| mapping injectivity | REUSED (Wave-B authority) | `test_mapping.py` |
| collective aggregate conservation (§10.1) | IMPLEMENTED | `TestCollectiveEquations` |
| message payload conservation | IMPLEMENTED | `TestMessageLoweringDifferential` |
| packet payload conservation in bits | IMPLEMENTED | `TestPacketization` |
| flit padding conservation, non-byte-aligned widths | IMPLEMENTED | `TestFlitization` |
| identity path-independence | IMPLEMENTED | `TestIdentityStability` |
| declared-nonsemantic permutations preserve identity | IMPLEMENTED | `test_wave_d_authenticity.py` |

## 28. Bounded exhaustive test plan — IMPLEMENTED

```
TP,PP,EP,DP ∈ [1,4]  (all 256 combinations; R ≤ 64 → all pass)
message_bits ∈ {8,16,504,512,520,2040,2048,2056,32760,32768,32776}
Q ∈ {1,8,64,256,1024}   (payload width bits)
F ∈ {16,32,64,65,128,256}   (65 exercises the non-byte-aligned path)
L ∈ [1,8]
N ∈ [1,8]
k ∈ [2,8]   (collective participants; k=1 is not represented, §10.3)
```

The 256-combination parallelism sweep and the `F = 65` non-byte-aligned
flit path are executed in `test_wave_d_semantics.py` (oracle
cross-checked), not merely declared.

## 29. Metamorphic test plan — IMPLEMENTED

| Transformation | Expected effect | Assumption | status |
|---|---|---|---|
| move workload file | identical identity | path not semantic | IMPLEMENTED |
| reorder non-semantic input | identical identity | order declared nonsemantic | IMPLEMENTED |
| double payload | double logical/message bytes | integer | IMPLEMENTED |
| increase packet payload capacity | packet count non-increasing | message_bits fixed | IMPLEMENTED |
| increase F | flit count non-increasing | payload/header widths fixed | IMPLEMENTED |
| TP=1 | no TP collective operation is generated | §10.3 singleton rule | IMPLEMENTED |
| PP=1 | zero PP transfers | §12 | IMPLEMENTED |
| EP=1 | no EP routing collective is generated | §10.3 | IMPLEMENTED |
| DP=1 | no DP collective operation is generated | §10.3 | IMPLEMENTED |
| different mapping, same design | logical IDs stable, physical ID moves | §23.3 | IMPLEMENTED (`test_wave_d_seal.py`) |
| different packet format, same design | logical IDs stable, physical ID moves | §23.3 | IMPLEMENTED (`test_wave_d_seal.py`) |

(A one-member collective object is never produced, so “identity/no-op”
statements apply to *operation generation*, not to a degenerate object.)

## 30. Mutation/adversarial test plan — IMPLEMENTED

Every row feeds a mutated object into a REAL production validator or
loader (never `mutate(copy); validate(original)`).

| Mutation | Must fail | status |
|---|---|---|
| delete/duplicate/swap rank | L1/L2/L3 | IMPLEMENTED |
| two ranks → one agent | L3 injectivity | IMPLEMENTED (Wave-B seam) |
| nonexistent endpoint | L3 | IMPLEMENTED |
| drop/duplicate collective participant | L5 | IMPLEMENTED |
| delete/duplicate message | L7 | IMPLEMENTED |
| ±1 byte payload | L7 | IMPLEMENTED |
| wrong src/dst | message identity | IMPLEMENTED |
| drop/duplicate tail packet | L8 | IMPLEMENTED (strict parser) |
| wrong packet payload bits | L8 | IMPLEMENTED (strict parser + oracle) |
| drop/duplicate flit; wrong width/padding | L9/L10 | IMPLEMENTED |
| non-divisible collective chunk (`B % k != 0`) | §10.2 refusal | IMPLEMENTED |
| duplicate a SEND/RECV half as two transfers | §15.1 | IMPLEMENTED |
| change dependency / introduce cycle | §15 acyclicity | IMPLEMENTED |
| generic `Σ message payload == op bytes` on a collective | L6 | IMPLEMENTED |
| `N·B` multicast traffic vs one-copy source payload | L8 | IMPLEMENTED |
| change KV owner; drop KV transfer | L12 | NOT_RUN (KV lowering UNSUPPORTED, §14) |
| change expert assignment | L6 | NOT_RUN (EXPLICIT_TRACE only) |
| same world size, different geometry transposition | §9 refusal | IMPLEMENTED (`test_wave_d_seal.py`) |
| persisted parent transplant (opgraph/messages/traffic) | loader refusal | IMPLEMENTED (`test_wave_d_seal.py`) |
| persisted content tamper (nodes/messages/packets) | loader refusal | IMPLEMENTED (`test_wave_d_seal.py`) |
| tampered parent invalidates a persisted result | result not VERIFIED | IMPLEMENTED (`test_wave_d_seal.py`) |
| forged evidence counter (quiescence) | BackendFailure | IMPLEMENTED (`test_wave_d_physical.py`) |

## 31. Unsupported matrix

| Capability | Status | Implemented? |
|---|---|---|
| inference | EXACT (v1 scope) | YES — `waved/workload.py`, `waved/operations.py` |
| training / backward / 1F1B | UNSUPPORTED | YES (refused: `KIND_*` vocabulary is closed) |
| endpoint-level rank→fabric mapping | EXACT | YES — `waved/traffic.py::_rank_to_endpoint_maps` |
| physical-node-aware semantics | DEFERRED (PhysicalNode is bookkeeping only, §5) | DECLARED (no code path consumes PhysicalNode) |
| multi-instance (serving) | DEFERRED | DECLARED |
| TP / PP / DP | EXACT | YES — `waved/parallelism.py` |
| EP | EXACT (no drop) | YES |
| MoE top-k routing | EXACT with EXPLICIT_TRACE only | PARTIAL — operation kinds exist; routing must be explicit |
| DETERMINISTIC_BALANCED routing | DEFERRED (underdefined) | DECLARED |
| token dropping | UNSUPPORTED | DECLARED |
| continuous batching | UNSUPPORTED | DECLARED |
| static batching | EXACT | YES (step index in the node) |
| phase tagging (PREFILL / DECODE) | EXACT | YES — `WaveDWorkloadSemantics.phase`, `OperationNode.phase` |
| explicit workload ops + declared comm bytes | EXACT | YES — `waved/workload.py` |
| automatic model-shape → operation synthesis | DEFERRED | DECLARED (nothing infers ops from shape) |
| P/D disaggregation | DEFERRED | DECLARED |
| KV transfer across ranks | UNSUPPORTED in row lowering; canonical `P2PTransfer` only | YES (refused) |
| multiple ranks per accelerator | UNSUPPORTED | YES (Wave-B mapping injectivity) |
| multiple endpoints per accelerator | DEFERRED | DECLARED |
| multicast (SOURCE_REPLICATION) | EXACT for the selected schedule | YES — `waved/messages.py` |
| multicast (HARDWARE_REPLICATION) | UNSUPPORTED / DEFERRED (refuse, do not substitute) | YES (refused: `UnsupportedSemantics`) |
| non-ring collective algorithms | UNSUPPORTED | YES (refused: `SCHEDULES` is pinned) |
| uneven collective chunks (`B % k != 0`) | UNSUPPORTED | YES (refused: `ref_collective`) |
| serving execution | BLOCKED | YES (`capabilities.SERVING_BOOKSIM2.execution`) |
| analytical execution | UNSUPPORTED | YES |
| RTL/UVM/formal | NOT_RUN | YES (no surface claims otherwise) |

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

### 34.1 D1 handoff contract

D1 may implement **only** these, and must not decide any identity-parent
question itself:

```
parallelism identity            parallelism_id = H(version, TP, PP, EP, DP)
rank namespace                  placement.py rank_of/coords_of (reused)
rank-coordinate bijection       L2
group construction              §9 families
mapping validation/composition  MappingArtifact + ResolvedFabric seam (§23.3)
Wave-D semantics envelope       WaveDWorkloadSemantics v1 skeleton required
                                by D1 (version + declared fields + bound
                                model descriptor hash)
```

The parent DAG in §23.2 is normative for D1: `operation_graph_id` already
names `workload_id`, `parallelism_id` and `wave_d_semantics_id` as its
direct parents, so D1 must not restructure the hash dependency graph, and
D2/D3/D4 must consume the parent lists as written.

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

## 37. D-SEAL closure — product integration and authenticity

D0 specified the semantics; D-SEAL closed the gap between "verified
library" and "trusted product architecture". Each item below is executed
code with a test that feeds a real mutated object into a real validator.

### 37.1 Transitive immutability

A frozen dataclass is only skin deep. Every Wave-D artifact now copies
caller-owned containers into an immutable canonical value tree
(`waved/immutable.py::freeze` / `FrozenMap`); `thaw` converts back at
JSON boundaries. Mutating the caller's dict after construction cannot
change an artifact, its identity, or a lowered child.

```
mutate caller's shape_metadata / node.detail
  → semantics_id(), operation_graph_id(), message_artifact_id() unchanged
```

### 37.2 Logical ↔ physical geometry seam

`PhysicalTrafficArtifact` refuses to bind a logical rank geometry to a
bundle compiled from a different geometry, even at equal world size:

```
logical TP=4 PP=1 EP=1 DP=1   (world_size 4)
bundle  TP=2 PP=2 EP=1 DP=1   (world_size 4)
  → MappingInvalid: equal world size is not semantic equivalence
```

The check compares against `bundle.inventory.parallelism` and the
compiled design workload geometry. `SrotaControlPlane` applies the same
seam at compile time against the preset's compiled design.

### 37.3 Bundle revalidation

Physical traffic calls `bundle.revalidate()` (Wave-B's own seam) before
any rank→endpoint binding: a bundle assembled around a stale/tampered
child can never feed traffic.

### 37.4 Persisted resources and verified loaders

Six content-addressed resources preserve the chain:

```
wavedworkload   WaveDWorkload            (declared semantics)
parallelism     ParallelismArtifact      (rank geometry)
wavedsemantics  WaveDWorkloadSemantics   (versioned envelope)
opgraph         OperationGraph           (causal DAG)
messages        LogicalMessageArtifact   (scheduled messages)
traffic         PhysicalTrafficArtifact  (packets + flits)
```

`waved/immutable.py`…`waved/strict.py` implement the persisted-resource
contract (exact type tag, exact schema version, required embedded ID,
unknown fields refused); `application/waved_resources.py` implements the
verified loaders, which require

```
requested filename ID == embedded resource_id == recomputed ID
```

plus resolved-and-verified parents and semantic revalidation. The
ConservationLedger is NOT persisted: it is derived from a verified
`PhysicalTrafficArtifact` and recomputed on demand, so there is no
ledger object to forge.

### 37.5 Product integration (one science path)

`SrotaControlPlane` is the single product authority for both workload
kinds:

```
LEGACY_TRACE       packet bytes → BookSim (unchanged legacy path)
WAVE_D_SEMANTIC    declared operations → verified graph → verified
                   logical messages → verified physical traffic →
                   DERIVED trace → sealed qualified BookSim
```

A legacy trace can never be labelled Wave-D provenance, and a Wave-D
workload cannot bypass its chain: `evaluate()` re-loads the traffic
through the verified loader and runs conservation + oracle + projection
gates before the spawn. The BookSim trace is a derived backend input.

### 37.6 Identity separation

`EvaluationPlan` binds the Wave-D chain (`waved_workload_id`,
`parallelism_id`, `wave_d_semantics_id`, `operation_graph_id`,
`message_artifact_id`, `physical_traffic_id`, `resolved_fabric_hash`,
`packet_format_hash`) and the derived workload resource binds it too, so
identical rendered BookSim bytes from a legacy trace and a Wave-D
workload never share a plan/experiment identity. A result carries the
same chain plus the sealed execution counters, and re-derives all of
them on load.

### 37.7 Wave-B evidence stays frozen

Wave D does NOT modify `CertifiedBookSimEvidence`. The Wave-D
quiescence proof uses only sealed counters:

```
delivered_packets == expected_packets
flits_injected == flits_accepted == expected_flits
```

A missing counter is a hard failure, never a skipped check.

### 37.8 What is NOT closed

| item | status |
|---|---|
| KV / expert-routing lowering | UNSUPPORTED (refused), §14 |
| physical-node semantics, multi-instance, P/D disaggregation | DEFERRED, §31 |
| uneven collective chunking | UNSUPPORTED (refused), §10.2 |
| shape → operation synthesis | DEFERRED, §31 |
| embedded route dump export | NOT_RUN (external contract, §36) |

## 38. Citation convention (brief → contract)

Code and tests cite THIS document's section numbers. The D0 brief used a
different numbering; the mapping for older references is:

| D0 brief | contract |
|---|---|
| §31–§41 (physical traffic, packetization, flit, ledger) | §18–§19, §24 |
| §35–§37 (bit-exact rules) | §18, §19 |
| §38 (oracle) | §26 |
| §39–§41 (ledger classes, fail-closed) | §24.1, §24 |
| §42–§43 (mutation, metamorphic matrices) | §30, §29 |
| §46–§50 (backend projection, trace losslessness, quiescence) | §21, §23.3 |
| §52 (real execution) | §21 |
| §56 (serving relationship) | §22 |
| §60 (identity mutation matrix) | §23.6 |
| §61–§62 (typed refusals) | §31, §10.2 |
| §67 (proof classes) | §25 |
| §68 (independent oracle) | §26 |
| §72–§73 (real-execution evidence) | §21 |
| §79 (decision format) | this document's preamble |
