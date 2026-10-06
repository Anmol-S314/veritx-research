# LOOM CONVERGENCE STATUS

Living acceptance record for the Srota Loom convergence mission.
Updated by engineering, never to make unfinished work look complete.

## Current HEAD

- HEAD: `d50b676d` — `fix(loom): full-outer-join agent rows, fail-closed reads, endpoint-routed sweep`
- Parent: `f920c3c8` — `feat(loom): one capability registry, one value-provenance vocabulary` (teammate Slice 1, landed mid-session)
- Baseline: `a6a4cfca` — `feat(studio): Loom UI/UX gap analysis + fabric-console work`
- Branch: `integration/studio-reconciliation` (no other branch in use)
- Working tree at last update: `M apps/studio/src/api/index.ts`, `M apps/studio/src/api/types.ts` (teammate Slice 1 client types, active writer — do not touch)

## Baseline test results (this HEAD)

### DSE suite — 5 failed, 5625 passed, 25 skipped (830 s)

Command: `PYTHONPATH=tracks/t3-topology/dse:tracks/t3-topology/dse/tests python3 -m pytest tracks/t3-topology/dse/tests -q -p no:randomly`
Log: `/tmp/run-dse-tests.log`

| Failure | Classification | Notes |
|---|---|---|
| `test_serving_federation_adapter.py::test_bound_valid_experiment_assesses_ready_or_unavailable` | CODE DEFECT (under repair) | `serving_adapter.py:271` assumes `context.workload`; test namespaces lack it. Delegated, worker refused — parent implementing |
| `test_serving_federation_adapter.py::test_planner_selects_serving_for_serving_questions` | CODE DEFECT (same root) | same line 271 |
| `test_serving_federation_adapter.py::test_explicit_pin_is_authoritative` | CODE DEFECT (same root) | same line 271 |
| `test_closure_phase3_serveproduct.py::test_run_summary_carries_per_analysis_backends` | ENVIRONMENT (triage) | `EXECUTION_FAILED: no qualified backend configured (set VERITX_BOOKSIM_BIN)`, assert 503 == 200. Backend matrix below confirms binaries resolve repo-relative; env override unset |
| `test_workload_collectives.py::test_collective_vocabulary_has_exactly_one_authority` | CODE DEFECT (in progress) | `migration.py` duplicates the collective vocabulary in `_PHASE9_COLLECTIVES` / `_ALLOWED_COLLECTIVE_TOKENS` (set-equal, order-differing vs canonical `('ALLREDUCE','REDUCESCATTER','ALLGATHER','ALLTOALL','BROADCAST')`); test references `_WAVED_COLLECTIVE_KINDS` which was never introduced. Delegated |

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

### Product gates — FAILING

Command: `make -C tracks/t3-topology product-gates` → `Error 1`
Log: `/tmp/run-gates.log`

- `scripts/check_intent_ontology.py`: **INTENT ONTOLOGY INVALID — 22 problem(s)**. Two classes: (a) stale line cites (`compile_model.py:2829` outside 1..2658, `mapping.py:170` outside 1..165, `certificate.py:405` outside 1..395); (b) UI rows naming undeclared classes (`NocControls.output_formats`, `NocControls.rcu_enabled`, `address_map.ranges`, `DependencyGraph.dependencies` with no ontology row).
- Gates 2–3 (`check_capability_registry.py`, `check_exposure_registry.py`) did not run — early exit on gate 1 (§3.1 violation, to fix).

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

## Scientific claims added this checkpoint

- None. This checkpoint removed overstatement (endpoints-only census, swallowed read errors, endpoint-as-router queries) and added none.

## Known limitations / next

1. Serving adapter drift (3 tests) — parent implementing after this doc.
2. Migration vocabulary alias — delegated, awaiting child.
3. Studio contract v2 failures — triage pending (likely stale fixtures, unproven).
4. Product gates — §3.1 repair pending (ontology cites + early exit).
5. `apps/studio/src/api/*` owned by active teammate writer — hands off.
