# HANDOFF — 2026-09-18: preset-integrity fix, Phase 14/15 landed, next = Phase 16

**Branch:** `epic/booksim-forward-port` @ `9cfc6c79` — pushed to **both** remotes
(origin `internal-devrepo` and `github.com:Anmol-S314/veritx-research`, identical tips).
The reviewer's certification blocker ("GitHub branch does not expose Phase-15
artifacts") is resolved: the worker's Phase 14/15 work existed only as untracked
files and is now committed.

## 1. Preset-mutation bug — FIXED (reviewer directive, executed first)

**Bug:** `p_bs.add_argument("--k", default=DEFAULT_K)` + handler merge
`{**preset.params, "k": args.k}` meant `veritx evaluate booksim --topo dragonfly_72`
ran dragonflynew **k=8 → 16,512 nodes** (declared: k=2, 72 nodes). Every preset
whose k ≠ 8 was corrupted at the CLI boundary; `presets.py` itself was always
correct. The fattree "339,382c" result the reviewer flagged was a 512-terminal
k=8 tree, not `fattree_k4n3`.

**Fix (`6f951783`):** resolution extracted to `_resolve_eval_topology` (cli.py)
with this contract, pinned by `tests/test_eval_preset_integrity.py` (19 tests):

- named preset (exact name), no flags → exactly the preset architecture
- named preset + explicit `--k`/`--routing` → REFUSE ("preset is immutable")
- backend alias bare (`--topo mesh`) → alias default preset (preserves the
  pre-existing alias feature)
- backend alias/unknown + explicit k(+routing) → raw form; **k REQUIRED**,
  never invented (defaulting k is precisely the original sin)
- evaluation log line now prints `topo=<name> terminals=<N>` — the reviewer's
  resolved-topology preflight, minimal form, on every run

Legacy tests updated: `test_unified_contracts.py` used a dead `topos=`
(plural) attribute that no parser has ever set — fixed to the real seam.

**Invalidation audit (139 eval files scanned):** exactly ONE poisoned run —
`results/evaluate/20260918_131010_seed6955105/eval_fattree8.json`
(`fattree_k4n3_8x8`) — marked `"invalid": true` with reason. Compare/sweep/
astrasim outputs carry **no** corruption signature (t3's pipeline builds
configs independently of this CLI path): 0 hits.

**Note:** this bug is unrelated to the dragonfly16 *embedded-sweep* stall —
that path used correct k=2; its root cause was the giant-packet wedging below.

## 2. Worker's Phase 14 + 15 landed (5 commits)

| commit | content |
|---|---|
| `5f7c44e0` | phase14: `core/memory.py` MemoryArtifact (+ `test_memory_artifact.py`, phase-14 handoff). Tracked `core/serving.py` already imported this — the import graph was dangling until now. |
| `9df78420` | `core/deps.py` — cli.py (committed in `d45cc04a`) imported it; module was never committed. CLI would `ImportError` on a clean checkout without it. |
| `fd2b6694` | phase15: vendored `third_party/ramulator2` (upstream @ 72427a1, source-only; VeritX-marked drain patch in `readwrite_trace.cpp` — EOF==drained), `workload/memory_lowering.py` (sequential_bankstriped_v1, explicit padding, capacity refusal), `simulation/ramulator.py` (drain-aware verdicts: PASS ⇒ issued==accepted==completed, outstanding==0), 3 test files, phase-15 + 15b handoffs. |
| `9cfc6c79` | the other agent's dragonfly MTU trial: `--booksim2-embedded-mtu` fragments message-sized sends into MTU packets (dragonfly16: 0 → 864 rank completions, zero tracker mismatches; default OFF, fail-fast on non-positive). Trial-scoped pending root-cause writeup. |

## 3. Gate (targeted, per time constraint — NOT the full suite)

- new preset-integrity tests + touched files: **125 passed** (test_eval_preset_integrity, test_cli_modules, test_unified_contracts)
- landed phase-14/15 modules: **62 passed** (test_deps, test_memory_artifact)
- MTU trial live tests: **3 passed**; py_compile OK on cli.py
- **Full suite + `t3 lint` still owed** before any Phase-16 gate — flagged, not hidden.

## 4. Next (per reviewer sequencing)

1. **Phase 15 acceptance battery** (reviewer's spec): direct raw-vs-wrapper
   equivalence, determinism ×3, isolated bank-parallelism fixture (both arms
   conflict-heavy), tiny non-saturating clock-ratio probe, drain matrix,
   backpressure, tamper matrix, one manually audited workload — one
   machine-readable verdict script. Only the isolated-bank + clock-ratio
   probes are new work.
2. **Preset integrity follow-ups** (small): `--resolve-only` JSON preflight;
   extend the node-count table to cover any alias-default quirk (alias with
   explicit routing is intentionally the raw form, not alias mutation).
3. **Phase 16 — system execution + bottleneck attribution**: dependency/event
   timeline over compute/BookSim/Ramulator evidence; **exposed** stall
   semantics (service ≠ exposed); verdicts COMPUTE/MEMORY/FABRIC/SYNC_BOUND,
   MIXED, INCONCLUSIVE, and `NETWORK_NOT_THE_BOTTLENECK`. No cycle-level
   BookSim↔Ramulator coupling in v1.

## 5. Environment facts for the next session

- Two remotes; push **both** (`git push origin …` + `git push github …`).
- ramulator2 ext currently cpython-314-tagged, built in-tree (gitignored);
  rebuild under the target interpreter with `./build.sh` (see VERITX_VENDOR.md).
- Live-skip pattern: `LIVE_PY` in test_ramulator_backend.py pins the
  interpreter; update it if the build interpreter changes.
