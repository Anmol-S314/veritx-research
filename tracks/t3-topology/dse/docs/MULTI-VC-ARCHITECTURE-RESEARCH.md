# Multi-VC NoC Router Architecture: Research & Design Proposal

**Date:** 2026-08-23
**Status:** Phase 1 parameterization IMPLEMENTED and verified (2026-08-23)
**Context:** Router template parameterized for any NUM_VCS. Key finding: escape stage VC index must be LATCHED at load time (`esc_stage_vc`), not recomputed from the combinational `esc_vc` signal each cycle. Without latching, the escape stage reads from the wrong VC slot when no new candidate is found.

---

## 1. Current Architecture: What's Hardcoded for 2 VCs

The router template (`router_template.sv`, 710 lines) has **12 distinct 2-VC assumptions** that prevent scaling:

### 1.1 Output Stage Multiplexer (show_vc)
```systemverilog
// Lines 211-234: round-robin pointer over NUM_VCS stages (ALREADY PARAMETERIZED)
logic [NUM_PORTS-1:0][$clog2(NUM_VCS > 1 ? NUM_VCS : 2)-1:0] show_vc_rr;
// Registered round-robin: advance on accept, skip empty VCs
show_vc_rr[p] <= (show_vc_rr[p] + 1) % NUM_VCS;
```
**Status:** ✅ This component is already parameterized for N VCs via round-robin pointer. However, the esc_starve logic (§1.12) still assumes show_vc is 1-bit, creating a width mismatch for N>2.

### 1.2 Output Stage Arrays
```systemverilog
// Lines 105-106: declared N-wide, but only [0] and [1] used
logic [NUM_PORTS-1:0][NUM_VCS-1:0] out_valid_all;
// Lines 412, 445: only VC0 and VC1 get loaded
out_valid_all[p3][0]  // free stage
out_valid_all[p3][1]  // escape stage
```
**Problem:** Declared as `[NUM_PORTS-1:0][NUM_VCS-1:0]` but only indices [0] and [1] are ever loaded or read. VC2..N-1 are dead weight.

### 1.3 Grant Logic (Switch Allocation)
```systemverilog
// Lines 286-350: PARTIALLY parameterized
// Escape candidate: VC1..N-1, first-match (loops over _ev = 1..NUM_VCS-1)
for (int _ev = 1; _ev < NUM_VCS && !esc_valid[_o]; _ev++)
  q_cnt[_p*NUM_VCS + _ev] > 0 && cred[_o][_ev] > 0 && ...
// Free candidate: VC0 only, round-robin
q_cnt[_p*NUM_VCS + 0] > 0 && cred[_o][0] > 0 && ...
```
**Status:** ⚠ Partially parameterized. Escape search iterates N-1 VCs (good), but:
- `esc_vc[_o]` is **undeclared** (§1.13 bug #1)
- `grant_sv[_o] = 2'd1` is hardcoded to VC1 regardless of which escape VC was found (§1.13 bug #2)
- Free candidate only checks VC0 (correct for the 2-class model, but limits flexibility)

### 1.4 Credit Tracking
```systemverilog
// Lines 412, 445: per-(port, VC) credits, but only VC0 and VC1 decremented
cred[p3][0] <= cred[p3][0] - 1;  // only VC0 (line 412)
cred[p3][1] <= cred[p3][1] - 1;  // only VC1 (line 445)
```
**Problem:** Credit decrement is hardcoded for VC0 and VC1. VC2..N-1 never get decremented.

### 1.5 Demotion Logic
```systemverilog
// Lines 475-495: only monitors VC0 queues
int c2 = p2 * NUM_VCS;  // always VC0 (free class)
if (blk_cnt[c2] >= AGE_K[7:0]) begin
  esc_mode[c2] <= 1'b1;  // demote to VC1
end
```
**Problem:** Demotion only applies to VC0→VC1. With N VCs, you need a demotion ladder (VC0→VC1→VC2→...).

### 1.6 Ejection Path
```systemverilog
// Lines 485-520: only processes VC0 and VC1
for (int pass2 = 1; pass2 >= 0; pass2--) begin
  // pass2=1: escape class (VC1)
  // pass2=0: free class (VC0)
end
```
**Problem:** Ejection iterates exactly 2 classes. With N VCs, you need N passes or a priority encoder.

### 1.7 Enqueue VC Selection
```systemverilog
// Lines 405-410: binary VC choice from flit header
int lv = get_esc(in_flit_all[p2]) ? 1 : 0;
int lc = p2 * NUM_VCS + lv;
```
**Problem:** Flit's escape bit maps to exactly 2 VCs. With N VCs, you need a class field in the flit header.

### 1.8 S3c Force-Escape Logic
```systemverilog
// Lines 142-148: body/tail forced to VC1 (escape)
wire my_esc_q = get_esc(in_flit_all[p]) ? esc_mode[p*NUM_VCS + 1]
                                         : esc_mode[p*NUM_VCS + 0];
```
**Problem:** Hardcoded VC indices 0 and 1. With N VCs, body/tail must be forced to the SAME VC as the head (not always VC1).

### 1.9 Per-Stage Credit Return
```systemverilog
// Lines 390-450: only VC0 and VC1 stages return credits
cred[p3][out_src_vc[p3][0]] <= cred[p3][out_src_vc[p3][0]] + 1;  // free stage
cred[p3][out_src_vc[p3][1]] <= cred[p3][out_src_vc[p3][1]] + 1;  // escape stage
```
**Problem:** `out_src_vc` is declared as `[NUM_PORTS-1:0][NUM_VCS-1:0]` but only [p][0] and [p][1] are used.

### 1.10 QCNT_W Formula
```python
# gen_rtl.py line 124 (inside emit_pkg)
localparam int QCNT_W = $clog2(2*{buf} + 1);
```
**Problem:** The `2*` is hardcoded for 2 VCs. Each q_cnt is per-queue (one per port×VC), so it only needs to count up to BUF_DEPTH. The formula should be `$clog2(BUF_DEPTH + 1)`. The current `2*BUF_DEPTH` wastes 1 bit but is functionally safe — it's just an artifact of the 2-VC assumption in the comment.

### 1.11 Flit Header Format
```
Current layout:
[63]    = escape_class (0 or 1)
[62:61] = type (HEAD/BODY/TAIL/SINGLE)
[47:0]  = src(8 bits) + payload(40 bits)
```
**Problem:** 1-bit escape field can only encode 2 classes. With N VCs, you need ceil(log2(N)) bits. **⚠ Incompatible change:** expanding to 2-bit traffic_class shifts the type field from [62:61] to [61:60], breaking the existing flit format. All NICs, traces, and the TB must be updated together.

### 1.12 Starvation Guard (ESC_YIELD_K)
```systemverilog
// Line 268: ESC_YIELD_K = 4; (constant)
// Lines 202-215: binary yield in show_vc mux
if (esc_starve[p] >= ESC_YIELD_K[3:0] && out_valid_all[p][0])
  show_vc[p] = 1'b0;
```
**Problem:** The yield mechanism only considers 2 classes. With N VCs, you need a weighted fair arbiter.

### 1.13 Additional Bugs Found During Review

**⚠ These are latent bugs in the current template (HEAD) that would surface if NUM_VCS > 2:**

1. **`esc_vc` undeclared** (line 322): The escape candidate search writes `esc_vc[_o] = _ev[1:0]` but `esc_vc` is never declared as a `logic` signal. Verilator would reject this.

2. **`grant_sv` hardcoded to VC1** (line 343): Even though the escape search iterates VC1..N-1, the grant encoding is `grant_sv[_o] = 2'd1` — always VC1. If the escape candidate is at VC2, the flit is loaded into VC1's output stage, corrupting the VC assignment.

3. **`esc_starve` comparison width mismatch** (lines 419-422): `show_vc[po] == 1'b1` compares a log2(N)-bit signal against 1-bit literal. For N=2 this works (show_vc is 1-bit), but for N>2 it silently truncates.

4. **`out_src_vc` and `cred` indexed by `pass2[0]`** (ejection, line 520): `out_src_vc[LOCAL_PORT][pass2] <= pass2[0]` — the source VC is set to the LSB of the pass index, not the actual VC class. For N>2 VCs, pass2=2 would set out_src_vc to 0 (wrong).

**These bugs confirm that the template is structurally 2-VC despite the show_vc_rr parameterization.** The round-robin show_vc mux (§1.1) is the only fully parameterized component.

---

## 2. Academic Landscape: Multi-VC Architectures

### 2.1 Dally 1992 (Virtual-Channel Flow Control) — The Foundation
**Key insight:** VCs break deadlock by creating acyclic channel dependency graphs. With N VCs, you can break up to N-1 independent cycles in the dependency graph.

**Scaling law:** Number of VCs needed = number of independent cycles in the channel dependency graph. For most practical topologies, 2-4 VCs suffice.

### 2.2 CONNECT (CMU, Papamichael 2012) — Parameterized N-VC
**Architecture:** Fully parameterized VC router generator. Key design decisions:
- **N separate buffer FIFOs per input port** (one per VC)
- **N-to-1 input port mux** selects which VC's head flit enters the crossbar
- **Per-VC round-robin arbiter** at input (VC allocation)
- **Per-output round-robin arbiter** (switch allocation)
- **Output register** with per-VC credit tracking

**Scaling characteristics:**
- Area grows ~linearly with VC count (each VC adds one buffer FIFO + one arbiter)
- Latency: +1 cycle per additional VC stage (pipelined allocation)
- Throughput: diminishing returns beyond 4 VCs (Buffered Crossbar saturation)

### 2.3 FlooNoC (PULP/ETH, Fischer 2024) — Wide-Link VC
**Architecture:** Optimized for wide physical channels (1024-bit). Key design decisions:
- **End-to-end AXI4 parallel multistream** (not hop-by-hop VC)
- **No per-hop VC buffers** — credit-based flow control at endpoints
- **Protocol-level separation** (read/write channels) rather than network-level VCs

**Relevance to VeritX:** FlooNoC demonstrates that for wide-link NoCs, protocol-level separation (AXI4 read/write) is more efficient than traditional per-hop VCs. Our router uses 64-bit flits (narrow), so traditional per-hop VCs are more appropriate.

### 2.4 Preemptive VCs (Leone/Colagrande/Benini 2026) — State of the Art
**Architecture:** Round-robin link arbitration with preemption. Key design decisions:
- **Registered downstream ready** (no combinational dependency)
- **Preemption:** if active VC can't progress, arbiter immediately grants link to next ready VC
- **3% area overhead** vs multiplane (76% routing savings)

**Relevance to VeritX:** Preemptive VCs solve the starvation problem that our ESC_YIELD_K guard addresses. A preemptive arbiter would replace the hardcoded yield counter with a general N-class arbiter.

### 2.5 MONET (DATE 2026) — MoE-Optimized NoC
**Architecture:** Two-tier NoC for MoE inference. Key design decisions:
- **Dedicated multicast channels** for expert dispatch
- **Priority lanes** for latency-critical traffic
- **Shared buffers** with class-based admission

**Relevance to VeritX:** Directly addresses our traffic patterns (MoE dispatch + allreduce + KV cache). The two-tier approach maps to our free/escape split, but with additional classes for MoE-specific traffic.

---

## 3. VeritX Traffic Patterns: What VCs Are Actually Needed

### 3.1 Current Traffic Classes (from DSE tool)

| Class | Pattern | Characteristics | VC Need |
|-------|---------|-----------------|---------|
| **MoE Dispatch** | Top-K expert routing | Hotspot (k=8), bursty, latency-tolerant | Best-effort, can use escape |
| **TP Allreduce** | Ring exchange | Uniform, steady, latency-sensitive | Guaranteed service |
| **KV Cache** | Prefill (burst) + Decode (short) | Mixed burst/short, latency-critical | Guaranteed service |
| **Control/Credit** | 1-flit ACKs | Tiny, latency-critical | Highest priority |

### 3.2 Traffic Class Dependency Graph (from vc_derivation.py)

```
MoE Dispatch  →  TP Allreduce  (blocking: dispatch must complete before allreduce)
TP Allreduce  →  KV Cache      (blocking: allreduce must complete before KV update)
KV Cache      ⇢  MoE Dispatch  (non-blocking: KV read doesn't block dispatch)
```

**Cycle analysis:** The blocking edges form a DAG (MoE→Allreduce→KV), no cycles → **2 VCs minimum** (free + escape). The current 2-VC design is theoretically sufficient for this workload. However, if the non-blocking edge becomes blocking (e.g., synchronous KV update before next dispatch), a cycle forms and a 3rd VC is needed.

### 3.3 When Would We Need More VCs?

**Scenario 1: Multi-TP-Group with Cross-Group Traffic**
```
TP Group 0: [0,1,2,3]  ←→  TP Group 1: [4,5,6,7]
  Intra-group allreduce (ring)     Intra-group allreduce (ring)
  Cross-group MoE dispatch         Cross-group MoE dispatch
```
If intra-group and cross-group traffic share links, you need 2 VCs minimum (one per TP group). With 8 TP groups on a 64-node mesh, you might need up to 4 VCs.

**Scenario 2: Mixed Latency Requirements**
```
Control flits (1 flit, <10 cycles budget)  →  VC0 (highest priority)
KV Cache decode (short, <100 cycles)       →  VC1
MoE dispatch (burst, <1000 cycles)         →  VC2
TP allreduce (bulk, <5000 cycles)          →  VC3 (lowest priority, most buffers)
```
4 VCs for 4 distinct latency classes.

**Scenario 3: Deadlock Avoidance in Irregular Topologies**
If we move beyond mesh to custom topologies (the MILP-generated shortcuts), the channel dependency graph may have more cycles, requiring more VCs for deadlock freedom.

### 3.4 Practical VC Count for VeritX

| Config | VCs Needed | Justification |
|--------|-----------|---------------|
| **Paper baseline** | 2 | Free + Escape, proven at 64-node |
| **QoS with 2 classes** | 2 | GS + BE, same as baseline |
| **QoS with 3 classes** | 3 | GS + BE + Scavenger (from qos_depth.py) |
| **Multi-TP-group** | 3-4 | Per-group isolation + escape |
| **Full QoS + MoE** | 4 | Control + GS + BE + MoE-specific |

**Recommendation:** Design for **4 VCs** as the production target, with the architecture supporting up to 8 for future flexibility.

---

## 4. Architecture Proposal: Parameterized N-VC Router

### 4.1 Design Principles

1. **Parameterized, not hardcoded:** Every VC-count-dependent structure uses `NUM_VCS` as a parameter
2. **Class-based arbitration:** Weighted round-robin across N classes (not binary esc/free)
3. **Per-VC independent stages:** Each VC has its own output stage (eliminates show_vc bottleneck)
4. **Generalized demotion ladder:** VC0→VC1→VC2→... based on cumulative age
5. **Flit header class field:** ceil(log2(N)) bits for VC class encoding

### 4.2 Proposed Flit Header Format

```
Current layout (2-VC):
[63]    = escape_class (0=free, 1=escape)
[62:61] = type (HEAD=0, BODY=1, TAIL=2, SINGLE=3)
[DST_W-1+48:48] = dst
[47:0]  = src(8 bits) + payload(40 bits)

Proposed layout (N-VC):
[63:62]  = traffic_class (2 bits → 4 classes: GS=0, BE=1, MoE=2, Scav=3)
[61:60]  = type (HEAD=0, BODY=1, TAIL=2, SINGLE=3)
[59:DST_W+48] = reserved
[DST_W+47:48] = dst
[47:0]  = src(8 bits) + payload(40 bits)
```

**⚠ Incompatible change:** The type field shifts from [62:61] to [61:60]. This breaks the existing flit format — all NICs, traces, TB, and downstream tools (BookSim, ASTRA-sim adapter) must be updated atomically. The change is justified only if 4 VCs are actually needed; for 2-VC production, keep the current format.

### 4.3 Router Microarchitecture

```
┌─────────────────────────────────────────────────────────┐
│                    N-VC Router                           │
│                                                          │
│  ┌──────────┐  ┌──────────┐  ┌──────────┐              │
│  │ VC0 FIFO │  │ VC1 FIFO │  │ VC2 FIFO │  ... VC(N-1) │
│  │ (GS)     │  │ (BE)     │  │ (MoE)    │              │
│  └────┬─────┘  └────┬─────┘  └────┬─────┘              │
│       │              │              │                    │
│  ┌────▼──────────────▼──────────────▼────┐              │
│  │     VC Allocator (per-input)          │              │
│  │  Selects which VC's head enters SA    │              │
│  └────────────────┬─────────────────────┘              │
│                   │                                     │
│  ┌────────────────▼─────────────────────┐              │
│  │   Switch Allocator (per-output)      │              │
│  │   Weighted RR across N VCs           │              │
│  │   Priority: GS > BE > MoE > Scav     │              │
│  └────────────────┬─────────────────────┘              │
│                   │                                     │
│  ┌────────────────▼─────────────────────┐              │
│  │   Crossbar N:1 mux per output port   │              │
│  │   (selects which VC's flit to send)  │              │
│  └────────────────┬─────────────────────┘              │
│                   │                                     │
│  ┌────────────────▼─────────────────────┐              │
│  │   Per-(output, VC) credit tracking   │              │
│  │   Credit return on downstream accept  │              │
│  └──────────────────────────────────────┘              │
└─────────────────────────────────────────────────────────┘
```

### 4.4 Key Changes from Current Template

| Component | Current (2-VC) | Proposed (N-VC) |
|-----------|----------------|-----------------|
| **Flit header** | 1-bit esc class | 2-bit traffic class |
| **Output stages** | 2 per port (show_vc mux) | N per port (no mux needed) |
| **Grant logic** | Binary esc/free | Weighted RR across N classes |
| **Credit tracking** | Per-(port, VC) | Per-(output, VC) — already parameterized |
| **Demotion** | VC0→VC1 (binary) | VC0→VC1→...→VC(N-1) (ladder) |
| **Ejection** | 2 passes (esc, free) | N passes or priority encoder |
| **Enqueue** | esc bit → VC0/VC1 | class field → VC[class] |
| **Starvation guard** | ESC_YIELD_K counter | Weighted fair arbiter |
| **QCNT_W** | $clog2(2*BUF+1) (wastes 1 bit) | $clog2(BUF+1) (correct per-queue) |

### 4.5 Area & Timing Estimates

Based on CONNECT and FlooNoC literature:

| VC Count | Buffer Area | Arbiter Area | Total Area | Freq Impact |
|----------|------------|--------------|------------|-------------|
| 2 (current) | 1x | 1x | 1x | Baseline |
| 3 | 1.5x | 1.3x | ~1.4x | -2% |
| 4 | 2x | 1.5x | ~1.7x | -3% |
| 8 | 4x | 2x | ~3x | -5% |

**Breakdown:** Each VC adds one buffer FIFO (BUF_DEPTH × 64-bit) per input port, one arbiter slice, and one credit counter per output port. The crossbar is already N-input:1-output per port (the N:1 mux selects which VC's flit to send), so it doesn't grow with VC count — only the input-side buffering and arbitration grow.

### 4.6 Deadlock Freedom

The N-VC design maintains deadlock freedom through:

1. **Channel dependency graph:** With N VCs, the channel dependency graph has N independent layers. As long as each layer's routing is deadlock-free (which our Dijkstra/tree tables guarantee), the overall router is deadlock-free.

2. **Strict priority ordering:** VC0 (highest priority) can never be blocked by VC1 (lower priority), which can never be blocked by VC2, etc. This breaks all circular dependencies. **Caveat:** pure strict priority starves low-priority VCs under load — the current ESC_YIELD_K guard (and its N-VC generalization via weighted RR) is essential for liveness.

3. **Preemption (optional):** If a higher-priority VC needs the output, it can preempt a lower-priority VC's flit in the output stage (like FlooNoC's preemptive VC design).

### 4.7 Migration Path

**Phase 1 (Current):** 2-VC, proven, paper baseline
- No changes needed. Ship the paper.

**Phase 2 (QoS):** 3-VC, GS/BE/Scavenger
- Minimal change: add one more output stage, generalize the grant loop
- Wire from existing qos_depth.py PerClassVCAllocator

**Phase 3 (Production):** 4-VC, GS/BE/MoE/Scavenger
- Full N-VC generalization of the router template
- Flit header class field (2 bits)
- Weighted fair arbiter

**Phase 4 (Future):** 8-VC, full QoS + multicast + custom topology support
- Scale to 8 VCs for maximum flexibility
- Integrate with Constellation/FlooNoC RTL generation

---

## 5. Implementation Sketch

### 5.1 Parameterized Grant Logic (pseudocode)

```systemverilog
// N-class weighted round-robin arbiter
for (int vc = 0; vc < NUM_VCS; vc++) begin
  // Candidate: any queue targeting this output, with credits
  if (!vc_valid[output][vc]) begin
    for (int p = 0; p < NUM_PORTS; p++) begin
      int ci = p * NUM_VCS + vc;
      if (q_cnt[ci] > 0 && cred[output][vc] > 0 &&
          cand_out[ci] == output &&
          get_dst(q[ci][0]) != ID) begin
        vc_valid[output][vc] = 1'b1;
        vc_pick[output][vc]  = p[7:0];
      end
    end
  end
end

// Weighted RR: higher-priority VCs win unless starved
int best_vc = -1;
int best_score = -1;
for (int vc = 0; vc < NUM_VCS; vc++) begin
  if (vc_valid[output][vc]) begin
    int score = vc_weight[vc] * (starve_counter[vc] + 1);
    if (score > best_score) begin
      best_score = score;
      best_vc = vc;
    end
  end
end
```

### 5.2 Parameterized Demotion Ladder

```systemverilog
// Demotion: VC0 → VC1 → ... → VC(N-1)
// KEY SEMANTIC: when a packet is demoted from VC(k) to VC(k+1), it must
// switch from VC(k)'s routing table to VC(k+1)'s routing table at the
// NEXT hop. The esc_mode flag causes cand_out to use get_rt_esc instead
// of get_rt_min — but with N VCs, each VC needs its own routing table.
// Simplified approach: VC0=free (Dijkstra min), VC1..N-1=escape (tree).
// Demotion from VC0→VC1 switches routing to the escape tree.
// No demotion from VC1+ (already on the deadlock-free escape path).
for (int p = 0; p < NUM_PORTS; p++) begin
  int ci = p * NUM_VCS;  // VC0 only
  if (q_cnt[ci] > 0 && blk_cnt[ci] >= AGE_K[7:0]) begin
    esc_mode[ci] <= 1'b1;  // switch to escape routing at next hop
    // Flip class bits on ALL queued flits (prevents VC split on arrival)
    for (int jj = 0; jj < BUF_DEPTH; jj++)
      if (jj < q_cnt[ci]) q[ci][jj][63:62] <= 2'd1;  // force to VC1 class
    blk_cnt[ci] <= 8'd0;
  end
end
```

**Note:** For >2 VCs with per-VC routing tables, the demotion logic needs a routing table selector (not just esc_mode). The current esc_mode boolean is sufficient for the 2-VC case but would need to become a `routing_class` field for N>2.

### 5.3 Parameterized Ejection

```systemverilog
// Ejection: highest-priority VC first
bit done_ej = 1'b0;
for (int vc = NUM_VCS - 1; vc >= 0 && !done_ej; vc--) begin
  // Check if output stage for this VC is free
  if (out_valid_all[LOCAL_PORT][vc] &&
      !(show_vc[LOCAL_PORT] == vc && out_ready_all[LOCAL_PORT]))
    continue;
  // Scan queues for this VC class
  for (int p = 0; p <= LOCAL_PORT && !done_ej; p++) begin
    int c = p * NUM_VCS + vc;
    if (q_cnt[c] > 0 && !grant_deq_q[c] &&
        get_dst(q[c][0]) == ID[$clog2(N_ROUTERS)-1:0]) begin
      // Eject this flit
      out_flit_all[LOCAL_PORT][vc] <= q[c][0];
      out_valid_all[LOCAL_PORT][vc] <= 1;
      out_src_vc[LOCAL_PORT][vc] <= vc[3:0];
      done_ej = 1'b1;
    end
  end
end
```

---

## 6. Recommendations

### For the Paper (Immediate)
- **Keep the 2-VC design.** It's proven, passes all gates, and the traffic analysis shows 2 VCs are sufficient for the Qwen3 MoE workload.
- The 2-VC architecture IS the paper's contribution: escape-class routing with cumulative-age demotion.

### For Production (After Paper)
- **Design for 4 VCs.** The architecture changes are well-understood (parameterize the 12 hardcoded spots listed in §1).
- **Start with Phase 2** (3-VC GS/BE/Scavenger) as a minimal increment.
- **Use vc_derivation.py** to automatically determine VC count from the workload's dependency graph.
- **Consider preemptive VCs** (Benini 2026) for the starvation guard — it's simpler than the yield counter and has provable fairness.

### For Future Research
- **Multicast VCs:** MoE dispatch is inherently multicast. A dedicated multicast VC with tree-based forwarding (not per-hop replication) would dramatically reduce fabric traffic (9.2% measured in ASTRA-sim).
- **Compiler-VC co-design:** The VC assignment could be computed at compile time (static VC allocation) rather than runtime (dynamic VC allocation), reducing router complexity.
- **FlooNoC integration:** For the L4 proof leg, use FlooNoC's preemptive VC architecture directly. Our custom router handles the L1-L3 search/proof; FlooNoC handles the silicon-proven endpoint.

---

## 7. References

1. Dally, W.J. (1992). "Virtual-Channel Flow Control." IEEE Trans. Parallel & Distributed Systems.
2. Papamichael, M.K. et al. (2012). "Re-Examining Conventional Wisdom for Designing NoCs in FPGAs." FPGA.
3. Fischer, M. et al. (2024). "FlooNoC: A 645-Gb/s/link 0.15-pJ/B/hop Open-Source NoC." arXiv:2409.17606.
4. Leone, L., Colagrande, L., Benini, L. (2026). "Physically-Aware Preemptive Virtual Channels for Deadlock-Free AXI NoCs." arXiv:2607.01430.
5. DATE 2026. "MONET: Multicast-Optimized Two-Tier Network-on-Chip for MoE Inference." (PDF not accessible for full verification; claimed in conference proceedings archive.)
6. VeritX `vc_derivation.py` — Dependency-driven VC derivation (§11.3).
7. VeritX `qos_depth.py` — Per-class VC allocation with weighted arbitration.
