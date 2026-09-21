# Wave F — Design-Optimization Scientific Contract

Status: **v1 supported domain** (branch `wave-f/design-optimization`, from
Wave-E seal `d878cf5ec6d9797083a7968baac58f2f7cf54ea7`).

Wave D answers **what** communication occurs. Wave E answers **when** it
occurs. Wave F answers **which declared architecture candidates satisfy the
declared requirements, which are dominated, and what the Pareto frontier is**
— as an orchestration layer *above* the sealed control plane, never as a
second evaluator.

## 1. Trust chain

```
OptimizationDefinition (content-addressed)
→ deterministic finite design space (canonical order)
→ canonical candidate assignments (dedupe → ALIAS, resolve before execute)
→ scenario intents resolved through the sealed intent system
→ sealed SrotaControlPlane.evaluate() (reuse included; no second backend path)
→ verified candidate results (load_verified_result ONLY)
→ typed metric extraction (closed registry, verified parents only)
→ hard-constraint verdicts (exact rational bounds)
→ comparability gate
→ scoped Pareto frontier (pareto_with_scope via direction adapter)
→ optional explicit selection policy (NONE | SINGLE_OBJECTIVE | LEXICOGRAPHIC)
→ verified OptimizationResult (full re-derivation on load)
```

Every reported selection must be mechanically explainable by this chain.
A candidate may never enter the frontier from an unverified copied number.

## 2. Primary invariant

**Optimization cannot make the underlying model more truthful.** If Wave E
says `UNCALIBRATED`, Wave F may find the best design *under that model*; it
may not upgrade that into "best hardware". Every result carries the
`fidelity_warning` derived from the verified Wave-E parents, and every
objective value carries `fidelity` + `source_result_id`.

## 3. Artifacts

Exactly two persisted resources:

- `optimizationdef` — the parsed, content-addressed `OptimizationDefinition`
  (`identity_dict()` round-trips through `parse`; the definition ID is
  `H(identity_dict)`).
- `optimizationresult` — the run record: per-raw-assignment accounting
  (including per-scenario `scenario_outcomes` evidence), objective
  values, constraint docs, Pareto scope/front, selection, completeness,
  verdict, budget, fidelity warning. Frontier, selection, verdicts and
  completeness are **derived summaries**: persisted for inspection,
  re-checked on load, never authority.

**Schema version:** the result artifact is `schema_version = 2` (the
pre-seal audit closure added `scenario_outcomes` evidence and the
strict refusal of execution-refusal statuses without authenticatable
attempts). The branch is not sealed and nothing external consumed the
unsealed v1 shape, so no migration machinery exists — v1 artifacts are
simply not loadable under the final pre-seal schema. This was a
deliberate reset, not a compatibility pretense.

## 4. Identity (§16/§17)

```
definition_id    = H(canonical identity_dict)
design space     canonicalized: parameter names sorted, domain values sorted
                 by canonical JSON — declaration order and domain-value order
                 are NOT semantic (§83/§84)
candidate_id     = H(definition_id, canonical assignment, resolved scenario
                 intent ids)
```

A change to objectives, direction, constraint bounds, budget, or parameter
domains changes `definition_id` — no stale result reuse (§79–§81).

## 5. Hardware consistency across scenarios (§10)

A multi-scenario candidate is one architecture evaluated against several
workloads. The hardware signature is the **hardware-only projection of
the EFFECTIVE (candidate-patched) scenario document**:
`patched_scenario_template(template, assignment)` — the same document
the evaluator resolves — projected onto every registered HARDWARE
parameter's assigned value plus the effective `fabric_preset` and
effective `fabric_overrides`. Nothing else enters — in particular the
Wave-D/E blocks (which carry the PHASE), the workload, and SUPERSEDED
base-override values do not: two scenarios whose base overrides differ
but whose candidate assignment overwrites the difference are the SAME
candidate hardware (pre-seal audit finding 1 — the base-template
signature falsely invalidated valid hardware).
A candidate whose scenarios disagree on this signature is `INVALID`; the
error names the disagreeing signatures. Do not guess.

## 6. Closed registries

- **Parameters** (`fabric.topology`, `fabric.link_width`, `workload.tp/pp/
  ep/dp`): registered only where the intent system provably patches. No
  arbitrary JSON paths. Unregistered names refuse at definition parse.
- **Metrics**: each provider declares unit, direction compatibility,
  required evidence and fidelity. Extraction reads ONLY verified parents:
  Wave-E timing block, Wave-D delivered counts, Wave-E latency
  re-derivation, and structural counts lowered through the SAME Wave-B
  chain the backend consumes (`derive_request` → `compile_bundle`).

Structural counts are `EXACT_STRUCTURAL` — read off the materialized
topology/attachment, never from `topo_size()`-style formulas (whose torus
formula disagrees with the lowered graph at k=2; §35 forbids trusting it).
Absent modeled behavior is `UNMEASURABLE`, never zero (§33): no requests
declared → `request.p95_latency_s` UNMEASURABLE; no verified template →
structural UNMEASURABLE. `area_mm2`, `power_w`, `energy_j` are not in the
registry (§36): no model, no metric.

Scenario-free specs pick the lexicographically first scenario with a
verified result and use THAT scenario's candidate-patched template — a
structural metric always sees the intent its evaluation saw.

## 7. Search (§21–§29)

- `EXHAUSTIVE_GRID`: every valid unique candidate; the only mode that may
  claim a global optimum within the declared space (§22). A budget under
  exhaustive search refuses at definition parse.
- `BUDGETED_GRID N`: at most N unique candidates in canonical order;
  language is "best observed", never "global optimum" or
  `NO_FEASIBLE_DESIGN` unless the space happened to be exhausted (§23).
- Canonical order: parameters sorted by name, values sorted by canonical
  JSON rendering (the SAME ordering identity uses; type preserved —
  `"128" < "2" < "4" < "8"` as strings, so `[8, 2, 128, 4]` enumerates
  as `128, 2, 4, 8`), lexicographic Cartesian enumeration. This order is
  scientifically consequential: it selects the BUDGETED_GRID evaluated
  prefix (pre-seal audit finding 6).
  JSON, lexicographic Cartesian enumeration (§24).
- Budget accounting reports requested vs planned vs evaluated vs reused
  (§25). The unevaluated tail stays visible as `NOT_EVALUATED` and must
  equal exactly the canonical prefix cut.
- Reuse goes through the control plane's content-addressed reuse (§26) —
  no second cache. Evidence-grade reuse additionally inherits the sealed
  producer contract: a dirty source tree refuses reuse and re-executes.
- No heuristic pruning in v1 (§28). Resolve-before-execute rejects invalid
  combinations before any backend launch (§18/§27).

## 8. Candidate statuses (§30)

`SUCCEEDED`, `INVALID`, `ALIAS`, `FAILED`, `TIMED_OUT`, `UNSUPPORTED`,
`BLOCKED`, `UNMEASURABLE`, `NOT_EVALUATED` — never one generic loser
bucket, no disappearing candidates (§64). `NOT_EVALUATED` is **not**
terminal: including it in the terminal set would derive
`search_complete=True` for budgeted runs — the §75 forgery from within.
`PRUNED_PROVEN` does NOT exist in v1: there is no pruning producer
(§28), and carrying unreachable vocabulary invites a silent second
search policy. It returns only with a real producer and a contract
amendment (§29).

### 8b. Non-success statuses are EVIDENCE-BOUND (pre-seal audit)

A serialized error document inside the optimization artifact is **not
evidence by itself** — a forger can fabricate status and error together
and re-sign. The verifier therefore proves every non-success outcome
against sealed evidence:

- `FAILED`/`TIMED_OUT` → the cited attempt must authenticate through
  `load_verified_attempt`, bind back through verified
  experiment → plan to THIS scenario's intent id, agree in status with
  the verified attempt, and agree in error code with the attempt's
  persisted error. A transplanted attempt (real evidence, wrong
  candidate/scenario/status) refuses.
- `UNSUPPORTED`/`BLOCKED` → the refusal is REPRODUCED deterministically:
  the candidate's patched scenario intent is re-resolved through the
  sealed control-plane path and the same sealed classifier
  (`study_status_for_code`) must yield the claimed status. Parsing the
  stored error code alone closes the syntax, not the evidence hole.
- The aggregate candidate status is re-derived with the ONE shared
  `aggregate_status` rule from the VERIFIED per-scenario outcomes; the
  persisted aggregate is a summary, never authority.
- Control-plane machinery defects (`EVIDENCE_INVALID`,
  `INTERNAL_ERROR`, `NOT_FOUND`, `CONFLICT`) are NEVER candidate
  science on either side: they escape and fail the run instead of
  becoming a `FAILED`/`INVALID`/`UNMEASURABLE` observation.

## 9. Constraints and verdicts (§45–§53)

- Operators: `<=`, `>=` on exact rational values. Value/bound truth table
  includes equality; wrong unit refuses at parse; missing metric →
  `UNMEASURABLE` (never passes, never zero).
- Feasible = every declared constraint SATISFIED (§48). With zero declared
  constraints this is vacuous for SUCCEEDED candidates — an evaluated
  candidate with no binding constraints IS feasible; FAILED/TIMED_OUT
  candidates are never feasible.

## 9b. Exact closure of nested collections (pre-seal audit)

The verifier proves exact membership, never merely expected ⊆ persisted:

- objective/constraint candidate keysets equal the re-derived keysets —
  no ghost candidate entries survive;
- `value_map_from_doc` REFUSES duplicate `(metric, scenario)` rows (a
  silent last-one-wins overwrite would let a forger replace a value by
  appending a row);
- per-candidate constraint rows correspond exactly to the declared
  constraint dimensions (no extra/missing rows);
- `scenario_outcomes` (per evaluated candidate) is exactly the declared
  scenario set with a closed field set; the convenience projections
  `scenario_result_ids`/`scenario_reused`/`scenario_intent_ids` must be
  EXACT projections of the authoritative outcomes — two independently
  editable truths are not allowed;
- `NOT_EVALUATED`/`ALIAS`/`INVALID` records carry no fabricated
  execution evidence;
- budget accounting (`scenario_evaluations_attempted/_reused`) is
  recomputed only from closed verified records — a ghost scenario key
  cannot inflate the counts.

Verdict ladder: `FEASIBLE` (existential, valid even budgeted) >
`CONSTRAINT_UNMEASURABLE` (no measurable evidence anywhere) >
`NO_FEASIBLE_DESIGN` (complete search AND every valid candidate
conclusively rejected by measured evidence — timeouts/unsupported/
unmeasurable never prove it) > `INCONCLUSIVE` > `NO_VALID_CANDIDATES`
(every assignment invalid before evaluation; not a feasibility claim).

## 10. Pareto and selection (§40–§42, §57–§61)

- Only SUCCEEDED + feasible + measurable + comparable candidates enter the
  frontier; every excluded candidate stays visible with a reason (§41).
- Production reuses `core.comparison.pareto_with_scope` through a thin
  direction adapter (MAX→−value for dominance only; the raw value and
  direction are preserved in the result). No second dominance
  implementation in production; the brute-force oracle lives in tests.
- Mixed-fidelity comparisons refuse by default (§94).
- Selection: `NONE` (no winner persisted), `SINGLE_OBJECTIVE` (exact ties
  preserved — all tied candidates are returned, `tied: true`; a scientific
  tie is never broken by name), `LEXICOGRAPHIC` (declared priority order,
  ties preserved at every level). No default weighted sum (§60).
- Scenario identity is preserved across candidates (§44): prefill A is
  never compared against decode B.

## 11. Completeness is derived (§54–§56, §62, §70)

`search_complete` and `frontier_complete` are recomputed from regenerated
accounting, never trusted. `frontier_complete=True` requires exhaustive
search + every valid candidate accounted + every feasible candidate
measurable on every objective + all comparable (`comparable_count` is the
scoped comparison's comparable input count — the size of the front is an
output, not the scope). Budgeted runs report the observed frontier only.

## 11b. Scenario scope of metrics (pre-seal audit)

Every registry metric declares `scenario_scoped`: does the value depend
on the WORKLOAD?

- `scenario_scoped = True` (`system.makespan_s`, `network.window_s`,
  `request.mean_latency_s`, `request.p95_latency_s`,
  `network.delivered_packets`): in a multi-scenario definition the
  request MUST name an explicit scenario — `"prefill"` vs `"decode"`
  never collapses to whichever name sorts first. Parse-time refusal,
  not extraction-time guessing.
- `scenario_scoped = False` (`fabric.router_count`,
  `fabric.endpoint_count`, `fabric.channel_count`): scenario-free is
  valid — §10 already proves one effective hardware across scenarios
  and the counts derive from that hardware.

No metric-name conditionals in parsing code; `MetricDef.scenario_scoped`
is the single authority.

## 11c. Exception policy (pre-seal audit)

Expected typed failures map to scientific outcomes; unexpected internal
failures ESCAPE and fail the run. A bug may never become evidence:

- `resolve_intent` during candidate construction: only `INVALID_INTENT`
  means "this assignment is invalid". Machinery codes
  (`EVIDENCE_INVALID`/`INTERNAL_ERROR`/`NOT_FOUND`/`CONFLICT`) and
  raw programming errors (`RuntimeError`, `AttributeError`, …) escape —
  a bug must never silently shrink the design space as fabricated
  `INVALID` science.
- `cp.evaluate`: the same machinery-code filter guards the candidate
  terminal path; only genuine candidate-terminal refusals classify
  through the sealed `study_status_for_error`.
- Wave-E metric re-derivation: typed scheduler/workload/time domain
  errors and the compile chain's typed refusals
  (`KeyError`/`TypeError`/`ValueError`) mean absent behavior →
  `UNMEASURABLE`; anything else is a bug and propagates.
- Verification-aid helpers (`request_latency_summary`) follow the same
  narrowed families.

## 12. Verification (§65–§71, §113–§120)

`load_verified_optimization_result` re-derives everything from verified
parents:

1. closed envelope/schema; resource_id = recomputed content id;
2. verified definition load (`optimizationdef` recomputes to its own ID —
   an in-place rewrite of stored definition content under the old ID
   refuses, closing the §79 in-place attack);
3. regenerated design space: same count, same assignments, same
   candidate_ids, same scenario-intent bindings (§71–§74);
4. status/tail agreement: NOT_EVALUATED = exact canonical prefix cut;
   `search_complete` agreement (§75);
5. per-SUCCEEDED-candidate re-extraction with the SAME patched templates
   as the builder — persisted objective values must match exactly
   (§66/§131–§137);
6. constraint verdict re-derivation (§67);
7. feasibility, comparability, Pareto recomputation (§68/§77);
8. budget recomputation; selection recomputation (§69/§78/§137);
9. verdict recomputation (§76).

The persisted outer ID covers definition + accounting + completeness, so
transplant/omission/forgery attacks that alter those must re-sign — and
re-signing is caught by re-derivation. Forged derived summaries (front,
selection) do not even change the outer ID; the immutable store refuses
the rewrite, and the verifier is the last line of defense.

## 13. Wave-F optimizes models, not reality (§37/§95)

Selection language is mechanically scoped: "best within the declared
finite design space under the declared performance models" (exhaustive) or
"best observed among N evaluated candidates" (budgeted). Never "fastest
physical implementation".

## 14. Known limitations (v1)

- Finite discrete domains only; no continuous/Bayesian search.
- Structural metrics limited to router/channel/endpoint counts.
- No area/power/energy/thermal metrics (no authoritative model).
- Fabric/topology parameters verified only against the presets' families
  (mesh, torus); other families refuse until audited.
- Wave-E fidelity propagates unchanged: uncalibrated parents yield
  uncalibrated selections.
