# Golden Model: Cycle-Accurate 2-VC NoC Router

## Status: Model is WIP — link-transfer logic needs rewrite

## What was proven (via RTL experiments)

These results are **validated against Verilator RTL** and are reliable:

### Admission gate comparison on mesh_4x4 (buf=8, block-k=8)

| Gate | mesh_4x4 IR=0.08 | mesh_4x4 IR sweep |
|---|---|---|
| **empty_queue** (5933b88) | **PASS** (12313 inj, 0 stuck) | PASS at all IRs |
| **rt_alloc** (on 5933b88) | 88-109 stuck | FAIL at all IRs |
| **capacity** (EXP-D) | 222 stuck at IR≥0.08 | PASS at IR≤0.075 |

### Key insight

**Empty-queue is CORRECT and NECESSARY for wormhole deadlock freedom.**

The rt_alloc gate is too loose because `rt_alloc` is set on GRANT (forward out), not on ADMISSION (queue in). Between admission and grant, there's a 1+ cycle window where a head enters the queue but `rt_alloc=0`, allowing a second head → interleaving → route corruption.

### Root cause of ea6f74a regression

The `begin : esc_stage` block uses `evc_fwd = esc_stage_vc[p3]` which initializes to 0 at reset. This makes the escape stage look at slot 0 (the free stage's slot), causing a double-dequeue race. Fix: `esc_stage_vc <= 1` at reset.

## Model approach

The model should verify these findings on small topologies (2x2, line_4) where
RTL runs are fast. The link-transfer model needs to correctly handle:
1. Flit-at-a-time acceptance (in_ready gate)
2. Credit return on acceptance
3. Output-stage backpressure (held flits)
4. Dequeue-aware enqueue (S3b race path)

Current model bugs:
- Link transfer is unconditional (should check destination admission gate)
- Credit return timing is off
- Ejection doesn't properly account for LOCAL output stage occupancy

## Files

- `tracks/t3-topology/scripts/golden_model.py` — model (WIP)
- `tracks/t3-topology/docs/EXP-D-HEAD-EXCLUSION-OFF.md` — EXP-D results
- `tracks/t3-topology/docs/EXP-D-RT-RESULTS.md` — EXP-D-RT results
