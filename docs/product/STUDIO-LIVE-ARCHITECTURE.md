# Studio Live Architecture (C9)

Status: **GATEWAY LIVE for the design→compile→evaluate path; frontend wiring
partial**. `apps/studio` is the existing React/TypeScript engineering tool
(Design, Verify, Evaluate, Optimize). The live FastAPI gateway at
`veritx_dse/gateway/app.py` now owns **immutable design revisions**, so later
stages name a revision instead of resubmitting raw engine JSON. The Runs and
Trust sections are live in the React app; Design/Verify/Evaluate/Optimize are
still fixture-backed (offline demo). The gap analysis lives in
`docs/validation/STUDIO-AUDIT-AND-GAP-REPORT.md`.

## Principle

Do not rewrite `apps/studio`. Replace fixture-only operation incrementally
with a thin gateway whose handlers call **canonical services only**. No
scientific semantics may live in HTTP code.

## Gateway (LIVE)

Stack: FastAPI (`veritx_dse/gateway/app.py`). Endpoints:

```text
GET  /health
POST /compile          preset+policy+overrides, OR a v3 design request
                       -> DesignView + CompilationView + immutable revision_id
GET  /revisions        immutable revision ids
GET  /revisions/{id}   re-derives the canonical request; refuses compiler drift
POST /evaluate         {revision_id, patch} or a raw v3 request -> evaluator
POST /optimize         {revision_id, definition} or raw request -> certified study
GET  /runs             finalized bundles under the runs root, VERIFIED/INVALID
GET  /runs/{id}        bundle verification + manifest
GET  /runs/{id}/evidence
GET  /workloads        product presets + validation experiments
GET  /qualification    canonical qualification registry
```

Handlers parse, call the same canonical service the CLI calls, and return
the versioned result plus the evidence ids the trust panel needs. No
scientific semantics live in HTTP code. `/evaluate` and `/optimize` return
503 until a qualified backend is configured (`VERITX_BOOKSIM_BIN`).

**Error taxonomy (R3.14).** Only typed failures map to 4xx/503: `InvalidInput`
-> 400, `UnsupportedSemantics` -> 422, `BackendUnavailable` -> 503,
`Conflict` -> 409, `NotFound` -> 404. Any programmer fault
(`ValueError`/`TypeError`/`RuntimeError`/`AttributeError`) is a logged 500 and
`INTERNAL_ERROR`; internals are never leaked.

**Revision continuity (R3.2/R3.4/R3.6).** `/compile` returns a
`revision_id` that is a content hash of the intent plus the compiled
identities. `/revisions/{id}` re-derives the canonical request and refuses if
the identities no longer match (compiler drift), so an old Run can never be
shown as the current revision. `/evaluate` and `/optimize` accept a
`revision_id`; raw `request` remains a compatibility path.

Config comes from the environment: `VERITX_STORE_ROOT`, `VERITX_RUNS_ROOT`,
`VERITX_REVISIONS_ROOT`, `VERITX_BOOKSIM_BIN`. Run with
`uvicorn veritx_dse.gateway.app:app`.

Tests: `tests/test_gateway.py`, `tests/test_gateway_errors.py` (taxonomy by
injection), `tests/test_gateway_revisions.py` (revision identity/continuity).

## Remaining C9 work (frontend)

- Point Design/Verify/Evaluate/Optimize at the gateway using the client
  functions already added in `src/api.ts` (`compileDesign`, `revision`,
  `evaluate`, `optimize`). Keep fixtures only as an explicit offline demo;
  when the gateway is unavailable the section must read
  `LIVE GATEWAY UNAVAILABLE`, never silently fall back to fixtures.
- A guided design-intent -> v3 request deriver so the UI can edit supported
  parameters without a raw `CompileRequestV3`. Until then the v3 design is an
  engine-authored template.
- Long-running job states, run detail/evidence list, and the "why can I trust
  this?" drawer wired to `/runs`.
- Browser E2E (currently absent).

### Offline-demo fixtures

`apps/studio/fixtures/*.json` remain an offline demo. Their regeneration
path (`generate_studio_fixtures.py`) imports
`application.product_evaluator`, which exists only on historical audit
branches, so regeneration is classified as unprovisioned in
`validate_fixtures.provisioned_environment`; the live product path is the
gateway. This is a non-blocking offline-demo gap.

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

