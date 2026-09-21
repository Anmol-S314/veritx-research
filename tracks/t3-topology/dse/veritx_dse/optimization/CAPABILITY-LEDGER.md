# P2 Capability Ledger — guided optimization (FROZEN audit, P2 base `ec747ffe`)

Scope: every search/optimization-adjacent capability in
`synthesis/*`, `wave-f/design-optimization`, `reference/.../optimization/`,
and existing Pareto tests/tools — classified REPLAY / MOVE / SUPERSEDED /
REIMPLEMENT / REJECT / HISTORICAL. No blind Wave-F merge: only ledger rows
marked MOVE/REPLAY entered `optimization/`; everything else is recorded
with its reason.

Conventions: source path + commit/branch where relevant; "validity" = the
condition under which the capability's claim holds; "destination" = where
it went (or why it did not).

Branch audited: `wave-f/design-optimization` @ `d178c90e` (Wave F tip).
Reference: `reference/target-architecture/src/veritx_dse/optimization/`
(5 files, 98 lines). Synthesis: 8 files, 3531 lines.

## 1. Wave-F design-optimization (`wave-f/design-optimization`)

| # | Capability | Source | Validity | Verdict | Destination / reason |
|---|------------|--------|----------|---------|----------------------|
| W1 | Canonical enumeration order (§24/§83/§84: sorted params, canonical-JSON value sort, declaration order non-semantic, budget keeps canonical prefix) | `optimization/space.py::iter_raw_assignments`, `budget_plan` | Holds iff enumeration is a pure function of the definition | REPLAY | `optimization/search.py::canonical_assignments`, `_budget_limit` (idea replayed, re-implemented on CompileRequest domain) |
| W2 | Candidate identity `H(design_space_id, assignment, intent ids)` (§17) + alias/INVALID accounting (§19) | `optimization/space.py::candidate_identity`, `build_candidates` | Holds under the sealed control-plane intent system (resolve_intent, fabric_overrides seam) | REPLAY (idea) / REJECT (mechanism) | Idea replayed as `optimization/candidate.py::candidate_id_for` = H(base_design_hash, canonical patch). The `fabric_overrides` patching seam + alias/dedupe machinery REJECTED: P2 authority is CompileRequest+NocConfig, not intent docs |
| W3 | Closed GUIDED registry (`PARAM_REGISTRY`: workload.tp/pp/ep/dp + fabric.topology/link_width via fabric_overrides) | `optimization/definition.py::PARAM_REGISTRY`, `patched_scenario_template` | Holds only inside Wave-F's intent-doc world | SUPERSEDED | `optimization/definition.py::GUIDED_PARAMS` on NocConfig fields (link_width, concentration, radix, rcu_enabled, topology_family, arbitration, mcast knobs). Same closed-registry discipline, product authority |
| W4 | Constraint truth table (§45–§48: SATISFIED/VIOLATED/UNMEASURABLE; unmeasurable never passes; asymmetric NO_FEASIBLE_DESIGN) | `optimization/constraints.py` | Holds generally (pure logic over MetricValue) | REPLAY | `optimization/constraints.py::evaluate_all` (truth table replayed; MetricValue/Fraction machinery superseded by plain floats) |
| W5 | Pareto as direction adapter over sealed `core.comparison.pareto_with_scope` (§40/§86; MAX→negate; ties stay ties) | `optimization/pareto.py::compute_frontier`, `dimensions` | Holds; the adapter-not-second-implementation rule is the durable insight | REPLAY | `optimization/pareto.py::pareto_with_sealed_gate` (adapter rule replayed; Wave-F scenario/multi-model comparability gate SUPERSEDED — P2 has one scenario, one fake fidelity) |
| W6 | Orchestrator sequencing (candidates → cp.evaluate → verified results → extract → frontier → select) | `optimization/orchestrator.py::run_optimization` | Holds under sealed control plane + store | REPLAY (shape) | `optimization/result.py::Optimizer.optimize` replays the sequencing shape against CandidateEvaluationPort (no control plane/store in P2) |
| W7 | Verified metric extraction (WAVE_E/WAVE_D_CHAIN/STRUCTURAL, Fraction-exact, UNMEASURABLE≠zero §31–§36) | `optimization/metrics.py` | Holds under Wave-E verified parents; no such parents exist in P2 | REJECT (deferred) | No `optimization/metrics.py` in P2. Returns with the real adapter (PerformanceResult-backed extraction at integration) |
| W8 | Verified result builder + full re-deriving verifier (§62–§82, §113–§116; evidence binding, budget-tail agreement, transplant refusal) | `optimization/result.py` (2211 lines) | Holds under sealed store + content-addressed resources | SUPERSEDED | `optimization/result.py` keeps identity-over-(base, definition, rows, frontier) + re-derivation assertions (identity stability), without the store-backed verifier. Full seal returns at integration if evidence persists |
| W9 | Comparability gate (one fidelity class, one model per scenario §42/§131/§132) | `optimization/pareto.py::comparability_report` | Holds for multi-model frontiers | HISTORICAL | Recorded; P2 frontier is single-fidelity by construction (fake evaluator). Revisit when the real adapter mixes backends |
| W10 | Selection policies (NONE/SINGLE_OBJECTIVE/LEXICOGRAPHIC §57; ties preserved §58/§59) | `optimization/pareto.py::select` | Pure logic, holds | REPLAY | `optimization/result.py::_select` (min-first-objective + lexicographic + none; deterministic smallest-id tiebreak) |
| W11 | Budget accounting (raw vs unique vs planned vs evaluated §25; search/frontier_complete §54/§55) | `optimization/result.py::derive_budget`, `derive_search_complete` | Holds where search can alias/prune/defer | HISTORICAL | P2 records requested vs executed via definition budget; full budget-tail machinery deferred (no ALIAS/INVALID/NOT_EVALUATED states in P2) |
| W12 | Independent-oracle tests (brute-force Pareto, truth tables — not calling production code) | `tests/test_optimization_core.py`, `tests/test_optimization_e2e.py`, `tests/veritx_e_helpers.py` | Holds as a testing discipline | REPLAY | `tests/test_p2_guided_optimization.py` follows the same discipline (brute oracle in-file, sealed-gate cross-check) |

## 2. Synthesis (`tracks/t3-topology/dse/veritx_dse/synthesis/`)

| # | Capability | Source | Validity | Verdict | Destination / reason |
|---|------------|--------|----------|---------|----------------------|
| S1 | Requirements-gated candidate evaluation (binding=hard constraint, non-binding=soft; FEASIBLE/NO_FEASIBLE_DESIGN/CONSTRAINT_UNMEASURABLE/INCONCLUSIVE; fail-closed: violations beat unmeasurable, failures/prunes stay visible; Pareto via Phase-8 gate only) | `synthesis/compiler.py::evaluate_candidates`, `CandidateEvaluationRequest` | Holds for caller-supplied candidates + SynthResult-shaped evaluate | REPLAY | `optimization/result.py::Optimizer.optimize` replays: feasible-only Pareto, fail-closed verdicts, crashed candidates visible & excluded, relaxation-as-information in rationale. The E2 Requirement type itself stays in compile_model (P1C owns) |
| S2 | Bridge translation (SynthResult dicts ↔ compiler candidates; failed→PRUNED with reason; re-evaluate the recorded spec, never a re-interpretation) | `synthesis/bridge.py` | Holds for the anynet/spec evaluation world | HISTORICAL | No anynet specs in P2 (candidates are CompileRequests). The translate-never-reinterpret rule is recorded and followed by `candidate.apply_patch` |
| S3 | BO over topology parameters (cluster_size/express_length/radix/intra/inter_weight via skopt GP) | `synthesis/bo_synthesizer.py` | Holds as sample-efficient search AFTER a correct oracle exists | REJECT (deferred) | Bayes only after deterministic correctness is established (contract §4). P2 ships grid/enumeration/seeded-random; BO returns on proof of interface mismatch or post-correctness milestone |
| S4 | RHO/GRPO iterative mutation search (edge add/remove + BookSim rollouts/group baseline) | `synthesis/iterative_synthesizer.py` | Same precondition as S3; mutates anonymous adjacency, not CompileRequests | REJECT (deferred) | Same as S3. Edge-level mutation is additionally the wrong authority (anonymous hardware dict — contract forbids) |
| S5 | Traffic-weighted MILP/SA topology generation (TMCF HiGHS exact ≤20 nodes; SA geodesic at 64+; priced physical latency) | `synthesis/milp_topology_v2.py` | Holds as a generator of topologies, not as a GUIDED search over CompileRequests | REJECT (deferred) | Same precondition as S3. MILP returns only with a GUIDED-domain formulation (decision vars = NocConfig knobs, LOCKED recompiled) |
| S6 | Canonical SynthResult schema (ok/error + latency + provenance + extra; topology/backend alias sync) | `synthesis/results.py::SynthResult` | Holds for BookSim-backed synthesis records | SUPERSEDED | `optimization/evaluators.py::CandidateEvaluation` (candidate_id/design_hash/status/objectives/locked_consequences; provenance = fake:hash until the real adapter supplies evidence IDs) |
| S7 | ONE BookSim evaluation path (BO/iterative/pareto presets converged; sentinels at record boundary, never inside science) | `synthesis/evaluator.py` | Holds for BookSim-backed scoring | HISTORICAL | P2 evaluates via FabricCompiler + analytic fake (no BookSim). The one-path + sentinel-at-boundary discipline is recorded for the real adapter |
| S8 | Event-native collective scoring (structural participants, multi-algorithm, priority-weighted priced geodesic) | `synthesis/event_objective.py` | Holds as an analytical scorer over adjacencies | HISTORICAL | No adjacency-level scoring in P2 (search is over NocConfig knobs). Candidate for the real adapter's analytic fallback, not the P2 fake |

## 3. Reference target-architecture (`reference/target-architecture/src/veritx_dse/optimization/`)

| # | Capability | Source | Validity | Verdict | Destination / reason |
|---|------------|--------|----------|---------|----------------------|
| R1 | Parameter/Objective/OptimizationDefinition + definition_id (duplicate-name and empty-objective guards) | `definition.py` | Holds; minimal and correct | MOVE | `optimization/definition.py::DomainParam/Objective/definition_id` (logic moved verbatim in shape; extended with GUIDED registry, constraints, method, budget, seed, selection) |
| R2 | Constraint `<=`/`>=` over Fractions | `constraints.py` | Holds; minimal and correct | MOVE | `optimization/constraints.py::evaluate_constraint_value` (operator rule moved verbatim; extended with UNMEASURABLE arm) |
| R3 | `pareto_front(values, directions)` exact dominance, sorted-id order | `pareto.py` | Holds; minimal and correct | MOVE | `optimization/pareto.py::pareto_front` (verbatim, no style rewrites) |
| R4 | CandidateResult/OptimizationResult + frontier() + result_id() (Fraction metrics, dual-bound rows) | `result.py` | Holds as identity shape; Fraction rows superseded by JSON floats in the frozen view | MOVE (shape) | `optimization/result.py::OptimizationResult.result_id/to_study_view` (identity-over-rows+frontier moved; Fraction encoding superseded by view floats) |
| R5 | `canonical_assignments` (sorted params, canonical-JSON value sort, product) | `search.py` | Holds; minimal and correct | MOVE | `optimization/search.py::canonical_assignments` (verbatim shape, typing adapted) |

## 4. Existing Pareto tests/tools

| # | Capability | Source | Validity | Verdict | Destination / reason |
|---|------------|--------|----------|---------|----------------------|
| P1 | Sealed Pareto gate with scope honesty (every candidate visible; COMPARABLE/MISSING_METRIC; mixed-fidelity refusal; front+dominated+excluded) | `core/comparison.py::pareto_with_scope` (+ `synthesis/compiler.py` usage) | Holds; the ONE Pareto authority | REPLAY | Used, not copied: `optimization/pareto.py::pareto_with_sealed_gate` calls it as a cross-check; `Optimizer` frontier agrees with it on MIN objectives (tested) |
| P2 | Pareto benchmark honesty (auto per-trace timeout; FAIL vs no-metric classes; dedupe; normalized geomean over common successful set) | `tools/multi_workload_pareto.py`, `tests/test_pareto_honesty.py` | Holds for multi-workload benchmark ranking | HISTORICAL | Single-scenario P2 has no per-trace populations; the never-conflate-failure-with-property discipline is recorded for the real adapter |
| P3 | Synthesis loop contracts (BO helpers, iterative mutation/connectivity, math cores with deterministic fixtures) | `tests/test_synthesis_loops.py`, `tests/test_synthesis_math.py`, `tests/test_fabric_compiler.py` | Hold for their modules | HISTORICAL | Untouched; P2 adds `tests/test_p2_guided_optimization.py` without duplicating their seams |

## Summary counts

- MOVE: R1, R2, R3, R4(shape), R5 (reference core promoted verbatim-in-shape)
- REPLAY: W1, W2(idea), W4, W5, W6, W10, W12, S1, P1 (discipline/shape, re-implemented on product authority)
- SUPERSEDED: W3, W8, S6 (same discipline, new authority)
- REJECT (deferred, with return condition): S3, S4, S5 (Bayes/MILP/RHO/GRPO/SA after deterministic correctness), W7 (metrics with real adapter)
- HISTORICAL: W9, W11, S2, S7, S8, P2, P3 (recorded, not imported)
- New authorities: `optimization/{definition,candidate,search,constraints,pareto,result,evaluators}.py`, `OptimizationStudyView` emission (contract v1)
- Removed authorities: none (synthesis/* untouched; no second CompileRequest/route/VC/evidence/performance authority introduced)
