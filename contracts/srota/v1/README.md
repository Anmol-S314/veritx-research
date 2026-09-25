# contracts/srota/v1 — frozen language-neutral product views

JSON Schemas (draft 2020-12) for the six Studio-facing views. Python
dataclasses remain the runtime authority; these schemas are the closed
interchange contract. Studio MUST validate fixtures and gateway payloads
against them and MUST NOT consume engine internals.

| View | Schema | Python authority |
|---|---|---|
| CompilationView | `compilation.view.schema.json` | `application/fabric_compiler.py::Compilation` + `verification/certificate.py` |
| DesignView | `design.view.schema.json` | `model/compile_model.py::CompileRequest` (+ derived LOCKED block) |
| TopologyView | `topology.view.schema.json` | `model/topology_artifact.py::TopologyArtifact` + `model/attachment.py::AgentAttachmentArtifact` |
| EvaluationView / EvaluationOutcome | `evaluation.view.schema.json` | `application/fabric_evaluator.py` (P1B) + `performance/result.py`, `backend/evidence.py` |
| RequirementReport | `requirement.report.schema.json` | `application/requirements.py` (P1C) |
| OptimizationStudyView | `optimization.study.view.schema.json` | `optimization/result.py` (P2) |

Conventions: `sha256:`-prefixed content identities; closed top-level
objects (`unevaluatedProperties: false` on views); enums frozen
(`COMPILED/INVALID/UNSUPPORTED`, `EVALUATED/BACKEND_UNAVAILABLE/
UNSUPPORTED/FAILED`, `SATISFIED/VIOLATED/UNMEASURABLE/NOT_APPLICABLE`).
`$id`: `https://veritx.dev/contracts/srota/v1/<name>`. Version: `1`.
