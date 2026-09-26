# INTENT-WORKLOAD — Domain B specification (Gate 2, closure pass)

Domain row: `intent-ontology.yaml :: domains.WORKLOAD`
Enforced by: `scripts/check_intent_ontology.py`
Supersedes the first-pass audit. **Design closure only** — no v4 code written.

---

## 0. Reality header

Verified at call sites. Four workload generations coexist today.

| Generation | Artifact | Node type | Class name |
|---|---|---|---|
| Phase-9 | `workload/canonical.py::WorkloadArtifact` | `WorkloadOp` | — |
| Wave-D canonical | `workload/graph.py::WorkloadGraph` | `OperationNode` | **`OperationNode`** |
| Wave-D "Waved" | `workload/operations.py::OperationGraph` | `OperationNode` | **`OperationNode`** |
| v3 declared | `model/compile_model.py::WorkloadV3` | — | `CollectiveIntent` |

`workload/canonical_graph.py` is a **retired shim** re-exporting `graph.py`.

| Concept | Reality | Evidence |
|---|---|---|
| model family | R2 | `ModelFamily` `compile_model.py:265`; ≠ dense refuses at lowering |
| model name | R1 presentation | `views.py:156` |
| shape metadata (6 keys) | R2 identity-bearing | `semantics.py:44` |
| serving mode | R1 decorative, **not a phase** | `semantics.py:36` |
| phases PREFILL/DECODE | R2 tags | `graph.py:148` |
| operation graph | R2 | `graph.py:645` |
| dependency edges | R2 DAG | `graph.py`, `operations.py:270` |
| compute node | R2 kind / **no duration** | `_COMPUTE_KEYS` `graph.py:106` |
| collective | R2 | `collectives.COLLECTIVE_KINDS` |
| collective algorithm | **R3 lowering policy** | `SCHEDULES` `collectives.py:33` |
| point-to-point | R2 | `P2P_ROLES = (TRANSFER, SEND, RECV)` |
| multicast | R2 | `KIND_MULTICAST`, `REPLICATION_KINDS` |
| expert markers | R2 (two forms) | `EXPERT_BEGIN/END` **vs** `EXPERT_DISPATCH/COMBINE` |
| PIM channel ops | R2 Phase-9-lineage | `PIM_CHANNEL {channel}`, `PIM_END {}` |
| KV read/write | R2 operations.py only | `KIND_KV_READ/WRITE` |
| memory operands + locations | R2 Phase-9, still consumed | `WorkloadOp`; `simulation/ramulator.py` |
| payload | R2 explicit bytes | `payload_bytes > 0` |
| symbolic scope | R2 (two forms) | `CollectiveDimension` (v3) vs `ALL`/mask (Phase-9) |
| numeric TP/DP/PP/EP | R2 **wrong domain** | `WorkloadGraph.parallelism`, `participant_count` |
| repeat / conditional / tensor | R0 | — |
| request trace / scheduler / KV state | R4 serving | `canonical_serving.py:3` |

---

## 1. Locked target architecture

```text
                         ModelSpec
                            │
                  ┌─────────┴──────────┐
            WorkloadIntent        ServingExperiment
                  │                    │
        semantic operation graph      │ requests · scheduler
                  │                    │ batching · service model
                  │              LLMServingSim
                  │                    │
                  └─────────┬──────────┘
                            │
                    ParallelismIntent
                            │
                     participant groups
                            │
                  ┌─────────┴──────────┐
                  │                    │
            static lowering      serving runtime ops
                  └─────────┬──────────┘
                            │
                         FABRIC
```

**Shared:** `ModelSpec`, `ParallelismIntent`, Fabric identity.
**Not shared:** operation execution graph, scheduler, request trace,
batching, runtime serving rounds, runtime dispatch/combine semantics.

**No fifth model is introduced.** The four generations are collapsed, not
added to.

---

## 2. W1/W2 — one canonical static workload authority

| Authority | Target role |
|---|---|
| `graph.py::WorkloadGraph` | **TARGET CANONICAL LINEAGE** |
| `operations.py::OperationGraph` | **DERIVED PROJECTION / RETIRE** |
| Phase-9 `WorkloadArtifact` | **LEGACY MIGRATION SOURCE ONLY** |
| `WorkloadV3` | **PRODUCT AUTHORING ADAPTER — not scientific authority** |

**One scientific authority.** The target class is `WorkloadIntentV4`,
in-memory-represented by the `WorkloadGraph` lineage with the Domain C
fields removed (§7). If a second representation exists it is a **strict
projection/serialization** of the canonical object, never a peer.

New code must not use the retired authorities except in migration code
(§31).

---

## 3. Duplicate class names — collision table

| Name | Module A | Module B | Target meaning | Migration |
|---|---|---|---|---|
| `OperationNode` | `graph.py:472` — canonical node, optional `owner/phase/step`, closed `detail` | `operations.py:182` — Waved node, **required** `phase/owner/step`, free dict `detail` | `graph.py` meaning | rename B → `WavedOperationNode`; retire |
| `CollectiveIntent` | `compile_model.py:1910` — v3 declared (kind, dimension, payload_bytes, traffic_class, source_rank) | `operations.py:67` — lowered (kind, participants, payload_bytes, collective_id) | v3 declared is the **declaration**; lowered form is derived | rename B → `LoweredCollective` |
| `OperationGraph` | — | `operations.py:227` | derived projection only | retire |
| `WorkloadGraph` | `graph.py:645` | — | canonical | evolve |

Temporary import aliases are acceptable **during migration**; a permanent
alias like `OperationNode as WavedOperationNode` is not architecture.

---

## 4. Operation-vocabulary reconciliation

| Kind | graph.py | operations.py | Phase-9 canonical.py | v3 | Class | Target |
|---|---|---|---|---|---|---|
| `COMPUTE` | ✔ | ✔ | ✔ | — | EXACT_EQUIVALENT | **COMPUTE** |
| `COLLECTIVE` | ✔ | ✔ | ✔ (5 kinds) | ✔ (5 kinds) | EXACT_EQUIVALENT | **COLLECTIVE** |
| `P2P` | ✔ | ✔ | `SEND`/`RECV` rows | — | RENAMED_EQUIVALENT | **P2P** (roles TRANSFER/SEND/RECV) |
| `MULTICAST` | ✔ | ✔ | — | — | EXACT_EQUIVALENT | **MULTICAST** |
| `EXPERT_BEGIN` | ✔ | — | ✔ (carries `comm_kind`) | — | RENAMED_EQUIVALENT | **EXPERT_DISPATCH** |
| `EXPERT_END` | ✔ | — | ✔ (carries `comm_kind`) | — | RENAMED_EQUIVALENT | **EXPERT_COMBINE** |
| `EXPERT_DISPATCH` | — | ✔ | — | — | TARGET_ONLY | **EXPERT_DISPATCH** |
| `EXPERT_COMBINE` | — | ✔ | — | — | TARGET_ONLY | **EXPERT_COMBINE** |
| `PIM_CHANNEL` | ✔ (`{channel}`) | — | — | — | PARTIAL_EQUIVALENT | **MEMORY** |
| `PIM_END` | ✔ (`{}`) | — | — | — | PARTIAL_EQUIVALENT | **MEMORY** |
| `KV_READ` / `KV_WRITE` | — | ✔ | — | — | **NO_EQUIVALENT** | out of scope (serving/KV) |
| — | — | — | — | `Dependency.kind` | LEGACY_ONLY | dependency edge kind |

**The union is not adopted.** A target kind survives only with defined
semantics, a consumer or deliberate contract, and clear identity meaning.
**`BARRIER` is not introduced** — nothing consumes it.
Unknown kinds fail closed.

**Decisive reconciliation fact:** Phase-9 `EXPERT_BEGIN/END` are *structural
markers that carry the dispatch/combine collective* via `comm_kind`
(`canonical.py:64`). `operations.py` models them as *distinct operations*.
The target adopts the **operations** form: dispatch and combine are
operations, not markers.

---

## 5. Canonical operation ontology

| Kind | Meaning | Required | Optional | Scope | Payload | Support |
|---|---|---|---|---|---|---|
| `COMPUTE` | semantic compute / dependency node | `operation_id`, `kind`, `deps` | `phase`, `step`, `owner`, `label` | owner rank | none | **REAL** |
| `COLLECTIVE` | semantic collective | `collective_kind`, `participant_scope`, `payload_bytes` | `source` (BROADCAST root) | one symbolic axis | per-kind bytes | **REAL** |
| `P2P` | one complete transfer | `role`, `src`/`dst`, `payload_bytes` | — | explicit endpoints | bytes | **REAL** |
| `MULTICAST` | one payload, N destinations | `source`, `destinations`, `payload_bytes`, `replication` | — | explicit | bytes | **REAL** |
| `EXPERT_DISPATCH` | MoE dispatch | `participant_scope=EP`, `payload_bytes` | `expert_num` | EP axis | bytes | **REPRESENTABLE · static lowering UNSUPPORTED** |
| `EXPERT_COMBINE` | MoE combine | `participant_scope=EP`, `payload_bytes` | `expert_num` | EP axis | bytes | **REPRESENTABLE · static lowering UNSUPPORTED** |
| `MEMORY` | memory channel operation | `channel` | operand bytes + location | — | — | **PARTIAL** (Ramulator path) |

Strict typed variants. **No `type: string` + `attributes: dict`.** Unknown
kinds fail closed. No arbitrary metadata bag enters scientific identity.

---

## 6. Stable operation identity

- `operation_id` is the scientific identity. **Settled (W4).**
- `label` is excluded everywhere (F23: *"source spelling is not science"*).
- Provenance of ids: **user-authored** (expert), **preset-generated**
  (deterministic expansion), **migration-generated** (`legacy-*`).
- Preset expansion ids are deterministic and documented.
- Array position is never identity. Canonical serialization is
  deterministic and **independent of UI order** (§37 B41).

---

## 7. W9 — numeric parallelism leaves WORKLOAD

**Removed from the target canonical `WorkloadIntent`:**

```text
WorkloadGraph.parallelism        (ParallelismShape)
WorkloadGraph.participant_count
WorkloadArtifact.parallelism     (Parallelism)
WorkloadArtifact.num_participants
```

**Kept:** the symbolic dimension reference.

```text
operation:
  kind: COLLECTIVE
  collective_kind: ALLREDUCE
  participant_scope: TP        # ← symbolic
```

`participant_count: 8` is **not** declared. Numeric shape is Domain C.

```text
WorkloadIntent + ParallelismIntent → BoundWorkloadGraph
```

`BoundWorkloadGraph` may carry concrete group ids, counts and rank
membership — **because those are derived after binding**. Static lowering
consumes the bound form.

Legacy fields are not deleted destructively; they migrate (§30).

---

## 8. Symbolic participant scope

**Strict contract, existing:** `CollectiveDimension` —
`TP | DP | EP | PP | GLOBAL` (`compile_model.py:1891`).

Rules per operation:

| Operation | Scope requirement |
|---|---|
| COLLECTIVE | exactly one axis, or `GLOBAL` |
| P2P | explicit endpoints (no axis) |
| MULTICAST | explicit source + destinations |
| EXPERT_DISPATCH / COMBINE | `EP` |
| COMPUTE | owner rank only |

`PP` is **not** a collective peer axis — a PP-dimension COLLECTIVE is a
typed refusal at lowering (pipeline stages communicate point-to-point).

**A workload referencing `TP` is valid without knowing `TP = 1|2|8`.**
Feasibility is evaluated after joining Domain C.

Arbitrary scope strings are refused.

---

## 9. W10 — EP has no implicit MoE meaning

**Locked.** `EP` is a parallelism dimension. It is **not** synonymous with
expert dispatch, expert combine, ALLTOALL, or MoE.

```text
EP + ALLTOALL  →  generic ALLTOALL over an EP participant group
```

MoE meaning exists **only** when the operation kind is `EXPERT_DISPATCH` or
`EXPERT_COMBINE`. This distinction survives UI, lowering, evidence and
comparison (§37 B48).

---

## 10. W11 — dispatch and combine are explicit

**Locked.** Two separate semantic operations. No implicit combine from
dispatch. No single EP collective expanded into both.

```text
router / selection  (no static contract — marked, not fabricated)
      ↓
EXPERT_DISPATCH
      ↓
expert compute
      ↓
EXPERT_COMBINE
```

Token-level expert routing is **not fabricated** — `routing_policy` supports
only `EXPLICIT_TRACE`.

---

## 11. Static MoE representable before executable

**Schema expressiveness ≠ current backend support.**

| Object | Status |
|---|---|
| `WorkloadIntent` containing MoE | **VALID** |
| current static lowering | **UNSUPPORTED** (`intent_lowering.py:224`) |
| request-driven serving MoE | supported through LLMServingSim |

A valid intent may be unsupported by a specific lowering path. Semantic MoE
is **not** INVALID merely because the static compiler cannot execute it.

---

## 12. W12 — static and serving relationship

| | Static | Serving |
|---|---|---|
| authority | `WorkloadIntent` → `BoundWorkloadGraph` | LLMServingSim |
| path | static lowering → physical traffic | runtime serving ops → physical network |
| owns | operation graph | arrivals, instances, queues, batching, prefill/decode rounds, scheduler decisions, runtime dispatch/combine |

**Do not force serving to consume `WorkloadIntent` for architectural
symmetry.** Do not claim the graphs are equivalent. No parity is claimed
until an explicit adapter is qualified.

---

## 13. ModelSpec

The six allowlisted, identity-bearing keys — `num_layers`, `hidden_size`,
`bytes_per_elem`, `decode_steps`, `num_experts`, `top_k` — become a reusable
typed **`ModelSpec`**, consumable by both `WorkloadIntent` construction and
`ServingExperiment` configuration.

| Part | Class |
|---|---|
| the six shape keys | **SCIENTIFIC** (hashed by value) |
| `model_descriptor_hash` | **SCIENTIFIC** |
| `model_descriptor_name`, vendor label, preset label | **PROVENANCE** |

Unknown shape keys fail closed unless v4 deliberately extends the schema.
**No arbitrary model-property dictionaries.**

---

## 14. Preset boundary

A preset (`llama_dense_8b`) **generates** `ModelSpec` + `WorkloadIntent`.
The generated objects are the science; the preset label is provenance.

Requirements: versioned · deterministic expansion · expanded objects
inspectable · version recorded. **A compiled workload never needs the preset
implementation to interpret it.**

---

## 15. W15 — `serving_mode` removed from workload science

Evidence: *"serving-mode labels are not phases"* (`semantics.py:36`); the
field has no consumer (`views.py` only); serving does not consume
`WorkloadV3`.

**Decision:** remove `serving_mode` from canonical workload identity. Its
possible homes, by actual consumer:

| Consumer | Home |
|---|---|
| UI workflow choice | workflow/experiment selection |
| preset selection hint | preset metadata |
| `ServingExperiment` configuration | serving experiment |

No identity-bearing workload field remains.

---

## 16. Phase semantics

Minimal and truthful. **No phase-container hierarchy in this closure.**

- Allowed values: `PREFILL`, `DECODE` — strict.
- An operation may carry an **optional phase tag** where meaningful.
- **No** `TRAINING` / `BACKWARD` / `OPTIMIZER` / `CUSTOM` — no semantics exist.
- **No** phase membership container, ordering object, or repetition object.
- Absence is meaningful: absent ≠ `PREFILL`.

---

## 17. W19 — repetition remains authoring-time expansion

Canonical `WorkloadIntent` is **fully expanded**. No loop/repeat construct.

A preset or editor template may express `repeat transformer block × 32`, but
before canonicalization it expands **deterministically into stable operation
IDs**. The canonical graph contains those nodes.

Benefits: simple DAG semantics, explicit identity, deterministic lowering,
no premature loop semantics.
**Documented cost:** graph size scales with layer count. A compressed graph
representation is explicitly **out of scope** for this gate.

---

## 18. Collective semantics and the lowering-policy law

**Settled (W7/W8).** Declaring `ALLREDUCE` means **semantic ALLREDUCE**.

Current lowering policy (`collectives.py:33`, the single production
authority):

```text
ALLREDUCE → RING · REDUCESCATTER → RING · ALLGATHER → RING
ALLTOALL → DIRECT · BROADCAST → ROOT_FANOUT
```

**New locked law:** this mapping is **lowering/compiler semantics identity,
not workload identity.** Introduce `CollectiveLoweringPolicy` (or cover it by
the compiler semantics version). If the mapping changes `RING → TREE`:

- workload identity: **unchanged**;
- compiler/lowering semantics identity: **changes**;
- downstream message / traffic / evidence identity: **changes**.

---

## 19. Payload authority

**One authority: explicit bytes** (W6 settled). No tensor shape + dtype +
bytes triple without an equivalence law.

If a preset derives bytes from model metadata, derivation happens **before**
canonical `WorkloadIntent` creation and the canonical explicit byte count is
stored. Derivation provenance may be recorded. Two conflicting payload
definitions are never retained.

---

## 20. Zero-byte and range law

**B24 resolved:** zero-byte semantic communication is **INVALID**. Evidence:
`payload_bytes > 0` is enforced for `CollectiveIntent`, `P2PTransfer` and
`MulticastIntent` (`operations.py:92,127,159`), and `_check_bytes` in
Phase-9. The backend does not decide this.

Large payloads: must be a positive int, bounded by divisibility law
(`B % k == 0` where the schedule requires it). No silent clamping.

---

## 21. Compute semantics

**Locked product truth:** a canonical `COMPUTE` operation is a **semantic
compute / dependency node** — *not* a calibrated compute-time model.

Do **not** add `duration_ns`, FLOPs or latency to `WorkloadIntent` unless a
real contract is introduced. Performance/service timing lives in the
performance layer.

Phase-9 `duration_ns` **cannot migrate losslessly** — recorded as a
legacy-only semantic loss (§30), preserved in the legacy adapter, never
promoted to the new authority.

---

## 22. Memory semantics

Classification of Phase-9 memory semantics (still consumed by
`simulation/ramulator.py`):

| Concept | Class |
|---|---|
| operand bytes (`input/weight/output_bytes`) | **LEGACY_BUT_MIGRATABLE** |
| location grammar `LOCAL` | **LEGACY_BUT_MIGRATABLE** |
| `REMOTE:<dev>`, `REMOTE:<dev>.<chan>` | **FUTURE_MEMORY_DOMAIN** |
| `CXL…`, `STORAGE` | **FUTURE_MEMORY_DOMAIN** |
| channel designation | **ACTIVE_CANONICAL** (Ramulator path) |

**Interface to Domain I (MEMORY):** WORKLOAD declares *operand size and
location*; MEMORY owns memory domains, address spaces, controller
relationships and memory traffic classes. Address ranges stay with
`AddressMap`. Domain I is **not** completed here.

---

## 23. Dependency semantics

| Rule | Value |
|---|---|
| edge meaning | must-finish-before-start (execution ordering) |
| DAG required | yes — cycles refuse |
| duplicate edges | refuse |
| missing node | refuse |
| self edge | refuse |
| ordering authority | **edges only** |

**Serialized node order must not become a second sequencing authority.**
Stable ids + explicit edges carry semantics; reordering serialization is a
semantic no-op (B41).

**Exception to document:** the v3 `collectives` tuple order **is** semantic
(`canonical_dict`: *"collective index feeds the lowering's operation chain"*).
Under the target model that ordering is represented by **explicit
dependency edges**, not tuple position.

---

## 24. Static-vs-serving model identity

One canonical `ModelSpec` scientific identity. Static workload references
it; serving experiment references it. LLMServingSim configuration is
**derived/projected** from it where fields correspond.

Do **not** maintain one `hidden_size` in the static workload and another in
serving JSON **without equivalence validation**. Extra serving-only model
fields belong a typed serving-model extension.

---

## 25. Static-vs-serving parallelism identity

Ownership contract (Domain C not implemented):

- `ParallelismIntent` is **one** canonical numeric authority.
- Static binding consumes it.
- Serving configuration consumes/projects it where supported.
- Serving-only concepts — instances, cluster seats, scheduler replica
  structure — remain `ServingExperiment` / serving-cluster semantics.
  They do **not** enter `ParallelismIntent` automatically.

---

## 26. Request traces remain outside WORKLOAD

**Locked.** Trace, arrival process, input/output token distribution and
request count belong `ServingExperiment`.

Same `ModelSpec` + `WorkloadIntent` + `ParallelismIntent` + Fabric may be
exercised by multiple traces. Changing the trace does **not** change static
workload identity (B29, B46).

---

## 27. Scheduler and batching remain outside WORKLOAD

**Locked.** Scheduler, admission, queue policy, continuous batching, max
batch size → serving execution/experiment configuration. Any current
duplicate fields are removed from the target `WorkloadIntent` (B30).

---

## 28. Traffic-class boundary

| Actor | Current authority | Target |
|---|---|---|
| WORKLOAD | declares `traffic_class` on collectives | semantic communication role / operation identity |
| LOWERING | carries `traffic_class_by_operation` sidecar | unchanged |
| COMMUNICATION INTENT (Domain D) | — | traffic-class assignment, QoS mapping, logical policy |
| REQUIREMENTS | references class | references operation/role, not a second definition |

**Current authority is WORKLOAD; the target direction is Domain D.** The
boundary is documented for Domain D; Domain D is not finalized here.
Requirements must never create a second traffic-class definition.

---

## 29. Requirement targetability

Stable references only — **never array index**.

```text
workload:<workload_id>
operation:<operation_id>
phase:PREFILL
```

Requirements may target: whole workload, phase tag, operation id,
communication operation id. **No requirement values inside `WorkloadIntent`.**

---

## 30. One migration spine

**v3 `WorkloadV3` → target `WorkloadIntent`**

| Case | Action |
|---|---|
| dense | deterministic translation; `collectives` order → explicit dep edges |
| MoE | **impossible today — no fabricated conversion** |
| `serving_mode` | dropped from identity (provenance only) |
| `model_family` | → `ModelSpec` family field |

**`graph.py::WorkloadGraph` → target** (closest migration)

| Field | Action |
|---|---|
| `parallelism` | **REMOVED** → Domain C |
| `participant_count` | **REMOVED** → Domain C |
| `operations` | kept; `owner` becomes symbolic-scope-derived |
| `semantics` | kept; `model_descriptor_*` → `ModelSpec` |
| `provenance` | kept, excluded from identity |
| `workload_id` | kept as derived identity |

**`operations.py::OperationGraph` → target**

| Kind | Action |
|---|---|
| COMPUTE/COLLECTIVE/P2P/MULTICAST | direct |
| EXPERT_DISPATCH/EXPERT_COMBINE | direct — **promoted to target** |
| KV_READ/KV_WRITE | **refused** — no canonical equivalent |
| required `phase`/`owner`/`step` | relax to optional where semantics allow |

**Phase-9 `WorkloadArtifact` → target**

| Content | Action |
|---|---|
| ops, kinds, participants | migratable |
| `duration_ns` | **LEGACY-ONLY LOSS** — no target semantic |
| memory operands/locations | migrate as `MEMORY` detail, or mark deferred |
| `EXPERT_BEGIN/END` + `comm_kind` | → `EXPERT_DISPATCH`/`COMBINE` |
| `SEND`/`RECV` rows | → `P2P` roles |
| `ALL_DIMENSIONS` / mask scope | → `CollectiveDimension` |

**No lossless claim is made where it is not true.**

---

## 31. Authority deprecation plan

| Stage | State |
|---|---|
| **0** | all four exist (today) |
| **1** | target canonical authority introduced; legacy readers/adapters remain |
| **2** | all producers write target form; legacy **read-only** |
| **3** | secondary graph authorities deleted or archived |

No new feature lands on a retired workload model. Repository checks
(forbidden-import lint) prevent new dependencies on retired classes.

---

## 32. Naming cleanup

| Concept | Target name |
|---|---|
| canonical operation node | `OperationNode` (graph lineage) |
| legacy waved operation node | `WavedOperationNode` (retired) |
| canonical collective declaration | `CollectiveIntent` (v3 declaration) |
| lowered collective | `LoweredCollective` |
| canonical workload | `WorkloadIntentV4` (representation: `WorkloadGraph` lineage) |

---

## 33. Change classes

| Class | Fields |
|---|---|
| **MODEL_SEMANTIC** | the six shape keys, `model_descriptor_hash` |
| **GRAPH_STRUCTURAL** | `operation_id`, `kind`, `step` |
| **DEPENDENCY** | `deps` |
| **COMMUNICATION_SEMANTIC** | `collective_kind`, `participant_scope`, `source_rank` |
| **PAYLOAD** | `payload_bytes` |
| **PHASE_TAG** | `phase` |
| **PROVENANCE_METADATA** | `label`, `model_name`, `model_descriptor_name`, `provenance` |

| Change | Class | Workload identity | Bound graph | Lowering | Traffic | Evaluation | Serving |
|---|---|---|---|---|---|---|---|
| model name | PROVENANCE | unchanged | — | — | — | — | — |
| `hidden_size` | MODEL_SEMANTIC | **changes** | changes | changes | changes | changes | **changes (shared ModelSpec)** |
| label | PROVENANCE | unchanged | — | — | — | — | — |
| collective kind | COMMUNICATION | changes | changes | changes | changes | changes | — |
| payload bytes | PAYLOAD | changes | changes | changes | changes | changes | — |
| parallelism number | *not a WORKLOAD field* | — | — | — | — | — | — |
| request count | *not a WORKLOAD field* | — | — | — | — | — | changes (experiment) |
| `serving_mode` | *removed from identity* | unchanged | — | — | — | — | experiment only |

---

## 34. Static MoE canonical example

```yaml
model_spec: {num_layers: 32, hidden_size: 4096, bytes_per_elem: 2,
             num_experts: 8, top_k: 2, decode_steps: 1}
operations:
  - {operation_id: "router.0",        kind: COMPUTE,         phase: PREFILL}
  - {operation_id: "moe.dispatch.0",  kind: EXPERT_DISPATCH, phase: PREFILL,
     deps: ["router.0"], participant_scope: EP, payload_bytes: 1048576}
  - {operation_id: "moe.experts.0",   kind: COMPUTE,         phase: PREFILL,
     deps: ["moe.dispatch.0"]}
  - {operation_id: "moe.combine.0",   kind: EXPERT_COMBINE,  phase: PREFILL,
     deps: ["moe.experts.0"], participant_scope: EP, payload_bytes: 1048576}
```

**Status:** REPRESENTABLE · **static lowering UNSUPPORTED** · serving
supported through a separate runtime authority. Expert *identity* and
token-level routing are **not** represented.

## 35. Dense canonical example

```yaml
model_spec: {num_layers: 32, hidden_size: 4096, bytes_per_elem: 2,
             decode_steps: 1}
operations:
  - {operation_id: "attn.qkv.0",  kind: COMPUTE,    phase: PREFILL}
  - {operation_id: "tp.reduce.0", kind: COLLECTIVE, phase: PREFILL,
     deps: ["attn.qkv.0"], collective_kind: ALLREDUCE,
     participant_scope: TP, payload_bytes: 16777216}
```

No numeric TP count · no request trace · no scheduler · no route · no VC.
This is the **sanity test for the target boundaries**.

## 36. Generic non-LLM workload

```yaml
model_spec: {}          # optional when no shape semantics are needed
operations:
  - {operation_id: "a", kind: COMPUTE}
  - {operation_id: "r", kind: COLLECTIVE, deps: ["a"],
     collective_kind: ALLREDUCE, participant_scope: GLOBAL,
     payload_bytes: 4096}
  - {operation_id: "b", kind: COMPUTE, deps: ["r"]}
```

The ontology does **not** require a transformer name. `model_family` is
absent from this example by design; where the current architecture requires
model metadata, that restriction is **documented, not faked**.

---

## 37. Adversarial verdicts B1–B52

B1 INVALID (empty) · B2 VALID · B3 VALID (RING pinned) · B4 VALID · B5 VALID
(P2P; PP-dim COLLECTIVE refuses) · **B6 representable, incomplete MoE flow —
valid partial graph** · **B7 representable** · **B8 valid generic EP
ALLTOALL, not MoE** · **B9 VALID partial/custom workload, not INVALID** (no
completeness law is claimed) · **B10 cross-domain compatibility, not
WORKLOAD failure** · B11 INVALID · B12 INVALID · B13 INVALID · B14 v3
collective order is semantic — represented by explicit edges in target ·
B15 no identity change · B16 identity change · B17 identity change · B18 not
expressible (no dual authority) · B19 fail closed · **B20 VALID workload,
UNSUPPORTED lowering** · B21 VALID · B22 VALID · B23 VALID (self-transfer
refuses) · **B24 INVALID** · B25 VALID (divisibility enforced) · B26–B28
VALID · **B29 workload identity unchanged** · **B30 workload identity
unchanged** · **B31 workload identity unchanged** · **B32 allowed — shared
model identity, different execution authority** · **B33 preset/editor
expands to canonical nodes** · **B34 static cannot claim token-level dynamic
identity** · B35 operand location, not agent id · B36 INVALID · **B37 wrong
domain** · **B38 wrong domain** · **B39 wrong domain** · B40 no identity
change.

New:

| # | Case | Verdict |
|---|---|---|
| **B41** | same graph, different serialization order | **same workload identity** |
| **B42** | same graph, label spelling changed | **same scientific identity** |
| **B43** | stable operation ID changed | **identity changes; references re-resolve** |
| **B44** | same `WorkloadIntent`, TP2 vs TP8 | **same workload identity; different parallelism + bound-graph identities** |
| **B45** | same `ModelSpec`, static vs serving | **shared model identity; different execution authority** |
| **B46** | same `ModelSpec`, different request trace | **same workload/model; different serving experiment** |
| **B47** | same ALLREDUCE, policy RING vs TREE | **same workload identity; different compiler/lowering semantics and downstream traffic** |
| **B48** | EP ALLTOALL labelled "dispatch" only in UI text | **still generic ALLTOALL** unless kind is `EXPERT_DISPATCH` |
| **B49** | static MoE on dense-only lowering | **VALID intent; UNSUPPORTED lowering** |
| **B50** | Phase-9 `duration_ns` cannot map | **explicit migration limitation; no silent loss** |
| **B51** | legacy memory location has no target semantic | **explicit migration / deferred-memory handling** |
| **B52** | `operations.py` kind with no canonical equivalent (`KV_READ`) | **migration refusal, no arbitrary coercion** |

---

## 38. Ontology update

`domains.WORKLOAD` updated to `in_progress` with 20+ rows: `R2` for the
real graph/kind/payload/scope/phase/model-descriptor concepts, `R1` for
presentation fields, `R3` for the derived schedule, and `R0` decisions
recorded for repeat, conditional, tensor, expert identity, compute time,
request trace and scheduler. The parallel-authority leak is recorded as
`workload.parallelism_authority`.

---

## 39. Coherence conditions

| # | Condition | Status |
|---|---|---|
| 1 | exactly one target static authority | **MET** (W1/W2) |
| 2 | legacy authorities have migration/deprecation roles | **MET** (§31) |
| 3 | duplicate class-name ambiguity resolved | **MET** (§3) |
| 4 | canonical operation vocabulary defined | **MET** (§5) |
| 5 | numeric parallelism removed from workload ownership | **MET** (W9) |
| 6 | symbolic participant-scope contract defined | **MET** (§8) |
| 7 | generic EP separated from MoE | **MET** (W10) |
| 8 | dispatch/combine explicit | **MET** (W11) |
| 9 | static/serving boundary explicit | **MET** (W12) |
| 10 | shared `ModelSpec` strategy defined | **MET** (§13) |
| 11 | duplicate model parameters have equivalence/migration law | **MET** (§24) |
| 12 | request trace outside workload | **MET** (§26) |
| 13 | scheduler/batching outside workload | **MET** (§27) |
| 14 | `serving_mode` resolved | **MET** (W15) |
| 15 | repeat policy explicit | **MET** (W19) |
| 16 | collective algorithm classified as lowering semantics | **MET** (§18) |
| 17 | payload has one authority | **MET** (§19) |
| 18 | compute-time limitation explicit | **MET** (§21) |
| 19 | memory migration boundary explicit | **MET** (§22) |
| 20 | requirement targetability stable-ID based | **MET** (§29) |
| 21 | traffic-class ownership boundary documented | **MET** (§28) |
| 22 | canonical migration spine defined | **MET** (§30) |
| 23 | B1–B52 carry verdicts | **MET** (§37) |
| 24 | no PARALLELISM planning begun | **MET** |

---

## 40. Domain verdict

All 24 coherence conditions are satisfied **at the design level**. The
authority model is collapsed to one canonical lineage with three explicit
legacy roles; the four blocker decisions (W1/W2, W9, W10/W11, W12) are
locked; `serving_mode` is removed from science; repetition stays an
authoring concern; and the collective-algorithm mapping is reclassified as
lowering semantics rather than workload identity.

**No fifth workload model is introduced.** Static and serving converge at
`ModelSpec`, later `ParallelismIntent`, and Fabric — **not** by pretending
an LLMServingSim scheduler executes the static graph.

**WORKLOAD INTENT: PLANNED — COHERENT**
