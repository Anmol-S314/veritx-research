# Synthesis Methods — What to Use Instead of SA

## Status Quo

| Method | Code | Scale | Quality | Status |
|---|---|---|---|---|
| MILP | `milp_topology_v2.py` | N≤32 | Exact | ✅ implemented |
| SA | `milp_topology_v2.py` | N≤256 | Heuristic | ✅ implemented |
| Bayesian opt | `search.py` | N≤64 | Surrogate | ✅ implemented |

SA is a PLACEHOLDER. It works for testing but is not production-quality.

## What the Literature Says

### Best methods by scale

| Scale | Method | Why | Reference |
|---|---|---|---|
| N≤32 | **MILP** | Exact, provably optimal | Already have it |
| N=64-256 | **Bayesian optimization** | Surrogate model learns objective landscape, sample-efficient | `search.py` + ArchGym scaffold |
| N=256+ | **Hierarchical decomposition** | Cluster→intra-block→inter-block express; only way to scale | RapidChiplet method (but license-blocked) |
| Any | **RL-based (PARL)** | Learns topology policy, generalizes across workloads | 2510.24113, no code released |
| Any | **Diffusion/CVAE** | Generates topologies conditioned on traffic | 2512.07877, 150K BookSim points |

### What exists as OSS

| Tool | License | What it does | Usable? |
|---|---|---|---|
| **ArchGym** | Apache-2.0 | Gym scaffold for ML search agents (ACO, GA, BO, RL) | ✅ Best foundation — needs NoC env we'd write |
| **Omelet** | MIT | Chiplet DSE with gem5-Garnet proof | ⚠️ Young, chiplet-focused |
| **NetSmith** | None | Machine-discovers topologies (MILP + routing + deadlock) | ❌ License-blocked |
| **RapidChiplet** | None | Chiplet DSE + BookSim export | ❌ License-blocked |
| **Constellation** | BSD-3 | Renders any topology graph → synthesizable RTL | ✅ Perfect for L4 (render our topologies) |

## Recommendation

**Phase 1 (now):** Replace SA with Bayesian optimization in the synthesis loop.
- `search.py` already has BO infrastructure
- Wire event format → BO → topology
- BO is sample-efficient (fewer BookSim evals than SA)
- Works at N=64-256 without changes

**Phase 2 (scale):** Add hierarchical decomposition for N=256+.
- Cluster nodes into groups (e.g., 16 tiles per cluster)
- Synthesize intra-cluster topology (BO, small N)
- Synthesize inter-cluster express links (BO, small N)
- Only way to scale to N=1024+

**Phase 3 (production):** Train RL agent on BO results.
- Use BO-generated topologies as training data
- Train PARL-style agent to generalize across workloads
- Agent predicts topology from traffic model in <1s

## Why This Works

The event format we validated is **method-agnostic**:
- Events → any synthesis method → topology
- The lossless representation is orthogonal to the optimizer
- We can swap methods without changing the input format

## Key Insight

Our moat is NOT the synthesis method — it's the **traffic model + certification loop**:
1. Events capture what matrices lose (ordering, priorities, phases)
2. Any optimizer can consume events
3. Certification (deadlock-free, latency bounds) validates the result
4. Constellation renders to RTL

The synthesis method is a commodity. The traffic model + certification is the product.
