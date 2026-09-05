# Pareto Replay Results — 2026-08-29

**First cycle-accurate multi-workload table.** 8 topologies × 3 traces × 3 seeds = 72
full-trace BookSim replays (`8b19afeb` TraceInjectionProcess, `latency_thres=1e6`,
`sample_period=span+10k`, `max_samples=5`). All 95K–1.29M packets, 132K–652K cycles,
deterministic timestamps. Raw: `runs/booksim/pareto_replay.json`, log `/tmp/pareto_replay.log`.

| Topo | Edges | qwen3_serving_16rank | llama70b_tp64_ring | llama_1b_attention |
|---|---:|---:|---:|---:|
| gec_express (k8 o7 d1, dor) | 448 | **1857.69c** | 62451.80c | **239.81c** |
| torus_8x8 (dim_order) | 128 | 1872.47c | **62451.80c** | 374.61c |
| mesh_8x8 (dim_order) | 128 | 1876.38c | 62454.40c | 546.99c |
| grpo_best (anynet min) | 111 | 1863.96c | 62451.90c | 566.91c |
| rho100_best (anynet min) | 106 | **1863.49c** | 62618.00c | 448.51c |
| flatfly_64 (ran_min) | 48 | 1922.73c | 63937.80c | 259.81c |
| gec_mecs (k8 o1 d7, vcs8) | ~128 ch | 1906.87c | 64235.20c | 260.44c |
| mecs64 (anynet min) | 111 | 2105.14c | 62452.90c | **32167.30c** |

Seeds identical under replay (deterministic). Only tie-break randomness: torus ±0.4%.

## Findings (honest, post-Bernoulli)

1. **mecs64 is DOMINATED**: 2105c (qwen, +12% vs mesh) and 32167c (attention, 5.9× mesh).
   The old "MECS wins mcast 2.0× / wire-Pareto FRONT" results were Bernoulli-timing
   artifacts. Shared/tapped channels serialize under real attention flows.
2. **mesh is dominated by torus** at equal wires (128e): torus ≥ mesh on all 3 workloads.
3. **Saturated LLaMA ring: topology doesn't matter** — mesh/torus/gec all 62,452c±0.2%.
   Demand = 1.2 flit/node/cyc > 1.0 capacity → pure capacity wall. Supports the
   dense-vs-MoE crossover claim: network choice matters only below the capacity wall.
4. **Attention is the discriminating workload**: 547→240c, 2.3× spread mesh→gec_express.
5. **Wire efficiency survives replay**: rho100 (106e) 1863.49c / grpo (111e) 1863.96c on
   qwen ≈ gec_express (448e) 1857.69c. ~0.3% latency penalty for 4.2× fewer wires.
   RHO/GRPO were optimized against the now-void Bernoulli objective and STILL land
   near-front under replay — the wire-count reduction transferred; the latency
   ordering (mecs>mesh) did not.
6. qwen spread is 3.5% (1857–1923c): sparse 0.009 pkt/node/cyc traffic ⇒ latency ≈
   path length + burst queuing; topology is a minor term. The headline paper number
   is attention (2.3×), not serving (3.5%).

## Workload-robust Pareto (latency-attention × latency-qwen × wires) — non-dominated set

- gec_express: best on both latency workloads, worst wires (448)
- flatfly_64: 260c attention, 48 wires — best wires in class, worst qwen/ring
- rho100_best: near-best qwen at 106e; middling attention (448c)
- torus_8x8: dominates mesh; the "boring baseline" that must be beaten on attention

## Open

- `veritx run` cert-skip bug, `evaluate anynet`/`sweep` need the replay cfg
  (`latency_thres`, span-derived sampling) — see FEATURE-AUDIT-2026-08-29.md
- 9ce5 rate-mismatch: Bernoulli knee was the confound; re-test under replay
- RHO/GRPO should be re-run against the replay objective (`--scorer replay`)
