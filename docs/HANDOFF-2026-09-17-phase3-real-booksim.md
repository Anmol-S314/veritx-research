# HANDOFF — Phase 3 (T6): real serving → BookSim execution PROVEN

**Date:** 2026-09-17 · **Branch:** `epic/booksim-forward-port`
**Gate: PASS — PR6 unblocked (integration task, not backend implementation)**
**Next permitted: Phase 4 (PR6 serving → BookSim slice)**

## Claim proven

The repository contains a real path:

```text
LLMServingSim → AstraSim_BookSim2 → BookSim fabric → completions → progress
```

Fixture: `single_node_moe_single_instance` (1 instance, TP=2, EP=2,
PP-free, Qwen3-30B MoE, RTXPRO6000), 1 request, `example_trace.jsonl`,
`--no-booksim-replay-only`, `VERITX_LEDGER=1`.
Raw logs/CSVs: `tracks/t3-topology/logs/t6-proof/` (gitignored scratch).

## Fabric evidence (real run, exit 0)

- 20,160 collectives submitted/constructed/completed (`COLL_SUBMIT` /
  `COLL_CONSTRUCTED` / `COLL_COMPLETE` on both ranks)
- 80,640 streams + datasets; 770 fabric STEPs; quiescence lines
- **1,211,088 flits retired; built ≈ retired (conservation holds)**;
  99,973 tail deliveries ≈ 99,973 request packets
- `Total clocks: 448,123,896 ns` vs replay control `339,685,220 ns`
  (+32% — network contention visible in the number, not just the ledger)
- CSV: 1/1 retired. Clean shutdown (results printed, `check_end` passed).
- Backend identity: `AstraSim_BookSim2.real` sha256 `09d7a3ce70dfda92…`
  (prefix; full hash in run environment).

## Replay control (same fixture, `--booksim-replay-only`, exit 0)

- LEDGER classes: LOAD + STATE only. **Zero** COLL/STREAM/STEP/fabric
  lines; no flit counters whatsoever.
- Machine-distinguishable from the real run by evidence presence, not
  by exit code or by eyeballing TTFT.

## User-raised comm concern — investigated, verdict recorded

Suspicion was that comm isn't used right (all-true `involved_dims`,
`group_members=none`). Findings from source + kept inputs:

- The 1-dim trace **correctly** carries no `involved_dim` scoping
  (`tp_dim`/`ep_dim` are `None` for single-dim topologies;
  `_with_dim` returns bare `ALLREDUCE`).
- The backend fallback (`Workload.cc`, missing-attr branch) fabricates
  all-true — comment claims 5-dim, loop pushes exactly **4** (upstream
  vestige; comment/code mismatch noted).
- `generate_collective` indexes only `[0, num_dims)`, so on 1-dim the
  extra trues are unread and behavior is correct. `group_members=none`
  is the nullptr-group display path, not missing membership.
- **Residual risk (not blocking T6):** on a genuine multi-dim run, a
  trace node missing the attr would silently scope ALL dims instead of
  failing. Trace emission covers multi-dim via `tp_dim`/`ep_dim`, so
  this triggers only on a generator bug — but the backend default is
  fabrication, same class as the PP shim was. Flagged for the
  RouteArtifact phase (Phase 10): unscopable collectives must fail
  closed there. If multi-dim goldens ever show all-true vectors where
  scoped ones are expected → STOP and re-review.

## Phase 3 gate

- [x] `network_mode = REAL_SIMULATION` (flag-selected, mapping-tested)
- [x] `semantic_losses = []` (PP-free, TP/EP supported, preflight-passed)
- [x] Actual BookSim activity > 0 (1.2M flits, 20k collectives)
- [x] Request completes (1/1 CSV)
- [x] Clean child shutdown
- [x] Backend binary identity recorded

## Files changed this phase

- `docs/VERITX_SROTA_IMPLEMENTATION_PLAN.md` (committed: the authority
  version this program executes against)
- This handoff. No source changes in T6 (evidence-only phase).
