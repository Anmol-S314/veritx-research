"""veritx_dse.application.fabric_compiler — the product compiler (P1.4).

One entry point, three stages kept separate (later optimization
repeats compile → verify → evaluate per candidate without
duplicating logic):

    compile(request)  → Compilation (bundle + certificate + status)

A LOCKED obligation that is not PASS means no ResolvedFabric is
presented as success: the outcome is INVALID (failed proof) or
UNSUPPORTED (refused semantics) with the certificate or the error
as evidence. Compilation is a pure function of the request — no
hidden environment state, no spawn, no backend.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from veritx_dse.model.compile_model import CompileRequest, CompileRequestV3

from .errors import ControlPlaneError, ErrorCode


@dataclass(frozen=True)
class Compilation:
    """In-memory compile outcome (not a persisted semantic artifact).

    status COMPILED carries the bundle + passing certificate.
    INVALID/UNSUPPORTED carry evidence (certificate or error) and
    never a bundle — a failed proof is not a fabric.
    """

    status: str  # COMPILED, INVALID, or UNSUPPORTED
    request: CompileRequest | CompileRequestV3
    bundle: Any | None
    certificate: Any | None
    error: str | None

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

    def compile(self, request: CompileRequest | CompileRequestV3
                ) -> Compilation:
        """Compile one request: bundle, then certificate, then verdict.

        P1C phase-2: v3 requests compile through the v3 bundle builder
        (genuine v3 derivation — never a fake-v2 conversion); v2 flows
        exactly as before.
        """
        from veritx_dse.verification.certificate import (
            verify_compiled_fabric,
        )

        from veritx_dse.compiler.orchestration import (
            build_resolved_bundle, build_resolved_bundle_v3)
        try:
            if isinstance(request, CompileRequestV3):
                bundle = build_resolved_bundle_v3(request)
            else:
                bundle = build_resolved_bundle(request)
        except ControlPlaneError as exc:
            if exc.code == ErrorCode.UNSUPPORTED_SEMANTICS:
                return Compilation(status="UNSUPPORTED", request=request,
                                   bundle=None, certificate=None,
                                   error=exc.message)
            return Compilation(status="INVALID", request=request,
                               bundle=None, certificate=None,
                               error=f"{exc.code.value}: {exc.message}")
        certificate = verify_compiled_fabric(bundle)
        if certificate.overall != "PASS":
            failed = sorted(o.obligation for o in certificate.obligations
                            if o.status != "PASS")
            return Compilation(
                status="INVALID", request=request, bundle=None,
                certificate=certificate,
                error=f"certificate obligations failed: {failed}")
        return Compilation(status="COMPILED", request=request,
                           bundle=bundle, certificate=certificate,
                           error=None)


__all__ = ["Compilation", "FabricCompiler"]
