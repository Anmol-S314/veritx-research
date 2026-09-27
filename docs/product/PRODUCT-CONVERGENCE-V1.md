# PRODUCT-CONVERGENCE-V1 — convergence ledger

Branch: `product/convergence-v1`
Base: `origin/rebuild/live-product-flow @ 2e51311d`
Worktree: `/home/datavex/veritx-product-convergence`

This ledger records what the original convergence brief asked for, what the
three predecessor commits **already satisfy**, and what is genuinely left.
Requirements are classified as:

| class | meaning |
|---|---|
| `ALREADY_PRESENT — VERIFY` | the behaviour exists; the work is to prove it, not to build it |
| `EXTEND` | a predecessor commit established the authority; acceptance criteria are still unmet |
| `FIX` | a confirmed defect |
| `NEW` | nothing exists yet |
| `DEFER` | out of scope for this slice, with a reason |

**Do not reimplement a predecessor commit because the brief was written
against the older GitHub head.** The brief's base (`b9e4de0d`) is the PARENT
of the three commits below; it does not contain them.

---

## Predecessor commits carried by this base

| SHA | Subject | Authority established |
|---|---|---|
| `c1f3d118` | `fix(product): split latest attempt from active revision` | `active_revision_id` vs `latest_attempt_revision_id`; `_revision_promotable()` — only a COMPILED revision with a PASS certificate may go active; a refused attempt is recorded but never displaces the last usable revision; `_ensure_revision_pointers()` backfills/repairs |
| `24f7813f` | `fix(product): refuse simulation honestly for unevaluable intents` | `_evaluation_support(revision) -> (bool, reason)` by attempting `lower_compile_workload`; `evaluation_supported` / `evaluation_note` on entries; `active_evaluation` on the project view; a submit gate raising `LOWERING_UNSUPPORTED`. Law: *"Compilation proves the fabric; only a successful intent lowering proves the workload can run on it."* |
| `2e51311d` | `feat(product): MoE declared-ops lowering, per-message classes, real capability reasons` | MoE declared-ops lowering; `LogicalMessageArtifactV3` per-message classes; real capability reasons; **the multi-class BookSim trace guard** in `render_trace` |

---

## Phase classification

| # | Brief requirement | Class | Evidence / notes |
|---|---|---|---|
| 1 | Every optimization option reaches `OptimizationDefinition` unchanged | **FIX** | `product/service.py:1039` `_parse_definition` returns `domain, objectives, constraints, method, selection, seed`. `product/service.py:1079` constructs `OptimizationDefinition(domain=…, objectives=…, constraints=…, method=…)` — **`selection`, `seed` and `budget` are dropped**. Backend has all three (`optimization/definition.py`: `budget`, `seed`, `selection`). |
| 1b | Expose `max_candidates` / `max_evaluations` | **NEW** | `_parse_definition` accepts no budget at all; `search.py:51` consumes `budget.get("max_candidates")` and `max_evaluations`. |
| 1c | Reject unsupported fields instead of dropping | **NEW** | no unknown-field check on the optimization body today. |
| 2 | Product capability API for Guided params | **NEW** | no such endpoint. Backend authority exists: `candidate.apply_patch` GUIDED keys, `definition.SEARCH_METHODS = ("grid","enumeration","random")`, `definition.SELECTION_POLICIES = ("min_first_objective","lexicographic","none")`. |
| 2b | Certified metrics derived from the real registry | **ALREADY_PRESENT — VERIFY** | `optimization/metric_registry.py`. Must be read, not restated. |
| 2c | LOCKED properties non-searchable | **ALREADY_PRESENT — VERIFY** | `candidate.apply_patch` accepts GUIDED keys only. |
| 3 | Rebuild the Optimize page as a decision workflow | **EXTEND** | `apps/studio/src/pages/optimize.tsx` + `components/OptimizeView.tsx` exist. |
| 4 | Result page leads with the decision, not hashes | **EXTEND** | depends on `24f7813f`'s `_evaluation_support` for "what VERITX did NOT measure". |
| 5 | Candidate comparison with human labels | **EXTEND** | candidate identity exists; human labelling does not. |
| 6 | LOCKED consequences rendered as consequences | **ALREADY_PRESENT — VERIFY** | canonical bundle views exist; must not be recomputed in React. |
| 7 | Selected candidate → Draft → explicit Compile → new revision | **EXTEND** | `c1f3d118` established revision immutability and promotability. What is missing is the Draft target and the `derived_from_optimization_id` / `derived_from_candidate_id` provenance. |
| 8 | Candidate evidence without pretending it is a Product Run | **ALREADY_PRESENT — VERIFY** | `product-run` vs `optimization-candidate` distinction is in the service model; the UX must not conflate them. |
| 9 | Study analysis incl. failed/unmeasurable counts | **EXTEND** | `24f7813f` supplies the unmeasurable axis; the study must surface the counts. |
| 10 | Single objective ⇒ "Measured ranking", never "Pareto" | **FIX** | UI rule; needs a pinned test. |
| 11 | CLI P0 defects A–G | **FIX** | see table below. |
| 12 | Documentation reset | **FIX** | path in the brief was wrong — see below. |
| — | **Hard gate:** optimisation/evaluation cannot collapse a multi-class workload to class 0 | **EXTEND** | The guard exists in `render_trace` and IS covered (`tests/test_workload_moe_lowering.py::test_v3_physical_projection_conserves_and_trace_refuses_classes`). Coverage does **not** yet reach the optimization/evaluation path. |

### Documentation path correction

The brief cited `docs/VERITX-CLI-AND-TUI-PLAN.md`. That path has never existed
in this repository. The file is at:

`tracks/t3-topology/dse/docs/VERITX-CLI-AND-TUI-PLAN.md`

### Phase 11 CLI defects — status to be confirmed per item

| item | defect | class |
|---|---|---|
| A | `veritx run` synthesizes `winner.anynet` but evaluates a freshly constructed mesh | FIX |
| B | `non-square nodes -> k=8` silent fallback | FIX |
| C | certification decided by `any("PASS" in stdout)` | FIX |
| D | `fail()` does not return non-zero | FIX |
| E | sweep reports `nodes=0` when the node count is known | FIX |
| F | failed/partial rows crash `results` | FIX |
| G | UVM requires an obsolete representation | FIX |

---

## Status board

| issue | evidence | fix | tests | status |
|---|---|---|---|---|
| P1 selection/seed/budget dropped | `product/service.py` `_run_optimization` constructed `OptimizationDefinition(domain, objectives, constraints, method)` only; `OptimizationStudyView._select` reads `definition.selection`, so `selection="none"` silently became `min_first_objective` | propagate `budget`, `seed`, `selection`; add `budget` to `OptimizeBodyV1` | `test_product_convergence_phase1.py` (12) | **DONE** |
| P1 budget not expressible | `_parse_definition` had no budget branch at all; backend `search.py` consumes `budget["max_candidates"]`/`["max_evaluations"]` | accept + validate `budget` object | same | **DONE** |
| P1 unknown options dropped | no unknown-key check; a misspelled option was ignored | `_OPTIMIZATION_KEYS` closed set; unknown ⇒ `INVALID_INTENT` naming the supported set | same | **DONE** |
| P1 requested definition not persisted | the optimization record stored only `study` + `candidate_runs`, so `method`/`selection`/`seed`/`budget` were unverifiable after the fact | persist `definition` (the normalized request) | same | **DONE** |
| P1 canonical domain order | — | `DomainParam` sorts values by canonical JSON, so `[32,64,128]` ⇒ `(128,32,64)`. Documented backend behaviour; **PHASE 3 must present canonical order, not declared order** | pinned in the same test | noted (no code change) |

### Environment note (not a code defect)

The fresh worktree has no built BookSim binary. Backend-dependent tests
(`test_p2_optimization_truth.py` and friends) fail with
`FileNotFoundError: BookSim binary not found`, and a symlink to the binary
from another worktree yields a provenance mismatch
(`BACKEND_UNAVAILABLE`). **Build `third_party/booksim2` in this worktree
before relying on backend-dependent results.** The PHASE 1 tests do not
require the binary.

---

## Verification rules for this slice

- Do not mark a capability implemented because the UI exists.
- Do not mark a result certified because an evaluator returned a number.
- Do not preserve bad behaviour for backwards compatibility unless a pinned
  consumer is proven.
- Every "supported" claim must resolve to a canonical backend authority.
