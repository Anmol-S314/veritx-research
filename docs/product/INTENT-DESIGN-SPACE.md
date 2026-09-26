# INTENT-DESIGN-SPACE — Domain J specification (Gate 2, final)

Domain row: `intent-ontology.yaml :: domains.DESIGN_SPACE_INTENT`
Enforced by: `scripts/check_intent_ontology.py`
Status: **PLANNED — COHERENT.** See §55.

---

## 0. Reality header

**This domain is not greenfield.** A canonical, typed, product-wired optimizer
already exists and is unusually disciplined: a closed GUIDED dimension registry,
content-addressed candidate identity, three never-merged authorities (product
requirements / optimization constraints / measured objectives), a sealed Pareto
authority, and fail-closed typed ineligibility.

| Concept | Reality | Evidence |
|---|---|---|
| `OptimizationDefinition` | **R2 canonical study definition** | `optimization/definition.py:156` |
| GUIDED dimension registry | **R2 canonical, closed** | `optimization/definition.py:36` |
| LOCKED token refusal | **R2 structural** | `optimization/definition.py:44,62` |
| `Candidate` | **R3 derived, content-addressed** | `optimization/candidate.py:107` |
| `search_candidates` | **R3 derived, deterministic** | `optimization/search.py:83` |
| `Constraint` + tri-state verdicts | **R2 canonical** | `optimization/constraints.py:24` |
| `pareto_front` | **R3 derived, sole authority** | `optimization/pareto.py:18` |
| `OptimizationResult` | **R3 scientific carrier** | `optimization/result.py:363` |
| `OptimizationStudyView` v2 | **R3 product projection** | `optimization/result.py:452` |
| `CertifiedMetricRegistry` | **R2 metric authority** | `optimization/metric_registry.py:96` |
| `RealCandidateEvaluator` | **R4 certified evaluator** | `optimization/real_evaluator.py:122` |
| candidate-owned resource config | **R0 — category defined, no field exists** | `definition.py:36` |
| deduplication / alias accounting | **R0** | `optimization/CAPABILITY-LEDGER.md` W11 |
| surrogate / predicted performance | **R0** | — |
| evidence/compile reuse cache | **R0** | — |
| TP/DP/PP/EP dimensions | **R0 — SUPERSEDED** | ledger W3 |
| Bayes/MILP/RHO/GRPO/SA engines | **R0 — REJECT (deferred)** | `definition.py:245` |
| serving / memory objectives | **R0** | Domain I; static only |

## 1. Domain boundary

```text
Design Intent → canonical compiler → derived artifacts → verification →
evaluation → authenticated evidence → metrics / RequirementReport
                                                             ↑
                                                    OPTIMIZATION
```

Optimization sits **above** the pipeline and generates candidate Design Intents.
Every candidate travels the **same** canonical pipeline. **No optimizer-exclusive
shortcut may create scientific results.**

```text
OPTIMIZER ≠ compiler ≠ backend ≠ verifier ≠ evidence authority
```

Enforced structurally: `optimize_certified` is the only certified entry point and
**internally constructs and owns** `RealCandidateEvaluator` via a module-private
factory (`result.py:190,699`), so "no caller-supplied evaluator can enter the
certified path".

## 2. Current authorities

| Concept | Symbol | Path | Authority | In/Derived | Target owner |
|---|---|---|---|---|---|
| study definition | `OptimizationDefinition` | `optimization/definition.py:156` | canonical input | input | DESIGN-SPACE |
| dimension | `DomainParam` | `optimization/definition.py:87` | canonical input | input | DESIGN-SPACE |
| objective | `Objective` | `optimization/definition.py:132` | canonical input | input | DESIGN-SPACE |
| constraint | `Constraint` | `optimization/definition.py:146` | canonical input | input | DESIGN-SPACE |
| candidate | `Candidate` | `optimization/candidate.py:107` | derived | derived | DESIGN-SPACE |
| search | `search_candidates` | `optimization/search.py:83` | derived | derived | DESIGN-SPACE |
| Pareto | `pareto_front`/`pareto_ids` | `optimization/pareto.py:18,39` | derived | derived | DESIGN-SPACE |
| sealed Pareto gate | `pareto_with_scope` | `core/comparison.py` | derived | derived | core |
| constraint verdicts | `evaluate_all` | `optimization/constraints.py:60` | derived | derived | DESIGN-SPACE |
| metric authority | `CertifiedMetricRegistry` | `optimization/metric_registry.py:272` | canonical | input | OPTIMIZATION/EVALUATION |
| certified evaluator | `RealCandidateEvaluator` | `optimization/real_evaluator.py:122` | backend | derived | EVALUATION |
| analytic evaluator | `FakeDeterministicEvaluator` | `optimization/evaluators.py:184` | research-only | derived | test-only |
| result carrier | `OptimizationResult` | `optimization/result.py:363` | derived | derived | DESIGN-SPACE |
| product projection | `to_study_view(2)` | `optimization/result.py:452` | derived | derived | PRODUCT |
| legacy synthesis | `synthesis/{bo,iterative,milp}` | `synthesis/` | **legacy, untouched** | — | legacy |

## 3. Scientific glossary — the terms are not interchangeable

| Term | Definition |
|---|---|
| **Design Intent** | The user's canonical declaration (`CompileRequest`/V3). |
| **Design Space** | The closed, typed set of dimensions the optimizer may vary. |
| **Study Definition** | Baseline identity + design space + objectives + constraints + evaluation policy (+ search config). |
| **Study Execution** | One run: generated candidates, attempts, results, evidence refs. |
| **Candidate** | `base_design_hash` + canonical GUIDED patch. |
| **Compiled Candidate** | The canonical compiler output for that candidate. |
| **Evaluation** | One backend execution producing authenticated evidence. |
| **Metric Observation** | A registered metric's value over that evidence. |
| **Optimization Constraint** | A rule the *optimizer* applies to candidates. |
| **Product Requirement** | A statement about whether a design meets an external requirement. |
| **Objective** | A preference direction over a metric. |
| **Pareto Eligibility** | The backend-owned predicate admitting a candidate to the frontier. |
| **Selection** | The study's policy for naming one candidate from the frontier. |
| **Study View** | The stable, backend-produced product projection. |

## 4. Study definition — exact contract

```text
OptimizationDefinition {
    domain      : tuple[DomainParam, ...]     # non-empty, unique names
    objectives  : tuple[Objective, ...]       # >= 1, unique metrics
    constraints : tuple[Constraint, ...]      # <= 1 per metric
    method      : grid | enumeration | random
    budget      : {max_candidates?, max_evaluations?}   # positive ints
    seed        : int | None
    selection   : min_first_objective | lexicographic | none
}
```

```text
definition_id() = content_id("veritx/optimization-definition/v2", {
    parameters  : sorted by name, values in canonical JSON order,
    objectives  : declaration order,
    constraints : declaration order,
    method, budget(sorted), seed, selection })
```

**Fail-closed at construction:** empty domain refuses (*"an optimization with no
guided dimension would only re-evaluate the base design"*), empty objectives
refuse, duplicate parameter names refuse, **duplicate objective metric** refuses
(*"one destination declared twice"*), **duplicate constraint metric** refuses
(*"never last-write-wins"*), unknown budget fields refuse, `random` without a
seed refuses.

## 5. Study execution

`Optimizer.optimize_certified(request, definition, backend_config=...)`:

```text
search_candidates → per candidate:
   re-derive candidate_id (refuse drift)  →  refuse transplanted base
   evaluator.evaluate(cand)               →  refuse transplanted evaluation
   verify authenticated proof (A4)        →  derive claims
   extract registered metrics from claims →  refuse misreported metrics
   constraint verdicts                    →  objective availability
   eligibility predicate                  →  typed reasons
→ pareto over ELIGIBLE only → _select → OptimizationResult
```

Two entry points, deliberately unequal:

| Method | Accepts | Result class |
|---|---|---|
| `optimize_with_port` / `optimize` | arbitrary port | `ANALYTIC_RESEARCH` — **certified claims are a typed refusal** |
| `optimize_certified` | `CertifiedBackendConfig` only | `CERTIFIED_PRODUCT` — **the single assignment site** |

## 6. Study view

`OptimizationStudyView` **v2** is authoritative and lossless
(`contracts/srota/v2/optimization.study.view.schema.json`):

```text
required: contract_version, result_class, metric_registry_id,
          metric_registry_version, optimization_result_id, base_design_hash,
          definition, candidates, pareto_ids
plus:     selected_candidate_id, selection_rationale
```

Candidate rows carry `candidate_id, guided_patch, locked_consequences,
evaluation_ids{design_hash, performance_result_id, requirement_report_id},
product_requirements{satisfied, verdicts}, objective_values,
objective_availability, constraint_verdicts, evaluation_authority,
compilation_status, evaluation_status, evaluation_reason, eligibility_reason,
pareto_eligible, pareto_member`.

**v1 is explicitly LOSSY** — *"UNMEASURABLE collapses to false … these booleans do
NOT preserve three-state semantics; callers that need the distinction must
consume v2"* (`result.py:527`).

**One hash boundary:** engine digests stay bare; product views are
`sha256:`-prefixed, converted only at the projector (`_view_hash`, idempotent).

## 7. DesignSpace — closed typed registry, not a JSON path editor

```text
GUIDED_PARAMS = {link_width, concentration, radix, rcu_enabled,
                 topology_family, arbitration, mcast_groups, mcast_setup_cycles}
```

Each maps to a **NocConfig field**, patched with `dataclasses.replace` — the base
request is never mutated. Dotted `noc_config.*` aliases normalize to short names.

**LOCKED properties are structurally inexpressible.** Any dimension whose name
contains `routing`, `vc`, `turn` or `escape` raises at construction:

> *"routing, VC count/structure, turn restrictions and escape VC are
> compiler-derived and structurally inexpressible here — every candidate
> recompiles them via FabricCompiler"* — `definition.py:62`

**There is no arbitrary path mutation anywhere.** `normalize_patch` refuses any
non-GUIDED key. The Wave-F `fabric_overrides PARAM_REGISTRY` — which patched
intents outside the product `CompileRequest` authority — is **SUPERSEDED**.

## 8. Typed dimensions — inventory

| Dimension | Owner field | Type | Validation | Identity effect | Compile impact |
|---|---|---|---|---|---|
| `link_width` | `NocConfig.link_width` | int ≥ 1 | `_as_int(minimum=1)` | candidate_id + design_hash | topology/link artifacts |
| `concentration` | `NocConfig.concentration` | int ≥ 1 | `_as_int(minimum=1)` | both | endpoint demand vs capacity |
| `radix` | `NocConfig.radix` | int ≥ 1 | `_as_int(minimum=1)` | both | `params["k"]`, topology |
| `topology_family` | `NocConfig.topology_family` | `TopologyFamily` enum | enum construction (unknown refuses) | both | topology + routing derivation |
| `arbitration` | `NocConfig.arbitration` | str (non-empty) | `_as_str` only | both (**raw string**) | `RouterResourceIntentV4` via `canonical_allocator` |
| `rcu_enabled` | `NocConfig.rcu_enabled` | bool | `_as_bool` | both | reduction capability |
| `mcast_groups` | `NocConfig.mcast_groups` | int ≥ 1 | `_as_int(minimum=1)` | both | multicast engine |
| `mcast_setup_cycles` | `NocConfig.mcast_setup_cycles` | int ≥ 0 | `_as_int(minimum=0)` | both | multicast cost |

**CLI exposes only two** (`--link-widths`, `--concentrations`).

**Correction:** `radix` is **not** legacy. `NocConfig.radix` is canonical
(`compile_model.py:616`); `k`/side-length is a **derived** projection
(`params["k"] = cr.noc_config.radix`, `:1514`). **No `radix`→`side_length`
migration is required.**

## 9. Baseline design

```text
CandidateDesign = BaselineDesign + authorized DesignSpace mutations
```

The baseline is the canonical `CompileRequestV3` the study is launched against;
its `design_hash()` is `base_design_hash` and is bound into **every**
`candidate_id` and into `result_id`. **No candidate is reconstructed from a
sparse record without a baseline parent.**

## 10. Candidate

```text
Candidate { candidate_id, base_design_hash, guided_patch, request }
candidate_id = "cand_" + content_id("veritx/optimization-candidate/v1",
                                    {base_design_hash, patch sorted})
```

`__post_init__` **re-derives and refuses a transplanted id**; the optimizer
re-derives again per candidate and refuses drift (explicit conditionals, not
`assert`, so production gates do not vanish under `python -O`). **The full digest
is the identity** — *"a truncated hash is not an identity"*.

## 11. Candidate-owned resources — the category is real but **empty**

Domain H established that router buffers may be candidate-owned rather than
Design Intent. **The optimizer has no buffer dimension.** `GUIDED_PARAMS` contains
no buffer/resource field, so:

```text
CandidateConfiguration : CATEGORY DEFINED, NO FIELD EXISTS TODAY
```

**Candidate-owned is not a generic escape hatch.** When it lands, the value must
be neither user Design Intent nor compiler-derived, and it must appear in
`locked_consequences`-style provenance — not silently in the patch.

## 12. Candidate identity

Content-based, complete for the varied science:

```text
base_design_hash  +  canonical patch   →  candidate_id
```

**Excluded:** trial number, evaluation order, Optuna internal id, table row.
Verified by `test_optimization_identity_exact.py` (full digest; truncated id
refused) and `test_identity_ignores_key_order`.

**Gap (OPT-D2):** for **string-valued** dimensions the patch is hashed **before
domain canonicalization**. `NocConfig.arbitration` validates only
non-emptiness (`compile_model.py:651`), while `router_behavior.canonical_allocator`
normalizes the label at **compile** time (`:217`). So `"islip"` and `"ISLIP"`
produce **different `candidate_id`s and different `design_hash`es but the same
canonical `RouterResourceIntentV4`** — two candidate records for one scientific
design. `topology_family` is safe (enum construction refuses unknown spellings);
`arbitration` is not.

## 13. Candidate generation

```text
canonical_assignments: parameters sorted by name; values sorted by canonical
JSON; first parameter varies SLOWEST (lexicographic product)
```

Declaration order never changes the searched set. Grid budget truncation **keeps
the canonical prefix, never a sample**; random shuffles the canonical enumeration
with `seed` and then **re-sorts canonically** so *"the evaluated SET is
seed-dependent but the ORDER is canonical"*.

## 14. Candidate validation

| Case | Behaviour |
|---|---|
| non-GUIDED patch key | `CandidateError` — *"LOCKED properties cannot be patched"* |
| same key set twice with different values | refuse |
| empty patch | refuse |
| unknown `topology_family` string | refuse |
| transplanted `candidate_id` | refuse |
| `NocConfig` type violation | refuse (its own `__post_init__`) |
| value not int/str/bool | `_canonical_value` refuses (`None` refuses: *"omit the parameter to leave it at base"*) |
| duplicate domain values | refuse |

**Missing dimension assignment (J7) is unrepresentable:** the search is a full
Cartesian product, so every candidate carries one value per dimension by
construction.

## 15. Candidate state machine — the real vocabulary

```text
evaluation_status ∈ { EVALUATED, COMPILE_FAILED, INVALID, UNSUPPORTED,
                      BACKEND_UNAVAILABLE, FAILED }
compilation_status : the FabricCompiler verdict (INVALID | UNSUPPORTED | …)
```

Orthogonal, **not** statuses: `objective_availability[metric] ∈ {MEASURED,
UNMEASURABLE}`, `constraint_verdicts[metric] ∈ {SATISFIED, VIOLATED,
UNMEASURABLE}`, `product_requirements.satisfied ∈ {true, false, null}`,
`pareto_eligible ∈ {true, false}`.

**`UNMEASURABLE` is not an evaluation status** — it is an objective/constraint
state. This is a correction to the speculative taxonomy.

`real_evaluator` keeps `EVALUATED` for a requirement-violating run:

> *"Simulated successfully, product requirements failed: the evaluation stays
> EVALUATED with its measurements and a typed reason; the Optimizer makes it
> Pareto-ineligible. **Never relabel a measured run as UNSUPPORTED.**"* — `:246`

## 16. Compile feasibility

`FabricCompiler().compile(request)`; a non-`COMPILED` verdict maps **all** compiler
verdicts to `COMPILE_FAILED` with the verdict preserved in `compilation_status`.
**Canonical compiler refusal is intrinsic feasibility, not a user constraint** —
there is no `must_compile=true` knob, and adding one is forbidden.

## 17. Verification

`COMPILED` without a bundle refuses: *"refusing to bind fabricated LOCKED
consequences"*. `locked_consequences` is taken from the **compiler's** output, so
derived values are *recorded consequences*, never varied inputs. Downstream,
lowering + `assert_traffic_classes_bound` must succeed, and a **single unified
traffic class** is required (*"multi-class refused until a per-operation message
artifact lands"*).

## 18. Backend qualification

One backend per study, constructed by the optimizer itself. `--evaluate` has
exactly one choice (`booksim`), so **silent substitution is structurally
impossible**. Backend failure statuses (`BACKEND_UNAVAILABLE`, `FAILED`,
`UNSUPPORTED`) stay distinct from `COMPILE_FAILED` and from `INVALID`.

## 19. Evaluation

`FabricEvaluator().evaluate(..., require_quiescence=True)` → authenticated proof →
`verify_authenticated_backend_evaluation` → derived claims. **The
`certified-backend` label is descriptive, never proof**: a forged proof refuses
hard, and a carried `RequirementReport` that is not the one the proof derives
refuses.

## 20. UNMEASURABLE

Never 0, never ∞, never a fabricated worst score.

```text
objective_availability[metric] = "UNMEASURABLE" + objective_details[].reason
constraint verdict            = "UNMEASURABLE" (unmeasurable NEVER passes)
```

Constraint feasibility is tri-state: `True` / `False` / **`None` = not proven**.

## 21. Metric authority

```text
MetricAuthority { metric, producer, producer_id, semantics_version }
registry_id() = content_id(version, [{metric, producer_id, semantics_version}])
CERTIFIED_METRIC_REGISTRY = 3 metrics (completion_cycles, completion_time,
                             completion_ns) — "certified-builtin-v1"
```

**Certified metrics come only from the frozen registry over the verified claims.**
The evaluator's `objective_values` **never score** in the certified path: *"a
registered metric the evaluator carried with a different (or non-finite) value
refuses"*. Experimental/plugin registries *"can never yield CERTIFIED_PRODUCT
results"*.

**Optimization never redefines metric semantics.**

## 22. Objectives

```text
Objective { metric: str, direction: MIN | MAX }
```

**No formulas, no weights, no composite score.** Objectives are bare metric names
validated against the registry in the certified path (`_has_metric_authority`).
Duplicate objective metrics refuse. There is **no overall score** and therefore no
scalar scientific ranking.

## 23. Multi-objective semantics

A candidate's measurement vector is `(metric_1, …, metric_n)` in **objective
declaration order**. No scalar ranking is implied. For `min_first_objective`,
`objectives[0]` is **semantically significant** — so objective order is science,
not presentation, and must become explicit rather than incidental (OPT-D6).

## 24. Pareto dominance

```text
A dominates B  iff  A is no worse on every objective
              and   A is strictly better on at least one
              (MIN: <= / <   MAX: >= / >)
```

**No epsilon.** Each objective is compared only against itself. **Ties stay
ties:** *"equal objective vectors neither dominate nor eliminate each other"*.

`pareto_ids` runs over `{candidate_id: {metric: value}}` for **eligible candidates
only** — *"ineligible candidates … never reach pareto.py's indexing (never a
KeyError)"*.

## 25. Pareto eligibility — the exact predicate

`pareto_eligible = not eligibility_reasons`, where reasons are:

```text
1. evaluation_status != EVALUATED
2. evaluation_authority != "certified-backend"      # analytic/fake never eligible
3. no product RequirementReport bound
4. no performance_result_id bound
5. performance_result_id startswith "fake:"
6. binding product requirements not satisfied
7. any requested objective not MEASURED
8. hard constraints not all SATISFIED
9. (certified) any objective/constraint metric lacks registered authority
```

**Backend/scientific authority, never frontend.** Studio reads
`pareto_eligible`/`pareto_member` and does not recompute dominance
(`OptimizeView.tsx:38`); the plot filters to `MEASURED` objectives and *"never
coerced to 0"*.

**Note the coupling:** product requirements **are** part of eligibility (reason 6)
— **explicitly**, with a typed reason, not secretly. The measurement is never
lost: a requirement-violating candidate keeps `EVALUATED` + its measurements and
is excluded from the frontier. This is a **stated study policy**, and v2 preserves
both facts losslessly.

## 26. Optimization constraints

```text
Constraint { metric: str, op: "<=" | ">=", threshold: finite float }
```

**Operators are exactly `<=` / `>=`. No expression parsing, no free formulas.**
One constraint per metric. Verdicts carry `margin_or_excess` and are re-exposed as
`constraint_details` in `result_id`.

**Evaluation stage:** constraints are evaluated **post-evaluation** against
measured values — there is no pre-compile constraint stage today. A constraint on
an unmeasured metric is `UNMEASURABLE`, never a pass.

## 27. Product Requirements boundary — three authorities, never merged

| Authority | Field | Answers |
|---|---|---|
| **Product Requirement** | `requirement_report_id`, `product_requirements_satisfied`, `product_requirement_details` | "did the design satisfy the customer's requirements?" |
| **Optimization constraint** | `constraint_verdicts`, `constraint_details`, `constraints_satisfied` | "did the candidate satisfy the study's constraints?" |
| **Objective** | `objective_values`, `objective_availability` | "what was measured?" |

Requirements are **bound by identity and read** (`report_passes`), **never
converted into constraints and never aliased into objectives**. They may reference
similar metrics; they are not the same object.

## 28. Selection

```text
selection ∈ { min_first_objective, lexicographic, none }
```

Selection runs over **feasible Pareto members only** (`pareto_eligible` **and** in
`pareto_ids`). Ties break by **smallest `candidate_id`** (deterministic). It
**refuses selection over incomplete measurements**. `none` selects nothing. The
rationale is recorded verbatim in `selection_rationale`.

**"Best" is not claimed.** The vocabulary is *selected candidate* / *Pareto
member* / *lowest measured X*.

## 29. Guided optimization

**"Guided" is not an engine, a preset DesignSpace, a selection strategy and a UI
mode at once.** In this repository it names exactly two things:

1. the **closed GUIDED registry** of NocConfig knobs (`GUIDED_PARAMS`) — the
   opposite of LOCKED compiler-derived properties;
2. the **canonical CLI preset** (`veritx optimize`) that populates a definition
   from `--link-widths`/`--concentrations`.

There is **one** typed `OptimizationDefinition`. Guided and expert are two ways to
populate it, not two contracts.

## 30. Expert optimization

An expert space is the same `OptimizationDefinition` built from explicit typed
dimensions. **No arbitrary JSON editor, no hidden fields.** Every dimension is
visible in Review because it is a `DomainParam` in the definition.

## 31. Search engines

```text
grid | enumeration   exhaustive Cartesian, canonical order, budget = prefix
random               seeded, deterministic, canonical re-sort
```

**Refused with a stated return condition:** `bayes`, `bo`, `milp`, `sa`, `rho`,
`grpo` — *"Bayes/MILP only after deterministic correctness is established"*.

## 32. Search-engine identity vs scientific identity

**Current law: `method`, `budget` and `seed` are inside `definition_id()`.**

Consequence: changing grid→random, or changing the seed, produces a **different
study definition identity** even when the design space, objectives and constraints
are identical.

This is the domain's clearest identity-design question. The **scientific question
is unchanged** by search order; only the explored subset changes. **OPT-D3**
records the target split — `StudyDefinition` (science) vs `SearchExecution`
(attempt) — while noting that today the two are deliberately fused so a study
identity always pins the exact searched set.

## 33. Determinism

Grid and enumeration are deterministic by construction; random is deterministic
given the seed and **requires** one. `canonical_assignments` is re-enumerable
(`test_canonical_assignments_reenumeration_agrees`), and the frontier is
cross-checked against a brute oracle and against the sealed gate.

## 34. Evidence chain

```text
Candidate → base_design_hash + patch → candidate_id
          → design_hash
          → performance_result_id (authenticated)
          → requirement_report_id
          → metric_registry_id + version
          → objective observations (from the registry over verified claims)
          → eligibility → Pareto → selection
          → OptimizationResult.result_id → StudyView.optimization_result_id
```

**No scientific result is duplicated inside study JSON without a reference.**
`result_id` binds *"evaluation provenance, not just rounded objectives"*.

## 35. Comparability

Comparability is guaranteed **by construction, not by check**: one study has one
backend, one profile, one registry. `MetricAuthority.semantics_version` versions
each metric's meaning, and the registry identity binds it. The sealed gate
`pareto_with_scope` **refuses mixed fidelities**.

**Mixed-producer Pareto is structurally unreachable today.** The Wave-F
comparability gate is classified **HISTORICAL** with the return condition
*"Revisit when the real adapter mixes backends"*.

## 36. Reuse / cache

```text
compile-artifact reuse : NONE
evaluation reuse       : NONE
failure caching        : NONE (transient and deterministic failures alike)
deduplication          : NONE (ledger W11 HISTORICAL: no ALIAS state in P2)
```

Each study recompiles and re-evaluates every candidate. This is **correct but
wasteful**, and it is the domain's largest efficiency debt (**OPT-D5**) — the
canonical identities needed to key a cache already exist.

## 37. Invalidation

| Change | New definition? | Candidate ids | Compile reusable | Evidence reusable | Report | Pareto |
|---|---|---|---|---|---|---|
| baseline design | **yes** | all change | no | no | no | recompute |
| design space | **yes** | new set | per-candidate | per-candidate | no | recompute |
| objective direction | **yes** | no | yes | **yes** | no | **recompute only** |
| add objective | **yes** | no | yes | yes if measured, else UNMEASURABLE | no | recompute |
| remove objective | **yes** | no | yes | yes | no | recompute |
| constraint threshold | **yes** | no | yes | **yes** | no | recompute |
| RequirementSet thresholds | **yes** (identity) | no | yes | **yes** | **recompute** | recompute (eligibility) |
| search method / seed | **yes** | no | yes | yes | no | recompute |
| backend profile | **yes** | no | yes | **invalidated** | yes | recompute |
| metric semantics version | **yes** | no | yes | **invalidated** | yes | recompute |
| compiler semantics | **yes** | no | **invalidated** | invalidated | yes | recompute |
| study display name | **no** | no | — | — | — | — |
| candidate table sort | **no** | no | — | — | — | — |
| UI row highlight | **no** | no | — | — | — | — |

## 38. Study revisions

**No in-place mutation of a completed study is possible**: `OptimizationDefinition`
is frozen and `definition_id()` is content-derived, so any scientific change
produces a new identity. `OptimizationResult` is likewise frozen.

`StudyDefinition` vs `StudyExecution` **is** modelled: the definition is the frozen
input; the result carries the execution outcome. What does **not** exist is a
persisted, standalone canonical `StudyArtifact` — `OptimizationResult` is
in-memory and `OptimizationStudyView` is the persisted projection. **No second
artifact is invented** (§58: smallest truthful change).

## 39. Failure diagnostics

Every ineligible candidate carries a typed `eligibility_reason`, e.g.:

```text
"evaluation status COMPILE_FAILED"
"evaluation authority 'analytic-fake' is not 'certified-backend' — non-certified
 (analytic/fake) evaluations are never optimization-eligible"
"binding product requirements are not satisfied"
"requested objectives not measured: completion_cycles"
"hard constraints are not all SATISFIED"
"metric(s) without a registered metric authority over the authenticated proof: X"
```

**No opaque red row.** Failed candidates remain in `records` — **optimization
failure is data**, and is never deleted.

## 40. Prediction / surrogate boundary

```text
surrogate / predicted performance : DOES NOT EXIST
```

There is no analytical guidance model, no PREDICTED label, and therefore no risk
of a prediction entering the frontier. The **only** two evaluation authorities are
`certified-backend` and `analytic-fake`, and `analytic-fake` is **structurally
ineligible** for Pareto (eligibility reason 2). If a surrogate is ever added it
must be labelled `PREDICTED` and barred from the measured frontier.

## 41. Static / serving boundary

Optimization evaluates **static** designs through BookSim. `--evaluate` has one
choice; `FabricEvaluator` is the static path. **Serving objectives
(TTFT/throughput) are NOT AVAILABLE** and are not inferred from the serving
integration. Mixing request-level and static-network objectives is **FUTURE
CAPABILITY**.

## 42. Memory boundary

Domain I established that the Ramulator workflow is **not product-wired**, and
that `CERTIFIED_METRIC_REGISTRY` holds **zero memory metrics**. Therefore **memory
metrics cannot be optimization objectives today** — the objective would be
`UNMEASURABLE` (reason 9) or refused at the registry boundary. **No unavailable
metric is exposed as an objective.**

## 43. Legacy optimization surface

Authoritative classification lives in `optimization/CAPABILITY-LEDGER.md`:

| Surface | Verdict |
|---|---|
| Wave-F `PARAM_REGISTRY` (workload tp/pp/ep/dp + fabric via `fabric_overrides`) | **SUPERSEDED** — patched intents outside product authority |
| Wave-F store-backed verifier, budget-tail/ALIAS machinery | **SUPERSEDED / HISTORICAL** |
| Wave-F comparability gate | **HISTORICAL** — return condition: mixed backends |
| `optimization/metrics.py` (verified extraction) | **REJECT (deferred)** — returned as `metric_registry.py` |
| Bayes/MILP/RHO/GRPO/SA loops | **REJECT (deferred, with return condition)** |
| `synthesis/{bo,iterative,milp}`, CLI `synthesize`, `sweep`, `pareto`, `compare`, `baseline` | **HISTORICAL, untouched** — not part of the canonical study contract |
| `POST /optimize` | **`deprecated=True`** in the gateway |

**No legacy CLI behavior regains authority.** `veritx optimize` (canonical) and
`POST /api/v1/revisions/{id}/optimize` (product) are the two supported entry
points; both reach `optimize_certified`.

## 44. Migration

| Legacy | Target | Lossless? |
|---|---|---|
| `radix` → `side_length` | **no migration needed** — `NocConfig.radix` is canonical; `k` is derived | n/a |
| `fabric_overrides` intent patching | **refuse** — no product authority | refusal |
| legacy `sweep`/`synthesize`/`baseline` result dirs | navigation only, never identity | n/a |
| legacy objective metric strings | must resolve in `CERTIFIED_METRIC_REGISTRY` | refusal otherwise |
| unknown dimension kind | **fail closed** | refusal |
| unknown optimization schema | **fail closed** | refusal |

**Directory names are never scientific identity** (`sweep_N64` is navigation).

## 45. Canonical contracts

`OptimizationDefinition`/`DomainParam`/`Objective`/`Constraint`/`GUIDED_PARAMS`/
`definition_id` `optimization/definition.py:156,87,132,146,36,272` ·
`Candidate`/`candidate_id_for`/`apply_patch`/`normalize_patch`
`optimization/candidate.py:107,59,78,40` · `canonical_assignments`/
`search_candidates`/`bounded_random_candidates` `optimization/search.py:24,83,66` ·
`evaluate_all`/`evaluate_constraint_value` `optimization/constraints.py:60,27` ·
`pareto_front`/`pareto_ids`/`pareto_with_sealed_gate` `optimization/pareto.py:18,39,52` ·
`OptimizationResult`/`result_id`/`to_study_view`/`_select`/`Optimizer`
`optimization/result.py:363,371,549,565,655` ·
`CertifiedMetricRegistry`/`MetricAuthority`/`registry_id`/`CERTIFIED_METRIC_REGISTRY`
`optimization/metric_registry.py:96,57,135,272` ·
`CandidateEvaluation`/`EVALUATION_AUTHORITIES` `optimization/evaluators.py:61,56` ·
`RealCandidateEvaluator` `optimization/real_evaluator.py:122` ·
`NocConfig` `model/compile_model.py:614` · `canonical_allocator`
`model/router_behavior.py:217` · schema `contracts/srota/v2/optimization.study.view.schema.json`.

## 46. Capability matrix

| Capability | Declared | Compiled | Executed | Qualified | Evidence |
|---|---|---|---|---|---|
| typed DesignSpace | **yes** | n/a | n/a | closed registry | `definition_id` |
| content-based candidate id | **yes** | n/a | n/a | — | `candidate_id` |
| certified optimization | **yes** | yes | yes | `CERTIFIED_PRODUCT` | authenticated proof |
| analytic research mode | yes | yes | fake | **never eligible** | `analytic-fake` |
| multi-objective Pareto | **yes** | n/a | yes | sealed gate | `pareto_ids` |
| tri-state constraints | **yes** | n/a | yes | — | `constraint_verdicts` |
| product Requirement binding | **yes** | n/a | yes | — | `requirement_report_id` |
| selection policy | **yes** | n/a | yes | 3 policies | `selection_rationale` |
| guided CLI | **yes** | yes | yes | 2 dimensions | study JSON |
| product-wired optimization | **yes** | yes | yes | gateway + Studio | `optimization_id` |
| candidate-owned resources | **no** | no | no | — | — |
| scientific dedup / alias | **no** | no | no | — | ledger W11 |
| compile/evidence reuse | **no** | no | no | — | — |
| surrogate / predicted | **no** | no | no | — | — |
| serving objectives | **no** | no | no | — | — |
| memory objectives | **no** | no | no | — | Domain I |
| Bayes/MILP/SA engines | **no** | no | no | deferred | `definition.py:245` |
| TP/DP/PP/EP dimensions | **no** | no | no | SUPERSEDED | ledger W3 |

## 47. Advanced capabilities (real)

Closed GUIDED registry with **structural** refusal of LOCKED compiler-derived
properties · `dataclasses.replace` patching that cannot touch unauthorized fields
· full-digest content-addressed candidate identity with transplanted-id refusal ·
canonical enumeration with declaration-order independence and prefix-preserving
budget truncation · **three never-merged authorities** (product requirement /
optimization constraint / measured objective) · **tri-state** constraint verdicts
where unmeasurable never passes · a **frozen, identity-bearing metric registry**
with per-metric `semantics_version` · **certified-only metric extraction** that
refuses a misreported value · an **authenticated-proof verifier call** where the
label is not proof · a **sealed Pareto gate** cross-checked against a brute oracle
· direction-aware exact dominance with ties preserved · an **eight-term typed
eligibility predicate** · three selection policies with deterministic tiebreak ·
one hash boundary (`sha256:` prefixing) · a **lossless v2 view with an explicitly
lossy v1** · deterministic seeded search that re-sorts canonically.

## 48. Unsupported / deferred

candidate-owned resource dimensions · scientific deduplication and alias
accounting · compile-artifact and evidence reuse · failure caching ·
pre-compile constraint stage · Bayes/MILP/SA/BO/RHO/GRPO engines · TP/DP/PP/EP
dimensions · surrogate/predicted performance · serving objectives · memory
objectives · mixed-backend or mixed-producer frontiers · per-candidate backend
substitution · arbitrary objective formulas · scalar composite scores ·
multi-profile evaluation policy · persisted standalone `StudyArtifact`.

## 49. Required user flows

```text
Optimize → Study
  Baseline        current compiled design (design_hash)
  Design space    typed GUIDED dimensions (2 exposed in guided mode)
  Objectives      registered metrics + MIN/MAX
  Constraints     metric <= / >= threshold
  Requirements    reference the revision's RequirementSet
  Evaluation      one backend/profile (booksim, qualified)
  Search          grid | enumeration | random (+ seed)

Results
  Candidate | Changes | Status | Objective A | Objective B |
  Requirements | Pareto | Qualification | eligibility_reason
```

Candidate row answers: *what changed from baseline · did it compile · certificate
status · which backend/profile · objective observations · requirement verdicts ·
Pareto eligible and why/why not.* **No score-only table.**

**Promotion:** "Use this candidate" creates a **new Design revision** from the
candidate's canonical intent. The study stays immutable historical evidence. The
project revision is **never silently overwritten**.

## 50. Adversarial cases J1–J50

J1 two-value side length → valid study · **J2 empty DesignSpace → INVALID**
(*"would only re-evaluate the base design"*) · **J3 empty allowed set → INVALID** ·
**J4 duplicate dimension for one field → INVALID** (duplicate names refuse) ·
**J5 dimension targeting a derived RouteArtifact field → INVALID** (LOCKED token
refusal) · **J6 unknown dimension kind → fail closed** · **J7 missing assignment →
unrepresentable** (full Cartesian product) · **J8 unauthorized extra mutation →
INVALID** (`normalize_patch` refuses; `replace` cannot reach other fields) ·
**J9 two candidates canonicalizing to identical DesignIntent → NOT deduplicated
(OPT-D2)** · **J10 same candidate proposed twice → distinct only if the patch
differs; no alias accounting (W11)** · J11 invalid Fabric value → INVALID ·
**J12 insufficient endpoint capacity → COMPILE_FAILED** · **J13 unqualified
backend → BACKEND_UNAVAILABLE/UNSUPPORTED, never invalid** · **J14 crash →
FAILED** · **J15 metric absent → UNMEASURABLE** · J16 MIN · J17 MAX ·
J18 two-objective Pareto · **J19 equal vectors → both nondominated** ·
**J20 one objective UNMEASURABLE → not eligible** · **J21 requirement violated
with valid objectives → EVALUATED, measurements kept, Pareto-ineligible with a
typed reason** · **J22 requirement threshold change → evidence reusable; report
recomputed** · **J23 direction change → evidence reusable; frontier recomputed** ·
J24 new objective already measured → reuse · **J25 new objective not measured →
UNMEASURABLE** · J26 constraint threshold change → reuse · J27 profile change →
compile reusable, evidence invalidated · **J28 engine change → candidate evidence
reusable in principle; definition_id changes (OPT-D3)** · **J29 seed change →
sequence changes, candidate ids content-derived** · **J30 study name change → no
scientific effect** · J31 table sort → no effect · J32 Pareto display order → no
effect · J33 user selection → selection state only · **J34 frontend recomputes
Pareto → forbidden** · **J35 frontend infers EVALUATED from nonempty metrics →
forbidden** · J36 concentration-1 candidate → qualified · **J37 concentration-2 →
BACKEND_NOT_QUALIFIED, not invalid Fabric** · **J38 same under an allowed generic
backend → not supported (single backend)** · **J39 mixed producers on one axis →
unreachable by construction** · **J40 surrogate with no measured evidence →
no surrogate exists** · J41 surrogate satisfying a threshold → n/a ·
**J42 grid and guided producing the same candidate → same candidate_id** ·
**J43 buffer-only change → no such dimension (CandidateConfiguration empty)** ·
**J44 arbitration change → DesignIntent changes; raw-string normalization gap
(OPT-D2)** · J45 link width change → downstream topology changes ·
**J46 requirement set differs only → same design identity** · **J47 baseline
revision change → new definition** · J48 baseline metadata rename → per
DesignIntent metadata law · **J49 unknown MetricId objective → UNMEASURABLE /
refused at registry boundary** · J50 incompatible producer → preflight refusal.

## 51. Adversarial cases J51–J80

| # | Case | Verdict |
|---|---|---|
| J51 | same MetricId, same direction, twice | **duplicate objective refused** |
| J52 | same MetricId, opposite directions | refused (duplicate metric) |
| J53 | duplicate constraint | **refused at construction** |
| J54 | dimension values `[256, 256]` | **duplicate values refused** |
| J55 | values differing only by alias spelling | **normalized for enums; NOT for `arbitration` (OPT-D2)** |
| J56 | random engine proposes an out-of-space value | structurally impossible (enumerates the space) |
| J57 | float not exactly representable | **`_canonical_value` refuses non int/str/bool; clock parsing refuses non-integral** |
| J58 | compiler semantics version changes | candidate id may stand; compiled artifacts/evidence require revalidation |
| J59 | routing semantics version changes | DesignIntent unchanged; compiled route onward stale |
| J60 | VC assignment semantics changes | candidate id unchanged; evidence stale |
| J61 | qualification profile semantics changes | old evidence stays old-profile evidence |
| J62 | metric semantics version changes | old observation **not silently reused** |
| J63 | same metric name, different producer semantics | **not comparable** — registry identity differs |
| J64 | certificate PASS but RequirementReport VIOLATED | **valid measured candidate, Pareto-ineligible** |
| J65 | certificate FAIL but backend emitted cycles | not admissible — `COMPILE_FAILED` precedes evaluation |
| J66 | UNMEASURABLE shown as zero | **forbidden** — never coerced |
| J67 | failed candidate removed from history | **forbidden** — failure is data |
| J68 | study definition edited after completion | **new revision** (frozen dataclass) |
| J69 | search-space expansion | old evidence reusable in principle; new ids generated |
| J70 | search-space contraction | out-of-space candidates not members of the new study |
| J71 | same candidate evaluated twice after a transient failure | two attempts; stable evidence law applies |
| J72 | same result, different raw stdout | attempt identity differs; stable evidence per the evidence model |
| J73 | candidate uses torus | topology derives; **routing unavailable → typed pipeline status** |
| J74 | candidate uses unsupported RCU field | RCU **is** a GUIDED param; unsupported downstream → typed status |
| J75 | candidate sets VC count manually | **structurally refused** (LOCKED token) |
| J76 | candidate alters a route path | **structurally refused** |
| J77 | memory metric objective today | **unsupported** — no registered memory MetricId (Domain I) |
| J78 | serving TTFT objective | **unsupported** — static evaluator only |
| J79 | selected candidate promotion | creates a **new Design revision** with the candidate's identity |
| J80 | promotion then new study | new baseline identity; **old study preserved** |

## 52. Research questions O1–O50

| # | Answer |
|---|---|
| O1 | `optimization/{definition,candidate,search,constraints,pareto,result,evaluators,real_evaluator,metric_registry}.py`, `cli/commands_optimize.py`, `product/service.py`, `gateway/app.py` |
| O2 | v2 schema — §6 (lossless; v1 explicitly lossy) |
| O3 | **No separate `StudyArtifact`** — `OptimizationResult` is the in-memory carrier, the view is the persisted projection |
| O4 | `definition_id()` — §4 (method/budget/seed **included**) |
| O5 | `_view_hash` = `sha256:` prefixing, idempotent; **view identity, not science** — science is `optimization_result_id` |
| O6 | `optimization_result_id`, `base_design_hash`, `design_hash`, `performance_result_id`, `requirement_report_id`, `metric_registry_id`, `metric_registry_version`, `evaluation_authority` |
| O7 | `cand_` + content_id(base_design_hash, sorted patch) |
| O8 | **no** — no alias/dedup accounting (ledger W11) |
| O9 | the 8 GUIDED params; CLI exposes 2 |
| O10 | **all varied fields are DesignIntent (NocConfig)**; candidate-owned is empty |
| O11 | **no** — `normalize_patch` + `dataclasses.replace` make it unreachable |
| O12 | `Objective {metric, direction}` only — no formulas/weights |
| O13 | bare metric strings, authority-checked against `CERTIFIED_METRIC_REGISTRY` |
| O14 | `Constraint {metric, op ∈ {<=,>=}, finite threshold}`; one per metric; tri-state |
| O15 | **bound by identity and read**, never copied or converted |
| O16 | `EVALUATED, COMPILE_FAILED, INVALID, UNSUPPORTED, BACKEND_UNAVAILABLE, FAILED` + `compilation_status` |
| O17 | backend ran **and** a verified performance result exists (requirement violation still EVALUATED) |
| O18 | `objective_availability = UNMEASURABLE` + typed reason; never 0/∞ |
| O19 | the nine-term predicate — §25 |
| O20 | `optimization/pareto.py`, cross-checked by `pareto_with_sealed_gate` → `core.comparison.pareto_with_scope` |
| O21 | `no_worse AND strict`, direction-aware, no epsilon, ties stay ties |
| O22 | `MIN`/`MAX` on `Objective.direction` |
| O23 | ties remain non-dominated; selection tiebreak = smallest `candidate_id` |
| O24 | yes — `selected_candidate_id` + `selection_rationale` |
| O25 | `none` / `min_first_objective` / `lexicographic`, over feasible Pareto |
| O26 | **no overall score** |
| O27 | n/a — nothing scalar is authoritative |
| O28 | **not a separate engine** — the closed GUIDED registry + CLI preset; one contract |
| O29 | grid, enumeration, random; Bayes/MILP/SA/BO/RHO/GRPO refuse |
| O30 | seed **is** in `definition_id`; random requires an explicit seed |
| O31 | **no caching or reuse of any kind** |
| O32 | no |
| O33 | no |
| O34 | typed `CandidateRecord` rows with `evaluation_status` + `evaluation_reason`; retained |
| O35 | **one backend/profile per study** |
| O36 | **no** — single producer by construction |
| O37 | registry identity (`MetricAuthority.semantics_version`) + mixed-fidelity refusal in the sealed gate |
| O38 | **no surrogate exists** |
| O39 | n/a — no predictions |
| O40 | **no** — static BookSim only |
| O41 | **no** — no registered memory metric (Domain I) |
| O42 | **no** — Wave-F `PARAM_REGISTRY` SUPERSEDED |
| O43 | **yes** — link_width, concentration, radix, topology_family (+ rcu/mcast) |
| O44 | **yes** — `arbitration` is a GUIDED param, but with the raw-string normalization gap |
| O45 | **no** — no buffer dimension |
| O46 | `veritx optimize --fixture --search --link-widths --concentrations --latency-ceiling --max-candidates --study-out --evaluate --binary --network-clock-hz --run-root --timeout --seed` |
| O47 | `synthesize bo\|grid\|iterative`, `sweep`, `pareto`, `compare`, `baseline`, `run`, `runs`, `results`, `reproduce`, deprecated `POST /optimize` |
| O48 | **none needed** — `NocConfig.radix` is canonical; `k` is derived |
| O49 | `evaluation_ids` + `locked_consequences` + `metric_registry_id/version` + `objective_details` + `constraint_details` + `product_requirement_details` |
| O50 | *"a certified, single-backend, single-fidelity Pareto study over typed GUIDED NocConfig dimensions, with three never-merged authorities, content-addressed candidate identity, and fail-closed typed ineligibility — product-wired through the gateway"* |

**All 50 answered.**

## 53. Implementation debt

```text
OPT-D2  normalize string-valued dimensions through their domain contract BEFORE
        candidate identity (arbitration: "islip" vs "ISLIP" are two candidates
        for one canonical RouterResourceIntentV4)
OPT-D3  separate StudyDefinition identity from SearchExecution identity
        (method/budget/seed are currently inside definition_id)
OPT-D5  evidence/compile reuse keyed by canonical scientific identity
        (compile: candidate design identity + compiler semantics versions;
         evaluation: compiled identity + backend producer/profile + registry
         semantics version)
OPT-D6  make objective ordering explicit where it is semantic
        (min_first_objective uses objectives[0]; today it is implicit array order)
OPT-D7  refuse silently-ignored study-definition fields
        (product._parse_definition parses `selection`/`seed` but does not pass
         them to OptimizationDefinition)
OPT-D8  scientific deduplication / alias accounting before Pareto
        (ledger W11 HISTORICAL; required once any dimension is non-injective)
```

**Withdrawn / not debt:** `radix`→`side_length` migration (no such rename);
typed `MetricId` (registry authority already enforces the contract);
`StudyArtifact` (the result/view split already suffices).

**Not v4 debt:** candidate-owned buffer dimensions · serving optimization ·
memory optimization · torus-routing optimization · RCU/multicast search ·
arbitrary user objective formulas · Bayes/MILP engines · mixed-backend frontiers.

## 54. Product IA consequences

Domain J is a genuine product surface and **already product-wired**
(`POST /api/v1/revisions/{id}/optimize`, `GET /api/v1/optimizations/{id}`,
`pages/optimize.tsx`). It is **not** a future capability.

```text
Optimize
  Study        baseline · design space · objectives · constraints ·
               requirements · evaluation policy · search
  Run
  Results      candidates · Pareto · requirements · qualification · evidence
```

`OptimizeView.tsx` already follows the law: it reads `pareto_member`/
`pareto_eligible`, plots only `MEASURED` objectives, and never coerces an
unmeasured value. **Studio must keep doing exactly that.**

## 55. Remaining blockers

**None for DESIGN-SPACE coherence.** Three items are recorded rather than
resolved, and none is a scientific ambiguity:

1. **OPT-D2** — the `arbitration` normalization gap is a *precision* defect with a
   known fix (canonicalize before identity); it does not make any current claim
   false, because the certified path's `design_hash` still separates the two
   candidates.
2. **OPT-D3** — definition-vs-execution identity is a deliberate current fusion,
   documented with its consequence.
3. **Global decisions D1–D8** — the ontology checker reports
   `GATE CLOSED pending decisions: D1, D2, D3, D4, D5, D6, D7, D8`. These are
   **Gate-3 cross-domain decisions** and are **not solved here**.

**Recorded for Gate 3 (not silently solved):**

- **D-item:** whether product-requirement satisfaction belongs in the Pareto
  *eligibility* predicate or in a separate frontier partition (current law:
  eligibility; explicit and typed).
- **D-item:** whether `method`/`budget`/`seed` belong in study or execution
  identity (current law: study).
- **D-item:** whether `arbitration` normalization is a compile-time or
  intent-construction-time obligation.
- **D-item:** whether a pre-compile constraint stage is admitted.

## 56. Domain verdict

The central question is answered from code, not from aspiration.

**What optimization may vary:** exactly eight typed `NocConfig` GUIDED dimensions,
each a `DomainParam` with a finite value set, patched by
`dataclasses.replace` so no other field is reachable. **What must remain fixed:**
everything else — and LOCKED properties (routing, VC count/structure, turn
restrictions, escape VC) are not merely forbidden but **structurally
inexpressible**, refused by name at definition construction. **What constitutes an
evaluated candidate:** `base_design_hash` + canonical patch → content-addressed
`candidate_id`, re-derived and refused on drift, run through the **same** canonical
pipeline. **What makes candidates comparable:** one study has one backend, one
profile, one metric registry, and a sealed Pareto gate that refuses mixed
fidelities.

The repository's optimizer is already more disciplined than the plan assumed. It
keeps **three authorities that are never merged** — product requirements,
optimization constraints, measured objectives — and it refuses to let an
`analytic-fake` evaluation reach the frontier at all. It has a **frozen,
identity-bearing metric registry** with per-metric `semantics_version`, and in the
certified path the evaluator's own numbers *never score*: metrics are extracted
from verified claims, and a misreported value refuses hard. Its Pareto predicate
is a **nine-term typed conjunction** whose every failure is a readable reason, and
its view is lossless in v2 with an explicitly lossy v1.

Three corrections to the planning brief came out of the audit and are recorded
rather than smoothed over. **`radix` is not legacy** — `NocConfig.radix` is
canonical and `k` is derived, so no migration is needed. **`UNMEASURABLE` is not a
candidate status** — the real vocabulary is six evaluation statuses plus orthogonal
objective/constraint states. And **the optimizer is not un-wired** — unlike
Ramulator, it is reachable from the gateway, the CLI and Studio.

The domain's real gaps are precision and efficiency, not coherence. Candidate
identity for string-valued dimensions is computed **before** domain
canonicalization, so `"islip"` and `"ISLIP"` are two candidates for one canonical
router intent. `method`/`budget`/`seed` sit inside `definition_id`, fusing the
scientific question with its search attempt. There is **no reuse of any kind** —
every study recompiles and re-evaluates everything — even though the canonical
identities needed to key a correct cache already exist. And product requirements
**are** part of Pareto eligibility; that coupling is explicit and typed rather
than hidden, but it is a policy the next phase should name deliberately.

What the product may honestly claim today: a certified, single-backend,
single-fidelity, deterministic Pareto study over a closed set of typed design
dimensions, with three separate authorities and fail-closed ineligibility — and
**not** candidate-owned resource search, deduplication, evidence reuse, surrogate
guidance, or serving/memory objectives.

**DESIGN-SPACE / OPTIMIZATION: PLANNED — COHERENT**

Gate 2 is complete for all eleven domains. **Gate 3 (D1–D8) is not begun.**
