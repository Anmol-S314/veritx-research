# serving/ -- ASTRA-sim / LLMServingSim evidence bundle

Vendored third-party tools for multi-die simulation and trace generation.

## What's here

```
serving/
  astra-sim/            ASTRA-sim 2.0 engine + BookSim2 network backend
    astra-sim/            engine core (Sys/Workload/analytical/ns3 frontends)
    network_frontend/booksim2/  BookSim2 wrapper (Booksim2NetworkApi.cc, main.cc)
    extern/
      graph_frontend/   Chakra trace converter
      helper/           fmt/spdlog/json/cxxopts
    build/astra_booksim2/  CMake build system
    examples/           network/system/workload configs
  LLMServingSim/        Traffic trace generator (KAIST)
    serving/            trace generation pipeline source
    profiler/           MEASURED module latencies (RTXPRO6000 torch hooks)
    traces/             THE CITED RUN -- .et traces + configs
    workloads/          input workload JSONLs
    configs/            cluster/model configs
  results/              3-way comparison results
  README.md             this file
```

## Pinned versions

| Component    | Source                 | Pin                                            |
|--------------|------------------------|------------------------------------------------|
| ASTRA-sim    | /var/tmp/r1work/astra-sim | 518bd51 ("update ns3 submodule (#366)")        |
| LLMServingSim | /var/tmp/opencode/LLMServingSim | 2c2042c ("Merge pull request #57") |

## How VeritX CLI uses these

- `veritx_dse/paths.py` defines `ASTRA_DIR`, `LLMSIM_DIR`, `ASTRA_BS_BIN`, `CHAKRA_TO_ET`
- The CLI shells out to `AstraSim_BookSim2` for multi-die simulation
- LLMServingSim generates traffic traces that feed into BookSim2

## Rebuilding ASTRA-sim

```bash
cd serving/astra-sim/build/astra_booksim2
BOOKSIM2_SRC_DIR=../../third_party/booksim2 cmake .
cmake --build . -j$(nproc)
# Binary: serving/astra-sim/astra-sim/network_frontend/booksim2/bin/AstraSim_BookSim2
```

Requires: protobuf 3.21.12+ (for Chakra trace parsing).

## Syncing BookSim2 source

The canonical BookSim2 source lives in `third_party/booksim2/src/`. ASTRA-sim has its own copy at `serving/astra-sim/extern/network_backend/booksim2/booksim2/src/`. After editing BookSim2 source:

```bash
third_party/booksim2/sync_to_astra.sh
```

## What was removed (cleanup 2026-08-31)

- `booksim2-embed/` -- near-duplicate of `third_party/booksim2/` (133/138 src files identical). The canonical copy is in `third_party/`.
- `LLMServingSim/docs/` -- Docusaurus web frontend (not needed for trace generation)
- `LLMServingSim/bench/` -- benchmarking code (not needed for trace generation)
- `LLMServingSim/.github/` -- CI config (not needed)
- Build artifacts (`build_debug/`, `lib/`, CMake caches) -- not in git, cleaned from disk

Recovery: `git checkout backup-pre-serving-cleanup -- serving/`
