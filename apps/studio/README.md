# Srota Studio (P4)

Fixture-backed product UI for the Srota Fabric Compiler program. Runs **entirely
from contract-validated fixtures** — no engine connectivity yet.

- Stack: **Vite + React + TypeScript** (typed, zero runtime UI dependencies;
  SVG canvas hand-rolled). Chosen for type safety against the contract views,
  fast iteration, and no extra supply-chain weight.
- Tone: semiconductor engineering tool — dense tables, monospace identities,
  flat dark/light themes. No gradients, no gloss.
- Consumes only the frozen views in `contracts/srota/v1/` (Design,
  Compilation, Evaluation, RequirementReport, OptimizationStudy). **Never imports
  Python engine modules** (the validator's engine mode deliberately does, to
  prove the fixtures are engine-realizable; the UI never does).

## Layout

```
apps/studio/
  fixtures/         five engine-generated *.json fixtures (no in-tree generator)
  scripts/          validate_fixtures.py (schema + linkage + engine realizability)
  src/
    types.ts        contract-mirror TS types
    fixtures.ts     fixture loading (validated JSON only)
    App.tsx         shell: sections + fixture switcher + theme
    components/
      DesignEditor.tsx   E1–E5 editor (LOCKED read-only, GUIDED/FREE editable)
      FabricCanvas.tsx   SVG structure canvas + overlay extension points
      VerifyView.tsx     10 P1A obligations, click for evidence
      EvaluateView.tsx   NOT_RUN / RUNNING / BACKEND_UNAVAILABLE / EVALUATED /
                         FAILED / UNSUPPORTED states; present-metrics-only
      OptimizeView.tsx   candidates, verdicts, Pareto frontier, comparison
```

## Commands

```bash
npm install
npm run dev        # local dev server
npm run build      # typecheck + production build
npm run validate   # schema/linkage fast path (engine mode on when CI is set)
npm run gen-fixtures  # regenerate via the engine tool (BookSim required)

# Force/refuse the engine realizability check explicitly:
python3 scripts/validate_fixtures.py --engine       # regenerate + byte-compare
python3 scripts/validate_fixtures.py --skip-engine  # offline: fast path only
```

## Fixtures

| File | State demonstrated |
|---|---|
| `compiled-mesh.json` | COMPILED, 10/10 PASS, evaluation NOT_RUN (9×9 mesh, 72 agents) |
| `invalid-design.json` | UNSUPPORTED typed refusal (torus has no certified routing derivation; no bundle) |
| `backend-unavailable.json` | COMPILED + BACKEND_UNAVAILABLE (unidentifiable producer, reason, no metrics) |
| `evaluated-design.json` | EVALUATED (16161-cycle aggregate window, present metrics, producer, fidelity warning) + RequirementReport |
| `optimization-study.json` | Study over link_width {64,128}: 2 candidates, Pareto set, selected + rationale |

Every fixture must pass `npm run validate` (Draft 2020-12 schemas + cross-view
hash linkage: design_hash consistency, performance_result_id binding,
EVALUATED completeness, no-metrics-on-refusal) plus the engine realizability
gate below when the engine is available.

## Realizability gate (fixture semantics, not just shape)

The frozen schemas accept broad strings, so schema validity alone would admit
impossible products. `scripts/validate_fixtures.py` runs two gates:

**Fast path (always):** mirrored engine vocabularies + invariants —

- `model_family` ∈ ModelFamily, `kind` ∈ AgentKind, `qos_class` ∈ QoSClass,
  `topology_family` ∈ TopologyFamily, `serving_mode` ∈ ServingMode,
  `arbitration` ∈ router-behavior allocator aliases.
- `rcu_enabled: true` with `status: COMPILED` is rejected — the compiler
  refuses RCU intent as UNSUPPORTED.
- COMPILED designs must satisfy the materialization sizing rule
  (`radix² × concentration ≥ agent count`), or the compiler would refuse them.

**Engine mode** (default ON when `CI`/`GITHUB_ACTIONS` is set; `--engine`
forces it, `--skip-engine` opts out offline): the validator regenerates all
five fixtures with the engine tool
(`python3 -m veritx_dse.tools.generate_studio_fixtures`, from
`tracks/t3-topology/dse`) into a temp directory and compares them to the
committed fixtures. Every field must match except the documented
producer-bound volatile set: the BookSim producer digest
(`evaluation.backend_producer.producer_identity`), the raw evidence digest
(the persisted evidence artifact embeds its absolute run path), and the
performance-result ids derived from that evidence. If the engine or BookSim
binary is unavailable, engine mode **fails loudly**; it never passes on the
fast path alone.

The fixtures themselves are engine-originated, not mirrored: the design is
the `llama_dense_64tiles-v3` request (dense_transformer, tp 8, 64 compute
tiles + 8 HBM controllers), compiled by `FabricCompiler`;
`compiled-mesh.json` carries that live run's certificate (9×9 mesh → 81
routers, 288 directed channels, 6480 route entries, 8 placements, vc_count 1,
CDG 288 nodes / 508 edges, all 10 obligations PASS); `evaluated-design.json`
carries the live BookSim window (16161 cycles) and its RequirementReport. The
negative fixture is the engine's typed UNSUPPORTED refusal for a torus family
(P1A certifies MESH and CONCENTRATED_MESH DOR_XY only) — the exact engine
message is shown in `invalid-design.json`.

Note: INVALID means a certificate failed its proof (reachable when persisted
artifacts are reopened/tampered, per the P1 contract). No fixture claims it
pre-integration — the negative fixture is a typed UNSUPPORTED refusal. The UI
styles all of PASS/FAIL/UNSUPPORTED/INVALID distinctly.

## Honesty rules enforced in UI

- LOCKED properties (routing DOR_XY, VC count, turn restrictions) render
  read-only with 🔒 Derived badges; they live in `locked_derived`, never in
  the editable `noc_guided` block.
- Evaluation metrics render **only when present**; absent metrics are omitted,
  never zero-filled. Non-EVALUATED outcomes show reason + explicit no-metrics note.
- Requirement verdicts come from the engine's RequirementReport
  (SATISFIED / UNMEASURABLE / VIOLATED / NOT_APPLICABLE); the evaluated
  fixture's latency ceiling is SATISFIED by the measured 16161-cycle window
  and no fixture invents a Gbps authority the engine did not produce.
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

## Integration notes (gateway/API shape expected)

When the gateway lands, it should serve the same five view shapes over HTTP
(application product views → UI contracts); Studio will swap `fixtures.ts` for
typed fetch calls against those endpoints. No React→Python imports, ever. The
validator stays as the payload gate for gateway responses.
