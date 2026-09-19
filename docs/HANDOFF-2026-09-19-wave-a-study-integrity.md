# HANDOFF 2026-09-19 — Wave A: study-integrity correctness fixes

Status: COMPLETE (all gates green). Follows the phases 13–17 freeze
(`36ade9fc`, tag `phase17-freeze-2026-09-19`). This is the first post-freeze
correctness wave, driven by two adversarial reviews (36-item post-freeze audit
+ T3 control-plane review).

## What landed (Wave A boundary only)

1. **Routing intent ≠ preset mutation (#1).** `NetworkSpec.routing` is now
   `str | None = None` — `None` means "no opinion, the named preset owns
   routing". A single resolver (`_resolve_named_network` in `core/spec.py`)
   resolves `None → preset.routing` and rejects any explicit value that
   contradicts the preset (`mesh_8x8 + dim_order` → `SpecError` before any
   run directory exists). The resolved spec always carries a concrete
   routing; `run_experiment()` consumes it and asserts it matches the
   preset — the `dataclasses.replace(topo, routing=...)` mutation is gone.
   `mesh_8x8` omitted vs explicit `min_adapt` produce the **same**
   `experiment_hash`.

2. **Serving fabric is cluster-owned — temporarily (#2/#3).** For
   `mode == "serving"`, `spec.network` must be omitted; the registered
   serving cluster is the authoritative fabric intent. Before `Run.create()`,
   `resolve_serving_fabric_identity(cluster_path)` derives the expected
   fabric using the **child's own production arithmetic**
   (`serving/core/config_builder.py` — imported, not replicated) and it is
   injected into the resolved spec, so the immutable experiment hash binds
   the fabric. After execution, `executed_fabric_identity()` parses the
   generated `config.cfg`/anynet/network.yml and the slice refuses any
   contradiction (`FABRIC_INTENT_MISMATCH`) or missing evidence — fail
   closed. **Wave B will replace this temporary authority with a first-class
   FabricArtifact; do not build on the cluster-derived rule.**

3. **Architecture invention removed (#8).** The child's silent
   `_infer_dims`/FullyConnected fallbacks are gone; malformed or missing
   cluster network semantics now fail preflight in the child too (source
   pinned).

4. **Compiler verdict honesty (#6).** Top-level verdict decision order is
   FEASIBLE > CONSTRAINT_UNMEASURABLE > EVALUATION_FAILED > SEARCH_INCOMPLETE
   > NO_FEASIBLE_DESIGN (pure helper `_verdict_from_counts`,
   `synthesis/compiler.py`). Simulator failure, unmeasurable constraints and
   pruning can never masquerade as `NO_FEASIBLE_DESIGN`; `pareto` is `None`
   for non-FEASIBLE verdicts; `relaxation_information` only for the fully
   measured NFD case.

5. **Comparison certification completeness (#7).** Fingerprints now carry
   executed-fabric fields (topology, routing, node_count, vc_count,
   packetization, backend) from run evidence; any unresolved mandatory
   dimension → `certified=False` with `INSUFFICIENT_PROVENANCE` and the
   missing list. Two `None`s are not equality.

6. **Rank-preserving workload identity (#11).** `workload_identity()`
   hashes the rank→artifact assignment (canonicalized by the rank key, not
   input order, not the artifact multiset). Swapping two ranks' workloads
   changes identity.

7. **T3 stop-bleeding (#9).** `_ui_open()` returns the child's rc;
   `start-here` short-circuits on first failed step; honest completion
   wording. No other T3 work — the T3-retirement review (second control
   plane, `topology_sweep.json` as master JSON, winner-recreating reports,
   hidden persisted state) is **recorded as the next milestone, not
   implemented here**.

## Gates (final run, this tree)

- `pytest tests -q` → **1512 passed, 3 skipped, 0 failed** (6:15)
- `make -C tracks/t3-topology lint` → rc=0
- phase15 acceptance battery → **VERDICT PASS 16/16** from `dse/` AND repo root
- Semantic pins A–L all pass in `tests/test_study_integrity.py`
  (+ serving/run-core/comparison fixture updates elsewhere)

## Incident record — foreign merge state in this worktree

This worktree is one of several linked worktrees (`.treehouse/`) of this
repo; a sibling agent's MR12 ("booksim csv trace extension", merge commit
`9029acbf`, branch `audit/wave-a-gates`) left a half-finished merge here:
66 unmerged paths, conflict markers in root `Makefile`/`README.md`/
`scripts/tools.py`, `traffic_model.json`, `Statistics.cc`, and stale
trace-instrumented binaries. Repair performed (their content is safe on
their branch; diffs also saved under `/tmp/wave-a-rescue/`):

- `git reset` (mixed — cleared index only; no worktree content lost)
- restored to HEAD: both vendored booksim2 src copies, `Statistics.cc`,
  root `Makefile`, `README.md`, `scripts/tools.py`, `traffic_model.json`
- rebuilt BOTH binaries from clean sources:
  `third_party/booksim2/src` (make) and
  `third_party/astra-sim/build/astra_booksim2/build.sh` →
  `.../booksim2/bin/AstraSim_BookSim2.real`
- **preserved deliberately** (pre-existing, not mine): the
  `injection_rate=0.0` embedded-safety convention (`4npus_*.cfg`,
  `Booksim2Fabric.cc`), `et_feeder_node_attr.h` + `ChunkIdGenerator.cc`
  hardening, llmservingsim `config_builder.py`/`run_paths.py` changes,
  `flow_certifier.py` conservation check, and the sibling's in-flight
  Wave-B study/pipeline work (`api.py`, `cli/pipeline.py`,
  `test_fabric_compiler.py`, `test_pipeline.py`, `test_study.py`) — left
  uncommitted, owned by them.

Rule reinforced: **never trust binaries under vendored trees after any
worktree incident — rebuild both and re-run the golden pins.**

## Not done here (explicitly out of Wave A)

StudyManifest/ExecutionFingerprint, FabricArtifact, `veritx study`,
T3 retirement, cross-surface equivalence tests, scientific mutation tests
(Waves B/C per the review's execution order).
