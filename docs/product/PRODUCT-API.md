# VERITX Studio Product API (v1)

The live product surface. Versioned under `/api/v1`; the older ad-hoc
routes (`/compile`, `/evaluate`, `/optimize`, `/runs`, `/workloads`,
`/qualification`) are retained as deprecated aliases for one release.

The gateway parses HTTP, validates API shape, loads resources, invokes
application services, projects canonical product views and maps typed
failures to HTTP. It derives no route, counts no packet and invents no
qualification.

## Resources

```text
Project  ── Draft
   │
   ├── DesignRevision ── Compilation ── VerificationCertificate
   │        ├── Run (RunBundle + EvaluationView + RequirementReport)
   │        └── OptimizationStudy (OptimizationStudyView + candidate runs)
   └── ...
Job      ── links to the Run / Optimization it produced
```

## Endpoints

| method | path | purpose |
|---|---|---|
| GET | `/api/v1/health` | liveness |
| GET | `/api/v1/qualification` | machine-readable engine qualification |
| GET | `/api/v1/catalog/workloads` | workload catalog (v3 request templates) |
| GET | `/api/v1/catalog/fabric-presets` | fabric presets (separate concept) |
| POST | `/api/v1/projects` | create a project from a workload |
| GET | `/api/v1/projects` | list projects |
| GET | `/api/v1/projects/{project_id}` | ProjectView (active revision, flow) |
| GET | `/api/v1/projects/{project_id}/draft` | DraftView |
| PUT | `/api/v1/projects/{project_id}/draft` | replace the draft request |
| POST | `/api/v1/projects/{project_id}/compile` | compile draft → RevisionView |
| GET | `/api/v1/revisions/{revision_id}` | RevisionView (Design+Compilation) |
| GET | `/api/v1/revisions/{revision_id}/compilation` | same envelope |
| POST | `/api/v1/revisions/{revision_id}/evaluate` | submit evaluation job |
| POST | `/api/v1/revisions/{revision_id}/optimize` | submit optimization job |
| GET | `/api/v1/jobs/{job_id}` | JobView (poll to terminal state) |
| GET | `/api/v1/runs` | list runs (`project_id`, `revision_id` filters) |
| GET | `/api/v1/runs/{run_id}` | RunView |
| GET | `/api/v1/runs/{run_id}/evidence` | evidence documents + artifact list |
| GET | `/api/v1/runs/{run_id}/artifacts` | the RunBundle checksum manifest |
| GET | `/api/v1/optimizations/{optimization_id}` | OptimizationView |
| GET | `/api/v1/compare?a=&b=` | ComparisonView (no automatic winner) |

## Linkage contracts

`ProjectView`, `RevisionView`, `DraftView`, `RunView`, `JobView`,
`OptimizationView`, `EvidenceView`, `QualificationView`,
`WorkloadCatalogView`, `FabricPresetCatalogView`, `ComparisonView`.

These **envelope** the frozen scientific views — they do not duplicate
`DesignView`, `CompilationView`, `EvaluationView`,
`RequirementReport`, or `OptimizationStudyView` (v2).

## Flow state machine (gateway-owned)

```text
DRAFT · DIRTY · COMPILED · VERIFIED · EVALUATION_QUEUED · EVALUATING
· EVALUATED · EVALUATION_FAILED · OPTIMIZING
```

`ProjectView.flow` carries `{state, next_action, reason}`. React renders
it and never infers a state from a missing object.

## Job lifecycle

```text
QUEUED -> PREPARING -> RUNNING -> FINALIZING -> COMPLETED
                                              | REFUSED | FAILED | CANCELLED
```

Jobs are filesystem-persisted and executed by an in-process worker pool.
No Redis/Celery. On gateway restart, non-terminal jobs are explicitly
marked `FAILED` (`interrupted by gateway restart`); they are never left
RUNNING.

## HTTP error boundary

| typed failure (`ControlPlaneError.code`) | HTTP |
|---|---|
| `INVALID_INTENT` | 400 |
| `UNSUPPORTED_SEMANTICS` / `LOWERING_UNSUPPORTED` / `POLICY_REJECTED` / `EVIDENCE_INVALID` | 422 |
| `NOT_FOUND` | 404 |
| `CONFLICT` | 409 |
| `EXECUTION_FAILED` (including backend unavailable) | 503 |
| `EXECUTION_TIMEOUT` | 504 |
| unexpected exception | 500 (`INTERNAL_ERROR`, `request_id`, logged) |

A programmer fault (`ValueError`/`TypeError`/`RuntimeError`/
`AttributeError` from trusted internal code) is **never** mapped to
400/422/INVALID/UNSUPPORTED. Adversarial tests pin this.

## Configuration

```text
VERITX_STORE_ROOT      compile store (default runs/studio-store)
VERITX_RUNS_ROOT       legacy runs root (deprecated routes)
VERITX_PROJECTS_ROOT   product resources (default <STORE_ROOT>/projects)
VERITX_BOOKSIM_BIN     qualified BookSim binary (required to evaluate/optimize)
```

Run: `uvicorn veritx_dse.gateway.app:app`.
