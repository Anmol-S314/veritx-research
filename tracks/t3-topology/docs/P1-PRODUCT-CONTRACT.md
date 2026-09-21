# P1 Product Integration Contract (frozen)

**Status:** FROZEN — this document plus `contracts/srota/v1/` is the shared
integration base for P1B / P1C / P2 / P4 parallel development.

**Base:** P1A HEAD `ba3ac847` (chain `79103d84 → f4780021 → 252fa544 →
f5787e48 → 7ca69248 → ba3ac847`).
**Regression baseline:** `tracks/t3-topology/docs/P1A-BATTERY-BASELINE.json`
(commit `2c7a7061`, 52 failed / 10 errors known missing-binary cascades).
No new failed/error node IDs without individual justification.

**P3 (RTL / SystemC / UVM / SVA generation) is DEFERRED.** No new work
there; existing code stays compatible.

## 0. One authority per concept (binding)

| Concept | Authoritative implementation at freeze | Owner |
|---|---|---|
| `CompileRequest` (v2 schema + semantics) | `dse/veritx_dse/model/compile_model.py` | P1C (v3 successor only) |
| Resolved topology | `model/topology_artifact.py` (`TopologyArtifact`) | sealed (P1A) |
| Route authority (LOCKED DOR_XY, MESH/C_MESH; TORUS/RING typed refusal) | `model/routing.py::derive_route` + `core/route_artifact.py` | sealed (P1A) |
| VC authority (bound to resolved route) | `model/compile_model.py::derive_vc_assignment_artifact` + `model/vc_assignment.py` | sealed (P1A) |
| Bundle assembly (orchestration only, no semantics) | `application/compile.py::compile_bundle` → `model/resolved_bundle.py::ResolvedFabricBundle` (in-memory proof carrier, never persisted) | sealed (P1A) |
| `VerificationCertificate` (10 LOCKED obligations) | `verification/certificate.py` | P1B (provenance tightening only) |
| `WorkloadGraph` (canonical) | `workload/canonical_graph.py` | P1B/P1C consume; no fork |
| Logical messages | `workload/messages.py::LogicalMessageArtifactV2` | P1B consumes |
| Physical traffic | `workload/traffic.py::PhysicalTrafficArtifactV2` | P1B consumes |
| Pre-spawn gates / quiescence | `verification/gates.py` | P1B consumes |
| Backend qualification / producer identity | `backend/qualification.py`, `backend/producer.py`, `backend/contracts.py` | P1B consumes |
| Evidence authority | `backend/evidence.py::EvidenceArtifact` (no P1 duplicate) | P1B consumes |
| Performance result | `performance/result.py::build_performance_result` + `reverify_result`; window binding `performance/network.py::NetworkWindowBinding` | P1B consumes |
| Workload intent lowering | NEW `workload/intent_lowering.py` (P1C) | P1C |
| Requirement evaluation | NEW `application/requirements.py` (P1C) | P1C |
| Optimization search semantics | NEW `optimization/` (P2, replayed from `synthesis/` + `reference/target-architecture/.../optimization/`) | P2 |
| Studio | NEW `apps/studio/` (fixtures only until integration) | P4 |

No worker introduces a second CompileRequest, topology, route, VC,
WorkloadGraph, traffic, evidence, performance, or optimizer-result
authority without repository evidence that the existing one cannot serve.

## 1. Compilation (sealed P1A, consumed by all)

```python
FabricCompiler.compile(request: CompileRequest) -> Compilation
# application/fabric_compiler.py
```

`Compilation`: `{status, request, bundle, certificate, error}` —
`status ∈ {COMPILED, INVALID, UNSUPPORTED}`. `COMPILED` carries
`bundle: ResolvedFabricBundle` + passing `VerificationCertificate`.
`INVALID`/`UNSUPPORTED` carry evidence and **never a bundle**.
Pure function of the request: no environment state, no spawn, no backend.

`VerificationCertificate`: 10 obligations in `verification/certificate.py`
(`TOPOLOGY_CONNECTED … FABRIC_DAG_VALID`), `overall ∈ {PASS, FAIL}`,
content-addressed `certificate_id`, schema v1.

**Known gap (P1B TASK A1 owns):** `DEADLOCK_FREE` currently certifies with
`router_behavior_hash=""` (`certificate.py` vs
`channel_vc_cdg.certify_channel_vc_deadlock(..., router_behavior_hash)`).
P1B binds `bundle.router_behavior.router_behavior_hash()` with
tamper/transplant tests. No other worker touches the certificate path.

## 2. Evaluation (P1B builds, all consume the view)

```python
FabricEvaluator.evaluate(
    compilation: Compilation,
    workload: WorkloadGraph,          # canonical_graph.py authority
    options: EvaluationOptions,       # {backend, timeout_s, require_quiescence}
) -> EvaluationOutcome
# NEW: application/fabric_evaluator.py
```

Preconditions (typed refusal, no backend work until met):
`compilation.status == COMPILED` and `certificate.overall == PASS`.

Canonical chain (reuse, do not reimplement):
`WorkloadGraph → LogicalMessageArtifactV2 → PhysicalTrafficArtifactV2 →
gates.assert_workload_ready → BookSim projection → gates.verify_backend_quiescence →
EvidenceArtifact → NETWORK_TRAFFIC_WINDOW via NetworkWindowBinding v2 →
build_performance_result`.

Traffic-class admission gate (before spawn): every `LogicalMessage`
traffic class must exist in `VCAssignmentArtifact` with ≥1 legal VC
mapping to a routing class of the resolved route. Unknown class = typed
refusal, never silent VC0.

`EvaluationOutcome.status ∈ {EVALUATED, BACKEND_UNAVAILABLE, UNSUPPORTED, FAILED}`:
absent qualified BookSim producer → `BACKEND_UNAVAILABLE` (never
`FileNotFoundError`, never fabricated performance); execution failure →
`FAILED`; unprojectable semantics → `UNSUPPORTED`; valid evidence →
`EVALUATED`. Performance honesty: BookSim yields one aggregate
`NETWORK_TRAFFIC_WINDOW`, never per-operation latency; cycles-only unless
a valid network clock is established.

`EvaluationOutcome` binds at minimum: `resolved_fabric_hash`,
`workload_id`, `message_artifact_id`, `physical_traffic_id`, backend
producer identity, backend config/input hashes, raw evidence + stats
digests, `performance_result_id`.

## 3. Workload + requirements (P1C builds, no backend)

v2 gaps recorded at freeze (do not reinterpret v2):
`CollectiveOp.bytes_per_element` meaning unproven; `Requirement` has no
`traffic_class` (only `qos_class`); `DependencyGraph` class names ad hoc;
`Workload.trace_path` environment-sensitive.

```python
lower_compile_workload(request: CompileRequest) -> WorkloadGraph
# NEW: workload/intent_lowering.py — v3 semantics only; v2 interpretation frozen.

RequirementEvaluator.evaluate(
    request: CompileRequest,
    workload: WorkloadGraph,
    performance: PerformanceResult,    # already verified
) -> RequirementReport
# NEW: application/requirements.py
```

v3: new schema generation with explicit `CollectiveIntent(kind,
dimension, payload_bytes, traffic_class)`; TP/DP/EP/PP/GLOBAL-derived
deterministic rank groups; unified traffic-class namespace
(`traffic_class` identity vs `qos_class` policy); immutable workload
source reference (content digest, not mutable path). Typed refusal where
intent is under-specified — no fabricated roots, scopes, or phases.

`RequirementReport` entries: `{requirement_index, verdict,
required, measured, metric_authority, performance_result_id, reason}`
with `verdict ∈ {SATISFIED, VIOLATED, UNMEASURABLE, NOT_APPLICABLE}`.
Binding + `UNMEASURABLE` never passes.

## 4. Optimization (P2 builds above the compiler)

```python
Optimizer.optimize(
    base_request: CompileRequest,
    definition: OptimizationDefinition,
    evaluator: CandidateEvaluationPort,   # fake deterministic in-dev; real adapter at integration
) -> OptimizationResult
# NEW: optimization/{definition,candidate,search,constraints,pareto,result,evaluators}.py
```

`Candidate = base CompileRequest + GUIDED patch` (no anonymous hardware
dict as authority). Searchable: `link_width`, `concentration`, supported
`radix`, `rcu_enabled`, other explicitly GUIDED knobs. Forbidden:
routing algorithm, VC count, turn restrictions, escape VC — always
compiler-derived; every candidate recompiles LOCKED properties.
Deterministic search (enumeration/grid/bounded seeded random) before
Bayes/MILP. `OptimizationResult` binds base request identity, definition,
candidate/evaluation IDs, objective values, constraint verdicts, Pareto
membership, selection rationale. Execution order never changes candidate
identity.

Capability ledger first: audit `synthesis/*` + `wave-f/design-optimization`
+ `reference/target-architecture/.../optimization/` into
REPLAY / MOVE / SUPERSEDED / REIMPLEMENT / REJECT / HISTORICAL. No blind
Wave-F merge; `synthesis/` renamed only by moving proven concepts into
`optimization/`.

## 5. Studio (P4 builds against views + fixtures, never engine internals)

Source area: `apps/studio/`. Consumes **only** the language-neutral views
in `contracts/srota/v1/` (`CompilationView`, `EvaluationView`,
`RequirementReport`, `OptimizationStudyView`, `DesignView`) plus
contract-validated fixtures. Never imports Python engine modules.
Sections: Design / Verify / Evaluate / Optimize (no P3 Generate UI beyond
a disabled future indicator). LOCKED properties rendered read-only
(`Routing: DOR_XY 🔒 Derived`). Every fixture validates against the
frozen schemas.

## 6. Cross-boundary violations (coordinator stops immediately)

P1B editing `CompileRequest` schema · P1C spawning backends · P2 setting
routing/VCs directly · P4 importing engine internals · anyone touching
`synthesis/` compiler science outside P2's ledger · cosmetic
renames of `srota/wavee/*` hash domains or persisted `wave_d/wave_e` keys
(historical identity stays; no NEW Wave-D/E production names).

## 7. Integration order (sequential; implementation is parallel)

1. P1B → `integration/p1-product`: Compilation + WorkloadGraph →
   authenticated PerformanceResult. Full battery + baseline node-set delta.
2. P1C: wire request → lower → WorkloadGraph → evaluator → PerformanceResult
   → RequirementReport. Real end-to-end (mesh_dense_64).
3. P2: real `CandidateEvaluationPort` adapter (compile → lower → evaluate
   → requirements). No optimizer rewrites unless interface mismatch proven.
4. P4: gateway/API adapter from application product views to UI contracts.
   No React→Python-module calls.

Primary scenario `mesh_dense_64`: v3 request → compiler → certificate →
WorkloadGraph → messages → traffic → qualified BookSim → evidence →
PerformanceResult → RequirementReport → OptimizationResult → Studio view.
Verification half reopens persisted data, not just in-memory objects.
Metamorphic + adversarial suites per program §9–§10 land during
integration.
