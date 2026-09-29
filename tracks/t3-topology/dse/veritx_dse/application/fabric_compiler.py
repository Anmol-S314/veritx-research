"""veritx_dse.application.fabric_compiler — the product compiler (P1.4).

Rationale: docs/decisions/modules/application.md
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from veritx_dse.model.compile_model import CompileRequest, CompileRequestV3

from .errors import ControlPlaneError, ErrorCode


STAGES = (
    "INVENTORY", "MAPPING", "TOPOLOGY", "ATTACHMENT", "ROUTING",
    "RESOLVED_ROUTE", "VC_ASSIGNMENT", "COMPOSE", "BUNDLE",
)


@dataclass(frozen=True)
class StagedDerivation:
    """Canonical artifacts produced before a later stage refused.

Rationale: docs/decisions/modules/application.md
    """

    stopped_at_stage: str
    produced_stages: tuple[str, ...]
    inventory: Any = None
    mapping: Any = None
    topology: Any = None
    attachment: Any = None
    view: Any = None

    def has(self, stage: str) -> bool:
        return stage in self.produced_stages


@dataclass(frozen=True)
class Compilation:
    """In-memory compile outcome (not a persisted semantic artifact).

Rationale: docs/decisions/modules/application.md
    """

    status: str  # COMPILED, INVALID, or UNSUPPORTED
    request: CompileRequest | CompileRequestV3
    bundle: Any | None
    certificate: Any | None
    error: str | None
    #: The stage that refused, when the refusal was a stage refusal.
    stopped_at_stage: str | None = None
    #: Upstream artifacts that survived the refusal.
    staged: StagedDerivation | None = None
    adaptive: Any = None


    def __post_init__(self) -> None:
        if self.status not in ("COMPILED", "INVALID", "UNSUPPORTED"):
            raise ControlPlaneError(
                ErrorCode.INTERNAL_ERROR,
                f"unknown compilation status {self.status!r}",
                operation="compile")
        if self.status == "COMPILED" and (
                self.bundle is None or self.certificate is None):
            raise ControlPlaneError(
                ErrorCode.INTERNAL_ERROR,
                "COMPILED without bundle + certificate",
                operation="compile")
        if self.status != "COMPILED" and self.bundle is not None:
            raise ControlPlaneError(
                ErrorCode.INTERNAL_ERROR,
                f"{self.status} must not present a bundle",
                operation="compile")


class FabricCompiler:
    """Deterministic intent → verified fabric (P1A slice)."""

    def compile(self, request: CompileRequest | CompileRequestV3,
                routing_policy: Any = None) -> Compilation:
        """Compile one request: bundle, then certificate, then verdict.

Rationale: docs/decisions/modules/application.md
        """
        if routing_policy is not None:
            from veritx_dse.model.routing_policy import (  # noqa: PLC0415
                RoutingPolicyDefinition,
            )
            if not isinstance(routing_policy, RoutingPolicyDefinition):
                raise TypeError(
                    f"routing_policy must be a RoutingPolicyDefinition, "
                    f"got {type(routing_policy).__name__} — routing "
                    f"stays LOCKED: no raw routing_function string")
            if not isinstance(request, CompileRequestV3) and not (
                    getattr(request, "schema_version", None) == 4
                    and hasattr(request, "noc_controls")):
                raise ControlPlaneError(
                    ErrorCode.UNSUPPORTED_SEMANTICS,
                    "adaptive routing policies are carried on v3/v4 "
                    "Product requests only",
                    operation="compile")
        from veritx_dse.verification.certificate import (
            verify_compiled_fabric,
        )

        from veritx_dse.compiler.orchestration import (
            build_resolved_bundle, build_resolved_bundle_v3,
            derive_stages_v3)
        try:
            if isinstance(request, CompileRequestV3) or (
                    getattr(request, "schema_version", None) == 4
                    and hasattr(request, "noc_controls")):
                bundle, staged, refusal = derive_stages_v3(request)
            else:
                staged = None
                refusal = None
                bundle = build_resolved_bundle(request)
        except ControlPlaneError as exc:
            stage = None
            cause = getattr(exc, "cause_type", "") or ""
            from veritx_dse.compiler.canonical import (  # noqa: PLC0415
                CanonicalCompileError,
            )
            if isinstance(exc.__cause__, CanonicalCompileError):
                stage = exc.__cause__.stage.value
            elif "stage=" in (exc.message or ""):
                stage = (exc.message.split("stage=", 1)[1]
                         .split(":", 1)[0].strip() or None)
            if exc.code == ErrorCode.UNSUPPORTED_SEMANTICS:
                return Compilation(status="UNSUPPORTED", request=request,
                                   bundle=None, certificate=None,
                                   error=exc.message,
                                   stopped_at_stage=stage)
            return Compilation(status="INVALID", request=request,
                               bundle=None, certificate=None,
                               error=f"{exc.code.value}: {exc.message}",
                               stopped_at_stage=stage)
        if bundle is None:
            exc = refusal
            status = ("UNSUPPORTED"
                      if exc is not None
                      and exc.code == ErrorCode.UNSUPPORTED_SEMANTICS
                      else "INVALID")
            error = (exc.message if exc is not None
                     else "derivation stopped before a bundle was produced")
            if exc is not None and exc.code != ErrorCode.UNSUPPORTED_SEMANTICS:
                error = f"{exc.code.value}: {error}"
            return Compilation(
                status=status, request=request, bundle=None,
                certificate=None, error=error,
                stopped_at_stage=(staged.stopped_at_stage
                                  if staged is not None else None),
                staged=staged)
        certificate = verify_compiled_fabric(bundle)
        if certificate.overall != "PASS":
            failed = sorted(o.obligation for o in certificate.obligations
                            if o.status != "PASS")
            from veritx_dse.compiler.canonical import (  # noqa: PLC0415
                CompileStage,
            )
            try:
                from veritx_dse.model.compile_model import (  # noqa: PLC0415
                    fabric_intent_view,
                )
                _view = fabric_intent_view(request)
            except Exception:
                _view = None
            _staged = StagedDerivation(
                stopped_at_stage=CompileStage.VERIFICATION.value,
                produced_stages=("INPUT", "INPUT_MAPPING", "TOPOLOGY",
                                 "ATTACHMENT", "ROUTING",
                                 "ROUTING_REALIZATION", "VC", "FABRIC",
                                 "RESOLVED_FABRIC"),
                inventory=getattr(bundle, "inventory", None),
                mapping=getattr(bundle, "mapping", None),
                topology=getattr(bundle, "topology", None),
                attachment=getattr(bundle, "attachment", None),
                view=_view,
            )
            return Compilation(
                status="INVALID", request=request, bundle=None,
                certificate=certificate,
                error=f"certificate obligations failed: {failed}",
                stopped_at_stage=CompileStage.VERIFICATION.value,
                staged=_staged)
        if routing_policy is None:
            return Compilation(status="COMPILED", request=request,
                               bundle=bundle, certificate=certificate,
                               error=None)
        from veritx_dse.compiler.orchestration import (  # noqa: PLC0415
            derive_adaptive_overlay,
        )
        try:
            overlay = derive_adaptive_overlay(
                request, bundle, routing_policy)
        except ControlPlaneError as exc:
            from veritx_dse.compiler.canonical import (  # noqa: PLC0415
                CompileStage,
            )
            stopped = CompileStage.ROUTING_REALIZATION.value
            if exc.code == ErrorCode.POLICY_REJECTED:
                stopped = CompileStage.VERIFICATION.value
            staged = StagedDerivation(
                stopped_at_stage=stopped,
                produced_stages=("INPUT", "INPUT_MAPPING", "TOPOLOGY",
                                 "ATTACHMENT", "ROUTING",
                                 "ROUTING_REALIZATION", "VC", "FABRIC",
                                 "RESOLVED_FABRIC"),
                inventory=bundle.inventory, mapping=bundle.mapping,
                topology=bundle.topology, attachment=bundle.attachment,
                view=None,
            )
            status = ("UNSUPPORTED"
                      if exc.code == ErrorCode.UNSUPPORTED_SEMANTICS
                      else "INVALID")
            return Compilation(
                status=status, request=request, bundle=None,
                certificate=None, error=exc.message,
                stopped_at_stage=stopped, staged=staged)
        return Compilation(status="COMPILED", request=request,
                           bundle=bundle, certificate=certificate,
                           error=None, adaptive=overlay)


__all__ = ["Compilation", "FabricCompiler"]
