# HANDOFF — Phase 13: Requirements-driven Fabric Compiler

**Date:** 2026-09-18 · **Branch:** `epic/booksim-forward-port` @ `bf53d934`
**Prior gate:** Phase-13 precursor (`ad992a26`) + cross-session review package
(`docs/HANDOFF-2026-09-18-cross-session-review.md`)
**Next permitted:** review, then the memory-semantics track proposed in
`docs/MEMORY-BACKEND-PROPOSAL.md` (other agent) or Phase 14 — **STOP here
until this phase is reviewed.**

## What landed

E2 requirements (PRD E2: `Requirement(qos_class, latency_ceiling_cycles,
bandwidth_floor_gbps, binding)`) were data consumed only by F8's bound
mapping. No synthesis path read them. Phase 13 makes them **actively gate
synthesis** per plan §17.

### New: `veritx_dse/synthesis/compiler.py`

`CompilerRequest` + `compile_fabric(request, evaluate)`:

- **Verdicts.** `FEASIBLE` (≥1 candidate met all constraints; Pareto evidence
  over the feasible set) or `NO_FEASIBLE_DESIGN` (violated-constraint evidence
  + relaxation information). Incoherent requests raise
  `InvalidCompilerRequest` *before any evaluation*.
- **Hard vs soft.** `binding=True` → hard constraint (must hold or the
  candidate is infeasible). Non-binding → recorded under
  `request.soft_requirements`, never enforced silently.
- **Fail-closed semantics (the load-bearing choices):**
  - **Bandwidth floors are `CONSTRAINT_UNMEASURABLE`.** The stack has no
    measured GB/s producer (precursor work gave us flits/latency, not
    bandwidth). Enforcing against an invented number would fabricate
    science; an unmeasurable constraint therefore fails closed — and this
    became the live argument for the other agent's memory-backend proposal.
  - **No derived `dropped`-style identities.** Constraint verdicts are made
    only against measured latency; `margin`/`excess` are computed, never
    fed back as verdicts.
  - **Failed evaluations stay visible** (`EVALUATION_FAILED` with the
    evaluator's error); evaluator exceptions are captured as evidence, not
    crashes. **Pruned candidates** are carried (`PRUNED` +
    `pruning_reason`) and are never evaluated — invisible pruning is the
    failure mode this compiler exists to prevent.
  - **n=1 honesty.** `seed_policy` is recorded verbatim; with replication ≤1
    the verdict states `sampling_basis: single_sample_no_confidence_interval`.
- **Relaxation information is measured-only and never an action.**
  `minimal_ceiling_admitting_best` = the tightest ceiling that would admit
  the best *measured* candidate. Hard requirements are never silently
  relaxed; on infeasible the output says exactly what would have to change.
- **Pareto via the Phase-8 gate.** `pareto_with_scope` over the feasible set
  (`fidelity` carried; mixed-fidelity refusal inherited). Never
  re-implemented here — one Pareto implementation per concept.

### New: `veritx_dse/synthesis/bridge.py`

The one place that knows both dialects: `SynthResult` records → compiler
candidates (ok → evaluable carrying its full provenance; failed → `PRUNED`
with the prior error as reason). Re-evaluation is **spec-faithful**: the
candidate's original `(topology, extra, routing)` spec is what
`evaluator.evaluate_spec` receives — the bridge translates, never
re-interprets (the Phase-10 "hope we agree" lesson applied to synthesis).
Anynet `network_file` is resolved absolute before spawn — a relative path
from the results-file era would vanish against the evaluator's scratch cwd
(the AGENTS.md #7 trap, caught live in the first E2E run).

### CLI: `synthesize compile`

```
veritx synthesize compile --results <synth_results.json> --trace <trace> \
  --requirements '[{"qos_class":"latency_critical","latency_ceiling_cycles":5000,"binding":true}]' \
  [--seed N] [--max-evals N] [--out PATH]
```

- Requirements are parsed **before any file I/O**: an incoherent spec is
  deterministic and free to check, and must be reported even when files are
  also missing (fail-fast pattern, `cmd_serve` reference). Pinned by test.
- Both verdicts are *real outcomes*: evidence JSON is written and the
  command exits 0 with a `✓` verdict line. Only setup/environment errors
  (`invalid --requirements`, missing files, unevaluable candidates) `fail()`
  with nonzero exit. NO_FEASIBLE_DESIGN is a scientific result, not a crash.
- Evidence JSON contains the full request (hard/soft, seed policy, sampling
  basis), scope counts, every candidate record with per-constraint verdicts,
  violated-constraint evidence, relaxation information, and (when feasible)
  the Phase-8 Pareto block.

## Live evidence (real BookSim, `configs/anynet16.links` golden, `test_dynamic.trace`, seed 42)

| Declared requirement | Verdict | Key evidence |
|---|---|---|
| `latency_ceiling ≤ 100000.0` binding | **FEASIBLE** | latency 31.9944c; pareto front `[anynet16]` |
| `latency_ceiling ≤ 30.0` binding | **NO_FEASIBLE_DESIGN** | best_measured 31.9944c; relaxation: tightest admitting ceiling = **31.9944c** |
| `bandwidth_floor ≥ 10.0` binding | **NO_FEASIBLE_DESIGN** | candidate `CONSTRAINT_UNMEASURABLE` — never a silent pass |

The first E2E run also *caught a real bug*: relative `network_file` → exit
255 (scratch-cwd resolution), fixed in the bridge with an absolute-path
resolution + not-found refusal before spawn.

## Provenance note (parallel work)

The other agent's memory-backend proposal landed as
`docs/MEMORY-BACKEND-PROPOSAL.md` (Ramulator 2.1, MemoryArtifact, fidelity
tiers, proposed Phase 14–16 renumbering). Its first action — quarantining
the `--memory` M/D/1 correction — was committed standalone this session as
`d45cc04a` after full-suite verification. No merge conflicts: their track
touches memory semantics; Phase 13 touched only `synthesis/` + a new
subcommand in `cli.py`. **Coordination point:** if their proposed renumbering
lands, this phase's "next permitted" becomes Phase 14 (Canonical Memory
Semantics) rather than plan-§18 control-plane migration — reviewer's call.

## Tests

- `tests/test_fabric_compiler.py` (16): verdicts, per-constraint verdicts
  with measured values pinned, relaxation math, fail-closed unmeasurable,
  non-binding-not-enforced, invalid requests (no bound / non-positive /
  empty candidates / unknown QoS class), pruned-never-evaluated (spy on the
  evaluator), budget requested-vs-executed, exception→evidence, seed-policy
  honesty, mixed-fidelity refusal through the real Phase-8 gate, round-trip.
- `tests/test_fabric_compiler_cli.py` (7): registration contract, flags
  contract, bridge dialect translation (ok→evaluable, failed→PRUNED with
  reason, spec round-trip), preflight fail-fast order (incoherent
  requirements reported even when results file is also missing).

## Gate

- Full suite: **1267 passed, 1 skipped** (+58)
- `make -C tracks/t3-topology lint` PASS (1268 collected)
- WIP baseline commit `d45cc04a` verified green before Phase-13 work landed

## Known residuals (honest)

1. **Latency is the only measurable constraint.** Throughput, power, area,
   radix, link-length from plan §17 have no measured producers yet —
   declaring them binding today would either fail closed (bandwidth) or is
   unrepresentable (others raise unknown-kind at construction? no — they are
   representable as E2 fields but the compiler only evaluates latency
   ceilings; anything else binding+present is `CONSTRAINT_UNMEASURABLE` by
   the same rule). This is deliberate: constraint vocabulary grows only when
   a measured producer exists.
2. **Candidate sets come from results files**, not live search loops — BO/
   iterative search loops do not yet prune through the compiler's record
   shape. Wiring `bo_synthesizer`/`iterative_synthesizer` to emit
   compiler-shaped candidate streams is the natural Phase-14/15 follow-up.
3. **`--max-evals` is recorded, not enforced** — budget enforcement requires
   search-loop integration (residual 2).
4. **No credit-style capacity check on evaluation cost** — each candidate is
   one real BookSim run; large candidate sets are O(n) simulations.

## Gate checklist (plan §17)

```text
[x] verdicts FEASIBLE / NO_FEASIBLE_DESIGN with evidence
[x] hard constraints never silently relaxed (relaxation is information)
[x] per-candidate constraint verdicts + measured values preserved
[x] failed evaluations remain visible
[x] pruned candidates remain visible with reasons
[x] candidate identity/generation/seed/fidelity preserved in records
[x] Pareto evidence scoped via Phase-8 machinery
[x] sampling basis stated (n=1 honesty)
[x] invalid requests fail closed before evaluation
[x] full suite passes; lint passes
```
