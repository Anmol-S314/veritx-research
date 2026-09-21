"""veritx_dse.optimization.evaluators — evaluation ports (P2).

CandidateEvaluationPort protocol + deterministic fake evaluator for
development and tests. No dependency on P1B/P1C branches.

FUTURE REAL ADAPTER (at integration, no optimizer rewrites unless the
interface mismatches — P1 contract §7 step 3):

    candidate CompileRequest
      -> FabricCompiler().compile(request)          # LOCKED consequences
      -> P1C lower_compile_workload(request)        # WorkloadGraph (v3)
      -> P1B FabricEvaluator.evaluate(              # authenticated perf
             compilation, workload, options)
      -> P1C RequirementEvaluator.evaluate(         # RequirementReport
             request, workload, performance)
      -> CandidateEvaluation{objective_values from PerformanceResult,
                             constraint verdicts from RequirementReport}

The real adapter must supply, per candidate: the compilation status +
certificate, workload/message/traffic IDs, backend producer identity +
config/input hashes, raw evidence + stats digests, performance_result_id,
and per-requirement {verdict, required, measured} bindings. UNMEASURABLE
never passes. BACKEND_UNAVAILABLE/UNSUPPORTED/FAILED stay visible and
never enter the Pareto set.

The fake below compiles every candidate through the REAL FabricCompiler
(LOCKED routing/VC consequences proven, never set) and then scores
deterministic analytic objectives as a pure function of the candidate
request — the stand-in for (lower -> evaluate -> requirements) until
the real adapter lands.
"""
from __future__ import annotations

import hashlib
from dataclasses import dataclass
from typing import Any, Protocol


class EvaluationError(ValueError):
    """Evaluator refusal (fail-closed)."""


@dataclass(frozen=True)
class CandidateEvaluation:
    """One candidate's evaluation outcome through a port.

    Hash boundary: engine values are bare digests (design_hash is the
    bare CompileRequest identity); product views add any ``sha256:``
    prefix at the view boundary only (see result.to_study_view).

    ``requirement_report`` carries the real RequirementReport dict when
    the port produced one (compiled + backend-evaluated requests), so
    the optimizer can bind the report's identity instead of discarding
    it; None means no report exists (never an empty stand-in).
    ``requirement_report_id`` is that report's canonical
    ``report_identity`` (bare digest); the optimizer re-derives it from
    the carried report and refuses a mismatch, so a transplanted report
    can never masquerade as this candidate's provenance.
    """
    candidate_id: str
    design_hash: str  # bare engine digest, never prefixed here
    status: str  # evaluation status: EVALUATED | COMPILE_FAILED | UNSUPPORTED | INVALID
    objective_values: dict[str, float]
    locked_consequences: dict[str, Any]
    compilation_status: str = "COMPILED"  # FabricCompiler verdict
    error: str | None = None
    performance_result_id: str | None = None
    requirement_report: dict[str, Any] | None = None
    requirement_report_id: str | None = None  # bare report_identity(report)


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

    latency (cycles, MIN): falls with link_width and rcu, rises with
        concentration (contention proxy).
    area (cost units, MIN): rises with link_width, concentration, radix
        and rcu. The two trade off over link_width, so the grid Pareto
        is non-trivial.
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

    Deterministic: same candidate request -> bit-identical evaluation
    (recompiles LOCKED consequences every call; analytic objectives are
    a pure function of the request plus content-hash jitter).
    Non-COMPILED candidates yield status COMPILE_FAILED/UNSUPPORTED
    with no objective values (excluded from Pareto, never silent).
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
            )
        assert comp.bundle is not None
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
        )


__all__ = [
    "CandidateEvaluation", "CandidateEvaluationPort", "EvaluationError",
    "FakeDeterministicEvaluator", "fake_objectives",
    "locked_consequences_of",
]
