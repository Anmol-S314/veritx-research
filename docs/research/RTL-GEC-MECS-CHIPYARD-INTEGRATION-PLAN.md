# GEC-MECS Chipyard RTL integration

**Superseded scope:** an earlier source-only request paused compilation. The current operator request authorizes RTL compilation and qualification, but only through the existing capped private runner. The historical source-only work remains documented in `RTL-ALL-14-SOURCE-DELIVERY.md`; no preview is full qualification.

**Goal:** Emit and simulate a Chipyard topology/routing preview for the finalized Mixtral revision (81 routers, 8 VCs, 162 shared wires), without changing its workload or revision. Full compiled-router equivalence remains a separate gate.

## Execution update

- Added `product/chipyard_gec.py`: validates deterministic compiled routes, binds route port IDs to physical wire IDs by source/tap, and exports the packet layout, endpoint map, VC assignment and router contract without dropping provenance.
- Added `rtl/chipyard/CompiledGecPreview.scala`: Chisel queues, shared-resource buses and endpoint interfaces; no independent per-tap point-to-point substitution.
- Preview limitations are explicit: SINGLE-flit unicast, per-router VC queues, round-robin and ready/valid, not the compiled per-input credit/iSLIP/packet-reservation pipeline. Final readiness must remain false.
- Python bridge check: `PYTHONPATH=tracks/t3-topology/dse python3 -m pytest -q tracks/t3-topology/dse/tests/test_chipyard_gec.py` → 3 passed (6.25s); existing pytest timeout-option warning.
- Selected contract hash: `01a8df769eef50c9cc95157100f354481c8a0a822a1a7ef34053819c88938259`.
- Emission uses existing `execution/private_runner.py`, job `gec-selected-r02-emit`. `runs/emit-1` failed at Scala compilation: `Method too large: veritx/chipyard/SelectedGec$.<clinit> ()V`. Split route constants into one method per router (contract hash unchanged); Python checks remain 3 passed. Same capped runner retry launched in `runs/emit-2`.
- `runs/emit-2` was BLOCKED before compilation (runner exit 2): `foreign heavy process detected`. Receipt captured concurrent `tb_project_top` and `tb_gec_hybrid16_fabric` Verilator/make/compiler processes. One deliberate ownership inspection confirmed PID 844499 (Verilator) and PID 844517 (make), parent shell 844497, still building `/tmp/opencode/obj_hybrid`. No foreign process was killed and no safety gate was bypassed.
- Resume only after the foreign compiler owner releases the heavy-execution slot. Reuse `jobs/gec-selected-r02-emit.json` through the same private runner with a new `runs/emit-3` directory; then inspect its receipt before launching prepared Verilator build and simulation jobs.
- Worktree is dirty and preserved; repository `/home/datavex/bruh/veritx-research`, branch `integration/studio-reconciliation`, HEAD `7b124cc5`. New files: `product/chipyard_gec.py`, `tests/test_chipyard_gec.py`, `rtl/chipyard/CompiledGecPreview.scala`, `rtl/chipyard/make_testbench.py`. Original Chipyard and candidate source files are unchanged; new source directory and target are separate. No generated RTL or successful simulation is claimed.
- Added a self-checking Verilator testbench generator for all endpoint pairs, concurrent same-sink traffic, exact payload/VC checking, backpressure stability, duplicate detection and drain.

## Plan critique

The prior plan conflated a topology preview with a full router implementation. The minimal useful deliverable is the explicitly limited preview above. No product support gate is widened merely because files exist; generation and simulation evidence must be inspected first. The remaining full-equivalence work below is not claimed by this preview.

## Evidence and plan

1. **Pin the contract and identify the integration seam.** Confirm the active revision, evaluated run, compiled topology/VC/wire facts, and whether existing Chipyard GEC-MECS output matches. **Check:** gateway records show the pinned revision and run; exporter parameters are compared against it.
2. **Implement a fail-closed compiled-contract bridge.** Carry router/link/shared-group identity, routes, VC legality, packet/control parameters into Chipyard; reject any missing or lossy field before RTL output. **Check:** round-trip manifest tests compare every field to the compiled artifact and reject deliberate mismatches.
3. **Connect shared-channel scheduling and the actual NoC top.** Preserve one physical resource per shared wire and its arbitration/credit behavior; do not expand into independent point-to-point links. **Check:** elaboration inventories match 81 routers, 162 shared resources and 8 VCs.
4. **Prove emitted design behavior against the selected contract.** Run focused RTL tests/simulation and the existing private runner with resource preflight. **Check:** test results and artifacts are tied to the pinned revision/manifest; lint alone is insufficient.
5. **Publish only evidence-backed readiness.** Save generated RTL and provenance, then refresh the gateway preview/readiness. **Check:** the product reports a connected preview only after all preceding gates pass.

## Current state

- Active revision: `p-fd7e5e31be77-r02`; draft design hash: `sha256:ab7bce8f71b5ed4fde4101ee80a60b6c69c16989d966f0f9096dd6d76ad392f0`.
- Confirmed contract: `gec_mecs`, 9x9 / 81 routers, 8 VCs, 162 shared wires.
- One user-authorized evaluation completed: job `job-5d42f6f3b6f6`, run `01a1c035-fc58-7c76-8f83-3115fd39bdd1`, status `EVALUATED`.
- Existing Chipyard `CatalogRtlGecMecsExport` is a different fixed profile (16 routers, 96 links, 6 VCs); it cannot be used as the selected revision's emitter.
- No RTL preview has been submitted or represented as qualified.
