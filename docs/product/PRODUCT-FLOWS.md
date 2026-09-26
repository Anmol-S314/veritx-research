# PRODUCT-FLOWS — Gate 5 (product flow architecture)

Authority: Gate 1–4 planning artifacts (`INTENT-*.md`, `CROSS-DOMAIN-LAWS.md`,
`CAPABILITY-MATRIX.md`, `capability-registry.yaml`, `intent-ontology.yaml`).
Current Studio was audited **only to understand what exists** (§120).
Status: **PLANNED — COHERENT.** Verdict §140; coherence check §139.

> **GATE-5 CORRECTION (applied).** The first pass stated *"RCU → ALLOW + WARN —
> declarable, not derivable"*. That contradicted the closed target contracts
> (`INTENT-ROUTER-RESOURCES.md:316,320` — *"REMOVE from v4"*, *"**No `rcu=true`
> checkbox.**"*; `INTENT-FABRIC.md:415` — *"a boolean with no structural artifact
> is not [intent]"*). The verdict was temporarily returned to **IN PROGRESS —
> NOT COHERENT** and corrected: **RCU / in-network reduction is now
> `FUTURE_CONTRACT` / `NOT_AVAILABLE` with no rendered control** (§19.2), and the
> governing rule is now explicit (§19.1): **`ALLOW + downstream warning` requires
> accepted canonical intent — a legacy field, enum or parser path is
> insufficient.** The same evidence line (`INTENT-FABRIC.md:386-387`) applies to
> `mcast_groups`/`mcast_setup_cycles`, which were corrected alongside it.
> Legacy parsing is preserved (§19.3).

---

## 1. The core question

> What are the smallest coherent end-to-end workflows SROTA Studio must support?

**Ten** (FLOW-A…FLOW-J, §81). Everything else is a mode of one of them.
**Navigation is derived from them** (§92), not the reverse.

## 2. Product mental model

```text
DECLARE  → Design Intent
COMPILE  → canonical derived artifacts
VERIFY   → Certificate
EVALUATE → qualified execution + evidence
ANALYZE  → metrics + requirements + comparisons
OPTIMIZE → typed candidate studies
PROMOTE  → new design revision
INSPECT  → derived artifacts / provenance / evidence
```

**These stages are never collapsed.** A single "status" spanning them is the
defect Gate 4 removed from capability truth; Gate 5 must not reintroduce it in the
product.

## 3. Product object model

| Object | Identity | Lifecycle | Mutable | Parent | Children | Created by | Canonical backing |
|---|---|---|---|---|---|---|---|
| **Project** | `project_id` | open → archived | **yes** (name only) | — | revisions, studies, experiments | user | container only |
| **Design Revision** | `revision_id` + `design_hash` | created → compiled → superseded → archived | **no** | Project | evaluations, studies, experiments | **compile** | `CompileRequestV3` |
| **Intent Draft** | `(project_id, draft_id)` | DIRTY → VALIDATED → COMPILING → COMPILED / REFUSED | **yes** | Project | — | user edit | **not canonical** |
| **Compiled Revision** | = Design Revision, post-compile | see above | **no** | Project | — | compile | `design_hash` + artifacts |
| **Static Evaluation** | `run_id` / `performance_result_id` | queued → running → EVALUATED / FAILED / UNAVAILABLE / UNSUPPORTED | **no** | Design Revision | evidence, metrics, report | user | `ScientificBackendEvidence` |
| **Serving Experiment** | `serving_id` | same | **no** | Design Revision | round evidence, request metrics | user | serving round evidence |
| **Optimization Study** | `optimization_id` + `definition_id` | created → running → completed | **no** | Design Revision (baseline) | candidates, frontier | user | `OptimizationResult` |
| **Candidate** | `candidate_id` (`cand_` + content_id) | generated → evaluated | **no** | Study | observations, verdicts | search | `Candidate` |
| **RequirementSet** | derived from the revision's `requirements` | edited with the draft | **via draft** | Design Revision | RequirementReport | user | `RequirementV3` |
| **Evidence** | `performance_result_id` + evidence chain | produced | **no** | Evaluation / Experiment | metric observations | backend | authenticated proof |
| **Capability Registry version** | `capability_semantics_version` | versioned | **no** | — | — | planning | `capability-registry.yaml` |

**No frontend-only concept is introduced.** Every row names its canonical
backing object. `Intent Draft` is the only object with no canonical identity — by
design (§74).

## 4. Project vs Design Revision

```text
PROJECT        a mutable container (name, membership). No scientific identity.
DESIGN REVISION an immutable scientific design, identified by design_hash.
```

**Locked:** editing never mutates a revision. `compile` freezes canonical
identity. **A project and a design never share one mutable object.**

## 5. Draft lifecycle

```text
                 edit
   ┌──────────────────────────────┐
   ▼                              │
 DIRTY ──validate──► VALIDATED ──compile──► COMPILING ──► COMPILED
   │                    │                        │
   │                    │                        └──► COMPILE_REFUSED
   └── edit ────────────┘                                  │
                                                      edit │
                                                           ▼
                                                         DIRTY
```

**The existing law, completed:**

```text
edit intent → DIRTY
  → every existing compile/verify/evaluate/optimize result becomes STALE (§7)
  → NOT deleted, NOT mutated; still attached to the prior revision
compile → new design_hash → new immutable Design Revision
```

**`COMPILING` is a job state, never a scientific state** (§114).

## 6. Revision immutability

Once a revision has authoritative `design_hash`, derived artifacts, or
certificate/evidence, **normal editing must not mutate it in place.**

```text
editing a compiled revision  →  creates a successor draft
                             →  the prior revision is untouched
```

**Locked.** Provenance is preserved by construction.

## 7. Scientific freshness model — per stage, never global

Each stage has **its own** freshness. There is no global status.

| Stage | Values |
|---|---|
| Design Intent | `DIRTY` · `VALIDATED` · `COMPILE_REFUSED` |
| Compilation | `CURRENT` · `STALE` · `NOT_RUN` · `REFUSED` |
| Verification | `CURRENT` · `STALE` · `NOT_RUN` · `FAILED` |
| Evaluation | `CURRENT` · `STALE` · `NOT_RUN` · `UNAVAILABLE` · `FAILED` · `NOT_QUALIFIED` |
| Requirements | `CURRENT` · `STALE` · `NOT_RUN` · `UNMEASURABLE` |
| Optimization | `CURRENT` · `STALE` · `NOT_RUN` · `RUNNING` · `FAILED` |

**Freshness is derived from parent identities** (Gate 3 §36), never guessed.
A stage is `STALE` when its parent identity moved.

## 8. Compile workflow

```text
open/create project
  → open draft (or fork from a compiled revision)
  → edit intent
  → validate (staged, §75)
  → review
  → compile
  → inspect compiled result (FLOW-B)
```

| Aspect | Detail |
|---|---|
| Inputs | the Intent Draft |
| Preflight | staged validation (§9) |
| Refusals | `INVALID` (malformed) · `UNSUPPORTED` (valid but no derivation path) |
| Result object | a new immutable **Design Revision** |
| New identities | `design_hash`; then `MappingArtifact`, `TopologyArtifact`, `AgentAttachmentArtifact`, `AddressDecodeArtifact`, `RouteArtifact`, `ResolvedRouteArtifact`, `VCAssignmentArtifact`, `RouterBehaviorArtifact`, certificate |
| Becomes current | compilation, verification |
| Becomes stale | nothing — a new revision has no prior results |

## 9. Preflight vs compile — four distinct authorities

| Level | Owner | Example | Failure meaning |
|---|---|---|---|
| **1. Field/schema** | form + dataclass contract | `side_length = 0` | **malformed** — fix the field |
| **2. Cross-domain preflight** | product preflight over canonical rules | `rank_count > compute_instances`; insufficient seats | **infeasible join** — design is well-formed |
| **3. Canonical compile** | `FabricCompiler` | torus route derivation unavailable | **capability unsupported** |
| **4. Backend qualification** | evaluation profile | concentration 2 under mesh-DOR profile | **not qualified** — design is valid |

**Locked:** *"Do not tell the user a backend limitation during ordinary design
validation as if the design were invalid."* Levels 3 and 4 are **not** design
validation failures.

## 10. Editable Design domains — final list

Derived from ontology ownership + capability registry:

| Domain | Editable? | Where |
|---|---|---|
| **SYSTEM** | **YES** | Design → System |
| **WORKLOAD** | **YES** | Design → Workload |
| **PARALLELISM** | **YES** | Design → Parallelism |
| **REQUIREMENTS** | **YES** | Design → Requirements |
| **FABRIC** | **YES** | Design → Fabric |
| **COMMUNICATION** | **YES (advanced)** | Design → Workload → advanced |
| **MEMORY (AddressMap)** | **YES (advanced)** | Design → System → advanced |
| **ROUTER arbitration** | **YES (advanced)** | Design → Fabric → advanced |
| **PHYSICAL (design clock)** | **YES (advanced)** | Design → System → advanced |

**Not editable, ever:** Placement · Mapping · TopologyArtifact · Attachments ·
Routes · ResolvedRoutes · VC count/assignment · turn restrictions · escape VC ·
deadlock/CDG · AddressDecode · backend IDs · BookSim node ids · ASTRA `Sys.id`.

## 11. System authoring workflow

**User goals:** declare physical agents and counts · declare hierarchy ·
declare clock/power-domain membership · declare interface properties · declare
the memory address map (advanced, §12).

**Identity law:** `AgentGroupId`/`AgentInstanceId` are stable; **declaration order
never changes science** (X1).

## 12. Memory authoring placement — **chosen: A (nested, advanced)**

```text
Design → System → Advanced → Memory map
```

**Why not B (separate Design sub-step):** `MemoryIntentV4` is `AddressMap` and
nothing else (Domain I §3) — one table. A peer sub-step would give a single table
the same weight as Workload.
**Why not C (a primary page):** explicitly unjustified for one contract.

**The address width is read-only** (from the target agent interface). Regions show
`[base, base+size)` with the owning memory agent. **No Ramulator timing here.**

**GATE-4 CONTRADICTION (recorded, minimally corrected).** The capability registry
listed `MEM-001 AddressMap` as `PRODUCT_WIRED: YES`. The Studio audit found **no
authoring control and no inspection surface**, and `DesignView` does not carry
`address_map`. Corrected to `PRODUCT_WIRED: "NO"` / `wiring: NOT_AVAILABLE`, with
the authoring surface recorded as **PF-D1**. **No scientific claim changed** —
`AddressMap` remains declarable and canonical; presets supply it internally.

## 13. Workload authoring workflow

**User actions:** choose/create a workload · select the model family and its
parameters · declare communication-relevant intent (collectives, dependencies).

**Never mixed into Workload:** serving requests · backend execution config ·
parallelism counts (those are Parallelism) · backend node ids.

## 14. Static workload vs serving experiment — separate workflows

```text
STATIC DESIGN WORKLOAD      → Design Intent (Workload domain)
SERVING EXPERIMENT          → evaluation/run configuration (FLOW-F)
```

**Shared:** `ModelSpec`, Parallelism, `FabricArtifact`.
**Not shared:** request trace, scheduler/batching config, serving parallelism
projection.

**A serving request schedule is never `WorkloadIntent`.** A project may hold both.

## 15. Parallelism workflow

**User declares:** TP · DP · EP · PP shape.

**Never exposed as editable:** rank IDs · group IDs · ASTRA rank · mapping.
After compile, derived groups/ranks are **inspectable** (FLOW-B), not editable.

## 16. Communication workflow — **advanced Workload subsection**

```text
Design → Workload → Advanced → Communication
```

**Why not a separate Design domain:** `CommunicationIntent` is real but narrow,
and most designs have **one class**. A peer destination would be empty for most
users. **Avoid an entire page when most users have one class.**

Editing: communication classes · operation→class bindings.
**Consequence:** multi-class intent is valid; **execution is not available**
(COMM-006) → staged capability feedback (§19).

## 17. Requirements workflow

**User actions:** create a RequirementSet · add requirements · choose target ·
metric · operator · threshold · binding/advisory.

**Exposed target (only real one):** `WholeNetworkEvaluationTarget`.
**Exposed metrics (only registered ones):** `network_completion_cycles`,
`network_completion_ns`.

**Not exposed:** bandwidth · class-target · memory · serving/operation/group
targets (all `NO_CONTRACT` / `NO_EVIDENCE_CONTRACT` in the registry).

**Relationship to the revision:** `RequirementV3` lives **inside**
`CompileRequestV3`, so a RequirementSet edit is a **draft edit** that changes the
revision identity. A **threshold-only** edit still reuses measurements (§36, §37).

## 18. Fabric workflow

**Core intent:** topology family · **side length** · concentration · link width.
**Advanced:** arbitration policy (`ISLIP` | `ROUND_ROBIN`).

**Never:** VC count · route choice · turn restrictions · multiplane · manual
endpoint placement · **hardware multicast**.

**Naming law (Gate 3 §7):** scientific name **"Side length"** (square-grid side
`k`); the implementation field is `NocConfig.radix`. **Studio must rename the
current "Radix" label** (§122) — the alias lives only at the boundary.

## 19. Capability-aware authoring — staged feedback

Three allowed behaviours:

```text
PREVENT          the choice is not rendered (no contract exists)
ALLOW + WARN     declarable, but a named downstream stage is NO
ALLOW + INSPECT  declarable and derivable, not executable
```

| Feature | Behaviour | Registry row |
|---|---|---|
| **Torus** | **ALLOW + INSPECT** — valid topology, routing unavailable | FAB-003/004 |
| **RCU / in-network reduction** | **PREVENT** — not modeled by the accepted v4 contract | ROUTE-011 |
| **mcast_groups / mcast_setup_cycles** | **PREVENT** — hardware multicast is a future contract | COMM-005 |
| **concentration > 1** | **ALLOW + WARN** — valid fabric, not qualified under mesh-DOR | FAB-002 |
| **multi-class** | **ALLOW + WARN** — valid intent, no execution | COMM-006 |
| **multi clock domain** | **ALLOW + WARN** — declarable, no fabric execution | SYS-003/004 |
| **manual placement** | **PREVENT** — no contract | MAP-002 |
| **VC count** | **PREVENT** — derived | ROUTE-005 |
| **multiplane** | **PREVENT** — FUTURE_CONTRACT | FAB-005 |
| **hardware multicast** | **PREVENT** — FUTURE_CONTRACT | COMM-005 |

**Torus must not be disabled globally.**

### 19.1 The precise rule

```text
ALLOW + downstream warning is permitted ONLY when accepted canonical intent exists.
```

**The presence of a legacy field, enum value, parser path or old UI control is
insufficient.** A field being parseable in a current schema does **not** make it
target Design Intent.

| Feature | Accepted canonical intent? | Behaviour |
|---|---|---|
| Torus | **yes** — Fabric intent is real, topology derivation exists | ALLOW + INSPECT |
| concentration > 1, multi-class, multi-clock | **yes** — the intent is real; the limit is downstream | ALLOW + WARN |
| RCU / in-network reduction | **no** — removed from v4; no structural artifact | **PREVENT** |
| hardware multicast (`mcast_*`) | **no** — future capability contract | **PREVENT** |
| manual placement | **no** — no `PlacementIntent` contract | PREVENT |
| VC count | **no** — compiler-derived | PREVENT |
| multiplane | **no** — future capability contract | PREVENT |

### 19.2 RCU — corrected target behaviour

**Source evidence (`INTENT-ROUTER-RESOURCES.md:316,320`):**

> *"RCU | **REMOVE from v4**; no canonical consumed artifact → **FUTURE CAPABILITY
> CONTRACT**"* · *"**No `rcu=true` checkbox.** None recorded as v4 implementation
> debt."*

**And (`INTENT-FABRIC.md:415`):** *"RCU → ROUTER/RESOURCE: a boolean with no
structural artifact is not [intent]"*.

```text
RCU / IN-NETWORK REDUCTION  →  FUTURE_CONTRACT / NOT_AVAILABLE
  no ordinary Design control is rendered
  no disabled or warning-only checkbox (that would imply an accepted contract
    awaiting execution support)
  no "enable anyway" path
  capability diagnostics may explain that in-network reduction semantics are not
    part of the accepted router-resource contract
```

**Not `INVALID` intent:** there is **no target intent field to validate**. RCU is
absent from the accepted contract, not rejected by it.

**Why `ALLOW + WARN` was wrong:** it requires accepted canonical intent. RCU has
none — it was explicitly removed from v4 and from Fabric authoring
(`INTENT-FABRIC.md:555`), and `RouterResourceIntentV4` carries `arbitration_policy`
**only**.

### 19.3 Legacy compatibility boundary (preserved)

```text
compatibility parsing     MAY preserve or detect a legacy rcu field
migration                 MUST classify it explicitly (LEGACY_ONLY / refusal)
new target authoring      MUST NOT expose it
canonical meaning         MUST NOT be acquired silently
imported legacy state     MUST NOT be represented as accepted v4 RCU science
```

**Legacy parsing is not removed to solve a product-flow issue.** The legacy field
remains parseable and detectable; it simply never becomes target authority.

## 20. Valid-but-not-executable designs — a first-class state

```text
Design a torus
  → compile: topology derives, certificate over the topology PASSES
  → inspect: routers, channels, seats, attachments
  → STOP before evaluation
```

**This is a success, not a failure.** The revision is **canonically valid**. Its
freshness reads:

```text
Compilation   CURRENT
Verification  CURRENT
Evaluation    NOT_RUN (route derivation unavailable → EXECUTABLE NO)
```

The design is **never marked "broken."**

## 21. Compile result workflow

After compile the user inspects derived science:

Mapping · Attachments · Topology · Routes · ResolvedRoutes · VC assignments ·
CDG/deadlock · Address decode · Resolved fabric · Certificate.

**These are not Design steps.** They are read-only inspectors over one object.

## 22. Inspector architecture — **one Compile Result with sub-inspectors**

```text
Compile Result (a Design Revision)
├── Summary            identities, certificate, capability stages
├── Mapping            participant → compute agent
├── Fabric             topology + attachments + unused seats
├── Routing            routes + resolved routes + observation scope
├── Resources          VC assignment + CDG + arbitration + router behavior
├── Address decode     ranges → memory agent → endpoint
└── Provenance         compiler semantics, artifact hashes, pins
```

**Why not one page per artifact:** workflow coherence beats artifact count. Ten
top-level destinations for one revision fragments a single object across
navigation. **No artifact becomes a top-level page** (§93).

## 23. Mapping inspection

**Questions:** where did participant X land · which ranks use accelerator Y ·
which compute agents are idle · what hierarchy does each participant occupy.

**Drill-down:** participant → rank → agent → hierarchy → endpoint. **No editing.**

## 24. Topology inspection

**Questions:** what network was generated · how many routers/channels/seats ·
which agents attach where · which seats are unused.

**Never blurred:** `TopologyArtifact` (derived) vs `FabricIntent` (declared).
**Idle-endpoint projection** (FAB-D6) is shown as a declared projection, not a
silent drop.

## 25. Route inspection

**Shown:** canonical full route · routing class · channel sequence ·
source/destination · `LOCAL_EJECTION`.

**Explicitly separate:** the canonical route is a **DERIVED EXPECTED STATE**; the
backend observes **first-hop routing-function equivalence over the complete
source×destination domain** (EVAL-007). **Two different surfaces, two different
labels** (§27 of Gate 3).

## 26. VC / deadlock inspection

**Shown:** derived VC count · class→VC assignment · escape designation · CDG
result · deadlock witness on failure. **No editing.**

**Diagnosis path:** CDG failure → inspect the cycle witness → inspect the routes
and VC assignment involved → **change editable upstream intent** (topology family,
concentration, arbitration, communication classes). The cycle itself is
**never hand-editable** (§66).

## 27. Verification workflow

```text
compile → derived artifacts → VerificationCertificate
```

**Compile success requires certificate PASS for the artifact to be usable
downstream.** A certificate is **not an optional checkbox** — it is the gate that
makes a compiled revision eligible for evaluation.

| Outcome | Meaning | User entry |
|---|---|---|
| `PASS` | obligations hold | inspect claims (§28) |
| `FAIL` | obligations exist and are violated | diagnostics with the witness |
| `UNSUPPORTED` | the verifier cannot reason about this design | capability explanation, not a bug |

**`FAIL` ≠ `UNSUPPORTED`.** The first means the design violates a proven
obligation; the second means no obligation could be formed.

## 28. Certificate claims — four separate claims

```text
ATTACHMENT_COMPLETE   every declared agent is attached
ROUTE_COMPLETE        every required (class, src, dst) has a route
ROUTE_LEGAL           every route's channel sequence is legal
DEADLOCK_FREE         the channel-VC CDG is acyclic / deterministic
```

**Each claim has exact limits and its own drill-down.** **No single green
"Verified" badge.** Claim limits are stated beside the claim (§119).

## 29. Static evaluation workflow

```text
choose compiled revision
  → choose a qualified evaluation profile (EvaluationPolicy)
  → preflight qualification
  → run
  → evidence
  → metric observations
  → RequirementReport
```

**Backend choice is never part of Design Intent.**

## 30. Evaluation Policy object — **adopt as a first-class object**

```text
EvaluationPolicy {
    backend_profile       one of the certified profiles
    network_clock_hz      exact int Hz | null
    execution_options     timeout, quiescence
}
```

**Why it is needed:** Gate 3 §34 locks that backend/profile belongs to
evaluation, not DesignIntent, and Gate 4 §8 shows **three materially different
certified BookSim profiles**. Without a named object the profile choice has no
home and would leak into the draft.

**It never alters `design_hash`.** Changing it changes **evaluation definition and
evidence**, not design identity.

## 31. Backend selection — profiles are never one generic "BookSim"

```text
CAP-ENV-BOOKSIM-MESH-DOR-XY-V1   CERTIFIED_BOOKSIM_MESH_DOR_XY_V1
CAP-ENV-BOOKSIM-ANYNET-V1        CERTIFIED_BOOKSIM_ANYNET_V1
CAP-ENV-BOOKSIM-SERVING-V1       CERTIFIED_SERVING_BOOKSIM2_V1
CAP-ENV-RAMULATOR-V1             (engine only — no product run)
```

Each materially changes the scientific claim (different semantics versions).
**The product must not show one generic "BookSim".**

## 32. Automatic backend selection — **B: recommend, user confirms**

```text
product computes the set of envelopes whose conditions the revision satisfies
product presents them, each with its claim scope
user confirms exactly one
```

**Why not A (fully explicit):** the user should not have to know that concentration
1 selects the mesh-DOR envelope.
**Why not C (automatic):** silent substitution is forbidden (Gate 4 §21), and a
choice that changes the scientific claim must be **user-visible**.

**Any fallback that ever exists must appear in the result provenance.**

## 33. Qualification preflight

```text
QUALIFIED            → run available
NOT_QUALIFIED        → run unavailable under this profile; design stays valid
BACKEND_UNAVAILABLE  → engine/binary missing; design stays valid
```

**Continuation options:** choose another compatible profile · change the design ·
inspect the qualification failure · stop. **The design is never relabelled
unsupported** (C11).

## 34. Static Evaluation result — a hierarchy, not a number

```text
Evaluation
├── qualification        profile id, semantics version, predicate results
├── execution attempt    attempt identity, status, timing
├── evidence             authenticated proof, chain
├── metric observations  registered MetricIds with units and producers
└── requirement report   per-RequirementId verdicts
```

## 35. Metrics workflow

**User can see:** which metrics are available (registry-backed) · which are
`UNMEASURABLE` and **why** · each metric's producer, unit, semantics version and
evidence source.

**No frontend-derived scientific metrics.** **No fabricated zero** (Gate 3 §23).

## 36. RequirementReport workflow

Per `RequirementId`: `SATISFIED` · `VIOLATED` · `UNMEASURABLE` ·
`NOT_APPLICABLE`.

**Binding/advisory affects the report aggregate only — never an individual
scientific verdict.**

**Rerun/reuse:** a threshold-only edit reuses measurements and recomputes the
report (§37).

## 37. Threshold edit workflow — the efficient path

```text
evaluation exists
  → user edits a requirement threshold
  → create/update the RequirementSet in the draft
  → REUSE the existing measurement
  → RECOMPUTE the RequirementReport
  → NO backend rerun
```

**Note the identity consequence:** because `RequirementV3` lives inside
`CompileRequestV3`, this edit produces a **new revision identity** while reusing
**evaluation evidence** for the same design. Both facts must be shown: the
revision changed; the measurement did not need to.

## 38. Comparison workflow

**Comparable objects:** Design revision vs Design revision · Evaluation vs
Evaluation · Candidate vs Candidate.

**Comparability follows MetricRegistry/provenance law.** Arbitrary numeric deltas
must never imply comparability.

## 39. Design comparison

Compare **intent differences** · **compiled artifact differences** ·
**capability differences**. **Not mixed** with evaluation results unless
evaluations are explicitly selected.

## 40. Evaluation comparison

```text
compatible  (same MetricId + producer + semantics_version + population)
    → compare
incompatible
    → INCOMPARABLE, with the reason
```

**No blind percentages** across producers or clocks. `completion_ns` from two
different clocks is **incomparable**; `completion_cycles` is reusable.

## 41. Serving workflow — a separate primary workflow

```text
choose compiled revision
  → define Serving Experiment
  → request trace
  → serving model / scheduler config
  → backend profile
  → run
  → request metrics + round evidence
```

**Do not reuse static Evaluation forms indiscriminately** — different entry,
different scheduling authority, different metrics.

## 42. ServingExperiment object

```text
ServingExperiment {
    compiled_revision_identity
    request_trace_identity
    serving_configuration
    serving_parallelism_projection
    backend_profile
}
```

**Serving instance IDs are never conflated with canonical participant IDs.**

## 43. Serving dense workflow — ownership split

| Owned by **LLMServingSim** | Owned by **VERITX** |
|---|---|
| request arrivals · queues · scheduling · batching · prefill/decode · instances · request metrics | fabric/network execution (ASTRA + qualified serving profile), round qualification, round evidence |

`simulation/serve_canonical.py:13` — *"LLMServingSim remains the service-semantics
authority (instances, …)"*. Backend network execution provenance is retained.

## 44. Serving MoE workflow — separate from static MoE

```text
static MoE  : DERIVABLE NO  → not available (WORK-002)
serving MoE : DERIVABLE YES → available under CAP-ENV-BOOKSIM-SERVING-V1
```

**Do not show one project-level "MoE supported" status.** The two rows are
different capabilities with different stages.

## 45. Serving result

**Metrics are exactly those the code produces** — request metrics from the
serving runtime (TTFT/latency/throughput/queueing as reported), plus round
evidence.

**Evidence/claim boundary:** serving metrics belong to the **serving** population;
they are **not comparable** to static network completion metrics without registry
compatibility proof.

## 46. Ramulator workflow — **no runnable Studio workflow today**

```text
current state : ENGINE_ONLY
```

**Target product behaviour today:** the capability is **discoverable in
capability diagnostics** with its status and claim scope, and **no Run action is
offered**. *"Memory simulation engine available; not connected to the current
product workflow."*

**Future intended workflow (documented, not wired):**

```text
legacy/canonical memory source → memory profile → standalone run → MemoryEvidence
```

**Product IA must label it not-wired rather than placing a clickable workflow
that cannot run.**

## 47. Optimization workflow — already product-wired

```text
choose baseline compiled revision
  → define StudyDefinition (design space, objectives, constraints, requirement context, evaluation policy)
  → define SearchExecutionPolicy (method, budget, seed)
  → run study
  → inspect candidates
  → Pareto frontier
  → select
  → promote (§55)
```

Uses the Gate-3 identity decisions.

## 48. Optimization study setup — two objects, never mixed

```text
StudyDefinition          SearchExecutionPolicy
  baseline revision        method (grid | enumeration | random)
  design space             budget
  objectives               seed
  constraints
  requirement context
  evaluation policy
```

**Workflow labels must keep them separate** (Gate 3 §9). `candidate_id` binds
neither.

## 49. Guided optimization journey

```text
choose an optimization goal
  → select the allowed variation scope
  → system materializes a typed DesignSpace
  → REVIEW the exact dimensions and values
  → choose evaluation policy
  → run
```

**No hidden design-space dimensions.** Every generated dimension is visible in
Review. Detailed Guided UI belongs Gate 6.

## 50. Expert optimization journey

```text
explicitly construct the typed DesignSpace
  → objectives
  → constraints
  → evaluation policy
  → search execution policy
  → run
```

**Same canonical `StudyDefinition` as Guided.** Two entry paths, one contract.

## 51. Candidate workflow

A candidate row must answer: **changed fields · canonical Design identity ·
compile state · certificate state · qualification · objective observations ·
requirements · Pareto state.**

**No opaque trial row.**

## 52. Failed candidate workflow

Failures **remain inspectable** and stay in study history: `INVALID` ·
`COMPILE_FAILED` · `UNSUPPORTED` · `BACKEND_UNAVAILABLE` · `FAILED`, plus
objective/constraint `UNMEASURABLE` states.

**Path to diagnostics:** candidate → typed status → `eligibility_reason` → the
owning stage → the upstream editable owner.

## 53. Pareto workflow

**Pareto state comes from backend authority.** The user can inspect the frontier ·
compare members · **filter** by requirement status.

**The frontend never recomputes the frontier.** Requirement satisfaction is an
**annotation** (Gate 3 §8), not an eligibility predicate.

## 54. Candidate selection — three distinct concepts

```text
UI FOCUS         clicking a row (no scientific meaning)
STUDY SELECTION  explicit, recorded as selected_candidate_id + rationale
PROMOTED DESIGN  a new Design Revision (§55)
```

**Clicking a row is not scientific selection.** Selection must be explicit.

## 55. Candidate promotion

**Current truth: `OPT-008` is `PRODUCT_NOT_WIRED` — an implementation gap.**
**The current product must not claim promotion exists.**

**Target workflow (specified, not implemented):**

```text
candidate
  → explicit "Use as new design"
  → new immutable Design Revision (successor draft)
  → the optimization study remains unchanged
```

**The baseline is never mutated.**

## 56. Evidence / provenance workflow — universal

From **any** result the user can answer: what compiler produced this · what
artifact identities · what certificate · what backend · what qualification
profile · what evidence · what metric semantics.

**Realized by:** every result object already carries its identity chain
(`evaluation_ids`, `locked_consequences`, `metric_registry_id/version`,
`producer`, evidence refs). **The product surfaces references, never a
reconstruction.**

## 57. Trust / provenance model

**One cross-cutting concept: Provenance.** It resolves to exact scientific
objects — compiler semantics version, artifact hashes, certificate, producer
identity, qualification profile, metric semantics version, evidence chain.

**No "confidence score".** Vague trust is forbidden; the vocabulary is the exact
object chain.

## 58. Capability inspection workflow

**User goals:** can I run this · why can I not · which stage blocks it · is this
an implementation gap or a future contract?

**Decision: user-accessible diagnostics, with expert detail.**

**Why:** Gate 4's whole purpose is that a single boolean lies. If capability truth
is developer-only, Product will re-invent a boolean. The user-facing level states
the stage and the claim scope; the technical level names the reason code and
profile; the deepest level cites the registry row.

`GET /api/v1/capabilities` already exists (`gateway/app.py:367`).

## 59. Capability-aware action availability

```text
Evaluate            available only when a compatible executable+qualified envelope exists
Inspect topology    available for Torus (INSPECT_ONLY)
Ramulator run       NOT available (ENGINE_ONLY)
Manual placement    not rendered (no contract)
Promote candidate   NOT available (IMPLEMENTATION_GAP)
```

**Every major action reads registry truth.** A stale capability cache must
**refuse to render a claim** rather than display a false one (P26).

## 60. Do not hide unavailable science — the global principle

```text
NOT RENDER   a nonexistent control          (manual placement, VC count, multiplane)
RENDER + EXPLAIN  a valid but downstream-limited capability (torus, multi-class,
                  concentration > 1)
NOT RENDER        a capability whose semantics are not accepted
                  (RCU, multiplane, hardware multicast, manual placement, VC count)
```

**The difference is whether a canonical contract exists.** If the intent is real
and the limitation is downstream, the product **shows it and explains the
blocker**. If no contract exists, there is nothing to show.

## 61. Error recovery workflows

| Stage failure | What the user can do next |
|---|---|
| Design validation | return to the owning field (§62) |
| Compile refusal | `INVALID` → fix the field; `UNSUPPORTED` → change topology/feature or stop |
| Verification FAIL | inspect witness → change upstream intent |
| Backend NOT_QUALIFIED | choose another compatible profile · change design · inspect |
| Backend UNAVAILABLE | retry later · choose another profile |
| Execution FAILED | retry (new attempt) · inspect debris |
| UNMEASURABLE metric | see the reason · choose a profile that produces it · accept |
| Requirement VIOLATED | edit threshold · change design · inspect evidence |
| Candidate failure | inspect typed reason → upstream owner |

**No dead ends.**

## 62. Invalid design recovery

Return to the **exact owning domain/field**. **No generic "Something went
wrong."** Diagnostics carry **object + field references**.

## 63. Cross-domain infeasibility recovery

```text
128 required endpoints, 64 seats
  remedy A: increase Fabric capacity
  remedy B: reduce System physical agents
```

**The product explains competing remedies and does not automatically mutate
either.**

## 64. Unsupported capability recovery

```text
"Topology is valid. The canonical route compiler is unavailable for torus."
actions: inspect topology · change Fabric topology · stop
```

**Do not suggest nonsensical configuration tweaks.**

## 65. Qualification failure recovery

```text
concentration 2 under the mesh DOR-XY profile
actions: choose another explicitly compatible profile · change concentration ·
         inspect the qualification failure
```

**No silent fallback.**

## 66. Verification failure recovery

```text
CDG cycle
  → inspect the cycle witness
  → inspect the routes and VC assignment involved
  → change editable upstream intent (topology family, concentration, arbitration,
    communication classes)
```

**Reasoning the product must convey:** routes and VCs are **derived**, so recovery
is by changing upstream intent, **not** by hand-fixing the cycle.

## 67. Stale result workflow

```text
user edits the current draft
  → existing compiled revisions and evaluations DO NOT disappear
  → they remain attached to their prior revision
  → the current draft simply has no current compile/evaluation
```

**Historical evidence is immutable.** Freshness is per stage (§7).

## 68. Branching design workflow — **revision chain, with promotion as the branch point**

```text
linear by default:  R1 → R2 → R3
branch point:       promotion from an optimization candidate (§55)
```

**Why not first-class arbitrary branching:** the product only needs linear
revisions plus promotion. **Do not over-engineer.** A promotion creates a
successor revision whose parent is the candidate, not the study's baseline.

## 69. Project history

User-visible history: **drafts · compiled revisions · evaluations · serving
experiments · studies.**

**User must be able to recover which result belongs to which revision** — every
result carries its revision identity, so history is a **view over objects**, not a
separate authority (§100).

## 70. New / open project workflow

```text
New Project       → name (+ optional workload preset)
Open Project      → list of projects → revisions
```

**No giant wizard.** Project creation requires only a name; design happens in the
draft.

## 71. Templates / presets — authoring presets only

**Scientific role: authoring preset.** A preset expands into **ordinary Design
Intent**. **No preset-only hidden semantics.** A preset is never a new artifact
type.

## 72. Invalid presets

**Preset output is validated exactly like manually authored intent.** A preset
does not bypass any law. Example: a preset producing an invalid combination must
fail the **same** validation as a manual entry.

## 73. Save semantics

```text
draft edits    autosaved (mutable, non-canonical)
compile        creates an immutable revision
```

**Scientific identity arises only at compile.** **No keystroke is a design
revision.**

## 74. Intent identity vs design hash

```text
user edits an INTENT DRAFT        (no canonical identity)
compile produces design_hash      (canonical identity)
```

**The UI uses revision labels with hashes available in provenance.** Raw SHA is
never the primary identity (Gate 3 D1: `intent_id` ≠ `design_hash`).

## 75. Validation timing — staged ownership

```text
on-edit    field/schema only        (local, instant, no compiler)
on-blur    field-level + local joins
preflight  cross-domain rules       (canonical rules, no full compile)
compile    full canonical derivation + certificate
evaluate   backend qualification
```

**Locked:** *"Do not make all validation immediate if it requires cross-domain
canonical compilation."*

## 76. D1 product-side resolution

**Exact repository wording** (`INTENT-ONTOLOGY.md:445-453`):

> *"Which declared layer is the page's subject? (blocking) (a) edit
> `CompileIntent` (preset + overrides + policy), matching product identity and
> `intent_id`; or (b) edit explicit `CompileRequestV3` with `CompileIntent` as a
> named-preset shortcut, defining how `intent_id` is derived. The ontology has two
> roots; the page must have one."*

**Chosen: (b).**

```text
The Design page edits an INTENT DRAFT whose canonical serialization IS
CompileRequestV3. CompileIntent is a named-preset entry shortcut that EXPANDS
into an ordinary draft; it is never a second editable layer.
```

**Law:** every editable field writes into the **Intent Draft**, never into a
derived artifact, a compiled design, or backend config — **unless the surface
explicitly belongs to Evaluation or Optimization rather than Design.**

**Why (b):** the compiler root is the canonical identity (Gate 3 D1); the product
root is a *convenience*, and the draft path already bypasses `CompileIntent`
entirely (`product/service.py:670`). Choosing (a) would make a shortcut layer
authoritative over the canonical one.

**`intent_id` is a preset-expansion record, never a design identity.**

## 77. D5 product-side resolution

**Exact repository wording** (`INTENT-ONTOLOGY.md:463-466`):

> *"Contract widening: confirm `DesignView` v2 must carry `collectives`,
> `dependencies`, `address_map`, `physical`, and the product layer, so the UI stops
> hand-mirroring `compile_model.py`. The DECLARED rows of §2.12 are the required
> field list."*

**Chosen: widen `DesignView` to v2** carrying `collectives`, `dependencies`,
`address_map`, `physical` and the product layer.

**Evidence that it is needed:** current `DesignView` v1
(`apps/studio/src/types.ts:56`) carries only `design_hash`, `schema_version`,
`compiler_semantics_version`, `workload`, `requirements`, `agents`, `noc_guided`,
`locked_derived`. **`address_map`, `physical`, `collectives` and `dependencies`
are absent**, so the UI cannot show them without re-deriving from the engine.

**Architectural boundary preserved:** Design pages consume **`DesignView` + draft
intent + compiled views** from the API. **No Python engine import into the
frontend.**

**Note:** this is a **view-schema widening**, not a science change — views are
projections, never identities.

## 78. D6 product-side resolution

**Exact repository wording** (`INTENT-ONTOLOGY.md:467-469`):

> *"Early validation: move the two doc-computable coherence checks into the form
> (`rank_count ≤ compute_instances`; `traffic_class ∈ derive_v3_traffic_classes`)?
> Both need no compiler."*

**Chosen: staged validation, with the two named checks at PREFLIGHT (level 2).**

```text
rank_count ≤ compute_instances        → preflight (cross-domain join)
traffic_class ∈ derive_v3_traffic_classes → preflight (cross-domain join)
```

**Why not "on edit":** both are **cross-domain joins** (SYSTEM↔PARALLELISM;
WORKLOAD↔COMMUNICATION), not field-local rules. Evaluating them per keystroke
would create a second authority for a cross-domain law.

**Authority law (Gate 3 D6):** compile/report retain the authority; a form-level
pre-check is **advisory only** and its absence must not change the outcome.

## 79. D8 product-side resolution

**Exact repository wording** (`INTENT-ONTOLOGY.md:474-477`):

> *"Visual primitive set: freeze the six primitives of §2.12 as the closed
> vocabulary for Gates 2–6, and forbid per-node hand-authored primitives
> (`.rcu-refusal`, `.locked-grid`)?"*

**Chosen: frozen, already mechanical.**

The ontology validates `visual ∈ {1..6}` per node
(`check_intent_ontology.py :: VISUAL = {1,2,3,4,5,6}`), so the six-primitive
vocabulary **is already the closed vocabulary**.

**Workflow-level interpretation (this gate's only addition):** each primitive
maps to a **workflow meaning**, not a style:

```text
1 declaration control   → an editable intent field
2 derived value         → an inspect-only value
3 refusal               → a staged capability limit shown beside the field
4 absence               → not rendered
5 identity              → a provenance reference
6 change class          → the invalidation consequence of an edit
```

**Detailed visual architecture belongs Gate 8.** This gate does not design the
primitive system.

## 80. Product action taxonomy

```text
Edit · Validate · Compile · Inspect · Verify · Evaluate · Compare ·
Optimize · Promote · Duplicate · Archive
```

**"Run" is never used bare.** The verbs are **Compile Design** · **Run
Evaluation** · **Run Serving Experiment** · **Run Optimization Study**.

## 81. Primary global flows

| Flow | Start → End |
|---|---|
| **FLOW-A** Create and compile a design | no project → immutable compiled revision |
| **FLOW-B** Inspect compiled fabric | compiled revision → understood derived science |
| **FLOW-C** Run static evaluation | compiled revision → qualified evaluation + evidence |
| **FLOW-D** Evaluate requirements | evaluation + RequirementSet → RequirementReport |
| **FLOW-E** Compare | two results → comparison or explicit INCOMPARABLE |
| **FLOW-F** Run serving experiment | compiled revision → serving evaluation |
| **FLOW-G** Run optimization study | baseline revision → completed study |
| **FLOW-H** Inspect/promote candidate | candidate → inspected/selected/promoted |
| **FLOW-I** Investigate failure | failure → typed cause → owning upstream field |
| **FLOW-J** Inspect capability/provenance | any result → claim scope + stages + provenance |

**Added (revealed by the audit):**

| Flow | Start → End |
|---|---|
| **FLOW-K** Threshold-only requirement edit | evaluation → reused measurement + new report |
| **FLOW-L** Capability diagnostics | user question → blocking stage + reason code |
| **FLOW-M** Archive / history | project → archived objects with provenance intact |

## 82. FLOW-A — create and compile a design

```text
[Project]                     user creates or opens
   ↓
[Intent Draft]                DIRTY
   ↓ edit (System, Workload, Parallelism, Fabric, Requirements, advanced)
   ↓ on-edit validation        field/schema
   ↓ on-blur validation        field-level
   ↓ preflight                 cross-domain joins
[Intent Draft]                VALIDATED
   ↓ Compile Design
[Job]                         COMPILING
   ↓
   ├── refusal → COMPILE_REFUSED → [typed diagnostics] → back to owning field
   ↓
[Design Revision]             immutable, design_hash assigned
   ├── derived artifacts       Mapping, Topology, Attachment, AddressDecode,
   │                           Routes, ResolvedRoutes, VC, RouterBehavior
   ├── certificate             PASS | FAIL | UNSUPPORTED
   └── freshness               Compilation CURRENT, Verification CURRENT,
                               Evaluation NOT_RUN
   ↓
FLOW-B (inspect)  or  FLOW-C (evaluate)  or  FLOW-G (optimize)
```

## 83. FLOW-B — inspect compiled fabric

```text
[compiled revision]
  → Compile Result (Summary)
      → Mapping         participant → agent → hierarchy → endpoint
      → Fabric          routers, channels, seats, unused seats, attachments
      → Routing         canonical routes + observation scope
      → Resources       VC count, class→VC, CDG, arbitration, router behavior
      → Address decode  ranges → memory agent → endpoint
      → Provenance      compiler semantics, artifact hashes, pins
[End] user understands derived science
```

**No derived object is editable.**

## 84. FLOW-C — static evaluation

```text
[compiled revision, certificate PASS]
  → choose EvaluationPolicy  (product recommends envelopes the revision satisfies)
  → preflight qualification
       ├── NOT_QUALIFIED       → choose another profile · change design · inspect
       ├── BACKEND_UNAVAILABLE → retry · choose another profile
       └── QUALIFIED
  → Run Evaluation
[Job] queued → running
  → ExecutionAttempt
       ├── FAILED    → retry (new attempt) · inspect debris
       └── EVALUATED
  → Evidence (authenticated)
  → MetricObservation[]  (registered MetricIds; UNMEASURABLE where not evidenced)
  → RequirementReport
[End]
```

## 85. FLOW-D — evaluate requirements

```text
[Evaluation + RequirementSet]
  → per-RequirementId verdict: SATISFIED | VIOLATED | UNMEASURABLE | NOT_APPLICABLE
  → aggregate (binding only)
[End]

THRESHOLD-ONLY EDIT BRANCH (FLOW-K):
  user edits a threshold
    → new draft → new revision identity
    → REUSE the existing measurement
    → RECOMPUTE the RequirementReport
    → NO backend rerun
```

## 86. FLOW-E — compare

```text
[two results]
  → comparability check (MetricId + producer + semantics_version + population)
       ├── compatible   → side-by-side comparison
       └── incompatible → INCOMPARABLE + the reason
[End]
```

**No blind percentages.**

## 87. FLOW-F — serving experiment

```text
[compiled revision]
  → define ServingExperiment (trace, serving config, serving parallelism, profile)
  → Run Serving Experiment
  → LLMServingSim-owned: arrivals, queues, scheduling, batching, prefill/decode
  → VERITX-owned: ASTRA network execution, round qualification, round evidence
  → request metrics + round evidence
[End]
```

**Static and serving identities stay separate.**

## 88. FLOW-G — optimization study

```text
[baseline compiled revision]
  → StudyDefinition      (design space, objectives, constraints, requirements, evaluation policy)
  → SearchExecutionPolicy (method, budget, seed)
  → Run Optimization Study
  → candidate generation (canonical, content-addressed)
  → per candidate through the canonical pipeline:
       compile → certificate → qualification → execution → evidence → metrics
  → constraint verdicts + objective availability
  → Pareto over ELIGIBLE candidates (backend authority)
  → selection (policy; ties by smallest candidate_id)
[End] completed Optimization Study
```

## 89. FLOW-H — candidate inspect / select / promote

```text
[candidate]
  → inspect: changed fields · design identity · compile state · certificate ·
             qualification · objectives · requirements · Pareto state · reason
  → explicit selection (study selection ≠ UI focus)
  → [PROMOTE]  ← IMPLEMENTATION_GAP today; must not be offered as available
[End]
```

## 90. FLOW-I — investigate a failure

```text
certificate FAIL
  → witness → owning upstream intent → edit → recompile
backend NOT_QUALIFIED
  → predicate results → another profile OR change the design → re-evaluate
execution FAILED
  → debris + attempt identity → retry (new attempt) OR inspect
```

**Each branch points to the appropriate upstream editable owner.**

## 91. FLOW-J — capability / provenance

```text
[any result or capability question]
  → claim scope        what may be claimed
  → capability stages  the 8 stages for the relevant row
  → limiting reason    the reason code for the first NO
  → provenance         compiler semantics · artifacts · certificate · producer ·
                       qualification profile · metric semantics · evidence
[End] no overclaim possible
```

## 92. Navigation derivation

Derived **after** the flows, from **workflow frequency** and **object
boundaries**.

```text
Objects:  Project → Revision → {Evaluation, ServingExperiment, Study, Candidate}
Actions:  edit intent · compile · inspect · evaluate · serve · optimize · compare
Cross-cutting: provenance · capability truth · history
```

## 93. Avoid artifact-driven navigation

**No top-level pages for** Mapping · Topology · Attachments · Routes · VCs ·
Certificate · Evidence. They belong under **Inspect compiled revision** or
**Evaluation provenance**.

## 94. Avoid domain-driven navigation

SYSTEM · WORKLOAD · PARALLELISM · COMMUNICATION · REQUIREMENTS · PHYSICAL are
**not** navigation destinations. **Ontology ≠ IA.**

## 95. Preferred IA — chosen

```text
┌──────────────────────────────────────────────────────────────────────┐
│  Project / Revision context bar        (always visible, unambiguous) │
├──────────────────────────────────────────────────────────────────────┤
│  Design   Evaluate   Serve   Optimize   History          Capability  │
└──────────────────────────────────────────────────────────────────────┘

DESIGN      authoring (System, Workload, Parallelism, Fabric, Requirements
            + advanced) AND the Compile Result inspector for the selected
            revision — one object, two modes
EVALUATE    static Evaluation (FLOW-C), Requirements (FLOW-D),
            Comparison (FLOW-E)
SERVE       Serving Experiments (FLOW-F)
OPTIMIZE    Studies, candidates, Pareto, selection (FLOW-G/H)
HISTORY     revisions, evaluations, experiments, studies, archive (FLOW-M)
CAPABILITY  capability diagnostics + provenance entry (FLOW-J/L)
```

**Why `Design` holds the inspector:** the compiled revision **is** the design
object. Splitting "author" and "inspect" into two destinations would fragment one
object and force the user to remember which mode they are in.

**Why `Serve` is primary and `Ramulator` is not:** serving has a real workflow;
Ramulator is `ENGINE_ONLY` and appears only in Capability.

**Rejected alternative: domain-driven navigation** (Design → System, Workload,
Parallelism, Communication, Fabric, Requirements, Memory as peers).
**Why it loses:** it makes one revision span seven destinations, gives a
single-table Memory map equal weight to Workload, and derives navigation from the
ontology rather than from user tasks (§94). It also cannot express the
static/serving split, because both share the same domains.

## 96. Design sub-navigation

```text
Design
├── System          agents, counts, hierarchy, interface, advanced: clock domains,
│                   advanced: Memory map (§12)
├── Workload        model family + params, advanced: Communication classes
├── Parallelism     TP / DP / EP / PP
├── Fabric          topology family, Side length, concentration, link width,
│                   advanced: arbitration
└── Requirements    RequirementSet
```

**Derived from §10 and the domain ownership law, not from screen layout.**

## 97. Compile / Inspect information architecture

```text
Compile Result
├── Summary        revision identity, certificate, capability stages, freshness
├── Mapping
├── Fabric         topology + attachments + unused seats
├── Routing        canonical routes + observation scope
├── Resources      VC + CDG + arbitration + router behavior
├── Address decode
└── Provenance
```

**Six groups, not ten pages.**

## 98. Evaluation information architecture

```text
Evaluate
├── Static Evaluation      FLOW-C
├── Requirements           FLOW-D / FLOW-K
├── Comparison             FLOW-E
└── Memory (status only)   ENGINE_ONLY disclosure — no run action (§46)
```

**Serving is not here** — it is its own primary destination because its entry,
scheduling authority and metrics differ (§41).

## 99. Optimization information architecture

```text
Optimize
├── Study Setup     StudyDefinition + SearchExecutionPolicy (§48)
├── Run / Progress  job state
└── Results         candidates, Pareto, requirements, selection, diagnostics
```

**Three product states are sufficient.**

## 100. History / provenance information architecture

```text
History
├── Revisions       compiled revisions + drafts
├── Evaluations     static + serving
├── Studies         optimization studies
└── Archive         archived objects with provenance intact
```

**Both project-wide and per-object views read the same objects.** **No duplicated
authority** — history is a projection over the object model, never a separate
store.

## 101. Deep links

Canonical deep-link targets: **Project revision · Evaluation · ServingExperiment ·
Study · Candidate · Certificate claim · Capability row · Provenance chain.**

**This enables reproducible collaboration** — a claim can be linked to the exact
object that supports it.

## 102. Empty states

| Missing | Semantic empty state |
|---|---|
| No project | create or open a project |
| No draft | create a draft or fork a revision |
| No compiled revision | **Compile design** |
| No evaluation | **Choose an evaluation profile** |
| No serving experiment | define one |
| No studies | **Create an optimization study** |
| No capability data | fail closed — no claim rendered |

**No marketing copy.**

## 103. Unsupported feature states — consistent product behaviour

| State | Product behaviour |
|---|---|
| `NOT_AVAILABLE` | **no action rendered**; explain if the capability is requested |
| `ENGINE_ONLY` | visible in **Capability diagnostics**; **no Run action** |
| `INSPECT_ONLY` | reachable through the relevant inspector; **no run** |
| `FUTURE_CONTRACT` | **no control**; documentation may explain "not modeled" |
| `LEGACY_ONLY` | only in migration/import diagnostics or a developer path |
| `IMPLEMENTATION_GAP` | **not offered as available**; planned flow documented only |

**No generic disabled button.** Each state has a distinct, explained behaviour.

## 104. INSPECT_ONLY state

**Torus:** reachable via Design → Fabric (declarable) and the Compile Result →
Fabric inspector (derivable). Evaluation is **prevented at the route stage** with
an explanation, not by disabling the topology.

## 105. ENGINE_ONLY state

**Ramulator:** appears in **Capability diagnostics** with status, profile and
claim scope. **No Run action.** **No fake workflow.**

## 106. IMPLEMENTATION_GAP state

**Accepted target, not implemented.** The planned flow may be documented; **the
current product must not claim availability.** Examples: candidate promotion ·
evidence reuse · multi-class execution · static MoE · escape-VC materialization.

**Distinct from `FUTURE_CONTRACT`**, where semantics are not accepted at all.

## 107. FUTURE_CONTRACT state

**No controls.** Capability documentation may explain *not modeled*.
**No disabled configuration surface implying near-term support** — a disabled
control is a promise.

## 108. LEGACY_ONLY state

Accessible only through **migration/import diagnostics** or a developer path.
**Never exposed as a normal new-design control.** Examples: REMOTE/CXL/STORAGE
location grammar · PIM markers · Phase-9 operand bytes.

## 109. User sophistication

```text
GUIDED user    task sophistication: wants a goal-driven path
EXPERT user    task sophistication: wants explicit typed contracts
```

**Both operate on the same canonical workflows.** Gate 5 only guarantees the
canonical contract exists; detailed differentiation belongs **Gate 6**.

## 110. Progressive disclosure — recorded, not designed

Advanced concepts that exist and must be reachable but are **not** designed here:
communication class bindings · address map · arbitration · backend qualification
details · evidence provenance · capability reason codes.

**Gate 6 decides Guided/Expert exposure.**

## 111. Undo / revision semantics

```text
draft edits        undoable (mutable, non-canonical)
compiled revisions immutable — no undo across a compile
historical evidence never mutated
```

**Recovery from a mistaken compile is a new draft, not an undo.**

## 112. Delete / archive semantics

Users may **archive** old revisions, evaluations and studies.
**Scientific parent references must not dangle.**

## 113. Cross-object deletion law — **archive, never destructive delete**

A revision referenced by an evaluation or study **must not disappear**. Target:
**archive/tombstone**, preserving resolvability (P28).

## 114. Long-running execution state

```text
queued → running → completed | failed | cancelled
```

**Job state is never scientific state.** `COMPILING` is a job state; the
scientific outcome is `COMPILED`/`COMPILE_REFUSED`. **Scientific result identity
is separate from job state.**

## 115. Retry semantics

```text
retry a failed execution → SAME scientific Evaluation definition
                         → NEW ExecutionAttempt
                         → NO new Design Revision
```

**Likewise for optimization attempts.**

## 116. Cancellation

**Cancelling creates no fake measured result.** Partial evidence admissibility
follows the backend contract; an incomplete drain is `INCONCLUSIVE`, never a
number.

## 117. Re-run semantics

```text
"Run again" under the same definition → new attempt
                                      → same scientific definition
```

**Stable evidence may deduplicate** where the evidence model says it is identical
(Gate 3 §19: cycle evidence survives a clock change; ns evidence does not).

## 118. Product object glossary (user-facing)

| Term | Meaning |
|---|---|
| **Project** | container; no scientific identity |
| **Design Revision** | immutable scientific design (`design_hash`) |
| **Draft** | mutable, non-canonical intent |
| **Compile Result** | the inspector over a Design Revision |
| **Static Evaluation** | one qualified static backend execution + evidence |
| **Serving Experiment** | one serving run with its own scheduling authority |
| **Optimization Study** | one study definition + its execution |
| **Candidate** | one content-addressed design point in a study |
| **Requirement Set** | the revision's declared requirements |
| **Evaluation Profile** | backend profile + clock + options; not design |
| **Provenance** | the exact object chain supporting a claim |
| **Capability** | staged truth for one feature |

**Avoided overloaded terms:** bare **Run** (always qualified) · **Config** (→
Intent / Evaluation Profile / Search Execution Policy) · **Node** (→ agent /
router / backend node) · **Rank** (→ participant) · **Model** (→ Workload model) ·
**Profile** (always qualified) · **Design** (→ Draft or Revision).

## 119. Claim-surface integration

Every surface making a scientific claim must have access to
**`capability_semantics_version`** and the **qualification/evidence scope**
(Gate 4 CAP-D5).

**Workflow requirement:** a claim surface that cannot resolve a current
`capability_semantics_version` **must refuse to render the claim** (P26).

## 120. Current Studio → target mapping

| Current surface | Target workflow | Problem | Action |
|---|---|---|---|
| `pages/index.tsx` | Project entry + summary | mixes project, design, capability, evaluation and demo copy; `intervention.supported` boolean (CC-1); vague "execute supported communication" (CC-2) | **REBUILD** as Project entry + summary facts (§129) |
| `pages/design.tsx` | FLOW-A + FLOW-B | merges authoring and inspection without distinction; `Radix` label; **RCU control rendered although RCU was removed from v4** | **REBUILD** (author/inspect modes) + **RENAME** (Side length) + **REMOVE** (RCU control) |
| `components/DesignEditor.tsx` | Design authoring | `Radix` wording; no memory map; no advanced grouping; missing staged capability feedback | **REBUILD** |
| `components/FabricView.tsx` | Compile Result → Fabric | correct role; belongs under Compile Result, not a peer page | **MOVE** |
| `components/FabricInspector.tsx` | Compile Result → Fabric | correct; keep | **KEEP** |
| `components/FabricCanvas.tsx` / `FabricCanvas3D.tsx` | Fabric visualization | presentation; out of scope here | **KEEP** |
| `components/VerifyView.tsx` | FLOW-I + certificate claims | single verdict framing; needs four separate claims (§28) | **REBUILD** |
| `components/EvaluateView.tsx` | FLOW-C | correct vocabulary; needs EvaluationPolicy + envelope choice + qualification preflight | **REBUILD** |
| `components/ArtifactChain.tsx` / `ArtifactStrip.tsx` | FLOW-J provenance | correct role; belongs to provenance, cross-cutting | **KEEP** + **MOVE** under Provenance |
| `pages/evidence.tsx` | FLOW-J provenance | correct as a RunBundle inspector; needs to be reachable from every result | **KEEP** |
| `pages/optimize.tsx` | FLOW-G/H | mostly correct; needs StudyDefinition vs SearchExecutionPolicy separation and promotion marked unavailable | **REBUILD** |
| `components/OptimizeView.tsx` | FLOW-G results | reads `pareto_member`/`pareto_eligible` correctly; keep the authority discipline | **KEEP** |
| `components/OptimizationAnalysis.tsx` | FLOW-G analysis | keep | **KEEP** |
| `pages/serving.tsx` | FLOW-F | correct separation; needs ownership split made explicit | **KEEP** + **REBUILD** labels |
| `pages/offline.tsx` | fixture/demo mode | developer/demo path; must not appear as a normal workflow | **MOVE** (developer path) |
| `api.capabilities()` / `GET /api/v1/capabilities` | FLOW-L | exists; needs product rendering + version check | **KEEP** + **REBUILD** surface |
| `api.compare()` | FLOW-E | exists; needs comparability refusal surfaced | **KEEP** |
| `api.preflight()` | §9 level 2 | exists; correct level | **KEEP** |
| legacy CLI `synthesize`/`sweep`/`baseline` | — | HISTORICAL, not canonical | **REMOVE** from product surfaces |
| `POST /optimize` | — | `deprecated=True` | **REMOVE** |

## 121. Current homepage

**Audit:** `pages/index.tsx` mixes project entry, design entry, capability
statements, evaluation entry and product-evaluation marketing copy
(*"Compile the fabric, prove its obligations, execute supported communication"*).

**Target role:** **Project entry + project summary** (§129). It states facts
about the active project's objects; it makes **no scientific claim** and renders
**no capability boolean**.

## 122. Current Design page — control audit

| Current control | Verdict |
|---|---|
| `workload.model_family` | **KEEP** |
| `workload.model_name` | **KEEP** (metadata) |
| `workload.serving_mode` | **KEEP** — but note it must not imply a serving workflow |
| `workload.tp/pp/ep/dp` | **KEEP** |
| requirements (traffic_class, qos_class, metric, op, threshold, binding) | **KEEP** — but `traffic_class`/`qos_class` are **advanced** (§17) |
| `agents[].count` | **KEEP** |
| `noc_config.topology_family` | **KEEP** — add staged feedback for torus |
| **`noc_config.radix` labelled "Radix"** | **RENAME → "Side length"** (Gate 3 §7) |
| `noc_config.concentration` | **KEEP** — add qualification feedback |
| `noc_config.link_width` | **KEEP** |
| `noc_config.arbitration` | **KEEP** — move to advanced; canonicalization must precede identity (XDOM-D6) |
| **`noc_config.rcu_enabled`** | **REMOVE** — RCU was removed from v4; `FUTURE_CONTRACT` / `NOT_AVAILABLE`. No ordinary Design control; capability diagnostics explain the concept is not modeled. Legacy parsing is preserved (§19.3) |
| `mcast_groups` / `mcast_setup_cycles` | **not currently rendered** — **keep it that way**: hardware multicast is `FUTURE_CONTRACT` (`COMM-005`), so no control is rendered |
| **missing: address map** | **ADD** (advanced, §12) — **PF-D1** |
| **missing: physical / design clock** | **ADD** (advanced) — **PF-D2** |
| **missing: communication classes** | **ADD** (advanced Workload) |
| **missing: dependencies / collectives** | **ADD** (D5 view widening) |
| placement / VC count / turn restrictions / manual endpoints | **absent — correct** |

## 123. Current Evaluation page

**Audit:** `EvaluateView.tsx` has the right status vocabulary
(`BACKEND_UNAVAILABLE / EVALUATED / FAILED / UNSUPPORTED`) but:
no `EvaluationPolicy` object; no envelope/profile choice (§31); no qualification
preflight step; no separation of static vs serving; requirements rendered without
the threshold-reuse path.

**Decision:** **REBUILD** (§98).

## 124. Current Optimize page

**Audit against Domain J / Gate 3:**

| Check | Result |
|---|---|
| StudyDefinition present | yes — but method/budget/seed are fused into `definition_id` (XDOM-D5) |
| search method/budget/seed separated in the UI | **NO** — not separated |
| candidate status vocabulary | correct |
| Pareto authority | correct — read, not recomputed |
| Requirement annotation | needs the Gate-3 §8 orthogonal treatment surfaced |
| raw dimensions | correct (typed) |
| canonicalization | **arbitration gap** (XDOM-D6) |
| promotion | **must be marked unavailable** (OPT-008) |

**Decision:** **REBUILD** the setup surface; **KEEP** the results surface.

## 125. Current derived-artifact views

`FabricView` and `FabricInspector` are correct in **not** offering editing.
**IA fix:** they move **under the Compile Result** rather than being peer
destinations (§97).

## 126. User-state continuity

**Global context model:**

```text
ACTIVE PROJECT   (always set once inside a project)
ACTIVE REVISION  (a draft OR a compiled revision — never ambiguous)
```

Every page operates on the active context. **No page may silently operate on a
different revision.**

## 127. Revision selector

```text
draft selected            → edit actions available; compile available
compiled revision selected → inspect/evaluate/optimize available; edit creates a successor draft
historic revision selected → read-only; actions available per that revision's state
```

**Actions depend on state.** No widget design here.

## 128. Latest-run semantics

**"Latest run" is eliminated.** It is replaced by three distinct facts:

```text
Latest Static Evaluation
Latest Serving Experiment
Latest Optimization Study
```

**No ambiguous global "run."**

## 129. Project summary state

```text
current draft (and its freshness)
latest compiled revision (+ certificate status)
latest static evaluation (+ qualification profile)
latest serving experiment
latest optimization study
```

**No single giant status.**

## 130. Error ownership

Every displayed error maps to **stage · owner domain · object · possible
remedy**.

**A typed refusal is always preferred over a raw backend exception as the
primary message.** The raw text is available at the technical detail level.

## 131. Diagnostic levels

```text
1  user-actionable summary      what failed, which field/stage, what to do
2  technical detail             reason code, profile predicates, compiler verdict
3  evidence/provenance detail   artifact hashes, semantics versions, proof chain
```

**Supports Guided and Expert later** without designing them here.

## 132. Adversarial verdicts P1–P30

| # | Case | Verdict |
|---|---|---|
| P1 | user edits a compiled design | creates **dirty successor draft**; historical revision intact (§6) |
| P2 | requirement threshold changed after evaluation | **no backend rerun**; report recomputed (FLOW-K) |
| P3 | user selects Torus | compile + inspect topology; **evaluation blocked at route stage** |
| P4 | concentration 2 + native mesh profile | design **valid**; `NOT_QUALIFIED` (§33) |
| P5 | backend profile changed only | **Design Revision unchanged** (§30) |
| P6 | network clock changed only | design unchanged; evaluation evidence per §19 (cycles reusable, ns not) |
| P7 | arbitration changed | design changes; **recompile required** |
| P8 | manual placement attempted | **action absent** (MAP-002) |
| P9 | VC count edit attempted | **action absent** (derived) |
| P10 | user inspects the full canonical route | **allowed** (EVAL-008) |
| P11 | "did BookSim observe the full route?" | product states **observation scope**: first-hop routing-function equivalence over the full src×dst domain; **not** observed packet paths |
| P12 | requirement report on a failed-certificate number | **no authoritative SATISFIED** (Gate 3 §26) |
| P13 | opens an old evaluation after new draft edits | historical result **stays attached to the old revision** |
| P14 | retries a failed evaluation | **new attempt, same definition** (§115) |
| P15 | launches optimization then edits the draft | running study stays bound to the **original baseline revision** |
| P16 | candidate violates a requirement | **may still be a Pareto member**, annotated (Gate 3 §8) |
| P17 | user promotes a candidate | creates a **new Design Revision**; study immutable (§55) |
| P18 | opens Ramulator capability | engine info visible; **no fake Run workflow** (§46) |
| P19 | wants static MoE evaluation | capability stage explains **`DERIVABLE NO`** |
| P20 | wants serving MoE | **separate serving workflow is available** (§44) |
| P21 | changes a communication class | downstream **staleness per the dependency graph** |
| P22 | changes only a display name | **no recompilation** (metadata law) |
| P23 | backend unavailable | evaluation definition remains; attempt **`BACKEND_UNAVAILABLE`** |
| P24 | backend not qualified | **no execution** unless an alternate profile is explicitly chosen |
| P25 | compares incompatible metric producers | **INCOMPARABLE** (§40) |
| P26 | stale capability cache disagrees with registry version | claim surface **refuses to render** (§119) |
| P27 | current draft invalid, historical evaluation valid | **both states coexist** (§7) |
| P28 | archives a revision used by a study | **provenance remains resolvable** (§113) |
| P29 | unknown enum arrives from the API | **fail closed** |
| P30 | current Studio exposes a `FUTURE_CONTRACT` control | **REMOVE** (§107) |

**Flow-specific additions:**

| # | Case | Verdict |
|---|---|---|
| P31 | user edits `radix` value | the **same** dimension as side length — one field, one law (§18) |
| P32 | RCU enabled then compiled | **no target control exists**; RCU is `FUTURE_CONTRACT` / `NOT_AVAILABLE` (§19.2) |
| P33 | multi-class design compiled | valid through verification; **execution unavailable** (COMM-006) |
| P34 | second clock domain declared | declarable; **fabric execution unavailable** (SYS-003/004) |
| P35 | preset produces an invalid combination | **same validation as manual entry** (§72) |
| P36 | user asks why evaluation is unavailable for torus | Capability row names the **single blocking stage** (route derivation) |
| P37 | user opens a study whose baseline revision was archived | study remains inspectable; baseline reference **resolves** |
| P38 | ns metric compared across two different clocks | **INCOMPARABLE** |
| P39 | cycles metric reused after a clock change | **reusable** under the authenticated recovery contract |
| P40 | user requests candidate promotion | **not offered** — `IMPLEMENTATION_GAP` (§106) |
| P41 | user wants to enable RCU | **no ordinary Design control exists**; capability inspection reports `FUTURE_CONTRACT` / `NOT_AVAILABLE`; the product explains that in-network reduction semantics are not part of the accepted router-resource contract; **no draft scientific identity changes**; **no "enable anyway" path exists** |
| P42 | legacy imported design contains `rcu=true` | the compatibility/import layer **recognizes** the legacy state; target authoring does **not** silently convert it into accepted RCU intent; migration/refusal status is **explicit**; a new v4 design **cannot originate** the field (§19.3) |

## 133. Flow completeness test

| Capability class | Where it is invoked / inspected / disclosed |
|---|---|
| **WIRED** (34 rows) | every one maps to a flow: FLOW-A (design domains), FLOW-B (inspection), FLOW-C (static eval), FLOW-D/K (requirements), FLOW-F (serving), FLOW-G/H (optimization) |
| **INSPECT_ONLY** (6 rows: MAP-001, FAB-003, ROUTE-005, ROUTE-006, EVAL-008, and the corrected MEM-001) | all live in **Compile Result** sub-inspectors (§22) |
| **ENGINE_ONLY** (1 row: MEM-002 Ramulator) | **Capability diagnostics** (§105) |
| **NOT_AVAILABLE** (32 rows) | **no action rendered**; explained where the user would look for it (§103) |

**No orphan capability.** Every `WIRED` row has a flow; every `INSPECT_ONLY` row
has an inspector; the `ENGINE_ONLY` row is discoverable; `NOT_AVAILABLE` rows
create no false action.

## 134. Action completeness test

| Action | Capability row authorizing it | Object mutated/created | Validation stage | Result object |
|---|---|---|---|---|
| Edit intent | the domain rows (UI-owned) | Intent Draft | on-edit / on-blur | draft |
| Compile Design | WORK-001 / FAB-001 | Design Revision | compile | revision + certificate |
| Inspect | INSPECT_ONLY rows | none | — | view |
| Run Evaluation | EVAL-004 + an envelope | Evaluation | qualification | evidence + metrics |
| Evaluate Requirements | REQ-001/002 | RequirementReport | report | report |
| Compare | the metric registry | none | comparability | comparison / INCOMPARABLE |
| Run Serving Experiment | EVAL-005 + CAP-ENV-BOOKSIM-SERVING-V1 | ServingExperiment | round qualification | round evidence |
| Run Study | OPT-001/002/003 | Optimization Study | candidate pipeline | study + frontier |
| Promote | **OPT-008 — NOT WIRED** | — | — | — |
| Archive | — | archive state only | — | — |

**No ungrounded action.** `Promote` is the one action whose capability is
`IMPLEMENTATION_GAP`, and it is therefore **not offered**.

## 135. Product IA deliverable

```text
PRIMARY NAVIGATION
  Design · Evaluate · Serve · Optimize · History · Capability

SECONDARY / CONTEXT
  Design      → System · Workload · Parallelism · Fabric · Requirements
  Compile Result → Summary · Mapping · Fabric · Routing · Resources ·
                   Address decode · Provenance
  Evaluate    → Static Evaluation · Requirements · Comparison · Memory status
  Optimize    → Study Setup · Run · Results
  History     → Revisions · Evaluations · Studies · Archive

OBJECT HIERARCHY
  Project
   └── Design Revision (immutable)
        ├── Compile Result (view)
        ├── Static Evaluation
        ├── Serving Experiment
        └── Optimization Study
             └── Candidate

ACTIVE CONTEXT
  active Project + active Revision, always visible, never ambiguous

PLACEMENT
  Design authoring        → Design
  Compiled inspection     → Design (Compile Result mode)
  Static evaluation       → Evaluate
  Serving                 → Serve
  Optimization            → Optimize
  History / provenance    → History (+ Provenance reachable from every result)
  Capability truth        → Capability
```

## 136. Preferred IA requirement — one choice, one rejected alternative

**Chosen: object-lifecycle navigation** (§95) — Design · Evaluate · Serve ·
Optimize · History · Capability.

**Rejected: domain-driven navigation** — Design → System / Workload / Parallelism
/ Communication / Fabric / Requirements / Memory as peers. **Why it loses:**
seven destinations for one revision; a single-table Memory map weighted equally
with Workload; navigation derived from the ontology instead of user tasks; and it
cannot express the static/serving split because both share the same domains.

## 137. Deliverable checklist

| # | Required content | § |
|---|---|---|
| 1 | product object model | §3 |
| 2 | lifecycle / state model | §5, §7 |
| 3 | revision model | §4, §6, §68 |
| 4 | editable Design domains | §10 |
| 5 | static workload workflow | §13, §82 |
| 6 | serving workflow | §41–§45, §87 |
| 7 | compile workflow | §8, §82 |
| 8 | inspect workflow | §21–§26, §83 |
| 9 | verification workflow | §27, §28 |
| 10 | static evaluation workflow | §29–§34, §84 |
| 11 | requirements workflow | §17, §36, §37, §85 |
| 12 | comparison workflow | §38–§40, §86 |
| 13 | optimization workflow | §47–§50, §88 |
| 14 | candidate selection / promotion | §51–§55, §89 |
| 15 | capability / provenance workflow | §56–§59, §91 |
| 16 | failure / recovery flows | §61–§66, §90 |
| 17 | stale / freshness law | §7, §67 |
| 18 | retry / re-run law | §114–§117 |
| 19 | FLOW-A…FLOW-J diagrams | §81–§91 |
| 20 | target IA | §92–§101, §135 |
| 21 | current Studio → target mapping | §120–§125 |
| 22 | product object glossary | §118 |
| 23 | P1–P40 adversarial verdicts | §132 |
| 24 | D1/D5/D6/D8 product resolutions | §76–§79 |
| 25 | remaining product-flow debt | §138 |

## 138. Remaining product-flow implementation debt

```text
PF-D1   address map authoring + inspection surface (Design → System → advanced)
        capability registry corrected to NOT_AVAILABLE for the surface
PF-D2   physical / design-clock authoring surface (advanced)
PF-D3   communication-class authoring surface (advanced Workload)
PF-D4   DesignView v2 widening: collectives, dependencies, address_map, physical,
        product layer (D5)
PF-D5   EvaluationPolicy as a first-class product object
PF-D6   envelope recommendation + explicit confirmation (no silent substitution)
PF-D7   capability diagnostics surface with capability_semantics_version check
PF-D8   staged capability feedback beside declarable-but-limited controls
        (torus, RCU, multicast knobs, concentration, multi-class, multi-clock)
PF-D9   four separate certificate claims instead of one verdict
PF-D10  StudyDefinition vs SearchExecutionPolicy separation in the setup surface
PF-D11  promotion marked unavailable until OPT-008 lands
PF-D12  "Side length" rename replacing the "Radix" label
PF-D13  remove the ambiguous "Latest run" concept
PF-D14  archive/tombstone instead of destructive delete
PF-D15  remove legacy CLI surfaces (synthesize/sweep/baseline) and POST /optimize
PF-D16  remove the `rcu_enabled` (and any `mcast_*`) control from Design authoring;
        route RCU to capability diagnostics as FUTURE_CONTRACT / NOT_AVAILABLE;
        classify legacy `rcu` state explicitly in the migration/import layer
        (GATE-5 CORRECTION, §19.2/§19.3)
```

**Referenced, not duplicated:** XDOM-D1…D8 · CAP-D1…D5 · OPT-D2…D8 · MEM-D1…D5 ·
FAB-D1/D4/D6 · VC-D1 · COMM-D1 · ROUTER-D2.

## 139. Coherence check against §138 criteria

| # | Criterion | Status |
|---|---|---|
| 1 | every primary object has one identity/lifecycle | **MET** (§3) |
| 2 | Draft vs compiled revision exact | **MET** (§4, §5) |
| 3 | editing never mutates historical science | **MET** (§6) |
| 4 | editable Design domains match ontology truth | **MET** (§10, §122) |
| 5 | derived artifacts inspection-only | **MET** (§21–§26) |
| 6 | static vs serving separate workflows | **MET** (§14, §41, §98) |
| 7 | capability stages control action availability | **MET** (§19, §59, §103) |
| 8 | Torus valid-but-non-executable flow coherent | **MET** (§20, §104) |
| 9 | backend qualification ≠ design validity | **MET** (§9, §33, §65) |
| 10 | requirement threshold edits reuse evidence | **MET** (§37, §85) |
| 11 | comparison obeys metric comparability | **MET** (§40, §86) |
| 12 | optimization binds immutable baseline revision | **MET** (§47, P15) |
| 13 | candidate promotion creates new revision | **MET** (§55) |
| 14 | no nonexistent placement/VC/routing controls | **MET** (§10, §122) |
| 15 | Ramulator ENGINE_ONLY has no fake workflow | **MET** (§46, §105) |
| 16 | all WIRED capabilities have a flow | **MET** (§133) |
| 17 | all INSPECT_ONLY capabilities have an inspector | **MET** (§133) |
| 18 | unavailable capabilities create no fake action | **MET** (§103, §133) |
| 19 | stale/current explicit per stage | **MET** (§7) |
| 20 | retry semantics distinct from definition identity | **MET** (§114–§117) |
| 21 | errors map to stage/domain/object/remedy | **MET** (§61, §130) |
| 22 | active Project/Revision context unambiguous | **MET** (§126, §127) |
| 23 | current Studio surfaces have decisions | **MET** (§120) |
| 24 | D1/D5/D6/D8 product halves resolved | **MET** (§76–§79) |
| 25 | preferred IA chosen | **MET** (§95, §136) |
| 26 | P1–P40 have verdicts | **MET** (§132) |
| 27 | Guided/Expert detailed planning not begun | **MET** |
| 28 | wireframes not begun | **MET** |
| 29 | HTML not begun | **MET** |

## 140. Domain verdict

Gate 5 answered the core question by building workflows first and navigation
last. **Ten primary flows** cover the product; three more fell out of the Studio
audit. Navigation is a **consequence** — Design · Evaluate · Serve · Optimize ·
History · Capability — and the rejected domain-driven alternative loses because
seven destinations for one revision is not an information architecture, it is the
ontology wearing a sidebar.

The single most important law this gate locks is that **the Design page edits an
Intent Draft whose canonical serialization is `CompileRequestV3`** (D1, option b),
with `CompileIntent` demoted to a preset-expansion shortcut. That choice is forced
by Gate 3: the compiler root carries the canonical identity, and the product root
is convenience. Combined with revision immutability, it makes the stale/current
model fall out for free — a draft has no results, and a revision's results never
move.

The second is **staged capability feedback**, which is how the product stops
lying without hiding valid science. Torus is *declarable and derivable and
unroutable*: it compiles, its topology is inspectable, and evaluation is blocked
at the route stage with an explanation. **RCU is neither declarable nor
derivable** — it was removed from v4, so no control is rendered and capability
diagnostics explain that in-network reduction semantics are not part of the
accepted router-resource contract. That
is `ALLOW + WARN`, not a refusal banner implying the design is broken. Meanwhile
manual placement, VC count and multiplane are **not rendered at all**, because no
canonical contract exists. **The difference is whether the intent is real.**

The Studio audit produced one genuine Gate-4 contradiction. The registry listed
`MEM-001 AddressMap` as `PRODUCT_WIRED: YES`; the audit found **no authoring
control, no inspection surface, and no `address_map` field in `DesignView`**.
Corrected minimally to `NOT_AVAILABLE` for the surface and recorded as **PF-D1** —
the science is unchanged, `AddressMap` remains declarable and canonical, and
presets supply it internally. The same audit found the Design page still labels
`NocConfig.radix` as **"Radix"** when Gate 3 fixed the scientific name as **side
length** (PF-D12), and that the RCU control implies invalidity where the truth is
that **RCU has no accepted contract at all** — a correction recorded here because
the first-pass Gate-5 wording (*"RCU → ALLOW + WARN"*) contradicted
`INTENT-ROUTER-RESOURCES.md:316,320` and `INTENT-FABRIC.md:415`. The rule is now
precise: **`ALLOW + downstream warning` requires accepted canonical intent; a
legacy field, enum or parser path is insufficient.**

Four D-decisions landed here, as Gate 3 intended. **D1** → the draft is the
editable layer and `intent_id` is never a design identity. **D5** → `DesignView`
must widen to v2 carrying `collectives`, `dependencies`, `address_map`, `physical`
and the product layer; the current v1 carries none of them, so the UI cannot show
them without reaching into the engine. **D6** → the two named coherence checks are
**cross-domain joins**, so they belong at preflight, not per keystroke, and
compile/report keep the authority. **D8** → the six primitives are already frozen
mechanically by the ontology checker; this gate adds only their **workflow
meaning**, and detailed visual architecture belongs Gate 8.

What the product may now honestly do: compile a design and inspect every derived
artifact · evaluate under one of three named certified profiles with the
qualification failure explained rather than hidden · recompute a requirement
report without re-running a backend · compare only what is comparable · run
serving experiments with LLMServingSim's authority and VERITX's network execution
kept distinct · run certified optimization studies and read a backend-authoritative
frontier. And what it may not do: offer promotion, offer a Ramulator run, offer
manual placement, or collapse any of these into one green badge.

**GATE 5 — PRODUCT FLOWS: PLANNED — COHERENT**

Gate 6 not begun. No Guided/Expert detailed UI. No wireframes. No HTML.
