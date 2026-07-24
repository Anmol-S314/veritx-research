# T3 — Topology Co-Optimization for Transformer Inference

Model an AI workload's data movement in **Timeloop**, turn the access counts into a
**traffic matrix**, simulate it on different NoC topologies in **Booksim**, and
compare them on latency/energy — visualized in a **dashboard**.

**The research question:** given a transformer layer mapped onto a grid of tiles,
*which NoC topology minimizes latency and energy for the resulting traffic?*

---

## Developer Quick Start (local Python environment)

One-time setup — works from **any** directory:

```bash
# 1. Navigate to the run directory and activate the environment
cd tracks/t3-topology/run
source env.sh

# 2. Verify everything is available
t3 check

# 3. Run the full analysis pipeline
t3 all          # analysis → aggregate → plot
                # outputs land in tracks/t3-topology/results/baseline/analysis/
```

> **Note:** `run/env.sh` is the **canonical** entry point. It resolves T3_DIR as
> its parent (`t3-topology/`), finds the repo `venv/` wherever it is, adds `t3`
> to your PATH, and exports all environment variables. You only source it once per shell.

### Individual commands

```bash
t3 help         # list all commands + env-var reference
t3 env          # print all resolved paths and variables
t3 analysis     # PA-01: load sweep JSON → summary table
t3 aggregate    # PA-02: merge all results → results/baseline/analysis/aggregate.csv
t3 plot --hops  # PA-03: latency curves   → results/baseline/analysis/latency_curves.png
t3 selfcheck    # regression guard for all three PA scripts
t3 sim          # run a fresh Booksim sweep (needs booksim on PATH)
t3 clean        # remove results/ and __pycache__
```

### Environment variable overrides

Set these **before** `source run/env.sh` to override defaults:

| Variable | Default | Purpose |
|---|---|---|
| `BOOKSIM_BIN` | `booksim` | Path to Booksim binary |
| `RATES` | `0.002,0.005,0.01,0.02,0.03` | Injection rate sweep |
| `TRAFFIC_MATRIX` | *(unset → uniform)* | Path to traffic matrix file |
| `PACKET_SIZE_BITS` | `128` | Energy proxy: hops × this |
| `SAT_K` | `2.0` | Saturation threshold multiplier |
| `MPLBACKEND` | `Agg` | Matplotlib backend (Agg = headless) |

---

## Container Quick Start (zero install)

Everything is pre-built in one container image — you don't install Booksim,
Timeloop, or Accelergy. From the repo root:

```bash
make pull                                        # pull the toolchain image once
make run TRACK=t3-topology CMD=timeloop          # full spine: Timeloop → matrix → sweep
make run TRACK=t3-topology CMD=dashboard         # build report/t3/index.html
```

`make help` lists every command; `make shell` drops you into the image for
interactive work. Open `report/t3/index.html` in a browser — no server. Results
land in `tracks/t3-topology/results/` (git-ignored).

---

## The one file you edit: `build_traffic_matrix()`

`scripts/timeloop_to_matrix.py` turns Timeloop's per-level access counts into an
N×N tile-to-tile traffic matrix. The shipped `build_traffic_matrix()` is a
**deliberately simple placeholder** (nearest-neighbor bias + memory-controller
traffic). **Your research is to replace this one function** with a real spatial
model:

- Where are attention heads / QKᵀ / FFN mapped onto tiles?
- How does data actually flow tile-to-tile for that mapping?
- How does the pattern change with sequence length, head count, model dim?

Everything else (parsing, the Booksim bridge, the sweep, the dashboard) already
works — you only touch this function until it's good, then explore topologies.

---

## Pipeline

```
timeloop/{arch,problem,mapper}.yaml
        │  timeloop-mapper
        ▼  results/baseline/timeloop.stats.txt
scripts/timeloop_to_matrix.py   ← YOU EDIT build_traffic_matrix()
        ▼  results/baseline/traffic_matrix.txt
Booksim  (traffic = matrix(...), swept over mesh/torus/fly)
        ▼  results/baseline/topology_sweep.json
scripts/analysis.py   → terminal summary table
scripts/aggregate.py  → results/baseline/analysis/aggregate.csv
scripts/plot_curves.py→ results/baseline/analysis/latency_curves.png
scripts/generate_dashboard.py
        ▼  report/t3/index.html
```

---

## Directory Structure

```
results/
└── baseline/                        ← raw simulation output (CONFIG=baseline)
    ├── topology_sweep.json          ← Booksim sweep results (make sim)
    ├── traffic_matrix.txt           ← traffic matrix (make timeloop)
    ├── timeloop.stats.txt           ← Timeloop stats (make timeloop)
    └── analysis/                    ← processed PA outputs (make pa-report)
        ├── aggregate.csv            ← PA-02 merged dataset
        └── latency_curves.png       ← PA-03 latency-throughput curves
```

> **Why two levels?** `results/baseline/` holds raw sim data that other targets
> depend on (e.g. dashboard reads `topology_sweep.json`). `analysis/` holds
> post-processed outputs so a `make aggregate` never risks overwriting sweep data.

---

## Commands

### `make` targets — from **inside the container** (`make shell`)

| Command | What it does |
|---|---|
| `make setup` | verify Booksim + Timeloop + Accelergy are present |
| `make lint` | syntax-check all Python scripts |
| `make test` | quick sanity sweep — the CI gate |
| `make sim [CONFIG=baseline]` | uniform-traffic Booksim sweep → `results/baseline/topology_sweep.json` |
| `make timeloop` | full spine: Timeloop → traffic matrix → topology sweep |
| `make timeloop-workload [CONFIG=baseline]` | configurable multi-workload Timeloop pipeline |
| `make energy [CONFIG=baseline]` | Timeloop energy breakdown → `results/baseline/energy.json` |
| `make analysis [CONFIG=baseline]` | PA-01: read sweep JSON → print summary table (terminal only) |
| `make aggregate [CONFIG=baseline]` | PA-02: merge all JSONs → `results/baseline/analysis/aggregate.csv` |
| `make plot [CONFIG=baseline]` | PA-03: latency curves → `results/baseline/analysis/latency_curves.png` |
| `make pa-report [CONFIG=baseline]` | run analysis + aggregate + plot in sequence |
| `make dashboard [CONFIG=baseline]` | (re)generate `report/t3/index.html` |
| `make clean` | remove `results/` and Timeloop artifacts |

### `make` targets — from the **repo root** (works from host or inside `make shell`)

| Command | What it does |
|---|---|
| `make timeloop TRACK=t3-topology CONFIG=baseline` | full Timeloop spine → `results/baseline/timeloop.stats.txt` + sweep |
| `make energy   TRACK=t3-topology CONFIG=baseline` | energy breakdown — **requires timeloop to have run first** |
| `make dashboard TRACK=t3-topology CONFIG=baseline` | build `report/t3/index.html` |
| `make pa-report TRACK=t3-topology CONFIG=baseline` | full PA pipeline (analysis + aggregate + plot) |
| `make analysis  TRACK=t3-topology CONFIG=baseline` | PA-01 (load sweep JSON → print summary table) |
| `make aggregate TRACK=t3-topology CONFIG=baseline` | PA-02 (merge all results → aggregate.csv) |
| `make plot      TRACK=t3-topology CONFIG=baseline` | PA-03 (latency curves → latency_curves.png) |
| `make run TRACK=t3-topology CMD=sim` | run any CMD target in container |
| `make shell` | drop into an interactive container shell |

> **Prerequisites for `make energy`:** `timeloop.stats.txt` must exist first.
> Run `make timeloop TRACK=t3-topology CONFIG=baseline` before `make energy`.

> **Smart execution:** The root Makefile automatically detects whether docker/podman is available.
> From the **host terminal**, it spawns the container. From **inside `make shell`**, it runs directly without trying to call docker/podman again.

### `t3` CLI (preferred for local dev with env.sh sourced)

| Command | What it does |
|---|---|
| `t3 help` | full help + env-var reference |
| `t3 check` | verify Python, pandas, booksim are available |
| `t3 analysis` | PA-01: sweep JSON → DataFrame + summary table |
| `t3 aggregate` | PA-02: merge all JSONs → `results/baseline/analysis/aggregate.csv` |
| `t3 plot` | PA-03: latency curves → `results/baseline/analysis/latency_curves.png` |
| `t3 all` | run analysis → aggregate → plot in sequence |
| `t3 sim` | fresh Booksim uniform sweep |
| `t3 dashboard` | build `report/t3/index.html` |
| `t3 selfcheck` | regression tests for all PA scripts |
| `t3 clean` | remove `results/` and `__pycache__` |

---

## Analysis Framework (PA-01 / PA-02 / PA-03)

Three Python scripts (in `scripts/`) form the metric infrastructure:

| Script | Task | Output |
|---|---|---|
| `analysis.py` | Load sweep JSON → pandas DataFrame with all Pareto columns | summary table in terminal |
| `aggregate.py` | Merge all `results/*.json` + `history.json` by commit SHA | `results/baseline/analysis/aggregate.csv` |
| `plot_curves.py` | Latency-throughput curves with saturation markers | `results/baseline/analysis/latency_curves.png` |
| `utils.py` | Shared helpers: path resolution, git SHA, saturation logic | imported by above |

All scripts read configuration from the environment variables in `run/env.sh`.

```python
# Python API — use in notebooks or other scripts
from scripts.analysis    import load_sweep_df, summarise
from scripts.aggregate   import load_aggregate_df
from scripts.plot_curves import plot_curves
from scripts.utils       import resolve_paths, saturation_point

df  = load_sweep_df()           # pandas DataFrame
agg = load_aggregate_df()       # all historical + current runs
fig, ax = plot_curves(df, k=2.0, show_hops=True)
fig.savefig("my_fig.pdf", bbox_inches="tight")
```

---

## Topology Status

Configs live in `configs/*.cfg`. Current status of the 10 configured topologies:

| Topology | Nodes | Status | Notes |
|---|---|---|---|
| `mesh4x4` | 16 | ✅ Working | k=4, n=2 |
| `torus4x4` | 16 | ✅ Working | k=4, n=2 |
| `fattree16` | 16 | ✅ Working | k=4 fat-tree |
| `cmesh16` | 16 | ✅ Working | concentrated mesh |
| `fly4` | 16 | ✅ Working | flattened butterfly |
| `flatfly16` | 16 | ⚠️ Fixed | cfg syntax error fixed (inline comment was malformed) |
| `dragonfly16` | 72 | ⚠️ Scale mismatch | Minimum dragonfly = 72 nodes (`2p²(2p²+1)`, p=2); not comparable to 16-node group |
| `qtree16` | 64 | ⚠️ Scale mismatch | k=4, n=3 → 4³=64 nodes; hardcoded in Booksim source |
| `tree4` | 64 | ⚠️ Scale mismatch | k=4, n=3 → 64 nodes; hardcoded in Booksim source |
| `anynet16` | 16 | ❌ Missing file | Requires external `anynet16` adjacency matrix file (not in repo) |

> **On scale-mismatched topologies:** `dragonfly16`, `qtree16`, and `tree4` run
> successfully but their node counts differ from the 16-node comparison group.
> Exclude them from direct latency comparisons or run a separate sweep at their
> native scale with a matching traffic matrix.

---

## Using a traffic matrix in Booksim (the bridge)

We added a `matrix` traffic pattern to Booksim. Point any config at a matrix file:

```
traffic = matrix(results/traffic_matrix.txt);
```

**File format:** `N×N` non-negative numbers, row-major (`row = source tile`,
`col = dest tile`); `#` starts a comment. Each packet's destination is sampled
from row `source`, weighted by the entries. `N` must equal the topology's node
count (a 4×4 mesh = 16, so a 16×16 matrix).

The sweep runner picks it up automatically:

```bash
TRAFFIC_MATRIX=results/baseline/traffic_matrix.txt \
RATES="0.002,0.005,0.01,0.02,0.03" \
python3 scripts/run_experiments.py
```

(Matrix/hotspot patterns saturate far earlier than uniform, so use low `RATES`.)

---

## Dashboard

`make dashboard` builds a self-contained Plotly page (`report/t3/index.html`):

- **Heatmap** — your traffic matrix (is the spatial model sane?)
- **Latency curves** — which topology wins, at which injection rate? (dotted line = saturation point)
- **Hops (energy proxy)** — avg hops × packet size, the Wk9 energy metric
- **Regression table** — did your last commit help or hurt? (Δ% per topology)
- **Timeloop breakdown** — where the access bottlenecks are.

Use the **run selector** (or `?run=<n>`) to load any past run's panels, not just
the latest — every run's full data is embedded. Light/dark toggle top-right.

On `main` pushes CI rebuilds it and uploads it as a **downloadable artifact**
(regression history persists across commits via a private `gh-pages` branch).
Results stay inside the private repo — per the IP rules they are **not** served
on a public URL. To view a CI run's dashboard, download the `report` artifact
and open `t3/index.html`, or just run `make dashboard` locally.

---

## Workarounds & Known Issues

### `make clean` wipes all results
`make clean` removes the entire `results/` directory. Since results are not
committed to git, they are permanently lost until you re-run `make sim`.

**Workaround:** Always re-run sim before the analysis pipeline after a clean:
```bash
make -C tracks/t3-topology sim pa-report CONFIG=baseline
```

### PA targets need pandas (container only)
`analysis.py`, `aggregate.py`, and `plot_curves.py` require `pandas` and
`matplotlib`, which are only available inside the tools container.

**Workaround:** Use the root Makefile targets which auto-launch the container:
```bash
make pa-report TRACK=t3-topology CONFIG=baseline   # from host — works always
```

### `anynet16` crashes (rc=255, all rates)
The `anynet` topology in Booksim requires an external adjacency-matrix file
(`network_file = anynet16`). That file does not exist in the repo.

**Workaround:** Either provide a valid `anynet16` adjacency file, or exclude this
topology from the sweep by removing its `.cfg` file.

### `flatfly16` syntax error (fixed)
The original `configs/flatfly16.cfg` had `c = 1; concentration: 1 node per router`
— the text after the semicolon was parsed as a second statement, crashing Booksim.

**Fix applied:** Corrected to `c = 1; // concentration: 1 node per router`.

---

## Suggested path (per the programme)

1. **Wk 1–3:** run the pipeline, understand each stage, reproduce baselines.
2. **Wk 4–8:** replace `build_traffic_matrix()` with your real spatial model —
   the novel work. Compare topologies on your matrix.
3. **Wk 9–16:** Pareto analysis (latency vs energy vs area), sensitivity sweeps,
   write-up.

## Reference

- [Booksim 2.0](https://github.com/booksim/booksim2) ·
  [Timeloop](https://github.com/Accelergy-Project/timeloop) ·
  [Accelergy](https://github.com/Accelergy-Project/accelergy)
