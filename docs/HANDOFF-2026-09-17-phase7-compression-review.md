# HANDOFF — Phase 7: semantic-compression architecture review

**Date:** 2026-09-17 · **Branch:** `epic/booksim-forward-port` @ PR7 `2ed6b623`
**Prior gate:** Phase 6 (1048 passed, 1 skipped)
**Next permitted:** Phase 8 (ComparisonSpec enforcement)

## Scope

The three trustworthy paths named by the program (§11) at review time:

```text
standalone BookSim        core/experiment.py          (Slice A)
serving → BookSim         core/experiment_serving.py  (Slice B)
serving → analytical      core/experiment_serving.py  (Slice B, backend data)
```

PR7 already made serving→BookSim and serving→analytical **one runner**
(`network_backend` as data; engine identity + fabric gate dispatched by
backend). The remaining comparison was therefore Slice A vs Slice B plus
their shared substrate.

## Duplication census (evidence, not vibes)

### Extracted (2 real instances, identical mechanics — §11 deletion test)

1. **Plan persistence** — `atomic_write(plan.json) + PLANNED + RUNNING`,
   byte-identical in both slices. Formatting + transition order is the
   run-lifecycle contract; a third path was the drift point. →
   **`Run.record_plan(plan)`** (owns plan-file layout, `PLANNED` note
   `N task(s)`, then `RUNNING`). Slice-owned remainder: the `VALIDATED`
   transition with slice-specific evidence (state machine correctly
   refuses `CREATED → PLANNED` — caught by the new test, kept that way).
2. **Rejection-evidence closure** — `add_result("validate", {error}) +
   CANCELLED`, identical in both. → **`Run.cancel(reason)`** (mutation);
   slices keep a 3-line `_cancel(reason) -> Run` wrapper because their
   call sites `return _cancel(...)` (caught by test as `NoneType` —
   return contract preserved at the slice layer).

### Deliberately left concrete (do NOT unify — semantics differ)

- Validation: trace-shape checks (A) vs preflight refusal (B). Different
  inputs, different evidence.
- Execution: BookSim runner loop per seed (A) vs supervised LLMServingSim
  process + CSV + ledger (B). Different process models.
- Verdicts: parse-stats vs retirement/fabric/tripwire/metrics. Different
  terminal truths by design.
- KeyboardInterrupt arms: 2 lines each, differently noted — cheaper
  concrete than abstracted.
- Failure classification / artifact writing already single-implementation
  via `supervised_run`, `binary_identity`, `atomic_write`, `errors.py` —
  nothing to do.

No `BackendFactory`/registry/inheritance tree was built (§2.4). The
backend dispatch that does exist (fabric gate, engine identity, mode/
fidelity tables) is closed data tables + one `if`, not a framework.

## Final control-plane boundaries (documentation deliverable)

```text
core/spec.py             scientific intent boundary (strict, hashed)
core/runs.py             immutable run dir + lifecycle + shared slice
                         mechanics (record_plan, cancel)
core/experiment.py       Slice A: standalone BookSim. run_experiment
core/experiment_serving.py
                         Slice B: serving (booksim|analytical backend
                         data). run_serving_experiment
core/serving.py          preflight + execution identity + wire-arg
                         assembly (cmd_serve and Slice B both delegate)
simulation/booksim.py    BookSim runner (Slice A's process seam)
core/process.py          supervised_run (Slice B's process seam)
```

Rule going forward: a new execution path starts as a concrete slice
function; it may call Run's shared mechanics; it earns extraction only
at the second/third identical instance (§2.4, §11).

## Incidents during the phase (self-inflicted, caught by tests)

- `_cancel = run.cancel` shortcut dropped the `-> Run` return contract
  (`NoneType.state` in 6 tests). Fixed: `Run.cancel` is a mutation;
  slices wrap + return.
- Import cleanup removed `re`/`sys` still used by Slice A (`NameError`).
  Restored; lesson: run the slice tests before declaring green.

## Gate

```text
suite: 1050 passed, 1 skipped  (481 s; +2 lifecycle tests)
lint:  make -C tracks/t3-topology lint  PASS
files: core/runs.py, core/experiment.py, core/experiment_serving.py,
       tests/test_run_core.py
```

## Residuals

- KeyboardInterrupt arms remain per-slice (2 lines each) — fine.
- `REPO / "docs"` is the handoff home; PRD-CHECKLIST §17 rows remain
  stale relative to PR6/PR7 reality (fidelity vocabulary supersedes
  §17.4/§17.5 wording) — a docs-consolidation task, not a gate item.
- Next phase owns: ComparisonSpec enforcement (§12 of the program):
  turn `pipeline.py`'s comparison warning into a gate keyed on
  workload hash, nodes, packetization, routing identity, VC config,
  simulator/fidelity, seed policy.

## Verdict

Phase 7 gate: **PASS**. Next permitted: Phase 8 (ComparisonSpec
enforcement), per §28 order.
