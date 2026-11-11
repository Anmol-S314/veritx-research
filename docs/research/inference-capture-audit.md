# Raw inference-capture acceptance audit

## Acceptance target

Obtain real multi-GPU inference communication events with ranks, collective
operations, tensor sizes/dtypes, timestamps and GPU durations. Do not promote a
paper-informed synthetic packet stream to captured traffic. A qualifying runtime
capture still does not establish physical packets, routes, power, area, energy,
or serving latency unless those are separately measured.

## CAL26: plot-data ZIP found; raw captures still inaccessible

The user supplied
`/home/datavex/Downloads/CAL26-NCCL-GEMM-data-v1.0.0.zip` (1,015,933 bytes,
SHA-256 `fc450e1f07ccf5060c446b82a28ab9f3be58aac7f5a9dc3306a63158b0dbd44e`,
MD5 `141707403996fe9b71d964eaa9fec1b2`, matching the Zenodo file checksum).
It contains 17 archive entries, including two inference CSVs and the exporter,
but **no `.nsys-rep`, `.qdstrm`, SQLite, or other raw trace**. Its inference
counter CSV has 350 rows; the published `nvlink_GBps` values range from 0 to
`6.1897e-7`. In the `DeepEP alone` panel, 40 samples range from `1.0338e-7` to
`4.5852e-7` GB/s (median `4.404e-7`). The source column points to
`inference_results/pm_cupti_tools/260810_vllm_gpc_nvlink_clean/output_dev3_0.csv`.
The three training Fig. 3 CSVs are similarly near zero: ring ReduceScatter
ranges `0–8.57e-7`, A2A SendRecv `0–8.5674e-7`, and DeepEP `0–7.4347e-7` GB/s.
The scale concern is therefore not confined to the inference rows; these
published columns cannot yet serve as physical NVLink-volume evidence.

The release exporter computes this field as `nvl / 1e9`, but the ZIP omits that
source capture and the upstream unit/scale for `nvl`. Thus the local copy
confirms the published numbers but does **not** resolve their physical meaning;
no correction factor is justified. The archive is the plot-data release linked
from [Zenodo v1.0.0](https://zenodo.org/records/21925183), not the raw captures
linked separately at
[liu2550/CAL26-NCCL-GEMM-data](https://huggingface.co/datasets/liu2550/CAL26-NCCL-GEMM-data).
Unauthenticated requests to that dataset API and recursive file tree returned
**HTTP 401 Unauthorized**. This does not distinguish a private/deleted dataset
from another access restriction. Local Nsight Systems 2025.5.2 cannot inspect
files that are not available.

## PACC: one rejected training pair and one ambiguous NCCL segment

Source revision: [`f2eed8c27fa0a28d027d8faf153e59e92fd80e45`](https://github.com/lynxarv/PACC/tree/f2eed8c27fa0a28d027d8faf153e59e92fd80e45).
Downloaded files were verified against their Git blob SHA-1 and independently
SHA-256 hashed. The LLaMA pair under
`TraceGen/mlperf_traces_inference/LLaMA3-3B-FSDP-QLoRA/` contains **training**:

| Raw file | Events | CPU collective calls | NCCL GPU kernels | Backward events |
|---|---:|---:|---:|---:|
| [`rank0/device_0.json`](https://github.com/lynxarv/PACC/blob/f2eed8c27fa0a28d027d8faf153e59e92fd80e45/TraceGen/mlperf_traces_inference/LLaMA3-3B-FSDP-QLoRA/rank0/device_0.json) | 131,770 | 85 | 85 | 10,522 |
| [`rank1/device_1.json`](https://github.com/lynxarv/PACC/blob/f2eed8c27fa0a28d027d8faf153e59e92fd80e45/TraceGen/mlperf_traces_inference/LLaMA3-3B-FSDP-QLoRA/rank1/device_1.json) | 124,998 | 85 | 85 | 10,522 |

Each rank has 57 AllGather and 28 ReduceScatter CPU calls and corresponding
counts of NCCL GPU kernels. Actual events include
`autograd::engine::evaluate_function: NllLossBackward0`,
`aten::nll_loss_backward`, and FSDP backward hooks. Metadata says NCCL 2.27.5,
world size 2, and Tesla V100S-PCIE-32GB GPUs. Those are real **training** runtime
observations, not inference evidence.

SHA-256:

- rank 0: `a0c4f3a4ead0e3d10f8e0dc838953cc94dcd886d8f215eca3d5de30dacbd8626`
- rank 1: `551d8264404bf15fb010b436554976d82426e5801bda6d4f669570c248f27ca1`

The source has separate forward-only (`model.eval()` / `torch.no_grad()`) and
training (`loss.backward()` / `optimizer.step()`) collectors. The presence of a
forward-only collector does **not** establish that a particular file was
produced by it. Moreover, a no-grad full-sequence model forward is not the same
as an autoregressive serving trace with measured TTFT/TPOT.

Primary source paths at the revision above:

- `TraceGen/r7525TraceGen.py`, lines 49–68: forward-only path.
- `TraceGen/r7525TrainTraceGen.py`, lines 91–152: training step.
- `TraceGen/utils/profiler.py`, lines 32–65: ET/Kineto collection.
- `TraceGen/models/llama3_fsdp_qlora.py`: LoRA/FSDP model and fixed-length inputs.

A search for a repository-root license file found none in that revision. Raw
files are cached locally under `.pi/inference-capture-audit/`, not redistributed
in the source evidence pack. Public availability alone does not grant a reuse
license.

### DeepSeek candidate: observed NCCL, inference provenance unresolved

The repository also contains
[rank 0](https://github.com/lynxarv/PACC/blob/f2eed8c27fa0a28d027d8faf153e59e92fd80e45/TraceGen/mlperf_traces_inference/DeepSeek-R1-Distill-Qwen-7B-FSDP-QLoRA/rank0/device_0.json)
and
[rank 1](https://github.com/lynxarv/PACC/blob/f2eed8c27fa0a28d027d8faf153e59e92fd80e45/TraceGen/mlperf_traces_inference/DeepSeek-R1-Distill-Qwen-7B-FSDP-QLoRA/rank1/device_1.json)
device traces. They are authentic PyTorch/Kineto files at the pinned revision and their metadata reports NCCL 2.27.5, world size 2, ranks
`[0,1]`, and two Tesla V100S-PCIE-32GB devices. The event audit found **29 CPU
`c10d::_allgather_base_` calls and 29 `ncclDevKernel_AllGather_RING_LL` GPU
kernels on each rank**, with no detected backward or optimizer events in these
files. The ranks have the same ordered call sequence and input shapes/dtypes;
that order comparison does not assert cross-rank clock alignment. Downloaded
sizes/SHA-256: rank 0, 12,713,105 bytes,
`d222e1cd7e413d679d752689b28836bd64a514baf45c9541e3ee06c1c4f31bb0`; rank 1,
12,448,320 bytes,
`a9a1b8e604b0fecc93381ab3266f0eb095b4bfef1473fca9bbddedd723fa7f93`.

Observed NCCL kernel fields report FP16 input element counts corresponding to
**234,499,584–1,089,998,336 bytes per input tensor** (median 234,499,584 bytes)
and GPU kernel durations of **23.740–145.469 ms** (median 28.948 ms). These are
NCCL kernel/input-tensor observations; they are **not measured wire bytes,
link-only latency, or per-packet traffic**. Sequence numbers contain gaps, so
the files are not a complete process-group event history.

Do not promote these files to an inference workload. PACC's top-level README
says its multi-GPU FSDP traces are training, while this directory is labeled
inference and its captured window has no backward events. The trace generator
that produced these exact files is not tied to the artifacts: the inspected
forward-only collector selects LLaMA-3.2-3B, not this DeepSeek model; another
PACC collector executes backward/optimizer steps. Thus the captures establish
real observed two-rank NCCL AllGather kernel events but leave workload phase and
collection provenance unresolved. Even if the forward-only interpretation is
correct, this is a fixed-input FSDP model forward, not autoregressive vLLM
serving or VLA inference. The PCIe V100 setup also does not establish H100/NVLink
behavior.

The reusable checker classifies each file as
`forward_only_candidate_requires_provenance`; that deliberately is not an
acceptance result. The original traces and event excerpts remain in the local
`.pi/inference-capture-audit/` cache; no trace data was copied into the repo.

## Reusable rejection check

`tracks/t3-topology/data/public-inference/audit_torch_trace.py` reads Chrome
trace events and emits a JSON audit. It rejects observed backward/optimizer
activity, records CPU collective events separately from NCCL GPU kernels, and
retains source event indices, timestamps, shapes/dtypes and kernel durations.
It does not pair host/GPU or cross-rank operations by guesswork.

A candidate without backward events is explicitly classified
`forward_only_candidate_requires_provenance`, **not accepted inference**.
CPU host-call duration is not GPU completion latency; Chrome event timestamps
and durations are in microseconds, regardless of the viewer's `displayTimeUnit`.

Checks run in the background, exit 0:

- `python3 tracks/t3-topology/data/public-inference/audit_torch_trace.py --self-test`
- both real Llama rank files returned the expected rejection exit code 2;
  assertions verified 85 CPU calls, 85 GPU kernels, and training rejection;
- source-ledger check confirmed Gather bytes remain explicitly assumed.

## Paper-table correction

[arXiv:2507.14392v1](https://arxiv.org/html/2507.14392v1), Section V-A, states that
AllReduce counts are independent of TP degree; Table III reports equal counts
for TP=2 and TP=4. This supports interpreting counts as collective calls, not
summed rank invocations, but supplies no per-rank timeline. Section IV-B excludes
rank-0 profiles. Table IV establishes AllReduce byte sizes, **not Gather dtype**;
the existing Gather byte estimate assumes two-byte elements and is now labeled
as such.

The previous BookSim result is an **execution smoke test of a paper-informed
synthetic scenario**. It does not validate inference fidelity or a topology
ranking. Its fixed round gap is open-loop, not a completion-dependent barrier.

## Result and remaining work

No multi-GPU inference capture has been accepted. We did find real observed
NCCL AllGather kernel intervals, but the available source does not establish
that those files came from inference. Treat them as an ambiguous forward/NCCL
segment only, not as a truthful serving workload. The next dependency is a
provenance-verified serving capture or approved multi-GPU hardware access—not
more invented packet detail.
