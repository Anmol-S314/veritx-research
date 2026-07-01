# Contributing — VeritX Research

## Git Workflow

1. **Clone** the monorepo:
   ```bash
   git clone git@gitlab.com:Anmol-S314/veritx-research.git
   cd veritx-research
   ```

2. **Create a feature branch** per experiment:
   ```bash
   git checkout -b <track>/<experiment-name>
   # e.g. git checkout -b t2-deadlock/vc-count-sweep
   ```

3. **Commit** your changes:
   ```bash
   git add <files>
   git commit -m "T2: sweep VC count on 4x4 mesh"
   ```

4. **Push** and create a **Merge Request**:
   ```bash
   git push -u origin <branch>
   # Then open MR at https://gitlab.com/Anmol-S314/veritx-research/-/merge_requests/new
   ```

5. **MR review**: At least one approval required. CI pipeline must pass.

## Branch Naming

| Track | Prefix | Example |
|-------|--------|---------|
| T1 — KVCache QoS | `t1-kvcache/` | `t1-kvcache/cache-size-sweep` |
| T2 — Deadlock | `t2-deadlock/` | `t2-deadlock/vc-count-sweep` |
| T3 — Topology | `t3-topology/` | `t3-topology/mesh-vs-torus` |
| T4 — Formal | `t4-formal/` | `t4-formal/fifo-induction` |

## Running Locally

```bash
export TRACK=t2-deadlock
make setup     # verify toolchain
make lint      # check configs
make test      # run sanity check
make sim       # run full experiment suite
make report    # generate plots
```

## CI Pipeline

Every push triggers the CI matrix (5 parallel cells: onboarding + 4 tracks).
Full sim runs only on `main` or manual trigger.

## RTL → Simulation Flow

### T2 / T3 (Booksim)
```
config/*.cfg → booksim → parse latency → results/*.json → report/plots
```

### T4 (Formal Verification)
```
rtl/*.sv → sby (BMC/induction) → pass/fail → results/*.json → report
```

### T1 (gem5 — deferred)
```
config/*.py → gem5.opt → m5out/ → parse stats → results/*.json → report
```

## Docker

Pre-built image: `ghcr.io/anmol-s314/veritx-tools-base:latest`

```bash
make docker-run  # interactive shell with all tools
```
