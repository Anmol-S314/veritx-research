# T3 — Topology Comparison with Timeloop + Booksim + Accelergy

This is the most infrastructure-rich track. You model an AI workload's data movement in **Timeloop**, convert the access counts to a **traffic matrix**, simulate it on different NoC topologies in **Booksim**, and compare **energy** via **Accelergy**.

## The Core Research Question

Given a transformer attention layer mapped onto a 2D grid of tiles, **which NoC topology minimizes latency and energy** for the resulting traffic pattern?

## Your Starting Point: `build_traffic_matrix()`

```python
# scripts/timeloop_to_matrix.py, line 42
def build_traffic_matrix(levels, num_nodes):
```

This is a **placeholder** — it assumes all traffic is DRAM→tiles star. Your research is to replace it with a **real spatial model**:

- Where are attention heads mapped to tiles?
- How does QK^T matmul data flow between tiles?
- What about the FFN layers?
- How does the traffic pattern change with sequence length, head count, model dimension?

## End-to-End Pipeline

```
Timeloop (workload model)
    ↓ *.stats.txt
timeloop_to_matrix.py  ← YOU EDIT THIS
    ↓ traffic_matrix.txt
Booksim (NoC sim)
    ↓ latency, hops
mesh vs torus vs flatfly comparison
    ↓
Dashboard (Plotly heatmap + curves + regression)
```

## What You Edit

| File | What it does |
|------|-------------|
| `scripts/timeloop_to_matrix.py` | **Your spatial model** — replace `build_traffic_matrix()` |
| `configs/*.cfg` | Topology parameters (size, radix, channel width) |

You can also add new topology configs. Booksim supports: `mesh`, `torus`, `flatfly`, `fattree`, `dragonflynew`, `cmesh`.

## Dashboard

On every `main` push, CI generates an interactive dashboard at:

[`https://anmol-s314.github.io/veritx-research/t3/`](https://anmol-s314.github.io/veritx-research/t3/)

It shows:
- **Heatmap** — your traffic matrix (is the spatial model sane?)
- **Latency curves** — which topology wins at which injection rate?
- **Regression table** — did your latest commit improve or hurt latency?
- **Timeloop breakdown** — where are the access bottlenecks?

## Local Development

```bash
make dashboard   # rebuild dashboard from latest results
```

Open `report/t3/index.html` in a browser — no server needed.

## CI Pipeline

```
make setup   → verify Booksim + Timeloop + Accelergy
make lint    → syntax check
make test    → sanity run (all topologies, uniform traffic)
make sim     → full Timeloop→matrix→Booksim spine → sweep
make dashboard → generate + publish dashboard
```

## Expected Results

| Topology | Zero-load latency | Saturation rate |
|----------|-------------------|-----------------|
| mesh 4×4 | ~220 cycles | ~0.25 |
| torus 4×4 | ~248 cycles | ~0.30 |
| flatfly 4 | ~353 cycles | ~0.35 |

These are placeholder numbers with the DRAM-star model. Your spatial model will produce different (correct) values.

## Research Path

1. **Weeks 1-3**: Run the pipeline, understand each stage, reproduce baselines
2. **Weeks 4-8**: Replace `build_traffic_matrix()` with your real spatial model — this is the novel research
3. **Weeks 9-16**: Explore topologies, add Accelergy energy comparison, write paper

## Reference

- [Booksim 2.0](https://github.com/booksim/booksim2)
- [Timeloop](https://github.com/Accelergy-Project/timeloop)
- [Accelergy](https://github.com/Accelergy-Project/accelergy)
