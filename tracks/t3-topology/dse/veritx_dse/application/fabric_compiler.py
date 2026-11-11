"""veritx_dse.application.fabric_compiler — the product compiler (P1.4).

Rationale: docs/decisions/modules/application.md
"""
from __future__ import annotations

from dataclasses import dataclass
from functools import cached_property
from typing import Any

from veritx_dse.model.compile_model import CompileRequest, CompileRequestV3
from veritx_dse.model.compile_request_v4 import CompileRequestV4
from veritx_dse.model.compile_request_v5 import CompileRequestV5

from .errors import ControlPlaneError, ErrorCode

STAGES = (
    "INVENTORY", "MAPPING", "TOPOLOGY", "ATTACHMENT", "ROUTING",
    "RESOLVED_ROUTE", "VC_ASSIGNMENT", "COMPOSE", "BUNDLE",
)

#: Remaining unsupported V5 extensions and the stage that owns their refusal.
_V5_EXTENSION_OWNERS: tuple[tuple[str, str, str], ...] = (
    ("reset_channels", "COMPOSE",
     "no reset materialization; no supported RTL oracle"),
    ("power_domains", "COMPOSE",
     "architectural intent only; isolation/retention/level shifters "
     "unspecified and not UPF"),
    ("transactions", "EVALUATE",
     "endpoint-bound transaction policies execute in ABSTRACT_DATA_MOVEMENT_V1 "
     "only; generic backend/product execution and external protocol "
     "qualification are unqualified"),
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
    request: CompileRequest | CompileRequestV3 | CompileRequestV4 | CompileRequestV5
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
    #: The per-subnet VC binding for a multi-plane fabric (multi_plane_vc.py).
    #: None for a single-plane design. On a multi-plane fabric THIS, not the
    #: flat ``bundle.vc_assignment``, says which VCs a traffic class uses.
    multi_plane_vc: Any = None
    #: STAGE 1 (M1–M4) verdicts, one dict per module that ran:
    #: ``{module, ok, status, reason, findings}``. Empty for v2/v3 requests
    #: (no stage-1 intent to check). Additive: existing clients read the
    #: fields they know and ignore these.
    stage1_verdicts: tuple = ()
    #: STAGE 1 warnings (e.g. max_outstanding without ordering). A warning
    #: compiles; the finding rides on the result instead of being dropped.
    findings: tuple = ()

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

    def _multi_plane_vc(self, bundle: Any) -> Any:
        """Bind classes to planes when the topology declares Plane C, else None.

        A single-plane fabric keeps the flat class/VC admission unchanged;
        only a declared second subnet gets the subnet-scoped binding.
        """
        from veritx_dse.model.multi_plane_vc import (
            materialize_multi_plane_vc,
        )
        return materialize_multi_plane_vc(
            primary=bundle.vc_assignment, topology=bundle.topology)

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
        if any(i.interface_role is not None for i in request.agent_intents):
            pending.append(("agent_intents", "ATTACHMENT",
                            "stable agent-interface role identity is not bound to attachment"))
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
        owner = min((stage for _n, stage, _w in pending),
                    key=lambda s: STAGES.index(s) if s in STAGES else len(STAGES))
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

    def _run_stage1(self, request: Any) -> tuple[tuple, tuple, str | None, str | None, str | None]:
        """Run STAGE 1 deep modules M1→M4 on a v4 request.

Rationale: docs/design/mesh-stage1-schema-compiler-scope.md §4.5.
Returns ``(verdicts, findings, status, stage, reason)``: verdicts/findings
are always populated; on the first refusal status/stage/reason name it.
v2/v3 requests carry no stage-1 intent and return empty verdicts.
"""
        if getattr(request, "schema_version", None) != 4 \
                or not hasattr(request, "noc_controls"):
            return (), (), None, None, None
        verdicts: list[dict[str, Any]] = []
        findings: list[str] = []

        def _record(module: str, verdict: Any, stage: str) -> tuple[str, str, str] | None:
            verdicts.append({
                "module": module,
                "ok": verdict.ok,
                "status": verdict.status,
                "reason": verdict.reason,
                "findings": list(verdict.findings),
                "stopped_at_stage": stage,
            })
            findings.extend(verdict.findings)
            if verdict.ok:
                return None
            return (verdict.status, stage,
                    f"[{module}] {verdict.reason}")

        from veritx_dse.model.address_permission import (  # noqa: PLC0415
            AddressPermissionInput, TrafficRequirement,
            check_address_permission,
        )
        from veritx_dse.model.clock_power_cdc import (  # noqa: PLC0415
            ClockPowerInput, EndpointDomain, check_clock_power_cdc,
        )
        intents = tuple(getattr(request, "agent_intents", ()) or ())
        by_idx = {intent.agent_idx: intent for intent in intents}

        # M1 — Address & Permission (owner: ADDRESS_DECODE).
        # Initiator × region model: group identity (agent_idx) is preserved
        # to the check, never flattened. Duplicate (agent_idx, range) is a
        # conflict; two groups on one range may differ.
        from veritx_dse.model.address_permission import (  # noqa: PLC0415
            InitiatorPolicy,
        )
        initiator_policies = tuple(
            InitiatorPolicy(
                agent_idx=int(intent.agent_idx),
                address_range=str(window.address_range),
                readable=bool(window.readable),
                writable=bool(window.writable),
                atomic=bool(getattr(window, "atomic", False)),
            )
            for intent in intents
            for window in getattr(intent, "permission_windows", ()) or ())
        protocol_of: dict[int, str | None] = {}
        for intent in intents:
            fam = getattr(getattr(intent, "protocol", None), "value", None)
            if fam is None:
                fam = getattr(intent, "protocol", None)
                fam = fam if isinstance(fam, str) else None
            protocol_of[int(intent.agent_idx)] = fam
        initiator_protocols = tuple(
            (idx, protocol_of[idx]) for idx in sorted(protocol_of))
        counts = tuple(int(a.count) for a in request.agents)
        # Traffic is unattributed at M1 (no rank→range home map, see
        # address_permission docstring): the check is existential across
        # initiators for a range, so a read-only window with any write
        # traffic is INVALID while two opposite policies on one range
        # (one allows write) compile and differ at runtime.
        def _req_for_profile(profile) -> TrafficRequirement:
            cls = profile.traffic_class
            low = cls.lower()
            return TrafficRequirement(
                traffic_class=cls,
                is_write=("write" in low or "invalidate" in low
                          or low == "wb" or low.endswith("_wb")),
                is_read=("read" in low),
                is_atomic=("atomic" in low),
                initiator_idx=None)
        traffic = tuple(
            _req_for_profile(profile)
            for profile in request.workload.traffic_profiles)
        refusal = _record(
            "address_permission",
            check_address_permission(AddressPermissionInput(
                ranges=tuple(request.address_map.ranges),
                windows=(),
                agent_counts=counts,
                traffic=traffic,
                initiator_policies=initiator_policies,
                initiator_protocols=initiator_protocols)),
            "ADDRESS_DECODE")
        if refusal is not None:
            return tuple(verdicts), tuple(findings), *refusal

        # M2 — Ordering & VC (owner: VC). The derived assignment is the
        # authority (D4); only constrains the checks when desires exist.
        policy = getattr(request, "traffic_policy", None)
        desired = tuple(getattr(policy, "traffic_class_vcs", ()) or ())
        if desired:
            from veritx_dse.model.compile_model import (  # noqa: PLC0415
                derive_vc_assignment_v3,
            )
            from veritx_dse.model.ordering_vc import (  # noqa: PLC0415
                OrderingVCInput, check_ordering_vc,
            )
            try:
                derived = derive_vc_assignment_v3(request)
            except Exception as exc:  # noqa: BLE001
                return (tuple(verdicts), tuple(findings), "INVALID", "VC",
                        f"[ordering_vc] derived VC assignment cannot be "
                        f"computed ({exc})")
            refusal = _record(
                "ordering_vc",
                check_ordering_vc(OrderingVCInput(
                    graph=request.dependencies,
                    desired=desired,
                    derived_vc_count=derived.vc_count,
                    derived_per_class_vc=tuple(sorted(
                        derived.per_class_vc.items())))),
                "VC")
            if refusal is not None:
                return tuple(verdicts), tuple(findings), *refusal
        else:
            verdicts.append({
                "module": "ordering_vc", "ok": True, "status": "INVALID",
                "reason": None, "findings": [], "stopped_at_stage": "VC",
            })

        # M3 — Clock, Power & CDC (owner: ATTACHMENT). Multi-domain fabrics
        # compile exactly when every named insertion point is covered by a
        # CdcCell (the CdcCell factory builds one at each point); an
        # uncovered crossing is a typed CDC_CELL_MISSING refusal.
        endpoints = tuple(
            EndpointDomain(
                agent_idx=i,
                agent_clock_domain=agent.clock_domain,
                agent_power_domain=agent.power_domain,
                intent_clock_domain=(by_idx[i].clock_domain
                                     if i in by_idx else None),
                intent_power_domain=(by_idx[i].power_domain
                                     if i in by_idx else None),
            )
            for i, agent in enumerate(request.agents))
        from veritx_dse.model.clock_power_cdc import (  # noqa: PLC0415
            crossing_points,
        )
        provisional = ClockPowerInput(
            endpoints=endpoints, agents=tuple(request.agents),
            num_power_domains=request.physical.num_power_domains)
        # Real coverage: attempt a CdcCell build at every insertion point.
        # A point whose build is refused stays uncovered and the M3 gate
        # below then refuses with CDC_CELL_MISSING (a refusal, not a warn).
        from veritx_dse.product.cdc_cell_rtl import (  # noqa: PLC0415
            CdcParams, build_cdc_cell,
        )
        covered: list[str] = []
        for point in crossing_points(provisional):
            src_agent = (request.agents[point.src_group]
                         if point.src_group is not None
                         and point.src_group < len(request.agents)
                         else (request.agents[0] if request.agents
                               else None))
            build = build_cdc_cell(CdcParams(
                insertion_point=point.insertion_point,
                src_domain=point.src_domain, dst_domain=point.dst_domain,
                src_group=point.src_group, dst_group=point.dst_group,
                data_width=(src_agent.data_width
                            if src_agent is not None else 64),
                # Per-domain rates UNDECLARED (rates stay None: MTBF is
                # NOT_CALCULATED with reason; never substituted from the
                # global default_clock_freq_mhz assumption).
            ))
            if build.verdict.ok:
                covered.append(point.insertion_point)
        refusal = _record(
            "clock_power_cdc",
            check_clock_power_cdc(ClockPowerInput(
                endpoints=endpoints,
                agents=tuple(request.agents),
                num_power_domains=request.physical.num_power_domains,
                cdc_cells=tuple(covered))),
            "ATTACHMENT")
        if refusal is not None:
            return tuple(verdicts), tuple(findings), *refusal

        # M4 — Protocol Adapter (owner: PACKET_FORMAT).
        from veritx_dse.model.protocol_adapter import (  # noqa: PLC0415
            ProtocolInput, check_protocol,
        )
        first = request.agents[0] if request.agents else None
        refusal = _record(
            "protocol_adapter",
            check_protocol(ProtocolInput(
                intents=intents,
                data_width=first.data_width if first else 256,
                addr_width=first.addr_width if first else 64)),
            "PACKET_FORMAT")
        if refusal is not None:
            return tuple(verdicts), tuple(findings), *refusal
        owned = {int(intent.agent_idx) for intent in intents}
        unowned = tuple(
            (idx, getattr(agent, "protocol", None))
            for idx, agent in enumerate(request.agents)
            if getattr(agent, "protocol", None) and idx not in owned)
        if unowned:
            findings.append(
                "AGENT_PROTOCOL_UNOWNED: "
                + ", ".join(f"group {idx} ({literal!r})"
                            for idx, literal in unowned)
                + " declare legacy Agent.protocol literals with no matching "
                "agent_intents entry; the literal is preserved for "
                "identity and reports only and no adapter is generated "
                "from it")
        return tuple(verdicts), tuple(findings), None, None, None

    def compile(self, request: CompileRequest | CompileRequestV3 | CompileRequestV4 | CompileRequestV5,
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
            build_resolved_bundle, derive_stages_v3)
        # STAGE 1 gate: M1–M4 run on the frozen request BEFORE derivation so
        # their owner stages are authoritative (§5) and intent errors fail
        # fast. v2/v3 requests carry no stage-1 intent (empty verdicts).
        # NOTE: the scope doc §4.5 sketches running after derive_stages_v3;
        # running first is what puts ADDRESS_DECODE/VC/ATTACHMENT/
        # PACKET_FORMAT refusals ahead of downstream derivation refusals
        # that would otherwise shadow M1/M3.
        verdicts, stage1_findings, refusal_status, refusal_stage, refusal_reason = \
            self._run_stage1(request)
        if refusal_status is not None:
            return Compilation(
                status=refusal_status, request=request, bundle=None,
                certificate=None, error=refusal_reason,
                stopped_at_stage=refusal_stage,
                stage1_verdicts=verdicts, findings=stage1_findings)
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
                staged=_staged,
                stage1_verdicts=verdicts, findings=stage1_findings)
        if routing_policy is None:
            return Compilation(status="COMPILED", request=request,
                               bundle=bundle, certificate=certificate,
                               error=None,
                               control_plane=self._control_plane(bundle),
                               multi_plane_vc=self._multi_plane_vc(bundle),
                               stage1_verdicts=verdicts,
                               findings=stage1_findings)
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
                stopped_at_stage=stopped, staged=staged,
                stage1_verdicts=verdicts, findings=stage1_findings)
        return Compilation(status="COMPILED", request=request,
                           bundle=bundle, certificate=certificate,
                           error=None, adaptive=overlay,
                           control_plane=self._control_plane(bundle),
                           multi_plane_vc=self._multi_plane_vc(bundle),
                           stage1_verdicts=verdicts,
                           findings=stage1_findings)

__all__ = ["Compilation", "FabricCompiler"]
