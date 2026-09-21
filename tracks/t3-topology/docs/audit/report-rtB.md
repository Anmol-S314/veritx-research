# RT-final Worker B report — product boundaries & cross-artifact seam closure

- **Worker:** B (product boundary and cross-artifact seam closure)
- **Worktree:** `/home/datavex/veritx-rtB`
- **Branch:** `rt-final/product-boundaries`
- **Base:** RT_MERGED_SHA `0e761060` (`integration/p1-product-rt-candidate`)
- **HEAD:** `bbd8ae79` (5 commits, one per item; not merged)
- **Binary:** `third_party/booksim2/src/booksim`, sha256
  `65d61d336fabfb6a4ea6e8fd47826f5e9a707834ef1450cbde11bd32defc7c11` —
  byte-identical to `/home/datavex/veritx-product-integration/...`
  (already present; no copy needed)
- **Python:** 3.14.4. Working tree clean after the battery
  (`tracks/t3-topology/workloads/` residue removed).

| Item | Commit | Subject | Files |
|---|---|---|---|
| B2 | `d04b4ea8` | FabricEvaluator refuses cross-design workload transplants | `fabric_evaluator.py`, 2 P1B fixtures, `test_rt_b2_fabric_transplant.py` |
| B1 | `599aeca1` | Wave-D chain binds the design identity (traffic-class transplant) | `fabric_evaluator.py`, `requirements.py`, 3 fixture files, `test_rt_b1_identity_chain.py` |
| B3 | `65a812e6` | evaluate_product maps the full documented refusal space | `product_evaluator.py`, `test_rt_b3_product_taxonomy.py` |
| B4 | `ed62fc4f` | design_view same-geometry cross-design refusal test | `test_p1_product_views.py` |
| B5/B6 | `bbd8ae79` | -O-safe evidence gate and optimization-mode proof | `fabric_evaluator.py`, `rt_identity_probe_o.py`, `test_rt_b5_o_invariants.py` |

---

## B1 — audit of the merged RT-2 closure (two provable binding gaps)

The audit walked the chain
`request.design_hash → LoweredWorkload.design_hash / graph provenance →
workload_id → physical_traffic_id → PerformanceResult.wave_d_chain →
performance_result_id → RequirementReport.design_hash /
performance_result_id` against the merged RT-2 code and proved each
link with tests (`tests/test_rt_b1_identity_chain.py`).

**Gap 1 (closed in B2): the Compilation→WorkloadGraph seam had no
design binding.** `FabricEvaluator.evaluate(compilation, workload)` only
checked types, compilation status/certificate and geometry. A canonical
`WorkloadGraph` is content-identified by `workload_id()`, which
deliberately excludes provenance, so `Compilation A + same-geometry
Workload B` was accepted and evaluated (backend work and a PerformanceResult
carrying A's `design_hash` with B's `workload_id`). Proven by test before
fixing.

**Gap 2 (closed in B1): traffic-class-only design differences share a
`workload_id`.** Traffic-class semantics live in the lowering sidecar
(`traffic_class_by_operation`), not in the canonical graph detail, so two
requests with identical TP/PP/EP/DP and identical collective payloads but
different `traffic_class` lower to byte-identical `workload_id()` values
while their `design_hash()` differs. RT-2's
`chain["workload_graph_id"] == workload.workload_id()` check therefore
accepted `RequirementEvaluator.evaluate(request_B, graph_B, perf_A)` for
that case, emitting B's `design_hash` over A's measurements. Proven by
executing the honest triple before fixing (accepted, `performance_result_id
== perf_a["resource_id"]`).

**Fix.** The evaluator records `design_hash` in the PerformanceResult
Wave-D chain, and `RequirementEvaluator` requires the chain to name this
request's design: missing binding → `EvidenceInvalid`; mismatch →
`MappingInvalid` naming both hashes. The check runs *after* the existing
workload-id check so every pre-existing refusal keeps its order and type.
Because the chain is inside `event_graph_id`, `reverify_result` already
authenticates the new field (tamper tests unchanged and green).

Links proven end to end on a REAL BookSim run
(`test_valid_matching_path_evaluates_with_full_chain`):
`lowered.design_hash == request.design_hash() == graph.provenance["design_hash"]
== outcome.design_hash == chain["design_hash"]`; `outcome.workload_id ==
graph.workload_id() == chain["workload_graph_id"]`;
`chain["message_artifact_id"] == outcome.message_artifact_id`;
`chain["physical_traffic_id"] == outcome.physical_traffic_id`;
`chain["resolved_fabric_hash"] == outcome.resolved_fabric_hash`;
`outcome.performance_result_id == performance_result["resource_id"] ==
report["performance_result_id"]`; `report["design_hash"] ==
"sha256:" + request.design_hash()`. Provenance is not content identity
(a provenance-free copy keeps the same `workload_id`), and missing
provenance/chain binding refuses (`EvidenceInvalid`).

## B2 — same-geometry transplant attacks

`tests/test_rt_b2_fabric_transplant.py` parametrizes three semantic
differences with real geometry equality asserted (same TP/PP/EP/DP, same
world size): collective payload, traffic class, ordered intent.

- `Compilation A + Workload B` → `ControlPlaneError` code
  `INVALID_INTENT` at `FabricEvaluator`, naming A's design hash, B's
  design hash and B's workload id; **no run directory and no backend
  binary access** (`run` and a would-be binary path asserted absent).
- Reverse direction (`Compilation B + Workload A`) refuses identically.
- A workload with `provenance=None` refuses (`provenance` in message) —
  fail closed, no geometry fallback.
- Positive control: matching identity reaches `BACKEND_UNAVAILABLE`
  (identity is not the gate; availability is).
- `Request B + PerformanceResult A` refuses at `RequirementEvaluator`
  (`MappingInvalid`, workload-id for payload/order, design-hash for the
  traffic-class case).
- `Request B + RequirementReport/parents A`: the parents refuse; report A
  is asserted to carry A's design hash/result id and a different
  `report_identity` from B's honest report.
- `Request B + Compilation A` passed to `design_view` refuses (B4).

Never fixed by adding geometry fields: every gate compares content
identity (`design_hash`, `workload_id`, chain ids).

## B3 — product orchestration total over documented typed refusals

`evaluate_product()` now maps the full documented space deliberately, with
no broad `except Exception`:

| Source refusal | Product status | Where |
|---|---|---|
| `UnsupportedSemantics` / `UnsupportedSchedule` (lowering) | UNSUPPORTED | RT-9 catch, retained |
| `InvalidInput` (lowering, incl. broadcast root) | INVALID | RT-9 catch, retained |
| `MappingInvalid` (traffic-class admission) | UNSUPPORTED | RT-9 catch, retained |
| requirement scope over absent traffic (request-only) | INVALID | **new pre-spawn gate** |
| `EvaluationError(INVALID_INTENT)` | INVALID | new deliberate mapping |
| `EvaluationError(UNSUPPORTED_SEMANTICS)` | UNSUPPORTED | new deliberate mapping |
| `EvaluationError(EVIDENCE_INVALID)` | FAILED | new deliberate mapping |
| unknown `EvaluationError` code (e.g. `INTERNAL_ERROR`) | **re-raised** | stays a bug |
| `InvalidInput` from RequirementEvaluator | INVALID | new deliberate mapping |
| `MappingInvalid` from RequirementEvaluator | UNSUPPORTED | new deliberate mapping |
| `EvidenceInvalid` from RequirementEvaluator | FAILED | new deliberate mapping |
| outcome statuses (`BACKEND_UNAVAILABLE` / `UNSUPPORTED` / `FAILED`) | passed through | unchanged |

The only request-only `RequirementEvaluator` refusal (a requirement
constraining a traffic class no intent declares) is decided **before any
backend work** by a pre-spawn mirror of the evaluator's condition;
`RequirementEvaluator` still enforces it at report time (defense in
depth). `bridge_to_evaluation_messages` is not on the product path (the
product passes the lowered unified class into `FabricEvaluator`); its
documented refusal space is pinned by `test_p1c_eval_bridge.py`.

RT-9 was verified complete and extended to the full documented space:
`tests/test_rt_b3_product_taxonomy.py` covers UnsupportedSemantics,
UnsupportedSchedule, InvalidInput (broadcast root + ghost requirement
class + bad option), MappingInvalid admission, the FabricEvaluator
identity/option refusals, multi-class and BACKEND_UNAVAILABLE — every
pre-backend refusal also asserts its `run_dir` was never created.

## B4 — design_view refuses transplanted Compilation

RT-8's `isinstance` + `request.design_hash()` guard is verified against
the stronger adversarial case: two v3 requests with identical TP/PP/EP/DP
and world size but different collective payloads. Both
`design_view(request_B, compilation_A)` and the reverse raise `ValueError`
naming both bare hashes; the matching pair still fills `locked_derived`
(`certificate_overall == "PASS"`). A mismatch raises — it never silently
projects `locked_derived=None` (`tests/test_p1_product_views.py`).

## B5 — no `assert` in seal-critical checks; `python3 -O` proof

- `fabric_evaluator.py` carried the evidence-authentication `assert`
  (`artifact.authenticates(...)`). Under `python3 -O` that invariant
  disappeared entirely. Replaced by an explicit conditional helper
  `_require_evidence_authentic(...)` raising the typed `EvidenceInvalid`
  the evaluator maps to FAILED. Static audit in
  `test_rt_b5_o_invariants.py` pins zero `ast.Assert` nodes in the file.
- `product_evaluator.py` and `views.py` contain no asserts; the new gates
  use explicit conditionals + typed exceptions.
- `tests/rt_identity_probe_o.py` runs **both** gates under
  `python3 -O` in a fresh interpreter: same-geometry transplant must
  refuse (`INVALID_INTENT`, "transplanted") and a non-authenticating
  artifact must refuse (`EvidenceInvalid`); it prints one canonical JSON
  verdict and exits non-zero on any bypass. `test_rt_b5_o_invariants.py`
  asserts the verdict (`{"ok": true, ...}`) via subprocess.
- Audit note: `requirements.py` keeps two `assert x is not None` lines
  used only for type narrowing immediately after the caller proved the
  same condition; they are not correctness gates (the fallback expression
  would raise anyway) and are outside this worker's file ownership.

## B6 — mandatory adversarial test matrix

| # | Proposition | Test |
|---|---|---|
| 1 | same geometry different design → RequirementEvaluator refuses | `test_rt_b1_identity_chain.py::TestIdentityChain` (payload) + `test_p1_requirements_provenance.py::test_same_geometry_different_traffic_class_refuses` (equal workload_id) |
| 2 | same → FabricEvaluator/product boundary refuses transplant | `test_rt_b2_fabric_transplant.py` (3 variants, both directions, no-provenance) |
| 3 | design_view(request_B, compilation_A) refuses | `test_p1_product_views.py::test_design_view_refuses_same_geometry_cross_design` |
| 4 | UnsupportedSemantics → typed product outcome | `test_rt_b3_product_taxonomy.py::test_unsupported_semantics_from_lowering` |
| 5 | UnsupportedSchedule → typed | `...::test_unsupported_schedule_from_lowering` (2047 B over 4 ranks) |
| 6 | InvalidInput → typed | `...::test_invalid_input_from_lowering`, `test_requirement_scope_over_absent_traffic_refuses_pre_backend`, `test_bad_option_refusal_is_typed_not_raised` |
| 7 | MappingInvalid → typed | `...::test_traffic_class_admission_mapping_invalid_is_unsupported` |
| 8 | no backend dir/process for pre-backend refusal | every B3 pre-backend test asserts `not run.exists()` (and B2 asserts a never-used binary path is untouched) |
| 9 | valid matching path still evaluates (real BookSim) | `test_rt_b1_identity_chain.py::TestValidPath` (real binary, EVALUATED, full chain) |
| 10 | `python3 -O` does not disable the new identity gates | `test_rt_b5_o_invariants.py` + `rt_identity_probe_o.py` |

---

## Verification

**Focused (21 files, HEAD):** 275 passed, 0 failed.

```
cd tracks/t3-topology/dse && python3 -m pytest \
  tests/test_rt_b1_identity_chain.py tests/test_rt_b2_fabric_transplant.py \
  tests/test_rt_b3_product_taxonomy.py tests/test_rt_b5_o_invariants.py \
  tests/test_p1_product_orchestration.py tests/test_p1_product_views.py \
  tests/test_p1_requirements_provenance.py tests/test_p1_clock_semantics.py \
  tests/test_p1_product_vertical_slice.py tests/test_p1b_fabric_evaluator.py \
  tests/test_p1b_meshdor_profile.py tests/test_p1b_meshdor_gates.py \
  tests/test_p1c_intent_lowering.py tests/test_p1c_eval_bridge.py \
  tests/test_p1c_requirements.py tests/test_p1c_v3_compile.py \
  tests/test_p1c_v3_schema.py tests/test_p1b_certificate_provenance.py \
  tests/test_p2_real_adapter.py tests/test_p2_guided_optimization.py \
  tests/test_p1_optimize_booksim.py -q -p no:cacheprovider
# 275 passed in 11.73s
```

**Broad battery vs the provisioned baseline from `0e761060`** (same
worktree, same binary, before any change):

```
cd tracks/t3-topology/dse && python3 -m pytest tests -q --tb=no -p no:cacheprovider
baseline (/tmp/rtB-baseline.log, nodes /tmp/rtB-baseline-nodes.json):
  118 failed, 3838 passed, 40 skipped, 9 xfailed, 2 warnings, 44 errors
final    (/tmp/rtB-final.log,    nodes /tmp/rtB-final-nodes.json):
  117 failed, 3864 passed, 40 skipped, 9 xfailed, 2 warnings, 44 errors
```

Node-set symdiff (`/tmp/rtB-final-nodes.json` vs
`/tmp/rtB-baseline-nodes.json`):

- **NEW FAILED: 0. NEW ERRORS: 0.**
- Resolved (1, individually explained):
  `tests/test_process_supervision.py::TestCancellation::test_ctrl_c_kills_child_and_propagates`
  — a pre-existing supervision-timing flake (also resolved in the RT-2
  battery); process supervision was not touched by this work, so this is
  recorded as resolved, not claimed as a fix.
- New passing nodes (+26) = 25 new tests in this branch (6 B1 + 6 B2 +
  9 B3 + 2 B5 + 1 B4 view + 1 provenance) plus the resolved flake.

No test files deleted, no new ignores, no xfail/skip added (the probe is
a plain script, not `test_*.py`, so pytest never collects it).

## Residual risks / disclosures

1. **Cross-ownership edit (flagged for the coordinator).**
   `application/requirements.py` is Worker A's file for a narrow
   report-identity addition, but B1's mandate ("every substitution must
   fail at the earliest boundary") could not be met without the chain
   `design_hash` check: the traffic-class-only transplant is invisible to
   `workload_id`. The edit is 19 added lines plus docstring updates in
   the existing provenance block; no other region of the file changed.
   The Wave-D chain producer change is in `fabric_evaluator.py` (this
   worker's file, permitted by the proven RT-2 gap).
2. **Pre-spawn mirror duplication.** The requirement-scope gate in
   `product_evaluator.py` repeats one condition from
   `RequirementEvaluator` (message included) because the evaluator's
   authority is not exposed as a preflight and Worker B does not own
   `requirements.py`'s API. `RequirementEvaluator` still enforces the
   same law at report time; if the evaluator's condition ever changes,
   both sites must move together.
3. **MappingInvalid mapping is tested by stub.** The v3 VC derivation
   always declares every intent class, so `assert_traffic_classes_bound`
   cannot fail on the honest product path; the test monkeypatches the
   admission call to raise the real `MappingInvalid` and asserts the
   orchestration maps it to UNSUPPORTED with no run dir. The real gate
   itself is pinned in `test_p1c_intent_lowering.py`.
4. **`FabricEvaluator`'s pre-existing broad `except Exception` blocks**
   (projection / realization / execution / evidence / window /
   performance construction) map unexpected bugs to FAILED/UNSUPPORTED.
   They predate this wave and are outside the proven binding gap; the
   new product-level mapping does not add any broad catch. Flagged for
   the seal worker's 20-rule audit.
5. **Committed Studio fixtures are now one chain field behind.** The
   added `wave_d_chain.design_hash` moves the engine's
   `performance_result_id`; Worker C regenerates `apps/studio` fixtures
   from `ENGINE_CLOSURE_SHA` per the campaign plan. No `apps/studio` file
   was touched here.
6. **P1B hermetic fixtures now carry design provenance**
   (`test_p1b_fabric_evaluator.py`, `test_p1b_meshdor_profile.py`) — a
   fixture-contract change forced by the fail-closed precondition, not a
   semantics change to the evaluator's outcomes.
