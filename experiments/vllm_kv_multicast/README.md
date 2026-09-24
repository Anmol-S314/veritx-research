# vLLM KV-Multicast & Contiguous-Head Layout Prototype

This directory contains a prototype and decoupled benchmark harness for testing the **KV-Cache Multicast** and **Per-Head-Contiguous Layout** optimization inside `vLLM`.

## Defensible Technical Claims & Bounds

1. **Volume Reduction (Definitional Arithmetic):**
   - In Grouped-Query Attention (GQA, e.g. Llama-3-70B with $g = 8$), naive head-parallel execution reads shared KV heads $g$ times redundantly.
   - Multicast eliminates redundant fetches, reducing byte volume by up to $g\times$ (8.0×).
   - As batch size and context length grow ($B \to \infty$), the throughput win approaches $g\times$ as the DRAM bound shifts from weights to KV cache.

2. **Layout Effect (Empirically Measured):**
   - Default block-interleaved KV cache layouts stride across multiple heads.
   - On host CPU RAM, strided slice access incurs L1/L2/L3 cache-line misses (~3–4× penalty).
   - On accelerator DRAM (GDDR6/HBM), strided access causes row-buffer open/close latency, degrading achievable bandwidth efficiency ($\epsilon \sim 0.66$ vs $\epsilon \sim 0.91$ for contiguous reads).

## Honest Benchmark Decoupling (`real_hardware_bench.py`)

The empirical benchmark cleanly separates:
- **Pure Layout Penalty:** Measures execution time of 1× KV byte volume using strided vs. contiguous memory layouts.
- **Pure Volume Reduction:** Measures execution time of 8× redundant strided reads vs. 1× single-pass strided read.
- **Total Combined Benefit:** Combined effect of volume reduction + layout contiguous access.

## Files

- `kv_multicast_connector.py`: PyTorch connector prototype implementing per-head contiguous layout formatting and GQA multicast logic.
- `benchmark_sim_vllm.py`: Theoretical decode roofline calculator modeling volume and layout efficiency.
- `real_hardware_bench.py`: Honest empirical memory benchmark decoupling volume reduction from layout penalty.
- `test_plugin.py`: Unit smoke test suite.

## Quick Start

Run the decoupled empirical benchmark:
```bash
python3 experiments/vllm_kv_multicast/real_hardware_bench.py
```
