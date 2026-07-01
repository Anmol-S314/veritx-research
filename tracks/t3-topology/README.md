# T3 — Topology Co-Optimization for Transformer Inference

Model an AI workload's data movement in **Timeloop**, turn the access counts into a
**traffic matrix**, simulate it on different NoC topologies in **Booksim**, and
compare them on latency/energy — visualized in a **dashboard**.

**The research question:** given a transformer layer mapped onto a grid of tiles,
*which NoC topology minimizes latency and energy for the resulting traffic?*

---

## Quick start (zero install)

Everything is pre-built in one container image — you don't install Booksim,
Timeloop, or Accelergy. From the repo root:

```bash
# 1. pull the toolchain image once
podman pull ghcr.io/anmol-s314/veritx-tools-base:latest

# 2. run the full spine: Timeloop → traffic matrix → Booksim topology sweep
podman run --rm -v "$PWD":/workspace -w /workspace \
  ghcr.io/anmol-s314/veritx-tools-base:latest \
  make -C tracks/t3-topology timeloop

# 3. build the dashboard (also in-container — pure python3, no host installs)
podman run --rm -v "$PWD":/workspace -w /workspace \
  ghcr.io/anmol-s314/veritx-tools-base:latest \
  make -C tracks/t3-topology dashboard
```

Open `report/t3/index.html` in a browser — no server. Results land in
`tracks/t3-topology/results/` (git-ignored). The only thing you install is a
container runtime (podman or docker); everything else is in the image.

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

| Command | What it does |
|---|---|
| `make setup` | verify Booksim + Timeloop + Accelergy are present |
| `make test` | quick sanity sweep (uniform traffic) — the CI gate |
| `make sim` | uniform-traffic baseline sweep across topologies |
| `make timeloop` | **the real spine** — Timeloop → matrix → topology sweep |
| `make dashboard` | (re)generate `report/t3/index.html` from `results/` |

`make timeloop` is the one you'll use for research. If Timeloop is unavailable it
falls back to a uniform sweep so the rest of the pipeline still runs.

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
- **Latency curves** — which topology wins, at which injection rate?
- **Regression table** — did your last commit help or hurt? (Δ% per topology)
- **Timeloop breakdown** — where the access bottlenecks are.

On `main` pushes CI publishes it to
`https://anmol-s314.github.io/veritx-research/t3/` (regression history persists
across commits).

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
