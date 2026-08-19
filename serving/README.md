# Serving-leg — ASTRA-sim / LLMServingSim evidence bundle

Isolated branch: **serving-leg** — the ASTRA-sim serving-leg research track.

This branch contains the complete evidence chain for the serving-level claim
(Qwen3-30B-A3B MoE dispatch, multicast fold, 3-way comparison), with the code
needed to regenerate and re-run it. Everything here is vendored from the
working dirs it was developed in; nothing depends on files outside this branch.

## Layout

```
serving/
  astra-sim/            ASTRA-sim 2.0 engine + our BookSim2 network backend
    astra-sim/            engine core (Sys/Workload/analytical/ns3 frontends)
    network_frontend/booksim2/  OUR wrapper (Booksim2NetworkApi.cc, main.cc, gen_qwen_slice.py)
    extern/network_backend/booksim2/  OUR fabric wrapper (Booksim2Fabric.cc/hh) + fork ref
    extern/graph_frontend/  Chakra trace converter (vendored flat)
    extern/helper/         fmt/spdlog/json/cxxopts (vendored flat)
  booksim2-embed/       Our embed API + the BookSim 2.0 fork source
    src/                  full fork source + veritx_embed.{cpp,hpp} + Makefile
  LLMServingSim/        The serving simulator (trace generator + profiler + evidence)
    serving/              trace generation pipeline source
    profiler/perf/        MEASURED module latencies (RTXPRO6000 torch hooks) — the timing evidence
    traces/run_1786643546936153_195056/  THE CITED RUN — .et traces + configs (832K)
    workloads/            input workload JSONLs (swe-bench-qwen3 = the cited workload)
    configs/              cluster/model configs
  results/              The 3-way comparison results (moved from tracks/t3-topology/results/trace_pipeline/)
```

## Pinned versions

| Component | Source | Pin |
|---|---|---|
| ASTRA-sim | /var/tmp/r1work/astra-sim | 518bd51 ("update ns3 submodule (#366)") |
| booksim2-embed | /var/tmp/r1work/booksim2-embed | not a git repo (developed in place) |
| LLMServingSim | /var/tmp/opencode/LLMServingSim | 2c2042c ("Merge pull request #57") |

## Reproducing the result

1. Build the BookSim2 fork (embed API):

   ```bash
   cd serving/booksim2-embed
   ./veritx-rebuild.sh
   ```

2. Build the `AstraSim_BookSim2` binary. The frontend is wired by the
   orchestrating CMakeLists in `serving/astra-sim/build/astra_booksim2/`
   (it adds the engine as `AstraSim`, the fabric backend as `BookSim2Fabric`,
   and the wrapper as `AstraSim_BookSim2` — the top-level astra-sim
   CMakeLists does NOT add the frontend on its own):

   ```bash
   mkdir -p /tmp/serving-build && cd /tmp/serving-build
   BOOKSIM2_SRC_DIR=<path-to>/serving/booksim2-embed \
     cmake <path-to>/serving/astra-sim/build/astra_booksim2
   cmake --build . -j2
   # binary: /tmp/serving-build/bin/AstraSim_BookSim2
   ```

   protobuf 3.21.12 (or newer with matching headers) is required for Chakra
   trace parsing; the system `libprotobuf` is found automatically.

3. Generate the slice trace (needs Chakra's Python stubs on `PYTHONPATH`):

   ```bash
   TRACE=<path-to>/serving/LLMServingSim/traces/run_1786643546936153_195056/trace/\
   RTXPRO6000/Qwen/Qwen3-30B-A3B-Instruct-2507/instance0_batch0.txt
   PYTHONPATH=.../serving/astra-sim/extern/graph_frontend/chakra/src/third_party/utils:\
   .../serving/astra-sim/extern/graph_frontend/chakra/schema/protobuf \
     python3 .../serving/astra-sim/astra-sim/network_frontend/booksim2/examples/gen_qwen_slice.py \
     $TRACE 4 12 /tmp/qwen_slice
   ```

4. Run the 3-way comparison (from `serving/astra-sim` so relative config paths resolve):

   ```bash
   # analytical + unicast + multicast-fold:
   AstraSim_BookSim2 \
     --workload-configuration=/tmp/qwen_slice/qwen_slice \
     --system-configuration=examples/system/native_collectives/Ring_4chunks.json \
     --remote-memory-configuration=examples/remote_memory/analytical/no_memory_expansion.json \
     --network-configuration=astra-sim/network_frontend/booksim2/examples/4npus_snake.cfg \
     --booksim2-extra="injection_rate=0.0" \
     [--booksim2-mcast-fold=true]
   ```

   Verified 2026-08-19: multicast-fold reproduces the documented
   **13,885,374 cycles** bit-exact; unicast gives 15,625,155 (the 15,295,386 in
   the results JSON predates a 22:36 code edit in Booksim2NetworkApi.cc — fold
   path unchanged).

4. The evidence JSONs: `serving/results/*.json`

## Provenance

The original run logs referenced in the results JSON:
`/tmp/opencode/qwen_nofold.log`, `qwen_fold4.log` (VERITX_DEBUG=1).
These are NOT vendored (they are run artifacts) — the .et traces and configs in
`serving/LLMServingSim/traces/` are the reproducible inputs.

## Safety

This branch is a PRUNED copy of t3-rtl-noc. The NoC RTL track (router.sv,
mesh.sv, Verilator co-sim gate, formal verification) lives on the `t3-rtl-noc`
branch and is untouched by this branch's existence.