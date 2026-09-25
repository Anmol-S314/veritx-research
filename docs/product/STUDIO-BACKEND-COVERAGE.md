# STUDIO-BACKEND-COVERAGE — Backend → Product Surface Map (UX0)

Status: **UX0 audit of `integration/studio-reconciliation` @ `8cd1198b`.**
Every row was verified against actual source in this tree, not against docs
or earlier audit prose. This file is the gate for all Studio work (§61):
no UI feature ships that is not an A row or an explicitly-scoped B row.

Presentation eligibility vocabulary (§2):

| Class | Meaning | Studio behavior |
|-------|---------|-----------------|
| **A** | PRODUCT READY — canonical authority, stable contract, qualified semantics | normal actionable surface |
| **B** | INSPECTABLE — real capability/evidence, not yet primary workflow | advanced/inspection surface with explicit scope |
| **C** | EXPERIMENTAL — implementation exists, qualification incomplete | Trust/Experimental section only |
| **D** | UNSUPPORTED / NOT ESTABLISHED | limitation statement only |

---

## 1. Compilation

| Field | Finding |
|---|---|
| Capability | Canonical fabric compilation (topology → attachment → route → VC → packet format → router behavior → address decode → fabric) |
| Canonical authority | `veritx_dse/application/fabric_compiler.py` (`FabricCompiler`, `Compilation`), `veritx_dse/model/compile_model.py` (`CompileRequestV3`) |
| Artifact / evidence | `Compilation.bundle.root_hashes()` carries: `topology_hash`, `attachment_hash`, `mapping_hash`, `router_route_hash`, `resolved_route_hash`, `vc_assignment_hash`, `packet_format_hash`, `router_behavior_hash`, `address_decode_hash`, `fabric_hash`, `resolved_fabric_hash` (verified in `application/views.py::compilation_view`) |
| Qualification | Compiler is the canonical authority; certificate gates its output |
| Existing application service | `FabricCompiler().compile(request)`; status ∈ `COMPILED` / `INVALID` / `UNSUPPORTED` |
| Existing product API | `POST /api/v1/projects/{id}/compile` → `product.compile_draft`; `GET /api/v1/revisions/{id}/compilation` |
| Existing Studio surface | Design page compile flow; CompilationView with obligations (contract v1) |
| Missing product adapter | Read-only artifact views (AttachmentView, MappingView, RoutingSummaryView, VCAssignmentView, PacketFormatView, RouterBehaviorView, AddressDecodeView, FabricIdentityView) — §12 of the program. All are pure projections of existing bundle artifacts; none exist yet. |
| Missing UI | Artifact DAG inspector (§14); per-artifact detail panels |
| Class | **A** (compile/verify path); artifact views missing → the *views* are the remaining work, not the capability |

## 2. Verification (certificate)

| Field | Finding |
|---|---|
| Capability | Ten LOCKED obligations, exactly: `TOPOLOGY_CONNECTED`, `ATTACHMENT_COMPLETE`, `ADDRESS_DECODE_VALID`, `ROUTE_COMPLETE`, `ROUTE_LEGAL`, `VC_ASSIGNMENT_VALID`, `DEADLOCK_FREE`, `MAPPING_VALID`, `PACKET_FORMAT_VALID`, `FABRIC_DAG_VALID` (verified: `veritx_dse/verification/certificate.py::OBLIGATIONS`) |
| Canonical authority | `verification/certificate.py` (`Certificate`, `ObligationResult`) |
| Artifact / evidence | Each obligation: `{obligation, status (PASS/FAIL only), method, evidence{}}`. `Certificate.certificate_id()`, `.overall` |
| Qualification | Canonical; fail-closed (non-semantic errors abort certification) |
| Existing product API | `compilation_view.obligations` (already served); revision views carry certificate |
| Existing Studio surface | `VerifyView.tsx`: obligation list, click → evidence, auto-selection of first obligation |
| Missing product adapter | Obligation *presentation* metadata (human-readable meaning per obligation, key-evidence selection per obligation, bound artifact identities). Must stay presentation-only (§48): no proof logic in views. |
| Missing UI | Deadlock evidence display (`SCCs > 1`, bound hashes); ROUTE_COMPLETE expected/actual counts; obligation → artifact identity cross-links |
| Class | **A** — one of the strongest backend features; presentation depth is the gap |

## 3. Topology materialization

| Field | Finding |
|---|---|
| Canonical authority | `application/views.py::topology_view` — explicitly documented as the ONLY shape Studio may draw |
| Artifact / evidence | `topology_hash`, `attachment_hash`, `family`, `routers[]`, `channels[]`, `physical_links[]`, `endpoints[]` (endpoint_id, kind, group/instance, router_id, port_id), `counts{routers, channels, seats, endpoints}` |
| Key semantics | Returns `None` for non-COMPILED compilation — a failed proof is never a fabric |
| Existing product API | `GET /api/v1/revisions/{id}/topology` → `product.get_revision_topology` (re-derivation would let the drawn graph drift from the proof — guarded, verified in `product/service.py`) |
| Existing Studio surface | `FabricCanvas` / `FabricCanvas3D` draw the certified topology |
| Class | **A** |

## 4. Workload lowering

| Field | Finding |
|---|---|
| Canonical authority | `veritx_dse/workload/graph.py` (`WorkloadGraph`), `workload/messages.py` (`LogicalMessageArtifactV2` → `message_artifact_id`), `workload/traffic.py` (`PhysicalTrafficArtifactV2`), collective lowering in compiler/evaluator chain |
| Artifact / evidence | `EvaluationView` carries `workload_id`, `message_artifact_id`, `physical_traffic_id` |
| Existing Studio surface | Catalog view of workloads (model, serving mode, parallelism, collectives); lowering identities shown on run evidence |
| Missing product adapter | Human-readable lowering projection (message/traffic summary view) — **B**: internal Python objects must never be exposed directly (§29). No stable product view exists yet for per-collective lowering detail. |
| Class | **A** for identities; **B** for lowering-detail projections |

## 5. Evaluation (EvaluationView)

| Field | Finding |
|---|---|
| Canonical authority | `application/fabric_evaluator.py::EvaluationOutcome.to_view_dict` (contract v1, `contracts/srota/v1/evaluation.view.schema.json`) |
| Carries (verified) | `status`, `design_hash`, `resolved_fabric_hash`, `workload_id`, `message_artifact_id`, `physical_traffic_id`, `backend_producer{backend, producer_identity, config_hash, input_hash}`, `evidence{raw_evidence_digest, stats_digest}`, `performance_result_id`, `network_traffic_window`, `metrics{}`, `fidelity_warning`, `reason` |
| Existing product API | Run records carry the full evaluation view (`product/service.py::_run_evaluation`) |
| Existing Studio surface | Run tables show status/qualification/completion; run detail reads evidence via `/runs/{id}/evidence` |
| Missing UI | Structured run-detail sections (Summary / Performance / Requirements / Integrity / Evidence / Artifacts) that surface every EvaluationView field instead of a thin table — §16/§20 |
| Class | **A** |

## 6. Product requirements (RequirementReport)

| Field | Finding |
|---|---|
| Canonical authority | `application/requirements.py` — verdicts exactly `SATISFIED` / `VIOLATED` / `UNMEASURABLE` / `NOT_APPLICABLE`; binding + UNMEASURABLE never passes (`report_passes()`); non-binding entries advisory |
| Carries | requirement index, traffic class, QoS class, binding, required value, measured value, metric authority, performance result id, reason |
| Existing product API | Run records carry `requirements` (report) + `requirements_pass` |
| Existing Studio surface | Runs table shows aggregate pass/fail only |
| Missing UI | Per-requirement four-state display (§19) with binding/reason/authority |
| Class | **A** — backend complete; UI reduces it to binary today (program violation to fix in UX7) |

## 7. Executed-route evidence

| Field | Finding |
|---|---|
| Canonical authority | `backend/route_observation.py` (`parse_route_dump`, `expected_route_rows`, `compare_route_realization`); evidence field `route_observation ∈ {DOMAIN_QUALIFIED_ROUTE_NOT_OBSERVED, EXECUTED_ROUTE_OBSERVED}` + `route_dump_sha256` (`backend/evidence.py` v3) |
| Scope (verified) | First-hop realization ONLY. `route_observation.py` states it "proves deterministic first-hop routing equivalence, not observed packet paths". Studio must say `FIRST-HOP REALIZATION OBSERVED`, never "full path verified" |
| Existing product API | Evidence documents served via `/runs/{id}/evidence` (with bundle verification first) |
| Missing UI | Route realization panel (§17): status, scope, coverage, expected/realized digests |
| Class | **A** (evidence exists, authenticated); UI panel missing |

## 8. Conservation

| Field | Finding |
|---|---|
| Canonical authority | `backend/booksim_execution.py` stats parser + gate; `backend/booksim_projection.py::verify_trace_conservation` (flit conservation gate before every spawn) |
| Exact fields (verified) | `loaded_trace_packets`, `injected_trace_packets`, `delivered_packets`, `flits_injected`, `flits_accepted`; declared flits come from `conservation["flits_total"]`; gate enforces `flits_injected == flits_accepted == expected_flits`. **No packet "declared" counter distinct from trace packets; no separate packet-level declared/loaded/injected/delivered quartet beyond these.** Absent counters must render NOT AVAILABLE, not zero (§18). |
| Existing Studio surface | None — hidden inside `backend-evidence.json` |
| Missing UI | Conservation panel from authenticated stats only |
| Class | **A** (evidence); UI missing |

## 9. RunBundle / verify-run / reproduce

| Field | Finding |
|---|---|
| Canonical authority | `core/run_bundle.py` (`verify_run_bundle`, `finalize_run_bundle`, `checksums.json`); `backend/reproduce.py::reproduce_booksim_run_bundle` ("Verify, re-execute and compare; refuse any scientific divergence"); CLI `veritx verify-run` / `veritx reproduce` |
| Existing product API | Bundle verification runs automatically inside `_verify_run_bundle` on every run read (§53 satisfied); runs listing shows VERIFIED/INVALID. **No `POST /runs/{id}/verify` or `/reproduce` product endpoint yet** — the deprecated alias layer returns verification summaries, and reproduction exists only via CLI |
| Missing product adapter | Thin endpoints that CALL `verify_run_bundle` / `reproduce_booksim_run_bundle` (no verification logic in gateway, §21–22) |
| Missing UI | Verify Bundle button; Reproduce action with SCIENTIFIC MATCH vs environment-metadata distinction per the canonical authority |
| Class | **A** (authorities canonical + tested); adapters/UI missing |

## 10. Optimization (OptimizationStudyView v2)

| Field | Finding |
|---|---|
| Canonical authority | `optimization/result.py` — `_to_study_view_v2` with per-candidate `guided_patch`, `locked_consequences`, `pareto_member`, `pareto_eligible`, constraint verdicts, `selection_rationale`, `result_class` (`CERTIFIED_PRODUCT` / analytic), metric registry identity, budget, seed |
| Three authorities | PRODUCT REQUIREMENTS / OPTIMIZATION CONSTRAINTS / MEASURED OBJECTIVES are distinct in the contract |
| Existing product API | `POST /api/v1/revisions/{id}/optimize`, `GET /api/v1/optimizations/{id}` |
| Existing Studio surface | `OptimizeView.tsx` already renders v2: result_class, metric registry, guided patch, locked consequences (JSON), pareto membership (backend-owned), selection rationale, constraint rollup |
| Missing UI | Constraint verdicts per candidate as first-class four-state cells; objective MEASURED/UNMEASURABLE display; Pareto scatter only when ≥2 numeric measured objectives (§27) |
| Class | **A** — the merged tree already carries most of §24–28; remaining gaps are presentation cells |

## 11. Capabilities & qualification

| Field | Finding |
|---|---|
| Canonical authority | `application/capabilities.py::capability_registry` (derived from sealed backend modules, not hand-copied); `product/qualification.py` loads `docs/production/ENGINE-QUALIFICATION.json` (single machine-readable authority; hand-copied dict deleted) |
| Key truths (verified) | BOOKSIM_STANDALONE: lowering/execution/route-evidence SUPPORTED, exact_fabric CONDITIONAL. SERVING_BOOKSIM2: execution BLOCKED. wave_e: network timing = aggregate window, per-operation causality UNSUPPORTED, wall time REQUIRES_EXPLICIT_CLOCK, compute calibration UNCALIBRATED, unsupported list includes throughput. Deferred: area/power/energy, RTL/UVM/formal NOT_RUN. ENGINE-QUALIFICATION.json: booksim engines QUALIFIED; rtl ESTABLISHED (RTL domain); ramulator ESTABLISHED (memory battery 16/16); **astra integration QUALIFIED but numerical NOT_ESTABLISHED**; workload levels W0 RUN, W1–W3 owed. |
| Existing product API | `GET /api/v1/qualification`; capabilities registry served via alias layer |
| Existing Studio surface | Trust/qualification surface exists |
| Missing UI | Capabilities page (§36) with supported/unsupported operations; validation campaign display (below) |
| Class | **A** |

## 12. Memory (Ramulator)

| Field | Finding |
|---|---|
| Canonical authority | `simulation/ramulator.py` — typed metrics, assumptions, fidelity, producer identity |
| Integration status (verified) | **NOT part of the Product Run pipeline**: no reference to ramulator in `product/service.py` or `fabric_evaluator.py`. Engine-qualification lists it ESTABLISHED for the memory battery (16/16) — a standalone qualified analysis, not coupled NoC+memory evidence. |
| Class | **B** (SEPARATE QUALIFIED ANALYSIS). No Memory tab on Runs. Adapter only via §37 chain (product service → canonical lowering → Ramulator → MemoryEvidence) if ever added. |

## 13. ASTRA

| Field | Finding |
|---|---|
| Canonical authority | `docs/production/ENGINE-QUALIFICATION.json` (current, refreshed by R2 commits): integration QUALIFIED, **numerical NOT_ESTABLISHED**, qualified_domains empty, limitations name F-ASTRA-0001 fix and pending independent per-domain timing oracles |
| Class | **C** for absolute timing (NOT ESTABLISHED — display exactly that); model-domain projection code exists (runtime integration QUALIFIED) but no certified product objective path. Never label ASTRA PASS globally. |

## 14. Serving

| Field | Finding |
|---|---|
| Canonical authority | `backend/canonical_serving.py`, `simulation/serving_runtime.py` + serving loop/DP/EP modules; R1.x prod commits added serving qualification domain statuses (explicit, **no global PASS**), independent scheduling oracle, runtime EP qualification from executed round ledger, multi-instance liveness proof |
| Product adapter | **None** — no `ServingExperiment/ServingJob/ServingRun` in `veritx_dse/product/`; no product endpoint |
| Class | **B/C**: capability + validation evidence only (Trust page). No Serving dashboard, no TTFT display as certified (§39/§65). |

## 15. Validation

| Field | Finding |
|---|---|
| Canonical authority | `validation/reports/V01–V14.json` (machine-readable: fabric, workload, authority vs veritx results, per-check verdicts — verified V01 structure); `validation/reports/{MUTATIONS,METAMORPHIC,INTERVENTION,ENGINES,PRODUCTION-WORKLOAD-TRUST}.md`; `validation/FINDINGS.md` (F-0001..F-0007, F-ASTRA-0001/0002 — what failed, how detected, fix, regression) |
| Existing Studio surface | None |
| Missing product adapter | A read-only projection over `validation/reports/*.json` + parsed findings records. V-reports are JSON (use directly); campaign MD reports stay prose-linked until machine-readable (§34: do not parse unstable prose). |
| Class | **B** — high-value Trust content; adapter is thin and safe |

## 16. State model, revision integrity, runs scoping

Verified in the merged tree (these are DONE, not gaps):

- **latest attempt vs active revision** (`product/service.py::_ensure_revision_pointers`, `_revision_promotable`): only COMPILED+PASS promotes; refused attempts never replace the active revision. Evaluation refuses non-promotable revisions with typed CONFLICT.
- **run scoping**: `project_view` carries `active_revision`, `latest_attempt`, and run lists scoped by revision; `latest_active_run` scoped to the active revision (§4).
- **execution identity parity** (`_check_compilation_parity`): every evaluation recompiles the stored request and demands exact equality of ALL recorded artifact hashes before spawn; drift → `EVIDENCE_INVALID` refusal (§5).
- **topology draw guard**: `get_revision_topology` refuses re-derivation drift (§52).

Remaining gaps (UX1–UX12 will pin with tests): the §50 browser regression sequence (r01→r02 unsupported) exists as backend tests; browser-level assertions need the live E2E extended.

## 17. Studio surface inventory (current, merged tree)

- Pages: `pages/index.tsx` (overview/runs), `design.tsx` (single DesignEditor — §6 satisfied: "The one editable Design Intent form... There is no second editor"), `optimize.tsx`, `offline.tsx`.
- Pipeline bar: status-only (§43 satisfied); context header shows Project / Revision (+ DRAFT UNCOMPILED) / Workload / Latest run (active-revision-scoped) / Next action (§44, human labels for internal enums, §32).
- VerifyView: 10 obligations, auto-select first, click → evidence.
- OptimizeView: v2 semantics (see §10 above).
- Fixtures: `apps/studio/fixtures/*.json` — offline demo only, never substituted for live failures (§58).

## 18. Coverage summary — what UX1+ must actually build

| Program item | State on this tree |
|---|---|
| §3/§4/§5/§50 state model + parity + scoping | **DONE** (backend); pin browser leg |
| §6 one editor | **DONE** |
| §9/§10 intent vs materialized, certified fabric center | Mostly done (FabricCanvas on TopologyView); verify PREVIEW labeling |
| §12 artifact views | **MISSING** — build as pure projections |
| §13 certificate inspector depth | Partial — add per-obligation key evidence + bound identities |
| §14 artifact DAG inspector | **MISSING** |
| §15 simulation preflight | **MISSING** |
| §16–§18 run detail / route realization / conservation panels | **MISSING** (evidence all exists) |
| §19 four-state requirements UI | **MISSING** |
| §20 run record viewer sections | **MISSING** |
| §21/§22 verify-run + reproduce endpoints/UI | **MISSING** (authorities exist) |
| §23 compare presentation | Partial (comparable gating done); add design/verification/requirements sections |
| §24–§28 optimization | Mostly done; per-candidate verdict cells remain |
| §29 workload detail | Partial |
| §33–§35 Trust: qualification done; campaigns + findings **MISSING** |
| §36 capabilities page | **MISSING** |
| §37/§38/§39 Ramulator/ASTRA/Serving | Correctly NOT integrated; classify only (B/C) |

Nothing in this table requires new science. Every missing item is a
projection, an adapter over an existing authority, or UI presentation.

---

## 19. Stage-2 surfaces added (post-Stage-1 RC)

Additions after the Stage-1 engineering console, all projections over
existing canonical authorities (no new science, no invented metrics):

| Surface | Authority | Product endpoint | UI | Class |
|---|---|---|---|---|
| Artifact DAG inspector (§12/§14) | `views.artifact_chain_view` over `bundle.root_hashes()` + certificate obligations | `GET /api/v1/revisions/{id}/artifacts` (persisted at certification; legacy re-derivation hash-checked; refusals → CONFLICT) | `ArtifactChain` on Compile & Verify | A |
| Certificate proof depth (§13) | per-obligation `evidence{}` dicts (routers/components, expected vs actual route entries, VC bindings, SCC count, flit width, placements, bound hashes) | already in `CompilationView` | `VerifyView` human meaning + key-evidence cells | A |
| Capabilities page (§36) | `application.capabilities.capability_registry` (import of dissolved `backend.analytical` fixed) | `GET /api/v1/capabilities` | Trust capabilities tables | A |
| Optimization study analysis (§24–28 depth) | `OptimizationStudyView` v2 fields (`definition.domain`, `guided_patch`, statuses, identities) | already served | `OptimizationAnalysis` (coverage, outcome distribution, lineage) — no sensitivity view (no authority) | A |
| Workload lowering explorer (§4/§29) | `views.lowering_view` over `LogicalMessageArtifactV2` via `lower_compile_workload`; artifact identity verbatim | `GET /api/v1/workloads/{id}/lowering` | Workload card inspector: collectives + message flows (rank space; physical traffic only inside runs) | A |
| Validation laboratory (§15 depth) | `mutations.json` / `metamorphic.json` / `engines.json` / `intervention.json` projected verbatim; FINDINGS.md stays link-only (§34) | `GET /api/v1/validation` extended | Trust campaign ledgers (mutations caught/missed as data, invariants, engine gates, intervention rows) | A |
| Serving analysis (§14) | **still no** stable `ServingExperiment/ServingRun` product resource — correctly withheld | none | none (Trust qualification only) | B/C |
| Ramulator / ASTRA workspaces (§12/§13) | correctly NOT coupled to runs; qualification + engine-gate battery visible in Trust | none | Trust only | B/C |
