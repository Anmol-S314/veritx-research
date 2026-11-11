# Clean-tree split into owned commits + Scope B framing (2026-11-12)

The 12/14 + C5 claims no longer live in an unvetted dirty tree. Summary of
this closeout line, measured not asserted:

- **Release hygiene: DONE.** The 806 dirty entries (566 untracked, 233
  modified, 7 deleted) were split into six owned lane commits on the committed
  tree: `574d5973` (shared-fabric RTL: framing/credit/Scope B line),
  `00bfb780` (compiler/DSE line), `bb4e3ded` (Studio snapshot),
  `daca1562` (gates/runners + LibreLane Sky130A spike), `841c3173`
  (composed-family evidence bundles + status docs), `587d45b1` (research WIP
  carry). ~211 MB of regenerable Verilator/Chisel/sby outputs were moved
  out-of-tree to `/tmp/opencode/backup-*`, not committed; excluded scratch
  (calculator/screenshots/.pi/.codex/.impeccable/audit/test-results) is
  recorded as a non-goal and stays untracked. **Product gates pass on the
  committed tree.**
- **C4 is CLOSED** (selected 74-agent project): the framed fabric carries
  HEAD/BODY/TAIL packets and per-VC allocation; the seat-run evidence is
  `runs/selected-r02-gec-mecs-seats-c4-20261112/` (lint 0 warnings, sim PASS,
  12/12 scenarios incl. multi_flit, multi_flit_contention and reset_recovery;
  5,476/5,476 flows, credits alias-free/drained/restored, design hash
  `ab7bce8f…`). C5 remains closed on that same fabric. C6/P9 physical stay
  operator-blocked.
- **Scope B framing landed and was verified at small shape.** The GEC-hybrid
  and SROTA fabrics now carry the same HEAD/BODY/TAIL framing (TYPE below
  SRC/VC), an output packet lock (one packet per wire at a time) and a
  `WIRE_PIPE`-deep elastic wire pipe with acceptance-space backpressure. At
  16 routers / 64-bit flits: hybrid lint clean, sim PASS (256+4 pairs,
  multi_flit ordered, mesh/mecs selector checks green); SROTA lint clean,
  sim PASS (256 pairs, multi_flit ordered, island/drop/row_first checks
  green). **Not closed by framing:** multicast bitmap, AXI/OrderingFSM/CDC
  composition, physical multidrop — those rows stay open in both manifests;
  hybrid/SROTA keep tap-derived semantic VCs (no producer VC to distrust) and
  occupancy-based backpressure (no per-(tap, VC) credit pools as on MECS).
- **Clean-tree release matrix: COMPLETE — 14/14 family rows PASS,**
  `PASS_WITH_NOT_RUN` (physical `NOT_RUN`; KNCube native-equivalence
  operator-owned). Manifest `runs/release-clean-20261112T020000Z/manifest.json`
  (sha256 `b375ffca195f48fcc42abe84c4307071fc4c1b231e4bd444d44857f6f2a4c86b`),
  `git_head` = the committed tree. **11/14 `final_implementation: true`**;
  GEC-MECS reports false with **2 lint warnings** at the committed state
  (`inject_vc` dead declaration; `vsel` 32-bit int with [31:2] unused,
  `u_noc.u_credited_fabric`) — both are dead-declaration nits fixed in the
  working tree; the gec_mecs row must be re-run after that lands for A2 to
  close. SROTA and GEC-hybrid stay false under their own Scope B lists; their
  `multi_flit` scenario returns **true** there (framing is real). The earlier
  00:17 run died at torus/tree4 on a dirty tree and is not evidence.
- **Single-project smoke manifest** (`scripts/complete_design.py --request`,
  frozen r02-derived v4 fixture): `runs/single-project-smoke-20261112T000000Z/`
  — freeze/compile/hardware `PASS_WITH_NOT_RUN`; physical `NOT_RUN`; not a
  release claim.
- **Toolchain pin** (REMAINING-WORK item 16): `sequential-gates.sh` now
  records repo head, dirty-file count and `--version` for python3/gcc/g++/
  make/verilator/yosys/openroad/iverilog into `toolchain.txt` before any gate
  stage starts.
- **Measured on this line:** small-shape lint+sim PASS (MECS 3×3 incl.
  framing, SROTA 4×4, GEC-hybrid 4×4); full DSE unit suite and the full
  Playwright re-run are NOT yet re-run on the clean tree and are not claimed
  green; `runs/veritx-p2p7p11-evidence/` remains dated 2026-11-09 and is
  explicitly stale until re-derived.

Still open: the gec_mecs 2-warning fix must land and the row re-run for
A2/12-of-14 to stand; Scope B multicast/AXI-CDC/physical rows; the 81-router
Chisel credit-preview emit (still OOMs structurally); REMAINING-WORK items
11–12 (full DSE unit suite, full Playwright re-run); the Studio Playwright
suite measured **115 passed / 4 failed / 13 skipped** with the opener's
environment — the 3 `app_repro` failures are the absent gateway on :8099
(operator-owned), the `native-sweep` failure is a UI input not enabled
(fixture-path control); neither is RTL; release-hermeticity items
GATE-5/6/7/10/11; INT-1/NEW-PROV-1 provenance persistence.

# Handoff blockers: A8 parity, slice template shape, mesh A2 (2026-11-11 19:08)

Three of the five `FINAL-IMPLEMENTATION-HANDOFF-20261111` blockers moved this
session. Measurements, not status words:

- **A8 parity — fixed.** `tests/test_final_implementation_evidence.py::_row_parity`
  passed the compiled `TopologyArtifact` object as BookSim's `network_file`, so
  BookSim exited before loading the trace and the parser reported the
  misleading "missing trace evidence". It now writes a real 2x2 AnyNet file,
  emits the RTL with `scripts/rtlgen/gen_rtl.py`, and runs the smoke. Measured
  CLOSED: BookSim drain 20 cycles, RTL 17, delta 3, payload parity exact, both
  sides conserve.
- **Slice template generate-shape — fixed.** `_apply_axi5_adapter_tieoffs_to_slice`
  required exactly one `endgenerate`; the template now has two (adapter select
  + CDC). It inserts the sink after the first block. The two prior failures
  (`payload_field`, then this refusal) now pass: **2 passed**.
- **Mesh A2 lint — clean.** Three emitter defects removed 133 warnings:
  dead `unused_noc_out_* = flit` assignments (now reduction sinks), ascending
  port-vector `ASCRANGE` (waived by name with the reason), and shared package
  `UNUSEDPARAM` (`FLIT_W`, `FT_BODY`; waived by name). Fresh mesh composed run:
  **lint PASS, 0 warnings, sim PASS, 13/13 scenarios**.
- **Negative evidence test clobbered the real bundles.** It called
  `write_evidence_bundle` for all 10 families, replacing measured A2 rows with
  `OPEN — no simulation scenarios supplied` (the actual reason every bundle
  read that). It now writes to a temp `BUNDLE_DIR` via monkeypatch.
- **A10 multi-flit test omitted `noc_pkg`.** The emitted destination adapter's
  ports are `noc_pkg::FLIT_W` wide, but the standalone test compiled only the
  adapter + TB. It now emits and includes `noc_pkg.sv`; **1 passed**.
- **Fly A7 — fixed (proof domain, not routing).** Fly has `vc_count=1`, but the
  proof still constructed a second `esc` class; it also walked routes between
  routers that can never hold an endpoint (fly injects at stage-0 and ejects at
  stage-2 routers). Both are false obligations. The proof now skips a
  non-existent escape class and restricts the starting pairs to real
  ingress↔egress terminals. Measured: **PASS**, 512 edges / 256 channels,
  unbounded `sby prove`. `fly` added to the parametrized CDG suite;
  `tests/test_composed_family_cdg_proof.py` **9 passed**.
- **Twelve of the fourteen families now carry `final_implementation: true`.**
  With A2/A8/A10 measured on the same design hash (and fly's A7 on its real
  ingress↔egress domain), the sweep reports **lint 0 warnings, sim PASS,
  13/13 scenarios, `open_rows: []`** for mesh, torus, concentrated_mesh, ring,
  fly, qtree, tree4, flatfly, fattree, dragonflynew, GEC-MECS and KNCube.
  Fresh end-to-end confirmations: mesh (`/tmp/opencode/mesh-final-qpbsvg1s`),
  fly (`/home/datavex/veritx-tmp/fly-final-sk4idckz`), GEC-MECS
  (`/home/datavex/veritx-tmp/gec-mecs-final-hxop6x49`) and KNCube
  (`/home/datavex/veritx-tmp/kncube-final-wag5ojw7`). The release matrix is
  **14/14 family rows PASS**; `PASS_WITH_NOT_RUN` remains because physical is
  `NOT_RUN` and KNCube native equivalence is operator-owned. GEC-hybrid and
  SROTA remain false under their own Scope B claim lists. This is the
  COMPOSED_FAMILY scope only; it is not the selected 74-agent project, not
  placed hardware, and not a release claim.

- **GEC-hybrid and SROTA lint is clean.** Their 19 and 12 style warnings
  (unused destination/VC vectors, per-instance constant direction comparisons,
  and the `'0` fill false positive) are fixed with named sinks/waivers in the
  emitted fabric templates. Rendered-fabric lint: **0 warnings**. Their
  `final_implementation` stays `false` under the Scope B claim lists; clean
  lint is not a Scope B closure.
- **C5 is closed.** The selected r02 contract's **74 seats are now the real
  traffic endpoints** on the emitted 81-router / 162-wire / 8-tap / 8-VC /
  128-bit GEC-MECS fabric. Run `selected-r02-seats-final-20261111T220516Z`:
  **lint 0 warnings, sim PASS, all 9 scenarios true**, 5,476/5,476 ordered
  seat flows accepted and delivered, routing local=74 / same_row=578 /
  same_col=536 / row_then_col=4,288, credits alias-free/drained/restored.
  Durable artifact: `runs/selected-r02-gec-mecs-seats-20261111/` (manifest,
  RTL, logs, SHA256SUMS). Gate: `tests/test_gec_mecs_selected_seats.py`.
  C4 (multi-flit + per-VC allocation) and C6 (physical) remain open, so the
  manifest correctly stays `final_implementation: false`.
- **C4 is closed.** The selected 81-router / 162-wire / 8-tap / 8-VC shared
  fabric now carries multi-flit packets: HEAD/BODY/TAIL is emitted, routed and
  reassembled as one packet; `multi_flit_contention` delivers 6 flits with one
  source switch; `reset_recovery` leaves outputs idle and carries a post-reset
  transfer. Injection VC allocation is per-router round-robin; the wire is a
  `WIRE_PIPE`-deep elastic pipeline (two real bugs fixed: non-elastic stage 0,
  and the pipe driver comparing the final destination instead of the
  intermediate row/col router). Measured on the selected 74-seat contract:
  **lint 0 warnings, sim PASS, 12/12 scenarios**; durable artifact
  `runs/selected-r02-gec-mecs-seats-c4-20261112/`. Gate
  `tests/test_gec_mecs_scaled.py` (5 passed). Residual: contention/reset are
  qualified at the selected 8-tap envelope; the 5-tap 6×6 shape exposes a
  back-to-back BODY/TAIL VC-selection ordering bug and stays a framing smoke.
  C6 (physical) remains open.
- **Final matrix:** `release-final2-20261111T203409Z` — **14/14 family rows
  PASS**, **12/14 `final_implementation: true`**, result `PASS_WITH_NOT_RUN`
  (physical `NOT_RUN`, KNCube native equivalence operator-owned).

Still open on this line: the full regression suite result; Scope B engineering
(multi-flit, VC allocation/credit pipeline, multicast, AXI/OrderingFSM/CDC
composition, physical multidrop); Scope C (selected 74-agent C4/C5, 81-router
Chisel OOM); P9 physical; release hygiene.

# Selected-project GEC emit — root cause found, route interface compacted (2026-11-11)

## What was actually wrong (measured, not assumed)

The selected-project emit failure was recorded as "Java heap OOM after 1,634 s at
`-Xmx6G`". The cause is structural, so a bigger heap cannot reach it:

- The Chisel `CreditRouter` carried its route table as a **one-hot legal mask over
  every slot plus a per-slot tag vector, per lane**. That is `lanes x slots` per
  router, and at the selected 81-router shape it is **2,966,784 bits across the
  router boundary** and **2,998,768 FIRRTL reduction nodes** — about **8.5x the
  36-router baseline** that does elaborate.
- The cost driver is the **FIRRTL IR, not the Verilog**. For the 36-router
  baseline the emitted IR is **302.8 MB of text in 2,174,947 statements** while
  the Verilog beside it is 25.6 MB. **70.5 % of statements are primitive `node`
  operations**, so the cost is node count, and every statement carries a
  source-location annotation.
- Module families of that IR: `CreditRouter` x36 = **54.4 %**,
  `CreditMatch` x72 = **33.6 %**, `Queue` x3952 = 5.7 %,
  `CreditOwnership` x36 = 2.6 %.
- Measured thresholds on this host at `-Xmx3G`: **36 routers emits** (spending
  85-90 % of its time in GC), **49 routers OOMs**, 81 routers needs > 6 GiB.

## Change made and verified

- `CreditRouter.scala`: the route interface is now a **slot index + `valid` +
  tag** instead of a one-hot mask plus a per-slot tag vector. The compiled
  contract resolves every destination to exactly one slot per VC, so this is the
  same information in 10 bits per lane rather than 256. The route interface
  drops to **97,744 bits** and the reduction nodes to **374,846**.
- `CompiledGecCreditPreview.scala` and `HybridCreditRouter.scala` drive the new
  interface; `CreditRouterSpec.scala` pokes the new fields.
- The granted slot is the lane's legal slot, so the tag is now captured at grant
  time instead of being re-read from a per-slot vector at send time. That is the
  same value for every compiled contract and every existing test.
- **ChiselTest suite: 24/24 pass, no elaboration warnings.**
- **36-router credit preview now emits at `-Xmx3G`** (the historical baseline
  was emitted under a 6-GiB heap). Verilog 28,640,272 -> **25,579,966 bytes**;
  the emitted artifact is no longer byte-identical to the historical one, and
  the reason is recorded rather than hidden.
- New: `tracks/t3-topology/dse/veritx_dse/product/gec_rtl_cost.py` (cost model
  plus `measure_firrtl`, which reads a real emitted IR) with
  `tests/test_gec_rtl_cost.py` — **7 passed**. New:
  `scripts/check_chipyard_gec_credit_preview.sh` makes the credit-preview emit
  reproducible in-repo.
- Python regression: `tests/test_chipyard_gec.py`, `tests/test_gec_mecs_scaled.py`,
  `tests/test_gec_rtl_cost.py` — **16 passed**.
- The 81-router contract was re-exported from the saved revision and reproduces
  **81 routers / 8 VCs / 162 shared wires / 74 endpoints** with binary hash
  `e772922bc4b069e418045248adcfb1c7e180823799c4d7c22c7beaf0fb21c6a0`, **identical
  to the input of the OOM'd attempt 4**. The router is therefore the only
  variable between that failure and this run.

## What is still open

- **The 81-router credit preview still does not emit.** The compaction is
  roughly a 2x improvement, not the 3-4x the shape needs. The remaining terms
  are `CreditRouter`'s `lanes x slots` reductions (about 39 % of that family's
  statements) and `CreditMatch` at 33.6 % of the IR.
- The product's own shared path (`run_gec_mecs_shared`) is a parameterized
  SystemVerilog template and **does take the selected 74-agent contract**.
  Measured 2026-11-11 on `p-fd7e5e31be77-r02`: **lint PASS** (18 warnings) and
  **sim PASS** under Verilator and Icarus, all nine scenarios true, at
  **81 routers / 162 shared wires / 8 taps per wire / 8 VCs / 128-bit flits**,
  driving **all 6,561 ordered router pairs** (`accepted=6561 delivered=6561
  stall_cycles=12 drained=1`; routing local=81 same_row=648 same_col=648
  row_then_col=5184). Evidence: `runs/selected-r02-gec-mecs-shared-20261111/`
  (manifest, both SystemVerilog sources, every lint/build/sim log).
  - **Honest scope:** the generated testbench's endpoint model is the *router*
    set, so the project's **74 declared agent seats are not the traffic
    endpoints of that run**. The fabric at the pinned shape is proved; the
    endpoint-attached design is not.
  - It is a structural shared fabric with per-(tap,VC) credit accounting. It
    does not carry the Chisel credit router's VC allocation (iSLIP) or its
    multi-flit HEAD/BODY/TAIL pipeline, which is what Scope C4 needs.
- So: **the selected project's fabric now has emitted, linted and simulated
  RTL.** Scope C4 (multi-flit framing + per-VC allocation in the shared
  fabric), C5 (end-to-end run of the selected contract *with the 74 seats as
  endpoints* and conservation/credit/reset accounting over them) and C6
  (physical signoff) remain open.
- Nothing here closes a release gate on its own, and `final_implementation`
  remains `false` in every artifact.

# Intent-to-RTL recovery — 2026-11-10

## Current implementation update

- The compiled family contract retains every attachment seat in `params.seats`. The composed-family renderer now emits endpoint-tagged seat/concentrator wiring for concentrated and multi-stage families. Latest strict release matrix (`scripts/complete_design.py --release`) records all 14 configured family rows PASS; see the 2026-11-10 checkpoint below. This remains development RTL (`final_implementation: false`), not selected-project completion.
- Fixed `_render_family_destination` to store the request's source endpoint in the declared `src_q` state instead of assigning the undefined `init_q` signal. A focused source regression covers this; Verilator lint exposed the original defect.
- Diagnosed and fixed the family RTL transaction stall from actual simulator logs: (1) output-stage valid flits never advanced their hold counter before the configured traversal threshold; (2) opposite link directions shared input/output signal names; (3) route-gate bit slices used packet endpoint width instead of router-ID width; and (4) request sequence/response status fields disagreed with the ordering FSM and destination adapter. The composed-family router now uses distinct input/output nets and consistent request/response field positions.
- Verifier logging is now actionable: family simulation assertions include the captured simulator log, and Verilator build timeouts surface partial output. A real `Disk quota exceeded` from GCC's `/tmp/cc*.s` assembly output was captured; reruns use disk-backed temporary/build directories under `/home/datavex/.cache` (34 GB free at inspection), one build job and `-O0`.
- Verification: torus transaction simulation and focused mesh regression passed. The current strict fourteen-family matrix evidence and its limitations are recorded below; older matrix runs are historical and are not promoted retroactively. Python syntax compilation and focused tests passed. Pytest continues to warn that the configured `timeout` option is unknown.
- Family labels in the test now follow canonical compiled names (`mesh`, `dragonflynew`), and failure assertions print actual simulation logs. A width-64/128 extension test exposed a contract mismatch: the compile bundle emits 64-bit flits (57-bit payload), while endpoints declare 64/128-bit data. The composed path correctly refuses before output with `UNSUPPORTED_COMPOSED_FAMILY: flit too narrow for data width`; the old test's assumed 96/160-bit flit widths were not in the compiled request. Regression now requires early refusal/no output and retains a 32-bit mixed-clock simulation check; **1 passed** in 26.05 s.
- The first adapter-integrated vertical path remains open. The composed-family wrapper is still a development path and must not replace the compiled endpoint-preserving GEC credit-router core in the product flow.
- Recovered the exact selected contract snapshot for revision `p-fd7e5e31be77-r02` (hash `ab7bce8f71b5ed4fde4101ee80a60b6c69c16989d966f0f9096dd6d76ad392f0`): 74 endpoints, 81 routers, 8 VCs, 162 shared wires. Its existing private-runner RTL emit job was attempted under the pinned 8-GiB cgroup / 6-GiB JVM / one-job policy, but the runner safely blocked before execution (`exit 2`, receipt `execution/runs/credit-gec-selected-v3-emit/attempt-1/receipt.json`): preflight saw an unrelated `constellation.SharedMecsProductionSpec` Java job and an active Verilator `obj_slice` build. No RTL output was generated. Do not bypass the runner or kill those processes; retry only after its preflight confirms the shared heavy queue is clear.
- Remaining project RTL regressions (`test_project_top_slice.py -k 'not test_composed_family_lints_and_sims'`) completed **13 passed / 12 failed / 11 deselected** (242.76 s). Captured causes: the 2×2 composed-slice simulation finishes with `status: FAIL errors=185` despite final aggregate conservation (intermediate write/read timeouts, ordering and beat-count failures; S18/S19 require an unimplemented multi-destination primitive); several tests still call the guarded 2×2 renderer for larger meshes (`DST_W=4/5`), and two family-ID assertions are stale (`kncube` is now recognized; canonical Dragonfly key is `dragonflynew`). Width-64/128 legacy-slice cases also hit the same 2×2 guard. The 4-VC failure was traced exactly: widening matched only an obsolete `esc_starve` selector template, but current RTL uses `esc_yield_q`; `show_vc` widened to 2 bits yet still exposed only VC1/VC0. Router trace showed VC2 flits loaded at router0 (`FWD p=1`) but never enqueued downstream, yielding `injected=2, ejected=0, dest_req=0`. Added a replacement for the current selector template; `test_vc4_cycles_ejection` now passes all four per-VC runs (**1 passed**, 85.09 s). The migrated family-gate run passed five structural/simulation checks in 251.28 s; five stale assertions were corrected and their focused rerun is **5 passed**. This is not a green full project RTL suite: the 2×2 composed-slice transaction failures remain open, and no P1–P11 release gate is closed by these development tests.

## Latest checkpoint — 2026-11-10

- Strict release-matrix command: `PYTHONPATH=tracks/t3-topology/dse python3 scripts/complete_design.py --release --out runs/rtl-final-matrix-20261110T143046Z`.
- `runs/rtl-final-matrix-20261110T143046Z/manifest.json`: **14/14 family rows PASS**; every row has nonempty all-true scenarios (7–13 per family), lint/simulation PASS, and hashed per-family logs. All rows are marked `development_milestone: true`.
- Overall runner result: `PASS_WITH_NOT_RUN`, process exit 1. Physical was not requested, so that gate is NOT_RUN. The manifest also retains `KNCUBE_NATIVE_EQUIVALENCE_UNVERIFIED` because the external Constellation source is absent. This is not a final-release green or selected 74-endpoint proof.
- First matrix attempt `runs/rtl-final-matrix-20261110T140602Z/` is preserved as failed evidence: it used a prior source revision and recorded four memory-co-seat refusals. The rerun above is the current result; no logs were overwritten.
- Focused current tests: family binding + multi-instance seat suites **65 passed**; full composed-family suite `test_project_top_slice.py` **37 passed**; Python syntax and status-doc diff checks clean. The configured matrix is smoke-level; pinned workload, packet/credit/reset, native KNCube equivalence, selected-project emission, physical placement, and clean reproduction remain open.

Goal: implement the saved selected design, not a fixed catalog reference. Preserve the original 74-endpoint/81-router GEC project; the operator-approved 36-router contract is a development regression only.

1. DONE: traced the real product handoff (`service.py::submit_rtl_preview` → `worker.py` → `rtl_export.run_rtl_preview`) and ran existing compile-bound source tests: 32 passed in 7.01 s. These are source-contract checks, not RTL simulation. Graph index was stale for the composed code, so actual files/callers were inspected directly.
2. Reuse the compile-bound hardware owners to implement one exact request end-to-end. Check: emitted topology/resources/endpoints, packet layout, VC assignment and router controls match the same frozen revision; unsupported behavior is identified before heavy execution. Do not route through the canned catalog exporters or silently substitute generic routing.
3. Simulate that exact implementation under the approved 12-GiB cap. Check: payload/packet identity, stalls/credits, contention, reset and conservation; a pass is not placement or complete qualification.
4. Extend the same request-bound path across fourteen families only after the first vertical path passes. Check: changing supported intent changes the corresponding hardware, while unsupported intent never produces substituted RTL.

Plan self-review: compilation already captures an exact `chipyard_source_contract`; do not build another contract/database. `worker.py` dispatches `RTL_PREVIEW` only to `run_rtl_preview`; the request-derived composed top and GEC credit preview are not used there. The GEC credit preview already preserves compiled widths/VCs/router timing but lacks protocol adapters/ordering/CDC. Simply wiring it into the UI or relabeling it final would not close the gap. Also, composed-family parameters already derive widths/VCs from the compile bundle; the earlier blanket statement that all its hardware is fixed 64-bit/2-VC was too broad—the legacy preview prerequisite and manifest constants are separate problems. Verify actual code and behavior before choosing an integration seam.

## First verified recovery patch

- Reproduced a concrete loss before product integration: a four-instance compiled mesh request produced four compiled seats but only two composed initiator ports plus one memory target (three total). `composed_family_params_from_request` grouped endpoint seats by agent group and silently kept the first router.
- Added two regression cases in `tests/test_project_top_slice.py` for either initiator group containing two instances. Both failed before the patch (`DID NOT RAISE`). They also prohibit preview emission and any output directory for a lossy request.
- Added a guard in `product/project_top_rtl.py::composed_family_params_from_request`: the group-level development wrapper refuses multiple instances before producing hardware. This prevents silent endpoint loss; it does NOT implement multi-instance endpoint adapters and is not completion of step 2.
- Verification: `PYTHONPATH=.:tests timeout --signal=TERM --kill-after=5s 60s python3 -m pytest -q tests/test_chipyard_fabric.py tests/test_chipyard_sources.py tests/test_chipyard_gec.py tests/test_project_top_slice.py -k 'chipyard or never_drops_agent_instances or family_router_interface_deterministic'` from `tracks/t3-topology/dse`: **35 passed, 31 deselected**, 8.45 s. One existing ignored pytest `timeout` option warning remains. No RTL compilation/simulation was run for this guard.
- Next actual implementation gap: one connected adapter path per compiled endpoint instance, including multiple memory targets and address-to-instance response routing. Keep the endpoint-preserving GEC credit-router core as the network owner; do not wire the lossy group-level top into the product or call the new refusal feature completion.

# Native topology RTL export — 2026-11-10 (stopped; reference evidence only)

- Pinned a 132-file native exporter snapshot at `/home/datavex/.cache/veritx-noc-lab/vla-native-execution/experiments/constellation_topology_rtl/rtl-completion-v3-20261109/execution/sources/all14-native-rtl-20261110-v1`; selected-source digest `606370211110259899cbdfbe0317a75062817e815ac4650fe37b7fae2d062ee8`.
- Kept catalog-native profiles unchanged. Exports run serially through the existing private runner (12-GiB cgroup, 6-GiB JVM heap, one build job). This is an RTL-emission milestone, not simulation or qualification.
- `mesh8x8` emitted successfully: 64 routers, 224 links, 64 terminals, 4 VCs, 128-bit payload, buffer depth 15; 2 Verilog files totaling 145,939,167 bytes. Its inventory checks 4,096 states with zero mask mismatches. Evidence: `execution/runs/all14-native-rtl-20261110-v1-mesh8x8-xmx6g/receipt.json` and `execution/ready-cells/all14-native-rtl-20261110-v1/rtl/mesh8x8-xmx6g/`.
- The first mesh attempt used an explicit 3-GiB heap and failed with Java heap OOM; it is preserved as a failed run, not counted. The corrected 6-GiB retry passed.
- Scope correction: these native exports are fixed research profiles, not RTL compiled from a saved workload/project. They do not satisfy intent-to-RTL. The unnecessary batch was stopped after `mesh8x8` and `torus8x8` completed; `cmesh` was interrupted mid-run and has no terminal receipt, so it is not counted. The other eleven were not started. Keep the two artifacts as reference-profile evidence only.
- The actual product path is still incomplete: `rtl_export.run_rtl_preview` consumes a compiled request but emits fixed 64-bit/2-VC generic routing and refuses shared wires; `run_composed_family` builds a request-derived development top but still labels it `final_implementation: false`, uses the preview sidecar and fixed packet/VC limits. Next work must close this selected-project gap, not extend the fixed-profile batch. No simulation, physical-design, or qualification status is inferred from either export.

# Agent address mapping, fine controls & fabric analysis — 2026-11-05

## Delivered
- New `#/design/agent-map` (Agent Fabric Map): edits real `agents` interface fields and `address_map.ranges` with FIXED_INSTANCE/STRIPED selection, auto-map, schema checks (overlap, alignment, target index, singleton/multi-instance selection), `topology-preview` validation, draft save, compile. Writes only those two blocks; schema-v5 drafts are guarded read-only, and analysis reads `base_v4`.
- New `#/analysis/fabric` (Fabric Analysis): static checks for address windows/coverage, Srota shape/VC-policy rules (RT-R7, Valiant second turn, rank express-layer), VC-R5 port-budget reconciliation, MECS shared-link reachability/taps, island confinement (I-ISL), arbitration executability, certificate/deadlock facts, and RTL reach.
- `#/design/addresses` now computes overlap, mapped union, target coverage and resolved decode; `#/design/mapping` links to the agent map and no longer claims mapping is absent when windows exist.
- RTL preview now emits `addr_decode.sv` from the resolved `AddressDecodeArtifact` (fixed, striped, base-0, top-of-2^64, empty), adds it to `meta.json`, the Makefile (`lint-addr-decode`), the archive and the manifest (entry count, hash, endpoint→router/port map, lint clean/warnings). Manifest `address_decode.status` is in the job result.

## Evidence
- `npx tsc --noEmit` clean; `npx vitest run` 281 passed (44 files); `npm run build` OK.
- Python: `tests/test_addr_decode_rtl.py` 8 passed; `test_rtl_support_gate.py` + `test_rtl_generation.py` + `test_catalog_refinement_rtl.py` 38 passed. Verilator lint is clean for fixed-only, striped, empty, base-0, top-of-space and 32-bit address cases.
- Playwright: route inventory + live Design + address correction 3/3. Full suite after the fixes: **108 passed / 0 failed / 13 skipped**. The two previously failing broad tests were fixed: `flow/compare` now resolves to the canonical search heading in the route sweep, and a schema-2 draft with `noc_config.concentration: null` seeds the documented mesh concentration instead of failing client-side validation.
- Live browser (separate Vite 5188 → gateway 8099): Srota `p-a34dda8428eb-r01` shows compiler deadlock PASS (160 nodes/144 edges), shape policy PASS, strong connectivity PASS across 48 shared links/96 taps, VC-R5 warnings. Address-map save+compile on disposable `p-88036865d1ff` produced r03 with resolved decode `TEST_RANGE → compute_tile instance 0 endpoint 0`.
- Gateway at 8099 is stale after the Python edits; restart before expecting `address_decode` in a live preview manifest.

## Gaps (deliberate)
- `AddressRange` has no per-initiator permission/firewall field. The UI states this on every surface; adding one needs model + compiler + RTL work.
- The preview remains topology-only 2-VC free/escape; Srota routing/VC policy/side buffer/telemetry/islands are compiled but not emitted.
- VC-R5 port enumeration remains open; the analysis shows the disagreeing readings instead of choosing one.
- No permanent e2e spec for the two new pages yet; the route inventory covers their source IDs and a standalone browser check covered both at 1440/1280/760/390.

# Prototype workflow correction — 2026-11-03

## Goal (operator's latest contract)
Workload template -> fine-tune HIGH-LEVEL WORKLOAD intent -> generate custom workload traffic -> run BookSim + ASTRA-SIM over the FULL topology catalog -> inspect measured results and choose a fabric -> AI-assisted PARAMETER refinement of that selected fabric -> finalize topology and generate actual supported RTL. No repository-trace requirement, no four-candidate scalar study masquerading as full search.
Acceptance: a disposable workload goes through the real path; every topology/backend has a measured result or explicit failure/unsupported reason; selection and AI changes remain pinned to their source; RTL comes from the real emitter with its actual support limits.

## Done / verified
- Earlier visual simplification removed duplicate flow rail. Prior build and 7 narrow browser checks passed, but operator correctly rejected the PRODUCT FLOW: those tests did not prove the requested workflow.
- Prior full unit run: 183 passed, 1 typography-contract failure (`styles.css` contains an 11px chart label). Do not hide this or claim full green.
- Current work-in-progress changes expand FlowOptimize to reuse DraftEditor, exposing topology sizing, physical assumptions, arbitration, 7 router buffer/pipeline controls and Srota intent (MECS, routing shapes, VC policy, side buffer, telemetry, islands). Removed the three-field-only ManualParameters and the unconfigured AI panel from that step.
- Current implementation now includes process-isolated CATALOG_EVALUATION jobs, a 12-family typed candidate catalog, the real BookSim + ASTRA federation, sealed result/trace artifacts, explicit evidence-reverified fabric selection, parameter-only AI proposal mode, and a clearly non-final RTL preview endpoint.
- `cd apps/studio/prototype && npx tsc --noEmit`: passed after the new campaign/refinement/finalization UI wiring. Current permanent browser tests still need updating; a separate temporary full-flow interaction harness is running.
- `PYTHONPATH=tracks/t3-topology/dse python3 -m pytest -q .../tests/test_catalog_evaluation.py --basetemp=/tmp/srota-catalog-contract-20261103-b`: 3 passed (15.12s), including REAL adapters, generated trace downloads, explicit selection and rejection of altered result manifests.
- Full REAL 12-family simulation with a disposable 32-agent declared compute/collective workload: exit 0. BOTH BookSim and ASTRA-SIM evaluated Mesh, Fat-tree, Flatfly, Srota, GEC MECS, GEC hybrid and Ring (7 families). Concentrated mesh refused concentration representation; Torus failed DEADLOCK_FREE; QTree/Tree4/Fly require complete 64-terminal attachment. All 12 rows contain both backend verdicts; 134 generated input artifacts were indexed. Evidence: /tmp/srota-full-catalog-20261103-a/catalog.json and background task baa1317e0.
- Live gateway on 127.0.0.1:8099 (now PID 446131 under background task b3e2286c2) was restarted with the new code after confirming no in-flight project jobs and preserving cwd/PYTHONPATH. User projects untouched: p-5735adef2860 stays at r06, p-2384fa5916a5 at r03 (all revisions dated before this work). Their catalog plans now report 12 families, both backends, and no selection.
- Live gateway coverage (disposable p-88036865d1ff, single tp collective, 8 participants, 4 declared compute stages): both backends EVALUATED mesh, fattree, flatfly, gec_mecs, gec_hybrid; UNSUPPORTED concentrated_mesh, srota, qtree/tree4/ring/fly_native; torus COMPILE_FAILED (deadlock certificate). With a two-class workload (tp_collective + dp_collective) only mesh survived: single-class profiles refuse multiple classes, the multi-class profile refuses concentration, and srota/gec refuse shared VC subsets. Both matrices are real refusals, not fabricated zeros; evidence in /tmp/srota-live-e2e/catalog-view.json and /tmp/srota-live-e2e-b/catalog-view.json.
- Discovered live: noc_controls.arbitration = round_robin compiles but is refused at evaluation ("authored router execution currently proves iSLIP only; round-robin is not substituted"). The editor now disables that option with the stated reason instead of letting a user reach a dead end.
- TEMPORARY harness /tmp/srota-thorough-check/ui-smoke.cjs (all APIs mocked) already passed the full interaction; it is not a permanent test.
- Concurrent edits were observed to the new tests/test_catalog_evaluation.py (400/422 assertions/comments changed outside this session). Preserved them and warned operator to pause other writers. Source checkpoint: /tmp/srota-thorough-check/service-checkpoint.diff.

## Next
1. DONE: browser interaction harness and permanent suite both consume the current flow (16/16 earlier, 11/11 after the arbitration change, RTL-warning test added).
2. DONE: focused tests for expanded DraftEditor/parameter proposals (tests/test_catalog_refinement_rtl.py, tests/flow.spec.ts).
3. DONE: CATALOG_EVALUATION lifecycle; workload lowers separately to BookSim packet trace and ASTRA-SIM execution graph.
4. DONE: full 12-row matrix with both backend verdicts, refusals kept visible.
5. DONE: explicit measured selection, then parameter-only AI refinement with consent and model config after selection.

### Remaining gaps (deliberate, do not paper over)
- LIVE PROOF COMPLETE on disposable p-753323d9dc88 (mesh): 12-family catalog job-28a9bdd66517 -> explicit mesh selection -> allocator/switch-traversal/islip refinement -> COMPILED r01 -> final evaluation job-1006b4406945 COMPLETED with NETWORK_COMPLETION (BOOKSIM_STANDALONE) and SYSTEM_MAKESPAN/ASTRA (ASTRA2) READY -> rtl-readiness available -> RTL preview job-4a38e4727aaf COMPLETED. Preview archive 29 KB with rtl/noc_pkg.sv, rtl/router.sv, rtl/noc_top.sv, rtl/tb_top.cpp, selected-topology.anynet and the manifest.
- Verilator lint on the emitted preview is PASS with 17 warnings (LATCH inference in router.sv:351), so `lint.clean` is false and the UI now prints the warning count. Emitter-quality fix (latch removal) is NOT done; it is a real limitation of the existing emitter, not a UI issue.
- Two-class workloads (tp_collective + dp_collective) currently leave only mesh measurable; single-class profiles refuse multiple classes and the multi-class profile refuses concentration. If the product must support multi-class intent across families, that is a backend capability gap, not a flow bug.
- General (non-preview) RTL for arbitrary compiled controls is still not implemented. The preview hardcodes 64-bit flits and 2 VCs and refuses shared-wire topologies.
- Broad browser regression (all 9 spec files) found 3 stale expectations, all fixed without weakening invariants: intent tab order is now Workload, Requirements, Fabric, Validate; the unconfigured-AI test asserted a removed message (consent is now disabled outright, a stronger guarantee); the fabric-comparison test used uppercase executable_values and a typed srota base the certified patcher cannot convert from (live capability returns lowercase ['concentrated_mesh','mesh']).
- LiveOperations now names the real reason family comparison is disabled for a typed fabric (patcher converts mesh/concentrated_mesh/torus only) instead of always claiming too few executable families.
- FINAL GATES: Python catalog/refinement/RTL contracts 32 passed; UI units 185 passed (35 files); every Playwright spec 92 passed, 13 skipped (live-only, gated by VERITX_LIVE_TEST), 0 failed; production build OK; tsc clean.
- Two rename drifts also fixed in tests: the advisor page heading is now 'Revision Study (Advanced)', and the study family picker no longer offers families the certified patcher cannot substitute.
- Fabric choice now reuses the Reference Catalog composition instead of a bespoke table-first view: four profile cards (Network / System / Balanced / Best evidenced) driven by src/catalogRecommendation.ts, the shared InteractiveScatter for network-vs-makespan trade-off, a fabric-selection strip carrying the explicit Choose action, and the measured table kept as the complete record. 8 unit tests cover refusal-never-wins, scope separation, frontier membership, bar derivation and no-winner copy.
- The guided flow is now an index: `flow-workspace-links` names the full workspace that owns each step's evidence (Workloads & requirements, Lowering preview, Reference catalog, Fabric ablations, Curves & Pareto, Revision study, Fabric topology, Analysis summary, Run evidence, Delivery manifest).
- Visual check at 1440/1280/760/390 shows no horizontal overflow and 4/2/1-column card stacks (screenshots /tmp/catalog-cards-*.png). Two polish fixes came out of reading the render: identical scope deltas print "same network cycles" instead of "−0", and the Balanced card names its frontier count rather than "eligible".
- flow/search now shows the same four profile cards unranked before a run (dashed, "Not measured"/"Awaiting run", no numerals), so the decision shape is visible before anything is measured. Verified in the browser: 4 cards, 0 numeric "cyc" strings, launch button still disabled without consent; screenshot /tmp/catalog-pending-1440.png.
- Final gates after the recommendation work: units 193/193 (36 files), every Playwright spec 92 passed / 13 skipped / 0 failed, production build OK.
- Live gateway note: the process I started (450220) shut down gracefully; port 8099 is now served by PID 519218 under parent 519216 (someone else's supervisor, started 00:30). I did not restart it. Live logs show the operator is using the new catalog flow (catalog-evaluation polling on p-3851c745c2c5 / p-fd7e5e31be77).
- `GET /projects/{id}/jobs` without `kind` returned 422 (the parameter was required). It is now optional: omitting it lists every kind, filtered results are unchanged, and tests/test_catalog_evaluation.py covers the unfiltered case (6 passed). This takes effect on the next gateway restart; the UI always sends kind, so nothing user-visible is blocked.
- No deletion endpoint for disposable projects; test projects p-88036865d1ff, p-e41d8c78ffec, p-753323d9dc88 remain in the store.
6. Wire supported RTL emission from the finalized pinned revision; run the real emitter and available lint. Never equate RTL emission/lint with hardware qualification.
7. Broad focused regression + full unit/build + real disposable end-to-end check, report exact gaps.

## Key facts and paths
- Repo highly dirty with extensive PRE-EXISTING changes. Preserve them. No delegation requested. Do not overwrite/reset/commit unrelated work.
- UI: apps/studio/prototype/src/{FlowView,DraftEditor,IntentWorkspace,FlowStart,FabricSearch,LiveOperations,LaunchEvaluation,LiveAgents}.tsx
- Workload editor already supports model, TP/DP/EP/PP, explicit collectives and compute stages: src/WorkloadStudio.tsx.
- Existing scalar study limit <=4 and family subset mesh/cmesh cannot satisfy full catalog search. Prior FlowSearch now uses LiveExplore fabricSearch and MUST be replaced with actual catalog workflow.
- Existing catalog ablation: gateway/ablations.py -> scripts/ablate_workloads.py. 12 static 64-terminal catalog arms, arbitrary safe simulator overrides. Existing runner has --replay-catalog but workload IDs still chosen from static WORKLOADS; project custom trace integration is not wired.
- Backend root: tracks/t3-topology/dse/veritx_dse.
- Canonical intent lowering: workload/intent_lowering.py::lower_compile_workload. Explicit collectives/compute required. Never infer timings/payload from model name alone.
- Logical->physical packets: workload/traffic.py::PhysicalTrafficArtifactV2/V3; backend/booksim_projection.py::render_trace. Renderer serial injection order is NOT profiled application time. PacketFormatArtifact has flit_width_bits.
- Shared existing projection construction: application/capability_truth.py::_parents_from_bundle; backend/booksim_adapter.py::_canonical_traffic.
- Existing authenticated candidate pipeline: optimization/{topology_search,real_evaluator,ai_search}.py. topology_search pilot bounds 4 proposals, 64 seats, allowed kinds mesh/cmesh/torus/flatfly/explicit. Do not silently call that full catalog.
- Service jobs: product/service.py::submit_ai_search,_worker_payload,ai_search_view,adopt_ai_candidate; product/{jobs,worker}.py provide process isolation, cancellation, immutable snapshot and proof revalidation. Reuse lifecycle rather than invent client-only loops.
- Actual RTL emitter EXISTS: tracks/t3-topology/scripts/rtlgen/gen_rtl.py reuses rtl/mot_htree/gen_rtl_htree.py. tests/test_rtl_generation.py pins a restricted connected 2-VC slice and real Verilator lint; other VCs/topologies can be refused. Product service currently says it does not emit/verify RTL, so the UI delivery seam remains missing.
- Live dev server http://127.0.0.1:5174 -> gateway http://127.0.0.1:8099. Other running servers/desktop gateway exist; do not kill/reconfigure casually.
- User projects observed read-only: Qwen p-5735adef2860 (r06) and Astr p-2384fa5916a5 (r02). Do not mutate them to test.
- Vite once cached an empty LiveOperations module during file edits; touch source invalidated it. Avoid running browser tests mid-edit. Early browser failures were cache-related; later 7 passed before current expansion.
- Existing tests/flow.spec.ts was rewritten for the new order/selectors and passes (7 tests). Legacy fabric-apply.spec.ts updated to the real routes and passes (3 tests). Combined permanent regression (flow, fabric-apply, fabric-search, intent-workspace) is 16/16 green with a production build. DraftEditor now supports ring_native/qtree_native/tree4_native/fly_native (radix/levels read-only, router knobs editable) and GEC express partition knobs gated on mode; FlowOptimize confirms before discarding dirty manual edits when switching refinement method. Remaining review finding: GEC mesh mode hides express knobs by design (nulled on switch).
- New permanent Python tests: tests/test_catalog_refinement_rtl.py (6 tests) prove parameter proposals keep workload/agents/compute/physical/family, refuse family/VC/cross-input changes and unbounded shapes, refuse shared-wire RTL substitution, and exercise a controlled local model server end-to-end through /ai-parameter-search plus adoption and selection survival. Combined with test_topology_search.py: 29 passed (17.73s).
- apps/studio/prototype/README.md and DESIGN.md now describe the actual six steps, the catalog campaign, selection evidence rules, parameter-only AI mode and the explicit limits of RTL export.
- New API/backend modules: product/catalog_evaluation.py, product/rtl_export.py; new UI components CatalogCampaign.tsx and FinalDelivery.tsx. General final RTL is explicitly unavailable: existing emitter's fixed 64-bit/2-VC/free-escape packet/router semantics do NOT implement arbitrary compiled NoC parameters. Only a consented topology-only preview with actual emitter output/lint is exposed; do not upgrade this to final RTL.
- Scratch verification plan and screenshots: /tmp/srota-thorough-check and /tmp/flow-*.png. A not-yet-wired custom trace generator prototype is being moved to scratch; don't treat it as implemented.

## Open questions / factual limits
- Full catalog ASTRA-SIM coverage must be measured/discovered; cannot promise every native BookSim research config is supported by ASTRA's product adapter.
- Whether ASTRA timing should use supplied/profiled compute durations; missing compute stages must prompt for input or be explicitly network-only, never invented.
- RTL coverage for Srota/shared-wire fabrics and derived VC counts must be checked against the actual emitter, not assumed from JSON export availability.

## Active blocker — compiled GEC credit preview (2026-11-09)
- Small 36-router attempt 1 OOMed in FIRRTL `ConvertAsserts` with the runner's 3-GiB heap / 4-GiB cgroup (335.1 s; no RTL/report).
- Attempt 2 enabled `veritx.synthesize` only during emission and routed preview checks through `SynthAssert`; it still OOMed in FIRRTL `RemoveVerificationStatements` (310.9 s; no RTL/report).
- Falsified assumption: custom assertion elaboration was the dominant memory cost. Assertion elision alone did not fit the full FIRRTL structure under the original cap.
- Optimization: emitted RTL now omits diagnostic-only top ports while the test keeps them. Scala + test compilation passed; the compile-only receipt is `execution/credit-gec-v5-opt/runs/compile-1/receipt.json`.
- Replaced the nested lane×slot conditional writes with per-lane payload/slot selection and per-output one-hot muxing from switch-allocation grants; slot reservations now use one-hot decode. Added a 2-input/2-output/2-VC routing regression.
- JDK 17 standalone router suite: **24 passed**, including the new simultaneous-output case.
- Fresh immutable 36-router/5-VC/72-wire snapshot `credit-gec-v6-mux-select` successfully emitted 28,640,272 bytes of Verilog under the approved 8-GiB cgroup / 6-GiB JVM policy. FIRRTL `ConstantPropagation` no longer blocked RTL emission in this run.
- Measured expansion: 36 routers, 32 endpoints, 72 shared wires with 360 taps, 5 VCs, 392 input ports / 392 output tap ports, 1,960 input-VC lanes and 1,960 output-VC slots. The old nested loop visited 106,800 lane×slot pairs (up to 3,025 at one router). Emitted RTL is 28,640,272 bytes; simulation FIRRTL is ~93.6 MB and SystemVerilog ~37.5 MB.
- Isolated Verilator frontends pass on both the emitted RTL and the larger simulation RTL (237 C++ files / 251.1 MiB generated). The test body has not yet been reached on failing full runs.
- Direct single-job C++ compilation of the earlier generated model hit the 8-GiB cgroup OOM. On the newer diagnostics-off/assertions-on snapshot, a direct `-O0` build compiled all generated C++ objects; its standalone link failed only because the probe harness lacked `main` (not a ChiselTest pass).
- At the 8-GiB cap, the full ChiselTest still OOMed: the 6-GiB-heap run OOM-killed Java while Verilator was active; a 4-GiB heap run OOM-killed both Java and Verilator. At 3 GiB, Java exhausted heap in FIRRTL `CInferMDir`; at 2 GiB, it exhausted heap in Chisel FIRRTL `Converter`.
- With the operator-approved 12-GiB cap (6-GiB JVM heap, one job), the unchanged 36-router baseline passed the full Verilator test: all endpoint pairs, stalls, contention drain, and reset checks. Receipt: `execution/credit-gec-v18-baseline-12g/runs/attempt-1/receipt.json`; JUnit report records 1 test, 0 failures. The runner needed a local GCC wrapper to supply Verilator's missing `.fast`/`.slow` PCH header aliases.
- The successful baseline emitted 32,800,616 bytes of simulation SV. Two source-level selector-sharing experiments both increased emitted SV (about +3.7% and +2.0% versus their saved baseline artifact), so both were discarded; `CreditRouter.scala` is restored to its pre-experiment version.
- The 36-router simulation result is now established. Keep the 81-router job gated; no 81-router, synthesis, placement, or PPA pass is claimed.

- Exact-address fixes: DraftEditor now reuses agentMap BigInt parsing and exact JSON wire values for base/size instead of safe-Number-only `reqInt`; legacy AgentFabricMap session snapshots now use the same exact conversion and reject unsafe Number snapshots rather than silently rounding. Browser command `cd apps/studio/prototype && ../node_modules/.bin/playwright test tests/backend-hardening.spec.ts --grep "fabric draft" --reporter=line` exited 0: 2 passed (7.1s), including high address 9223372036854788153; backend `AddressRange` parsed the same value exactly. Full backend-hardening spec plus `tsc --noEmit` completed exit 0 (task be7fcb1c0): 23 browser tests passed (58.5s), typecheck clean. After snapshot fix, pinned full Vitest passed 322/322 tests across 49 files (task b8dafed49); the focused BigInt suite passed 8/8; TypeScript and `git diff --check` passed. Added a Playwright regression restoring a legacy session snapshot containing `9223372036854788153`; focused Playwright passed 1/1 (4.6s).
- Prior blocking Java PIDs 22869/27063 are gone. Selected-project emit retry into `execution/runs/credit-gec-selected-v3-emit/attempt-2` (task bb455f1f2) exited 2: receipt confirms BLOCKED before execution, reason `foreign heavy process detected`. Two concurrent Verilator project-top builds (PIDs 335835, 337109, with child make/compiler processes) occupied the machine. Java jobs ending did not establish a clear heavy queue. Keep safety preflight unchanged; no RTL qualification claimed. Subsequently verified both blocking Verilator PIDs had ended and submitted attempt-3 (task babfe104e) through the same runner; exit 2, receipt again BLOCKED before execution: a new Verilator build PID 350467 and make PID 350473 with compiler children appeared. Three attempts have been blocked by competing heavy jobs, not RTL compiler errors. Stop manual retries. A bounded scheduler (`b28707ffb`) now invokes only the same private runner up to 20 times, waiting 20s only after receipts specifically report `foreign heavy process detected`; each attempt has a distinct preserved receipt, and it stops on any other outcome. (Attempt-3 receipt now available at `execution/runs/credit-gec-selected-v3-emit/attempt-3/receipt.json`; preflight saw Verilator PID 350467, make 350473, compiler children.) Receipt: `execution/runs/credit-gec-selected-v3-emit/attempt-3/receipt.json`. Pinned release/workload/address/Chipyard contract suite task b5ed17f00 completed exit 0: 27 passed in 8.63s; pytest warned that config option `timeout` is unknown (timeout plugin unavailable). This proves source/contracts, not simulated RTL or placement.
- Executing `RTL-FINAL-CLOSEOUT-PLAN.md`: created `docs/product/RTL-FINAL-CLOSEOUT-STATUS.md` with current phase dispositions, the pinned project identity, safe heavy-job state and live tree inventory (2,665 entries; no cleanup/stage/commit). Step 1 remains OPEN until the active scheduler terminates and P0–P11 evidence reconciliation is reviewed.
- Step 8 first code fix: `scripts/complete_design.py` now derives the single-project hardware family from the existing `_family_id_from_topology` owner and refuses unknown/mismatched family labels instead of silently defaulting the selected GEC request to mesh. `tracks/t3-topology/dse/tests/test_complete_design.py`: 15 passed; `py_compile` and `git diff --check` passed. This proves exact dispatch only, not selected GEC generation.
- Completion-runner gate hardening: `hardware_evidence_status` requires lint PASS, sim PASS and nonempty all-true boolean scenarios; missing verdicts BLOCK and failed evidence FAIL. Requested `--with-physical` now records `DESIGN_BOUND_PHYSICAL_RUNNER_NOT_WIRED`/BLOCKED because the old fixed LibreLane spike is not the generated design. Both single-project and `--release` now include the required physical stage (NOT_RUN unless requested; BLOCKED because no generated-design runner exists), and only manifest result `PASS` returns process success. The fourteen-family matrix uses the same strict lint/sim/nonempty all-true-scenario gate and stores hash-pinned logs per family. Removed the torus-backed KNCube substitution; until general KNCube intent/equivalence exists, its row is explicitly BLOCKED. Focused `test_complete_design.py`: 43 passed; py_compile and diff-check clean. Composed-slice/family and GEC MECS/hybrid/SROTA Verilator and Icarus calls now stream stdout/stderr directly to separate files as they run (plus combined logs), so a timeout/interruption does not depend on an in-memory capture; timeout output is covered by tests. the outer completion manifest records every log path, byte count and SHA-256, and runner exceptions are retained in `hardware/runner-error.log`. This prevents false green and preserves diagnostics; P9 is still unimplemented.
