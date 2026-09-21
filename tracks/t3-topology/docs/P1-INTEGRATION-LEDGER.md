# P1 Integration Ledger (integration authority: `integration/p1-product`)

Lane branches are evidence sources. Nothing merges INTO them. All
integration happens here, in stage order. P3 remains deferred.

## Pinned inputs (immutable for this campaign)

| Role | Ref | SHA |
|---|---|---|
| Shared base (P1X.0 contracts) | `p1x/product-contracts` | `ec747ffe` |
| P1B verified evaluation | `p1b/verified-evaluation` | `3def89c3` |
| P1C workload + requirements | `p1c/workload-requirements` | `33703bd0` |
| P2 guided optimization | `p2/guided-optimization` | `8c80a38f` |
| P4 studio | `p4/studio` | `f8e01c4a` |
| Handoff lane (capability mine, NEVER wholesale-merged) | `p1/fabric-compiler-productization` | reconciled per-change at Stage 8 |

## Lane gates (reconciliation ruler)

- P1B: 47/47 focused; DOR live mesh EVALUATED; 63/63 unprovisioned
  cross-qualification; 162/162 provisioned cross-qualification; matrix
  symdiffs empty. Exit: `FabricCompiler → llama_dense_64tiles → DOR_XY →
  mesh-DOR → EVALUATED` (4257 cycles, schema-valid view).
- P1C: v3 workload schema (disjoint `srota/CompileRequest/v3` domain);
  single-class bridge; multi-class honest refusal; requirements with
  binding+UNMEASURABLE never passing; immutable workload source semantics.
- P2: GUIDED-only candidates recompiled per candidate; deterministic
  search/Pareto; evaluation provenance (`evaluation_status`,
  `performance_result_id`, requirement verdicts) in result identity;
  `sha256:` view boundary. Fake evaluator unit-tests only.
- P4: real-engine-projected fixtures; 5/5 schema+realizability validation;
  Studio UI on views only (no engine imports).

## Law (from review, binding on integration)

1. Evaluator derives the backend projection from fabric semantics
   (MESH+DOR_XY → CERTIFIED_BOOKSIM_MESH_DOR_XY_V1; ANYNET-compatible →
   CERTIFIED_BOOKSIM_ANYNET_V1; else UNSUPPORTED). No user routing knob.
2. Traffic class comes from lowered workload intent; `len(unique) == 1`
   supported, multi-class → UNSUPPORTED. Never collapse to DEFAULT.
   `EvaluationOptions.traffic_class` is legacy/test-only.
3. Requirements stay honest: aggregate-only evidence + bandwidth floor →
   UNMEASURABLE (never SATISFIED); wrong-class → NOT_APPLICABLE/UNMEASURABLE.
4. Real optimization metrics only (completion/latency/packets/flits as
   evidenced); no fake area — UNMEASURABLE instead. Unevaluated or
   binding-violated candidates never reach Pareto. CMESH-compiled but
   uncertified-backend candidates stay visible as EVALUATION_UNSUPPORTED.
5. Studio consumes views only
   (Compilation/Evaluation/RequirementReport/OptimizationStudy/Design);
   hash normalization at the view boundary, never in React.

## Stage log

- [x] Stage 0 — ledger + tip pins recorded (P1-INT.0)
- [x] Stage 1 — P1B merged (P1-INT.1). Gates: 47/47 focused green; merged-tree
      battery 118F/44E with EMPTY symdiff vs P1B provisioned matrix (162/162);
      120-vs-P1A set proven env-travel (identical at base); 20 resolved by binary;
      live anchor llama_dense_64tiles -> EVALUATED + schema-valid view green.
      Binary: BookSim sha65d61d3 (copied byte-identical from P1B lane).
- [x] Stage 2 — P1C merged (P1-INT.2, 136/136 focused green incl. 2-line gate
      widenings). `application/product_evaluator.py`: v3 -> compile -> lower ->
      bound-check -> P1B evaluate -> requirements; class from lowered intent
      (no relabel knob); multi-class -> UNSUPPORTED pre-spawn; 5/5
      orchestration tests incl. provisioned tp=4 mesh EVALUATED +
      SATISFIED report over mesh-DOR.
- [x] Stage 3 — demonstrated by provisioned orchestration test (tp=4 mesh
      EVALUATED over mesh-DOR + SATISFIED report) and the Stage-4 slice below.
- [x] Stage 4 — `llama_dense_64tiles-v3.json` (square MESH, 1 class, 1 binding
      latency req, inside DOR certified domain) + vertical slice green:
      COMPILED -> 10/10 PASS -> 8-rank graph -> admission -> mesh-DOR
      EVALUATED -> evidence digest match -> SATISFIED report, then cold
      reopen (cert/graph/message/traffic IDs, evidence, verdicts) all equal.
- [x] Stage 5 — P2 merged (P1-INT.5). `optimization/real_evaluator.py`:
      v3 candidate -> compile -> lower -> bound-check -> P1B evaluate ->
      requirements; EVALUATED ⟺ compiled+evaluated+binding-SATISFIED,
      else COMPILE_FAILED/UNSUPPORTED with cause in error (visible, never
      Pareto); objectives = evidenced only (completion_cycles/ns +
      backend numerics; NO area/analytics). One justified optimizer touch:
      `apply_patch` accepts v3 (identical replace path). 2/2 real-adapter
      tests (live grid Pareto + uncertified-corner visibility).
- [x] Stage 6 — `--evaluate booksim` wired (fake stays offline-safe default;
      booksim requires v3, fail-closed). Golden on llama_dense_64tiles-v3:
      link_width{64,128} -> 16161 vs 7207 cycles, Pareto={128}, selected,
      schema-valid view. Found+fixed en route: v3 Objective metric field,
      evidence-slot reuse across invocations (fresh study token per run).
      CLI test proves real + repeatable (distinct evidence digests).
- [x] Stage 7 — P4 merged (P1-INT.7, isolated apps/studio). Gateway
      `application/views.py` (compilation/design projectors; absent facts
      omitted, never faked). All 5 fixtures regenerated from live engine
      runs (validator 5/5 incl. new study linkage rule: design/opt.base
      bind base intent, product views bind one winner hash from candidates).
- [x] Stage 8 — handoff branch (`p1/...`, tip 662e7ce6) reconciled
      per-change; never wholesale-merged:
      - P1B.3a golden re-pin -> REJECT (handoff-only DEFAULT VC base
        class; integrated golden corpus green unmodified, 6/6).
      - Q1/Q2 implementation (profile registry, C++ dump, lowering,
        projection threading) -> SUPERSEDED by integrated meshdor
        (separate CERTIFIED_BOOKSIM_MESH_DOR_XY_V1, already merged).
      - Q3 adversarial tests -> USEFUL_TEST replayed as
        `test_p1b_meshdor_gates.py` (11/11: seat gate, exact-grid
        positive, native render keys, forged k/n/routing_function,
        foreign-bundle transplant, path selection x3, multi-endpoint).
        Deliberately not ported: missing/express-link gate refusals
        (lane gates don't check exact adjacency; routing divergence
        still caught by dump compare), trace round-trip (no lane
        surface), serving-target (P0-sealed layer), synthetic-dump
        positive (covered by live exit gate).
      - QB/Q3a + P1B-QUALIFICATION.md -> noted, not replayed as doc
        (numbers are handoff-tree-specific); useful findings kept here:
        handoff tree reaches 5 failed/0 errors because Q1 wires mesh
        lowering into legacy control-plane paths (out of scope: legacy
        surfaces stay base-identical by design); pinned-producer dirt
        discipline + flaky supervision-timing pair confirmed.
      - In-flight evaluator files (prepare/evaluate/performance tests)
        + P1B.5/6/7 items -> REJECT (authorities exist integrated);
        left uncommitted on the handoff branch.
      KNOWN LIMITATION (follow-up, not papered over): a non-grid
      express channel passes lane gates and, if DOR never routes over
      it, the dump compare too — silent area/timing drift. Fix:
      exact-adjacency gate in `_mesh_link_semantics` (refuse more,
      never less).
- [x] Seal — global verification: 218/218 focused (lanes + orchestration +
      slice + views + real adapter + booksim CLI + gates); final battery
      118F/3796P/44E with EMPTY symdiff vs provisioned matrix (162/162);
      P4 validator 5/5 on merged tree. Tag below.

---

# P1 RED-TEAM CLOSURE WAVE (seal WITHDRAWN)

**Status change:** `P1 product integration — SEALED` →
`P1 integration candidate — functional vertical slice demonstrated;
adversarial integration closure NOT PASSED`.

The `p1-product-integration-seal` tag was withdrawn (deleted local +
remote) after adversarial review of `5d252eb5`. The review's process
critique is accepted without reservation: focused counts and a
matrix-identical battery are regression evidence, not correctness
evidence, and several tests encoded weaker propositions than their
names claimed.

## Finding adjudication (coordinator-verified against the tree)

| # | Finding | Verdict | Evidence |
|---|---|---|---|
| RT-1 | Express/missing adjacency passes gates while lowering claims `TOPOLOGY_GRAPH -> DERIVED_EXACT` | **CONFIRMED (P0)** | `mesh_dor.py:_mesh_link_semantics` checks latency/weight/parallelism only; `mesh_dor.py:372` claims DERIVED_EXACT. Unsoundness, not debt. |
| RT-2 | RequirementEvaluator provenance-transplant hole (no design_hash/workload_graph_id binding) | **CONFIRMED (P0)** | `requirements.py` checks types + geometry + resource_id presence only. |
| RT-3 | "Cold reopen" never calls `reverify_result` | **CONFIRMED (P0)** | 0 occurrences in `test_p1_product_vertical_slice.py`; warm `scalars` retained. |
| RT-4 | Caller network clock rescales cycles requirement verdicts | **CONFIRMED (P0)** | evaluator cycles→ns via `network_clock_hz`; requirements ns→cycles via `default_clock_freq_mhz`. All tests used 1GHz/1GHz. |
| RT-5 | Studio fixtures not live-engine; validator not engine-realizability | **PARTIAL** | Fixture-content claim REFUTED: sealed fixture is engine-generated (`window_cycles=16161, cycles_only=false, measured=16161.0` at `5d252eb5`). BUT: stale stdlib `generate_fixtures.py` (hardcoded 50000/96.4) still ships and would recreate impossible fixtures if run — duplicate-authority hazard, delete it. Validator weakness CONFIRMED (mirrors enums; runs no engine). |
| RT-6 | Fixture shows EVALUATED+cycles_only+SATISFIED-with-50k | **REFUTED as stated** (stale generator's output, not the committed fixture); the hazard it points at is RT-5's stale-generator half. |
| RT-7 | Validator cannot catch impossible states | **CONFIRMED (P1)** | `validate_fixtures.py` never invokes compiler/evaluator/requirements. |
| RT-8 | `design_view` permits cross-design locked-state transplant | **CONFIRMED (P1)** | no isinstance/design_hash match in `views.py::design_view`. |
| RT-9 | Orchestration leaks typed refusals as exceptions | **CONFIRMED (P1)** | `evaluate_product` calls lowerer/bound-check unguarded; `RealCandidateEvaluator` catches a subset. |
| RT-10 | Optimizer KeyError on unmeasured objective | **CONFIRMED (P1)** | `pareto.py` indexes `vals[m]` for every declared objective. |
| RT-11 | P1C RequirementReport discarded at optimization boundary | **CONFIRMED (P1)** | `CandidateEvaluation` has no report field. |
| RT-12 | Study view destroys VIOLATED vs UNMEASURABLE | **CONFIRMED (P1)** | `to_study_view` maps None→False (fail-closed but lossy). |
| RT-13 | Repeatability test does not test colliding root; token is 1-second | **CONFIRMED (P1)** | test uses `runs-a`/`runs-b`; token `%Y%m%dT%H%M%S`. |
| RT-14 | No independent CI on sealed SHA; unpinned container | **CONFIRMED (process)** | `ci.yml` triggers exclude `integration/**`; container tag `:latest`. |

## Exit gates for this wave (no new functionality)

1. Exact adjacency equality gate (channel set == native k×k mesh
   adjacency) — refuse more, never less; express/missing cases adversarial.
2. Same-geometry cross-design transplant attacks (evaluator + requirements
   + views) refused at the earliest authority boundary.
3. Tampered persisted PerformanceResults with stale IDs refused via
   `reverify_result`; vertical slice cold half must USE it.
4. 0.5×/2× clock attack matrix: cycles-based verdicts invariant under
   caller clock; wall-time claims refuse without a valid clock.
5. Unsupported-workload typed refusals at the product boundary
   (`evaluate_product` never leaks InvalidInput/UnsupportedSemantics/…).
6. Missing real objective → typed UNMEASURABLE/ineligible, never KeyError.
7. Mismatched request/Compilation view projection refused.
8. Requirement provenance bound into optimization records (report
   identity or per-entry verdicts+authority), not discarded.
9. Truly process-cold replay (subprocess, no warm scalars).
10. Engine-generated Studio fixtures byte-for-byte, stale generator
    deleted, validator proves realizability by running the engine.
11. CI runs on `integration/**` with a digest-pinned container.

No P3, no 120-node legacy cleanup, no feature work until these gates pass.

## RT-3 closure note — Studio realizability (branch `rt3/studio-realizability`)

- **RT-5a (stale generator):** `apps/studio/fixtures/generate_fixtures.py`
  deleted. Single authority is
  `tracks/t3-topology/dse/veritx_dse/tools/generate_studio_fixtures.py`;
  `apps/studio/package.json` `gen-fixtures` and the Studio README now point
  at that tool (and the README no longer repeats the stale generator's
  5×5/78-agent/radix-3/6-candidate numbers — it documents the engine
  fixture values actually committed).
- **RT-5b (engine realizability):** `apps/studio/scripts/validate_fixtures.py`
  keeps the schema/linkage/enum fast path and adds an engine mode (default
  ON when `CI`/`GITHUB_ACTIONS` is set; `--engine` forces it, `--skip-engine`
  opts out offline). It regenerates all five fixtures with the engine tool
  into a temp dir and compares. Missing engine/BookSim **fails loudly**.
  Finding: the volatile allowlist cannot be empty as the task assumed — the
  BookSim evidence artifact embeds its absolute run path and the producer
  binary digest, so `producer_identity`, `evidence.raw_evidence_digest`, and
  the performance-result-id chain are regenerated per host/run. Those exact
  paths are the documented allowlist; every other field (design,
  certificate/obligations, window, metrics, verdicts, candidates, objectives,
  Pareto) must match exactly. v2 study-view acceptance is wired: v2 is
  selected when `contract_version == 2` and
  `contracts/srota/v1/optimization.study.view.v2.schema.json` exists; v1
  fixtures keep validating against v1 (verified against RT-1's real v2
  schema: tri-state verdicts accepted, boolean verdicts refused under v2).
- **RT-13 (collision):** `cmd_optimize` now creates its evidence root as
  `%Y%m%dT%H%M%S-<pid>-<counter>` with `mkdir(parents=True, exist_ok=False)`
  and retries on `FileExistsError` (module-level monotonic counter); a root
  is never reused. `test_p1_optimize_booksim.py` freezes wall time, runs two
  invocations against the SAME base root in the SAME second, and asserts both
  succeed with distinct per-run evidence digests while candidate identities
  stay stable.
- **RT-14 (CI):** `integration/**` added to push triggers. Container pinned
  to `ghcr.io/anmol-s314/veritx-tools-base@sha256:4018cd4786a4d3d64143e1452a76bffecec26922e92ef9590ff9810f2d344bed`
  (resolved from the registry via `podman pull` → RepoDigests; the
  `rebuild-docker` job notes that a new `:latest` does not move the pin).
  **REQUIREMENT / fail-loud:** that image (and the cached local rebuild)
  ships Python 3.10, which cannot parse `tracks/t3-topology/dse` (PEP 701
  f-strings) — the t3 container leg fails at `make lint` until the image is
  rebuilt on Python ≥ 3.12. A separate `studio-fixtures` job was added on a
  plain 3.12 runner (pip-installs the DSE package, builds the vendored
  BookSim, runs `validate_fixtures.py --engine`) so gate 10 has CI evidence
  independent of the stale container.

No engine semantics changed. The only non-`apps/studio` code touched is the
RT-13-mandated `veritx_dse/cli/cli.py` run-root construction (no scientific
identity, no evaluation semantics).
