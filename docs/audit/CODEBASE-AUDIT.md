# VeritX Research — Codebase Audit

Date: 2026-09-29
Tree: `integration/studio-reconciliation` (dirty; 27 modified + 6 untracked paths)
Method: static inspection (`ast` walkers, pattern scans), full test run, provenance
cross-checks, CI/Makefile review. Coverage is broad, not exhaustive — ~98k LOC
first-party Python (`veritx_dse`) + ~26k LOC TypeScript (`apps/studio`) + track scripts.

Full test run: **25 failed, 5401 passed, 28 skipped** in 19m37s.

---

## 0. Executive summary

The codebase is a genuine mix. The certified backend path (`backend/booksim*.py`,
`core/process.py`, `simulation/llmserving_protocol.py`, `application/capability_truth.py`)
is careful, fail-closed, and honestly engineered. But the repo is **currently red**,
carries real dead/broken code, several gates are advertised but inert, and the
"truth/provenance" story has concrete holes (a stale release manifest, repo-wide
dirty coupling, asserts that vanish under `-O`).

The single biggest issue: **certified execution is impossible while *any* file in the
repo is uncommitted**, because build provenance computes dirtiness over the whole
repository. That is the root cause of 24 of the 25 test failures *today*.

---

## 1. Blocking / correctness findings

### B1. Repo-wide dirtiness taints every backend's provenance (root of 24 test failures)
`core/build_manifest.py:write_build_manifest` sets
`dirty = bool(_git(root, "status", "--porcelain"))` against the **repo root**, and
`backend/producer.py:resolve_producer_identity` does the same. So an uncommitted
frontend `.tsx` edit marks the vendored BookSim/ASTRA/Ramulator builds as dirty, and
`assert_pinned_producer` (`producer.py:196`) hard-refuses all reusable evidence.

Evidence: on-disk manifests currently record `"source_dirty": true`; the full suite
fails with `ASTRA producer not pinned, refusing spawn: producer tree is DIRTY`
(4 tests), `BookSim producer not qualified: producer tree is DIRTY` (2 tests), and
`assert 'UNSUPPORTED' == 'EVALUATED'` downstream of that (many tests).

Impact: a monorepo with an actively edited UI can never run certified science. The
dirty check should be scoped to the producer's source subtree, or replaced by a
content digest of the producer inputs.

### B2. Duplicate `plan_from_round` — first definition is dead and has a different signature
`backend/serving_round.py:355` and `:583` define the same name. The later one
(shadowing) returns a `ServingRoundPlan` and takes `instance_ranks/participant_count`;
the earlier one returns a `ServingBatchPlan` and takes `participant_ranks`. Nothing
calls the first; callers/tests all use the second signature. Misleading dead code that
will confuse the next reader (and would explode if anyone used the documented-looking
first signature).

### B3. Duplicate `edges_of` with an authoring artifact left in source
`synthesis/iterative_synthesizer.py:62` defines `edges_of` returning `set()` with the
comment *"unreachable — but the function is called; fix: Actually this was a bug in my
earlier script. Let me rewrite properly."* It is then redefined at `:68`. This is an
un-finished edit committed into the tree.

### B4. `eval_bs` swallows every failure as a latency sentinel
`synthesis/iterative_synthesizer.py:118-136`: any exception (missing binary, bad
config, timeout, parse failure) becomes `lat = 1e9`. The RHO/GRPO optimizers then
treat a broken backend as "very slow topology" and keep searching. A failed run must
be distinguishable from a slow one.

### B5. `assert` used for safety invariants in library code (28 sites; dies under `python -O`)
Examples: `application/requirements.py:367,411` (`ceiling/floor is not None`),
`backend/evidence.py:133` (`isinstance(value,str)`), `workload/graph.py:223`
(frozen-map check), `application/inventory.py:177`, `core/paths.py:75-76`,
`simulation/llmserving_protocol.py:346,363,390,425`. The codebase *elsewhere* explicitly
avoids asserts for exactly this reason (`application/fabric_evaluator.py:145`,
`optimization/result.py:1253`, `docs/product/INTENT-DESIGN-SPACE.md:238`) — so this is
an internal inconsistency, not a stylistic preference. Run with `-O` and these
fail-closed checks silently become no-ops.

### B6. Track `lint` targets can never fail
`tracks/{t1,t2,t3,t4}/Makefile` all use
`python3 -m py_compile scripts/*.py 2>/dev/null || true`.
The `|| true` and stderr suppression make it a no-op: a syntax error in any track
script passes CI's "Lint" step. The README claims lint syntax-checks the scripts.

### B7. T3 sanity "test" hardcodes PASS
`tracks/t3-topology/scripts/sanity_test.py:35` always writes `"status": "pass"`,
never checks `result.returncode`, and never fails on an empty config glob. This is the
`make test` CI gate for T3. (`t2`'s variant at least exits 1 on unparseable latency.)

### B8. Frozen v3 identity is broken by the in-progress edit
`tests/test_v3_semantics_frozen.py::test_v3_identity_is_byte_for_byte_unchanged` fails.
`git diff` shows `examples/qwen3_moe_tp2_ep4_16tiles-v3.json` changed `model_name`
and **added an `ep_combine` alltoall**, which moves the design hash, while the golden
fixture was not amended (the amendment test requires a documented amendment). The
working tree therefore does not satisfy its own freeze contract.

---

## 2. Unfinished / stub inventory

| Location | State |
|---|---|
| `tracks/t3-topology/scripts/timeloop_to_matrix.py:43` | `"""PLACEHOLDER spatial model — replace this for real T3 work (Wk6)."""` |
| `scripts/archive/milp_topology.py:92` | "using PuLP/CBC heuristic (same as greedy for now)" |
| `scripts/archive/noc_requirements.py:158` | "Nearest k neighbors (placeholder — real impl needs topology)" |
| `scripts/archive/gen_llmserv_traces.py:52` | `# KiB-ish placeholder` |
| `scripts/archive/milp_exactness_norm.py:67` | inline `# placeholder` in matrix build |
| `scripts/gen_trace.py:15,167` | `from_chakra is stubbed` → `raise NotImplementedError` |
| `dse/scripts/objective.py:48` | "weighted average (equal weight for now)" |
| `apps/studio/src/pages/implementation-lab.tsx:18` | "TOOL_CALIBRATED proxy (PLACEHOLDER ERT)" |
| `backend/canonical_serving.py` / `serving_round.py` | `autonomous_injection_packets` is 507×`null` by construction (the fork never emits the counter; the parser returns `None`). `SERVING_BACKLOG.md` bug 1. |
| `tests/test_compile_console_browser.py`, `test_live_browser_e2e.py` | large browser paths `pytest.skip` when playwright absent |

`SERVING_BACKLOG.md` itself documents more open items (round-level records, per-round
network packets, evidence browser). `docs/product/FULL-STACK-TRUTH-CLOSURE.md` lists
almost every capability row as **OPEN**.

---

## 3. "Truth" claims vs. reality

- **Stale release manifest.** `release-manifest.json` records ASTRA
  `binary_sha256 = de8782c7…`, but the on-disk binary *and* its per-binary manifest say
  `487c232d…`. The file is untracked and **not gitignored**, so it can be committed as
  authoritative while already lying about a binary. (`release_sha` is `bf736532`, older
  than the tree's start SHA `a05d7769`.)
- **Inert gates.** `lint` (B6) and the T3 sanity test (B7) are advertised checks that
  cannot fail. `pyproject.toml` sets `timeout = 900` but `pytest-timeout` is not
  installed by default (warning: "Unknown config option: timeout"), so a hung test
  hangs CI instead of failing it.
- **Frontend contract tests are dead.** `apps/studio/src/contract/*.contract.test.tsx`
  + `vitest.config.ts` exist, but `package.json` has no `test` script and no workflow
  invokes vitest — the two contract tests never execute.
- **Coverage gap on active branches.** The 5449-test DSE suite runs only in
  `release.yml` (prod/**, tags, PR→main). `ci.yml` (which runs on `integration/**`)
  runs only `product-gates` + the hardcoded-PASS sanity test. The current branch is
  `integration/studio-reconciliation`.
- **`apps/studio/package.json` description** still says "No engine connectivity; boots
  from contract-validated fixtures only" while the app now talks to a live gateway
  (`src/api/client.ts`, pages).

---

## 4. Robustness / design concerns

- **HTTP client has no timeout / AbortController** (`apps/studio/src/api/client.ts`):
  a hung gateway request hangs the UI forever.
- **Import-time side effects**: `gateway/app.py` ends with `app = create_app()` and
  `warn_if_stale()`, resolving binaries at import.
- **`ProductStore._locked`** opens a fresh `.store.lock` fd and `flock`s it per reentrant
  root; nested locking via two `ProductStore` instances on the same root in one thread
  can self-deadlock (flock is per open file description).
- **Broad silent swallows** in production paths (18 `except Exception: pass/continue`,
  e.g. `synthesis/bo_synthesizer.py:151,443`; `product/store.py:534,560,610`;
  `product/vnext.py:322,756`; `tools/multi_workload_pareto.py:49,137,157,304`). Some are
  deliberate cache skips; others hide real errors.
- **`iterative_synthesizer.py`** is a leftover standalone script whose logic is
  duplicated by `synthesis/rho_grpo_adapter.py`; it is not wired to the product.
- **Hardcoded probe shapes** (`application/capability_truth.py`, e.g. GEC
  `grid_side_length=8`) — intentional probes, but they are constants, not derived.
- **A dead-ish eval authority visible in UI**: `analytic-fake` is test-only in the
  backend, but `EvaluationAuthority` is typed and rendered in the Studio optimize views.
- **`sanity_test.py`-style** smoke tests can pass without exercising anything.

---

## 5. Repo hygiene / CI

- Root `node_modules/` is untracked **and not ignored**; `release-manifest.json` likewise.
- `.gitignore` lists `CHANGELOG.md` and `LICENSE` as "Generated docs" — wrong; new
  copies would be silently untracked.
- `.pytest_cache/`, `.hypothesis/` are only self-ignored by their tool-generated
  `.gitignore` files, not by the repo.
- `studio-live-e2e.yml` runs `make release-build` on a **plain runner** (not the tools
  container) that must supply `protoc`, `cmake`, `libprotobuf-dev`; it also installs
  Playwright through both pip and npm. Likely broken; unverified.
- `ci.yml` publishes to `gh-pages` via `peaceiris/actions-gh-pages@v4` (a third-party
  action **not pinned by SHA**) with `contents: write`, contradicting the README's
  "do not enable GitHub Pages" warning.

---

## 6. 25 test failures — grouped

- 24 are the **dirty-producer** cascade (B1): ASTRA runs refused (4), BookSim/ASTRA
  qualification refused (2), and downstream `UNSUPPORTED != EVALUATED/FAILED` (18,
  across `test_p2_*`, `test_p1_optimize_booksim`, `test_multi_fidelity_objectives`,
  `test_product_federation`, `test_run_bundle`, `test_optimize_canonical_cli`,
  `test_closure_phase3_*`).
- 1 is the **frozen v3 identity** break (B8).
- Plus one 503 log line: "no qualified backend configured (set VERITX_BOOKSIM_BIN)" —
  a test that builds its own `GatewayConfig` without the binary; production
  `resolve_booksim_bin` correctly falls back to `find_booksim_bin` (verified).

Not a code bug per se, but note the suite is 19+ minutes with no enforced timeout.

---

## 7. Prioritized recommendations

1. Scope build-provenance dirtiness to the producer subtree (B1). Rebuild manifests on
   a clean tree.
2. Fix the frozen v3 golden or revert the example change (B8).
3. Delete the duplicate `plan_from_round` (B2) and `edges_of` (B3); make `eval_bs`
   surface failures (B4).
4. Replace library `assert`s with explicit raises (B5).
5. Make `lint` fail on real errors; make the T3 sanity test assert (B6, B7).
6. Run the full DSE suite on every branch that runs `ci.yml`; enforce pytest-timeout.
7. Wire the vitest contract tests into CI; add an HTTP timeout in the client.
8. Ignore/remove `release-manifest.json`, root `node_modules/`; fix `.gitignore`.
9. Reconcile the stale ASTRA hash in `release-manifest.json` with the on-disk binary.
10. Audit the silent `except Exception` sites and downgrade to typed, logged handling.

---

## 8. Debloat & cleanup log (2026-09-29)

### Comment debloat (verified: no code token changed)

| Pass | Scope | Result |
|---|---|---|
| Module docstrings | 205 `veritx_dse` modules | moved → `docs/decisions/modules/*.md` (17 files); module keeps a 1-line pointer |
| Inline comment blocks (≥3 lines) | 656 blocks across 138 files | moved → `docs/decisions/modules/*.md` |
| Class/function essay docstrings | 508 essays across ~150 files | narrative moved → docs; summary + `Args/Raises/Returns/Note` sections kept |
| Studio TS file headers | 15 files | moved → `docs/decisions/studio.md`; `tsc --noEmit` clean |

`veritx_dse`: 98,230 → 87,709 lines; comment/docstring bloat 21,471 (22%) → 8,815 (10%).
Every pass was gated by an `ast.dump` fingerprint (module/function/class docstrings
removed) so only comments/docstrings changed. Verification: `compileall`, heavy imports,
the capability/exposure/intent/preset/deps gates, and the full 5401-test suite.

### Deleted

- `tracks/t3-topology/dse/scripts/deadlock_routing.py` — 0 bytes (real one lives in `veritx_dse/tools/`).
- `tracks/t3-topology/dse/inputs/archive/` — 8 files, exact byte-duplicates of live `inputs/`.
- `srota-studio-product-flow.html`, `veritx-serving-workspace-hardened.html` — superseded prototypes.
- Root build artifacts: `release-manifest.json` (stale — see B§3), `node_modules/`, `apps/studio/dist/`, `log/`, `.pytest_cache`, `.hypothesis`, `.playwright-mcp`, `.freebuff`.
- Dead first `plan_from_round` in `backend/serving_round.py` (audit B2).

### Moved

- `SERVING_*.md`, `SROTA_STUDIO_IMPLEMENTATION_HANDOFF.md` → `docs/reports/`.

### Fixed

- `.gitignore`: added `node_modules/`, `.pytest_cache/`, `.hypothesis/`, `release-manifest.json`; removed the bogus `LICENSE`/`CHANGELOG.md` "generated docs" ignores.
- 5 source-annotation contract tests that the docstring pass would have broken — the
  pinned annotations were restored (they are invariants, exactly the comments the
  policy keeps).
- Regenerated `tests/fixtures/serving_chakra/MANIFEST.json` (its
  `generator_source_sha256` hashes the generator source, which the debloat edited).

### Still not done

- The 25 pre-existing failures (audit B1 dirty-producer root cause, B8 frozen v3 golden) are **unfixed**.
- Track scripts (`tracks/*/scripts`, root `scripts/`) module docstrings were **not**
  swept — they feed `argparse(description=__doc__)` and several annotation tests.
- Studio TS inline comments below file headers were not swept.
