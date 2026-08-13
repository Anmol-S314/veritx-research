# LLM Serving-Trace Pipeline — LLMServingSim → Chakra → BookSim → RTL

Status: **leg 1 (matrix) DONE, leg 2 (RTL replay) in progress**. Epic:
`veritx-research-e77a`. Compiled 2026-08-13.

Closes the paper threat (paper_draft.md §7, threat line 385): *"Traffic is
synthetic KV row-multicast, not a Chakra-derived trace."* The die-to-die
traffic matrix now comes from an actual token-by-token serving simulation of
a real MoE model, not hand-built serving constants.

## The pipeline

```
LLMServingSim 2.0 (ISPASS 2026, KAIST casys-kaist/LLMServingSim)
  ├─ model: Qwen/Qwen3-30B-A3B-Instruct-2507 (MoE, 128 experts top-8, GQA 4 KV heads)
  ├─ hardware: RTXPRO6000 (shipped profile DB, bf16, tp∈{1,2})
  ├─ cluster: 1 node, 2 NPUs, TP=2 EP=2 (MoE dispatch + TP collectives)
  └─ workload: workloads/sharegpt-qwen3-30b-a3b-300-sps10.jsonl (300 sps)
        │  serving/__main__.py --num-req 20 --no-cleanup-inputs
        ▼
  per-batch traces: astra-sim/inputs/runs/<run>/trace/<hw>/<model>/instance*_batch*.txt
        │  (chakra converter also runs; .et files for the ASTRA-Sim network sim)
        ▼
  scripts/trace_to_matrix.py  (this repo, committed 9fb248d)
        │  parses comm events: ALLREDUCE (TP), EXPERT ALLGATHER (MoE dispatch),
        │  REMOTE:n locs (cross-die memory)
        ▼
  N×N traffic matrix (BookSim `matrix(<file>)` format) + raw bytes .json
        ▼
  BookSim bridged_2die gate (128 nodes: 2× 8×8 mesh + 1 bridge link)
        ▼
  RTL replay (noc_tb TWO_DIE, Verilator) — leg 2
```

## Results so far (leg 1)

**Run**: Qwen3-30B-A3B, 2 NPUs, TP2/EP2, 20 requests, bf16, block 16,
sharegpt workload. 1,178 per-batch traces, **24.2 GB inter-die bytes**,
perfectly symmetric 2-die pair matrix (all-reduce + expert dispatch
dominate; KV traffic on this config is local).

**Bridge gate** (trace matrix → 128×128 core expansion → bridged_2die):

| rate | accepted | latency | status |
|---|---|---|---|
| 0.005 | 0.0051 | 67.4 | free |
| 0.01  | 0.0101 | 69.4 | near-sat |
| 0.02  | 0.0156 | 381.5 | SATURATED (5.6× latency) |
| 0.04  | 0.0151 | 315.1 | SATURATED |

The single bridge link saturates at aggregate ≈ 1.0 of link capacity:
accepted caps at 1/64 per core (= the bridge ceiling), latency 68 → 381
cycles. **First dynamic serving-trace evidence for the UCIe bridge
bottleneck** — replaces the hand-built constants from
`die_to_die_matrix.py`.

**PD-disaggregated run** (single_node_moe_pd_instance): prefill + decode
instances, prefix caching 61.9% hit ratio on a shared-prefix workload,
remote KV transfers visible as `REMOTE:0` at embed/sampler (8 KB each way).

## Toolchain install notes (all under /var/tmp/opencode)

- Repo: `git clone --recurse-submodules https://github.com/casys-kaist/LLMServingSim`
  (official, ISPASS 2026; **updated 2026-08-13**).
- Venv: `/var/tmp/opencode/llmssim-venv` (Python 3.14; pyinstrument, pandas,
  msgspec, rich, protobuf>=7.35.1).
- Chakra: `pip install -e .` from
  `astra-sim/extern/graph_frontend/chakra` — **patched**: the fork's
  `build_grpc` command is declared but never implemented
  (`setup.py`/`setup.cfg` patched; protos pre-generated with
  `grpc_tools.protoc`). Laura regenerated the python protos at the pinned
  protobuf 6.x — gencode/runtime now match.
- ASTRA-Sim analytical backend: `build/astra_analytical/build.sh -t
  congestion_unaware`. Build fixes: system `protoc` absent → pre-generated
  `et_def.pb.{h,cc}`; `libprotobuf-dev` absent → extracted from
  `apt-get download libprotobuf-dev` (3.21.12) to
  `/var/tmp/opencode/tools/protobuf-dev/root/usr`, exported via
  `CMAKE_PREFIX_PATH`; `cxxopts.hpp` missing `<cstdint>` include (GCC 15);
  static libprotobuf needs `-lz` (find_library ZLIB in astra-sim CMakeLists);
  NUM_THREADS capped at 4 (14 GB host).
- LLMServingSim itself needs `sys.executable` in graph_generator (was
  hardcoded `python`) to find chakra in the venv.

## What is still open (leg 2+)

1. **RTL replay of the trace matrix** on `noc_2die.sv` (TWO_DIE, BRIDGE_ROW
   0 on-axis) — Verilator build in progress; diff against BookSim per-flit.
2. KV-cache lifecycle (`kv_load`/`kv_evict`) events fire only on pool
   eviction (model 56 GB > tight NPU mem); cross-die KV shows up as
   `REMOTE:` locs instead — acceptable, documented.
3. DeepSeek-V4/V3 shapes: not shippable without a vLLM profiler pass on the
   real GPU (perf DBs are hardware-measured); Qwen3-30B-A3B is the
   highest-fidelity MoE+GQA config available. If a DeepSeek profile DB
   becomes available, model config JSON + arch YAML (qwen3_moe-compatible)
   is the only addition needed.
