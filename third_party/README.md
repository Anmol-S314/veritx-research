# third_party — vendored tools

External simulators the research runs on, checked in so every run is reproducible
from a commit (no network fetch). We only patch them; the patches are recorded per
tool in `METADATA.json`.

> **`METADATA.json` is the source of truth.** Each tool directory carries one: where
> the code came from, how to build it, what we changed, and which copies must stay in
> sync. `scripts/tools.py` (and the root `make tool-*` targets) drive everything from it.

## Inventory

| Tool | Pin | What it is | Canonical source | Synced to |
|---|---|---|---|---|
| `astra-sim` | `518bd51` | Network simulator + Chakra/ns-3 externs | `third_party/astra-sim/` | — |
| `booksim2` | `28f43299` | Cycle-accurate NoC simulator | `third_party/booksim2/src/` | astra-sim extern booksim2 |
| `llmservingsim` | `a4053bc` | LLM serving simulator | `third_party/llmservingsim/` | — (wires astra-sim) |
| `timeloop` | `6b70505` | DNN accelerator mapper | `third_party/timeloop/` | — |

Run `python3 scripts/tools.py` to list all four with binary status.

## Using the tools

```bash
make tools                                   # list tools + binary status
make tool-info TOOL=booksim2                 # details: deps, gaps, sync targets
make tool-build TOOL=booksim2                # compile canonical source
make tool-run  TOOL=booksim2 ARGS="examples/foo.cfg"
make tool-clean TOOL=booksim2
make tool-sync TOOL=booksim2                 # push canonical src to downstream copies
python3 scripts/tools.py booksim2 sync --check   # read-only dry run — do this first
```

## How the copies relate

**Canonical → astra-sim extern (booksim2).** `third_party/booksim2/src/` is the real
source. astra-sim compiles its own mirror at
`third_party/astra-sim/extern/network_backend/booksim2/booksim2/src` — what the DSE
actually runs. That mirror must always equal canonical.

**Never hand-edit the extern copy** — it is regenerated. After changing canonical
source (or after any merge that touches it):

```bash
python3 scripts/tools.py booksim2 sync --check   # preview the diff
python3 scripts/tools.py booksim2 sync           # copy canonical -> extern
# rebuild astra-sim's booksim backend (echoed by post_sync):
cd third_party/astra-sim/extern/network_backend/booksim2/build \
  && cmake .. -DBOOKSIM2_SRC_DIR=$(realpath ../../../../../../third_party/booksim2) \
  && make -j$(nproc)
```

**llmservingsim → astra-sim.** `third_party/llmservingsim/astra-sim/` contains
**symlinks into the standalone `third_party/astra-sim/`**, so serving and network
simulation share one source tree. ⚠️ They are currently absolute links — see the portability
item in the backlog below.

**Binaries are never tracked.** `booksim`, `*.a`, `build/`, `results/`, `report/` are
build output — keep them out of git (booksim2's sync `skip` list already excludes them).

## Changing vendored code — rules of thumb

1. Edit **canonical** source only (`third_party/<tool>/src/…`), never the extern copy.
2. Update that tool's `METADATA.json` (`local_modifications` / `known_gaps`) in the
   same commit — it feeds `make tool-info` and tells the next person what changed.
3. Build + smoke test (`make tool-build`, `make tool-run`).
4. Run `tools.py <tool> sync` if the tool has sync targets, then re-check
   (`sync --check` → *All … in sync*).
5. Don't commit build artifacts.

## Improvement backlog

Tagged by priority. Current as of the 2026-09-04 `feat/veritx-cli` → main merge.

**P1 — Add a sync-drift check to CI**
Merging `origin/main` into `feat/veritx-cli` silently desynced 15 booksim2 files
(4 from the merge taking main's `gec.cpp/hpp`, `routefunc.cpp`, `booksim_config.cpp`,
11 pre-existing). All are synced now, but nothing stops it recurring.
*Do:* a CI step running `python3 scripts/tools.py booksim2 sync --check` that fails on
any diff (`Found N differences` → exit 1). Note: `--check` exits 0 even with diffs, so
grep the output.

**P1 — Make llmservingsim's astra-sim symlinks portable**
The links point at absolute paths (`/home/datavex/…/third_party/astra-sim/…`) and
nothing in-repo creates them, so a fresh clone on another machine has no
`llmservingsim/astra-sim/*` and the DSE breaks.
*Do:* retarget the tracked symlinks to relative paths (`../../astra-sim/…`) or add a
setup script (`scripts/`) that creates them.

**P2 — GEC: `use_noc_latency=1` is refused, not priced**
Canonical `gec.cpp` (main's GEC work) supports mesh / hybrid mesh+MECS
(`hybrid=1` + `routing_function=hybrid_gec`) / express / MECS modes, but hardcodes
1-cycle channel latency and exits on `use_noc_latency=1`. The per-wire priced variant
lives on `alice-booksim-wirepriced`.
*Do:* decide — port the priced variant here (then update METADATA + the guard), or keep
the guard and always compare with `use_noc_latency=0` on both sides. Battle scripts
assuming priced GEC hard-fail until then.

**TODO — Port `snake_mesh` / `snakeroute` onto the mcast model**
`Flit::mcast` now exists (`flit.hpp`: `mcast` + `mcast_copies`), but `snake_mesh`
registration is still commented out in `veritx_ext.cpp` and `snakeroute.{cpp,hpp}`
remain excluded. Porting snake routing onto the mcast-fork model is open work.

**P3 — Repo is heavy**
Working tree ≈ 120 MiB tracked; the git pack (clone size) ≈ **3.4 GiB**. Biggest
tracked items: `tracks/t3-topology/dse/inputs/traces/qwen3_serving_astra.trace`
(11.5 MB), ns-3 LTE fading traces (~8.3 MB × 3, upstream vendor), llmservingsim
profiler CSVs (~1 MB × ~dozen, upstream vendor). `archive/` dirs (e.g.
`dse/inputs/archive/`) also duplicate live inputs.
*Do:* short-term, run `git gc --prune=now` to drop stray temp objects. For the
full phased plan (prune history with `git filter-repo`, LFS/asset offload for big
data) see the repo-size backlog item — ask the team before any history rewrite.

**Note — astra-sim build is on-disk only**
`third_party/astra-sim/build/` (≈ 120 MB) is gitignored by design — a fresh clone must
rebuild before running the DSE.

### Resolved

- **2026-09-04** — Live VM credentials in `docs/archive/VM-SETUP.md` removed
  (`78f00447`); both `docs` paths gitignored. Out-of-repo: rotate the credentials;
  scrub git *history* with `git filter-repo` only if the team decides it's warranted.

## Verification

```bash
python3 scripts/tools.py list                  # all tools visible, binaries OK
python3 scripts/tools.py booksim2 sync --check # canonical/extern agree
make -n tools tool-sync TOOL=booksim2          # Makefile targets wired to the right CLI
# METADATA files parse:
python3 -c "import json,glob;[json.load(open(f)) for f in glob.glob('third_party/*/METADATA.json')]"
```
