"""The standalone-BookSim backend adapter.

Rationale: docs/decisions/modules/backend.md
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from types import SimpleNamespace as _NS
from typing import Any

from veritx_dse.application.evaluation_context import (
    CanonicalEvaluationContext,
)
from veritx_dse.application.evaluation_question import EvaluationQuestion
from veritx_dse.backend.adapter import (
    BackendAdapter, BackendAssessment, BackendCapability, BackendReadiness,
    ModelFidelity, PreparedExecution, SupportLevel,
)


class BookSimProjectionRefusal(Exception):
    """The canonical traffic/fabric pair is not projectable to BookSim.

Rationale: docs/decisions/modules/backend.md
    """

    def __init__(self, reason: str, *,
                 message_artifact_id: str | None = None,
                 physical_traffic_id: str | None = None) -> None:
        super().__init__(reason)
        self.message_artifact_id = message_artifact_id
        self.physical_traffic_id = physical_traffic_id


#: the certified model fidelity of standalone BookSim execution
BOOKSIM_MODEL_FIDELITY = ModelFidelity.NETWORK_PACKET_SIMULATION


@dataclass(frozen=True)
class BookSimExecutionResult:
    """The backend-native result: the execution record plus the pinned
    producer identity the evidence chain must bind."""

    record: Any
    producer: Any


class BookSimExecutionFailure(Exception):
    """The prepared execution failed AFTER the producer was identified.
    Carries the producer identity so a FAILED outcome can still bind
    which binary ran — the pre-adapter evaluator always did."""

    def __init__(self, message: str, *, producer: Any) -> None:
        super().__init__(message)
        self.producer = producer


@dataclass(frozen=True)
class BookSimPreparation:
    """What prepare() hands to execute() — the native prepared input plus
    the identity fields the evaluator's outcome binds."""

    prepared: Any
    physical_traffic: Any
    message_artifact_id: str
    physical_traffic_id: str
    profile_id: str
    config_hash: str
    input_hash: str
    realization_digest: str


def _check_booksim_evidence_binding(
    evidence: Any, *,
    message_artifact_id: str | None,
    physical_traffic_id: str | None,
    config_hash: str | None,
    input_hash: str | None,
    realization_digest: str | None,
    resolved_fabric_hash: str,
) -> None:
    """Anti-transplant: persisted evidence must claim exactly the
    preparation (and fabric) it is normalized against.

Rationale: docs/decisions/modules/backend.md
    """
    from veritx_dse.backend.evidence import BackendEvidenceError

    def _require(name: str, claimed: Any, bound: Any) -> None:
        if bound is None:
            raise BackendEvidenceError(
                f"cannot normalize BookSim evidence: the {name} this "
                f"run binds is absent — refusing an unbound "
                f"normalization")
        if claimed != bound:
            raise BackendEvidenceError(
                f"native evidence {name} {claimed!r} does not match "
                f"the prepared {name} {bound!r} — refusing a "
                f"transplanted normalization")

    _require("prepared_id", evidence.prepared_id, realization_digest)
    _require("config_sha256", evidence.config_sha256, config_hash)
    _require("trace_sha256", evidence.trace_sha256, input_hash)
    _require("message_artifact_id", evidence.message_artifact_id,
             message_artifact_id)
    _require("physical_traffic_id", evidence.physical_traffic_id,
             physical_traffic_id)
    _require("resolved_fabric_hash", evidence.resolved_fabric_hash,
             resolved_fabric_hash)


class BookSimAdapter:
    """Orchestrates the certified standalone-BookSim execution chain.

Rationale: docs/decisions/modules/backend.md
    """

    def __init__(
        self,
        *,
        binary: str | Path | None = None,
        repo_root: str | Path | None = None,
    ) -> None:
        self._binary = Path(binary) if binary is not None else None
        self._repo_root = Path(repo_root) if repo_root is not None else None
        self._capabilities: tuple[BackendCapability, ...] = (
            BackendCapability(
                question=EvaluationQuestion.NETWORK_COMPLETION,
                support=SupportLevel.SUPPORTED,
                fidelity=BOOKSIM_MODEL_FIDELITY,
                limitations=(
                    "network packet simulation only: cycles are the "
                    "canonical projection's completion window, never "
                    "end-to-end workload runtime",)),
        )

    @property
    def backend_id(self) -> str:
        return "BOOKSIM_STANDALONE"

    def capabilities(self) -> tuple[BackendCapability, ...]:
        return self._capabilities

    # ── assessment: the canonical gates, unchanged ────────────────────

    def assess(
        self,
        context: CanonicalEvaluationContext,
        question: EvaluationQuestion,
    ) -> BackendAssessment:
        if question is not EvaluationQuestion.NETWORK_COMPLETION:
            return BackendAssessment(
                backend_id=self.backend_id, question=question,
                support=SupportLevel.UNSUPPORTED,
                readiness=BackendReadiness.BLOCKED,
                fidelity=BOOKSIM_MODEL_FIDELITY,
                qualification_profile=None,
                reason="standalone BookSim answers NETWORK_COMPLETION only",
                required_parents=self._required_parents(),
                limitations=self._capabilities[0].limitations)
        try:
            # the assess gate asserts the lowered intent's own class —
            # an assertion against the context, never a relabel
            _logical, physical = self._canonical_traffic(
                context, traffic_class=context.unified_traffic_class)
            self._select_profile(context, physical)
        except BookSimProjectionRefusal as exc:
            return BackendAssessment(
                backend_id=self.backend_id, question=question,
                support=SupportLevel.UNSUPPORTED,
                readiness=BackendReadiness.BLOCKED,
                fidelity=BOOKSIM_MODEL_FIDELITY,
                qualification_profile=None,
                reason=str(exc),
                required_parents=self._required_parents(),
                limitations=self._capabilities[0].limitations)
        try:
            bin_path = self._resolve_binary()
        except FileNotFoundError as exc:
            return BackendAssessment(
                backend_id=self.backend_id, question=question,
                support=SupportLevel.SUPPORTED,
                readiness=BackendReadiness.UNAVAILABLE,
                fidelity=BOOKSIM_MODEL_FIDELITY,
                qualification_profile=None,
                reason=f"BookSim producer absent: {exc}",
                required_parents=self._required_parents(),
                limitations=self._capabilities[0].limitations)
        from veritx_dse.backend.booksim_execution import (
            BOOKSIM_BUILD_RECIPE_VERSION,
        )
        from veritx_dse.backend.producer import (
            ProducerError, assert_pinned_producer,
            resolve_producer_identity,
        )
        try:
            producer = resolve_producer_identity(
                bin_path, repo_root=self._repo_root_or_default(),
                require_manifest_recipe=BOOKSIM_BUILD_RECIPE_VERSION)
        except ProducerError as exc:
            return BackendAssessment(
                backend_id=self.backend_id, question=question,
                support=SupportLevel.SUPPORTED,
                readiness=BackendReadiness.BLOCKED,
                fidelity=BOOKSIM_MODEL_FIDELITY,
                qualification_profile=None,
                reason=f"BookSim producer not qualified: {exc}",
                required_parents=self._required_parents(),
                limitations=self._capabilities[0].limitations)
        try:
            assert_pinned_producer(producer)
        except ProducerError as exc:
            return BackendAssessment(
                backend_id=self.backend_id, question=question,
                support=SupportLevel.SUPPORTED,
                readiness=BackendReadiness.BLOCKED,
                fidelity=BOOKSIM_MODEL_FIDELITY,
                qualification_profile=None,
                reason=f"BookSim producer not pinned: {exc}",
                required_parents=self._required_parents(),
                limitations=self._capabilities[0].limitations)
        return BackendAssessment(
            backend_id=self.backend_id, question=question,
            support=SupportLevel.SUPPORTED,
            readiness=BackendReadiness.READY,
            fidelity=BOOKSIM_MODEL_FIDELITY,
            qualification_profile="CERTIFIED_BOOKSIM",
            reason=None,
            required_parents=self._required_parents(),
            limitations=self._capabilities[0].limitations)

    def _repo_root_or_default(self) -> Path:
        if self._repo_root is not None:
            return self._repo_root
        from veritx_dse.core.paths import REPO as _REPO
        return Path(_REPO)

    def _resolve_binary(self) -> Path:
        """The BookSim executable: explicit configuration first, else the
        canonical discovery. Absence is FileNotFoundError (UNAVAILABLE),
        never a semantic verdict."""
        if self._binary is not None:
            if not self._binary.is_file():
                raise FileNotFoundError(
                    f"explicit BookSim binary absent: {self._binary}")
            return self._binary
        from veritx_dse.simulation.booksim import find_booksim_bin
        return find_booksim_bin(self._repo_root_or_default())

    def _required_parents(self) -> tuple[str, ...]:
        return ("design", "resolved_fabric", "workload",
                "message_artifact", "physical_traffic")

    # ── prepare: canonical artifacts + admission + projection ─────────

    def _canonical_traffic(
            self, context: CanonicalEvaluationContext,
            *, traffic_class: str | None = None) -> tuple[Any, Any]:
        """Build the canonical message/traffic artifacts EXACTLY as the
        pre-adapter evaluator did: V3 per-message classes when the
        lowering is multi-class, V2 with the ASSERTED class when it is
        single-class — then admit every class against the compiled VC
        assignment (before spawn; never silent VC0).

Rationale: docs/decisions/modules/backend.md
        """
        from veritx_dse.application.fabric_evaluator import (
            VCAdmissionError, _admit_traffic_classes,
        )
        from veritx_dse.core.errors import (
            ConservationFailed, EvidenceInvalid, InvalidInput,
            MappingInvalid, UnsupportedSchedule, UnsupportedSemantics,
        )
        from veritx_dse.workload.messages import (
            LogicalMessageArtifactV2, LogicalMessageArtifactV3,
        )
        from veritx_dse.workload.traffic import (
            PhysicalTrafficArtifactV2, PhysicalTrafficArtifactV3,
        )
        workload = context.workload
        expected_class = context.unified_traffic_class
        try:
            if expected_class is None:
                logical = LogicalMessageArtifactV3(
                    graph=workload,
                    traffic_class_by_operation=(
                        context.lowered_workload.traffic_class_by_operation))
                physical = PhysicalTrafficArtifactV3(
                    logical=logical,
                    resolved_fabric=context.bundle.resolved_fabric,
                    mapping=context.bundle.mapping,
                    attachment=context.bundle.attachment,
                    inventory=context.bundle.inventory,
                    packet_format=context.bundle.packet_format)
            else:
                if traffic_class is None:
                    raise BookSimProjectionRefusal(
                        "single-class evaluation must assert the lowered "
                        "traffic class (the intent owns class names; "
                        "evaluation only asserts them)")
                logical = LogicalMessageArtifactV2(
                    workload, traffic_class=traffic_class)
                physical = PhysicalTrafficArtifactV2(
                    logical=logical,
                    resolved_fabric=context.bundle.resolved_fabric,
                    mapping=context.bundle.mapping,
                    attachment=context.bundle.attachment,
                    inventory=context.bundle.inventory,
                    packet_format=context.bundle.packet_format)
        except (UnsupportedSemantics, UnsupportedSchedule) as exc:
            raise BookSimProjectionRefusal(
                f"workload semantics unprojectable: {exc}") from exc
        except (InvalidInput, EvidenceInvalid, MappingInvalid,
                ConservationFailed) as exc:
            raise BookSimProjectionRefusal(
                f"workload lowering failed: {type(exc).__name__}: {exc}") \
                from exc
        try:
            _admit_traffic_classes(logical, context.bundle)
        except VCAdmissionError as exc:
            raise BookSimProjectionRefusal(
                f"traffic-class admission refused: {exc}",
                message_artifact_id=logical.message_artifact_id(),
                physical_traffic_id=physical.physical_traffic_id()) from exc
        return logical, physical

    def _assert_intent_class(
            self, context: CanonicalEvaluationContext,
            traffic_class: str | None, *, logical: Any,
            physical: Any) -> None:
        """The intent-class assertion (semantics outside workload_id):
        relabeling at eval time is refused. Multi-class lowerings assert
        nothing globally — their classes are per-message, admitted above."""
        expected_class = context.unified_traffic_class
        if expected_class is not None and traffic_class != expected_class:
            raise BookSimProjectionRefusal(
                f"evaluation traffic class {traffic_class!r} does "
                f"not match the lowered intent class {expected_class!r}: "
                f"eval-time relabeling is refused (the intent owns class "
                f"names; evaluation only asserts them)",
                message_artifact_id=logical.message_artifact_id(),
                physical_traffic_id=physical.physical_traffic_id())

    def _projection_parents(
            self, context: CanonicalEvaluationContext,
            physical: Any) -> Any:
        """The certified projection parents for this context — the same
        object preparation consumes. Profile selection over these is a
        semantic gate shared by assess() and prepare()."""
        from veritx_dse.backend.booksim_projection import (
            BookSimProjectionParents,
        )
        from veritx_dse.model.vc_resource import (
            vc_resources_from_assignment,
        )
        bundle = context.bundle
        return BookSimProjectionParents(
            resolved_fabric=bundle.resolved_fabric,
            topology=bundle.topology,
            attachment=bundle.attachment, mapping=bundle.mapping,
            vc_resource=vc_resources_from_assignment(
                bundle.vc_assignment),
            vc_assignment=bundle.vc_assignment,
            packet_format=bundle.packet_format,
            route=bundle.router_route,
            physical_traffic=physical)

    def _select_profile(
            self, context: CanonicalEvaluationContext,
            physical: Any) -> str:
        """The certified profile for this fabric, or a typed refusal."""
        from veritx_dse.backend.booksim_projection import (
            BookSimProjectionError, select_booksim_profile,
        )
        try:
            return select_booksim_profile(
                self._projection_parents(context, physical)).profile_id
        except BookSimProjectionError as exc:
            raise BookSimProjectionRefusal(
                f"{type(exc).__name__}: {exc}") from exc

    def _prepare_native(
        self,
        context: CanonicalEvaluationContext,
        question: EvaluationQuestion,
        *,
        traffic_class: str | None = None,
    ) -> BookSimPreparation:
        """The backend-native preparation: canonical artifacts + admission
        + projection. Only KNOWN semantic/projection failures become a
        refusal — programming bugs escape and fail tests, never a
        semantic verdict."""
        if question is not EvaluationQuestion.NETWORK_COMPLETION:
            raise BookSimProjectionRefusal(
                "standalone BookSim answers NETWORK_COMPLETION only")
        logical, physical = self._canonical_traffic(
            context, traffic_class=traffic_class)
        self._assert_intent_class(context, traffic_class,
                                  logical=logical, physical=physical)
        from veritx_dse.backend.booksim_projection import (
            BookSimProjectionError, prepare_booksim_input,
        )
        from veritx_dse.core.errors import (
            ConservationFailed, EvidenceInvalid, InvalidInput,
            MappingInvalid, UnsupportedSchedule, UnsupportedSemantics,
        )
        parents = self._projection_parents(context, physical)
        try:
            prepared = prepare_booksim_input(parents)
        except (BookSimProjectionError, InvalidInput, EvidenceInvalid,
                MappingInvalid, ConservationFailed, UnsupportedSemantics,
                UnsupportedSchedule) as exc:
            raise BookSimProjectionRefusal(
                f"{type(exc).__name__}: {exc}") from exc
        from veritx_dse.backend.booksim_execution import (
            CONFIG_FILE, TRACE_FILE, prepared_file_digests,
        )
        digests = prepared_file_digests(prepared)
        return BookSimPreparation(
            prepared=prepared, physical_traffic=physical,
            message_artifact_id=logical.message_artifact_id(),
            physical_traffic_id=physical.physical_traffic_id(),
            profile_id=prepared.profile_id,
            config_hash=digests[CONFIG_FILE],
            input_hash=digests[TRACE_FILE],
            realization_digest=prepared.prepared_id())

    def prepare(
        self,
        context: CanonicalEvaluationContext,
        question: EvaluationQuestion,
        **kwargs: object,
    ) -> PreparedExecution:
        """The federation seam: native preparation wrapped in the generic
        ``PreparedExecution``. No duplicate BackendConfigArtifact /
        BackendInputManifest is manufactured to fill fields the BookSim
        projection does not naturally expose — those stay None while the
        native preparation carries the real identities."""
        traffic_class = kwargs.get("traffic_class")
        if traffic_class is not None and not isinstance(traffic_class, str):
            raise BookSimProjectionRefusal(
                f"traffic_class must be a string, got "
                f"{type(traffic_class).__name__}")
        native = self._prepare_native(
            context, question,
            traffic_class=traffic_class)  # type: ignore[arg-type]
        return PreparedExecution(
            backend_id=self.backend_id,
            projection_identity=native.realization_digest,
            qualification_identity=native.profile_id,
            backend_config=None, backend_input=None, producer=None,
            native_prepared=native)

    # ── execute: pinned producer + qualified execution ────────────────

    def execute(
        self,
        prepared: PreparedExecution,
        options: object,
    ) -> Any:
        """Run the prepared input under a pinned producer.

        ``options`` is the evaluator's own namespace (binary, run_dir,
        timeout, seed, repo_root) — the backend-native execution options;
        migrating them into a generic dataclass is deliberately NOT this
        commit. Returns the ``ExecutionRecord`` unchanged.
        """
        from veritx_dse.backend.booksim_execution import (
            BOOKSIM_BUILD_RECIPE_VERSION,
        )
        from veritx_dse.backend.booksim_execution import (
            BookSimExecutionError, execute_prepared_booksim,
        )
        from veritx_dse.backend.producer import (
            ProducerError, assert_pinned_producer,
            resolve_producer_identity,
        )
        native = prepared.native_prepared
        if not isinstance(native, BookSimPreparation):
            raise TypeError(
                f"BookSimAdapter.execute takes a PreparedExecution whose "
                f"native_prepared is a BookSimPreparation, got "
                f"{type(native).__name__}")
        bin_path = Path(options.binary) \
            if getattr(options, "binary", None) is not None \
            else self._resolve_binary()
        repo_root = Path(options.repo_root) \
            if getattr(options, "repo_root", None) is not None \
            else self._repo_root_or_default()
        producer = resolve_producer_identity(
            bin_path, repo_root=repo_root,
            require_manifest_recipe=BOOKSIM_BUILD_RECIPE_VERSION)
        assert_pinned_producer(producer)
        try:
            record = execute_prepared_booksim(
                prepared=native.prepared, binary=bin_path,
                run_dir=Path(options.run_dir) / "run",
                timeout=options.timeout, seed=options.seed,
                repo_root=repo_root, write=True,
                require_pinned_producer=True,
                require_manifest_recipe=BOOKSIM_BUILD_RECIPE_VERSION)
        except BookSimExecutionError as exc:
            raise BookSimExecutionFailure(
                f"{type(exc).__name__}: {exc}",
                producer=producer) from exc
        return BookSimExecutionResult(record=record, producer=producer)

    # ── normalize: authenticated evidence into the common envelope ───

    def normalize(
        self,
        context: CanonicalEvaluationContext,
        question: EvaluationQuestion,
        prepared: PreparedExecution,
        native_result: object,
    ) -> NormalizedBackendEvidence:
        """Project the authenticated native evidence into the normalized
        envelope. Re-reads the persisted bytes through the canonical
        reader and admits them for certified product use — normalization
        never invents metrics, and never invents wall time."""
        from veritx_dse.backend.normalized_evidence import (
            MetricValue, NormalizedBackendEvidence,
        )
        if question is not EvaluationQuestion.NETWORK_COMPLETION:
            raise BookSimProjectionRefusal(
                "standalone BookSim answers NETWORK_COMPLETION only")
        native = prepared.native_prepared
        if not isinstance(native, BookSimPreparation):
            raise TypeError(
                f"BookSimAdapter.normalize takes a PreparedExecution "
                f"whose native_prepared is a BookSimPreparation, got "
                f"{type(native).__name__}")
        if not isinstance(native_result, BookSimExecutionResult):
            raise TypeError(
                f"BookSimAdapter.normalize takes a "
                f"BookSimExecutionResult, got "
                f"{type(native_result).__name__}")
        from veritx_dse.backend.evidence import (
            ScientificBackendEvidence, admit_for_certified_product,
            read_verified_evidence, validate_evidence_document,
        )
        persisted = read_verified_evidence(native_result.record.ref)
        if not isinstance(persisted.get("evidence"), dict):
            from veritx_dse.backend.evidence import BackendEvidenceError
            raise BackendEvidenceError(
                "persisted evidence wrapper carries no scientific "
                "evidence document")
        verified_doc = validate_evidence_document(persisted["evidence"])
        evidence = ScientificBackendEvidence.from_dict(verified_doc)
        admit_for_certified_product(evidence)
        _resolved = context.bundle.resolved_fabric.resolved_fabric_hash
        resolved_hash = _resolved() if callable(_resolved) else _resolved
        _check_booksim_evidence_binding(
            evidence,
            message_artifact_id=native.message_artifact_id,
            physical_traffic_id=native.physical_traffic_id,
            config_hash=native.config_hash,
            input_hash=native.input_hash,
            realization_digest=native.realization_digest,
            resolved_fabric_hash=resolved_hash)
        metrics: list[MetricValue] = []
        for key, value in evidence.stats.items():
            if isinstance(value, bool):
                continue
            if isinstance(value, int):
                metrics.append(MetricValue(
                    key=key, value=float(value), unit=None,
                    source_metric_key=key))
            elif isinstance(value, float):
                if value == value and abs(value) != float("inf"):
                    metrics.append(MetricValue(
                        key=key, value=value, unit=None,
                        source_metric_key=key))
        return NormalizedBackendEvidence(
            backend_id=self.backend_id, question=question,
            model_fidelity=BOOKSIM_MODEL_FIDELITY,
            canonical_parent_ids=(
                context.design_hash, resolved_hash,
                context.workload_id,
                native.message_artifact_id,
                native.physical_traffic_id),
            native_evidence_id=evidence.evidence_id(),
            qualification=evidence.execution_fidelity,
            producer_identity=evidence.binary_sha256,
            backend_config_hash=native.config_hash,
            backend_input_hash=native.input_hash,
            metrics=tuple(metrics),
            limitations=self._capabilities[0].limitations)


def normalize_booksim_outcome(
    context: CanonicalEvaluationContext,
    outcome: Any,
) -> NormalizedBackendEvidence:
    """Normalize the authenticated resulting outcome of the certified
    FabricEvaluator — the federated path that must NOT construct a
    second BookSim evidence chain.

Rationale: docs/decisions/modules/backend.md
    """
    from veritx_dse.backend.normalized_evidence import (
        MetricValue, NormalizedBackendEvidence,
    )
    if getattr(outcome, "status", None) != "EVALUATED":
        raise BookSimProjectionRefusal(
            f"only an EVALUATED BookSim outcome normalizes, got "
            f"{getattr(outcome, 'status', None)!r}")
    from veritx_dse.backend.evidence import (
        BackendEvidenceError, admit_normalize_bare_evidence,
    )
    evidence_path = getattr(outcome, "evidence_path", None)
    if not evidence_path:
        raise BackendEvidenceError(
            "the BookSim outcome carries no evidence path; refusing to "
            "normalize an outcome without persisted evidence")
    producer_sha = getattr(outcome, "producer_identity", None)
    if not producer_sha:
        raise BackendEvidenceError(
            "the BookSim outcome names no producer identity; refusing "
            "to normalize evidence without a bound producer")
    sealed = getattr(outcome, "raw_evidence_digest", None)
    if not sealed:
        raise BackendEvidenceError(
            "the BookSim outcome names no sealed evidence digest; "
            "refusing to normalize evidence without a digest binding")
    evidence = admit_normalize_bare_evidence(
        Path(evidence_path),
        expected_sha256=sealed,
        prepared_id=getattr(outcome, "realization_digest", None),
        config_sha256=getattr(outcome, "backend_config_hash", None),
        trace_sha256=getattr(outcome, "backend_input_hash", None),
        binary_sha256=producer_sha)
    if outcome.design_hash != context.design_hash:
        raise BackendEvidenceError(
            f"BookSim outcome design_hash {outcome.design_hash!r} does "
            f"not match this context {context.design_hash!r} — "
            f"refusing a transplanted normalization")
    if outcome.workload_id != context.workload_id:
        raise BackendEvidenceError(
            f"BookSim outcome workload_id {outcome.workload_id!r} does "
            f"not match this context {context.workload_id!r} — "
            f"refusing a transplanted normalization")
    _outcome_resolved = context.bundle.resolved_fabric.resolved_fabric_hash
    _outcome_resolved_hash = _outcome_resolved() \
        if callable(_outcome_resolved) else _outcome_resolved
    if outcome.resolved_fabric_hash != _outcome_resolved_hash:
        raise BackendEvidenceError(
            "BookSim outcome resolved_fabric_hash does not match this "
            "context — refusing a transplanted normalization")
    _check_booksim_evidence_binding(
        evidence,
        message_artifact_id=outcome.message_artifact_id,
        physical_traffic_id=outcome.physical_traffic_id,
        config_hash=outcome.backend_config_hash,
        input_hash=outcome.backend_input_hash,
        realization_digest=outcome.realization_digest,
        resolved_fabric_hash=_outcome_resolved_hash)
    metrics: list[MetricValue] = []
    stats = outcome.metrics or {}
    for key, value in stats.items():
        if isinstance(value, bool):
            continue
        if isinstance(value, int):
            metrics.append(MetricValue(
                key=key, value=float(value), unit=None,
                source_metric_key=key))
        elif isinstance(value, float):
            if value == value and abs(value) != float("inf"):
                metrics.append(MetricValue(
                    key=key, value=value, unit=None,
                    source_metric_key=key))
    _resolved = context.bundle.resolved_fabric.resolved_fabric_hash
    resolved_hash = _resolved() if callable(_resolved) else _resolved
    return NormalizedBackendEvidence(
        backend_id="BOOKSIM_STANDALONE",
        question=EvaluationQuestion.NETWORK_COMPLETION,
        model_fidelity=BOOKSIM_MODEL_FIDELITY,
        canonical_parent_ids=(
            context.design_hash, resolved_hash,
            context.workload_id,
            outcome.message_artifact_id,
            outcome.physical_traffic_id),
        native_evidence_id=evidence.evidence_id(),
        qualification=evidence.execution_fidelity,
        producer_identity=evidence.binary_sha256,
        backend_config_hash=outcome.backend_config_hash,
        backend_input_hash=outcome.backend_input_hash,
        metrics=tuple(metrics),
        limitations=(
            "network packet simulation only: cycles are the "
            "canonical projection's completion window, never "
            "end-to-end workload runtime",))


__all__ = [
    "BOOKSIM_MODEL_FIDELITY", "BookSimAdapter", "BookSimExecutionResult",
    "BookSimPreparation", "BookSimProjectionRefusal",
    "normalize_booksim_outcome",
]
