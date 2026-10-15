# V4 optimization recovery — 2026-10-12

## Failure and bounded repair

The Qwen study `p-72d52e15419d`, revision `p-72d52e15419d-r03`, was refused by job `job-8e6f82a9ec3f` with `UNSUPPORTED_SEMANTICS: certified optimization requires a v3 design request`.

The product optimization boundary had a stale V3-only check despite the real candidate evaluator already supporting V4. Candidate patching also attempted to replace V4's read-only legacy `noc_config` view.

- `veritx_dse/product/service.py`: accept V4 alongside V3 at that boundary. V2 and V5 are not newly admitted.
- `veritx_dse/optimization/candidate.py`: patch V4's actual `noc_controls` and typed `topology` directly. Preserve other request fields, extended router controls, compute, workload, agents, address map, physical context and provenance.
- Scalar radix/concentration edits retain the family's other authored parameters and validation. Mesh/concentrated-mesh/torus family switches retain the explicit side length and concentration. A scalar family name cannot supply missing construction parameters or replace an explicit graph; those patches refuse instead of inventing topology. Control-only patches preserve explicit graphs.
- No conversion to V3, evidence-admission bypass, producer replacement or draft adoption was used for recovery.

## Regression evidence

`tests/test_optimization_v4.py` covers canonical preservation, typed family dimensions, GEC partition-law refusal, invalid/LOCKED knobs, explicit-graph preservation, product submission, unavailable-backend taxonomy, candidate adoption and compilation. Its scripted adapter tests establish orchestration only, not simulator measurements.

The focused optimizer/capability/identity/CLI/product/gateway selection completed: **213 passed**. Pytest emitted the existing unknown `timeout` configuration warning.

Cache-backed artifacts: `/home/datavex/.cache/veritx-optimize-v4-20261012/`, including `red.log`, `final-regression.log`, direct native study views, live job/study JSON, and draft-preservation proof.

## Live execution proof

Direct native execution was followed by an idle gateway restart, preserving the command, environment, working directory and storage. There were zero active jobs across the stored job records. Replacement gateway PID: `1866914`.

HTTP submissions against the actual Qwen revision completed with all three candidates `EVALUATED`:

| Link width (bits) | BookSim network completion (cycles) | ASTRA system makespan (cycles) |
| --- | ---: | ---: |
| 32 | 9,697 | 16,577 |
| 64 | 3,722 | 14,401 |
| 128 | 1,643 | 13,313 |

- Network job: `job-53b0fad304c5`; study: `opt-a4509e45d580`.
- System job: `job-2e1485ee1463`; study: `opt-86bc16cf18f1`.
- Each study selected its 128-bit candidate under its own MIN objective.
- Canonical draft request, V4 generation and active revision remained unchanged. A selected candidate was **not** automatically adopted.

These are distinct simulation objectives, not interchangeable axes or measured hardware timings. Existing producer qualification, calibration, HEAD ASTRA integration and broader release/review limitations remain unchanged.

## Capability-impact reconciliation

The successful Qwen runs exposed a stale `WORK-002` denial in the shared capability registry. It now describes **declared static MoE schedule — WIRED**, with projection, execution, qualification and evidence conditional on explicit valid collective intents and the selected backend's per-request profile checks. `WORK-005` no longer incorrectly denies multi-class collective execution. The Qwen preset remains Expert-only; its reason no longer says static lowering is absent.

Full expert dispatch/combine semantics remain unavailable under `WORK-009`. Model-family and EP declarations do not infer expert selection, token routing, load imbalance or dispatch/combine payloads. Serving execution remains a separate capability, not established by the static schedule runs. No backend admission checks or Guided-safe envelopes were relaxed.

Focused registry/design/preset/origin/optimizer proof: **195 passed**. `scripts/check_intent_ontology.py` passed (356 rows, 101 declared fields covered). The idle gateway was reloaded as PID `1867830`; the live Qwen Design API now returns the corrected WIRED/CONDITIONAL row with unchanged draft identity. Evidence: `/home/datavex/.cache/veritx-moe-capability-20261012/` (`red.log`, `regression.log`, `ontology.log`, `design-before.json`, `design-after.json`, `restart-proof.json`).
