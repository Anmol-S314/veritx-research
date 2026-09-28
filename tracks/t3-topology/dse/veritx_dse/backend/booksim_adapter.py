"""The standalone-BookSim backend adapter.

Federation Commit 05: the BookSim-specific core of the certified
evaluator (canonical traffic artifacts → VC admission → projection →
prepared input → pinned producer → qualified execution), orchestrated
through the federation contracts. Every projection/execution/evidence
authority is REUSED, never copied. Refusal strings are byte-identical
to the pre-adapter evaluator: the characterization suite
(``test_federation_booksim_baseline.py``) freezes them.
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
    BackendAdapter, BackendAssessment, BackendCapability, ModelFidelity,
    PreparedExecution, SupportLevel,
)


class BookSimProjectionRefusal(Exception):
    """The canonical traffic/fabric pair is not projectable to BookSim.

    Typed so the evaluator can map a PREPARE refusal to UNSUPPORTED
    without a bare ``except Exception`` — which would swallow bugs into
    a semantic verdict. Carries the message/traffic artifact identities
    when those artifacts were constructed before the gate refused, so a
    refusal outcome can bind exactly which traffic was refused."""

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


class BookSimAdapter:
    """Orchestrates the certified standalone-BookSim execution chain.

    Supports exactly NETWORK_COMPLETION at NETWORK_PACKET_SIMULATION
    fidelity. Assessment re-runs the same canonical gates the evaluator
    always applied (artifact construction, VC admission, projection) —
    a SUPPORTED assessment means those gates passed on this context,
    not merely that the backend exists.
    """

    def __init__(self) -> None:
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
            self._canonical_traffic(context)
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
        return BackendAssessment(
            backend_id=self.backend_id, question=question,
            support=SupportLevel.SUPPORTED,
            readiness=BackendReadiness.READY,
            fidelity=BOOKSIM_MODEL_FIDELITY,
            qualification_profile="CERTIFIED_BOOKSIM",
            reason=None,
            required_parents=self._required_parents(),
            limitations=self._capabilities[0].limitations)

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

        The asserted class is the EVAL-TIME CONTRACT: a single-class
        caller MUST pass the lowered class (assertion, never a label);
        omitting it is a caller bug, not something to silently repair
        with the lowered value.
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

    def prepare(
        self,
        context: CanonicalEvaluationContext,
        question: EvaluationQuestion,
        *,
        traffic_class: str | None = None,
    ) -> BookSimPreparation:
        if question is not EvaluationQuestion.NETWORK_COMPLETION:
            raise BookSimProjectionRefusal(
                "standalone BookSim answers NETWORK_COMPLETION only")
        # gate ORDER is the pre-adapter law: construct artifacts (ids
        # exist), admit classes, THEN assert the intent class — so a
        # refused outcome always binds the traffic identities it refused.
        logical, physical = self._canonical_traffic(
            context, traffic_class=traffic_class)
        self._assert_intent_class(context, traffic_class,
                                  logical=logical, physical=physical)
        from veritx_dse.backend.booksim_projection import (
            BookSimProjectionParents, prepare_booksim_input,
        )
        from veritx_dse.model.vc_resource import (
            vc_resources_from_assignment,
        )
        bundle = context.bundle
        parents = BookSimProjectionParents(
            resolved_fabric=bundle.resolved_fabric,
            topology=bundle.topology,
            attachment=bundle.attachment, mapping=bundle.mapping,
            vc_resource=vc_resources_from_assignment(
                bundle.vc_assignment),
            vc_assignment=bundle.vc_assignment,
            packet_format=bundle.packet_format,
            route=bundle.router_route,
            physical_traffic=physical)
        try:
            prepared = prepare_booksim_input(parents)
        except Exception as exc:
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
            execute_prepared_booksim,
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
        bin_path = Path(options.binary)
        repo_root = Path(options.repo_root)
        producer = resolve_producer_identity(
            bin_path, repo_root=repo_root,
            require_manifest_recipe=BOOKSIM_BUILD_RECIPE_VERSION)
        # The certified path never accepts an unpinned producer: a binary
        # whose build manifest does not verify against the canonical
        # recipe cannot produce certified evidence.
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


__all__ = [
    "BOOKSIM_MODEL_FIDELITY", "BookSimAdapter", "BookSimExecutionResult",
    "BookSimPreparation", "BookSimProjectionRefusal",
]
