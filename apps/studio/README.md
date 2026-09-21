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
  Python engine modules.**

## Layout

```
apps/studio/
  fixtures/         five *.json fixtures + generate_fixtures.py (deterministic)
  scripts/          validate_fixtures.py (schema + linkage gate)
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
npm run validate   # validate all fixtures against contracts/srota/v1
npm run gen-fixtures  # regenerate fixtures deterministically (then validate)
```

## Fixtures

| File | State demonstrated |
|---|---|
| `compiled-mesh.json` | COMPILED, 10/10 PASS, evaluation NOT_RUN |
| `invalid-design.json` | INVALID (2 FAIL obligations, typed refusal, no bundle) |
| `backend-unavailable.json` | COMPILED + BACKEND_UNAVAILABLE (reason, no metrics) |
| `evaluated-design.json` | EVALUATED (aggregate window, present metrics, producer, fidelity warning) + RequirementReport |
| `optimization-study.json` | Study over link_width × concentration: 5 candidates, Pareto set, selected + rationale |

Every fixture must pass `npm run validate` (Draft 2020-12 schemas + cross-view
hash linkage: design_hash consistency, performance_result_id binding,
EVALUATED completeness, no-metrics-on-refusal).

## Honesty rules enforced in UI

- LOCKED properties (routing DOR_XY, VC count, turn restrictions) render
  read-only with 🔒 Derived badges; they live in `locked_derived`, never in
  the editable `noc_guided` block.
- Evaluation metrics render **only when present**; absent metrics are omitted,
  never zero-filled. Non-EVALUATED outcomes show reason + explicit no-metrics note.
- Canvas overlays (routing / VC class / traffic class / utilization) are
  **extension points with stated data needs**, never fabricated colors.
- Design edits are local-only and flagged dirty ("recompile required"); fixture
  mode cannot recompile. "Request evaluation" on a NOT_RUN design demonstrates
  RUNNING, then resolves to an honest refused run (no metrics).
- Generate section is a disabled indicator (P3 deferred). No export buttons —
  no fake export functionality.
- E4 Dependencies: the frozen contract carries no DependencyGraph view, so the
  panel derives admission ordering from binding E2 requirements and says so.

## Integration notes (gateway/API shape expected)

When the gateway lands, it should serve the same five view shapes over HTTP
(application product views → UI contracts); Studio will swap `fixtures.ts` for
typed fetch calls against those endpoints. No React→Python imports, ever. The
validator stays as the payload gate for gateway responses.
