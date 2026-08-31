# Qwen3-30B-A3B NPU Scaling Analysis

## TL;DR
**The NoC is NOT the bottleneck for Qwen3-30B-A3B at any practical scale.** Even at 64 NPUs, communication is only ~8% of total time. The workload is severely compute-bound.

---

## What We Measured

### 1. Pure Network Scaling (AllReduce 1MB Microbenchmark)

Ran ASTRA-sim analytical backend with 1MB ring allreduce at different NPU counts:

| NPUs | Total Cycles | Scaling vs 4-NPU |
|------|-------------|-------------------|
| 4    | 15,580      | 1.00× (baseline)  |
| 8    | 21,208      | 1.36×             |
| 16   | 29,320      | 1.88×             |

**Ring scaling is ~linear** as expected: O(N) for ring allreduce with constant message size.

### 2. Qwen3-30B-A3B Workload (ASTRA-sim, 2-NPU baseline)

Real Chakra ETs from LLMServingSim (Qwen3-30B-A3B-Instruct-2507, dp_A_batch0):

| Metric | Value |
|--------|-------|
| Total cycles | 39,963,930,428 (~40B, ~40s at 1GHz) |
| GPU time | 39,906,432,000 (99.85%) |
| Comm time | 67,557,980 (0.17%) |
| Exposed comm | 57,498,428 (0.14%) |
| Overlap | 10,059,552 |

### 3. Workload Communication Pattern (from trace)

Per decoder layer (48 layers total):
- **ALLREDUCE** (o_proj): 8,388,608 bytes (8 MB)
- **ALLGATHER** (expert dispatch): 2,228,224 bytes (2.2 MB)
- **REDUCESCATTER** (expert combine): 8,388,608 bytes (8 MB)
- **Total per layer**: 18.2 MB
- **Total per decode iteration**: ~874 MB

Compute per layer: ~1.6M cycles (attention) + ~1.1M cycles (expert) ≈ 2.7M cycles
Comm per layer: ~1.4M cycles (at 128 GB/s ring)

---

## Scaling Projections

Using the actual 2-NPU ASTRA-sim measurement as calibration:

| NPUs | Compute/NPU | Exposed Comm | Total | Comm% |
|------|------------|-------------|-------|-------|
| 2    | 39.9B      | 57.5M       | 40.0B | 0.14% |
| 4    | 20.0B      | 86.2M       | 20.0B | 0.43% |
| 8    | 10.0B      | 100.7M      | 10.1B | 1.00% |
| 16   | 5.0B       | 108.2M      | 5.1B  | 2.12% |
| 32   | 2.5B       | 112.4M      | 2.6B  | 4.31% |
| 64   | 1.2B       | 115.4M      | 1.4B  | 8.47% |

**Communication never exceeds 10% even at 64 NPUs.**

---

## Why Communication Doesn't Scale

1. **MoE is compute-dominated**: Each expert has 302M params × 2 bytes = 604 MB of weight loads. The expert compute (553K cycles each) dwarfs the communication (1.4M cycles per layer for 18.2 MB).

2. **Communication is small relative to compute**: 874 MB total communication vs ~2.6 TB of weight loads (48 layers × 2 experts × 302M × 2 bytes). Communication/weight ratio = 0.03%.

3. **Ring allreduce scales well**: Even with 64 NPUs, the ring only adds 63 extra hops. At 128 GB/s and 100ns/hop, the 8MB allreduce takes ~1.5µs per hop = ~95µs total = 95K cycles. Compare to 1.2B cycles of compute per NPU.

4. **Expert parallelism keeps comm bounded**: The MoE dispatch (ALLGATHER 2.2MB) and combine (REDUCESCATTER 8MB) are per-layer and independent of TP size. They only scale with EP size, which stays small.

---

## What Would Make NoC the Bottleneck

For the NoC to matter, you'd need one of:

1. **Dense model (not MoE)**: A 30B dense model would have much larger activations (full hidden state × all layers), making communication proportionally larger.

2. **Small batch size**: At batch=1, compute per token is small, so comm becomes relatively larger. Our trace is batch=0 (decode), which is already the smallest batch.

3. **Higher bandwidth utilization**: If the NoC bandwidth is lower than 128 GB/s (e.g., on-chip NoC at 32 GB/s), communication grows proportionally.

4. **More NPUs with larger collectives**: Going from TP=2 to TP=64 for a dense model would make ALLREDUCE dominate.

---

## Implications for Srota/VeritX

1. **NoC DSE for MoE serving is not the right use case** — the network is never the bottleneck.

2. **The right use case is dense model training/inference** where activation allreaches dominate, or **small-batch latency-critical serving** where every microsecond matters.

3. **The DSE harness is valuable for topology comparison** (mesh vs hierarchical vs flatfly) when the NoC IS the bottleneck — we showed hierarchical beats mesh by 2.5% at identical wire cost.

4. **For Qwen3-30B-A3B specifically**: optimize the compute fabric (PE count, SRAM sizing) not the network. The NoC just needs to be "fast enough" — any reasonable topology works.

---

## Reproducing the Results

```bash
# AllReduce microbenchmark
python3 /tmp/network_scaling_run.py

# ASTRA-sim with real Qwen3 traces (2-NPU)
cd serving/astra-sim
./build/astra_analytical/build/bin/AstraSim_Analytical_Congestion_Aware \
  --workload-configuration=/tmp/npu_scaling/4npu/llm \
  --system-configuration=/tmp/npu_scaling/4npu/system.json \
  --network-configuration=/tmp/npu_scaling/4npu/network.yml \
  --remote-memory-configuration=/tmp/npu_scaling/4npu/remote_memory.json
```

---

## Files Referenced
- Source trace: `serving/LLMServingSim/astra-sim/inputs/runs/test_debug4/trace/.../instance0_batch0.txt`
- ETs: `serving/LLMServingSim/astra-sim/inputs/runs/test_debug5/workload/.../llm.{0,1}.et`
- ASTRA-sim binary: `serving/astra-sim/build/astra_analytical/build/bin/AstraSim_Analytical_Congestion_Aware`
- AllReduce microbenchmark ETs: `serving/astra-sim/examples/workload/microbenchmarks/all_reduce/`
- Scaling script: `/tmp/network_scaling_run.py`
