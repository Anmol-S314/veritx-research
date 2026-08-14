# ASTRA-sim serving leg: Qwen3-30B-A3B slice through our BookSim2 multicast fabric

**Status: first serving-level result, network-only scope. Date: 2026-08-14 (jane).**

## What was run

| ingredient | value |
|---|---|
| workload source | LLMServingSim per-batch trace, Qwen3-30B-A3B-Instruct-2507, `instance0_batch0.txt` (run_1786643546936153_195056) |
| slice | first 12 comm ops of the batch (6× ALLREDUCE 8 MiB + 6× ALLGATHER 2.1 MiB = 63.7 MB) |
| model | 4 NPUs (2 dies × 2), 2×2 mesh, snake routing, 4 VCs, iSLIP, 8 B flits @ 1 ns/cycle (8 GB/s links) |
| simulators | ASTRA-sim 2.0 (master 518bd51) + our booksim2 fork as the network backend (`AstraSim_BookSim2`); analytical backend as reference |
| mapping | ALLREDUCE → native ring (no multicast benefit); ALLGATHER → BROADCAST (MoE dispatch one-to-k semantics, root=rank 0); REDUCESCATTER/REMOTE not present in slice |

## Measured result — the three-way table (all at 8 GB/s links)

| backend | completion (all 4 ranks) | wall |
|---|---|---|
| analytical (congestion-free latency model) | 10,495,246 cycles | 0.1 s |
| booksim2 fabric, unicast (source-fork) | 15,295,386 cycles | 12 s |
| booksim2 fabric, multicast fold (bridge-fork) | 13,885,374 cycles | 109 s |

- Analytical vs unicast fabric: 1.46x — the queueing/congestion gap the
  cycle-accurate fabric pays and the latency model ignores.
- Fold vs unicast on the SAME fabric: **9.2% faster**, simultaneous completion.
- Fold wall time is higher: per-flit packets cost more simulator time; the
  CYCLE count is the network claim (in a real NIC the stream machinery is
  hardware).

Fold record: 6 multicast folds with k=3 (each dispatch collapsed 3 concurrent sends into
1 stream per flit), 576 k=1 (ring allreduce sends, unicast fallback).

Mechanism arithmetic: the dispatch class is 20.7% of the slice's bytes; multicast cuts its
injection 3× (one stream delivers to 3 nodes). The ALLREDUCE class (79.3%) is ring-based
and gains nothing — hence 9.2% total, not 3×. Under dispatch-dominated load the gap widens
(the trace_pipeline 15-21% / 3.43x headroom numbers were pure dispatch geometry).

## Claim scope (seed 5de1 discipline)

- **NETWORK-LEVEL claim only**: a communication-only timeline of one batch slice on a
  cycle-accurate fabric. NOT end-to-end serving; no compute, no KV-remote memory traffic
  (REMOTE ops excluded, <0.1% of bytes), no gem5/ASTRA-sim full-stack.
- The ALLGATHER→BROADCAST mapping is the MoE-dispatch semantics (one-to-k fanout).
  Ring-based ALLGATHER implementations would not benefit — the claim is dispatch-scoped.
- Routing constraint (honest): the mcast stream follows the snake, so a mid-snake source
  cannot reach nodes behind it (dispatch roots constrained to rank 0 in this demo). On the
  bridged_2die fabric, dispatch geometry should align expert placement with the route.
- Flit granularity 8 B @ 1 ns matches the bridge model in
  `serving_level_headroom.json` (8 B flit @ 1 GHz).

## Reproducibility

- ASTRA-sim: github.com/astra-sim/astra-sim @ 518bd51 (cloned 2026-08-14); booksim2 fork:
  repo `third_party/booksim2` + `veritx_embed.{hpp,cpp}` embedding API (dev copy
  /var/tmp/r1work/booksim2-embed); protobuf 3.21.12 built from source (no sudo) at
  /var/tmp/r1work/protobuf-install.
- Build: `build/astra_booksim2/build.sh` (cmake, -j2, PROTOBUF_FROM_SOURCE=True,
  CMAKE_PREFIX_PATH=/var/tmp/r1work/protobuf-install).
- Trace gen: `astra-sim/network_frontend/booksim2/examples/gen_qwen_slice.py`
  <llmserving trace> 4 12 /var/tmp/r1work/qwen_slice.
- Run: `AstraSim_BookSim2 --workload-configuration=/var/tmp/r1work/qwen_slice/qwen_slice
  --system-configuration=examples/system/native_collectives/Ring_4chunks.json
  --remote-memory-configuration=examples/remote_memory/analytical/no_memory_expansion.json
  --network-configuration=astra-sim/network_frontend/booksim2/examples/4npus_snake.cfg
  --booksim2-extra="injection_rate=0.0" [--booksim2-mcast-fold=true]`
- Logs: /tmp/opencode/qwen_nofold.log, qwen_fold4.log (VERITX_DEBUG=1).
