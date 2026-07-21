# T3 Topology — Run Directory

This is the **canonical entry point** for the T3 topology track.  
Anyone who wants to run the T3 analysis/simulation flow should start here.

## Quick Start

```bash
# 1. Navigate to this directory
cd tracks/t3-topology/run

# 2. Source the environment (sets all T3_* variables and puts 't3' on PATH)
source env.sh

# 3. Run the full pipeline
t3 all
```

## What `env.sh` Does

`env.sh` sets up all environment variables needed by the `t3` CLI and the
Python scripts. **You only need to source it once per shell session.**

| Variable         | Default                     | Description                        |
|------------------|-----------------------------|------------------------------------|
| `T3_DIR`         | `../` (t3-topology/)        | Track root directory               |
| `T3_RESULTS`     | `$T3_DIR/results/`          | Where simulation output lives      |
| `T3_OUTPUT`      | `$T3_DIR/output/`           | Where analysis outputs are written |
| `T3_SCRIPTS`     | `$T3_DIR/scripts/`          | Python scripts directory           |
| `T3_PYTHON`      | venv or system python3      | Python interpreter                 |
| `BOOKSIM_BIN`    | `booksim`                   | Booksim binary (must be on PATH)   |
| `RATES`          | `0.002,0.005,0.01,0.02,0.03`| Injection-rate sweep values        |
| `PACKET_SIZE_BITS`| `128`                      | Energy proxy constant              |
| `SAT_K`          | `2.0`                       | Saturation threshold multiplier    |
| `MPLBACKEND`     | `Agg`                       | Matplotlib backend (headless)      |

## Overriding Variables

Set any variable **before** sourcing `env.sh`:

```bash
# Use a custom output directory
T3_OUTPUT=/data/my_run source env.sh

# Use a different booksim binary
BOOKSIM_BIN=/opt/booksim/bin/booksim source env.sh

# Override injection rates
RATES="0.01,0.02,0.05" source env.sh && t3 sim
```

## Common Commands

```bash
t3 help          # full command reference
t3 check         # verify tools and environment
t3 sim           # run Booksim uniform-traffic sweep
t3 analysis      # PA-01: parse results → DataFrame summary
t3 aggregate     # PA-02: merge results → output/aggregate.csv
t3 plot          # PA-03: latency-throughput curves → output/latency_curves.png
t3 all           # run full pipeline: analysis → aggregate → plot
t3 env           # print all active environment variables
```

## Why a `run/` Directory?

Keeping the entry point in its own directory means:
- A single `source env.sh` sets up everything — no absolute paths to remember.
- The Makefile and scripts stay in the track root, co-located with the configs
  and results they reference.
- CI/CD can simply `cd run && source env.sh && t3 all`.

> **Note:** The `Makefile` lives in the track root (`t3-topology/`), not here.
> It picks up all `T3_*` variables when sourced via this `env.sh`, so
> `make analysis` / `make plot` also work once you've sourced `env.sh`.
