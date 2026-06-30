# ADR-0001: VeritX Infrastructure — Monorepo with CI Matrix

## Status
Accepted

## Context
VeritX BTech programme has 15 students across 4 research tracks with different toolchains. Need a GitLab-based infrastructure that is:
- Easy for students to clone and contribute to
- Reproducible across all machines
- CI-gated with automated testing
- Cost-effective on a single self-hosted runner

## Decision
Use a monorepo structure with GitLab CI parallel:matrix and Docker-based reproducibility.

### Rationale
1. **Monorepo** — All 15 students share weeks 1-2 onboarding (identical material). Single GitLab project for permissions, variables, MR templates. Track isolation via directories with CI matrix.
2. **CI Matrix** — One `.gitlab-ci.yml` with 5 parallel jobs (onboarding + 4 tracks). Each track job runs only its own tests. No duplicated CI config.
3. **Docker multi-stage image** — Pre-built with all 4 toolchains, pushed to GitLab container registry. CI jobs pull the image (no build time).
4. **Self-hosted runner** — Docker executor on 32GB+ server. Required for gem5 (4-6 hr builds, 45-90 min sims).

## Consequences
- Students only clone one repo
- CI is fast (no tool rebuilds)
- Docker image must be rebuilt when tool versions change (~monthly)
- Self-hosted runner needs maintenance (disk space, Docker updates)

## Repository Structure
```
veritx-research/
├── onboarding/                # Shared weeks 1-2
│   ├── 01-linux-setup/
│   ├── 02-booksim-hello-world/
│   └── 03-python-visualization/
├── t1-kvcache-qos/            # gem5/Garnet/ASTRA-sim
├── t2-deadlock/               # Booksim 2.0
├── t3-topology/               # Booksim + Timeloop + Accelergy
├── t4-formal/                 # SymbiYosys + Yosys + CBMC
├── .gitlab-ci.yml             # CI matrix — 5 parallel jobs
├── Makefile                   # Top-level: make setup, make test
├── Dockerfile                 # Multi-stage build for all tools
└── README.md                  # Student onboarding
```

## CI Pipeline Stages
1. **build** — (no-op in CI, tool is in Docker image)
2. **lint** — Validate configs, traffic traces, Python syntax
3. **test** — Sanity simulation (4x4 mesh, uniform traffic)
4. **sim** — Full experiment suite
5. **report** — Generate latency/throughput plots, compare vs baselines
