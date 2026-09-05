# MONET: Multicast-Optimized Two-Tier Network-on-Chip for MoE Inference

**Source:** DATE 2026 (978-3-9826741-1-7/DATE26/© 2026 EDAA)
**Authors:** IIIT Bangalore (International Institute of Information Technology Bangalore)
**Saved:** 2026-08-23

---

## Abstract

The growing complexity of Mixture-of-Experts (MoE) models in machine learning applications demands innovative hardware solutions to address their unique computational and data movement challenges. Some of the critical challenges facing MoE models include sparse activation, dynamic token routing and irregular computation patterns that lead to low utilization and higher communication latency. In this paper, we introduce MONET, a novel two-tier Network-on-Chip (NoC) architecture designed to efficiently execute MoE workloads by co-optimizing compute, memory, and interconnect subsystems. The first tier consists of a reconfigurable systolic processing element (PE) island, executing both gating and expert computations, with runtime-configurable support for sparse/dense operations, expert reordering, and activation functions. The second tier incorporates a dual mesh network connecting a grid of PE islands; one network manages input token delivery with a broadcast scheme optimized for the gating phase of MoE, while the other is tailored for efficient inter-expert communication necessary for result aggregation. Evaluated on MoE benchmarks, MONET demonstrates up to 8.5× lower latency and over 6× better energy efficiency compared to state-of-the-art MoE accelerators.

## Key Architecture: Two-Tier NoC

MONET's NoC consists of three logically decoupled routing planes:

1. **Gating Phase (Tier 1):** Input tokens broadcast into the array from the entry point, routed horizontally across gating units. Multicast-capable routers (Mel) support multiple simultaneous outputs per flit.

2. **Expert Weight Delivery (Tier 2a):** After top-k expert selection, weights for activated experts are routed to designated PE islands on an isolated communication plane.

3. **Token-Expert Execution + Aggregation (Tier 2b):** Tokens dispatched vertically to selected expert islands, outputs routed to aggregation units. Bypass-enabled routers (Bel) accelerate output fusion.

## Router Microarchitectures

### Mel Router (Multicast-enabled Link Reversal)
- Dual-directional data paths
- Internal multicast-capable buffers
- Dynamic link reversal (output ports can be reassigned as inputs)
- Packet duplication at buffer level
- Multiple output ports driven per cycle
- Based on R-NoC [27] extended to mesh topologies

### Bel Router (Bypass-enabled Low-Latency)
- 5×5 crossbar switch with integrated bypass paths
- Single-cycle forwarding when no contention
- Bypass Control unit detects conflict-free conditions
- Skips RC, VA, SA stages on fast path

## RTL Synthesis Results (22nm, 300MHz, 0.8V)

| Module | Area (mm²) | Power (mW) |
|--------|-----------|------------|
| Global Buffer | 14.7 | 420 |
| PE Islands (MAC + Buffer) | 39.5 | 2180 |
| Mel Routers (Multicast NoC) | 6.2 | 125 |
| Bel Routers (Aggregation NoC) | 8.1 | 138 |
| Control Unit | 5.6 | 133 |
| **Total** | **74.1** | **2996** |

## Latency Comparison (Batch=16)

| Platform | M3ViT (μs) | DeepSpeed (μs) | Switch-base (μs) |
|----------|-----------|----------------|------------------|
| Systolic Array | 8824 | 496 | 140918 |
| EdgeMoE | 1295 | 184 | 12465 |
| Space-Mate | 873 | 120 | 5483 |
| MONET | 550 | 62 | 3195 |

## Key Results
- Up to **8.5× lower latency** than EdgeMoE
- Over **6× better energy efficiency** than Systolic Array baseline
- **2.1× throughput** over XY mesh, **1.6×** over Adder-Tree
- Near-linear scaling up to 64×64 PE array

## Relevance to VeritX

| MONET Concept | VeritX Equivalent |
|---------------|-------------------|
| Mel router (multicast) | ASTRA-sim multicast fold (9.2% gain measured) |
| Bel router (bypass aggregation) | Bel = bypass-enabled; our router has demotion-based escape |
| Two-tier NoC | Our free/escape dual-class (2 VCs) |
| Token reuse via vertical multicast | Our multicast fold in ASTRA-sim |
| Expert reordering for load balancing | Our DSE tool's traffic matrix synthesis |

**Key insight for VeritX:** MONET validates that MoE workloads benefit from dedicated multicast + aggregation planes. Our 2-VC escape-class architecture maps to MONET's Tier 1 (multicast/gating) and Tier 2 (aggregation), but we use a single shared fabric with VC-based separation rather than physically separate meshes. This is the right tradeoff for our scale (64 nodes, shared fabric) vs MONET's (4×4 PE islands, dedicated planes).
