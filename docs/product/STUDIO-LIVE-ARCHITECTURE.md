# Studio Live Architecture

Status: **LIVE**. The product resource layer
(`veritx_dse/product/`) provides filesystem-backed Project / Draft /
DesignRevision / Run / Job / OptimizationStudy resources over the
canonical application services; the gateway exposes them under
`/api/v1`; `apps/studio` is wired to that API for the primary flow. The
old ad-hoc routes remain as deprecated aliases for one release. The
product-flow audit and target model live in
`docs/product/STUDIO-FLOW-AUDIT.md`; the API reference is
`docs/product/PRODUCT-API.md`.

## Principle

Do not rewrite `apps/studio`. Replace fixture-only operation incrementally
with a thin gateway whose handlers call **canonical services only**. No
scientific semantics may live in HTTP code. This still holds: the product
layer composes `FabricCompiler`, `FabricEvaluator`,
`RequirementEvaluator`, `Optimizer.optimize_certified` and
`core/run_bundle.py`; it derives nothing itself.

## Gateway

Stack: FastAPI (`veritx_dse/gateway/app.py`). Product endpoints:

```text
```text
GET  /api/v1/health
GET  /api/v1/qualification
GET  /api/v1/catalog/workloads
GET  /api/v1/catalog/fabric-presets
POST /api/v1/projects
GET  /api/v1/projects
GET  /api/v1/projects/{id}
GET  /api/v1/projects/{id}/draft
PUT  /api/v1/projects/{id}/draft
POST /api/v1/projects/{id}/compile
GET  /api/v1/revisions/{id}
GET  /api/v1/revisions/{id}/compilation
POST /api/v1/revisions/{id}/evaluate
POST /api/v1/revisions/{id}/optimize
GET  /api/v1/jobs/{id}
GET  /api/v1/runs
GET  /api/v1/runs/{id}
GET  /api/v1/runs/{id}/evidence
GET  /api/v1/runs/{id}/artifacts
GET  /api/v1/optimizations/{id}
GET  /api/v1/compare?a=&b=
```

Compile is synchronous (fast, and it runs the certificate). Evaluation
and optimization are jobs: submit returns `{job_id, state: QUEUED}` and
Studio polls `GET /api/v1/jobs/{id}` to a terminal state.

Config: `VERITX_STORE_ROOT`, `VERITX_RUNS_ROOT`, `VERITX_PROJECTS_ROOT`,
`VERITX_BOOKSIM_BIN`. Run `uvicorn veritx_dse.gateway.app:app`.

Tests: `tests/test_gateway.py` (endpoint mechanics),
`tests/test_product_workflow.py` (compile+verify, dirty-draft regression,
error boundary, catalog separation, qualification, live evaluation),
`apps/studio/tests/test_live_browser_e2e.py` (browser acceptance,
`VERITX_E2E=1`).

**Error taxonomy (R3.14, deprecated alias layer).** Only typed failures map
to 4xx/5xx: `InvalidInput` -> 400, `UnsupportedSemantics` -> 422,
`BackendUnavailable` -> 503, `Conflict` -> 409, `NotFound` -> 404. Any
programmer fault (`ValueError`/`TypeError`/`RuntimeError`/`AttributeError`)
is a logged 500 with code `INTERNAL_ERROR`; internals are never leaked.

**Revision continuity (R3.2/R3.4/R3.6, deprecated alias layer).** The alias
`/revisions/{id}` route re-derives the canonical request and refuses if the
identities no longer match (compiler drift), so an old Run can never be
shown as the current revision. Config additionally honours
`VERITX_REVISIONS_ROOT` for that store.

## Sections (target)

`DESIGN · WORKLOAD · VERIFY · SIMULATE · COMPARE · OPTIMIZE · RUNS · TRUST`.
Internal wave names must never reach the UI.

## Evidence-first UI

Every important metric exposes "why can I trust this?": backend, producer,
binary sha, recipe, fabric identity, workload identity, evidence id,
qualification and limitations. Example:

```text
ASTRA  Integration:      QUALIFIED
       Absolute timing:  NOT ESTABLISHED
```

## No fake visualization

Route overlay, VC overlay, utilization, power and traffic-class heatmaps
must not be shown unless real backend/artifact data exists; otherwise the
section reads `DATA NOT AVAILABLE`. This is the UI form of the program's
first principle: a displayed number must have evidence behind it.

## Dependency

C9 depends on C3 (`GET /runs` needs a durable run authority) and C7
(serving/metrics qualification). It must not begin while run identity is
ambiguous.

