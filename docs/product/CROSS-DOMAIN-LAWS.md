# CROSS-DOMAIN LAWS — Gate 3

Authority: `intent-ontology.yaml` + `scripts/check_intent_ontology.py`
Upstream: the eleven Gate-2 domain documents in `docs/product/`
Status: **PLANNED — COHERENT.** See §50.

---

## 0. The D1–D8 registry — recovered verbatim

**D1–D8 are NOT cross-domain scientific decisions.** They are Gate-1
**product-surface decisions** recorded in `docs/product/INTENT-ONTOLOGY.md` §5
(*"Open decisions (block Gate 2/3)"*). The Gate-3 brief assumed they were
cross-domain laws; the repository says otherwise. This is the pass's first and
largest correction.

Verbatim titles and bodies (`INTENT-ONTOLOGY.md:445-478`):

| Decision | Exact repository wording | Domains involved | Why unresolved |
|---|---|---|---|
| **D1** | *"Which declared layer is the page's subject?* *(blocking)* (a) edit `CompileIntent` (preset + overrides + policy), matching product identity and `intent_id`; or (b) edit explicit `CompileRequestV3` with `CompileIntent` as a named-preset shortcut, defining how `intent_id` is derived. The ontology has two roots; the page must have one." | product root vs compiler root | two roots exist (`roots: product: CompileIntent`, `compiler: CompileRequestV3`); the draft path bypasses `CompileIntent` |
| **D2** | *"Placement intent:* keep placement entirely derived (`MappingArtifact` + `MappingPolicy`), or create a declared affinity/placement contract. Today it is derived; `MappingPolicy` is 'owned by candidate generation'." | SYSTEM, PARALLELISM, PLACEMENT | a *scientific* ownership question — Gate 3 owns it |
| **D3** | *"Design-space intent:* pull `OptimizationDefinition` under Design/Intent, or keep the Optimize page as its sole owner." | DESIGN-SPACE, all | a *scientific* ownership question — Gate 3 owns it |
| **D4** | *"NOT-MODELLED domains* (§2 items): explicitly out of scope for this redesign, or new contracts? Each 'new' converts this from a UI redesign into a compiler + contract redesign." | all | a *scope* question — Gate 3 owns it |
| **D5** | *"Contract widening:* confirm `DesignView` v2 must carry `collectives`, `dependencies`, `address_map`, `physical`, and the product layer, so the UI stops hand-mirroring `compile_model.py`." | PRODUCT | **view schema** — product-flow gate |
| **D6** | *"Early validation:* move the two doc-computable coherence checks into the form (`rank_count ≤ compute_instances`; `traffic_class ∈ derive_v3_traffic_classes`)? Both need no compiler." | SYSTEM, COMMUNICATION, PRODUCT | **form timing** — product-flow gate |
| **D7** | *"Per-type classification sentinel:* require every declared type (`WorkloadV3`, `RequirementV3`, `Agent`, `PhysicalContext`) to publish a reality/kind classification with a fail-closed sentinel, as `NocConfig` already does?" | compiler completeness | Gate 3 owns the *law*; the change is a compiler change |
| **D8** | *"Visual primitive set:* freeze the six primitives of §2.12 as the closed vocabulary for Gates 2–6, and forbid per-node hand-authored primitives (`.rcu-refusal`, `.locked-grid`)?" | PRODUCT | **visual vocabulary** — wireframe gate |

**Registry defect found.** `intent-ontology.yaml` carries
`pending_decisions: [D1, D2, D3, D4, D5, D6, D7, D8]` with **no definitions**,
while the authoritative wording lives only in the Markdown. The machine authority
was silent about what it was blocking. This pass writes the definitions into the
ontology so the registry is self-describing (§48).

**Disagreement check:** the ontology and the doc do **not** contradict each other
— the ontology merely omits the definitions. One authority wins by **addition**,
not by override.

---

## 1. Frozen contracts

All eleven Gate-2 documents are treated as upstream contracts. **No ownership,
identity, namespace, intent/derived boundary, capability state or evidence claim
was altered to make a cross-domain law easier.**

One genuine cross-domain **contradiction** was found and is corrected here:
Domain G (FABRIC) and Domain J (DESIGN-SPACE) made **contradictory statements
about the same field name** (§7). That is the only `CROSS-DOMAIN CORRECTION`.

---

## 2. D1–D8 decisions

Format per §43. **Every decision is made; nothing is "recommended".**

### D1 — Which declared layer is the page's subject?

**Current conflict:** the ontology has two roots (`CompileIntent`,
`CompileRequestV3`); `product/service.py:670` bypasses `CompileIntent` entirely
and hardcodes `BASELINE_FABRIC_SETTINGS` inline (`orchestration.py:123`), so the
product layer is duplicated rather than dispatched.

**Evidence:** `intent-ontology.yaml:30-32`; `INTENT-ONTOLOGY.md:449-453`;
`orchestration.py:123`; `product/service.py:670`.

**Options:** A — page edits `CompileIntent`; B — page edits `CompileRequestV3`
with `CompileIntent` as a named preset.

**Chosen law (scientific half, Gate 3 owns):**
`CompileRequestV3` is the **canonical design identity**; `design_hash` is derived
from it. `CompileIntent` is a **named-preset authoring surface** in a **separate
identity namespace** (`intent_id`). **`intent_id` and `design_hash` are never
conflated**, and an `intent_id` never substitutes for a `design_hash` in any
downstream parent link.

**Deferred half:** *which* layer the page edits is a product-surface decision with
no scientific content. **Re-homed to the product-flow gate.**

**Why:** the two roots carry different identities. Resolving the identity law is
scientific; choosing the page subject is not. Gate 3 must not do product-flow
work.

**Identity consequence:** two namespaces remain distinct; `intent_id` may never be
used as a `base_design_hash`.

**Invalidation/reuse:** unchanged — nothing downstream keys on `intent_id`.

**Migration:** none. **Product consequence:** deferred. **Debt:** none.

**Affected docs:** `INTENT-ONTOLOGY.md` §5. **Ontology resolution:** RESOLVED
(identity law); page-subject half re-homed.

### D2 — Placement intent

**Current conflict:** placement is entirely derived today, but `MappingPolicy` is
described as *"owned by candidate generation"* — which would make a compiler
policy a candidate-owned value.

**Evidence:** `compiler/candidate_policy.py:144` (`RANK_ORDER_V1 = "rank_order_v1"`),
`:308` (`mapping_policy=MappingPolicy.RANK_ORDER_V1`); `model/mapping.py:135`
(`canonical_dict`).

**Options:** A — placement stays derived; B — a declared affinity contract.

**Chosen law: A. Placement stays entirely derived. No declared
affinity/anti-affinity/locality/co-location/fixed-placement/reserved-resource/
mapping-objective contract exists in v4.**

**Why:** no declared affinity entity exists (`INTENT-ONTOLOGY.md:156`); the
mapping is a deterministic function of PhysicalInventory + ParallelismIntent +
`MappingPolicy`. Adding a declared contract would convert a UI redesign into a
compiler + contract redesign with no scientific driver.

**Identity consequence:** `MappingArtifact` is `R3` derived. `MappingPolicy` is
**compiler-owned**, not candidate-owned — the Gate-1 phrasing is corrected here
(see §7's sibling correction).

**Invalidation/reuse:** a policy change changes the derived relation →
`MappingArtifact` changes; intents do not.

**Migration:** none. **Product consequence:** no placement control exists.

**Debt:** the policy is **not bound into `MappingArtifact` identity** — recorded as
**XDOM-D1** (§29, §47). **Ontology resolution:** RESOLVED.

### D3 — Design-space intent

**Current conflict:** `OptimizationDefinition` could be pulled under Design/Intent
or remain the Optimize page's sole owner.

**Evidence:** `optimization/definition.py:156`; `INTENT-DESIGN-SPACE.md` §1, §4;
`optimization/result.py:699`.

**Options:** A — pull under Design/Intent; B — Optimize owns it.

**Chosen law: B, with a precise boundary.** `OptimizationDefinition` is a
**Study Definition that sits ABOVE the design**. It is **never** part of
`CompileRequestV3`, **never** enters `design_hash`, and is **not** Design Intent.
Its dimensions *reference* design fields; they are not design fields.

**Why:** the optimizer proposes; canonical compilation decides
(`INTENT-DESIGN-SPACE.md` §1). Folding the study definition into Design Intent
would let an experiment configuration mutate the scientific design identity.

**Identity consequence:** `definition_id` and `design_hash` are disjoint
namespaces. A candidate's `candidate_id` binds **both** (`base_design_hash` +
patch) — that is the one legitimate composition.

**Invalidation/reuse:** study changes never invalidate `design_hash`; they
invalidate candidate identity only.

**Migration:** none. **Product consequence:** the Optimize surface owns the study;
the Design surface shows only the address/design fields.

**Debt:** none. **Ontology resolution:** RESOLVED.

### D4 — NOT-MODELLED domains

**Current conflict:** each NOT-MODELLED concept could become a new contract or
stay out of scope.

**Evidence:** `INTENT-ONTOLOGY.md` §2 rows at `:95, 97, 107, 108, 109, 119, 145,
146, 156, 171, 183, 191, 210`.

**Options:** A — explicitly out of scope; B — new contracts.

**Chosen law: A. Every §2 NOT-MODELLED concept remains NOT-MODELLED in v4.**

| Concept | v4 verdict |
|---|---|
| Nodes / accelerators / chiplets | out of scope — `NodeInventory` derives nodes from counts |
| Resource domains (power/clock) | out of scope — per-`Agent` + `PhysicalContext` only |
| Operation graph | out of scope — collectives + dependencies are the declared substitutes |
| Phases | **explicitly refused as an inference from `serving_mode`** |
| Memory behaviour | out of scope — Domain I: no memory-behaviour entity |
| Group constraints | out of scope |
| Locality / isolation / reachability | out of scope — no requirement type |
| Reliability / qualification **as intent** | out of scope — producer qualification is execution-side |
| Affinity / anti-affinity / co-location / fixed placement / reserved resources / mapping objective | out of scope — D2 |
| Dimensions / hierarchy / planes / links / traffic-plane binding / topology constraints | out of scope — concrete dimensions and links are derived |
| Implementation constraints | out of scope |
| Memory domains / address spaces / locality / controller relationships / memory traffic classes | out of scope — only ranges exist (Domain I) |
| Fixed parameters | out of scope — "fixed" is implicit: anything absent from `domain` |

**Why:** each "new" converts a UI redesign into a compiler + contract redesign,
and **none has a scientific driver in the current repository**.

**Identity/invalidation/migration:** none — nothing is added.
**Product consequence:** these surfaces must not appear. **Debt:** none.
**Ontology resolution:** RESOLVED.

### D5 — Contract widening

**Current conflict:** `DesignView` v2 must carry `collectives`, `dependencies`,
`address_map`, `physical` and the product layer, or the UI keeps hand-mirroring
`compile_model.py`.

**Evidence:** `INTENT-ONTOLOGY.md:464-466`; the DECLARED rows of §2.12.

**Options:** A — widen `DesignView` v2; B — leave it narrow.

**Chosen law (scientific half, Gate 3 owns):** the **field-ownership matrix**
(§6) is the authority for *what may be projected*. A view may carry a field only
if that field appears in the matrix with a source-of-value class; a view may
**never** recompute a derived value.

**Deferred half:** the exact `DesignView` v2 schema is a **view-schema decision
with no scientific content**. **Re-homed to the product-flow gate.**

**Why:** Gate 3 can say which fields are projectable and under what authority; it
cannot say what the page shows without doing product-flow work.

**Identity consequence:** none — views are projections, never identities.

**Invalidation/reuse:** a view may be regenerated from existing artifacts at any
time. **Migration:** none. **Debt:** none.

**Ontology resolution:** RESOLVED (projection authority); schema half re-homed.

### D6 — Early validation

**Current conflict:** should the two doc-computable checks
(`rank_count ≤ compute_instances`, `traffic_class ∈ derive_v3_traffic_classes`)
move into the form?

**Evidence:** `INTENT-ONTOLOGY.md:467-469`, §5.1 (*"`mapping.py:181` and
`requirements.py:564` enforce document-local rules at compile/report"*).

**Options:** A — move into the form; B — leave at compile/report.

**Chosen law (scientific half, Gate 3 owns):** **validation authority stays at the
canonical stage that owns the rule.** A form-level pre-check is an **advisory
affordance only**; it is never the sole guard, never a second authority, and its
absence must not change the outcome. The two named checks are **compile-stage
(L3d)** and **report-stage (L5)** coherence laws respectively — they are
cross-domain joins (§21), not field-level parsing.

**Deferred half:** whether the form surfaces them early is a **UX-timing
decision**. **Re-homed to the Guided/Expert gate.**

**Why:** a duplicated check in the UI would create a second authority for a
cross-domain law, violating "no field has two editable authorities" in spirit.

**Identity consequence:** none. **Invalidation/reuse:** none. **Migration:** none.
**Debt:** none. **Ontology resolution:** RESOLVED (authority); UX half re-homed.

### D7 — Per-type classification sentinel

**Current conflict:** only `NocConfig` publishes a reality/kind classification with
a fail-closed sentinel (`check_noc_field_classification()`).

**Evidence:** `INTENT-ONTOLOGY.md:470-473`, §5.1 (*"`check_noc_field_classification()`
is the only completeness guard"*).

**Options:** A — require it for every declared type; B — leave `NocConfig` only.

**Chosen law: A. Every declared type must publish a reality/kind classification
with a fail-closed sentinel.** This is the mechanism that makes the §6
field-ownership matrix **enforceable rather than remembered**, and it is the
Gate-3 answer to "no field may have two editable authorities".

Required for: `WorkloadV3`, `RequirementV3`, `Agent`, `PhysicalContext`,
`AddressMap`, `AddressRange`, `DependencyGraph`, `Dependency`,
`CollectiveIntent`, `WorkloadSourceRef`, `CompileIntent`.

**Why:** a matrix that lives only in prose drifts. The repository already proved
the pattern works for `NocConfig`.

**Identity consequence:** none directly; it prevents unclassified fields from
entering identity. **Migration:** none. **Product consequence:** none.

**Debt:** the compiler change itself — **XDOM-D3** (§47).
**Ontology resolution:** RESOLVED.

### D8 — Visual primitive set

**Current conflict:** freeze the six primitives as the closed vocabulary, or allow
per-node hand-authored primitives.

**Evidence:** `INTENT-ONTOLOGY.md:474-477`, §5.1 (*"`.rcu-refusal` covers 1 of 10
refusals; `.locked-grid` covers 4 of ~12 derived objects"*).

**Options:** A — freeze six primitives; B — allow hand-authored primitives.

**Chosen law:** **Gate 3 has no scientific content for this decision.** The
ontology already carries the machine form: `visual ∈ {1..6}` is validated per node
by `check_intent_ontology.py` (`VISUAL = {1, 2, 3, 4, 5, 6}`), so the six-primitive
vocabulary is **already frozen mechanically**.

**Deferred:** the CSS/component realisation is a **wireframe-gate decision**.

**Why:** Gate 3 is explicitly forbidden from wireframes. Recording the mechanical
freeze and re-homing the rest is the honest resolution.

**Identity/invalidation/migration/debt:** none.
**Ontology resolution:** RESOLVED (mechanical freeze already enforced); styling
half re-homed.

---

## 3. Authority graph

Edges: `PRODUCES` `CONSUMES` `BINDS IDENTITY` `PROJECTS` `VALIDATES` `QUALIFIES`
`DOES NOT DEPEND`.

```text
USER INTENT (declared)
  CompileRequestV3 ──PRODUCES──> SYSTEM · WORKLOAD · PARALLELISM ·
                                 COMMUNICATION · REQUIREMENTS · PHYSICAL ·
                                 FABRIC(NocConfig) · MEMORY(AddressMap)
  OptimizationDefinition ──PRODUCES──> DESIGN SPACE (dimensions/objectives/
                                 constraints/evaluation policy)
        │
        └─ DOES NOT DEPEND on any derived artifact (it is above the pipeline)

COMPILER / DERIVATION
  SystemIntent ──PRODUCES──> PhysicalInventory ──PRODUCES──> LogicalParticipantInventory
  PhysicalInventory + ParallelismIntent ──PRODUCES──> MappingArtifact
  FabricIntent ──PRODUCES──> TopologyArtifact
  TopologyArtifact + PhysicalInventory ──PRODUCES──> AgentAttachmentArtifact
  AddressMap + AgentAttachmentArtifact ──PRODUCES──> AddressDecodeArtifact
  TopologyArtifact + RouterResourceIntent ──PRODUCES──> RouteArtifact
  RouteArtifact ──PRODUCES──> ResolvedRouteArtifact
  CommunicationIntent + TopologyArtifact ──PRODUCES──> VCAssignmentArtifact
  VCAssignmentArtifact + RouterResourceIntent ──PRODUCES──> RouterBehaviorArtifact
  FabricArtifact ──BINDS IDENTITY──> topology + attachment + address_decode +
                                     routes + resolved_routes + vc + router_behavior
  CommunicationIntent ──PRODUCES──> communication lowering ──PRODUCES──> physical traffic

VERIFICATION / QUALIFICATION
  FabricArtifact ──VALIDATES──> VerificationCertificate
  VerificationCertificate ──CONSUMES──> Channel-VC CDG
  BackendQualificationProfile ──QUALIFIES──> a candidate+backend pair
  QualificationResult ──CONSUMES──> BackendQualificationProfile
  AddressDecodeArtifact ──VALIDATES──> the design AddressMap (validate_against)

EXECUTION / EVIDENCE
  lowered workload + FabricArtifact ──CONSUMES──> ASTRA | BookSim | LLMServingSim
  MemoryLoweringManifest ──CONSUMES──> Ramulator  (DISCONNECTED from the above)
  any backend ──PRODUCES──> ExecutionAttempt ──PRODUCES──> ScientificBackendEvidence
  ScientificBackendEvidence ──PRODUCES──> MetricObservation
  Ramulator ──PRODUCES──> MemoryEvidence  (does NOT DEPEND on FabricArtifact)

PRODUCT / ANALYSIS
  MetricObservation + RequirementV3 ──PRODUCES──> RequirementReport
  OptimizationResult ──PROJECTS──> OptimizationStudyView
  OptimizationStudyView ──CONSUMES──> Pareto state ──CONSUMES──> candidate selection
```

**Explicit `DOES NOT DEPEND` edges (the domain's most important boundaries):**

| Edge | Why |
|---|---|
| `Ramulator` **does not depend** on `FabricArtifact` | standalone trace execution (Domain I §27) |
| `Ramulator` **does not depend** on `AddressDecodeArtifact` | no canonical→Ramulator bridge |
| `OptimizationDefinition` **does not depend** on any derived artifact | it is above the pipeline |
| `FabricArtifact` **does not depend** on `RequirementV3` | requirements are product acceptance, not compilation |
| `RequirementReport` **does not depend** on `OptimizationStudyView` | the study consumes the report, never the reverse |
| `MappingArtifact` **does not depend** on `RouteArtifact` | rank placement has nothing to do with route decode |
| `VerificationCertificate` **does not depend** on any backend | certificate ≠ qualification |

## 4. Artifact parent / identity graph

| Artifact | Parents | Semantics authority | Content identity | Context-bound | Run-stable |
|---|---|---|---|---|---|
| `PhysicalInventory` | SystemIntent | `PHYSICAL_INVENTORY_SCHEMA_VERSION = 1` | `system_intent.py:53` | yes | yes |
| participant inventory | PhysicalInventory + ParallelismIntent | participant schema | derived | yes | yes |
| `MappingArtifact` | PhysicalInventory + ParallelismIntent + **`MappingPolicy`** | `MAPPING_SCHEMA_VERSION` | `{type, schema_version, placements}` — **policy NOT bound** | **weakly** | yes |
| `TopologyArtifact` | FabricIntent | `SCHEMA_VERSION = "0"` (`topology_ir.py:37`) | identity_dict | yes | yes |
| `AgentAttachmentArtifact` | TopologyArtifact | `ATTACHMENT_SCHEMA_VERSION = 3` | `{type, schema_version, topology_hash, endpoints}` | yes | yes |
| `AddressDecodeArtifact` | AddressMap + Attachment + **decode semantics** | `ADDRESS_DECODE_SCHEMA_VERSION = 3` | `{…, attachment_hash, address_transform, unmatched_address_policy, entries}` | yes | yes |
| `RouteArtifact` | TopologyArtifact + **`ROUTING_ALGORITHM`** | `RoutingClassDefinition.algorithm_version` | content_id over the (class, src, dst) table | yes | yes |
| `ResolvedRouteArtifact` | RouteArtifact | `ROUTING_RELATION_SCHEMA_VERSION = 1` | content_id | yes | yes |
| `VCAssignmentArtifact` | CommunicationIntent + TopologyArtifact + **derivation** | `VC_RESOURCE_SCHEMA_VERSION = 1` | `{vc_count, vc_ids, traffic_class_to_vcs, allowed_transitions}` — **`derivation` deliberately absent** | **no** (*"carries no design hash and no parent hash"*) | yes |
| `RouterBehaviorArtifact` | VCAssignmentArtifact + RouterResourceIntent | `ROUTER_BEHAVIOR` schema | `{…, vc_resource_hash, buffer_organization, depths, flow_control, credit_return_latency_cycles, vc_reuse_policy, vc_allocator, switch_allocator}` | yes | yes |
| `VerificationCertificate` | FabricArtifact | certificate semantics | content_id | yes | yes |
| `BackendQualificationProfile` | backend identity + envelope | profile version | `SUPPORTED` envelope | yes | yes |
| `ScientificBackendEvidence` | ExecutionAttempt + producer identity | evidence semantics | hash-linked to the request | yes | **stable across reruns** |
| `ExecutionAttempt` | backend + run context | — | run-varying | yes | **run-varying** |
| `RequirementReport` | MetricObservation + RequirementV3 | report identity | `report_identity(report)` | yes | yes |
| `MemoryArtifact` | Phase-9 WorkloadArtifact + MemorySystemDesign | `MEMORY_LOWERING` schema 1 | `artifact_hash` + `source_workload_hash` | yes | yes |
| `MemoryLoweringManifest` | MemoryArtifact + RamulatorGeometry | `MAPPING_ALGORITHM` | `{schema_version, source_memory_artifact_hash, access_stream_hash, lowerer, mapping_algorithm, backend_config_hash, trace_sha256, …}` | yes | yes |
| `Candidate` | base design + patch | `optimization-candidate/v1` | `cand_` + content_id | yes | yes |
| `OptimizationResult` | definition + candidate rows + frontier | `optimization-result/v2` | `result_id()` | yes | yes |

### 4.1 The silent-policy hunt (§3's mandatory search)

Searched for `derivation`, `policy`, `algorithm`, `method`, `strategy`,
`semantics_version`, `version`, `provenance` excluded from semantic identity while
changing a derived relation. **Four instances exist. All four are already-recorded
Gate-2 debt — Gate 3 found no *unrecorded* instance.**

| # | Field | Where | Excluded from identity? | Changes the relation? | Status |
|---|---|---|---|---|---|
| 1 | `MappingPolicy.RANK_ORDER_V1` | `candidate_policy.py:144`, used `:308` | **yes** — `MappingArtifact.canonical_dict` (`mapping.py:135`) binds only `{type, schema_version, placements}` | **yes** | **XDOM-D1** (new cross-domain debt; Domain F's target contract, unimplemented) |
| 2 | `VCResourceArtifact.derivation` | `vc_resource.py:111,197` — *"deliberately absent"* | **yes, by explicit design** | the artifact is a **relation**; the policy that produced it is not | **XDOM-D2** |
| 3 | `TopologySemanticsIdentity` | **does not exist** (zero hits) | n/a | topology construction is deterministic | already **FAB-D4** |
| 4 | `AttachmentSemanticsIdentity` / `ATTACHMENT_ORDER_V1` | **does not exist** (zero hits) | n/a | attachment ordering is deterministic | already **FAB-D1** |
| 5 | `VCAssignmentSemanticsIdentity` | **does not exist** (zero hits) | n/a | — | already **VC-D1** |

**Finding:** items 3–5 are **not** new discoveries. Domain F and Domain H recorded
them as **target contracts** (`FAB-D1`, `FAB-D4`, `VC-D1`) while Gate 2 froze
implementation. Gate 3's job was to prove the *list* is complete, not to
re-discover it. **It is complete: no unrecorded instance remains.**

Items 1–2 are promoted to cross-domain debt because they are **not** captured by
any single domain's debt list: they are *relation-vs-artifact* defects spanning
compiler policy and artifact identity.

**Relation-vs-artifact distinction (§4)** is preserved where it exists
(`MappingRelation`/`MappingArtifact`, `AttachmentRelation`/
`AgentAttachmentArtifact`) and is the reason `VCResourceArtifact` legitimately
carries no parent hash — it is a **relation**, and its context-bound wrapper is
`RouterBehaviorArtifact`, which **does** bind `vc_resource_hash`.

## 5. Namespace graph

| Namespace | Authority | Injective? | Total? |
|---|---|---|---|
| `AgentGroupId` | SYSTEM | yes | yes |
| `AgentInstanceId` | SYSTEM (`placement.py:123` `instance_id`) | yes | yes |
| `group_index` | SYSTEM | **positional — never an identity** | yes |
| `LogicalParticipantId` | PARALLELISM | yes | yes |
| global rank | PARALLELISM / MAPPING | yes | yes |
| parallelism group ID | PARALLELISM | yes | yes |
| `CommunicationClassId` | COMMUNICATION | yes | yes |
| workload operation ID | WORKLOAD | yes | yes |
| bound operation ID | COMMUNICATION lowering | yes | partial (bound only for lowered ops) |
| `RouterId` | FABRIC | yes | yes |
| `ChannelId` | FABRIC | yes | yes |
| `EndpointSeatId` | FABRIC | yes | yes |
| `EndpointId` | FABRIC (seat-derived — FAB-D2) | yes | yes |
| `RoutingClassId` | ROUTER RESOURCE | yes | yes |
| VC ID | ROUTER RESOURCE (compiler-derived) | yes | yes |
| serving instance ID | SERVING | yes | yes |
| virtual NPU ID | SERVING | yes | yes |
| ASTRA `Sys.id` | ASTRA (backend) | backend-local | backend-local |
| BookSim node / injection ID | BookSim (backend) | backend-local | backend-local |
| `RequirementId` | REQUIREMENTS | yes | yes |
| `MetricId` | METRIC REGISTRY | yes | yes |
| `CandidateId` | DESIGN SPACE | yes | yes |
| `StudyDefinitionId` | DESIGN SPACE | yes | yes |

**Conversions and their authorities:**

| From → To | Authority | Artifact | Injective | Total |
|---|---|---|---|---|
| `AgentInstanceId` → global rank | MAPPING | `MappingArtifact` | **no** (many agents, few ranks) | no |
| global rank → `AgentInstanceId` | MAPPING | `MappingArtifact` | yes | yes |
| `LogicalParticipantId` → `AgentInstanceId` | MAPPING | `MappingArtifact` | yes | yes |
| `AgentInstanceId` → `EndpointId` | ATTACHMENT | `AgentAttachmentArtifact` | **no** (one agent, many seats) | partial |
| `EndpointId` → backend node | FABRIC backend projection | backend config | yes | partial (idle endpoints — FAB-D6) |
| `RouterId` → ASTRA `Sys.id` | backend projection | backend config | yes | partial |
| address → `AgentInstanceId` | ADDRESS DECODE | `AddressDecodeArtifact` | yes (ranges) | partial (gaps legal) |
| metric name → `MetricId` | REGISTRY | `CertifiedMetricRegistry` | yes | no (3 registered) |
| base design + patch → `CandidateId` | DESIGN SPACE | `Candidate` | yes | yes |

**Locked law: the same integer value NEVER proves identity across namespaces.**
Audit result: **no violation found in the compile path.** The two places where a
bare integer crosses a namespace boundary — `group_index` (SYSTEM) and backend
node ordinals — are explicitly **positional/projection** values, and both are
already recorded as migration debt (`S9`, `FAB-D2`). `AddressDecodeEntry` carries
**both** `target_agent_group` **and** `target_endpoint_id` precisely so the
ordinal is never mistaken for the identity.

## 6. Field-ownership matrix (the 59 declared fields)

Source-of-value classes: **UI** user intent · **CV** candidate-owned variable ·
**CD** compiler-derived · **VD** verification-derived · **EC** evaluation config ·
**BP** backend projection · **ER** evidence result · **MD** metadata.

| Class | Fields |
|---|---|
| `CompileRequestV3` | `agents` UI · `dependencies` UI · `workload` UI · `noc_config` UI · `address_map` UI · `physical` UI · `requirements` UI · `compiler_semantics_version` MD(pin) |
| `WorkloadV3` | `model_family` UI · `hidden_size` UI · `num_layers` UI · `num_heads` UI · `seq_len` UI · `batch_size` UI · `tp` UI · `pp` UI · `ep` UI · `dp` UI · `collectives` UI · `serving_mode` UI |
| `RequirementV3` | `kind` UI · `metric` UI · `op` UI · `threshold` UI · `binding` UI |
| `Agent` | `kind` UI · `count` UI · `interface` UI · `group_index` CD(positional) |
| `NocConfig` | `topology_family` UI · `radix` UI · `concentration` UI · `arbitration` UI · `link_width` UI · `output_formats` UI · `obfuscation_level` UI · **`rcu_enabled` LEGACY (not target intent)** · **`mcast_groups` / `mcast_setup_cycles` LEGACY (not target intent)** |
| `AddressMap`/`AddressRange` | `name` **MD** · `base` UI · `size` UI · `target_agent_idx` UI→stable id |
| `PhysicalContext` | `default_clock_freq_mhz` UI(design clock) |
| `DependencyGraph`/`Dependency` | declared edges UI |
| `CollectiveIntent` | `kind` UI · `size` UI · `traffic_class` UI |
| `WorkloadSourceRef` | source metadata UI/MD |
| `CompileIntent` | preset name **MD** · `fabric_overrides` UI · `candidate_policy` UI |
| router buffers | **CV** (Domain H/J — no field exists yet) |
| routing / VC count / turn restrictions / escape VC | **CD** |
| `MappingPolicy.RANK_ORDER_V1` | **CD** |
| network clock | **EC** |
| Ramulator technology/profile | **EC** (memory evaluation profile) |
| BookSim node ids / ASTRA `Sys.id` | **BP** |
| metric observations, cycles, ns | **ER** |
| `schema_version`, `*_hash`, `intent_id`, display names | **MD** |

**Enforcement:** every class above must be machine-checked by D7's per-type
classification sentinel. **No field appears twice.** The one field that appeared
under two authorities in Gate 1 — `MappingPolicy`, described as *"owned by
candidate generation"* while being a compiler policy — is corrected by **D2**:
`MappingPolicy` is **CD**.

## 7. `radix` vs `side_length` — CROSS-DOMAIN CORRECTION

**Affected domains:** FABRIC (Domain G) and DESIGN-SPACE (Domain J).

**Old statements:**
- Domain G: *"the field represents square-grid side length `k`, not router
  radix/degree"* — and Domain J's brief assumed a `radix`→`side_length` rename
  requiring migration.
- Domain J: *"`NocConfig.radix` is canonical (`compile_model.py:616`); `k`/side
  length is a derived projection (`params["k"] = cr.noc_config.radix`, `:1514`).
  **No `radix`→`side_length` migration is required.**"*

**Source evidence:** `model/compile_model.py:616` (`radix: int | None = None`),
`:1514-1515` (`params["k"] = cr.noc_config.radix`); `optimization/definition.py:36`
(`"radix": "radix"` in `GUIDED_PARAMS`).

**Chosen authority: option A.**
**`NocConfig.radix` remains the canonical implementation field name.** The target
scientific/product name is **`side_length`** — it denotes square-grid side length
`k`, not router degree. **`k` remains a derived projection**, never a second
input.

```text
scientific name : side_length      (square-grid side k)
implementation  : NocConfig.radix  (retained; boundary alias only)
derived         : params["k"]      (never an input)
```

**No schema migration.** The alias exists **only at the presentation/definition
boundary** and normalizes immediately to `radix` — exactly as dotted
`noc_config.*` aliases already do (`definition.py:56`).

**Why not C (rename):** a rename is a schema change with zero scientific gain, and
it would invalidate every persisted request and study for a naming preference.
**Why not B (keep `radix` in docs):** `radix` is actively misleading — it is not a
router degree — and Domain G already established the product semantic.

**Identity consequence:** none — the value and therefore every hash is unchanged.
**Migration consequence:** none. **Optimization dimension naming:** the GUIDED
dimension stays `radix` in code and is **presented as "side length"**; a future
dimension rename is a boundary alias, not a schema change.
**Docs updated:** `INTENT-FABRIC.md` and `INTENT-DESIGN-SPACE.md` now state the
same law; `INTENT-DESIGN-SPACE.md` §8's "correction" is confirmed and Domain G's
statement is reconciled as *scientific name*, not *field name*.

**Ontology resolution:** RESOLVED.

## 8. Requirement satisfaction vs Pareto eligibility

**Evidence:** `optimization/result.py:913-946` — *"binding product requirements are
not satisfied"* is an explicit `eligibility_reason`. `real_evaluator.py:246` keeps
a requirement-violating run as `EVALUATED` with its measurements.

**Options:** A — requirement satisfaction is a mandatory eligibility predicate;
B — the frontier is over measured objectives and requirement status is orthogonal.

**Chosen law: B, with A available as an explicit study policy.**

```text
Pareto frontier  = over candidates that are MEASURED and scientifically eligible
                   (evaluation succeeded · certified authority · metrics admissible ·
                    objectives measured · constraints SATISFIED)
RequirementReport = an ORTHOGONAL product-acceptance annotation on every candidate
```

A candidate that **dominates objectively** but **violates a Product Requirement**
**stays on the frontier**, carrying `product_requirements.satisfied = false` and its
requirement verdicts. It is **not** silently removed.

**Why — the scientific argument:**

1. **The optimization problem is defined by objectives and constraints.** A
   Product Requirement is a statement about *whether a finished design is
   acceptable to the customer*. Folding it into eligibility makes the frontier a
   function of an external acceptance threshold, so **the same design space with
   different RequirementSet thresholds would have different Pareto frontiers** —
   which would make the frontier non-scientific.
2. **Requirements are not part of the search problem.** The optimizer already has
   a separate, typed mechanism for "must hold": **optimization constraints**
   (§26 of Domain J). A study that genuinely wants "only requirement-passing
   candidates" declares a constraint; the authority is then the study's, not the
   customer's.
3. **Domain E already established that threshold changes need no new
   measurements.** Under A, a threshold change would silently *change the
   frontier* while reusing evidence — an invisible scientific change. Under B it
   changes only the annotation.
4. **It is recoverable.** `pareto_eligible` already requires *"binding product
   requirements are not satisfied"* today; moving it to an annotation **loses no
   information** (v2 already carries both) and **gains** a frontier that is a
   function of the design space alone.

**Identity consequence:** `RequirementSet` identity **stays out of** the Pareto
predicate but **stays in** `StudyDefinition` identity (a study promises a report).
**Candidate `design_hash` is unaffected.**

**Invalidation/reuse:** threshold change → **no new measurement**; RequirementReport
recomputed; frontier recomputed only if the study declares a requirement-derived
constraint. **Migration:** the optimizer's eligibility predicate drops the
requirement term; the term becomes a `constraint`-like derived status. Recorded as
**XDOM-D4**.

**Product consequence:** the Results view distinguishes *Pareto member + requirements
satisfied* from *Pareto member + requirements violated* — visually, without
rewriting the frontier. **Ontology resolution:** RESOLVED.

## 9. Search method / budget / seed identity

**Evidence:** `definition.py:272` — `definition_id()` binds `method`, `budget`,
`seed`.

**Options:** A — keep all three in study identity; B — split into
`StudyDefinition` + `SearchExecutionPolicy`.

**Chosen law: B.**

```text
StudyDefinition (scientific question)   identity: study_definition_id
    baseline_design_identity · design_space · objectives · constraints ·
    requirement_set_identity · evaluation_policy

SearchExecutionPolicy (exploration)     identity: search_execution_id
    method · budget · seed

StudyExecution (one run)                identity: execution_attempt_id (run-varying)
    candidate proposals · attempts · evidence refs
```

**Answers to the three direct questions:**

| Question | Answer |
|---|---|
| Does GRID→GUIDED change the scientific study? | **No.** It changes which candidates are proposed, not what is being asked. |
| Does changing the seed change the study question? | **No.** It changes the explored subset. `bounded_random_candidates` already re-sorts canonically so *"the evaluated SET is seed-dependent but the ORDER is canonical"*. |
| Does changing the budget change the scientific definition? | **No.** It changes completeness of exploration. Budget truncation already keeps the canonical prefix. |

**Why B and not A:** under A, changing a seed produces a *different study*, which
would force evidence re-keying and make two runs of one question look like two
questions. Candidate science is already content-based, so nothing is gained by
fusing the attempt into the question.

**Identity consequence:** `definition_id` splits; `candidate_id` is **unchanged**
(it never bound method/seed/budget). **Invalidation/reuse:** search-policy change →
no candidate identity change → **existing evidence reusable**. **Migration:** the
current combined `definition_id` becomes `study_definition_id`; persisted studies
are re-keyed once. **Debt:** **XDOM-D5**.

**Product consequence:** the Study surface shows the scientific definition; the
Search surface shows exploration policy. **Ontology resolution:** RESOLVED.

## 10. Arbitration canonicalization ownership

**Evidence:** `optimization/candidate.py:97` passes `arbitration` raw;
`candidate_id_for` hashes the raw patch; `compile_model.py:1070` puts the raw
string in `design_hash`; `router_behavior.py:217` `canonical_allocator`
canonicalizes **at compile time**.

**Chosen law:** **canonicalization is owned by the domain that owns the field —
`RouterResourceIntent`'s `canonical_allocator` — and candidate identity MUST
consume its canonical result.**

```text
authoritative canonicalizer : model/router_behavior.py::canonical_allocator
candidate identity          : computed from canonical domain values ONLY
optimizer-specific aliasing : FORBIDDEN
```

**Why:** the optimizer must not own an alternative normalization rule for a field
it does not own. The defect is not "a missing alias table" — it is **ordering**:
identity was computed before the owning domain canonicalized.

**Identity consequence:** `"islip"` and `"ISLIP"` become **one** `candidate_id`.
**Invalidation/reuse:** existing studies with non-canonical spellings re-key once.
**Migration:** a one-time re-canonicalization of persisted patches.

**Debt:** **XDOM-D6** (this is Domain J's OPT-D2, promoted to cross-domain because
it is a **canonicalization-ownership law**, not an optimizer detail).
**Ontology resolution:** RESOLVED.

## 11. Pre-compile optimization constraints

**Chosen law: NO pre-compile optimization-constraint stage is admitted in v4.**

**Why:** a DesignSpace dimension's allowed value set **already** bounds every
pre-compile quantity. `side_length ≤ 16` is `DomainParam("radix", (2,4,8,16))`;
`link_width_bits ∈ set` is the value tuple; `candidate buffer depth ≤ N` is the
value tuple of a future CV dimension. A separate pre-compile constraint type would
**add no scientific expressiveness** while creating a second authority over the
same field — forbidden by §6's "no field may have two editable authorities".

**A dimension's allowed range is NOT a constraint.** Distinction locked:

| Concept | Meaning | Stage |
|---|---|---|
| DesignSpace dimension bound | the *enumerated* values the optimizer may propose | construction |
| Optimization constraint | a *measured-metric* bound the candidate must satisfy | post-evaluation |

**Failure state:** out-of-space values are **engine proposal failures** (J56),
never constraint violations. **Migration:** none. **Debt:** none.
**Ontology resolution:** RESOLVED.

## 12. Compile feasibility is NOT an optimization constraint

**Locked regardless of D1–D8.** Insufficient endpoint seats, an invalid
`AddressMap`, and unsupported route derivation are **canonical pipeline
outcomes**. There is **no** `must_compile` / `must_verify` user constraint; the
compiler's verdict already precedes evaluation (`real_evaluator.py:161`), and a
`COMPILE_FAILED` candidate never reaches measurement. **Canonical scientific
validity is mandatory and non-negotiable.**

## 13. Verification PASS vs backend qualification

**Global law — these are independent layers.**

| State | Meaning |
|---|---|
| CANONICALLY VALID | the design compiles |
| CERTIFICATE PASS | the canonical verifier's obligations hold |
| BACKEND NOT QUALIFIED | the selected profile's claim envelope does not cover this candidate |

**Valid combination:** certificate PASS + NOT QUALIFIED → a valid canonical design
with **no admissible measurement under that profile**. Example: `concentration > 1`
under the native BookSim profile (J37). **Also valid:** torus topology
materializable + route derivation unavailable.

**Never collapse to `SUPPORTED`.** See §14.

## 14. Capability-stage vocabulary

Adopted, reconciled against the domain matrices:

```text
DECLARABLE    a user may declare it in an intent
DERIVABLE     the compiler can materialize it
VERIFIABLE    the canonical verifier can prove it
PROJECTABLE   it can be projected to a backend
EXECUTABLE    a backend can run it
QUALIFIED     a backend/profile permits a scoped claim about it
EVIDENCE-CAPABLE  an authenticated observation can be produced
PRODUCT-WIRED     a product entry point reaches it
```

Worked examples:

```text
TORUS
  declarable YES · topology derivable YES · route derivable NO ·
  projectable NO · executable NO · qualified NO · product-wired NO

RAMULATOR
  declarable NO · derivable YES (legacy) · verifiable NO · projectable YES ·
  executable YES · qualified YES (v1 envelope) · evidence-capable YES ·
  product-wired NO

OPTIMIZATION
  declarable YES · derivable YES · verifiable YES · projectable YES ·
  executable YES · qualified YES (certified) · evidence-capable YES ·
  product-wired YES

MULTI-CLASS COMMUNICATION
  declarable YES · derivable YES · verifiable YES · projectable NO ·
  executable NO · qualified NO (native BookSim requires one class) ·
  evidence-capable NO · product-wired NO
```

## 15. Static evaluation vs Serving

| | Static Product Evaluation | Serving |
|---|---|---|
| Entry | canonical workload graph | request trace |
| Scheduling | none | LLMServingSim scheduling/batching |
| Lowering | communication lowering | serving network projection |
| Backend | canonical fabric → BookSim | canonical fabric/network backend |
| **Execution graph** | **NOT identical** | **NOT identical** |

**Shared objects:** `ModelSpec`, ParallelismIntent, `MappingArtifact`,
`FabricArtifact`. **Not shared:** the execution graph, the time domain, the
metric population.

**Locked:** the PRODUCT layer must **never** display a serving result as a static
result or vice versa. **Comparability:** a serving metric and a static metric are
comparable only if `MetricId`, producer, `semantics_version` and population all
agree — which today they do not.

## 16. Static MoE vs Serving MoE

**Locked reality:** serving MoE has real dispatch/combine behaviour. **Static
Product Evaluation does NOT have an equivalent MoE lowering.** A shared EP extent
does **not** bridge them.

```text
SERVING MoE : declarable YES · derivable YES · executable YES ·
              qualified (serving backend) · evidence-capable YES
STATIC MoE  : declarable YES · derivable NO (no MoE lowering) ·
              executable NO · evidence-capable NO
```

**A shared EP extent is not a capability bridge.** This distinction survives into
the whole-system matrix (§41).

## 17. Communication-class cross-domain law

Domain D established: `CommunicationClass` affects **VC assignment**; it does
**not** affect **route selection** today. Static execution remains limited by
**COMM-D1** (multi-class lowering) and native BookSim qualification requires a
single class.

**Exact state progression for a multi-class design:**

| Stage | Verdict |
|---|---|
| Intent validity | **VALID** — multiple classes are declarable |
| logical message artifact | **DERIVABLE** |
| physical propagation | **DERIVABLE** |
| VC assignment | **DERIVABLE** — class→VC map is real |
| verification | **VERIFIABLE** — class-VC CDG is checked |
| backend qualification | **NOT QUALIFIED** under native BookSim (single class) |
| execution | **NOT EXECUTABLE** in the static certified path |

**It is never globally "supported" or "unsupported".**

## 18. Time-domain law

| Time domain | Owner | Representation | Conversion authority | Metrics using it | Legal conversion |
|---|---|---|---|---|---|
| design clock | PHYSICAL (`PhysicalContext.default_clock_freq_mhz`) | int MHz | **none** | design-level timing | **no** |
| evaluation network clock | EVALUATION (`--network-clock-hz`, exact int Hz) | exact int Hz | authenticated recovery contract | `completion_ns` | to cycles only under the recovery contract |
| serving-model clock | SERVING | model time | serving runtime | serving metrics | **no** |
| DRAM / Ramulator clock | MEMORY EVALUATION PROFILE | `clock_ratio 4/1` | **none** | `completion_cycles` (DRAM) | **no** |
| native BookSim cycles | BookSim | integer cycles | **none** (native) | `completion_cycles` | n/a (native) |
| ASTRA timing | ASTRA | backend cycles | **none** | ASTRA metrics | **no** |
| wall duration | harness | seconds | **none** | diagnostic only | **no** |

**Locked:** **time is never cross-compared without a proven conversion. There is
no universal clock.**

## 19. Cycles vs nanoseconds

**The subtle law from PHYSICAL:** native network-cycle evidence **survives** a
change in the caller's network clock under the authenticated recovery contract.
**Derived nanoseconds do not.**

| Consumer | Effect |
|---|---|
| `RequirementReport` | a `completion_ns` requirement is **stale** when the clock changes; a `completion_cycles` requirement is **reusable** |
| Optimization objectives | same split — `completion_cycles` reusable, `completion_ns` not |
| evidence reuse | cycle evidence reusable; ns evidence requires the same clock |
| comparison views | ns values from different clocks are **not comparable** |

**No frontend recomputation with an arbitrary clock** (X26).

## 20. Memory vs network law

**Locked:** the canonical `AddressMap` compile path and the standalone Ramulator
evaluation chain **remain disconnected today**.

```text
FORBIDDEN : BookSim latency + Ramulator latency summed
FORBIDDEN : canonical memory locality claim
FORBIDDEN : network+DRAM coupled timing claim
```

**Ramulator product state:** engine available · **product workflow not wired**.
Carried into the whole-system matrix (§41). Proven from both directions by I62/I63
and by `build_artifact` having no caller outside `memory_lowering`.

## 21. Intent validity vs join feasibility

| Situation | Verdict |
|---|---|
| SystemIntent valid + ParallelismIntent valid, insufficient compute agents | both intents **VALID**; **MAPPING JOIN infeasible** |
| FabricIntent valid + PhysicalInventory valid, insufficient seats | both **VALID**; **FABRIC/ATTACHMENT JOIN infeasible** |
| Torus FabricIntent valid | **VALID**; route generator **unavailable** downstream |
| AddressMap targets a compute agent | MemoryIntent **INVALID** (not a join failure) |

**Law: an upstream intent is never retroactively labelled invalid because a
downstream join failed.** The failure belongs to the **join**, and its name says
so. This is why `COMPILE_FAILED` preserves the compiler's own verdict in
`compilation_status` rather than flattening it.

## 22. Error / refusal taxonomy

Cross-domain meanings (domains keep their own enums; these are the **shared
semantics**):

| Cross-domain class | Meaning | Domain vocabularies mapped |
|---|---|---|
| **MALFORMED / INVALID** | the object itself violates its own contract | `InvalidInput`, `AddressDecodeError`, `MappingError`, `OptimizationDefinitionError`, `CandidateError`, MemoryIntent `INVALID_RANGE` |
| **VALID BUT CROSS-DOMAIN INFEASIBLE** | intents individually valid; the join cannot be satisfied | `MappingInvalid`, seat-capacity refusal, `L3d` coherence failures |
| **VALID BUT CAPABILITY UNSUPPORTED** | valid design, no canonical derivation path | `UnsupportedSemantics`, `UNSUPPORTED_SEMANTICS`, `AddressDecodeError` UNSUPPORTED, torus routing |
| **CANONICAL VERIFICATION FAILED** | verifier obligations not met | certificate FAIL, CDG failure |
| **BACKEND NOT QUALIFIED / UNAVAILABLE** | profile cannot cover the candidate | `BACKEND_UNAVAILABLE`, qualification FAIL |
| **EXECUTION FAILED** | backend ran and failed | `FAILED`, `EVALUATION_FAILED` |
| **MEASUREMENT UNMEASURABLE** | execution succeeded; the metric has no admissible observation | `UNMEASURABLE`, objective `UNMEASURABLE`, constraint `UNMEASURABLE`, `UNMEASURABLE` |

**Not forced into one enum** — `UNSUPPORTED` in `AddressDecode` and `UNSUPPORTED`
in the compiler are the same *cross-domain class*, with different local spellings.

## 23. No fabricated zero law

**Locked globally.** Missing measurement, unsupported metric, backend failure,
unmapped value and unsupported capability **never become numeric zero**.

| Consumer | Enforcement |
|---|---|
| Requirement evaluation | `UNMEASURABLE` (Domain E) |
| Optimization | `UNMEASURABLE` objective/constraint state; *"unmeasurable never passes"* (`constraints.py:24`) |
| Serving metrics | absent, never 0 |
| Memory evaluation | `UNMEASURABLE` / typed failure; *"never zero"* |
| network evidence | `None`, never 0 |

**Audit result:** no default-zero behaviour found in the compile, evaluation,
optimization or report paths. The optimizer's `_finite_number` returns `None`, and
Studio's plot explicitly *"never coerced to 0"* (`OptimizeView.tsx:96`).

## 24. Metric authority across Requirements and Optimization

**One authority: `CertifiedMetricRegistry`.** `RequirementV3.metric` and
`Objective.metric` / `Constraint.metric` are **bare names resolved against the same
registry**. There are **no duplicate metric definitions**.

| Shared metric | Unit | Producer | Semantics version | Population | Target | Qualification |
|---|---|---|---|---|---|---|
| `completion_cycles` | cycles | `authenticated-network-window-cycles` | 1 | one authenticated network window | the evaluated design | certified backend |
| `completion_time` | cycles | same | 1 | same | same | same |
| `completion_ns` | ns | `authenticated-network-window-wall-time-ns` | 1 | same | same | same + exact clock |

**Mixed producers require a compatibility proof.** Today no study mixes producers
(one registry, one backend), and the sealed gate refuses mixed fidelities. When a
second producer lands, comparability must be proven via `MetricAuthority.identity()`
before two values share an axis.

## 25. Evidence admissibility law

A number may become a **Requirement observation** or an **Optimization objective
observation** only when **all** hold:

```text
1. registered MetricId in the frozen CertifiedMetricRegistry
2. qualified producer for that metric
3. compatible semantics_version
4. required canonical certificate state (PASS where the metric requires it)
5. evidence integrity (authenticated proof re-verified, not a label)
6. target/population compatibility
```

**Raw backend output never enters product science.** In the certified optimizer
path, the evaluator's `objective_values` **never score**: metrics are extracted
from `claims.verified_result`, and a misreported value **refuses hard**
(`result.py:268`).

## 26. Certificate vs Qualification vs Evidence

| Layer | Definition | Owner |
|---|---|---|
| **Certificate** | canonical design/compiler/verifier correctness obligations | canonical verifier |
| **Qualification** | the backend/profile permitted-claim envelope | evaluation policy |
| **Evidence** | an authenticated observation produced by an execution | evidence chain |

**Valid:** certificate PASS · qualification FAIL · no admissible measurement.
**Invalid:** certificate FAIL · backend printed a number → **the number cannot
become an authoritative product measurement** (X14).

**These are independent layers and are never collapsed.**

## 27. Observation scope law

Route evidence today is **`FIRST_HOP_VERIFIED`**. Canonical route derivation proves
the **full canonical route terminates and is legal**. These are different.

```text
DERIVED EXPECTED STATE  must never be labelled  OBSERVED EVIDENCE
```

Applied generally: a compiler-derived expectation is never reported as an
observation, and an observation scope is always named (`FIRST_HOP` vs `FULL_PATH`).
This is why `RouteObservationScope` exists (Domain H) and why the certificate
proves termination over the whole table rather than one hop.

## 28. Product-wired vs engine-available

| Capability | Compiler-available | Engine-available | Product-wired |
|---|---|---|---|
| Optimization | yes | yes | **yes** (`/api/v1/revisions/{id}/optimize`) |
| Ramulator | n/a | **yes** | **NO** |
| Torus topology | yes | — | route path **unavailable** |
| Serving | yes | yes | yes |

**Law: a product capability matrix must never infer a UI flow from the existence
of code.** Only `PRODUCT-WIRED` justifies a flow.

## 29. Compiler-owned policy registry

| Policy | Inputs | Outputs | Identity binding | Location |
|---|---|---|---|---|
| `MappingPolicy.RANK_ORDER_V1` | inventory + parallelism | rank→agent relation | **NOT bound** → XDOM-D1 | `candidate_policy.py:144,308` |
| `ATTACHMENT_ORDER_V1` | topology + inventory | agent→endpoint relation | **does not exist** → FAB-D1 | — |
| `RoutingClassDefinition.algorithm_version` | topology + classes | route table | **bound** | `core/route_artifact.py:174` |
| `ROUTING_ALGORITHM = "anynet_dijkstra_hops"` | topology | routes | **bound** | `core/route_artifact.py:53` |
| `MIN_ADAPT_ALGORITHM = "per_hop_min_adaptive"` | routes | resolved routes | **bound** | `routing_relation_materialize.py:54` |
| `VCAssignmentSemanticsIdentity` | classes + topology | VC assignment | **does not exist**; `derivation` excluded → XDOM-D2 / VC-D1 | `vc_resource.py:197` |
| `ADDRESS_DECODE_SCHEMA_VERSION = 3` | address map + attachment | decode table | **bound** | `address_decode.py:72` |
| `MAPPING_ALGORITHM = "sequential_bankstriped_v1"` | memory artifact | request stream | **bound** | `memory_lowering.py:381` |
| topology construction semantics | FabricIntent | topology | **does not exist** → FAB-D4 | `topology_ir.py:37` |
| `COMPILER_SEMANTICS_VERSION` | — | all derivations | **bound** (pinned in the request) | `compile_model.py:46,1850` |

**Every science-changing deterministic derivation must be identity-bound.**
Ten policies audited; **six bound, four recorded debt** (all pre-existing).

## 30. Candidate-owned vs DesignIntent fields

| Field | Class |
|---|---|
| `arbitration` | **UI (Design Intent)** |
| router buffers | **CV** — category defined, no field exists |
| network clock | **EC** |
| Ramulator profile | **EC** |
| routing | **CD** |
| VC count / structure | **CD** |
| turn restrictions, escape VC | **CD** |
| `MappingPolicy` | **CD** (corrected from Gate 1's "candidate generation") |
| address ranges | **UI** |
| `RequirementV3.threshold` | **UI (product requirement)** |
| objective direction / constraint threshold | **UI (study definition)** |
| BookSim node ids, ASTRA `Sys.id` | **BP** |
| cycles, ns, observations | **ER** |
| names, `*_hash`, `schema_version`, `intent_id` | **MD** |

**This is the basis for the Guided/Expert UI.**

## 31. Optimization's eight dimensions

| Optimizer dimension | `NocConfig` field | Canonical domain owner | Target scientific name | Status |
|---|---|---|---|---|
| `link_width` | `link_width` | FABRIC | link width (bits) | coherent |
| `concentration` | `concentration` | FABRIC | endpoints per router | coherent |
| `radix` | `radix` | FABRIC | **side length `k`** | **misleading name** — §7 |
| `topology_family` | `topology_family` | FABRIC | topology family | coherent |
| `arbitration` | `arbitration` | ROUTER RESOURCE | arbitration policy | coherent; canonicalization ordering → §10 |
| `rcu_enabled` | `rcu_enabled` | **none — removed from v4** | in-network reduction | **REMOVED from v4** (`INTENT-ROUTER-RESOURCES.md:316,320`); FUTURE CAPABILITY CONTRACT |
| `mcast_groups` | `mcast_groups` | **none — removed from v4** | hardware multicast groups | **REMOVED from v4** (`INTENT-FABRIC.md:387`); FUTURE CAPABILITY CONTRACT |
| `mcast_setup_cycles` | `mcast_setup_cycles` | **none — removed from v4** | per-group reconfiguration cost | **REMOVED from v4** (`INTENT-FABRIC.md:387`); FUTURE CAPABILITY CONTRACT |

**No dimension targets a derived, deprecated, backend-only or future-capability
field.** The three multicast/RCU dimensions are **declared in the current schema
but removed from v4** — classified by §14, not silently promoted. **Gate 3 is not
---

**GATE-5 CORRECTION (recorded):** the first pass described `rcu_enabled` and the
`mcast_*` knobs as *"declarable but not executable"*, which implied an accepted
contract awaiting execution support. That contradicts
`INTENT-ROUTER-RESOURCES.md:316,320` (*"REMOVE from v4"*; *"**No `rcu=true`
checkbox.**"*) and `INTENT-FABRIC.md:386-387` (both classified
**ROUTER/RESOURCE (unsupported)**). They are **not target Design Intent**. Legacy
parsing is preserved; target authoring must not expose them.
blocked by any dimension.**

## 32. Search-space canonicalization

**Law:** every optimizer dimension value is canonicalized through its **owning
domain** before `CandidateId`, deduplication, cache lookup or comparison. **The
optimizer must not duplicate normalization.**

Systematic resolution (not a one-off): `topology_family` already canonicalizes via
enum construction; `arbitration` must route through `canonical_allocator`;
numeric dimensions are already exact ints; `None` refuses by design. **Debt:**
**XDOM-D6**.

## 33. Requirements and candidate identity

| Changed | `design_hash` | `StudyDefinition` | Pareto eligibility | `RequirementReport` | Selection |
|---|---|---|---|---|---|
| `RequirementSet` | **unchanged** | **changes** (identity) | **unchanged** (§8 law B) | **recomputed** | recomputed only if a requirement-derived constraint exists |

**Measurements remain reusable** when metric semantics are unchanged. Locked.

## 34. Evaluation-policy identity

Backend/profile belongs to **`StudyDefinition` / EvaluationPolicy**, never
DesignIntent. Changing it: candidate design **same** · compile artifacts
**reusable** · qualification/evidence **change**. Locked.

## 35. Search execution identity

| Change | New `StudyDefinition`? | New `SearchExecutionPolicy`? | New execution? |
|---|---|---|---|
| design space / objectives / constraints / baseline / requirements / evaluation policy | **YES** | — | yes |
| method | no | **YES** | yes |
| budget | no | **YES** | yes |
| seed | no | **YES** | yes |
| re-running the same definition+policy | no | no | **yes** (new attempt) |

Precise enough for caching: **candidate evidence keys on candidate science, never
on the policy.**

## 36. Invalidation matrix

Derived from parent identities (§4), not intuition. `—` = unaffected.

| Change ↓ / Artifact → | PhysInv | Mapping | Topology | Attach | AddrDec | Routes | Resolved | VC | Cert | backend cfg | Evidence | ReqReport | Study/Pareto |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| SYSTEM change | **new** | new | — | new | new | — | — | — | new | — | new | new | new |
| WORKLOAD change | — | — | — | — | — | — | — | **new** | new | new | new | new | new |
| PARALLELISM change | — | **new** | — | new | new | — | — | — | new | — | new | new | new |
| COMMUNICATION change | — | — | — | — | — | — | — | **new** | new | new | new | new | new |
| REQUIREMENTS change | — | — | — | — | — | — | — | — | — | — | **reusable** | **new** | new defn; frontier per §8 |
| PHYSICAL design clock | — | — | — | — | — | — | — | — | — | new | new | new | new |
| MAPPING semantics | — | **new** | — | — | — | — | — | — | new | — | new | new | new |
| FABRIC change | — | — | **new** | new | new | new | new | new | new | new | new | new | new |
| ROUTER arbitration | — | — | — | — | — | — | — | — | new | new | new | new | new |
| MEMORY AddressMap | — | — | — | — | **new** | — | — | — | new | — | — | — | — |
| DESIGN SPACE change | — | — | — | — | — | — | — | — | — | — | per-candidate | per-candidate | **new defn** |
| network evaluation clock | — | — | — | — | — | — | — | — | — | new | **cycles reusable; ns new** | new | new |
| backend profile change | — | — | — | — | — | — | — | — | — | **new** | **new** | new | new |
| qualification semantics | — | — | — | — | — | — | — | — | — | **new** | **old-profile evidence** | new | new |
| metric semantics version | — | — | — | — | — | — | — | — | — | — | **not reusable** | new | new |

## 37. Reuse matrix

| Change class | Verdict |
|---|---|
| hierarchy-only SYSTEM change | **REVALIDATE** — `MappingRelation` may be identical; `MappingArtifact` reissued (context moves) |
| link-width change | **REVALIDATE** — attachment relation identical; `AgentAttachmentArtifact` reissued because the topology parent moves |
| Requirement threshold change | **REUSE AS-IS** measurements; **RECOMPUTE** the report |
| objective direction change | **REUSE AS-IS**; **RECOMPUTE** the frontier |
| objective added, already measured | **REUSE AS-IS** |
| objective added, not measured | **RERUN BACKEND** or `UNMEASURABLE` |
| constraint threshold change | **REUSE AS-IS** observation; recompute status |
| search seed/method change | **REUSE AS-IS** candidate evidence |
| backend profile change | **RECOMPUTE** compile; **RERUN BACKEND** |
| metadata rename | **REUSE AS-IS** everything |

## 38. Migration-authority matrix

| Legacy identity | Single authority | Consumers | Duplicated elsewhere? |
|---|---|---|---|
| legacy agent group index | **SYSTEM** stable identity map | MAPPING, ADDRESS MAP, ATTACHMENT | **no** — Domain I explicitly reuses SYSTEM's map |
| legacy `radix`→`side_length` | **none needed** (§7) | — | n/a |
| legacy parallelism spec | **PARALLELISM** | MAPPING | no |
| legacy `routing_function` | **demoted** (ROUTER-D2) | — | no |
| Phase-9 memory location grammar | **legacy evaluation adapter** | memory lowering | no |
| legacy sweep/synthesis dirs | navigation only | — | no |

**No subsystem may create its own translation table for the same legacy
identity.** Audit: **no duplication found.**

## 39. Metadata law

**Metadata** (never scientific): display names · project title · range `name` ·
candidate table labels · `intent_id` · `schema_version` strings · `*_hash` fields ·
file paths · directory names.

**Verified:** `AddressDecodeEntry.semantic_dict()` deliberately omits `name`, and
`validate_against` states *"Range names are presentation and do not participate:
two design revisions differing only in range labels reuse the same hardware decode
artifact"* (`address_decode.py:203,420`).

**Audit for accidental hashing:** no display field is hashed into a scientific
identity. **Conversely, no real ID is classified as metadata** — `AgentInstanceId`,
`EndpointId`, `CandidateId`, `MetricId`, `RequirementId` are all semantic.

## 40. Canonical ordering law

| Structure | Order semantic? | Rule |
|---|---|---|
| agent groups | no | canonical sort |
| agent instances | no | canonical sort |
| parallel participants | **yes** (rank order) | explicit |
| communication classes | no | canonical sort |
| address ranges | no | `(base, size, target_agent_group, target_endpoint_id)` — enforced |
| routers | no | canonical sort |
| channels | no | canonical sort |
| endpoint seats | **yes** (seat derivation) | explicit |
| mapping bindings | **yes** (rank index) | explicit |
| attachment bindings | no | canonical sort |
| routes | no | canonical sort |
| VC assignments | no | canonical sort |
| optimizer dimensions | no | sorted by name |
| optimizer objectives | **YES** (`min_first_objective` uses `[0]`) | **must be explicit** |
| optimizer constraints | no | one per metric |

**Lexicographic-bug class:** ordering by string representation of an integer id
(`…-1000` < `…-999`). Audit: canonical ordering uses **typed keys** (int base,
int rank), not string sort. `_semantic_key` sorts on ints. **No instance found.**
Optimizer objectives are the one place where order is semantic and **implicit** →
already **OPT-D6**, retained.

## 41. Whole-system capability truth table

Stages per §14: **D**eclarable · de**R**ivable · **V**erifiable · **P**rojectable ·
**E**xecutable · **Q**ualified · evidence-**C**apable · product-**W**ired.

| Feature | D | R | V | P | E | Q | C | W |
|---|---|---|---|---|---|---|---|---|
| Dense static workload | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ |
| Static MoE | ✓ | ✗ | ✗ | ✗ | ✗ | ✗ | ✗ | ✗ |
| Serving dense | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ |
| Serving MoE | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ |
| Mesh | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ |
| Concentrated mesh | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ |
| Torus topology | ✓ | ✓ | ✓ | ✗ | ✗ | ✗ | ✗ | ✗ |
| Torus routed execution | ✓ | ✗ | ✗ | ✗ | ✗ | ✗ | ✗ | ✗ |
| Multiclass communication | ✓ | ✓ | ✓ | ✗ | ✗ | ✗ | ✗ | ✗ |
| Hardware multicast | ✓ | ✗ | ✗ | ✗ | ✗ | ✗ | ✗ | ✗ |
| Broadcast / root-fanout | ✓ | ✗ | ✗ | ✗ | ✗ | ✗ | ✗ | ✗ |
| Multiplane | ✗ | ✗ | ✗ | ✗ | ✗ | ✗ | ✗ | ✗ |
| RCU / in-network reduction | ✗ | ✗ | ✗ | ✗ | ✗ | ✗ | ✗ | ✗ |
| Multiple clock domains | ✓ | ✗ | ✗ | ✗ | ✗ | ✗ | ✗ | ✗ |
| Ramulator standalone | ✗ | ✓ | ✗ | ✓ | ✓ | ✓ | ✓ | ✗ |
| Network+memory coupling | ✗ | ✗ | ✗ | ✗ | ✗ | ✗ | ✗ | ✗ |
| Optimization | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ |
| Serving optimization | ✗ | ✗ | ✗ | ✗ | ✗ | ✗ | ✗ | ✗ |
| Memory optimization | ✗ | ✗ | ✗ | ✗ | ✗ | ✗ | ✗ | ✗ |
| Candidate-owned buffer search | ✗ | ✗ | ✗ | ✗ | ✗ | ✗ | ✗ | ✗ |

## 42. The four Gate-3 items Domain J recorded

| # | Item | Decision |
|---|---|---|
| 1 | Requirement satisfaction in Pareto eligibility | **§8: law B** — orthogonal annotation; a requirement-derived constraint is an explicit study policy |
| 2 | method/budget/seed identity placement | **§9: law B** — `SearchExecutionPolicy`, separate from `StudyDefinition` |
| 3 | arbitration normalization ownership | **§10** — `RouterResourceIntent.canonical_allocator` owns it; identity consumes the canonical result |
| 4 | pre-compile optimization constraint stage | **§11: NOT admitted** — DesignSpace bounds already cover it; a second authority is forbidden |

**None remains commentary.**

## 43. Adversarial verdicts X1–X30

| # | Case | Verdict |
|---|---|---|
| X1 | agent declaration order changes | **no scientific change** — stable ids + canonical ordering (§40) |
| X2 | TP4/EP1 → TP2/EP2, same world size | Parallelism identity moves; `MappingArtifact` moves |
| X3 | mapping changes only | Topology/Attachment stay; the participant→endpoint projection changes |
| X4 | hierarchy-only physical move | relations may remain; context-bound artifacts **reissued** (§37) |
| X5 | mesh concentration 1→2 | Fabric valid; **native BookSim qualification changes** (§13) |
| X6 | mesh→torus | topology derives; **routing unavailable** |
| X7 | single→multi class | §17 stage progression; **not** a global support verdict |
| X8 | arbitration alias spelling changes | **no scientific identity change** after §10 |
| X9 | arbitration policy genuinely changes | `RouterResourceIntent`/`RouterBehaviorArtifact`/evidence change |
| X10 | network clock changes | cycles reuse law; **ns invalidated** (§19) |
| X11 | Requirement threshold changes | **no backend rerun** (§37) |
| X12 | RequirementSet changes under optimization | candidate design identities stable; frontier per **§8 law B** |
| X13 | search seed changes | candidate science unaffected; **new `SearchExecutionPolicy`** (§9) |
| X14 | backend prints a number after certificate failure | **not admissible** (§26) |
| X15 | certificate PASS, profile NOT QUALIFIED | valid canonical design; **no qualified measurement** |
| X16 | canonical full route + first-hop observed | **never `FULL_PATH VERIFIED`** (§27) |
| X17 | Ramulator result + BookSim result | **cannot sum** (§20) |
| X18 | static MoE vs serving MoE | **capability states distinct** (§16) |
| X19 | candidate uses derived VC count as a dimension | **reject** — LOCKED token refusal |
| X20 | candidate uses candidate-owned buffer dimension | **valid per contract; no field exists yet** (§30) |
| X21 | optimizer `radix` vs Fabric semantic naming | **one law** — §7 (implementation `radix`, scientific `side_length`) |
| X22 | AddressMap points to reordered HBM agents | stable `AgentInstanceId` preserves the mapping |
| X23 | address target is a compute agent | **INVALID v4 MemoryIntent** |
| X24 | same integer equals ASTRA `Sys.id` and a logical rank | **no identity collapse** (§5) |
| X25 | frontend recomputes Pareto and disagrees | frontend result **non-authoritative** |
| X26 | frontend recomputes ns from cycles with another clock | **forbidden** (§19) |
| X27 | metadata rename | scientific identities follow §39 — unchanged |
| X28 | compiler policy version changes but outputs coincide | context artifact identity **changes** where the policy is a scientific parent (§29) |
| X29 | qualification profile changes only | canonical artifacts unchanged; historical evidence stays **old-profile evidence** |
| X30 | metric semantics version changes | old observations **cannot silently** satisfy a new requirement/objective |

**D-specific cases added:**

| # | Case | Verdict |
|---|---|---|
| X31 | `intent_id` used as `base_design_hash` | **refused** — disjoint namespaces (D1) |
| X32 | declared affinity contract requested | **no contract exists** (D2) |
| X33 | `OptimizationDefinition` folded into `design_hash` | **refused** — study is above the design (D3) |
| X34 | a NOT-MODELLED concept surfaced as a control | **out of scope** (D4) |
| X35 | a view recomputes a derived value | **forbidden** — projection authority only (D5) |
| X36 | a form pre-check becomes the sole guard | **forbidden** — compile/report retain authority (D6) |
| X37 | a declared type ships without a classification sentinel | **fail closed** (D7) |
| X38 | a per-node hand-authored visual primitive appears | **rejected** — `visual ∈ {1..6}` is machine-validated (D8) |
| X39 | requirement violated, candidate dominates | **stays on the frontier**, annotated (§8) |
| X40 | study re-run with a new seed | same `StudyDefinition`, new `SearchExecutionPolicy`, **evidence reusable** (§9) |

## 44. Cross-domain proof tests

**Existing tests cited (no new suites created):**

| Property | Test |
|---|---|
| candidate identity is content-based, order-independent | `tests/test_optimization_identity_exact.py`, `test_p2_guided_optimization.py::test_identity_ignores_key_order` |
| definition identity ignores declaration order | `test_p2_guided_optimization.py::test_definition_id_ignores_declaration_order` |
| selection=none changes definition identity | `tests/test_optimization_definition_identity.py` |
| Pareto agrees with the sealed gate and a brute oracle | `test_p2_guided_optimization.py::test_agrees_with_sealed_gate`, `test_matches_brute_oracle_on_random_fronts` |
| ties stay ties | `test_p2_guided_optimization.py::test_ties_stay_ties` |
| locked consequences match direct recompilation | `test_p2_guided_optimization.py::test_locked_consequences_match_direct_recompilation` |
| live study view prefixes view hashes; engine identities stay bare | `tests/test_optimize_canonical_cli.py::test_live_study_view_conventions` |
| missing fixture fails closed; non-integral clock refuses | `test_optimize_canonical_cli.py::test_missing_fixture_fails_closed`, `test_nonintegral_clock_refuses_at_the_boundary` |
| address decode realizes the design map; names are presentation | `model/address_decode.py::validate_against` |

**Missing (recorded as debt, not built during planning):**

- a test that `MappingArtifact` identity moves when `MappingPolicy` changes
  (**XDOM-D1**);
- a test that `arbitration` alias spellings produce one `candidate_id`
  (**XDOM-D6**);
- a test that a requirement-violating Pareto member stays on the frontier
  (**XDOM-D4**).

## 45. Gate-3 implementation debt

Narrow, cross-domain only. **Domain-local debt is referenced, not re-listed.**

```text
XDOM-D1  bind MappingPolicy (RANK_ORDER_V1) into MappingArtifact identity
         mapping.py:135 binds {type, schema_version, placements} only
XDOM-D2  bind a VC-assignment semantics identity around VCResourceArtifact
         (the relation correctly has no parent hash; its context-bound wrapper
          RouterBehaviorArtifact binds vc_resource_hash but not the derivation
          policy) — merges with existing VC-D1
XDOM-D3  per-type classification sentinel for every declared type (D7)
XDOM-D4  move requirement satisfaction out of the Pareto eligibility predicate
         into an orthogonal annotated status (§8 law B)
XDOM-D5  split study_definition_id from search_execution_id (§9 law B)
XDOM-D6  canonicalize every dimension through its owning domain before
         CandidateId (merges with OPT-D2; §10, §32)
XDOM-D7  add the three missing cross-domain proof tests (§44)
```

**Referenced, not duplicated:** FAB-D1, FAB-D4, VC-D1, ROUTER-D2, COMM-D1,
OPT-D2…D8, MEM-D1…D5, MEM-EVAL-D1/D2.

## 46. Coherence check against §49

| # | Criterion | Status |
|---|---|---|
| 1 | D1–D8 read from repository, not inferred | **MET** (§0) |
| 2 | all eight have one chosen law | **MET** (§2) |
| 3 | no scientific field has two editable authorities | **MET** (§6, §30) |
| 4 | every compiler-owned science-changing policy identity-bound | **MET as an audit** — 6 bound, 4 recorded (XDOM-D1/D2, FAB-D1/D4, VC-D1) |
| 5 | identifier namespaces explicit | **MET** (§5) |
| 6 | no numeric coincidence used as identity | **MET** (§5) |
| 7 | artifact parentage coherent | **MET** (§4) |
| 8 | relation-vs-artifact preserved | **MET** (§4) |
| 9 | `radix`/side-length reconciled | **MET** (§7) |
| 10 | requirement/Pareto policy explicit | **MET** (§8) |
| 11 | method/budget/seed placement explicit | **MET** (§9) |
| 12 | arbitration canonicalization has one owner | **MET** (§10) |
| 13 | pre-compile constraint policy explicit | **MET** (§11) |
| 14 | certificate/qualification/evidence distinct | **MET** (§26) |
| 15 | expected vs observed distinct | **MET** (§27) |
| 16 | capability stages replace "supported" | **MET** (§14, §41) |
| 17 | static vs serving boundaries intact | **MET** (§15) |
| 18 | static vs serving MoE honest | **MET** (§16) |
| 19 | memory and network not falsely coupled | **MET** (§20) |
| 20 | MetricRegistry is one authority | **MET** (§24) |
| 21 | Requirements and Optimization use admissible evidence consistently | **MET** (§25) |
| 22 | invalidation follows artifact parents | **MET** (§36) |
| 23 | reuse distinguishes four verdicts | **MET** (§37) |
| 24 | migration authorities not duplicated | **MET** (§38) |
| 25 | canonical ordering deterministic | **MET** (§40) |
| 26 | optimizer dimensions map to real domain-owned fields | **MET** (§31) |
| 27 | X1–X30 + D-specific have verdicts | **MET** (§43) |
| 28 | ontology checker has zero pending D1–D8 | **MET** (§48) |
| 29 | PRODUCT workflow planning not begun | **MET** |
| 30 | HTML not begun | **MET** |

## 47. Remaining blockers

**None for Gate-3 coherence.** The four policy-identity gaps (XDOM-D1, XDOM-D2,
FAB-D1, FAB-D4, VC-D1) are **recorded, scoped, and pre-existing** — they are
implementation debt, not contradictions between closed contracts.

**Re-homed to later gates (decided, not deferred):** the product-surface halves of
**D1** (page subject), **D5** (`DesignView` schema), **D6** (form timing) and
**D8** (styling) belong to the product-flow / Guided-Expert / wireframe gates.
They carry **no scientific content**, and Gate 3 was forbidden to do that work.

## 48. Ontology resolution

`pending_decisions` is set to `[]` and replaced by a self-describing `decisions:`
registry carrying each decision's **exact repository title**, owner gate and
resolution — so the machine authority is no longer silent about what it blocked.

---

## 49. Domain verdict

Gate 3's first act was to read D1–D8 rather than accept the brief's framing — and
the framing was wrong. **D1–D8 are not cross-domain scientific laws.** They are
Gate-1 product-surface decisions from `INTENT-ONTOLOGY.md` §5: which layer the page
edits, the `DesignView` schema, form-validation timing, the visual primitive set.
The ontology carried them as bare labels with **no definitions at all**, so the
machine authority could not say what it was blocking. That registry defect is
fixed by writing the definitions into the ontology.

Four of the eight — **D2** (placement stays derived), **D3** (the study definition
sits above the design and never enters `design_hash`), **D4** (every NOT-MODELLED
concept stays out of scope), **D7** (every declared type publishes a fail-closed
classification sentinel) — are genuinely cross-domain and are **decided here**.
The other four are split: Gate 3 decides their **scientific half** (D1's
`intent_id` ≠ `design_hash`; D5's projection authority; D6's compile/report
validation authority; D8's mechanically-frozen `visual ∈ {1..6}`) and **re-homes
the product-surface half**, because doing that work would be product-flow
planning, which this gate is forbidden to start.

One genuine contradiction between closed domains was found. Domain G and Domain J
made contradictory statements about the same field. **Resolved by §7:**
`NocConfig.radix` stays the implementation name; **`side_length` is the scientific
name** for square-grid side `k`; `params["k"]` stays derived; the alias lives only
at the boundary. **No schema migration.**

The silent-policy hunt found **no unrecorded instance**. Ten compiler-owned
policies were audited: six are identity-bound, four are not — and all four were
already recorded as Gate-2 debt (`FAB-D1`, `FAB-D4`, `VC-D1`, `OPT-D2`). Gate 3's
contribution is proving the list is **complete**, plus promoting two
relation-vs-artifact defects that no single domain owned (`MappingPolicy` unbound
in `MappingArtifact`; the VC derivation policy absent from any semantics identity)
to cross-domain debt.

The remaining decisions are the ones with real scientific weight. **Requirement
satisfaction leaves the Pareto eligibility predicate** (§8) — not for UX reasons,
but because a frontier that moves when a customer threshold moves is not a
scientific frontier, and because the optimizer already has a typed mechanism for
"must hold": optimization constraints. **Search method/budget/seed leave the study
definition** (§9) — a seed is an exploration detail, and fusing it into the
question would force evidence re-keying and make two runs of one question look
like two questions. **Arbitration canonicalization is owned by
`RouterResourceIntent`** (§10) — the optimizer must not own an alias rule for a
field it does not own. And **no pre-compile constraint stage is admitted** (§11) —
DesignSpace value sets already bound every pre-compile quantity, so a second
mechanism would create a second authority over one field.

What remains is coherence. Certificate, qualification and evidence are three
independent layers. Capability claims are expressed as eight explicit stages
instead of one "supported" boolean — which is why `TORUS` can be *declarable and
derivable* while being *unroutable*, and why `RAMULATOR` can be *executable and
qualified* while being *not product-wired*. Time domains never cross-compare.
Static and serving MoE stay honestly different. Memory and network stay
disconnected. No missing measurement becomes zero. And the invalidation matrix
follows artifact parents rather than intuition.

**GATE 3 — CROSS-DOMAIN LAWS: PLANNED — COHERENT**
