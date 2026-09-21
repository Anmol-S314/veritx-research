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
- `optimizationresult` — the run record: per-raw-assignment accounting,
  objective values, constraint docs, Pareto scope/front, selection,
  completeness, verdict, budget, fidelity warning. Frontier, selection,
  verdicts and completeness are **derived summaries**: persisted for
  inspection, re-checked on load, never authority.

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
workloads. The hardware signature is the **hardware-only projection**:
every registered HARDWARE parameter's assigned value plus the template's
`fabric_preset` and `fabric_overrides`. Nothing else enters — in particular
the Wave-D/E blocks (which carry the PHASE) and the workload do not.
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

## 9. Constraints and verdicts (§45–§53)

- Operators: `<=`, `>=` on exact rational values. Value/bound truth table
  includes equality; wrong unit refuses at parse; missing metric →
  `UNMEASURABLE` (never passes, never zero).
- Feasible = every declared constraint SATISFIED (§48). With zero declared
  constraints this is vacuous for SUCCEEDED candidates — an evaluated
  candidate with no binding constraints IS feasible; FAILED/TIMED_OUT
  candidates are never feasible.
- Verdict ladder: `FEASIBLE` (existential, valid even budgeted) >
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
