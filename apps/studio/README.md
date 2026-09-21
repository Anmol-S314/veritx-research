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
  scripts/          validate_fixtures.py (schema + linkage + realizability gate)
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
| `compiled-mesh.json` | COMPILED, 10/10 PASS, evaluation NOT_RUN (5×5 mesh, 78 agents) |
| `invalid-design.json` | UNSUPPORTED typed refusal (radix 3 seats 36 < 78 agents; no bundle) |
| `backend-unavailable.json` | COMPILED + BACKEND_UNAVAILABLE (reason, no metrics) |
| `evaluated-design.json` | EVALUATED (aggregate window, present metrics, producer, fidelity warning) + RequirementReport |
| `optimization-study.json` | Study over link_width × concentration: 6 candidates, Pareto set, selected + rationale |

Every fixture must pass `npm run validate` (Draft 2020-12 schemas + cross-view
hash linkage: design_hash consistency, performance_result_id binding,
EVALUATED completeness, no-metrics-on-refusal).

## Realizability gate (fixture semantics, not just shape)

The frozen schemas accept broad strings, so schema validity alone would admit
impossible products. `scripts/validate_fixtures.py` therefore also checks that
semantic values come from real engine authorities (no engine import — values
are mirrored and documented):

- `model_family` ∈ ModelFamily, `kind` ∈ AgentKind, `qos_class` ∈ QoSClass,
  `topology_family` ∈ TopologyFamily, `serving_mode` ∈ ServingMode,
  `arbitration` ∈ router-behavior allocator aliases.
- `rcu_enabled: true` with `status: COMPILED` is rejected — the compiler
  refuses RCU intent as UNSUPPORTED.
- COMPILED designs must satisfy the materialization sizing rule
  (`radix² × concentration ≥ agent count`), or the compiler would refuse them.

Like the fixtures themselves, these values were verified against the real
compiler (not assumed): the projected request — canonical P1A dependencies
(`prefill-attn → prefill-ffn` blocking) and an `allreduce` collective, which
the frozen DesignView cannot carry — COMPILES with radix 5 / concentration 4 /
link_width 128 over 78 agents, and every obligation evidence value in
`compiled-mesh.json` (25 routers, 80 channels, 600 route entries, 64
placements, vc_count 1, CDG node/edge counts) was read from that run. The
radix-3 variant is refused UNSUPPORTED with the exact engine message shown in
`invalid-design.json`.

Note: INVALID means a certificate failed its proof (reachable when persisted
artifacts are reopened/tampered, per the P1 contract). No fixture claims it
pre-integration — the negative fixture is the typed UNSUPPORTED refusal the
engine actually produces for a bad GUIDED config. The UI styles all of
PASS/FAIL/UNSUPPORTED/INVALID distinctly.

## Honesty rules enforced in UI

- LOCKED properties (routing DOR_XY, VC count, turn restrictions) render
  read-only with 🔒 Derived badges; they live in `locked_derived`, never in
  the editable `noc_guided` block.
- Evaluation metrics render **only when present**; absent metrics are omitted,
  never zero-filled. Non-EVALUATED outcomes show reason + explicit no-metrics note.
- Requirement verdicts stay honest: the bandwidth floor is UNMEASURABLE in the
  evaluated fixture (cycles-only aggregate window has no valid clock for Gbps).
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
