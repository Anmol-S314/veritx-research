# INTENT-COMMUNICATION — Domain D specification (Gate 2, closure pass)

Domain row: `intent-ontology.yaml :: domains.COMMUNICATION_INTENT`
Enforced by: `scripts/check_intent_ontology.py`
Supersedes the first-pass audit. **Design closure only** — COMM-D1 not implemented.

---

## 0. Reality header

| Concept | Reality | Evidence |
|---|---|---|
| traffic class | **R2 bare `str`, no type** | `CollectiveIntent.traffic_class` |
| class registry | R3 derived from collectives | `derive_v3_traffic_classes` |
| per-op class sidecar | R2, **COLLECTIVE-only**, sorted by op id | `traffic_class_by_operation` `intent_lowering.py:104` |
| **message provenance** | **R2 — every message carries `operation_id`** | `messages.py:224,238,247` |
| per-message class | **R0 — BLOCKED** | §3 |
| class → VC | R3 derived | `traffic_class_to_vcs` |
| routing class | R2, distinct | `DOR_XY` / `ANYNET_MIN_HOPS` |
| plane | R2, exactly one | `PlaneComposition.SINGLE_PLANE` |
| multicast (semantic) | R2, lowered as source replication | `messages.py:243` |
| multicast (hardware) / RCU / multiplane | R3 refused | `resolved_fabric.py:255-268` |
| serving class | R2 hardcoded single | `serve_canonical.py:163` |

---

## 1. Domain scope — narrow, and locked

Domain D owns **`CommunicationClass`** and **the assignment of
communication-producing semantic operations to those classes**. Nothing else.

**Not owned:** collective kind · collective algorithm · payload bytes ·
participants · groups · routes · routing algorithms · planes · VC ids ·
VC count · arbitration · buffer depth · QoS requirements · latency ceilings ·
bandwidth floors · multicast hardware · RCU · packetization.

```text
Workload operation → CommunicationIntent binding → Bound operation
  → Logical communication lowering → Logical message + class
  → Physical traffic + class → VC assignment → backend / evidence
```

**No class identity may disappear silently along this chain.**

## 2. CommunicationIntent is real — but narrow

**Decision:** Communication Intent **is** an independent domain, because
traffic class affects downstream VC assignment independently of workload
operation type.

```text
CommunicationIntentV4 { classes[], bindings[] }
```

No more unless evidence demands it.

**Traffic-class ownership moves off WORKLOAD.** WORKLOAD owns the semantic
operation; COMMUNICATION owns the operation→class binding. Canonical v4 has
**one authority**. `WorkloadIntentV4` must not carry a second authoritative
`traffic_class`; legacy fields remain readable through migration only.

## 3. Typed class identity

```text
CommunicationClassId = a stable non-empty string (the class_id)

CommunicationClass {
  class_id        # semantic identity
  display_name?   # presentation metadata, excluded from identity
  description?    # presentation metadata, excluded from identity
}
```

**Not added** (no consumer): priority · latency sensitivity · plane · VC ·
routing · isolation.

## 4. Legacy string migration

Legacy traffic-class strings are **scientifically meaningful** (VC assignment
consumes them), so they cannot be demoted to display names.

| Rule | Value |
|---|---|
| mapping | legacy string → `class_id` **verbatim** when it satisfies the grammar |
| normalization | only if the legacy schema already normalized it |
| collisions | **proved**; a collision is a migration refusal |
| original value | preserved in migration metadata when any normalization occurs |
| silent transforms | **forbidden** — no lowercase, trim or slugify that merges distinct values |

## 5. Display-label law

`class_id` is semantic. `display_name` is presentation.

```text
change display_name → CommunicationIntent identity UNCHANGED
change class_id     → semantic identity CHANGED
```

The UI may show *Expert dispatch* while the technical identity stays
`expert_dispatch`.

## 6. Binding object

```text
CommunicationBinding {
  target_operation_id   # stable Workload operation id
  class_id
}
```

**Never bound by** array index · collective position · label spelling ·
graph traversal order. Reordering operations or bindings must not change
semantics.

## 7. Binding totality

**Target invariant:**

- every operation that lowers to network communication has **exactly one**
  binding;
- every non-network operation has **none**.

Authoring may say `AUTO`; **canonicalization materializes explicit bindings**.
The canonical scientific state contains **no invisible default class**.

Feasible against current contracts: every message already carries
`operation_id`, and the sidecar is already total over COLLECTIVE operations
(§37).

## 8. No implicit default routing class

Historical hidden default-routing semantics are **not** reintroduced.

If a legacy workload has no explicit class, the **versioned** defaulting
policy materializes a real class — conceptually `CommunicationClassId("default")`
— only because current semantics genuinely treat an omitted class as one
common class (`DEFAULT_TRAFFIC_CLASS = "DEFAULT"`). After normalization the
canonical object is **explicit**.

## 9. One operation → one class

**Locked for v4.** One semantic network operation → exactly one class. If
lowering emits N logical messages, **all N inherit the operation's class**.

This is the inheritance law. Multi-class message splitting would require a
new versioned contract and is **not pre-designed**.

## 10. LogicalCommunicationArtifactV3 — the missing seam

```text
LogicalCommunicationArtifactV3 {
  schema_version
  workload_identity
  parallelism_identity
  communication_identity
  lowering_semantics_identity
  messages[]
  artifact_hash
}

LogicalMessageV3 {
  message_id
  semantic_operation_id
  bound_operation_id
  source_participant_id
  destination_participant_id
  payload_bytes
  communication_class_id
}
```

**Excludes:** physical endpoint ids · routers · route · VC assignment ·
BookSim node · plane. **Topology-independent.**

This is a **versioned successor** to `LogicalMessageArtifactV2`, **not** a
parallel authority and **not** another sidecar.

## 11. Message identity law

`message_id` derives from **scientific parents**, never backend trace position.

| Property | Required |
|---|---|
| stable across serialization reorder | yes |
| stable across backend execution | yes |
| stable when physical placement changes | yes |
| changes when semantic communication changes | yes |
| changes when source/destination participant changes | yes |
| changes when payload changes | yes |

**Decision on class participation:** `communication_class_id` participates in
**artifact identity only**, not in `message_id`. Rationale: the class is a
*classification of* a message, not part of *which message* it is; making it
part of `message_id` would change message identity when a purely
policy-level decision changes, breaking stable references from evidence and
requirements. The class change is still visible — through
`communication_identity` in the artifact's parent chain.

## 12. Operation provenance

Every message retains **`semantic_operation_id`** and **`bound_operation_id`**
where both exist, so `Workload operation → Bound operation → Logical messages`
stays navigable. Studio and evidence must never reverse-engineer parentage
from message names.

## 13. PhysicalTraffic propagation

```text
LogicalCommunicationArtifactV3 + Mapping + Attachments + Fabric
        ↓
PhysicalTrafficArtifact
```

Physical traffic **preserves `message_id` and `communication_class_id`**
while adding physical endpoint information. **The current `MessageTraffic`
observability gap is removed in the target design** — the class is carried,
not looked up.

## 14. No duplicate sidecar after v3

`traffic_class_by_operation` is **transitional**. After V3:

- class travels **inside each message**;
- the operation→class binding remains the **intent** authority;
- the message class is **derived provenance**;
- sidecars survive only as compatibility projections.

Never two authorities.

## 15. VC-assignment consumption

```text
CommunicationIntent binding → message.communication_class_id
  → physical_traffic.communication_class_id → VCAssignment
```

VC assignment **must not** query Workload or reconstruct classes from
operation names. One authority.

## 16. Route independence

Preserved from the audit: **traffic class does not affect route derivation**
(`derive_route` reads nothing from the request). Changing a class must not
change the route artifact. Route and VC assignment are **separate derived
decisions**.

## 17. Arbitration independence

Arbitration is global (`NocConfig.arbitration`). **No per-class arbitration
semantics.** `CommunicationClass` has no scheduling-priority property. Any
future version belongs ROUTER.

## 18. Multicast stays outside

Capability truth preserved: semantic/source-side multicast is
declarable and lowered through **replication to unicasts**; hardware
multicast is **not routable, verifiable or executable**. No multicast class
feature is introduced. Multicast is **orthogonal** to traffic classification.

## 19. Broadcast stays semantic WORKLOAD

Broadcast is a real semantic collective with `ROOT_FANOUT` lowering owned by
compiler/lowering semantics. Domain D may **classify** a broadcast operation;
it does not own broadcast semantics.

## 20. RCU stays outside

RCU / in-network reduction is a **FABRIC / ROUTER** capability. Domain D may
classify the *original semantic reduction communication*; it never requests
physical RCU execution. **No `use_rcu` here.**

## 21. Multiplane stays outside

`PlaneComposition` has one member. Multiplane is unsupported by schema and
canonical fabric. **No class→plane binding in v4.** Ownership revisited after
FABRIC planning.

## 22. Glossary retained

`CommunicationClass` is **not** synonymous with `VirtualNetwork` (R0),
`RoutingClass`, `VCClass` (not a separate concept), `VCId`, or `Plane`. It is
semantic classification consumed by downstream resource assignment.
Nothing more.

## 23. Static/serving comparability — not comparable

| | Static | Serving |
|---|---|---|
| classes | per-operation | hardcoded single `"default"` |

**Locked: not comparable today.** Do not force a shared identity in this
closure.

**Future contract:** `ServingCommunicationProjection` may classify runtime
serving operations into canonical class ids — requires an explicit serving
adapter contract. Marked **FUTURE CONTRACT**, not current parity.

## 24. Serving default class

Serving's `"default"` is a **serving implementation limitation**, not evidence
that canonical CommunicationIntent should have one class.

```text
SERVING CLASSIFICATION: single-class only today
STATIC MULTI-CLASS TARGET: independent capability
```

## 25. Evidence propagation

Required chain: semantic operation → logical message → physical traffic →
VC assignment → backend input/evidence.

**Known adapter gap:** `MessageTraffic` drops `traffic_class`; ASTRA carries
it. The target removes the gap at the physical layer. **Where BookSim/ASTRA
evidence cannot yet preserve the canonical class id end to end, the exact
adapter gap is recorded — class identity is never synthesized in frontend
analysis.**

## 26. Identity parent chain

```text
LogicalCommunicationArtifactV3 parents:
  WorkloadIntent identity · ParallelismIntent identity
  · CommunicationIntent identity · lowering/compiler-semantics identity
```

**Excluded:** Fabric · Placement · Mapping · Topology — logical communication
is **topology-independent**. `PhysicalTrafficArtifact` adds those physical
parents later. This separation is the point.

## 27. Canonical ordering

- classes sorted by `class_id`
- bindings sorted by `target_operation_id`

Reordering UI rows must not move scientific identity (D41, D42).

## 28. Unused classes — INVALID

A declared class with **zero bindings** is **INVALID**.

Rationale: an inert class would move `CommunicationIntent` identity **without
changing execution** — decorative scientific state, which the design rules
forbid. Canonicalization normalizes it away or refuses.

## 29. Unknown-class reference

Binding → missing class: **INVALID**, fail closed during intrinsic
CommunicationIntent validation. Never deferred to VC assignment.

## 30. Duplicate bindings

Same network-producing operation bound twice: **INVALID**. No last-write-wins.

## 31. Missing binding

Under explicit totality: a network-producing operation without a binding is
**INVALID after canonicalization**. The authoring/preset layer fills defaults
*before* canonical object creation.

## 32. Non-network binding

Binding a COMPUTE-only operation: **INVALID** — cross-domain validation
(`WorkloadIntent ⊕ CommunicationIntent`).

## 33. One-member collective interaction

Domain C refuses one-member communication. Therefore:

```text
CommunicationIntent: VALID
bound / lowering stage: REFUSED for one-member communication
```

**Class validation never depends on group size.**

## 34. Class targetability

`CommunicationClassId` is a stable targetable object. Domain E may say
`target: communication_class: expert_dispatch`. **No requirement values in
the class.**

## 35. Migration from per-collective classes

```text
legacy: collective.traffic_class = X
  → WorkloadIntentV4: collective semantics only
  → CommunicationIntentV4: class X declared + binding operation_id → X
```

Many operations sharing X ⇒ **one declaration, many bindings**. Explicit
operation bindings are preferred for v4 because they are unambiguous.

## 36. Migration from the single-class artifact — proven lossless

| Source | Rule |
|---|---|
| single-class artifact | every message receives that same `class_id` |
| multi-class sidecar + message parent | each message receives the class bound to **its parent operation** |

**Determinism proof:** every message already carries `operation_id`
(`messages.py:224,238,247`), and the sidecar is **total and sorted over
COLLECTIVE operations** (`intent_lowering.py:104`). So
`message.operation_id → sidecar → class_id` is a total function for every
message that can exist in a multi-class graph today (multi-class arises only
from collectives). **No inference by message ordering is required.**

## 37. Provenance audit — the implementation seam is located

**Verified:** `LogicalMessage.operation_id` is present for **all three**
message-producing branches (COLLECTIVE, P2P, MULTICAST). The sidecar is
COLLECTIVE-only, but today P2P/MULTICAST inherit the artifact-wide class,
which equals the unified collective class — so no ambiguity exists in any
graph the current code accepts.

**Producer change required:** the message builder must accept a
`class_by_operation` map covering **every** network-producing kind (not just
COLLECTIVE) and stamp `communication_class_id` per message. That is COMM-D1.

**Conclusion: provenance is feasible; the domain is not blocked.**

## 38. Artifact versioning

A **new version** carries per-message classes. Old readers **migrate safely
or reject explicitly**. A v2 reader encountering v3 **fails closed** — it must
never deserialize v3 as v2 while discarding classes.

## 39. Current pipeline behaviour until COMM-D1 lands

Planning coherence ≠ current engine support. Until the artifact exists:

```text
multi-class static evaluation: REFUSED
```

Future UI must show **MULTI-CLASS EVALUATION — NOT AVAILABLE IN CURRENT
ENGINE**, never implying design support is executable.

## 40. Current UI policy

```text
Guided communication surface: READ-ONLY
Expert class editing: DISABLED / NOT AVAILABLE
Reason: the pipeline cannot evaluate multi-class canonical messages
```

Prefer **refusal before edit/compile** over letting users draft intent the
product cannot carry.

## 41. Future UI shape

```text
COMMUNICATION
  Classification      AUTO / explicit
  Classes             Tensor parallel · Expert dispatch · Expert combine
  Bindings            12 communication operations · 12 classified
  Execution support   per-message classes SUPPORTED · VC assignment SUPPORTED
                      route influence NONE · multiplane UNSUPPORTED
                      hardware multicast UNSUPPORTED · RCU separate fabric capability
```

No full networking-policy page. No routes, VC ids, hops or packets.

## 42. Change classes

| Class | Fields |
|---|---|
| **CLASS_IDENTITY** | `class_id` |
| **CLASS_BINDING** | `target_operation_id`, binding→class |
| **PRESENTATION_METADATA** | `display_name`, `description` |

| Change | CommunicationIntent | LogicalCommunication | PhysicalTraffic | VCAssignment | Route | Workload | Parallelism |
|---|---|---|---|---|---|---|---|
| display name | unchanged | unchanged | unchanged | unchanged | unchanged | unchanged | unchanged |
| class id | changes | changes | changes | changes | **unchanged** | unchanged | unchanged |
| binding A→B | changes | changes | changes | changes | **unchanged** | unchanged | unchanged |
| payload | unchanged | changes (via Workload parent) | changes | stale | stale | changes | unchanged |
| TP shape | unchanged | changes (via Parallelism parent) | stale | stale | stale | unchanged | changes |
| topology | **unchanged** | **unchanged** | stale | stale | stale | unchanged | unchanged |

## 43. D1–D40 re-evaluated

D1 authoring default → **canonical form must materialize an explicit binding** ·
D2 two ops same class → VALID · D3 same kind, different classes → VALID ·
D4 display name → identity unchanged · D5 class id → identity changes ·
D6 missing class → INVALID · D7 unused class → **INVALID (§28)** ·
D8 payload change → class unchanged, logical changes · D9 TP change → class
unchanged · D10 topology change → communication unchanged ·
D11 generic EP ALLTOALL vs EXPERT_DISPATCH → **semantically distinct
independent of class** · D12 dispatch/combine different classes → VALID ·
D13 static/serving → **NOT COMPARABLE** · D14 broadcast → VALID ·
D15–D17 multicast → semantic VALID, lowered as replication, **routing
UNSUPPORTED** · D18–D19 RCU → UNSUPPORTED, not this domain · D20–D21
class→plane → **not part of v4** · D22 two classes share a VC →
communication VALID; derived assignment may be insufficient for later
isolation requirements · D23 cross-class VC transition → **VC verification
concern** · D24 route algorithm change → communication unchanged ·
D25 RING→TREE → CommunicationIntent unchanged · D26 packetization change →
communication identity unchanged · D27 priority → not introduced ·
D28–D31 wrong domain (requirements / VC / route / plane) · D32 unknown class
→ fail closed · D33 reordered mappings → same identity · D34 static/serving
shared class → not claimed · D35 **class absent in physical/evidence records
→ target artifact/adapter gap** · D36 one-member → class well-formed, lowering
refuses · D37 PP adjacency → cannot be invented · D38 memory class → boundary
verdict · D39 class→plane nonexistent plane → cross-domain refusal ·
D40 policy omitted → **authoring normalization produces explicit canonical
bindings**.

## 44. Adversarial cases D41–D55

| # | Case | Verdict |
|---|---|---|
| **D41** | two bindings reordered | **same CommunicationIntent identity** |
| **D42** | classes reordered | same identity |
| **D43** | same class id, display name changed | same scientific identity |
| **D44** | operation changes class A→B | communication identity + class-sensitive downstream change |
| **D45** | payload changes, binding unchanged | CommunicationIntent unchanged; logical changes via Workload parent |
| **D46** | TP shape changes, binding unchanged | CommunicationIntent unchanged; multiplicity changes |
| **D47** | topology changes | CommunicationIntent **and** LogicalCommunication unchanged |
| **D48** | message class lost during physical projection | **hard validation failure** |
| **D49** | VC assignment reconstructs class from an operation label | **forbidden architecture** |
| **D50** | legacy multi-class sidecar maps every message by parent operation | **lossless migration** |
| **D51** | legacy message cannot be mapped to a parent operation | **refusal — never guess** |
| **D52** | old single-class artifact migrated to per-message classes | **lossless** |
| **D53** | v2 reader encounters v3 per-message classes | **explicit unsupported-schema refusal** |
| **D54** | serving `"default"` compared with static `"default"` | **not automatically comparable** — same spelling is insufficient |
| **D55** | class assigned to a COMPUTE operation | **cross-domain INVALID** |

## 45. Implementation-debt record

```text
COMM-D1: per-message communication-class artifact

Scope:
  - versioned logical message schema (LogicalCommunicationArtifactV3)
  - per-operation provenance on every network-producing kind
  - per-message communication_class_id
  - physical-traffic propagation (removes the MessageTraffic gap)
  - VC-assignment consumption from the artifact
  - evidence propagation (ASTRA / BookSim adapter gap)
  - migration from the single-class artifact and the COLLECTIVE-only sidecar

Linked from:
  - Communication domain (this document)
  - Evaluate capability surface
  - Studio capability/refusal view
```

**Not hidden in comments.**

## 46. Coherence decision

The missing artifact has a **precise, versioned, non-duplicative target
contract** (§10), and **message-parent provenance is resolved** (§36, §37) —
every message already carries `operation_id`, and the sidecar is total over
the only kind that can produce multi-class graphs today.

This follows the same discipline as SYSTEM hierarchy and static MoE:

```text
ontology coherence  ≠  current implementation completeness
```

Current execution remains **single-class only**; that is a recorded
capability gap (COMM-D1), not an incoherence in the boundary.

## 47. Domain verdict

Domain scope locked narrow (classes + bindings) · traffic-class ownership
moved off WORKLOAD with one authority · typed class identity with an
id/name split · deterministic, collision-safe legacy migration ·
explicit-totality binding law with canonicalization materializing defaults ·
no implicit default routing class · one-operation→one-class inheritance law ·
`LogicalCommunicationArtifactV3` defined as a **versioned successor, not a
sidecar** · message identity law with the class participating in **artifact**
identity only, justified · operation provenance preserved · physical-traffic
class propagation mandated · sidecar demoted to a compatibility projection ·
VC assignment given one authority · route and arbitration independence
preserved · multicast, broadcast, RCU, multiplane and vnets kept outside ·
static/serving non-comparability locked with a future contract ·
evidence-propagation gap recorded · parent chain excludes physical layers ·
canonical ordering defined · unused-class, unknown-class, duplicate-binding,
missing-binding and non-network-binding all fail closed · one-member
interaction correct · class targetability prepared for Domain E · both
migrations proven · **provenance feasibility proven** · versioning fails
closed · current-engine behaviour and UI policy explicit · change classes and
invalidation complete · **D1–D55 all carry verdicts** · **COMM-D1 recorded**.

**COMMUNICATION INTENT: PLANNED — COHERENT**

Per Gate 2's rule, REQUIREMENTS is not begun.
