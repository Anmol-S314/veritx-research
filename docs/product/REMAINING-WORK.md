# Remaining work — prioritized backlog

**Baseline snapshot:** 2026-11-12 — the tree is no longer dirty WIP: the 806
changed entries were split into owned lanes (`574d5973` rtl, `00bfb780` compiler,
`bb4e3ded` studio snapshot, `daca1562` gates, `841c3173` closeout docs, `587d45b1`
research WIP). `git status --porcelain` now shows only excluded scratch
(root-level calculator/screenshot artifacts, `.pi/`, `.codex/`, `.impeccable/`,
`audit/`, `test-results/`). The clean-tree release matrix is re-running at
`runs/release-clean-20261112T020000Z/`; product gates pass on the committed
tree. Non-goal: unreviewed scratch is not committed and stays untracked.

**Rule for every item below:** the definition of done is a live run or a
typed refusal, never a new status word. An item is done when a test shows
the behavior it names — compile + certificate for model work, flit
conservation for execution work.

---

## P0 — commit the green tree (blocks ALL evidence) — DONE 2026-11-12

Pinned live-evidence tests refuse by design when their producer or model tree
is dirty. The tree is no longer dirty: the split landed as six lane commits
(see the 2026-11-12 verification-integrity entry below) and the clean-tree
release matrix re-ran. The fork residue from this section is historical.

Original record, kept for lineage:

The original shared-wire snapshot included these fork edits:

- `third_party/booksim2/src/networks/{network.cpp,network.hpp,gec.cpp}`
  (tap + VC-range route dumps; bare GEC routing-function name fallback)
- model/verification/backend/test additions from the shared-wire line

This is a general evidence gate, not a fixed count of currently refusing tests;
subsequent worktree changes also require clean-tree verification before evidence
can be pinned.

**DoD:** the fork change and the model change land as separate commits on a
clean tree; the affected live-evidence refusals are rerun and pass. The tree
is clean of fork/model/product dirt at the committed revision; the shared-wire
qualification claim rests on `runs/release-clean-20261112T020000Z/` plus the
pinned evidence bundles under `docs/product/evidence/` (committed). The
contention/NCU and C5 seat runs were re-verified on the committed tree with
the framing in place.

Studio work was kept OUT of the RTL lanes: it landed as its own snapshot lane
(`bb4e3ded`), and its unreviewed state is recorded there.

---

## P1 — GEC-hybrid materializer (implemented)

`GEC_HYBRID` contains canonical mesh channels plus MECS shared wires.
`test_gec_hybrid_materialize.py` pins the union and source-law refusals.
Materialization alone claims no routing proof; the earlier routing refusal
is superseded by the explicit candidate-union path in P2.

**DoD:** materialization truth is tested. Complete.

---

## P2 — GEC-hybrid (ranked candidate-union path integrated; escape theorem open)

`model/gec_hybrid_route.py` owns both source-legal runtime candidates, binds
actual channel/wire IDs and ordered taps, and preserves every eligible VC.
The compiler resolves this union, derives exactly `2*d` X/Y phase/tap VCs,
and certifies `DEADLOCK_FREE` with the topology-bound integer-rank proof in
`verification/gec_hybrid_instance.py`. No distinguished escape VC is invented.

`gec_hybrid16` and the representative capability probe use a 4x4 fabric,
`c=1, o=1, d=3`, six VCs. `CERTIFIED_BOOKSIM_GEC_HYBRID_V1` renders the native
hybrid network. Live tests exercise both mesh and MECS selections, assert
flit conservation and static route observation, and require runtime selector
cost/port/tap/VC-range membership evidence. Pruned routes, changed VC envelopes,
prepared candidate tampering, and invalid runtime choices fail closed. The
existing topology proof tests reject reversed dependencies, altered taps and
missing mesh edges. Oversized tap envelopes still refuse (`d=7` needs 14 VCs,
above the compiler's eight-VC cap); cyclic class dependencies are not qualified.

**Alternative path DoD:** compile, certificate, projection and live conservation
are implemented and focused-tested. Scope remains
`STRUCTURAL_CANDIDATE_UNION_ONLY`; runtime observations describe route-compute
choices before allocation, not complete flit paths, fairness or buffer
availability. Dirty-tree runs are diagnostic, not pinned release evidence.
The P2-focused acceptance set passed 34 checks (including three live hybrid
geometries); a neighboring SROTA rank regression exposed a Plane-C audit/render
mismatch, which was corrected and its live check passed on rerun. The topology
registry gate and `git diff --check` passed. A later release-gated hybrid
materialization/execution run passed 21 tests, and the full dirty-tree CI
diagnostic passed; neither replaces clean-tree pinned evidence.

**Original escape-method DoD remains open:** the source has no distinguished
escape role, accessibility/closure invariant, or meaningful negative control
for removing an escape VC. The candidate-union rank proof is an explicitly
different sufficient proof, not a relabeled escape theorem.

---

## P3 — SROTA shape-mixing compiler wiring (implemented; clean-tree evidence pending)

The earlier claim that `derive_route` refuses two-shape SROTA is stale. The
compiler now derives two VCs for `vc_policy="shape"`, produces the row+column
union route, and carries it through certification and the `srota_path_en = 3`,
`srota_vc_policy = shape` profile. The live execution test
`test_two_shape_srota_executes_live_and_every_hop_was_certified` asserts
conservation and per-hop certification.

**DoD:** satisfied by the live run and its test. Keep this as completed; do not
reopen it as a backlog item. The full DSE suite is still the separate P9 gate.

---

## P4 — SROTA Valiant (rank policy wired and live-qualified)

The rank route and VC policy are wired through compile, certificate/CDG,
projection, and route observation. The shipped `srota32_rank` preset is
row+column+Valiant (the fork requires row-first as an anchor), uses four rank
VC sets, and is checked against the fork's executed route dump. The live test
asserts route observation, completion, and flit conservation.

**DoD:** satisfied by `test_srota_rank_valiant.py`; do not describe P4 as
blocked at compiler routing. Further work must establish stronger differential
coverage of every allowed rank/shape envelope before broadening the claim.

---

## P5 — SROTA islands and Plane C (model work first)

- **Islands:** the artifact cannot carry a rate regulator's state, and the
  model explicitly does not simulate one. The release-gated BookSim island
  suite passes (5 tests), proving the current placement/route/conservation
  slice only. Either add a regulator primitive or prove a placement-only rule;
  compiler work comes second, never first.
- **Plane C (closed this line):** `model/control_plane.py` materializes an
  independent `ControlPlaneArtifact` with REQ/RSP/SNP VCs and plain XY. The
  flat class/VC admission used to refuse it because two classes on DIFFERENT
  subnets looked like a shared-VC subset. `model/multi_plane_vc.py`
  (`MultiPlaneVCAssignment`) now binds each traffic class to exactly one
  subnet and carries that subnet's own `VCAssignmentArtifact` (Plane C's
  routing authority is the control-plane artifact; routing class
  `SROTA_PLANEC_XY`). `assert_traffic_classes_bound` and the evaluator's
  `_admit_traffic_classes` take the binding and check disjointness WITHIN a
  subnet only; the BookSim projection renders `class_subnet` from the same
  binding, so renderer and admission cannot drift. Plane C class vocabulary
  is the control/coherence namespace (`control`, `control:*`, `coherence`,
  `coherence:*`; legacy `control_collective`), so a data class cannot take
  the control plane by alphabet: see `PLANE-C-CLASS-VOCABULARY.md`.
  Single-plane designs pass no binding and keep the flat check unchanged.
  Evidence: the product path
  (`FabricEvaluator` -> `CERTIFIED_BOOKSIM_SROTA_ROW_FIRST_V1`) reaches
  `EVALUATED` on `srota32_plane_c` with `flits_injected == flits_accepted`
  (62,496) across the two subnets (`tests/test_srota_plane_c.py`).

**DoD per item:** typed refusal removed AND a live multi-plane run conserves
flits on both planes.

---

## P6 — V5 intent materialization (the broad track)

V5 capabilities remain PARTIAL, but the structural compiler slice now
preserves the original V5 root alongside its explicit V4 hardware base.
`FABRIC_DAG_VALID` additionally checks the complete supported record set and
binds the V5 hash, base-design hash, resolved fabric and extension hashes into
certificate identity. Scope is `DECLARED_V5_EXTENSION_STRUCTURE_ONLY`, with
execution semantics explicitly `NOT_MODELED`.

Compilation/design/artifact-chain/Compile Result exports carry the source root
and bound records; JSON export/reload preserves certificate identity. Changed
clock dividers change design/certificate identity without changing the hardware
DAG. Missing, undeclared, foreign or tampered records/certificates refuse.
The focused V5 and legacy compatibility gate passed **71 tests**; the later
full dirty-tree CI diagnostic passed, while clean-tree evidence remains
pending. Each remaining capability still needs its own
compile→verify→execute→qualify slice:

- transactions (outstanding / ordering / splitting) — V5 endpoint-bound policies
  now execute in `ABSTRACT_DATA_MOVEMENT_V1` for explicit addressed READ/WRITE
  demand, with split-child credit/completion accounting. Generic backend/product
  execution and external protocol qualification remain open.
- access policy — emitted and structurally bound, but not Access Loom
  enforcement or backend authorization
- sidebands and clocks/domains — emitted, V5-root-preserved, structurally
  certified and exported; the scoped data-movement runner binds explicit agent
  transaction clocks across declared FIFO bridges with exact multi-rate abstract
  timing. General domain execution, RTL CDC qualification, sideband execution
  and persisted product-revision integration remain open
- reset and power — architectural identity only, typed compiler refusals
- CDC + async-FIFO model — abstract behavior remains distinct from RTL
  qualification; explicit signoff requests now refuse at the verification/RTL
  generation owner because no RTL differential exists
- IP catalog — 12 templates; explicit stamping/materialization requests now
  refuse at the IP stamp/instance-materializer owner because no compiler hook
  exists
- multi-plane fabric — `PlaneComposition` accepts single plane only

**DoD per item:** a compiled, certified, executed design — or the refusal
stays and says exactly which stage owns it. The evaluation-context boundary
now explicitly refuses V5 execution before workload lowering, rather than
silently executing the V4 base and discarding V5 intent. Structural certificate
PASS does not qualify clock/domain execution; persisted product V5 revisions
also remain refused.

---

## P7 — verification and generation

- **UVM** (`PARTIAL`): the bundle-based generator now emits
  `noc_dut_binding.sv`, maps flat endpoint flit/credit pins to the real
  `rtl/t3/mesh.sv` array ports, and uses the DUT's `VCS/X_DIM/Y_DIM` parameters.
  `test_uvm_dut_binding.py` compiles and simulates this generated binding with
  Verilator for one and two VCs, checking endpoint correctness, duplication,
  and conservation. The UVM top uses scalar native virtual interfaces, and
  CLI/API output includes the binding. Scope is explicitly native link
  interface only (64-bit RTL payload), not equivalence to the compiled packet
  format. Canonical generation refuses unsupported dimensions, >4 VCs, or
  non-DOR routing. A UVM library and complete driver/environment are still
  missing; assertion templates also remain unqualified. DoD: all generated
  collateral compiles and runs with real UVM against the repository DUT.
- **RTL generation** (`PARTIAL`): a callable `scripts/rtlgen/gen_rtl.py`
  seam delegates to the existing emitter; its supported 2-VC connected mesh
  slice has a Verilator lint smoke and typed refusals outside that slice. It is
  not wired into `compile_model.py`'s `-rtl` artifact path, so compile-product
  RTL generation is still open. Do not label this `READY`.

---

## P8 — physical, packaging, measurements

- **Authored placement:** the scoped data-movement experiment validates router
  footprints/die bounds and derives Manhattan wire lengths and routed flit-distance.
  Geometry is not delay, PPA or a physical implementation. See
  `tracks/t3-topology/dse/docs/DATA-MOVEMENT-EXECUTION.md` for the exact envelope.
- **OpenROAD** (`NOT_IMPLEMENTED`): needs a PDK choice, LEF/Liberty/SDC/DEF
  contracts, tool provenance. DoD: one placed-and-routed block with
  provenance, before any PPA-adjacent claim.
- **Desktop/Tauri** (`NOT_IMPLEMENTED`).
- **Throughput/PPA** (`NOT PROVIDED` everywhere, by explicit design):
  assert only what the fork measures. Completion, conservation, and latency
  are already in the evidence and asserted for SROTA/GEC-MECS.

---

## P9 — process and hygiene (never silent)

- Upstream reuse audit incomplete (rate-limited, partial license
  evidence): **nothing may be vendored** until exact commits, licenses,
  sources, and tests are recorded.
- The latest `scripts/ci_gate.sh` diagnostic run passed all five stages: DSE
  **6,701 passed, 25 skipped**; Studio TypeScript, Vitest (**217 passed**),
  and Python (**10 passed, 8 skipped**) passed; product gates passed. This
  supersedes the earlier dirty-run failures and interrupted-suite note, but
  remains diagnostic because the tree is dirty. Run the gate on a stable,
  clean tree before any release claim. Pytest still warns that the configured
  `timeout` option is unknown; its 900-second setting is not enforced.
  The concentration-2 refusal and exact unsupported-producer boundaries
  remain in force.
- Fat-tree spellings now normalize through one alias table without changing persisted identities (128 focused tests passed). Plain concentrated-mesh 2:1 remains unsupported: the canonical topology preserves seat capacity 2, but the native CMesh producer asserts `c == 4` and no exact AnyNet endpoint-seat mapping is proved; the product refusal and direct qualifier refusal are pinned. Closing it requires a real producer/projection mapping and live route/conservation qualification. Studio P2 notes remain open.

## P10 — bounded Studio search and compile jobs (implemented)

Operator-initiated, server-configured, cancellable. Not unattended
autonomy: every run names a provider, a pinned draft, and a fixed budget.

- Compile runs as an owned child process (`/projects/:id/compile-jobs`), so a
  heavy or pathological topology no longer blocks Design, Review, or health.
  The parent — not the child — publishes, and only when the pinned draft hash
  and the revision identity still agree. `CANCELLED`, `EXECUTION_TIMEOUT`, and
  stale submissions publish nothing. See
  `tests/test_product_bounded_jobs.py` (6 checks, including the 1,057-router
  QTree cancel and non-blocking proof) and the live browser check.
- AI topology search runs the existing certified pilot as a job
  (`/projects/:id/ai-topology-search`) with a four-proposal budget. Adoption
  is a separate, explicit call that refuses stale drafts, non-`COMPLETED`
  jobs, requirement failures, and unverifiable evidence; the search itself
  never writes the draft. Bounded by 64 routers/seats, 256 directed channels,
  degree 8, 30-second backend timeout.
- Evidence is re-derived at read time. Stored measurements are not trusted:
  a tampered evidence byte reports `EVIDENCE_INVALID` with no score and no
  adoption (verified live and in tests).
- Provider configuration is server-owned (`VERITX_AI_BASE_URL`,
  `VERITX_AI_MODEL`, `VERITX_AI_API_KEY` for non-loopback). No provider is
  configured in this workspace, so the Studio panel honestly reports
  `configured: false` and disables the action.

Still open, and deliberately not claimed: no multi-objective frontier, no
robustness or multi-seed study, no area/power/signoff, no autonomous
multi-round search without an operator, and no LLM-authored score anywhere.

### Repairs from the live reports (same line)

- **FlatFly was silently reshaped.** `qualify_native_flatfly_min` solved
  `k = isqrt(router_count)` and pinned `n = 2`, so a design authored as a
  4-dimensional flatfly (radix 4, 256 routers, degree 12) was executed as a
  16-ary 2-fly (degree 30). The post-execution route guard then refused on
  39,168 divergent entries — correct, but only after the run. The shape is now
  solved from the artifact and **proven by full adjacency equality** against
  the render (`_flatfly_shape`), and the render writes `n = qual.n`. Verified:
  `flatfly k=4 n=4` reproduces the declared 65,536-row table exactly
  (`EXECUTED_ROUTE_OBSERVED`, `CERTIFIED_BOOKSIM_FLATFLY_MIN_V1`, QUALIFIED,
  3,101 cycles), where the old `k=16 n=2` config diverged. An adjacency that
  is no k-ary n-fly now refuses instead of being redrawn.
- **The plan claimed ASTRA legs it could not run.** A GEC-hybrid design
  rendered `hybrid_gec_observation_file`, declared by the standalone fork and
  absent from ASTRA's vendored network backend; the plan said READY and the
  runtime exited 255 mid-run with `Parse error : Unknown string field`. The
  embedded config now checks every emitted name against the field set read
  from the **installed runtime's own** `booksim_config.cpp`, and refuses with
  the field named. The three ASTRA legs now plan as UNSUPPORTED/BLOCKED for
  that design while NETWORK_COMPLETION stays READY. ASTRA's vendored BookSim
  is untouched, so this is a representation boundary, not a regression.
- **"Checking topology support…" on every visit.** The probed capability
  table re-compiled all 16 families on every mount (4.16 s measured, every
  time). It is a pure function of the loaded code, so the gateway now
  memoizes it keyed by `newest_source_mtime`, single-flights concurrent
  probes, prewarms once at startup, and re-probes on `?refresh=true`. Measured
  after the change: 4.16 s → 5 ms per request, and the Fabric topology
  selector is ready in ~90-100 ms on every visit.

---

## 2026-11-10 — consolidated remainder (post-audit, post-P8/P9 lanes)

This section supersedes earlier snapshot estimates. Only items that remain are listed; anything finished is listed as evidence elsewhere in the repo. Effort scale: **S** = hours, **M** = days, **L** = weeks+. Owners in brackets.

### Blocked on an operator decision
1. **P0.8 PDK** [operator] — ASAP7 unobtainable via ciel/volare (only sky130 / gf180mcu / ihp-sg13g2). sky130A is the declared diagnostic; a 7-nm release needs ASAP7 or an approved equivalent; GF180MCU is the fallback for independent timing confirmation. See `PDK-DECISION-REQUIRED.md`.
2. **Die bounds + pinout + CDC/plane for the network block** [operator] — none exist; §12 records the blocker; required before any route/DRC claim.
3. **Constellation / KNCube native source** [operator] — agent cannot fetch; `KNCubeSourceSpec` equivalence checking stays open without it.
4. **Scope of the release claim** [operator] — "network block placed/routed on sky130A" vs "full-chip signoff"; current repo supports neither as a signoff qualified claim.

### Engineering (L–L+M)
5. **P3 finish line — multi-instance/multi-seat compose path** [this repo] — **multi-instance emission LANDED 2026-11-10**: a group with `count=2` now compiles, emits two `initiator_slice` instances on two distinct routers with two distinct endpoint port sets, and the composed top lints PASS and simulates PASS 13/13 (both instances write/read/complete; ordering, decode-miss, SLVERR, backpressure, concurrent, conservation, drain all true). Zero regression measured (torus top + TB render byte-identical; torus family test green); regression tests 12/12. **Still open:** (a) the multi-seat concentrator **wiring** — the arbiter + response demux primitive is built and proven (`tracks/t3-topology/rtl/multi_seat/seat_concentrator.sv`, 5 scenarios PASS, gate test 3/3) but is not yet placed between the per-seat slices and the router local port, so the five multi-seat families keep their typed refusals; (b) the full-size 74-agent Mixtral run through the same multi-instance path (the compiler seats every instance on its own router for concentration-1 fabrics — measured); (c) KNCube native equivalence (item 19). M–L.
6. **P9 — RTL prerequisite for timing close at 10 ns on sky130A** [this repo] — the grant-arbiter re-pipeline **landed** (registered grant stage, `esc_yield_q` priority state, 4-VC dwell extension; composed slice re-verified 38/38) and post-CTS STA still measures setup WNS **−4.424 ns / TNS −11.4 µs**, hold clean. Binding classes moved to **7,212 × async-reset fanout flop** and **1,470 × reg-reg/out** (debug-tap adders in `project_top.sv`); the arbiter is no longer binding. LibreLane resizer (`ResizerTimingPostCTS`, stages 37/38) was killed twice at iteration ~240 (~0.01 ns/iter, 23,570 violating endpoints; no metrics). Routing/DRC/signoff remain **NOT_RUN**. Remaining honest paths: reset-tree constraint review + a pipeline stage on the debug-tap adders, then a PDK decision; no clock tweak allowed. M–L; verify with the full top STA re-run.
7. **Compute-architecture / STREAM / BIDIRECTIONAL / RCU materializers** [this repo] — the 9 honestly refused templates (npu-tensor-core, vector-coprocessor, rcu-collective, concentrated-router, streaming-dma-engine, telemetry-atb-trace-hub, cdc-async-fifo-bridge, pipeline-retiming-stage, ucie-d2d-chiplet). Each refusal names its missing artifact by blocker id in `ip_catalog.py ROADMAP`. L (per family).
8. **P1.5 — attachment-side stable identity binding** [this repo] — v4 `Agent.group_name` substrate landed (hash-stable absent, every-group-must-declare, unique refusals, 11/11 browser exact pins, compile COMPILED with named groups); the attachment artifact (`AgentAttachmentArtifact`) still binds positionally; no `group_name → attachment` mapping artifact or the reorder-safety check exists yet. M.

### Evidence / signoff (S–M)
9. **`--release` matrix re-run after the 2026-11-10 kncube routing fix** — DONE 2026-11-12 on the committed tree: `runs/release-clean-20261112T020000Z/` (manifest sha256 `b375ffca195f48fcc42abe84c4307071fc4c1b231e4bd444d44857f6f2a4c86b`). Result: **14/14 family rows PASS, `PASS_WITH_NOT_RUN`** (physical `NOT_RUN`; KNCube native-equivalence stays operator-owned). **11/14 `final_implementation: true`** (release-clean row set: mesh, torus, concentrated_mesh, ring, fly, qtree, tree4, flatfly, fattree, dragonflynew, kncube). GEC-MECS reports `final_implementation: false` with **lint warnings = 2** at the committed state (`inject_vc` declared but unused; `vsel` 32-bit with [31:2] unused, instance `u_noc.u_credited_fabric`); both are dead-declaration nits fixed in `c3d360e9` — the gec_mecs row must be re-run on that commit for A2 to close and 12/14 to stand again. SROTA and GEC-hybrid stay false under their own Scope B lists (their `multi_flit` scenario returns true with the framing line, and since 2026-11-12 their **multicast row is CLOSED** too: `test_project_top_shared.py` measures 20 copies from 8 injected flits on each fabric, including a forked HEAD/BODY/TAIL packet, with SROTA's island-class refusal counted and the hybrid mesh asserted multicast-free; evidence `docs/research/RTL-SCOPE-B-MULTICAST.md`). Their remaining open rows are AXI/OrderingFSM/CDC composition and the physical multidrop/STA/parity.
10. **Single-project smoke manifest (`complete_design.py --request fixture.json --out runs/…`)** — DONE 2026-11-12: `runs/single-project-smoke-20261112T000000Z/manifest.json` — freeze/compile/hardware `PASS_WITH_NOT_RUN` (physical `NOT_RUN`; not a release claim), `git_head` = the committed tree.
11. **Backend DSE full unit suite (`sequential-gates.sh dse-pytest`)** — DONE (measured, red at the time of the run) 2026-11-12: the full suite completed 2:14:15 with **9,530 passed / 8 failed / 55 skipped / 1 warning / 3 errors**. All eleven failures/errors were re-run against the committed tree and pass: the three renderer determinism tests failed on the retired harness's `no // in emitted RTL` assert (the invariant was dropped and the tests rewritten during the rework; they now pass); `test_hybrid_composed_lints_and_sims_on_the_top` failed mid-rework and passes; `test_family_registry` (kncube) passes; `test_env_gates`/`test_gateway_staleness` (fresh-process staleness) failed on a mid-run dirty tree and pass on the committed tree; `test_entry_point` passes; the three `test_booksim_source_build_verification` errors pass in isolation on the cleaned disk. Not re-established: a pinned full-suite green at one commit (the suite caught the tree mid-rework, and the current head was never re-run end to end); treat this row as measured-but-stale, not as a green gate.
12. **Full Playwright suite re-run** — DONE (measured, red) 2026-11-12: `apps/studio/prototype` — **115 passed / 4 failed / 13 skipped** (132 tests). The four failures are Studio-owned, none RTL: three `app_repro.spec.ts` failures are the absent operator-owned gateway on :8099 (`/gw/api/v1/health` and `/projects` return 500; the Find-fabrics button stays disabled) and one `native-sweep.spec.ts` failure does not reproduce in isolation (the spec passes 3/3 under `--repeat-each=3`; the full-run split of failing ids across two project-hash prefixes under a config declaring no projects points at shared Vite/route-mock state) and is recorded as context-dependent, to be settled on a quiet tree by the Studio owner. Gateway relaunch is operator-owned per `docs/product/GATEWAY-RESTART.md`; this row stays red until the Studio owner lands those fixes.
13. **`runs/sequential-gates-*` logs archived into release evidence** — PARTIAL 2026-11-12: the clean-tree release matrix archives every family's logs with per-log sha256 inside `runs/release-clean-20261112T020000Z/manifest.json` (root manifest sha256 `b375ffca195f48fcc42abe84c4307071fc4c1b231e4bd444d44857f6f2a4c86b`; per-family manifest sha256 recorded in this file's release section). The sequential-gates archive for the full DSE suite is still pending item 11; do not cite ephemeral `/tmp` logs for the suite.
14. **`sha256sum` pinning for fresh evidence** — DONE (bounded) 2026-11-12: the clean-tree matrix pins every family's lint/build/sim logs inside its manifest (root sha256 `b375ffca195f48fcc42abe84c4307071fc4c1b231e4bd444d44857f6f2a4c86b`; per-family manifest digests are computed deterministically from the run artifacts and recorded verbatim in this file's release entry). The product gates pin their own registry files. `test_final_implementation_evidence.py` pins the 12 composed-family bundles against the committed tree (hash-keyed). The mesh8x8 pin and the sequential-gates archive close with item 11.
15. **`runs/veritx-p2p7p11-evidence/` re-derivation** — report dated 2026-11-09; P2 pass-conditional and P7 partial are not valid 2026-11-10 evidence without re-runs. NOT re-derived this cycle; the report stays explicitly stale. M.
16. **Compiler toolchain pinning in gate logs** — DONE 2026-11-12: `sequential-gates.sh` now writes `toolchain.txt` first (repo head, dirty-file count, `--version` for python3/gcc/g++/make/verilator/yosys/openroad/iverilog) before any gate stage starts; landed in the closeout docs commit `8679a652` with `scripts/sequential-gates.sh`.

### Backend defects found by formal proof (M)

- ~~**Ring family deadlock (known defect, measured 2026-11-10).**~~ **CLOSED 2026-11-10 (late).** Root cause found by reading the BookSim fork's own `dor_next_torus`: the fork computes the dateline partition once, when the flow turns into the dimension, and keeps it — and the fork's law is *acyclic per VC class*. The composed RTL was not carrying that half: its VC was a class (free/escape), so every flow shared VC0 and the ring's dependency graph was cyclic. The ring's VC is now the fork's dateline half (`src_router > dst_router`), the escape engage is disabled for the ring so the VC never changes, and the dependency-graph proof is now **per VC class**. Measured: both classes acyclic, unbounded `sby prove` PASS, 64 routers, and the ring still lints and simulates 13/13. Pinned by `tests/test_composed_family_cdg_proof.py::test_composed_family_channel_dependency_graphs_are_acyclic[ring]` and the analysis tests in `tests/test_ring_vc_cdg_analysis.py`.
- **Multi-seat memory co-seating (last typed refusal).** Co-seating the memory endpoint with initiator seats needs the composed fabric to be endpoint-addressed so the concentrator can demux by destination endpoint id.
- ~~**Per-tap credits inside the multidrop wires (P4 4.3).**~~ **APPLIED 2026-11-11** — the shared fabric now carries per-(port, tap, VC) credit accounting: one proven `tap_credit_pool` per wire, a credited grant path (a credit is claimed when the flit actually moves onto the wire, and only for the exact (tap, VC)), a release path that returns the credit to the exact (tap, VC) it was taken from (the far end holds the return until the fabric takes it, and the fabric serves the holding destinations round robin per source), and a VC/tap-echo in the shared flit so the return cannot alias. The directed over-subscription scenario proves all of it at the full 81-router shape; the transformation is anchored and refuses rather than emitting a half-wired fabric; the pinned historical 16-router artifact stays byte-identical. Gate: `tests/test_gec_mecs_credited_fabric.py`. Wiring spec and the honest scope note: `docs/product/proposals/P4-4-3-credit-wiring-spec.md`. **Still open:** the wire model delivers one flit per wire per cycle, so the credit is rarely the binding constraint today — making it so needs a pipelined wire model.

### Verification integrity (S)
17. **`git status --porcelain` (508 untracked / 220 modified / 7 deleted entries)** — DONE 2026-11-12: split into owned lane commits (`574d5973` rtl shared-fabric framing/credits, `00bfb780` compiler/DSE line, `bb4e3ded` Studio snapshot, `daca1562` gates/runners, `841c3173` composed-family evidence + status docs, `587d45b1` research WIP carry). Build products under `rtl/chipyard/**/target|test_run_dir`, `rtl/tap_credit/tap_credit_formal/`, `rtl/cdc/cdc_fifo/` and ~211 MB of Verilator/Chisel outputs were preserved out-of-tree at `/tmp/opencode/backup-*` for provenance, never committed. Excluded as non-goals: root calculator/screenshot artifacts, `.pi/`, `.codex/`, `.impeccable/`, `audit/`, `test-results/`. The clean-tree evidence pass is `runs/release-clean-20261112T020000Z/` + the product gates on the committed tree; remaining: the full DSE unit suite (item 11) and the Playwright re-run (item 12).
18. **`final_implementation = false` everywhere** — must remain true of the tree until P9/P11 pass; no exception.
19. **KNCUBE native equivalence** — **partly closed 2026-11-10**: the general intent exists and works (`StructuredTopologyIntent(family="kncube", params={radix, dimensions, wrap})` compiles COMPILED, composes to 9 routers, emits lint-clean RTL that simulates PASS 13/13; a mismatched wrap is refused by name; the runner's wrong kwargs and its false BLOCKED row are fixed). What remains is equivalence against the external Constellation KNCube source — `KNCUBE_GENERAL_INTENT_AND_NATIVE_EQUIVALENCE_CHECKER_MISSING` is raised by the new guard module by design rather than approximated; cannot close without the Constellation source (item 3).
20. **Contention qualification scope** — S26/S27 pass only at AW-first ordering; outstanding-release under sink hold qualifies at that cadence; S28/S18/S19/HEAD-BODY-TAIL/credit-tap/credit-delay remain NOT_RUN (`SLICE_MULTI_DEST`, `SLICE_CREDIT_TAP`, `SLICE_CREDIT_DELAY` missing). M–L (per primitive).

### Verification sweep state as of 2026-11-10 ~15:0x
- Frontend 325/325, `agentMapExact` 11/11, backend address-range 12/12, IP catalog 63/63, frozen pins 11/11, endpoint-loss 4/4, slice TB suite 38/38 (contention-enhanced locked TB, 14.2 min), parameterized 12/12, shared 14/14, p8 contention invariants 5/5, source suites 32/32.
- Backend DSE full unit suite: **NOT RUN (clean)** this cycle.
- Release matrix: last recorded FAIL (300 s mesh timeout; dragonflynew pending re-run; kncube row fixed in runner but unverified).
- LibreLane full top: CTS PASS; post-CTS STA FAIL (WNS −4.424 ns, TNS −11.4 µs, hold clean); stages ≥37 NOT_RUN effective (resizer dead, no metrics).
- Gateway fresh (`stale:false`, `source_age_s:0`, pid 16846) as of 2026-11-10 14:0x; any further edit repeats the staleness rule.


---

## 2026-11-12 — two backlog claims checked against the code, and corrected (read-only)

Both corrections come from reading the tree, not from a build. They change what the
remaining work *is*, so they are recorded here rather than edited into the older rows.

### Multi-seat concentrator (item 5a) — "not yet placed" is stale; the residue is narrower

`seat_concentrator.sv` **is** emitted, instantiated and linted by the composed-family
path whenever a non-endpoint-tagged family has co-seated routers
(`project_top_rtl.py:6515,6532,7431-7438,7459-7461`). It is not an unplaced primitive.

What remains is a *demux* limitation, not a wiring gap. The tagless concentrator
answers a response into `owner_q`, the seat most recently granted
(`rtl/multi_seat/seat_concentrator.sv:120`) and holds the router's local port in
`S_WAIT_RSP` until that response returns (`:141,148`), so it is functionally correct
only at one outstanding request per router. The endpoint-tagged families instead
demux by a destination-endpoint field read from the flit
(`product/cmesh_rtl.py:49`, parameters `:12,:14`). The refusal at
`project_top_rtl.py:4972` therefore blocks exactly the case where a *memory* router
is co-seated outside the tagged set — closing it means either carrying a tag in the
flit for those families (packet-format, adapter and parity change) or proving strict
single-outstanding is acceptable for the specific shape. See
`docs/product/proposals/multi-seat-concentrator.md` for the amendment.

### Concentrated mesh 2:1 (P9) — the stated blockers are stale; the open part is the live run

The row said "the native CMesh producer asserts `c == 4` and no exact AnyNet
endpoint-seat mapping is proved". Neither holds in the current tree:

- `CMeshTerminalMap` accepts `concentration in (2, 4)` (`backend/cmesh_terminal_map.py:34,118`);
- `qualify_native_cmesh_dor` accepts uniform `seat_capacity` in `{2, 4}`
  (`backend/booksim_projection.py:1360`);
- the fork accepts both, with `c == 2` restricted to `dor_no_express`
  (`third_party/booksim2/src/networks/cmesh.cpp:77-79`) — and the qualifier already
  pins exactly that routing function (`booksim_projection.py:38`);
- measured this session: `ConcentratedMeshIntent(side_length=4, concentration=2)`
  **compiles**, producing 16 routers with `seat_capacity == {2}`.

So the remaining obligation is the one that cannot be read off the source: a live
route/conservation qualification at the c=2 shape, and the product-level refusal text
updated to match. No redesign is implied. This row therefore moves from
"producer/mapping missing" (L) to "live qualification" (M) — the code path is present
and the claim on it is what is unproven.

### Playwright row 12 — the fourth failure is not a UI defect (checked 2026-11-12)

The row attributed it to "a UI input not enabled in the recorded fixture path". Isolated
at the current head that does not reproduce: `npx playwright test tests/native-sweep.spec.ts`
passes, and passes **3/3** under `--repeat-each=3` (8.7 s). The spec needs nothing the
fixture lacks — `public/data/topology_sweep.json` carries 143 rows, 46 with
`native_model.status == "AVAILABLE"`, `mesh4x4` at `native_area_mm2 = 0.280976` and
`gec_mecs16` `UNSUPPORTED`, which is exactly what the assertions read.

So the failure is **context-dependent**, i.e. test isolation rather than product
behaviour. It appeared only in the 132-test run, whose `.last-run.json` records four
failed ids with **two different project-hash prefixes** even though
`playwright.config.ts` declares no `projects` — consistent with the three gateway-less
`app_repro` specs perturbing shared state (one Vite server via
`reuseExistingServer: true`, a global `page.route` mock over the same sweep endpoint)
rather than with a control that is disabled.

Consequence for the row: the three gateway failures stay operator-owned and red, but this
one must not be charged to a Studio UI fix it does not need. It should be re-attributed
to isolation and reproduced inside a full-suite run before anything is edited — a fix
applied to passing UI code would be a change made to satisfy a phantom.

**Caveat on the above, recorded because it limits the claim.** While that isolated run
was taken, the Studio tree was being modified by a concurrent session (eleven files
under `apps/studio/prototype/src/`, uncommitted, including `App.tsx`, `FlowView.tsx`
and `ui.tsx`), and the Playwright dev server serves source straight from disk. The
"passes 3/3" measurement is therefore true of the tree at that moment, not necessarily
of the tree after that lane commits. What does not depend on their edits: the fixture
content (unchanged, and sufficient for every assertion), and the isolation argument
(an ids prefix split under a config with no `projects`). The reproduction that settles
this must be taken on a quiet Studio tree — by its owner, after that lane lands.

### Full-suite runs: what the 2h14m run actually measured, and how to run it so the result means something

`python3 -m pytest tests -q` completed on 2026-11-12: **9530 passed, 55 skipped, 8
failed, 3 errors** (8055.89 s). Attributed one by one afterwards:

| outcome | count | cause |
|---|---|---|
| `booksim_source_verification.VerificationError: source git provenance drift/mismatch` | 3 errors | three commits landed during the run; the provenance check is designed to notice exactly that |
| `test_staleness_gate_reports_fresh_on_stable_tree` | 1 | its own guard printed "sources changed mid-run … rerun on a stable tree" |
| `test_a_fresh_process_is_not_stale` | 1 | same |
| `*_renderers_are_deterministic` ×3 | 3 | pytest collected the file **before** a concurrent edit retired a blanket `assert "//" not in …`; the old assertion ran against new renderers |
| `test_hybrid_composed_lints_and_sims_on_the_top` | 1 | passes at rest (56.19 s) — it composed from a template being edited at that moment |
| `TestInstalledConsoleScript::test_installed_package_is_used_not_the_worktree` | 1 | the invocation's `PYTHONPATH=.:tests` leaks into the venv subprocess, so the worktree shadows the installed package. Invocation artifact |
| `test_the_table_agrees_with_the_declared_registry` | **1 real** | the registry declares `kncube`, `TOPOLOGY_FAMILIES` had no row. Fixed in `bc476e6d` |

So **one of eleven was a product defect**; the other ten are the measurement reacting to
a tree that moved. That is not a flake to shrug at — three of the repo's own gates
(provenance, staleness, determinism) exist to refuse a verdict taken on a moving tree,
and they were right.

**The method that makes a green run meaningful:** run the suite from a detached git
worktree at a pinned commit, so no other writer can move it. Two things a worktree needs
that `.gitignore` withholds — the built BookSim binary
(`third_party/booksim2/src/booksim`, 24 MB, untracked) must be copied in — and one test
must be deselected, because `test_installed_package_is_used_not_the_worktree` asserts an
installation property the worktree deliberately overrides:

```
git worktree add --detach /home/datavex/veritx-tmp/stable-wt <commit>
cp third_party/booksim2/src/booksim /home/datavex/veritx-tmp/stable-wt/third_party/booksim2/src/
cd /home/datavex/veritx-tmp/stable-wt/tracks/t3-topology/dse
TMPDIR=/home/datavex/veritx-tmp PYTHONPATH=.:tests python3 -m pytest tests -q -p no:randomly \
  --deselect "tests/test_entry_point.py::TestInstalledConsoleScript::test_installed_package_is_used_not_the_worktree"
```

**And redirect straight to a file, never through a pipe.** The first attempt of this run
piped into `tail`; when its 90-minute limit hit, the pipe had buffered everything and the
log was empty — an hour and a half of evidence lost to a `|`.
