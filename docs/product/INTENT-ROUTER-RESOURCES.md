# INTENT-ROUTER-RESOURCES — Domain H specification (Gate 2, closure pass)

Domain row: `intent-ontology.yaml :: domains.ROUTER_RESOURCE_INTENT`
Enforced by: `scripts/check_intent_ontology.py`
Supersedes the first-pass audit. **Design closure only** — ROUTER-D1/D2, VC-D1/D2, VERIFY-D1, BACKEND-D1, OBS-D1 not implemented.

---

## 0. The locked conclusion

```text
RouterResourceIntentV4 {
  arbitration_policy: ISLIP | ROUND_ROBIN      # the ONLY declared field
}
```

Everything else is **derived** (routing, VC count, VC assignment, turn
restrictions), **candidate-owned** (buffers, speedups), **verification** (CDG,
certificate), **backend** (qualification, projections), or **unsupported**
(RCU, multicast, torus routing, valiant, adaptive).

## 1. Routing is not user intent — locked

`NocConfig` intentionally has no routing override:

> *"An override isn't something the compiler refuses — it's something that
> **cannot be expressed**."*

```text
MESH topology → canonical routing semantics → DOR_XY RouteArtifact
```

**No `routing = "dor_xy"` field is created.** The UI may show it as derived state.

## 2. Legacy `routing_function` demoted — ROUTER-D2

`dim_order` / `dor` / `min_adapt` are *"derived text that controlled no hardware
semantics"* (`routing.py`).

**Target law:**

```text
routing_function is NOT scientific routing authority.
The RouteArtifact table is execution authority.
```

It must not independently change `RouteArtifact` identity, `ResolvedRoute`
identity, the certificate result, or backend route authority.

**When legacy text disagrees with the authoritative `RouteArtifact`, the
canonical artifact wins — and migration/validation surfaces the inconsistency
rather than pretending agreement.** Two route authorities are not allowed.

## 3. ROUTER-D2 migration path

```text
1. parse the known legacy spelling
2. map it to a NON-authoritative compatibility representation
3. verify it against canonical routing semantics where possible
4. refuse ONLY where the old schema explicitly requires semantic consistency
5. NEVER derive exact routes from the string when a RouteArtifact is present
```

**Deletion stage:** the field disappears from the target contract entirely; a
legacy loader may carry it as ignored compatibility text that **cannot enter
identity**.

## 4. `RoutingClassDefinition` remains the routing-semantics authority

**No `ROUTE-D1` object is introduced.** One authority, already bound:

```text
{ id, algorithm, algorithm_version, parameters }
```

| Question | Answer |
|---|---|
| what participates | `id`, `algorithm`, `algorithm_version`, `parameters` — all of it |
| what `algorithm_version` means | the semantics revision of that class's algorithm |
| effect on `RouteArtifact` identity | the classes are part of `route_table_hash` and `artifact_hash` |
| unknown algorithm version | **fail closed** |

**`ROUTE-D1` is NOT recorded as debt** — the binding already exists.

## 5. `RouteArtifact` law — locked

```text
(class, src_router, dst_router) → channel_id
```

A **compact next-hop execution law**, not a hint. It must prove **whole-route
termination**: repeatedly applying the table must reach the destination without
looping or referencing an invalid channel. *"A table can pick a legal first
channel for every pair and still loop forever."*

Validation detects every-first-hop-locally-legal-but-non-terminating tables.
**Mandatory canonical correctness.**

## 6. `RouteArtifact` identity

```text
parents: topology_hash  +  RoutingClassDefinition (algorithm_version)
```

**Communication classes are NOT parents** — similar words do not create
dependencies. **Mapping and Requirements are not parents.**

## 7. `ResolvedRouteArtifact` law

```text
RouteArtifact        = router-level next-hop authority
ResolvedRouteArtifact = endpoint-resolved routing authority after attachment
```

`LOCAL_EJECTION` remains the correct semantic for same-router endpoint pairs.
**No network channel is fabricated for local ejection.**

## 8. `ResolvedRoute` integrity

Parents: **`RouteArtifact` + `AgentAttachmentArtifact` (+ topology
transitively)**. The endpoint expansion is **not stored** — a compact digest plus
deterministic re-derivation; `validate_against()` recomputes it, so *"a
fabricated endpoint-table hash cannot pass."*

| Change | RouteArtifact | ResolvedRoute |
|---|---|---|
| attachment | **unchanged** | **changes** |
| **MappingArtifact** | **unchanged** | **unchanged** |

Mapping is participant→agent, not agent→endpoint — so it touches neither
routing artifact.

## 9. VC count is derived — locked

```text
derive_vc_count(graph) = 1 + (cycle witnesses needing separation)
                        1 when there are no cycles
vc_count > PLANE_C_MAX_VC (= 8) → UNSUPPORTED, never clamped
```

**No `VC count = 2` Design control.** The formula and invariants are documented
from code.

## 10. `VCAssignment` is derived

Exact class→VC assignment is compiler-owned. **No intent field for VC0, VC1 or
an escape VC number.** Post-compile inspection only.

## 11. VC-D1 closure — `VCAssignmentSemanticsIdentity`

The defect: `VCAssignmentArtifact.derivation` is **provenance**, excluded from
identity. Target identity binds:

```text
authoritative parents  +  assignment semantics/version  +  resulting assignment
```

**Changing the derivation algorithm must move `VCAssignmentArtifact` identity
even when a test case coincidentally produces identical bindings** — the same
rule as `RANK_ORDER_V1` and `ATTACHMENT_ORDER_V1`.

## 12. VC derivation authority — exact

| Step | Law |
|---|---|
| class enumeration | sorted distinct classes from the route + communication declarations |
| cycle detection | `find_cycles()` — **deterministic DFS witnesses**, not an exhaustive list |
| separation | each witness needs ≥1 member on a distinct VC; the least-cost victim is chosen |
| VC ids | dense `0..vc_count-1`; `vc_ids == tuple(range(vc_count))` |
| routing class default | **every VC uses the resolved route's default routing class** |
| transitions default | **VC-preserving only** — *"silent cross-VC hops are how deadlock proofs get falsified"* |
| escape designation | **empty** (`escape_vcs=()`) |
| tie ordering | sorted iteration throughout — **no dict/set accidents** |

## 13. VC-D2 closure — the real meaning

The audit resolves the debt label: there is **no user-facing VC budget** in
canonical intent, so VC-D2 is **not** "resource insufficiency against a declared
budget". It is:

```text
typed derivation failure when the derived requirement cannot be represented:
  vc_count > PLANE_C_MAX_VC        → UNSUPPORTED (never clamped)
  a class bound to an unmaterialized routing class → UNSUPPORTED at the CDG
```

**No `vc_budget` field is introduced.**

## 14. VC namespace — locked

VC ids are **global symbolic dense integers `0..vc_count-1`**, referenced by
`vc_to_routing_class` and `RouterBehaviorArtifact`. **Not per-channel, not
per-router, not per-class.** The UI must say what `VC 1` means rather than
showing a bare integer.

## 15. Escape VCs — designation, and **currently never populated**

Two facts:

1. **Law:** *"a designated escape VC is evidence only: it is reported, and it
   NEVER bypasses graph analysis or produces PASS by itself."*
2. **Reality:** the v3 derivation path produces **no escape VCs at all** —
   `make_vc_assignment_artifact` defaults `escape_vcs=()` and the compiler never
   passes one.

**So escape is a supported-but-unused designation.** It does not bypass the CDG,
cycle detection or parent validation.

## 16. Class-transition convention — locked

```text
class_in  selects the channel currently HELD
class_out selects the REQUESTED next channel
```

Deriving both from `class_out` is wrong: *"it invents dependencies for packets
that never travelled the `class_out` path."*

**Explicit regression property required.**

## 17. Cross-class transitions are derived

From compiled route + resource semantics. **Not `CommunicationIntent`, not
editable `RouterIntent`.** No `transition A→B` user control.

## 18. Channel-VC CDG — exact categories

| Input | Verdict |
|---|---|
| malformed parents | **hard failure** (`CDGError`) — never `UNSUPPORTED`, never `PASS` |
| valid but unsupported construction | **`UNSUPPORTED`** |
| actual dependency cycle | **`FAIL`** |
| acyclic valid graph | **`PASS`** |

## 19. Deterministic cycle witness

Confirmed by construction: `edges=tuple(sorted(edges))`,
`cdg_route_classes=tuple(sorted(declared))`, sorted class and table iteration,
and *"first cycle in deterministic DFS order."*

**Same graph → same witness.** This underpins regression tests, Studio
debugging and evidence comparison.

## 20. Turn restrictions are derived

Source: the cycle structure (`_routing_for_cycle_structure` /
`derive_vc_assignment`). `views.py` **omits** the list rather than fabricating
it. **Read-only view. Never `RouterResourceIntent`.**

## 21. Arbitration — the one genuine intent field

```text
RouterResourceIntentV4 { arbitration_policy: ArbitrationPolicy }
ArbitrationPolicy = ISLIP | ROUND_ROBIN
```

**A canonical enum, not an arbitrary string.**

## 22. Arbitration alias normalization

```text
None · "islip" · " iSLIP "        → ISLIP
"round_robin" · "round-robin" · "rr" · "RR" → ROUND_ROBIN
unknown                            → RouterBehaviorError, fail closed
```

*"Raw spelling is not part of semantic identity."* **Canonicalization occurs
before hashing.** Unknown values are **never** mapped to iSLIP.

## 23. Arbitration semantic scope

| Question | Answer |
|---|---|
| what it controls | `vc_allocator` **and** `switch_allocator` — one intent value configures both |
| may they diverge? | not from intent; both derive from the single policy |
| scope | **global to all routers** |
| class-aware? | **no** — class-independent |
| topology restriction | none |

## 24. `RouterBehaviorArtifact` — a real canonical artifact

Consumers verified: `views` · `resolved_fabric` · `resolved_bundle` ·
`fabric_artifact` · `orchestration` · `canonical` · **`certificate`** ·
**`channel_vc_cdg`** · `meshdor` · `booksim`.

**It is consumed by both backends and by verification** — it is **not**
backend-only, which is the decisive evidence that arbitration is canonical
intent.

Identity includes buffers, flow control, allocators, speedups and per-stage
latencies: *"every resolved semantic field participates."*

## 25. Buffers are **not** Design Intent

They participate in `RouterBehaviorArtifact` identity but originate from
`FabricCompileSettings` / `BASELINE_FABRIC_SETTINGS` — the **candidate recipe**,
identified by `CandidatePolicy`.

**No buffer controls in `RouterResourceIntent`.** Ownership boundary recorded for
**DESIGN-SPACE / candidate generation** (Domain J) — not designed here.

## 26. Four categories, never mixed

| Category | Examples | Owner |
|---|---|---|
| **user declaration** | `arbitration_policy` | RouterResourceIntent |
| **candidate-owned** | buffers, speedups, per-stage latencies | candidate / Domain J |
| **compiler-derived** | routes, VC assignment, turn restrictions | compiler |
| **backend profile** | BookSim config, injection | backend |
| **qualification** | native-profile predicates | backend authority |

## 27–29. RCU, in-network reduction, hardware multicast

| Concept | Verdict |
|---|---|
| RCU | **REMOVE from v4**; no canonical consumed artifact → **FUTURE CAPABILITY CONTRACT** |
| in-network reduction | **unavailable** — *semantic REDUCE does not imply physical router reduction* |
| hardware multicast | **FUTURE CAPABILITY CONTRACT** — *multiple output ports are not multicast capability* |

**No `rcu=true` checkbox. None recorded as v4 implementation debt.**

## 30–31. Channel/router latency and route weights

| Concept | Owner |
|---|---|
| `DirectedChannel.latency_cycles` | **FABRIC** (Domain G); native profile requires **exactly 1** |
| `route_weight` | **channel field** (FABRIC), default 1; native profile requires 1 |
| router pipeline latency (`route_compute_cycles`, `vc_alloc_cycles`, …) | **candidate-owned** inside `RouterBehaviorArtifact` |

**No duplicate authority. None is user intent.**

## 32. `BackendQualificationProfile` — explicit and versioned

```text
BackendQualificationProfile {
  profile_id
  semantics_version
  predicates[]        # typed codes, never executable strings
}
```

**One versioned identity for the qualification conditions**, replacing implicit
`if` conditions.

## 33. `CERTIFIED_BOOKSIM_MESH_DOR_XY_V1` — explicit predicates

```text
P1  topology family == MESH
P2  square k×k router grid
P3  every router seat_capacity == 1
P4  identity-prefix attachment: dense endpoint ids 0..E-1 AND endpoint i → router i
P5  RouteArtifact realizes DOR_XY
P6  every VC binds DOR_XY
P7  uniform channel latency == 1
P8  route_weight == 1
P9  no parallel channels
P10 single traffic class over the full VC set
P11 identity transitions
```

**All verified from code. None omitted, none broadened.**

## 34. Qualification ≠ design validity

```text
concentration 2
  → FabricIntent VALID · RouteArtifact VALID · VCAssignment VALID
  → native profile NOT QUALIFIED
```

**Failure to satisfy the native profile never implies invalid canonical
artifacts.** This separation survives into Studio.

## 35. BACKEND-D1 closure — `QualificationResult`

```text
QualificationResult {
  profile_id
  profile_semantics_version
  status                    # QUALIFIED | NOT_QUALIFIED
  failed_predicates[]       # typed codes with observed/expected values
}
```

**Machine-readable**, using the existing evidence framework where similar
contracts exist. Profile logic is not left dispersed across `if` statements with
no semantic identity.

## 36. Qualification profile changes

A predicate-set change moves the **profile semantics identity**. Historical
evidence remains tied to the profile it was qualified under. **Old evidence is
never silently reinterpreted under a stricter or looser profile.**

## 37. AnyNet — two meanings, two namespaces

| Meaning | Layer |
|---|---|
| **AnyNet algorithm** | `anynet_dijkstra_hops` — a Dijkstra-hop routing mechanism |
| **AnyNet projection** | `CERTIFIED_BOOKSIM_ANYNET_V1` — a generic backend network representation |

**Neither is user intent.** No single "AnyNet" switch.

## 38. AnyNet evidence tier

`qualify_anynet_min_hops` exists — **AnyNet is a certified profile, not an
experimental fallback.** Its evidence tier and limitations are **separate** from
the native profile, and it is not called a fallback that preserves scientific
equivalence beyond what its qualification proves.

## 39. Five-layer backend capability state

```text
CANONICAL VALIDITY · BACKEND PROJECTABLE · BACKEND EXECUTABLE
· BACKEND QUALIFIED · EVIDENCE CLAIM SCOPE
```

**Never collapsed into SUPPORTED / UNSUPPORTED.**

## 40. FIRST-HOP evidence scope — OBS-D1 locked

```text
canonical expected FIRST HOP  vs  backend executed FIRST HOP
compared MECHANICALLY, per entry
```

Evidence scope is **`FIRST_HOP_VERIFIED`**. **Never `FULL_PATH_VERIFIED`.**

## 41. Expected route vs observed route — two truths

```text
CANONICAL FULL ROUTE DERIVED          (by repeated next-hop application)
BACKEND FIRST HOP OBSERVED AND MATCHED
```

Studio must keep them separate and **never render expected intermediate hops as
observed backend hops**.

## 42. OBS-D1 target contract

```text
RouteObservationScope { FIRST_HOP, FULL_PATH }
```

Current backend evidence: **`FIRST_HOP`**. `FULL_PATH` is not advertised until a
backend trace proves it. If the current evidence type cannot encode scope, that
is explicit implementation debt.

## 43. `route_equivalence` semantics

It is **first-hop equality** between the canonical expectation and the executed
dump. **The name must not imply full-route equivalence** — rename/document
accordingly (OBS-D1).

## 44. VERIFY-D1 closure — the real defect

The defect is **not** parent binding generally; it is that **verification
semantics identity is not explicit** and that certificate replayability depends
on parent hashes being carried correctly through every obligation's evidence.

**Target:** a certificate must bind **all scientific parents necessary to prove
the verdict belongs to this exact topology / routes / VC assignment**, and must
**not be replayable against mismatched artifacts** (H104).

## 45. Certificate claim matrix

| Obligation | Proves | Does NOT prove |
|---|---|---|
| `ATTACHMENT_COMPLETE` | every design agent is attached, seats proven (`attachment.validate_against/v1`) | fabric routing |
| `ROUTE_COMPLETE` | the route table covers every class×src×dst pair (`entry-coverage/v1`) | route legality |
| `ROUTE_LEGAL` | every route is channel-legal **and terminates** (`route.validate_against/v1`) | deadlock freedom |
| `DEADLOCK_FREE` | `CHANNEL_VC_DEPENDENCY_ACYCLIC` over the realized CDG | attachment completeness (the CDG states this explicitly) |
| others | as enumerated in `LOCKED_OBLIGATIONS` | — |

**A LOCKED obligation that is not PASS means the fabric is not valid with this
certificate as evidence. No obligation may be skipped.**

## 46. Certificate ≠ qualification

```text
VerificationCertificate : canonical compiler/verifier correctness
QualificationResult     : the backend may legitimately execute / authorize evidence
```

**A canonical certificate PASS may coexist with native BookSim NOT QUALIFIED.**

## 47. `RouterResourceIntent` identity

**Only `arbitration_policy`.** Derived routing, VC count, turn restrictions and
escape assignment have their own artifacts and parent chains and are **never** in
this hash.

## 48. Applicability across backends

`RouterBehaviorArtifact` is consumed by `meshdor`, `booksim`, the certificate
and the CDG — so arbitration is **canonical router behavior, not backend-only**.

An analytical/ASTRA path that ignores the allocator does not make the field
backend-only; it means **that path's evidence is unaffected by it**. Precise
statement, not a downgrade.

## 49. `RouterBehaviorArtifact` parentage

```text
RouterResourceIntent identity  (arbitration)
+ candidate-owned router resource state  (buffers, speedups, latencies)
+ router-behavior semantics identity
```

**Candidate-owned buffer state stays separate from declared arbitration intent,
even though both appear in the same artifact.**

## 50. Candidate provenance

Where the artifact mixes intent-owned and candidate-owned values, it must
preserve **which parent supplied each value**. **Values are not duplicated across
authorities.** This matters for DESIGN-SPACE.

## 51. Change / invalidation laws

| Change | RouterResourceIntent | RouterBehavior | Route | ResolvedRoute | VCAssignment | CDG | Certificate | Backend evidence |
|---|---|---|---|---|---|---|---|---|
| **arbitration** | **changes** | **changes** | unchanged | unchanged | unchanged | unchanged | **changes** (via `fabric_hash`) | stale |
| routing semantics | unchanged | unchanged | **changes** | changes | changes | changes | changes | stale |
| VC-assignment semantics | unchanged | unchanged | unchanged | unchanged | **changes** | changes | changes | stale |
| buffer candidate | unchanged | **changes** | unchanged | unchanged | unchanged | unchanged | changes | stale |
| qualification profile | unchanged | unchanged | unchanged | unchanged | unchanged | unchanged | unchanged | **admissibility changes** |
| communication class | unchanged | unchanged | **unchanged** | unchanged | **changes** | changes | changes | stale |
| attachment | unchanged | unchanged | **unchanged** | **changes** | changes | changes | changes | stale |
| mapping only | unchanged | unchanged | unchanged | unchanged | unchanged | unchanged | unchanged | unchanged |

## 52. Native-profile failure diagnostics

```text
profile  CERTIFIED_BOOKSIM_MESH_DOR_XY_V1
status   NOT_QUALIFIED
reasons  [ concentration: observed 2, expected 1 ]
         [ traffic_class_count: observed 2, expected 1 ]
```

**Never a generic "unsupported configuration."**

## 53. Torus staged state

```text
Torus topology      : VALID / DERIVED
Route derivation    : UNAVAILABLE — no canonical route generator
```

**Not a `RouterIntent` failure.** No user routing override exists to "fix" it.
Future torus routing requires **new compiler routing semantics**.

## 54. Valiant / adaptive

**FUTURE CAPABILITY CONTRACT, not v4 debt.** Legacy enum values must
**migrate or refuse explicitly** — they are not kept as apparent supported
choices.

## 55. Buffers — Domain J handoff

Router resource **candidate dimensions** include the `FabricCompileSettings`
fields already in `RouterBehaviorArtifact` identity. **No primary Design UI
control.** Domain J is not designed here.

## 56. Current Intent UI disposition

| Concept | Disposition |
|---|---|
| Routing | **READ-ONLY DERIVED** |
| VC count | **READ-ONLY DERIVED** |
| Turn restrictions | **READ-ONLY DERIVED** |
| Certificate | **POST-COMPILE VERIFICATION** |
| **Arbitration** | **KEEP** — the sole editable router resource field |
| RCU | **REMOVE / FUTURE CAPABILITY** |

**No control is preserved for visual continuity.**

## 57. Product IA

**No standalone Router Design page for one field.** Arbitration surfaces under
**Fabric → Advanced router behavior**.

After compile: **Mapping · Attachments · Topology · Routes · VCs · Deadlock ·
Qualification** — the scientifically rich part.

## 58. Derived router summary

```text
ROUTER BEHAVIOR
  Arbitration                 iSLIP
  Routing                     compiler-derived DOR_XY
  VC resources                derived after route dependency analysis
  Deadlock verification       pending compile
  Native BookSim qualification determined after compile
```

## 59–60. Inspector semantics

**Route inspector — two separated layers:**

```text
CANONICAL ROUTE     full expected path from RouteArtifact
BACKEND OBSERVATION first hop only, when evidence exists
```

**Qualification inspector — three-part distinction (mandatory):**

```text
Canonical verification   PASS / FAIL
Backend profile          QUALIFIED / NOT QUALIFIED
Evidence scope           FIRST-HOP VERIFIED
```

## 61. H1–H80 re-evaluated

H10 unsupported routing request → **cannot be expressed** · H14 routing semantics
change → artifacts change, **RouterResourceIntent unchanged** · H18/H19 VC count
→ **derived-state tests, not intent cases** · H20/H21 zero/negative VC count →
**the field does not exist** · H23/H24 class sharing → per assignment policy ·
H25/H26 escape → evidence/designation, **currently never populated** · **H30
VC0→ANYNET / VC1→DOR_XY → the `class_in`/`class_out` convention applies; a VC
bound to an unmaterialized class is UNSUPPORTED** · H36/H37 arbitration → the
only real intent field · H39 RCU → unavailable contract · **H43–H51 native
profile → qualification outcomes, not design validity** · **H53 canonical full
route + first-hop evidence → two separate truths** · H57 routing semantics
version → RouteArtifact identity changes · H58 VC semantics version →
VCAssignment identity changes.

## 62. H81–H105

| # | Case | Verdict |
|---|---|---|
| **H81** | legacy `min_adapt` but RouteArtifact is DOR_XY | **RouteArtifact authoritative; inconsistency surfaced; no second authority** |
| **H82** | legacy spelling change only | no canonical routing identity change |
| **H83** | same VC result, new derivation algorithm version | **artifact identity changes** |
| **H84** | same RouteArtifact, unchanged class version | stable identity |
| **H85** | full canonical route, backend first hop matches | **`FIRST_HOP_VERIFIED` only** |
| **H86** | backend first hop mismatches | evidence/qualification failure |
| **H87** | no first-hop observation | **no route observation claim** |
| **H88** | future full-hop trace | only then may `FULL_PATH` be introduced |
| **H89** | profile predicates reordered | same profile semantics identity (canonical set ordering) |
| **H90** | a predicate value changes | **profile semantics identity changes** |
| **H91** | historical evidence under an older profile | **remains bound to the old profile** |
| **H92** | certificate PASS + native NOT QUALIFIED | **valid state** |
| **H93** | certificate FAIL + backend number | number is **not** authoritative requirement evidence |
| **H94** | `None` vs `iSLIP` | **same identity** per the normalization law |
| **H95** | unknown arbitration alias | fail closed |
| **H96** | buffer candidate changes | Design Intent unchanged; RouterBehavior/evidence may change |
| **H97** | arbitration changes | Design Intent **and** RouterBehavior change |
| **H98** | routing changes, arbitration unchanged | route artifacts change; intent stable |
| **H99** | derived VC count changes via CDG structure | RouterResourceIntent unchanged |
| **H100** | communication classes reordered | VC assignment stable after canonicalization |
| **H101** | communication class id changes | VC assignment parent/binding changes |
| **H102** | qualification condition hard-coded outside the profile | **closure failure — profile incomplete** |
| **H103** | `route_equivalence` name implies more than first-hop | **rename/document before coherence** |
| **H104** | certificate parent mismatch | **fail closed** |
| **H105** | unknown verification/qualification schema | fail closed |

## 63. Implementation debt — normalized

```text
ROUTER-D1  typed RouterResourceIntentV4 carrying the canonical arbitration policy
ROUTER-D2  demote/remove legacy routing_function authority; surface inconsistency
VC-D1      bind VCAssignmentSemanticsIdentity into artifact identity
VC-D2      typed VC derivation/refusal diagnostics (over PLANE_C_MAX_VC; unmaterialized class)
VERIFY-D1  explicit verification-semantics identity + non-replayable certificate parents
BACKEND-D1 versioned BackendQualificationProfile + machine-readable QualificationResult
OBS-D1     RouteObservationScope typing; rename route_equivalence to first-hop
```

**Not recorded as v4 debt:** torus routing · adaptive routing · valiant ·
hardware multicast · RCU · buffers-as-intent · VC-count-as-intent. These are
**future capability contracts or out of scope**.

## 64. Domain closure law

```text
RouterResourceIntent  one field — arbitration
Routing               compiler derived
VC count              compiler derived
VCAssignment          compiler derived
Deadlock              mandatory verifier
Qualification         backend authority
Observation           first-hop only today
```

**No controls are added to make the domain appear richer.**

## 65. Domain verdict

The four fractures are closed at the design level.

**1. Legacy routing text is demoted.** `routing_function` becomes
non-authoritative compatibility text; the `RouteArtifact` table is execution
authority; disagreement is **surfaced, never silently accepted**; two route
authorities are forbidden.

**2. VC-assignment semantics is bound.** `VCAssignmentSemanticsIdentity` joins
`RANK_ORDER_V1` and `ATTACHMENT_ORDER_V1` as the third compiler-owned policy that
must move artifact identity even when a coincidence hides the change. And the
audit resolved VC-D2's real meaning: there is **no user VC budget**, so the debt
is a **typed derivation failure**, not resource insufficiency against a declared
budget.

**3. Qualification becomes an explicit versioned authority.**
`BackendQualificationProfile` with eleven verified predicates for
`CERTIFIED_BOOKSIM_MESH_DOR_XY_V1`, plus a machine-readable `QualificationResult`
carrying failed predicates with observed/expected values. **Qualification is not
design validity** — concentration 2 yields valid canonical artifacts and
`NOT_QUALIFIED`.

**4. First-hop observability is encoded honestly.** Evidence scope is
`FIRST_HOP_VERIFIED`; canonical full routes and observed first hops are **two
separate truths**; `route_equivalence` is documented as first-hop equality; and
`FULL_PATH` is not advertised until a backend trace proves it.

Two further results worth naming: **escape VCs are a supported-but-unused
designation** (the v3 path never populates one), and **arbitration is genuinely
canonical intent** — `RouterBehaviorArtifact` is consumed by both backends *and*
by the certificate and CDG, so it is not backend-only.

**ROUTER / ROUTING / RESOURCES: PLANNED — COHERENT**

Per Gate 2's rule, MEMORY is not begun.
