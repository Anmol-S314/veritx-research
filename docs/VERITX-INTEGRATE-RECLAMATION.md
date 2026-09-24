# VERITX-INTEGRATE — Reclamation Ledger

Product tree: `veritx-integrate` (this branch). One writer. Historical branches are
capability warehouses; nothing is merged wholesale. Every row records the source
ref/path and the reclamation status.

## 0. Source inventory (verified in this worktree)

| Ref | Commit | Verified |
|-----|--------|----------|
| integration/canonical (pin) | `2f727dd1503c00697b2afaeda75a7fa6947dd1c3` | yes |
| integration/canonical (local, 1 commit ahead of pin) | `96603ae21142ef48816ad9443701eb37ab8b3ddd` | yes |
| audit/wave-b-intent-identity | `3d70ffd93bc7a5a8b7491fa44191921b24329be1` | yes |
| audit/wave-b-mapping-artifact-wip | `5509b9dce5b05844c3596d7a427ea03bd4c98d20` | yes |
| wave-c/unified-control-plane | `8455c0450e27486ae034028b76c9a05b94f2ea72` | yes |
| wave-d/distributed-semantics | `d3f3bd63b952b54fb5cac688532caf83ca66c512` | yes |
| wave-e/system-performance | `16ebd71bde25e3045b51cba8f06f88c34ff1330d` | yes |
| wave-f/design-optimization | `d178c90ee0a08663538dce68b85d690a74ff1a15` | yes |
| audit/wave-f-parity-ledger | `fef627fa3e171ea37fb9f7f6cd5aefbd649184dd` | yes |
| integration/p1-product-rt-candidate | `26e6f9dcb1bba85e7d97f4663c5da29e14c9b721` | yes |
| integration/p1-product (pin) | `b1b6ed5579210a48a4617bb36bb3d82148446f43` | yes |
| p1/fabric-compiler-productization | `662e7ce6e4ec5462b7e710eece6a5a78e35093fb` | yes |
| p1b/verified-evaluation | `3def89c3a146490a91288210ba6252af51cd8eba` | yes |
| p1c/workload-requirements | `33703bd04df2a737c0cff6e75874274fa5d72425` | yes |
| p1x/product-contracts | `ec747ffe9a4f25c89335d0bae6dcc7f76d57664f` | yes |
| serving-leg | `ffee33334c7b9c24d6a5597d4e87cdb0c644b9d0` | yes |
| t3-rtl-noc-backup-20260815 | `f8ab4a63ff3ea5058d04f64ed6bb0338f58b0e70` | yes |

**Base-of-work decision.** The mandate pins canonical at `2f727dd1`. The local
`integration/canonical` is exactly one commit ahead (`96603ae2` "Serving: dense
data-parallel quorum semantics over the fixed canonical fabric", direct child of
the pin, canonical message). Per the newer-equivalent rule the integration is
built on `96603ae2`. Nothing older is promoted over it.

**Divergent remote tips (not used):** `origin/wave-e/system-performance`
(`fbc71d74`) and `origin/p1c/workload-requirements` (`24c2ab63`) are divergent
from their pins (neither ancestor nor descendant). The pinned commits are used,
per §1. `origin/p1b` tip `f67c2408` is older than its pin (the pin contains it).
`origin/integration/p1-product` tip equals the P1X pin `ec747ffe` (divergent from
the `b1b6ed55` pin); the RT candidate `26e6f9dc` carries the whole evolved RT
lineage and is the product source per §2 precedence.

**Environment note (pre-existing, not introduced here):** the BookSim2 binary was
built for the real-workload gates. Canonical test
`tests/test_cli_compile_surface.py::test_no_booksim_binary_needed_for_canonical_compile`
asserts the binary is ABSENT (a no-binary dev proof) and therefore fails in this
environment by design. It passes in its intended condition. Baseline full-suite
result before any integration work: **3088 passed, 13 skipped, 1 failed (that
test only)** in 1235s.

## 1. Reclamation rows

Statuses: KEEP_CANONICAL / COPY_VERBATIM / COPY_AND_ADAPT / TEST_ONLY /
RETAIN_RESEARCH / SUPERSEDED / REJECTED.

### Core spine support

| Capability | Source | Source path | Destination | Status |
|------------|--------|-------------|-------------|--------|
| canonical_json / sealed spec types | p1-product-rt-candidate `26e6f9dc` | veritx_dse/core/spec.py | veritx_dse/core/spec.py | COPY_VERBATIM |
| Wave-E exact rational time (QTime) | p1-product-rt-candidate `26e6f9dc` | veritx_dse/core/time.py | veritx_dse/core/time.py | COPY_VERBATIM |
| sealed Pareto gate (pareto_with_scope) | p1-product-rt-candidate `26e6f9dc` | veritx_dse/core/comparison.py | veritx_dse/core/comparison.py | COPY_VERBATIM |
| typed refusal classes (TimeoutError/BackendFailure/BackendTimeout) | p1-product-rt-candidate `26e6f9dc` | veritx_dse/core/errors.py | veritx_dse/core/errors.py | COPY_AND_ADAPT (additive merge; canonical docstrings kept) |
| run-directory paths (VERITX_RUNS_DIR/RESULTS_DIR/SYNTH_DIR/new_run_dir) | p1-product-rt-candidate `26e6f9dc` | veritx_dse/core/paths.py | veritx_dse/core/paths.py | COPY_AND_ADAPT (additive merge) |
| content_id/content_hash/FrozenMap/freeze | current canonical | veritx_dse/core/artifact.py | (already present) | KEEP_CANONICAL |
| CompileRequest / validation / semantics v2 | current canonical | veritx_dse/model/compile_model.py | (already present) | KEEP_CANONICAL |
| canonical compiler (CompiledFabric) | current canonical | veritx_dse/compiler/canonical.py | (already present) | KEEP_CANONICAL |
| ResolvedFabric / fabric artifact / route model | current canonical | veritx_dse/model/* | (already present) | KEEP_CANONICAL |
| authenticated backend evidence | current canonical | veritx_dse/backend/evidence.py | (already present) | KEEP_CANONICAL |
| WorkloadGraph / ParallelismShape / rank namespace | current canonical | veritx_dse/workload/graph.py | (already present) | KEEP_CANONICAL |
| messages / traffic / ParticipantEndpointMapping | current canonical | veritx_dse/workload/messages.py, traffic.py | (already present) | KEEP_CANONICAL |
| ASTRA projections/namespace/execution | current canonical | veritx_dse/backend/astra*.py | (already present) | KEEP_CANONICAL |
| BookSim preparation/execution | current canonical | veritx_dse/backend/booksim_*.py | (already present) | KEEP_CANONICAL |
| real request-driven serving loop + DP quorum + TP groups | current canonical (`96603ae2`) | veritx_dse/simulation/serving_*.py | (already present) | KEEP_CANONICAL |
| application service/store/resources/compile_intent | current canonical | veritx_dse/application/{service,store,resources,compile_intent}.py | (already present) | KEEP_CANONICAL |

| application service/store/resources/compile_intent | current canonical | veritx_dse/application/{service,store,resources,compile_intent}.py | (already present) | KEEP_CANONICAL |

### Wave B — identity/integrity (§5)

| Capability | Source | Source path | Destination | Status |
|------------|--------|-------------|-------------|--------|
| strict primitive validation | audit/wave-b `3d70ffd9` | model/compile_model.py (`_TOP_KEYS`, `CompileRequestSchemaError`) | veritx_dse/core/artifact.py + test_artifact_primitives.py | KEEP_CANONICAL |
| deep immutability (freeze/FrozenMap) | wave-d `d3f3bd63` waved/immutable.py (triplicate) | waved/immutable.py | veritx_dse/core/artifact.py (merged per docstring) | KEEP_CANONICAL |
| content-addressed intent identity | audit/wave-b `3d70ffd9` | model/compile_model.py | veritx_dse/model/compile_model.py (semantics v2) + application/compile_intent.py | KEEP_CANONICAL |
| dependency identity | audit/wave-b `3d70ffd9` | model/compile_model.py | same as above (COMPILER_SEMANTICS_VERSION=2) | KEEP_CANONICAL |
| mapping identity | mapping-WIP `5509b9dc` | core/mapping.py | veritx_dse/model/mapping.py (diff 3+/5-) | KEEP_CANONICAL |
| transplant refusal | wave-b + wave-d SEAL.1 | design identity + result provenance binding | application/results.py + waved_resources.py (v2) | KEEP_CANONICAL |
| lossless strict serialization | wave-b | canonical_bytes | veritx_dse/core/artifact.py::canonical_bytes | KEEP_CANONICAL |
| mapping-WIP binary/dirty-tree provenance | mapping-WIP `5509b9dc` | core/comparison.py, core/runs.py | — (not ported; mapping part superseded by model/mapping.py) | OUT-OF-SCOPE (binary/dirty-tree provenance is dev-environment metadata, not scientific identity; no consumer requires it) |

No Wave-B production copy. High-value adversarial tests already present in canonical suite.

### Wave C — application/control plane (§6)

| Capability | Source | Source path | Destination | Status |
|------------|--------|-------------|-------------|--------|
| errors/inventory/presets/studies/surfaces | wave-c `8455c045` | application/{errors,inventory,presets,studies,surfaces}.py | same paths | KEEP_CANONICAL (zero diff) |
| capabilities/comparison/compile/requests/resources/results/service/store | wave-c `8455c045` | application/*.py | same paths (current superset, transplant-bound) | KEEP_CANONICAL |
| legacy.py, cli/service_cli.py | wave-c `8455c045` | application/legacy.py, cli/service_cli.py | replaced by cli/commands_compile.py + commands_trace.py | SUPERSEDED |
| RT 5-file application slice | RT candidate `26e6f9dc` | reference/*/application/ (5 files) | subsumed by current 20-file plane | SUPERSEDED |
| lifecycle/integrity tests (SEAL.1, ATTEMPT_STATUSES) | wave-c `8455c045` | tests/test_control_plane_* (9 files) | not ported | OUT-OF-SCOPE (canonical application coverage via service/store/results/compile tests; lifecycle vocabulary superseded by 4-kind ResourceStore + immutable run skeleton) |
| evaluation-plane modules (compile/results/waved/wave_e/fabric_evaluator/...) | RT candidate `26e6f9dc` | application/*.py (17 files) | same paths (added at a5b806fe) | COPY_VERBATIM + seam adapters (local envelope shims; v1 readers fail closed; see §4 notes) |

### Wave D — distributed semantics (§7)

Second authority prohibited: no WorkloadGraph2 / DistributedWorkload / v1
message-traffic classes. v1 `WaveDWorkload`/`WaveDOperation`/v1
`LogicalMessageArtifact`/`PhysicalTrafficArtifact` deleted; canonical
`WorkloadGraph` + V2 artifacts are the sole authority.

| Capability | Source | Source path | Destination | Status |
|------------|--------|-------------|-------------|--------|
| operation identity / causal DAG | wave-d `d3f3bd63` | waved/operations.py | workload/operations.py (OperationGraph) | KEEP_CANONICAL |
| participant/P2P/collective semantics | wave-d `d3f3bd63` | waved/semantics.py, messages.py | workload/semantics.py + messages.py (V2) + collectives.py | KEEP_CANONICAL |
| traffic provenance / conservation | wave-d `d3f3bd63` | waved/traffic.py | workload/traffic.py (V2) + waved_resources.py + results.py | KEEP_CANONICAL |
| rank geometry | wave-d `d3f3bd63` | waved/parallelism.py | model/parallelism.py (verbatim reparent) + placement.py authority | KEEP_CANONICAL |
| backend projection | wave-d `d3f3bd63` | waved/backend.py | backend/astra*.py + booksim_execution/projection.py | KEEP_CANONICAL |
| waved/identity.py, strict.py, immutable.py | wave-d `d3f3bd63` | waved/*.py | merged into core/artifact.py | KEEP_CANONICAL (do not resurrect) |
| waved/oracles.py | wave-d `d3f3bd63` | waved/oracles.py | test helper/oracle only, never production | TEST_ONLY |
| contract JSON + scientific contract doc | wave-d `d3f3bd63` | tracks/t3-topology/docs/wave-d-contract.json + WAVE-D-SCIENTIFIC-CONTRACT.md | same paths (were missing at HEAD) | COPY_VERBATIM |
| v1 chain tests (authenticity/semantics/physical/seal) | RT lineage | tests/test_wave_d_{authenticity,semantics,physical,seal}.py | same paths, module-level historical skip (v1 authority deleted; V2 in test_wave_d_contract.py) | SUPERSEDED |
| contract test helpers | wave-d + canonical | test_wave_d_contract.py (presets→placement import; astra heuristic skipped) | same path | COPY_AND_ADAPT (canonical placement.world_size; historical astra collapse refused by derive_logical_dimensions) |

### Wave E — system performance (§8)

All 10 files byte-identical across `wave-e 16ebd71b` == RT `26e6f9dc` ==
HEAD. Phase-16 exposed-vs-stall distinction and explicit clock/units
preserved. No new model invented; canonical BookSim/ASTRA/serving evidence
connects via thin adapters (existing evidence seam).

| Capability | Source | Source path | Destination | Status |
|------------|--------|-------------|-------------|--------|
| performance/metrics,model,network,result,scheduler,sensitivity,workload | wave-e `16ebd71b` | veritx_dse/performance/*.py (7 files) | same paths | COPY_VERBATIM (diff 0) |
| workload/timeline.py | wave-e `16ebd71b` | veritx_dse/workload/timeline.py | same path | COPY_VERBATIM (diff 0) |
| verification/gates.py, reference_semantics.py | wave-e `16ebd71b` | veritx_dse/verification/*.py | same paths | COPY_VERBATIM (diff 0; +4-line canonical payload-width adapter) |

### Memory + Ramulator (§9)

Sourced from Phase-14 (`5f7c44e0`) / Phase-15 (`fd2b6694`, `aa3ef692`,
`fd7f6f7a`) via RT lineage; no algorithm reimplementation. Memory mapping
algorithm unchanged; only ancestry link adapted.

| Capability | Source | Source path | Destination | Status |
|------------|--------|-------------|-------------|--------|
| MemoryArtifact / placement / triple hash | phase14/RT | core/memory.py (668 ln) | veritx_dse/core/memory.py | COPY_VERBATIM |
| resolve_memory / RamulatorGeometry / manifest / trace lowering | phase15/RT | workload/memory_lowering.py (689 ln) | veritx_dse/workload/memory_lowering.py | COPY_VERBATIM |
| discover/binary_hash/producer/MemoryEvidence/chain-verify/drain verdict | phase15/RT | simulation/ramulator.py (535 ln) | veritx_dse/simulation/ramulator.py | COPY_VERBATIM |
| acceptance battery (BUILD/DRAIN/EQUIV/DETERM/LOCALITY/BANK/CLOCK/INTEGRITY/AUDIT) | phase15 `fd7f6f7a` | acceptance/phase15.py | tracks/.../dse/qualification/ramulator.py (relocated, semantics kept) | COPY_AND_ADAPT (moved out of production package, no shim) |
| tests (51+31+17+19) | phase14/15 | test_memory_artifact/lowering/ramulator_{lowering,backend}.py | tracks/.../dse/tests/ | COPY_VERBATIM (284 passed incl. timeline/wave-e suites) |

Historical battery claimed 16/16 PASS; re-ran seal-fresh 2026-09-24: VERDICT PASS (16/16) in 1.9s (python3.12 vendored extension). Memory evidence attaches compositionally via the Wave-E performance model (no cycle-coupled co-simulation was ever implemented; none invented).

### Serving — LLMServingSim semantics (§10–13)

LLMServingSim remains service-semantics authority; VeritX remains
physical-fabric authority. No algorithm reimplementation.

| Capability | Source | Source path | Destination | Status |
|------------|--------|-------------|-------------|--------|
| real Router/Scheduler lifecycle + JSONL workloads | vendored LLMServingSim | third_party/llmservingsim | simulation/serving_loop.py (real route/schedule/load) | RECLAIMED + VERIFIED |
| per-instance TP groups (Slice-38) | canonical `2f727dd1` | simulation/serving_round.py | same (container of per-instance batch plans) | KEEP_CANONICAL |
| DP quorum + dummy/padding | canonical `96603ae2` | simulation/serving_dp.py | same (DpQuorumCoordinator, sent-flag guard) | KEEP_CANONICAL |
| canonical network authority + round qualification | canonical slices | backend/canonical_serving.py + serving_round.py | same | KEEP_CANONICAL |
| EP executable semantics (AG/expert/RS, NOT ALLTOALL; ep≤tp, no rank mult) | vendored trace_generator.py | third_party/llmservingsim | simulation/serving_loop.py (profile ep_* fields) + backend/serving_round.py (EXPERT_BEGIN/compute-chain/EXPERT_END lowering) + tests/test_serving_ep.py (6 tests) | RECLAIMED + ADAPTED + VERIFIED (MoE live gate 1/1, 70 rounds) |
| PP staging via SEND/RECV→KIND_P2P | vendored (pp_comm) | third_party/llmservingsim | — (no adapter built) | OUT-OF-SCOPE (canonical serve refuses pp_size≠1 fail-closed; KIND_P2P seam exists in workload/graph.py for a future adapter) |
| PD KV/output transfer | vendored (kv_comm) | third_party/llmservingsim | — (no adapter built) | OUT-OF-SCOPE (canonical serve refuses prefill disaggregation fail-closed; KIND_P2P seam exists for a future adapter) |
| MemoryModel / prefix cache | vendored | third_party/llmservingsim | — (loop forces caching off) | OUT-OF-SCOPE (real vendored MemoryModel runs inside Scheduler for accounting; prefix-cache enablement + authentication deferred; caching forced off, never silently on) |
| CXL / PIM service semantics | vendored (cxl_mem, PIMModel) | third_party/llmservingsim | — (no adapter built; serving_loop excludes PIM/CXL/offload timing) | OUT-OF-SCOPE (fail-closed exclusions declared in simulation/serving_loop.py; never silently mapped to HBM) |
| profiler-backed compute | vendored perf DB | third_party/llmservingsim | simulation/serving_loop.py CertifiedServiceProfile (declared linear model in profile identity) | OUT-OF-SCOPE (honest declared model; per-batch profiled-table binding deferred; never invented measurements) |

PP/PD rule honored: no new protocol; LLMServingSim SEND/RECV maps to
`KIND_P2P(src_rank,dst_rank,payload_bytes)`; canonical endpoint binding
lowers rank→endpoint.

### Optimization — Wave F / P1 (§14)

Current `optimization/` == RT `26e6f9dc` exactly (diff 0); deliberately
diverges from `wave-f d178c90e` per parity ledger. Deferred/rejected
(BO, GRPO/RHO, MILP topology mutation) stay in `synthesis/` (unwired).

| Capability | Source | Source path | Destination | Status |
|------------|--------|-------------|-------------|--------|
| candidate generation / closed registry / constraints+truth-table / Pareto / selection / deterministic search / budget / result identity / authenticated backend evaluation | RT `26e6f9dc` | veritx_dse/optimization/*.py (11 files) + CAPABILITY-LEDGER.md | same paths | KEEP_CANONICAL |
| BO / GRPO-RHO / MILP topology mutation | wave-f / P1 | synthesis/*.py | synthesis/ only, zero imports from optimization/ | RETAIN_RESEARCH (deferred) |

First integrated optimizer uses the real evaluator over canonical
backend evidence (§26 CLOSED 2026-09-24, Option 2): `veritx optimize`
→ `Optimizer.optimize_certified` → `RealCandidateEvaluator` →
`FabricEvaluator` → canonical `prepare_booksim_input` →
`execute_prepared_booksim` (real binary) → canonical
`ScientificBackendEvidence` → validate → persist → reload → metrics →
Pareto/selection. Proven by `test_p1_optimize_booksim`
(real BookSim study, repeatable) + `test_evidence_authority`
(authority boundary).

### §26 optimizer-evidence closure (Option 2 decision record)

| Capability | Source | Source path | Destination | Status |
|------------|--------|-------------|-------------|--------|
| canonical BookSim execution for optimizer | canonical | veritx_dse/backend/booksim_execution.py + booksim_projection.py | unchanged (optimizer now routes here) | KEEP_CANONICAL |
| canonical evidence read path (`from_dict`, closed) | new (thin) | veritx_dse/backend/evidence.py | additive strict constructor | COPY_AND_ADAPT (read half of the contract never existed; validator already claimed it) |
| canonical evidence helpers (`_require_hex64` name, schema-version comparison) | canonical | veritx_dse/backend/evidence.py | same file, one-word/one-constant fixes | COPY_AND_ADAPT (latent NameErrors on never-exercised paths) |
| optimizer evaluator backend seam | RT `26e6f9dc` | veritx_dse/application/fabric_evaluator.py | same path (meshdor/projection RT seams replaced by canonical prepare+execute; RT evidence construction removed) | COPY_AND_ADAPT (canonical backend evaluation replaces RT evidence model; optimizer/Pareto/selection semantics untouched) |
| optimizer proof seam | RT `26e6f9dc` | veritx_dse/application/authenticated_evaluation.py | same path (reads canonical evidence keys with per-field rationale; no cross-schema mapping) | COPY_AND_ADAPT (proof logic intact; field vocabulary is canonical) |
| canonical completion-cycles key acceptance | canonical Wave-E | veritx_dse/performance/network.py (`bind_network_window`) | same path (accepts `completion_cycles` alongside historical `completion_time`; historical label keeps precedence) | COPY_AND_ADAPT (one measurement, two labels; digest-covered stats untouched) |
| v3 request compilation through canonical store (topology view, address decode, resolved fabric binding) | canonical | veritx_dse/model/topology_artifact.py, address_decode.py, resolved_fabric.py | same paths (accept `FabricIntentView`/v3 request where the v3 path already promised it) | COPY_AND_ADAPT (v3 compilability the P1C report claims; no semantic reinterpretation) |
| RT meshdor backend + profile + qualification | RT `26e6f9dc` | veritx_dse/backend/{meshdor,meshdor_profile,qualification}.py | same paths (recovered for reference; canonical optimizer path does NOT route through them) | LEGACY-ONLY (reference/provenance; not on the certified path) |
| RT standalone BookSim lowering (`backend/booksim.py`, `backend/projection.py`, `backend/booksim_profile.py`) | RT lineage | veritx_dse/backend/{booksim,projection,booksim_profile}.py | same paths (importable; canonical optimizer path does NOT route through them) | LEGACY-ONLY (isolated RT evidence model; see boundary test) |
| RT `CertifiedBookSimEvidence` → canonical coercion | — | — | — | REJECTED (no approved field equivalence; boundary test proves refusal) |
| hardened site-gated source audit names (`GatedReadSite`, `GATED_READ_SITES`, `verify_site_gates`, ...) | RT `26e6f9dc` | veritx_dse/backend/source_audit.py | same file, additive block; canonical simple-audit API untouched | COPY_AND_ADAPT (additive only; required by LEGACY-ONLY RT backend imports) |
| RT transport constants | RT `26e6f9dc` | veritx_dse/backend/producer.py | same file, two additive constants | COPY_AND_ADAPT (additive only) |

### Optimizer authority cleanup (§26 follow-through)

Single optimizer authority: `veritx_dse/optimization/` (definition,
search, Pareto, selection, result, real evaluator) + canonical backend
execution + canonical evidence. There is no second implementation in
this tree: `evaluators.py`/`real_evaluator.py`/`result.py` are the
authority itself, not a parallel one.

| Capability | Source | Source path | Destination | Status |
|------------|--------|-------------|-------------|--------|
| `TestOptimizeCli` (RT CLI surface: `COMMANDS`, `Ctx.failed`, fake-default optimization, v1 StudyView) | RT tests | tests/test_p2_guided_optimization.py::TestOptimizeCli | RETIRED; replaced by tests/test_optimize_canonical_cli.py (registration, fail-closed input, exact-clock boundary, live view conventions) + tests/test_p1_optimize_booksim.py (live repeatability) | SUPERSEDED |
| `test_p2_optimization_truth` 12/13/14 (old CLI surface) | RT tests | tests/test_p2_optimization_truth.py | DELETED 12/13 (superseded by p1 repeatability test); 14 REJECTED (contradicts canonical identical-bytes contract) | SUPERSEDED/REJECTED |
| `test_ap02` backend-failure intent | RT tests | tests/test_p2_optimization_truth.py | PORTED to canonical seam (`execute_prepared_booksim` injection) | COPY_AND_ADAPT |
| `test_p2_optimization_truth` remainder (41 tests: R1/C1-C4/AP-series mechanics over the live package) | RT tests | same path | KEEP collecting (tests single-copy production modules through the canonical backend where live) | KEEP_CANONICAL |
| `test_p2_real_adapter` (incl. live `optimize_certified` grid) | RT tests | same path | KEEP collecting (passes live; `RealCandidateEvaluator` is canonical load-bearing) | KEEP_CANONICAL |
| `RealCandidateEvaluator` | RT `26e6f9dc` | veritx_dse/optimization/real_evaluator.py | same path (sole certified evaluator; owns §26 live path) | KEEP_CANONICAL (not legacy: `Optimizer.optimize_certified` constructs it) |
| `CandidateEvaluation` / `CandidateEvaluationPort` / `AUTHORITY_*` taxonomy | RT `26e6f9dc` | veritx_dse/optimization/evaluators.py | same path (live record/port/label vocabulary of the single implementation) | KEEP_CANONICAL |
| `FakeDeterministicEvaluator` | RT `26e6f9dc` | veritx_dse/optimization/evaluators.py | same path (analytic test-double; structurally barred from certified Pareto by C4 tests) | KEEP_CANONICAL (test-support; not an authority) |
| selection-identity (`none` vs `min_first_objective` vs `lexicographic`) | new (thin) | tests/test_optimization_definition_identity.py | new file (no production change; `definition_id()` already binds `selection`) | COPY_AND_ADAPT (test-only) |
| `selection_metric_order` field | — | — | does not exist in this tree; lexicographic selection orders by declared objective sequence | OUT-OF-SCOPE (vocabulary gap, not a defect) |
| `OptimizationResult` persist/reload API | — | — | does not exist in this tree; result reload is covered at the evidence layer (p1 digests equality + reload gate) | OUT-OF-SCOPE (vocabulary gap, not a defect) |

### Synthesis (§15)

| Capability | Source | Source path | Destination | Status |
|------------|--------|-------------|-------------|--------|
| analytical/event objective code | P1 | synthesis/event_objective.py | same (future real-adapter fallback candidate, not active authority) | RETAIN_RESEARCH |
| bo/iterative/milp synthesizers | P1 | synthesis/*.py | same (legacy generators, unwired) | RETAIN_RESEARCH |
| canonical FabricCompiler authority | canonical | application/fabric_compiler.py (single class) | unchanged; optimization/ never sets routing/VC | KEEP_CANONICAL |

### Studio (§16)

| Capability | Source | Source path | Destination | Status |
|------------|--------|-------------|-------------|--------|
| UI (DesignEditor/FabricCanvas/Evaluate/Optimize/Verify) + schemas + fixtures + validation | RT `26e6f9dc` | apps/studio/ (26 files) | same paths | COPY_VERBATIM (fixtures validate 5/5; 6 contract tests pass) |
| engine tools (chakra_to_dse, deadlock_routing, flow_certifier, fixture generator, ...) | RT `26e6f9dc` | veritx_dse/tools/ (8 files) | same paths | COPY_VERBATIM |
| example workloads | RT `26e6f9dc` | tracks/t3-topology/examples/llama_dense_*.json (2 files) | same paths | COPY_VERBATIM |
| live gateway (fixture boundary → integrated application layer) | new (thin) | apps/studio/src/ boundary | fixture mode kept deterministic | OUT-OF-SCOPE (fixture contract 6/6 + 5/5 validate; live study feed not demonstrated end-to-end this slice) |

Studio §27 gate (render a live study) not executed this slice; recorded as a known limitation in the seal report.

### RTL (§17)

| Capability | Source | Source path | Destination | Status |
|------------|--------|-------------|-------------|--------|
| 2D/two-die (router/mesh/nic/noc_2die/noc_pkg/islip) | T3 backup `f8ab4a63` | tracks/t3-topology/rtl/*.sv | tracks/t3-topology/rtl/t3/ (verbatim quarantine) | RETAIN_RESEARCH |
| testbench | T3 backup `f8ab4a63` | tracks/t3-topology/tb/noc_tb.sv | tracks/t3-topology/tb/noc_tb.sv | RETAIN_RESEARCH |
| binding audit | T3 backup `f8ab4a63` | docs/research/rtl-audit-2026-08-13.md | tracks/t3-topology/research/rtl-audit-2026-08-13.md | RETAIN_RESEARCH |
| 3D (functional-only) / 4D (unqualified stub) | T3 backup `f8ab4a63` | rtl/mesh_3d,router_3d,noc_3d_pkg,mesh_4d,router_4d | rtl/t3/ with README labels | RETAIN_RESEARCH (F5/F6 labeled) |
| F1–F3 multicast corners | audit | — | explicit limitation (README) | KNOWN UNSUPPORTED |

### Physical multicast (§18)

| Capability | Source | Source path | Destination | Status |
|------------|--------|-------------|-------------|--------|
| BookSim fork patch (mcast_k/naive/reduce_col/bcast_all) | T3 backup `f8ab4a63` | archive/booksim-ext/multicast.patch (300 ln) | archive/booksim-ext/multicast.patch | RETAIN_RESEARCH (NOT applied; optional fidelity mode only) |
| bandwidth model | T3 backup `f8ab4a63` | tracks/t3-topology/hardware/noc_multicast_bw.cpp | same path | RETAIN_RESEARCH |
| serving/prefix/multicast scripts | T3 backup `f8ab4a63` | tracks/t3-topology/scripts/*.py | tracks/t3-topology/scripts/research/*.py | RETAIN_RESEARCH |
| vLLM KV multicast experiments | T3 backup `f8ab4a63` | experiments/vllm_kv_multicast/ (5 files) | same path | RETAIN_RESEARCH |

Canonical MULTICAST stays replicated unicast; never called physical multicast.

### Multiplane research (§19)

| Capability | Source | Source path | Destination | Status |
|------------|--------|-------------|-------------|--------|
| plane cfgs (shared/data/control/cmesh/cmesh_ctrl) | T3 backup `f8ab4a63` | tracks/t3-topology/configs/plane_*.cfg (5 files) | same paths | RETAIN_RESEARCH |
| separation sweep | T3 backup `f8ab4a63` | tracks/t3-topology/scripts/plane_separation.py | tracks/t3-topology/scripts/research/plane_separation.py | RETAIN_RESEARCH |
| prior-art note | T3 backup `f8ab4a63` | tracks/t3-topology/research/monet-vs-plane-separation.md | same path | RETAIN_RESEARCH |

Research-only; no Fabric-plane abstraction forced.

### Canonical-seam adapters applied in this slice (why verbatim copy cannot compile)

| File | Adaptation | Reason |
|------|------------|--------|
| application/compile.py | v1 packet_format/router_behavior/make_fabric_artifact → canonical vc_resources_from_assignment + routing_realization + make_deterministic_fabric + make_resolved_deterministic_fabric | canonical FabricArtifact is the single fabric authority |
| model/resolved_bundle.py | dataclass moved to class; revalidate() via canonical validate_against_deterministic + re-derived vc_resource/realization | canonical validation interface changed |
| model/packet_format_v1.py, router_behavior_v1.py | deleted | v1 second authorities; compile.py no longer uses them |
| application/waved_resources.py, wave_e_resources.py, results.py | local Wave-C envelope shims (RESOURCE_SCHEMA_VERSION/check_envelope) | canonical resources.py owns 4-kind CompileIntent persistence; must not be overwritten |
| application/waved_resources.py | v1 readers fail closed (historical v1 wavedworkload/opgraph/messages/traffic unsupported; V2 only) | v1 authorities deleted per §4/§7 |
| application/waved_resources.py, results.py | method-or-attribute hash shims (resolved_fabric_hash/fabric_hash/packet_format_hash) | canonical v2 stores hashes as attributes; RT v1 as methods |
| backend/projection.py | binds PhysicalTrafficArtifactV2 (alias) | v1 traffic authority deleted; V2 carries same traffic/bundle surface |
| backend/producer.py | additive tool_identity property | RT evidence compatibility; canonical frozen dataclass unchanged |
| simulation/booksim.py | additive drain-verdict/counter parsing | qualified fork prints counters stock BookSim lacks |
| verification/reference_semantics.py | payload_width_bits function import | canonical packet format exposes function, not method |
| tests/test_wave_d_contract.py | presets→placement import; historical astra heuristic skipped | canonical placement authority; canonical refuses silent replication |
| tests/test_wave_d_{authenticity,semantics,physical,seal}.py | module-level historical skip | v1 authority deleted; V2 coverage in contract test |

Rejected/prohibited (not applied): workload/ v1 second authorities
(WaveDWorkload/WaveDOperation/v1 messages+traffic + BROADCAST weakening);
application/service.py + resources.py + store.py wholesale replacement;
full source_audit.py wholesale replacement (applied ADDITIVELY instead:
gated-site names added, canonical simple-audit API untouched);
RT→canonical evidence field mapping (rejected per §26 Option 2);
Wave-F BO/GRPO/MILP promotion; sparse AllToAllV;
new PP/PD/CXL/PIM models; RTL rewrite; wholesale branch merges.
