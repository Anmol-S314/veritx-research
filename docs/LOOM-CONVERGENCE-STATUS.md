# LOOM CONVERGENCE STATUS

Living acceptance record for the Srota Loom convergence mission.
Updated by engineering, never to make unfinished work look complete.

## Current HEAD

- HEAD: `56e2cafb` — `fix(science): close silent fabrication paths across BO, traffic, provenance`
- `01fca4ea` — `fix(gates): ontology cites anchored, truth gate real, CI unified`
- `c9075632` — teammate `Loom 2a: a capabilities tab` (their files, hands off)
- `2e8fe8ba` — `fix(serving,workload): adapter tolerates partial context, one collective vocabulary`
- `d50b676d` — `fix(loom): full-outer-join agent rows, fail-closed reads, endpoint-routed sweep`
- `f920c3c8` — `feat(loom): one capability registry, one value-provenance vocabulary` (teammate Slice 1)
- Baseline: `a6a4cfca` — `feat(studio): Loom UI/UX gap analysis + fabric-console work`
- Branch: `integration/studio-reconciliation` (no other branch in use)
- Working tree at last update: teammate Slice-1 UI in progress (`M apps/studio/src/api/types.ts`, `M apps/studio/src/pages/loom/data.ts`, `M apps/studio/src/router.ts`, `?? SelectionBar.tsx`, `?? selection.ts`, `?? selectionStore.ts`) — active writer, do not touch, do not commit
- Subagent fan-out 2026-10-06 (workflow 3729f829, async): 9 tracks, disjoint ownership, no commits by children, no apps/studio writes. T1 srota-intent (new model/srota_intent.py only) · T2 families-torus (presets/family/torus verifier) · T3 route-projection (parser/ABI/TopologyIR/names/escape-VC) · T4 ramulator ownership · T5 serving-workload · T6 sim-measure (fork emission) · T7 optimize+firewall-spec · T8 audit-triage (read-only) · T9 isolation-tests (new test files only). Parser/emission boundary: T3 owns tolerant parsing + trailer ABI, T6 owns additive emission only.

## Baseline test results (this HEAD)

### DSE suite — 5 failed, 5625 passed, 25 skipped (830 s)

Command: `PYTHONPATH=tracks/t3-topology/dse:tracks/t3-topology/dse/tests python3 -m pytest tracks/t3-topology/dse/tests -q -p no:randomly`
Log: `/tmp/run-dse-tests.log`

| Failure at baseline | Classification | Outcome |
|---|---|---|
| `test_serving_federation_adapter.py` (3 tests) | CODE DEFECT — FIXED in `2e8fe8ba` | `serving_adapter.py:271` assumed `context.workload`; now reads it defensively (absent ⇒ that incompatibility ground is skipped, never assumed compatible; all other gates run). Delegated to a worker, worker refused to execute — parent implemented. Verified: serving + collectives files **62/62 pass** |
| `test_closure_phase3_serveproduct.py::test_run_summary_carries_per_analysis_backends` | ENVIRONMENT (triage) — OPEN | `EXECUTION_FAILED: no qualified backend configured (set VERITX_BOOKSIM_BIN)`, assert 503 == 200. Backend matrix below confirms binaries resolve repo-relative; env override unset |
| `test_workload_collectives.py::test_collective_vocabulary_has_exactly_one_authority` | CODE DEFECT — FIXED in `2e8fe8ba` | `migration.py` now aliases `_WAVED_COLLECTIVE_KINDS` / `_PHASE9_COLLECTIVES` / `_ALLOWED_COLLECTIVE_TOKENS` to `collectives.COLLECTIVE_KINDS` by identity (delegated, verified by parent). Verified in the same 62/62 run |

### Studio TypeScript — CLEAN

- `npx tsc --noEmit`: no errors
- `npx vitest run`: **72/72 pass, 4 files** (includes new agentRows join cases, resolveRouterPairs concentration cases incl. 1024-endpoint, problemsOf read-error findings, expectedChannelLoad unterminated-skip, declaredScope, and the static no-`.catch(() => null)` rule)

### Studio Python tests — 3 failed, 7 passed, 8 skipped (9.47 s)

Command: `PYTHONPATH=tracks/t3-topology/dse:tracks/t3-topology/dse/tests python3 -m pytest apps/studio/tests -q -p no:randomly`
Log: `/tmp/run-studio-py.log`

| Failure | Classification | Notes |
|---|---|---|
| `test_studio_contract_v2.py::test_provisioned_validator_proves_backend_fixtures_through_engine` | TRIAGE PENDING | provisioned byte-for-byte reproducibility FAIL; fast checks pass 5/5 |
| `test_studio_contract_v2.py::test_fresh_provisioned_regeneration_bytes` | TRIAGE PENDING | same area |
| `test_studio_contract_v2.py::test_generated_hashes_originate_from_engine_objects` | TRIAGE PENDING | design_hash mismatch `28ffce…` vs `6f015d…` at line 193 — smells like STALE FIXTURE, unproven |

### Product gates — ALL 7 PASS (fixed in `01fca4ea`)

- `check_intent_ontology`: OPEN — 354 rows, 88 fields, all evidence=V. 13 stale cites verified via git history and converted to `path::Symbol` anchors (checker extended so line numbers cannot rot silently); `NocControls` added to DECLARED (real dataclass, already covered); UI check admits only field-writing blocks; `dependency.graph` node added for `DependencyGraph.dependencies`.
- `check_capability_truth` is now a real gate: mapping lives in the registry (`truth:` per family, `_FAMILY_KEY` deleted); every probed kind must be claimed (else UNGATED); unique ownership; WIRED YES needs truth YES, PARTIAL needs the materialized floor; empty truth only for TEST_FIXTURE/BACKEND_ONLY. Missing `tree4` registry row added (honest underclaim, §6 follow-up noted on the row). Negative-tested 5 failure modes in-process; clean tree green.
- Recipe runs all gates with a failure summary and preserves non-zero exit. `lint` can fail again (4 Makefiles); `sanity_test.py` fails closed. `scripts/ci_gate.sh` (product-gates + DSE suite + studio tsc/vitest/pytest with explicit SKIP) consumed by the GitHub matrix T3 step and the new GitLab `convergence-gate` job.
- §3.5 assessed: base image digest-pinned, FetchContent pinned to tags/hashes, no bit-reproducibility claims anywhere, RELEASE_CXX in manifests, protoc in the gate. Dev `:latest` tools image left as operational convenience, not the release path.

## Backend matrix (live gateway :8123, all HTTP 200)

`/api/v1/health`: `status ok`, `code.stale false`. All backends PRESENT with binary+manifest present:

| Backend | State | Binary resolution |
|---|---|---|
| BOOKSIM_STANDALONE | PRESENT | repo-relative default (`third_party/booksim2/src/booksim`, 23 MB + `.build-manifest.json`); `VERITX_BOOKSIM_BIN` **unset** |
| ASTRA2_EMBEDDED_BOOKSIM | PRESENT | repo-relative default; `VERITX_ASTRA_BIN` **unset** |
| RAMULATOR2_HBM3_V1 | PRESENT | repo-relative default |

`/api/v1/loom/capabilities?include_topology_probe=false`: 25 capabilities — **READY 9 / PARTIAL 7 / BLOCKED 3 / NOT_IMPLEMENTED 6**. READY: design.compile_request, attachment.endpoints, routing.canonical_route, vc.assignment, verification.deadlock_certificate, execution.booksim_standalone, evidence.chain_and_provenance, optimization.candidate_ledger, comparison.runs. BLOCKED: execution.astra, execution.ramulator, execution.serving.
`/api/v1/loom/provenance`: origins `[AUTHORED, DERIVED, DECLARED, MEASURED]` (+ESTIMATED semantics in `value_provenance.py`); freshness `[CURRENT, STALE, FOREIGN_REVISION]`; 12 artifact kinds.

## Loom routes (all wired)

`/projects/:id/loom/<view>` via `router.ts` + `App.tsx` EXPLORE nav: topology, agents, catalog, domains, access, floorplan, workload, simulation (+ ProblemsPanel). 13 files in `apps/studio/src/pages/loom/`.

## Checkpoint B (§2 P0 data-integrity) — DONE, commit d50b676d

- **2.1** `agentRows()` is a full outer join on `(group_index, instance_index)`: ATTACHED / UNATTACHED / ORPHAN_ARTIFACT / INTEGRITY_ERROR, duplicate-seat and kind-mismatch protection, canonical `agent_group[g]/kind[i]` labels, `declaredScope()` draft-vs-revision banner. Consumers updated (AgentsLoom scope filter/column/CSV/detail, CatalogLoom artifact seats, index.tsx catalog line, domainsOf declared-census + endpoint-derived occupancy).
- **2.2** all 14 `.catch(() => null)` loaders removed (loom data ×3, ProblemsPanel ×4, TopologyInspector ×4, optimize ×2, candidates ×1 — verified zero remain); views render loading/ready/error distinctly; `problemsOf` emits advisory findings for unreadable preflight/integrity; static contract test forbids reintroduction.
- **2.3** sweep resolves traced endpoint pairs → router pairs via the certified attachment (`resolveRouterPairs`), dedupes router queries, drops non-terminating routes from attribution, counts unresolvable/unterminated. Verified mapping: every executable BookSim projection addresses the endpoint universe (dense 0..E-1; native additionally enforces endpoint==router).

## Checkpoint T6 (§20.1 measured per-link load, fork emission) — DONE, commit b275a592

- Fork (additive, gated): `SwitchMonitor`/`BufferMonitor` gain read-only `At()`/`ReadsAt()`/`WritesAt()`/`Cycles()` accessors; new `channel_activity` module dumps `veritx/channel-activity/v1` JSON (per-router per-output flits-by-class, per-input reads/writes-by-class, cycles observed) when `channel_activity_output` names a file — empty key changes nothing; unopenable path fails the run. Proven on a live cmesh16 run: conservation attributed+unmatched==emitted holds exactly (50005==50005).
- Python `channel_measurements` reader joins (router, port) counters to the certified channel table into a `MEASURED_CHANNEL_LOAD` artifact (schema/refusal/ambiguity rules enforced); unmatched ports reported, never attributed; shares no type with DERIVED expected load. NOT emitted and explicitly out of scope: cycles-busy/occupancy (no per-cycle busy state exists), credits/stalls (no counters), VC activity (class dimension is traffic class).
- Manifest discipline: the rebuild invalidated the binary↔manifest pair checkout-wide (manifest verification refuses mismatched bytes by design); regenerated via `write_build_manifest.py` with the Makefile's exact flags (dirty=false, digest matches). Producer resolve+recheck+pinned all pass; closure-phase3 booksim 16/16; backend booksim files 76/76. Note: `booksim.build-manifest.json` is gitignored build output, not versioned — any rebuilder must regenerate it.
- 11 tests (9 refusal/contract + 2 end-to-end driving the real binary).
- Follow-up (not this track): prepared-input opt-in for the dump + run-evidence attachment (touches prepared-identity/evidence schemas — separate checkpoint).

## Scientific claims added this checkpoint

- None. This checkpoint removed overstatement (endpoints-only census, swallowed read errors, endpoint-as-router queries) and added none.

## Known limitations / next

1. ~~Serving adapter drift (3 tests)~~ FIXED. ~~Migration vocabulary alias~~ FIXED. Remaining DSE red: closure_phase3 booksim-bin env (triage: environment vs hermetic binary resolution).
2. Studio contract v2 failures (3) — triage pending (likely stale fixtures, unproven).
3. ~~Product gates~~ FIXED (7/7 green, capability truth gated, CI unified).
4. §4 silent-wrongness FIXED in `56e2cafb`: BO raises EVALUATION_FAILED (ask/tell, 13 tests); invented-allreduce fallback deleted (5 tests); profile-without-provenance ingests as unspecified (2 tests); compute source survives lowering + gates comparison (7 tests); ASTRA durations refuse sub-µs/missing with documented boundary (10 tests); Pareto takes per-candidate fidelity (2 tests); backend_profile vs execution_fidelity separated; static registry de-truthed. Full DSE suite: 5685 passed; remaining red is 1 environment (booksim-bin) + 2 procedural staleness artifacts from a mid-run edit of mine (both pass in isolation — the gate worked as designed). NEXT: §5 Srota canonical/product integration — the highest-value feature slice.
4. Teammate Slice-1 UI (`api/*`, `CapabilityLoom.tsx`, `zz-smoke.*`, loom view wiring) owned by active writer — hands off, do not commit.
5. Subagent note: `worker` child refused a scoped write task (acceptance rejected, no writes); `delegate` read-only sweep succeeded. Prefer direct implementation for writers until the refusal pattern is understood.
