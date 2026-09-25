# Srota Studio (P4)

Fixture-backed product UI for the Srota Fabric Compiler program. Runs **entirely
from contract-validated fixtures** — no engine connectivity.

- Stack: **Vite + React + TypeScript** (typed, zero runtime UI dependencies;
  SVG canvas hand-rolled). Chosen for type safety against the contract views,
  fast iteration, and no extra supply-chain weight.
- Tone: semiconductor engineering tool — dense tables, monospace identities,
  flat dark/light themes. No gradients, no gloss.
- Consumes the frozen product views: the **OptimizationStudyView is contract
  v2** (`contracts/srota/v2/optimization.study.view.schema.json`), the other
  four views stay v1 (`contracts/srota/v1/`). **Never imports Python engine
  modules** (the validator's provisioned mode deliberately does, to prove the
  fixtures are engine-realizable; the UI never does).

## Layout

```
apps/studio/
  landing.html     marketing surface (second Vite entry, served at
                   /landing.html; its hero renders public/assets/
                   veritx-board.webp with Anime.js motion only)
  fixtures/         five engine-generated *.json fixtures (no in-tree generator)
  scripts/          validate_fixtures.py (schema + linkage + vocabulary fast
                    path; provisioned engine proof + byte comparison)
  tests/            test_studio_contract_v2.py (the C-6 required tests)
  src/
    types.ts        contract-mirror TS types
    presentation.json  state -> {class,label} policy (Python-readable single
                    source; every engine state renders distinctly)
    fixtures.ts     fixture loading (validated JSON only)
    App.tsx         shell: sections + fixture switcher + theme
    landing/        light landing styles + motion.ts (entrance, parallax)
    components/
      DesignEditor.tsx   E1–E5 editor (LOCKED read-only, GUIDED/FREE editable)
      FabricCanvas.tsx   SVG structure canvas + overlay extension points
      VerifyView.tsx     10 P1A obligations, click for evidence
      EvaluateView.tsx   NOT_RUN / RUNNING / BACKEND_UNAVAILABLE / EVALUATED /
                         FAILED / UNSUPPORTED states; present-metrics-only
      OptimizeView.tsx   v2 three-authority study: candidate state taxonomy
                         (compilation / evaluation / requirement / objective
                         availability / tri-state constraints / eligibility /
                         Pareto), no inference from missing values
```

## Commands

```bash
npm install
npm run dev        # local dev server: console at /, landing at /landing.html
npm run build      # typecheck + production build (both entries)
npm run validate   # schema/linkage/vocabulary fast path (provisioned proof
                   # runs automatically when CI is set)
npm run gen-fixtures  # regenerate via the engine tool (BookSim required)

# Force/refuse the provisioned proof explicitly:
python3 scripts/validate_fixtures.py --engine       # engine proof + byte compare
python3 scripts/validate_fixtures.py --skip-engine  # offline: fast path only
```

## Fixtures

| File | State demonstrated |
|---|---|
| `compiled-mesh.json` | COMPILED, 10/10 PASS, evaluation NOT_RUN (9×9 mesh, 72 agents) |
| `invalid-design.json` | UNSUPPORTED typed refusal (torus has no certified routing derivation; no bundle) |
| `backend-unavailable.json` | COMPILED + BACKEND_UNAVAILABLE (unidentifiable producer, reason, no metrics) |
| `evaluated-design.json` | EVALUATED (16161-cycle aggregate window, present metrics, producer, fidelity warning) + RequirementReport |
| `optimization-study.json` | **contract v2** study over `{link_width ∈ 32/64/128} × {rcu_enabled ∈ false/true}`: 6 engine-produced candidates — one eligible Pareto member (128-bit, 437 cycles), one evaluated candidate failing a binding product requirement (64-bit, 845), one evaluated candidate violating a hard constraint (32-bit, 1950), and three compile-refused candidates (RCU intent) with objective/constraint `UNMEASURABLE` |

Every fixture must pass `npm run validate` (Draft 2020-12 schemas + cross-view
hash linkage: design_hash consistency, performance_result_id binding,
EVALUATED completeness, no-metrics-on-refusal) plus the three-state study
coherence gate and the provisioned engine proof below when available.

## The v2 study view (three authorities, never merged)

| Authority | Fields | Question answered |
|---|---|---|
| Product requirements | `evaluation_ids.requirement_report_id`, `product_requirements` | Did the DESIGN satisfy the customer? |
| Optimization constraints | `constraint_verdicts` — `SATISFIED / VIOLATED / UNMEASURABLE` | Did the CANDIDATE satisfy the study's hard constraints? |
| Measured objectives | `objective_values` + `objective_availability` — `MEASURED / UNMEASURABLE` | Was each requested objective actually measured? |

Every candidate also carries `compilation_status`, `evaluation_status`
(`EVALUATED / COMPILE_FAILED / INVALID / UNSUPPORTED / BACKEND_UNAVAILABLE /
FAILED`), `evaluation_reason`, `evaluation_authority`,
`eligibility_reason`, `pareto_eligible` and `pareto_member`. The top level
carries `result_class` (`CERTIFIED_PRODUCT` only from
`Optimizer.optimize_certified`), the bound `metric_registry_id` /
`metric_registry_version`, `optimization_result_id`, and the lossless
`definition` (`definition_id`, objective `{metric,direction}`, constraint
`{metric,op,threshold}`, `method`, `selection`).

Studio renders these fields as-is: a boolean constraint verdict or an absent
objective value can no longer be silently read as PASS. `src/presentation.json`
is the single presentation source keyed by the engine values, and a test
proves `UNMEASURABLE` renders differently from `VIOLATED` and that every enum
value is mapped (an unknown value renders as a dashed `UNKNOWN`, never as a
passing style).

## Realizability gate (fixture semantics, not just shape)

The frozen schemas accept broad strings, so schema validity alone would admit
impossible products. `scripts/validate_fixtures.py` runs:

**Fast path (always):** mirrored engine vocabularies + invariants —

- `model_family` ∈ ModelFamily, `kind` ∈ AgentKind, `qos_class` ∈ QoSClass,
  `topology_family` ∈ TopologyFamily, `serving_mode` ∈ ServingMode,
  `arbitration` ∈ router-behavior allocator aliases.
- `rcu_enabled: true` with `status: COMPILED` is rejected — the compiler
  refuses RCU intent as UNSUPPORTED.
- COMPILED designs must satisfy the materialization sizing rule
  (`radix² × concentration ≥ agent count`), or the compiler would refuse them.
- v2 study coherence: constraint verdicts are three-state strings (never
  booleans), `pareto_eligible` is the full conjunction (EVALUATED +
  certified-backend + passing product requirements + every objective
  MEASURED + every constraint SATISFIED), ineligibility is always typed,
  `pareto_ids` equals the member set, the selection is a Pareto member, and
  `CERTIFIED_PRODUCT` binds a registry identity. A self-test proves the gate
  rejects a document the schemas would accept for each impossibility.

The fast path ends with exactly:

```
FAST PATH ONLY: backend realizability not proven
```

and never claims a backend proof.

**Provisioned proof** (`--engine`, or default ON when `CI`/`GITHUB_ACTIONS` is
set): requires a qualified BookSim producer. The validator then

1. regenerates all five fixtures with the engine tool
   (`python3 -m veritx_dse.tools.generate_studio_fixtures`, from
   `tracks/t3-topology/dse`) into a TEMP directory;
2. proves the regenerated objects through the engine gateways: the EVALUATED
   fixture (metrics + network window + producer), its binding
   RequirementReport (identity + SATISFIED verdicts), and a real
   OptimizationStudy (`CERTIFIED_PRODUCT`, engine registry identity, full
   three-state candidate taxonomy, `optimize_certified` only);
3. compares the regenerated bytes with the committed fixtures
   **byte-for-byte**, and reports any difference. No producer-volatile
   allowlist exists: a difference is either a typed semantic mismatch or a
   reported engine regression.

### Byte reproducibility (gate 10)

The committed `evaluated-design.json` and `optimization-study.json` are
byte-reproducible on a fresh run. evidence-v2 split the persisted backend
evidence into the run-stable scientific document
(`veritx/backend-scientific-evidence/v2`, what `raw_evidence_digest`
hashes and what every derived identity binds) and a separate execution
attempt record (`veritx/execution-attempt/v1`: wall time, absolute run
paths, host platform text). Runtime provenance can no longer enter
`performance_result_id`, the requirement-report identity or
`optimization_result_id`.

The provisioned gate still fails on ANY byte difference. If runtime
provenance ever leaks back into the scientific digest, the diff lands on
the provenance-derived identity paths and the gate prints:

```
ENGINE DEFECT (REPORTED, NOT NORMALIZED) <fixture>: ...
```

The checker does not strip the fields and does not compare normalized
documents.

## Honesty rules enforced in UI

- LOCKED properties (routing DOR_XY, VC count, turn restrictions) render
  read-only with 🔒 Derived badges; they live in `locked_derived`, never in the
  editable `noc_guided` block.
- Evaluation metrics render **only when present**; absent metrics are omitted,
  never zero-filled. Non-EVALUATED outcomes show reason + explicit no-metrics note.
- Requirement verdicts come from the engine's RequirementReport
  (SATISFIED / UNMEASURABLE / VIOLATED / NOT_APPLICABLE); the evaluated
  fixture's latency ceiling is SATISFIED by the measured 16161-cycle window
  and no fixture invents a Gbps authority the engine did not produce.
- Optimization: the three authorities render in separate columns/panels;
  unmeasured objectives render `UNMEASURABLE` (never `0`), ineligible
  candidates show the engine's `eligibility_reason`, and the Pareto plot
  excludes candidates whose objectives are not explicitly MEASURED.
- Canvas overlays (routing / VC class / traffic class / utilization) are
  **extension points with stated data needs**, never fabricated colors.
- Design edits are local-only and flagged dirty ("recompile required"); fixture
  mode cannot recompile. "Request evaluation" on a NOT_RUN design demonstrates
  RUNNING, then resolves to an honest refused run (no metrics). Checking the
  RCU GUIDED box surfaces the engine's documented UNSUPPORTED refusal inline.
- Generate section is a disabled indicator (P3 deferred). No export buttons —
  no fake export functionality.
- E4 Dependencies: the frozen contract carries no DependencyGraph view, so the
  panel derives admission ordering from binding E2 requirements and says so.

## Required tests

`python3 -m pytest apps/studio/tests -q` runs the C-6 tests: schema versions,
the exact fast-path statement, the provisioned engine proof, byte comparison
(identical or the reported defect, never a semantic drift), engine-originated
hashes, `optimize_certified` provenance (with an analytic negative control),
distinct UNMEASURABLE/VIOLATED rendering, no reference to the deleted
synthetic generator, and no surviving hard-coded synthetic values.

## Integration notes (gateway/API shape expected)

When the gateway lands, it should serve the same five view shapes over HTTP
(application product views → UI contracts); Studio will swap `fixtures.ts` for
typed fetch calls against those endpoints. No React→Python imports, ever. The
validator stays as the payload gate for gateway responses.
