# contracts/srota/v2 — authoritative OptimizationStudyView

`optimization.study.view.schema.json` is the one authoritative v2 study
view (contract_version 2), emitted by
`optimization/result.py::OptimizationResult.to_study_view()` by default.

It intentionally separates three authorities that must never be merged:

| Authority | Fields | Question answered |
|---|---|---|
| Product requirements | `evaluation_ids.requirement_report_id`, `product_requirements` | Did the DESIGN satisfy the customer's requirements? |
| Optimization constraints | `constraint_verdicts` (SATISFIED/VIOLATED/UNMEASURABLE) | Did the CANDIDATE satisfy the study's hard constraints? |
| Measured objectives | `objective_values`, `objective_availability` (MEASURED/UNMEASURABLE) | Was each requested objective actually measured? |

`pareto_eligible` is the conjunction required for Pareto input
(evaluation succeeded AND the evaluation authority is
`certified-backend` AND binding product requirements pass AND every
requested objective measured+finite AND every hard constraint
SATISFIED); `pareto_member` implies it. `evaluation_authority`
(`certified-backend` | `analytic-fake` | null) is structural: analytic
fakes are development doubles and can never be eligible. Every row also
carries `compilation_status` (COMPILED/INVALID/UNSUPPORTED),
`evaluation_status` (EVALUATED/COMPILE_FAILED/INVALID/UNSUPPORTED/
BACKEND_UNAVAILABLE/FAILED) and `evaluation_reason` (the typed message,
null for a clean run), so a consumer renders refusals without inferring
them from missing metrics; a simulated run that fails a binding product
requirement stays EVALUATED with
`product_requirements.satisfied=false` and an `evaluation_reason`.

The definition block is lossless and identified: `definition_id`,
`objectives` as `{metric, direction}`, `constraints` as
`{metric, op, threshold}`, `method`, `selection`, `budget`, `seed` and
`domain`. The view top level exposes `optimization_result_id`, the bare
content digest of the bound `OptimizationResult` (the engine re-derives
it from definition identity + candidate rows + frontier).

The top level also carries `result_class` (R1):
`CERTIFIED_PRODUCT` comes only from `Optimizer.optimize_certified`,
which internally owns the real backend evaluator;
`ANALYTIC_RESEARCH` comes from `Optimizer.optimize_with_port` and can
never contain certified Pareto (`pareto_ids` is empty there).

The v1 file at `contracts/srota/v1/optimization.study.view.schema.json`
remains frozen for pinned callers. The v1 projector
(`to_study_view(contract_version=1)`) is LOSSY by design: it collapses
UNMEASURABLE to `false` and carries none of the v2 availability/product
fields; it never claims to preserve three-state semantics.

`$id`: `https://veritx.dev/contracts/srota/v2/<name>`. Version: `2`.
