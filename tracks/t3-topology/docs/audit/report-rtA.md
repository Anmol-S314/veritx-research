# RT-A closure report — optimization truth, provenance, contract v2, repeatability

- **Worker:** RT-A (`/tmp/task-rtA.md`)
- **Worktree:** `/home/datavex/veritx-rtA`
- **Branch:** `rt-final/optimization-truth`
- **Base:** `0e761060` (RT_MERGED_SHA)
- **Final HEAD:** `f4e4a58d` (`P1-RT.A8`)
- **Tree state at finish:** clean (`git status --short` empty; battery
  residue `tracks/t3-topology/workloads/` removed after the final run)
- **Binary:** `third_party/booksim2/src/booksim`, sha256
  `65d61d336fabfb6a4ea6e8fd47826f5e9a707834ef1450cbde11bd32defc7c11`
  (the required `sha65d61d3` build; already present)
- **apps/studio:** untouched (`git diff --name-only 0e761060..HEAD` has
  zero `apps/studio` paths); Studio coordination is in the ledger note.

## Commits (one per item, on top of `0e761060`)

| Item | Commit | Subject |
|---|---|---|
| A1 | `bae80b40` | carry canonical RequirementReport identity into evaluations and records |
| A2 | `a01fa3a3` | separate product RequirementReport and optimization constraints |
| A3 | `6d04fe91` | every objective has an explicit MEASURED/UNMEASURABLE state |
| A4 | `6c953c77` | refuse duplicate constraint/objective identity (no last-write-wins) |
| A5 | `24a72573` | authoritative contract v2 in `contracts/srota/v2`, separated view |
| A6 | `f379de5c` | per-evaluation evidence slots for the real adapter |
| A8 | `f4e4a58d` | mandatory adversarial optimization-truth suite (14 cases) |

A7 required no code change: RT-3's collision-free run-root construction
is proven unchanged by the frozen-second CLI test (below) and was
re-verified after A6.

---

## A1 — requirement-report identity carried transitively

- `CandidateEvaluation` gains `requirement_report_id` (bare
  `report_identity`); `RealCandidateEvaluator` fills it for both the
  EVALUATED outcome and the binding-refused outcome, and always alongside
  the carried report and `performance_result_id`.
- The Optimizer **re-derives** the identity from the carried report and
  refuses (typed `OptimizationResultError`, never an assert) when:
  the carried id differs from the re-derived digest; the report's
  `design_hash` is not this candidate's; the report's top-level or any
  entry's `performance_result_id` is not this evaluation's; the report is
  not a mapping or carries no `entries` list.
- `OptimizationResult.result_id()` binds `requirement_report_id`,
  `product_requirements_satisfied`, product entry details, constraint
  details and objective availability/details, so a transplanted or
  altered report either refuses outright or moves the bound result
  identity.
- `report_identity` (RT-11, `application/requirements.py`) hashes the
  whole report via `content_id` → canonical JSON; no repr/object
  identity. `test_4` now proves every bound field moves identity:
  top-level `design_hash`/`performance_result_id`, and per-entry
  `requirement_index`, `traffic_class`, `qos_class`, `verdict`,
  `binding`, `required`, `measured`, `metric_authority`, entry
  `performance_result_id`, `reason`.
- Eligibility gate: a candidate is never optimization-eligible on backend
  success alone — `report_passes()` must hold when a report exists
  (`TestProductRequirementAuthority`).

## A2 — separate authorities

- No optimizer structure is named "requirements" any more:
  `CandidateRecord` now carries `requirement_report_id` /
  `product_requirements_satisfied` / `product_requirement_details`
  (product authority) separately from `constraint_verdicts` /
  `constraint_details` / `constraints_satisfied` (optimization
  authority) and `objective_values` / `objective_availability` /
  `objective_details` (measurement authority).
- Engine constraint verdicts are now tri-state strings
  (`SATISFIED|VIOLATED|UNMEASURABLE`), matching the authoritative v2
  contract; the v1 boolean projector is explicitly named
  `_to_study_view_v1()` and documented as LOSSY (never claims to
  preserve three-state semantics).
- `test_6` proves one record can simultaneously say "product requirements
  satisfied, study constraint violated" and vice versa, and that either
  failure makes `pareto_eligible` false.

## A3 — RT-10 completeness (objective states)

- Every requested objective gets `objective_availability[metric] ∈
  {MEASURED, UNMEASURABLE}` (plus any extra measured metric as MEASURED).
- Missing, `NaN`, ±inf, bool, string and `None` objective values are
  UNMEASURABLE with a typed reason; they are never 0, infinity, a backend
  failure, SATISFIED, or Pareto input. Constraint evaluation runs over the
  sanitized finite map, so a malformed value yields a verdict, never a
  crash.
- Pareto input is exactly: evaluation succeeded AND product binding
  requirements pass AND every requested objective measured+finite AND
  every hard constraint SATISFIED (`pareto_eligible`). `pareto.py` only
  receives complete candidates; `_select` re-checks completeness and
  refuses explicitly (python `-O` safe).

## A4 — duplicate constraint/objective identity

- Chosen design: **(B) refuse at construction** — one metric, one
  verdict slot. `OptimizationDefinition` refuses duplicate objective
  metrics and duplicate constraint metrics with typed errors naming the
  metrics; `constraints.evaluate_all()` additionally refuses a duplicate
  metric instead of silently overwriting the earlier verdict.
- `latency<=100` + `latency>=50` therefore cannot be expressed and cannot
  silently overwrite; the refusal is explicit at both seams.

## A5 — contract v2 at the right path

- The one authoritative v2 study view is
  `contracts/srota/v2/optimization.study.view.schema.json`
  (`$id` .../srota/v2/...); `contracts/srota/v1/optimization.study.view.v2.schema.json`
  no longer exists. `contracts/srota/v1/optimization.study.view.schema.json`
  stays frozen and is the only v1 study view.
- v2 candidates expose: `evaluation_ids {design_hash,
  performance_result_id, requirement_report_id}`,
  `product_requirements {satisfied, verdicts}`,
  `objective_values`, `objective_availability`
  (`MEASURED|UNMEASURABLE`), `constraint_verdicts`
  (`SATISFIED|VIOLATED|UNMEASURABLE`), `pareto_eligible`, `pareto_member`,
  plus patch/locked consequences. Schema-level `if/then` pins
  `pareto_member → pareto_eligible`.
- Both CLI study validators select `contracts/srota/{v1,v2}` by the
  emitted `contract_version` (the RT-3 validator path note is in the
  integration ledger).
- `contracts/srota/v2/README.md` documents the authority separation and
  the lossy v1 projector.

## A6 — evidence-slot reuse collisions

- `RealCandidateEvaluator` now stores each evaluation under
  `run_root/<candidate_id>/eval-<mkdtemp>/` (OS-atomic
  `tempfile.mkdtemp()`), so the same evaluator instance can evaluate the
  same candidate repeatedly without overwriting a prior evidence slot.
  The candidate directory is transport; no timestamp/PID/random token
  feeds any scientific identity.
- Two evaluations both complete, candidate/design identity is stable,
  measured objectives and report verdicts agree, and the two eval slots
  and their evidence are distinct (`test_11`, real-adapter
  `test_same_evaluator_same_candidate_twice_allocates_distinct_slots`).
  The bound `performance_result_id` legitimately differs between slots
  because the persisted evidence embeds its run path (the documented
  RT-3 property); the measured science does not.

## A7 — CLI same-root repeatability (verification)

- `test_p1_optimize_booksim.py::test_booksim_study_is_real_and_repeatable`
  freezes wall time and runs two `cmd_optimize --evaluate booksim`
  invocations against the SAME explicit `--run-root` in the SAME second:
  both succeed, two per-invocation roots exist (same second+pid prefix,
  distinct counter suffix), candidate ids stable, evidence digests
  distinct. It passes after A6 unchanged.
- `test_12` adds the no-sleep variant (same explicit root, immediate
  repeat, no clock patch).

## A8 — mandatory adversarial suite

`tests/test_p2_optimization_truth.py` — one test per mandated case:

1. real evaluator + missing objective → UNMEASURABLE/ineligible, no KeyError
2. missing-objective candidate never Pareto (empty front, no selection)
3. report identity carried into `CandidateRecord`; result id moves with it
4. changing verdict/authority (and every other bound field) moves report identity
5. transplanted report refuses; forged carried identity refuses
6. product requirements vs optimization constraints stay separate
7. VIOLATED survives the v2 study view (v1 collapses, explicitly)
8. UNMEASURABLE survives the v2 study view (v1 collapses, explicitly)
9. duplicate same-metric constraints refuse at construction and in `evaluate_all`
10. duplicate objective declaration refuses
11. same evaluator object, same candidate, twice (distinct slots)
12. same CLI run root twice immediately, no sleep
13. repeated runs preserve candidate/design identity
14. repeated runs allocate distinct evidence slots (digests differ)

---

## Evidence

Focused suite (from `tracks/t3-topology/dse`):

```
python3 -m pytest tests/test_p2_optimization_truth.py \
  tests/test_p2_guided_optimization.py tests/test_p2_real_adapter.py \
  tests/test_p1_optimize_booksim.py tests/test_p1_requirements_provenance.py \
  tests/test_p1c_requirements.py tests/test_p1_product_vertical_slice.py \
  tests/test_p1_product_orchestration.py tests/test_p1_product_views.py \
  tests/test_p1b_fabric_evaluator.py -q --tb=no
→ 156 passed
```

Production-gate hardening: `grep -n "assert " veritx_dse/optimization/*.py`
→ none (the two bundle invariants are now typed `EvaluationError`s), and
the optimizer identity/transplant gates were exercised under
`python3 -O` (forged candidate and transplanted evaluation both refused).

Broad provisioned battery, same binary and same host for baseline and
final:

```
python3 -m pytest tests -q --tb=no -p no:cacheprovider
```

| Run | SHA | result |
|---|---|---|
| Baseline (captured this worktree) | `0e761060` | 118 failed / 3838 passed / 40 skipped / 9 xfailed / 44 errors |
| Final | `f4e4a58d` | 118 failed / 3866 passed / 40 skipped / 9 xfailed / 44 errors |

Node-set symdiff (FAILED + ERROR), `/tmp/rtA-base-nodes.json` and the
provisioned `/tmp/p1b-matrix/p1b-bin-nodes.json`:

```
vs base 0e761060        failed: new=0 resolved=0   errors: new=0 resolved=0
vs provisioned p1b-bin  failed: new=0 resolved=0   errors: new=0 resolved=0
```

+28 new passing tests (3 A1 + 7 A3 + 3 A4 + 1 A6 + 14 A8), zero new
FAILED/ERROR, zero previously failing node resolved. No test files were
deleted, no skips/xfails added, no baseline files edited.

## Deviations / notes

1. **A4 option B chosen** (refuse at construction) over per-constraint
   identity. Consequence: a two-sided bound on one metric
   (`latency<=X` + `latency>=Y`) is intentionally inexpressible; the
   refusal names the metric. Both plan-gate-14 alternatives are allowed;
   refusal was chosen for the metric-keyed verdict contract (one slot per
   metric) and fail-closed simplicity.
2. **Studio retarget is Worker C's.** Removing the v1-dir v2-named schema
   is deliberate (one authority). `apps/studio/scripts/validate_fixtures.py`
   still references the removed path; the ledger note in
   `docs/P1-INTEGRATION-LEDGER.md` instructs Worker C to retarget it to
   `contracts/srota/v2/` and regenerate
   `apps/studio/fixtures/optimization-study.json` (v2 gains the separated
   authority fields). apps/studio was not edited here.
3. **CLI edits beyond schema selection:** the two `cmd_optimize`
   constraint-verdict displays now map the tri-state strings to
   `PASS/FAIL/?` (the engine values are no longer bools). No scientific
   identity or evaluation semantics changed in the CLI.
4. **A6 "identities equal"** means candidate/design identity and measured
   metrics; the bound `performance_result_id` differs between evaluation
   slots because the persisted evidence artifact embeds its run path
   (documented RT-3 behavior, and the same property the CLI repeatability
   test asserts across invocations).
5. **Out of scope:** `application/requirements.py` keeps RT-2's internal
   `assert ceiling is not None` / `assert floor is not None` guards in the
   latency/bandwidth evaluators — the task allowed only the canonical
   report-identity addition there, and every call site is guarded by an
   explicit `is not None` check in the same function. No other
   optimization-seal gate uses `assert`.
