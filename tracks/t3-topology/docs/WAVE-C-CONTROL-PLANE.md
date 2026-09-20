# Wave-C Unified Control Plane — Architecture

Single spine for every product-facing request:

```text
intent -> compile -> plan -> lower -> execute -> evidence -> result -> compare
```

```text
                ┌────────────────────────────┐
                │ CLI / API / T3 / Python    │
                └─────────────┬──────────────┘
                              │
                              ▼
                ┌────────────────────────────┐
                │      CONTROL PLANE         │
                │                            │
                │ capabilities  validate     │
                │ compile  plan  evaluate    │
                │ run_study  compare         │
                │ inspect  list  diagnose    │
                └─────────────┬──────────────┘
                              │
               ┌──────────────┼──────────────┐
               │              │              │
               ▼              ▼              ▼
         Semantic         Resource       Capability /
         compiler          store           policy
               │
               ▼
         EvaluationPlan
               │
               ▼
           Experiment
               │
               ▼
            Attempt
               │
               ▼
       Wave-B Backend Chain
               │
               ▼
         EvidenceRef
               │
               ▼
       EvaluationResult
               │
         ┌─────┴──────┐
         ▼            ▼
      Study      Comparison
```

## 1. What Wave C owns (and does not)

Wave C owns **orchestration**: validate → resolve → compile → plan →
lower → prepare → execute → persist → compare. It derives NO semantic
truth: routes, VC assignment, packet formats, address decode, router
behavior, BookSim profile values and config semantics all stay in the
sealed Wave-B layers. A second semantic authority anywhere in Wave C
is a defect.

## 2. Resource model

| Resource | Identity | Notes |
|---|---|---|
| Intent | `intent_id` = H(semantic fields) | labels/paths excluded |
| CompiledDesign | content id over intent/design/mapping/fabric | references Wave-B hashes |
| WorkloadRecord | H(trace sha, bytes, endpoint universe) | bytes are the authority |
| EvaluationPlan | content id over design + workload + backend + seed + metrics | deterministic, path-free |
| ExperimentRecord | H(plan, config hash, input hash, mode) | producer excluded by rule |
| AttemptRecord | uuid7 | terminal single-write |
| EvaluationResult | H(experiment, attempt, evidence sha) | typed metrics + refs |
| StudyResult | H(name, candidate intents, comparison) | grouping, not a DAG |
| ComparisonResult | H(candidates, contract, metrics) | gate output |
| EvidenceRef | external `(path, sha256)` | Wave-B verified on reuse |

Every persisted resource carries `resource_type` / `schema_version` /
`resource_id`. Unsupported schema versions refuse.

## 3. Experiment vs attempt

- **Experiment**: "what scientific execution was requested" —
  deterministic for identical semantics (plan + config + input hashes).
  Same binary swap, same experiment; different producer provenance.
- **Attempt**: one concrete execution (uuid7), terminal states
  `SUCCEEDED / FAILED / TIMED_OUT / INTERRUPTED`, single-write,
  never mutated. Retry = new attempt. Resume = new attempt.

Lifecycle decision (reconciled with `core/runs.py`): Wave-C
`PLANNED` covers old `CREATED + VALIDATED` (validation evidence IS the
persisted plan/design); terminal states match; `CANCELLED` is modeled
as terminal `INTERRUPTED`/refusal at the service boundary (no async
workers exist to cancel); `resume` reinterprets as a new attempt.

## 4. Error taxonomy

`INVALID_INTENT / UNSUPPORTED_SEMANTICS / LOWERING_UNSUPPORTED /
EXECUTION_FAILED / EXECUTION_TIMEOUT / EVIDENCE_INVALID /
COMPARISON_INCOMPATIBLE / NO_FEASIBLE_DESIGN / POLICY_REJECTED /
NOT_FOUND / CONFLICT / INTERNAL_ERROR`.

Simulator crash, timeout, bad evidence and unsupported semantics are
never `NO_FEASIBLE_DESIGN`. That verdict comes only from
`summarize_study` over completed records: all measured candidates
violate binding constraints (crashes/timeouts → `INCONCLUSIVE`,
nothing measurable → `CONSTRAINT_UNMEASURABLE`, backend blocked →
`UNSUPPORTED`).

Policy budgets (`max_execution_seconds`, `max_study_candidates`,
`max_query_rows`) reject over-budget requests (`POLICY_REJECTED`);
nothing is silently clamped.

## 5. Capability registry

`application/capabilities.py` derives support from the sealed backend
modules: `BOOKSIM_STANDALONE` lowering + execution + route evidence
supported; `SERVING_BOOKSIM2` lowering + seam supported, execution
BLOCKED; analytical lowering-metadata only, execution UNSUPPORTED;
RTL/UVM/formal NOT_RUN. CLI/API/Studio read this registry; no
duplicate advertising lists.

## 6. Comparison gate

`ComparisonContract(kind, allowed_variations, metric_ids,
acknowledged_differences)`. Default `DESIGN_COMPARISON` lets the
fabric vary; workload, mapping, backend profile/semantics, execution
mode, seed policy, metric schema, producer binary and loss digests
must match unless explicitly varied (loss variation additionally
requires acknowledgement of the differing dimensions). Only
`SUCCEEDED`, supervised-transport, digest-verified, clean-tree
evidence compares. Output uses observed language
(`lower_observed`), never winner/best/optimal.

## 7. Safe reuse

Only `verify_reusable_evidence(EvidenceRef, …)` against the live
producer; success returns the stored result marked `reused: true`
(no fake new attempt). Anything else (stale ref, tamper, dirty
producer) falls through to a fresh attempt.

## 8. Surface migration

| Surface | Old path | New path | Status |
|---|---|---|---|
| CLI `service …` | — (new) | application service | AUTHORITATIVE |
| `api.service_*` | — (new) | application service | AUTHORITATIVE |
| Python `SrotaControlPlane` | — (new) | application service | AUTHORITATIVE |
| T3 `service …` / `t3_intent` | bash → CLI | forwarded/constructed intent | AUTHORITATIVE |
| CLI run/sweep/compare/evaluate-\* | own semantics | service group | LEGACY_INTERNAL |
| `api.execute/compare/get_run` | run_experiment/Runs | service_* wrappers | LEGACY_INTERNAL |
| `core/experiment.py` | Slice-A runner | service.evaluate | LEGACY_INTERNAL |
| `simulation/booksim.py` legacy | handcrafted cfgs | sealed backend chain | LEGACY_INTERNAL |
| `synthesis/*` search+evaluator | private evaluator | none (Wave-E science) | LEGACY_INTERNAL |
| `core/comparison.py` fingerprints | result-dir parsing | typed gate | LEGACY_INTERNAL |
| `model/presets.py` dicts | mutable presets | immutable registries | LEGACY_INTERNAL |
| `t3/scripts` analysis | Make pipeline | none (research-only) | LEGACY_INTERNAL |
| `core/store.py` SQLite | result index | search/index only | LEGACY_INTERNAL |
| test runner seam | unit tests | none (never product) | TEST_ONLY |

Legacy runs/results: `LEGACY_RESULT` — listable, inspectable,
never auto-upgraded to verified results.

## 9. Deferred scope (not Wave C)

Wave D (mapping/parallelism/collectives/memory/concurrency science),
Wave E (area/power/energy/synthesis/Studio explanations), RTL re-entry
(B3.6R/B3.8-HW), exotic topologies, prefill/decode, overlap DAGs,
serving execution, analytical execution. User-driven mapping variation
beyond derived rank placement is Wave-D scope; comparison already
carries `mapping_hash` so it will move when mappings do.

## 10. Wave C.1 integrity closure

- Verified result loading: scientific consumers never read
  `store.get("result")` directly. `load_verified_result` re-derives
every field from plan/experiment/attempt records, digest-authenticated
  Wave-B evidence and the metric registry; anything else refuses with
  `EVIDENCE_INVALID`.
- Workload content identity: intent identity carries the trace content
digest (same bytes at different paths share identity; different bytes
differ; stale explicit digests refuse). Resolved once per operation;
downstream stages never reread files.
- Reuse binds the CURRENT experiment (link/result/experiment/config/
input agreement) with Wave-B verification on current hashes, then
full result validation. Transplanted links re-execute fresh.
- Legacy scientific commands live under `veritx legacy …`
(`t3_mode: blocked`, T3-blocklisted); the public API advertises only
`service_*`; the field-only binding helper is private.
- Comparison and study identities are directional/order-preserving.
- Query over-budget refuses (`POLICY_REJECTED`); omitted limits default.
- `ControlPlaneError` is unfrozen (frozen exceptions cannot cross
generator context managers); intent/workload label collisions resolve
first-wins with semantic verification.
