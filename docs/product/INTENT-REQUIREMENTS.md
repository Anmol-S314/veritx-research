# INTENT-REQUIREMENTS — Domain E specification (Gate 2, closure pass)

Domain row: `intent-ontology.yaml :: domains.REQUIREMENTS`
Enforced by: `scripts/check_intent_ontology.py`
Supersedes the first-pass audit. **Design closure only** — REQ-D1…D6 not implemented.

---

## 0. Reality header

| Concept | Reality | Evidence |
|---|---|---|
| `RequirementId` | **R0** — positional `requirement_index` | `requirements.py:604` |
| `RequirementSet` | **R0** | bare tuple in `CompileRequestV3` |
| typed target | **R0** | a free `traffic_class` string |
| `MetricId` on a requirement | **R0** | unit-suffixed field names |
| **`traffic_class` narrows the population?** | **NO — attribution guard only** | §6 |
| latency metric | **R2, crisp** | `authenticated_network_cycles` `:251` |
| bandwidth metric | **R2 producer, defective window law** | `_measured_bandwidth_bps` `:317` |
| certified registry | **R2, 3 entries / 2 producers** | `metric_registry.py:272` |
| verdicts | **R2, four** | `:96` |
| aggregate law | **R2, doc↔code mismatch** | `report_passes` `:673` |
| `qos_class` | **R1 decorative** | no evaluator reads it |
| evidence reuse | **R2 supported** | `evaluate` takes a verified result |
| regression / memory / isolation | **R0** | — |

## 1. Domain boundary

REQUIREMENTS owns: desired measurable conditions · stable requirement identity ·
target identity · metric identity · comparator · threshold · binding/advisory
policy · requirement-set identity.

**Not owned:** compile feasibility · verification obligations · optimization
hard constraints · Pareto eligibility · regression policies · measurement
production · backend qualification · routing/VC/placement mechanisms.

## 2. Preserved strengths (do not regress)

1. one `authenticated_network_cycles` authority — *"the rule exists once, never mirrored"*;
2. four verdicts;
3. missing metrics are never zero;
4. missing evidence is never fabricated as `VIOLATED`;
5. binding/advisory aggregation has precise behaviour;
6. registry identity binds `metric + producer_id + semantics_version`;
7. time domains are not cross-compared without proof;
8. **requirement changes do not invalidate the fabric**;
9. compatible evidence may be re-evaluated without re-running the simulation.

## 3. Stable RequirementId

`requirement_index` must not remain canonical identity.

```text
RequirementId = a stable, non-empty string, unique within the set
```

- independent of list order;
- deterministic serialization;
- targetable by reports and comparison;
- **display name separate from the id**; ids are never derived from labels.

Report entries reference `requirement_id`; `requirement_index` survives only
as migration/debug metadata.

## 4. Requirement display metadata

`name` / `label` / `description` are **presentation/provenance**, excluded from
identity. Changing a display name does not move requirement identity; changing
`RequirementId` does.

## 5. RequirementSet

```text
RequirementSet {
  schema_version
  requirements[]          # canonical order by RequirementId
  requirement_set_hash
}
```

List reorder must not move identity.

**Empty-set law (resolved):** an **empty `RequirementSet` is schema-VALID** —
a design may declare no goals. This is **distinct** from `report_passes(empty)
== False`, which says *"an empty report satisfies nothing"*. The two are not
conflated: the set may be empty; a report with no entries can never be a
vacuous success.

## 6. **`traffic_class` does not narrow the measured population — the decisive finding**

```python
scoped_conservative = (req.traffic_class is not None and not single_class)
```

`_evaluate_latency` and `_evaluate_bandwidth` read the **aggregate** measurement
from the performance result. The class string **never filters messages or
bytes**. Its only effect:

| Situation | Effect |
|---|---|
| class-scoped, single-class workload | aggregate **==** class evidence → `SATISFIED`/`VIOLATED` legitimate |
| class-scoped, multi-class workload, measured ≤ bound | `SATISFIED` (aggregate is a sound upper bound) |
| class-scoped, multi-class workload, measured > bound | **`UNMEASURABLE`** — *"the excess cannot be attributed"* |
| no class | aggregate evaluated directly |

**Conclusion: the legacy `traffic_class` is an ATTRIBUTION GUARD, not a
target.** The schema is semantically inconsistent with the measurement, and
the evaluator is right.

## 7. Latency target semantics — resolved

`latency_ceiling_cycles` measures **`authenticated_network_cycles`**: the bound
network window's completion cycles, `network_binding.duration ×
network_binding.network_clock_hz`, required to reconstruct an **exact
integer**. Population = **the whole bound network window (all traffic)**.

A wall-time fallback exists, labelled *"(wall-time superset, conservative)"*,
used only when no window duration is bound — *"may false-violate, never
false-pass, and never driven by a caller clock."*

**Target = whole network evaluation. Not a class. Not a message. Not an
operation.**

## 8. Bandwidth target semantics — resolved, and **defective**

`_measured_bandwidth_bps` — *"Aggregate bytes/window over BANDWIDTH
utilization entries"*:

```text
numerator   = Σ bytes_moved over ALL BANDWIDTH utilization entries
denominator = the FIRST entry that carries a window  (else makespan)
value       = aggregate (never class-specific)
kind        = ACHIEVED bandwidth (bytes actually moved / time)
```

**The defect:** the numerator sums **every** BANDWIDTH entry while the
denominator is taken from the **first entry that has a window** — possibly a
different entry. Nothing enforces that all entries share one window, so
`(A + B) / W_A` is computed when `W_A ≠ W_B`.

**Therefore the calculation cannot be given a crisp population contract.**

## 9. **Bandwidth decision — REMOVE from v4**

Per the closure rule (REGISTER with crisp semantics, or REMOVE — no third
option), and because the window law is not enforced:

```text
bandwidth requirements: REMOVED from RequirementV4
recorded as REQ-D4, with the exact re-admission condition:
  a single window must be enforced across all BANDWIDTH utilization entries,
  or the metric must be defined per-entry with an explicit aggregation.
```

No new meaning is invented. Legacy designs carrying a bandwidth floor remain
readable through a legacy adapter and are **not** promoted to v4 semantics.

## 10. Typed target model — **one member**

```text
RequirementTargetV4 =
    WholeNetworkEvaluationTarget      # the bound network window (all traffic)
```

**Deferred, explicitly, with rationale:**

| Target | State | Why |
|---|---|---|
| `CommunicationClassTarget` | **DEFERRED** | no class-attributable measurement exists for any registered metric (§6) |
| `WorkloadOperationTarget` | **DEFERRED** | multiplicity law undefined (§12) |
| `ParallelismGroupTarget` | **DEFERRED** | no metric is resolvable to a participant group |
| `FabricTarget` | **DEFERRED** | no fabric-resolved metric |
| `ServingMetricTarget` | **DEFERRED** | serving vocabulary exists; no requirement path |

**A stable id is not a target.** A target type enters v4 only with a stable
identity, supported metrics, an aggregation law, an evaluator and evidence
traceability.

## 11. MetricId becomes mandatory

Remove unit-suffixed requirement fields. A v4 requirement carries
`metric_id`, `comparator`, `threshold`. The registry supplies unit, time
domain, producer identity, semantics version, population and applicable
target types. **None of these are duplicated in the requirement.**

## 12. Operation targetability — deferred with the exact missing law

A semantic operation may bind to multiple participant groups, producing
multiple bound instances and messages. Before `WorkloadOperationTarget` can
exist, one of these must be defined:

```text
ALL bound instances satisfy the threshold
MAX across bound instances vs threshold
MEAN / percentile across instances
a backend-supplied aggregation metric
```

**No law exists → `WorkloadOperationTarget` = CONTRACT NOT AVAILABLE.**

## 13. ParallelismGroupTarget — deferred

Stable group ids exist (Domain C). But no evaluator can attribute an
authoritative measurement to one group. **No synthesis from frontend traces.**

## 14. Target × metric compatibility — strict

```text
TargetType × MetricId → valid | invalid
```

No `target: any` / `metric: any`. A requirement with an undefined pairing
**fails validation**. The matrix is the future Studio filter.

## 15. Unified metric authority

The split between `CERTIFIED_METRIC_REGISTRY` and inline evaluator producers
is **eliminated in the target**: every requirement-evaluable metric has one
registered `MetricId`. Evaluators **implement** registered metrics; there is no
bare internal function producing a number without registry identity.

## 16. Metric registry closure — the v4-valid list

| MetricId | unit | value type | time domain | producer_id | sem. ver | target types | population | prerequisites |
|---|---|---|---|---|---|---|---|---|
| `network_completion_cycles` | cycles | exact integer (as `Fraction`) | BookSim network cycles | `authenticated-network-window-cycles` | 1 | `WholeNetworkEvaluationTarget` | the bound network window (all traffic) | verified performance result carrying `network_binding.{duration, network_clock_hz}` that reconstructs an exact integer |
| `network_completion_ns` | ns | integer | wall-time nanoseconds | `authenticated-network-window-wall-time-ns` | 1 | `WholeNetworkEvaluationTarget` | the bound network window | the same window, wall-time variant |

**Two metrics.** `completion_time` is **collapsed** into
`network_completion_cycles` — the certified registry registers both names
against **the same producer** (`authenticated-network-window-cycles`), so
they are one metric under two names (REQ-D3).

**Naming (§46):** the generic name `latency` is rejected; the id states the
population and the domain. The legacy label *"Latency ceiling (cycles)"* was
misleading and is replaced.

## 17. Comparator and threshold

Comparators: exactly `LE` and `GE` — the only relations with implementations.
**Equality is not added** (no float-equality semantics exist).

Threshold representation is **metric-determined**: `network_completion_cycles`
is an exact integer, so `1000.5 cycles` is **refused**; the comparator uses
`Fraction(str(x))` to avoid binary-float drift.

## 18. Canonical units

One canonical unit per metric, defined by the registry. UI conversion is
presentation only. **Equivalent values canonicalize identically; display units
never enter scientific identity.**

## 19. Time-domain binding

Preserved law: *"time (never cross-compared without proof)"*. A time-like
`MetricId` binds a specific time domain, so a threshold **inherits** it. There
is no free *"cycles"* threshold, and the frontend never converts scientific
domains.

## 20. Binding / advisory

```text
enforcement = BINDING | ADVISORY
```

The per-requirement verdict is **unaffected** by enforcement; enforcement
affects only aggregate set success. **No `critical` / `warning` / `info`
levels** — they have no evaluator meaning.

## 21. The four verdicts (exact)

| Verdict | Exact condition |
|---|---|
| `SATISFIED` | an authoritative measurement exists and the comparator passes |
| `VIOLATED` | an authoritative measurement exists and the comparator fails |
| `UNMEASURABLE` | the requirement is valid and applies, but no authoritative measurement can be produced or admitted |
| `NOT_APPLICABLE` | the requirement is valid but does not apply to this evaluation context |

**`VIOLATED` is never used for missing data.** No aliases are added.

## 22. Aggregate law — exact, with a resolved doc↔code mismatch

Documented intent (`report_passes` docstring): *"NOT_APPLICABLE binding entries
… do NOT fail the gate (fail-closed applies to evidence, not to vacuous
specs)."*

Implementation: `if entry.get("binding") and entry.get("verdict") != SATISFIED:
return False` — which **does** fail a binding `NOT_APPLICABLE`.

**Decision (REQ-D6):** follow the documented intent. The binding gate applies
to **`VIOLATED` and `UNMEASURABLE`**, not to `NOT_APPLICABLE`.

```text
aggregate:
  no entries                       → NOT satisfied
  any binding VIOLATED             → NOT satisfied
  any binding UNMEASURABLE         → NOT satisfied
  binding NOT_APPLICABLE           → does NOT fail (vacuous spec)
  advisory VIOLATED                → warning only
  otherwise                        → satisfied
```

## 23. Measurement authority

The registry entry defines admissible producer authority. Producer strings are
**never** put on a requirement — metric identity already carries
`metric + producer_id + semantics_version`. If two producers implement one
conceptual metric, they produce **distinct MetricIds** or pass an explicit
qualification layer. **Equal metric names never imply equal science.**

## 24. Certificate admissibility (E49 resolved)

If the certificate is not PASS but a backend produced a number:

```text
the measurement may exist;
the evaluator refuses authoritative SATISFIED/VIOLATED without the prerequisite;
the raw number is not discarded and not trusted as requirement evidence.
```

The prerequisite gate today is `verify_performance_result` — **not** the
certificate (R18). The target makes the prerequisite explicit in the registry
entry.

## 25. Hardware-vs-simulation authority (E50)

A hardware-latency requirement cannot be satisfied by simulation-only
evidence. Result: **`UNMEASURABLE`**, never `VIOLATED` — made automatic by
metric identity and authority, with **no UI heuristics**.

## 26. RequirementReport v4

```text
RequirementReport {
  requirement_set_identity
  evaluation_identity          # the verified measurement's identity
  entries[] { requirement_id, metric_id, target_ref,
              expected {comparator, threshold},
              observed_value?, verdict, evidence_refs, reason_code? }
  aggregate
}
```

**Never keyed by array index.**

## 27. Result identity

`(requirement_id, evaluation_identity)` uniquely locates a result. No reliance
on report-entry position. This enables baseline comparison, re-evaluation,
diffing and history.

## 28. Evidence refs

A result must explain **required · measured · producer · authority · verdict**
with **direct references** — Studio must not discover evidence by hash search.

## 29. Threshold-only re-evaluation — a first-class capability

```text
existing evidence / registered measurement  +  new RequirementSet
        ↓
new RequirementReport            (no backend re-run)
```

Reuse conditions depend on `MetricId`, target compatibility, producer/authority,
semantics version, population and evaluation context — **never on the old
threshold value**. Threshold is comparison policy, not measurement identity.

## 30. Change classes

| Class | Set identity | Measurement | Report | Fabric | Simulation | Optimization |
|---|---|---|---|---|---|---|
| `THRESHOLD_CHANGE` | changes | **reusable** | stale | **unchanged** | reusable | re-evaluates |
| `COMPARATOR_CHANGE` | changes | reusable | stale | unchanged | reusable | re-evaluates |
| `ENFORCEMENT_CHANGE` | changes | reusable | stale | unchanged | reusable | eligibility may change |
| `METRIC_CHANGE` | changes | reusable **only if** the new metric was already measured and is compatible | stale | unchanged | **may require re-run** | re-evaluates |
| `TARGET_CHANGE` | changes | reusable **only if** the measurement is attributable to the new target | stale | unchanged | may require re-run | re-evaluates |
| `PRESENTATION_METADATA` | **unchanged** | reusable | **unchanged** | unchanged | reusable | unchanged |

## 31. Fabric invalidation law

**Requirements do not guide compiler derivation** (`canonical.py`). Therefore a
`RequirementSet` change **does not invalidate `FabricArtifact`**; the same
compiled fabric is reusable. A future compiler that synthesises topology from
requirements is a **new compiler-guidance contract** and is not assumed.

## 32. Optimization boundary

A study may reference a `RequirementSet`, but a `Requirement` is **not** a
`Constraint`. Product requirement: *"the design should satisfy X."*
Optimization hard constraint: *"this candidate is eligible only when Y."*
**Same metric and threshold, different roles, different ids, different result
vocabularies.** Shared comparison utilities are fine; shared authority is not.

## 33. Regression boundary

Regression is **R0**. It is **not** added to `RequirementSet`. No
`threshold_relative_to_baseline` field exists in v4.

## 34. Compiler validation boundary

`world_size ≤ compute_tiles`, acyclic hierarchy, complete routes and
deadlock-free VCs are **correctness/feasibility laws**, not optional goals. No
requirements are created for them.

## 35. Verification boundary

Certificate obligations remain mandatory and **cannot be disabled by a
`RequirementSet`**. A user cannot declare *deadlock freedom = advisory*.

## 36. Target deletion / 37. Target rename

A disappeared target makes the requirement **BROKEN**; canonical set
construction **refuses** unresolved refs. **No label-based fallback, no
nearest match, no silent retarget.** A display-name-only change keeps the
reference valid; a semantic id change breaks it unless an explicit migration
map exists.

## 38. Legacy `traffic_class` migration

Because §6 proves the class string is **not** a target:

```text
traffic_class: "foo"  →  attribution_scope: CommunicationClassId("foo")
                         (typed, NOT a target)
```

The `attribution_scope` carries exactly the evaluator's guard semantics: a
multi-class workload plus a declared scope makes a violation
`UNMEASURABLE`. Unknown legacy class → **migration refuses**. The value binds
to `CommunicationIntent` identity (Domain D), never to a display name.

## 39. RequirementSet ↔ CommunicationIntent compatibility

A set carrying `attribution_scope` must validate against the design's
`CommunicationIntent`. Distinguish **schema-valid** from **bound to a specific
DesignIntent**, with a binding/validation stage.

## 40–42. Target decisions (explicit)

- `WorkloadOperationTarget`: **excluded** from v4 (§12).
- `ParallelismGroupTarget`: **excluded** from v4 (§13).
- `CommunicationClassTarget`: **excluded** from v4 — the strongest candidate,
  but **no registered metric has a class-level population** (§6). *This is the
  critical call: the legacy schema's class field is semantically inconsistent
  with the measurement, and the evaluator wins.*

## 43–44. Legacy latency / bandwidth target resolution

Both resolved by following the evaluator: **whole network evaluation**. Latency
is crisp and registered; bandwidth is removed (§8, §9).

## 45. Metric registry closure — statement

After the decisions above, the authoritative v4-valid registry is exactly
§16's two metrics. **No orphan evaluator metric remains** (bandwidth's producer
is retired from requirement evaluation, REQ-D4). **No registered metric without
an evaluator is offered as supported.**

## 46. Metric naming

Ids encode population and domain. `latency` and `bandwidth` are rejected as
generic. Registry metadata fixes the rest.

## 47. Metric evolution

A semantics change requires a **new `semantics_version` and registry identity**.
Old requirement sets and evidence stay reproducible. **An old `MetricId` is
never silently repointed** to a new calculation.

## 48. Legacy requirement migration (V3 → V4)

| Legacy field | Disposition |
|---|---|
| `traffic_class` | → `attribution_scope` (typed, non-target) |
| `qos_class` | **DROPPED_LEGACY_METADATA** — never v4 scientific state |
| `latency_ceiling_cycles` | → `metric_id=network_completion_cycles`, `comparator=LE`, `threshold` |
| `bandwidth_floor_gbps` | **MIGRATION_REFUSAL** (REQ-D4) — or legacy adapter only |
| `binding` | → `enforcement = BINDING | ADVISORY` |

## 49. RequirementId migration

Legacy requirements have index identity only. Migration creates deterministic
ids: `legacy-requirement-000`, `-001`, … **Recorded honestly: this is a
migration-created stable identifier; it does not recover a historical semantic
name.**

## 50. Report migration

Legacy reports keyed by `requirement_index` migrate using **the same
deterministic mapping function**. Requirement migration and report migration
**must agree exactly** — one function, never two.

## 51. Re-evaluation compatibility

```text
can_reuse_measurement(existing_measurement, new_requirement) =
    metric_id matches
and target compatible
and producer/authority admissible
and semantics_version matches
and population matches
and evaluation context matches
```

**Never a function of the old threshold.**

## 52. Target × metric matrix — v4 initial

| Target | `network_completion_cycles` | `network_completion_ns` |
|---|---|---|
| `WholeNetworkEvaluationTarget` | **valid** | **valid** |
| `CommunicationClassTarget` | deferred | deferred |
| `WorkloadOperationTarget` | deferred | deferred |
| `ParallelismGroupTarget` | deferred | deferred |
| `ServingMetricTarget` | deferred | deferred |

**Two valid cells.** A small matrix is the truthful outcome.

## 53. Stage matrix

| Stage | Whole-network cycles | Whole-network ns |
|---|---|---|
| DECLARE | schema-valid | schema-valid |
| BIND | target resolves (whole evaluation — always) | same |
| MEASURE | requires a verified result with a bound network window | same, wall-time variant |
| REPORT | `RequirementReport` v4 | same |
| static context | **supported** | supported |
| serving context | not currently declarable | not currently declarable |
| memory context | not supported | not supported |

## 54. Current E2 UI disposition — locked

| Control | Disposition |
|---|---|
| Traffic class | **REPLACE** → typed `attribution_scope` (not a target) |
| QoS class | **REMOVE** |
| Latency ceiling (cycles) | **REPLACE** → `metric_id=network_completion_cycles` + comparator + threshold |
| Bandwidth floor (Gbps) | **REMOVE** (REQ-D4) |
| Binding | **KEEP** as `enforcement` |

The old five-column table does not survive for familiarity's sake.

## 55. Future authoring shape

```text
REQUIREMENT
  Target         [typed selector — whole network evaluation]
  Metric         [registry-filtered selector]
  Condition      ≤ / ≥
  Threshold      [canonical-unit-aware value]
  Enforcement    Binding / Advisory
  Measurement    read-only: "Authenticated network completion cycles over the
                 qualified network evaluation window."
```

The explanatory line comes **from the registry**, never from a hand-written UI
string.

## 56. Requirement review

Each line answers: what object · what metric · what condition · what threshold ·
what measurement authority. No raw `MetricId` as primary text.

## 57. Unknown enums fail closed

Unknown target type · metric id · comparator · enforcement · verdict → **fail
closed**. Never mapped to `other`.

## 58. E1–E50 re-evaluated

E1 empty set → **schema-valid**; empty report → not satisfied (distinct) ·
E2 whole-evaluation bound → VALID · E3 operation-level → **DEFERRED** ·
E4 class-level → **DEFERRED** (no class-attributable metric) · E5 group-level →
**DEFERRED** · E6 duplicate id → INVALID · E7 reorder → same set identity ·
E8 display name → identity unchanged · E9 threshold → report stale, fabric
unchanged · E10 comparator → same · E11 target deleted → BROKEN, refuse ·
E12 unknown target → fail closed · E13 unknown MetricId → fail closed ·
E14 invalid pairing → fail closed · E15 wrong unit → schema invalid ·
E16 equivalent display unit → **same canonical threshold** · E17 cross-time-domain
→ inadmissible · E18 missing measurement → `UNMEASURABLE` (or
`NOT_APPLICABLE` if the context does not apply) · E19 unqualified backend →
`UNMEASURABLE` · E20 unsupported evaluator → `UNMEASURABLE` (no fifth verdict
added) · E21 pass → `SATISFIED` · E22 fail → `VIOLATED` · E23 binding FAIL →
aggregate not satisfied · E24 advisory FAIL → **report may still pass** ·
E25 binding UNMEASURABLE → never passes · E26 two requirements, same
target/metric → VALID · E27 latency with undefined population → **now defined**
by `MetricId` · E28 bandwidth ambiguity → **removed** · E29 QoS string → not a
valid requirement · E30 compile feasibility as a requirement → wrong domain ·
E31 deadlock as optional → wrong domain · E32 new evidence, same set → VALID ·
E33 threshold-only → **measurement reused** · E34 metric semantics version
changed → old evidence **not** silently reused · E35 same name, different
authority → not interchangeable · E36 static metric for a serving requirement →
invalid · E37 serving requirement on a static run → `NOT_APPLICABLE` ·
E38 requirement vs constraint, same threshold → distinct roles · E39 requirement
vs regression → distinct · E40 different sets → comparison **now possible by
`RequirementId`**; unmatched requirements shown explicitly · E41 partial
population → `UNMEASURABLE` · E42 complete population → evaluable · E43 unknown
verdict → fail closed · E44 class renamed in display → `attribution_scope`
still valid · E45 class id changed → BROKEN unless migrated · E46 operation
reorder → stable once ids exist · E47 group identity stable → stable ·
E48 evidence hash changes, semantics equivalent → reuse per §51 · E49 failed
certificate + number → **no blind SATISFIED** · E50 hardware vs simulation →
`UNMEASURABLE`.

## 59. E51–E70

| # | Case | Verdict |
|---|---|---|
| **E51** | requirements reordered | **same RequirementSet identity** |
| **E52** | display names changed | same scientific identity |
| **E53** | duplicate `RequirementId` | INVALID |
| **E54** | legacy requirement index migration | deterministic id |
| **E55** | legacy report index migration | **same deterministic mapping** |
| **E56** | `qos_class` differs only | no v4 scientific effect |
| **E57** | latency threshold changes | measurement reusable |
| **E58** | metric changes, threshold same | reuse only if already measured and compatible |
| **E59** | target changes, MetricId same | reuse depends on target-attributed measurement |
| **E60** | operation target where the multiplicity law is absent | **authoring refusal** |
| **E61** | group target with no per-group metric | authoring refusal |
| **E62** | class-target metric receives global-only measurement | invalid pairing per §52 |
| **E63** | same class display name, different ids | not interchangeable |
| **E64** | same metric label, different semantics version | not interchangeable |
| **E65** | same value from unqualified and qualified producers | only qualified evidence admissible |
| **E66** | old evidence, compatible MetricId, after a threshold change | **reused** |
| **E67** | old evidence, older incompatible semantics version | **not reused silently** |
| **E68** | RequirementSet changes, FabricArtifact reused | **valid** |
| **E69** | RequirementSet changes during an optimization study | product-intent identity changes; study compatibility documented |
| **E70** | unknown verdict in a stored report | fail closed |

## 60. Implementation-debt records

```text
REQ-D1  stable RequirementId + RequirementSet v4
REQ-D2  typed target union (one member today)
REQ-D3  metric-registry unification; collapse completion_time/cycles
REQ-D4  bandwidth removed from v4; re-admit only with an enforced single-window
        contract (numerator and denominator must share one window)
REQ-D5  report migration from requirement_index (one mapping function)
REQ-D6  report_passes doc↔code mismatch on binding NOT_APPLICABLE
```

Linked from the Requirements domain, the Evaluate capability surface and the
Studio capability/refusal view. **Not hidden in prose.**

## 61. Coherence gate

All 22 conditions are satisfied at the design level: stable `RequirementId` ·
`RequirementSet` identity · target union **precisely bounded to one member** ·
deferred targets explicitly deferred with rationale · every v4 requirement
references `MetricId` · registry is the sole semantic authority · all supported
evaluator metrics have registry identity (two) · **bandwidth removed with a
recorded defect and a re-admission condition** · `qos_class` removed ·
latency target/population resolved · comparator and threshold deterministic ·
time domains explicit · binding/advisory preserved · four verdicts exact ·
aggregate law exact (REQ-D6 resolution) · evidence admissibility explicit ·
report keyed by `RequirementId` · reuse law defined · fabric reuse law explicit ·
migration deterministic · E1–E70 verdicts · PLACEMENT not begun.

## 62. Domain verdict

The scientific evaluator was stronger than its schema, and the closure is
structural: identity, set, targets, metric authority, and deletion of one
decorative field.

Two findings changed the design rather than confirming it:

1. **`traffic_class` never narrowed the population.** It is an attribution
   guard, not a target — so the legacy targeting model is semantically
   inconsistent, and `CommunicationClassTarget` is **deferred** rather than
   built on a stable id that has no measurement behind it.
2. **The bandwidth calculation mixes an aggregate numerator with a
   possibly-mismatched denominator.** Rather than carry an ambiguous control
   forward, **bandwidth requirements are removed from v4** with the exact
   condition for re-admission.

The resulting v4 domain is **small and truthful**: one target, two registered
metrics, four verdicts, one aggregate law, and a reuse rule that makes
threshold-only changes free.

**REQUIREMENTS INTENT: PLANNED — COHERENT**

Per Gate 2's rule, PLACEMENT is not begun.
