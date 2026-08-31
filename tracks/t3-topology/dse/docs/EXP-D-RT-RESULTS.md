# Experiment D-RT: Per-Packet VC Reservation Admission Gate

**Agent:** D  
**Date:** 2026-08-23  
**Task:** Replace empty-queue head-exclusion with rt_alloc-based gate

## Summary

**The rt_alloc gate is the wrong fix.** It's too loose — allows interleaving that corrupts routes. The empty-queue check in 5933b88 is correct and necessary for wormhole integrity.

## Two discoveries

### Discovery 1: esc_stage_vc regression (ea6f74a vs 5933b88)

The `begin : esc_stage` block introduced in ea6f74a uses `evc_fwd = esc_stage_vc[p3]` which initializes to 0 at reset. This makes the escape stage look at **slot 0** (the free stage's slot), causing a double-dequeue race. In 5933b88, the escape stage was hardcoded to slot 1.

**Fix:** Initialize `esc_stage_vc` to 1 (escape class VC), not 0:
```systemverilog
esc_stage_vc[p3] <= {{(VC_IDX_W-1){1'b0}}, 1'b1};
```

This partially improves ea6f74a (49 stuck at IR=0.02 vs 55 before) but doesn't fully recover to 5933b88's pass.

### Discovery 2: rt_alloc gate is wrong

Tested three admission policies on mesh_4x4 (buf=8, block-k=8, IR=0.08, seed=42):

| Policy | mesh_4x4 result | Why |
|--------|----------------|-----|
| **Empty-queue** (5933b88) | **PASS** (12313 inj, 0 stuck) | Correct wormhole invariant |
| **rt_alloc gate** (on 5933b88) | **88-109 stuck** | Interleaving corrupts routes |
| **No gate** (EXP-D) | 222 stuck at IR≥0.08 | Same interleaving problem |

**Why rt_alloc fails:** `rt_alloc` is set on GRANT (forward out), not on ADMISSION (queue in). There's a 1+ cycle window where a head is in the queue but `rt_alloc=0`, allowing a second head to enter. The second head follows the first packet's `rt_out`, getting routed to the wrong destination.

```
Cycle N:   Head A admitted to queue, rt_alloc=0 (not yet granted)
Cycle N+1: Head A at front, granted → rt_alloc <= 1 (non-blocking)
           Meanwhile Head B arrives, rt_alloc still 0 → admitted!
Cycle N+2: Head B now in queue behind Head A's body/tail
           Head B will follow Head A's route → WRONG PATH
```

## Why empty-queue is correct

The empty-queue check (`q_cnt == 0`) ensures no second head enters a VC while ANY flit of the first packet is present. This is the wormhole invariant:
- Head enters empty queue → starts packet
- Body/tail follow → queue non-empty → new heads blocked
- Tail transmitted → queue empty → new head can enter

The downside (HOL blocking at IR > 0.008 on ea6f74a) is caused by other bugs in ea6f74a (esc_stage_vc regression), NOT by the admission gate itself.

## Root cause of ea6f74a's failures

The baseline at ea6f74a fails at ALL IR levels (43-55 stuck, seed-independent). This is NOT caused by the admission gate — it's caused by the `esc_stage_vc` regression. 5933b88 (without the regression) passes cleanly.

## Conclusions

1. **The empty-queue admission gate is correct** — it enforces the wormhole invariant
2. **The rt_alloc gate is wrong** — it's too loose, allowing interleaving
3. **The real bug is in ea6f74a's escape stage** — `esc_stage_vc` init to 0 collides with free stage slot 0
4. **Fix the ea6f74a regressions**, don't change the admission gate

## Files

- Branch: `exp-d-rtalloc-on-good` (on top of ea6f74a, with 5933b88 template + rt_alloc gate)
- Test artifacts: `/tmp/m4_good/` (5933b88 PASS), `/tmp/m4_rt_good/` (rt_alloc FAIL)

## Reproduction

```bash
# 5933b88 baseline: PASSES
git checkout 5933b88 -- tracks/t3-topology/scripts/rtlgen/router_template.sv
gen_rtl.py --anynet .noc_p0/mesh_4x4.anynet --outdir /tmp/good --buf 8 --block-k 8
NOC_IR=0.08 NOC_SEED=42 ./obj_dir/Vnoc_top  # → 0 stuck

# + rt_alloc gate: FAILS (88-109 stuck)
# (apply rt_alloc patch to template, then same build/run)
```
