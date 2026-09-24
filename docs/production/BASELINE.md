# VERITX Production Baseline

Captured at the creation of `prod/production-readiness`. This document is
the reproducibility anchor for the production program: every later claim
is compared against these exact inputs and outputs.

## 1. Base refs (resolved 2026-09-24, not assumed)

| Ref | SHA | Role |
|-----|-----|------|
| `origin/main` | `4be11e484aa81aa36799a9098f132f1eacfe2d2c` | internal remote main |
| `github/main` | `d7eb7bbee5d20b4de92e575d7c858fd4e1207a05` | GitHub mirror main |
| `github/veritx-integrate` | `39a180ecc87c90241a674d59d1c4f14deda721bb` | canonical integration authority |
| `github/validation/b4-campaign` | `190d04f1` (was `9d040afa` at fetch; advanced during setup) | B4 validation |
| `github/integration/canonical` | `2f727dd1503c00697b2afaeda75a7fa6947dd1c3` | pinned canonical base |
| local `integration/canonical` | `96603ae21142ef48816ad9443701eb37ab8b3ddd` | one commit ahead of pin |

Lineage: `main` is an ancestor of `veritx-integrate`; `veritx-integrate`
is an ancestor of `validation/b4-campaign`. The B4 campaign is therefore a
clean linear descendant of the canonical integration, not a divergent
fork that needs a merge.

## 2. Production branch

| Field | Value |
|-------|-------|
| branch | `prod/production-readiness` |
| base | `190d04f1` (F-0004 hardening + full campaign freeze, B4 tip) |
| worktree | `/home/datavex/veritx-production` |
| HEAD at baseline | `8d61da35edbfb5289261a4b2b2b7434103833642` |
| dirty status | clean |
| upstream | deliberately unset (do not push to `validation/b4-campaign`) |

`prod/production-readiness` = B4 tip + three P0 closure commits:

```text
8d61da35 P0/cert:  fail closed on certificate obligations — no fault laundering
8c32ccc2 P0/model: remove shadow CompileRequest/migrate_design duplicate
a0b934b6 P0/vc:    fail closed on malformed VC-assignment authoring/persistence
190d04f1 F-0004 hardening + full campaign freeze   <- B4 base
```

The B4 fixes F-0001 and F-0004 are present via `190d04f1`; the exact
step/phase ring-oracle hardening is present via the same commit.

## 3. Toolchain identity

| Tool | Version / identity |
|------|--------------------|
| Python | 3.14.4 |
| g++ | 15.2.0 (Ubuntu 15.2.0-16ubuntu1) |
| Verilator | 5.032 2025-01-01 |
| cmake | 4.2.3 |
| protoc | libprotoc 3.21.12 |
| flex / bison | present (BookSim lex/yacc build) |
| pytest | 9.0.3 |

The supported interpreter floor in `pyproject.toml` is `>=3.10`; the
baseline was taken on 3.14, the newest available. A 3.12 interpreter is
also present (`~/.local/bin/python3.12`) and is used by the vendored
Ramulator battery.

## 4. Backend provenance (built in this worktree)

| Backend | Path | SHA256 | Size |
|---------|------|--------|------|
| BookSim2 | `third_party/booksim2/src/booksim` | `936aeefdfab9dfac4aa9a28e84987cec47ea5431145bcfdd4b7f291bbeca6ba9` | 20832448 |
| ASTRA-Sim frontend | `third_party/astra-sim/astra-sim/network_frontend/booksim2/bin/AstraSim_BookSim2` | `7d4bb43574988fbfcf12f9102cc58d6387726cbc8552a34ee35a9884f040aba5` | 4028520 |
| Ramulator2 | `third_party/ramulator2` | source tree; builds under vendored Python 3.12 | n/a |

Build commands (tracked source only — no gitignored build logic):

```bash
cd third_party/booksim2/src && make -j$(nproc)
JOBS=12 bash third_party/astra-sim/build/astra_booksim2/build.sh
```

Note: neither binary is tracked by Git. The baseline above is valid only
for a worktree that rebuilt them; binary identity is bound into evidence
via `binary_sha256`, but build provenance is **not yet manifest-bound** —
see `AUTHORITY-MAP.md` concept `backend build provenance` and the closure
plan item P0.6.

## 5. Test commands and results

All runs from `/home/datavex/veritx-production` with
`PYTHONPATH=tracks/t3-topology/dse:tracks/t3-topology/dse/tests`.

### 5.1 Full DSE suite — BEFORE any closure (B4 `9d040afa`, ASTRA absent)

```text
pytest tracks/t3-topology/dse/tests -q -p no:randomly
24 failed, 3538 passed, 34 skipped in 104.65s
```

Breakdown of the 24: 13 VC-assignment contract failures, 9
ASTRA-binary-absent serving failures, 1 legacy-compiler authority
failure, 1 migration byte-identity failure, 1 environment-conditional
proof failure.

### 5.2 Fast tier AFTER P0 closures (ASTRA built)

```text
pytest tracks/t3-topology/dse/tests -q -p no:randomly -k "not real"
2 failed, 3426 passed, 15 skipped, 160 deselected in 104.83s
```

Remaining failures:

```text
test_application_service.py::test_application_package_reaches_no_legacy_compiler
    -> application/compile.py still exists and is reachable (P0 authority, open)
test_cli_compile_surface.py::test_no_booksim_binary_needed_for_canonical_compile
    -> asserts a binary is ABSENT; fails because baseline built BookSim (skip policy, open)
```

The 160 deselected `real` tests are the live-backend matrix (T4). They
were previously failing because ASTRA was unbuilt; with ASTRA built they
execute real backend rounds (up to 600 s each), which is why the default
run must exclude them (see `SKIP-INVENTORY.md`).

### 5.2b Fast tier AFTER all P0 closures (all three engines built)

```text
pytest tracks/t3-topology/dse/tests -q -p no:randomly -k "not real"
3458 passed, 13 skipped, 160 deselected in 103.80s   (0 failed)
```

Closed since 5.2: legacy compiler authority, VC contract, certificate
laundering, model duplicate, exact clock, evidence admissibility, plus
the environment-conditional BookSim-absence proof (now a positive proof).
Remaining risk in this tier is the 13 unexplained skips (§23 skip
inventory) and the 160 deselected live-backend tests.

### 5.3b Validation corpus pytest (all engines built)

```text
PYTHONPATH=... pytest validation/tests -q
16 passed in 306.34s   (0 failed)
```

Baseline with ASTRA absent was `15 passed, 1 failed` (engine gate). With
BookSim + ASTRA + Ramulator built the engine gate itself passes
(`validation/tests/test_engines.py` → `1 passed in 191.51s`).

### 5.4b Backend build commands that actually work in this environment
```bash
cd third_party/booksim2/src && make -j$(nproc)          # -> src/booksim
JOBS=12 bash third_party/astra-sim/build/astra_booksim2/build.sh
cd third_party/ramulator2 && JOBS=12 ./build.sh          # NOT "bash build.sh"
```

Note: `bash third_party/ramulator2/build.sh` fails silently with exit 1
because the script resolves its own path via `command -v "$0"` and
`build.sh` is not on PATH. This is a reproducibility trap (P0 in the
closure plan's reproducible-build phase).

### 5.5 Full validation battery (all engines built)

```text
python3 -m validation.harness.run --all --mutations --metamorphic --engines --intervention
```

Result: **72/72 checks exact, 0 quarantined**. V01–V10 PASS, mutations
M1–M8 CAUGHT, metamorphic M1–M8 PASS, F-0003 SUPPORTED, engine gates:

```text
ramulator_battery  PASS  established      16/16 checks
rtl_selfcheck      PASS  established      GATE R0 ALL CHECKS PASSED
astra_runtime      PASS  NOT_ESTABLISHED  executes; aggregate/exposed_comm unexplained
```

ASTRA numerical validity remains explicitly NOT_ESTABLISHED and is
excluded from scientific comparison. The generated report files
(`validation/reports/*.json`, `ENGINES.md`, `MUTATIONS.md`) differ from
the committed B4 freeze only in run-varying metadata (wall time, local
binary SHA, ephemeral scratch paths), so they were **not** committed —
committing them would put untracked-run provenance into tracked evidence.
Finding: the harness embeds the run's temp directory path in report text;
that should be normalized before reports are used as durable evidence
(§7).

## 6. Known failures / skips at baseline

| Item | Classification | Release-critical? |
|------|----------------|-------------------|
| legacy compiler reachable (`application/compile.py`) | CLOSED `9eb7c2e6` | — |
| `test_no_booksim_binary_needed_for_canonical_compile` | CLOSED `7e7c440e` (positive proof) | — |
| 9 ASTRA-absent serving failures | CLOSED by building ASTRA | — |
| `ramulator_battery` 0/1 checks | CLOSED by building Ramulator | — |
| 13 skipped (fast tier) | unclassified | must inventory (§23) |
| 160 deselected `real` tests | live backend tier, slow | structural (§22) |

## 7. B4 validation result at baseline

The B4 corpus is present and its oracle now enforces exact step ids
`[0..n-1]` and exact ALLREDUCE phase ranges (`0..k-2` reduce-scatter,
`k-1..2k-3` all-gather) via `190d04f1`. `validation/FINDINGS.md` records
F-0001 and F-0004 as FIXED and F-0002 as ACCEPTED. This validates
**network-level ring semantics only**; chunk ownership/rotation is not
modeled by `LogicalMessage` and is explicitly out of scope
(F-0004 scope note).

## 8. Reproducibility caveat

This baseline is a developer-worktree baseline, not a clean-clone
baseline. It has no build manifest, the backends are untracked binaries,
and the Python environment is the host interpreter (no lockfile/venv).
Clean-clone qualification (P8/P13) is owed and is the gate that converts
this baseline into a production baseline.
