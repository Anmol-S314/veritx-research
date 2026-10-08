# Remaining work — prioritized backlog

**Base:** working tree after the shared-wire line (SROTA row-first/two-shape,
GEC-MECS compile, certify, render, execute live). Verified by 722 focused
tests, `make product-gates`, both registry gates, `git diff --check` clean.
Full DSE suite NOT run in that session, by operator instruction.

**Rule for every item below:** the definition of done is a live run or a
typed refusal, never a new status word. An item is done when a test shows
the behavior it names — compile + certificate for model work, flit
conservation for execution work.

---

## P0 — commit the green tree (blocks ALL evidence)

The 32 live-evidence tests refuse by design because the tree is dirty:

- `third_party/booksim2/src/networks/{network.cpp,network.hpp,gec.cpp}`
  (tap + VC-range route dumps, `dor_gec_gec` aliases)
- all model/verification/backend/test additions from the shared-wire line

**DoD:** the fork change and the model change land as separate commits on a
clean tree; the 32 refusals become passes. Until then, **neither shared-wire
qualification is usable as pinned evidence** — the producer guard forbids it,
and that is correct behavior, not a bug.

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
registry gate and `git diff --check` passed. No full-suite rerun was performed.

**Original escape-method DoD remains open:** the source has no distinguished
escape role, accessibility/closure invariant, or meaningful negative control
for removing an escape VC. The candidate-union rank proof is an explicitly
different sufficient proof, not a relabeled escape theorem.

---

## P3 — SROTA shape-mixing compiler wiring (implemented; suite gate pending)

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
  model explicitly does not simulate one. Either add a regulator primitive
  or prove a placement-only rule; compiler work comes second, never first.
- **Plane C:** `model/control_plane.py` now materializes an independent
  `ControlPlaneArtifact` with REQ/RSP/SNP VCs and plain XY, emitted on
  `Compilation.control_plane`. It explicitly makes no traffic/timing claim.
  Binding that second subnet through all pipeline/evidence stages and proving
  live conservation on both planes remain the acceptance conditions.

**DoD per item:** typed refusal removed AND a live multi-plane run conserves
flits on both planes.

---

## P6 — V5 intent materialization (the broad track)

From `docs/product/LOOM-CAPABILITY-CLOSURE.md`: nearly every V5 capability
is `PARTIAL / root identity only, blocked at MATERIALIZABLE`. Each is its
own compile→verify→execute→qualify slice, using the MECS line as template:

- transactions (outstanding / ordering / splitting) — no issue scheduler
- access policy — artifact exists, not emitted, not bound to Access Loom
- sidebands and clocks/domains — materialized records now emitted on
  `Compilation.sideband_set` / `clock_domains`; V5-root preservation,
  certificate/export binding and execution semantics still need closure
- reset and power — architectural identity only, typed compiler refusals
- CDC + async-FIFO model — no RTL differential
- IP catalog — 12 templates, not bound to stamps or compiler
- multi-plane fabric — `PlaneComposition` accepts single plane only

**DoD per item:** a compiled, certified, executed design — or the refusal
stays and says exactly which stage owns it.

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
- **RTL generation** (`NOT_IMPLEMENTED`): no emitter. DoD: supported-subset
  emitter with lint + simulation smoke before any READY claim.

---

## P8 — physical, packaging, measurements

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
- A full DSE run on the dirty tree previously reported **6266 passed, 25
  skipped, 10 failed**. Subsequent targeted work refreshed the compiled
  fixtures, aligned GEC materialization/import-layer assertions with the new
  implementation, and fixed the SROTA profile's missing config-key ordering;
  the affected focused set passed (18 tests). A rerun of the full suite was
  started but interrupted at operator request. It remains the pending final
  gate; run it once on a stable, clean tree before any release claim. The
  configured pytest-timeout plugin is absent, so its 900-second setting is
  not enforced.
- `fattree` spelling normalization, concentrated-mesh 2:1 lowering, and
  the Studio P2 notes remain open with ownership outside this line.
