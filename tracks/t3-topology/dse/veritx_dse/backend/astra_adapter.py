"""The ASTRA2 embedded-BookSim backend adapter.

Federation Commit 09: promote the EXISTING ASTRA authorities
(``astra.AstraWorkloadProjection``, ``astra_machine.qualify_astra_machine``
over the certified BookSim fabric projection, ``astra_execution.
execute_astra_machine``) into a first-class federation path. The adapter
orchestrates; it never re-derives what those modules already derive.

Backend identity is ``ASTRA2_EMBEDDED_BOOKSIM`` because the embedded
BookSim network backend materially affects the model — "ASTRA" alone
would hide which network simulator produced the number.

ASTRA consumes the canonical V2 message artifact (single-class
collective communication); a multi-class lowering has no ASTRA
projection today and refuses instead of flattening classes.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from types import SimpleNamespace
from typing import Any

from veritx_dse.application.evaluation_context import (
    CanonicalEvaluationContext,
)
from veritx_dse.application.evaluation_question import EvaluationQuestion
from veritx_dse.backend.adapter import (
    BackendAdapter, BackendAssessment, BackendCapability, ModelFidelity,
    PreparedExecution, SupportLevel,
)


#: the certified model fidelity of an ASTRA2 system simulation
ASTRA2_MODEL_FIDELITY = ModelFidelity.SYSTEM_SIMULATION

#: questions this adapter can answer with authentic runtime evidence
ASTRA2_QUESTIONS = (
    EvaluationQuestion.SYSTEM_MAKESPAN,
    EvaluationQuestion.COMMUNICATION_EXPOSURE,
    EvaluationQuestion.PER_RANK_COMPLETION,
)


@dataclass(frozen=True)
class Astra2Preparation:
    """The native prepared structures plus the federation identities."""

    machine: Any                      # AstraMachineProjection
    workload_projection_id: str
    machine_id: str
    prepared_id: str                  # embedded BookSim config identity
    standalone_config_sha256: str
    embedded_fabric_abi_version: str
    rank_to_endpoint: tuple[tuple[int, int], ...]
    namespace: Any = None             # AstraExecutionNamespace


class Astra2Adapter:
    """Orchestrates workload → machine → execution → runtime evidence.

    Assessment walks the real gate chain (operation audit, namespace-
    valid projection, machine qualification over the certified fabric
    projection, executable present, producer identifiable) — a SUPPORTED
    assessment means those gates passed on this context.
    """

    def __init__(self) -> None:
        self._capabilities: tuple[BackendCapability, ...] = tuple(
            BackendCapability(
                question=question,
                support=SupportLevel.SUPPORTED,
                fidelity=ASTRA2_MODEL_FIDELITY,
                limitations=(
                    "system simulation: cycles are the projected machine's "
                    "makespan/exposure window, never end-to-end workload "
                    "runtime",
                    "single-class collective communication (V2 artifact)",
                ))
            for question in ASTRA2_QUESTIONS)

    @property
    def backend_id(self) -> str:
        return "ASTRA2_EMBEDDED_BOOKSIM"

    def capabilities(self) -> tuple[BackendCapability, ...]:
        return self._capabilities

    # ── assess ────────────────────────────────────────────────────────

    def assess(
        self,
        context: CanonicalEvaluationContext,
        question: EvaluationQuestion,
    ) -> BackendAssessment:
        limitation_bundle = self._capabilities[0].limitations
        if question not in ASTRA2_QUESTIONS:
            return self._refused(
                question, "ASTRA2 answers system-level questions only: "
                f"{[q.value for q in ASTRA2_QUESTIONS]}",
                limitation_bundle)
        try:
            self.prepare(context, question)
        except Exception as exc:
            return self._refused(question, f"{type(exc).__name__}: {exc}",
                                 limitation_bundle)
        return BackendAssessment(
            backend_id=self.backend_id, question=question,
            support=SupportLevel.SUPPORTED,
            readiness=self._readiness(),
            fidelity=ASTRA2_MODEL_FIDELITY,
            qualification_profile="ASTRA2_EMBEDDED_BOOKSIM",
            reason=None, required_parents=self._required_parents(),
            limitations=limitation_bundle)

    def _readiness(self):
        from veritx_dse.backend.adapter import BackendReadiness
        from veritx_dse.backend.astra import resolve_runtime_binary
        if resolve_runtime_binary() is None:
            return BackendReadiness.UNAVAILABLE
        return BackendReadiness.READY

    def _refused(self, question: EvaluationQuestion, reason: str,
                 limitation_bundle: tuple[str, ...]) -> BackendAssessment:
        from veritx_dse.backend.adapter import (
            BackendReadiness, SupportLevel,
        )
        support = SupportLevel.UNSUPPORTED \
            if isinstance(reason, str) and (
                "no canonical ASTRA lowering" in reason
                or "multi-class" in reason
                or "answers system-level questions only" in reason) \
            else SupportLevel.CONDITIONAL
        readiness = BackendReadiness.BLOCKED \
            if support is SupportLevel.UNSUPPORTED \
            else self._readiness()
        if readiness is BackendReadiness.UNAVAILABLE:
            support = SupportLevel.CONDITIONAL
        return BackendAssessment(
            backend_id=self.backend_id, question=question,
            support=support, readiness=readiness,
            fidelity=ASTRA2_MODEL_FIDELITY,
            qualification_profile=None, reason=reason,
            required_parents=self._required_parents(),
            limitations=limitation_bundle)

    def _required_parents(self) -> tuple[str, ...]:
        return ("design", "resolved_fabric", "workload", "message_artifact",
                "mapping", "attachment", "embedded_booksim_prepared")

    # ── prepare ───────────────────────────────────────────────────────

    def prepare(
        self,
        context: CanonicalEvaluationContext,
        question: EvaluationQuestion,
        *,
        traffic_class: str | None = None,
    ) -> Astra2Preparation:
        if question not in ASTRA2_QUESTIONS:
            raise ValueError(
                "ASTRA2 answers system-level questions only: "
                f"{[q.value for q in ASTRA2_QUESTIONS]}")
        from veritx_dse.backend.astra import (
            AstraWorkloadProjection, resolve_runtime_binary,
        )
        from veritx_dse.backend.astra_execution import (
            resolve_astra_identity,
        )
        from veritx_dse.backend.astra_machine import (
            AstraMachineError, qualify_astra_machine,
        )
        from veritx_dse.workload.messages import (
            LogicalMessageArtifactV2, LogicalMessageArtifactV3,
        )

        # ASTRA consumes the V2 artifact: a multi-class lowering has no
        # ASTRA representation — refuse rather than flatten classes.
        lowered = context.lowered_workload
        if lowered.unified_traffic_class is None:
            raise ValueError(
                f"lowering spans classes {list(lowered.classes)}: ASTRA "
                f"projection is single-class (V2 artifact); multi-class "
                f"traffic refuses rather than flattening")
        unified = lowered.unified_traffic_class
        if traffic_class is not None and traffic_class != unified:
            raise ValueError(
                f"evaluation traffic class {traffic_class!r} does not "
                f"match the lowered intent class {unified!r}: eval-time "
                f"relabeling is refused")

        logical = LogicalMessageArtifactV2(context.workload,
                                           traffic_class=unified)
        bundle = context.bundle
        # The canonical BookSim fabric projection is the machine's network
        # authority; embed its prepared config into the ASTRA machine.
        from veritx_dse.backend.booksim_adapter import (
            BookSimAdapter, BookSimProjectionRefusal,
        )
        booksim = BookSimAdapter()
        try:
            bs_prep = booksim.prepare(
                context, EvaluationQuestion.NETWORK_COMPLETION,
                traffic_class=traffic_class if traffic_class is not None
                else unified)
        except BookSimProjectionRefusal as exc:
            raise ValueError(
                f"embedded BookSim fabric projection refused: {exc}") \
                from exc
        projection = AstraWorkloadProjection.build(
            logical=logical,
            resolved_fabric=bundle.resolved_fabric,
            mapping=bundle.mapping, attachment=bundle.attachment)
        # the machine qualification consumes the SAME canonical parents
        # the BookSim fabric projection consumed (packet_format, mapping,
        # attachment) — the machine is derived from the certified fabric
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

        binary = resolve_runtime_binary()
        if binary is None:
            from veritx_dse.backend.astra import AstraUnavailable
            raise AstraUnavailable(
                "the ASTRA2 runtime binary is absent: the machine "
                "projection exists but cannot execute here")
        # producer identifiable — the runtime's own identity chain
        resolve_astra_identity(binary, repo_root=None)

        # canonical rank→endpoint binding: identity over the machine's
        # Sys.id namespace (one endpoint per rank), validated and refused
        # if it leaves the fabric endpoint namespace
        from veritx_dse.workload.traffic import ParticipantEndpointMapping
        binding = ParticipantEndpointMapping(
            participant_count=projection.participant_count,
            rank_to_endpoint=tuple(
                (rank, endpoint) for rank, endpoint
                in zip(range(projection.participant_count),
                       range(machine.astra_sys_count))),
            fabric_id=machine.resolved_fabric_hash)
        from veritx_dse.backend.astra_namespace import build_namespace
        namespace = build_namespace(
            machine=machine, workload=projection, binding=binding,
            endpoint_count=machine.astra_sys_count,
            router_count=machine.router_count)
        return Astra2Preparation(
            machine=machine,
            workload_projection_id=projection.workload_id,
            machine_id=machine.machine_id(),
            prepared_id=machine.prepared_id,
            standalone_config_sha256=machine.standalone_config_sha256,
            embedded_fabric_abi_version=machine.embedded_fabric_abi_version,
            rank_to_endpoint=binding.rank_to_endpoint,
            namespace=namespace)

    # ── execute ───────────────────────────────────────────────────────

    def execute(
        self,
        prepared: PreparedExecution,
        options: object,
    ) -> Any:
        """Run the projected machine through ``execute_astra_machine``.

        Returns the backend-native ``AstraRuntimeEvidence`` unchanged;
        normalization into the common envelope is Federation 08's seam
        and stays out of the native path.
        """
        from veritx_dse.backend.astra import resolve_runtime_binary
        from veritx_dse.backend.astra_execution import (
            execute_astra_machine,
        )
        native = prepared.native_prepared
        if not isinstance(native, Astra2Preparation):
            raise TypeError(
                f"Astra2Adapter.execute takes a PreparedExecution whose "
                f"native_prepared is an Astra2Preparation, got "
                f"{type(native).__name__}")
        binary = resolve_runtime_binary()
        if binary is None:
            from veritx_dse.backend.astra import AstraUnavailable
            raise AstraUnavailable("the ASTRA2 runtime binary is absent")
        return execute_astra_machine(
            machine=native.machine, binary=str(binary),
            run_dir=Path(options.run_dir) / "astra",
            workload_configuration=options.workload_configuration,
            timeout_s=options.timeout_s, write=True,
            namespace=native.namespace)


__all__ = [
    "ASTRA2_MODEL_FIDELITY", "ASTRA2_QUESTIONS", "Astra2Adapter",
    "Astra2Preparation",
]
