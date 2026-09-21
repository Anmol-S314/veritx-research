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
- [ ] Stage 6 — real optimization golden (`--search grid --evaluate booksim`)
- [ ] Stage 7 — merge P4; regenerate fixtures from integrated engine; view
      boundary gateway
- [ ] Stage 8 — reconcile handoff branch per-change (ALREADY_IMPLEMENTED /
      SUPERSEDED / USEFUL_TEST / USEFUL_ORCHESTRATION / REJECT); never
      wholesale-merge
- [ ] Seal — `p1-product-integration-seal` tag with full provenance record
