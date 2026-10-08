"""veritx_dse.application.fabric_compiler — the product compiler (P1.4).

Rationale: docs/decisions/modules/application.md
"""
from __future__ import annotations

from dataclasses import dataclass
from functools import cached_property
from typing import Any

from veritx_dse.model.compile_model import CompileRequest, CompileRequestV3
from veritx_dse.model.compile_request_v5 import CompileRequestV5

from .errors import ControlPlaneError, ErrorCode

STAGES = (
    "INVENTORY", "MAPPING", "TOPOLOGY", "ATTACHMENT", "ROUTING",
    "RESOLVED_ROUTE", "VC_ASSIGNMENT", "COMPOSE", "BUNDLE",
)

#: Every non-empty V5 extension and the compiler stage that would have to
#: materialize it. The reason is the capability-closure "next blocker" for
#: that field, so a refusal names the exact missing piece rather than a
#: generic "V5 unsupported".
_V5_EXTENSION_OWNERS: tuple[tuple[str, str, str], ...] = (
    ("agent_intents", "ATTACHMENT",
     "stable agent-interface role identity is not bound to attachment"),
    ("reset_channels", "COMPOSE",
     "no reset materialization; no supported RTL oracle"),
    ("power_domains", "COMPOSE",
     "architectural intent only; isolation/retention/level shifters "
     "unspecified and not UPF"),
    ("crossings", "COMPOSE",
     "no crossing artifact; no RTL differential against a pinned "
     "primitive"),
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
    route: Any = None
    view: Any = None

    def has(self, stage: str) -> bool:
        return stage in self.produced_stages

@dataclass(frozen=True)
class Compilation:
    """In-memory compile outcome (not a persisted semantic artifact).

Rationale: docs/decisions/modules/application.md
    """

    status: str
    request: CompileRequest | CompileRequestV3 | CompileRequestV5
    bundle: Any | None
    certificate: Any | None
    error: str | None
    stopped_at_stage: str | None = None
    staged: StagedDerivation | None = None
    adaptive: Any = None
    #: A materialized V5 design extension, when the request carried one.
    #: They are NOT part of the hardware fabric DAG (an access policy is a
    #: design-level I-T contract, a sideband edge is its own edge), so they
    #: ride on the compilation rather than the FabricArtifact.
    access_policy: Any = None
    sideband_set: Any = None
    clock_domains: Any = None
    #: The SR-C control plane, when the design declares Plane C. It is a
    #: SECOND subnet with its own VC structure, materialized independently
    #: (control_plane.py), never recoloured onto Plane D.
    control_plane: Any = None

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
        self.validate_design_binding()
        if self.status == "COMPILED" and getattr(self.certificate, "overall", None) == "PASS":
            self.compiled_system  # materialize/revalidate the canonical root

    @cached_property
    def compiled_system(self):
        if self.status != "COMPILED":
            return None
        from veritx_dse.verification.system_certificate import materialize_compiled_system
        return materialize_compiled_system(
            request=self.request, bundle=self.bundle, certificate=self.certificate,
            access_policy=self.access_policy, sideband_set=self.sideband_set,
            clock_domains=self.clock_domains, control_plane=self.control_plane,
            adaptive=self.adaptive)

    def validate_design_binding(self) -> None:
        """Recheck V5 records/certificate before crossing an export boundary."""
        if self.status != "COMPILED" or not isinstance(self.request, CompileRequestV5):
            return
        from veritx_dse.verification.certificate import (
            VerificationCertificate, verify_v5_compilation,
        )
        expected = verify_v5_compilation(
            self.request, self.bundle, clock_domains=self.clock_domains,
            sideband_set=self.sideband_set, access_policy=self.access_policy)
        # Identity compares canonical JSON semantics (tuples become lists on
        # export/reload), not incidental in-memory container representation.
        if (expected.overall != "PASS"
                or type(self.certificate) is not VerificationCertificate
                or self.certificate.certificate_id() != expected.certificate_id()):
            raise ControlPlaneError(
                ErrorCode.EVIDENCE_INVALID,
                "V5 compilation records/certificate do not match the declared design binding",
                operation="compile")

class FabricCompiler:
    """Deterministic intent → verified fabric (P1A slice)."""

    def _control_plane(self, bundle: Any) -> Any:
        """Materialize Plane C when the design declares it, else None.

        Plane C is a second subnet, so it is derived from the Plane D
        fabric (same grid and concentration) and carried on the compilation
        rather than recoloured onto the fabric DAG.
        """
        planes = getattr(getattr(bundle, "topology", None), "planes", ())
        if "c" not in planes:
            return None
        from veritx_dse.model.control_plane import materialize_control_plane
        return materialize_control_plane(bundle.topology)

    def _compile_v5(self, request: Any,
                    routing_policy: Any) -> Compilation:
        """Preserve the V5 root while compiling its explicit base fabric.

        Supported records are bound by structural certification, not executed
        as clocks/sidebands/access enforcement. Other extensions refuse by
        owning stage; none are silently down-projected or dropped.
        """
        from veritx_dse.model.compile_request_v5 import CompileRequestV5
        if not isinstance(request, CompileRequestV5):
            raise ControlPlaneError(
                ErrorCode.UNSUPPORTED_SEMANTICS,
                "schema_version 5 without a CompileRequestV5 payload",
                operation="compile")
        pending: list[tuple[str, str, str]] = []
        for name, stage, why in _V5_EXTENSION_OWNERS:
            if getattr(request, name, None):
                pending.append((name, stage, why))
        policy = request.access_policy
        sideband_set = None
        if request.sideband_interfaces or request.sideband_connections:
            from veritx_dse.model.sideband import materialize_sidebands
            universe = tuple(f"group:{i}"
                             for i in range(len(request.base_v4.agents)))
            sideband_set = materialize_sidebands(
                request.sideband_interfaces, request.sideband_connections,
                agent_universe=universe)
        clock_domains = None
        if request.clock_sources or request.clock_domains:
            from veritx_dse.model.domain_intent import (
                materialize_clock_domains,
            )
            clock_domains = materialize_clock_domains(
                request.clock_sources, request.clock_domains)
        if not pending:
            from dataclasses import replace
            from veritx_dse.verification.certificate import verify_v5_compilation
            base = self.compile(request.base_v4, routing_policy=routing_policy)
            if base.status != "COMPILED":
                return replace(base, request=request)
            certificate = verify_v5_compilation(
                request, base.bundle, clock_domains=clock_domains,
                sideband_set=sideband_set, access_policy=policy)
            if certificate.overall != "PASS":
                return replace(base, request=request, status="INVALID",
                               bundle=None, certificate=certificate,
                               error="V5 structural design binding failed certification",
                               stopped_at_stage="VERIFICATION")
            return replace(base, request=request, certificate=certificate,
                           access_policy=policy, sideband_set=sideband_set,
                           clock_domains=clock_domains)
        owner = min((stage for _n, stage, _w in pending), key=STAGES.index)
        detail = "; ".join(
            f"{name} (owner stage {stage}: {why})"
            for name, stage, why in pending)
        reason = (
            f"UNSUPPORTED: CompileRequestV5 sets {len(pending)} V5 "
            f"extension(s) with no compiler materializer: {detail}. "
            "Empty V5 extension collections are the sole lossless "
            "down-projection to V4; a non-empty one must be materialized "
            "by the stage that owns it, never dropped.")
        return Compilation(status="UNSUPPORTED", request=request,
                           bundle=None, certificate=None, error=reason,
                           stopped_at_stage=owner)

    def compile(self, request: CompileRequest | CompileRequestV3 | CompileRequestV5,
                routing_policy: Any = None) -> Compilation:
        """Compile one request: bundle, then certificate, then verdict.

Rationale: docs/decisions/modules/application.md
        """
        if getattr(request, "schema_version", None) == 5 \
                and hasattr(request, "base_v4"):
            return self._compile_v5(request, routing_policy)
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
                               error=None,
                               control_plane=self._control_plane(bundle))
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
                           error=None, adaptive=overlay,
                           control_plane=self._control_plane(bundle))

__all__ = ["Compilation", "FabricCompiler"]
