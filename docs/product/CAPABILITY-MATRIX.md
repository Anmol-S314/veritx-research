# CAPABILITY MATRIX — Gate 4

Machine registry: `docs/product/capability-registry.yaml`
Upstream: `docs/product/CROSS-DOMAIN-LAWS.md` (Gate 3) + the eleven
`docs/product/INTENT-*.md` domain documents (Gate 2)
Status: **PLANNED — COHERENT.** See §52.

---

## 0. What this gate replaces

Capability truth was distributed across domain documents, cross-domain laws,
backend qualification code, verification certificates, execution adapters, Studio
surfaces and legacy UI language. This gate collapses it into **one model**.

The forcing requirement: **Product must not be able to say `SUPPORTED` when the
truth is *declarable but not derivable*, *derivable but not verifiable*,
*verifiable but backend-unqualified*, *engine available but product-unwired*,
*expected canonically but not backend-observed*, or *legacy-only*.**

Today the repository does exactly that in at least one place:
`apps/studio/src/pages/index.tsx:747` renders
`{data.intervention.supported ? 'SUPPORTED' : 'NOT SUPPORTED'}` — a single
boolean for a multi-stage fact (§48).

## 1. Stage vocabulary (finalized)

Eight stages, **ordered but independent** — no stage implies the next.

| Stage | Question |
|---|---|
| **DECLARABLE** | can canonical intent/schema represent it? |
| **DERIVABLE** | can the canonical compiler/lowering produce the required artifacts? |
| **VERIFIABLE** | can mandatory canonical verification issue a meaningful verdict? |
| **PROJECTABLE** | can it be projected into a concrete backend representation? |
| **EXECUTABLE** | can a backend actually execute that projection? |
| **QUALIFIED** | does a named profile authorize a scientific claim for that execution? |
| **EVIDENCE_CAPABLE** | can authenticated evidence be produced for the claimed property? |
| **PRODUCT_WIRED** | can the product invoke and expose it today? |

**Allowed transitions — the law of the matrix:**

```text
DECLARABLE   → DERIVABLE → VERIFIABLE → PROJECTABLE → EXECUTABLE
                                                        → QUALIFIED → EVIDENCE_CAPABLE
any stage → PRODUCT_WIRED (independent axis)

A later stage is NOT REACHED when an earlier one is NO.
PRODUCT_WIRED never implies any scientific stage.
```

**Reconciliation with Gate 3 (§14).** Gate 3's vocabulary was
`DECLARABLE · DERIVABLE · VERIFIABLE · PROJECTABLE · EXECUTABLE · QUALIFIED ·
EVIDENCE-CAPABLE · PRODUCT-WIRED`. **Identical, unchanged.** Gate 3 already
distinguished `PRODUCT-WIRED` as the product axis; Gate 4 adds the **product-wiring
sub-vocabulary** (§5) so "product state" can be finer than yes/no.

**No ambiguous "supported" state exists.** `SUPPORTED` is not a value.

## 2. Stage independence — the three canonical demonstrations

| Capability | DECL | DERIV | VERIF | PROJ | EXEC | QUAL | EVID | WIRED |
|---|---|---|---|---|---|---|---|---|
| **TORUS** | YES | topology YES / routing **NO** | topology YES | NO | NO | NO | NO | INSPECT_ONLY |
| **RAMULATOR** | NO | YES | NO | YES | **YES** | **YES** (envelope) | YES | **ENGINE_ONLY** |
| **CONCENTRATION > 1** | YES | YES | YES | CONDITIONAL | CONDITIONAL | **NO** (mesh-DOR envelope) | CONDITIONAL | WIRED |

A single boolean cannot express any of these rows.

## 3. Result vocabulary

```text
YES · NO · CONDITIONAL · NOT_APPLICABLE · LEGACY_ONLY · FUTURE_CONTRACT · ENGINE_ONLY
```

**Forbidden in a cell:** `mostly`, `partial`, `experimental`, `kind of supported`.

**`CONDITIONAL` requires a referenced condition or envelope ID.** Example:

```yaml
QUALIFIED: CONDITIONAL
conditions: [CAP-ENV-BOOKSIM-MESH-DOR-XY-V1]
```

**`NOT_APPLICABLE`** means the stage is meaningless for that capability (e.g.
`EXECUTABLE` for a declared inventory). **`LEGACY_ONLY`** means reachable only
through a Phase-9 / compatibility path. **`FUTURE_CONTRACT`** means no accepted
semantics exist. **`ENGINE_ONLY`** is used only on the product axis.

## 4. Capability object model

```text
CapabilityRecord {
    capability_id        SYS-001 … OPT-008
    scientific_name
    domain_owner         SYSTEM | WORKLOAD | PARALLELISM | COMMUNICATION |
                         PLACEMENT | FABRIC | ROUTER_RESOURCE | MEMORY |
                         EVALUATION | REQUIREMENTS | DESIGN_SPACE
    stages[8]            one result value each
    conditions[]         named condition/envelope IDs when CONDITIONAL
    wiring               WIRED | ENGINE_ONLY | INSPECT_ONLY | NOT_AVAILABLE
    reason               limiting-reason code when any stage is NO
    limiting             one sentence
    claim_scope          what may actually be claimed
    future_contract      bool
}
```

**Not implemented as code.** It is the semantics model Product consumes.

## 5. Claim-scope model

Stage classification alone is insufficient: an `EVIDENCE_CAPABLE` cell must say
**what may actually be claimed**. Three worked cases:

**Route correctness — two different claims:**

```text
CANONICAL (derived expected):
  the canonical route table is legal and terminating.
BACKEND OBSERVED (first hop):
  the runtime routing-function/table first-hop realization is exactly
  equivalent to the canonical route over the COMPLETE source x destination
  domain.
NOT CLAIMED:
  observed packet paths.
```

This is **stronger** than the Gate-3 phrase "first hop verified" implied, and
**narrower** than per-packet instrumentation. The exact wording is taken from
`backend/route_observation.py:1-30`:
*"stronger than static configuration checking but narrower than per-packet
instrumentation … it proves deterministic first-hop routing equivalence, not
observed packet paths."*

**Ramulator:**

```text
CLAIM:     standalone DRAM-cycle timing simulation over a recorded
           legacy-derived request stream (request_generation: recorded stream;
           dram_timing: MEMORY_CYCLE_SIMULATION).
NOT CLAIM: NoC-inclusive memory latency; end-to-end model time; hardware accuracy.
```

**Optimization:**

```text
CLAIM:     typed finite design-space search over supported dimensions, with
           candidates compiled and evaluated through the canonical pipeline and
           a scientifically admissible Pareto set over compatible certified
           metrics.
NOT CLAIM: globally optimal interconnect; hardware-optimal design; complete
           exploration of arbitrary architecture space.
```

## 6. Limiting-reason taxonomy

```text
NO_CONTRACT · NO_DERIVATION · NO_VERIFIER · NO_BACKEND_PROJECTION ·
BACKEND_UNAVAILABLE · NOT_QUALIFIED · NO_EVIDENCE_CONTRACT ·
PRODUCT_NOT_WIRED · LEGACY_ONLY · FUTURE_CONTRACT · INVALID_COMBINATION ·
IMPLEMENTATION_GAP
```

**`IMPLEMENTATION_GAP` vs `FUTURE_CONTRACT` is a mandatory distinction** (§40):
a gap is an accepted target with unfinished work; a future contract has **no
accepted semantics**. **No free-text-only reasons** — every `NO` carries a code.

## 7. Product-wiring model (separate axis)

```text
WIRED          the product can invoke and expose the capability today
ENGINE_ONLY    a real engine exists with no product entry point
INSPECT_ONLY   derived output is viewable; not an invocable experiment
NOT_AVAILABLE  no product surface
```

**Scientific/engine capability ≠ product availability.**

| Capability | Wiring |
|---|---|
| Optimization | **WIRED** |
| Static Product Evaluation | **WIRED** |
| Serving Evaluation | **WIRED** |
| Ramulator | **ENGINE_ONLY** |
| Mapping / VC assignment / decode / CDG | **INSPECT_ONLY** |
| Torus topology | **INSPECT_ONLY** |
| Placement intent, affinity, promotion | **NOT_AVAILABLE** |

## 8. Condition / envelope registry

**Three real qualification profiles exist** (correcting the brief's single-profile
assumption):

| Envelope | Profile ID | Semantics version | Source |
|---|---|---|---|
| `CAP-ENV-BOOKSIM-MESH-DOR-XY-V1` | `CERTIFIED_BOOKSIM_MESH_DOR_XY_V1` | `booksim2-fork+P1B-meshdor-dump` | `backend/meshdor_profile.py:54` |
| `CAP-ENV-BOOKSIM-ANYNET-V1` | `CERTIFIED_BOOKSIM_ANYNET_V1` | `booksim2-fork+B3.7b-anynet-dump` | `backend/booksim_profile.py:33` |
| `CAP-ENV-BOOKSIM-SERVING-V1` | `CERTIFIED_SERVING_BOOKSIM2_V1` | — | `backend/booksim_profile.py:397` |
| `CAP-ENV-RAMULATOR-V1` | `ramulator-2.1-v1` | `veritx_dse.simulation.ramulator/1` | `simulation/ramulator.py:54` |
| `CAP-ENV-CERTIFIED-OPTIMIZATION-V1` | `certified-builtin-v1` | `veritx/optimization-result/v2` | `optimization/result.py:363` |

**Conditions** (`capability-registry.yaml :: conditions`):
`COND-TOPOLOGY-MESH` · `COND-ROUTING-DOR-XY` · `COND-CANONICAL-ROUTE-PRESENT` ·
`COND-SINGLE-COMM-CLASS` · `COND-IDENTITY-VC-TRANSITIONS` ·
`COND-SINGLE-CLOCK-FABRIC` · `COND-DENSE-STATIC-WORKLOAD` ·
`COND-CONFIG-AUDIT-CLOSED` · `COND-RAMULATOR-V1` ·
`COND-SERVING-ROUND-QUALIFIED` · `COND-CERTIFIED-BACKEND-AUTHORITY`.

**Five envelopes, not four** — the optimizer needs its own, because its
qualification is the certified metric registry and proof authority rather than a
BookSim profile. All 73 capability rows reference a known envelope or condition,
and every `QUALIFIED: YES` row names one.

**Each envelope lists:** required conditions · authorized stage · claim scope ·
failure meaning. **Failure means `NOT QUALIFIED FOR THAT ENVELOPE` — never
`invalid design`** (§35, C11).

**The closed-world config audit** (`backend/booksim_profile.py:1-20`) is the
mechanism that makes `COND-CONFIG-AUDIT-CLOSED` checkable:

> *"No result-affecting value consumed by the certified backend may come from an
> unnamed, unversioned compiled default."*

### 8.1 A Gate-4 reconciliation: `ParameterOwner`

Gate 3's field-ownership matrix had eight classes. The repository already has an
**enforced, narrower taxonomy for backend parameters**
(`backend/contracts.py:160`):

```text
FABRIC_DERIVED · WORKLOAD_DERIVED · EXECUTION_POLICY · BACKEND_PROFILE ·
SEMANTIC_LOSS · INACTIVE_FOR_PROFILE
```

Mapping: `FABRIC_DERIVED`+`WORKLOAD_DERIVED` → CD · `EXECUTION_POLICY` → EC ·
`BACKEND_PROFILE` → BP · `INACTIVE_FOR_PROFILE` → BP (documented subclass).

**Gate 4 adds one class Gate 3 lacked: `SEMANTIC_LOSS`** — a *named, declared*
semantic loss in a projection. This is not `MD` and not `BP`: it is a
first-class, auditable statement that a projection loses meaning. Gate 3's matrix
is extended by it (recorded as **XDOM-D8**).

Also relevant: `RepresentationStatus = EXACT | DERIVED_EXACT | COARSENED |
BACKEND_IRRELEVANT` (`backend/contracts.py:122`) — the per-dimension
representability contract that gives **PROJECTABLE** its real teeth: a dimension
is projectable when its status is `EXACT`/`DERIVED_EXACT`; `COARSENED` is a
declared loss, not a silent one.

## 9. Complete capability matrix

The full staged matrix is `docs/product/capability-registry.yaml`. Summary of the
rows whose truth is *not* a simple yes:

| ID | Capability | Non-trivial stages |
|---|---|---|
| SYS-003 | multiple declared clock domains | DECL YES · DERIV YES · **PROJ NO** |
| SYS-004 | multi-clock fabric execution | **DERIV NO** |
| WORK-002 | static MoE | DECL YES · **DERIV NO** (no dispatch/combine lowering) |
| WORK-004 | serving MoE | DECL YES · DERIV YES · EXEC CONDITIONAL |
| PAR-005 | sharding correctness | **DECL NO** — no contract |
| COMM-005 | hardware multicast | **DECL NO** — FUTURE_CONTRACT |
| COMM-006 | multiple communication classes | DECL YES · DERIV YES · VERIF YES · **PROJ NO** |
| MAP-002/003 | manual placement / affinity | **DECL NO** — NO_CONTRACT (D2) |
| FAB-002 | concentrated mesh | DECL YES · DERIV YES · **QUAL NO** (mesh-DOR envelope) |
| FAB-003 | torus topology | DECL YES · DERIV YES · **PROJ NO** |
| FAB-004 | torus routed execution | **DERIV NO** |
| ROUTE-004 | torus routing | **DERIV NO** |
| ROUTE-008 | escape VC designation | DERIV YES · **PROJ NO** |
| ROUTE-011 | RCU | **DECL FUTURE_CONTRACT** · DERIV NO |
| MEM-002 | Ramulator engine | EXEC YES · QUAL CONDITIONAL · **WIRED NO** |
| MEM-005 | network+memory coupling | **DECL NO** — FUTURE_CONTRACT |
| EVAL-006 | backend full-path observation | **NO** — no instrumentation |
| OPT-007 | evidence reuse / cache | **NO** — IMPLEMENTATION_GAP |
| OPT-008 | candidate promotion | **WIRED NO** — PRODUCT_NOT_WIRED |

## 10. Dense static workload — the complete staged row

```text
DECLARABLE      YES   dense_transformer, tp/pp/ep/dp, collectives
DERIVABLE       YES   participant inventory, mapping, topology, attachment,
                      decode, routes, resolved routes, VC assignment,
                      router behavior, communication lowering
VERIFIABLE      YES   FabricCompiler certificate + channel-VC CDG
PROJECTABLE     CONDITIONAL   requires a named envelope
EXECUTABLE      CONDITIONAL   under CAP-ENV-BOOKSIM-MESH-DOR-XY-V1 or
                              CAP-ENV-BOOKSIM-ANYNET-V1
QUALIFIED       CONDITIONAL   one of the two static envelopes
EVIDENCE_CAPABLE CONDITIONAL  authenticated backend evidence
PRODUCT_WIRED   YES
```

**Supported envelope (not merely "YES"):**

```text
model_family      dense_transformer
communication     exactly ONE unified traffic class (COND-SINGLE-COMM-CLASS)
clock domains     ONE (COND-SINGLE-CLOCK-FABRIC)
topology/routing  mesh + DOR-XY  → CAP-ENV-BOOKSIM-MESH-DOR-XY-V1
                  any canonical route → CAP-ENV-BOOKSIM-ANYNET-V1
config            closed-world audit passes (COND-CONFIG-AUDIT-CLOSED)
```

**Important exclusion conditions:** multi-class lowering (COMM-D1), static MoE,
multi-clock fabric, torus, hardware multicast.

## 11. Static MoE

```text
DECLARABLE      YES   MoE model semantics and EP extent exist
DERIVABLE       NO    no full static dispatch/combine lowering
VERIFIABLE      NO
PROJECTABLE     NO
EXECUTABLE      NO
QUALIFIED       NO
EVIDENCE_CAPABLE NO
PRODUCT_WIRED   NO
reason          IMPLEMENTATION_GAP
```

**Claim:** *MoE semantics are declarable; static MoE evaluation is not available.*
**A shared EP extent is not a capability bridge.**

## 12. Serving MoE — separate row

```text
DECLARABLE      YES   real dispatch/combine semantics
DERIVABLE       YES   serving participant projection
VERIFIABLE      YES   round qualification
PROJECTABLE     YES   ASTRA machine projection
EXECUTABLE      CONDITIONAL  CAP-ENV-BOOKSIM-SERVING-V1
QUALIFIED       CONDITIONAL
EVIDENCE_CAPABLE CONDITIONAL  round evidence
PRODUCT_WIRED   YES
```

**Serving MoE support ≠ static MoE support.** No inheritance in either direction.

## 13. TP / DP / EP / PP — decomposed, never "parallelism supported"

| Row | Claim scope |
|---|---|
| **PAR-001 TP** | grouping and collective participation are real; **tensor-sharding correctness is NOT proven** |
| **PAR-002 DP** | DP extent/group algebra is real; **gradient-replica semantics are NOT asserted** |
| **PAR-003 EP** | EP extent and communication participation are real; **expert-assignment boundaries are not modelled in static** |
| **PAR-004 PP** | PP group family is real; **stage assignment/lowering is INCOMPLETE** |
| **PAR-005 sharding correctness** | **no contract exists** (DECL NO) |

## 14. Broadcast vs multicast

| Row | Truth |
|---|---|
| **COMM-003 broadcast / root-fanout** | a real semantic collective, lowered to per-destination messages |
| **COMM-004 semantic multicast** | lowers to repeated unicasts — **it is not hardware multicast** |
| **COMM-005 hardware multicast** | **DECL NO**, FUTURE_CONTRACT. `mcast_groups`/`mcast_setup_cycles` are declarable knobs with **no execution** |

**Product must never show one generic "Multicast supported".** (C19.)

## 15. Multi-class communication — why the matrix exists

| Stage | Verdict |
|---|---|
| Intent validity | **YES** — multiple classes are declarable and coherent |
| logical message artifact | **YES** |
| physical propagation | **YES** |
| VC assignment | **YES** — class→VC map is real |
| verification | **YES** — class-VC CDG is checked |
| backend projection | **NO** |
| execution | **NO** |
| qualification | **NO** — native profiles require one class (`COND-SINGLE-COMM-CLASS`) |
| evidence | **NO** |

**Blocked by COMM-D1** (multi-class logical-message/physical-propagation debt).
**Never globally "supported" or "unsupported".**

## 16. Mesh capability

Three separate rows, never flattened:

```text
FAB-001 mesh                    → QUALIFIED under CAP-ENV-BOOKSIM-MESH-DOR-XY-V1
FAB-002 concentrated mesh       → valid canonical fabric; NOT covered by the
                                  mesh-DOR envelope (QUAL NO)
EVAL-001 native qualified mesh  → CERTIFIED_BOOKSIM_MESH_DOR_XY_V1
```

**Naming law (Gate 3 §7):** scientific name **`side_length`** (square-grid side
`k`); implementation field **`NocConfig.radix`**; `params["k"]` is derived; the
alias exists only at the boundary. **No schema migration.**

## 17. Torus capability

```text
FAB-003 torus topology        DECL YES · DERIV YES · VERIF YES ·
                              PROJ NO · wiring INSPECT_ONLY
FAB-004 torus routed execution DERIV NO · wiring NOT_AVAILABLE
ROUTE-004 torus routing       DERIV NO — UNSUPPORTED_SEMANTICS
```

**Dependency chain (§39):**

```text
TorusIntent
  → TopologyArtifact PASS
  → Route generator MISSING            ← the single blocking stage
  → PROJECTABLE / EXECUTABLE / QUALIFIED / EVIDENCE NOT REACHED
```

**Claim string:** *"Topology construction available; routed execution not
available."* Product **may** inspect topology; it **must not** offer a runnable
torus experiment.

## 18. AnyNet — two separate capabilities

```text
ROUTE-002 AnyNet canonical route algorithm   DERIV YES · compiler-owned
ROUTE-003 AnyNet backend projection          PROJ YES · backend-owned
```

**Neither is user intent.** There is **no AnyNet checkbox**. Both are covered by
`CAP-ENV-BOOKSIM-ANYNET-V1`, which is **not interchangeable** with the mesh-DOR
profile (C14).

## 19. VC capabilities — five separate rows

```text
ROUTE-005 derived VC count + class→VC map   DERIV YES · INSPECT_ONLY
            cross-class transitions          part of the same artifact
ROUTE-006 deadlock / channel-VC CDG          VERIF YES · INSPECT_ONLY
ROUTE-008 escape VC designation              DERIV YES · PROJ NO (supported-but-unused)
            backend materialization          NO
```

**Never "VCs supported".** `VCResourceArtifact.identity_dict` excludes
`derivation` by explicit design — the artifact is a **relation**; its
context-bound wrapper is `RouterBehaviorArtifact`.

## 20. Multiple clock domains

```text
SYS-003 multiple DECLARED clock domains
        DECL YES · DERIV YES · PROJ NO · reason NO_BACKEND_PROJECTION
SYS-004 multi-clock FABRIC EXECUTION
        DERIV NO
COND-SINGLE-CLOCK-FABRIC is a coherence law (SYSTEM domain)
```

**Declaration is valid; execution is unsupported.** There is **no
clock-crossing artifact.** (C2: the stages genuinely diverge.)

## 21. Concentration > 1

```text
FABRIC DECLARABLE   YES
TOPOLOGY DERIVABLE  YES
canonical fabric    VALID
mesh-DOR envelope   NOT QUALIFIED      ← COND-TOPOLOGY-MESH + concentration==1
AnyNet envelope     CONDITIONAL (projectable/executable if the canonical route
                    exists and the config audit closes)
evidence tier       depends on the envelope actually used
```

**Failure is `NOT QUALIFIED FOR THAT ENVELOPE`, never an invalid design.** No
silent substitution to a different profile (C11, C14).

## 22. Ramulator — exact staged row

```text
engine implementation    AVAILABLE              (EXECUTABLE YES)
profile                  QUALIFIED within the fixed v1 envelope
                         (CAP-ENV-RAMULATOR-V1)
canonical WorkloadV4→Ramulator bridge   UNAVAILABLE
serving→Ramulator bridge                UNAVAILABLE
network coupling                        UNAVAILABLE
product wiring                          UNAVAILABLE (ENGINE_ONLY)
DECLARABLE               NO   (not design intent)
VERIFIABLE               NO   (no canonical verifier reasons about it)
```

**Claim:** *standalone DRAM-cycle timing simulation over a recorded
legacy-derived request stream.* **Never** NoC-inclusive memory latency, and
**never** summed with BookSim latency (C20).

## 23. Static Product Evaluation — exact scope

```text
intent validity        YES
compile                YES  (FabricCompiler; INVALID/UNSUPPORTED fail first)
canonical certificate  YES  (channel-VC CDG, route legality/termination)
backend evaluation     CONDITIONAL — one named static envelope
metric evidence        CONDITIONAL — registered metrics over verified claims
```

**Exclusion conditions:** multi-class lowering · static MoE · multi-clock fabric ·
torus routing · hardware multicast · unqualified concentration under mesh-DOR ·
metric not in `CERTIFIED_METRIC_REGISTRY`.

**Certificate precedes qualification.** A certificate failure means no backend
number can become admissible science (C12).

## 24. Serving Evaluation — boundary in claim scope

```text
LLMServingSim owns:  request arrivals · queues · scheduling · batching ·
                     prefill/decode · instances · request metrics
VERITX owns:         fabric/network execution (ASTRA + qualified serving profile)
```

`simulation/serve_canonical.py:13` — *"LLMServingSim remains the service-semantics
authority (instances, …)"*. The `python -m serving` path lets LLMServingSim own
the network; the canonical path does not.

**A serving metric and a static metric are comparable only if `MetricId`,
producer, `semantics_version` and population all agree** — which today they do
not.

## 25. ASTRA capability

```text
role            drives serving-round network execution against a qualified
                machine projection built from canonical artifacts only
qualification   AstraServingRoundQualification predicates (COND-SERVING-ROUND-QUALIFIED)
evidence tier   qualified serving-round evidence
```

**ASTRA execution ≠ hardware-latency truth.** ASTRA owns *network execution under
a qualified projection*, not silicon timing. `qualify_astra_machine` refuses any
input that is not canonical (`backend/astra_machine.py:664-682`).

## 26. Native BookSim — exact profiles

```text
CAP-ENV-BOOKSIM-MESH-DOR-XY-V1   CERTIFIED_BOOKSIM_MESH_DOR_XY_V1
CAP-ENV-BOOKSIM-ANYNET-V1        CERTIFIED_BOOKSIM_ANYNET_V1
CAP-ENV-BOOKSIM-SERVING-V1       CERTIFIED_SERVING_BOOKSIM2_V1
```

Each carries a **semantics version** and a **closed-world config audit**. The
claim is scoped per profile; **two profiles are never merged into one "BookSim
qualified" state** (C14).

## 27. Generic BookSim / AnyNet vs native

**Both are executable and qualified — under different profiles with different
semantics versions.** They are **not scientifically interchangeable**: the
mesh-DOR profile carries `booksim2-fork+P1B-meshdor-dump`; the AnyNet profile
carries `booksim2-fork+B3.7b-anynet-dump`.

`backend/qualification.py:1-18` computes **two claims and never conflates them**:

```text
AUTHORITY AGREEMENT    two targets claim EXACT/DERIVED_EXACT and bind the SAME
                       authoritative source identity. Does NOT prove encodings agree.
PROJECTION EQUIVALENCE for targets sharing one canonical lowerer, fabric-derived
                       backend parameters must be byte-equal after projecting out
                       target-specific execution fields. The stronger claim.
```

And explicitly: *"does NOT impose latency equality across heterogeneous backend
families."*

## 28. First-hop vs full-path

```text
EVAL-008 CANONICAL FULL ROUTE DERIVATION + legality/termination
         DERIV YES · VERIF YES · EVIDENCE NOT_APPLICABLE (it is a DERIVED state)
EVAL-007 BACKEND FIRST-HOP OBSERVATION
         EVIDENCE_CAPABLE YES under a supported path
EVAL-006 BACKEND FULL-PATH OBSERVATION
         NO — NO_EVIDENCE_CONTRACT
```

**This distinction is product-source truth.** A canonical derivation is never
labelled an observation (§27 of Gate 3; C6).

## 29. Requirements

```text
target    WholeNetworkEvaluationTarget ONLY
metrics   network_completion_cycles · network_completion_ns
```

| Row | Verdict |
|---|---|
| REQ-001 cycles | DECL YES · EVID YES · ns/cycles law applies |
| REQ-002 ns | DECL YES · EVID YES · **invalidated by a clock change** |
| REQ-003 bandwidth | **NO** — NO_CONTRACT |
| REQ-004 class target | **NO** — NO_CONTRACT |
| REQ-005 memory target | **NO** — NO_EVIDENCE_CONTRACT |
| REQ-006 serving / operation / group targets | **NO** — NO_CONTRACT |

**Requirement evaluation itself is supported over admissible evidence.**

## 30. Optimization — decomposed

```text
OPT-001 guided optimizer        WIRED · 8 typed GUIDED NocConfig dimensions
OPT-002 expert typed design space WIRED · same OptimizationDefinition contract
OPT-003 multi-objective Pareto  WIRED · backend-authoritative exact dominance
OPT-004 requirement reporting   WIRED · orthogonal annotation (Gate-3 law B)
OPT-005 serving optimization    NOT_AVAILABLE · FUTURE_CONTRACT
OPT-006 memory optimization     NOT_AVAILABLE · NO_EVIDENCE_CONTRACT
OPT-007 evidence reuse / cache  NOT_AVAILABLE · IMPLEMENTATION_GAP
OPT-008 candidate promotion     NOT_AVAILABLE · PRODUCT_NOT_WIRED
```

**Locked derived properties are inexpressible** (routing, VC count/structure,
turn restrictions, escape VC). **One backend/profile per study.** **Frozen metric
registry.** Studio reads `pareto_member`/`pareto_eligible` and never recomputes.

**Never "Optimizer supported" as one row.**

### 30.1 Optimization claim scope (largest honest claim)

```text
SROTA can search a typed finite design space over supported dimensions, compile
and evaluate candidates through the canonical pipeline, and compute a
scientifically admissible Pareto set over compatible certified metrics.
```

**Cannot claim:** globally optimal interconnect · hardware-optimal design ·
complete exploration of arbitrary architecture space.

### 30.2 Candidate promotion

**NOT product-wired.** A `selected_candidate_id` exists; promotion into a new
design revision is **not** implemented. **Do not infer from a selected candidate
that promotion exists** (C5).

## 31. Evidence tiers

| Tier | Definition | Source |
|---|---|---|
| `CANONICAL_DERIVED` | compiler-derived expectation; never an observation | RouteArtifact, ResolvedRoute, CDG |
| `CERTIFICATE` | canonical verifier verdict over correctness obligations | FabricCompiler certificate |
| `QUALIFIED_BACKEND_SIMULATION` | authenticated execution under a named profile | BookSim/ASTRA + evidence chain |
| `FIRST_HOP_OBSERVED` | runtime routing-function/table equivalence over the full src×dst domain | `route_observation.py` |
| `TEST_INJECTED` | fixture-provided observation | tests |
| `ANALYTIC_FAKE` | deterministic placeholder; **structurally never Pareto-eligible** | `evaluators.py` |
| `LEGACY` | Phase-9-derived input authority | memory lowering |

**UI must not invent labels such as "High Confidence"** without an exact mapping
to this table.

## 32. "Experimental" terminology

**Not used.** `EXPERIMENTAL` is not a result value, not a reason code and not a
product state. Where it would be tempting:

| Tempting use | Exact replacement |
|---|---|
| "experimental routing" | `ROUTE-004 torus routing: DERIV NO, NO_DERIVATION` |
| "experimental backend" | `ENGINE_ONLY` + `PRODUCT_NOT_WIRED` |
| "experimental multicast" | `COMM-005: FUTURE_CONTRACT` |
| "partially supported" | the exact stage that is `NO` + its reason code |

**No escape hatch.**

## 33. Capability combinations — named envelopes

A capability may depend on a **combination**, not a feature. Condition sets are
**named**, never free prose:

```text
CAP-ENV-BOOKSIM-MESH-DOR-XY-V1
  mesh + DOR-XY + single class + identity VC transitions + single clock
  + dense static workload + closed config audit

CAP-ENV-BOOKSIM-ANYNET-V1
  canonical route present + single class + single clock + dense static
  + closed config audit

CAP-ENV-BOOKSIM-SERVING-V1
  serving round qualified + closed config audit

CAP-ENV-RAMULATOR-V1
  HBM3 + HBM34 + sequential_bankstriped_v1 + clock_ratio 4/1
```

## 34. Static / serving capability split

| | Static | Serving |
|---|---|---|
| entry | canonical workload graph | request trace |
| scheduling | none | LLMServingSim |
| backend | BookSim (static profiles) | ASTRA + serving profile |
| MoE | **NO** | **YES** |
| metrics | network completion cycles/ns | serving + network |

**PRODUCT must never display a serving result as a static result or vice versa.**

## 35. Legacy-only and future-contract distinctions

**LEGACY_ONLY:**

| Capability | Why |
|---|---|
| MEM-006 REMOTE / CXL / STORAGE | grammar tokens refused at lowering |
| MEM-007 PIM | `KIND_PIM_*` markers only |
| Phase-9 operand bytes + location grammar | consumed only by the unwired memory chain |

**FUTURE_CONTRACT (no accepted semantics):**

hardware multicast · multiplane · adaptive routing · valiant · RCU/in-network
reduction · network+memory coupled timing · serving optimization · custom /
hierarchical topology.

**IMPLEMENTATION_GAP (accepted target, unfinished):**

multi-class propagation (COMM-D1) · static MoE lowering · escape-VC backend
materialization · evidence reuse/cache · candidate promotion.

## 36. Claim-conflict ledger

Current wording audited against Gate-4 truth. **Copy is not fixed here.**

| # | Surface | Current wording | Why inaccurate | Approved replacement |
|---|---|---|---|---|
| CC-1 | `pages/index.tsx:747`, `:455` | `SUPPORTED` / `NOT SUPPORTED` (single boolean) | collapses 8 independent stages into one bit | "Check the capability registry for the exact stage." UI must render the stage table, not a boolean |
| CC-2 | `pages/index.tsx:327` | "Compile the fabric, prove its obligations, execute **supported communication**" | "supported communication" is undefined; multi-class is not executable | "Compile the fabric, prove its obligations, and evaluate under a named qualification profile." |
| CC-3 | `cli/cli.py:1502` | `certify full` — "Full certification" | "full" implies universal scope; certification is per-envelope | "Certify under a named profile envelope." |
| CC-4 | `types.ts:155`, `:222` | `UNSUPPORTED` shared by compilation and evaluation | two different cross-domain classes share one token | keep the token, but Product must render the **reason code** (`NO_DERIVATION` vs `NOT_QUALIFIED`) |
| CC-5 | `EvaluateView.tsx:9` | "…/ BACKEND_UNAVAILABLE / EVALUATED / FAILED / UNSUPPORTED" | correct vocabulary, but not mapped to stages | map to the stage table |
| CC-6 | legacy CLI `synthesize bo/grid/iterative`, `sweep`, `baseline` | presented alongside canonical commands | HISTORICAL, not part of the canonical study contract | mark deprecated; do not surface as capability |
| CC-7 | any surface implying Ramulator is integrated | (no current instance found) | would be false | "Memory simulation engine available; not connected to the current product workflow." |
| CC-8 | any surface implying torus is runnable | (no current instance found) | route generator missing | "Topology construction available; routed execution not available." |

**CC-1 is a real, current inaccuracy and the single strongest justification for
this gate.**

## 37. Approved user-visible claim strings

```text
TORUS
  "Topology construction available; routed execution not available."

RAMULATOR
  "Memory simulation engine available; not connected to the current product
   workflow."

ROUTE EVIDENCE
  "Canonical route verified; backend first hop observed over the full
   source/destination domain."

MULTICAST
  "Semantic multicast lowers to unicasts; hardware multicast is not modeled."

MULTI-CLASS
  "Multiple communication classes are declarable; execution requires a single
   class under the current qualified profiles."

MULTI-CLOCK
  "Multiple clock domains can be declared; fabric execution across them is not
   supported."

STATIC MoE
  "MoE semantics are declarable; static MoE evaluation is not available."

CONCENTRATION > 1
  "Valid canonical fabric; not qualified under the mesh DOR-XY profile."

OPTIMIZATION
  "Typed design-space search with certified metric-based Pareto computation."
```

**Claim strings only — no card, colour, icon, page or tooltip decisions.**

## 38. Forbidden claim strings

Product **must not** say:

```text
"Full route verified by BookSim"
"Ramulator integrated end-to-end"
"Torus supported"
"Multicast supported"
"Multi-clock fabric supported"
"Static MoE fully supported"
"Hardware-accurate latency"
"Optimal NoC"
"VCs supported"
"AnyNet supported"
"High confidence"
"Partially supported"
"Experimental routing/backend/multicast"
"BookSim qualified"          (without naming the profile)
"Memory latency"             (without "standalone, recorded stream")
```

unless the qualified wording in §37 makes them true.

## 39. Capability dependency examples

```text
TORUS ROUTED EXECUTION
  TorusIntent → TopologyArtifact PASS → Route generator MISSING
  → PROJECTABLE NOT REACHED

MULTI-CLASS EXECUTION
  CommunicationIntent (multi) → logical messages PASS → physical propagation
  PASS → VC assignment PASS → CDG PASS → backend projection BLOCKED
  (COND-SINGLE-COMM-CLASS) → EXECUTABLE NOT REACHED

RAMULATOR PRODUCT WORKFLOW
  MemoryLoweringManifest PASS → Ramulator execution PASS → MemoryEvidence PASS
  → product entry point MISSING → PRODUCT_WIRED NOT REACHED

STATIC MoE
  MoE semantics PASS → static dispatch/combine lowering MISSING
  → everything downstream NOT REACHED
```

**Limitations are actionable: each names the single blocking stage.**

## 40. Machine-readable registry decision

**Decision: a SEPARATE file — `docs/product/capability-registry.yaml`.**

**Why not the ontology:** the ontology answers *"what may the Design page
render?"* and is validated by `check_intent_ontology.py` against
`DesignEditor.tsx` field paths. Capabilities answer *"what can the system do?"* —
a different concern, a different vocabulary and a different checker. Overloading
the ontology would create one file with two validation contracts and would force
capability rows to satisfy the ten-answer node schema, which they cannot.

**Ownership:** `docs/product/capability-registry.yaml` is owned by the capability
model, versioned by `capability_semantics_version: cap-v1`. **Product claims must
correspond to a known registry version.**

**No duplicate manually drifting truth:** the registry **derives** from Gate-2/3
documents and cites the code constants it encodes (`backend/meshdor_profile.py:54`,
`backend/booksim_profile.py:33`, `simulation/ramulator.py:54`, …). Where a code
constant exists, the registry **names** it rather than restating its value.

## 41. Checker requirements

A future `scripts/check_capability_registry.py` must enforce:

```text
1. every capability has a capability_id, scientific_name and domain_owner
2. domain_owner is one of the eleven closed domains
3. every stage value is in the result vocabulary
4. every CONDITIONAL stage references a known condition or envelope ID
5. every referenced condition/envelope ID exists
6. every non-YES stage carries a reason code from the taxonomy
7. every capability with PRODUCT_WIRED != NOT_AVAILABLE has at least one
   scientific stage that is YES or CONDITIONAL
8. no capability is QUALIFIED without a named profile/envelope
9. every evidence claim references an evidence tier
10. LEGACY_ONLY and FUTURE_CONTRACT rows carry no QUALIFIED=YES
11. capability_semantics_version is present
```

**Not implemented in this gate** (recorded as debt, §47).

## 42. Adversarial verdicts C1–C20

| # | Case | Verdict |
|---|---|---|
| C1 | enum value exists but no consumer | **must not** become DECLARABLE=YES automatically. Example: `mcast_groups` is DECLARABLE because intent accepts it; hardware multicast is **DECL NO** |
| C2 | schema accepts it but the verifier cannot reason | stages diverge — SYS-003 (DECL YES, PROJ NO) |
| C3 | backend can execute raw config but no qualification exists | EXECUTABLE YES, **QUALIFIED NO** |
| C4 | qualified engine exists but no product caller | **PRODUCT_WIRED NO** — MEM-002 `ENGINE_ONLY` |
| C5 | UI control exists but canonical contract absent | product surface is **wrong**; capability remains unavailable (promotion, OPT-008) |
| C6 | canonical route fully derives, backend observes first hop only | **separate rows** EVAL-007 / EVAL-008 |
| C7 | serving capability exists, static equivalent absent | **no inheritance** — WORK-004 vs WORK-002 |
| C8 | legacy adapter supports a field absent from v4 | **LEGACY_ONLY** — MEM-006/007 |
| C9 | implementation debt blocks an accepted target | mark the stage `NO` with **`IMPLEMENTATION_GAP`**, not FUTURE_CONTRACT |
| C10 | future contract with no accepted semantics | **`FUTURE_CONTRACT`** |
| C11 | qualification profile fails one predicate | design remains **valid**; failure = `NOT QUALIFIED FOR THAT ENVELOPE` |
| C12 | certificate fails | qualified evidence **cannot** become admissible science |
| C13 | product action yields an unauthenticated number | **not evidence-capable product science** |
| C14 | two backends expose the same metric name with incompatible semantics | **no shared claim** without registry compatibility — mesh-DOR vs AnyNet profiles |
| C15 | optimizer can generate a candidate field whose capability is FUTURE_CONTRACT | definition construction **must refuse** (locked-token law) |
| C16 | status changes only due to UI work | scientific stages **unchanged**; `PRODUCT_WIRED` changes |
| C17 | backend added without canonical projection | EXECUTABLE **cannot leap over** PROJECTABLE |
| C18 | verifier added without derivation | VERIFIABLE does **not** imply executable |
| C19 | hardware multicast mistaken for semantic fanout | **forbidden** — COMM-004 vs COMM-005 |
| C20 | Ramulator + BookSim mistaken for coupled timing | **forbidden** — MEM-005 |

**Capability-specific additions:**

| # | Case | Verdict |
|---|---|---|
| C21 | `side_length` and `radix` both offered as inputs | **forbidden** — one field, one name law (Gate 3 §7) |
| C22 | torus topology offered as a runnable experiment | **forbidden** — FAB-003 `INSPECT_ONLY` |
| C23 | "BookSim qualified" without a profile | **forbidden** — three distinct profiles |
| C24 | requirement violated but candidate dominates | stays on the frontier, annotated (Gate 3 §8) |
| C25 | ns metric reused after a clock change | **forbidden** — cycles reusable, ns not |
| C26 | an `ANALYTIC_FAKE` number displayed as a measurement | **forbidden** — never Pareto-eligible |

## 43. Implementation debt discovered by Gate 4

```text
CAP-D1  write scripts/check_capability_registry.py enforcing the 11 invariants (§41)
CAP-D2  Studio must render the stage table, not `intervention.supported` (CC-1)
CAP-D3  extend the field-ownership matrix with the SEMANTIC_LOSS class and
        reconcile it with ParameterOwner / RepresentationStatus (XDOM-D8)
CAP-D4  map existing UNSUPPORTED tokens to cross-domain reason codes in product copy (CC-4)
CAP-D5  add `capability_semantics_version` to any product claim surface
```

**Referenced, not duplicated:** XDOM-D1…D7, FAB-D1/D4/D6, VC-D1, COMM-D1,
ROUTER-D2, OPT-D2…D8, MEM-D1…D5, MEM-EVAL-D1/D2.

## 44. Coherence check against §51

| # | Criterion | Status |
|---|---|---|
| 1 | one stage vocabulary | **MET** (§1, reconciled with Gate 3 §14) |
| 2 | no capability is one ambiguous boolean | **MET** (§2, §9) |
| 3 | product wiring distinct from engine/scientific support | **MET** (§5, §7) |
| 4 | canonical validity distinct from backend qualification | **MET** (§22, C11) |
| 5 | evidence claim scope explicit | **MET** (§4, §31) |
| 6 | static and serving separate | **MET** (§34) |
| 7 | static and serving MoE separate | **MET** (§11, §12) |
| 8 | semantic vs hardware multicast separate | **MET** (§14) |
| 9 | torus topology vs execution separate | **MET** (§17) |
| 10 | multi-class stages exact | **MET** (§15) |
| 11 | clock declaration vs execution exact | **MET** (§20) |
| 12 | Ramulator not overclaimed | **MET** (§22) |
| 13 | network+memory coupling explicitly unavailable | **MET** (§22, MEM-005) |
| 14 | route derivation vs backend observation explicit | **MET** (§28) |
| 15 | Requirement target/metric capability exact | **MET** (§29) |
| 16 | optimizer capabilities decomposed | **MET** (§30) |
| 17 | future contracts not called implementation debt | **MET** (§35, §6) |
| 18 | legacy-only identified | **MET** (§35) |
| 19 | important current product claims audited | **MET** (§36) |
| 20 | each inaccurate claim has replacement wording | **MET** (§36, §37) |
| 21 | conditions/envelopes named | **MET** (§8, §33) |
| 22 | capability ownership unambiguous | **MET** (§4, registry `domain_owner`) |
| 23 | product-flow architecture not begun | **MET** |
| 24 | HTML not begun | **MET** |

## 45. Remaining blockers

**None for Gate-4 coherence.** The registry encodes truth; the only *current*
inaccuracy is CC-1 in Studio, which is **product copy** and is recorded as
`CAP-D2`, not fixed here.

## 46. Domain verdict

The matrix exists because a single boolean lies.

`apps/studio/src/pages/index.tsx:747` renders
`intervention.supported ? 'SUPPORTED' : 'NOT SUPPORTED'` for a fact that is
genuinely eight independent stages. This gate replaces that with a vocabulary
whose whole purpose is to make the honest answer expressible: **`TORUS` is
declarable and derivable and unroutable. `RAMULATOR` is executable and qualified
and product-unwired. `CONCENTRATION > 1` is a valid canonical fabric that is not
qualified under the mesh DOR-XY profile.** None of those is a yes or a no.

Three corrections came out of reading the code rather than the brief. There are
**three** certified BookSim profiles, not one — `CERTIFIED_BOOKSIM_MESH_DOR_XY_V1`,
`CERTIFIED_BOOKSIM_ANYNET_V1` and `CERTIFIED_SERVING_BOOKSIM2_V1` — each with its
own semantics version, so **"BookSim qualified" is not a claim** and the two
static profiles are not interchangeable. The **first-hop observation** is
stronger than Gate 3 implied: it proves *runtime routing-function/table
equivalence to the canonical route over the complete source × destination
domain*, not one hop of one packet. And the repository already has an **enforced
backend-parameter ownership taxonomy** (`ParameterOwner`) plus a per-dimension
representability contract (`RepresentationStatus`) that gives **PROJECTABLE** real
teeth — and contributes one class Gate 3's matrix lacked, `SEMANTIC_LOSS`.

The claim-scope model is where this gate earns its keep. Stages say *how far* a
capability goes; scope says *what may be said*. A canonical route is a **derived
expected state** and may never be labelled an observation. Ramulator's claim is
explicitly *standalone DRAM timing over a recorded stream* and never
NoC-inclusive latency. Optimization's largest honest claim is a **typed finite
design-space search with certified metric-based Pareto computation** — never a
globally optimal interconnect.

The forbidden-claim list is the product-integrity artefact: *"Full route verified
by BookSim"*, *"Ramulator integrated end-to-end"*, *"Torus supported"*,
*"Multicast supported"*, *"Hardware-accurate latency"*, *"Optimal NoC"*, and
`EXPERIMENTAL` as an escape hatch — all barred, each with approved replacement
wording. Failures are typed: `IMPLEMENTATION_GAP` for accepted-but-unfinished
targets, `FUTURE_CONTRACT` for capabilities with no accepted semantics at all,
`LEGACY_ONLY` for what survives only through Phase-9 adapters.

**GATE 4 — CAPABILITY MATRIX: PLANNED — COHERENT**

Gate 5 not begun. No product-flow architecture. No wireframes. No HTML.
