"""veritx_dse.application.fabric_evaluator — compiled fabric → performance.

The product evaluation service (P1B.4+). It owns NO backend semantics:
it sequences the sealed authorities the P0 science already proved —

    Compilation (COMPILED + PASS certificate)
      → WorkloadGraph (product lowerer, caller-supplied)
      → LogicalMessageArtifactV2 (DEFAULT class)
      → PhysicalTrafficArtifactV2 (bound to the compiled bundle)
      → assert_projection_ready (admission + conservation + projection)
      → prepare_physical_traffic_booksim (sealed backend input)

``prepare()`` is pure and spawn-free (no binary needed); ``evaluate()``
resolves the qualified producer, executes, authenticates evidence, and
binds the network PerformanceResult. A missing backend is the explicit
outcome BACKEND_UNAVAILABLE — never FileNotFoundError, never a
fabricated zero-latency result.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .errors import ControlPlaneError, ErrorCode

EVALUATION_STATUSES = ("EVALUATED", "BACKEND_UNAVAILABLE", "UNSUPPORTED",
                       "FAILED")

SUPPORTED_EVALUATION_BACKENDS = ("booksim",)


@dataclass(frozen=True)
class EvaluationOptions:
    """How to evaluate. ``backend="booksim"`` is the only supported
    producer name; ``seed=None`` selects the certified pinned-default
    seed (never an invented number); ``timeout_s`` is budget-checked
    against the capability policy at evaluate time."""

    backend: str = "booksim"
    timeout_s: int = 600
    require_quiescence: bool = True
    seed: int | None = None
    repo_root: str | Path | None = None
    binary: str | Path | None = None


@dataclass(frozen=True)
class PreparedEvaluation:
    """In-memory evaluation carrier (never a persisted authority).

    ``summary`` is the projection summary (packet/flit expectations)
    that quiescence later proves the backend drained exactly.
    """

    compilation: Any
    workload_graph: Any
    logical: Any
    traffic: Any
    prepared: Any
    summary: dict[str, Any]


class FabricEvaluator:
    """Product evaluation over verified compilations."""

    def prepare(self, compilation: Any, workload: Any,
                options: EvaluationOptions | None = None) -> PreparedEvaluation:
        """Lower the compiled fabric to a sealed backend input.

        Requires a COMPILED compilation with a PASS certificate.
        Semantic failures (unadmitted classes, conservation breaks)
        propagate with their own types for evaluate() to map onto
        UNSUPPORTED — prepare() never invents an outcome.
        """
        from veritx_dse.backend.projection import (
            prepare_physical_traffic_booksim,
        )
        from veritx_dse.backend.projection import assert_projection_ready
        from veritx_dse.workload.messages import LogicalMessageArtifactV2
        from veritx_dse.workload.traffic import PhysicalTrafficArtifactV2

        opts = options or EvaluationOptions()
        if opts.backend not in SUPPORTED_EVALUATION_BACKENDS:
            raise ControlPlaneError(
                ErrorCode.UNSUPPORTED_SEMANTICS,
                f"evaluation backend {opts.backend!r} is not supported "
                f"(supported: {SUPPORTED_EVALUATION_BACKENDS})",
                operation="evaluate")
        if compilation.status != "COMPILED":
            raise ControlPlaneError(
                ErrorCode.INVALID_INTENT,
                f"cannot prepare an evaluation from a "
                f"{compilation.status} compilation "
                f"({compilation.error or 'no evidence'})",
                operation="evaluate")
        if compilation.certificate is None or \
                compilation.certificate.overall != "PASS":
            raise ControlPlaneError(
                ErrorCode.INVALID_INTENT,
                "cannot prepare an evaluation without a PASS fabric "
                "certificate",
                operation="evaluate")
        logical = LogicalMessageArtifactV2(
            graph=workload, traffic_class="DEFAULT")
        traffic = PhysicalTrafficArtifactV2(
            logical=logical, bundle=compilation.bundle)
        summary = assert_projection_ready(traffic)
        prepared, _ = prepare_physical_traffic_booksim(
            traffic, seed=opts.seed)
        return PreparedEvaluation(
            compilation=compilation, workload_graph=workload,
            logical=logical, traffic=traffic, prepared=prepared,
            summary=summary)


__all__ = [
    "EVALUATION_STATUSES", "SUPPORTED_EVALUATION_BACKENDS",
    "EvaluationOptions", "FabricEvaluator", "PreparedEvaluation",
]
