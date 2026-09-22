# RT-final Worker B repair report — independent audit v2 (BLOCKED → repaired)

- **Worker:** B (product boundary and cross-artifact seam closure)
- **Worktree:** `/home/datavex/veritx-rtB`
- **Branch:** `rt-final/product-boundaries`
- **Audit-v2 tip:** `adc1cde2332cc9aa18a2c851e1787193e8064240`
- **Pushed:** `github` → `refs/heads/audit/rt-final-product-boundaries-v2`
  (remote ref verified identical to HEAD)
- **Base:** `0e761060`; audited pre-repair tip `bbd8ae79`
- **Binary:** `third_party/booksim2/src/booksim`, sha256
  `65d61d336fabfb6a4ea6e8fd47826f5e9a707834ef1450cbde11bd32defc7c11`
- **Python:** 3.14.4. Working tree clean; no merge performed.

## Repair commits (per repair)

| Repair | Commit | Subject | Files |
|---|---|---|---|
| B-P0.1 | `191da934` | re-derive the workload instead of trusting provenance | `fabric_evaluator.py`, `requirements.py`, P1B + RT test migrations |
| B-P0.2 | `2bae0058` | RequirementEvaluator takes only verified results | `fabric_evaluator.py`, `requirements.py`, fixtures, `cold_replay_p1_slice.py` |
| B-P1.3 | `742a73d9` | one requirement-scope authority (no mirrored rule) | `requirements.py`, `product_evaluator.py`, `test_rt_b3` |
| B-P1.4 | `adc1cde2` | narrow evaluator excepts to the documented taxonomy | `fabric_evaluator.py`, `test_rt_b4_seam_taxonomy.py` |

Each commit was staged with hunk-level precision; commits 1 and 2 were
additionally verified green in isolated worktrees (125 and 191 focused
tests respectively) before proceeding.

---

## B-P0.1 — provenance-as-authority was forgeable

**Confirmed.** `WorkloadGraph` identity deliberately excludes provenance,
so a foreign semantic graph carrying `provenance["design_hash"] = hash(A)`
has B's `workload_id()` and passed the old gate. A test proved the
acceptance before fixing.

**Fix.** The evaluator no longer asks the workload who its parent is. It
re-derives the authority:

```
expected = lower_compile_workload(compilation.request)
require supplied.workload_id == expected.graph.workload_id()
```

* `FabricEvaluator.evaluate` re-derives before any lowering/backend work
  and returns the expected `LoweredWorkload`; the traffic-class semantics
  that intentionally live outside `workload_id` are then asserted against
  the options class (`opts.traffic_class == expected.unified_traffic_class`;
  a multi-class lowering refuses). Relabeling to another fabric-declared
  class now refuses as `UNSUPPORTED` before spawn.
* `RequirementEvaluator` re-derives the same way for its
  `(request, workload)` pair; the provenance block is gone.
* A non-v3 compilation has no lowering authority and refuses
  (`INVALID_INTENT`) — fail closed.

**Mandatory adversarial test (verifier-named):** foreign semantic graph +
forged matching provenance refuses in both boundaries —
`test_rt_b2_fabric_transplant.py::test_forged_provenance_cannot_bind_a_foreign_graph`
and
`test_p1_requirements_provenance.py::test_foreign_graph_with_forged_provenance_refuses`;
the product boundary maps the refusal via
`test_rt_b3_product_taxonomy.py::test_fabric_identity_refusal_maps_to_product_invalid`.

**Consequential test changes.** The P1B evaluator fixtures now build v3
requests and use `lower_compile_workload(request).graph` as the workload
(the certified v2 bundles are paired with the v3 intent under test). The
old "missing provenance refuses" test was removed: a provenance-free copy
of the *exact* lowering is content-identical and is accepted — provenance
is metadata, content identity is authority. The traffic-class transplant
test was restructured: the canonical graph cannot see the class, so the
refusal is the options-class assertion against the re-derived sidecar.

## B-P0.2 — RequirementEvaluator trusted a naked PerformanceResult dict

**Fix.** New verified boundary in `requirements.py`:

```
raw persisted result -> verify_performance_result(result, workload=TemporalWorkload)
    -> reverify_result(...) -> VerifiedPerformanceResult -> RequirementEvaluator
```

* `RequirementEvaluator.evaluate` refuses a naked dict
  (`InvalidInput`: "a nonempty resource_id is not authentication") and
  re-runs `reverify_result` on every call, so even a hand-forged
  `VerifiedPerformanceResult` whose content was mutated after verification
  refuses (`EvidenceInvalid`).
* `FabricEvaluator` produces the wrapper at evaluation time through the
  same factory; hermetic fixtures, the clock-semantics fixtures and the
  cold replay construct it the same way. No legacy entry point was needed.
* The requirement-level binding checks
  (`_authenticated_latency_cycles`: duration without clock, non-integral
  cycle product) remain enforced directly as defense in depth; the tests
  now call the helper plus assert the verified boundary refuses the
  mutated document.

**Mandatory adversarial test (verifier-named):** mutating
`wave_d_chain.design_hash`, `wave_d_chain.workload_graph_id` or the
`makespan` summary with the stale `resource_id` untouched refuses at the
verified boundary —
`test_p1_requirements_provenance.py::TestVerifiedBoundaryRefuses::test_stale_resource_id_after_mutation_refuses`
(parametrized), plus `test_chain_without_workload_graph_id_refuses`,
`test_result_without_wave_d_chain_refuses` and
`test_naked_result_dict_is_not_authentication`.

## B-P1.3 — duplicated requirement-scope authority

**Fix.** One pure authority:
`requirements.validate_requirement_scopes(request)` computes the
intent-class registry and refuses (`InvalidInput`) any requirement scope
over absent traffic. The product pre-spawn gate and
`RequirementEvaluator` both call the identical function object; the
evaluator's inline copy was deleted.

**Mandatory adversarial test (verifier-named):**
`test_rt_b3_product_taxonomy.py::test_scope_rule_has_exactly_one_implementation`
asserts `product_evaluator.validate_requirement_scopes is
requirements.validate_requirement_scopes`, that the authority refuses, that
the product preflight refuses pre-backend with no run directory, and that
the refusal text occurs exactly once in production code.

## B-P1.4 — broad exception laundering removed

All six `except Exception` blocks in `fabric_evaluator.py` were narrowed
to the documented taxonomy:

| Seam | Caught | Maps to |
|---|---|---|
| projection (`prepare_*`) | `BookSimLoweringError`, `Refusal`, `BackendConfigError`, `BackendInputError`, `MeshDorMaterializationError` | UNSUPPORTED (lowering) / FAILED |
| shared realization | `QualificationError` | UNSUPPORTED |
| execution (`run_waved_*`) | `BookSimError`, `Refusal`, `BookSimLoweringError`, `BookSimRouteError`, `BackendMaterializationError`, `ProducerError` | FAILED |
| evidence authentication | `BackendEvidenceError`, `ArtifactError`, `OSError` | FAILED |
| network window bind | `TimeError`, `ArtifactError` | FAILED |
| performance construction | `ResultError`, `TimeError`, `ModelError`, `WorkloadError`, `SchedulerError`, `ImmutableError`, `ArtifactError`, `ControlPlaneError` | FAILED |

**Mandatory adversarial test (verifier-named):**
`test_rt_b4_seam_taxonomy.py` injects a `KeyError` in the projection seam
and an `AttributeError` in the execution seam and asserts both propagate;
a positive control asserts a documented `BookSimError` still maps to
FAILED; a source audit pins zero `except Exception` and zero bare
`except` handlers in the module.

---

## Verification

**Focused (22 files, final HEAD):** 285 passed, 0 failed.

```
cd tracks/t3-topology/dse && python3 -m pytest \
  tests/test_rt_b1_identity_chain.py tests/test_rt_b2_fabric_transplant.py \
  tests/test_rt_b3_product_taxonomy.py tests/test_rt_b4_seam_taxonomy.py \
  tests/test_rt_b5_o_invariants.py tests/test_p1_product_orchestration.py \
  tests/test_p1_product_views.py tests/test_p1_requirements_provenance.py \
  tests/test_p1_clock_semantics.py tests/test_p1_product_vertical_slice.py \
  tests/test_p1b_fabric_evaluator.py tests/test_p1b_meshdor_profile.py \
  tests/test_p1b_meshdor_gates.py tests/test_p1c_intent_lowering.py \
  tests/test_p1c_eval_bridge.py tests/test_p1c_requirements.py \
  tests/test_p1c_v3_compile.py tests/test_p1c_v3_schema.py \
  tests/test_p1b_certificate_provenance.py tests/test_p2_real_adapter.py \
  tests/test_p2_guided_optimization.py tests/test_p1_optimize_booksim.py \
  -q -p no:cacheprovider
# 285 passed in 11.26s
```

**Intermediate commit trees** (isolated `git worktree` + `BOOKSIM_BIN`):
commit `191da934` → 125 passed; commit `2bae0058` → 191 passed.

**Broad battery vs the provisioned `0e761060` baseline** (same worktree,
same binary, `/tmp/rtB-baseline.log` / `/tmp/rtB-baseline-nodes.json`):

```
baseline: 118 failed, 3838 passed, 40 skipped, 9 xfailed, 44 errors
final:    117 failed, 3874 passed, 40 skipped, 9 xfailed, 44 errors
          (/tmp/rtB2-final2.log, /tmp/rtB2-final-nodes.json)
```

- **NEW FAILED: 0. NEW ERRORS: 0.**
- Resolved (1, not claimed): the pre-existing supervision-timing flake
  `tests/test_process_supervision.py::TestCancellation::test_ctrl_c_kills_child_and_propagates`
  (untouched by this work; also resolved in the RT-2 battery).
- +36 passed vs baseline = the 25 tests added in the original B wave, the
  10 tests added/changed by this repair (`test_rt_b4` 4,
  one-implementation 1, stale-ID parametrized 3, plus the provenance/B2
  restructure), and the resolved flake.

No test files deleted, no new ignores, no xfail/skip. `tracks/t3-topology/
workloads/` battery residue removed; clean tree at the tip.

## Residual risks / disclosures

1. **FabricEvaluator is now v3-only.** A v2 compilation has no intent
   lowering authority and refuses (`INVALID_INTENT`). Production callers
   (`product_evaluator`, `real_evaluator`) are v3-only, so no production
   behaviour changes; the P1B hermetic fixtures were migrated to v3
   requests paired with their certified v2 bundles. Any future v2 caller
   must migrate explicitly.
2. **`VerifiedPerformanceResult` is a dict subclass**, so callers can
   construct one; the evaluator re-runs `reverify_result` on every call
   against the carried `temporal_workload`, so a forged wrapper cannot
   bypass verification. The wrapper is the transport, `reverify_result`
   is the authority.
3. **Cost:** the verified boundary re-runs the deterministic scheduler per
   requirement evaluation (single network-window workload, CPU-only,
   negligible). FabricEvaluator also re-lowers the request per evaluation;
   also CPU-only and small.
4. **Cross-ownership note:** `requirements.py` carries the B-P0.2/B-P1.3
   additions (new function/class plus evaluator call sites). Worker A's
   report-identity work is in different regions (`report_identity`,
   `__all__`); the merge should be conflict-free but is flagged for the
   coordinator.
5. **Defense-in-depth checks shadowed:** the requirement-level
   `(duration, clock)` binding refusals are now unreachable through the
   verified boundary for mutated documents (reverify catches them first);
   they stay enforced directly and are unit-tested via the helper.
6. **Studio fixtures** remain one chain field behind from the prior wave;
   Worker C regenerates them at ENGINE_CLOSURE_SHA per the campaign plan.
7. The original B-wave broad-except audit note is closed: no
   `except Exception` remains in `fabric_evaluator.py`.
