# HANDOFF — Phase 13 precursor: F2/F3/F8 evidence plumbing

**Date:** 2026-09-18 · **Branch:** `epic/booksim-forward-port` @ `ad992a26`
**Context:** Phases 11 (RTL) and 12 (formal) **deferred by decision** — both
consume RTL. This precursor was the agreed lead-in to Phase 13 (the
"Verify must mean something" prerequisite). It is complete and merged;
**Phase 13 proper (requirements-driven synthesis) is next.**

## What landed

The Step 3 → Step 4 evidence gap in `cmd_compile` is closed: what BookSim
measured now reaches the F-checks as evidence, with strict
honesty semantics.

### 1. Fork delta — flit conservation totals (both booksim2 copies)

`VeritX:`-marked, mirrored to `third_party/booksim2/src` AND
`third_party/astra-sim/extern/.../booksim2/src` (sync protocol):

- **`_veritx_total_sent_flits` / `_veritx_total_accepted_flits`** —
  per-class accumulators, incremented at the two single points where
  flits are injected/ejected (`trafficmanager.cpp:1052/1318` region).
  Increment-on-event is immune to the per-phase `_ClearStats` calls.
- Emitted ONCE per run at the **trace-drain success point**:
  `VeritX: injected flits total = N` / `accepted … = N`, summed over
  classes (disjoint traffic; the sum is the network conservation quantity).

**Why not the Overall block (recorded so nobody re-tries it):** in trace
mode the phase-transition `_ClearStats` wipes the counters before
`_UpdateOverallStats` runs — the Overall block provably prints `-nan`/0
while the per-phase stats held the true 96. Three capture points were
tested against the real binary; only drain-point + increment-on-event
survived. Live: 24 pkts → injected 96 == accepted 96.

### 2. `parse_output` additions

- `flits_injected` / `flits_accepted` from the fork lines (stock binary →
  keys absent → F3 stays NOT_RUN, never a fabricated zero)
- `max_packet_latency`: the `\tmaximum` **within the "Packet latency
  average" block** (grammar: average, minimum, maximum, before "Network
  latency average"), NaN/inf-guarded, ends at block boundary. The
  first naive "any `\tmaximum`" heuristic mis-attached (flit-latency,
  rate blocks); the state machine is anchored to the block.

### 3. `evidence_from_result` (simulation/booksim.py)

Result dict → F-check vocabulary. **No derived drop counter**: F3's
injected == completed + dropped fed with `dropped = injected - accepted`
would be an arithmetic identity, verifying nothing. Instead:

- two-key shape (injected, accepted) → F3 **complete-delivery** semantics:
  any gap is loss inside the fabric → FAIL with `lost=N` visible
- three-key shape (dropped explicitly provided by a future fork) → the
  classic identity, unchanged
- contradictory evidence (accepted > injected) surfaces as F3 FAIL, never
  clamped

### 4. F2/F8 in `verify_design`

- **F2** consumes `evidence["topology_adjacency"]` — BFS from node 0 over
  the executed topology's adjacency → PASS (all reachable, n in detail) /
  FAIL (k of n reachable) / FAIL (malformed evidence, named). No
  adjacency evidence → NOT_RUN (a topology name is not evidence, §3.11).
- **F8** bound comes from `latency_bound_from_requirements` — min over
  declared E2 latency ceilings. No declared ceiling → NOT_RUN. The bound
  is a scientific constraint, never a defaulted number.

### 5. `topology_adjacency(topo)` (model/compile_model.py)

Adjacency of the topology actually simulated: mesh/cmesh (no wraparound),
torus (wraparound), anynet (network file via core/anynet — the ONE
parser). Unsupported backend → None → F2 NOT_RUN honestly.

### 6. `cmd_compile` Step 4 wiring

`evidence = evidence_from_result(result)` + topology adjacency + declared
bound → `verify_design(cr, evidence=…)`. With a conserved run the board
now legitimately reads F1 PASS, F2 PASS, F3 PASS, F4/F5 ASSUMPTION,
F6 NOT_RUN (RTL pending), F7 NOT_RUN, F8 PASS/FAIL/NOT_RUN per bound.

### 7. Doctor: `seam.booksim_fork_mirror` (quick + deep)

Compares the VeritX-delta signature lines between the two booksim2
copies (not full files — vendor baselines may legitimately differ). It
caught a real mirror gap during development (extern still had the v1
print) — exactly its job.

## Tests added

`tests/test_evidence_plumbing.py` — **19 tests**: seam mapping (full
result, gap=loss, stock-binary honesty, absent max, contradictory
accounting, pkt_count corroboration), F3 PASS/FAIL through verify_design,
F8 bound from requirements (binding, none, min-over), F2 adjacency
PASS/FAIL, `topology_adjacency` (mesh k4 corners/interior, torus
wraparound, anynet real file, unsupported → None).

`tests/test_cli_modules.py::TestParseOutput` — +4: drain-point evidence,
stock-binary absent keys, NaN-guarded per-block max (real/NaN/wrong-block).

## Full-suite result

**1180 passed, 1 skipped** (Phase 10: 1158 → +22). Lint PASS. Doctor
quick: all pass incl. the new mirror check. Embedded ASTRA binary
rebuilt from the mirrored extern sources; Golden-A still passes
(41s live).

## Known residuals

1. `delivered 0 packets` on the "Trace replay complete" line is a
   pre-existing cleared-counter display quirk (same root as the Overall
   -nan); the VeritX totals supersede it for conservation. A cleanup
   could print `_veritx_total_accepted_flits/pkt_size` there instead.
2. `mclb`/`escape`/`shortest` cert paths don't emit VeritX totals (they
   don't run trace-drain); only trace-driven runs get conservation
   evidence today.
3. Phase 13 proper must now consume these evidence shapes (constraint
   verdicts in the compiler's candidate records).

## Gate

```text
[x] sim measurements reach F2/F3/F8 as typed evidence
[x] absent stats → NOT_RUN, never fabricated zeros
[x] conservation is measured (fork totals), not derived (identity)
[x] F2 uses executed topology, F8 uses declared requirements
[x] fork delta mirrored + doctor-guarded against drift
[x] embedded + standalone binaries rebuilt and live-verified
[x] full suite passes
```

**Next: Phase 13 — Requirements-driven Fabric Compiler** (the compiler
returns FEASIBLE/NO_FEASIBLE_DESIGN; hard constraints never silently
relaxed; full candidate records per §17).
