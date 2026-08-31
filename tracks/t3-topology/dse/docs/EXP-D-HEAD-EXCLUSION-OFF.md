# Experiment D: Disable Head-Exclusion Admission Control

**Agent:** D  
**Date:** 2026-08-23  
**Baseline:** commit ea6f74a  
**Build:** `gen_rtl.py --anynet .noc_p0/mesh_4x4.anynet --outdir <dir> --buf 8 --block-k 8`

## What was changed

Removed the head-exclusion clause from the admission control (both network ports and LOCAL port):

```diff
-  assign in_ready_all[p] =
-      (effective_esc ? q_cnt[p*NUM_VCS + 1]
-                    : q_cnt[p*NUM_VCS + 0]) < BUF_DEPTH &&
-      (!is_head(in_flit_all[p]) ||
-       ((effective_esc ? q_cnt[p*NUM_VCS + 1]
-                       : q_cnt[p*NUM_VCS + 0]) == 0));
+  assign in_ready_all[p] =
+      (effective_esc ? q_cnt[p*NUM_VCS + 1]
+                    : q_cnt[p*NUM_VCS + 0]) < BUF_DEPTH;
```

This removes the requirement that head flits can only enter an **empty** VC queue. Now any flit (head or body) can enter any VC as long as the queue isn't full (`< BUF_DEPTH`).

## Results

### Full IR sweep (seed=42)

| IR | Baseline (head-excl ON) | EXP-D (head-excl OFF) | Δ |
|---|---|---|---|
| 0.001 | PASS (221 inj) | PASS | — |
| 0.005 | PASS (975 inj) | PASS | — |
| 0.01 | **40 stuck** (810 inj) | PASS | **fixed** |
| 0.015 | **33 stuck** (696 inj) | PASS | **fixed** |
| 0.02 | **47 stuck** (780 inj) | PASS (3892 inj) | **fixed** |
| 0.04 | **43 stuck** (494 inj) | PASS (8001 inj) | **fixed** |
| 0.06 | **49 stuck** (322 inj) | PASS (11965 inj) | **fixed** |
| 0.065 | **48 stuck** (590 inj) | PASS (12898 inj) | **fixed** |
| 0.07 | **55 stuck** (327 inj) | PASS (13768 inj) | **fixed** |
| 0.075 | **44 stuck** (331 inj) | PASS (14743 inj) | **fixed** |
| 0.08 | **45 stuck** (298 inj) | **222 stuck** (3910 inj) | baseline worse |
| 0.10 | **44 stuck** (254 inj) | **229 stuck** (2878 inj) | baseline worse |
| 0.12 | **54 stuck** (410 inj) | **224 stuck** (2127 inj) | baseline worse |
| 0.15 | **43 stuck** (2169 inj) | **228 stuck** (1622 inj) | baseline worse |

### Determinism

Both configurations are **seed-independent** — same stuck count regardless of NOC_SEED (tested 1, 7, 13, 42, 99, 123, 256, 1000). The deadlock is structural, not traffic-pattern-dependent.

### Deadlock threshold

| Configuration | Threshold | Notes |
|---|---|---|
| Head-exclusion ON (baseline) | IR ≈ 0.008 | Between 0.005 and 0.01 |
| Head-exclusion OFF (EXP-D) | IR ≈ 0.078 | Between 0.075 and 0.08 |

**Disabling head-exclusion raises the deadlock threshold by 10×.**

## Analysis

### Why head-exclusion causes deadlock at low IR

Head-exclusion says: "a head flit can only enter a VC queue if that queue is **empty**."

At any non-trivial injection rate, this creates a vicious cycle:

1. A head flit enters VC0 at router R, queue becomes non-empty
2. The head is routed to router S, but S's VC0 is occupied → head blocked
3. Meanwhile, body/tail flits of the same packet are backpressured to R
4. R's VC0 holds flits → new heads targeting R from other ports are blocked
5. Cascading HOL blocking: packets that need to traverse R are permanently stuck

The key insight: **the empty-queue requirement is too strict for a mesh topology** where multiple packets must share VCs. The 4x4 mesh has 16 routers × 2 VCs = 32 queues, but 240 possible source-destination pairs. At IR > 0.008, enough queues are non-empty that head admission becomes permanently blocked for some packets.

### Why higher IR makes baseline injection stall early

The baseline injects only 298 packets at IR=0.08 (vs 3910 for EXP-D). The head-exclusion blocks injection early because the testbench's `in_ready` deasserts when the queue is non-empty and the arriving flit is a head. All local injection ports stall, the network freezes with most queues still empty.

### Why EXP-D fails at IR ≥ 0.08

Without head-exclusion, multiple packets can interleave into the same VC queue. The `rt_alloc`/`rt_out` state machine then tracks only ONE active reservation per VC, but TWO packets are present. The second packet follows the first packet's route, ejecting at the wrong destination. This is the interleaving hazard that head-exclusion was designed to prevent.

At low IR, the probability of actual interleaving is low (queues are mostly empty), so the router works correctly. At high IR, interleaving becomes inevitable and causes route corruption.

## Conclusion

**Head-exclusion is both the problem and the (partial) solution:**

1. **Without head-exclusion:** Network works at low IR but fails at high IR due to interleaving
2. **With head-exclusion:** Network fails at ALL useful IRs due to premature HOL blocking

The correct fix is **neither** extreme:
- Head-exclusion is necessary to prevent interleaving (wormhole invariant)
- But the current implementation is too aggressive — it blocks ALL heads when ANY flit is in the queue

**The real fix must be more nuanced:** reserve the VC for the packet (using `rt_alloc`), and only block NEW heads from the same source (not all heads). Or: use per-packet VC allocation instead of per-queue exclusion.

## Branch

```bash
git checkout exp-d-no-head-excl  # commits on top of ea6f74a
```

## Reproduction

```bash
# Baseline
git checkout ea6f74a
python3 tracks/t3-topology/scripts/rtlgen/gen_rtl.py \
  --anynet .noc_p0/mesh_4x4.anynet --outdir /tmp/m4_baseline \
  --buf 8 --block-k 8
cd /tmp/m4_baseline && make -j4
NOC_IR=0.02 NOC_SEED=42 ./obj_dir/Vnoc_top  # → 47 stuck

# EXP-D (head-excl disabled)
git checkout exp-d-no-head-excl
python3 tracks/t3-topology/scripts/rtlgen/gen_rtl.py \
  --anynet .noc_p0/mesh_4x4.anynet --outdir /tmp/m4_expd \
  --buf 8 --block-k 8
cd /tmp/m4_expd && make -j4
NOC_IR=0.02 NOC_SEED=42 ./obj_dir/Vnoc_top  # → PASS (0 stuck)
```
