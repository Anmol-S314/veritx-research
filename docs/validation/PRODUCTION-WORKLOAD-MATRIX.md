# Production Workload Matrix — W0/W1/W2/W3 Proposal

Status: DRAFT v1 (baseline audit at `prod/production-readiness`, up to and
including the P0.10 route-observation closure `c2748f9a`/`bd973e6c`)
Location when implemented: `validation/production_workloads/`

Each workload gets a manifest (`workload_id`, model, precision, TP/DP/EP/PP,
serving mode, request count, arrival distribution, token distributions,
collectives, source, source digest, classification, notes). The scientific
portion is content-addressed.

## Level W0 — Micro-oracle workloads

Purpose: exact mechanics, ASTRA timing-component validation, packet/flit
counts, route observation. All answers computable by hand or independent
arithmetic. These extend the existing V01–V10 corpus.

| id | workload | expected answer source |
|----|----------|------------------------|
| W0-01 | 2 endpoints, one P2P transfer, 4×4 mesh | hand arithmetic (hops, cycles, flits) |
| W0-02 | 4-node mesh, deterministic XY route | hand route table `(src,dst)→next hop`; also exercises the P0.10 first-hop dump comparison (`c2748f9a`) end-to-end on a hand-known table |
| W0-03 | 2-rank collective (ring ALLREDUCE, k=2) | hand ring arithmetic |
| W0-04 | 4-rank ring ALLREDUCE | ring oracle (existing V09-class check, extended) |
| W0-05 | single memory operation through Ramulator wrapper | battery-equivalent drain counters |
| W0-06 | single compute op + one collective (the `astra_tiny` shape, 16 ranks) | cycle-accounting table: declared compute + network transfer + endpoint delay + collective scheduling = total. **This is the instrument for F-ASTRA-0001** |
| W0-07 | 2-rank P2P through ASTRA+BookSim | independent arithmetic oracle; classifies the ASTRA-vs-canonical comparison as SHARED ENGINE DIFFERENTIAL, never independent |
| W0-08 | ALLGATHER k=4 (chunk semantics: each rank sources distinct chunk) | per-step src/dst/participants/bytes table, independent of implementation under test |
| W0-09 | REDUCESCATTER k=4 | same discipline; payload semantics per §11 |
| W0-10 | ALLTOALL k=4 (direct) | same |
| W0-11 | BROADCAST k=4 (tree and ring variants if both exist) | same |

## Level W1 — Component-realistic workloads

Model configs already in-repo (`third_party/llmservingsim/configs/model/`).
Every model must traverse the full canonical pipeline; config presence alone
confers no status. Provenance recorded per manifest.

| id | model | shape (L/H/kv/experts) | parallelism | scenario class | notes |
|----|-------|------------------------|-------------|----------------|-------|
| W1-01 | Llama-3.1-8B | 32/4096/8/– | TP1 | OFFLINE, single instance | profiler data exists (RTXPRO6000 bf16 tp1/tp2) |
| W1-02 | Llama-3.1-8B | TP2 | SERVER, steady | — |
| W1-03 | Qwen3-32B | 64/5120/8/– | TP1/TP2 | OFFLINE + SERVER | profiler data exists |
| W1-04 | Qwen3-30B-A3B (MoE) | 48/2048/4/8 active | TP1, EP where supported | OFFLINE + SERVER | profiler data exists |
| W1-05 | Mixtral-8x7B | 32/4096/8/8 active | TP1 | OFFLINE | no profiler data — synthetic compute model, recorded as such |
| W1-06 | Llama-3.1-70B | 80/8192/8/– | TP2/TP4 if supported | OFFLINE, memory-feasibility-gated | mark UNSUPPORTED cell if it cannot fit |

## Level W2 — Serving-realistic workloads

Request distributions, not uniform traces. Existing assets:

- `workloads/workload_me2_01_mixed.jsonl` (608 requests, mixed) — **primary**
- `workloads/shared_prefix_30.jsonl` (30, shared-prefix)
- `workloads/longctx_shared_4k_10.jsonl`, `longctx_shared_8k.jsonl` (long context)
- `workloads/dual_512_10.jsonl`, `example_trace.jsonl` (small/interactive)
- `workloads/generators/sharegpt.py` — ShareGPT-derived generator; use where
  the trace license permits; record source + digest in the manifest
- `workloads/generators/` — synthetic arrival-pattern generators for the rest

| id | distribution | arrival | serving mode | mixes |
|----|--------------|---------|--------------|-------|
| W2-01 | mixed (me2_01) | steady, low QPS | SERVER | prefill/decode mixed |
| W2-02 | mixed (me2_01) | steady, near-saturation QPS (found via W3-style probe) | SERVER | — |
| W2-03 | mixed (me2_01) | burst (step arrivals) | SERVER | — |
| W2-04 | short interactive (example_trace class) | Poisson-ish steady | SERVER | short prompts, short outputs |
| W2-05 | long context (4k/8k shared prefix) | steady | SERVER | prefill-heavy |
| W2-06 | mixed | arrival-time-driven, all-at-once | OFFLINE | throughput-focused |
| W2-07 | mixed | — | SERVER | decode-heavy (long outputs) |
| W2-08 | mixed | burst | SERVER | multi-instance (2/4 instances), TP2, DP/EP where supported |

OFFLINE metrics: completed req/s, tokens/s, fabric utilization, completion
cycles. SERVER metrics: TTFT, end-to-end latency, decode latency where
modeled, throughput, queue depth, tail latency. Do not claim MLPerf
compliance — benchmark discipline only, no trademark.

## Level W3 — Stress and boundary workloads (label: STRESS)

Not PRODUCTION_TYPICAL. Purpose: find the edges.

| id | stressor | note |
|----|----------|------|
| W3-01 | all-to-all pressure | saturates every link |
| W3-02 | ring concentration | single-dimension ring on mesh |
| W3-03 | hotspot traffic | one destination takes λ× traffic |
| W3-04 | large collective (payload sweep ×10/×100 of W0-04) | packetization scaling |
| W3-05 | many concurrent instances (4–16) | liveness under load, per-instance ledger (§21) |
| W3-06 | long decode (output ≤ 4k tokens) | sustained decode rounds |
| W3-07 | large context (32k if memory permits) | prefill burst |
| W3-08 | bursty arrivals at knee | pairs with §15 saturation sweep |
| W3-09 | instance/tenant skew | imbalance, per-instance progress exposed |
| W3-10 | MoE expert skew (if modeled) | gate imbalance; mark UNSUPPORTED if gate skew not modeled |
| W3-11 | remote memory pressure (if supported) | CXL config exists; mark reachability first |

## Realism / calibration bookkeeping (§7)

Every experiment record carries both, never conflated:

```text
WORKLOAD_REALISM:      SYNTHETIC | TRACE_DERIVED | PROFILE_DERIVED | REAL_REQUEST_DISTRIBUTION
HARDWARE_CALIBRATION:  NONE | COMPONENT_CALIBRATED | BACKEND_VALIDATED | HARDWARE_MEASURED
```

Current honest defaults: W0 = SYNTHETIC / BACKEND_VALIDATED (BookSim domain);
W1/W2 = TRACE_DERIVED / NONE unless profiler-coupled compute is used
(COMPONENT_CALIBRATED for RTXPRO6000 tp1/tp2 rows only); W3 = SYNTHETIC / NONE.

## Saturation sweep plan (§15)

For W1-02, W2-02, W2-03: sweep offered load / QPS over
{low, medium, near-knee, post-knee}. Track throughput, avg latency, p95/p99
where supported, completion, queueing, link utilization (only if per-link
artifact exists), flit stalls. Locate the knee empirically; never extrapolate
past measured points. Known blocker: current trace model cannot inject faster
than 1 packet/cycle (F-0003), so network-side saturation needs the burst
injection model or ASTRA-side arrival driving — record which path was used.

## Tolerance pre-registration (§24)

Before any W1/W2 comparison run, record: metric, expected model error,
tolerance, rationale. A post-hoc tolerance change is prohibited; a miss is a
finding (§55), not a tuning signal.
