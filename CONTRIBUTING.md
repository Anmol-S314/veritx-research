# Contributing to VeritX Research

## Day 1: Getting Started

### Prerequisites

- Python 3.10+
- Make
- Git
- (Optional) Docker/Podman for the tools image

### Quick Setup

```bash
# Clone and enter the repo
git clone <repo-url> && cd veritx-research

# Install the VeritX CLI (the main development tool)
cd tracks/t3-topology/dse
pip install -e .
cd ../..

# Verify everything works
make tools                          # list vendored tools
veritx --help                       # verify CLI works
python3 -m pytest tracks/t3-topology/dse/tests/ -x -q  # run tests
```

### What to Read First

1. **Root README.md** -- repo structure, quick start, how tooling fits together
2. **tracks/t3-topology/dse/README.md** -- the VeritX CLI wiki (2700+ lines, 17 Mermaid diagrams)
3. **serving/README.md** -- multi-die simulation architecture (5 Mermaid diagrams)
4. **dse/docs/CONTRIBUTING.md** -- code style, design rules, module responsibilities

## Repository Layout

```
veritx-research/
├── Makefile                    # top-level commands (make help)
├── CONTRIBUTING.md             # this file
├── scripts/
│   └── tools.py               # unified vendored tool management
├── third_party/               # tools we MODIFY (canonical source)
│   ├── booksim2/              # BookSim2 NoC simulator (fork with veritx extensions)
│   └── timeloop/              # Timeloop dataflow mapper
├── serving/                   # tools we VENDOR (upstream stays pristine)
│   ├── astra-sim/             # ASTRA-sim multi-die simulator
│   ├── LLMServingSim/         # LLM workload trace generator
│   └── results/               # published research evidence
├── tracks/
│   └── t3-topology/           # topology co-optimization track
│       └── dse/               # VeritX DSE engine (the CLI)
│           ├── veritx_dse/    # canonical Python package (30 modules)
│           ├── tests/         # 278 tests
│           ├── scripts/       # standalone analysis scripts
│           ├── docs/          # research documentation
│           ├── examples/      # sample CompileRequest JSONs
│           └── README.md      # CLI wiki
└── runs/                      # simulation outputs (git-tracked)
```

## Vendored Tool Management

All third-party tools are managed by `scripts/tools.py`, which auto-discovers
them from `METADATA.json` files.

```bash
make tools                          # list all tools with status
make tool-info TOOL=booksim2        # show details, deps, gaps
make tool-build TOOL=booksim2       # build the tool
make tool-run TOOL=booksim2 ARGS="mesh.cfg trace.txt"  # run it
make tool-sync TOOL=booksim2        # sync to downstream copies
make tool-tag TOOL=booksim2 VER=2.0 # tag version
make tool-pick TOOL=booksim2        # interactive version picker
make tool-clean TOOL=booksim2       # clean build artifacts
```

### Adding a New Tool

1. Vendor the source into `third_party/<name>/` or `serving/<name>/`
2. Create `METADATA.json` (see `third_party/booksim2/METADATA.json` for schema)
3. If the tool needs syncing to another location, add `sync_targets` to METADATA.json
4. Run `make tools` to verify it appears
5. Run `make tool-build TOOL=<name>` to verify the build works

## VeritX CLI Development

The CLI lives at `tracks/t3-topology/dse/veritx_dse/`. Key modules:

| Module | Responsibility |
|--------|---------------|
| `cli.py` | Entry point -- arg parsing + dispatch ONLY |
| `logging.py` | Ctx dataclass (replaces globals) |
| `paths.py` | Single source of truth for all file paths |
| `presets.py` | Topology + workload definitions |
| `booksim.py` | BookSim2 config generation + execution |
| `traces.py` | Trace I/O (pure functions) |
| `pipeline.py` | Orchestration (compare, sweep, run) |
| `compile_model.py` | PRD E1-E5 data model, guardrails, VC derivation |
| `reports.py` | Area/power/timing estimation |
| `artifact.py` | Signing + manifest |
| `uvm_gen.py` | UVM testbench generation |

### Design Rules

1. **No globals** -- every function takes a `Ctx` or returns a result
2. **Paths go through `paths.py`** -- never use `Path(__file__).parent.parent.parent`
3. **Business logic in modules, not CLI** -- `cli.py` dispatches, modules do work
4. **Tests must pass** -- `python3 -m pytest tests/ -x -q` before any commit

### Running Tests

```bash
cd tracks/t3-topology/dse
python3 -m pytest tests/ -x -q          # all 278 tests
python3 -m pytest tests/test_compile_model.py -x -q  # just compile model
python3 -m pytest tests/test_cli.py -x -q             # just CLI tests
```

## Simulation Paths

### Single-Die (BookSim2 Standalone)

```bash
# Compare topologies on a real trace
veritx compare --trace runs/traces/qwen3.txt --topos mesh_8x8,torus_8x8

# Full compile pipeline
veritx compile examples/qwen3_moe_16npu.json
```

### Multi-Die (ASTRA-sim + BookSim2)

```bash
# Build ASTRA-sim first
make tool-build TOOL=astra-sim

# Run multi-die simulation
veritx run astra \
  --ets serving/astra-sim/qwen_slice/qwen_slice \
  --system-config serving/astra-sim/examples/system/native_collectives/Ring_4chunks.json \
  --network-config serving/astra-sim/astra-sim/network_frontend/booksim2/examples/4npus_snake.cfg \
  --memory-config serving/astra-sim/examples/remote_memory/analytical/no_memory_expansion.json
```

## Common Tasks

### "I need to add a new topology"

1. Add topology definition to `veritx_dse/presets.py`
2. Add BookSim2 config generation to `veritx_dse/booksim.py`
3. Add tests to `tests/test_compile_model.py`
4. Run `veritx compare --topos <new_topo>` to verify

### "I need to add a new workload preset"

1. Add to `WORKLOAD_PRESETS` in `veritx_dse/presets.py`
2. Add a sample JSON to `examples/`
3. Run `veritx compile examples/<new>.json` to verify

### "I need to modify BookSim2"

1. Edit files in `third_party/booksim2/src/` (canonical copy)
2. Run `python3 scripts/tools.py booksim2 sync` to propagate
3. Rebuild: `make tool-build TOOL=booksim2`

### "I need to add a new CLI command"

1. Add the function to `veritx_dse/cli.py`
2. Register it in the `COMMANDS` dict
3. Add tests to `tests/test_cli.py`
4. Run `veritx <command> --help` to verify

## Git Workflow

```bash
# Feature branch
git checkout -b feat/my-feature

# Work on changes
# ...

# Run tests
cd tracks/t3-topology/dse && python3 -m pytest tests/ -x -q

# Commit
git add <files>
git commit -m "feat: description of change"

# Push
git push origin feat/my-feature
```

### Commit Message Format

```
<type>: <description>

Types: feat, fix, docs, refactor, test, chore

Examples:
feat: add GEC topology to sweep
fix: BookSim2 trace replay crash on empty trace
docs: update README with architecture diagrams
refactor: extract trace parsing into commands_trace.py
test: add integration tests for compile pipeline
chore: clean up unused scripts
```

## Getting Unstuck

- **"veritx command not found"**: Run `pip install -e tracks/t3-topology/dse`
- **"BookSim2 binary not found"**: Run `make tool-build TOOL=booksim2`
- **"ASTRA-sim binary not found"**: Run `make tool-build TOOL=astra-sim`
- **Tests fail**: Check `tracks/t3-topology/dse/tests/` for the failing test
- **Paths broken**: All paths go through `veritx_dse/paths.py` -- check there first
- **Tool sync issues**: Run `python3 scripts/tools.py booksim2 sync --check`
