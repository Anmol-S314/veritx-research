# Remaining work — prioritized backlog

**Baseline snapshot:** working tree after the shared-wire line (SROTA row-first/two-shape,
GEC-MECS compile, certify, render, execute live). Latest incremental diagnostic:
`bash scripts/ci_gate.sh` completed with all five stages passing (DSE 6,701
passed, 25 skipped; Studio TypeScript and 217 Vitest tests passed; Studio Python
10 passed, 8 skipped). This was on the heavily dirty tree and is not clean-tree
release evidence. The stable, clean-tree evidence gate remains pending.

**Rule for every item below:** the definition of done is a live run or a
typed refusal, never a new status word. An item is done when a test shows
the behavior it names — compile + certificate for model work, flit
conservation for execution work.

---

## P0 — commit the green tree (blocks ALL evidence)

Pinned live-evidence tests refuse by design when their producer or model tree
is dirty. The original shared-wire snapshot included these fork edits:

- `third_party/booksim2/src/networks/{network.cpp,network.hpp,gec.cpp}`
  (tap + VC-range route dumps; bare GEC routing-function name fallback)
- model/verification/backend/test additions from the shared-wire line

This is a general evidence gate, not a fixed count of currently refusing tests;
subsequent worktree changes also require clean-tree verification before evidence
can be pinned.

**DoD:** the fork change and the model change land as separate commits on a
clean tree; the affected live-evidence refusals are rerun and pass. Until then,
**neither shared-wire qualification is usable as pinned evidence** — the
producer guard forbids it, and that is correct behavior, not a bug.

Pre-existing unrelated Studio work in the tree must NOT be swept into these
commits.

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
  binding, so renderer and admission cannot drift. Single-plane designs pass
  no binding and keep the flat check unchanged. Evidence: the product path
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
