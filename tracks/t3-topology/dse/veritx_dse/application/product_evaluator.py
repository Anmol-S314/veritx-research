"""veritx_dse.application.product_evaluator — ONE product evaluation.

Rationale: docs/decisions/modules/application.md
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from veritx_dse.application.fabric_compiler import Compilation, FabricCompiler
from veritx_dse.application.fabric_evaluator import (
    STANDALONE_BACKEND, EvaluationOptions, EvaluationOutcome, FabricEvaluator,
)
from veritx_dse.application.requirements import (
    RequirementEvaluator, report_passes,
)
from veritx_dse.model.compile_model import CompileRequestV3


@dataclass(frozen=True)
class ProductEvaluation:
    """One product evaluation attempt.

Rationale: docs/decisions/modules/application.md
    """

    status: str
    compilation: Compilation
    outcome: EvaluationOutcome | None
    requirement_report: dict[str, Any] | None
    requirements_pass: bool | None
    reason: str | None = None

    @property
    def run_dir(self) -> str | None:
        return None if self.outcome is None else self.outcome.run_dir


def evaluate_product(
    request: CompileRequestV3,
    *,
    binary: str | Path | None,
    network_clock_hz: float | None = None,
    timeout_s: int = 120,
    run_dir: str | Path | None = None,
    repo_root: str | Path | None = None,
    seed: int | None = None,
) -> ProductEvaluation:
    """Compile then evaluate one v3/v4 request through the canonical chain."""
    from veritx_dse.model.generation import is_v4_request
    if not isinstance(request, CompileRequestV3) \
            and not is_v4_request(request):
        raise TypeError(
            f"evaluate_product takes a CompileRequestV3 or v4, got "
            f"{type(request).__name__}")

    compilation = FabricCompiler().compile(request)
    if compilation.status != "COMPILED":
        return ProductEvaluation(
            status=compilation.status, compilation=compilation, outcome=None,
            requirement_report=None, requirements_pass=None,
            reason=compilation.error)

    from veritx_dse.workload.intent_lowering import lower_compile_workload
    lowered = lower_compile_workload(request)
    workload = lowered.graph
    classes = {cls for _op, cls in lowered.traffic_class_by_operation}
    traffic_class = next(iter(classes)) if len(classes) == 1 else "DEFAULT"

    options = EvaluationOptions(
        backend=STANDALONE_BACKEND,
        traffic_class=traffic_class,
        timeout_s=timeout_s,
        network_clock_hz=network_clock_hz,
        seed=seed,
        run_dir=run_dir,
        repo_root=repo_root,
        binary=binary,
    )
    outcome = FabricEvaluator().evaluate(compilation, workload, options)
    if outcome.status != "EVALUATED":
        return ProductEvaluation(
            status=outcome.status, compilation=compilation, outcome=outcome,
            requirement_report=None, requirements_pass=None,
            reason=outcome.reason)

    report = RequirementEvaluator.evaluate(
        request, workload, outcome.performance_result)
    return ProductEvaluation(
        status="EVALUATED", compilation=compilation, outcome=outcome,
        requirement_report=report, requirements_pass=report_passes(report),
        reason=None)


__all__ = ["ProductEvaluation", "evaluate_product"]
