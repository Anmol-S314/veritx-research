# IMPLEMENTATION-LEDGER

Append-only record of implementation against the frozen planning corpus.
No architectural prose — see the planning documents.

## Baseline

| Field | Value |
|---|---|
| Branch | `integration/studio-reconciliation` |
| HEAD | `914d65db42fcfaaabbb9f4fa02cb7f155434ef36` |
| HEAD subject | `studio-serving: namespace discipline + ownership boundary; evaluate flow rail` |
| HEAD date | 2026-09-25 20:28:18 +0530 |
| Worktree at start | **DIRTY** — 55 entries (pre-existing serving work + untracked planning corpus) |

### Baseline failures

| Command | Result |
|---|---|
| `python3 -m pytest tests/` (dse) | **3833 passed, 17 skipped** |
| `python3 -m pytest tests/` (studio) | **2 failed, 8 passed, 1 skipped** |
| `npx tsc --noEmit` (studio) | **exit 0** |
| `python3 scripts/validate_fixtures.py` | exit 0 (fast path) |
| `python3 scripts/check_intent_ontology.py` | exit 0 — `348 rows, 59 declared fields covered, all evidence=V` |
| capability registry checker | **did not exist** |
| exposure registry checker | **did not exist** |

Pre-existing studio failures, attributed to the uncommitted serving work at
baseline and **not fixed in this program** (still failing, unchanged):

- `tests/test_studio_contract_v2.py::test_provisioned_validator_proves_backend_fixtures_through_engine`
- `tests/test_studio_contract_v2.py::test_fresh_provisioned_regeneration_bytes`
  — fixture regeneration digest mismatch on `evaluated-design`
  (`raw_evidence_digest`, `performance_result_id`, `backend_producer.producer_identity`).

Pre-existing **flaky** test, unrelated to this program (no reference to
`compile_draft` or `design_view`), passes 3 of 4 isolated runs:

- `tests/production/test_concurrency.py::test_concurrent_finalize_same_directory_is_idempotent`
  — temp-file race in `core/run_bundle.py` (`tempfile.mkstemp` + concurrent
  rename of `.checksums-*`).

### Planning artifact versions

| Artifact | Bytes | Authority |
|---|---|---|
| `docs/product/INTENT-ONTOLOGY.md` | 33511 | Gate 1 |
| `docs/product/intent-ontology.yaml` | 301905 | Gate 1 — 348 rows, 59 declared fields |
| `docs/product/CROSS-DOMAIN-LAWS.md` | 80761 | Gate 3 |
| `docs/product/CAPABILITY-MATRIX.md` | 43688 | Gate 4 |
| `docs/product/capability-registry.yaml` | 36146 | Gate 4 — 73 rows, 5 envelopes, 11 conditions, `cap-v1` |
| `docs/product/PRODUCT-FLOWS.md` | 88013 | Gate 5 |
| `docs/product/GUIDED-EXPERT.md` | 61571 | Gate 6 |
| `docs/product/exposure-registry.yaml` | 14462 | Gate 6 — 69 rows, 10 classes, 6 presets |
| `docs/product/DESIGN-REVIEW.md` | 40470 | Gate 7 |
| `docs/product/STUDIO-WIREFRAMES.md` | 163514 | Gate 8 |
| `docs/product/INTENT-*.md` | ×12 | Gate 2 |

The corpus is **immutable** during implementation: code changes, not the
corpus.

## Slices

| # | Slice | Commit | Status |
|---|---|---|---|
| 0a | preserve pre-existing uncommitted work | `d0803f2d` | done |
| 0b | freeze the planning corpus | `d87e6616` | done |
| 1 | remove false v4 controls and claims | `623e76ef` | done |
| 2 | validate capability and exposure registries | `e6c1c2cf` | done |
| 3 | canonical arbitration identity + capability semantics version | `47fa751a` | done |
| 4–6 | DesignViewV2 · readiness/findings · compile binding | `08de20c6` | done |
| 7–8 | rebuild design editor on DesignViewV2 + review flow | `5b2b67af` | done |
| 9 | reconcile compile result handoff | — | **not started** |
| 10 | PF-D13 three distinct facts, no ambiguous "run" | `6a0c4a1`-series | done |

Slices 4, 5 and 6 share one projection module and one HTTP surface, so they
land in a single commit; they are itemised separately under *Contracts
implemented*.

## Commits

| SHA | Purpose |
|---|---|
| `d0803f2d` | `studio-serving: preserve pre-existing uncommitted work at program baseline` — not authored by this program; committed so later slices are attributable. |
| `d87e6616` | `product: freeze the planning corpus into version control` |
| `623e76ef` | `studio: remove false v4 controls and claims` |
| `e6c1c2cf` | `product: validate capability and exposure registries` |
| `47fa751a` | `product: canonical arbitration identity + capability semantics version` |
| `08de20c6` | `product: DesignViewV2, structured readiness/findings, review compile binding` |
| `5b2b67af` | `studio: rebuild design editor on DesignViewV2 + canonical review flow` |

Staging-order note: the `FabricCanvas3D.tsx` deletion landed in `d0803f2d`
rather than `623e76ef` because it was staged before the baseline commit was
made. The file is deleted either way; the attribution is off by one commit.

## Files changed

### Backend

| File | Change |
|---|---|
| `veritx_dse/application/product_registry.py` | **new** — the one backend owner of the Gate-4/Gate-6 registries and `capability_semantics_version` |
| `veritx_dse/application/design_view_v2.py` | **new** — DesignViewV2 projection (sections, readiness, findings, consequences, completeness, diff, freshness) |
| `veritx_dse/application/errors.py` | `ErrorCode.STALE_REVIEW` |
| `veritx_dse/gateway/errors.py` | `STALE_REVIEW` → 409 |
| `veritx_dse/gateway/app.py` | `GET /api/v1/projects/{id}/design`; `CompileDraftBody`; removed `POST /optimize` + `OptimizeBody` |
| `veritx_dse/product/service.py` | `design_view_v2()`; `compile_draft(expected_draft_design_hash=…)`; PF-D13 three distinct facts on `project_view` |
| `veritx_dse/model/compile_model.py` | arbitration normalized in both `canonical_dict` implementations |
| `veritx_dse/model/router_behavior.py` | `canonical_arbitration_token()` |

### Frontend

| File | Change |
|---|---|
| `src/components/DesignViewV2Editor.tsx` | **new** — section navigator + central editor, progressive disclosure |
| `src/components/DesignReviewV2.tsx` | **new** — Review presentation + snapshot-bound Compile |
| `src/components/DesignEditor.tsx` | **deleted** — superseded; where the false controls lived |
| `src/components/FabricCanvas3D.tsx` | **deleted** (§186) |
| `src/components/FabricView.tsx` | 2D-only; no 3D toggle |
| `src/components/badges.tsx` | `TierBadge` removed |
| `src/api/types.ts` | `DesignViewV2` and its sub-types |
| `src/api/index.ts` | `api.design()`, `api.compile(pid, expectedHash)` |
| `src/pages/design.tsx` | `Design` rebuilt on the projection; new `Review` |
| `src/pages/offline.tsx` | false controls removed |
| `src/pages/index.tsx` | `intervention.supported` binary removed |
| `src/pages/{design,evidence,serving,optimize}.tsx` | `WorkflowBar` removed |
| `src/studio.tsx` | `WorkflowBar` / `PIPELINE` / `pipelineStatuses` removed; `ContextHeader` rebuilt (PF-D13 + §7) |
| `src/router.ts` | `/projects/:pid/design/review` |
| `src/App.tsx` | light-first default; `Review` route; rail "Intent" → "Design" |
| `src/styles.css` | light-first tokens; tabular figures; DesignViewV2/Review styles |
| `package.json` | `three`, `@types/three` removed |

### Tests

| File | Added |
|---|---|
| `tests/test_product_registry_gates.py` | 34 — registry gate invariants + mutation negatives |
| `tests/test_product_registry.py` | 21 |
| `tests/test_design_view_v2.py` | 51 |
| `tests/test_design_view_v2_api.py` | 16 |
| `tests/test_design_intent_identity.py` | +6 arbitration identity |
| `tests/test_gateway_errors.py` | −1 (duplicate of existing coverage) |

### Docs / CI

| File | Change |
|---|---|
| `docs/product/IMPLEMENTATION-LEDGER.md` | this file |
| `scripts/check_capability_registry.py` | **new** |
| `scripts/check_exposure_registry.py` | **new** |
| `scripts/check_intent_ontology.py` | UI admission repointed at the new editor |
| `tracks/t3-topology/Makefile` | `product-gates` target |
| `.github/workflows/ci.yml` | t3-topology `product-gates` step |

## Contracts implemented

| Slice | Planning contract | Status |
|---|---|---|
| 1 | STUDIO-WIREFRAMES §181 remove-first list | done, except the legacy CLI surfaces (see blockers) |
| 1 | PF-D15 deprecated `POST /optimize` | done |
| 1 | PF-D16 / GX-D6 / ROUTE-011 RCU control | done |
| 1 | GX-D6 / PF-D6 `bandwidth_floor_gbps` control | done |
| 1 | CAP-D2 `intervention.supported` boolean | done |
| 1 | PF-D12 "Radix" → "Grid size" / side length | done |
| 1 | STUDIO-WIREFRAMES §186 no 3D | done |
| 1 | STUDIO-WIREFRAMES §144 linear pipeline, TierBadge | done |
| 1 | STUDIO-WIREFRAMES §3/§5 light-first theme | done |
| 2 | CAPABILITY-MATRIX registry invariants | done |
| 2 | GUIDED-EXPERT exposure invariants | done |
| 3 | Gate 3 §15 / STUDIO-WIREFRAMES §24 arbitration identity | done |
| 3 | Gate 4 §7 one `capability_semantics_version` authority | done |
| 3 | Gate 3 §16 `radix` → `side_length` boundary translation | done (registry labels; no schema migration) |
| 4 | Gate 7 §51.1 DesignViewV2 schema | done |
| 4 | Gate 7 §9 nine Review sections | done |
| 4 | Gate 7 §52 semantic classes | done |
| 4 | Gate 7 §22/§23 REV-D6 read-only Memory Addressing | done |
| 4 | Gate 7 §5 completeness invariant | done, mechanically reported |
| 4 | Gate 7 §39/§40 no later-stage claims | done |
| 4 | Gate 7 §33 CURRENT/STALE freshness | done |
| 4 | Gate 7 §53 snapshot bound by identity, no second hash | done |
| 5 | Gate 6 §106 / Gate 7 §26 REV-D5 readiness, five states | done |
| 5 | Gate 7 §27 validation classes | done (local/canonical + cross-domain preflight; compile-time unknown stays with the compiler) |
| 5 | Gate 7 §29 finding taxonomy | done |
| 5 | Gate 7 §30 capability consequences | done |
| 6 | Gate 7 §4 REV-D2 `expected_draft_design_hash` + `STALE_REVIEW` | done |
| 10 | PF-D13 / PRODUCT-FLOWS §128 remove the ambiguous "latest run" | done |
| 10 | Gate 8 §7 persistent project/revision context | done |
| 7 | Gate 8 §8/§9/§27 left section navigator + central editor | done |
| 7 | Gate 8 §28/§29 progressive disclosure + hidden-active indicator | done |
| 7 | Gate 8 §30 Advanced is not a dumping ground | done (registry-driven) |
| 7 | Gate 8 §12/§13 exposure + consequence projection | done |
| 8 | Gate 8 §33/§34/§35 Review screen, stale state, Review-only Compile | done |
| 8 | Gate 8 §150 deep links | done for `/design/review` |
| — | Gate 8 §36 compile result handoff | **not started** |

Not implemented in Phase 1 by instruction: Evaluate / Serve / Optimize visual
rebuilds, and the Compile Result inspector rebuild (§36 permits preserving the
existing views so a compile still yields an inspectable immutable revision,
which it does).

## Removals

| Removed | Authority |
|---|---|
| RCU authoring checkbox + `.rcu-refusal` banner | PF-D16, GX-D6, ROUTE-011 |
| Requirement "Bandwidth floor (Gbps)" control | PF-D6, GX-D6, REQ-003 |
| `intervention.supported` binary rendering | CAP-D2 |
| `FabricCanvas3D.tsx` + 3D/2D toggle | STUDIO-WIREFRAMES §186 |
| `WorkflowBar` / `PIPELINE` / `pipelineStatuses` | STUDIO-WIREFRAMES §144/§181 |
| `TierBadge` | STUDIO-WIREFRAMES §144 |
| `DesignEditor.tsx` | superseded by the backend projection |
| `POST /optimize` + `OptimizeBody` | PF-D15 |
| Ambiguous global "Latest run" in the context header | PF-D13 |
| `three` / `@types/three` direct deps | consequence of the §186 removal |
| Dark-as-default theme | STUDIO-WIREFRAMES §3/§5 |
| Inter-as-default UI face | STUDIO-WIREFRAMES §129 |
| `test_gateway_errors.py::test_optimize_internal_fault_is_500` | duplicate of existing coverage |

## Test results

| Command | Baseline | Final |
|---|---|---|
| `python3 -m pytest tests/` (dse) | 3833 passed, 17 skipped | **3964 passed, 17 skipped** |
| `python3 -m pytest tests/` (studio) | 2 failed, 8 passed, 1 skipped | **2 failed, 8 passed, 1 skipped** (same pre-existing) |
| `npx tsc --noEmit` | exit 0 | **exit 0** |
| `npx vite build` | exit 0 | **exit 0** |
| `python3 scripts/check_intent_ontology.py` | exit 0 | **exit 0** |
| `python3 scripts/check_capability_registry.py` | n/a | **exit 0** |
| `python3 scripts/check_exposure_registry.py` | n/a | **exit 0** |
| `make -C tracks/t3-topology product-gates` | n/a | **exit 0** |
| `python3 scripts/validate_fixtures.py` | exit 0 | **exit 0** |

Net new tests: **+131**.

The validators are verified to be able to fail: every encoded invariant has a
mutation test (`test_product_registry_gates.py`), and the ontology UI-admission
check was confirmed to exit 1 on a temporarily added uncovered field.

## Known blockers

| Blocker | Debt ID | Notes |
|---|---|---|
| Legacy CLI surfaces (`synthesize`/`sweep`/`baseline`) still exist | PF-D15 | **Deferred deliberately.** A developer surface, not a product surface; 1819-line `cli.py` with three test modules. Removing it is its own slice. |
| `docs/product/STUDIO-WIREFRAMES.md` §181 `landing/*` ambient motion retained | §142/§181 | Separate marketing surface, not the console. Removal is a product-scope decision. |
| Compile Result inspector rebuild | Gate 8 §36–§63 | Phase 1 preserves the existing views so a compile still yields an inspectable revision. |
| Certificate has 10 obligations; Gate 7/8 name 4 claims | — | **Not a conflict**: the four are a product-labelled subset, so the planning contract is satisfiable by projection. Compile Result slice. |
| `PreflightView` still carries evaluation fields | REV-D5 | Design readiness is now separate; `PreflightView` keeps them for Evaluation. Removing them from the design path is done; the endpoint itself is Evaluation's. |
| AddressMap authoring surface | PF-D1 | Review shows it read-only; authoring stays `NOT_RENDERED`. |
| Studio fixture regeneration digests | — | Pre-existing, out of scope. |
| `run_bundle` concurrency flake | — | Pre-existing, out of scope. |

No `IMPLEMENTATION-CONTRACT-CONFLICT` was raised: no planning contract proved
impossible.

## Debt references

Referenced, never duplicated: PF-D1…PF-D16, GX-D1…GX-D8, CAP-D1…CAP-D5,
XDOM-D1…XDOM-D8, REV-D1…REV-D7, MEM-D1/D3/D4, MEM-EVAL-D1/D2, MEM-METRIC-D1,
OPT-D2/D3/D5/D6/D7/D8, FAB-D1/D4/D6, VC-D1, COMM-D1, ROUTER-D2.

## Contract conflicts

None.
