# INTENT-PARALLELISM — Domain C specification (Gate 2)

Domain row: `intent-ontology.yaml :: domains.PARALLELISM`
Enforced by: `scripts/check_intent_ontology.py`
Design closure only — no v4 code written.

---

## 0. Reality header

**Structurally different from A and B:** the canonical numeric authority
already exists. `model/parallelism.py::ParallelismArtifact` carries identity
(`parallelism_id`), the four dimensions, and a **stable group derivation**.
Domain C is therefore *consolidation and namespace discipline*, not invention.

| Concept | Reality | Evidence |
|---|---|---|
| TP / DP / PP / EP extents | **R2, seven authorities** | §2 |
| rank algebra (`rank_of`/`coords_of`) | **R2, sealed** | `placement.py:82` |
| `world_size` | **R3 derived** | `parallelism.py:88`; stored value validated, never identity |
| parallelism identity | **R2** | `parallelism_id()` `parallelism.py:114` |
| participant groups | **R2** | `ParallelismArtifact.groups` `parallelism.py:169` |
| group identity | **R2, stable by (family, fixed coords)** | `Group.family` + `Group.index` `parallelism.py:42` |
| `LogicalRank` / coordinates | **R2** | `placement.py:134` |
| `LogicalParticipantInventory` | **R0** | no artifact; groups are derived in two places |
| `BoundWorkloadGraph` | **R0** | Domain B contract |
| PP stage assignment | **R0** | no stage model; `PP family = stages, not collectives` |
| PP point-to-point lowering | **R0** | PP-dim COLLECTIVE refuses |
| DP gradient semantics | **R0** | DP is a collective axis only |
| expert→EP-rank assignment | **R0 in compiler** | only in `tools/chakra_to_dse.py:272` |
| model divisibility laws | **R0** | no `hidden_size % TP` anywhere |
| serving rank space | **R4, different namespace** | virtual NPU `serving_loop.py:26` |
| ASTRA rank | **R4 = endpoint namespace** | `astra_namespace.py:1` |
| serving instance | **R4** | not a participant |

**Positive finding:** the four-namespace discipline is *already documented in
code*:

```text
workload rank --MappingArtifact--> agent
agent --AgentAttachmentArtifact--> physical endpoint
endpoint --> BookSim fabric node == ASTRA Sys.id
"Nothing may assume rank == endpoint."   (astra_namespace.py)
```

---

## 1. Domain boundary

```text
ModelSpec + WorkloadIntent + ParallelismIntent
        ↓
LogicalParticipantInventory
        ↓
BoundWorkloadGraph
        ↓
Placement / Mapping
        ↓
Physical endpoints
```

| Owner | Owns |
|---|---|
| **PARALLELISM** | logical dimensions, participant membership, groups |
| **PLACEMENT** | logical participant → physical compute-agent mapping |
| **SERVING** | serving instances, scheduler objects |
| **SYSTEM** | physical compute supply |
| **FABRIC** | physical network resources |

**Namespace law — nine identities, never merged:**

```text
logical participant · global rank · serving rank · serving instance
ASTRA rank (= endpoint) · physical agent · endpoint · BookSim node · router
```

---

## 2. Current numeric authorities

| Field | Symbol | Path | Current owner | Consumer | Target owner |
|---|---|---|---|---|---|
| tp/pp/ep/dp | `WorkloadV3` | `compile_model.py:2073` | WORKLOAD (v3 declared) | `FabricIntentView`, groups | **PARALLELISM** |
| tp/pp/ep/dp | `Workload` (v2) | `compile_model.py:319` | WORKLOAD v2 | legacy | **PARALLELISM** |
| tp/pp/ep/dp | `ParallelismShape` | `placement.py:33` | rank algebra (sealed) | inventory, mapping | **PARALLELISM — the algebra** |
| tp/pp/ep/dp | `ParallelismArtifact` | `parallelism.py:57` | Waved identity + groups | `OperationGraph` | **PARALLELISM — the target** |
| tp/pp/ep/dp | `WorkloadGraph.parallelism` | `workload/graph.py:645` | WORKLOAD (**leak**) | lowering | **PARALLELISM** |
| participant_count | `WorkloadGraph` | `workload/graph.py:645` | WORKLOAD (**leak**) | lowering | **PARALLELISM (derived)** |
| parallelism + num_participants | `WorkloadArtifact` | `workload/canonical.py:428` | Phase-9 | memory lowering, migration | **PARALLELISM** |
| tp/pp/ep/dp | `FabricIntentView` | `compile_model.py:2699` | compiler seam | topology, routing | **PARALLELISM** |
| world_size | `WorkloadV3.world_size` | `compile_model.py:2112` | **DEAD — broken import** | none | **remove** |
| tp/pp/ep/dp | serving cluster config | LLMServingSim | SERVING | serving loop | **PARALLELISM via projection** |
| coords law | `reference_semantics.py:27` | independent | verification | differential test | **keep independent** |

**Seven numeric authorities.** The gate cannot close while more than one
*editable scientific* authority exists. §3 collapses them.

---

## 3. Target canonical authority

**`ParallelismIntentV4`** — one authority, evolving
`ParallelismArtifact` (which already has identity + groups):

```text
ParallelismIntentV4 {
  tp: int >= 1
  pp: int >= 1
  ep: int >= 1
  dp: int >= 1
  schema_version
}
```

- **All four dimensions are always required.** No optional axes, no
  `custom_axis_1`, no dimension dictionary. Strict TP/DP/PP/EP.
- **`1` is explicit canonical state**, never omitted. A UI omitting DP means
  `dp = 1`, normalized before identity.
- Identity = `{type, schema_version, tp, pp, ep, dp}` — exactly
  `ParallelismArtifact.identity_dict`.
- `world_size` is **derived, never identity**; a stored value is validated
  for self-integrity only (`parallelism.py:148`).
- The dimension law has **one definition**: `ParallelismShape`. The artifact
  adds identity and groups and **must not restate the law**.

---

## 4. Parallelism shape

`ParallelismShape` (`placement.py:33`) is the sealed algebra: four sizes,
each `>= 1`, plus `world_size`. It is the single answer to "is `tp=0`
legal". `ParallelismArtifact` delegates to it.

## 5. World-size law

```text
world_size = tp × pp × ep × dp
```

Verified. `parallelism.py:8` states `R = TP·PP·EP·DP` is derived and never
independent; `from_dict` rejects a stored `world_size` that disagrees.

## 6. Dimension ordering

Two distinct orders exist and both must be declared once:

**Algebra / flattening order (least → most significant): `TP, EP, DP, PP`.**

```text
rank_of = ((pp_i * dp + dp_i) * ep + ep_i) * tp + tp_i
```

**Declaration / serialization order (repository convention): `tp, pp, ep, dp`**
(`identity_dict`, `sizes()`, `ParallelismShape`).

**Law:** the algebra order governs rank computation; the declaration order
governs serialization. Neither may be reordered silently. The coords law is
independently re-implemented in `reference_semantics.py` **on purpose** (a
differential test), so a single change to one is caught.

## 7. Participant identity

`LogicalParticipantId` = the **global rank**, derived deterministically from
coordinates. Ordinal and semantic identity coincide today because the
flattening is a bijection.

**Changing shape while retaining world size changes participant identity:**

```text
TP4 EP1 → coords (t,0,0,0)   TP2 EP2 → coords (t,0,e,0)
world size 4 → 4, but coordinates differ ⇒ different ParallelismIntent identity
```

Confirmed: identity is over extents, not over world size (B/C11).

## 8. Rank coordinates

Every participant carries `global_rank` plus `(tp, dp, pp, ep)` indices
(`LogicalRank`). `NodeInventory` self-checks that stored coordinates equal
the canonical `coords_of` result for the declared shape.

## 9. Rank flattening

```text
rank_of(t, p, e, d) = ((p*dp + d)*ep + e)*tp + t
coords_of(rank):  t = rank % tp; r = rank // tp
                  e = r % ep;    r //= ep
                  d = r % dp;    p = r // dp
```

Round-trip is a required property test (C17). **This is compiler
semantics**: changing the flattening changes scientific identity.

## 10. LogicalParticipantInventory

**Home decided: deterministic in-memory derivation, not a persisted
artifact — for now.**

```text
LogicalParticipantInventory {
  parallelism_identity
  world_size
  participants[]   { participant_id, global_rank, tp, dp, pp, ep }
  groups[]         { group_id, dimension, fixed_coordinates, members[] }
  inventory_hash
}
```

**Rationale for in-memory:** it is a pure function of `ParallelismIntent`
(no cross-domain input), so a persisted artifact would add storage without
adding proof. It becomes a persisted artifact only if evidence or
requirements must reference participant ids independently — at which point
the decision is revisited, not pre-empted.

No physical mapping · no endpoint · no serving instance.

## 11. Participant groups

Verified derivation law (`intent_lowering._groups_for_dimension`,
mirroring `ParallelismArtifact.groups`):

| Family | Varies | Fixed | Iteration order |
|---|---|---|---|
| TP | `t` | `(p, e, d)` | `p, d, e` |
| EP | `e` | `(t, p, d)` | `t, p, d` |
| DP | `d` | `(t, p, e)` | `t, p, e` |
| PP | `p` | `(t, e, d)` | **stages, not collectives** |
| GLOBAL | all | — | single all-ranks group |

Group counts:

```text
TP groups = pp·dp·ep    DP groups = tp·pp·ep
EP groups = tp·pp·dp    GLOBAL = 1
```

Property tests C13–C16 assert these.

## 12. Group identities

`Group { family, index, members }` where **`index` is the fixed coordinate
key** — not an array position. Group identity is therefore
`(family, fixed_coordinates)`, stable under serialization reorder and under
list reordering. Human-readable form: `tp[dp=0,pp=0,ep=0]`.

`group_of(family, rank)` is derived **by lookup in the one group
derivation**, never by a second formula — the module explicitly warns that
"two derivations of the same groups is how a group law and a group listing
come to disagree."

## 13. Workload binding

**Binding law (multiplicity is explicit, not hand-waved):**

A workload operation with `participant_scope = D` binds to **every group of
family `D`** in the bound shape.

```text
TP=4, DP=2, one TP-scoped ALLREDUCE
→ 2 TP groups (dp=0 and dp=1)
→ 2 bound communication operations
```

```text
TP=4, DP=1 → 1 TP group → 1 bound operation
```

`GLOBAL` binds to the single all-ranks group. `PP`-scoped collectives are
**refused** (§17). Explicit-endpoint operations (P2P, MULTICAST) do not
multiply by group — they bind their declared endpoints.

## 14. BoundWorkloadGraph

```text
BoundWorkloadGraph {
  workload_identity
  parallelism_identity
  logical_participant_inventory_identity
  participants[]
  participant_groups[]
  bound_operations[]   { source_operation_id, group_id, members[] }
}
```

**No physical endpoint ids.** Must be valid **without SYSTEM or FABRIC**.
Identity derives from workload + parallelism + inventory — never from
placement.

Enables the distinction: *same workload, different TP → different bound
graph*; *same bound graph, different placement → same logical binding,
different mapping*.

## 15. TP semantics

**TP is a communication participant dimension, and nothing more.** There is
**no tensor-sharding law, no attention-head partition, no FFN partition**
contract in the repository. TP does not encode model sharding; it names a
group family. State this plainly — do not market TP as sharding semantics.

## 16. DP semantics

DP is a **collective axis** (and a group family). There is **no gradient
semantics, no replica identity, no replication contract**. In static
evaluation DP means only "these participants share `(t,p,e)` and vary `d`".

**DP=1:** the DP family yields one group of size 1. That group is a
**one-member group** (§28) — see the law there.

## 17. PP semantics — honest classification

| Aspect | Status |
|---|---|
| PP as coordinate dimension | **R2** |
| PP as a group family ("stages") | **R2** (`parallelism.py:14`) |
| PP stage **assignment** model | **R0** |
| PP-dimension COLLECTIVE | **REFUSED** (`intent_lowering.py:185`) |
| PP point-to-point between adjacent stages | **R0** — no stage adjacency, no directional lowering |
| `pp > 1` shape | **DECLARABLE SHAPE / WORKLOAD STAGE BINDING INCOMPLETE** |

**PP is not a collective axis.** Stages communicate point-to-point; the
refusal message says exactly that. A numeric `pp > 1` exists **without**
stage semantics. This is a **capability gap**, visible in the matrix — not a
malformed intent.

## 18. EP semantics

EP is a **group-construction dimension only**. Domain B removed MoE meaning
from EP. Domain C defines EP group construction; **not** dispatch, combine,
or expert routing.

`EP groups = tp·pp·dp`, each varying `e` at fixed `(t,p,d)`.

## 19. MoE boundary

| Concept | Owner |
|---|---|
| `num_experts`, `top_k` | **ModelSpec** (WORKLOAD) |
| EP extent | **ParallelismIntent** |
| EP group membership | **PARALLELISM** |
| expert→rank assignment | **R0 in the compiler** — only `tools/chakra_to_dse.py:272` does round-robin; serving/tool-side |
| dispatch / combine | **WORKLOAD** (explicit operations) |

**`num_experts % EP == 0` is enforced nowhere.** Do **not** infer evenly
divided experts.

## 20. SYSTEM feasibility boundary

SYSTEM supplies `compute_instance_count`; PARALLELISM demands
`world_size`. Feasibility (`world_size <= usable compute instances`) belongs
**PLACEMENT / cross-domain validation**.

`ParallelismIntent` with `TP8·DP8·EP8` is **semantically valid** even when
the system cannot place it. The later result is `PLACEMENT REFUSED`, never
malformed parallelism.

## 21. Placement boundary

`derive_mapping` binds rank `r` to the `r`-th compute instance in canonical
`NodeInventory` order and **refuses oversubscription**. So:

- mapping is **injective** — one rank → one distinct compute instance;
- **multiple logical ranks → one compute agent is not legal**;
- **idle compute agents are legal** (more compute than ranks is fine).

No endpoint id enters `ParallelismIntent`.

## 22. Serving projection

**Target law:** `ParallelismIntent → ServingParallelismProjection`, with
**equivalence validation**.

Today LLMServingSim independently owns model and parallelism from its
cluster config; the static path gets them from the CompileRequest. That is a
**duplicate authority** and the highest-risk item in this domain.

Rules:

- `ParallelismIntent` remains authority for numeric logical shape;
- serving remains authority for instances/scheduling;
- a serving configuration whose shape contradicts `ParallelismIntent`
  **fails equivalence validation** — it is never silently preferred (C29);
- if serving interprets a dimension differently, it is **not** called an
  identical projection; the incompatibility is documented.

## 23. Serving-instance boundary

**Locked.** `ServingInstanceId ≠ LogicalParticipantId`.

```text
ServingInstance --owns--> virtual NPU span (contiguous)
virtual NPU --translates--> canonical rank --mapping--> agent --attachment--> endpoint
```

The vendored scheduler requires a **contiguous** NPU span per instance, while
canonical ranks are permuted onto non-contiguous endpoints — hence an
explicit virtual namespace translated "never by numeric coincidence"
(`serving_loop.py:26`). One instance may own multiple ranks.

**Serving does not use the canonical rank algebra.** That is a documented
namespace difference, not a shared identity.

## 24. ASTRA rank boundary

**ASTRA rank is the endpoint namespace**, not the logical participant.

```text
endpoint --> BookSim fabric node == ASTRA Sys.id
"ASTRA operates in the endpoint namespace … Nothing may assume rank == endpoint."
```

ASTRA communicator groups carry **endpoint ids**. So P18: communicator groups
are the **endpoint projection** of dimension groups — not identical to them.

## 25. Endpoint boundary

```text
LogicalParticipant → MappingArtifact → AgentInstance
  → AgentAttachmentArtifact → endpoint
```

`rank → endpoint` is **derived downstream**. No endpoint ids in
`ParallelismIntent` or `BoundWorkloadGraph` (C31, C32).

## 26. Intrinsic validation

Integer · `>= 1` · exact `int` (no bool, no float) · schema version exact ·
overflow-safe product · strict keys. **No machine-capacity maximum** — the
current system's capacity is not a schema bound.

## 27. Cross-domain validation

`world_size <= compute_instances` (PLACEMENT) · model divisibility
(ModelSpec ⊕ Parallelism) · serving equivalence (§22) · collective
one-member law (§28).

## 28. One-member semantics

**Law: a one-member collective is never represented.**

Evidence: `operations.py:82` — *"a one-member collective intent is never
represented"* (`len(participants) >= 2`); `collective_schedule` requires
`k >= 2`.

Therefore for a dimension with extent 1:

| Situation | Result |
|---|---|
| dimension extent 1 | the group **exists** with one member |
| a COLLECTIVE over that group | **REFUSED at intent construction** |
| a COMPUTE operation | unaffected |

**Chosen canonical model: the dimension exists with extent 1** (identity
stays simple, §22 of the brief). Communication over a size-1 group is
**refused**, not elided and not a no-op — one rule for every lowering path.

## 29. Model-divisibility laws

**Inventory: none are enforced.** No `hidden_size % TP`,
`attention_heads % TP`, `num_experts % EP`, or `num_layers % PP` check
exists anywhere in the compiler. The only `%` uses are the rank algebra.

**Classification:** these are **cross-domain** checks
(`ModelSpec ⊕ ParallelismIntent`), **not** intrinsic parallelism validation.

**Capability gap, stated:** the repository does **not** claim full sharding
correctness. A shape that cannot shard the declared model is accepted today.
C22–C24 record the actual behaviour; the gap is not papered over.

## 30. Change classes

| Field | Class |
|---|---|
| `tp`, `dp`, `pp`, `ep` | **LOGICAL_TOPOLOGY** |
| `schema_version` | CONTRACT_VERSION |

## 31. Invalidation

```text
TP2 → TP4
  WorkloadIntent                    UNCHANGED
  ModelSpec                         UNCHANGED
  SYSTEM physical inventory         UNCHANGED
  Request trace                     UNCHANGED
  ParallelismIntent                 CHANGED
  LogicalParticipantInventory       CHANGED
  BoundWorkloadGraph                CHANGED
  Placement                         STALE
  Mapping                           STALE
  Attachments                       STALE
  Routes / VC                       STALE
  Traffic                           STALE
  Evaluation                        STALE
```

Mirror cases: request trace → PARALLELISM unchanged (C34); compute-tile
count → PARALLELISM unchanged, feasibility may change (C33); hidden size →
PARALLELISM unchanged, cross-domain compatibility may change (C35);
collective algorithm → PARALLELISM unchanged (C36).

## 32. Migration

| Source | Field | Target | Lossless? | Conflict rule |
|---|---|---|---|---|
| `WorkloadGraph.parallelism` | shape | `ParallelismIntent` | yes | — |
| `WorkloadGraph.participant_count` | count | **dropped** → derived `world_size` | yes | must equal product, else REFUSE |
| `WorkloadArtifact.parallelism` | shape | `ParallelismIntent` | yes | — |
| `WorkloadArtifact.num_participants` | count | dropped → derived | yes | must equal product, else REFUSE |
| `WorkloadV3.tp/pp/ep/dp` | shape | `ParallelismIntent` | yes | — |
| `WorkloadV3.world_size` | — | **dead property; remove** | n/a | broken import |
| `FabricIntentView.tp/pp/ep/dp` | shape | projection of `ParallelismIntent` | yes | — |
| serving cluster config | shape | `ServingParallelismProjection` | **only with equivalence validation** | **CONFLICT → REFUSE** |
| `reference_semantics` coords | — | stays independent | n/a | deliberate differential |

**No legacy conflict is resolved silently.**

## 33. Duplicate-authority conflicts

| Case | Verdict |
|---|---|
| static TP=4, serving TP=8 | **CONFLICT — refuse, do not pick one** (C29) |
| `participant_count=8`, product=16 | **CONFLICT — refuse** |
| legacy `world_size=8`, product=8 | validated redundancy, then **removed** |
| two legacy shapes disagree | **refuse migration**; require explicit resolution |

## 34. Canonical contracts

`ParallelismShape` `placement.py:33` (algebra) · `rank_of`/`coords_of`
`placement.py:68,82` · `ParallelismArtifact` + `Group` `parallelism.py:57,42`
· `LogicalRank`/`NodeInventory` `placement.py:134,157` ·
`_groups_for_dimension` `intent_lowering.py:144` ·
`reference_semantics.py:27` (independent) · `astra_namespace.py` (endpoint
projection).

## 35. Derived artifacts

`LogicalParticipantInventory` (in-memory, §10) · `BoundWorkloadGraph`
(§14) · `ServingParallelismProjection` (§22) · group list per family (§11) ·
`world_size` (§5).

## 36. Unsupported / deferred

| Concept | State |
|---|---|
| PP stage assignment | `CONTRACT NOT AVAILABLE` |
| PP point-to-point lowering | `CONTRACT NOT AVAILABLE` |
| DP replica / gradient semantics | `CONTRACT NOT AVAILABLE` |
| TP sharding law (heads/FFN) | `CONTRACT NOT AVAILABLE` |
| expert→EP-rank assignment | tool/serving-side only |
| model divisibility laws | **not enforced — capability gap** |
| arbitrary/custom axes | refused |
| partial-membership collectives (serving) | not supported |
| `PP`-dimension collective | `UNSUPPORTED` |

## 37. Required user flows (structure only)

**Guided:** TP / DP / PP / EP with live `world_size`, plus compatibility
rows — *System capacity · Workload binding · Serving projection*.

**Expert:** Shape · Participants · Groups · Compatibility · Derived bindings,
with a rank/coordinate browser and a group browser
(`TP group 0 → ranks 0,1`).

**Never here:** endpoints, routers, instances, routes, VCs.

## 38. Adversarial cases

| # | Case | Verdict |
|---|---|---|
| C1 | TP1 DP1 PP1 EP1 | VALID; all families size 1; any COLLECTIVE refuses (§28) |
| C2 | TP=8 only | VALID; 1 TP group of 8; DP/PP/EP groups size 1 |
| C3 | DP=8 only | VALID; 1 DP group of 8 |
| C4 | PP=4 only | VALID shape; **stage binding incomplete**; PP-collective refuses |
| C5 | EP=8 only | VALID; 1 EP group of 8 |
| C6 | TP2 DP2 PP2 EP2 | VALID; world 16 |
| C7 | zero dimension | INVALID |
| C8 | negative | INVALID |
| C9 | non-integer / bool | INVALID (exact int) |
| C10 | overflow product | INVALID — deterministic overflow rejection |
| C11 | TP4 EP1 vs TP2 EP2 | **different `ParallelismIntent` identity** |
| C12 | serialization field reorder | same identity |
| C13–C16 | TP / DP / PP / EP group enumeration | counts per §11 formulas |
| C17 | flatten/unflatten round-trip | identity for all ranks |
| C18 | one-member TP collective | **REFUSED** |
| C19 | one-member DP collective | **REFUSED** |
| C20 | one-member EP generic operation | **REFUSED** |
| C21 | world_size > compute instances | **parallelism VALID; placement infeasible** |
| C22 | `hidden_size % TP != 0` | **accepted today** — no divisibility law (gap) |
| C23 | `num_experts % EP != 0` | **accepted today** — gap |
| C24 | `num_layers % PP != 0` | **accepted today** — gap |
| C25 | TP operation with TP=1 | refused at binding (one-member) |
| C26 | EP dispatch with EP=1 | refused at binding |
| C27 | generic EP ALLTOALL with EP=4 | VALID; 1 EP group of 4; **not MoE** |
| C28 | same `WorkloadIntent`, TP2 vs TP8 | same workload identity; **different parallelism + bound graph** |
| C29 | static TP4, serving TP8 | **CONFLICT — refuse** |
| C30 | serving instance owns ranks 0–3 | instance identity distinct from participants |
| C31 | rank mapped to endpoint | mapping downstream; no endpoint in PARALLELISM |
| C32 | endpoint assignment changed | PARALLELISM identity unchanged |
| C33 | SYSTEM compute count changed | PARALLELISM unchanged; feasibility may change |
| C34 | request trace changed | PARALLELISM unchanged |
| C35 | hidden size changed | PARALLELISM unchanged; compatibility may change |
| C36 | collective algorithm changed | PARALLELISM unchanged |
| C37 | unknown axis | fail closed |
| C38 | legacy duplicates agree | migration succeeds, normalizes to one authority |
| C39 | legacy duplicates disagree | **migration refuses** |
| C40 | group ids under serialization reorder | **stable** (family + fixed coords) |

## 39. Research questions P1–P18

| # | Question | Answer |
|---|---|---|
| P1 | canonical dimension order | algebra `TP,EP,DP,PP`; declaration `tp,pp,ep,dp` (§6) |
| P2 | rank-flattening law | `((p*dp+d)*ep+e)*tp+t` (§9) |
| P3 | are groups materialized | yes — `ParallelismArtifact.groups`, and mirrored in `intent_lowering` |
| P4 | group ids stable or positional | **stable** — `(family, fixed coordinates)` |
| P5 | what PP means | coordinate dimension + stage family; **no assignment model** |
| P6 | what DP means statically | a collective axis only; no gradient semantics |
| P7 | does serving use the same rank space | **no** — virtual NPU namespace |
| P8 | ASTRA rank == logical participant? | **no** — endpoint namespace |
| P9 | one-member collectives | **refused**, never represented |
| P10 | divisibility laws enforced? | **no** — gap |
| P11 | expert→EP-rank assignment | tool/serving-side only (`chakra_to_dse.py:272`) |
| P12 | `world_size == TP·DP·PP·EP` everywhere? | yes in the algebra; validated against stored values |
| P13 | idle compute agents legal? | **yes** — topology seats every agent |
| P14 | multiple ranks → one agent? | **no** — mapping is injective |
| P15 | mapping injective? | **yes**; oversubscription refuses |
| P16 | groups as persisted artifacts? | possible (`ParallelismArtifact` is a persisted resource); inventory stays in-memory |
| P17 | does serving multiply ranks? | instances own virtual NPU spans; not the canonical rank count |
| P18 | communicator groups == dimension groups? | **no** — endpoint projection |

**No question is unanswered.**

## 40. Remaining blockers

1. **Seven numeric authorities** — convergence is designed, not implemented.
2. **Serving duplicate authority** — equivalence validation is specified, not built.
3. **PP stage binding incomplete** — capability gap, visible in the matrix.
4. **Model divisibility laws absent** — capability gap.
5. Global decisions **D1–D8** open.

None of these is an incoherence in the *boundary*; each is recorded with an
owner.

## 41. Domain verdict

All 24 coherence conditions are satisfied **at the design level**:

one target numeric authority (`ParallelismIntentV4`, evolving the existing
`ParallelismArtifact`) · seven authorities inventoried with target owners ·
world-size law verified · dimension order declared twice and distinctly ·
flatten/unflatten law locked with round-trip tests · participant identity
defined · group derivation verified against code with count formulas ·
stable group identity by `(family, fixed coordinates)` · binding multiplicity
stated explicitly (one operation → one bound operation **per group of the
family**) · SYSTEM feasibility correctly cross-domain · serving-instance and
ASTRA-rank boundaries explicit · serving duplicate authority has a
projection + equivalence strategy · endpoint boundary explicit · one-member
law chosen (dimension exists; communication refuses) · PP and DP honestly
classified · EP/expert-assignment boundary explicit · divisibility gap
recorded · inventory home decided with rationale · duplicate conflicts fail
closed · C1–C40 verdicts · **P1–P18 all answered** · COMMUNICATION not begun.

**PARALLELISM INTENT: PLANNED — COHERENT**
