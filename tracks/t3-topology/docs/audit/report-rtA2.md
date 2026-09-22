# RT-A audit-v2 repair report — optimization truth

- **Worker:** RT-A repair scope (`/tmp/task-rtA2.md`)
- **Worktree:** `/home/datavex/veritx-rtA`
- **Branch:** `rt-final/optimization-truth`
- **Base:** `0e761060` (RT_MERGED_SHA)
- **Audited tip:** `f4e4a58d` (independent verifier: BLOCKED, 4 repairs)
- **Final tip:** `07377439`
- **Pushed:** `github HEAD:refs/heads/audit/rt-final-optimization-truth-v2`
- **Tree state:** clean (`git status --short` empty; battery residue removed)
- **Binary:** `third_party/booksim2/src/booksim`, sha256
  `65d61d336fabfb6a4ea6e8fd47826f5e9a707834ef1450cbde11bd32defc7c11`
- **apps/studio:** untouched (zero `apps/studio` paths in the diff);
  Studio retarget stays Worker C's per the ledger note.

## Repairs (one commit per repair, on top of the audited tip)

| Repair | Commit | Subject |
|---|---|---|
| A-P0.1 | `095bb57b` | fake/no-report evaluations are never authoritative |
| A-P0.2 | `28d5834c` | preserve the real evaluation status taxonomy |
| A-P1.3 | `b98d2c4a` | lossless identified v2 definition + optimization_result_id |
| A-P1.4 | `07377439` | candidate status and reason in records, v2 and result_id |

---

## A-P0.1 — fake/no-report evaluations never masquerade as authoritative

- `CandidateEvaluation` carries `evaluation_authority`
  (`certified-backend` | `analytic-fake` | `None`). The real adapter
  declares `certified-backend` on every outcome; the deterministic fake
  is structurally `analytic-fake` and still has no RequirementReport and
  a `fake:` performance result.
- Eligibility (the only route into `feasible_values`/Pareto/selection)
  now requires ALL of: status EVALUATED, authority
  `certified-backend`, a bound product RequirementReport, a bound
  non-fake `performance_result_id`, product requirements pass, every
  requested objective measured+finite, and every hard constraint
  SATISFIED. Each failed condition appends a typed string to
  `CandidateRecord.eligibility_reason`, which is bound into
  `OptimizationResult.result_id()`.
- v2 exposes `evaluation_authority` and `eligibility_reason`; the schema
  enforces `pareto_member ⇒ pareto_eligible` and
  `pareto_eligible ⇒ evaluation_authority = certified-backend` with
  `eligibility_reason = null`. The fake CLI path now emits empty
  `pareto_ids`, `selected_candidate_id = null`, and per-row reasons.
- Adversarial test `test_ap01_fake_v2_pareto_refusal_for_authority`:
  fake study ⇒ not eligible / not Pareto / not selected in the
  authoritative v2 view; the same candidate mechanics under a declared
  certified test double still reach the frontier (real candidates
  unaffected; the real BookSim grid test still selects).

## A-P0.2 — status taxonomy preserved

- Compile-phase refusals (compiler INVALID and UNSUPPORTED) →
  `evaluation_status = COMPILE_FAILED`, with the compiler's own verdict
  kept in `compilation_status`.
- Lowering refusals keep INVALID / UNSUPPORTED; backend-phase outcomes
  keep BACKEND_UNAVAILABLE / FAILED / UNSUPPORTED verbatim. An unknown
  `FabricEvaluator` status raises `EvaluationError` instead of being
  collapsed.
- A simulated run that violates a binding product requirement stays
  `EVALUATED` with its measured objectives and a reason naming the
  failing entries; the Optimizer marks
  `product_requirements_satisfied = false`, `pareto_eligible = false`.
  Never UNSUPPORTED.
- Adversarial tests (all through the real adapter → Optimizer → v2):
  - `test_ap02_backend_unavailable_preserved_into_record`
  - `test_ap02_backend_failed_preserved_into_record`
    (synthetic crash injected into the certified meshdor runner)
  - `test_ap02_requirement_violation_stays_evaluated`
  - `test_ap02_unsupported_and_compile_failed_preserved_in_v2`
  Each asserts the record status, `pareto_eligible=false`, the typed
  reason, and the v2 row (`evaluation_status`, `compilation_status`,
  `evaluation_reason`); status/reason movement is bound into result_id
  (below).

## A-P1.3 — v2 definition lossless/identified

- v2 `definition` now emits `definition_id`,
  `objectives: [{metric, direction}]`,
  `constraints: [{metric, op, threshold}]`, `method`, `selection`,
  `budget`, `seed`, `domain`; the v1 string-only projection is isolated
  as `_definition_view_v1()` (LOSSY).
- The view top level exposes `optimization_result_id` (bare content
  digest, equal to `OptimizationResult.result_id()`).
- Schema pins the new shapes and enums (direction MIN/MAX, op <=/>=,
  method/selection closed sets); `contracts/srota/v2/README.md` updated.
- Adversarial tests:
  - `test_ap13_min_vs_max_definition_distinction`: MIN vs MAX produces
    different `definition` payloads, `definition_id`s and
    `optimization_result_id`s, and the view id equals the engine id.
  - `test_ap13_selection_policy_definition_distinction`:
    `min_first_objective` vs `lexicographic` produces different
    definition payloads/ids.

## A-P1.4 — status/reason carried in record, v2 and result_id

- `CandidateRecord.evaluation_reason` carries the evaluator message
  (null for a clean EVALUATED run; the binding-failure message for
  requirement-violating runs).
- v2 candidates expose `compilation_status`, `evaluation_status` and
  `evaluation_reason` (plus `eligibility_reason`), so Worker C can render
  backend-unavailable / failed / unsupported / compile-failed /
  requirement-violating rows without inferring anything from missing
  metrics.
- `result_id()` binds `evaluation_reason` alongside
  `compilation_status` and `evaluation_status`.
- Adversarial test `test_ap14_status_and_reason_bound_into_result_id`:
  changing `evaluation_reason`, `evaluation_status`, or
  `compilation_status` moves the result identity; clean rows expose
  `EVALUATED` / `COMPILED` / null reason.

## Verifier-named required tests (all present)

1. fake v2 Pareto refusal → `test_ap01_fake_v2_pareto_refusal_for_authority`
2. BACKEND_UNAVAILABLE preserved → `test_ap02_backend_unavailable_preserved_into_record`
3. FAILED preserved → `test_ap02_backend_failed_preserved_into_record`
4. requirement violation stays EVALUATED + not eligible → `test_ap02_requirement_violation_stays_evaluated`
5. MIN vs MAX v2 distinction → `test_ap13_min_vs_max_definition_distinction`
6. selection-policy distinction → `test_ap13_selection_policy_definition_distinction`
7. status/reason bound into result_id → `test_ap14_status_and_reason_bound_into_result_id`

Plus `test_ap02_unsupported_and_compile_failed_preserved_in_v2` for the
remaining taxonomy arms. All prior adversarial tests (A8 suite) still
pass with the new semantics (fake studies now assert ineligibility; the
Pareto/selection mechanics are covered through explicit certified test
doubles, never by relabeling the fake as authoritative).

## Evidence

Focused suite (from `tracks/t3-topology/dse`):

```
python3 -m pytest tests/test_p2_optimization_truth.py \
  tests/test_p2_guided_optimization.py tests/test_p2_real_adapter.py \
  tests/test_p1_optimize_booksim.py tests/test_p1_requirements_provenance.py \
  tests/test_p1c_requirements.py tests/test_p1_product_vertical_slice.py \
  tests/test_p1_product_orchestration.py tests/test_p1_product_views.py \
  tests/test_p1b_fabric_evaluator.py -q --tb=no
→ 164 passed
```

Broad provisioned battery, same binary/host for baseline and tip:

```
python3 -m pytest tests -q --tb=no -p no:cacheprovider
```

| Run | SHA | result |
|---|---|---|
| Baseline | `0e761060` | 118 failed / 3838 passed / 40 skipped / 9 xfailed / 44 errors |
| Audited tip | `f4e4a58d` | 118 failed / 3866 passed / 40 skipped / 9 xfailed / 44 errors |
| Audit-v2 tip | `07377439` | 118 failed / 3874 passed / 40 skipped / 9 xfailed / 44 errors |

Node-set symdiff (FAILED + ERROR) vs `/tmp/rtA-base-nodes.json` and the
provisioned `/tmp/p1b-matrix/p1b-bin-nodes.json`:

```
vs base 0e761060        failed: new=0 resolved=0   errors: new=0 resolved=0
vs provisioned p1b-bin  failed: new=0 resolved=0   errors: new=0 resolved=0
```

+8 new passing tests over the audited tip (the repair's adversarial
cases), zero new FAILED/ERROR, zero resolved. No test deletions, no
skips/xfails added, no baseline files edited.

## Deviations / notes

1. **A-P0.1 changes the fake CLI study output by design**: `veritx
   optimize --evaluate fake` now emits empty Pareto and no selection
   with per-row `eligibility_reason`. The CLI test was updated to assert
   this; the real BookSim CLI path still selects.
2. **Certified test doubles**: the guided-optimization grid tests now use
   an explicit `_CertifiedEvaluator` test double (real FabricCompiler +
   analytic values + declared authority + contract-shaped report) so the
   Pareto/selection machinery keeps coverage without claiming the fake
   is authoritative. The authority is declared in test code only;
   production never fabricates it.
3. **Studio retarget unchanged and broader** (ledger note): Worker C
   must retarget `STUDY_SCHEMA_V2` to `contracts/srota/v2/` and
   regenerate `apps/studio/fixtures/optimization-study.json`; the v2
   payload gained authority/status/reason and the lossless definition.
4. `application/requirements.py` remains untouched beyond the canonical
   report identity (RT-11); its internal `assert ... is not None` guards
   are RT-2-owned and out of this repair's scope.
