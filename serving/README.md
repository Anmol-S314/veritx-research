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

2. Build ASTRA-sim with the BookSim2 backend:

   ```bash
   cd serving/astra-sim
   # per the original build: cmake + make with the booksim2 frontend
   # (protobuf 3.21.12 from source was required for Chakra trace parsing)
   ```

3. Generate the slice trace and run the 3-way comparison:

   ```bash
   cd serving/astra-sim/astra-sim/network_frontend/booksim2/examples
   python3 gen_qwen_slice.py   # emits the Qwen3 slice (first 12 comm ops)
   # then run the backend with the analytical / unicast / multicast-fold configs
   ```

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