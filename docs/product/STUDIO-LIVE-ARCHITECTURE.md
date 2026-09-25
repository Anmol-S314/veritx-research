# Studio Live Architecture (C9)

Status: **GATEWAY BUILT; frontend wiring partial**. `apps/studio` is the
existing React/TypeScript engineering tool (Design, Verify, Evaluate,
Optimize). The live FastAPI gateway now exists at
`veritx_dse/gateway/app.py`; the React app is still fixture-backed and is
to be pointed at the gateway incrementally. The gap analysis lives in
`docs/validation/STUDIO-AUDIT-AND-GAP-REPORT.md`.

## Principle

Do not rewrite `apps/studio`. Replace fixture-only operation incrementally
with a thin gateway whose handlers call **canonical services only**. No
scientific semantics may live in HTTP code.

## Gateway (BUILT)

Stack: FastAPI (`veritx_dse/gateway/app.py`). Endpoints:

```text
GET  /health
POST /compile          preset + policy + overrides -> SrotaControlPlane
POST /evaluate         v3 request + patch -> RealCandidateEvaluator
POST /optimize         v3 request + definition -> Optimizer.optimize_certified
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

Config comes from the environment: `VERITX_STORE_ROOT`, `VERITX_RUNS_ROOT`,
`VERITX_BOOKSIM_BIN`. Run with `uvicorn veritx_dse.gateway.app:app`.

Tests: `tests/test_gateway.py` (compile, runs listing/verification/invalid,
path-traversal refusal, qualification, workloads, 503 without backend).

## Remaining C9 work

- Point the React app at the gateway (replace `fixtures.ts` reads with API
  calls); add a vite dev proxy to the gateway. The sections
  (`DESIGN · WORKLOAD · VERIFY · SIMULATE · COMPARE · OPTIMIZE · RUNS ·
  TRUST`) and the evidence-first trust panel are to be wired to the
  endpoints above; no internal wave names may surface.

## Sections (target)

`DESIGN · WORKLOAD · VERIFY · SIMULATE · COMPARE · OPTIMIZE · RUNS · TRUST`.
Internal wave names must never reach the UI.

## Evidence-first UI

Every important metric exposes "why can I trust this?": backend, producer,
binary sha, recipe, fabric identity, workload identity, evidence id,
qualification and limitations. Example, until C6 changes it:

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
