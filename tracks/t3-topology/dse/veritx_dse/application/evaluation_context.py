"""The canonical evaluation context — the fixed input boundary.

Rationale: docs/decisions/modules/application.md
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from veritx_dse.application.fabric_compiler import Compilation
from veritx_dse.workload.intent_lowering import LoweredWorkload


class EvaluationContextError(ValueError):
    """A canonical evaluation context could not be established."""


@dataclass(frozen=True)
class CanonicalEvaluationContext:
    """Everything an adapter may evaluate against — nothing more.

Rationale: docs/decisions/modules/application.md
    """

    request: Any
    compilation: Compilation
    lowered_workload: LoweredWorkload
    workload: Any
    bundle: Any

    @property
    def design_hash(self) -> str:
        return self.request.design_hash()

    @property
    def workload_id(self) -> str:
        return self.workload.workload_id()

    @property
    def unified_traffic_class(self) -> str | None:
        """Single class when the lowering is single-class, else None."""
        return self.lowered_workload.unified_traffic_class


def build_evaluation_context(compilation: Compilation) -> (
        CanonicalEvaluationContext):
    """Establish the canonical context for one PASSing compilation.

Rationale: docs/decisions/modules/application.md
    """
    if not isinstance(compilation, Compilation):
        raise EvaluationContextError(
            f"build_evaluation_context takes a Compilation, got "
            f"{type(compilation).__name__}")
    if compilation.status != "COMPILED":
        raise EvaluationContextError(
            f"cannot build an evaluation context: compilation is "
            f"{compilation.status}: {compilation.error}")
    certificate = compilation.certificate
    if certificate is None or getattr(certificate, "overall", None) != "PASS":
        raise EvaluationContextError(
            "cannot build an evaluation context: the compilation "
            "certificate is not PASS — a failed proof is not a fabric")

    from veritx_dse.workload.intent_lowering import lower_compile_workload
    lowered = lower_compile_workload(compilation.request)
    if lowered.design_hash != compilation.request.design_hash():
        raise EvaluationContextError(
            "the canonical lowering does not bind back to this design: "
            f"lowered from {lowered.design_hash!r}, compilation carries "
            f"{compilation.request.design_hash()!r}")

    bundle = compilation.bundle
    if bundle is None:
        raise EvaluationContextError(
            "cannot build an evaluation context: COMPILED compilation "
            "carries no bundle")

    return CanonicalEvaluationContext(
        request=compilation.request, compilation=compilation,
        lowered_workload=lowered, workload=lowered.graph, bundle=bundle)


__all__ = [
    "CanonicalEvaluationContext", "EvaluationContextError",
    "build_evaluation_context",
]
