# Wave F seal report (candidate)

Status: **complete, seal pending user review** (branch
`wave-f/design-optimization`, from Wave-E seal `d878cf5e`).

```
branch      wave-f/design-optimization
base        Wave-E seal d878cf5ec6d9797083a7968baac58f2f7cf54ea7
contract    docs/WAVE-F-SCIENTIFIC-CONTRACT.md (14 sections)
package     veritx_dse/optimization/ (definition, space, metrics,
            constraints, pareto, result, orchestrator, __init__)
entry       SrotaControlPlane.optimize() / .inspect_optimization()
resources   optimizationdef, optimizationresult
tests       tests/test_optimization_core.py   63 pure unit (oracles)
            tests/test_optimization_e2e.py   24 real-BookSim E2E + adversarial
```

## 1. What was built

One orchestration layer above the sealed control plane. Candidates are
enumerated by a canonicalized finite design space, resolved through the
sealed intent system, evaluated through `SrotaControlPlane.evaluate()`
(reuse included), and every persisted summary is re-derived on load by a
full verifier. The optimizer never launches a backend and never invents a
metric.

## 2. Findings fixed during the wave (all reproduced before fixing)

| # | Finding | Fix |
|---|---|---|
| 1 | **§75 from within:** `NOT_EVALUATED` sat in `TERMINAL_EVALUATION_STATUSES`, so the verifier's own `derive_search_complete()` returned `True` for budgeted runs — the forged-completeness claim committed by production. | removed from the terminal set; tail-agreement check added (NOT_EVALUATED must equal the canonical prefix cut). |
| 2 | **Verifier/builder metric-scope mismatch:** verifier re-extracted objectives for ALL valid candidates (including the budget tail and failures) with BASE templates, while the builder extracted SUCCEEDED candidates with PATCHED templates. Structural metrics would silently disagree the day a parameter changes channel count. | one shared `patched_scenario_template` helper (definition.py); builder and verifier extract the same set with the same templates. |
| 3 | **Scenario-free structural metrics never saw the candidate patch:** `templates.get(spec.scenario)` with `spec.scenario=None` looked up the None key, so `fabric.channel_count` came back UNMEASURABLE for every candidate. | `_pick_scenario_free` returns (scenario, result); the template of the picked scenario is used. |
| 4 | **Zero-constraint vacuous feasibility:** `docs and len(docs)==n` made an empty `docs` list fail the feasible check, so with zero declared constraints no candidate could ever be feasible → `CONSTRAINT_UNMEASURABLE` on every constraintless run. | feasible = SUCCEEDED and every declared constraint satisfied; vacuously true at zero constraints (§48). |
| 5 | **§10 signature swallowed workload semantics:** the hardware projection copied every non-`workload` template key, including the `wave_e` block that carries the PHASE — decode/prefill scenarios of the SAME fabric refused as `INVALID` ("hardware signature differs"). | hardware-only projection: HARDWARE parameter values + `fabric_preset` + `fabric_overrides`; wave_d/wave_e/trace/mapping excluded. |
| 6 | **`comparable_count` fed the wrong quantity:** `frontier_is_complete` received `len(front)` (an output) instead of the comparison's comparable input count — any dominated candidate made `frontier_complete=False`. | both call sites pass the scoped report's `comparable_count`. |
| 7 | **Round-trip closure:** `identity_dict()` renders bounds as `{numerator, denominator}` docs but `_exact()` rejected that form — a persisted definition failed its own re-validation. | `_exact()` accepts the canonical doc form (via `frac_from_doc`). |
| 8 | **Missing import:** `inspect_optimization` referenced `load_verified_optimization_result` without importing it (NameError on first use). | local import at the use site. |

## 3. Probes that shaped the design (§124 honesty checks)

- **mesh vs torus at 2×2 is a genuine exact tie**: at k=2 the wraparound
  links coincide with the boundary links, so both families lower to
  identical anynet graphs. The plumbing is real; the honest E2E reports
  the tie (`tied: true`, both width=128 candidates selected — §58) and
  uses `fabric.link_width` (64→128 bits halves the network window) as the
  differentiating dimension.
- **`topo_size()`'s torus formula disagrees with the lowered graph** at
  k=2 (8 links vs 4 channels). Structural metrics therefore read
  `router_count` / `channel_count` / `endpoint_count` off the Wave-B
  compilation chain — the same derivation the backend consumes (§35).

## 4. Verification

```
optimization_core   54 passed   (independent oracles: Pareto brute-force,
                                constraints truth table, space enumeration,
                                selection, verdicts, permutation invariance)
optimization_e2e    24 passed   (real BookSim, WAVE_F_E2E=1)
  demonstrations    exhaustive single-objective, multi-objective no-implicit-
                    winner, two-scenario frontier, budgeted scope with visible
                    tail, NO_FEASIBLE_DESIGN (complete + conclusive),
                    CONSTRAINT_UNMEASURABLE, fidelity warning propagation,
                    verified inspect navigation, zero-new-evidence reuse
  adversarial       §72 candidate transplant, §73 scenario transplant,
                    §74 omission, §75 forged completeness, §76 forged
                    NO_FEASIBLE, §77 Pareto tamper, §78 winner tamper,
                    §79 in-place definition rewrite, §80 constraint-bound
                    identity, §81 budget identity, §82 domain dedupe,
                    §83/§84 permutation invariance, §136 forged verdict,
                    §137 winner without policy — every forgery refused with
                    a SPECIFIC re-derivation failure
full dse battery    baseline(seal) 26 failed / 3210 passed / 41 skipped
                    wavef         27 failed / 3204 passed / 65 skipped
                    diff vs seal: +1 failure ONLY (see §5)
```

## 4b. Post-commit capability audit (same day)

An audit of the commit against the full §-checklist found the seal
preserved but the wave not yet complete; the following were closed in a
second commit:

| # | Gap | Closure |
|---|---|---|
| 1 | **§25 violation:** `n_reused` was tallied in the orchestrator but never persisted — the budget block did not report evaluations reused. | `scenario_reused` rides on each candidate record; `scenario_evaluations_reused` is a derived budget field the verifier recomputes from accounting (§62); E2E asserts the rerun reuses all 4 scenario evaluations. |
| 2 | **§18/§19/§27/§53 untested:** ALIAS dedupe and resolve-before-execute INVALID had production code but zero coverage. | `TestCandidateAccounting`: distinct assignments stay VALID (no false dedupe), §82 canonical domain dedupe, unresolvable template → every assignment INVALID with reasons (→ `NO_VALID_CANDIDATES`), §10 hardware-signature mismatch refuses multi-scenario candidates by name. |
| 3 | **§30 classification untested.** | `TestFailureClassification` pins the sealed `study_status_for_error` mapping (TIMEOUT→TIMED_OUT, unsupported family→UNSUPPORTED, else FAILED) and the orchestrator's use of it. |
| 4 | **§89 differential implicit.** | `TestExhaustiveBudgetDifferential`: budgeted plan IS the canonical prefix cut; terminal vs NOT_EVALUATED tails derive different `search_complete`; verdict vocabulary (existential FEASIBLE under budget vs complete-search-only NO_FEASIBLE_DESIGN vs INCONCLUSIVE). |

Pure battery now 63 tests; E2E 24.

## 4c. Environmental finding (not a Wave-F defect)

`test_pp_failclosed::test_effective_copy_matches_vendored_tree` began
failing mid-session: the user-site chakra install was refreshed at
14:12 from the **Gate V2.1 converter repair** (`d3e0117b`, present in a
parallel worktree, postdating the Wave-E seal). This tree's vendored
copy is seal-era, so the provenance gate refuses — working as designed.
Resolution is a base-management decision (forward-port d3e0117b into
the Wave-F base, or reinstall from this tree); either flips exactly one
tree's result, so it is not resolved unilaterally here.

## 5. The one battery delta is the seal posture, not a defect

`test_wave_e_product::test_reuse_keeps_wave_e_block` fails while the tree
carries uncommitted Wave-F work and passes on a clean tree. Root cause
(traced, not inferred): `_try_reuse` → `verify_reusable_evidence` raises
`ProducerError: producer source tree is dirty at d878cf5e…; refusing
evidence-grade reuse — commit or stash first`. The sealed producer
contract refuses evidence-grade reuse from a dirty tree; the control plane
then falls back to fresh execution and the test's `reused is True` fails.
This is the trust posture working as designed — it resolves the moment
the wave is committed. Post-commit re-verification on the clean tree is a
seal prerequisite.

## 6. Non-goals honored

No second control plane, no Bayesian search, no weighted sums, no fake
silicon (area/power/energy remain unregistered), no heuristic pruning, no
`wavef/` package (it is `veritx_dse/optimization/`), Wave-D/E semantics
untouched (two-file delta: `service.py` +87 lines, `store.py` +2 resource
kinds).
