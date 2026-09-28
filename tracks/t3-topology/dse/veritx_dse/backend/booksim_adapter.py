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
from veritx_dse.backend.contracts import BackendConfigArtifact


class BookSimProjectionRefusal(Exception):
    """The canonical traffic/fabric pair is not projectable to BookSim.

    Typed so the evaluator can map a PREPARE refusal to UNSUPPORTED
    without a bare ``except Exception`` — which would swallow bugs into
    a semantic verdict."""


#: the certified model fidelity of standalone BookSim execution
BOOKSIM_MODEL_FIDELITY = ModelFidelity.NETWORK_PACKET_SIMULATION


@dataclass(frozen=True)
class BookSimExecutionResult:
    """The backend-native result: the execution record plus the pinned
    producer identity the evidence chain must bind."""

    record: Any
    producer: Any


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
        lowering is multi-class, V2 with the asserted class when it is
        single-class — then admit every class against the compiled VC
        assignment (before spawn; never silent VC0)."""
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
                logical = LogicalMessageArtifactV2(
                    workload, traffic_class=traffic_class or expected_class)
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
                f"traffic-class admission refused: {exc}") from exc
        return logical, physical

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
        logical, physical = self._canonical_traffic(
            context, traffic_class=traffic_class)
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
            BOOKSIM_BUILD_RECIPE_VERSION, execute_prepared_booksim,
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
        record = execute_prepared_booksim(
            prepared=native.prepared, binary=bin_path,
            run_dir=Path(options.run_dir) / "run",
            timeout=options.timeout, seed=options.seed,
            repo_root=repo_root, write=True,
            require_pinned_producer=True,
            require_manifest_recipe=BOOKSIM_BUILD_RECIPE_VERSION)
        return BookSimExecutionResult(record=record, producer=producer)


__all__ = [
    "BOOKSIM_MODEL_FIDELITY", "BookSimAdapter", "BookSimExecutionResult",
    "BookSimPreparation", "BookSimProjectionRefusal",
]
