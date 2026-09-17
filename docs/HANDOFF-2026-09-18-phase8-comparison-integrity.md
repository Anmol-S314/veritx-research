# HANDOFF — Phase 8: scientific comparison integrity (ComparisonSpec enforcement)

**Date:** 2026-09-18 · **Branch:** `epic/booksim-forward-port` @ `1110bc71` (pushed to `github`)
**Prior gate:** Phase 7 (`0e91a612`), 1050 passed, 1 skipped
**Gate:** **PASS** — 1087 passed, 1 skipped; lint green
**Next permitted:** Phase 9 — canonical workload semantic artifact (STOP before it per instruction)

## What landed

One new module (`core/comparison.py`, ~490 lines incl. docstrings) plus
enforcement wiring in the two existing comparison paths. No new
framework; no WorkloadIR/RouteArtifact/RTL/formal/synthesis/Studio.

### 1. Comparison path map (deliverable §1, pre-edit census)

```text
cmd_compare (cli.py:1956..2095)
  → run_compare (pipeline.py): trace × topo_specs × seeds, rows via run_topology_eval
  → checks: WARNING ONLY on mixed node counts (old pipeline.py:230)
  → metrics: honest_latency/latency (cycles, booksim, untyped)
  → output: print_compare_table + winner(min mean) → CompareResult.to_dict
    → results/compare/<ts>/compare.json + --json

multi_workload_pareto.py (tools/, also driven by cmd_pareto)
  → data: traces × topos via shared evaluator (PARETO_PRESET)
  → checks: trace fingerprints, duplicate-md5, common_ok warning (no gate)
  → metrics: per-trace latency, geomean over common successful traces
  → output: pareto_front(ok_agg, keys) ← ok-only filter drop; pareto.json

run manifests (immutable runs, PR6/PR7 slices)
  → full provenance (fidelity, network_mode, network_engine,
    semantic_losses, metric_schema, typed metrics w/ unit+producer+scope)
  → never compared anywhere — now the certified-comparison source
```

`ComparisonSpec` in `spec.py` had **zero consumers** before this phase.

### 2. The gate (`core/comparison.py`)

- **ComparisonIntent** (strict, unknown fields refused; canonical-hash
  `comparison_id` when not supplied). Empty declaration is legal and
  maximally conservative: every dimension controlled → any difference
  refuses. Refusals come from differences, never request shape.
- **Fingerprints**: `fingerprint_from_run` reads spec.resolved.json +
  manifest.json (workload identity = sha256 over canonical
  workload+serving block; missing files → `INSUFFICIENT_PROVENANCE`,
  never guessed). `fingerprint_from_legacy_row` resolves what the row
  actually carries (topology display-name, nodes, seed) and lists the
  rest in `unresolved_dimensions` with `certified: false`; fidelity is
  the declared adapter default (`NETWORK_SIMULATION` +
  `fidelity_provenance`), never silent.
- **Two-tier verdict** (`evaluate_comparability`), matching §8/§13:
  - SET-level incoherence → `INVALID_COMPARISON`: undeclared material
    difference (`UNDECLARED_DIFFERENCE`, names field + first differing
    pair), `TRACE_REPLAY_MIXED` (cannot be declared away, even under
    CROSS_FIDELITY_CALIBRATION — replay is not a fidelity, it's a
    non-simulation), `FIDELITY_MISMATCH` / `NETWORK_MODE_MISMATCH`
    under DESIGN_COMPARISON.
  - CANDIDATE-level → comparison stays valid, candidate excluded with
    visible status: `SEMANTIC_LOSS` (§9 default ban),
    `NOT_COMPARABLE` (§7 engine capability), `MISSING_METRIC`.
- **Metric semantics** (§6): closed tables `KNOWN_UNITS` /
  `KNOWN_METRICS` (booksim cycles/ratio + the Phase-5 serving ns/requests
  vocabulary). `UNKNOWN_METRIC` / `UNKNOWN_UNIT` / `UNIT_MISMATCH`
  refuse; same JSON key ≠ same metric.
- **§7 special case**: `METRIC_CAPABILITY["exposed_communication"]
  .engines_without = {congestion_unaware}` — a constant zero from an
  engine that does not produce the metric is never a measured zero.
- **`pareto_with_scope`** (§8/§11): dominance only over COMPARABLE
  candidates with all objectives present; every requested candidate in
  the output with status + reason; `pareto_scope` states the evaluated
  set; refuses mixed-fidelity DESIGN_COMPARISON frontiers even if a
  caller bypasses the gate.

### 3. Enforcement wiring (§14 migration)

- `CompareResult.verdict` (machine-readable, in `to_dict()` →
  compare.json + --json; `None` only from pre-gate callers = uncertified).
- `run_compare(..., comparison=<intent dict>)`: fingerprints every
  aggregated candidate row (legacy adapter) and evaluates. Default
  intent declares the command's own purpose — `topology` as the
  experimental variable (§4's example) — so any OTHER material
  difference (node count, workload, seeds) refuses undeclared.
- `print_compare_table` returns a claim dict
  `{winner_claimed, certified, verdict_status}`; `INVALID_COMPARISON`
  prints `COMPARISON REFUSED — no winner is claimed.` plus one line per
  difference (field, left/right, reason) and the fix hint. The old
  node-count WARNING is now this gate.
- `multi_workload_pareto.py`: keeps its ok-only frontier but prints the
  scope line (`N requested, M comparable, K excluded` + names) and
  writes `pareto_scope: {…, certified: false, scope:
  LEGACY_BOOKSIM_ROWS}` — legacy output can never read as a certified
  Pareto claim.

## Tests (seam-level, §15; diagnostics pinned, not booleans)

`tests/test_comparison_integrity.py` — 33 tests:
boundary (unknown field, empty declaration legal), fingerprints
(run-dir + INSUFFICIENT_PROVENANCE + legacy unresolved/certified
markers), controlled-vs-variable (workload/nodes/VC undeclared →
REFUSE with exact field; topology/routing declared → ALLOW), fidelity
policy (booksim vs analytical design → FIDELITY_MISMATCH; explicit
CROSS_FIDELITY_CALIBRATION → ALLOW with kind; replay-vs-real →
TRACE_REPLAY_MIXED even under calibration kind; calibration cannot
launder replay), metric compatibility (unit mismatch/unknown
unit/unknown metric/unaware exposed_communication), §9 semantic-loss
exclusion, scoped Pareto (failed/missing visible, no filter-drop,
never-mixed-front), and the §12/§13 end-to-end topology experiment.

`tests/test_pipeline.py` — 5 new: undeclared node-count fails closed
through `run_compare` + printer (UNDECLARED_DIFFERENCE in output, no
winner); declaring both actual differences allows the winner claim
(uncertified, legacy rows); default-intent comparability; INVALID
verdict suppresses the winner block; verdict flows through `to_dict`.

## Live examples (exact output)

Undeclared node-count difference (only `topology` declared):

```text
  COMPARISON REFUSED — no winner is claimed.
  UNDECLARED_DIFFERENCE: node_count (4 vs 8)
  Declare the differing dimensions as experimental_variables in the
  comparison spec, or compare like with like.
claim: {'winner_claimed': False, 'certified': False,
        'verdict_status': 'INVALID_COMPARISON'}
```

Both differences declared → winner claimed (`certified: false` because
legacy rows cannot prove tool/VC/packetization identity):

```text
  Winner: mesh_4 (10.00c, n=1 — no spread sampled)
  vs mesh_8: 50.0% faster
claim: {'winner_claimed': True, 'certified': False,
        'verdict_status': 'COMPARABLE'}
```

## Rulings / design decisions (with the tests that forced them)

- **Two tiers, not one**: my first draft made semantic loss set-level
  invalid; the §13 shape (VALID + excluded[]) and §8's status list
  forced the restructure — candidate defects exclude the candidate,
  set incoherence invalidates the comparison.
- **No VARIABLE_DOES_NOT_VARY refusal**: declaring `topology` +
  `routing` while only topology varies must ALLOW (routing is coupled
  to topology choice); the rule is one-directional (differing ⇒
  declared). A constant declared axis is degenerate, not invalid.
- **Legacy display names are topology identity**: the name-collision
  logic already guarantees distinct display names = distinct candidate
  graphs, so m4-vs-m8 differs in `topology` AND `node_count` and the
  intent must declare both (test updated — the gate was right).
- **`certified` flag**: legacy-compare output is permanently
  `certified: false` (vc/packetization/tool identity unresolved).
  Certified comparisons require immutable runs via
  `fingerprint_from_run` — that path exists and is tested; the
  compare-between-runs CLI surface is a later UX step, not Phase 8
  scope.
- **Replay is not a fidelity**: CROSS_FIDELITY_CALIBRATION legitimizes
  estimate-vs-simulation, never replay-vs-simulation.

## Gate checklist (§17)

```text
[x] every official comparison passes through ComparisonSpec enforcement
    (cmd_compare carries verdict; pareto tool marked uncertified-legacy)
[x] undeclared scientifically material differences fail closed
[x] intended experimental variables may differ (topology/routing/VC tests)
[x] metric units/semantics checked (closed tables; UNKNOWN refusals)
[x] replay cannot mix with real simulation (TRACE_REPLAY_MIXED, undeclarable)
[x] unaware zero-exposed cannot masquerade (NOT_COMPARABLE by engine)
[x] semantic-loss runs excluded explicitly (SEMANTIC_LOSS status)
[x] failed/incompatible candidates remain visible (pareto_with_scope)
[x] Pareto scope reports eligible count (pareto_scope + printer scope line)
[~] stochastic replication basis explicit (seed_policy fingerprinted;
    per-seed rows preserved; CI computation deferred — single-seed
    legacy reality, noted below)
[x] old warning-only path no longer authoritative (winner suppressed,
    diagnostics printed, claim dict returned)
[x] full suite passes (1087 passed, 1 skipped; lint green)
```

## Residuals

- Confidence intervals: single-seed legacy runs make CI moot today;
  `seed_policy` is fingerprinted and replication aggregation hooks
  exist (`objectives_status`, per-seed rows). Real multi-seed CIs land
  with run-based comparisons where stochastic replication is declared
  in the spec (replication.seeds already exists in ExperimentSpec).
- `veritx compare` has no `--comparison-spec <file>` flag yet; intent
  currently comes from the API param (default = topology experiment).
  A thin flag forwarding to `resolve_intent` is trivial follow-up.
- `fingerprint_from_run` sets `vc_count`/`packetization` to None (not
  recorded at spec level) — Phase 9/10 artifacts close this honestly.
- Pareto tool is script-shaped (841 lines, sys.path shims); migration
  onto core.comparison's pareto_with_scope is desirable once run-based
  candidates exist. Not done here to keep Phase 8 bounded.

## Verdict

Phase 8 gate: **PASS**. Committed `1110bc71`, pushed to `github`.
Next permitted: **Phase 9 — canonical workload semantic artifact.**
Stopping here per instruction.
