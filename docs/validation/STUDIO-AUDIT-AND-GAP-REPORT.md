# Studio Live-Product Audit and Program Gap Report

Status: DRAFT v1 (baseline audit spanning `prod/production-readiness`
`cf626566`…`bd973e6c` — includes the P0.10 route-observation closure)

Part 1 audits `apps/studio` against the live-product requirements. Part 2 is
the consolidated gap report (science / ASTRA / serving / frontend blockers).
No code was changed for this audit.

---

## Part 1 — Studio audit

### What exists (verified in tree)

- Vite + React + TypeScript, no heavy framework. `App.tsx` (122 lines) tabs
  across Design / Verify / Evaluate / Optimize.
- Contract-first: 5 fixtures validated by `scripts/validate_fixtures.py`
  against frozen view schemas (study view v2, others v1). `types.ts` (268
  lines) encodes the view contracts.
- Honest-state vocabulary already present:
  - `CompilationStatus = COMPILED | INVALID | UNSUPPORTED`
  - `ConstraintVerdict = SATISFIED | VIOLATED | UNMEASURABLE`
  - `ObjectiveAvailability = MEASURED | UNMEASURABLE`
  - `TierBadge: LOCKED | GUIDED | FREE`
  - muted `UNSUPPORTED` badge styling in `badges.tsx`
- FIXTURE MODE is explicit and loud: header badge with title text "No engine
  connectivity", fixture-bar selector, DesignEditor states plainly that edits
  do not recompile and LOCKED values are frozen.
- Evaluation fixture carries `backend_producer`, `evidence`,
  `fidelity_warning`, artifact IDs — the trust-chain raw material exists in
  the contract already.

### Gaps against the live product (§29–§53)

| # | requirement | gap | severity |
|---|-------------|-----|----------|
| G-01 | live gateway (§31) | none exists; no HTTP layer anywhere in `apps/` | BLOCKER (frontend) |
| G-02 | job model QUEUED…CANCELLED (§33) | absent — fixtures are static documents | BLOCKER (frontend) |
| G-03 | WorkloadView (§36) | no workload view, no workload contracts | BLOCKER (frontend) |
| G-04 | run inspector (§45) | no run view; evaluation fixture shows evidence fields but no drill-down/evidence chain UI | BLOCKER (frontend) |
| G-05 | trust badges (§39) | no QUALIFIED/PARTIAL/INTEGRATION-ONLY/NOT-ESTABLISHED badge system; verdict vocabulary covers constraints, not scientific qualification | BLOCKER (frontend) |
| G-06 | trust/qualification page (§46) | absent | BLOCKER (frontend) |
| G-07 | comparison view (§43) | fixtures contain a study but no multi-run comparison surface; no explicit no-auto-winner rule in UI | MAJOR |
| G-08 | production workload dashboard (§42) | absent | MAJOR |
| G-09 | serving view (§41) | absent | MAJOR |
| G-10 | ASTRA dual-status display (§40) | no way to show "integration QUALIFIED + timing NOT ESTABLISHED" — needs new contract field before UI | MAJOR (depends on trust contract) |
| G-11 | STATICALLY_VERIFIED vs EXECUTED_ROUTE_OBSERVED routing distinction (§37) | absent; P0.10 closed (`c2748f9a`) so both statuses now exist and must never be rendered identically | MAJOR |
| G-12 | overlays gated on artifacts (§35, §50) | FabricCanvas draws declared topology only (good); needs DATA-NOT-AVAILABLE states for overlays when they land | MINOR (guard at build time) |
| G-13 | mode separation LIVE vs PRECOMPUTED (§47) | only FIXTURE MODE exists; must become explicit tri-state to avoid fixture-passing-as-live | BLOCKER (frontend) |
| G-14 | e2e browser acceptance test (§53) | none | MAJOR |

### Verdict

Studio is a good, honest fixture-mode console and must not be rewritten. The
trust vocabulary (verdicts, tiers, explicit unsupported states) maps cleanly
onto the required scientific trust badges; the main work is: gateway, job
model, three new views (Workload / Run / Trust), mode tri-state, and the
versioned contract extension that carries qualification status per metric.
UI work must wait for the trust contracts produced by Track A (§2) — in
particular G-05/G-10 need `PRODUCTION-CLAIMS.md` rows as their data source.

---

## Part 2 — Consolidated gap report

### Science blockers (Track A)

| id | blocker | closes claim | program ref |
|----|---------|--------------|-------------|
| S-01 | ~~P0.10 executed-route observation~~ **CLOSED** (`c2748f9a`, `bd973e6c`): first-hop dump compared destination-by-destination vs resolved route; `EXECUTED_ROUTE_OBSERVED` + `route_dump_sha256` recorded. Remaining: full-path (beyond-first-hop) observation | C-17 (first-hop scope) | §14 |
| S-01b | route observation covers mesh-DOR + AnyNet only; extend to other qualified routing classes and to full-path identity | C-17 full closure | §14 |
| S-02 | per-collective independent semantic audit (ALLGATHER / REDUCESCATTER / ALLTOALL / BROADCAST); F-0004 precedent: implementation-under-test must never be its own oracle | C-11 | §11 |
| S-03 | chunk-level collective data semantics not modeled (no chunk_id / reduction ownership / RS-AG reconstruction) — must remain declared as NETWORK-LEVEL; decide if a versioned chunk-identity artifact program is warranted | C-16 | §12 |
| S-04 | saturation regime unmeasurable: trace projection cannot inject >1 pkt/cycle (F-0003); need burst/sub-cycle injection or ASTRA-arrival driving | C-18 | §15 |
| S-05 | production workload corpus does not exist (only V01–V10 micro corpus); no manifests, no content addressing | all W1/W2/W3 | §5–§8 |
| S-06 | no RunBundle yet: run dirs are timestamped, not content-addressed (BLOCKER B5 in AUTHORITY-MAP); raw-artifact retention contract missing | reproducibility row of §59 | §27 |

### ASTRA validation blockers

| id | blocker | program ref |
|----|---------|-------------|
| A-01 | F-ASTRA-0001: unexplained dominant constant. Tiny fixture exposed comm = 30,310 c; production = 30,003,310 c. Delta = exactly 30,000,000 — round-constant signature (default / horizon / unit / config), not physics. Instrument W0-06 cycle-accounting before changing any parameter | §16–§17 |
| A-02 | no independent timing oracle for any ASTRA case; W0-07 must establish the shared-engine-differential-then-independent-oracle sequence | §18 |
| A-03 | no domain decomposition: one global NOT_ESTABLISHED; define ASTRA_P2P_SIMPLE / RING / COMPUTE_PLUS_COMM / MULTI_ROUND / SERVING / MOE and qualify separately | §19 |
| A-04 | no preregistered tolerance discipline for ASTRA comparisons yet | §24, §57 |

### Serving blockers

| id | blocker | program ref |
|----|---------|-------------|
| V-01 | S1 scheduling semantics unvalidated (no hand-checkable trace battery for arrivals→batch→retire, TTFT/latency definitions) | C-28/C-30, §20 |
| V-02 | S2 parallelism semantics unvalidated (no expected-operation tables for TP/DP/EP/MoE; rank-reuse / no-accidental-multiplication not independently checked) | C-27, §20 |
| V-03 | S3 round→execution correspondence not enforced corpus-wide (dispatched instance without execution evidence must fail) | C-29, §20 |
| V-04 | multi-instance liveness only partially exercised; per-instance progress ledger exists but no production-like long-run corpus evidence | C-31, §21 |
| V-05 | serving matrix (§22) not run; unsupported cells not yet enumerated | §22 |
| V-06 | hardware calibration layer absent; profiler data (RTXPRO6000 × 3 models × tp1/tp2) provenance must be recorded before use; only compare quantities both systems model | §23 |

### Frontend blockers

See Part 1 gaps G-01…G-14. Order of work after Track A contracts exist:
gateway → job model → LIVE/PRECOMPUTED/FIXTURE tri-state → contracts for
qualification → WorkloadView → RunView/EvidenceView → trust badges →
Trust page → production dashboard → comparison → e2e smoke.

### What we can defend today (honest summary for §59)

- Topology derivation, packet/flit conservation, BookSim completion cycles,
  ring-ALLREDUCE network-level lowering, RTL execution in-domain, Ramulator
  battery behavior: **qualified within declared domains**.
- Executed route identity (first hop): **YES — QUALIFIED (first-hop scope,
  mesh-DOR + AnyNet)** via P0.10 (`c2748f9a`); full-path identity
  **NOT ESTABLISHED**.
- ASTRA absolute cycles: **NO — NOT_ESTABLISHED, F-ASTRA-0001**.
- Serving TTFT/latency/throughput numbers, TP/DP/EP semantics:
  **NOT ESTABLISHED** (integration only).
- Reproducibility of evidence: **PARTIAL** (build manifests + evidence IDs
  exist; run dirs not content-addressed, B5 open).
- Independent audit of evidence: **PARTIAL** — corpus reports carry per-check
  authority labels, but production-workload artifacts are not retained yet.

Baseline evidence recorded 2026-09-25 at `cf626566` (+ P0.10 closure
`c2748f9a`/`bd973e6c` verified in tree, route-observation tests 9 PASS):
`validation.harness.run --all` → V01–V10 all PASS (per-check verdicts exact);
binary SHAs match BASELINE.md (booksim `936aeefd…`, AstraSim_BookSim2
`7d4bb435…`); engines battery PASS (ramulator 16/16, rtl_selfcheck,
astra_runtime execution-PASS with NOT_ESTABLISHED numerical validity); full
pytest suite 3661 passed / 24 skipped / 1 failed (F-0005, fixed).
