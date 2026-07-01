# VeritX Research — AI-native Network-on-Chip Architecture

Monorepo for the VeritX BTech research programme (6 months, 15 students, 4 tracks). Each track studies a different aspect of AI accelerator NoCs, sharing infrastructure across Booksim, Timeloop, Accelergy, Yosys/SymbiYosys, and CBMC.

## Repository Structure

```
.
├── tracks/
│   ├── onboarding/        # Toolchain validation — start here
│   ├── t1-kvcache/        # KVCache QoS with gem5/Garnet/ASTRA-sim (deferred)
│   ├── t2-deadlock/       # Routing deadlock with Booksim 2.0
│   ├── t3-topology/       # Topology comparison with Booksim + Timeloop + Accelergy
│   └── t4-formal/         # Formal verification with SymbiYosys + Yosys + CBMC
├── scripts/               # Cross-track report generation
├── report/                # Generated plots and summaries
├── Dockerfile             # Multi-stage build of all tools
└── .github/workflows/     # GitHub Actions CI (5-cell matrix)
```

## Student Workflow

```
1. git checkout -b <track>/<experiment-name>
2. <edit your track's code>
3. git push -u origin <branch>
4. Open a pull request → CI runs automatically
5. CI artifacts: results/*.json, latency plots, dashboard
```

You never install tools locally. Everything runs in the CI container.

### Per-Track Guides

| Track | What you study | Files you edit | Start here |
|-------|---------------|----------------|------------|
| [Onboarding](tracks/onboarding/README.md) | Toolchain sanity | — | First |
| [T1](tracks/t1-kvcache/README.md) | KVCache QoS (gem5) | `configs/*.py` | *Deferred* |
| [T2](tracks/t2-deadlock/README.md) | Deadlock avoidance | `configs/*.cfg` | ✅ |
| [T3](tracks/t3-topology/README.md) | Topology × traffic | `scripts/timeloop_to_matrix.py` | ✅ |
| [T4](tracks/t4-formal/README.md) | Formal verification | `rtl/*.sv`, `configs/*.sby` | ✅ |

## CI Pipeline

GitHub Actions runs 5 cells in parallel on every push:

```
onboarding  ── setup → lint → test ✓
T1          ── setup → lint → test (stub)
T2          ── setup → lint → test → sim → artifacts
T3          ── setup → lint → test → sim → dashboard → gh-pages
T4          ── setup → lint → test → sim → artifacts
     └── report ── aggregates all → plots + summary
```

Full simulation runs on `main` and manual triggers only.

## Dashboard

T3 produces an interactive dashboard (Plotly heatmap + latency curves + regression table) on every `main` run. Access it at:

[`https://anmol-s314.github.io/veritx-research/t3/`](https://anmol-s314.github.io/veritx-research/t3/)

(T2/T4 dashboards planned — same generator template.)

## Tool Versions

All tools are pinned in the Docker image at `ghcr.io/anmol-s314/veritx-tools-base:latest`:

| Tool | Version | Track |
|------|---------|-------|
| Booksim 2.0 | commit `28f4329` | T2, T3 |
| Timeloop | commit `6b70505` (pre-barvinok) | T3 |
| Accelergy | latest | T3 |
| Yosys | 0.66+ | T4 |
| SymbiYosys | latest | T4 |
| CBMC | 6.10.0 | T4 |
| z3 | 4.8.12 | T4 |

## License

See [LICENSE](LICENSE).
