"""veritx_dse.optimization.evaluators — evaluation ports (P2).

Rationale: docs/decisions/modules/optimization.md
"""
from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from typing import Any, Protocol

from veritx_dse.application.evaluation_question import EvaluationQuestion

class EvaluationError(ValueError):
    """Evaluator refusal (fail-closed)."""

AUTHORITY_CERTIFIED_BACKEND = "certified-backend"
AUTHORITY_ANALYTIC_FAKE = "analytic-fake"
EVALUATION_AUTHORITIES = (
    AUTHORITY_CERTIFIED_BACKEND, AUTHORITY_ANALYTIC_FAKE)

@dataclass(frozen=True)
class ObjectiveProvenance:
    """One measured objective value with its federation provenance.

Rationale: docs/decisions/modules/optimization.md
    """

    metric_key: str
    question: EvaluationQuestion
    backend_id: str | None
    model_fidelity: str | None
    qualification: str | None
    native_evidence_id: str | None
    unit: str | None
    value: float

    def __post_init__(self):
        if not isinstance(self.metric_key, str) or not self.metric_key:
            raise EvaluationError("objective provenance needs a metric key")
        if not isinstance(self.question, EvaluationQuestion):
            raise EvaluationError(
                f"objective provenance question must be an "
                f"EvaluationQuestion, got {self.question!r}")
        if self.backend_id is not None and (
                not isinstance(self.backend_id, str)
                or not self.backend_id):
            raise EvaluationError(
                "objective provenance backend_id must be a backend id "
                f"string or None, got {self.backend_id!r}")
        if isinstance(self.value, bool) or \
                not isinstance(self.value, (int, float)):
            raise EvaluationError(
                f"objective provenance value must be a real number, got "
                f"{self.value!r}")
        import math
        if not math.isfinite(float(self.value)):
            raise EvaluationError(
                "objective provenance value must be finite")
        object.__setattr__(self, "value", float(self.value))

    def to_dict(self) -> dict[str, Any]:
        return {
            "metric_key": self.metric_key,
            "question": self.question.value,
            "backend_id": self.backend_id,
            "model_fidelity": self.model_fidelity,
            "qualification": self.qualification,
            "native_evidence_id": self.native_evidence_id,
            "unit": self.unit,
            "value": self.value,
        }

@dataclass(frozen=True)
class CandidateEvaluation:
    """One candidate's evaluation outcome through a port.

Rationale: docs/decisions/modules/optimization.md
    """
    candidate_id: str
    design_hash: str
    status: str
    objective_values: dict[str, float]
    locked_consequences: dict[str, Any]
    compilation_status: str = "COMPILED"
    error: str | None = None
    performance_result_id: str | None = None
    requirement_report: dict[str, Any] | None = None
    requirement_report_id: str | None = None
    evaluation_authority: str | None = None
    workload: Any = None
    verified_performance_result: Any = None
    authenticated_proof: Any = None
    objective_provenance: dict[str, Any] = field(default_factory=dict)
    objective_unmeasured_reasons: dict[str, str] = field(
        default_factory=dict)
    federated_analyses: tuple[Any, ...] = ()

class CandidateEvaluationPort(Protocol):
    """What Optimizer.optimize needs from any evaluator (fake or real)."""

    def evaluate(self, candidate: Any) -> CandidateEvaluation:
        ...

def _jitter(candidate_id: str, metric: str, scale: float = 0.6) -> float:
    """Tiny deterministic content-hash jitter (keeps the fake honest).

    Pure function of (candidate_id, metric): proves evaluations bind to
    candidate identity without dominating the analytic signal.
    """
    h = hashlib.sha256(f"{candidate_id}\0{metric}".encode()).hexdigest()
    return (int(h[:8], 16) % 7) * 0.1 * scale

def fake_objectives(request: Any) -> dict[str, float]:
    """Deterministic analytic objectives as a pure function of request.

Rationale: docs/decisions/modules/optimization.md
    """
    noc = request.noc_config
    lw = noc.link_width if noc.link_width is not None else 32
    conc = noc.concentration if noc.concentration is not None else 1
    radix = noc.radix if noc.radix is not None else 4
    rcu = bool(noc.rcu_enabled)
    topo = noc.topology_family.value if noc.topology_family is not None else "mesh"
    topo_bias = {"mesh": 0.0, "concentrated_mesh": 12.0, "torus": 25.0,
                 "gec": 40.0, "fat_tree": 40.0}.get(topo, 15.0)
    latency = (600.0 * (32.0 / float(lw)) + 25.0 * float(conc)
               - (40.0 if rcu else 0.0) + topo_bias
               + 4.0 * (4.0 / float(radix)))
    area = (80.0 * (float(lw) / 32.0) + 30.0 * float(conc)
            + 6.0 * float(radix) + (15.0 if rcu else 0.0))
    return {"latency": round(latency, 3), "area": round(area, 3)}

def locked_consequences_of(compilation: Any) -> dict[str, Any]:
    """Extract LOCKED consequences from a COMPILED compilation."""
    bundle = compilation.bundle
    vc = bundle.vc_assignment
    topo = bundle.topology
    route = bundle.router_route
    classes = sorted({str(rc) for _, rc in getattr(vc, "vc_to_routing_class", [])})
    family = getattr(topo, "family", "")
    family_name = getattr(family, "value", family)
    return {
        "routing_classes": classes,
        "vc_count": int(getattr(vc, "vc_count", 0)),
        "topology_family": str(family_name),
        "router_count": int(getattr(topo, "router_count", 0)),
        "route_hash": str(getattr(route, "artifact_hash", "")),
    }

class FakeDeterministicEvaluator:
    """Deterministic fake port: real compile + analytic objectives.

Rationale: docs/decisions/modules/optimization.md
    """

    def __init__(self, seed: int = 0):
        if type(seed) is not int:
            raise EvaluationError(f"seed must be int, got {seed!r}")
        self.seed = seed
        self.calls = 0

    def evaluate(self, candidate: Any) -> CandidateEvaluation:
        from veritx_dse.application.fabric_compiler import FabricCompiler
        self.calls += 1
        expected_hash = candidate.request.design_hash()
        comp = FabricCompiler().compile(candidate.request)
        if comp.status != "COMPILED":
            return CandidateEvaluation(
                candidate_id=candidate.candidate_id,
                design_hash=expected_hash,
                status=comp.status,
                objective_values={},
                locked_consequences={},
                compilation_status=comp.status,
                error=comp.error,
                performance_result_id=None,
                evaluation_authority=AUTHORITY_ANALYTIC_FAKE,
            )
        if comp.bundle is None:
            raise EvaluationError(
                "FabricCompiler returned COMPILED without a bundle — "
                "refusing to fabricate LOCKED consequences")
        locked = locked_consequences_of(comp)
        objectives = fake_objectives(candidate.request)
        for metric in list(objectives):
            objectives[metric] = round(
                objectives[metric] + _jitter(candidate.candidate_id, metric), 3)
        return CandidateEvaluation(
            candidate_id=candidate.candidate_id,
            design_hash=expected_hash,
            status="EVALUATED",
            objective_values=objectives,
            locked_consequences=locked,
            compilation_status="COMPILED",
            error=None,
            performance_result_id="fake:" + expected_hash[:16],
            evaluation_authority=AUTHORITY_ANALYTIC_FAKE,
        )

__all__ = [
    "AUTHORITY_ANALYTIC_FAKE", "AUTHORITY_CERTIFIED_BACKEND",
    "CandidateEvaluation", "CandidateEvaluationPort", "EVALUATION_AUTHORITIES",
    "EvaluationError", "FakeDeterministicEvaluator", "fake_objectives",
    "locked_consequences_of", "ObjectiveProvenance",
]
