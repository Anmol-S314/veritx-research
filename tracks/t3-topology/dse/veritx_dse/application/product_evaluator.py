"""veritx_dse.application.product_evaluator — P1 integration orchestration.

One thin product path with NO semantics of its own:

    CompileRequest v3
      -> FabricCompiler.compile()            (P1A authority)
      -> lower_compile_workload()            (P1C authority)
      -> assert_traffic_classes_bound()      (pre-spawn gate)
      -> FabricEvaluator.evaluate()          (P1B authority)
      -> RequirementEvaluator.evaluate()     (P1C authority)

Traffic-class law (review Gate 2, binding): the class comes from the
lowered workload intent. Single unique class -> evaluated under that
class. Multiple classes -> typed UNSUPPORTED (no evaluator call — there
is nothing honest to evaluate until a per-operation message artifact
lands). There is deliberately NO traffic_class knob here: eval-time
relabeling (e.g. best_effort measured as latency_critical) would forge
QoS evidence. P1B's EvaluationOptions.traffic_class remains for
isolation tests only.

Network clock: explicit caller modeling assumption (Hz, exact), passed
straight through. Default None -> honest cycles-only, no wall-time
claims. Nothing is guessed from the request here.
"""
from __future__ import annotations

from dataclasses import dataclass
from fractions import Fraction
from typing import Any

from veritx_dse.application.fabric_compiler import Compilation, FabricCompiler
from veritx_dse.application.fabric_evaluator import (
    EvaluationOptions,
    EvaluationOutcome,
    FabricEvaluator,
)
from veritx_dse.application.requirements import (
    RequirementEvaluator,
    report_passes,
)
from veritx_dse.model.compile_model import CompileRequestV3
from veritx_dse.workload.intent_lowering import (
    LoweredWorkload,
    assert_traffic_classes_bound,
    lower_compile_workload,
)


@dataclass(frozen=True)
class ProductEvaluation:
    """One orchestrated product run. A carrier, not an authority.

    status mirrors the furthest stage reached: the compilation status
    (COMPILED/INVALID/UNSUPPORTED) or the evaluation outcome status
    (EVALUATED/BACKEND_UNAVAILABLE/UNSUPPORTED/FAILED). requirements_pass
    is None until a verified PerformanceResult exists to judge.
    """

    request: CompileRequestV3
    compilation: Compilation
    lowered: LoweredWorkload | None
    outcome: EvaluationOutcome | None
    requirement_report: dict[str, Any] | None
    status: str
    requirements_pass: bool | None
    reason: str | None


def evaluate_product(
    request: CompileRequestV3,
    *,
    backend: str = "BOOKSIM_STANDALONE",
    network_clock_hz: int | Fraction | None = None,
    timeout_s: int = 120,
    require_quiescence: bool = True,
    run_dir: Any = None,
    binary: Any = None,
    repo_root: Any = None,
    seed: int | None = None,
) -> ProductEvaluation:
    """Run the full v3 product chain. Orchestration only."""
    if not isinstance(request, CompileRequestV3):
        raise TypeError(
            f"evaluate_product takes a CompileRequestV3, got "
            f"{type(request).__name__}")
    compilation = FabricCompiler().compile(request)
    if compilation.status != "COMPILED":
        return ProductEvaluation(
            request=request, compilation=compilation, lowered=None,
            outcome=None, requirement_report=None,
            status=compilation.status, requirements_pass=None,
            reason=compilation.error)
    bundle = compilation.bundle
    lowered = lower_compile_workload(request)
    assert_traffic_classes_bound(lowered, bundle.vc_assignment)
    unified = lowered.unified_traffic_class
    if unified is None:
        return ProductEvaluation(
            request=request, compilation=compilation, lowered=lowered,
            outcome=EvaluationOutcome(
                status="UNSUPPORTED",
                design_hash=request.design_hash(),
                resolved_fabric_hash=(
                    bundle.resolved_fabric.resolved_fabric_hash()),
                workload_id=lowered.graph.workload_id(),
                reason=(
                    f"lowering spans traffic classes "
                    f"{list(lowered.classes)}: no single-class message "
                    f"artifact can represent per-operation classes — "
                    f"UNSUPPORTED until a versioned per-operation "
                    f"message artifact lands")),
            requirement_report=None, status="UNSUPPORTED",
            requirements_pass=None,
            reason="multi-class workload refused before backend work")
    outcome = FabricEvaluator().evaluate(
        compilation, lowered.graph,
        EvaluationOptions(
            backend=backend, traffic_class=unified,
            network_clock_hz=network_clock_hz, timeout_s=timeout_s,
            require_quiescence=require_quiescence, run_dir=run_dir,
            binary=binary, repo_root=repo_root, seed=seed))
    if outcome.status != "EVALUATED" or \
            outcome.performance_result is None:
        return ProductEvaluation(
            request=request, compilation=compilation, lowered=lowered,
            outcome=outcome, requirement_report=None,
            status=outcome.status, requirements_pass=None,
            reason=outcome.reason)
    report = RequirementEvaluator.evaluate(
        request, lowered.graph, outcome.performance_result)
    return ProductEvaluation(
        request=request, compilation=compilation, lowered=lowered,
        outcome=outcome, requirement_report=report,
        status=outcome.status, requirements_pass=report_passes(report),
        reason=None if report_passes(report)
        else "binding requirements not satisfied")


__all__ = ["ProductEvaluation", "evaluate_product"]
