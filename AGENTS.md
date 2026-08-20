<!-- seeds:start -->
## Issue Tracking (Seeds)
<!-- seeds-onboard:v0.5.9 -->
<!-- seeds-onboard-schema:7 -->

This project uses [Seeds](https://github.com/jayminwest/seeds) v0.5.9 for git-native issue tracking.

**At the start of every session**, run:
```
sd prime
```

This injects session context: rules, command reference, and workflows. Pass `--format json|compact|markdown|plain|ids` on any command for agent-friendly output.

**Quick reference:**
- `sd ready` — Find unblocked work
- `sd search <query>` — Full-text search across titles + descriptions
- `sd create --title "..." --type task --priority 2` — Create issue
- `sd update <id> --status in_progress` — Claim work
- `sd close <id>` — Complete work
- `sd dep add <id> <depends-on>` — Add dependency between issues
- `sd sync` — Sync with git (run before pushing)

### Planning
Use `sd plan` when work is large or ambiguous enough that an LLM benefits from structured decomposition. Submit spawns one child seed per step; `step.blocks` uses forward semantics (step i with `blocks: [j]` means step i blocks step j, and step j gets step i's id in its `blockedBy`).

- `sd plan templates` — List built-ins (`feature`, `bug`, `refactor`) plus custom templates
- `sd plan prompt <seed-id>` — Emit a structured prompt the LLM fills in
- `sd plan submit <seed-id> --plan <file>` — Validate + spawn child seeds
- `sd plan show <pl-id>` — View sections, children, sub-plans
- `sd plan edit <id> [--name | --section <name> <text> | --step <i> --title/--priority/--type]` — In-place field edits; bumps revision
- `sd plan outcome <pl-id> --result success|partial|failure` — Record outcome (storage-only)
- `sd plan review <pl-id> --by <name>` — Record reviewer (informational)

### Before You Finish
1. Close completed issues: `sd close <id>`
2. File issues for remaining work: `sd create --title "..."`
3. Sync and push: `sd sync && git push`
<!-- seeds:end -->

<!-- comms:start -->
## Agent Comms (mandatory startup ritual)

Read these at the start of EVERY session, before doing anything:

```
bash comm/check.sh <your-name>     # unread mail addressed to you
bash comm/read.sh status           # canonical live state (single source of truth)
bash comm/read.sh alerts           # blockers and build hazards
```

- **Your name** is one of: `laura`, `dave`, `junior`, `steve`.
- **Send mail**: `bash comm/send.sh -f <you> <to> "<subject>"` (p2p)
- **Broadcast**: `bash comm/publish.sh -f <you> <topic> "<subject>"` (topics: status/decisions/alerts/questions)
- **Update state**: when you change something material (a build, a fix, a closure), publish to `status` or `alerts` so others see it without polling.
- **Before launching a build**: check `comm/read.sh alerts` + inbox — ONE build at a time (RAM rule, GATE-R1-COORD.md). The box kills concurrent/long builds.
- **Never** edit another agent's unread message; commit `comm/` after sending.
<!-- comms:end -->

<!-- tooling:start -->
## Tooling & Install Location (mandatory)

- **ALWAYS install venvs, model caches, and downloaded research repos INSIDE this repo** (e.g. `<repo>/kronos/`, `<repo>/research-vendor/`). We have ~60G free on the real disk — use it.
- **NEVER use `/tmp` for installs, venvs, or model downloads.** `/tmp` is tmpfs (RAM-backed, ~7G) — a torch/CUDA install blows the quota, and RAM is our bottleneck (14G total).
- The repo venv for trading-stack is `trading-stack/.venv` (uv-managed). New research tooling gets its own venv under the repo, e.g. `<repo>/kronos/venv`.
- Add a one-line note here under `## Tooling & Install Location` whenever you add a new vendored tool, so future sessions know where it lives and why.
- Vendored 2026-08-17: `kronos/` — Kronos-base OHLCV foundation model (Tsinghua, AAAI 2026) + CUDA torch venv (`kronos/venv`, torch 2.11+cu128, skfolio 0.20.2, yfinance 1.6.0). Stocks OOS: NO EDGE (40.6% vs 1/N 53.5% vs SPY 76.7%). Crypto 1h native domain: 58% directional hit-rate (real, p=0.0007) but weekly top-3 backtest −48.6% vs EW −30.7% vs BTC +9.3% over 102 weeks — turnover eats the thin signal. fp16+ctx256 confirmed 4.2x speedup (41.9s/batch). Runners: `research/kronos_oos_test.py` (stocks), `kronos/kronos_crypto_backtest.py` (crypto). See PLAYBOOK.md.
- Vendored 2026-08-17: `timesfm/` — TimesFM 2.5 (Google, 200M params, 16k context) + CUDA torch venv (`timesfm/venv`, torch 2.11+cu128, peft, accelerate, transformers). Zero-shot: −35.5% vs Kronos −48.6% (better but still loses to baselines). LoRA fine-tuned: catastrophic overfitting (IS +437% vs OOS −20%). Speed advantage: 1.4s/week vs Kronos 42s/week, 0.88GB VRAM. Runners: `timesfm/timesfm_backtest.py` (zero-shot), `timesfm/finetune_crypto.py` (LoRA), `timesfm/timesfm_finetuned_backtest.py` (fine-tuned OOS). See PLAYBOOK.md.
- Vendored 2026-08-17: `trading-stack/vibe-trading/` — sparse clone of HKUDS/Vibe-Trading (agent/backtest/engines only), kept for the IndiaEquity delivery cost-stack reference (STT/exchange/SEBI/GST/stamp defaults cross-checked vs our flat 40bp India assumption).
- Vendored 2026-08-18: `LLMServingSim` (pre-existing at `/var/tmp/opencode/LLMServingSim`) — its ASTRA-Sim **ns-3 cycle-accurate network backend** now BUILDS and runs (was blocked by GCC 15.2.0 + Python 3.14 + memory-config issues). Fixes applied in-tree: `ns3` script argparse positional `store_true`→`nargs="?"` (6 spots, Py3.14), `addWorkload`→`add_workload(filename, systems)` API, qualified all unqualified `format(`→`fmt::format(` in `spdlog_setup/{conf,details/conf_impl,details/template_impl}.h` (GCC 15 `<format>` ambiguity). Runtime gotchas: memory config must be `PER_NODE_MEMORY_EXPANSION` with `num-devices` set (ET traces contain mem ops; `NO_MEMORY_EXPANSION` aborts); topology/output paths in `scratch/config/config*.txt` are relative to ns-3 root; workload base path appends `.N.et`; sim waits at stdin for `exit` after completion. Verified end-to-end: Qwen3-30B-A3B dp_A_batch0 on 4-node ring, 9216 flows FCT, sys[1] finished 241,450,898 cycles (exposed comm 201,544,466). Binary: `ns-3/build/scratch/ns3.42-AstraSimNetwork-default`. Configs: `scratch/topology/4nodes_ring_topology.txt`, `scratch/config/config_4ring_abs2.txt`, `examples/ns3/remote_memory_pernode.json`. Smoke runner: `/var/tmp/opencode/run_ns3_smoke.sh`.
- Vendored 2026-08-18: `qlib-research/` — Microsoft Qlib (47.7k stars, MIT) + venv at `qlib-research/venv`. LightGBM on CSI300 (China A-shares) OOS 2017-2023: ICIR 0.27 (below 0.3 threshold), Sharpe 1.01 with costs, annual return 8.9%, max DD -9.0%. Signal decays from 3.5yr OOS (ICIR 0.38, Sharpe 1.31) to 7yr OOS (ICIR 0.27, Sharpe 1.01). Data: `~/.qlib/qlib_data/cn_data`. Runners: `qlib-research/verify_qlib.py`, `qlib-research/qlib/examples/benchmarks/LightGBM/workflow_config_lightgbm_Alpha158_2023.yaml`. MLflow: set `MLFLOW_ALLOW_FILE_STORE=true` before qrun. Fix multiprocessing: `multiprocessing.set_start_method('fork', force=True)`.
- Vendored 2026-08-19: `noxim/` — davidepatti/noxim master (University of Catania, GPL), **cycle-accurate SystemC NoC simulator** = the intra-die helper (complements Timeloop's energy model + ASTRA-sim's inter-die leg). Built against SYSTEM SystemC 3.0.2 (`libsystemc-dev`) + system yaml-cpp 0.8.0 (`libyaml-cpp-dev`); the bundled deps are shimmed via `bin/libs/{systemc-2.3.1,yaml-cpp}` symlinks so `bin/Makefile` needs no path edits. One in-tree fix: `--std=c++11`→`--std=c++17` in `bin/Makefile` (SystemC 3.0.2 headers need C++14+). `bin/libs/systemc-2.3.1/lib-3.0.2` carries libsystemc symlinks. Config format is YAML (master, 2026); traffic tables (format `src dst pir [por t_on t_off t_period]`, `%` comments) are cwd-relative. Verified: stock 4x4 mesh config; T3-relevant 8x8/4-VC mesh + MoE-dispatch k=8 table (`config_examples/t3_8x8_mesh.yaml` + `t3_moe_dispatch.t.txt`) → free-flow 20.7 cyc avg delay, saturation 4279 cyc. This is the drop-in target for an expanded 64x64 intra-die matrix from `tracks/t3-topology/scripts/trace_to_matrix.py`. Runner: `noxim/bin/noxim -config <yaml>`. Rebuild: `make -C noxim/bin`.
- Vendored 2026-08-19: `SCALE-Sim/` — scalesim-project/SCALE-Sim v3.0.0 (MIT, Tushar Krishna group), **cycle-accurate systolic-array simulator** (GEMM/conv/attention) + Ramulator DRAM (submodule `submodules/ramulator`) + Accelergy energy hooks. Fills Timeloop's "validated cycles" gap: compute cycles RTL-validated, Eyeriss ≤5%, DRAM via Ramulator. Venv: `SCALE-Sim/.venv` (uv, Python 3.12 — numba 0.67 needs <3.13; system py3.14 fails). Deps via `uv pip install --python .venv/bin/python -r requirements.txt && uv pip install --python .venv/bin/python -e .`. In-tree fixes required for numpy 2.x: `scalesim/memory/double_buffered_scratchpad_mem.py:307` and `read_buffer.py:423` both `int(max(...))`→`int(np.max(...))` (numpy2 `max()` returns array). Upstream topology bug: bundled `topologies/llama/llama3b.csv` lacks a Sparsity Ratio column → `load_arrays_conv` crashes (reads batch size as sparsity); use `topologies/llama/llama3b_fixed.csv` (added `1:1` col). Config gotcha: `configs/tpuv4.cfg` is missing the `[layout]` section → crashes with `NoSectionError`; use `configs/t3_tpuv4_fixed.cfg` (128x128 ws, 1024B/cyc). RAM model is quadratic in channel count: 4096-ch GEMMs need ~4 GiB operand matrices (`operand_matrix.py`), so full llama3b on this 14G box is NOT runnable — downscale spatial dim (e.g. `topologies/llama/llama_small.csv`, 8x8 spatial / 64ch) or cap with `ulimit -v`. Verified: tiny 8x8 GEMM (2626 cyc, 40.5% util) + 7-layer llama_small on TPUv4 config (complete, per-layer SRAM/DRAM cycle traces in `outputs/`). Runner: `SCALE-Sim/.venv/bin/python -m scalesim.scale -c configs/<cfg> -t topologies/<csv> -p outputs/<name>`. Note: NO NoC/router model — fabric stays in Noxim; SCALE-Sim provides the validated compute/memory half.

- GPU on this box: RTX 3050 Laptop 4GB (CUDA 13.2 driver). If a job needs more VRAM, ask the user — they have a bigger GPU available.
<!-- tooling:end -->
