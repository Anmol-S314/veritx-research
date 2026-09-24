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

### 5.3 Validation corpus pytest

```text
PYTHONPATH=... pytest validation/tests -q
15 passed, 1 failed   (ASTRA unbuilt)
```

The single failure was the engine gate requiring the ASTRA binary
(`test_independent_engines_pass`); `ramulator_battery` also reported
`0/1 checks`. Re-run with ASTRA built is recorded in the closure plan.

### 5.4 Full validation battery

```text
python3 -m validation.harness.run --all --mutations --metamorphic --engines --intervention
```

Not green at baseline (engines require ASTRA; ASTRA was unbuilt at the
first fetch). Re-run after the ASTRA build is required before any seal.

## 6. Known failures / skips at baseline

| Item | Classification | Release-critical? |
|------|----------------|-------------------|
| legacy compiler reachable (`application/compile.py`) | real authority defect | yes (P0) |
| `test_no_booksim_binary_needed_for_canonical_compile` | environment-conditional proof | no (test hygiene) |
| 9 ASTRA-absent serving failures | fixed by building ASTRA | no |
| `ramulator_battery` 0/1 checks | backend not built / gating | yes (engine gate) |
| 15 skipped (fast tier) | unclassified | must inventory |
| 160 deselected `real` tests | live backend tier, slow | structural |

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
