# INTENT-SYSTEM — Domain A specification (Gate 2, closure pass)

Domain row: `intent-ontology.yaml :: domains.SYSTEM`
Enforced by: `scripts/check_intent_ontology.py`
Supersedes the first-pass audit. **Not implemented** — this closes the design,
not the code.

---

## 0. Reality header

Verified at call sites. Two rows correct the first-pass audit.

| Concept | Reality | Evidence |
|---|---|---|
| compute tiles / HBM controllers / NICs / peripheral / UCIE | **R2** | `AgentKind` `compile_model.py:222` |
| `count` | **R2** | `build_inventory` `placement.py:242` |
| `addr_width` | **R2** | consumed: address domain bound `address_decode.py:405` |
| `data_width` | **R1 — CORRECTED** | stored at `attachment.py:147`; **no consumer reads `data_width_bits`** |
| `protocol` | **R1** | stored at `attachment.py:149`; no consumer |
| `clock_domain` / `power_domain` | **R2/R3** | consumed + refused >1 `fabric_artifact.py:305,317` |
| nodes, endpoint demand | **R4** | `AgentInstance`, `agent_count` |
| physical vs logical inventory | **R4** | `NodeInventory` (both universes) |
| hierarchy, packages, chiplets, accelerators | **R0** | no type |
| resource domains (general), capabilities, replication, elastic inventory, affinity domains | **R0** | no type |

**Correction of consequence:** `data_width` does **not** feed packet or flit
width. Flit width comes from topology channels — `derive_packet_format`
reads `{channel.width_bits}` (`packet_format.py:569`) — which comes from
`NocConfig.link_width`. `Agent.data_width` is a **second decorative
interface field**, exactly like `protocol`.

---

## 1. Locked decisions

| # | Verdict | Consequence |
|---|---|---|
| **S1** | **NEW CONTRACT** — one generic containment model, not four | `SystemContainer`; kinds finite |
| **S2** | **DO NOT generalize** — typed `ClockDomain` / `PowerDomain` only | no generic `ResourceDomain` bag; memory domains → MEMORY; locality → hierarchy |
| **S3** | **KEEP DERIVED** | endpoint demand = `agent_count`; no editable integer |
| **S4** | **DEFER** — no capability bag | `AgentKind` remains the discriminator; else `CONTRACT NOT AVAILABLE` |
| **S5** | **COUNT canonical** | replication policy → authoring/design-space, expands to exact inventory |
| **S6** | **SPLIT** | SYSTEM declares locality scopes; PLACEMENT declares affinity policy |
| **S7** | **FIXED in SYSTEM** | ranges → DESIGN-SPACE; candidate resolves to one exact inventory |
| **S8** | **REMOVE AS AUTHORITY** | `num_power_domains` derived from domain membership; legacy validates equality |
| **S9** | **NEW CONTRACT** | stable `group_id`; migrate `target_agent_idx` → `target_agent_group_id` |
| **S10** | **DECIDED — option C** | `protocol` is intended semantic state, support incomplete → `DECLARED / NOT INTERPRETED`; identity movement intentional and documented |
| **S11** | **REQUIRED** | SYSTEM → physical inventory; PARALLELISM → logical participants; PLACEMENT joins |
| **S12** | **NEW DERIVED ARTIFACT** | `PhysicalInventoryArtifact` — immutable identity for expanded supply |

---

## 2. Target ontology

```text
SYSTEM
├── containers[]            SystemContainer      NEW CONTRACT (S1)
├── agent_groups[]          AgentGroup           extends today's Agent (S9)
├── clock_domains[]         ClockDomain          NEW CONTRACT (S2)
├── power_domains[]         PowerDomain          NEW CONTRACT (S2)
└── derived
    └── PhysicalInventoryArtifact                NEW ARTIFACT (S12)

EXCLUDED (with ownership)
├── affinity / anti-affinity      → PLACEMENT     (S6)
├── elastic ranges                → DESIGN-SPACE  (S7)
├── replication policy            → authoring / DESIGN-SPACE (S5)
├── memory domains                → MEMORY        (S2)
├── agent capabilities            → deferred      (S4)
└── machine tier / topology tier  → FABRIC, never SYSTEM (§5)
```

---

## 3. Current contracts

| Contract | Path |
|---|---|
| `Agent`, `AgentKind` | `model/compile_model.py:232,222` |
| `AgentInstance`, `NodeInventory`, `LogicalRank`, `ParallelismShape` | `model/placement.py:104,157,134,33` |
| `build_inventory` | `model/placement.py:242` |
| `AgentAttachmentArtifact`, `EndpointInterface` | `model/attachment.py:105,147` |
| `AddressRange.target_agent_idx` | `model/compile_model.py:660` |
| `AddressDecodeEntry.target_agent_group` | `model/address_decode.py:186` |

## 4. Target contracts (proposed, reviewable field by field)

```text
SystemIntentV4
  containers:     tuple[SystemContainer, ...]
  agent_groups:   tuple[AgentGroup, ...]
  clock_domains:  tuple[ClockDomain, ...]
  power_domains:  tuple[PowerDomain, ...]

SystemContainer
  container_id:   str          # stable, semantic
  kind:           ContainerKind
  parent_id:      str | None   # None only for the single root
  name:           str = ""     # presentation; excluded from identity

ContainerKind: MACHINE | NODE | PACKAGE | ACCELERATOR | CHIPLET

AgentGroup
  group_id:        str         # stable, semantic (S9)
  kind:            AgentKind
  count:           int >= 1
  container_id:    str         # must resolve
  interface:       AgentInterface
  clock_domain_id: str | None
  power_domain_id: str | None
  name:            str = ""    # presentation; excluded from identity

AgentInterface
  data_width:  int >= 8        # DECLARED / NOT INTERPRETED
  addr_width:  int >= 8        # consumed: address domain bound
  protocol:    str             # DECLARED / NOT INTERPRETED

ClockDomain { domain_id: str; name: str = "" }
PowerDomain { domain_id: str; name: str = "" }
```

**Schema properties:** versioned · strict (unknown keys refuse) · lossless ·
deeply immutable · stable semantic IDs · canonical ordering **by id, not by
array position** · deterministic hashing · no duplicate authority · no
implicit array identity · **no arbitrary extension dictionaries** · no hidden
topology semantics.

**Not final.** `ContainerKind` gains `BOARD` only when a concrete use exists;
`CUSTOM` is refused to avoid dodging semantics.

---

## 5. Physical hierarchy

```text
machine
└── node0
    ├── accelerator0
    │   ├── chiplet0
    │   └── chiplet1
    └── accelerator1
```

**Rules**

1. exactly one logical root (or a documented root convention);
2. acyclic;
3. stable IDs;
4. deterministic canonical ordering **independent of UI order**;
5. every non-root container has exactly one parent;
6. container identity is semantic;
7. containment creates **no** network edge, route, endpoint or placement decision.

**Hard non-leakage rule.** SYSTEM must not infer `chiplet → router`,
`package → plane`, or `node → network tier`. Those are FABRIC/PLACEMENT
decisions. §20 A34 tests this.

---

## 6. Stable identity model

- **`group_id` is the primary semantic reference.** Array position is never
  identity.
- **Instance IDs are derived, deterministic:** group `compute_a`, count 4 →
  `compute_a/0 … compute_a/3`.
- **Canonical serialization is sorted by id**, so reordering a form is a
  no-op (A18).

**Positional-reference migration table**

| Current reference | Future stable reference | Compatibility |
|---|---|---|
| `AddressRange.target_agent_idx` | `AddressRange.target_agent_group_id` | v3 loader maps index → deterministic `legacy-agent-group-<NNN>` |
| `AgentInstance.group_index` | `AgentGroup.group_id` | internal; derived keys change |
| `AgentInstance.instance_id` = `agent_group[i]/kind[j]` | `<group_id>/<j>` | derived artifact change |
| `AddressDecodeEntry.target_agent_group` | `target_agent_group_id` | derived artifact change |
| `(group_index, instance_index, kind)` keys in attachment / traffic / resolved_fabric / certificate | `(group_id, instance_index, kind)` | derived artifact change |
| `application/views.py:101 group_index` | display `group_id` | presentation |
| `AddressDecodeEntry.target_endpoint_id` | unchanged (concrete endpoint) | none |

`group_index` appears in **20 call sites** across `address_decode`,
`attachment`, `resolved_fabric`, `placement`, `workload/traffic`,
`verification/certificate` and `application/views` — the migration is
well-bounded but not local.

---

## 7. Agent groups / interfaces

Per-field classification, verified:

| Field | Class | Consumer | Change class |
|---|---|---|---|
| `kind` | SEMANTIC_AND_CONSUMED | inventory, topology, attachment | STRUCTURAL |
| `count` | SEMANTIC_AND_CONSUMED | inventory, topology, mapping | STRUCTURAL |
| `data_width` | **METADATA_ONLY** | **none** | METADATA |
| `addr_width` | SEMANTIC_AND_CONSUMED | `address_decode.py:405` | INTERFACE |
| `protocol` | **METADATA_ONLY** | **none** | METADATA → intended INTERFACE |

**Interface lives on the group, not the instance.** Per-instance
heterogeneity is expressed by declaring a second group.

---

## 8. Clock and power domains

- Free-text per-group strings are replaced by **stable references**:
  `clock_domain_id`, `power_domain_id`.
- No frequency, voltage, level-shifter or DVFS semantics are invented — none
  exist.
- Current execution supports **at most one distinct clock and one distinct
  power domain**.

**The useful distinction is preserved:** the schema may *represent* multiple
domains while compilation refuses them. That is **DECLARABLE but UNSUPPORTED
BY CURRENT FABRIC LOWERING** (A25) — the declaration is not INVALID.

Memory, failure, coherence and security domains stay out of SYSTEM until a
downstream consumer exists.

---

## 9. Physical inventory derivation (S12)

```text
PhysicalInventoryArtifact
  schema_version
  system_intent_hash        # parent identity
  containers[]
  agent_groups[]
  agent_instances[]         # stable ids: <group_id>/<i>
  clock_domains[]
  power_domains[]
  agent_count
  compute_instance_count
  endpoint_demand           # == agent_count (S3)
  inventory_hash
```

**Contains:** expanded physical supply only.
**Excludes:** logical ranks · placement · router seats · endpoint attachments.

Required: strict serialization · hash/tamper detection · parent identity ·
immutability · round-trip tests.

**Status: contract defined, implementation deferred.** Rationale: it must not
be created before the v4 `SystemIntent` exists, or it would encode today's
flat model. The domain is coherent because the identity home is decided.

---

## 10. Logical-inventory boundary (S11)

```text
SystemIntent ──► PhysicalInventoryArtifact
ParallelismIntent ──► LogicalParticipantInventory
        ⊕ ──► Placement / Mapping ──► Attachments ──► Topology ──► Routes / VC
```

`NodeInventory` is retained as a **CROSS-DOMAIN JOIN STRUCTURE** — not SYSTEM
ontology — for migration only.

**Reclassification:** `compute_instances >= world_size` is **not** an
intrinsic SYSTEM validation. It is a **cross-domain placement feasibility
check**. SYSTEM must be valid independently of any workload. The SYSTEM
editor may *preview* it when parallelism context exists.

---

## 11. Endpoint-demand derivation

Derived, never declared: one agent instance → one required attachment seat
(`agent_count`). No `endpoint_demand` field. If agents ever require multiple
endpoints, that arrives through a real **interface/attachment cardinality**
contract, not a preemptive integer.

---

## 12. Cross-domain relationships

| To | Fact SYSTEM owns | Policy others own |
|---|---|---|
| PARALLELISM | physical supply | logical demand |
| PLACEMENT | `ancestor(agent, LEVEL)`, `same_container(a,b,level)` | `must_be_same` / `prefer_same` / `must_differ` |
| FABRIC | `agent_count` → seat demand | router count, planes, links |
| MEMORY | container/group identity | memory domains, locality policy |
| PHYSICAL | domain membership | domain *support* limits |
| COMMUNICATION | endpoint interfaces | traffic classes |

**SYSTEM owns structural facts. PLACEMENT owns policy.** No affinity rule
appears in SYSTEM (§20 A29).

---

## 13. Intrinsic validation (SYSTEM-INTRINSIC)

| Rule | Layer |
|---|---|
| `count ≥ 1` | L1n |
| `agent_groups` non-empty | L1d |
| `data_width ≥ 8`, `addr_width ≥ 8` | L1n |
| `protocol` non-empty | L1n |
| unique `group_id` / `container_id` / domain ids | L1d |
| `container_id` resolves | L1d |
| hierarchy acyclic, single root, one parent | L1d |
| `container.kind` ∈ finite enum | L1n |
| `AgentKind` ∈ enum | L1n |
| domain references resolve | L1d |

## 14. Cross-domain validation (NOT SYSTEM's to own)

| Rule | Owner | Today's code |
|---|---|---|
| `compute_instances ≥ world_size` | PLACEMENT | `mapping.py:181` |
| address target exists / singleton | MEMORY + attachment | `address_decode.py:488` |
| seat capacity vs radix/concentration | FABRIC | `topology_artifact.py:399` |
| attachment feasibility | attachment | `attachment.py` |
| ≤1 distinct domain supported | FABRIC | `fabric_artifact.py:305` |

The UI may **preflight** these; ownership does not move.

---

## 15. Failure / refusal model

| State | Trigger | Ownership |
|---|---|---|
| `INVALID` | duplicate ids, missing container, cycle, unknown kind, `count=0` | SYSTEM-intrinsic |
| `INVALID` | elastic range or affinity rule supplied to SYSTEM | wrong domain |
| `UNSUPPORTED` | >1 distinct clock/power domain | fabric lowering |
| `UNSUPPORTED` | address target non-singleton | attachment/decode |
| `INVALID` | `rank_count > compute_instances` | placement |
| **silent** | `protocol` / `data_width` changed | **none — but hash moves** |

---

## 16. Change classes / invalidation

Authoritative table. **The UI must not hard-code this in React.**

| Field | Change class | Invalidates |
|---|---|---|
| `kind` | STRUCTURAL | inventory → attachments → fabric → certificate → evaluation |
| `count` | STRUCTURAL | same |
| `container_id` / `parent_id` / `container.kind` | STRUCTURAL (locality) | inventory → placement → … → certificate |
| `group_id` | STRUCTURAL (identity) | everything (references re-resolve) |
| `addr_width` | INTERFACE | attachment → address decode → fabric → certificate |
| `data_width` | **METADATA** | attachment_hash → resolved_fabric_hash → certificate *(no functional change)* |
| `protocol` | **METADATA (intended INTERFACE)** | same as `data_width` |
| `clock_domain_id` / `power_domain_id` | DOMAIN | attachment → fabric (or refusal) |
| `name` (any) | **METADATA — excluded from identity** | nothing |

---

## 17. V3 → V4 migration

```text
V3  agents: [ {kind, count, data_width, addr_width, protocol,
               clock_domain, power_domain}, ... ]

V4  system:
      containers:  [ {container_id: "machine", kind: MACHINE, parent_id: null} ]
      agent_groups:[ {group_id: "legacy-agent-group-000",
                      kind, count, container_id: "machine",
                      interface: {...}, clock_domain_id: ..., power_domain_id: ...} ]
```

- Migration IDs are **deterministic**: `legacy-agent-group-<NNN>`, zero-padded,
  in declaration order.
- **Documented honestly:** migrated positional identity was *not* originally
  named identity. The migration **invents** names; it does not recover them.
- **Address map is lossless:** `target_agent_idx = i` →
  `target_agent_group_id = legacy-agent-group-<i>`, a bijection.
- **Unavoidable identity reset:** v4 is a **new identity domain**, exactly as
  v3 was against v2. `design_hash` changes by construction; v3 revisions are
  **never reinterpreted**. Existing v3 revisions remain valid as v3.
- Legacy `num_power_domains`: accepted, validated equal to the derived count,
  rejected on mismatch; **absent from canonical v4 serialization**.

---

## 18. UI implications (structure only — no HTML)

**Guided**

```text
SYSTEM
  Compute    64 tiles
  Memory      8 HBM controllers
  I/O         2 NICs
  Architecture  1 node · 1 package · 8 accelerators
  [Customize system]
```

Only if the hierarchy contract supports those counts.

**Expert** — a structured architecture editor, not seven loose inputs:

```text
SYSTEM TREE
Machine
└── Node 0
    └── Package 0
        ├── Accelerator 0
        │   ├── Compute A × 8
        │   └── HBM A × 1
        └── Accelerator 1
            ├── Compute B × 8
            └── HBM B × 1
```

Selecting a group opens **Identity · Kind · Count · Interface · Clock domain ·
Power domain**. Derived side panel: instances · endpoint demand · downstream
effects. **No routers, routes or seats** — those stay compiler-derived.

---

## 19. Unsupported / deferred

| Concept | State | Presentation |
|---|---|---|
| >1 clock / power domain | `UNSUPPORTED` (fabric) | named refusal + stage |
| multiple domains *declared* | `DECLARABLE` | allowed; compile refuses |
| agent capabilities | `CONTRACT NOT AVAILABLE` | explicit absence |
| replication policy | `CONTRACT NOT AVAILABLE` | `count` only |
| affinity / anti-affinity | `CONTRACT NOT AVAILABLE` (PLACEMENT) | wrong domain |
| elastic inventory | `CONTRACT NOT AVAILABLE` (DESIGN-SPACE) | wrong domain |
| memory / failure / coherence / security domains | `CONTRACT NOT AVAILABLE` | — |
| hierarchy → topology inference | **forbidden** | never inferred |

---

## 20. Adversarial cases

A1–A17 retained from the first pass. A18–A34 new.

| # | Case | Expected verdict |
|---|---|---|
| A1 | two compute groups, different `data_width` | LEGAL, distinct identity |
| A2 | two compute groups, identical interface | LEGAL, distinct by `group_id` |
| A3 | `world_size = 8`, 4 compute tiles | REFUSE at placement (cross-domain) |
| A4 | 8 compute + 4 HBM, `world_size = 8` | LEGAL (HBM not counted) |
| A5 | all-HBM inventory | REFUSE — no compute supply |
| A6 | two clock domains | `UNSUPPORTED` at fabric |
| A7 | two power domains | `UNSUPPORTED` at fabric |
| A8 | `num_power_domains=2`, agents imply 1 | REFUSE — authorities disagree |
| A9 | `target_agent_idx = 5`, 2 groups | REFUSE at address decode |
| A10 | `count = 0` | REFUSE L1n |
| A11 | `protocol = "CHI"` | ACCEPTED; moves `attachment_hash` → certificate |
| A12 | `data_width = 8` | ACCEPTED; **no** packet consequence (corrected) |
| A13 | 1000 compute tiles | ACCEPTED; router-count/seat pressure downstream |
| A14 | duplicate `(group_index, instance_index)` | REFUSE L1d |
| A15 | peripheral with no address range | ACCEPTED; seat, no decode entry |
| A16 | hierarchy via `fabric_overrides` | IMPOSSIBLE (no array indices) |
| A17 | `clock_domain` on one group only | LEGAL (set size 1) |
| **A18** | reorder two groups, ids unchanged | **LEGAL, no identity change** (canonical order by id) |
| **A19** | rename display label only | **no scientific identity change** (`name` excluded) |
| **A20** | duplicate `group_id` | INVALID L1d |
| **A21** | group references missing container | INVALID L1d |
| **A22** | container parent cycle | INVALID L1d |
| **A23** | two packages, otherwise identical agents | LEGAL; distinct hierarchy, distinct identity |
| **A24** | group moved accelerator A → B | SYSTEM identity moves; STRUCTURAL invalidation chain |
| **A25** | multiple declared clock domains | **schema VALID**; fabric compile `UNSUPPORTED` |
| **A26** | legacy `num_power_domains=2`, domains imply 1 | migration REFUSES (inconsistency) |
| **A27** | address map targeting a group survives reorder | same target under stable id |
| **A28** | elastic count range in SYSTEM | INVALID — belongs DESIGN-SPACE |
| **A29** | affinity rule in SYSTEM | INVALID — belongs PLACEMENT |
| **A30** | replicate-per-node directive in SYSTEM | not canonical intent — unknown key refuses |
| **A31** | unknown container kind | fail closed (enum) |
| **A32** | unknown agent kind | fail closed (enum) |
| **A33** | `protocol` change | identity: `attachment_hash` → `resolved_fabric_hash` → certificate. Function: none. `DECLARED / NOT INTERPRETED` |
| **A34** | hierarchy-only change | SYSTEM identity changes; **no** links/routes/planes derived. Fabric consequences require declared fabric/placement policy |

---

## 21. Remaining blockers

1. **`data_width` is decorative.** Verified: no consumer; flit width comes
   from `link_width`. Two decorative interface fields (`data_width`,
   `protocol`) move the certificate. **Recommendation:** `data_width` should
   either be consumed by a real interface contract or **removed from the
   scientific identity** — it currently duplicates `link_width`'s role.
2. **`PhysicalInventoryArtifact` implementation deferred** (contract defined).
3. **v4 implementation not started** — this pass closes design only.
4. **`NodeInventory` remains a join structure** until PLACEMENT owns the join.
5. **Global decision D1 still open** — the page's declared layer.

---

## 22. Domain verdict

All 15 coherence-gate conditions are satisfied at the design level:

S1–S8 resolved · S9 stable identity designed · address-map migration designed ·
physical/logical ownership split · physical-inventory identity home defined ·
protocol identity decided (option C) · every editable field carries a change
class · every R0 item excluded-with-rationale or assigned a contract ·
hierarchy provably does not leak topology (A34) · placement-affinity boundary
explicit · fixed-vs-elastic boundary explicit · duplicate power-domain
authority eliminated in the target model · v3→v4 migration lossless with
identity reset documented · A1–A34 have expected verdicts · **no WORKLOAD
planning has begun.**

**SYSTEM INTENT: PLANNED — COHERENT**

(Blocker 21.1 is recorded as a defect to resolve in the interface contract, not
an incoherence in the SYSTEM boundary.)
