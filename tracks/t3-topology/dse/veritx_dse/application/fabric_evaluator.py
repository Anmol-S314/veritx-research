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
from dataclasses import dataclass
from fractions import Fraction
from pathlib import Path
from typing import Any

from veritx_dse.application.errors import ControlPlaneError, ErrorCode
from veritx_dse.application.requirements import verify_performance_result
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


def _hash_of(obj: Any, name: str) -> str:
    """Read a child-artifact hash that may be a method (RT v1) or a
    stored attribute (canonical v2). Identity comes from the child;
    this shim only normalizes the accessor."""
    value = getattr(obj, name)
    return value() if callable(value) else value


def _require_context_for_workload(
        compilation: Any, workload: Any) -> Any:
    """Seal the Compilation→WorkloadGraph seam with ONE canonical
    lowering.

    The canonical context lowers the compilation request exactly once;
    the caller's workload is validated against it by content identity
    only — provenance is forgeable metadata, never authority. A
    transplanted workload is a typed refusal, never a second lowering.
    Returns the ``CanonicalEvaluationContext`` the adapters evaluate.
    """
    from veritx_dse.application.evaluation_context import (
        build_evaluation_context,
    )
    from veritx_dse.core.errors import (
        InvalidInput, UnsupportedSchedule, UnsupportedSemantics,
    )
    from veritx_dse.model.compile_model import CompileRequestV3
    request = compilation.request
    if not isinstance(request, CompileRequestV3):
        raise _refuse(
            ErrorCode.INVALID_INTENT,
            f"cannot evaluate: compilation request is "
            f"{type(request).__name__}, not a v3 intent — there is no "
            f"lowering authority to re-derive the workload from, and an "
            f"unverifiable workload is not a pass",
            cause_type=type(request).__name__)
    try:
        context = build_evaluation_context(compilation)
    except InvalidInput as exc:
        raise _refuse(
            ErrorCode.INVALID_INTENT,
            f"cannot evaluate: the compilation request does not lower to "
            f"a workload: {exc}",
            cause_type="CompileRequestV3") from exc
    except (UnsupportedSemantics, UnsupportedSchedule) as exc:
        raise _refuse(
            ErrorCode.UNSUPPORTED_SEMANTICS,
            f"cannot evaluate: the compilation request lowering is "
            f"unsupported: {exc}",
            cause_type=type(exc).__name__) from exc
    if workload.workload_id() != context.workload_id:
        raise _refuse(
            ErrorCode.INVALID_INTENT,
            f"workload {workload.workload_id()!r} is not the lowering of "
            f"compilation request design {request.design_hash()!r} "
            f"({context.workload_id!r}) — refusing a semantic "
            f"transplant; provenance cannot bind a foreign graph",
            cause_type="WorkloadGraph")
    return context


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
    attempt_path: str | None = None
    attempt_digest: str | None = None
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
        from veritx_dse.workload.graph import WorkloadGraph

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
            _hash_of(bundle.resolved_fabric, "resolved_fabric_hash")
        workload_id = workload.workload_id()
        # The canonical context lowers the request EXACTLY once; the
        # workload is validated against it by identity (provenance is
        # forgeable metadata). No second lowering anywhere downstream.
        context = _require_context_for_workload(compilation, workload)

        def refuse(status: str, reason: str, **extra: Any) -> EvaluationOutcome:
            return EvaluationOutcome(
                status=status, design_hash=design_hash,
                resolved_fabric_hash=resolved_fabric_hash,
                workload_id=workload_id, reason=reason, **extra)

        if opts.backend != STANDALONE_BACKEND:
            return refuse(UNSUPPORTED,
                          f"backend {opts.backend!r} is not wired by the P1B "
                          f"evaluator (supports {STANDALONE_BACKEND} only)")

        # ── canonical projection via the BookSim adapter ───────────
        # Federated: the evaluator consumes the certified BookSim stack
        # through the BackendAdapter seam. The ADAPTER owns the canonical
        # traffic construction (V3/V2 by unified class), the VC admission
        # gate, the intent-class assertion, and the projection — exactly
        # once, no duplicate artifact construction here. The prepared
        # execution flows straight from prepare() to execute(); the
        # evaluator binds the native identities and keeps the
        # evidence/window/performance assembly.
        from veritx_dse.application.evaluation_question import (
            EvaluationQuestion,
        )
        from veritx_dse.backend.booksim_adapter import (
            BookSimAdapter, BookSimExecutionFailure,
            BookSimProjectionRefusal,
        )
        seed = opts.seed if type(opts.seed) is int \
            and not isinstance(opts.seed, bool) and opts.seed >= 0 else 0
        adapter = BookSimAdapter()
        try:
            exec_prepared = adapter.prepare(
                context, EvaluationQuestion.NETWORK_COMPLETION,
                traffic_class=opts.traffic_class)
        except BookSimProjectionRefusal as exc:
            # Preserve the pre-adapter refusal taxonomy: lowering/traffic
            # construction failures are FAILED; admission and projection
            # refusals are UNSUPPORTED. When the canonical artifacts were
            # constructed before the gate refused, bind their identities.
            reason = str(exc)
            if reason.startswith("workload lowering failed:"):
                return refuse(FAILED, reason,
                              message_artifact_id=exc.message_artifact_id,
                              physical_traffic_id=exc.physical_traffic_id)
            return refuse(UNSUPPORTED,
                          f"fabric unprojectable to BookSim: {exc}",
                          message_artifact_id=exc.message_artifact_id,
                          physical_traffic_id=exc.physical_traffic_id)
        bs_prep = exec_prepared.native_prepared
        message_id = bs_prep.message_artifact_id
        traffic_id = bs_prep.physical_traffic_id
        prof = bs_prep.profile_id
        config_hash = bs_prep.config_hash
        input_hash = bs_prep.input_hash
        realization_digest = bs_prep.realization_digest
        prepared = bs_prep.prepared

        # ── backend availability via the adapter (producer.py; no
        # FileNotFoundError) ──
        from veritx_dse.backend.producer import ProducerError
        from veritx_dse.core.paths import REPO as _REPO
        repo_root = Path(opts.repo_root) if opts.repo_root is not None \
            else Path(_REPO)
        run_dir = Path(opts.run_dir) if opts.run_dir is not None \
            else Path(tempfile.mkdtemp(prefix="p1b-eval-"))
        evidence_dir = run_dir / "evidence"
        try:
            if opts.binary is not None:
                bin_path = Path(opts.binary)
            else:
                from veritx_dse.simulation.booksim import find_booksim_bin
                bin_path = find_booksim_bin(repo_root)
            from types import SimpleNamespace
            exec_opts = SimpleNamespace(
                binary=bin_path, repo_root=repo_root,
                run_dir=run_dir, timeout=opts.timeout_s, seed=seed)
            result = adapter.execute(exec_prepared, exec_opts)
            producer = result.producer
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
                          f"BookSim producer not qualified: {exc}",
                          message_artifact_id=message_id,
                          physical_traffic_id=traffic_id,
                          backend=STANDALONE_BACKEND,
                          backend_profile=prof,
                          backend_config_hash=config_hash,
                          backend_input_hash=input_hash,
                          realization_digest=realization_digest)
        except BookSimExecutionFailure as _exc:
            return refuse(FAILED,
                          f"backend execution failed: {_exc}",
                          message_artifact_id=message_id,
                          physical_traffic_id=traffic_id,
                          backend=STANDALONE_BACKEND,
                          backend_profile=prof,
                          producer_identity=_exc.producer.binary_sha256,
                          backend_config_hash=config_hash,
                          backend_input_hash=input_hash,
                          run_dir=str(run_dir),
                          realization_digest=realization_digest)

        record = result.record
        evidence = record.evidence
        # execute_prepared_booksim fails closed on nonzero exit, so a
        # completed record always carries exit_status 0 and parsed stats.
        # Stats flow unmodified from here on: the proof re-derives the
        # stats digest from the persisted bytes, so any local key alias
        # would break artifact↔binding agreement. The canonical
        # ``completion_cycles`` key is consumed as-is downstream.
        stats = evidence.stats

        # ── evidence authentication (evidence.py only) ─────────────
        # §26 reload gate: the persisted bytes must read back through
        # the canonical reader and validate — proving the write/read
        # contract, not just in-memory construction. execute wrote the
        # canonical {"evidence","attempt"} wrapper to the run
        # directory; the SCIENTIFIC document inside it is what validates
        # as evidence.
        #
        # The evidence CHAIN (binding, artifact, outcome, proof) then
        # names the pure scientific document only: the wrapper mixes
        # run-varying attempt metadata (run_dir, wall time) into its
        # bytes, so a wrapper digest can never be run-stable. The bare
        # scientific bytes are deterministic for identical science, and
        # write_evidence refuses to overwrite them with anything else.
        from veritx_dse.backend.evidence import (
            EVIDENCE_SCHEMA_VERSION, BackendEvidenceError, EvidenceArtifact,
            ScientificBackendEvidence, admit_for_certified_product,
            read_verified_evidence, validate_evidence_document, write_evidence,
            write_execution_attempt,
        )
        from veritx_dse.core.artifact import ArtifactError
        try:
            persisted = read_verified_evidence(record.ref)
            if not isinstance(persisted.get("evidence"), dict):
                raise BackendEvidenceError(
                    "persisted evidence wrapper carries no scientific "
                    "evidence document")
            verified_doc = validate_evidence_document(
                persisted["evidence"])
            if verified_doc.get("schema_version") != EVIDENCE_SCHEMA_VERSION:
                raise BackendEvidenceError(
                    "persisted evidence is not the current schema; it "
                    "cannot certify")
            # The certified evaluator only ever emits admitted evidence:
            # content authentication alone is not qualification.
            admit_for_certified_product(
                ScientificBackendEvidence.from_dict(verified_doc))
            eref = write_evidence(evidence_dir, verified_doc)
            attempt_ref = write_execution_attempt(
                evidence_dir, record.attempt.to_dict())
            artifact = EvidenceArtifact.build(
                backend=STANDALONE_BACKEND,
                backend_input_id=input_hash,
                backend_input_sha256=input_hash,
                raw_evidence_sha256=eref.sha256,
                stats=stats)
            _require_evidence_authentic(
                artifact, backend_input_sha256=input_hash,
                raw_evidence_sha256=eref.sha256,
                stats=stats)
        except (BackendEvidenceError, ArtifactError, OSError) as exc:
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
        metrics = _numeric_metrics(stats) or None

        # ── network window bind (ONE aggregate window, v2 chain) ───
        chain = {"chain_schema_version": 2,
                 "workload_graph_id": workload_id,
                 "physical_traffic_id": traffic_id,
                 "backend_config_hash": config_hash,
                 "backend_input_hash": input_hash}
        try:
            from veritx_dse.core.time import TimeError
            from veritx_dse.performance.network import bind_network_window
            clock = opts.network_clock_hz if _valid_clock(
                opts.network_clock_hz) else None
            from types import SimpleNamespace as _NS
            binding, window = bind_network_window(
                evidence=_NS(stats=stats), chain=chain,
                network_clock_hz=clock,
                evidence_sha256=eref.sha256,
                expected_packets=prepared.expected_packets)
        except (TimeError, ArtifactError) as exc:
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
                          raw_evidence_digest=eref.sha256,
                          stats_digest=artifact.stats_sha256,
                          metrics=metrics,
                          run_dir=str(run_dir),
                          evidence_path=eref.path,
                          attempt_path=attempt_ref.path,
                          attempt_digest=attempt_ref.sha256,
                          realization_digest=realization_digest)
        # Same canonical-key acceptance as bind_network_window above:
        # completion cycles under either the historical or canonical key.
        window_cycles = stats.get("completion_time")
        if not isinstance(window_cycles, int) \
                or isinstance(window_cycles, bool):
            window_cycles = stats.get("completion_cycles")

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
                          raw_evidence_digest=eref.sha256,
                          stats_digest=artifact.stats_sha256,
                          network_traffic_window={
                              "window_cycles": window_cycles,
                              "wall_time_ns": None,
                              "cycles_only": True},
                          metrics=metrics,
                          run_dir=str(run_dir),
                          evidence_path=eref.path,
                          attempt_path=attempt_ref.path,
                          attempt_digest=attempt_ref.sha256,
                          realization_digest=realization_digest)

        # ── verified performance (window event only — no per-op
        #    latency is ever invented) ─────────────────────────────
        try:
            from veritx_dse.core.artifact import ImmutableError
            from veritx_dse.core.time import QTime
            from veritx_dse.performance.model import (
                ClockDef, ModelError, PerformanceModel, ResourceDef,
                fidelity_warning,
            )
            from veritx_dse.performance.network import (
                NetworkWindowBinding,
            )
            from veritx_dse.performance.result import (
                PerformanceEventGraph, ResultError,
                build_performance_result,
            )
            from veritx_dse.performance.scheduler import (
                SchedulerError, schedule_workload,
            )
            from veritx_dse.performance.workload import (
                EVENT_NETWORK_TRAFFIC_WINDOW, TemporalEvent,
                TemporalWorkload, WorkloadError,
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
                "evidence_sha256": eref.sha256,
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
            warning = fidelity_warning(model)
        except (ResultError, TimeError, ModelError, WorkloadError,
                SchedulerError, ImmutableError, ArtifactError,
                ControlPlaneError) as exc:
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
                          raw_evidence_digest=eref.sha256,
                          stats_digest=artifact.stats_sha256,
                          network_traffic_window={
                              "window_cycles": window_cycles,
                              "wall_time_ns": None,
                              "cycles_only": True},
                          metrics=metrics,
                          run_dir=str(run_dir),
                          evidence_path=eref.path,
                          attempt_path=attempt_ref.path,
                          attempt_digest=attempt_ref.sha256,
                          realization_digest=realization_digest)
        # ── verified boundary (the wrapper is the only input
        #    RequirementEvaluator accepts; a stale resource_id is not
        #    authentication) ─────────────────────────────────────────
        try:
            verified_perf = verify_performance_result(perf,
                                                      workload=temporal)
        except ArtifactError as exc:
            return refuse(FAILED,
                          f"performance verification failed: "
                          f"{type(exc).__name__}: {exc}",
                          message_artifact_id=message_id,
                          physical_traffic_id=traffic_id,
                          backend=STANDALONE_BACKEND,
                          backend_profile=prof,
                          producer_identity=producer.binary_sha256,
                          backend_config_hash=config_hash,
                          backend_input_hash=input_hash,
                          evidence_id=artifact.evidence_id(),
                          raw_evidence_digest=eref.sha256,
                          stats_digest=artifact.stats_sha256,
                          network_traffic_window={
                              "window_cycles": window_cycles,
                              "wall_time_ns": None,
                              "cycles_only": True},
                          metrics=metrics,
                          run_dir=str(run_dir),
                          evidence_path=eref.path,
                          attempt_path=attempt_ref.path,
                          attempt_digest=attempt_ref.sha256,
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
            raw_evidence_digest=eref.sha256,
            stats_digest=artifact.stats_sha256,
            performance_result_id=verified_perf["resource_id"],
            performance_result=verified_perf,
            network_traffic_window={
                "window_cycles": window_cycles,
                "wall_time_ns": wall_ns,
                "cycles_only": False},
            metrics=metrics,
            fidelity_warning=warning,
            reason=None,
            run_dir=str(run_dir),
            evidence_path=eref.path,
            attempt_path=attempt_ref.path,
            attempt_digest=attempt_ref.sha256,
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
