# VeritX Research — Infrastructure

Monorepo for the BTech VeritX research programme (AI-native Network-on-Chip).

## 4 Tracks

| Track | Topic | Students | Tools |
|-------|-------|----------|-------|
| T1 | KVCache QoS | 4 | gem5 + Garnet + ASTRA-sim |
| T2 | Deadlock | 4 | Booksim 2.0 |
| T3 | Topology | 4 | Booksim + Timeloop + Accelergy |
| T4 | Formal Verification | 3 | SymbiYosys + Yosys + CBMC |

## Quick Start

```bash
export TRACK=t1-kvcache   # or t2-deadlock, t3-topology, t4-formal, onboarding
make setup
make lint
make test
make sim
```

## CI Pipeline

The CI matrix runs 5 cells in parallel (onboarding + 4 tracks):

```
lint → test (sanity) → sim (full) → report (plots)
```

See `.gitlab-ci.yml` (GitLab) or `.github/workflows/ci.yml` (GitHub Actions).

## Docker

All toolchains are pre-built in a multi-stage Docker image:

```bash
make docker-build     # Build locally
make docker-push      # Push to registry (set REGISTRY env var)
make docker-run       # Interactive shell
```

## Self-Hosted Runner Setup

- **GitLab**: `sudo bash scripts/setup-gitlab-runner.sh`
- **GitHub**: `sudo bash scripts/setup-github-runner.sh`
