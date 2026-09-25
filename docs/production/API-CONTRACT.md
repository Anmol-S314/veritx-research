# VERITX API / CLI Contract (P5)

The product surface is a set of verbs over content-addressed artifacts.
This documents what exists at the release candidate and what P5 owes; it is
not yet frozen.

## Verbs that exist

| verb | purpose | result |
|------|---------|--------|
| `veritx compile` | intent → resolved fabric bundle | `CompileResult` (JSON), artifact hashes |
| `veritx evaluate booksim` / `anynet` / `astra` | run a qualified backend over a prepared input | `EvaluationResult` + `ScientificBackendEvidence` |
| `veritx optimize` | guided candidate search; `optimize_certified` produces `CERTIFIED_PRODUCT` | `OptimizationResult` (records, Pareto, selection) |
| `veritx serve` | canonical LLM serving simulation over the fabric | `ServingResult` |
| `veritx certify flow` / `rtl` / `full` | obligations + verdicts | `VerificationResult` / certificate |
| `veritx run` / `sweep` / `compare` / `pareto` / `diff` | experiment orchestration | `Result` |
| `veritx runs` / `results` / `status` / `report` | inspection | read-only |

## Refusal semantics

- A typed semantic refusal is an outcome (`UNSUPPORTED`, `INVALID`,
  `INFEASIBLE`), never an exception and never `PASS`.
- A programmer fault (`ValueError`/`TypeError`/`AttributeError`/`RuntimeError`/
  `NameError` in trusted internal code) propagates and aborts; it is never
  laundered into a design verdict (`SemanticError` taxonomy, C1.2).
- A certified result is produced only by `Optimizer.optimize_certified`,
  only from product-controlled metric registry, only with a pinned producer
  and observed route (C1.3/C1.4).

## Evidence contract (every important number)

Any metric surfaced by the product must be able to answer "why can I trust
this?" from persisted evidence:

```text
backend          (embedded BookSim / ASTRA / RTL / Ramulator)
producer         (binary sha256, size, source revision, dirty=false)
recipe           (booksim2-fork/v1, exact for the certified profile)
fabric identity  (resolved_fabric_hash)
workload identity(physical_traffic_id / message_artifact_id)
evidence id      (content-addressed)
qualification    (profile + fidelity + route observation)
limitations      (first-hop only; ASTRA numerics NOT_ESTABLISHED)
```

## Owed for the freeze (P5)

- Versioned machine-readable result schemas with a published
  `SCHEMA-COMPATIBILITY` entry each (`CompileResult`, `VerificationResult`,
  `EvaluationResult`, `OptimizationResult`, `ServingResult`, `RunBundle`).
- `veritx verify-run <bundle>` and `veritx reproduce <bundle>` (C3).
- A stable exit-code contract for refusals vs failures.
- Golden request/response fixtures for each verb.
