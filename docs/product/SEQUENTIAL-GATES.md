# Sequential gates — run order and why

Date: 2026-11-10. This host saturates swap (~95% used) and the load average exceeded 9 while parallel Verilator builds ran. Heavy gates must not run concurrently; they are queued in one script, `scripts/sequential-gates.sh`.

## Order and expected cost (12-core host, memory ~14 GiB)

1. `frontend-tsc` — prototype typecheck. Fast.
2. `dse-pytest` — full DSE unit suite. ~20–40 min; Reisdent memory ~1–2 GiB.
   Known: run it only after the router emission stops changing (STA lane).
3. `slice-family` — composed-top lint/sim for slice + shared + parameterized suites. ~10–15 min.
4. `parameterized` — the parameterized mesh suite alone. ~5–10 min.
5. `families-lint` — every composed family: lint + TB + scenarios. ~15–25 min.
6. `release-matrix` — `scripts/complete_design.py --release`: the fourteen-family matrix.~20–40 min.
   Records typed FAILs honestly (multi-seat families); a single-project run never publishes 14/14.
7. `playwright` — full prototype suite (`npm --prefix apps/studio/prototype run test:e2e`). ~6 min.
8. `reproduce` — `scripts/reproduce_slice.sh --clean`: fresh-dir slice reproduction.
9. `verify` — `scripts/verify_slice.sh`: re-verifies hashes + lint + sim.

## Rules

- One stage at a time; the script stops at the first failure and names the log.
- Do NOT run these in parallel with each other or with a live LibreLane flow.
- The 6 GB memory cap is a hard limit; `--build-jobs 1` and `-O0` on 64-router TB builds are deliberate, not bugs.
- `kncube` composes only through the test-harness path (family params are built by tests; no saved-project request can select it yet); the release matrix row harness-routes it directly since 2026-11-10 — its honest verdict comes from the next matrix re-run, not from the source change alone.
- `cmesh`/`fly`/`qtree`/`tree4`/`fattree` rows refuse `UNSUPPORTED_COMPOSED_FAMILY` until a multi-seat concentrator exists; that is the open P3 item, not a flaky gate.

## Status as of 2026-11-10

- `mesh` 8x8 (64-router): reported PASS once (lint PASS, sim PASS, 13 scenarios true, ~157 s with the raised timeout + `-O0`), but the log/artifacts were never pinned into `runs/` and were destroyed at the 2026-11-10 service restart. The claim is **unsubstantiated until the matrix re-run lands under `runs/`** — do not cite it.
- `playwright` delivery suites: 8/8 green after spec copy was corrected to the renamed page ("Research RTL evidence" / "Current project preview").
- Frontend unit suite: **325/325** green (`npx vitest run` durable re-measure 2026-11-10, 49 files; typography contract green unedited).
- Slice/backend suites: a run racing a mid-edit router reported 27 failed (not a verdict). Since then: `tests/test_project_top_shared.py` re-run green (**14/14**, ~9 min), `tests/test_project_top_parameterized.py` re-run green (**12/12**, ~7 min), `tests/test_p8_mesh2x2_contention.py` narrowed to the landed invariant set (**5/5**), and `tests/test_project_top_slice.py` is now the arbiter: **38 passed, 14.2 min** (2026-11-10, contention-enhanced locked TB). The backend DSE unit suite queued via this script has never completed this cycle cleanly (died under combined memory pressure) — it is still **NOT RUN** as a gate.
- Release matrix: torus/ring/gec_mecs/flatfly/srota/gec_hybrid PASS (2026-11-09 run); mesh pending re-run with the raised timeout; cmesh/fly/qtree/tree4/fattree typed-refused (multi-seat, P3 open); dragonflynew kwarg fix present but unverified in a re-run; kncube row was unrunnable before 2026-11-10 (`make_family_request` raise) and has routed to the kncube harness — the matrix needs one re-run to settle every row; do not quote a matrix verdict before that re-run exists under `runs/`.

## Sacred-runs schedule (2026-11-10)

**Rule 0:** a run is sacred. Nothing here runs because someone wants a quick peek; every stage exists to prove a claim, and skipping one is a honest report of what was not done.

**Rule 1 — order of machine ownership:**
1. P9 STA lane owns the machine (LibreLane/Yosys on the full `project_top`) until it notifies. No gate starts before that.
2. P8 contention lane owns the TB generators until it notifies. No matrix re-run before that.
3. After both, one gate at a time in this exact order: `frontend-tsc` → `dse-pytest` → `slice-family` → `parameterized` → `families-lint` → `release-matrix` → `playwright` → `reproduce` → `verify`.

**Rule 2 — budgets:** every heavy stage needs ~4 GiB free and ~1 GiB swap headroom (enforced by the script's preflight — it refuses to start otherwise). The 64-router TB build uses `--build-jobs 1 -CFLAGS -O0` on purpose (memory, not speed).

**Rule 3 — resume points:** after a failure at stage N, do not restart from zero. Inspect the log, fix the cause, and rerun only from stage N (`scripts/sequential-gates.sh <stage-name>`).

**Rule 4 — no gaming:** if a stage fails, the verdict is FAIL (or NOT_RUN), never "rerun until green". Flaky timing-dependent stages get one rerun with `--basetemp` pinned and then stay failed.

**Rule 5 — refresh discipline:** after any RTL emission change, `dse-pytest` and the slice suites are stale evidence until re-run at this order.
