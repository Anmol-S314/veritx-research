# Calibration — three-way table (BookSim leg vs analytical leg vs textbook)

All rows produced by `veritx topology diff` (TopologyIR v0) unless noted.
Reproduce any row: `python3 -m veritx_dse.cli topology diff --ir <ir> --ets <base> …`
from `tracks/t3-topology/dse`.

## Row 1 — mesh8 calibration leg (single-leg, 2026-09-16)

* Workload: ASTRA `all_gather/8npus_1MB` (8 ranks × 1 MB ring all-gather)
* Fabric: 8-node 1-D mesh (`mesh8.cfg`, DOR), flit 64 B
* Result: **119,080 cycles all ranks, exposed = wall** (pure comm, no overlap)
* `[plat] packets=56 avg=16396 min=16393 p50=16393 p95=16417 max=16417 hops_avg=2.75`
* Textbook check: 8 ranks × 7 steps = 56 packets ✓; per-chunk 16,384 flits +
  ~12 cycles header/hop ✓; pipelined ring wall ≈ 7 × ~17k ≈ 119k ✓
* Serialization share: 16,384/16,393 = **99.9%** (near-contention-free — free validation)
* Calibrated wire latency: **L_wire = min − serialization = 16,393 − 16,384 = 9 cycles**

## Row 2 — ring8 diff (same overlay both sides, 2026-09-16)

* IR: `ring8` (ring/8, link_attrs 64 GB/s, 9 ns — calibrated from Row 1)
* Workload: same 8×1 MB all-gather; `booksim=119,080c analytical=106,949c`
* **Divergence 10.19% → close.** This is the backend-fidelity signal: same
  overlay, calibrated params, order-of-magnitude smaller than Row 3.
* NOTE: booksim wall equals Row 1 exactly (119,080). Same ETs/system; the
  1-D torus wrap only shortens the single 7→0 chunk, which the pipeline
  absorbs. Recorded as measured, not deduplicated.

## Row 3 — diffmesh16 (topology mismatch, 2026-09-16)

* IR: mesh 4×4/16 (`link_attrs` 50 GB/s, 500 ns — ASTRA-example defaults, UNCALIBRATED)
* Workload: `tests/fixtures/astra_tiny/one-coll.et` (16 ranks, small collective)
* `booksim=50,310c analytical=35,340c` → **29.76% diverge** (verdict correct)
* Decomposition (analytical sweeps, same ET):
  * BW 50→64→128 GB/s: 35,340 → 35,310 → 35,310 — bandwidth irrelevant
    (latency-dominated small collective).
  * LAT 500→100→10→5 ns: 35,340 → 23,340 → 20,640 → 20,490 —
    **30 cycles/ns = 2×(16−1) ring steps**, floor ≈ 20,340.
  * ~15,000 of the analytical 35,340 (500 ns × 30 hops) is the uncalibrated
    default. At measured L_wire = 9 ns the leg reads ≈20,610 — honest
    divergence vs booksim ≈ **59%**, not 29.76%. The reported number was
    flattered by two errors partially canceling (inflated analytical latency
    vs mesh overhead on the booksim side).
  * Remaining structural gap: 4×4 mesh (diameter 6, DOR, contention,
    endpoint-delay 10, router pipeline) vs ideal single-hop ring overlay.
    v0 maps mesh→Ring by design; closing this needs calibrated link_attrs
    (Row 1 numbers) + same-overlay comparisons (Row 2 pattern).

## Row 4 — torus8 diff (reproduces Row 2 bit-identically, 2026-09-16)

* IR: `configs/topology/torus8.topo.json` (kind torus, k=8 n=1, calibrated
  link_attrs 64 GB/s / 9 ns); same 8×1 MB all-gather ETs; run dir
  `results/topology-diff/20260916_195439_seed8680657/`.
* `booksim=119,080c analytical=106,949c` → **10.19% close — identical to Row 2
  to the cycle.** Expected, and now verified: `topology_ir.to_booksim_cfg`
  maps ring AND torus 1-D to `topology = torus` (BookSim has no ring), so
  Row 2 (ring8) and this row are the same BookSim config. Cross-kind
  consistency + run-to-run determinism, both measured.
* Torus plat signature (vs Row 1 mesh): `avg=16394 uniform, hops 2/2/2` —
  every packet takes the wrap-shortened 2-hop path, and per-packet latency is
  dead flat (no p95 tail). Mesh shows 2.75 avg hops with a 16393–16417
  spread. Same wall, different fabric — the [plat] profile is what tells them
  apart.
* **input_speedup sensitivity (protocol knob, recorded):** this morning's
  hand-written torus cfg (same k/n/routing, `input_speedup = 2`, ps=64/cd=2)
  measured **133,080 cycles / avg 18441** — 11.8% slower than the harness
  template's `input_speedup = 1`. Re-run through the harness config with
  ps=64/cd=2 still gives 119,080, isolating input_speedup as the differing
  variable. Mesh8 is invariant to it (119,080 under both). On a saturated
  1-D ring, deeper per-node injection changes drain behavior; on mesh the
  extra ports go unused. Any torus-vs-mesh wall-time claim must pin
  input_speedup first.
* Also explains the two mesh8 diffs in results/ (14:37 vs 14:41): the 14:37
  run used uncalibrated IR attrs (50 GB/s / 500 ns) → analytical 140,297;
  the 14:41 run used calibrated attrs (64 / 9) → analytical 106,949. Booksim
  leg bit-identical (119,080) both times — analytical-only sensitivity,
  consistent with Row 3's decomposition.

## Lesson for translator defaults

Never ship example-derived performance numbers as IR defaults. `link_attrs`
must come from measurement (Row 1 protocol: time baseline → L_wire = min −
serialization), and cross-topology diffs must be read as
topology-mismatch + backend-fidelity compounded — same-overlay rows (Row 2)
isolate the backend term.
