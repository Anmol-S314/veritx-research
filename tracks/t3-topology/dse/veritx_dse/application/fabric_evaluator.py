"""veritx_dse.application.fabric_evaluator — P1B verified evaluation.

One entry point:

    FabricEvaluator.evaluate(compilation, workload, options)
        -> EvaluationOutcome (EVALUATED | BACKEND_UNAVAILABLE |
                              UNSUPPORTED | FAILED)

Preconditions are REFUSALS (typed ControlPlaneError, no backend work):
the input must be a COMPILED Compilation whose certificate is PASS, the
workload a canonical WorkloadGraph, the options an EvaluationOptions.
Anything downstream of satisfied preconditions is a TYPED OUTCOME —
never an exception, never fabricated performance.

Canonical chain (reuse, never reimplement):

    WorkloadGraph -> LogicalMessageArtifactV2 -> PhysicalTrafficArtifactV2
    -> traffic-class admission gate -> profile selection (derived from
    fabric semantics, never a user knob) -> pre-spawn gates
    (assert_projection_ready) -> certified BookSim projection
    (mesh-DOR native for MESH+DOR_XY fabrics, AnyNet for
    ANYNET_MIN_HOPS fabrics) -> producer availability (producer.py) ->
    qualified execution (quiescence inside) -> EvidenceArtifact
    (evidence.py only) -> NetworkWindowBinding v2 (ONE aggregate window)
    -> PerformanceModel + TemporalWorkload (window event only)
    -> schedule_workload -> build_performance_result -> reverify_result

Status law:
  * absent qualified BookSim producer -> BACKEND_UNAVAILABLE (the
    FileNotFoundError never escapes; no performance is fabricated);
  * execution failure (spawn, timeout, nonzero exit, quiescence,
    evidence authentication, timing bind) -> FAILED;
  * unprojectable semantics (unsupported workload semantics, unknown
    traffic class, BookSim lowering refusal, no valid network clock)
    -> UNSUPPORTED;
  * valid evidence + valid clock -> EVALUATED with a verified
    PerformanceResult.

Timing honesty: BookSim exposes one aggregate completion window, not
per-operation latency, so the temporal workload declares exactly ONE
NETWORK_TRAFFIC_WINDOW event. The network clock is an explicit caller
declaration (EvaluationOptions.network_clock_hz), recorded in the
PerformanceModel identity — never guessed. Without a valid clock the
evidence still authenticates but wall-time claims refuse: UNSUPPORTED
with a cycles-only window (window_cycles set, wall_time_ns None).
"""
from __future__ import annotations

import tempfile
from collections.abc import Mapping
from dataclasses import dataclass
from fractions import Fraction
from pathlib import Path
from typing import Any

from veritx_dse.application.errors import ControlPlaneError, ErrorCode
from veritx_dse.core.errors import EvidenceInvalid

EVALUATED = "EVALUATED"
BACKEND_UNAVAILABLE = "BACKEND_UNAVAILABLE"
UNSUPPORTED = "UNSUPPORTED"
FAILED = "FAILED"
OUTCOME_STATUSES = (EVALUATED, BACKEND_UNAVAILABLE, UNSUPPORTED, FAILED)

STANDALONE_BACKEND = "BOOKSIM_STANDALONE"

EVALUATION_CONTRACT_VERSION = 1


class EvaluationError(ControlPlaneError):
    """Typed refusal of an evaluation call (precondition, not outcome)."""


def _refuse(code: ErrorCode, message: str, *, cause_type: str = "") -> EvaluationError:
    return EvaluationError(code, message, operation="evaluate",
                           cause_type=cause_type)


def _require_workload_belongs_to_compilation(
        workload: Any, *, design_hash: str, workload_id: str) -> None:
    """Seal the Compilation→WorkloadGraph seam (content identity, never
    geometry).

    A canonical WorkloadGraph is a standalone artifact: its content
    identity (``workload_id``) deliberately excludes provenance, so
    same-geometry graphs from different designs are indistinguishable
    by shape. The lowering stamps ``provenance['design_hash']``; this
    gate refuses to evaluate a workload whose provenance does not name
    THIS compilation's design. Missing provenance is not a pass (fail
    closed — no fallback to geometry), because an unbindable workload
    cannot be proven to belong here.
    """
    provenance = workload.provenance
    if not isinstance(provenance, Mapping):
        raise _refuse(
            ErrorCode.INVALID_INTENT,
            f"workload {workload_id!r} carries no provenance block — it "
            f"cannot be proven to belong to design {design_hash!r}; "
            f"refusing to evaluate an unbindable workload (geometry is "
            f"not authority)",
            cause_type="WorkloadGraph")
    workload_design_hash = provenance.get("design_hash")
    if not isinstance(workload_design_hash, str) or \
            not workload_design_hash:
        raise _refuse(
            ErrorCode.INVALID_INTENT,
            f"workload {workload_id!r} provenance declares no "
            f"design_hash (has {sorted(provenance)}); refusing to "
            f"evaluate an unbindable workload",
            cause_type="WorkloadGraph")
    if workload_design_hash != design_hash:
        raise _refuse(
            ErrorCode.INVALID_INTENT,
            f"workload {workload_id!r} provenance design_hash "
            f"{workload_design_hash!r} does not match compilation design "
            f"hash {design_hash!r} — refusing a workload transplanted "
            f"from another design",
            cause_type="WorkloadGraph")


def _require_evidence_authentic(
        artifact: Any, *, backend_input_sha256: str,
        raw_evidence_sha256: str, stats: Any) -> None:
    """Seal the evidence-authentication gate with an explicit conditional.

    Deliberately NOT an ``assert``: production invariants must survive
    ``python3 -O`` (asserts disappear under optimization). A failing
    authentication raises the typed evidence refusal the caller maps to
    FAILED — never a silently accepted artifact.
    """
    if not artifact.authenticates(
            backend_input_sha256=backend_input_sha256,
            raw_evidence_sha256=raw_evidence_sha256,
            stats=stats):
        raise EvidenceInvalid(
            "evidence artifact does not authenticate against the backend "
            "input digest and raw evidence digest; refusing fabricated "
            "evidence")


@dataclass(frozen=True)
class EvaluationOptions:
    """How to evaluate. The network clock is an explicit caller-declared
    modeling assumption (Hz, exact): without a valid one the evaluator
    reports cycles-only and refuses wall-time claims."""

    backend: str = STANDALONE_BACKEND
    timeout_s: int = 120
    require_quiescence: bool = True
    network_clock_hz: int | Fraction | None = None
    traffic_class: str = "DEFAULT"
    seed: int | None = None
    run_dir: str | Path | None = None
    repo_root: str | Path | None = None
    binary: str | Path | None = None


@dataclass(frozen=True)
class EvaluationOutcome:
    """One adjudicated evaluation. EVALUATED binds authenticated evidence
    plus a reverified PerformanceResult; every other status carries a
    reason and never fabricated metrics. to_view_dict() is the
    contracts/srota/v1/evaluation.view.schema.json projection."""

    status: str
    design_hash: str
    resolved_fabric_hash: str
    workload_id: str
    message_artifact_id: str | None = None
    physical_traffic_id: str | None = None
    backend: str | None = None
    backend_profile: str | None = None
    producer_identity: str | None = None
    backend_config_hash: str | None = None
    backend_input_hash: str | None = None
    evidence_id: str | None = None
    raw_evidence_digest: str | None = None
    stats_digest: str | None = None
    performance_result_id: str | None = None
    performance_result: dict[str, Any] | None = None
    network_traffic_window: dict[str, Any] | None = None
    metrics: dict[str, Any] | None = None
    fidelity_warning: str | None = None
    reason: str | None = None
    run_dir: str | None = None
    evidence_path: str | None = None
    realization_digest: str | None = None

    def __post_init__(self) -> None:
        if self.status not in OUTCOME_STATUSES:
            raise EvaluationError(
                ErrorCode.INTERNAL_ERROR,
                f"unknown evaluation status {self.status!r}",
                operation="evaluate")

    def to_view_dict(self) -> dict[str, Any]:
        """The language-neutral EvaluationView (schema contract v1)."""
        backend_producer = None
        if self.producer_identity is not None:
            backend_producer = {
                "backend": self.backend,
                "producer_identity": self.producer_identity,
                "config_hash": self.backend_config_hash,
                "input_hash": self.backend_input_hash,
            }
        evidence = None
        if self.raw_evidence_digest is not None:
            evidence = {
                "raw_evidence_digest": self.raw_evidence_digest,
                "stats_digest": self.stats_digest,
            }
        return {
            "contract_version": EVALUATION_CONTRACT_VERSION,
            "status": self.status,
            "design_hash": _view_hash(self.design_hash),
            "resolved_fabric_hash": _view_hash(
                self.resolved_fabric_hash),
            "workload_id": self.workload_id,
            "message_artifact_id": self.message_artifact_id,
            "physical_traffic_id": self.physical_traffic_id,
            "backend_producer": backend_producer,
            "evidence": evidence,
            "performance_result_id": self.performance_result_id,
            "network_traffic_window": self.network_traffic_window,
            "metrics": self.metrics,
            "fidelity_warning": self.fidelity_warning,
            "reason": self.reason,
        }


def _view_hash(value: str | None) -> str | None:
    """Render an engine-native digest for the language-neutral view.

    Engine artifact hashes are bare 64-hex digests while the frozen
    EvaluationView schema requires self-describing ``sha256:<hex>`` for
    design_hash/resolved_fabric_hash. The outcome itself keeps the
    native identities (comparable with == against the artifacts); only
    the view projection prefixes. Strip one ``sha256:`` prefix to map
    a view hash back to its engine identity."""
    if value is None:
        return None
    if value.startswith("sha256:"):
        return value
    return "sha256:" + value


class VCAdmissionError(ValueError):
    """A workload traffic class cannot be admitted to the fabric VCs."""


def _admit_traffic_classes(logical: Any, bundle: Any) -> None:
    """Traffic-class admission gate (before spawn).

    Every LogicalMessage traffic class must exist in the
    VCAssignmentArtifact, map to >= 1 legal VC, and every such VC must
    exist and map to a routing class of the resolved route (which the
    router route must also materialize for execution). Unknown or
    missing classes are a typed refusal — never a silent VC0.
    """
    vc = bundle.vc_assignment
    class_to_vcs = {cls: tuple(vcs)
                    for cls, vcs in vc.traffic_class_to_vcs}
    vc_to_class = {v: rc for v, rc in vc.vc_to_routing_class}
    resolved_classes = set(bundle.resolved_route.routing_classes)
    router_classes = {d.id for d in bundle.router_route.routing_classes}
    for m in logical.messages:
        tc = m.traffic_class
        if tc not in class_to_vcs:
            raise VCAdmissionError(
                f"message {m.message_id!r} traffic class {tc!r} is not "
                f"declared by the VC assignment (declares "
                f"{sorted(class_to_vcs)}); refusing — never silent VC0")
        vcs = class_to_vcs[tc]
        if not vcs:
            raise VCAdmissionError(
                f"traffic class {tc!r} maps to an empty VC set; refusing")
        for v in vcs:
            if v not in vc.vc_ids:
                raise VCAdmissionError(
                    f"traffic class {tc!r} maps to VC {v}, which does "
                    f"not exist (vc_ids 0..{vc.vc_count - 1}); refusing")
            rc = vc_to_class.get(v)
            if rc is None:
                raise VCAdmissionError(
                    f"VC {v} (traffic class {tc!r}) names no routing "
                    f"class; refusing")
            if rc not in resolved_classes:
                raise VCAdmissionError(
                    f"VC {v} (traffic class {tc!r}) maps to routing "
                    f"class {rc!r}, which the resolved route does not "
                    f"define (has {sorted(resolved_classes)}); refusing")
            if rc not in router_classes:
                raise VCAdmissionError(
                    f"VC {v} (traffic class {tc!r}) maps to routing "
                    f"class {rc!r}, which the router route does not "
                    f"materialize (has {sorted(router_classes)}); refusing")


def _select_backend_path(bundle: Any) -> str | None:
    """Derive the certified backend path from fabric semantics.

    Never a user knob: the evaluator routes on what the fabric IS.
    ``meshdor``: square MESH family, DOR_XY materialized, every VC
    bound to DOR_XY (the native-mesh DOR profile's door). ``anynet``:
    ANYNET_MIN_HOPS materialized with every VC bound to it. The
    lowerers still enforce their full narrow domains; selection only
    routes to the right lowerer. Anything else (CONCENTRATED_MESH,
    TORUS/RING remnants, split classes) matches no certified path.
    """
    from veritx_dse.core.route_artifact import ANYNET_MIN_HOPS, DOR_XY
    from veritx_dse.model.topology_artifact import MaterializedFamily
    vc_classes = {rc for _, rc in
                  bundle.vc_assignment.vc_to_routing_class}
    router_classes = {d.id for d in
                      bundle.router_route.routing_classes}
    if (bundle.topology.family == MaterializedFamily.MESH
            and vc_classes == {DOR_XY} and DOR_XY in router_classes):
        return "meshdor"
    if (ANYNET_MIN_HOPS in router_classes
            and vc_classes == {ANYNET_MIN_HOPS}):
        return "anynet"
    return None


def _valid_clock(value: Any) -> bool:
    if isinstance(value, bool):
        return False
    if isinstance(value, int):
        return value > 0
    if isinstance(value, Fraction):
        return value > 0
    return False


def _numeric_metrics(stats: dict[str, Any]) -> dict[str, Any]:
    """Only metrics the backend actually produced. Absent metrics stay
    absent (never zero-filled); non-numeric evidence fields (verdicts,
    flags) are not metrics."""
    out: dict[str, Any] = {}
    for key, value in stats.items():
        if isinstance(value, bool):
            continue
        if isinstance(value, int):
            out[key] = value
        elif isinstance(value, float):
            if value == value and abs(value) != float("inf"):
                out[key] = value
    return out


class FabricEvaluator:
    """Compilation + WorkloadGraph -> authenticated, verified performance."""

    def evaluate(self, compilation: Any, workload: Any,
                 options: EvaluationOptions | None = None) -> EvaluationOutcome:
        from veritx_dse.application.fabric_compiler import Compilation
        from veritx_dse.workload.canonical_graph import WorkloadGraph

        opts = options if options is not None else EvaluationOptions()
        if not isinstance(opts, EvaluationOptions):
            raise _refuse(ErrorCode.INVALID_INTENT,
                          f"options must be an EvaluationOptions, got "
                          f"{type(opts).__name__}",
                          cause_type=type(opts).__name__)
        if not isinstance(compilation, Compilation):
            raise _refuse(ErrorCode.INVALID_INTENT,
                          f"compilation must be a Compilation, got "
                          f"{type(compilation).__name__}",
                          cause_type=type(compilation).__name__)
        if not isinstance(workload, WorkloadGraph):
            raise _refuse(ErrorCode.INVALID_INTENT,
                          f"workload must be a canonical WorkloadGraph, got "
                          f"{type(workload).__name__}",
                          cause_type=type(workload).__name__)
        self._check_option_types(opts)

        # ── preconditions: typed refusal, no backend work ──────────
        if compilation.status != "COMPILED":
            if compilation.status == "UNSUPPORTED":
                raise _refuse(ErrorCode.UNSUPPORTED_SEMANTICS,
                              f"cannot evaluate: compilation is UNSUPPORTED: "
                              f"{compilation.error}",
                              cause_type="Compilation")
            raise _refuse(ErrorCode.INVALID_INTENT,
                          f"cannot evaluate: compilation is "
                          f"{compilation.status}: {compilation.error}",
                          cause_type="Compilation")
        certificate = compilation.certificate
        if certificate is None or \
                getattr(certificate, "overall", None) != "PASS":
            raise _refuse(ErrorCode.EVIDENCE_INVALID,
                          "cannot evaluate: the compilation certificate is "
                          "not PASS — a failed proof is not a fabric",
                          cause_type="VerificationCertificate")
        bundle = compilation.bundle
        design_hash = compilation.request.design_hash()
        resolved_fabric_hash = \
            bundle.resolved_fabric.resolved_fabric_hash()
        workload_id = workload.workload_id()
        # The workload must belong to THIS design before any lowering or
        # backend work; same geometry never authorizes substitution.
        _require_workload_belongs_to_compilation(
            workload, design_hash=design_hash, workload_id=workload_id)

        def refuse(status: str, reason: str, **extra: Any) -> EvaluationOutcome:
            return EvaluationOutcome(
                status=status, design_hash=design_hash,
                resolved_fabric_hash=resolved_fabric_hash,
                workload_id=workload_id, reason=reason, **extra)

        if opts.backend != STANDALONE_BACKEND:
            return refuse(UNSUPPORTED,
                          f"backend {opts.backend!r} is not wired by the P1B "
                          f"evaluator (supports {STANDALONE_BACKEND} only)")

        # ── canonical lowering: graph -> messages -> traffic ───────
        from veritx_dse.core.errors import (
            ConservationFailed, EvidenceInvalid, InvalidInput,
            MappingInvalid, UnsupportedSchedule, UnsupportedSemantics,
        )
        try:
            from veritx_dse.workload.messages import (
                LogicalMessageArtifactV2,
            )
            from veritx_dse.workload.traffic import (
                PhysicalTrafficArtifactV2,
            )
            logical = LogicalMessageArtifactV2(
                workload, traffic_class=opts.traffic_class)
            physical = PhysicalTrafficArtifactV2(logical=logical,
                                                 bundle=bundle)
        except (UnsupportedSemantics, UnsupportedSchedule) as exc:
            return refuse(UNSUPPORTED,
                          f"workload semantics unprojectable: {exc}",
                          )
        except (InvalidInput, EvidenceInvalid, MappingInvalid,
                ConservationFailed) as exc:
            return refuse(FAILED,
                          f"workload lowering failed: "
                          f"{type(exc).__name__}: {exc}")
        message_id = logical.message_artifact_id()
        traffic_id = physical.physical_traffic_id()

        # ── traffic-class admission gate (before spawn) ────────────
        try:
            _admit_traffic_classes(logical, bundle)
        except VCAdmissionError as exc:
            return refuse(UNSUPPORTED, f"traffic-class admission refused: "
                                       f"{exc}",
                          message_artifact_id=message_id,
                          physical_traffic_id=traffic_id)

        # ── certified path selection (derived, never a user knob) ─
        path = _select_backend_path(bundle)
        if path is None:
            vc_classes = sorted(
                {rc for _, rc in
                 bundle.vc_assignment.vc_to_routing_class})
            router_classes = sorted(
                {d.id for d in bundle.router_route.routing_classes})
            return refuse(
                UNSUPPORTED,
                f"fabric matches no certified BookSim path: family "
                f"{getattr(bundle.topology.family, 'value',
                            bundle.topology.family)!r}, router classes "
                f"{router_classes}, VC classes {vc_classes} "
                f"(mesh-DOR needs MESH+DOR_XY; AnyNet needs "
                f"ANYNET_MIN_HOPS)",
                message_artifact_id=message_id,
                physical_traffic_id=traffic_id)

        # ── canonical projection (pure: gates + lowering + render) ─
        try:
            if path == "meshdor":
                from veritx_dse.backend.meshdor import (
                    prepare_meshdor as _prepare,
                )
            else:
                from veritx_dse.backend.projection import (
                    prepare_waved_booksim as _prepare,
                )
            prepared, summary = _prepare(physical, seed=opts.seed)
        except Exception as exc:
            from veritx_dse.backend.booksim import BookSimLoweringError
            if isinstance(exc, BookSimLoweringError):
                return refuse(UNSUPPORTED,
                              f"fabric unprojectable to BookSim: {exc}",
                              message_artifact_id=message_id,
                              physical_traffic_id=traffic_id)
            return refuse(FAILED,
                          f"pre-spawn projection failed: "
                          f"{type(exc).__name__}: {exc}",
                          message_artifact_id=message_id,
                          physical_traffic_id=traffic_id)
        config = prepared.config
        manifest = prepared.manifest
        prof = config.backend_profile
        config_hash = config.backend_config_hash()
        input_hash = manifest.backend_input_hash()

        # ── shared-realization statement (qualification.py) ────────
        try:
            from veritx_dse.backend.qualification import (
                booksim_shared_realization,
            )
            from veritx_dse.core.spec import canonical_json
            import hashlib
            realization = booksim_shared_realization(config)
            realization_digest = hashlib.sha256(
                canonical_json(realization).encode()).hexdigest()
        except Exception as exc:
            return refuse(UNSUPPORTED,
                          f"BookSim realization unstatable: "
                          f"{type(exc).__name__}: {exc}",
                          message_artifact_id=message_id,
                          physical_traffic_id=traffic_id,
                          backend=STANDALONE_BACKEND,
                          backend_profile=prof)

        # ── backend availability (producer.py; no FileNotFoundError) ─
        from veritx_dse.backend.producer import (
            ProducerError, resolve_producer_identity,
        )
        from veritx_dse.core.paths import REPO as _REPO
        repo_root = Path(opts.repo_root) if opts.repo_root is not None \
            else Path(_REPO)
        try:
            if opts.binary is not None:
                bin_path = Path(opts.binary)
                producer = resolve_producer_identity(
                    bin_path, repo_root=repo_root)
            else:
                from veritx_dse.simulation.booksim import find_booksim_bin
                bin_path = find_booksim_bin(repo_root)
                producer = resolve_producer_identity(
                    bin_path, repo_root=repo_root)
        except FileNotFoundError as exc:
            return refuse(BACKEND_UNAVAILABLE,
                          f"no qualified BookSim producer available: {exc}",
                          message_artifact_id=message_id,
                          physical_traffic_id=traffic_id,
                          backend=STANDALONE_BACKEND,
                          backend_profile=prof,
                          backend_config_hash=config_hash,
                          backend_input_hash=input_hash,
                          realization_digest=realization_digest)
        except ProducerError as exc:
            return refuse(BACKEND_UNAVAILABLE,
                          f"BookSim producer unidentifiable: {exc}",
                          message_artifact_id=message_id,
                          physical_traffic_id=traffic_id,
                          backend=STANDALONE_BACKEND,
                          backend_profile=prof,
                          backend_config_hash=config_hash,
                          backend_input_hash=input_hash,
                          realization_digest=realization_digest)

        run_dir = Path(opts.run_dir) if opts.run_dir is not None \
            else Path(tempfile.mkdtemp(prefix="p1b-eval-"))
        backend_run_dir = run_dir / "run"
        evidence_dir = run_dir / "evidence"

        # ── qualified execution (+ quiescence when required) ───────
        try:
            if path == "meshdor":
                from veritx_dse.backend.meshdor import (
                    run_waved_meshdor as _run,
                )
            else:
                from veritx_dse.backend.projection import (
                    run_waved_booksim as _run,
                )
            result = _run(
                prepared, run_dir=backend_run_dir, repo_root=repo_root,
                timeout=opts.timeout_s, binary=bin_path,
                summary=summary if opts.require_quiescence else None)
        except Exception as exc:
            return refuse(FAILED,
                          f"backend execution failed: "
                          f"{type(exc).__name__}: {exc}",
                          message_artifact_id=message_id,
                          physical_traffic_id=traffic_id,
                          backend=STANDALONE_BACKEND,
                          backend_profile=prof,
                          producer_identity=producer.binary_sha256,
                          backend_config_hash=config_hash,
                          backend_input_hash=input_hash,
                          run_dir=str(run_dir),
                          realization_digest=realization_digest)
        cert_evidence = result["evidence"]
        if cert_evidence.exit_status != 0:
            return refuse(FAILED,
                          f"backend execution failed with exit status "
                          f"{cert_evidence.exit_status}",
                          message_artifact_id=message_id,
                          physical_traffic_id=traffic_id,
                          backend=STANDALONE_BACKEND,
                          backend_profile=prof,
                          producer_identity=producer.binary_sha256,
                          backend_config_hash=config_hash,
                          backend_input_hash=input_hash,
                          run_dir=str(run_dir),
                          realization_digest=realization_digest)
        if cert_evidence.route_equivalence != "EXACT":
            return refuse(FAILED,
                          f"executed route not proven EXACT "
                          f"(got {cert_evidence.route_equivalence!r})",
                          message_artifact_id=message_id,
                          physical_traffic_id=traffic_id,
                          backend=STANDALONE_BACKEND,
                          backend_profile=prof,
                          producer_identity=producer.binary_sha256,
                          backend_config_hash=config_hash,
                          backend_input_hash=input_hash,
                          run_dir=str(run_dir),
                          realization_digest=realization_digest)

        # ── evidence authentication (evidence.py only) ─────────────
        try:
            from veritx_dse.backend.evidence import (
                EvidenceArtifact, read_verified_evidence, write_evidence,
            )
            ref = write_evidence(evidence_dir, cert_evidence.to_dict())
            verified_doc = read_verified_evidence(ref)
            artifact = EvidenceArtifact.build(
                backend=STANDALONE_BACKEND,
                backend_input_id=input_hash,
                backend_input_sha256=input_hash,
                raw_evidence_sha256=ref.sha256,
                stats=cert_evidence.stats)
            _require_evidence_authentic(
                artifact, backend_input_sha256=input_hash,
                raw_evidence_sha256=ref.sha256,
                stats=cert_evidence.stats)
        except Exception as exc:
            return refuse(FAILED,
                          f"evidence authentication failed: "
                          f"{type(exc).__name__}: {exc}",
                          message_artifact_id=message_id,
                          physical_traffic_id=traffic_id,
                          backend=STANDALONE_BACKEND,
                          backend_profile=prof,
                          producer_identity=producer.binary_sha256,
                          backend_config_hash=config_hash,
                          backend_input_hash=input_hash,
                          run_dir=str(run_dir),
                          realization_digest=realization_digest)
        _ = verified_doc
        stats = cert_evidence.stats
        metrics = _numeric_metrics(stats) or None

        # ── network window bind (ONE aggregate window, v2 chain) ───
        chain = {"chain_schema_version": 2,
                 "workload_graph_id": workload_id,
                 "physical_traffic_id": traffic_id,
                 "backend_config_hash": config_hash,
                 "backend_input_hash": input_hash}
        try:
            from veritx_dse.performance.network import bind_network_window
            clock = opts.network_clock_hz if _valid_clock(
                opts.network_clock_hz) else None
            binding, window = bind_network_window(
                evidence=cert_evidence, chain=chain,
                network_clock_hz=clock, evidence_sha256=ref.sha256,
                expected_packets=summary["num_packets"])
        except Exception as exc:
            return refuse(FAILED,
                          f"network window bind failed: "
                          f"{type(exc).__name__}: {exc}",
                          message_artifact_id=message_id,
                          physical_traffic_id=traffic_id,
                          backend=STANDALONE_BACKEND,
                          backend_profile=prof,
                          producer_identity=producer.binary_sha256,
                          backend_config_hash=config_hash,
                          backend_input_hash=input_hash,
                          evidence_id=artifact.evidence_id(),
                          raw_evidence_digest=ref.sha256,
                          stats_digest=artifact.stats_sha256,
                          metrics=metrics,
                          run_dir=str(run_dir),
                          evidence_path=ref.path,
                          realization_digest=realization_digest)
        window_cycles = stats.get("completion_time")

        if clock is None:
            # Honest cycles-only refusal: the evidence is authenticated
            # and quiescence-proven, but with no valid network clock no
            # wall-time claim may be made.
            return refuse(UNSUPPORTED,
                          "no valid network clock declared "
                          "(EvaluationOptions.network_clock_hz): refusing "
                          "wall-time claims; reporting the authenticated "
                          "cycles-only completion window",
                          message_artifact_id=message_id,
                          physical_traffic_id=traffic_id,
                          backend=STANDALONE_BACKEND,
                          backend_profile=prof,
                          producer_identity=producer.binary_sha256,
                          backend_config_hash=config_hash,
                          backend_input_hash=input_hash,
                          evidence_id=artifact.evidence_id(),
                          raw_evidence_digest=ref.sha256,
                          stats_digest=artifact.stats_sha256,
                          network_traffic_window={
                              "window_cycles": window_cycles,
                              "wall_time_ns": None,
                              "cycles_only": True},
                          metrics=metrics,
                          run_dir=str(run_dir),
                          evidence_path=ref.path,
                          realization_digest=realization_digest)

        # ── verified performance (window event only — no per-op
        #    latency is ever invented) ─────────────────────────────
        try:
            from veritx_dse.core.time import QTime
            from veritx_dse.performance.model import (
                ClockDef, PerformanceModel, ResourceDef, fidelity_warning,
            )
            from veritx_dse.performance.network import (
                NetworkWindowBinding,
            )
            from veritx_dse.performance.result import (
                PerformanceEventGraph, build_performance_result,
                reverify_result,
            )
            from veritx_dse.performance.scheduler import schedule_workload
            from veritx_dse.performance.workload import (
                EVENT_NETWORK_TRAFFIC_WINDOW, TemporalEvent,
                TemporalWorkload,
            )
            model = PerformanceModel(
                clocks=(ClockDef("network", clock),),
                resources=(ResourceDef("fabric.network_window",
                                       "EXCLUSIVE", capacity=1),),
                network_clock="network")
            net_event = TemporalEvent(
                "network_traffic_window",
                EVENT_NETWORK_TRAFFIC_WINDOW, QTime.zero())
            temporal = TemporalWorkload(performance_model=model,
                                        events=(net_event,))
            wave_d_chain = {
                "design_hash": design_hash,
                "workload_graph_id": workload_id,
                "message_artifact_id": message_id,
                "physical_traffic_id": traffic_id,
                "resolved_fabric_hash": resolved_fabric_hash,
                "backend_config_hash": config_hash,
                "backend_input_hash": input_hash,
                "evidence_sha256": ref.sha256,
                "stats_sha256": artifact.stats_sha256,
            }
            egraph = PerformanceEventGraph(
                workload=temporal,
                network_binding=NetworkWindowBinding.from_dict(
                    binding.to_dict()),
                wave_d_chain=dict(wave_d_chain))
            schedule = schedule_workload(
                temporal, network_durations=egraph.network_durations())
            perf = build_performance_result(graph=egraph,
                                            schedule=schedule)
            reverify_result(perf, workload=temporal)
            warning = fidelity_warning(model)
        except Exception as exc:
            return refuse(FAILED,
                          f"performance construction failed: "
                          f"{type(exc).__name__}: {exc}",
                          message_artifact_id=message_id,
                          physical_traffic_id=traffic_id,
                          backend=STANDALONE_BACKEND,
                          backend_profile=prof,
                          producer_identity=producer.binary_sha256,
                          backend_config_hash=config_hash,
                          backend_input_hash=input_hash,
                          evidence_id=artifact.evidence_id(),
                          raw_evidence_digest=ref.sha256,
                          stats_digest=artifact.stats_sha256,
                          network_traffic_window={
                              "window_cycles": window_cycles,
                              "wall_time_ns": None,
                              "cycles_only": True},
                          metrics=metrics,
                          run_dir=str(run_dir),
                          evidence_path=ref.path,
                          realization_digest=realization_digest)
        wall_ns = window.to_float() * 1e9 if isinstance(window, QTime) \
            else None
        return EvaluationOutcome(
            status=EVALUATED, design_hash=design_hash,
            resolved_fabric_hash=resolved_fabric_hash,
            workload_id=workload_id,
            message_artifact_id=message_id,
            physical_traffic_id=traffic_id,
            backend=STANDALONE_BACKEND,
            backend_profile=prof,
            producer_identity=producer.binary_sha256,
            backend_config_hash=config_hash,
            backend_input_hash=input_hash,
            evidence_id=artifact.evidence_id(),
            raw_evidence_digest=ref.sha256,
            stats_digest=artifact.stats_sha256,
            performance_result_id=perf["resource_id"],
            performance_result=perf,
            network_traffic_window={
                "window_cycles": window_cycles,
                "wall_time_ns": wall_ns,
                "cycles_only": False},
            metrics=metrics,
            fidelity_warning=warning,
            reason=None,
            run_dir=str(run_dir),
            evidence_path=ref.path,
            realization_digest=realization_digest)

    @staticmethod
    def _check_option_types(opts: EvaluationOptions) -> None:
        if not isinstance(opts.backend, str) or not opts.backend:
            raise _refuse(ErrorCode.INVALID_INTENT,
                          "options.backend must be a non-empty string",
                          cause_type="EvaluationOptions")
        if type(opts.timeout_s) is not int or opts.timeout_s <= 0:
            raise _refuse(ErrorCode.INVALID_INTENT,
                          f"options.timeout_s must be a positive int, got "
                          f"{opts.timeout_s!r}",
                          cause_type="EvaluationOptions")
        if type(opts.require_quiescence) is not bool:
            raise _refuse(ErrorCode.INVALID_INTENT,
                          "options.require_quiescence must be a bool",
                          cause_type="EvaluationOptions")
        if not isinstance(opts.traffic_class, str) or \
                not opts.traffic_class:
            raise _refuse(ErrorCode.INVALID_INTENT,
                          "options.traffic_class must be a non-empty string",
                          cause_type="EvaluationOptions")
        if opts.seed is not None and \
                (type(opts.seed) is not int or opts.seed < 0):
            raise _refuse(ErrorCode.INVALID_INTENT,
                          f"options.seed must be a non-negative int or None, "
                          f"got {opts.seed!r}",
                          cause_type="EvaluationOptions")
        # network_clock_hz is deliberately NOT type-checked here: an
        # absent or invalid clock is a typed UNSUPPORTED outcome
        # (cycles-only refusal), never a call rejection.


__all__ = [
    "BACKEND_UNAVAILABLE", "EVALUATED", "FAILED", "EvaluationError",
    "EvaluationOptions", "EvaluationOutcome", "FabricEvaluator",
    "OUTCOME_STATUSES", "STANDALONE_BACKEND", "UNSUPPORTED",
    "VCAdmissionError",
]
