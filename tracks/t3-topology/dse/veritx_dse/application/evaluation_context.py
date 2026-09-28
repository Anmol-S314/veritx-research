"""The canonical evaluation context — the fixed input boundary.

Every backend adapter receives ONE canonical context, never a raw
compilation: the request is lowered exactly once here, the workload
identity is bound back to the design by re-derivation, and the bundle
is the compilation's own. Adapters never call arbitrary lowerers
independently, so no backend can silently evaluate against a different
semantic graph than another.

    CompileRequest → FabricCompiler → Compilation
        → CanonicalEvaluationContext → planner / adapters
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

    ``request``/``compilation`` bind provenance; ``lowered_workload`` is
    the one canonical lowering; ``workload`` is its graph (the identity
    adapters receive); ``bundle`` is the compiled fabric. Constructed
    ONLY through :func:`build_evaluation_context`, which enforces the
    PASS/identity laws.
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

    Laws (each a typed refusal, never a silent downgrade):
      * the compilation is COMPILED — a failed proof is not a fabric;
      * the certificate is PASS — an unverified fabric is not evaluable;
      * the request is lowered EXACTLY once, here;
      * the graph's identity is bound back to this design by
        re-derivation — a transplanted workload is refused.
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

    # Lower EXACTLY once, here. Binding back to the design: the lowering
    # carries the design_hash it was derived from, and it must be THIS
    # compilation's request identity — a transplanted lowering is refused.
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
