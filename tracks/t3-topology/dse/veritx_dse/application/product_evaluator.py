"""veritx_dse.application.product_evaluator — ONE product evaluation.

Composes the canonical authorities without duplicating any science:

    FabricCompiler.compile            (application/fabric_compiler.py)
      -> Compilation (bundle + certificate)

    lower_compile_workload            (workload/intent_lowering.py)
      -> the request's exact WorkloadGraph

    FabricEvaluator.evaluate          (application/fabric_evaluator.py)
      -> EvaluationOutcome (authenticated, verified performance)

    RequirementEvaluator.evaluate     (application/requirements.py)
      -> RequirementReport (typed verdicts, no invented metrics)

This module owns *sequencing only*. It derives no route, counts no packet,
decides no verdict and invents no metric. It exists so the gateway, the
Studio fixture generator and any future product surface all call the same
four-step chain instead of re-implementing it.
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

    ``outcome`` is None only when the design never compiled. ``status``
    mirrors the canonical evaluator status (EVALUATED,
    BACKEND_UNAVAILABLE, UNSUPPORTED, FAILED) or the compilation status
    (INVALID, UNSUPPORTED) for a design that could not be compiled.
    ``requirement_report`` exists only for an EVALUATED outcome.
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
    """Compile then evaluate one v3 request through the canonical chain."""
    if not isinstance(request, CompileRequestV3):
        raise TypeError(
            f"evaluate_product takes a CompileRequestV3, got "
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
