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

| Command | What it does |
|---|---|
| `make setup` | verify Booksim + Timeloop + Accelergy are present |
| `make test` | quick sanity sweep (uniform traffic) — the CI gate |
| `make sim` | uniform-traffic baseline sweep across topologies |
| `make timeloop` | **the real spine** — Timeloop (one mapping per NoC size) → matrix → topology sweep |
| `make energy` | pJ/compute + EDP (Timeloop) **and** real die area (Accelergy) → `results/energy_<N>.json` |
| `make area` | die area alone — routers + buffers + MACs → `results/area_<N>.json` |
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

Want a custom topology, traffic pattern, or routing function in C++? See
**Extending Booksim** below.

---

## Extending Booksim (C++)

Booksim is **vendored as a git subtree** at
[`third_party/booksim2/`](../../third_party/booksim2/) — pinned upstream plus our
edits as ordinary commits. You change the simulator itself (traffic pattern,
routing function, topology, router) by editing the **real `.cpp` files**:

```bash
make shell
# edit third_party/booksim2/src/... like normal code
third_party/booksim2/veritx-rebuild.sh   # sync → rebuild → install → verify
```

No patch to write, no `Dockerfile` to edit. `veritx-rebuild.sh` verifies the
flit-fork multicast still forks, so you find out immediately if a build dropped
our edits. Note this is the same Booksim **T2 runs too**, so a break here breaks
both tracks.

See [`third_party/booksim2/VERITX.md`](../../third_party/booksim2/VERITX.md) for
the full workflow — the edit loop, seeing our delta with `git diff`, the
`git subtree pull` version-bump, the extension catalog, and the gotchas.

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
