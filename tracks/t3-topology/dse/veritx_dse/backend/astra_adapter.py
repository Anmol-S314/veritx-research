"""The ASTRA2 embedded-BookSim backend adapter.

Rationale: docs/decisions/modules/backend.md
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from veritx_dse.application.evaluation_context import (
    CanonicalEvaluationContext,
)
from veritx_dse.application.evaluation_question import EvaluationQuestion
from veritx_dse.backend.adapter import (
    BackendAdapter, BackendAssessment, BackendCapability, BackendReadiness,
    ModelFidelity, PreparedExecution, SupportLevel,
)

ASTRA2_MODEL_FIDELITY = ModelFidelity.SYSTEM_SIMULATION

ASTRA2_QUESTIONS = (
    EvaluationQuestion.SYSTEM_MAKESPAN,
    EvaluationQuestion.COMMUNICATION_EXPOSURE,
    EvaluationQuestion.PER_RANK_COMPLETION,
)

ASTRA_NORMALIZED_METRICS: dict[EvaluationQuestion, tuple] = {
    EvaluationQuestion.SYSTEM_MAKESPAN: (
        ("system_makespan_cycles", "cycles", True),
    ),
    EvaluationQuestion.COMMUNICATION_EXPOSURE: (
        ("communication_exposure_cycles", "cycles", True),
    ),
    EvaluationQuestion.PER_RANK_COMPLETION: (
        ("completion_cycles", "cycles", False),
        ("exposed_communication_cycles", "cycles", False),
    ),
}

class Astra2SemanticRefusal(ValueError):
    """The workload has no representation on the qualified ASTRA path.

Rationale: docs/decisions/modules/backend.md
    """

@dataclass(frozen=True)
class ProducerPin:
    """The pinned runtime producer bound at execution time.

Rationale: docs/decisions/modules/backend.md
    """

    binary_sha256: str
    binary_size: int
    source_revision: str | None
    dirty: bool | None
    build_manifest_sha256: str | None
    build_recipe_version: str | None

@dataclass(frozen=True)
class Astra2Preparation:
    """The native prepared structures plus the federation identities.

Rationale: docs/decisions/modules/backend.md
    """

    workload_projection: Any
    machine: Any
    namespace: Any
    workload_projection_id: str
    machine_id: str
    prepared_id: str
    standalone_config_sha256: str
    embedded_fabric_abi_version: str
    rank_to_endpoint: tuple[tuple[int, int], ...]
    collective_binding: Any = None
    producer_pin: ProducerPin | None = None

def _check_astra_evidence_binding(evidence: Any, native: Any) -> None:
    """Anti-transplant: runtime evidence must claim exactly the
    machine, workload projection and namespace preparation bound —
    the same identities reproduction re-verifies before re-execution.
    A mismatch is evidence corruption, never normalized."""
    from veritx_dse.backend.astra_execution import AstraExecutionError

    def _require(name: str, claimed: Any, bound: Any) -> None:
        if claimed != bound:
            raise AstraExecutionError(
                f"native ASTRA evidence {name} {claimed!r} does not "
                f"match the prepared {name} {bound!r} — refusing a "
                f"transplanted normalization")

    _require("machine_id", evidence.machine_id,
             native.machine.machine_id())
    _require("workload_projection_id",
             evidence.workload_projection_id,
             native.workload_projection.projection_id())
    _require("namespace_id", evidence.namespace_id,
             native.namespace.namespace_id())
    _require("prepared_id", evidence.prepared_id, native.prepared_id)
    _require("rank_to_endpoint",
             tuple(tuple(pair) for pair in evidence.rank_to_endpoint),
             tuple(tuple(pair) for pair in native.rank_to_endpoint))

class Astra2Adapter:
    """Orchestrates workload → machine → execution → runtime evidence.

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
        self._capabilities: tuple[BackendCapability, ...] = tuple(
            BackendCapability(
                question=question,
                support=SupportLevel.SUPPORTED,
                fidelity=ASTRA2_MODEL_FIDELITY,
                limitations=(
                    "system simulation: cycles are the projected machine's "
                    "makespan/exposure window, never end-to-end workload "
                    "runtime",
                    "collective-mode execution only: the qualified path "
                    "delegates collective expansion to ASTRA "
                    "(et_granularity=collectives); SEND/RECV message-mode "
                    "operations refuse rather than execute unqualified",
                    "multi-class collective communication (V3 artifact) "
                    "only where the embedded runtime proves class-aware "
                    "injection; otherwise explicit refusal, never "
                    "flattening",
                ))
            for question in ASTRA2_QUESTIONS)

    @property
    def backend_id(self) -> str:
        return "ASTRA2_EMBEDDED_BOOKSIM"

    def capabilities(self) -> tuple[BackendCapability, ...]:
        return self._capabilities

    def _repo_root_or_default(self) -> Path | None:
        return self._repo_root

    def _resolve_binary(self) -> Path | None:
        """The ASTRA runtime: explicit configuration first, else the
        canonical resolver. None means absent (UNAVAILABLE), never
        UNSUPPORTED."""
        if self._binary is not None:
            return self._binary if self._binary.is_file() else None
        from veritx_dse.backend.astra import resolve_runtime_binary
        return resolve_runtime_binary()

    def assess(
        self,
        context: CanonicalEvaluationContext,
        question: EvaluationQuestion,
    ) -> BackendAssessment:
        limitation_bundle = self._capabilities[0].limitations
        if question not in ASTRA2_QUESTIONS:
            return BackendAssessment(
                backend_id=self.backend_id, question=question,
                support=SupportLevel.UNSUPPORTED,
                readiness=BackendReadiness.BLOCKED,
                fidelity=ASTRA2_MODEL_FIDELITY,
                qualification_profile=None,
                reason="ASTRA2 answers system-level questions only: "
                f"{[q.value for q in ASTRA2_QUESTIONS]}",
                required_parents=self._required_parents(),
                limitations=limitation_bundle)
        try:
            self.prepare(context, question)
        except AstraUnavailable as exc:
            return BackendAssessment(
                backend_id=self.backend_id, question=question,
                support=SupportLevel.CONDITIONAL,
                readiness=BackendReadiness.UNAVAILABLE,
                fidelity=ASTRA2_MODEL_FIDELITY,
                qualification_profile=None,
                reason=str(exc),
                required_parents=self._required_parents(),
                limitations=limitation_bundle)
        except _SEMANTIC_REFUSALS as exc:
            return BackendAssessment(
                backend_id=self.backend_id, question=question,
                support=SupportLevel.UNSUPPORTED,
                readiness=BackendReadiness.BLOCKED,
                fidelity=ASTRA2_MODEL_FIDELITY,
                qualification_profile=None,
                reason=f"{type(exc).__name__}: {exc}",
                required_parents=self._required_parents(),
                limitations=limitation_bundle)
        binary = self._resolve_binary()
        if binary is None:
            return BackendAssessment(
                backend_id=self.backend_id, question=question,
                support=SupportLevel.SUPPORTED,
                readiness=BackendReadiness.UNAVAILABLE,
                fidelity=ASTRA2_MODEL_FIDELITY,
                qualification_profile=None,
                reason="the ASTRA2 runtime binary is absent: the machine "
                "projection exists but cannot execute here",
                required_parents=self._required_parents(),
                limitations=limitation_bundle)
        if not _chakra_staging_available():
            return BackendAssessment(
                backend_id=self.backend_id, question=question,
                support=SupportLevel.SUPPORTED,
                readiness=BackendReadiness.UNAVAILABLE,
                fidelity=ASTRA2_MODEL_FIDELITY,
                qualification_profile=None,
                reason="the Chakra protobuf bindings required to stage "
                "the ASTRA workload are unavailable",
                required_parents=self._required_parents(),
                limitations=limitation_bundle)
        from veritx_dse.backend.astra_execution import (
            AstraExecutionError as _ExecError, resolve_astra_identity,
        )
        from veritx_dse.backend.producer import (
            ProducerError, assert_pinned_producer,
        )
        try:
            identity = resolve_astra_identity(
                binary, repo_root=self._repo_root)
        except _ExecError as exc:
            return BackendAssessment(
                backend_id=self.backend_id, question=question,
                support=SupportLevel.SUPPORTED,
                readiness=BackendReadiness.BLOCKED,
                fidelity=ASTRA2_MODEL_FIDELITY,
                qualification_profile=None,
                reason=f"ASTRA producer not qualified: {exc}",
                required_parents=self._required_parents(),
                limitations=limitation_bundle)
        try:
            assert_pinned_producer(identity)
        except ProducerError as exc:
            return BackendAssessment(
                backend_id=self.backend_id, question=question,
                support=SupportLevel.SUPPORTED,
                readiness=BackendReadiness.BLOCKED,
                fidelity=ASTRA2_MODEL_FIDELITY,
                qualification_profile=None,
                reason=f"ASTRA producer not pinned: {exc}",
                required_parents=self._required_parents(),
                limitations=limitation_bundle)
        return BackendAssessment(
            backend_id=self.backend_id, question=question,
            support=SupportLevel.SUPPORTED,
            readiness=BackendReadiness.READY,
            fidelity=ASTRA2_MODEL_FIDELITY,
            qualification_profile="ASTRA2_EMBEDDED_BOOKSIM",
            reason=None, required_parents=self._required_parents(),
            limitations=limitation_bundle)

    def _required_parents(self) -> tuple[str, ...]:
        return ("design", "resolved_fabric", "workload", "message_artifact",
                "mapping", "attachment", "embedded_booksim_prepared")

    def prepare(
        self,
        context: CanonicalEvaluationContext,
        question: EvaluationQuestion,
        **kwargs: object,
    ) -> PreparedExecution:
        """Semantic projection only — no runtime binary required.

        Returns the generic ``PreparedExecution`` seam; the native
        ``Astra2Preparation`` (real projections retained) rides in
        ``native_prepared`` so ``execute()`` stages the workload itself.
        """
        traffic_class = kwargs.get("traffic_class")
        native = self._prepare_native(
            context, question, traffic_class=traffic_class)  # type: ignore[arg-type]
        return PreparedExecution(
            backend_id=self.backend_id,
            projection_identity=native.workload_projection_id,
            qualification_identity=native.machine_id,
            backend_config=None, backend_input=None, producer=None,
            native_prepared=native)

    def _prepare_native(
        self,
        context: CanonicalEvaluationContext,
        question: EvaluationQuestion,
        *,
        traffic_class: str | None = None,
    ) -> Astra2Preparation:
        if question not in ASTRA2_QUESTIONS:
            raise Astra2SemanticRefusal(
                "ASTRA2 answers system-level questions only: "
                f"{[q.value for q in ASTRA2_QUESTIONS]}")
        from veritx_dse.workload.messages import (
            LogicalMessageArtifactV2, LogicalMessageArtifactV3,
        )

        lowered = context.lowered_workload
        if lowered.unified_traffic_class is None:
            if traffic_class is not None:
                raise Astra2SemanticRefusal(
                    f"evaluation traffic class {traffic_class!r} cannot "
                    "subset a multi-class lowering: eval-time class "
                    "selection would silently drop the other classes")
            logical: Any = LogicalMessageArtifactV3(
                graph=lowered.graph,
                traffic_class_by_operation=
                lowered.traffic_class_by_operation)
        else:
            unified = lowered.unified_traffic_class
            if traffic_class is not None and traffic_class != unified:
                raise Astra2SemanticRefusal(
                    f"evaluation traffic class {traffic_class!r} does "
                    "not match the lowered intent class "
                    f"{unified!r}: eval-time relabeling is refused")
            logical = LogicalMessageArtifactV2(context.workload,
                                               traffic_class=unified)

        self._require_collective_envelope(context.workload)

        bundle = context.bundle
        from veritx_dse.backend.booksim_adapter import (
            BookSimAdapter, BookSimProjectionRefusal,
        )
        from veritx_dse.application.evaluation_question import (
            EvaluationQuestion as _Q,
        )
        booksim = BookSimAdapter()
        try:
            bs_prepared = booksim.prepare(
                context, _Q.NETWORK_COMPLETION,
                traffic_class=traffic_class
                if traffic_class is not None
                else lowered.unified_traffic_class)
        except BookSimProjectionRefusal as exc:
            raise Astra2SemanticRefusal(
                f"embedded BookSim fabric projection refused: {exc}") \
                from exc
        bs_prep = bs_prepared.native_prepared
        from veritx_dse.backend.astra import AstraWorkloadProjection
        projection = AstraWorkloadProjection.build(
            logical=logical,
            resolved_fabric=bundle.resolved_fabric,
            mapping=bundle.mapping, attachment=bundle.attachment,
            et_granularity="collectives")
        from veritx_dse.backend.astra_machine import qualify_astra_machine
        from veritx_dse.backend.booksim_projection import (
            BookSimProjectionParents,
        )
        from veritx_dse.model.vc_resource import (
            vc_resources_from_assignment,
        )
        parents = BookSimProjectionParents(
            resolved_fabric=bundle.resolved_fabric,
            topology=bundle.topology, attachment=bundle.attachment,
            mapping=bundle.mapping,
            vc_resource=vc_resources_from_assignment(bundle.vc_assignment),
            vc_assignment=bundle.vc_assignment,
            packet_format=bundle.packet_format,
            route=bundle.router_route,
            physical_traffic=bs_prep.physical_traffic)
        machine = qualify_astra_machine(
            parents=parents, prepared=bs_prep.prepared,
            projection=projection, logical=logical)

        from veritx_dse.workload.traffic import bind_participants
        binding = bind_participants(
            participant_count=projection.participant_count,
            mapping=bundle.mapping, attachment=bundle.attachment,
            resolved_fabric=bundle.resolved_fabric)
        from veritx_dse.backend.astra_namespace import (
            build_namespace, derive_collective_binding,
        )
        namespace = build_namespace(
            machine=machine, workload=projection, binding=binding,
            endpoint_count=machine.astra_sys_count,
            router_count=machine.router_count)
        collective_binding = derive_collective_binding(
            namespace=namespace, workload=projection)
        return Astra2Preparation(
            workload_projection=projection,
            machine=machine,
            namespace=namespace,
            collective_binding=collective_binding,
            workload_projection_id=projection.projection_id(),
            machine_id=machine.machine_id(),
            prepared_id=machine.prepared_id,
            standalone_config_sha256=machine.standalone_config_sha256,
            embedded_fabric_abi_version=machine.embedded_fabric_abi_version,
            rank_to_endpoint=binding.rank_to_endpoint)

    def _require_collective_envelope(self, workload: Any) -> None:
        """Prove every network-bearing operation is representable through
        the qualified collective-mode path before projecting.

Rationale: docs/decisions/modules/backend.md
        """
        from veritx_dse.backend.astra import (
            _CHAKRA_COLLECTIVE_TYPE, audit_operations,
        )
        from veritx_dse.workload.graph import (
            KIND_COLLECTIVE, KIND_EXPERT_BEGIN, KIND_EXPERT_END,
        )
        for row in audit_operations(workload):
            if row["classification"] == "ZERO_TRAFFIC":
                continue
            operation = workload.by_id(row["operation_id"])
            if row["classification"] == "UNSUPPORTED":
                raise Astra2SemanticRefusal(
                    f"no canonical ASTRA lowering for operation "
                    f"{operation.operation_id!r} (kind={operation.kind}): "
                    f"refusing rather than reporting zero communication "
                    f"cost")
            if operation.detail.get("collective_kind") in \
                    _CHAKRA_COLLECTIVE_TYPE and operation.kind in \
                    (KIND_COLLECTIVE, KIND_EXPERT_BEGIN, KIND_EXPERT_END):
                continue
            raise Astra2SemanticRefusal(
                f"operation {operation.operation_id!r} "
                f"(kind={operation.kind}) requires the unqualified "
                f"SEND/RECV message path on this runtime: the qualified "
                f"ASTRA execution path is collective-mode "
                f"(et_granularity=collectives); refusing rather than "
                f"executing unqualified")

    def execute(
        self,
        prepared: PreparedExecution,
        options: object,
    ) -> Any:
        """Stage the workload and run the projected machine.

Rationale: docs/decisions/modules/backend.md
        """
        from veritx_dse.backend.astra import AstraUnavailable
        from veritx_dse.backend.astra_execution import (
            ASTRA_BUILD_RECIPE_VERSION, execute_astra_machine,
        )
        from veritx_dse.backend.producer import (
            ProducerError, resolve_producer_identity,
        )
        native = prepared.native_prepared
        if not isinstance(native, Astra2Preparation):
            raise TypeError(
                f"Astra2Adapter.execute takes a PreparedExecution whose "
                f"native_prepared is an Astra2Preparation, got "
                f"{type(native).__name__}")
        binary = self._binary if self._binary is not None else None
        if binary is None:
            from veritx_dse.backend.astra import resolve_runtime_binary
            binary = resolve_runtime_binary()
        if binary is None:
            raise AstraUnavailable("the ASTRA2 runtime binary is absent")
        from dataclasses import replace as _replace
        from veritx_dse.backend.astra_execution import AstraExecutionError
        try:
            pin_identity = resolve_producer_identity(
                Path(binary),
                require_manifest_recipe=ASTRA_BUILD_RECIPE_VERSION)
            pin = ProducerPin(
                binary_sha256=pin_identity.binary_sha256,
                binary_size=pin_identity.binary_size,
                source_revision=pin_identity.source_revision,
                dirty=pin_identity.dirty,
                build_manifest_sha256=
                pin_identity.build_manifest_sha256,
                build_recipe_version=
                pin_identity.build_recipe_version)
        except ProducerError as exc:
            raise AstraExecutionError(
                f"ASTRA producer identity unresolvable, refusing "
                f"spawn: {exc}") from exc
        native = _replace(native, producer_pin=pin)
        run_dir = Path(getattr(options, "run_dir"))
        timeout_s = getattr(options, "timeout_s", 600)
        astra_dir = run_dir / "astra"
        astra_dir.mkdir(parents=True, exist_ok=True)
        workload_dir = astra_dir / "workload"
        canonical_dir = astra_dir / "workload-canonical"
        native.workload_projection.write_chakra(
            directory=canonical_dir, stem="workload")
        from veritx_dse.backend.astra_namespace import (
            stage_endpoint_workload,
        )
        staged = stage_endpoint_workload(
            workload=native.workload_projection,
            namespace=native.namespace,
            source_directory=canonical_dir,
            target_directory=workload_dir, stem="workload",
            collective_binding=native.collective_binding)
        return execute_astra_machine(
            machine=native.machine, binary=str(binary),
            run_dir=astra_dir,
            workload_configuration=staged.base,
            timeout_s=timeout_s, write=True,
            namespace=native.namespace,
            repo_root=self._repo_root,
            class_binding_id=
            native.workload_projection.class_binding_id(),
            expected_collective_kinds=tuple(
                kind for _, kind, _, _
                in native.workload_projection.collective_operations))

    def normalize(
        self,
        context: CanonicalEvaluationContext,
        question: EvaluationQuestion,
        prepared: PreparedExecution,
        native_result: object,
    ) -> NormalizedBackendEvidence:
        """Project authenticated ASTRA runtime evidence into the common
        envelope. Only certified native evidence normalizes: EXECUTED
        status, supervised transport, the qualified collective tier, and
        zero autonomous injection."""
        from veritx_dse.backend.astra_execution import (
            EVIDENCE_TIER_ASTRA_COLLECTIVE,
            EXECUTION_TRANSPORT_SUPERVISED, STATUS_EXECUTED,
            AstraExecutionError, AstraRuntimeEvidence,
        )
        from veritx_dse.backend.normalized_evidence import (
            MetricValue, NormalizedBackendEvidence,
        )
        if question not in ASTRA2_QUESTIONS:
            raise Astra2SemanticRefusal(
                "ASTRA2 answers system-level questions only: "
                f"{[q.value for q in ASTRA2_QUESTIONS]}")
        native = prepared.native_prepared
        if not isinstance(native, Astra2Preparation):
            raise TypeError(
                f"Astra2Adapter.normalize takes a PreparedExecution "
                f"whose native_prepared is an Astra2Preparation, got "
                f"{type(native).__name__}")
        if not isinstance(native_result, AstraRuntimeEvidence):
            raise TypeError(
                f"Astra2Adapter.normalize takes an "
                f"AstraRuntimeEvidence, got "
                f"{type(native_result).__name__}")
        evidence = native_result
        if evidence.status != STATUS_EXECUTED:
            raise AstraExecutionError(
                f"ASTRA evidence status {evidence.status!r} is not "
                f"{STATUS_EXECUTED}: only executed runs normalize")
        if evidence.transport != EXECUTION_TRANSPORT_SUPERVISED:
            raise AstraExecutionError(
                f"ASTRA evidence transport {evidence.transport!r} is not "
                f"the supervised production process: only certified "
                f"product evidence normalizes")
        if evidence.evidence_tier != EVIDENCE_TIER_ASTRA_COLLECTIVE:
            raise AstraExecutionError(
                f"ASTRA evidence tier {evidence.evidence_tier!r} is not "
                f"the qualified collective tier "
                f"{EVIDENCE_TIER_ASTRA_COLLECTIVE}: unqualified "
                f"message-mode runs never normalize")
        if evidence.autonomous_injection_packets not in (None, 0):
            raise AstraExecutionError(
                f"the embedded fabric injected "
                f"{evidence.autonomous_injection_packets} packets of its "
                f"own; evidence with autonomous traffic never normalizes")
        _check_astra_evidence_binding(evidence, native)
        from veritx_dse.backend.astra_execution import (
            ASTRA_BUILD_RECIPE_VERSION,
        )
        if evidence.astra_build_recipe_version != \
                ASTRA_BUILD_RECIPE_VERSION:
            raise AstraExecutionError(
                f"ASTRA evidence build recipe "
                f"{evidence.astra_build_recipe_version!r} is not the "
                f"qualified {ASTRA_BUILD_RECIPE_VERSION!r}: refusing "
                "evidence from an unqualified producer")
        if not isinstance(evidence.astra_build_manifest_sha256, str) \
                or len(evidence.astra_build_manifest_sha256) != 64:
            raise AstraExecutionError(
                "ASTRA evidence carries no build-manifest digest: it "
                "did not come through the pinned spawn gate")
        if not evidence.astra_source_revision \
                or evidence.astra_dirty is not False:
            raise AstraExecutionError(
                "ASTRA evidence producer is not clean/revision-identified: "
                "refusing evidence from an unqualified producer")
        if evidence.embedded_network_class_abi_version != \
                native.machine.embedded_network_class_abi_version:
            raise AstraExecutionError(
                f"ASTRA evidence class ABI "
                f"{evidence.embedded_network_class_abi_version!r} does "
                "not match the prepared machine "
                f"{native.machine.embedded_network_class_abi_version!r}: "
                "refusing a cross-generation transplant")
        _projection_classes = \
            native.workload_projection.traffic_classes()
        if len(_projection_classes) > 1:
            _expected_binding = \
                native.workload_projection.class_binding_id()
            if evidence.class_binding_id != _expected_binding:
                raise AstraExecutionError(
                    f"ASTRA evidence class binding "
                    f"{evidence.class_binding_id!r} does not match the "
                    f"prepared {_expected_binding!r}: refusing a "
                    "class-swapped or collapsed normalization")
            if evidence.embedded_network_class_abi_version < 1:
                raise AstraExecutionError(
                    "multi-class evidence from a class-blind runtime "
                    f"(class ABI "
                    f"{evidence.embedded_network_class_abi_version}): "
                    "refusing unattributable classes")
        if evidence.per_class_injected or evidence.per_class_completed:
            _inj = dict(evidence.per_class_injected)
            _done = dict(evidence.per_class_completed)
            if set(_inj) != set(_done) or any(
                    _inj[c] != _done[c] for c in _inj):
                raise AstraExecutionError(
                    f"per-class conservation violated "
                    f"(injected={sorted(_inj.items())} vs completed="
                    f"{sorted(_done.items())}): refusing a lossy "
                    "normalization")
        metrics: list[MetricValue] = []
        if question is EvaluationQuestion.SYSTEM_MAKESPAN:
            metrics.append(MetricValue(
                key="system_makespan_cycles",
                value=float(evidence.aggregate_cycles), unit="cycles",
                source_metric_key="aggregate_cycles"))
        elif question is EvaluationQuestion.COMMUNICATION_EXPOSURE:
            metrics.append(MetricValue(
                key="communication_exposure_cycles",
                value=float(evidence.aggregate_exposed_comm),
                unit="cycles",
                source_metric_key="aggregate_exposed_comm"))
        elif question is EvaluationQuestion.PER_RANK_COMPLETION:
            for rank, cycles in evidence.per_rank_cycles:
                metrics.append(MetricValue(
                    key="completion_cycles", value=float(cycles),
                    unit="cycles", source_metric_key="per_rank_cycles",
                    dimensions=(("rank", str(rank)),)))
            for rank, exposed in evidence.per_rank_exposed_comm:
                metrics.append(MetricValue(
                    key="exposed_communication_cycles",
                    value=float(exposed), unit="cycles",
                    source_metric_key="per_rank_exposed_comm",
                    dimensions=(("rank", str(rank)),)))
        _resolved = context.bundle.resolved_fabric.resolved_fabric_hash
        resolved_hash = _resolved() if callable(_resolved) else _resolved
        return NormalizedBackendEvidence(
            backend_id=self.backend_id, question=question,
            model_fidelity=ASTRA2_MODEL_FIDELITY,
            canonical_parent_ids=(
                context.design_hash, resolved_hash,
                context.workload_id,
                native.workload_projection_id, native.machine_id,
                native.namespace.namespace_id()),
            native_evidence_id=evidence.evidence_id(),
            qualification=evidence.evidence_tier,
            producer_identity=evidence.astra_binary_sha256,
            backend_config_hash=native.machine_id,
            backend_input_hash=native.workload_projection_id,
            metrics=tuple(metrics),
            limitations=self._capabilities[0].limitations)

def _chakra_staging_available() -> bool:
    """Can this process stage Chakra ET artifacts for execution."""
    try:
        from chakra.schema.protobuf import et_def_pb2  # noqa: F401
        from chakra.src.third_party.utils import protolib  # noqa: F401
    except Exception:
        return False
    return True

from veritx_dse.backend.astra import (  # noqa: E402
    AstraError, AstraLoweringRefused, AstraUnavailable,
)
from veritx_dse.backend.astra_execution import AstraExecutionError  # noqa: E402
from veritx_dse.backend.astra_machine import AstraMachineError  # noqa: E402
from veritx_dse.backend.booksim_adapter import (  # noqa: E402
    BookSimProjectionRefusal,
)
from veritx_dse.backend.booksim_projection import SemanticLoss  # noqa: E402
from veritx_dse.core.errors import (  # noqa: E402
    ConservationFailed, EvidenceInvalid, InvalidInput, MappingInvalid,
    UnsupportedSchedule, UnsupportedSemantics,
)

_SEMANTIC_REFUSALS = (
    Astra2SemanticRefusal, AstraLoweringRefused, AstraMachineError,
    AstraError, AstraExecutionError, BookSimProjectionRefusal,
    SemanticLoss, MappingInvalid, InvalidInput, EvidenceInvalid,
    ConservationFailed, UnsupportedSemantics, UnsupportedSchedule,
)

__all__ = [
    "ASTRA2_MODEL_FIDELITY", "ASTRA2_QUESTIONS", "Astra2Adapter",
    "Astra2Preparation", "Astra2SemanticRefusal",
]
