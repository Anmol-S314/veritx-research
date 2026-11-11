# Public inference evidence and paper-informed synthetic projections

**Not yet a validated inference traffic workload.** The paper tables lack raw
rank/timestamp events; the Qwen counter scale is unresolved. The BookSim run
only validates execution of an assumed traffic scenario, not inference fidelity,
NCCL performance, or topology superiority. Raw-capture checks and rejection
evidence are recorded in
[`docs/research/inference-capture-audit.md`](../../../../docs/research/inference-capture-audit.md). `audit_torch_trace.py` rejects training events and preserves
separate host collective and GPU kernel observations; a forward-only candidate
still requires provenance review.

This directory holds two independent evidence sources. **Do not merge their
numbers:** they are different models, hardware and telemetry.

## Llama-3.1-8B, TP=4: measured collective ledger

`llama31-8b-tp4/collectives.json` transcribes Table III of Xu et al. and
cross-checks the AllReduce message sizes against Table IV:

- vLLM 0.8.5.post1, PyTorch 2.6, NCCL 2.21.5;
- one request, prefill 128 tokens / decode 128 tokens;
- 4 H100s connected by intra-node NVLink;
- profiler reports 65 prefill and 8,255 decode AllReduce calls, plus Gather
  calls, with tensor shapes and message sizes.

These are **paper-reported operation counts and tensor shapes**, not locally
inspected profiler events. Section V-A states that AllReduce counts are
independent of TP degree, and Table III gives the same counts for TP=2 and TP=4.
This supports interpreting them as collective calls, not summed rank invocations;
it does not establish a raw per-rank timeline. Table IV reports AllReduce bytes,
but the Gather byte estimates assume two-byte elements—the Gather dtype is not
independently established and must not be called measured. The paper does not publish per-operation
rank/timestamp traces or the selected NCCL algorithm. Therefore this file is
not directly convertible to a truthful `cyc src class dst flits` trace. Any
simulator projection must separately declare rank mapping, collective
expansion, packetization, injection schedule, and topology; those are model
assumptions, not measurements.

Source: [arXiv:2507.14392](https://arxiv.org/abs/2507.14392), Tables II–IV.

## Qwen3-30B, EP=4: measured link-counter samples

`cal26-qwen3-30b-ep4/` contains the published inference rows from the CAL26
release:

- `nvlink-counter-samples.csv`: CUPTI-sampled NVLink bandwidth and other GPU
  performance counters over time for vLLM Qwen3-30B DeepEP inference;
- `inference-kernel-slowdowns.csv`: measured kernel slowdowns in the inference
  overlap experiment.

This is a **published counter series from a real inference experiment**, not
per-rank messages or packet events. It is not the same model/run as the Llama
profile above. Important quality check: the published `nvlink_GBps` values in
the DeepEP panel are only about `1e-7` to `5e-7` GB/s (with other panels near
zero), despite the figure-data README naming a 900 GB/s measured peak. The
upstream exporter divides its `nvl` column by `1e9`; the counter's raw unit /
scale is not independently established here. Therefore **do not use these
values as a calibrated bandwidth target yet**. They remain useful provenance
and a lead to the original captures, not validated traffic magnitudes.

Source repository: [yechen3/CAL26-NCCL-GEMM-data](https://github.com/yechen3/CAL26-NCCL-GEMM-data). The plotted data is from [Zenodo v1.0.0](https://zenodo.org/records/21925183), licensed CC BY 4.0. The 1.7 GB raw Nsight captures are linked from the repository but are not included here.

## Paper-informed synthetic BookSim projection

`llama31-8b-tp4/project_ring.py` interprets the reported counts as a repeated
four-rank operation schedule and expands it into a **synthetic ring projection**,
not an observed NCCL trace. That interpretation does not establish the paper's
rank-specific communication schedule. It is useful for
smoke-testing BookSim and comparing explicit fabric scenarios. The script pins
the assumptions in its trace header: clockwise 4-rank ring, 256-bit flits,
16-flit packets, one packet/source/cycle, a fixed 32-cycle round barrier, and
zero compute gaps. Gather is projected as direct sends from ranks 1–3 to rank 0.
None of those transport/timing choices is asserted by the paper.

The smoke projection is one prefill AllReduce/Gather plus one full 65-AllReduce
decode token/Gather. The full projection preserves the paper's 65 prefill and
8,255 decode AllReduce counts plus 1/127 Gather counts, but its serialized
zero-compute schedule is deliberately a traffic stress scenario, not measured
request timing. The BookSim run record, exact assumptions, trace hash, and
results are in `llama31-8b-tp4/projection-results.md`. The exact source ledger
remains the measured artifact; any simulator result must be labeled *projected*.
