# VERITX Final Baseline (C0)

Recorded before further closure work. This file complements `BASELINE.md`
(the historical branch/SHA inventory); it is the reproducibility snapshot
the closure program requires. Raw logs are kept outside the repository
(`/tmp/veritx-baseline/`).

## Release position

| field | value |
|-------|-------|
| branch | `prod/production-readiness` |
| release candidate SHA | `2521d7135a4e2c1c55227d2ee6080639326ce1ed` |
| worktree | `/home/datavex/veritx-production` |
| working tree | clean at record time |
| `github/prod/production-readiness` | `bd6be628` (rebase/push owed; local is ahead by 3 closure commits) |
| `main` | `4be11e4` (untouched) |

## Toolchain

| tool | version / identity |
|------|--------------------|
| Python | 3.14.4 (`/usr/bin/python3`) |
| g++ / gcc | 15.2.0 (Ubuntu 15.2.0-16ubuntu1) |
| clang++ | not installed on the host |
| Verilator | 5.032 (2025-01-01) |
| container runtime | podman 5.7.0 |

## Backends

| backend | path | identity |
|---------|------|----------|
| BookSim (fork) | `third_party/booksim2/src/booksim` | sha256 `936aeefdfab9dfac4aa9a28e84987cec47ea5431145bcfdd4b7f291bbeca6ba9`; size 20832448 |
| BookSim build manifest | `third_party/booksim2/src/booksim.build-manifest.json` | recipe `booksim2-fork/v1`, compiler `g++`, config Release, `source_revision 43f55d94`, `source_dirty false` |
| ASTRA-Sim | `third_party/astra-sim/astra-sim/network_frontend/booksim2/bin/AstraSim_BookSim2` | sha256 `7d4bb43574988fbfcf12f9102cc58d6387726cbc8552a34ee35a9884f040aba5`; recipe `astra-sim+booksim2/v1` |
| Ramulator | `third_party/ramulator2/libramulator.so` | vendored Python extension via `simulation/ramulator.py`; engine gate 16/16; no binary manifest (documented limitation) |

BookSim's `routing_dump_file` first-hop dump hook is present in the
vendored source and compiled into the binary (verified via `strings`).

## Test totals (at the release candidate SHA)

| tier | command | result |
|------|---------|--------|
| fast DSE (`-k "not real"`) | `pytest tracks/t3-topology/dse/tests -q -p no:randomly -k "not real"` | **3530 passed, 13 skipped, 160 deselected** (126 s) |
| validation pytest | `pytest validation/tests -q` | **20 passed** (308 s) |
| validation harness | `python3 -m validation.harness.run --all --mutations --metamorphic --engines --intervention` | V01–V14 PASS; mutations CAUGHT; metamorphic PASS; engines pass; intervention SUPPORTED; 0 quarantined |
| live backend (`-k real`, with `VERITX_BOOKSIM_BIN` set) | `pytest tracks/t3-topology/dse/tests -q -k "real"` | last run at `bd6be628`: **153 passed, 12 skipped** (877 s); re-run at the RC SHA owed in C10 |

### Skip inventory (fast tier)

13 skips, all classified in `SKIP-INVENTORY.md`:

- 6 × historical Wave-D v1 artifacts deleted (`LEGACY_ONLY`, not release-critical)
- 1 × historical `astrasim_adapter` heuristic superseded (`DEPRECATED`)
- 1 × `VERITX_ASTRA_REF_BIN` unset — two-binary ASTRA differential (`OPTIONAL_BACKEND`, release-critical for ASTRA numerics)
- 6 × `test_full_pipeline.py` trace fixtures not vendored (`TEMPORARY_BLOCKER`, release-critical — C7.1)

## Open findings at baseline

| finding | status |
|---------|--------|
| F-0001 completion-window artifact | FIXED |
| F-0002 BookSim hops +1 | ACCEPTED |
| F-0003 injection-bound completion | SUPPORTED (low-pressure) |
| F-0004 "ring" was full exchange | FIXED |
| F-0005 B7 allow-list gap | FIXED |
| F-0006 ALLGATHER factor-k over-transmission | FIXED |
| F-0007 convergence window truncates concentrated multi-flit traces | FIXED (`e9abab38`) |

## Gates run before any code change

The fast and live tiers, the validation pytest and the full harness were
run on the pre-change tree (logs in `/tmp/veritx-baseline/`). The V13
broadcast conservation refusal recorded there (`delivered 132 != declared
300`) was root-caused to F-0007 and fixed; no expected value was edited
before the baseline was captured.
