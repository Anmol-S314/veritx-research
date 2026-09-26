# INTENT-FABRIC — Domain G specification (Gate 2, closure pass)

Domain row: `intent-ontology.yaml :: domains.FABRIC_INTENT`
Enforced by: `scripts/check_intent_ontology.py`
Supersedes the first-pass audit. **Design closure only** — FAB-D1…D7 not implemented.

---

## 0. Audited reality — locked

Current attachment is **deterministic compiler policy** · routers traversed in
**router-id order** · seats `0..capacity-1` · agents in **canonical NodeInventory
order** · **not an optimizer** · attachment occurs **after topology** · topology
construction is canonical · channels are **directed** · a bidirectional link is
**two channels** · router/channel ids deterministically assigned ·
**concentration = `Router.seat_capacity`** · every `AgentKind` consumes one
endpoint · **idle compute agents still consume endpoints** · no agent
unattached · no endpoint shared · unused seat capacity **implicit** · absolute
bandwidth is **not** Fabric intent · network clock belongs **EVALUATION** ·
multiplane is **not** v4 · arbitration / RCU / hardware multicast are **not**
Fabric topology intent.

## 1. Corrected artifact dependency graph

```text
PhysicalInventory ──► MappingArtifact
FabricIntent ──► TopologyArtifact
PhysicalInventory + TopologyArtifact + AttachmentSemantics
        ──► AgentAttachmentArtifact
MappingArtifact + AgentAttachmentArtifact
        ──► participant → endpoint projection
```

This replaces the earlier oversimplification that attachment was
SYSTEM-derived alone. Applied consistently to Domains F and G.

## 2. `FabricIntentV4` — typed

```text
FabricIntentV4 {
  topology: MeshIntentV4 | TorusIntentV4
  link_width_bits: int
}
MeshIntentV4  { side_length: int, concentration: int }
TorusIntentV4 { side_length: int, concentration: int }
```

**Excluded** (verified non-Fabric): arbitration · RCU · VC count/ids · routing
path · network clock · absolute bandwidth · plane count · hardware multicast ·
output formats · obfuscation.

**No `parameters: dict`.** Unknown variant fails closed.

## 3. `radix` is removed from user intent

Audited semantics: **`radix = k`**, the **grid side length**, and
`router_count = k²`. It is **not** the router degree.

**Target name: `side_length`.** The misleading `radix` does not survive in the
target product contract or primary UI.

```text
legacy radix → target side_length   (lossless)
```

## 4. Shape does not generalize

`_grid_adjacency(k, wrap)` iterates `for y in range(k): for x in range(k)` —
**strictly square `k×k`**. The native projection refuses non-square:
*"certified mesh-DOR covers square k x k meshes only."*

**No rectangular `(rows, cols)` shape is introduced.** The schema reflects
current scientific capability.

## 5. `MeshIntent` — exact law

```text
routers_needed = ceil(endpoint_count / concentration)
k = side_length if given else max(1, ceil(sqrt(routers_needed)))
require k*k*concentration >= endpoint_count
router_count    = k*k
seat_capacity   = k*k*concentration
coordinates[r]  = (r % k, r // k)          # (column, row), fixed
channels        = directed, dense, sorted (src, src_port, dst, dst_port)
ports           = local seats 0..concentration-1, then link ports ascending
self-loops      = REFUSED
```

**All derived fields stay derived.** `router_count` is never editable.

## 6. `TorusIntent` — staged capability

| Stage | State |
|---|---|
| intent validity | **VALID** |
| topology materialization | **SUPPORTED** |
| routed execution | **NOT AVAILABLE** in the canonical route path |

**Torus intent is not INVALID because routing is unavailable.** Capability is
staged, never flattened to "unsupported" or "supported".

## 7. `TopologyArtifact` means physical topology, not connectivity

`width_bits` is a `DirectedChannel` field and participates in `topology_hash`.
Therefore:

```text
TopologyArtifact = canonical physical network topology INCLUDING channel properties
```

Locked terminology. **No split of the artifact.**

## 8. `TopologyStructureView` — derived projection

A read-only projection of **routers · coordinates · channel connectivity · seat
capacities**, excluding width. **Not an authority.**

A `256 → 512` bit change may preserve the structural projection while moving
`topology_hash`. Acceptable and explicit.

## 9. `TopologySemanticsIdentity`

Compiler-owned construction rules — **router enumeration · coordinate
assignment · port assignment · channel ordering · seat ordering · PhysicalLink
grouping** — get an explicit semantics identity.

```text
FabricIntent + TopologySemanticsIdentity ⇒ identical TopologyArtifact
```

A release that changes enumeration semantics **must** move the derivation
identity.

## 10. Link-width law

Positive integer **bits**. Alignment is validated **only** where it is a Fabric
intrinsic rule; otherwise the packetizer refuses downstream.

```text
width change → FabricIntent changes · TopologyArtifact changes
             · packetization stale · backend config/evidence stale
             · structural connectivity unchanged
```

## 11. Absolute bandwidth stays outside intent

`bandwidth = width × clock`, and **the clock is EVALUATION**. No
`bandwidth_gbps` in `FabricIntent`.

**Before evaluation the UI shows width, never a fabricated Gbps.**

## 12. Stable seat identity

```text
EndpointSeatId ≡ (router_id, local_seat_index)
```

Deterministic · derived entirely from `TopologyArtifact` · **independent of
agent order and attachment order** · stable under serialization reorder.

**Never** attachment array position.

## 13. Stable endpoint identity

`endpoint_id = i` (positional over canonical inventory order) **must not remain
target scientific identity**.

```text
EndpointId is derived from the topology seat it occupies.
```

An endpoint is a **physical fabric namespace** — never derived from agent
position, mapping rank, or array position.

## 14. Endpoint vs attachment

```text
Endpoint / seat : the physical injection location in the topology
Attachment      : the relation agent → endpoint
```

Changing which agent occupies a seat **does not redefine the seat**. Same
relation-vs-context discipline as Mapping.

## 15. `AgentAttachmentRelation`

```text
agent_instance_id → endpoint_id
attachment_relation_hash   # normalized bindings only
```

Distinguishes *same agent→seat assignment* from *the same assignment produced
under another topology/inventory context*.

## 16. `AgentAttachmentArtifact` — context-bound

```text
AgentAttachmentArtifactV? {
  schema_version
  physical_inventory_identity
  topology_identity
  attachment_semantics_identity
  bindings[]
  relation_hash
  attachment_hash
}
```

Adapt to the existing artifact framework rather than duplicating hash
machinery.

## 17–18. Why inventory and topology are parents

**Inventory:** agent ids alone do not prove the inventory was complete, the
agents valid, the set free of omissions or illegal duplicates.

**Topology:** `router 3 / seat 0` under another topology is **not** the same
seat. Topology identity is a mandatory parent.

## 19. `ATTACHMENT_ORDER_V1`

The current deterministic policy is **scientifically consequential**:

```text
ATTACHMENT_ORDER_V1: router traversal order · seat traversal order · agent ordering
```

**Compiler-owned. Never user intent.** Changing it **must** move
`AgentAttachmentArtifact` identity even when a small example happens to yield
the same relation.

## 20–21. Canonical orders — one authority each

**Agent order:** the **same** authoritative SYSTEM ordering law used by Mapping.
**No competing agent-sort convention.**

**Seat order:** router ids ascending, then seat indices ascending. Part of
attachment semantics — **never** inferred from dict iteration. Deterministic
tests required.

## 22. Capacity law

```text
total seat capacity = Σ router.seat_capacity      (k² × concentration for square)
required seats      = inventory.agent_count       (all AgentKinds, one each)
success             ⇔ agent_count ≤ total seat capacity
```

## 23. Typed capacity refusal

```text
FabricCapacityRefusal {
  reason_code
  required_endpoints
  available_seats
  shortfall
  topology_summary
}
```

Internal exceptions may remain; the **application/compiler boundary exposes
machine-readable semantics**.

## 24. Invalid vs insufficient — never one generic error

| Case | Verdict |
|---|---|
| `side_length = 0` / `concentration = 0` | **INVALID** intent |
| `agent_count > seat capacity` | **valid inputs · FABRIC JOIN UNSATISFIABLE** |
| unsupported topology family | **UNSUPPORTED** |
| unknown schema | **INVALID / unsupported schema** |
| native-projection domain violation | **`SemanticLoss`** (the backend's own typed refusal) |

## 25. Unused seats stay implicit

No placeholder empty endpoints are serialized.

```text
unused_seat_count = seat_capacity - endpoint_count    # read-only derived
```

## 26. Every agent receives exactly one endpoint

**v4 law:** `∀ AgentInstance: exactly one endpoint`. No unattached agents, no
shared endpoints. The relation is **injective** agents → physical seats.

**All kinds** — compute · HBM · NIC · peripheral · UCIe. **No exception
exists.**

## 27. Idle compute endpoints

An idle compute agent has **no mapped participant** but **is attached**.
**It is never removed** because no rank currently uses it — critical for fabric
node count, backend projection, qualification and future traffic capability.

## 28. **FAB-D6 resolved — the backend law**

### 28.1 Two mutually exclusive certified projections

```text
CERTIFIED_BOOKSIM_ANYNET_V1        explicit AnyNet graph from topology + attachment
CERTIFIED_BOOKSIM_MESH_DOR_XY_V1   native mesh DOR — ONLY inside a narrow proven domain
```

### 28.2 The native mesh-DOR domain — all must hold

```text
family == MESH · every router seat_capacity == 1 · square k×k grid
identity-prefix attachment: endpoint ids dense 0..E-1 AND endpoint i → router i (E ≤ N)
route realizes DOR_XY AND every VC binds DOR_XY
uniform channel latency 1 · route_weight 1 · no parallel channels
single traffic class over the full VC set · identity transitions
```

Otherwise: **AnyNet projection or refusal** — never a silent substitution.

### 28.3 Concrete consequences

- **`concentration > 1` has no native representation**: *"concentration has no
  native representation"*. It must take the AnyNet projection or refuse.
- **`latency_cycles` must be exactly 1** for the native path.
- **Only square meshes** are native.
- **Attachment must be identity-prefix** — the canonical policy satisfies this
  **only when `concentration == 1`**, because with concentration > 1 endpoint 1
  attaches to router 0, not router 1.

### 28.4 Idle endpoints — the answer

`len(endpoints) > n` refuses, and **every attached endpoint is projected**. So:

```text
no endpoint is ever omitted
node count = router count N          (not endpoint count E)
endpoint i ↔ router i  for i < E
routers ≥ E exist as nodes with no endpoint
```

**There are no idle endpoints — there are unused ROUTERS.** And they are part of
the mesh node universe. **The backend node count is the router count.**

## 29. Backend node-count authority

**Canonical endpoint count is the scientific authority.** Backend node counts
are projections. If a backend requires a different count or omits an endpoint,
the projection must be **explicit and validated** — it may never silently
redefine the fabric endpoint count.

## 30–31. Endpoint → ASTRA / BookSim projections

```text
endpoint → BookSim fabric node == ASTRA Sys.id
"Nothing may assume rank == endpoint."
```

The projection is **identity under the identity-prefix law**, and
**coincidence only** otherwise. Canonical endpoint ids are never numeric merely
for a backend's convenience. Both projections are deterministic and
evidence-bound, carried by the backend projection artifacts.

## 32. Endpoint-id migration

Legacy ids are positional integers. Migration must recover
**router · seat · agent** from the legacy topology + attachment ordering +
inventory, then produce the stable target identity.

**`legacy endpoint 7 → target endpoint 7` is never assumed without proving seat
equivalence.**

## 33. Legacy attachment migration

The legacy artifact is `{type, schema_version, topology_hash, endpoints}` with
**no policy identity**. Contextual migration adds the inventory, topology and
attachment-semantics parents **only when provenance proves the baseline policy
produced it**. Standalone artifacts without inventory context **refuse**
(`MIGRATION_CONTEXT_REQUIRED`).

## 34. `NocConfig` ownership table

| Legacy field | Target owner | Lossless? |
|---|---|---|
| `topology_family` | **FABRIC** typed variant | yes |
| `radix` | **FABRIC** → **`side_length`** | yes |
| `concentration` | **FABRIC** | yes |
| `link_width` | **FABRIC** `link_width_bits` | yes |
| `arbitration` | **ROUTER / RESOURCE** | yes |
| `rcu_enabled` | **ROUTER / RESOURCE** (unsupported) | yes, unsupported |
| `mcast_groups` / `mcast_setup_cycles` | **ROUTER / RESOURCE** (unsupported) | yes, unsupported |
| routing policy | **ROUTER** (not designed here) | n/a |
| `num_power_domains` | **removed** — derived from SYSTEM (S8) | validated then removed |
| network clock | **EVALUATION** | n/a |
| VC count / ids | **ROUTER / RESOURCE** | n/a |
| plane | **constant/internal**, not editable | n/a |
| `output_formats` / `obfuscation_level` | **PRODUCT/authoring** | yes |

**No field retains duplicate authority.**

## 35. Plane field

Single-valued enum. **Removed from user-editable `FabricIntent`.** A constant
may remain internally for compatibility. **No scientific user choice with one
valid value.**

## 36. Multiplane — FUTURE CAPABILITY CONTRACT

**No `plane_count`.** Unresolved: plane↔topology relation · shared vs separate
routers · endpoint membership · routing · VC namespace · failure/resource
sharing · communication-class binding · backend projection.

**Not v4 debt. Not solved here.**

## 37–39. Arbitration, RCU, hardware multicast move out

- **arbitration** → ROUTER/RESOURCE (arbiter policy, per-router vs global, class
  awareness, evidence — Domain H).
- **RCU** → ROUTER/RESOURCE: a boolean with no structural artifact is not
  topology intent. Domain H decides real capability vs dead field.
- **hardware multicast** → FABRIC exposes only **capability status:
  NOT REPRESENTED**. **No Fabric multicast flags.**

## 40. Broadcast compatibility

`BROADCAST` remains a **semantic workload collective** lowered as `ROOT_FANOUT`
over ordinary unicast-capable fabric. **FabricIntent requires no
broadcast-specific field.**

## 41–42. Routing-family boundary and Torus product state

Domain G records **topology compatibility facts only**:

```text
MESH / CONCENTRATED_MESH → routing certified
TORUS → topology materializes; canonical routing unavailable/refused
```

Exact routing policy and resource semantics are **Domain H**.

**Torus product state is staged:**

```text
TOPOLOGY CONSTRUCTION   SUPPORTED
ROUTED EXECUTION        NOT AVAILABLE
```

## 43. Target schema (locked)

```text
FabricIntentV4 { topology: MeshIntentV4 | TorusIntentV4, link_width_bits: int }
MeshIntentV4   { side_length: int, concentration: int }
TorusIntentV4  { side_length: int, concentration: int }
```

## 44. `FabricIntent` identity

**Included:** topology variant · `side_length` · concentration · `link_width_bits`.
**Excluded:** derived counts · network clock · arbitration · RCU · VCs ·
backend node ids.

## 45. `TopologyArtifact` parents

```text
FabricIntent identity + TopologySemanticsIdentity
```

**No** Mapping · Requirements · Workload · Communication · design clock —
none is consumed by topology derivation. Endpoint demand is checked later, at
attachment.

## 46. Topology may exceed endpoint demand

```text
64 seats · 48 agents → VALID topology
```

Unused capacity does not make the artifact incomplete.

## 47. `AgentAttachmentArtifact` parents — and the key separation

```text
physical_inventory_identity + topology_identity
+ attachment_semantics_identity + bindings
```

**`MappingArtifact` is NOT a parent.** Attachment is agent→endpoint, independent
of which participant occupies the agent. **Changing `MappingArtifact` does not
change `AgentAttachmentArtifact`.** This is a key experimental separation.

## 48. Attachment and SYSTEM hierarchy

Attachment ignores hierarchy. A hierarchy-only change that preserves
`AgentInstanceId`s leaves the **relation** unchanged, while the
**physical-inventory parent** moves per SYSTEM identity law — so the
context-bound artifact may change. Same relation-vs-artifact discipline as
Mapping.

## 49. Relation identities — no hash proliferation

Three pure identities are useful: **topology structure projection · mapping
relation · attachment relation**. Use the existing artifact/hash abstractions.
**Five hashes are not created merely because the plan can.**

## 50. Derivation semantics versions

Three compiler-owned deterministic policies now exist:

```text
RANK_ORDER_V1            (mapping)
ATTACHMENT_ORDER_V1      (attachment)
TopologySemanticsIdentity (topology construction)
```

The compiler identity must represent **which transformation changed**. A single
`compiler_version="4"` that cannot localize the change is insufficient.

## 51. Determinism tests

same `FabricIntent` → same topology · serialization reorder → same topology ·
reordered inventory input → same attachment · reordered router/link arrays →
same identity (or a rejected non-canonical form) · reordered bindings → same
artifact identity. **No accidental dict/set dependence.**

## 52. Stable endpoint tests

same topology + inventory → same `EndpointId`s · inventory declaration reorder
after SYSTEM stable-id migration → same ids and bindings · a new agent sorting
**after** all existing → existing assignments stable if the policy implies it ·
a new agent sorting **before** → assignments may move — **expected compiler
semantics; no more stability is promised than the policy guarantees.**

## 53–55. Topology / width / concentration consequences

| Change | Topology | Attachment | Mapping | Projection |
|---|---|---|---|---|
| mesh→torus | changes | recomputed (seat/topology parent) | **unchanged** | changes; routes/VC stale |
| link width only | **changes** (`width` in channels) | relation may be identical; **artifact revalidated** | unchanged | packetization stale |
| concentration | changes (seats) | changes | unchanged | stale; revalidated |

**An old attachment artifact hash is never reused across a changed topology
parent.**

## 56. Typed capacity preflight

`required endpoints` · `available seats` · `shortfall`, derived from
`PhysicalInventory + FabricIntent` **without route/VC execution**. **No route
feasibility is fabricated from it.**

## 57. Current UI field disposition

| Current control | Disposition |
|---|---|
| Topology | **KEEP**, typed |
| Radix | **RENAME** → `side_length` (grid side `k`) |
| Concentration | **KEEP** |
| Link width | **KEEP** |
| Arbitration | **REMOVE from Fabric** → Domain H |
| RCU | **REMOVE from Fabric** → Domain H / deferred |

**Add derived read-only:** routers · endpoint capacity · required endpoints ·
capacity status. **No plane field.**

## 58. Guided Fabric UI

```text
FABRIC
  Topology            Mesh
  Side length         8            (grid 8 × 8)
  Concentration       1
  Link width          256 bits
  Derived  routers 64 · endpoint capacity 64 · required endpoints 48 · unused seats 16
  Capacity            PASS
  Routing execution   Certified for the current family
```

No arbitration, RCU or VCs here.

## 59. Torus UI

```text
Topology creation      SUPPORTED
Routing / execution    NOT AVAILABLE IN CURRENT ENGINE
```

The compile workflow refuses **at the correct stage**, before pretending
evaluation is possible. Torus stays visible — it is valid topology research —
but never implies end-to-end capability.

## 60–62. Inspectors

**Topology inspector:** routers · coordinates · directed channels ·
physical-link grouping · seat capacities · attached agents · unused seats.
**Never** logical rank as endpoint identity; a cross-domain `agent → mapped rank`
column may appear, clearly marked as composition.

**Endpoint inspector:** endpoint · router · seat · attached agent · mapped
participant (if any) · backend projections. **Not user-editable.**

**Backend projection inspector:** ASTRA `Sys.id` and BookSim node/injection id,
each **labelled by namespace**. **Never one unlabeled numeric "Node ID"** — this
directly prevents the namespace collapse identified in Domains C/F.

## 63. Migration defect handling

Where stable seat/router/agent identity cannot be reconstructed: **REFUSE**.
Assigning ids by current sorted order and claiming historical equivalence is
forbidden. Record `MIGRATION_CONTEXT_REQUIRED`.

## 64. Implementation debt

```text
FAB-D1  AttachmentSemanticsIdentity (ATTACHMENT_ORDER_V1) bound into AgentAttachmentArtifact
FAB-D2  stable seat-derived EndpointId
FAB-D3  typed FabricIntentV4 + NocConfig ownership split
FAB-D4  TopologySemanticsIdentity binding
FAB-D5  typed capacity refusal / preflight
FAB-D6  backend idle-endpoint projection — RESOLVED in design (§28); implementation gap recorded
FAB-D7  context-bound attachment parent identities
```

**Multiplane is NOT v4 debt** — it is a FUTURE CAPABILITY CONTRACT.

## 65. G1–G60 re-evaluated

G13 `agent_count == capacity` → success · G14 `<` → valid, implicit unused seats ·
**G15 `>` → typed capacity refusal** · G16 idle compute → still requires an
endpoint · G17 `world_size` changes, SYSTEM same → seat demand unchanged ·
G18 mapping changes → topology/attachment unchanged · **G21 width changes →
`TopologyArtifact` changes despite the same structural graph** · G22
concentration → seat structure and attachment change · G25 multiplane →
FUTURE CONTRACT · G28 RCU → removed from Fabric · G29 arbitration →
ROUTER/RESOURCE · G32 torus route → topology valid / routing unavailable ·
**G39 idle-endpoint backend projection → resolved: no endpoint omitted; unused
ROUTERS exist** · G40/G41 backend ids → explicit projections · **G46 attachment
policy version change → artifact changes** · G47 same relation under a changed
topology parent → relation may match, **artifact identity differs**.

## 66. G61–G80

| # | Case | Verdict |
|---|---|---|
| **G61** | same agent→seat relation, different inventory parent | same relation possible; **different attachment artifact** |
| **G62** | same relation, different topology parent | **different artifact** |
| **G63** | same parents/relation, different attachment semantics version | **different artifact** |
| **G64** | positional endpoint ids → seat-derived ids | migration preserves exact physical seat semantics |
| **G65** | legacy endpoint integer not traceable to router/seat | **migration refuses** |
| **G66** | agent declaration reorder after stable SYSTEM identity | attachment unchanged |
| **G67** | new agent sorts before existing | later assignments may shift — deterministic |
| **G68** | new agent sorts after existing | existing assignments remain if capacity permits |
| **G69** | mapped rank changes agents | **attachment unchanged**; composition changes |
| **G70** | same agent moved hierarchy only | relation unchanged; artifact context follows inventory identity |
| **G71** | link width changes only | seats structurally same; **topology parent changes**; attachment revalidated |
| **G72** | network clock changes | Fabric/Topology/Attachment unchanged |
| **G73** | design clock changes | unchanged |
| **G74** | `RequirementSet` changes | unchanged |
| **G75** | workload payload changes | unchanged |
| **G76** | communication class changes | unchanged |
| **G77** | unknown topology variant | fail closed |
| **G78** | unknown attachment semantics identity | fail closed |
| **G79** | backend omits a canonical endpoint | **projection must justify explicitly or refuse — no silent drop** |
| **G80** | backend node count ≠ canonical projection expectation | qualification refusal |

## 67. Closure questions C1–C20

| # | Answer |
|---|---|
| C1 | **`side_length`** (the grid side `k`) |
| C2 | **strictly square `k×k`** |
| C3 | `FabricIntentV4 { topology: MeshIntentV4\|TorusIntentV4, link_width_bits }` |
| C4 | `TopologySemanticsIdentity`, following the `semantics_version` convention |
| C5 | `ATTACHMENT_ORDER_V1` |
| C6 | none — seats are implicit `(router_id, seat_index)` |
| C7 | derived from the occupied topology seat |
| C8 | **only indirectly** via `topology_hash`; no inventory parent |
| C9 | derive through the existing artifact primitives |
| C10 | **yes — all kinds, exactly one each** |
| C11 | every attached endpoint is projected; node count = **router count**; unused **routers** remain |
| C12 | `Sys.id == endpoint id` (identity under the identity-prefix law) |
| C13 | through the backend projection artifacts and qualification |
| C14 | **yes today** — width is in `topology_hash`, so the parent changes |
| C15 | **yes** — revalidate and reissue with a new parent-bound identity |
| C16 | arbitration · RCU · mcast_* · VC count/ids · routing policy |
| C17 | `derive_route`: family not in `_CERTIFIED_FAMILIES` |
| C18 | **yes** — staged: construction supported, routed execution unavailable |
| C19 | `PreparedBookSimInput` and the ASTRA machine projection |
| C20 | typed `SemanticLoss` / schema errors, per project conventions |

**All 20 answered.**

## 68. Coherence gate

1. typed `FabricIntent` — **MET** (§2)
2. `radix` naming corrected — **MET** (§3)
3. topology variant semantics explicit — **MET** (§5, §6)
4. topology derivation semantics identity-bound — **MET** (§9)
5. stable seat identity — **MET** (§12)
6. endpoint identity no longer positional — **MET** (§13)
7. attachment relation explicit — **MET** (§15)
8–10. attachment binds inventory, topology, semantics — **MET** (§16–19)
11. capacity law exact — **MET** (§22)
12. typed capacity failure — **MET** (§23)
13. all-agent attachment law exact — **MET** (§26)
14. idle agents/endpoints explicit — **MET** (§27)
15–16. BookSim and ASTRA idle-endpoint projection known — **MET** (§28)
17. backend namespace mappings explicit — **MET** (§30–31, §62)
18. link-width/topology identity law explicit — **MET** (§7, §10)
19. absolute bandwidth outside intent — **MET** (§11)
20. torus staged support explicit — **MET** (§6, §42, §59)
21. arbitration/RCU moved out — **MET** (§37–38)
22. multiplane remains a future contract — **MET** (§36)
23. legacy migration authoritative or refuses — **MET** (§32–33, §63)
24. G1–G80 verdicts — **MET**
25. C1–C20 answered — **MET**
26. ROUTER / RESOURCES not begun — **MET**

## 69. Domain verdict

Topology derivation was already disciplined; the closure is architectural.

**The largest single result is FAB-D6.** The backend treatment of endpoints is
not a detail — the **native mesh-DOR projection has a narrow proven domain**
requiring square meshes, **`seat_capacity == 1`**, uniform latency 1, identity
transitions and **identity-prefix attachment**. That means **`concentration > 1`
has no native representation**, and the canonical attachment policy satisfies
identity-prefix **only at concentration 1**. The answer to "are idle endpoints
projected?" is that **there are no idle endpoints — there are unused routers**,
and the backend node count is the **router count**.

Also closed: a typed `FabricIntentV4` with **`side_length`** replacing the
misleading `radix`; square-only shape preserved rather than generalized;
`TopologyArtifact` locked as *physical topology including channel properties*
with a derived `TopologyStructureView`; stable seat-derived `EndpointId`;
`AgentAttachmentRelation` with a context-bound artifact binding inventory,
topology and **`ATTACHMENT_ORDER_V1`**; a typed capacity refusal; and
arbitration/RCU/multicast moved to Domain H with multiplane left as a future
contract rather than fake v4 state.

**FABRIC INTENT: PLANNED — COHERENT**

Per Gate 2's rule, ROUTER / RESOURCES is not begun.
