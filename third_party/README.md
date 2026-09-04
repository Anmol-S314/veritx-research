# third_party — vendored tools

This tree pins the external simulators/tools VeritX research runs on. Nothing here
is "our" code except the small local patches recorded per tool; upstream source is
checked in so every run is reproducible from a commit, with no network fetch.

Every tool directory carries a `METADATA.json` — **that file is the source of truth**
for what is vendored, where it came from, how to build it, and where copies of it
must be kept in sync. The tooling around it lives in `scripts/tools.py`
(see the root README's *Vendored tool management* section for the `make tool-*`
targets).

## Inventory

| Tool | Pin (METADATA `commit`) | What it is | Canonical source | Synced to |
|---|---|---|---|---|
| astra-sim | `518bd51` | Network simulator + Chakra/ns-3 externs | `third_party/astra-sim/` | — |
| booksim2 | `28f43299` | Cycle-accurate NoC simulator | `third_party/booksim2/src/` | astra-sim extern `network_backend/booksim2/booksim2` |
| llmservingsim | `2c2042c` | LLM serving simulator | `third_party/llmservingsim/` | — (wires astra-sim, see below) |
| timeloop | `6b70505` | DNN accelerator mapper | `third_party/timeloop/` | — |

`python3 scripts/tools.py` lists all four and reports whether each binary is built.

## Daily commands

```bash
make tools                                    # list tools + binary status
make tool-info TOOL=booksim2                  # full detail (deps, gaps, sync targets)
make tool-build TOOL=booksim2                 # compile canonical source (cd src && make)
make tool-clean TOOL=booksim2                 # remove build artifacts
make tool-run TOOL=booksim2 ARGS="examples/foo.cfg"   # run the binary
make tool-sync TOOL=booksim2                  # canonical src -> downstream copies
python3 scripts/tools.py booksim2 sync --check   # dry-run the sync (read-only, use first!)
```

## How the wiring works

**booksim2 canonical → astra-sim extern.** The real source of truth is
`third_party/booksim2/src/`. astra-sim's network backend
(`third_party/astra-sim/extern/network_backend/booksim2/booksim2/src`) must mirror it —
that copy is what astra-sim compiles when the DSE runs serving simulations. **Never
hand-edit the extern copy.** After any change to canonical source (or after any merge
that touches it), run:

```bash
python3 scripts/tools.py booksim2 sync --check   # see what would change
python3 scripts/tools.py booksim2 sync           # copy canonical -> extern
# then rebuild astra-sim's booksim backend (echoed by post_sync):
cd third_party/astra-sim/extern/network_backend/booksim2/build \
  && cmake .. -DBOOKSIM2_SRC_DIR=$(realpath ../../../../../../third_party/booksim2) \
  && make -j$(nproc)
```

**llmservingsim → astra-sim.** `third_party/llmservingsim/astra-sim/{astra-sim,build,
extern,inputs,network_frontend}` are **symlinks into the standalone
`third_party/astra-sim/`** so the serving simulator and the network simulator share one
source tree. See *Known issues* below — these are absolute symlinks and need a setup
story for fresh clones.

**Binaries are never tracked.** `booksim`, `libveritx_embed.a`, `build/` dirs etc. are
build output; keep them out of git (booksim2's sync `skip` list already excludes them).

## Known issues & improvement backlog

Friendly, actionable notes for whoever picks these up. Tagged by priority; all current
as of the 2026-09-04 `feat/veritx-cli` → main merge.

- **[security][P0] Live credentials are tracked in `docs/archive/VM-SETUP.md`** — it
  contains a real VM password, host IP and VNC credentials. Delete the file, add it to
  `.gitignore`, and rotate the credentials. Note they also exist in git *history*, so a
  full removal needs a history rewrite (`git filter-repo`) — decide if that's warranted.
- **[process][P1] Add a sync-drift check to CI.** Merging `origin/main` into
  `feat/veritx-cli` silently desynced 4 booksim2 files (the merge took main's
  `gec.cpp/hpp`, `routefunc.cpp`, `booksim_config.cpp` into canonical while astra-sim's
  extern copy kept the old versions); 11 more files had drifted before the merge. All 15
  are now synced, but nothing stops it recurring. A CI step running
  `python3 scripts/tools.py booksim2 sync --check` and failing on any diff would catch it.
- **[portability][P1] llmservingsim's astra-sim symlinks are absolute**
  (`/home/datavex/veritx-research/third_party/astra-sim/...`) and nothing in-repo creates
  them — a fresh clone on another machine has no `llmservingsim/astra-sim/*` and the DSE
  breaks. Replace with relative symlinks or add a small setup script
  (e.g. `scripts/`) that creates them.
- **[GEC][P2] Pricing gap: `use_noc_latency=1` is refused, not priced.** Canonical
  `gec.cpp` (main's GEC work, merged 2026-09-04) supports mesh / hybrid mesh+MECS
  (`hybrid=1` + `routing_function=hybrid_gec`) / express / MECS modes, but hardcodes
  1-cycle channel latency and exits on `use_noc_latency=1`. The per-wire priced express
  variant lives on `alice-booksim-wirepriced`. Decision needed: port it here (then
  update METADATA + the guard), or keep the guard and always compare with
  `use_noc_latency=0` on both sides. Battle scripts assuming priced GEC hard-fail until
  then.
- **[TODO] snake_mesh / snakeroute.** `Flit::mcast` support now exists
  (`flit.hpp`: `mcast` + `mcast_copies`), but `snake_mesh` registration is still
  commented out in `veritx_ext.cpp` and `snakeroute.{cpp,hpp}` stay excluded — porting
  snake routing onto the mcast-fork model is open work.
- **[docs] METADATA drift guardrail.** If you modify vendored source, update that
  tool's `METADATA.json` `local_modifications`/`known_gaps` in the same commit — it feeds
  `make tool-info` and is how the next person learns what you changed (this bit us once
  already: the gaps text described pre-merge state).
- **[size][P3] Repo is heavy.** Working tree ≈ 120 MiB tracked; the pack (clone) is
  ≈ 3.4 GiB. Biggest tracked items: `tracks/t3-topology/dse/inputs/traces/qwen3_serving_astra.trace`
  (11.5 MB), ns-3 LTE fading traces (~8.3 MB × 3, upstream vendor), llmservingsim
  profiler CSVs (~1 MB × ~dozen, upstream vendor). Plus redundant `*_archive*`/`archive/`
  dirs (e.g. `tracks/t3-topology/dse/inputs/archive/`) duplicating live inputs. Options:
  prune history with `git filter-repo` (team decision — rewrites shared history), move
  large data files to Git LFS or a release asset, and stop committing new trace/profiler
  data. Run `git gc --prune=now` occasionally to clean stray temp objects.
- **[build] astra-sim build is on-disk only.** `third_party/astra-sim/build/` (≈ 120 MB)
  is gitignored — expected, but remember a fresh clone must rebuild before running the DSE.

## Contribution rules of thumb

1. Edit **canonical** source only: `third_party/<tool>/src/…`. Never edit astra-sim's
   extern booksim2 copy by hand.
2. Update `<tool>/METADATA.json` `local_modifications` for anything you change.
3. Build + smoke test (`make tool-build`, `make tool-run`), then `tools.py <tool> sync`
   if the tool has sync targets.
4. Keep `python3 scripts/tools.py` green (it validates METADATA + binary status).
5. Don't commit build artifacts (`booksim`, `*.a`, `build/`, `results/`, `report/`).

## Verification cheatsheet

```bash
python3 scripts/tools.py list                  # every tool visible, binaries OK
python3 -c "import json;[json.load(open(f'third_party/{t}/METADATA.json')) for t in ['astra-sim','booksim2','llmservingsim','timeloop']]"  # METADATA parses
python3 scripts/tools.py booksim2 sync --check # canonical/extern copies agree
make -n tools tool-sync TOOL=booksim2          # Makefile targets wired to the right CLI
```
