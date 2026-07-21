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
                # outputs land in tracks/t3-topology/output/
```

> **Note:** `run/env.sh` is the **canonical** entry point. It resolves T3_DIR as
> its parent (`t3-topology/`), finds the repo `venv/` wherever it is, adds `t3`
> to your PATH, and exports all environment variables. You only source it once per shell.

### Individual commands

```bash
t3 help         # list all commands + env-var overrides
t3 env          # print all resolved paths and variables
t3 analysis     # PA-01: load sweep JSON → summary table
t3 aggregate    # PA-02: merge all results → output/aggregate.csv
t3 plot --hops  # PA-03: latency curves   → output/latency_curves.png
t3 selfcheck    # regression guard for all three PA scripts
t3 sim          # run a fresh Booksim sweep (needs booksim on PATH)
t3 clean        # remove output/ and __pycache__
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

Run everything from the repo root — `make run` executes inside the tools image
(podman or docker, auto-detected), so you install nothing but a container runtime:

```bash
make pull                                   # pull the toolchain image once
make run TRACK=t3-topology CMD=timeloop     # full spine: Timeloop → matrix → sweep
make run TRACK=t3-topology CMD=dashboard    # build report/t3/index.html
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
        ▼  results/timeloop.stats.txt
scripts/timeloop_to_matrix.py   ← YOU EDIT build_traffic_matrix()
        ▼  results/traffic_matrix.txt
Booksim  (traffic = matrix(...), swept over mesh/torus/fly)
        ▼  results/topology_sweep.json
scripts/generate_dashboard.py
        ▼  report/t3/index.html   (heatmap · latency curves · regression · bottlenecks)
```

---

## Commands

### `t3` CLI (preferred for local dev)

| Command | What it does |
|---|---|
| `t3 help` | full help + env-var reference |
| `t3 check` | verify Python, pandas, booksim are available |
| `t3 analysis` | PA-01: sweep JSON → DataFrame + summary table |
| `t3 aggregate` | PA-02: merge all JSONs → `output/aggregate.csv` |
| `t3 plot` | PA-03: latency curves → `output/latency_curves.png` |
| `t3 all` | run analysis → aggregate → plot in sequence |
| `t3 sim` | fresh Booksim uniform sweep |
| `t3 dashboard` | build `report/t3/index.html` |
| `t3 selfcheck` | regression tests for all PA scripts |
| `t3 clean` | remove `output/` and `__pycache__` |

### `make` targets (container + CI)

| Command | What it does |
|---|---|
| `make setup` | verify Booksim + Timeloop + Accelergy are present |
| `make test` | quick sanity sweep (uniform traffic) — the CI gate |
| `make sim` | uniform-traffic baseline sweep across topologies |
| `make timeloop` | **the real spine** — Timeloop → matrix → topology sweep |
| `make energy` | Timeloop energy: per-component pJ/compute + energy-delay product → `results/energy.json` |
| `make dashboard` | (re)generate `report/t3/index.html` from `results/` |

`make timeloop` is the one you'll use for research. If Timeloop is unavailable it
falls back to a uniform sweep so the rest of the pipeline still runs.

---

## Analysis Framework (PA-01 / PA-02 / PA-03)

Three Python scripts (in `scripts/`) form the metric infrastructure:

| Script | Task | Output |
|---|---|---|
| `analysis.py` | Load sweep JSON → pandas DataFrame with all Pareto columns | summary table in terminal |
| `aggregate.py` | Merge all `results/*.json` + `history.json` by commit SHA | `output/aggregate.csv` |
| `plot_curves.py` | Latency-throughput curves with saturation markers | `output/latency_curves.png` |
| `utils.py` | Shared helpers: path resolution, git SHA, saturation logic | imported by above |

All scripts read configuration from the environment variables in `run/env.sh`.
The `output/` directory (writable by you) holds all generated files;
`results/` is populated by CI/Docker runs.

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
TRAFFIC_MATRIX=results/traffic_matrix.txt \
RATES="0.002,0.005,0.01,0.02,0.03" \
python3 scripts/run_experiments.py
```

(Matrix/hotspot patterns saturate far earlier than uniform, so use low `RATES`.)

---

## Topologies

Configs live in `configs/*.cfg` (16-node `mesh4x4`, `torus4x4`, `fly4`). Add your
own — Booksim supports `mesh`, `torus`, `flatfly`, `fattree`, `dragonflynew`,
`cmesh`. For a 4×4 2-D mesh use `k=4; n=2;` (`n` is the number of dimensions, not
the grid side).

Want a custom topology or traffic pattern in C++? The Booksim source ships in the
image at `/opt/booksim2` with compilers — edit and `cd /opt/booksim2/src && make`.
Our matrix pattern (`matrixtraffic.{hpp,cpp}` + `matrix_traffic.patch`) in
`booksim-ext/` is a worked example of adding one.

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
