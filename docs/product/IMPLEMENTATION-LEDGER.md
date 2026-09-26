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
| 10 | PF-D13 three distinct facts, no ambiguous "run" | `acbef67d` | done |
| 11 | preset certification authority (audit closure) | `b7147075` | done |
| 12 | CompileResultView — seven inspector groups | `3fb97400` | done |
| 13 | Compile Result surface + certificate/verification | `92103d07` | done |

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
| `src/pages/evidence.tsx` | `intervention.supported` binary removed (second occurrence, found by the false-surface sweep) |
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
| `intervention.supported` binary rendering (both `pages/index.tsx` and `pages/evidence.tsx`) | CAP-D2 |
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
| `python3 -m pytest tests/` (dse) | 3833 passed, 17 skipped | **3999 passed, 17 skipped** |
| `python3 -m pytest tests/` (studio) | 2 failed, 8 passed, 1 skipped | **2 failed, 8 passed, 1 skipped** (same pre-existing) |
| `npx tsc --noEmit` | exit 0 | **exit 0** |
| `npx vite build` | exit 0 | **exit 0** |
| `python3 scripts/check_intent_ontology.py` | exit 0 | **exit 0** |
| `python3 scripts/check_capability_registry.py` | n/a | **exit 0** |
| `python3 scripts/check_exposure_registry.py` | n/a | **exit 0** |
| `python3 scripts/check_preset_certification.py` | n/a | **exit 0** |
| `make -C tracks/t3-topology product-gates` | n/a | **exit 0** |
| `python3 scripts/validate_fixtures.py` | exit 0 | **exit 0** |

Net new tests: **+166**.

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

---

## Audit closure — preset certification (GX-D5)

A contract contradiction was raised after the first Phase-1 report:
`mesh4` declared `ModelFamily.MOE` while Gate 6 certified it Guided-safe
under `CAP-ENV-BOOKSIM-MESH-DOR-XY-V1`, whose `COND-DENSE-STATIC-WORKLOAD`
requires `dense_transformer`.

### Audit of `mesh4` — the four options, decided from source

| Question | Finding |
|---|---|
| Preset ID | `mesh4`, `mesh4_hbm`, `mesh4_wide128` |
| ModelFamily | `ModelFamily.MOE` in **both** canonical sources (`application/presets.py:55`, `application/compile_intent.py:131`) |
| Workload template | `Workload(model_family=MOE, tp=1, pp=1, ep=1, dp=1)` — a single NPU, no parallelism |
| Operation graph | two dependency classes: `Dependency("A","B",BLOCKING)`, `Dependency("B","A",BLOCKING)` |
| Collectives | **none** — the network workload is the synthetic trace `tiny2` / `tiny2x5` |
| TP/DP/EP/PP | 1/1/1/1 |
| Communication semantics | **multi-class**: `traffic_class_to_vcs = {A: (1,), B: (0,)}`, `vc_count = 2` |
| Generated CompileRequest | schema v2, mesh, `radix=None` (derived), `link_width=None` except wide128=128 |
| Capability rows triggered | `COMM-006` (multi-class execution `NOT_AVAILABLE`); `WORK-002` only under the old MOE label |

**Classification: (C) mislabelled by preset metadata — plus a second,
independent certification error.**

1. `model_family=MOE` was wrong metadata. These are **fabric** presets: a
   4-tile mesh carrying a synthetic trace, with `total_npus = tp × ep = 1`
   and no collectives. `moe-8x7b-64tiles` (`ep=8`, `alltoall`) is the real
   MoE preset.
2. Even with the family corrected, the family **still** fails the envelope:
   it is multi-class, and every static envelope requires
   `COND-SINGLE-COMM-CLASS`. `GUIDED-EXPERT.md` §86 already wrote the
   envelope as *"(if single class)"* — the conditionality was known and the
   verdict ignored it.

### Inertness proof for the metadata correction

| | MOE carrier | DENSE carrier |
|---|---|---|
| `Workload.total_npus` | 1 | 1 |
| compile | COMPILED | COMPILED |
| certificate | PASS | PASS |
| topology / attachment / mapping / route / resolved-route / VC / fabric hashes | **identical** | **identical** |
| `design_hash`, `resolved_fabric_hash` | differ | differ |

Only the identity moved — the same class of move the repo already documents
for semantics v1 → v2. Pinned goldens updated in
`test_compile_intent.py`, `test_cli_compile_surface.py`,
`test_application_service.py`. `test_candidate_policy.py` was **not**
changed: it builds its own design and its golden is independent.

### Certification after the correction

| Preset | State | Envelope |
|---|---|---|
| `dense-1b-16tiles` | **GUIDED_SAFE (PROVEN)** | `CAP-ENV-BOOKSIM-MESH-DOR-XY-V1` |
| `mesh4` · `mesh4_hbm` · `mesh4_wide128` | EXPERT_ONLY | none — multi-class (`COMM-006`) |
| `dense-4b-32tiles-conc4` | EXPERT_ONLY | none — concentration 4 |
| `moe-8x7b-64tiles` | EXPERT_ONLY | serving envelope |

**Guided safe path: `dense-1b-16tiles` — proven, not asserted.** All seven
required conditions hold from real artifacts. §6's requirement is met, so
this is **not** `GUIDED SAFE PATH BLOCKED`.

### Second defect found during the closure

`DesignViewV2`'s capability-consequence projection **under-reported**:
it read *declared collective* classes, so the mesh4 family — multi-class
through its dependency graph, with no collectives declared — produced no
consequence at all and projected as `READY`. It now reads the **lowered**
`traffic_class_to_vcs` from the canonical compilation, and reports
`COMM-006 multiple communication classes (A, B)`.

The projection also now compiles **once** and threads that compilation
through preflight, consequences and derived summaries, so it cannot
disagree with itself.

### Files changed (audit closure)

| File | Change |
|---|---|
| `veritx_dse/application/presets.py` | `mesh4` carrier → `DENSE_TRANSFORMER` + rationale |
| `veritx_dse/application/compile_intent.py` | same correction |
| `veritx_dse/application/preset_certification.py` | **new** — certification authority, fail-closed |
| `veritx_dse/application/design_view_v2.py` | lowered-class consequences; single compilation |
| `scripts/check_preset_certification.py` | **new** — CI gate |
| `docs/product/exposure-registry.yaml` | `presets` certification corrected |
| `docs/product/GUIDED-EXPERT.md` | §86 corrected; §87 marked ENFORCED |
| `docs/product/STUDIO-WIREFRAMES.md` | §18/§20 preset lists corrected |
| `tracks/t3-topology/Makefile` | gate wired |
| tests | +32 certification, +3 registry, +2 projection |

### Blocker closed

| Was | Now |
|---|---|
| GX-D5 preset certification asserted, never enforced | **Enforced.** `scripts/check_preset_certification.py` fails closed on a refuted Guided claim; verified by re-asserting the false `mesh4` claim (exit 1) and restoring (exit 0). |

---

# PHASE 2 — compiled inspectors + verification/certificate surfaces

Baseline at entry: `b7147075`, clean tree, backend 3999 passed / 17 skipped,
four registry gates exit 0, studio tsc/vite exit 0, studio tests 2
pre-existing failures.

## Scope

Gate 8 §50–§63 and §36–§63: the Compile Result inspectors and the
verification/certificate surface. Evaluate / Serve / Optimize were **not**
touched, per the Phase-1 handoff.

## Contracts implemented

| Contract | Status |
|---|---|
| Gate 5 §97 / Gate 8 §50 — seven inspector groups under one Compile Result | done |
| Gate 8 §51 — compiled revision header | done |
| Gate 8 §52 — summary: declared / derived / verified | done |
| Gate 8 §53/§54 — mapping, table-first | done |
| Gate 8 §55/§56 — fabric inspector over the compiled topology | done |
| Gate 8 §57 — semantic zoom thresholds | done |
| Gate 8 §58 — canonical DERIVED EXPECTED route | done |
| Gate 8 §59 — runtime observation, separate and honestly unavailable | done |
| Gate 8 §60 — VC inspector, no controls | done |
| Gate 8 §61 — deadlock/CDG witness | done |
| Gate 8 §62/§63 — certificate: four claims over ten obligations | done |
| Gate 7 §23 — address decode stable identity | done |
| Gate 7 §9 PF-D9 — four separate claims, not one verdict | done |
| Gate 8 §115/§116 — provenance | done |
| Gate 8 §35 — inspector draws the compiled artifact, never a preview | done |

## The certificate projection — the flag from Phase 1, resolved

The verifier issues **ten** obligations; Gate 7 §9 / Gate 8 §62 name
**four** claims. Phase 1 flagged this as unresolved.

Resolution: expose **both**. `claims` is the four, in the product's order
with the planning scope sentences; `obligations` is all ten verbatim;
`additional_obligations` names the six that are not claims; `claim_count`
and `obligation_count` are both carried. A test asserts no obligation is
dropped. The planning contract is satisfiable by projection and nothing was
invented — hiding six obligations would have hidden proof the certificate
relied on.

## Two defects found and fixed during the slice

**1. `route_realization` is not an observation.** The DEADLOCK_FREE
evidence carries `route_realization: "v2_channel_id"` — the artifact's
*encoding scheme*. The first implementation treated it as a runtime
observation and set `observation.available = True`, which would have
claimed a runtime fact that does not exist. A compiled revision has no
execution, so the observation is now reported unavailable with its source
named (an evaluation run, where `RunIntegrityView.route_realization`
reports OBSERVED | NOT_OBSERVED at its own scope).

**2. The route table value is a channel id, not a port or a next router.**
`entries[(class, src, dst)]` → channel id; the next router is that
channel's destination. The first walk assumed a port and produced
`0 → 0 → 0 …` and `<no channel from r0 port 0>`. Corrected and verified:
`0 → 8` walks `0,1,2,5,8`, `8 → 0` walks `8,7,6,3,0`, and a self-route
terminates in `LOCAL_EJECTION`.

## Design decisions

**The payload is frozen at certification time** (Gate 5 §97). The
inspectors are materialized during compile and stored with the revision, so
a drawn graph can never drift from the proof it claims to show.

**The payload is pure data.** The revision is persisted as JSON, so the
route walker is a module-level query (`GET /revisions/{id}/route`) rather
than a closure on the payload. The first attempt attached a function and
broke compilation with `TypeError: Object of type function is not JSON
serializable`.

**Legacy revisions re-derive and are hash-verified.** A revision persisted
before this payload existed re-derives from its own immutable request and
is checked against the hashes it already recorded — the rule
`get_revision_topology` already follows. A mismatch is
`EVIDENCE_INVALID`, never a silently redrawn fabric.

**`Verify` is reconciled, not duplicated.** Gate 8 §50 is explicit that
there is not one page per artifact, so `/verify` renders the same Compile
Result projection. `VerifyView` is retained only for the offline fixture
page, which has no gateway.

**`FabricCanvas` needed no `DesignView`.** `modelFromTopology` accepted one
but used it only for concentration/link-width presentation fallbacks;
those are now explicit optional hints, so a Compile Result never fabricates
a `DesignView` to draw a graph it already holds.

## Live verification (real revision, not a fixture)

Against a real 81-router revision served by the gateway:

```text
groups        summary · mapping · fabric · routing · resources ·
              address_decode · provenance
certificate   4 claims / 10 obligations
fabric        routers 81 · channels 288 · seats 81 · attached 72 ·
              unused_seats 9 · detail ROUTERS_AND_LINKS
route         0 → 1 → … → 80  (17 hops) → LOCAL_EJECTION
observation   unavailable (no runtime execution)
```

The 81-router fabric sits **between** the 64 and 256 thresholds, so the
semantic-zoom rule was exercised for real rather than by a unit test alone.

## Test results

| Command | Baseline | Final |
|---|---|---|
| `pytest tests/` (dse) | 3999 passed, 17 skipped | **4040 passed, 17 skipped** |
| `pytest tests/` (studio) | 2 failed, 8 passed | **2 failed, 8 passed** (same pre-existing) |
| `npx tsc --noEmit` | exit 0 | **exit 0** |
| `npx vite build` | exit 0 | **exit 0** |
| `make -C tracks/t3-topology product-gates` | exit 0 | **exit 0** |

Net new tests: **+41**.

## Known blockers

| Blocker | Debt | Notes |
|---|---|---|
| Gate 8 §5 primary navigation (Design · Evaluate · Serve · Optimize · History · Capability) | — | The rail still carries Compile/Verify as numbered workflow entries. Gate 8 §146 has no Verify screen. A separate IA slice. |
| Compile Result is not routed per group | Gate 8 §150 | `/revisions/:rid/:group` deep links are specified; the surface uses tabs. |
| `PreflightView` still carries evaluation fields | REV-D5 | Unchanged from Phase 1; belongs to Evaluate. |
| Studio fixture regeneration digests · `run_bundle` concurrency flake | — | Pre-existing, out of scope. |

No `IMPLEMENTATION-CONTRACT-CONFLICT` was raised.

---

# PHASE 2 CLOSURE — compiled inspectors / verification / certificate

Baseline at entry: `b7147075`, clean tree, backend 3999 passed / 17 skipped,
four registry gates exit 0, studio tsc/vite exit 0, studio tests 2
pre-existing failures.

## 1. The 10-obligation audit

Read from `verification/certificate.py` (`_OBLIGATION_RUNNERS` and each
producer), `VerificationCertificate.__post_init__`,
`verification/channel_vc_cdg.py`, `application/views.py`, and the
obligation tests. Not inferred from names.

| Obligation | Producer | Inputs | Status vocabulary | Exact meaning | Claim(s) | Primary / sub |
|---|---|---|---|---|---|---|
| `TOPOLOGY_CONNECTED` | `_topology_connected` | topology channels | PASS/FAIL | router graph is one undirected component, no isolated routers | — | technical-only |
| `ATTACHMENT_COMPLETE` | `_attachment_complete` | `attachment.validate_against(design, inventory, topology)` | PASS/FAIL | every declared agent has a proven seat | **ATTACHMENT_COMPLETE** | primary |
| `ADDRESS_DECODE_VALID` | `_address_decode_valid` | `decode.validate_against(address_map, attachment)` | PASS/FAIL | the decode realizes the declared address map | — | technical-only |
| `ROUTE_COMPLETE` | `_route_complete` | route table | PASS/FAIL | entries == classes × routers × (routers−1) | **ROUTE_COMPLETE** | primary |
| `ROUTE_LEGAL` | `_route_legal` | `route.validate_against(topology)` | PASS/FAIL | every route is channel-legal and terminates | **ROUTE_LEGAL** | primary |
| `VC_ASSIGNMENT_VALID` | `_vc_assignment_valid` | `vc.validate_against(resolved_route)` | PASS/FAIL | VC structure binds the resolved route | — | technical-only |
| `DEADLOCK_FREE` | `_deadlock_free` | `(channel, VC)` CDG | PASS/FAIL **at the obligation**, PASS/FAIL/UNSUPPORTED/NOT_RUN **underneath** | the realized CDG is acyclic | **DEADLOCK_FREE** | primary |
| `MAPPING_VALID` | `_mapping_valid` | mapping↔attachment seam over `mapping.placements` | PASS/FAIL | every mapped rank lands on an attached agent; ranks contiguous from 0 | — | technical-only |
| `PACKET_FORMAT_VALID` | `_packet_format_valid` | `packet_format.validate_against(topology, attachment, vc_resources)` | PASS/FAIL | the wire format fits topology/attachment/VC bounds | — | technical-only |
| `FABRIC_DAG_VALID` | `_fabric_dag_valid` | `bundle.revalidate()` | PASS/FAIL | the whole hardware + design/mapping seam revalidates | — | technical-only |

Two facts the audit established, both enforced in code:

* `VerificationCertificate.__post_init__` requires **exactly** these ten
  and rejects an obligation status outside `PASS|FAIL`. There is no
  obligation-level `UNSUPPORTED` — the earlier projection invented one.
* `_deadlock_free` folds every non-PASS CDG verdict into obligation
  `FAIL` (`if cert.verdict != "PASS": return _fail(...)`), recording the
  true verdict in the evidence and in a prose `failure_reason`. That is
  correct for the certificate; it is not correct for the product.

## 2. Product claim derivation

`MAPPING_VALID` is **not** part of `ATTACHMENT_COMPLETE`, despite sharing
an artifact-provenance parent in `views.py`: the former is the mapping
seam (`mapping.placements`), the latter is agent attachment
(`attachment.validate_against`). Different artifacts, different failure
modes. The contribution table is therefore 1:1:

| Product claim | Contributing obligations | Aggregation | Failure semantics |
|---|---|---|---|
| `ATTACHMENT_COMPLETE` | `ATTACHMENT_COMPLETE` | ALL_PASS | not established if the obligation is not PASS |
| `ROUTE_COMPLETE` | `ROUTE_COMPLETE` | ALL_PASS | as above |
| `ROUTE_LEGAL` | `ROUTE_LEGAL` | ALL_PASS | as above |
| `DEADLOCK_FREE` | `DEADLOCK_FREE` | ALL_PASS | as above, plus the analysis verdict |

No `IMPLEMENTATION-CONTRACT-CONFLICT` was raised: every claim has a
proven mapping, and the projection **fails closed** if a certificate ever
carries an obligation it does not classify.

## 3. The deadlock verdict fix

Two layers, modelled separately:

```text
certificate obligation status   PASS | FAIL                       (canonical)
CDG analysis verdict            PASS | FAIL | UNSUPPORTED | NOT_RUN (separate)
```

The verdict is recovered from **evidence keys**, never by parsing prose:

```text
acyclic is True                    -> PASS
acyclic is False + cycle present   -> FAIL
unsupported_reason, no acyclic     -> UNSUPPORTED
no analysis evidence at all        -> NOT_RUN
```

`detected_deadlock` is true only for a real FAIL carrying a cycle witness,
so `UNSUPPORTED` and `NOT_RUN` can never render as a detected deadlock.

## 4. Compiled-result authority table

| Product fact | Canonical authority | Product projection | Frontend surface |
|---|---|---|---|
| declared values | `CompileRequestV3` | `groups.summary.declared` | Summary |
| derived counts | `TopologyArtifact`, `AgentAttachmentArtifact`, `VCAssignmentArtifact`, `RouteArtifact` | `groups.summary.derived` | Summary |
| mapping | `MappingArtifact` + `AgentAttachmentArtifact` | `groups.mapping` (+ coordinates from `model.placement.coords_of`) | Mapping |
| topology | `TopologyArtifact` | `groups.fabric.topology` | Fabric inspector |
| attachments / seats | `AgentAttachmentArtifact` | `groups.fabric.topology.endpoints` + counts | Fabric inspector |
| routes | `RouteArtifact` + `ResolvedRouteArtifact` | `groups.routing` (table stored, not shipped) + `GET /route` | Routing |
| VCs | `VCAssignmentArtifact` | `groups.resources` | Resources |
| CDG / deadlock | `channel_vc_cdg` via `DEADLOCK_FREE` | `groups.resources.deadlock` + `certificate.deadlock_analysis` | Resources + Verification |
| certificate | `VerificationCertificate` | `certificate` (4 claims + 10 obligations) | Verification |
| capability consequences | `capability-registry.yaml` | `capability_consequences` | Summary |
| provenance | bundle `root_hashes()` + `ArtifactChainView` | `groups.provenance` | Provenance |

## 5. Two defects found and fixed during closure

**Occupancy was wrong.** `_fabric` counted *distinct routers* as
`attached` instead of endpoints. `dense-4b-32tiles-conc4` (9 routers × 4
seats, 36 agents) reported **27 unused seats when it has zero**. Now
endpoint-counted, with `occupied_routers` added so the two facts stay
distinct.

**The 16×16 payload was 4.8 MB**, because the routing group shipped 65,280
route-entry rows inline. The frontend never needs them — the canonical
route is a query walked server-side over the frozen table. The served
response withholds the entries; the stored revision keeps them.
**4.8 MB → 311 KB**, route still walks correctly.

## 6. Current view audit

| Component | Verdict | Reason |
|---|---|---|
| `FabricCanvas` | **KEEP** | preview + materialized structural renderer; still used by the Design preview and offline page |
| `FabricInspector` | **KEEP** | the selection detail panel, reused conceptually by `FabricInspector2D` |
| `FabricInspector2D` | **NEW** | the canonical compiled inspector |
| `FabricView` | **KEEP** | 2D-only wrapper, no 3D |
| `CompileResultView` | **REPLACE** (done) | was flat cards; now the seven groups |
| `VerifyView` | **REFACTOR** (done) | `/verify` renders the same Compile Result projection; the component survives only for the offline fixture page |
| Compile page | **REPLACE** (done) | no longer mixes Review with the result |

## 7. Phase-2 acceptance battery

| ID | Obligation | Result | Evidence |
|---|---|---|---|
| P2-A | 10 obligations preserved | **PASS** | `test_p2_a_*`; 4 claims + 6 technical-only partition the set; an unclassified obligation raises |
| P2-B | claims derive deterministically | **PASS** | `test_p2_b_*`; contribution table, ALL_PASS, order-independent, missing contributor fails closed |
| P2-C | frontend does not aggregate | **PASS** | claims computed backend-side; `certificate_status` and `established` are payload fields |
| P2-D | no sole generic VERIFIED | **PASS** | `test_p2_d_*`; no `VERIFIED` token; vocabulary declared explicitly |
| P2-E | mapping uses stable identities | **PASS** | `test_p2_e_*`; rank/agent/endpoint ids + rank-algebra coordinates |
| P2-F | mapping cannot be edited | **PASS** | `test_p2_f_mapping_is_not_editable` |
| P2-G | mesh geometry from canonical coordinates | **PASS** | `test_p2_g_*`; unique 2D coords, no self-loops, no diagonal shortcuts |
| P2-H | torus wrap links render from artifact | **BLOCKED** | no compiled torus can exist — see P2-S. Arc rendering is implemented and coordinate-derived, but unexercised |
| P2-I | concentration renders seats not routers | **PASS** | `test_p2_i_*`; 9 routers × 4 seats = 36, capacity uniform |
| P2-J | unused seats render correctly | **PASS** | `test_p2_j_*`; 5 unused (dense-1b), 0 unused (conc4), per-router sums match |
| P2-K | attachment selection resolves exactly | **PASS** | `test_p2_k_*`; every endpoint resolves to a real router, full identity chain |
| P2-L | route from canonical artifact | **PASS** | `test_p2_l_*`; every entry names a real channel; server-side walk |
| P2-M | LOCAL_EJECTION handled | **PASS** | `test_p2_m_*` |
| P2-N | derived route and runtime evidence separate | **PASS** | `test_p2_n_*`; observation unavailable, Gate-4 wording, "not observed packet paths" |
| P2-O | VC inspection read-only | **PASS** | `test_p2_o_*`; `editable: false`, canonical integer VC ids |
| P2-P | deadlock FAIL displays witness | **PASS** | `test_p2_p_*`; witness fields + cycle rendering + recovery links |
| P2-Q | deadlock UNSUPPORTED ≠ FAIL | **PASS** | `test_p2_q_*`; all four verdicts independently; `detected_deadlock` false for UNSUPPORTED/NOT_RUN |
| P2-R | CDG witness resolves to channels/VCs | **PASS** | `test_p2_r_*`; witness channel ids exist in the topology |
| P2-S | torus inspectable despite route-unavailable | **BLOCKED** | `test_p2_s_*` asserts the blocker; see below |
| P2-T | multi-class result inspectable | **PASS** | `test_p2_t_*`; mesh4 family compiles, certifies, all 7 groups |
| P2-U | capability limitation ≠ invalidity | **PASS** | `test_p2_u_*`; certificate PASS + COMM-006 consequence together |
| P2-V | provenance in technical detail | **PASS** | `test_p2_v_*`; hashes, versions, parentage |
| P2-W | scientific SVG has data equivalent | **PASS** | `test_p2_w_*`; router/channel/attachment columns complete in the payload, rendered as tables |
| P2-X | 3D not reintroduced | **PASS** | `test_p2_x_*`; 2D coordinates only, no spatial tokens |

**BLOCKED, with evidence (not a silent absence):**

`P2-H` and `P2-S` depend on a **compiled torus**, which cannot exist.
`FabricCompiler` refuses a torus at `stage=ROUTING` and returns
`bundle=None`, so there is no `TopologyArtifact`, no certificate and no
Compile Result to inspect. The capability registry agrees the topology is
derivable (`FAB-003`: `DECLARABLE=YES`, `DERIVABLE=YES`,
`PROJECTABLE=NO`), and `derive_topology_spec(torus)` succeeds — but the
compiler discards the derived topology with the bundle when routing
refuses.

**Smallest real correction:** the compiler must surface the derived
topology when a later stage refuses (a topology-only compile outcome), or
the product needs a topology-only inspection path for a
declarable-but-not-projectable topology. Both are compiler/product changes
outside Phase 2. The arc rendering for wrap links is implemented and
coordinate-derived, so the visual half is ready.

## 8. Performance

| Case | Compile | Project | Routers | Channels | Payload |
|---|---|---|---|---|---|
| mesh4 | 92 ms | 61 ms | 9 | 24 | 32 KB |
| 8×8 | 317 ms | 7 ms | 64 | 224 | 360 KB |
| 16×16 | 4.2 s | 55 ms | 256 | 960 | 311 KB (was 4.8 MB) |

SVG remains adequate: the drawing is bounded by router count (≤256 in the
router-detail band), not by route-table size. No graphics-stack change is
warranted.

## 9. Test results

| Command | Baseline | Final |
|---|---|---|
| `pytest tests/` (dse) | 3999 passed, 17 skipped | **4105 passed, 17 skipped** |
| `pytest tests/` (studio) | 2 failed, 8 passed | **2 failed, 8 passed** (same pre-existing) |
| `npx tsc --noEmit` | exit 0 | **exit 0** |
| `npx vite build` | exit 0 | **exit 0** |
| `make -C tracks/t3-topology product-gates` | exit 0 | **exit 0** |
| `generate_compiled_fixtures.py --check` | n/a | **exit 0 (5 cases)** |

Net new tests: **+106**.

## 10. Unresolved blockers

| Blocker | ID | Notes |
|---|---|---|
| No compiled torus → P2-H/P2-S | — | Compiler discards the derived topology on a routing refusal. Needs a topology-only compile outcome. |
| Gate 8 §5 primary navigation | — | Rail still carries Compile/Verify as numbered workflow entries; §146 has no Verify screen. Separate IA slice. |
| Compile Result group deep links | Gate 8 §150 | Tabs, not `/revisions/:rid/:group`. |
| `PreflightView` evaluation fields | REV-D5 | Unchanged; belongs to Evaluate. |
| Studio fixture digests · `run_bundle` flake | — | Pre-existing, out of scope. |

No `IMPLEMENTATION-CONTRACT-CONFLICT` was raised.

---

## FEATURE RECLAMATION IMPLEMENTATION TRANCHE 1

Bounded tranche under `FEATURE-RECLAMATION-AMENDMENT.md`. Establishes the
generic topology representation and proves it. No qualification claim was
broadened anywhere.

### AMEND-0 — audit bookkeeping correction

**Commit:** `1834495c` — `audit(amend-0): correct three bookkeeping defects in the audit seal`

Three defects, all mechanically derived rather than asserted:

| Defect | Printed | Derived |
|---|---|---|
| Wave-F 21-item parity | `10·7·4` | **`10 YES · 6 PARTIAL · 5 NO`** |
| T3 example parity | `9·6·17` | **`11 YES · 4 PARTIAL · 13 NO`** |
| T4 serving parity | `28·3·3` | **`29 YES · 2 PARTIAL · 4 NO`** |
| Thesis count | "six of eight" | **five of eight** |
| Branch status | `MET pending per-file diff` | `REPLACEMENT CONDITION LIKELY MET — ARCHIVAL NOT AUTHORIZED` |

The suggested `11·5·5` was **also not** the correct Wave-F split.

### AMEND-1 — topology taxonomy separated from capability stages

**Commit:** `4fdc7555` — `product: separate topology taxonomy from capability stages`

**Files:** `docs/product/topology-family-registry.yaml`,
`scripts/check_topology_family_registry.py`,
`tests/test_topology_taxonomy.py`

Nine independent stages; membership in either enum is no longer a
capability statement. **Corrects the amendment's rejected rule** (GEC and
FAT_TREE stay AUTHORABLE; RING stays AUTHORABLE=NO as TEST_FIXTURE).

**Tests:** TAX-1..TAX-6 (15 tests). TAX-6c mutates a registry row and
asserts the checker exits 1 — drift is detected, not assumed.

```
TopologyFamily      (6): concentrated_mesh, custom, fat_tree, gec, mesh, torus
MaterializedFamily  (6): concentrated_mesh, custom, flatfly, mesh, ring, torus
declarable-not-materializable: fat_tree, gec
materializable-not-declarable: flatfly, ring
```

### AMEND-2 / AMEND-3 — explicit topology materialization + generic staged law

**Commit:** `2b04709a` — `model: materialize explicit topology and add the flatfly proof family`

**Files:** `veritx_dse/model/topology_artifact.py`,
`veritx_dse/model/compile_model.py`, `tests/test_explicit_topology.py`

Custom topology intent is the **existing** `TopologyIR`; the missing half
was the materializer. `MaterializedFamily.CUSTOM` and `.FLATFLY` added as
**classification** markers, not algorithms. Shared `_artifact()` makes the
staged law generic.

**Mesh identity proven stable:** `524cf3267d4d64c3cdd07dd2`, 16 routers,
48 channels — unchanged by the refactor.

**Tests:** CUSTOM-1..10, STAGE-1/2/3/6 (29 tests).

### AMEND-4 — search completeness

**Commit:** `8ec11e56` — `optimization: restore explicit search completeness`

**Files:** `veritx_dse/optimization/completeness.py`,
`veritx_dse/optimization/result.py`,
`contracts/srota/v2/optimization.study.view.schema.json`,
`tests/test_search_completeness.py`

Replaces `cands[:limit]` silent truncation with an identity-bearing
`SearchCompleteness`. `EXHAUSTIVE` is never inferred. The contract schema is
strict, so the field is **declared** there rather than smuggled.

**Tests:** SEARCH-1..6 (16 tests).

### AMEND-5 — Wave-E metric projection

**Commit:** `64fc4760` — `performance: expose certified Wave-E metrics`

**Files:** `veritx_dse/optimization/metric_registry.py`,
`tests/test_wave_e_metric_projection.py`

`certified-builtin-v2` extends v1 (a new version, not a replacement — one
authority per metric). Four metrics registered with exact canonical names;
`ttft`/`decode_step_latency` **not fabricated** (declared but not computed);
absent is never zero; honesty metadata travels with the metrics.

**Tests:** PERF-1..5 (14 tests).

### Tranche 1 totals

| | |
|---|---|
| New tests | **74** |
| Full suite | **4202 passed, 17 skipped, 0 failed** |
| Registry gates | all exit 0 |
| Branches | 84 — **none deleted, archived or modified** |

### Unresolved blockers

1. **Two unrelated `TopologyError` classes** — `core.errors` and
   `model.topology_artifact`. Neither catches the other. Not merged.
2. **`flatfly` materializable, not yet authorable** — no intent schema.
   Recorded honestly rather than over-claimed.
3. **`concentrated_mesh` backend cells unverified** — deferred.
4. **`TopologyIR` CLI not restored** — module and tests wired only.
5. **`TopologyIR` test/CLI MIGRATION HOLE** — `tests/test_topology_ir.py`
   (349 lines) and `cmd_topology_render/_stats/_diff` survive only on
   `integration/p1-product-rt-candidate` @ `26e6f9dc`.

### Not started (out of tranche scope)

AMEND-6 workload parity · AMEND-7 capability-registry correction ·
AMEND-8 synthesis adapter · AMEND-9 structural optimizer ·
AMEND-10 Studio IA · Phase 3 Static Evaluate

---

## FEATURE RECLAMATION IMPLEMENTATION TRANCHE 2

### TRANCHE 1 SEAL

**Test-count reconciliation — by collected node-ID set diff, not arithmetic.**

| | |
|---|---|
| Baseline `1834495c` collected | **4140** |
| HEAD collected | **4220** |
| **Added** | **+80** |
| **Removed** | **0** |

Added = 74 (tranche 1's four new files: TAX 15, CUSTOM/STAGE 29, SEARCH 16,
PERF 14) + 6 (`test_compile_result_view.py`). Method: `pytest
--collect-only -q` at both commits, `LC_ALL=C sort`, `comm`. An earlier
`comm` run without the locale pin reported 4 spurious removals; the correct
answer is **0**.

**The reported "+31" was a REPORTING error, not a test loss.** The "4171
baseline" figure was a mid-tranche measurement taken after 44 of the 74 new
tests already existed. **No regression test disappeared.**

**FlatFly concentration proof.** Target derived from source, not asserted:
`presets.py:51-57` defines `nodes=(k**n)*c`, `r=c+(k-1)*n`,
`edges=nodes//c*(r-c)//2`, and `SWEEP_TOPOS` names the preset `flatfly_64`.

| Fact | Expected | Materializer |
|---|---|---|
| routers | 16 (`k**n`) | 16 ✓ |
| endpoints | **64** (`k**n * c`) | 64 seats ✓ |
| seats/router | 4 | {4} ✓ |
| total seats | 64 | 64 ✓ |
| router degree | 6 (`(k-1)*n`) | 6 ✓ |
| directed channels | 96 (`2*48`) | 96 ✓ |

**Endpoint universe is 64 over 16 routers — not 64 routers.** Concentration
is owned by `Router.seat_capacity` inside the artifact, so `c=4` and `c=1`
**do not collapse**: their `topology_hash` differs while the router graph is
identical. SEAL-1/SEAL-3 tests added.

**SEAL-4 defect found and fixed.** `FabricInspector2D` laid out from
`r.coordinates`, so a coordinate-free custom graph stacked every router at
(0,0). A deterministic presentation-only grid now covers that case.

**Verdict: `TRANCHE 1 SEAL — PASS`** (with the studio fixture blocker below).

### AMEND-6 — workload origin parity

Evidence: the question is who **PRODUCES** a kind, not who consumes it.

| Kind | Producer | Status |
|---|---|---|
| COMPUTE | `lowering.py` | DERIVED_ONLY |
| COLLECTIVE (×5) | `lowering.py` from `CollectiveIntent` | **AUTHORABLE** |
| P2P | `migration.py` only | DERIVED_ONLY (legacy import) |
| MULTICAST | `migration.py` only | DERIVED_ONLY (logical) |
| EXPERT_BEGIN/END | `migration.py` only | DERIVED_ONLY |
| PIM_CHANNEL/END | `migration.py` only | DERIVED_ONLY / BACKEND_INTERNAL |

`WorkloadV3` exposes `collectives` and **no** operations/p2p/multicast/pim
field. `migration.py` is **not called from the product path** (its only
reference is a comment in `lowering.py`).

**BROADCAST is safe:** `CollectiveIntent` refuses a BROADCAST without an
explicit `source_rank` — *"participants[0] is a legacy"* invention is named
in the refusal. Never silently dropped.

**CXL / REMOTE / STORAGE still refuse** at lowering with typed reasons.

### AMEND-7 — capability truth

77 rows (was 73). New: WORK-006 P2P, WORK-007 logical multicast, WORK-008
hardware multicast, WORK-009 static expert. MEM-007 rebuilt.

**The checker caught a real contradiction.** `check_capability_registry.py`
enforces a **TERMINAL** law: a `LEGACY_ONLY` stage makes every later stage
`NO`. My first MEM-007 draft claimed `DERIVABLE: LEGACY_ONLY` with
`PROJECTABLE: YES` and was **refused**. The correct characterisation is
that PIM's chain is legacy **end-to-end** — live code, legacy provenance —
and the row now says exactly that, with the nuance in `claim_scope`.

### Unresolved blockers

1. **Studio fixture staleness (pre-existing, now entangled).** 4 failures in
   `apps/studio/tests/test_studio_contract_v2.py`: 2 pre-existing
   (`test_provisioned_validator_proves_backend_fixtures_through_engine`,
   `test_fresh_provisioned_regeneration_bytes`) and 2 caused by AMEND-5
   moving the certified registry to v2. Regeneration was **attempted and
   reverted**: it absorbs ~43 lines of unrelated drift (staged-compilation
   `staged` block, `raw_evidence_digest`, `performance_result_id`,
   `producer_identity`) and then **breaks schema validation** —
   `test_all_committed_fixtures_validate_against_declared_contract_versions`
   fails on the regenerated `invalid-design.json`. The fixture set and its
   schema are mutually stale, independent of this work. Needs a separate
   deliberate refresh.
2. Two unrelated `TopologyError` classes (unchanged, deferred).
3. `flatfly` materializable, not authorable (unchanged).
4. `TopologyIR` CLI not restored (unchanged).

### Not started (out of tranche scope)

AMEND-8 synthesis adapter · AMEND-9 structural optimizer · AMEND-10 Studio
IA · Phase 3 Static Evaluate

---

## TRANCHE 2 CLOSURE — contract/versioning boundary

### The blocker was a SCHEMA BUG, not stale golden data

`views.py` has emitted `staged` and `stopped_at_stage` since **`2fdd758f`**
(staged compilation). `contracts/srota/v1/compilation.view.schema.json` was
last touched in **`a5b806fe`** — *before* that commit — and declares
`unevaluatedProperties: false`.

So the engine emitted fields its own contract forbade, and **every fixture
regeneration failed schema validation**. The fixtures were not stale; the
contract was. That is why the earlier regeneration attempt was reverted.

Fix: the schema now declares the fields (the product contract changed
intentionally — a staged refusal genuinely is not "compilation failed").
Both are **additive** and `types.ts` already has `staged?:` optional, so
this is backward compatible and `CONTRACT_VERSION` stays 1. A version bump
is reserved for an *incompatible* change.

### Four Studio failures — classified

| Test | Fields | Class |
|---|---|---|
| `test_generated_hashes_originate_from_engine_objects` | `metric_registry_id` | **AMEND-5 INTENTIONAL** |
| `test_optimization_fixture_originates_from_optimize_certified` | `metric_registry_id` | **AMEND-5 INTENTIONAL** |
| `test_provisioned_validator_proves_backend_fixtures_through_engine` | `compilation.staged`, `stopped_at_stage`, `producer_identity` | **SCHEMA BUG + PRE-EXISTING** |
| `test_fresh_provisioned_regeneration_bytes` | `performance_result_id`, `producer_identity`, `raw_evidence_digest` | **PRE-EXISTING STALE FIXTURE** |

### AMEND-5 identity impact — exactly four fields

```
optimization.completeness             AMEND-4 (new SearchCompleteness)
optimization.metric_registry_id       v1 -> v2
optimization.metric_registry_version  v1 -> v2
optimization.optimization_result_id   CONSEQUENCE (result_id binds registry id)
```

**Unchanged, proven by diff:** `design_hash`, `resolved_fabric_hash`,
`base_design_hash`, topology identity, candidate ids, the definition.
Design/topology/fabric identity is computed *before* any registry is
consulted, so adding metric projection cannot move it (FIX-8).

### The ~43 unrelated lines — classified, not absorbed

| Field(s) | Origin |
|---|---|
| `.compilation.staged`, `.stopped_at_stage`, `.produced_stages`, `has_*` | `2fdd758f` staged compilation |
| `.evaluation.performance_result_id`, `.requirements.*.performance_result_id` | pre-existing engine change |
| `.evaluation.backend_producer.producer_identity` | pre-existing engine change |
| `.evaluation.evidence.raw_evidence_digest` | pre-existing engine change |
| `.optimization.candidates[*].evaluation_ids`, `product_requirements` | same performance-result provenance |

Each traces to a named commit. These are **legitimate older changes that
were never regenerated** — not obsolete generator output, not accidental
drift. Handled in a **separate commit** (`6aa20f25`) with field-level
provenance so the two causes never blur.

### Commits

| Commit | Scope |
|---|---|
| `16bcf2eb` | gateway BookSim resolution + staleness reporting |
| `5dbab873` | **contract fix** + AMEND-4/5 fixture (4 fields, field-surgical) |
| `6aa20f25` | pre-existing fixture reconciliation (separate provenance) |

### FINAL TEST MATRIX

| Command | Passed | Failed | Skipped |
|---|---|---|---|
| backend `pytest tests/` | **4260** | **0** | 17 |
| studio `pytest tests/` | **10** | **0** | 1 |
| `npx tsc --noEmit` | exit 0 | — | — |
| `npx vite build` | exit 0 | — | — |
| `check_capability_registry` | PASS | — | — |
| `check_topology_family_registry` | PASS | — | — |
| `check_exposure_registry` | PASS | — | — |
| `check_intent_ontology` | PASS | — | — |
| `check_preset_certification` | PASS | — | — |
| `gen_feature_reclamation --check` | PASS | — | — |

**Every required command has zero failures.**

### Unresolved blockers

1. Two unrelated `TopologyError` classes (deferred; tree-wide change).
2. `flatfly` materializable, not authorable.
3. `TopologyIR` CLI not restored.
4. Gateway staleness is now *observable* but not *prevented* — a long-lived
   process still needs a restart. `/api/v1/health` reports it.

---

## FEATURE RECLAMATION IMPLEMENTATION TRANCHE 3

**Purpose:** prove an EXISTING synthesis engine can generate a canonical
candidate that enters the SAME compiler/verification/evaluation/visualisation
pipeline as an authored topology. Not structural optimization, not multiple
engines, not a broad topology catalog.

### Engine audit (from source, not names)

| Engine | Input | Output | Objective | Constraints | Determinism | Tests |
|---|---|---|---|---|---|---|
| `milp_topology_v2.py::solve_tmcf` | traffic matrix, layout, radix, max_len | chosen link set | traffic-weighted hops (or priced geodesic) | **link-capacity, flow conservation, radix** | yes (HiGHS) | **none in tree** |
| `milp_topology_v2.py::sa_synthesize` | same | adjacency | geodesic / priced | radix + connectivity | seeded | none in tree |
| `bo_synthesizer.py` | param registry | SynthResult | skopt GP | — | seed-dependent | none in tree |
| `iterative_synthesizer.py` | anonymous adjacency | `.anynet` | rollouts | connectivity | seed-dependent | none in tree |
| `event_objective.py` | adjacency | scalar | priced geodesic | — | deterministic | none in tree |

**Migration hole:** `tests/test_synthesis_loops.py` and
`tests/test_synthesis_math.py` exist **only on another branch** — the
synthesis modules are in the tree, their tests are not. Same pattern as
`TopologyIR`.

### Engine selection: MILP/TMCF

Deterministic under explicit inputs · emits an exact graph · radix and
link-length constraints are explicit · source is executable · no hidden
evaluator authority · no obsolete topology identity. Selected on those
criteria, not algorithm prestige.

### `diameter` REMOVED — the engine never enforces it

`milp_topology_v2` advertises *"optional diameter"* in its docstring, but
`solve_tmcf` adds only link-capacity, flow-conservation and radix
constraints. Exposing a constraint the engine ignores is a false capability
claim, so the field **does not exist** (SYN-18/19 asserts this).

### Science vs execution policy

| Class | Fields |
|---|---|
| **SCIENTIFIC_IDENTITY** | nodes, layout, k/rows/cols, layout_seed, jitter, radix, max_len, objective, pipe_cost, wire_cost, bandwidth_GBs, latency_ns, engine |
| **EXECUTION_POLICY** | timeout_s, max_nodes |
| **PROVENANCE** | algorithm, producer_id, generator_semantics_version, solver_status, objective_value |

SYN-4 proves a timeout/cap change does **not** move `definition_id`.

### Traffic authority

`SynthesisTrafficMatrix` — declared namespace, source artifact identity,
unit, aggregation rule, dimension. **No hidden fallback:** ragged, negative,
NaN, Inf, non-square, nonzero-diagonal, missing source and dimension
mismatch all refuse (SYN-8..10). The historical `load_matrix` validates
**nothing**; SYN-10b asserts that remains true so the adapter's rationale
stays honest.

### Identity laws

- `candidate_id` binds **definition + traffic + exact graph** only —
  excludes algorithm, solver status and the `.anynet` projection, so two
  runs producing the same graph describe the same scientific candidate.
- `graph_id` binds the graph alone (SYN-27: changed traffic → different
  candidate, **same** graph_id).
- `generator_semantics_version` is provenance, not identity (SYN-30).

### Solver honesty

`OPTIMAL` is reported **only** when the solver proved optimality of the
encoded MILP — never inferred from an incumbent. scipy status 1 (time
limit) maps to `TIME_LIMIT` even when a solution exists. The 4×4 fixture
genuinely solves to **OPTIMAL**, so SYN-37 tests the real claim; SYN-38b
tests the time-limited case is **not** promoted.

### Convergence — the central proof

```
SynthesisDefinition + SynthesisTrafficMatrix
  -> milp_topology_v2 (UNMODIFIED)
  -> TopologyCandidate
  -> TopologyIR (kind=custom)        <- SAME representation as authored
  -> materialize_ir -> TopologyArtifact
  -> [STOPS: FAB-007, the compiler request cannot carry an explicit graph]
```

SYN-22: a synthesized graph and the **identical hand-authored graph**
produce the **same `topology_hash`**. Origin differs; science does not.

### Honest stopping point

`TopologyFamily.CUSTOM` refuses with a typed error pointing at
`materialize_ir`. A synthesized graph stops at **exactly the same stage** as
an authored custom graph — synthesis is not special-cased to bypass a
missing stage. Legacy direct `MILP -> AnyNet -> BookSim` scripts remain
developer tooling and are **not** the canonical path.

### Fixture

4×4 grid, 16 routers, radix 4, max_len 1.0 → **OPTIMAL in ~0.2s**, 24 links.
Practical as an ordinary test and it makes solver honesty provable.

### Tests

**43 new** (SYN-1..SYN-40), 10.8s total.

### Final test matrix

| Command | Passed | Failed | Skipped |
|---|---|---|---|
| backend `pytest tests/` | **4303** | **0** | 17 |
| studio `pytest tests/` | 10 | 0 | 1 |
| `npx tsc --noEmit` | exit 0 | — | — |
| `npx vite build` | exit 0 | — | — |
| capability / topology / exposure / ontology / preset gates | PASS | — | — |

### Not started (out of tranche scope)

Structural optimization · BO/SA/iterative adapters · additional topology
families · product API/CLI entry point for synthesis · Studio UI.

---

## FEATURE RECLAMATION IMPLEMENTATION TRANCHE 4

**Goal:** make explicit/custom topology a first-class canonical
`CompileRequest` input and carry it through the ordinary compiler until the
next genuine capability boundary.

### FAB-007 traced and resolved at the CONTRACT boundary

`CompileRequestV3` gained `explicit_topology: TopologyIR | None`. The
**topology-selection law**: a request expresses EXACTLY ONE source.

```
NAMED     noc_config.topology_family names a family
EXPLICIT  explicit_topology carries the graph (TopologyIR kind=custom)
```

Both declared → refused ("two authorities for one fact"). A TEMPLATE kind
smuggled through the explicit door → refused. Not resolved by catching the
exception or injecting side state.

### §6 — origin must not enter design identity

The subtle rule. `TopologyIR.scientific_dict()` excludes `name`:

| | Persistence (`to_dict`) | Identity (`canonical_dict`) |
|---|---|---|
| content | lossless (label + backend policy) | `kind`, `nodes`, `links`, `link_attrs` only |

So a synthesized candidate and the identical hand-authored graph are **the
same design**. CFAB-8/8b pin it.

### Named identities PROVEN unchanged

Measured at the parent commit and after, byte-identical:

```
mesh4            e04583a3e1bf2dfd6f1fd8832b80a35149342439
mesh4_hbm        0d7a4654bcb004ce99a7b4411f8d024ca2b79f77
mesh4_wide128    df68df8d5af9a6fbeccf0cd8b86e2113165972b1
```

### The honest boundary moved from TOPOLOGY to ROUTING

```
NAMED (mesh)                -> FULL COMPILE, 25 routers
EXPLICIT 4x4 (16 routers)   -> STOPS at ATTACHMENT: "16 seats but 20 agents"
EXPLICIT 5x5 (25 routers)   -> STOPS at ROUTING: "no certified routing
                               derivation for topology family 'custom'"
produced: INPUT, INPUT_MAPPING, TOPOLOGY, ATTACHMENT
```

The 4×4 case is the §14 **capacity law** working: excess attachment demand
refuses. Unused seats stay legal and produce no fake endpoints (CFAB-22/24).

### Routing audit (§16) — §18 option C, deliberately

`derive_route` certifies **MESH and CONCENTRATED_MESH (DOR_XY) only** and
refuses a custom family with a typed error rather than letting a backend
choose routes independently — the §17 prohibited state.

**`routing_materialize.py` ALREADY has** `WEIGHTED_SHORTEST_PATH` ("minimum
sum of `DirectedChannel.route_weight`, tie-break lexicographically smallest
full channel-id sequence") and `ANYNET_MIN_HOPS`, both producing the same
sealed `RouteArtifact`. So the graph-general deterministic router **exists**
— but wiring it into the compiler ROUTING stage is a routing tranche, and
the brief says C is acceptable and forbids implementing routing to make the
tranche look end-to-end. **Recorded as the named candidate, not done.**

### Historical contract reclaimed, not invented

`SROTA_FABRIC_SEMANTICS_V1.md` (branch `integration/p1-product-rt-candidate`
@ `26e6f9dc`) already ruled `model/topology_ir.py` = **"EVOLVE —
materialization authority"**, and its P0 finding **C-01** states:
*"RouteArtifact sole route truth; consumers ingest or prove equivalence"*.
Tranche 1 used TopologyIR on that basis; Tranche 4 completes it.

### Gap found and fixed

`TopologyIR.from_dict` was **not a closed schema** — it dropped unknown
fields. §8 requires strictness, so `_DOC_KEYS` now refuses them (CFAB-6).

### Migration holes recorded (not fixed)

- `tests/test_synthesis_loops.py`, `test_synthesis_math.py` — other branch only.
- `test_architecture_law.py`, `FABRIC-COMPILER-AUTHORITY.md` — other branch only.
- `TopologyIR` CLI (`cmd_topology_render/_stats/_diff`) — other branch only.

### Final test matrix

| Command | Passed | Failed | Skipped |
|---|---|---|---|
| backend `pytest tests/` | **4326** | **0** | 17 |
| explicit-request focused | 116 | 0 | — |
| capability / exposure / topology / ontology / preset gates | PASS | — | — |

23 new tests (CFAB-1..CFAB-40).

### Not started (out of tranche scope)

Structural optimization · routing materialization into the compiler stage ·
synthesis product/API seam · candidate promotion API · Studio UI ·
BO/SA/iterative adapters.

---

## FEATURE RECLAMATION IMPLEMENTATION TRANCHE 5

**Goal:** determine whether an existing graph-general route producer is
suitable as canonical custom-fabric routing authority, and if so wire it
into the normal compiler.

### TRANCHE-4 SEAL — CFAB accounting corrected

The Tranche-4 report said *"23 new tests (CFAB-1..CFAB-40)"*. That was
misleading. The honest mapping:

| CFAB | Status |
|---|---|
| 1–8 (request identity, round trip, selection law, strict schema) | **PASS** (10 test functions) |
| 9–13 (promotion) | **NOT_IMPLEMENTED** — no promotion API exists |
| 14–19 (compiler convergence) | **PASS**, updated this tranche (see below) |
| 20 (seat capacity respected) | COVERED_BY_OTHER_TEST (21/22/24) |
| 21, 22, 24 (capacity, unused seats, no fake endpoints) | **PASS** |
| 23 (heterogeneous seat capacity) | **NOT_IMPLEMENTED** — TopologyIR has no seat field |
| 25–31 (routing) | **NOT_IMPLEMENTED in T4** — delivered in T5 |
| 32–36 (API/product seam) | **NOT_IMPLEMENTED** |
| 37, 38 (schema before persistence) | COVERED_BY_OTHER_TEST (39) |
| 39, 40 (stale hash, parser) | **PASS** |

23 test functions covered roughly CFAB-1..8, 14..19, 21/22/24, 39, 40 — not
all 40. **The aggregate hid a large NOT_IMPLEMENTED block.**

### TopologyIR identity audit

| field | class | identity |
|---|---|---|
| `name` | PRESENTATION | excluded (proven: synthesized and authored hash equal) |
| `kind`, `nodes`, `links`, `link_attrs` | SCIENTIFIC_SEMANTIC | **included** |
| `routing`, `booksim_params`, `rtl` | BACKEND_PROJECTION | excluded |
| `dims` | BACKEND_PROJECTION (analytical leg) | excluded |

**`route_weight` (§6/§7).** It is a `DirectedChannel` field, so it IS in
`TopologyArtifact` identity — a weight change moves `topology_hash`.
**But `TopologyIR` has no `route_weight` field**, so every explicit graph
materializes with `route_weight=1` and `WEIGHTED_SHORTEST_PATH` currently
degenerates to minimum-hop. **Honest gap**, pinned by
`test_route_c_2b_route_weight_cannot_vary_for_explicit_topology_yet` so the
day weights are added the identity question re-opens deliberately.
**Semantics: dimensionless routing cost** — not latency, not distance.

### Routing producer audit (§8/§9) — three independent questions

| Producer | Derives? | Verifiable? | Backend executes? |
|---|---|---|---|
| `DOR_XY` | yes | **yes, by construction** | mesh yes |
| `WEIGHTED_SHORTEST_PATH` | **yes** | **yes — CDG check runs** | **no equivalence** |
| `ANYNET_MIN_HOPS` | yes | yes | BookSim-coupled name |
| `CUSTOM_STATIC` | yes | depends on the table | no |
| `tools/flow_certifier` CDG | n/a | **graph-general (Dally-Seitz)** | n/a |

### Selected policy: `WEIGHTED_SHORTEST_PATH` (§10/§11/§12)

Chosen on **canonical semantic clarity**, not convenience: self-contained
deterministic Dijkstra over `(sum route_weight, channel-id sequence)`,
backend-neutral name, explicit traversal-independent tie-break, defined over
canonical **directed** channels, handles parallel links individually.

`ANYNET_MIN_HOPS` was **not** chosen: its name and `anynet_ascending_min`
tie-break encode a BookSim backend concept (§12 backend-coupling debt).

### Ownership: a DECLARED table, not a hidden branch (§13)

`model/routing.py::_POLICY_BY_FAMILY` is the authority — data, inspectable
via the public `routing_policy_for(topology)`.

```
MESH, CONCENTRATED_MESH -> DOR_XY                 (deadlock-free BY
                                                   CONSTRUCTION)
CUSTOM                  -> WEIGHTED_SHORTEST_PATH (deadlock-freedom is a
                                                   PROPERTY CHECKED)
TORUS/RING/FLATFLY      -> absent (typed refusal)
```

**Torus/Ring/FlatFly are deliberately absent.** Measured: a 5×5 torus
routes fine and the CDG then reports `acyclic=False` with a 6-node cycle.
That is a real, useful verdict — but widening those families changes an
existing contract (torus currently stops at ROUTING) and is a separate,
deliberate decision. Tranche 5's purpose is **custom** fabrics.

### Measured outcomes — the CDG does real work

| Graph | status | certificate | `DEADLOCK_FREE` |
|---|---|---|---|
| 5×5 explicit mesh | **COMPILED** | **PASS** | `acyclic: true`, 80 nodes, 124 edges |
| 25-node ring | **INVALID** | **FAIL** | `acyclic: false` + 6-node **cycle witness** |
| chorded irregular | INVALID | FAIL | real cyclic CDG |

A deadlock stays a deadlock with a witness — **no reroute magic**.
Custom topology gets the **full 10 obligations**, not a smaller certificate.

### Independent oracle (§19/§20)

`test_custom_routing.py` implements its own BFS/Dijkstra — it never imports
the production producer. Comparison law: **cost must always agree**;
**next-hop must agree where the choice is unique** (ties may legitimately
break differently, which is why an independent formulation is evidence
rather than tautology). Verified on a diamond ladder, a non-grid
caterpillar, and a 5×5 mesh.

### Origin equivalence

A synthesized graph and the identical hand-authored graph produce the same
`topology_hash`, route table, `ResolvedRouteArtifact` and `VCAssignment`.
Only the label differs.

### BookSim boundary (§25/§27) — REFUSED, not weakened

BookSim AnyNet computes its own routes. **No exact ingestion and no
all-pairs equivalence has been established**, so `PROJECTABLE` and
`EXECUTABLE` stay **NO** for custom fabrics. Custom topology compiles and
certifies; backend execution is UNAVAILABLE. The rule was not weakened to
make custom evaluation work.

### Escape VCs — the finding that shaped the design

`derive_vc_assignment_artifact_v3` never passes `escape_vcs` (defaults to
`()`), and `make_vc_assignment_artifact` documents "no escape VC is
designated". So the CDG must be acyclic **without** escape channels — which
is why a mesh passes and a ring fails. This is honest: the certificate
reports the truth rather than routing around it.

### Final test matrix

| Command | Passed | Failed | Skipped |
|---|---|---|---|
| backend `pytest tests/` | **4344** | **0** | 17 |
| `test_custom_routing.py` | 16 | 0 | — |
| `test_explicit_topology_request.py` | 25 | 0 | — |
| capability / topology / exposure / ontology / preset gates | PASS | — | — |

Named-family identity re-verified unchanged:
`mesh4 e04583a3… · mesh4_hbm 0d7a4654… · mesh4_wide128 df68df8d…`

### Not done in this tranche (honest)

Synthesis product/API seam · promotion API · TopologyIR CLI disposition ·
historical test reclamation · MCTS/MCLB and escape/up-down audit ·
BookSim route equivalence · Torus/Ring/FlatFly routing widening ·
structural optimization.

---

## TRANCHE 5 CLOSURE PASS

### ROUTING ORACLE CORRECTED (§1/§2)

The earlier oracle checked **cost**, and the next hop **only when the
optimum was unique**. That is insufficient: the tie-break IS part of the
canonical route function.

`tests/routing_oracle.py` now implements the SAME specification as a
**different algorithm** — Bellman-Ford on cost alone (forward and reverse),
then a greedy lexicographic walk over the min-cost DAG. No heap, no settled
set, no production import. Comparison is on the **complete channel-id
path**, always.

Adversarial fixtures: equal-cost diamond · diamond ladder (different first
hops) · late divergence (same first hop, different later sequence) ·
symmetric cycle · triple equal-cost paths · irregular with a chord · the
compiled 5×5 mesh. **14 tests pass**; a guard test asserts the suite is not
vacuous (the diamond must contain ≥2 min-cost first hops).

### ROUTE-WEIGHT DECISION (§3/§4) — **OUTCOME B**

| Evidence | Finding |
|---|---|
| `DirectedChannel.route_weight` | exists, `minimum=1`, in `TopologyArtifact` identity |
| `TopologyIR` | **no route_weight field** |
| `materialize_ir` | uniform; every explicit graph gets weight 1 |
| `booksim_projection.py` | "uniform channel latency 1, route_weight 1, no parallel channels" |

**Weighted routing is NOT an authorable canonical semantic.** TopologyIR
stays unweighted and the contract is exposed honestly as **deterministic
minimum-hop routing with lexicographic channel-id tie-break**.
`WEIGHTED_SHORTEST_PATH` remains the **implementation producer** (accurate:
it minimises `route_weight`); it is not a product claim that users can
author weights. Semantics of the weight: **dimensionless routing cost** —
not latency, not distance.

### POLICY IDENTITY (§5)

`_POLICY_BY_FAMILY` is compiler-owned and **not user-selectable**: there is
no request field for routing policy, so no two policies can alias. The
selected class is carried into the certificate evidence as
`cdg_route_classes`, so the route science is visible in the proof. **No
hidden unversioned algorithm selection**: the table is the single owner and
`routing_policy_for()` exposes it.

### CFAB-23 — HETEROGENEOUS SEATS (§6) — **PASS with invariant**

Heterogeneous capacity **IS representable**: `Router.seat_capacity` is
per-router and `TopologyArtifact` validates it per-router. Verified with a
{2, 5} artifact that round-trips.

**Invariant:** it is **not authorable** — `TopologyIR` has no seat field, so
`materialize_ir` takes a single uniform `seat_capacity`. Representable in
the artifact, not expressible in intent.

### PROMOTION CONTRACT (§7/§8/§9) — **IMPLEMENTED**

`promote_to_explicit_topology(candidate, definition)` and
`apply_promotion_to_request_doc(doc, promotion)`.

**A BUG MY OWN TEST CAUGHT.** The first implementation put
`synthesis_provenance` into `_semantic_dict()`, which feeds
`canonical_dict()` — so **origin entered design identity** and a promoted
candidate was NOT the same design as the identical manual graph
(`DESIGN IDENTICAL: False`). Moved to `to_dict()` only, after identity is
settled. Now:

```
provenance in design identity?  False
provenance persisted?           True
DESIGN IDENTICAL                True
TOPOLOGY / ROUTES / VC IDENTICAL True
certificate                     COMPILED PASS
```

Stale promotion refuses on: wrong `expected_candidate_id`, changed
definition, non-SUCCEEDED status, and failure to re-verify against the
candidate's own wire form. No `SynthesizedDesign` type exists.

### TOPOLOGYERROR (§24) — **CLOSED**

The two classes have distinct, legitimate owners:

| class | owner | is SemanticError? |
|---|---|---|
| `core.errors.TopologyError(VeritXError)` | TopologyIR / schema layer | no |
| `model.topology_artifact.TopologyError(ValueError, SemanticError)` | artifact construction | yes |

**Proven not to escape untyped:** a malformed `explicit_topology` in a
request document is mapped to the typed `CompileRequestV3SchemaError`
(`"invalid explicit_topology: TopologyIR: links[0] endpoint 9 out of
range"`). The application boundary catches it. Blocker closed with evidence,
not deferred.

### BOOKSIM ROUTING AUDIT (§15–§19) — **OUTCOME C**

| Question | Finding |
|---|---|
| AnyNet route algorithm | `AnyNet::route()` — Dijkstra over `std::set<int>`, **strict `<`** |
| tie-break | **smallest router id** (ascending set iteration) |
| weight interpretation | **hop count** (`"distance is hops not cycles"`) — ignores `route_weight` |
| execution | `min_anynet` is a **table lookup** (`global_routing_table[r][dest]`) |
| exact ingestion | **NOT AVAILABLE** — `routing_dump_file` is **output-only** |
| export for comparison | **EXISTS** — VeritX `B3.7b` dump: `src_router/dst_node/next_router/port` |
| equivalence machinery | **EXISTS and is generic** — `route_observation.expected_route_rows(routing_class=...)` takes the class as a parameter and is wired into `booksim_execution.py` |

**Canonical tie-break is smallest channel-id sequence; BookSim's is smallest
router id. They diverge on ties.** So:

- **A (exact ingestion):** unavailable — no input path
- **B (exhaustive equivalence):** mechanically possible (the dump and a
  generic comparator both exist) but **NOT established**, and would fail on
  ties as specified
- **C: BACKEND_EXECUTION_UNAVAILABLE**

### STRUCTURAL-OPTIMIZATION READINESS

**STRUCTURAL PERFORMANCE OPTIMIZATION — BLOCKED ON CUSTOM BACKEND
EXECUTION.** Under outcome C a generated custom candidate cannot obtain
qualified BookSim metrics, so Wave-F structural optimization must not
begin.

### Final test matrix

| Command | Passed | Failed | Skipped |
|---|---|---|---|
| backend `pytest tests/` | **4370** | **0** | 17 |
| tie-break oracle | 14 | 0 | — |
| promotion | 12 | 0 | — |
| custom routing | 16 | 0 | — |
| capability / topology / exposure / ontology / preset gates | PASS | — | — |

### NOT COMPLETED in this pass (honest)

- §10 synthesis **product/control-plane seam** — no application operation
- §11 explicit/promoted compile through the **gateway/API**
- §13 TopologyIR CLI disposition
- §14 historical test reclamation
- §17 BookSim equivalence **run** (audit done, run not attempted)
- §20 qualification envelope
- §26 CFAB-1..40 regenerated matrix
