# FEATURE RECLAMATION AMENDMENT

> A bounded amendment to the frozen Gate 1–8 architecture, derived from
> repository evidence discovered after implementation began.

**This is not Gate 9.** No new gate, no new planning program. It is a change
ledger: *old decision → evidence → amended decision*, limited to the seven
confirmed findings A1–A7 from `FEATURE-RECLAMATION-AUDIT.md`.

**No implementation in this document.** It specifies the contracts and the
exact sequence. AMEND-0 (audit bookkeeping) is committed; AMEND-1..10 are
specified, not executed.

Companion: `docs/product/FEATURE-RECLAMATION-AUDIT.md`,
`docs/product/feature-reclamation-registry.yaml` (historical/target truth).
`capability-registry.yaml` (present canonical/product truth) is **not**
modified by this document — its corrections are AMEND-7.

---

## 0. AUDIT-SEAL CORRECTIONS (AMEND-0 — committed)

| Defect | Printed | Mechanically derived |
|---|---|---|
| Wave-F 21-item parity | `10 YES · 7 PARTIAL · 4 NO` | **`10 YES · 6 PARTIAL · 5 NO`** (YES 1,2,3,8,10,13,14,15,16,21; PARTIAL 4,5,9,11,12,20; NO 6,7,17,18,19) |
| T3 example parity | `9 YES · 6 PARTIAL · 17 NO` | **`11 YES · 4 PARTIAL · 13 NO`** = 28 |
| T4 serving parity | `28 YES · 3 PARTIAL · 3 NO` | **`29 YES · 2 PARTIAL · 4 NO`** = 35 |
| Thesis count | "six of eight verbs intact for both" | **five of eight** |
| Protected branches | `MET pending per-file diff` | `REPLACEMENT CONDITION LIKELY MET — ARCHIVAL NOT AUTHORIZED` |

**The suggested `11 · 5 · 5` is also not the correct Wave-F split.** The
derivation is now printed in the audit with its row lists.

The verbs `CURRENT` for **both** axes are exactly **ROUTE, VERIFY, EXECUTE,
COMPARE, VISUALIZE**. REPRESENT is PARTIAL (named) and
NEEDS_CANONICALIZATION (custom), so it cannot be counted.

---

## 1. THREE SELF-CORRECTIONS TO THE AUDIT (evidence found during this pass)

The audit's Part II raised contradictions C, D and E. **Two of them were
the audit's own error**, and the amendment must not be built on them.

### C was FALSE. `ROUTE-008` is already correct as staged.

The audit claimed the row contradicted sealed code because
`VCAssignmentArtifact.escape_vcs` exists (`model/vc_assignment.py:164`,
validated sorted-unique at `:249`). **That was a category error.** The row
is already staged:

```text
ROUTE-008 escape VC designation
  DECLARABLE YES · DERIVABLE YES · VERIFIABLE YES
  PROJECTABLE NO · EXECUTABLE NO · QUALIFIED NO · EVIDENCE_CAPABLE NO
  wiring NOT_AVAILABLE · reason IMPLEMENTATION_GAP
  claim_scope "supported-but-unused; no backend materialization"
```

The row says escape VC **is** declarable, derivable and verifiable — and is
**not** projectable or executable. That is exactly right: there is no
BookSim/ASTRA materialization of an escape VC. `IMPLEMENTATION_GAP`
describes the **wiring**, not the derivation.

The audit compared a wiring flag against an artifact's existence without
reading the stage breakdown — the precise mistake the staged model exists to
prevent. **No correction is required for `ROUTE-008`.**

### D was FALSE. `ROUTE-009` `FUTURE_CONTRACT` is correct.

The audit claimed a "full `RoutingPolicyDefinition` including `ADAPTIVE`"
contradicts the row. **`ADAPTIVE` is not a routing policy in that module.**
It is a member of `RoutingResourceRoleKind` (`routing_policy.py:115`) — the
*semantic role a VC subnetwork plays in a deadlock proof*, alongside
`ESCAPE`, `PHASE`, `RING`, `TAP`. And the same module states its own
boundary at line 20: *"adaptive/stateful policies → a future relation
artifact"*. `router_behavior.py:64-65`: *"Explicitly absent: escape/adaptive
priority, routing-action priority, congestion thresholds, MinAdapt/UGAL
arbitration."*

The row is all-NO with `FUTURE_CONTRACT`. **Correct. No correction
required for `ROUTE-009`.**

### E is REAL but MIS-STATED. `MEM-007` needs a stage, not a flip.

`MEM-007` and `MEM-006` are **structurally identical**:

```text
MEM-006 REMOTE/CXL/STORAGE   DECLARABLE LEGACY_ONLY · wiring NOT_AVAILABLE · reason LEGACY_ONLY
MEM-007 PIM                  DECLARABLE LEGACY_ONLY · wiring NOT_AVAILABLE · reason LEGACY_ONLY
```

But they are **not** the same situation. `memory_lowering.py` **refuses**
REMOTE/CXL/STORAGE with typed reasons. `KIND_PIM_CHANNEL` is **live and
consumed** in `workload/graph.py:88` and `backend/astra.py`.

So the defect is **not** `LEGACY_ONLY` being wrong about PIM's declaration —
it is that PIM has **no downstream stages recorded at all**, while it is in
fact derived and executed downstream. `MEM-007` also carries
`claim_scope: None`, where `MEM-006` carries a real claim.

**Correct action: add the missing stages and a claim to `MEM-007`; do not
flip `LEGACY_ONLY` to something it is not.** See §11.

> **Consequence for the amendment:** A6 shrinks from three row corrections
> to one. Two of the three "contradictions" were audit artifacts. This is
> recorded because an amendment built on a false contradiction would
> corrupt the registry it is meant to repair.

---

## 2. TOPOLOGY TAXONOMY

Three concepts are currently conflated. They are separated here.

### 2A. Named parametric topology intent

A family name plus parameters. Today `TopologyFamily` (declaration) and
`MaterializedFamily` (derivation) are **two enums that disagree**:

```text
TopologyFamily      MESH · TORUS · CONCENTRATED_MESH · GEC · FAT_TREE      (5)
MaterializedFamily  MESH · TORUS · CONCENTRATED_MESH · RING                (4)
```

`_family_of()` (`topology_artifact.py:339-349`) maps three and refuses the
rest with a typed error: *"topology_family 'gec' is not materializable in
B3.1 (supported: mesh, torus, concentrated_mesh) — no silent fallback."*

**Amended law — eight independent stages, never one membership bit.** A
family is described by a vector, not a flag:

| Stage | Meaning |
|---|---|
| `DECLARABLE` | the name is accepted in intent |
| `MATERIALIZABLE` | a `TopologyArtifact` can be derived from name + params |
| `ROUTABLE` | a canonical route exists over the derived artifact |
| `VERIFIABLE` | attachment/route/CDG verification applies |
| `PROJECTABLE` | a backend (BookSim/ASTRA) projection exists |
| `EXECUTABLE` | the projection runs |
| `QUALIFIED` | the run is qualified against an authority |
| `PRODUCT_WIRED` | reachable from the product |

`RING` is the proof this must be a vector: **materializable but not
declarable** — it exists as a derivation target with no intent surface.
`GEC`/`FAT_TREE` are the mirror: **declarable but not materializable**.

**Resolutions:**

- `GEC`, `FAT_TREE` — keep `DECLARABLE` **only if** a materializer is
  planned; otherwise remove from `TopologyFamily`. **Decision: remove
  `GEC` and `FAT_TREE` from declaration authority in AMEND-1 and re-add
  them when a materializer lands.** A family that cannot be materialized
  must not be declarable — failing at declaration with a clear message is
  correct; failing later at materialization is mysterious.
- `RING` — **add to `TopologyFamily`.** A materializer with no declaration
  path is a capability nobody can reach.

### 2B. Explicit / custom topology intent

A user-provided graph. **Legitimate design science, and not the same as
editing compiler-derived routes.** Contract in §4.

### 2C. Synthesized topology candidate

The **output** of a synthesis process — not user intent. It becomes a
content-addressed candidate that enters the **normal canonical compiler**
(§6, §9).

> **Law: synthesis is never a second evaluator and never a second
> verification authority.** A synthesizer emits a candidate topology; the
> compiler derives routes/VCs; the verifier issues the certificate. The
> synthesizer emits none of those.

---

## 3. TARGET PRODUCT MODEL (the law this amendment restores)

```text
SYSTEM / WORKLOAD INTENT
        ↓
FABRIC DESIGN INTENT
        ├── named parametric topology      (§2A)
        └── explicit / custom topology     (§2B)
        ↓
CANONICAL TOPOLOGY ARTIFACT               TopologyArtifact
        ↓
ROUTING / ATTACHMENT / VC / VERIFICATION
        ↓
EXECUTION / EVIDENCE
```

and separately:

```text
WORKLOAD + PHYSICAL CONSTRAINTS + DESIGN SPACE
        ↓
TOPOLOGY SYNTHESIS / STRUCTURAL SEARCH    (§6)
        ↓
CANDIDATE TOPOLOGY                        content-addressed
        ↓
normal canonical compiler                 ← the SAME compiler
        ↓
verified / evaluated candidate
        ↓
comparison / Pareto / selection
        ↓
optional immutable promotion into a Design Revision   (§16)
```

---

## 4. CUSTOM TOPOLOGY CONTRACT

**Name:** `ExplicitTopologyIntent` (`veritx/explicit-topology-intent/v1`),
in `model/explicit_topology.py`, following `RoutingPolicyDefinition`'s
content-addressed convention (`ROUTING_POLICY_SCHEMA_VERSION`,
`_strict_keys`, `from_dict` that recomputes identity).

**The user declares only what the compiler cannot derive:**

| User declares | Why |
|---|---|
| stable router identities | physical topology is the user's fact |
| router coordinates | needed for layout-aware science and visualization |
| router-local seat capacity | how many endpoints attach at each router |
| undirected physical connectivity | the graph itself |
| link width (bits) | genuinely affects science |
| link latency (cycles) | genuinely affects science |
| optional physical link grouping + `length_mm` | layout/wire science |

**The user does NOT declare:**

| Compiler derives | Why |
|---|---|
| routes | `ResolvedRoute` / route table |
| VC count and VC assignment | `derive_vc_count` from the dependency graph |
| turn restrictions | derived from topology + routing |
| escape VC designation | proof-oriented, derived |
| port ordering | deterministic from canonical router order |
| `channel_id` | assigned by the materializer |
| artifact hashes | content-addressed |
| backend node IDs | backend projection concern |

**Identity.** `intent_hash` = content-id over
`(schema_version, sorted routers, sorted connectivity, link attributes,
seat capacities)`. **Any graph change changes identity. Coordinate/layout
changes that do not alter connectivity must not change the *routing*
identity — but must change the *artifact* identity**, because
`DirectedChannel.latency_cycles` feeds execution. This distinction is
recorded explicitly so a future author does not "helpfully" drop
coordinates from the hash.

**Directionality.** Connectivity is declared **undirected** (a physical
link). `DirectedChannel` is **directed** and is derived as both directions.
Declaring directed links directly is refused — it would let a user author a
half-duplex topology that the verifier cannot reason about.

**Seat capacity.** `Router.seat_capacity` is already canonical
(`topology_artifact.py:80`). Explicit intent carries it; the materializer
preserves it. This is what makes the occupancy fix (`_fabric` counts
**endpoints**, not routers) correct for custom graphs too.

**Validation at intent stage — only pre-derivation facts:**

duplicate router IDs · self-links (already refused in `DirectedChannel`
`__post_init__` and must be refused earlier, at intent) · duplicate edges ·
dangling endpoints · disconnected graph (refused if disconnected topologies
are illegal) · non-positive `width_bits` · negative `latency_cycles` ·
`seat_capacity < 1` · non-finite/negative `length_mm`.

**Explicitly NOT validated at intent stage:** routing legality, deadlock
freedom, VC sufficiency, CDG acyclicity. Those are **downstream
obligations** and must remain so.

**Gap vs historical AnyNet.** `milp_topology_v2.py` prices edges with
`PIPE_COST = 3.0` and `WIRE_COST = 1.0` and emits `.anynet` carrying
router/port/link and latency. `TopologyArtifact` represents routers,
directed channels (with `latency_cycles`, `route_weight`, `width_bits`,
`physical_link_id`) and `PhysicalLink.length_mm`. **No information is
lost** — `route_weight` and `physical_link_id` cover the priced-link
semantics. Recorded here so the gap is closed explicitly rather than
silently.

---

## 5. TOPOLOGY FAMILY REGISTRY

**One machine-readable registry**, `docs/product/topology-family-registry.yaml`,
checked by `scripts/check_topology_family_registry.py`. **Not a plugin
framework** — its purpose is to stop enum drift.

Per family: canonical identifier · parameter schema · materializer
reference · visualization support · routing availability · backend
projection mappings · capability references · historical source.

**Backend vocabulary is NOT product ontology.** `dragonflynew`, `fly`,
`flatfly`, `gec`, `anynet`, `ftree`, `qtree16` are BookSim spellings. The
registry carries an explicit **projection mapping**:

```yaml
mesh:            { booksim: "mesh",        astra: "mesh" }
torus:           { booksim: "torus",       astra: "mesh" }
concentrated_mesh: { booksim: "cmesh",     astra: "mesh" }
custom:          { booksim: "anynet",      astra: "namespace" }
```

A BookSim enum string must never be a design contract. Changing a backend
spelling must not alter scientific identity.

---

## 6. SYNTHESIS OWNERSHIP

**Old decision:** synthesis is `LEGACY_INTERNAL`, replacement *"none in
Wave C (synthesis science is Wave E)"*, and the historical parity ledger
records BO/MILP/RHO as `REJECT (deferred)`.

**Evidence:** the engines are in the current tree and functional
(`milp_topology_v2.py` — traffic matrix + grid/interposer layout + radix +
link-length budget + optional diameter → topology, MILP/HiGHS ≤20 nodes and
SA at 64+, priced geodesic, `.anynet` emission). They have **no canonical
owner**.

**Amended decision.** Permanent owner: **topology synthesis**, distinct
from the fabric compiler, the backend evaluator and the parameter
optimizer.

```text
consumes:  workload / traffic evidence or declared traffic model
           physical / layout constraints
           synthesis policy
           optional deterministic seed + budget
emits:     TopologyCandidate   (canonical candidate description)
```

**New authority, not a new evaluator.** `TopologyCandidate` carries the
exact graph plus provenance; it does **not** carry routes, VCs, a
certificate, or performance. `.anynet` becomes a **backend/export
projection**, not scientific authority.

**Search strategy ≠ topology generator.** The planning corpus deferred
Bayes/MILP/SA as **search methods over a fixed design space**
(`INTENT-DESIGN-SPACE.md:512`). `milp_topology_v2.py` is also a **topology
generator**. These are different concepts and the ontology must distinguish
them:

| Concept | Question |
|---|---|
| `SEARCH_STRATEGY` | *how* to walk a space that already has a shape |
| `TOPOLOGY_GENERATOR` | *produce* the shape itself |

A generator may use MILP internally. Its semantic role is still
generation. Conflating them is what let "MILP is deferred" read as
"topology synthesis does not exist".

---

## 7. STRUCTURAL OPTIMIZATION CONTRACT

`DomainParam` accepts int/str/bool only (`_canonical_value`) — a graph
cannot be a value. And `_LOCKED_TOKENS = ("routing", "vc", "turn",
"escape")` refuses structural knobs by name.

**Amended:** introduce an explicit **structural candidate producer**
relationship. Do **not** stuff graphs into `DomainParam` strings.

```text
StructuralDesignSpace
  ├── named_family enumeration      → TopologyCandidate
  └── synthesizer producer ref      → TopologyCandidate
```

The optimizer then evaluates candidates produced by either source through
the **same** compiler → verify → evaluate path.

**Compiler ownership preserved (unchanged):** exact routes · VC assignment ·
turn realization · escape realization · verification certificate. Structural
search may vary **topology**. It may vary a **high-level routing policy**
only if the routing contract allows it. It must **never** edit
`RouteArtifact` / `VCAssignmentArtifact` directly.

**Routing as a structural dimension.** Only the high-level product-owned
`RoutingPolicyDefinition` may be a dimension. The canonical route table
stays derived. **Decision: keep structural routing search deferred**, with
the exact reason recorded — `RoutingPolicyDefinition` exists as a
representation, but `ROUTE-009` is all-NO and `router_behavior.py` declares
adaptive/escape priority explicitly absent. Representation is not
qualification.

---

## 8. SEARCH COMPLETENESS CONTRACT (P0 scientific honesty)

**Evidence of the defect:**

```python
# optimization/search.py
def search_candidates(base, defn):
    if method in ("grid", "enumeration"):
        cands = enumerate_candidates(base, defn)
        limit = _budget_limit(defn)
        if limit is not None:
            cands = cands[:limit]          # ← silent truncation
        return cands
```

No completeness fact survives. `EXHAUSTIVE_GRID` (2 commits),
`BUDGETED_GRID` (3), `NOT_EVALUATED` (4) existed historically and are gone.
`CAPABILITY-LEDGER.md` W11 records the deferral as `HISTORICAL` with reason
*"no ALIAS/INVALID/NOT_EVALUATED states in P2"*.

**Amended contract.** `OptimizationResult` gains a mandatory
`SearchCompleteness` fact:

| Field | Meaning |
|---|---|
| `method` | `grid` / `enumeration` / `random` / `synthesized` |
| `universe_size` | total candidate universe when knowable (`raw_cardinality`) |
| `universe_known` | bool — `False` when a generator cannot bound its space |
| `budget` | the applied limit, or `None` |
| `evaluated_count` | candidates actually evaluated |
| `not_evaluated_count` | valid candidates excluded by budget |
| `not_evaluated_identities` | identities, or a count+range when materializing is too expensive |
| `completeness` | `EXHAUSTIVE` \| `BUDGETED` \| `UNBOUNDED` |

**Seven mechanical invariants:**

1. Truncation is **identity/evidence-visible**.
2. `EXHAUSTIVE` is **never inferred** — it is only claimed when
   `evaluated_count == universe_size` and `universe_known`.
3. Non-evaluated candidates remain **represented** — absence must not look
   like nonexistence.
4. Pareto uses only **eligible, evaluated** candidates.
5. Requirement violation stays **separate** from Pareto eligibility unless
   it is an explicit hard optimization constraint.
6. **Generated objective ≠ evaluated metric.**
7. A synthesis engine **cannot manufacture** a certificate or evidence.

**Product language.**

| Situation | Permitted claim |
|---|---|
| exhaustive finite enumeration, all resolved | *"complete over this declared finite design space"* |
| budgeted / synthesized | *"best observed among evaluated candidates"* |
| anything else | **no optimality claim** |

**Never** "optimal NoC" without a fully qualified, mathematically
appropriate scope.

---

## 9. SYNTHESIS INPUT / OUTPUT CONTRACTS

**`SynthesisDefinition`** (immutable, content-addressed) — the minimum set
supported by real engines, no invented parameters:

source design/base constraints · workload/scenario set · traffic authority
(matrix or declared model) · physical layout model if used (`grid`,
`interposer`, `rows`, `cols`, `seed`, `jitter`) · radix constraint ·
link-length constraint (`max_len`) · diameter constraint if supported ·
permitted generator family · deterministic seed when meaningful ·
synthesis budget (`iters`, `t0`, `max_nodes`) · objective definitions
(`geodesic` vs `priced_geodesic`) · evidence requirements.

**`TopologyCandidate`** — enough to reconstruct:

exact explicit topology graph · synthesis-definition identity ·
generator/producer identity · candidate identity ·
generation status · generator objective value where applicable.

> **The generator objective value is NOT verified product performance.**
> It is a search-internal scalar. It must never be projected as a metric.

The candidate then goes: **compiler → verification → evaluation.**

---

## 10. METHOD PHASING

| Method | Source | Scientific semantics | Determinism | Identity | Evidence | Status | Return condition |
|---|---|---|---|---|---|---|---|
| **MILP / TMCF** | `milp_topology_v2.py` | traffic-weighted generation, radix + link-length + diameter | **deterministic** given seed/layout | graph is exact and content-addressable | emits `.anynet` + JSON | **AMEND-8 — first** | adapter to `TopologyCandidate` |
| **SA / heuristic** | `milp_topology_v2.py::sa_synthesize` | local search over candidate edges | deterministic given seed | same | same | AMEND-8 (second) | same adapter |
| **BO** | `bo_synthesizer.py` (skopt GP) | sample-efficient search | seed-dependent | same | historical only | **deferred** | after deterministic correctness is established |
| **Iterative / RHO-GRPO** | `iterative_synthesizer.py` | edge add/remove + rollouts | seed-dependent | same | historical only | **deferred** | same; edge mutation on anonymous adjacency is additionally the wrong authority |
| **Event objective** | `event_objective.py` | analytical collective scorer | deterministic | n/a | historical | **RESEARCH_ONLY** | candidate for the real adapter's analytic fallback |

`milp_topology_v2.py` is reclaimed **first** because it is the only method
that is simultaneously: implemented, deterministic, radix/length/diameter
aware, and already emitting a complete topology.

---

## 11. WORKLOAD PARITY DECISIONS

Authoring vocabulary: `CollectiveKind` = ALLREDUCE · ALLGATHER ·
REDUCESCATTER · BROADCAST · ALLTOALL (5).
Live graph kinds: COMPUTE · COLLECTIVE · **P2P** · **MULTICAST** ·
**EXPERT_BEGIN** · **EXPERT_END** · **PIM_CHANNEL** · **PIM_END** (8).

| Kind | Decision | Reason |
|---|---|---|
| **P2P** | **AUTHORABLE CANONICAL INTENT** | valid workload science; needs the smallest representation: source, destination, payload, dependency semantics. **Not** a two-member collective — a two-member collective has collective semantics (ordering, conservation) that a point-to-point transfer does not |
| **MULTICAST (logical)** | **AUTHORABLE CANONICAL INTENT** | source replication is existing science |
| **MULTICAST (hardware)** | **REMAINS UNAVAILABLE** | no physical replication/tree/resource artifact exists. `mcast_groups`/`mcast_setup_cycles` are fabric-side knobs and do **not** constitute a hardware multicast artifact. **Do not reintroduce a hardware multicast checkbox** |
| **EXPERT / MoE (static)** | **DERIVED-ONLY SEMANTIC** | Serving MoE ≠ Static Evaluation MoE. Static has a `model_family` shape declaration and **no** dispatch/combine semantics. If expert ops become authorable, define static semantics precisely — never infer them from the serving implementation |
| **PIM** | **DERIVED-ONLY / BACKEND-ONLY** (recommended) | `KIND_PIM_CHANNEL` is live in `workload/graph.py:88` and `backend/astra.py`. Recommended: classify as backend-derived and record the stages. Alternative: make it authorable. **Either way `MEM-007` must stop saying `LEGACY_ONLY` with no stages** |

### `MEM-007` correction (the one real A6 row fix)

```text
MEM-007 PIM
  DECLARABLE  LEGACY_ONLY      (unchanged — the grammar token is legacy)
  DERIVABLE   YES              (NEW — KIND_PIM_CHANNEL is emitted downstream)
  VERIFIABLE  per routing      (NEW — subject to normal verification)
  EXECUTABLE  YES (ASTRA)      (NEW — backend/astra.py consumes it)
  claim_scope "downstream-only: the canonical graph and ASTRA consume
               PIM_CHANNEL, but no WorkloadV3 intent originates it"
```

`LEGACY_ONLY` is a **hidden/exposure class** (`HIDDEN_CLASSES` in
`product_registry.py`), not a scientific claim. It is defensible for the
*declaration*; the defect was the **missing stages and the empty claim**.

### CXL / REMOTE / STORAGE — NOT reclaimed

`memory_lowering.py` refuses each with a typed reason (*"remote access
mislabeled, not local memory"*; *"package storage is never HBM. Refused."*)
and explicitly rejects *"eh, use HBM"*. **Keep the refusal.** No canonical
adapter is ready for migration. Documented deferral.

---

## 12. WAVE-E METRIC PROJECTION (the RECLAIMABLE item)

`FRA-PERF-002` is the audit's one `RECLAIMABLE`: semantics valid,
implementation exists, canonical representation **already fits**, only
registration missing.

**Do it without redesign.** `CertifiedMetricRegistry` already exposes
`MetricRegistryBuilder.register(metric, producer, *, producer_id,
semantics_version)` and is wired into `real_evaluator.py` and `result.py`.

**Register, using exact canonical names — no duplicates:**

| Canonical name | Producer |
|---|---|
| `makespan` | `performance/metrics.py` |
| `critical_path` | `dependency_critical_path` |
| `resource_utilization` | `resource_utilization` |
| `request_latency` | `request_latencies` |
| `ttft` | Wave-E serving path |
| `decode_step_latency` | Wave-E serving path |
| `sensitivity` | `performance/sensitivity.py` |

**Do not duplicate** `completion_cycles` / `completion_ns` /
`completion_time` — already represented.

**Preserve the honesty metadata** (§25 of the brief):

- `fidelity_warning` (`performance/model.py`)
- the `unsupported` list: throughput · continuous_batching ·
  per_operation_network_causality · analytical_compute_roofline ·
  memory_capacity
- `predictive_validation: NOT_ESTABLISHED`
- analytical/model authority (`ANALYTICAL_MODEL`, `MEMORY_ONLY`,
  `UNCALIBRATED`)

**`predictive_validation = NOT_ESTABLISHED` must remain visible.** An
analytical output must never render as a backend measurement.

**Metric ownership (§26).** Registration ≠ validity for every evaluator.
Eligibility stays **backend/registry driven**. Studio must **never** infer
metric validity.

---

## 13. STUDIO IA AMENDMENT

Amend Gate-8 IA for the confirmed holes. **Do not redesign global nav.**

**Debug Network.** Determine coverage: Fabric Inspector ·
Routing/VC inspector · CDG/deadlock inspector · evidence diagnostics.
**Decision: fully superseded by the Fabric Inspector + CDG inspector +
Compile Result refusal surface.** Record the mapping; add **no** top-level
page. Unique historical debugging interactions that remain unrepresented
are recorded as `NEEDS_CANONICALIZATION` rather than invented as UI.

**Memory.** Give memory analysis a deliberate home. Ramulator is
`ENGINE_ONLY` / `MEM-002` with `QUALIFIED: CONDITIONAL`, and
`MEM-003`/`MEM-004` are `NO_CONTRACT`. **Decision: expose memory
inspection/status inside the existing Evaluate/Fabric area — no Run
Ramulator button** until product wiring exists.

**Compare.** Comparison is a core thesis verb and must not be discoverable
only through Evidence. **Decision: a deliberate Compare path under
Evaluate/History**, consistent with existing global nav. No top-level entry
for symmetry.

**Nav change is explicitly out of scope** (the Gate-8 §5 rail →
Design · Evaluate · Serve · Optimize · History · Capability change remains a
separate IA slice).

---

## 14. TOPOLOGY-FAMILY CAPABILITY MATRIX

`I`=Intent `M`=Materialize `R`=Route `V`=Verify `B`=BookSim `A`=ASTRA
`Q`=Qualify `Z`=Visualize `O`=Optimize

| Family | I | M | R | V | B | A | Q | Z | O |
|---|---|---|---|---|---|---|---|---|---|
| mesh | YES | YES | YES | YES | YES | YES | YES | YES | YES |
| torus | YES | YES | **NO** | YES | NO | NO | NO | YES | NO |
| concentrated_mesh | YES | YES | YES | YES | YES | YES | YES | YES | YES |
| ring | **NO**→YES | YES | NO | YES | NO | NO | NO | YES | NO |
| gec | YES→**REMOVE** | NO | NO | NO | NO | NO | NO | NO | NO |
| fat_tree | YES→**REMOVE** | NO | NO | NO | NO | NO | NO | NO | NO |
| flatfly | NO | NO | NO | NO | cfg only | NO | NO | NO | NO |
| flattened butterfly (`ftree`) | NO | NO | NO | NO | cfg only | NO | NO | NO | NO |
| qtree / tree4 | NO | NO | NO | NO | cfg only | NO | NO | NO | NO |
| dragonfly | NO | NO | NO | NO | cfg only | NO | NO | NO | NO |
| custom / anynet | **NEW** | **NEW** | YES | YES | YES | YES | partial | YES | **NEW** |

No binary "supported" flag. `cfg only` means a BookSim configuration exists
and **no** canonical scenario does.

**Verification status of this matrix.** Mesh, torus, concentrated_mesh and
ring cells are verified from `topology_artifact.py` (`_family_of`, the
`materialize_family` dispatch) and `test_staged_compilation.py`. `RING`'s
`I` and `GEC`/`FAT_TREE`'s `M` are verified from the two enums directly.

The **backend cells (`B`, `A`) for `concentrated_mesh` are NOT verified in
this pass** — no `cmesh`/`concentrated` projection reference was found in
`backend/booksim.py` or `backend/astra.py`, and the topology→backend
projection path was not traced. They are carried from the audit's
execution evidence (the `dense-4b-32tiles-conc4` preset is `GUIDED_SAFE`)
and are **marked for verification in AMEND-1**, not asserted here.

`flatfly`, `ftree`, `qtree`, `tree4` and `dragonfly` rows are derived from
the **presence of a config file only** — no materializer, no test, no
scenario. They are recorded as reclaim targets (§19), not as capabilities.

## 15. CUSTOM TOPOLOGY MATRIX

| Concept | Intent | Materialize | Route | Verify | Execute | Identity | Distinct because |
|---|---|---|---|---|---|---|---|
| imported explicit graph | **NEW** | **NEW** | YES | YES | YES | user-authored | user is the author |
| synthesized candidate graph | producer ref | **NEW** | YES | YES | YES | generator+def | machine is the author |
| AnyNet backend/export projection | n/a | n/a | n/a | n/a | YES | derived | **spelling, not authority** |

These are **not** the same concept. The third is a projection of the first
two and must never become scientific authority.

## 16. SYNTHESIS MATRIX

| Engine / method | Input authority | Output authority | Deterministic identity | Canonical candidate | Verified evaluation | Current status |
|---|---|---|---|---|---|---|
| MILP / TMCF | traffic matrix + layout + radix + max_len | `.anynet` file | yes (seed/layout) | **NO** → AMEND-8 | via normal compiler | implemented, unwired |
| SA / heuristic | same + `iters`/`t0` | `.anynet` | yes (seed) | **NO** → AMEND-8 | via normal compiler | implemented, unwired |
| BO | `PARAM_REGISTRY` intent docs | SynthResult dict | seed-dependent | NO | historical | deferred |
| iterative / RHO | anonymous adjacency | `.anynet` | seed-dependent | NO | historical | deferred |
| event objective | adjacency | scalar | deterministic | n/a | historical | research only |

## 17. IDENTITY LAWS

| Object | Identity over | Changes identity when |
|---|---|---|
| `ExplicitTopologyIntent` | schema, routers, connectivity, link attrs, seats | **any graph/attribute change** |
| `TopologyCandidate` | synthesis-def identity, producer identity, exact graph | graph or provenance changes |
| `SynthesisDefinition` | source, scenarios, traffic authority, layout, radix, max_len, diameter, family, seed, budget, objectives | any declared input changes |
| `StructuralDesignSpace` | named enumeration + producer refs | dimension set changes |
| `OptimizationStudy` | `result_id()` — full evaluation provenance | provenance moves, not just floats |

**A topology graph change must change identity. A presentation/layout change
must not — except where layout feeds `latency_cycles`, which is recorded
explicitly (§4). Backend projection spelling must not alter scientific
identity unless semantically meaningful.**

## 18. PROMOTION LAW

A synthesized or optimized candidate promoted into a Design becomes
**immutable canonical Design intent**. Promotion must freeze:

- the topology graph;
- relevant declared parameters;
- source synthesis provenance **as metadata**.

**Future changes to the synthesis engine must not reinterpret the promoted
design.** The engine may improve; the promoted design is frozen.

---

## 19. IMPLEMENTATION SEQUENCE

| # | Scope | Depends on | Closes |
|---|---|---|---|
| **AMEND-0** | audit bookkeeping correction | — | **DONE** `1834495c` |
| **AMEND-1** | topology taxonomy + family registry + enum reconciliation (`GEC`/`FAT_TREE` out, `RING` in) + backend projection mappings | — | A1, §5 |
| **AMEND-2** | `ExplicitTopologyIntent` + materializer + intent-stage validation | AMEND-1 | A1, §4 |
| **AMEND-3** | generalise staged compilation across all families (Torus law becomes generic) | AMEND-2 | §3, §20 |
| **AMEND-4** | search-completeness restoration + `NOT_EVALUATED` visibility | — | A2, §8 |
| **AMEND-5** | Wave-E metric registration + honesty metadata projection | — | A3, §12 |
| **AMEND-6** | workload-origin parity: P2P authorable; MULTICAST logical only; EXPERT derived-only; PIM derived-only | — | A5, §11 |
| **AMEND-7** | capability-registry correction: `MEM-007` stages + claim; topology-family stage rows; synthesis rows; custom rows; Wave-E metric rows. **`ROUTE-008`/`ROUTE-009` unchanged** | AMEND-1, 6 | A6, §1 |
| **AMEND-8** | canonical synthesis adapter — **MILP/TMCF first** | AMEND-2, 4 | A4, §6 |
| **AMEND-9** | structural optimization integration | AMEND-4, 8 | A4, §7 |
| **AMEND-10** | Studio IA reconciliation (Debug Network mapping, Memory home, Compare path) | AMEND-5, 7 | A7, §13 |

AMEND-4 and AMEND-5 have no dependency on the topology work and may run in
parallel with AMEND-1..3.

### First tranche boundary (§45)

**Not "support every topology."** The first tranche establishes a **generic
canonical representation** and proves it with:

1. **Mesh** — the certified baseline, must not regress.
2. **Torus** — proves staged compilation survives a later routing refusal.
3. **One explicit custom graph** — proves user-authored topology.
4. **One historically non-mesh named family** — proves the registry.
5. **One synthesized candidate** — proves synthesis is not a second authority.

Additional families then become **adapters/materializers**, not
architectural rewrites.

### First non-mesh reclamation (§46) — **GEC, not FlatFly**

Chosen on evidence, not novelty:

| Candidate | Surviving implementation | Tests | Route support | Backend | Semantic clarity |
|---|---|---|---|---|---|
| **GEC** | declarable (`TopologyFamily.GEC`) and `gec` is a BookSim config family | no GEC-specific test found | needs materializer | BookSim `gec` | **high** — express/MECS/mesh variants are well-defined |
| FlatFly | BookSim `flatfly16.cfg` only | none | none | BookSim | medium |
| Dragonfly | BookSim `dragonfly16.cfg` only | none | none | BookSim | medium |

**GEC wins** on declaration survival + backend availability + semantic
clarity. It is also the family the audit's adversarial probe identified as
*unrepresentable*, so reclaiming it proves the represent layer actually
widened.

---

## 20. FILES / DOCS TO CHANGE

**New:**
`docs/product/FEATURE-RECLAMATION-AMENDMENT.md` (this file) ·
`docs/product/topology-family-registry.yaml` ·
`scripts/check_topology_family_registry.py` ·
`dse/veritx_dse/model/explicit_topology.py` ·
`dse/veritx_dse/synthesis/candidate.py` (`TopologyCandidate`) ·
`dse/veritx_dse/synthesis/definition.py` (`SynthesisDefinition`) ·
`dse/tests/test_explicit_topology.py` ·
`dse/tests/test_search_completeness.py` ·
`dse/tests/test_synthesis_candidate.py`

**Modified (code):**
`model/compile_model.py` (`TopologyFamily`) ·
`model/topology_artifact.py` (`MaterializedFamily`, `_family_of`, custom
materializer) ·
`optimization/{definition,search,result}.py` (`SearchCompleteness`) ·
`optimization/real_evaluator.py` (metric registration) ·
`application/certificate_projection.py`, `compile_result_view.py` (Wave-E
metadata projection) ·
`application/product_registry.py` (stage rows) ·
`application/inventory.py` (**`reports/` only** — it is absent from the ledger; `synthesis/` is already recorded at line 82 as `LEGACY_INTERNAL`)

**Modified (planning corpus — only affected portions):**
`INTENT-FABRIC.md` · `INTENT-DESIGN-SPACE.md` · `INTENT-WORKLOAD.md` ·
`CROSS-DOMAIN-LAWS.md` · `CAPABILITY-MATRIX.md` · `PRODUCT-FLOWS.md` ·
`GUIDED-EXPERT.md` · `DESIGN-REVIEW.md` · `STUDIO-WIREFRAMES.md` ·
`capability-registry.yaml` · `exposure-registry.yaml`

**Unchanged:** `feature-reclamation-registry.yaml` (historical/target
truth — §37: the two registries stay separate and are **not merged**).

---

## 21. CONTRACT CONFLICTS

| # | Conflict | Resolution |
|---|---|---|
| 1 | `TopologyArtifact.family` is typed `MaterializedFamily`, so a **custom graph has no family value** | Add `MaterializedFamily.CUSTOM` (or make `family` optional for explicit graphs). **Must be resolved in AMEND-2, not worked around.** |
| 2 | `_LOCKED_TOKENS` refuses `"routing"` by name, but §7 wants a high-level policy dimension | The token check must be narrowed to refuse *derived* routing knobs while permitting `RoutingPolicyDefinition` identity. **Not resolved in this amendment** — structural routing search stays deferred |
| 3 | `DomainParam` accepts int/str/bool only; structural search needs graphs | Resolved by §7's producer relationship, **not** by widening `DomainParam` |
| 4 | `RING` materializable but not declarable | AMEND-1 |
| 5 | `GEC`/`FAT_TREE` declarable but not materializable | AMEND-1 |
| 6 | Audit contradictions C and D were **false** | Recorded in §1; **no registry change** |
| 7 | `MEM-007` `LEGACY_ONLY` + empty claim vs live `KIND_PIM_CHANNEL` | AMEND-7 (§11) |
| 8 | `.anynet` is currently both a synthesis output **and** a backend input | AMEND-8: demote to export projection; `TopologyCandidate` becomes authority |
| 9 | **`reports/`** absent from `inventory.py` (verified: the ledger lists 20+ paths including `synthesis/` at line 82, but no `reports/` entry) | AMEND-7 |

---

## 22. COHERENCE TESTS (§49)

| Question | Answer |
|---|---|
| Declare a named topology? | **YES** — `TopologyFamily` (AMEND-1) |
| Declare/import a custom topology? | **YES** — `ExplicitTopologyIntent` (AMEND-2) |
| Synthesizer generates without becoming compiler authority? | **YES** — emits `TopologyCandidate` only (AMEND-8) |
| Generated topology passes the **same** compiler? | **YES** — §3, §16 |
| Certified Mesh unchanged? | **YES** — no stage regresses; AMEND-1 only removes unreachable names |
| Torus inspectable when routing refuses? | **YES** — staged law generalised (AMEND-3) |
| Topology structure optimizable without exposing route/VC knobs? | **YES** — §7; `_LOCKED_TOKENS` retained |
| Budgeted search can never masquerade as exhaustive? | **YES** — §8, seven invariants |
| Wave-E metrics remain visibly analytical? | **YES** — §12, `predictive_validation` preserved |
| Workload multicast without claiming hardware multicast? | **YES** — §11 |
| PIM state representable truthfully? | **YES** — §11 staged row |
| Every family has staged capability status? | **YES** — §14, no binary flag |
| 2D Inspector renders arbitrary graphs without family logic? | **YES** — it draws `TopologyArtifact`; family is metadata |

**All thirteen answer YES.** The amendment is coherent.

---

## VERDICT

The amended architecture restores a valid path for **REPRESENT** (named via
`TopologyFamily`, custom via `ExplicitTopologyIntent`), **SYNTHESIZE**
(`TopologyCandidate` → normal compiler, never a second authority),
**ROUTE**, **VERIFY**, **EXECUTE**, **COMPARE**, **OPTIMIZE** (structural
producer + preserved compiler ownership) and **VISUALIZE** — without
claiming that every topology or method is already implemented or qualified.

The amendment **broadens representability and weakens nothing**: strict
schemas, content identity, route authority, VC derivation, CDG
verification, backend qualification, evidence authentication, requirements
honesty and the staged capability model are all preserved. Broader design
space still **fails closed**.

Two audit claims were found to be the audit's own errors (contradictions C
and D) and are withdrawn rather than carried into the registry.

**FEATURE RECLAMATION AMENDMENT — COHERENT — IMPLEMENTATION MAY RESUME**

---

# PART II — AMENDMENT CORRECTION AND TRANCHE 1

## 45. AMENDMENT CORRECTION (three items)

The amendment as first written contained one architectural mistake and two
premature decisions. All three are corrected here, and the correction is
what AMEND-1..5 implement.

### 45.1 The taxonomy mistake — REJECTED rule

The amendment proposed:

> *remove GEC and FAT_TREE from declaration authority; add RING, because
> materializable families should be declarable and non-materializable ones
> should not.*

**That rule is rejected. It collapses AUTHORABLE and MATERIALIZABLE — the
exact conflation the staged model exists to prevent.**

| Family | AUTHORABLE | MATERIALIZABLE | Verdict |
|---|---|---|---|
| `gec` | **YES (kept)** | NO | stays in the taxonomy; `_family_of` refuses with a typed error |
| `fat_tree` | **YES (kept)** | NO | same |
| `ring` | **NO (kept)** | YES | `role: TEST_FIXTURE` — materializable ≠ declarable |

Evidence for `RING`: `MaterializedFamily.RING` is referenced **only** by
tests (`test_attachment`, `test_route_artifact`, `test_channel_vc_cdg`,
`test_min_adapt_materialize`, `test_packet_format`,
`test_topology_artifact`), and `topology_artifact.py`'s own docstring says
*"NocConfig can express mesh, torus and concentrated mesh; ring/custom/
anynet arrive via TopologyIR"*. RING is a minimal-graph fixture, not user
intent.

Evidence for `GEC`/`FAT_TREE`: they are in `TopologyFamily` and not in
`MaterializedFamily`, and the refusal already existed and already named the
supported set. Removing them would have deleted two recognized families
from the scientific taxonomy to satisfy an enum-shaped rule.

**Three sets, never one:**

```text
taxonomy    — scientifically recognized topology identities
authorable  — a canonical intent schema exists
material    — the compiler can lower it to a TopologyArtifact
```

### 45.2 The coordinate law

The amendment's draft `ExplicitTopologyIntent` **required** coordinates.
That would have silently redefined "custom topology" as "2D physical-layout
topology".

**`TopologyIR` already existed and already had the right law.** It carries
undirected explicit links, strict validation, and **no coordinates**. The
correction is therefore not a new contract at all — it is wiring the
existing one.

| Kind | Identity-bearing? | Where it lives |
|---|---|---|
| SCIENTIFIC coordinates | **YES** — feeds link length, allowed links, latency, physical cost | `materialize_ir(coordinates=...)`; persisted in the artifact |
| PRESENTATION layout | **NO** — never persisted | derived frontend-side at render time |

**Directionality law:** connectivity is declared **undirected** (a physical
link); `TopologyIR` validates duplicates as undirected
(`min(u,v), max(u,v)`). One undirected link lowers to **two**
`DirectedChannel`s. Declaring a directed link directly is refused — it
would let a user author a half-duplex topology the verifier cannot reason
about.

**Unit gap, recorded not hidden:** `TopologyIR` carries ANALYTICAL units
(`bandwidth_GBs`, `latency_ns`); `DirectedChannel` carries PHYSICAL units
(`width_bits`, `latency_cycles`). Converting ns→cycles needs a clock
`TopologyIR` does not carry, so `materialize_ir` does **not** guess — the
caller supplies the canonical channel properties. A hidden conversion would
silently invent a clock.

### 45.3 First non-mesh family — **FlatFly**, not GEC

The amendment preselected GEC on surviving-declaration and
backend-availability grounds. **That was the wrong criterion.**

**GEC-MECS finding (decisive):** `model/presets.py:110` states it verbatim:

```python
# GEC MECS: o=1,d=7 → 1 express channel, tapped to 7 dests
Topology("gec_mecs_k8", "gec", "dor", {"k": 8, "c": 1, "o": 1, "d": 7}, ...)
```

GEC-MECS is **tapped / multidrop** — one express channel fanned to seven
destinations. Flattening that into ordinary `DirectedChannel`s would be
**semantic loss**. GEC Express (`o=7,d=1`) *is* point-to-point, but the
family is not uniformly representable, so it must not be forced to fit
first.

| Candidate | Point-to-point | New channel primitive | Verdict |
|---|---|---|---|
| **FlatFly** | **YES** | **none** | **chosen** |
| GEC Express | yes | none | follows once GEC semantics are exact |
| GEC-MECS | **NO (tapped)** | multidrop | classify separately |
| flattened butterfly | yes | none | no materializer, config only |
| Dragonfly | yes | none | no materializer, config only |
| FatTree | yes | none | no materializer |

**FlatFly is the first proof family:** radix `r = c + (k-1)*n`, every
router port an ordinary channel; at `k=4, n=2, c=4` it is 16 routers, 48
undirected links, degree `(k-1)*n = 6`. It proves *"TopologyArtifact is
generic beyond Mesh/Torus"* with **zero semantic distortion**.

## 46. MIGRATION HOLE FOUND — `TopologyIR` was an orphan

| Artifact | In the current tree? |
|---|---|
| `veritx_dse/model/topology_ir.py` | **YES** |
| `tests/test_topology_ir.py` (349 lines) | **NO** — survives only on `integration/p1-product-rt-candidate` @ `26e6f9dc` |
| CLI `cmd_topology_render` / `_stats` / `_diff` | **NO** — same branch |
| `application/inventory.py` entry | **NO** |

Module survived; test and CLI did not. The module had **no test, no
consumer, and no ledger entry** — the textbook MIGRATION_HOLE. AMEND-2
wires it and adds 29 tests.

## 47. TRANCHE 1 — what was implemented

| Step | Commit | Scope |
|---|---|---|
| AMEND-1 | `4fdc7555` | taxonomy registry + checker + TAX-1..6 |
| AMEND-2 | `2b04709a` | `materialize_ir` + `materialize_flatfly` + coordinate law + CUSTOM-1..10 |
| AMEND-3 | `2b04709a` | shared `_artifact()` — staged law generic, mesh identity proven stable |
| AMEND-4 | `8ec11e56` | `SearchCompleteness` + SEARCH-1..6 |
| AMEND-5 | `64fc4760` | Wave-E metric projection + PERF-1..5 |

**Not implemented, deliberately:** full topology catalog reclamation, full
synthesis adapter (AMEND-8), structural optimizer (AMEND-9), workload
parity (AMEND-6), Studio IA (AMEND-10), Phase 3 Static Evaluate.

### 47.1 Stop-condition check

| Condition | State |
|---|---|
| taxonomy not inferred from the materialization enum | **MET** — registry is authority; TAX-6 fails closed on drift |
| GEC/FAT_TREE/RING have evidence-based roles | **MET** — GEC/FAT_TREE RESEARCH+AUTHORABLE; RING TEST_FIXTURE |
| custom graph intent is canonical | **MET** — `TopologyIR`, existing and stricter than the draft |
| coordinate/presentation semantics separated | **MET** — CUSTOM-7/8/8c |
| custom graph lowers to exact TopologyArtifact | **MET** — CUSTOM-1/4c/6b |
| the same 2D inspector renders it | **MET** — CUSTOM-9/9b: identical key sets for mesh/flatfly/custom |
| staged compile is generic | **MET** — shared `_artifact()`; STAGE-1/2/3/6 |
| one genuinely non-mesh family proves the abstraction | **MET** — FlatFly, pure point-to-point |
| search completeness is explicit | **MET** — SEARCH-1..6 |
| Wave-E metrics/fidelity projected | **MET** — PERF-1..5 |
| no qualification claims broadened | **MET** — FlatFly `QUALIFIED: NO`; no row gained a stage |

### 47.2 Unresolved blockers

1. **TWO UNRELATED `TopologyError` CLASSES.** `core.errors.TopologyError(VeritXError)`
   and `model.topology_artifact.TopologyError(ValueError, SemanticError)`.
   Neither catches the other. `TopologyIR` raises the first; the
   materializer raises the second. Tests catch both explicitly. **Not
   merged here** — merging changes error handling tree-wide and is out of
   tranche scope.
2. **`flatfly` is MATERIALIZABLE but not yet AUTHORABLE.** No intent schema
   yet; `NocConfig.topology_family` has no `flatfly` value. Deliberate: the
   registry records the honest stage rather than over-claiming.
3. **`concentrated_mesh` backend cells unverified.** `B`/`A` for
   concentrated_mesh were never traced; marked for AMEND-1 follow-up rather
   than asserted.
4. **`TopologyIR` CLI not restored.** `cmd_topology_render/_stats/_diff`
   remain absent; only the module and its tests are wired.
