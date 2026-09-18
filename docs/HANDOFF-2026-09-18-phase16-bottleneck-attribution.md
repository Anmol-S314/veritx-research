# HANDOFF — Phase 16: system execution / bottleneck attribution

**Date:** 2026-09-18 · **Branch:** `epic/booksim-forward-port`
**Prior:** Phase-15 landing + preset-integrity fix (`a456a30e`); the deferred
Phase-15 acceptance battery remains OWED (see `HANDOFF-2026-09-18-preset-fix-and-phase15-landing.md`).
**Next permitted:** Phase 17 (stable application/control-plane API) after review.

## What landed

`workload/timeline.py` + `tests/test_workload_timeline.py` (25 tests, all
hand-computed). One dependency-aware timeline over DECLARED per-op service
legs, composed through the WorkloadArtifact's dependency structure.

### Core rulings (each pinned by a test)

1. **Dependency carrier = artifact ORDER.** Op *i* is released by op *i−1*;
   no dependency edges are invented (a pruned/inferred DAG would
   mis-attribute; the ARTIFACT hash would no longer name what executed).
2. **One op = one step issuing concurrent legs; `finish = ready + max(legs)`.**
   This is what makes hidden time representable — the reviewer's exact
   example is a test: compute 20,000c with a 5,000c operand fetch ⇒
   `memory exposed = 0`, total 20,000c, never "compute + memory".
3. **Critical-path attribution.** The step span is credited to its
   longest leg's dimension(s); strictly-shorter legs are hidden by
   definition. (A leg-difference rule — `max(0, leg − max other)` — was
   REJECTED: it credits a 20,000c compute leg only 15,000c when a 5,000c
   mem leg runs beside it, understating the critical path by 25%.)
   Under a tie, EACH tied leg is credited the full span: the exposed sum
   may exceed the chain advance exactly when a single-bottleneck verdict
   must be refused.
4. **Fail-closed service resolution.** A COMPUTE op without
   `compute_cycles` raises; a comm op with neither `net_cycles` nor the
   `(mem_bw, comp_bw)` rate pair raises; both forms together raise
   (ambiguous authority). Services are never defaulted or fabricated.
5. **Units.** `duration_ns × ns_per_cycle` with the clock declared on the
   dimension's `BackendBinding` (producer + fidelity + clock — evidence
   attribution rides on every leg).
6. **Verdicts:** `COMPUTE_BOUND` / `MEMORY_BOUND` / `FABRIC_BOUND`;
   `NETWORK_NOT_THE_BOTTLENECK` when net ties for max exposed with any
   other dimension; `MIXED` on tie or runner-up within 5% of the leader
   (`margin = runner_up/leader ≥ 0.95`); `INCONCLUSIVE` when no dimension
   has exposed > 0 (e.g. all-zero net legs — the congestion-unaware case
   stays INCONCLUSIVE, never a fabricated FABRIC_BOUND).
7. **SYNC_BOUND unreachable in v1** (no barrier ops in the canonical op
   set) — recorded as an explicit assumption on every attribution, never
   a silent zero. Same for absent memory legs (absent ≠ zero).

## End-to-end evidence (real measurements)

Composed the Phase-5 sweep's measured `exposed_comm_cycles` (11-topology
ASTRA-sim allreduce sweep, `results/sweep/astrasim_sweep.json`) as the net
leg for a 16MB ALLREDUCE, chained after a declared 8.6M-cycle dense-layer
compute (WorkloadArtifact `tp=16`, artifact-hash carried into the timeline):

```
topology       runtime(c)  net share  verdict
anynet16       12,560,310     31.5%   COMPUTE_BOUND   ┐ 7 fabrics: fabric
cmesh16        20,318,610     57.7%   FABRIC_BOUND    │ choice worth 0.0%
fattree16      12,560,310     31.5%   COMPUTE_BOUND   │ among the fast
flatfly16      18,818,610     54.3%   FABRIC_BOUND    │ set
fly4           21,366,610     59.8%   FABRIC_BOUND    ┘
mesh4x4/torus4x4/ftree  12,560,310    COMPUTE_BOUND
qtree16/tree4  12,759,270     32.6%   COMPUTE_BOUND

→ fly4 costs +70.1% runtime vs anynet16 on this workload;
→ among {anynet16, fattree16, ftree, mesh4x4, torus4x4}: 0.0%.
```

This is the Srota deliverable: `NETWORK_NOT_THE_BOTTLENECK` reasoning with
per-dimension exposed totals, not "Topology B wins by 35% fabric latency".

## Tests / gate

- `tests/test_workload_timeline.py`: **25 passed** (chain, concurrent legs,
  critical-path attribution, fail-closed matrix, evidence attribution,
  full verdict matrix, serialization)
- Neighbors untouched: test_workload_canonical + test_memory_lowering
  alongside = 97 passed; `make -C tracks/t3-topology lint` rc=0.
- Full suite NOT run this session (time constraint; still owed with the
  Phase-15 acceptance battery).

## Known residuals / next

- v1 chain semantics: per-participant skew and intra-artifact parallelism
  are out of scope (the artifact's order is one global chain). Multi-stream
  dependency graphs need artifact-level dependency edges first — a Phase-9
  schema extension, deliberately not smuggled in here.
- Compute service today is a declared constant (`compute_cycles`);
  wiring `core/serving.py` compute modeling as a producer is Phase-17 work.
- Memory legs can be populated from Ramulator evidence (Phase-15 producer)
  once the acceptance battery passes — the leg/evidence plumbing exists.
- `build_timeline` consumes declared evidence; a CLI surface
  (`veritx timeline …`) is deliberately deferred with the other CLI work
  ("CLI last, must stay boring").

**STOP before Phase 17** per program discipline.
