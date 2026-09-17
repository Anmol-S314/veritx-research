# HANDOFF 2026-09-17 — Verified-PRD Integrity PRs A–E (implementation complete, awaiting your review)

**Branch:** `epic/booksim-forward-port` · **HEAD:** `fa71db29` (uncommitted working tree)
**Suite:** `911 passed, 1 skipped` (`python3 -m pytest dse/tests -q`, 1:54) — up from 869/1 at session start.
**Authority:** `docs/SROTA_VERITX_VERIFIED_PRD_ARCHITECTURE.md` (your document, snapshot SHA `8bae314e…`). User's decision: implement A–E as one batch. **PR 5 (serving protocol fixture) still held** per your instruction.

This document lists what we changed, where, and how each gate is evidenced, so you can verify against the live tree rather than take the summary on faith. Line numbers are current as of HEAD `fa71db29`.

---

## PR A — environment contract (Gate A: clean install from declared metadata)

**Defects fixed (yours, §11):** `requires-python = ">=3.10"` + `dependencies = []` while the code imports pydantic/numpy/scipy/skopt/yaml; `uuid.uuid7()` called directly (3.14+ stdlib) inside run creation, so any 3.12/3.13 environment crashed the moment it created a run — and CI could never see it because the only test job ran inside one container image.

**Changes:**
- `dse/veritx_dse/core/runs.py`
  - `_uuid_v7()` — stdlib-only UUIDv7 implementation (48-bit ms timestamp + ver/variant + 62 random bits), used by run creation. `import uuid` module-level preserved for other uses.
  - `_RUNTIME_FLOOR = (3, 12)` + explicit loud failure in run creation below the floor (gate A: silent incompatibility is the failure mode we're killing — refusing is correct, not rude).
  - `_dependency_lock_identity()` — SHA256 of `dse/requirements.lock`, recorded in `provenance.json["python_dependency_lock"]`; returns `None` **labeled as missing** rather than inventing an identity.
- `dse/pyproject.toml` — floor raised to `>=3.12`, all five runtime deps declared with floors, 3.12/3.13/3.14 classifiers, comment tying the declared range to the tested range.
- `dse/requirements.lock` (new) — exact pins from the reference env (pydantic 2.13.4, numpy 2.4.6, scipy 1.17.1, scikit-optimize 0.10.2, pyyaml 6.0.3). Header documents regeneration via `make lock`. This file is the provenance fingerprint, not an install vector.
- `tracks/t3-topology/Makefile` — `lock` target (`make -C tracks/t3-topology lock`).
- `.github/workflows/ci.yml` — new matrix job, python ["3.12","3.13","3.14"], `pip install -e tracks/t3-topology/dse` **from declared metadata only**, then `test_environment_contract.py` + `test_run_core.py`. This is the job that would have caught the original uuid7 defect.
- `dse/tests/test_environment_contract.py` (new, 18 tests) — pins: uuid7 correctness (version/variant bits, monotonic ordering, uniqueness), interpreter-floor refusal, dependency-lock provenance behavior (present + missing-file), lock/pyproject consistency (every pyproject dep appears in the lock, numeric-safe comparison), CI matrix presence.

**Gate evidence:** the CI job installs from metadata alone; on this box `test_environment_contract.py` passes under 3.14 (the only interpreter available here — 3.12/3.13 verification happens in CI, which we cannot execute locally).

---

## PR B — verification honesty (Gate B: PASS ⇔ the check actually ran)

**Defects fixed (yours, §7 — highest severity):** F1–F8 emitted `PASS` without executing checks; F2 was literally built from the topology *name string*; F3 passed with no simulation evidence; signing used a hardcoded default secret; placeholder artifacts looked generated.

**Changes:**
- `dse/veritx_dse/model/compile_model.py`
  - `VerificationStatus` closed set: `PASS, FAIL, NOT_RUN, UNSUPPORTED, INCONCLUSIVE, ASSUMPTION` (comment at :1347 states the contract).
  - `verify_design` rewritten: every F1–F8 entry now carries an honest status + the *referenced evidence path or explicit "none"* + acceptance rule. F2 liveness → `NOT_RUN` (needs a BookSim run); F3 conservation → `PASS` only when a BookSim result with packet counters exists; F4/F5 → `ASSUMPTION`; F7 → `UNSUPPORTED` (or `NOT_RUN` with a recorded attempt); F8 → `NOT_RUN` until timeouts measured. The single check that genuinely executes (F1 cycle detection) keeps `PASS`.
  - Artifact construction marks non-generated placeholders `generated: false`.
- `dse/veritx_dse/reports/artifact.py`
  - Default-secret constant removed; key is an explicit parameter; `Artifact.create_unsigned()` sets `signing_mode: "CHECKSUMMED_UNSIGNED"` + empty signature (declared unsigned, never silently "signed"); `create`/`revise` compress onto one `_build` path.
- `dse/veritx_dse/cli/cli.py` — PASS-counting and display symbols updated to the honest statuses (F2 no longer prints a green checkmark).

**Gate evidence (reproduced live, not asserted):** a real `veritx compile` on a small model now reports F1 PASS (executed), F2/F3/F6/F8 NOT_RUN, F4/F5 ASSUMPTION, F7 UNSUPPORTED, manifest `signing_mode: CHECKSUMMED_UNSIGNED` with empty signature, placeholders `generated=false`. The fabricated-PASS code path no longer exists.

**Test pins moved (all deliberate):** `test_prd_gaps` (40 now, was pinning fabricated statuses), `test_compile_uvm` (14), `test_entry_point` (23, incl. the CLI e2e — its compile-report assertions updated to honest statuses), `test_api_contract` (11). No test was deleted to make the suite pass; each moved pin corresponds to a behavior you flagged.

---

## PR C — workload lowering fail-closed (Gate C: the trace IS the workload)

**Defects fixed (yours, §6.3):** unknown `comm_type` skipped with a warning (real repo model `automotive_adas.json` carries `BROADCAST`); singleton-participant instances silently dropped; no conservation record. Net effect: a malformed model silently became a *lighter* workload and every downstream number was wrong.

**Changes:**
- `dse/veritx_dse/simulation/model_to_trace.py`
  - `LoweringError(ValueError)` (:31); `lower_model` raises on unknown comm_type, participant out of `[0, nodes)`, degenerate instance (`<2` participants) — with class/instance/index context in the message.
  - **BROADCAST is now defined, not skipped** (:122): first participant = source, remaining = destinations, fanout = `len(destinations)` (documented interpretation, visible in code).
  - `build_lowering_manifest()` (:240) → **LoweringManifest v0** sidecar: per flow class `{kind, instances, packets, bytes, participants}` + `{total_packets, total_bytes, unsupported_classes: []}`. Empty `unsupported_classes` is the fail-closed invariant.
  - CLI `trace model` command surfaces `LoweringError` as a clean failure (`dse/veritx_dse/cli/cli.py`).
- `dse/tests/test_trace_tools.py` (25) — three tests that *pinned the silent-drop behavior* rewritten to pin fail-closed raising; new class pins manifest shape, conservation totals, BROADCAST decomposition.
- `dse/tests/test_trace_commands.py` (25) — CLI-level: invalid model now exits non-zero with a precise message instead of producing a shrunken trace.

**Deliberate data decision left for you:** `automotive_adas.json` now **refuses to lower** (1 unknown `BROADCAST`-as-data class + 64 singleton `lidar_pointcloud` instances) until the model is repaired. We did not silently "fix" the model — whether singleton lidar P2P is modeler error or a semantic to support is §34-class, and per the handoff we don't guess.

---

## PR D — routing stopgap (Gate D: certified routes = routes BookSim executes)

**Defects fixed (yours, §6.8 — "most dangerous scientific defect"):** the cert leg invoked the certifier with no `--method`, so argparse defaulted to `mclb` while BookSim executes its internal Dijkstra. Certificate PASS on route set A, simulator runs route set B.

**Changes:**
- `dse/veritx_dse/tools/deadlock_routing.py`
  - argparse default `mclb` → **`booksim`** with help text stating why (:451).
  - `--export-table` (already existed) persists the BookSim-exact next-hop table; the certificate JSON records `method` + `route_table_sha256`, so a cert is now falsifiable against the routes actually executed.
  - Weighted anynet: parser records non-unit weights; certifier **refuses** weighted topologies (exit 2, stderr explanation) — BookSim's anynet has no link weights, so certifying a weighted graph would again certify a fiction.
- `dse/veritx_dse/core/anynet.py` — `non_unit_weights` recorded at parse; `has_non_unit_weights` property.
- `dse/veritx_dse/cli/cli.py` — cert leg passes `--method booksim` + `--export-table` explicitly (:1770, comment explains the invariant); two astra invocations now pass explicit `--logging-folder` (bonus: killed a second repo-littering writer — the analytical frontend's `CmdLineParser.cc` defaults to relative `log/`, cwd=REPO).
- `dse/tests/test_routing_stopgap.py` (new, 7) — method default, weighted rejection, route-table persistence + hash stability, cert JSON carries method+hash.

**Live smoke (verified end-to-end in /tmp):** unit topology → cert with `method: "booksim"` + hashed route table on disk; weighted topology → exit 2, no certificate.

**Honest residual (unchanged by design):** this makes the certifier and BookSim agree; the RTL generator still derives its own routes (VC0 Dijkstra / VC1 up-down tree). Representation alignment across all three remains future work per your doc; we did not touch `gen_rtl.py` in this batch.

---

## PR E — typed metrics + executable provenance (Gate E: naked numbers are not results)

**Defects fixed (yours, §4/§10.4):** BookSim cycles stored as bare numbers with no unit/producer/fidelity; provenance lacked binary identity, so "the binary changed" was undetectable.

**Changes:**
- `dse/veritx_dse/core/runs.py`
  - `metric(name, value, unit, *, producer, fidelity, scope)` (:165) — fidelity validated against a closed set (`NETWORK_SIMULATION`, `ANALYTICAL`, `MEASURED`, `ESTIMATED`), rejects empty producer/unit at the seam.
  - `binary_identity(path)` — SHA256 + size, missing file → explicit `None`, never fabricated.
- `dse/veritx_dse/simulation/booksim.py` — result emission types core metrics at the source (`latency_cycles`, etc.: unit `cycles`, producer `booksim2`, fidelity `NETWORK_SIMULATION`); binary SHA256 into provenance; timeout path raises instead of silently emitting partial typed results.
- `dse/tests/test_metrics_provenance.py` (new, 8) — metric validation (bad fidelity/producer/unit), binary identity (real file hash, missing-file honesty), end-to-end run through the fake binary with typed metrics + provenance assertions.

**Scope note:** this is the *baseline* the PRD asked for — the seam exists and the BookSim path uses it. ASTRA/Timeloop/LLMServingSim emitters still emit untyped numbers; converting them is mechanical now but touches slices B/C which don't exist yet, so we left it.

---

## Test deltas and mistakes made (transparency)

- 869 → **911** passed (+42 net; +18 A, +7 D, +8 E, +≈20 C rewrite/expansion, −pins moved in B).
- Two pin-shift classes in B: (1) tests asserting fabricated PASS → assert honest statuses; (2) the CLI e2e compile-report assertions. Neither test was weakened; each now pins the behavior your PRD demands.
- Mistakes made and caught during the session (all fixed before this handoff): one clobbering `write_file` on the audit doc (restored + re-verified section-by-section), one str_replace that replaced a function *definition* with a call in `model_to_trace.py` (repaired, suite green), a CLI guard that fought Python argument binding instead of fixing the signature (redone as `create_unsigned`), and a test expectation based on a wrong instance count (corrected against the actual model).
- Known cosmetic residue: stale `.pyc` caches in `__pycache__` (including pre-rename `milestone_c.cpython-314.pyc`); nothing references them.

## Deliberately not done (per your doc / handoff discipline)

- PR 5 (serving protocol fixture) — **held** until your review, per your explicit instruction.
- No `base.py`, no universal runner, no serving slices, no Studio UI, no abstract verification framework — statuses live in `compile_model.py` as data.
- RTL route-truth alignment and ASTRA/Timeloop typed metrics — noted above as residuals.
- `automotive_adas.json` left unmodified (fail-closed refusal is the fix; the data decision is yours).

## Questions for your review

1. **F4/F5 as `ASSUMPTION`** — you called for statuses, not implementations; is ASSUMPTION the right label for ordering/flow-control, or should they be NOT_RUN with evidence paths?
2. **BROADCAST semantics** — first=source, rest=destinations, fanout=dest-count. Confirm or correct before any real workload relies on it.
3. **Singleton-participant P2P** — modeler error to reject, or a semantic to support? Currently rejects.
4. **CI 3.12/3.13 leg** — we cannot execute GitHub Actions from here; the job is written but unverified. If it has a wiring mistake it will surface on first push.
5. **Next step after your review** — you previously gated Slice B on Q12.1 livelock diagnostics (6 open questions in `docs/SEMANTIC_QUESTIONS.md`). Do we do PR 5 fixture → Q12.1 diagnostics → PR 6, in that order, or does the routing residual (RTL alignment) outrank the serving track?

## Where to look first if you verify only three things

1. `dse/veritx_dse/model/compile_model.py:1347-1530` — the honest verification statuses (your highest-severity finding).
2. `dse/veritx_dse/tools/deadlock_routing.py:451` + `dse/veritx_dse/cli/cli.py:1770` — the routing-truth gate.
3. `dse/tests/` — 911 tests, all green; the four new/rewritten files (`test_environment_contract`, `test_routing_stopgap`, `test_metrics_provenance`, `test_trace_tools`) pin the A/C/D/E gates.
