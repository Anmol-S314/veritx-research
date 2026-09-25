# Production Workload Trust (C5)

Levels and their current state. A workload is trusted only when it has a
content-addressed manifest and passes the independent checks for its level.

| level | meaning | state |
|-------|---------|-------|
| W0 micro-oracle | hand-verifiable fabric/workload; exact expected counts | **RUN** — experiments V01–V14 |
| W1 model-realistic | Llama-3.1-8B/70B, Qwen3-32B, Qwen3-30B-A3B, Mixtral-8x7B | **MANIFESTS OWED** (matrix drafted in `docs/validation/PRODUCTION-WORKLOAD-MATRIX.md`) |
| W2 serving-realistic | short/long-context prefill/decode, mixed, burst/steady, multi-instance, TP/DP/EP | **OWED** (blocked by C7 qualification and `.et` fixtures) |
| W3 stress | hotspot, all-to-all, large collectives, skew, near-saturation, high concurrency | **OWED** |

## W0 evidence (this candidate)

```text
V01 2-node P2P                      PASS
V02 ALLREDUCE 4x4 (k=16)            PASS
V03 ALLTOALL 4x4                    PASS
V04 link-width monotonicity         PASS
V05..V10 P2P / compute / memory     PASS
V11 ALLGATHER k=16                  PASS
V12 REDUCESCATTER                   PASS
V13 BROADCAST non-zero root         PASS (needs F-0007 window fix)
V14 ALLGATHER k=2                   PASS
```

Each W0 experiment reports independent-oracle checks (hand arithmetic, ring
law, graph law) plus semi-independent standalone parity, not production
self-agreement. Only network-level collective semantics are claimed;
chunk ownership is not modeled.

## Trust rules

- Every workload must carry a content-addressed manifest
  (`physical_traffic_id`, `message_artifact_id`, prepared identity).
- A model is used only if the pipeline supports it; unsupported models
  refuse, they are not approximated for breadth.
- A workload result is only trusted when the backend conservation gate and
  (for certified claims) producer admission pass.
