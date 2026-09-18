# HANDOFF — Phase 15: Ramulator detailed-memory backend (15a lowering + 15b execution)

**Date:** 2026-09-18 · **Branch:** `epic/booksim-forward-port`
**Prior gate:** Phase 14 handoff (memory semantics + resolver, same day).
**Spec:** `tracks/t3-topology/docs/MEMORY-ROADMAP.md` (§13–§22, Appendix D).

## What landed

### Backend pinning (no fork)

- `third_party/ramulator2/` vendored (2.2MB): upstream
  `CMU-SAFARI/ramulator2 @ 72427a1`, no `.git` per repo precedent;
  `ext/` (FetchContent deps), `visualizer/`, build outputs pruned.
- `third_party/ramulator2/VERITX_VENDOR.md`: pin, build notes,
  interpreter caveat, Stage-1 boundary record.
- Provenance: vendor tree builds clean out-of-tree (`BUILD_DIR=/tmp/...`),
  build outputs removed afterward (global `*.so`/`build/` gitignore keeps
  the tree source-only).

### 15a — `MemoryArtifact → ReadWriteTrace` lowering

In `workload/memory_lowering.py` (pure — never imports Ramulator, runs on
any interpreter):

- `RamulatorGeometry`: explicit backend geometry (7 level counts + tx
  bytes + class/preset/controller), caller-supplied, hashed into the
  manifest. `hbm3_16gb_8hi_geometry()` transcribes the audited preset
  (pc2/sid2/bg4/bank4/row16384/col256, tx64); transcription pinned by
  tests grepping the vendored tree (no import needed).
- `sequential_bankstriped_v1`: flat-tx → `(ch,pc,sid,bg,bank,row,col)`,
  column fastest, row slowest (locality-monotonic). New orders are new
  versions; unknown names refuse.
- Backend-faithful padding: whole-tx service ⇒ unaligned heads/tails
  become explicit front/back padding; `logical + padding == generated`
  asserted per-kind and in total. Capacity overflow refuses (never wraps).
- `MemoryLoweringManifest`: artifact/stream/trace/config hashes, counts,
  bytes, coverage, transformations; losses/unsupported `[]` established
  by the asserts, per ET-manifest culture.

### 15b — `simulation/ramulator.py` execution + evidence

- `discover()`: explicit readiness (interpreter + package + built ext);
  `producer()` identity (name/version/commit/binary-sha).
- `execute()`: fixed v1 driver (HBM3/HBM34/FRFCFS/open/pass-through/
  NoRefresh, single controller); tamper-evident (trace hash verified
  pre-run); raw debris retained (driver/stdout/stderr/stats.json).
- Machine channel is `stats.json` on disk — supervised_run's line-bounded
  stdout capture truncates the single-line stats block (found live).
- Drain-aware verdicts: issued==accepted==served → PASS; backend loss or
  drain shortfall → INCONCLUSIVE quantified; crash/timeout/garbage →
  EVALUATION_FAILED with debris; off-envelope geometry → UNSUPPORTED
  without executing; missing backend/tampered trace → raise.
- `MemoryEvidence`: typed metrics (value+unit; absent stays absent) +
  derived completed bytes (served × tx); dual fidelity labels
  (request-generation recorded vs dram-timing cycle simulation).

### Standing verdict — SUPERSEDED (2026-09-18, later same day)

The text below described the pre-15b state. The C++ drain patch has since
LANDED (vendored `readwrite_trace.cpp`, `VeritX:`-marked: `is_finished()`
waits for accepted requests to complete; `outstanding` derived as
`accepted − completed`), real runs PASS with full drain, and the fix was
certified live (write-coalescing/read-forwarding probes after the
`req.addr` flat-address repair). The Phase-15 acceptance battery
(`veritx_dse.acceptance.phase15`) closes the phase: **VERDICT: PASS,
16/16 checks** — drain matrix (1R / 192R+32W / 4096R / 4096W / mixed /
backpressure), wrapper≡direct equivalence on a shared trace,
determinism ×3, row-locality + isolated bank-parallelism sensitivity,
capacity/tamper refusal, byte conservation. The paragraph below is kept
as the honest record of why the patch was initially considered.

---

### Original standing verdict (superseded — see above)

The v1 frontend leaves ~31 requests in flight at EOF regardless of trace
length, so real runs terminate INCONCLUSIVE (measured live: accepted
192R/32W, served 161R/0W). Metrics stay valid over served requests. A C++
drain patch was rejected (no outstanding-count API on either interface —
it would invent surface to manufacture PASS). PASS awaits the Stage-2
draining (External) frontend.

## Tests (27 new: 14 lowering + 13 backend)

- Mapping vectors (origin/column-walk/bank-then-row), capacity refusal,
  unknown-mapping refusal, exact-expansion counts (152 tx, zero pad),
  padding math, order preservation, trace-hash link, oversize refusal.
- Verdict matrix via canned runner: PASS drain, shortfall/loss/missing-
  counter INCONCLUSIVE variants, crash/garbage/missing-file EVAL_FAILED,
  absent-metric absence, not-built/tamper raises, DDR5 UNSUPPORTED with
  zero subprocess calls.
- Live (skipif, needs_binary pattern): discovery + honest-shortfall
  execution against the real HBM3 backend.

## Live evidence

- Full suite: **1318 passed, 1 skipped, 0 failures** (1319 collected =
  1319 executed); `make -C tracks/t3-topology lint` rc=0.
- Lowered 224-tx trace runs end to end on HBM3 (192R+32W issued, row
  behavior as mapped: 160 hits/0 conflicts on the sequential stream).

## Known residuals / next

- Interpreter binding: ext is cpython-tagged; host (3.14) vs container
  (3.10) vs spike (3.12). In-image build at CLI-integration time.
- Thin CLI (`memory inspect` / `memory evaluate --backend ramulator`)
  deliberately not built (agreed sequence: CLI last, must stay boring).
- Coupled BookSim↔Ramulator co-sim stays a later milestone (needs the
  External frontend + drain semantics proven here first).
- `simulate/`-level system/bottleneck model (Phase 16) now unblocked on
  the memory side: network evidence (BookSim) + memory evidence
  (this handoff) share status/metric conventions by design.
