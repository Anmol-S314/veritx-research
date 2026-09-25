# VERITX Studio — Product Flow Audit (UI0)

Status: **AUDIT DONE — no code changed.**
Worktree: `/home/datavex/veritx-studio-rebuild`
Branch: `rebuild/live-product-flow`
Baseline: `b2600851` (`github/prod/production-readiness`)
Date: 2026-09-25

This document is the UI0 deliverable required by the rebuild brief. It records
what exists **in tree at this SHA**, the exact current data flow, the broken
seams, and the target resource model. It does not propose a visual redesign and
does not change compiler/evaluator science.

Where a claim is a code fact it carries a `file:line` reference. Where it is a
judgement it is labelled.

---

## 1. Executive summary

The engineering core is in much better shape than the product surface. Canonical,
contract-producing authorities already exist and are tested:

- `FabricCompiler.compile(request) -> Compilation` (bundle **+ certificate**)
  — `tracks/t3-topology/dse/veritx_dse/application/fabric_compiler.py:59`.
- `views.design_view()` / `views.compilation_view()` — the product-view projector
  for `DesignView` / `CompilationView` (v1)
  — `tracks/t3-topology/dse/veritx_dse/application/views.py:35,71`.
- `FabricEvaluator.evaluate(compilation, workload_graph, options)` with
  `EvaluationOutcome.to_view_dict()` — `fabric_evaluator.py:347,215`.
- `authenticate_backend_evaluation` / `verify_authenticated_backend_evaluation`
  producing a canonical `RequirementReport` — `authenticated_evaluation.py:353,458`.
- `Optimizer.optimize_certified(...)` → `OptimizationResult.to_study_view()` (v2)
  — `optimization/result.py:685,548`.
- `core/run_bundle.py` (`finalize_run_bundle` / `verify_run_bundle` / `bundle_id`)
  — `core/run_bundle.py:51,72,134`.
- `application/errors.py` — one typed control-plane taxonomy
  (`INVALID_INTENT`, `UNSUPPORTED_SEMANTICS`, `EXECUTION_FAILED`,
  `EVIDENCE_INVALID`, `CONFLICT`, `INTERNAL_ERROR`, …) — `errors.py:18`.

The live gateway (`tracks/t3-topology/dse/veritx_dse/gateway/app.py`) wires
almost **none** of the above into a product resource model:

- `/compile` runs `SrotaControlPlane` (which does **no verification**) and
  returns a hand-rolled flat hash bundle, not `CompilationView`
  (`app.py:68-103`).
- `/evaluate` takes a full raw `CompileRequestV3` in the request body and calls
  the **optimization** candidate evaluator, returning
  `{status, performance_result_id, objective_values, error}` — not an
  `EvaluationView`, not a `RequirementReport` (`app.py:213-232`).
- `/optimize` also takes a full raw `CompileRequestV3` (`app.py:234-262`).
- `/runs` scans a directory on disk and returns `run_id/status/bundle_id`
  (`app.py:106-124`).
- `/workloads` mixes fabric presets with validation experiments
  (`app.py:137-155`).
- `/qualification` returns a **hand-copied dict** that duplicates release facts
  (`gateway/qualification.py:10-51`).

There is **no** `Project`, `Draft`, `DesignRevision`, `Run`, `Job`, or
`OptimizationStudy` anywhere in the gateway or Studio (`grep` for
`ProjectView|RevisionView|JobView|WorkspaceView|DesignRevision` finds nothing
outside unrelated `attachment.py`/tests). Studio is fixture-backed for Design /
Verify / Evaluate / Optimize and live only for Runs / Trust
(`apps/studio/src/App.tsx:23`).

**The leverage is therefore high and the risk is low**: the rebuild is a thin
product-resource/continuity layer over existing authorities, not new science.
The one genuinely missing scientific-completeness decision is that the live
compile path does not verify (see S-02).

---

## 2. Authority of this document vs existing docs

- `docs/product/STUDIO-LIVE-ARCHITECTURE.md` says "GATEWAY BUILT; frontend
  wiring partial" and enumerates the current endpoints. Still accurate.
- `docs/validation/STUDIO-AUDIT-AND-GAP-REPORT.md` is **stale**:
  - G-01 claims "no [gateway] exists; no HTTP layer anywhere in `apps/`" — a
    gateway now exists (`gateway/app.py`).
  - S-06 claims "no RunBundle yet" — `core/run_bundle.py` now exists.
  The audit predates C9. This UI0 document supersedes its product-flow claims.
- `docs/production/AUTHORITY-MAP.md` is the scientific authority map. The
  product resources proposed here must obey it: one writer per concept, no second
  authority.

---

## 3. Current system map

| layer | location | state |
|---|---|---|
| Studio UI | `apps/studio/src/` | Vite + React 19 + TS, no router, no state lib |
| Studio contracts | `apps/studio/src/types.ts` | mirrors 5 frozen views; no Project/Revision/Run/Job |
| Studio fixtures | `apps/studio/fixtures/*.json` | 5 contract-validated fixtures |
| Gateway | `tracks/t3-topology/dse/veritx_dse/gateway/app.py` | FastAPI, 9 endpoints, no resources |
| Qualification | `gateway/qualification.py` | hard-coded duplicate of release facts |
| App services | `application/*.py` | canonical compile / evaluate / optimize / views |
| Run bundle | `core/run_bundle.py` | content-addressed bundle id + verification |
| Contracts | `contracts/srota/v1/*.json`, `v2/*.json` | frozen: Design/Compilation/Evaluation/Requirement v1, Study v2 |
| Existing gateway tests | `tracks/t3-topology/dse/tests/test_gateway.py` | endpoint mechanics only (8 tests) |
| Studio tests | `apps/studio/tests/test_studio_contract_v2.py` | fixture contract tests |

---

## 4. Current data flow (exact, as built)

### 4.1 Compile

```text
Studio DesignEditor (fixture only)
   └─ api.compile(preset, policy)            api.ts:97
        POST /gw/compile {preset, policy}
          app.py:174  _compile                    app.py:68
            _parse_override / CandidatePolicy     app.py:73-81
            SrotaControlPlane.compile(intent)     service.py:167
               derive_compile_request             service.py:178
               generate_baseline_candidate        service.py:194
               compile_deterministic_candidate    service.py:212
               store.commit_resolution            service.py:231
            ← flat dict of hashes + vc_count      app.py:91-103
```

Returned shape (NOT `CompilationView`, NOT a certificate):

```json
{ "intent_id": "...", "design_hash": "...", "resolved_fabric_hash": "...",
  "topology_hash": "...", "attachment_hash": "...", "mapping_hash": "...",
  "route_hash": "...", "resolved_route_hash": "...", "vc_assignment_hash": "...",
  "fabric_hash": "...", "vc_count": 4 }
```

Key facts:

- `SrotaControlPlane` **does not verify**. The CLI says so explicitly:
  `commands_compile.py:162` prints `Verification: not performed`.
- `FabricCompiler.compile` (which produces the certificate that `CompilationView`
  needs) is **not on this path**.
- The live `CompiledFabric` is returned but discarded by the gateway; only hashes
  survive (`app.py:91-103`).

### 4.2 Evaluate

```text
POST /gw/evaluate {request: <full CompileRequestV3>, patch}
   app.py:213
     _require_binary()  -> 503 if unset                app.py:205-211
     CompileRequestV3.from_dict(body.request)          app.py:222
     RealCandidateEvaluator(...).evaluate(             app.py:225-228
         make_candidate(request, patch))
     ← {status, performance_result_id, objective_values, error}
```

Key facts:

- The client must **reconstruct the entire engine request**; compile output does
  not feed it. This is the brief's central seam.
- The evaluator used is `optimization/real_evaluator.py:122`
  (`RealCandidateEvaluator`), not the canonical `FabricEvaluator` and not the
  authenticated path. Its return shape is a `CandidateEvaluation`, not
  `EvaluationView` + `RequirementReport`.
- Runs are written under `runs_root/_evaluate` (`app.py:226`), which is a
  **different tree** from the `/runs` listing root (`runs_root`), so an
  evaluation does not naturally appear as a Run.

### 4.3 Optimize

```text
POST /gw/optimize {request: <full CompileRequestV3>, domain, objectives, constraints}
   app.py:234
     Optimizer().optimize_certified(request, definition, backend_config)
     ← result.to_study_view()  (OptimizationStudyView v2)     app.py:262
```

`OptimizationStudyView` **is** returned correctly shaped, but:
- it is keyed only by `base_design_hash`; there is no `base_revision_id`
  (`types.ts:228`);
- candidate runs carry `performance_result_id` but no link to a `RunBundle`
  or `run_id` (`types.ts:190-194`).

### 4.4 Runs

```text
GET /gw/runs                               app.py:178
   _list_runs: iterate runs_root children with checksums.json   app.py:106-124
   ← [{run_id, status: VERIFIED|INVALID|UNVERIFIED, bundle_id, file_count, reason}]
```

No `revision_id`, `workload_id`, `backend`, `design_hash`, no metrics. The UI
shows a filesystem-style id and a status (`LiveView.tsx:178-195`).

### 4.5 Qualification / workloads

```text
GET /gw/qualification -> hard-coded dict            qualification.py:61
GET /gw/workloads     -> preset_names() (FABRIC presets) + validation experiments app.py:137-155
```

`preset_names()` are mesh presets (`application/compile_intent.py:193`), so the
live "workload" list is actually geometry presets plus V-experiments. There is
no real workload catalog.

---

## 5. Broken seams (the defects this rebuild exists to fix)

| id | seam | evidence | consequence | brief stop condition |
|---|---|---|---|---|
| S-01 | **No product resources.** No Project/Draft/Revision/Run/Job/Study model; state is implicit in files and hashes. | grep finds none; `app.py` is stateless per call | Studio cannot know "what am I looking at"; refresh loses context | §54 "two resources claim same identity" (latent) |
| S-02 | **Live compile does not verify.** Gateway uses the non-certifying `SrotaControlPlane` path and discards the `CompiledFabric`. | `app.py:85-86`; `commands_compile.py:162` | `VerifyView` (10 obligations) can never be rendered live; certificate is fixture-only | §54 "Studio must reconstruct engine semantics" |
| S-03 | **Two compile authorities coexist** (engineering, not product): `FabricCompiler.compile -> Compilation(+certificate)` vs `SrotaControlPlane.compile -> CompileOutcome(no certificate)`. | `fabric_compiler.py:59` vs `service.py:167` | The product must pick one canonical compile that yields a certifyable bundle, or the Revision can't own verification | §54 "two resources claim ownership of the same identity" |
| S-04 | **Compile output is hashes, not `CompilationView`.** Canonical projector exists but is unused by the gateway. | `app.py:91-103` vs `views.py:35` | Frozen view contract is bypassed by a second hand-written representation | §5 "do not return a different hand-written gateway representation" |
| S-05 | **Evaluate re-requires raw `CompileRequestV3`.** | `EvaluateBody.request` `app.py:55-57,222` | Compile output does not become evaluation input; raw engine schema leaks into the UI boundary | §11 "NOT the entire CompileRequestV3 again" |
| S-06 | **Evaluate returns a candidate result, not `EvaluationView` + `RequirementReport`.** | `app.py:229-232` | Simulate/Run detail cannot show metrics, windows, producer, evidence, requirements | §11, §13 |
| S-07 | **Evaluation is not a Run.** Writes to `_evaluate`, not the `/runs` authority; no bundle. | `app.py:226` vs `app.py:106-124` | No first-class `Run`; evidence not durable as a run | §12, §35 |
| S-08 | **`/runs` is a filesystem scan.** | `app.py:111-113` | Users browse directories; no filter by project/revision/workload/backend | §12, §30 |
| S-09 | **No Job model.** `/evaluate` and `/optimize` hold one HTTP request open. | `app.py:213,234` | Multi-minute simulation blocks the browser; no QUEUED/RUNNING/FAILED lifecycle | §11, §34 |
| S-10 | **Workloads = fabric presets + experiments.** | `app.py:137-155` | Concept collision; validation experiments look like user workloads | §15 |
| S-11 | **Qualification is a hand-copied duplicate of release facts.** | `qualification.py:4-5,10-51` | Drift risk already demonstrated; two authorities for the same claim | §19, §54 |
| S-12 | **Error laundering.** Broad `except Exception` maps programmer faults to 400/422. | `app.py:82-83,87-89,222-224,254-255` | `ValueError`/`TypeError`/`AttributeError` from trusted code become "INVALID/UNSUPPORTED" user errors | §20, §47, §48 |
| S-13 | **Studio has no router / no deep linking / no active-context state.** | `App.tsx` uses `useState` only; no react-router in `package.json` | Refresh loses context; no shareable product state | §23, §41 |
| S-14 | **Fixture mode is the default, not an explicit demo mode.** | `App.tsx:26,46,98-118` | Fixtures can be mistaken for live; offline silently degrades to fixtures | §31 |

---

## 6. Duplicate concepts and raw-engine leakage

- **Compilation facts exist twice**: once canonically as `CompilationView`
  (`views.py:35`), once hand-rolled as a flat dict in the gateway
  (`app.py:91-103`). §5 forbids this.
- **Evaluation facts exist twice**: `EvaluationView` (`fabric_evaluator.py:215`)
  and the gateway's `RealCandidateEvaluator` response (`app.py:229-232`).
- **`CompileRequestV3` is a UI transport type** in the current gateway
  (`EvaluateBody.request`, `OptimizeBody.request`). The frozen `CompilationView`
  / `DesignView` were built precisely so the UI never sees it.
- **Hashes leak as the primary payload** (9 hashes on `/compile`), which is
  exactly the "hash soup" §39 warns against. The human-readable fabric summary
  (8×8 mesh, DOR XY, 128-bit, 4 VC) is not projected at all.
- **`intent_id` is the closest thing to an identity**, but it is deterministic
  from the intent and carries no project scope, so it cannot serve as a
  project-scoped `revision_id`.

---

## 7. Contract mismatches (frozen views vs live gateway)

| view (frozen) | produced by | live gateway returns | gap |
|---|---|---|---|
| `DesignView` v1 | `views.design_view` | nothing | 100% fixture |
| `CompilationView` v1 | `views.compilation_view` | flat hash dict | status/certificate/obligations/artifact_hashes all missing |
| `EvaluationView` v1 | `EvaluationOutcome.to_view_dict` | `{status, performance_result_id, ...}` | design_hash/workload_id/producer/evidence/metrics/window missing |
| `RequirementReport` v1 | evaluator report dict | nothing | missing |
| `OptimizationStudyView` v2 | `OptimizationResult.to_study_view` | returned | no `base_revision_id`; candidates not linked to runs/bundles |

`tsconfig`/types mirror all four v1 views plus v2 study (`types.ts`), so Studio is
ready to render the real shapes — it simply never receives them on a live path.

---

## 8. Target product model

One understandable progression, exactly one owner per concept:

```text
INTENT -> COMPILE -> VERIFY -> SIMULATE -> COMPARE / OPTIMIZE -> INSPECT EVIDENCE
```

### 8.1 Resources

**Project** — logical workspace, filesystem-backed. No Postgres/Redis.
`project_id`, `name`, `created_at`, `active_revision_id`, `revision_ids`,
`run_ids`, `optimization_ids`.

**Draft** — mutable user intent. Editable: `workload`, `system`/agents,
`requirements`, `parallelism`, NoC guided knobs. Derived artifacts are never
stored on the Draft. A Draft becomes `DIRTY` when edited after its last compile.

**DesignRevision** — immutable snapshot created by compile. `revision_id`
(project-scoped human identity, e.g. `r-04`), `project_id`, canonical request,
`design_hash` (machine identity), `created_at`. Never mutated.

**Compilation** — belongs to one revision; carries the existing `DesignView` +
`CompilationView` (status, `certificate_id`, `certificate_overall`,
`obligations`, `artifact_hashes`). This is where Verify reads from.

**Run** — one evaluation of one immutable revision. `run_id`, `bundle_id`,
`revision_id`, workload identity, backend, status, `EvaluationView`,
`RequirementReport`, evidence references. Maps to the durable `RunBundle`.

**OptimizationStudy** — optimization over one `base_revision_id`; carries the v2
`OptimizationStudyView` plus candidate run references and the selected candidate.

**Job** — long-running operation (evaluation / optimization / serving). States:
`QUEUED, PREPARING, RUNNING, FINALIZING, COMPLETED, REFUSED, FAILED, CANCELLED`.
Compile may stay synchronous. Simulation must not hold one HTTP request.

### 8.2 Product graph

```text
Project
  ├── Draft
  ├── DesignRevision A (immutable)
  │      ├── Compilation ── VerificationCertificate
  │      ├── Run 1 ── RunBundle ── EvaluationView + RequirementReport + evidence
  │      ├── Run 2
  │      └── OptimizationStudy 1
  │             ├── Candidate Run A
  │             ├── Candidate Run B
  │             └── Selected Candidate
  └── DesignRevision B
         ...
```

---

## 9. New linkage contracts (resource/linkage only)

These envelop the **existing** scientific views; they must not duplicate
`DesignView` / `CompilationView` / `EvaluationView` fields. Name decision:
use **`ProjectView`** consistently (not `WorkspaceView`).

```jsonc
// ProjectView
{
  "contract_version": 1,
  "project": { "project_id": "...", "name": "...", "created_at": "..." },
  "active_revision_id": "r-04",
  "revisions": ["r-01", "r-02", "r-03", "r-04"],
  "runs": ["run-...", "..."],
  "optimizations": ["opt-..."],
  "draft": { "dirty": true, "based_on_revision_id": "r-03" },
  "flow": {
    "state": "COMPILED",              // see §10
    "next_action": "RUN_EVALUATION"
  }
}

// RevisionView (+ Compilation envelope)
{
  "contract_version": 1,
  "revision_id": "r-04",
  "project_id": "...",
  "design_hash": "sha256:...",
  "created_at": "...",
  "design": { /* real DesignView v1 object */ },
  "compilation": { /* real CompilationView v1 object */ },
  "certificate": { /* certificate_id, overall, obligations */ }
}

// RunView
{
  "contract_version": 1,
  "run_id": "run-...",
  "bundle_id": "sha256:...",
  "project_id": "...",
  "revision_id": "r-04",
  "design_hash": "sha256:...",
  "workload": { "workload_id": "...", "display_name": "..." },
  "backend": "...",
  "status": "QUALIFIED",
  "started_at": "...", "completed_at": "...",
  "evaluation": { /* real EvaluationView v1 object */ },
  "requirements": { /* real RequirementReport v1 object */ },
  "evidence_refs": { "evidence_id": "...", "run_bundle": "sha256:..." }
}

// JobView
{
  "contract_version": 1,
  "job_id": "job-...",
  "kind": "EVALUATION",             // EVALUATION | OPTIMIZATION | SERVING
  "state": "RUNNING",               // §10
  "submitted_at": "...", "updated_at": "...",
  "revision_id": "r-04",
  "error_code": null, "error_message": null,
  "result": { "run_id": "run-..." } // or optimization_id
}

// OptimizationEnvelope
{
  "contract_version": 1,
  "optimization_id": "opt-...",
  "project_id": "...",
  "base_revision_id": "r-04",
  "study": { /* real OptimizationStudyView v2 object */ },
  "candidate_runs": [{ "candidate_id": "...", "run_id": "run-..." }],
  "selected_candidate_id": "..."
}

// QualificationView / WorkloadCatalogView / FabricPresetCatalogView
// ComparisonView (later)
```

Also needed: `EvidenceView` (per-run evidence chain) and
`FabricPresetCatalogView` separated from `WorkloadCatalogView` (§15).

---

## 10. Product state machine (gateway-owned; React renders, never infers)

```text
DRAFT
DIRTY                 (draft edited after last compile)
COMPILED
VERIFIED
EVALUATION_QUEUED
EVALUATING
EVALUATED
EVALUATION_FAILED
OPTIMIZING
```

Rules:
- The engine/gateway emits `flow.state` and `flow.next_action` explicitly
  (`ProjectView` / `RevisionView`). React must never derive
  "no evaluation object => NOT_RUN".
- Editing the Draft after compile: the existing revision stays valid; the Draft
  shows `STALE / RECOMPILE REQUIRED`. Old runs stay attached to the old revision.
- `COMPILED` vs `VERIFIED` distinguish "structural compile succeeded" from
  "certificate PASS". (Because the canonical compile already runs the
  certificate, S-03 must be resolved so this mapping is unambiguous.)

---

## 11. HTTP boundary mapping (replaces error laundering)

| typed failure | HTTP |
|---|---|
| `INVALID_INTENT` | 400 |
| `UNSUPPORTED_SEMANTICS` / `LOWERING_UNSUPPORTED` | 422 |
| `EVIDENCE_INVALID` / `EXECUTION_FAILED` / `EXECUTION_TIMEOUT` (job result) | represented in `JobView.state`, not as 4xx/5xx after a job starts |
| `CONFLICT` | 409 |
| `NOT_FOUND` | 404 |
| Backend unavailable | 503 |
| unexpected `Exception` (programmer fault) | **500**, logged with request id; never 400/422 |

The gateway must map exactly `ControlPlaneError.code` (`errors.py:18`) at the
HTTP boundary and let everything else escape to the framework 500 handler.
Adversarial tests must inject `ValueError`/`TypeError`/`RuntimeError`/
`AttributeError` from trusted internal seams and assert they are **not**
400/422/UNSUPPORTED/INVALID.

---

## 12. Ownership rules (reinforces brief §21)

Allowed in `gateway/`: parse HTTP, validate API shape, load resources, invoke
application services, project canonical product views, map typed failures to
HTTP.

Forbidden in `gateway/`: derive routes, calculate metrics, decide Pareto
membership, invent qualification, count packets, derive workload messages,
independently validate science. **Zero new scientific authorities.**

---

## 13. Qualification authority

Replace `gateway/qualification.py`'s hand-copied dict with one machine-readable
authority (e.g. `ENGINE-QUALIFICATION.json`, generated/validated at release)
carrying `backend`, `integration`, `numerical`, `independence`,
`qualified_domains`, `limitations`, `validation_sha`. Studio and gateway consume
the same file. Do not parse `docs/production/ENGINE-QUALIFICATION.md` at runtime.
ASTRA must read `Integration: QUALIFIED`, `Numerical timing: NOT_ESTABLISHED`
until C6 closes it.

---

## 14. Studio information architecture (target)

Main navigation: `Overview · Workload · Design · Compile & Verify · Simulate ·
Compare · Optimize · Runs · Trust`.

- Persistent context header (project / revision / workload / fabric / latest run).
- Primary workflow stepper with per-stage `NOT STARTED / READY / RUNNING /
  COMPLETE / REFUSED / STALE`.
- Overview answers: current revision, verification, latest run, qualification,
  next action.
- Run detail is the trust center; every key metric offers "Why can I trust
  this?" opening producer / route observation / evidence / RunBundle.
- Reduce hash soup: human summary first, hashes in expandable evidence.
- Explicit modes: `LIVE` default, `OFFLINE DEMO` explicit; no silent fixture
  fallback.
- One typed API client module (`src/api/{client,projects,revisions,jobs,runs,
  optimization}.ts`); no `fetch()` scattered in components; no Python models in
  React.
- Deep linking: `/projects/{id}/revisions/{rid}`, `/runs/{id}`,
  `/optimizations/{id}`; refresh preserves context.

Visual language stays: semiconductor engineering tool, dense but readable, flat,
dark/light, monospace identities, real units/diagrams. Avoid glassmorphism,
gradients, glow, decorative charts.

**UI skills**: UI phases (UI4+) will consult `github.com/ibelick/ui-skills`
(design-engineering skills registry; MCP at `ui-skills.com/mcp`) for baseline UI
and interaction guidance. This UI0 audit does not install or apply them.

---

## 15. Migration phases (mapped to the brief §51/§52)

| phase | scope | commit |
|---|---|---|
| UI0 | this audit + product state model | `UI0 audit + product state model` |
| UI1 | Project/Draft/DesignRevision/Run/Job + versioned linkage views + contract tests | `UI1 product contracts` |
| UI2 | gateway resource endpoints under `/api/v1`; legacy routes marked | `UI2 project/revision gateway` |
| UI3 | live compile + verify (`DesignView` + `CompilationView` + certificate) | `UI5 live compile + verify` |
| UI4 | jobs + evaluate + RunBundle + RunView/evidence | `UI6 live evaluate + run inspector` |
| UI5 | Compare | `UI7 compare` |
| UI6 | live optimization from `base_revision_id` | `UI8 optimize` |
| UI7 | Workload + Trust + Qualification authority | `UI9 workload + trust` |
| UI8 | fixtures become explicit Offline Demo | — |
| UI9 | browser E2E against a real qualified BookSim | `UI10 browser E2E` |
| UI10 | docs/demo runbook | `UI11 docs/demo runbook` |

First milestone only (§55): **Create/open Project → Edit Draft → Compile →
immutable DesignRevision → DesignView → CompilationView → VerifyView.** No
fixtures, no manual JSON, no raw `CompileRequestV3` in React.

---

## 16. Open decisions requiring the product owner

1. **Canonical product compile path (blocks S-02/S-03).** Options:
   (a) invoke `FabricCompiler.compile` for the Revision and persist its bundle +
       certificate (recommended: it already yields `CompilationView`);
   (b) run `SrotaControlPlane.compile` then `verify_compiled_fabric` on its
       compiled bundle (keeps the current store commit path).
   One must be chosen so a Revision owns exactly one certification authority.
2. **Filesystem layout for projects/revisions/jobs.** Extend `VERITX_STORE_ROOT`
   vs a new `VERITX_PROJECTS_ROOT`. Must remain filesystem-backed.
3. **Run id authority.** Reuse `core/runs.py` `new_run_id()` + `core/run_bundle.py`
   `bundle_id` (recommended) vs a new run id. Must not create a second run
   identity authority.
4. **Legacy route retention.** Keep `/compile`,`/evaluate`,`/optimize`,`/runs`,
   `/workloads`,`/qualification` as deprecated aliases for one release, or cut
   immediately? Brief §42 says version, don't break casually.

---

## 17. Acceptance / stop conditions

Do not proceed if any holds (brief §54): two resources own one identity; Studio
must reconstruct engine semantics; the gateway calculates science; evaluation is
not tied to an immutable revision; a Run cannot be traced to one revision and
workload; edited Draft shows stale results as current; an internal exception
becomes user INVALID/UNSUPPORTED; the UI qualification contradicts release
qualification; the browser flow needs manual JSON; fixtures are presented as
live.

The finished first milestone is clean when a hardware/system engineer can do the
flow in §49 of the brief without repository knowledge, copying JSON, knowing
`CompileRequestV3`, knowing a filesystem path, or typing a hash.
