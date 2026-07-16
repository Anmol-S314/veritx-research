# VeritX Research — AI-native Network-on-Chip Architecture

Monorepo for the VeritX BTech research programme (6 months, 15 students, 4 tracks).
Each track studies a different aspect of AI-accelerator NoCs, sharing one toolchain
(Booksim, Timeloop, Accelergy, Yosys/SymbiYosys, CBMC, Verilator).

**You install nothing but a container runtime.** Every tool is prebuilt into the
image `internal-devrepo.datavex.ai:5050/anmol/veritx-research/veritx-tools-base:latest`, and `make` drives it. (A GHCR mirror,
`ghcr.io/anmol-s314/veritx-tools-base:latest`, is kept in sync for GitHub CI —
use it with `make shell IMAGE=ghcr.io/...` if you can't reach the internal host.)

## Quick start

```bash
make pull                                    # download the tools image (once)
make run TRACK=t3-topology CMD=timeloop      # run a track command inside the image
make run TRACK=t3-topology CMD=dashboard     # build the T3 dashboard
make shell                                   # or drop into the image and poke around
make help                                    # list everything
```

Only prerequisite: **podman** or **docker** (auto-detected).

## Commands

Run from the repo root. `make run` executes a track command *inside the image*, so
it works even with nothing installed locally.

| Command | What it does |
|---|---|
| `make help` | List available commands (also works inside any track dir) |
| `make pull` | Download the prebuilt tools image (GitLab registry; GHCR is the mirror) |
| `make run TRACK=<t> CMD=<c>` | Run track `<t>`'s command `<c>` **inside the image** — e.g. `make run TRACK=t4-formal CMD=test` |
| `make shell` | Open an interactive bash shell inside the image (run tools by hand) |
| `make setup\|lint\|test\|sim TRACK=<t>` | Run that phase for a track (on the host; use `make run` if you lack the tools) |
| `make report` | Build the aggregate cross-track report into `report/` |
| `make clean` | Remove all generated `results/` and `report/` |
| `make image-build` / `make image-push` | Build / push **this commit's** image `:<sha>` (maintainers) |
| `make image-promote` | Run every track's tests against `:<sha>`, then move `latest` to it (maintainers) |
| `make image-rev` | Print the commit that built the image you're actually running |

Set `IMAGE=…` to point at a different image. Runtime is auto-detected as podman or docker.

### Image versioning — why `latest` is not enough

Every image is tagged twice: `:latest` and `:<commit-sha>`, with the commit stamped
into an OCI label. That exists because a floating `latest` cannot answer the one
question that matters when a number looks wrong — *which image produced it?*

This is not hypothetical. A stale `latest` once carried Accelergy's `dummy_tables`
estimator, which answers **1 pJ and 1 µm² to every query and exits 0**. The whole
pipeline stayed green and reported a fabricated die area. Nothing crashed.

```bash
make image-rev                          # which commit built the image I'm running?
make run TRACK=t3-topology CMD=area TAG=a1b2c3d   # reproduce an old result exactly
```

`latest` moves only by **promotion**: CI builds `:<sha>`, runs the entire suite
against that exact image, and retags it `latest` only if everything passed. A red
pipeline leaves `latest` untouched and still working. `make image-promote` is the
same gate by hand. Never `docker push …:latest` directly — that is how an image
nobody tested becomes the image everybody pulls.

### Per-track commands

Every track exposes the same verbs (`make run TRACK=<t> CMD=<verb>`, or
`make -C tracks/<t> <verb>`):

| Verb | Does |
|---|---|
| `setup` | Check the track's tools are present (friendly hint if you're outside the image) |
| `lint` | Syntax-check the scripts |
| `test` | Quick sanity run — the CI gate |
| `sim` | The track's experiment suite |
| `help` | List that track's commands |

**T3** adds three more: `timeloop` (the full Timeloop → traffic-matrix → Booksim
topology-sweep spine), `energy` (Timeloop's per-component pJ/compute breakdown +
energy-delay product → `results/energy.json`), and `dashboard` (build
`report/t3/index.html`).

## How the tooling fits together

- **One image** (`Dockerfile`, multi-stage) holds every tool, pinned. Students never compile anything; CI pulls the same image.
- **`tracks/common.mk`** is included by each track's `Makefile` and provides `make help` plus the `need`/`want` tool-check macros — so behaviour and messages are consistent and defined in one place.
- **Adding a track:** copy an existing `tracks/<x>/`, `include ../common.mk`, keep the `setup/lint/test/sim` verbs. It then shows up in `make help` and `make TRACK=<x> …` with **no root-Makefile changes**.

## Repository structure

```
.
├── Makefile               # top-level commands (help / run / shell / pull / …)
├── tracks/
│   ├── common.mk          # shared Make machinery (help + tool-check macros)
│   ├── onboarding/        # toolchain validation — start here
│   ├── t1-kvcache/        # KV-cache QoS with gem5/Garnet/ASTRA-sim (deferred)
│   ├── t2-deadlock/       # routing deadlock with Booksim 2.0
│   ├── t3-topology/       # topology co-opt with Booksim + Timeloop + Accelergy
│   └── t4-formal/         # formal verification with SymbiYosys + Yosys + CBMC
├── third_party/
│   └── booksim2/          # vendored BookSim 2.0 (git subtree) + VeritX edits — see VERITX.md
├── archive/               # superseded machinery, kept for reference (pre-subtree booksim-ext)
├── scripts/               # cross-track report generation
├── Dockerfile             # multi-stage build of all tools
└── .github/workflows/     # GitHub Actions CI (5-cell matrix)
```

Booksim (used by T2 and T3) is **vendored as a git subtree** under `third_party/booksim2/`.
You change the simulator by editing its real source — see
[`third_party/booksim2/VERITX.md`](third_party/booksim2/VERITX.md) for the edit/rebuild
loop and the `git subtree pull` version-bump.

## Per-track guides

| Track | What you study | Files you edit | Status |
|-------|---------------|----------------|--------|
| [Onboarding](tracks/onboarding/README.md) | Toolchain sanity | — | First |
| [T1](tracks/t1-kvcache/README.md) | KV-cache QoS (gem5) | `configs/*.py` | *Deferred* |
| [T2](tracks/t2-deadlock/README.md) | Deadlock avoidance | `configs/*.cfg` | ✅ |
| [T3](tracks/t3-topology/README.md) | Topology × traffic | `scripts/timeloop_to_matrix.py` | ✅ |
| [T4](tracks/t4-formal/README.md) | Formal verification | `rtl/*.sv`, `configs/*.sby` | ✅ |

## Student workflow

```
1. git checkout -b <track>/<experiment-name>
2. <edit your track's files>
3. make run TRACK=<track> CMD=test      # check it locally, in the image
4. git commit  &&  git push             # CI runs the full pipeline
```

Every result must be reproducible from a `make` command and tied to a commit.

## CI pipeline

GitHub Actions runs a 5-cell matrix on every push (inside the same image):

```
onboarding  ── setup → lint → test
t1-kvcache  ── setup → lint → test (gem5 deferred)
t2-deadlock ── setup → lint → test → sim → artifacts
t3-topology ── setup → lint → test → sim → timeloop → dashboard
t4-formal   ── setup → lint → test → sim → artifacts
     └── report ── aggregates all tracks → artifact
```

Full `sim`/`timeloop` run on `main` and manual triggers. Results and the T3
dashboard are uploaded as **downloadable CI artifacts** — kept private to the repo.

## Dashboard (T3)

`make run TRACK=t3-topology CMD=dashboard` builds a self-contained
`report/t3/index.html`: traffic-matrix heatmap, latency-vs-injection curves,
hops (energy proxy), a per-commit regression table, and a Timeloop bottleneck
breakdown. A **run selector** lets you inspect any past run, and there's a
light/dark toggle.

Per the programme's IP rules, results are **not** published to a public URL — the
dashboard is a private CI artifact (or `make ... CMD=dashboard` locally). History
persists across CI runs on a private `gh-pages` branch; do **not** enable GitHub
Pages unless it's the private (paid-plan) variant.

## Tool versions

Pinned in `internal-devrepo.datavex.ai:5050/anmol/veritx-research/veritx-tools-base:latest`:

| Tool | Version | Track |
|------|---------|-------|
| Booksim 2.0 (+ `matrix` traffic pattern) | commit `28f4329` | T2, T3 |
| Timeloop | commit `6b70505` (pre-barvinok) | T3 |
| Accelergy | latest | T3 |
| Yosys | 0.66+ | T4 |
| SymbiYosys | latest | T4 |
| CBMC | 6.10.0 | T4 |
| Verilator | 4.038 | T4 |
| z3 | 4.8.12 | T4 |
| gem5 | *deferred build* | T1 |

## License

See [LICENSE](LICENSE).
