# Contributing — VeritX Research

## Workflow

1. **Clone** the monorepo:
   ```bash
   git clone git@github.com:Anmol-S314/veritx-research.git
   cd veritx-research
   ```

2. **Create a feature branch** per experiment:
   ```bash
   git checkout -b <track>/<experiment-name>
   # e.g. git checkout -b t3-topology/attention-spatial-model
   ```

3. **Edit** your track's files:
   - T2: `tracks/t2-deadlock/configs/*.cfg`
   - T3: `tracks/t3-topology/scripts/timeloop_to_matrix.py`
   - T4: `tracks/t4-formal/rtl/*.sv`, `tracks/t4-formal/configs/*.sby`

   Changing **Booksim itself** (traffic pattern, routing function, topology) is a
   different workflow — it rebuilds the shared tools image and affects both T2 and
   T3. See [Extending Booksim](tracks/t3-topology/README.md#extending-booksim-c).

4. **Push and open a Pull Request**:
   ```bash
   git add <files>
   git commit -m "T3: implement attention head spatial mapping"
   git push -u origin <branch>
   # Then open PR at https://github.com/Anmol-S314/veritx-research/pulls
   ```

5. **Check CI** — pipeline runs automatically. Artifacts include:
   - Simulation results (`*.json`)
   - Latency plots (`*.png`)
   - T3 only: interactive dashboard (Plotly heatmap + curves)

6. **Merge** after CI passes and review is complete.

## Branch Naming

| Track | Prefix | Example |
|-------|--------|---------|
| Onboarding | `onboarding/` | `onboarding/verify-tools` |
| T1 — KVCache QoS | `t1-kvcache/` | `t1-kvcache/cache-size-sweep` |
| T2 — Deadlock | `t2-deadlock/` | `t2-deadlock/vc-count-sweep` |
| T3 — Topology | `t3-topology/` | `t3-topology/attention-spatial-model` |
| T4 — Formal | `t4-formal/` | `t4-formal/fifo-induction` |

## CI Pipeline

GitHub Actions matrix: 5 cells run in parallel on every push.

```
onboarding → setup → lint → test  (toolchain validation)
T1         → setup → lint → test  (gem5 stub — deferred)
T2         → setup → lint → test → sim → artifacts
T3         → setup → lint → test → sim → dashboard → gh-pages
T4         → setup → lint → test → sim → artifacts
         └── report ── aggregates all → plots
```

Full simulation (`sim` step) runs on `main` and manual triggers only.

## Per-Track READMEs

Start with the README for your track:
- [Onboarding](tracks/onboarding/README.md)
- [T1 — KVCache QoS](tracks/t1-kvcache/README.md)
- [T2 — Deadlock](tracks/t2-deadlock/README.md)
- [T3 — Topology](tracks/t3-topology/README.md)
- [T4 — Formal](tracks/t4-formal/README.md)

## Dashboard (T3)

T3 generates an interactive dashboard on each `main` run. Published to:

`https://anmol-s314.github.io/veritx-research/t3/`

Shows: traffic matrix heatmap, latency curves per topology, regression table across runs, Timeloop access breakdown.
