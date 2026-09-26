# INTENT-PLACEMENT — Domain F specification (Gate 2, closure pass)

Domain rows: `intent-ontology.yaml :: domains.PLACEMENT_INTENT` and the
`MAPPING` subsystem.
Enforced by: `scripts/check_intent_ontology.py`
Supersedes the first-pass audit. **Design closure only** — MAP-D1…D5 not implemented.

---

## 0. The corrected domain model

```text
PLACEMENT INTENT     R0 — CONTRACT NOT AVAILABLE (no user-editable placement contract)
MAPPING              real compiler-derived subsystem
```

```text
PhysicalInventory + Parallelism + MappingSemantics
        ↓ derive_mapping
MappingArtifact
```

**No `PlacementIntentV4 {}` is invented.** An empty scientific object with no
semantics is schema furniture. If an API needs a future slot it may carry
`placement_intent: null` — **null has no scientific identity and no user
semantics.**

Future constraints require a new versioned contract.

## 1. False "Placement Intent" claims removed

| Capability | State |
|---|---|
| automatic deterministic rank→compute mapping | **AVAILABLE** |
| mapping inspection | **AVAILABLE** (derived view) |
| mapping feasibility diagnostics | **AVAILABLE** (typed, §14) |
| fixed / partial placement, pinning | **CONTRACT NOT AVAILABLE** |
| affinity / anti-affinity / co-location / spread | **CONTRACT NOT AVAILABLE** |
| locality / hierarchy-aware constraints | **CONTRACT NOT AVAILABLE** |
| soft preferences | **CONTRACT NOT AVAILABLE** |
| communication-aware / topology-aware placement | **CONTRACT NOT AVAILABLE** |
| placement optimization | **CONTRACT NOT AVAILABLE** |

These are **absent**, not disabled fake controls.

## 2. The mathematical mapping law

For a successful `MappingArtifact` `M`:

```text
∀ participant p:  ∃! compute agent a such that M(p) = a
p₁ ≠ p₂  ⇒  M(p₁) ≠ M(p₂)                    (injective)
codomain: AgentKind.COMPUTE_TILE only
participant_count ≤ eligible_compute_count   (necessary for success)
surjectivity: NOT required
```

Verified: `derive_mapping` refuses `rank_count > compute_instances` —
*"never oversubscribed or modulo-mapped"*; `MappingArtifact` refuses a
duplicate agent and any non-`COMPUTE_TILE` host.

## 3. Idle-agent law — locked

`compute_instances > participant_count` is **valid**. Unused compute instances
remain part of SYSTEM physical inventory and remain eligible for **attachment
derivation, endpoint creation and fabric seat demand**, even with no participant
mapped to them.

```text
rank_count  ≠  endpoint_count
MappingArtifact cardinality does NOT determine fabric endpoint demand.
```

**Future UI must never say "8 ranks = 8 endpoints."**

## 4. Relation vs artifact — the mandatory distinction

```text
MappingRelation        participant_id → agent_instance_id
  relation_hash        depends ONLY on the normalized bindings
        │
        │  stable across hierarchy-only movement
        ▼
MappingArtifact        the compiler-derived mapping produced under a context
  parents: physical_inventory_identity · parallelism_identity
           · mapping_semantics_identity
  bindings[]
  relation_hash
  mapping_hash
```

The **relation** answers *which participant sits on which agent*. The
**artifact** additionally proves **which supply universe and which participant
semantics it was validated against**.

## 5. `physical_inventory_identity` **is** an artifact parent — reversal

The first pass proposed excluding it. **That is reversed.**

An artifact must prove which physical supply universe was validated when it was
derived. Self-describing agent ids do **not** prove that those agents existed in
the source inventory, were eligible, had no duplicate inventory identity, or
shared the relevant system context.

```text
rank 0 → compute_a/0
  before: relation_hash = R,  inventory = P1
  after moving compute_a/0 to another package:
          relation_hash = R,  inventory = P2
  ⇒ relation_hash UNCHANGED, MappingArtifact identity CHANGED
```

**The relation is reusable only after revalidation against the new inventory
context.**

## 6. `parallelism_identity` is a mandatory parent (fixes F8)

`TP4 EP1` and `TP2 EP2` at equal world size currently serialize to **identical
placements**. Binding the parallelism parent fixes it:

```text
same relation, different ParallelismIntent
  ⇒ same relation_hash, DIFFERENT MappingArtifact identity
```

This is **intentional**: the logical participant semantics differ even when the
ordinal assignment coincides.

## 7. `mapping_semantics_identity` is a mandatory parent

`MappingPolicy.RANK_ORDER_V1` exists today only as **provenance** — *"it does
NOT become Fabric or ResolvedFabric identity."* **Promoted** into compiler
scientific identity.

```text
RANK_ORDER_V1 → a future policy
  ⇒ MappingArtifact rederived, even if a particular case yields identical bindings
```

**Algorithm changes may not hide behind the same artifact identity.**

## 8. Mapping policy is **not** user intent

The policy remains **compiler-owned**. `RANK_ORDER_V1` is **never** exposed as a
Design control. If multiple user-selectable policies ever exist, that is a new
planning decision. **Current user declaration: none.**

## 9. Stable agent identity

Target references **`AgentInstanceId`** derived from stable **`AgentGroupId`**
+ instance index — never `group_index` tuple position. This resolves the
inherited SYSTEM S9 blocker at the mapping level.

## 10. Stable participant identity

**Global rank is the canonical participant identifier** (Domain C: a
deterministic bijection of coordinates). No placement-local rank namespace is
created. Conflation between `rank 0 @ TP4/EP1` and `rank 0 @ TP2/EP2` is
prevented by the **parallelism parent**, not by the ordinal.

## 11. Canonical compute-agent ordering

Today: **group declaration order, then instance index** (`build_inventory`
enumerates `cr.agents` then `range(group.count)`).

Target ordering must be independent of UI declaration order:

```text
sort by stable AgentGroupId, then instance_index
```

deterministic · documented · **versioned through `mapping_semantics_identity`**.

## 12. Legacy order preservation — with a precise caveat

V3 agent tuple order **is** semantically meaningful, and the SYSTEM migration
assigns `legacy-agent-group-000`, `-001`, … **in declaration order**.

**Proven:** sorting those zero-padded ids lexicographically reproduces
declaration order — **for up to 999 groups**.

**Caveat recorded:** at 1000+ groups, `"…-1000"` sorts before `"…-999"`
because `'1' < '9'`. The migration must **pad to a width sufficient for the
group count**, or the target ordering must sort numerically.

**If the migrated order cannot reproduce the v3 relation, the migration must
record an explicit identity break — never silently alter placement.**

## 13. Derivation law (target)

```text
1. canonical LogicalParticipants from Parallelism
2. canonical eligible COMPUTE_TILE AgentInstances from PhysicalInventory
3. participant_count > eligible_count → typed infeasibility (§14)
4. participant i → eligible compute agent i
5. normalize bindings
6. compute relation identity
7. bind parents + mapping semantics
8. produce MappingArtifact
```

**No topology. No workload payload. No requirement. No physical clock.**

## 14. Typed mapping refusal

Failure is **not** a second scientific artifact. It is a structured, typed,
machine-readable refusal:

```text
MappingRefusal {
  reason_code
  required_participants
  eligible_compute_agents
  shortfall
  details?
}
```

Reason codes, only those that are real:

```text
INSUFFICIENT_COMPUTE_AGENTS
NO_ELIGIBLE_COMPUTE_AGENTS
INVALID_AGENT_REFERENCE
DUPLICATE_AGENT_ASSIGNMENT
UNSUPPORTED_MAPPING_SCHEMA
```

## 15. Exception vs refusal transport

`MappingError` remains the **internal** exception mechanism. The
compiler/application boundary **translates** it into the typed refusal payload.
Internal functions are **not** rewritten into union-returning style — this is
about typed product semantics, not stylistic rewrites.

## 16. Placement constraints remain unavailable

`FixedPlacement` · `Affinity` · `AntiAffinity` · `CoLocate` · `Spread` · `Pin` ·
`Prefer` are **not** defined in v4.

Ontology: `R0`, decision `out_of_scope_for_current_v4`, future `new_contract`.

Rationale, in one line each: **no solver**, **no declaration contract**, **no
current semantic consumer**.

## 17. Hierarchy is inspection context only

SYSTEM hierarchy exists but MAPPING **does not consume it**. Moving the same
stable `AgentInstance` between chiplet/accelerator/package/node leaves the
**relation** unchanged and changes the **inventory context**:

```text
relation_hash stable · mapping_hash changes (physical inventory parent)
```

A future hierarchy-aware placement would make hierarchy influence the relation
itself. **That is not current v4.**

## 18–22. Non-dependencies, verified

| Change | Relation | MappingArtifact |
|---|---|---|
| communication (payload, class, collectives) | unchanged | unchanged |
| topology (mesh↔torus, link width, routers) | unchanged | unchanged |
| requirement (threshold, metric, enforcement) | unchanged | unchanged |
| physical clock | unchanged | unchanged |
| workload payload / operation graph, same parallelism | unchanged | unchanged |

**Parents deliberately minimal:** no `WorkloadIntent`, no `CommunicationIntent`,
no `RequirementSet`, no topology, no physical. `derive_mapping` consumes
**inventory + parallelism only** — verified.

## 23–24. Serving boundary

`serve_canonical.py:245` calls **the same** `derive_mapping`, so the *relation*
is reused. But serving runs in a **virtual NPU namespace** translated to
canonical ranks/endpoints *"never by numeric coincidence."*

```text
serving instance ≠ virtual NPU ≠ canonical participant ≠ agent ≠ endpoint ≠ ASTRA Sys.id
```

**`serving_instance_id` and `virtual_npu_id` are never added to
`MappingArtifact`.** They belong the serving projection. If serving uses the
canonical mapping only after an explicit projection, that projection is
documented — **"same rank" is never asserted across namespaces.**

## 25. Attachment boundary — preserved

```text
MappingArtifact:        participant → agent
AgentAttachmentArtifact: agent → endpoint
composition:            participant → agent → endpoint
```

**No endpoint in `MappingArtifact`.**

## 26. Endpoint-count independence

Because idle agents are attached, endpoint demand derives from **SYSTEM
inventory** — not `world_size`, not the binding count.

## 27. Certificate chain

`mapping_hash` → `resolved_fabric_hash` → certificate identity, and
`mapping_hash` appears in `results.py`, `comparison.py`, `waved_resources.py`.
**No `MappingCertificate` is invented.**

## 28. Target `MappingArtifact` schema

```text
MappingArtifactV3 {
  schema_version
  physical_inventory_identity
  parallelism_identity
  mapping_semantics_identity
  bindings[] { participant_id, agent_instance_id }
  relation_hash
  mapping_hash
}
```

Where the artifact framework already hashes the canonical dict, **adapt rather
than duplicate hash authorities**. The semantic distinction is what matters:
**relation identity vs context-bound artifact identity.**

## 29. No persisted reverse map

`agent → participant` is **derived** from the injective bindings
(`participant_for_agent(...)`). **One authority.** Both directions are never
serialized without strict equivalence validation.

## 30. Canonical ordering

Bindings serialize in **canonical participant order**. Input order is
irrelevant; physical agent source declaration order must not perturb the target
mapping once SYSTEM stable identity migration has run.

## 31. Same relation, different parent context — the deliberate model

```text
A: inventory P1 · parallelism X · relation R
B: inventory P2 · parallelism X · relation R
   ⇒ A.relation_hash == B.relation_hash
   ⇒ A.mapping_hash  != B.mapping_hash

C: inventory P · parallelism X · relation R
D: inventory P · parallelism Y · relation R
   ⇒ relation hashes may match; artifact identities differ
```

## 32. Relation reuse (optional optimization)

A future compiler may reuse a relation when the context changes **if** all
referenced agents still exist, eligibility is unchanged, participants are
unchanged and mapping semantics are compatible — but reuse must produce a
**newly validated artifact bound to the new parents**. **Never carry the old
artifact hash forward.** Not required for v4.

## 33. Legacy `MappingArtifact` migration requires context

The legacy artifact is `{type, schema_version, placements}` with **no parents**.
Migration must reconstruct the parallelism, physical-inventory and
mapping-semantics parents **from the containing compiled design context**.

**A standalone legacy artifact without its parent design context cannot be
authoritatively upgraded — it requires context or it refuses. Parents are never
invented.**

## 34. Mapping semantics migration

Legacy mappings are tagged `RANK_ORDER_V1` **only if provenance proves they came
from that compiler path**. An imported or manual mapping is **not** labelled
`RANK_ORDER_V1` merely because it happens to match.

## 35–36. Stable agent and parallelism migration

Agent ids migrate through the **single SYSTEM migration map** — no
mapping-specific regeneration; ambiguous source context **refuses**.

Rank placements associate with the **exact historical parallelism shape**.
**Equal world size is insufficient**; the shape is never guessed from rank
count. Unrecoverable shape ⇒ migration refuses, or the legacy artifact is
preserved **without claiming v3 target identity**.

## 37. Relation hash semantics

`relation_hash` covers **participant ids and agent ids only**. Parents and
policy version belong **artifact** identity. That is what makes relation reuse
and context comparison possible. Where the framework already supplies a
canonical `bindings_hash`, **use it** rather than adding a redundant
cryptographic identity.

## 38. Change classes

| Class | Example | Relation | Artifact |
|---|---|---|---|
| `PARTICIPANT_SET_CHANGE` | TP shape change | may change | changes (parallelism parent) |
| `PHYSICAL_ELIGIBLE_SET_CHANGE` | compute agent added/removed | may change | changes (inventory parent) |
| `MAPPING_SEMANTICS_CHANGE` | policy version | may be identical | **changes** |
| `MAPPING_RELATION_CHANGE` | a binding differs | changes | changes |
| `CONTEXT_ONLY_PHYSICAL_CHANGE` | hierarchy-only move | **unchanged** | **changes** |
| topology / requirement / clock | — | unchanged | unchanged |

## 39. Agent addition/removal — no false stability promised

Adding a compute agent **may** change the rank-order mapping depending on the
canonical ordering. If the new agent sorts before an existing one, **rank
assignments move**.

**Stable ids alone do not guarantee relation stability under set changes.**
This is scientifically expected when available supply changes. **No unnecessary
stability is promised.**

## 40. Display rename

If only display metadata changes and the `AgentInstanceId` does not, the
relation is unchanged and the artifact follows **SYSTEM** identity law. **No
local rename semantics.**

## 41. Feasibility diagnostics

```text
required_participants
eligible_compute_instances
shortfall
```

Optional: eligible agent counts grouped by SYSTEM container — **only if it
improves the explanation**. **No hierarchy-based solver claims.**

## 42. Domain naming

```text
PLACEMENT_INTENT   unavailable / future
MAPPING            real / planned coherent
```

The product documentation heading becomes **MAPPING / PLACEMENT BOUNDARY**
rather than implying user placement exists. Repository modules are **not**
renamed.

## 43. **IA consequence: Placement leaves the editable primary flow**

```text
DESIGN (editable)
  System · Workload · Parallelism · Requirements · Fabric · Review · Compile

AFTER COMPILE (inspection)
  Mapping · Attachments · Topology · Routes · VCs
```

**Placement is not an editable primary step.** This is not a loss of
capability — it prevents advertising a placer that does not exist. If
`PlacementIntent` gains real constraints, Placement returns to the editable
flow.

**No empty page with fake knobs.**

## 44. Preflight mapping summary (read-only)

```text
MAPPING
  Logical participants     8
  Eligible compute agents  16
  Mapping policy           Compiler automatic
  Capacity                 Feasible
  Exact mapping            Derived at compile
  Placement constraints    Not available in the current contract
```

## 45. Post-compile mapping inspector

Shows: logical participant · parallel coordinates · physical agent · SYSTEM
hierarchy path. Derived summaries: mapped participants · idle compute agents ·
group locality facts.

**Endpoint, router and route are not in the core mapping relation table** —
cross-linked to Attachments / Fabric.

## 46. Locality facts are derived presentation

Post-compile UI may compute *"TP group spans 2 accelerators"* or *"DP group
occupies 2 nodes"* from parallelism groups + mapping + SYSTEM hierarchy. These
are **structural facts**.

**Never called** *placement quality*, *violations* or *scores* unless a
Requirements/Placement contract defines such a judgment.

## 47. F1–F50 re-evaluated under the split identity model

F7 SYSTEM reorder after stable-id migration → same inventory identity, same
relation and artifact · **F8** TP4/EP1 → TP2/EP2 → relation may be identical,
**artifact differs via the parallelism parent** · F9 mesh→torus → same relation
and artifact · **F26/F27** hierarchy-only move → **relation_hash unchanged,
inventory parent changes, artifact identity changes** · F31 idle compute still
attached → confirmed · **F34** mapping semantics version change → artifact
identity changes even when the relation coincides · F49 legacy positional map
migration → uses the SYSTEM migration authority · **F50** missing migration
context → **refuse**.

## 48. F51–F65

| # | Case | Verdict |
|---|---|---|
| **F51** | same relation, different inventory parent | **same `relation_hash`, different `mapping_hash`** |
| **F52** | same relation, different parallelism parent | same relation hash possible; **artifact differs** |
| **F53** | same parents and relation, semantics version differs | **artifact differs** |
| **F54** | legacy standalone artifact without SYSTEM context | **cannot authoritatively upgrade** |
| **F55** | legacy standalone artifact without a parallelism shape | **cannot infer shape from world size** |
| **F56** | new compute agent sorts before existing ones | relation may change per the documented canonical order |
| **F57** | new idle **non-compute** agent | relation unchanged; inventory parent changes |
| **F58** | HBM agent removed | relation unchanged if no mapped agent affected; inventory parent changes; revalidation required |
| **F59** | a **mapped** compute agent removed | old mapping **cannot validate** against the new inventory |
| **F60** | mapped agent moved to another package | relation same; artifact context changes |
| **F61** | display-only agent label change | follows SYSTEM metadata identity law |
| **F62** | future `PlacementIntent` field seen by an old mapper | **unsupported schema — fail closed** |
| **F63** | empty `placement_intent={}` supplied | **normalize to no intent, or reject** — it must **not** create a distinct identity |
| **F64** | manual mapping claiming `RANK_ORDER_V1` provenance | **provenance mismatch — refuse** |
| **F65** | serving virtual NPU integer equals a canonical rank | **no namespace identity inference** |

## 49. Implementation debt

```text
MAP-D1  stable AgentInstanceId migration — depends on SYSTEM S9 implementation
MAP-D2  MappingArtifact parents: physical inventory, parallelism, mapping semantics
MAP-D3  relation identity vs artifact identity (relation_hash / mapping_hash)
MAP-D4  typed MappingRefusal diagnostics at the compiler/application boundary
MAP-D5  legacy contextual migration (parents reconstructed or refused)
```

**"Implement PlacementIntent" is NOT recorded as debt** — it is a future
capability, not missing implementation of an agreed v4 intent.

## 50. Domain coherence law

```text
PLACEMENT INTENT:  CONTRACT NOT AVAILABLE
MAPPING:           PLANNED — COHERENT
```

The ontology records `PLACEMENT_INTENT` as R0/out-of-scope and `MAPPING` as a
planned derived subsystem. The document verdict uses the combined form.

## 51. Coherence criteria

1. no empty scientific `PlacementIntent` invented — **MET**
2. MAPPING explicitly compiler-derived — **MET**
3. relation and cardinality exact — **MET** (§2)
4. injectivity and idle semantics exact — **MET** (§2, §3)
5. `COMPUTE_TILE` eligibility exact — **MET**
6. stable `AgentInstanceId` target defined — **MET** (§9)
7. stable participant identity reused — **MET** (§10)
8. canonical ordering defined — **MET** (§11, §12)
9. parallelism identity is a parent — **MET** (§6)
10. physical inventory identity is a parent — **MET** (§5)
11. mapping semantics identity is a parent — **MET** (§7)
12. relation vs artifact identity distinguished — **MET** (§4)
13. non-dependencies explicit — **MET** (§18–22)
14. serving namespace boundary intact — **MET** (§23–24)
15. attachment boundary intact — **MET** (§25)
16. typed feasibility refusal defined — **MET** (§14)
17. legacy migration requires authoritative context — **MET** (§33–36)
18. F1–F65 verdicts — **MET**
19. MAP-D1…D5 recorded — **MET**
20. FABRIC not begun — **MET**

## 52. Domain verdict

The first pass proved there is **no placement intent**. This pass stops treating
that as a gap to fill and turns it into the architecture: `PLACEMENT_INTENT` is
**CONTRACT NOT AVAILABLE**, and **MAPPING is a real, coherent, derived
subsystem**.

The identity model is now correct in both directions:

- **the relation** (`participant → agent`) is stable across hierarchy-only
  movement, so it can be compared and reused;
- **the artifact** binds the physical-inventory, parallelism and
  mapping-semantics context, so an artifact validated against one supply
  universe can never masquerade as one produced against another, and
  `TP4 EP1` can never be confused with `TP2 EP2` at equal world size.

Also locked: `COMPUTE_TILE`-only eligibility, injectivity, idle-agent legality
with **endpoint demand following inventory rather than rank count**, a typed
refusal contract, and a migration that **refuses rather than inventing parents**
or guessing a parallelism shape.

**Product consequence:** Placement disappears as an editable primary step. The
compiled Mapping inspector becomes the rich surface instead — because the
mapping is real, deterministic, serving-reusable and scientifically meaningful.

**PLACEMENT / MAPPING: PLANNED — COHERENT**

Per Gate 2's rule, FABRIC is not begun.
