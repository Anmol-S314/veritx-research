# Studio Live Architecture (C9)

Status: **NOT BUILT**. `apps/studio` is the existing React/TypeScript
engineering tool (Design, Verify, Evaluate, Optimize) running on fixtures.
This file records the agreed shape of the live upgrade; the gap analysis
lives in `docs/validation/STUDIO-AUDIT-AND-GAP-REPORT.md`.

## Principle

Do not rewrite `apps/studio`. Replace fixture-only operation incrementally
with a thin gateway whose handlers call **canonical services only**. No
scientific semantics may live in HTTP code.

## Gateway (owed)

Preferred stack: FastAPI. Initial endpoints:

```text
POST /compile
POST /evaluate
POST /optimize

GET  /runs
GET  /runs/{id}
GET  /runs/{id}/evidence

GET  /workloads
GET  /qualification
```

Each handler:

1. parses the request into the canonical request type,
2. calls the same service the CLI calls (`SrotaControlPlane`,
   `RealCandidateEvaluator`/`Optimizer.optimize_certified`,
   the serving entry),
3. returns the versioned result, including the evidence ids needed for the
   UI trust panel.

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
