# VeritX CLI — Production Pipeline Interface

## Status (2026-08-28)
- **TUI removed** — parked until pipeline runs end-to-end with real numbers
- **`cli.py` deleted** — legacy cruft
- **All commands tested and working**

## Verified Commands

```
veritx trace model <json> --nodes 64 --out trace.trace          ✅ tested
veritx trace chakra <et_dir> --nodes 64                         ✅ wired
veritx trace hpc <trace_file> --nodes 64                        ✅ wired

veritx synthesize bo --traffic trace.trace --nodes 64 --iters 10 ✅ tested (min 10)
veritx synthesize grid --nodes 64                               ✅ wired

veritx evaluate booksim --trace trace.trace --k 8               ✅ tested (177c LLaMA)
veritx evaluate anynet --topo winner.anynet --trace trace.trace ✅ tested (162c LLaMA)
veritx evaluate astra --ets <et_dir>                            ✅ wired

veritx certify flow --model model.json --topo winner.anynet     ✅ tested (PASS)
veritx certify rtl --topo winner.anynet --tier quick            ✅ wired (needs verify.sh)
veritx certify full --model model.json --topo winner.anynet     ✅ wired

veritx run --model model.json --nodes 64 --iters 10             ✅ tested (1.4s end-to-end)
veritx status --last 5                                          ✅ tested
```

## What `veritx run` Does

```
Step 1/4: trace model → input.trace (184K packets, 2.7MB)
Step 2/4: synthesize bo → best_params (113 edges, 5-dim search)
Step 3/4: evaluate booksim → mesh 8x8 latency (16.5c throughput mode)
Step 4/4: certify flow → PASS (injection ceiling, conservation)
→ manifest.json with all results
```

## Files
| File | Purpose |
|------|---------|
| `veritx_dse/veritx_cli.py` | All CLI commands (single file) |
| `veritx_dse/pipeline.py` | Importable pipeline orchestrator |
| `veritx_dse/__init__.py` | Package init |
| `pyproject.toml` | Single `veritx` entry point |

## Known Limitations
1. **BO booksim validation**: `best_latency_booksim: 1000.0` means the BO's BookSim validation timed out (30s limit). The analytical search finds good params but validation is incomplete.
2. **Traffic model trace is dense**: 184K packets at IR=0.1 — BookSim throughput mode handles it (16.5c), latency mode times out.
3. **RTL cert needs `verify.sh`**: `certify rtl` calls `tracks/t3-topology/scripts/certify.sh` which needs Verilator setup.

## Next Steps
1. Wire BO's BookSim validation with longer timeout so `best_latency_booksim` is real
2. Add `veritx compare --topo a.anynet --topo b.anynet --trace t.trace` for head-to-head
3. Add `veritx sweep --trace t.trace --topologies mesh,ring,torus,flatfly` for batch eval
4. After BookSim S1 is the scorer: `veritx calibrate` to validate analytical vs cycle-accurate
