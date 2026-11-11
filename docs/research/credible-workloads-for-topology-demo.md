# Credible workloads for a topology demo

**Audience correction:** NVIDIA's interest is robotics/VLA, not generic datacenter LLM serving. Lead with [the GR00T/Thor and concurrent whole-body-control workload brief](nvidia-robotics-vla-workloads.md); the options below are secondary datacenter references.

**Bottom line:** credible workloads do not require raw packet traces. Present request datasets, measured collective profiles, communication-kernel benchmarks, and serving measurements as distinct evidence categories. None alone validates a proposed topology's performance.

## Ranked workload options

| Workload | Source-backed configuration | What is evidenced; limits | Honest label |
|---|---|---|---|
| **1. NVIDIA TensorRT-LLM MoE communication sweep** | DeepSeek-V3-style profile: hidden size 7,168, top-k 8, 256 experts. The main BF16 sweep varies EP=8/16/32/64 and batch=1–2,048. At EP=8, batch=2,048 on GB200 NVL72, NVIDIA reports dispatch 311.8 μs / 753.28 GB/s and combine 322.6 μs / 728.20 GB/s. | NVIDIA-reported kernel timings and **logical** bandwidth; the source says the bandwidth calculation includes local-rank traffic that does not traverse NVLink. The reproduction script requires compatible hardware/software and is not in the release container/wheel. These are not physical-link counters, packet captures, or results on Microchip/our fabric. The separate post-quant table is labeled B200, so do not mix it with the GB200 NVL72 sweep. | “NVIDIA-reported MoE communication-kernel benchmark on GB200 NVL72; logical bandwidth, not target-fabric measurement.” |
| **2. Dense tensor-parallel inference profile: Llama 3.1 8B, TP=4** | Xu et al. profile vLLM on a 4×H100 (94 GB, NVLink) system for one request with 128 prefill and 128 decode tokens. Table III reports 65 prefill and 8,255 decode AllReduce calls, plus Gather counts/shapes. Table IV reports AllReduce message bytes: 1,048,576 prefill and 8,192 decode. The paper describes PyTorch profiling triggered by server requests and excludes rank-0 profiles. | Paper-reported measured operation counts/shapes and AllReduce bytes. No raw rank/timestamp events, selected NCCL algorithm, or packet/link trace. Gather byte size remains a two-byte-element assumption in the local ledger. | “Published measured collective profile; any packet schedule is a projection.” |
| **3. UCCL-EP DeepSeek expert-parallel results** | Authors report a normal-mode DeepSeek-V3-style case with 4,096 tokens, hidden size 7,168, top-4 groups/top-8 experts, FP8 dispatch and BF16 combine. At EP=32 on H200/EFA they report dispatch 54 GB/s and combine 43 GB/s. Separately, their vLLM DeepSeek-V3-0324 serving case uses two p5en instances, EP=16, 1K input/256 output tokens; they report 8.92 requests/s and mean TPOT 81.41 ms for AllGather+ReduceScatter versus 9.24 requests/s and 61.02 ms for UCCL-EP low-latency mode. | UCCL-EP authors' reported multi-node kernel and serving results on named platforms; not independently reproduced here and not official upstream DeepEP results. Keep normal and low-latency modes, hardware, and serving/kernel results separate. EFA results are not Microchip or target-fabric measurements. | “UCCL-EP authors’ reported H200/EFA results; external reference, not our hardware result.” |
| **4. Standard dense LLM serving: MLPerf Inference v5.1, Llama 3.1 8B** | CNN/DailyMail validation set (13,368 examples); average 778 input and 73 output tokens. The reference README gives a vLLM/BF16 example with batch size 16 and configurable tensor parallelism. Server targets: TTFT ≤2 s and TPOT ≤100 ms. | Reproducible application-level workload and benchmark protocol—not NCCL operations or network traffic. Crucially, the README says its GPU Server SUT was not tested. | “MLPerf-defined serving demand; not a validated GPU Server result. Communication is modeled separately.” |
| **5. vLLM request replay: timed trace or ShareGPT** | Official `vllm bench serve` supports timed-trace inputs with timestamp, input length, output length, and optional hash IDs; the benchmarking guide also documents ShareGPT and custom JSONL. | A method for replaying request arrivals/lengths against a serving endpoint. The docs provide schema/recipes, not a particular timed trace or topology result. ShareGPT prompts alone do not establish production arrival timing. Identify the actual dataset/trace, time units, field mapping, model, and run settings. | “Official vLLM workload/replay method; result depends on selected input and serving setup.” |
| **6. Canonical collective sweep: NVIDIA NCCL Tests** | `all_reduce_perf`, 8 B through 128 MiB by powers of two, one node with 8 GPUs (`-b 8 -e 128M -f 2 -g 8`). | Standard, reproducible communication microbenchmark recipe. It is not an application workload or published result for our system; run on target hardware before citing performance. | “Standard NCCL AllReduce microbenchmark; not serving traffic.” |
| **MoE implementation candidate: official DeepEP** | The official repository documents expert-parallel all-to-all dispatch/combine, BF16/FP8 dispatch, and API parameters including token capacity, hidden size, top-k, and expert count. | Useful implementation reference, but its README does not pin a reproducible model/workload configuration with benchmark results. Do not attribute UCCL-EP or other fork results to official DeepEP. | “MoE scenario configured for exploration; parameters/results must be separately sourced or measured.” |

## Best investor demo

1. **Show a real communication profile:** use the Xu et al. TP=4 collective ledger as the simulator input, with counts/bytes and assumptions visibly separated.
2. **Show a published NVIDIA MoE reference:** use the TensorRT-LLM GB200 NVL72 sweep, explicitly calling bandwidth *logical* and the results NVIDIA-reported—not Srota or Microchip measurements.
3. **Add serving demand separately:** MLPerf defines a recognizable request workload, but its GPU Server SUT was not tested. If you have an actual timed request trace, vLLM documents how to replay it; the docs themselves do not supply that trace.
4. **For a multi-node comparison:** show UCCL-EP H200/EFA results as the authors' external result, separate from NVIDIA NVLink data and from any Microchip claims.
5. **State the evidence gap:** no listed source supplies packet captures or rank-level event timestamps for these cases. Packetization, endpoint mapping, injection schedule, and link behavior in Srota remain modeled until validated on the target system.

**Do not combine parameters across sources into one supposedly measured run.** MLPerf's 778/73 average is not the Xu paper's 128/128 profile. GB200 NVL72 logical bandwidth, H200/EFA results, and any Microchip-switch projection are different systems and evidence types.

## Existing local workload evidence

`tracks/t3-topology/data/lerobot/SMOLVLA.md` and `SMOLVLA_VLA.md` document real CPU forward passes and measured pipeline/model stages. Inputs are synthetic observations; there is no closed-loop task-success measurement or GPU/interconnect evidence. These demonstrate workload instrumentation, **not** network performance.

## Sources

- [NVIDIA TensorRT-LLM: Optimizing MoE Communication with One-Sided AlltoAll Over NVLink](https://github.com/NVIDIA/TensorRT-LLM/blob/main/docs/source/blogs/tech_blog/blog18_Optimizing_MoE_Communication_with_One_Sided_AlltoAll_Over_NVLink.md)
- [UCCL-EP authors: Portable Expert-Parallel Communication — Full Results](https://uccl-project.github.io/posts/uccl-ep-full/)
- [Xu et al., Characterizing Communication Patterns in Distributed LLM Inference](https://arxiv.org/abs/2507.14392)
- [MLCommons: MLPerf Inference 5.1, small LLM workload](https://mlcommons.org/2025/09/small-llm-inference-5-1/)
- [MLPerf Llama 3.1 8B benchmark README](https://github.com/mlcommons/inference/blob/master/language/llama3.1-8b/README.md)
- [Official vLLM `bench serve` documentation](https://docs.vllm.ai/en/stable/cli/bench/serve/)
- [Official vLLM benchmarking CLI guide](https://github.com/vllm-project/vllm/blob/main/docs/benchmarking/cli.md)
- [NVIDIA NCCL Tests](https://github.com/NVIDIA/nccl-tests)
- [DeepSeek DeepEP official repository](https://github.com/deepseek-ai/DeepEP)
