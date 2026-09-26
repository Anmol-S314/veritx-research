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
