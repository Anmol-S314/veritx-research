# Liveness Fix Analysis: 64-Node Freeze Root Cause and Solutions

## Date: 2026-08-23

## Executive Summary

The 64-node RTL liveness freeze (FAIL at IR≥0.04, PASS at IR=0.02) is caused by a **fundamental architectural flaw**: the `show_vc` mux gives VC1 (escape) priority on ALL output ports, creating a hidden dependency where a VC1 flit held in the output stage while `show_vc` points to VC0 is invisible to downstream but occupies the stage, blocking VC0 progress.

Two fix approaches have been prototyped:

| Approach | 4-node | 16-node | Architecture |
|----------|--------|---------|-------------|
| Force-show (single wire) | PASS all IRs | FAIL 42 stuck @IR 0.04/0.08 | Band-aid on flawed arch |
| Dual-port (independent VCs) | Builds, TB wrong_dst | Not tested | Correct Dally/Duato |

**Recommendation**: Debug the dual-port approach (it's architecturally correct), then scale to 64-node.

## Root Cause Detail

### The show_vc Mux Problem

```
// Current: shared wire, show_vc selects which VC is visible
assign n_out_flit[p]  = out_flit_all[p][show_vc[p]];  // VC0 or VC1, NOT both
assign n_out_valid[p] = out_valid_all[p][show_vc[p]];
```

When `show_vc[p] = VC1`:
- VC1's flit is on the wire → downstream can accept it
- VC0's flit is in `out_flit_all[p][0]` but INVISIBLE to downstream
- VC0's flit occupies the output stage → credit consumed but not returned
- VC0's queue can't dequeue (output stage occupied)
- VC0's grant can't fire (output stage occupied)

When `show_vc[p] = VC0`:
- VC1's flit is in `out_flit_all[p][1]` but INVISIBLE
- Same problem in reverse

The ESC_YIELD_K=4 guard tries to alternate, but creates a ping-pong:
- 4 cycles: show_vc=VC1, VC0 held invisible
- 1 cycle: show_vc=VC0, VC0 transmitted, VC1 held invisible
- Repeat: neither VC makes sustained progress

### Why 16-Node Fails but 4-Node Passes

At 4 nodes: low aggregate demand, enough slack for both VCs to drain during alternation.
At 16 nodes: moderate demand, escape tree root (r7) receives from 15 nodes → VC1 output stages fill faster than they drain → 42 packets permanently stuck.

## Fix 1: Force-Show (Single Wire)

### Design
Add per-output force-show counters. When a VC's output stage holds a flit for > FORCE_SHOW_K cycles while `show_vc` points elsewhere, override `show_vc`.

### Results
- 4-node: PASS at all IRs (0.02-0.32) ✓
- 16-node: FAIL 42 stuck at IR 0.04/0.08 ✗
- 16-node: PASS at IR 0.02, 0.20, 0.32

### Limitation
The force-show mechanism alternates show_vc between VCs every ~2 cycles. Each VC gets ~50% wire time. But with single wire, each VC can only transmit 1 flit per 2 cycles. At moderate IR, this bandwidth is insufficient → packets accumulate → permanent stuck.

### Verdict
**Insufficient for 64-node**. The single-wire bandwidth is fundamentally limited to 1 flit/cycle total (shared between 2 VCs). The Dally/Duato escape class design requires independent resources.

## Fix 2: Dual-Port Architecture

### Design
Each VC gets its own independent input and output port per physical link:

```
// VC0 (free) — completely independent
input  [0:DEG-1] n_in_flit_free,  n_in_valid_free,  // from sender's VC0 output
output [0:DEG-1] n_out_flit_free, n_out_valid_free,  // to receiver's VC0 input
input  [0:DEG-1] n_out_ready_free,                   // from receiver's VC0 ready

// VC1 (escape) — completely independent  
input  [0:DEG-1] n_in_flit_esc,  n_in_valid_esc,
output [0:DEG-1] n_out_flit_esc, n_out_valid_esc,
input  [0:DEG-1] n_out_ready_esc,
```

### Advantages
- NO show_vc mux → NO cross-VC wire dependency
- Both VCs can transmit simultaneously (2 flits/cycle per link)
- Both VCs can receive simultaneously (2 flits/cycle per link)
- Correct Dally/Duato escape class architecture

### Current Status
- Router template: ✓ (compiles, builds)
- gen_rtl.py: ✓ (generates noc_top with dual VC wires)
- TB: ✓ (accepts ejections from both VCs)
- 4-node simulation: ✗ (25 wrong_dst — TB injection bug)

### TB Bug
The wrong_dst issue is likely in how the TB handles the dual input ports. The TB drives `local_in_valid` (single) which the router splits into VC0/VC1 based on esc bit. But the TB may be injecting the same flit into both VCs, or the route tables may be incompatible.

### Next Steps for Fix 2
1. Add trace events to the 4-node simulation to identify the wrong_dst source
2. Fix the TB injection/ejection logic
3. Verify route tables are correct for the dual-port architecture
4. Test on 16-node and 64-node

## FlooNoC-Inspired Fix (RECOMMENDED)

FlooNoC (ETH Zurich, TVLSI 2025) solves this exact problem with:

1. **Per-VC output FIFOs** — each VC has its own independent output buffer (not a shared output stage). A flit sits in the FIFO until its VC's turn on the wire. No "hidden hold" problem.

2. **Per-VC output arbiters** (`floo_wormhole_arbiter`) — each VC arbitrates among its input sources. Round-robin with wormhole lock (locks onto a VC for the duration of a packet).

3. **VC arbiter** (`floo_vc_arbiter`) — merges VCs onto the physical wire. Round-robin selection, credit-based flow control per VC.

4. **No show_vc mux** — the VC arbiter IS the wire selection logic, registered and fair.

### Why this works
- The output FIFO absorbs flits when the wire shows the other VC
- The VC arbiter guarantees progress for both VCs (round-robin)
- Wormhole lock prevents packet interleaving (correctness)
- Credit-based per-VC flow control prevents overflow

### Implementation plan
1. Add per-VC output FIFOs (depth 2-4) to each output port
2. Replace show_vc mux with registered round-robin VC arbiter
3. Add wormhole lock (track packet boundaries)
4. Keep per-VC credit tracking
5. Test on 4-node → 16-node → 64-node

## Recommended Path

1. **Implement FlooNoC-inspired fix** — per-VC output FIFOs + VC arbiter
2. **Test on 4-node, 16-node, 64-node**
3. **Update gen_rtl.py** to support the new architecture
4. **Integrate into production pipeline**

## Files Modified
- `tracks/t3-topology/scripts/rtlgen/router_template.sv` — dual-port router
- `tracks/t3-topology/scripts/rtlgen/gen_rtl.py` — dual-port noc_top generation
- `tracks/t3-topology/docs/LIVENESS-FIX-ANALYSIS.md` — this document

## Estimated Effort
- Debug dual-port TB: 1-2 hours
- 16-node validation: 1 hour
- 64-node validation: 2-3 hours
- Integration into production pipeline: 1 day
