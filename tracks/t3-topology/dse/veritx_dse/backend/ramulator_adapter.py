"""The certified Ramulator2 HBM3 backend adapter.

Promotes the EXISTING memory authorities into a first-class federation
path:

    workload graph --resolve_memory_graph--> MemoryArtifact
        --lower_to_ramulator_trace--> ReadWriteTrace
        --simulation.ramulator.execute--> MemoryEvidence

The adapter orchestrates; it never re-derives what those modules already
derive and never invents memory demand: a workload with no resolvable
memory operands is UNSUPPORTED/BLOCKED, never zero memory cost.

Backend identity is ``RAMULATOR2_HBM3_V1`` because the audited HBM3
single-channel profile materially affects the model — bare "RAMULATOR"
would hide which memory standard produced the number. The fixed profile
is a MODEL ASSUMPTION, not a user-authored design: capability
limitations and normalized evidence state it explicitly.

Model fidelity is MEMORY_CYCLE_SIMULATION, never FULL_SYSTEM_SIMULATION:
this is standalone DRAM-timing trace execution over a recorded request
stream, not a composed system.

Native preparation holds the resolved MemoryArtifact, the certified
geometry, the memory-profile identity and the mapping policy. No run
paths, PIDs, timestamps or host names ever enter scientific identity.
"""
from __future__ import annotations

import hashlib
import json
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

#: stable execution identity: simulator + audited profile, not bare RAMULATOR
BACKEND_ID = "RAMULATOR2_HBM3_V1"

#: the certified model fidelity of standalone Ramulator trace execution
RAMULATOR_MODEL_FIDELITY = ModelFidelity.MEMORY_CYCLE_SIMULATION

#: the fixed profile is a MODEL ASSUMPTION, never a user-authored design.
#: Capability limitations AND normalized evidence carry it verbatim.
MODEL_ASSUMPTION = (
    "DRAM timing assumes the certified HBM3 single-channel v1 profile. "
    "It is not a user-authored memory-system design."
)

RAMULATOR_LIMITATIONS = (
    MODEL_ASSUMPTION,
    "memory cycle simulation over a recorded request stream: row/queue "
    "timing is simulated, request generation is assumed (see the memory "
    "artifact assumptions)",
    "single-channel single-controller execution only (the audited v1 "
    "envelope)",
)

#: native qualification vocabulary: the backend's own verdict words.
#: PASS is never relabeled to the BookSim word QUALIFIED.
QUALIFICATION_PROFILE = "CERTIFIED_RAMULATOR_HBM3_V1"


class RamulatorSemanticRefusal(ValueError):
    """The workload has no representation on the certified Ramulator path.

    Typed so assessment maps a PREPARE refusal to UNSUPPORTED without a
    bare ``except Exception`` — which would launder programming bugs
    into capability verdicts.
    """


class RamulatorBackendAbsent(Exception):
    """The compiled Ramulator extension is absent: preparation succeeded
    but there is no backend to execute on. Maps to UNAVAILABLE, never to
    a semantic verdict and never to a fabrication."""


def certified_memory_design() -> Any:
    """The audited single-pool memory design the adapter resolves against."""
    from veritx_dse.workload.memory_lowering import MemorySystemDesign
    return MemorySystemDesign(hbm_devices=(0,))


def certified_mapping_policy() -> Any:
    """The audited address-mapping policy (a model assumption)."""
    from veritx_dse.core.memory import AddressMappingPolicy
    return AddressMappingPolicy(
        name="contiguous_aligned_v1", version=1, alignment_bytes=64,
        parameters={})


def certified_geometry() -> Any:
    """The audited HBM3 single-channel geometry transcription."""
    from veritx_dse.workload.memory_lowering import (
        hbm3_16gb_8hi_geometry,
    )
    return hbm3_16gb_8hi_geometry()


def ramulator_evidence_id(evidence: Any) -> str:
    """Content identity of native Ramulator evidence.

    Hashes the scientific fields only: status, producer, fidelity, the
    four hash links, metrics EXCEPT wall_time_s (nondeterministic across
    repeat runs — a repeat execution must reproduce the same identity),
    assumptions, semantic losses and the failure reason. ``raw`` is
    excluded: it carries host run paths, never science.
    """
    metrics = {
        key: value for key, value in
        (getattr(evidence, "metrics", None) or {}).items()
        if key != "wall_time_s"
    }
    payload = json.dumps({
        "type": "veritx/ramulator-memory-evidence",
        "version": 1,
        "status": evidence.status,
        "producer": evidence.producer,
        "fidelity": evidence.fidelity,
        "memory_artifact_hash": evidence.memory_artifact_hash,
        "lowering_manifest_hash": evidence.lowering_manifest_hash,
        "backend_input_hash": evidence.backend_input_hash,
        "backend_config_hash": evidence.backend_config_hash,
        "metrics": metrics,
        "assumptions": list(evidence.assumptions),
        "semantic_losses": list(evidence.semantic_losses),
        "failure_reason": evidence.failure_reason,
    }, sort_keys=True, separators=(",", ":")).encode()
    return "sha256:" + hashlib.sha256(payload).hexdigest()


@dataclass(frozen=True)
class RamulatorPreparation:
    """What prepare() hands to execute() — the resolved memory semantics
    plus the certified profile they were resolved against.

    The real MemoryArtifact is retained (not only its hash) so
    ``execute()`` generates the real trace itself — preparation is
    semantic resolution, executable by itself, with no runtime binary
    required. ``backend_config_hash`` is the recomputable config identity
    (``backend_config_payload`` over the certified geometry); execute()
    refuses when the trace it lowers does not reproduce it.
    """

    artifact: Any                        # MemoryArtifact
    geometry: Any                        # RamulatorGeometry
    memory_artifact_hash: str
    access_stream_hash: str
    backend_config_hash: str


class RamulatorAdapter:
    """Orchestrates workload-graph → memory artifact → trace → evidence.

    Supports exactly DRAM_TIMING at MEMORY_CYCLE_SIMULATION fidelity.
    Assessment re-runs the real semantic gate (``resolve_memory_graph``
    against the certified profile) AND proves runtime readiness (the
    compiled extension exists and certified producer facts establish) —
    a READY assessment means those gates all passed on this context, not
    merely that the backend exists. Assessment never spawns Ramulator.
    """

    def __init__(
        self,
        *,
        vendor_dir: str | Path | None = None,
        python_exe: str | None = None,
    ) -> None:
        self._vendor_dir = Path(vendor_dir) \
            if vendor_dir is not None else None
        self._python_exe = python_exe
        self._capabilities: tuple[BackendCapability, ...] = (
            BackendCapability(
                question=EvaluationQuestion.DRAM_TIMING,
                support=SupportLevel.SUPPORTED,
                fidelity=RAMULATOR_MODEL_FIDELITY,
                limitations=RAMULATOR_LIMITATIONS),
        )

    @property
    def backend_id(self) -> str:
        return BACKEND_ID

    def capabilities(self) -> tuple[BackendCapability, ...]:
        return self._capabilities

    def _discover(self) -> Any:
        """Locate the backend through the canonical discovery authority."""
        from veritx_dse.simulation.ramulator import discover
        return discover(
            python_exe=self._python_exe, vendor_dir=self._vendor_dir)

    def _required_parents(self) -> tuple[str, ...]:
        return ("design", "resolved_fabric", "workload",
                "memory_artifact", "access_stream")

    # ── assess ────────────────────────────────────────────────────────

    def assess(
        self,
        context: CanonicalEvaluationContext,
        question: EvaluationQuestion,
    ) -> BackendAssessment:
        if question is not EvaluationQuestion.DRAM_TIMING:
            return BackendAssessment(
                backend_id=self.backend_id, question=question,
                support=SupportLevel.UNSUPPORTED,
                readiness=BackendReadiness.BLOCKED,
                fidelity=RAMULATOR_MODEL_FIDELITY,
                qualification_profile=None,
                reason="certified Ramulator answers DRAM_TIMING only",
                required_parents=self._required_parents(),
                limitations=RAMULATOR_LIMITATIONS)
        try:
            self._prepare_native(context, question)
        except _SEMANTIC_REFUSALS as exc:
            return BackendAssessment(
                backend_id=self.backend_id, question=question,
                support=SupportLevel.UNSUPPORTED,
                readiness=BackendReadiness.BLOCKED,
                fidelity=RAMULATOR_MODEL_FIDELITY,
                qualification_profile=None,
                reason=f"{type(exc).__name__}: {exc}",
                required_parents=self._required_parents(),
                limitations=RAMULATOR_LIMITATIONS)
        # semantics resolve; now prove a usable, qualified backend exists
        from veritx_dse.simulation.ramulator import RamulatorError
        try:
            backend = self._discover()
        except RamulatorError as exc:
            return BackendAssessment(
                backend_id=self.backend_id, question=question,
                support=SupportLevel.SUPPORTED,
                readiness=BackendReadiness.UNAVAILABLE,
                fidelity=RAMULATOR_MODEL_FIDELITY,
                qualification_profile=None,
                reason=f"Ramulator backend undiscoverable: {exc}",
                required_parents=self._required_parents(),
                limitations=RAMULATOR_LIMITATIONS)
        if not backend.ready:
            return BackendAssessment(
                backend_id=self.backend_id, question=question,
                support=SupportLevel.SUPPORTED,
                readiness=BackendReadiness.UNAVAILABLE,
                fidelity=RAMULATOR_MODEL_FIDELITY,
                qualification_profile=None,
                reason="Ramulator backend not built: no compiled "
                f"extension at {backend.ext_path}; build with "
                f"interpreter {backend.python_exe}: "
                "cd third_party/ramulator2 && ./build.sh",
                required_parents=self._required_parents(),
                limitations=RAMULATOR_LIMITATIONS)
        try:
            backend.producer()
        except RamulatorError as exc:
            return BackendAssessment(
                backend_id=self.backend_id, question=question,
                support=SupportLevel.SUPPORTED,
                readiness=BackendReadiness.UNAVAILABLE,
                fidelity=RAMULATOR_MODEL_FIDELITY,
                qualification_profile=None,
                reason=f"Ramulator producer facts unestablished: {exc}",
                required_parents=self._required_parents(),
                limitations=RAMULATOR_LIMITATIONS)
        return BackendAssessment(
            backend_id=self.backend_id, question=question,
            support=SupportLevel.SUPPORTED,
            readiness=BackendReadiness.READY,
            fidelity=RAMULATOR_MODEL_FIDELITY,
            qualification_profile=QUALIFICATION_PROFILE,
            reason=None,
            required_parents=self._required_parents(),
            limitations=RAMULATOR_LIMITATIONS)

    # ── prepare ───────────────────────────────────────────────────────

    def prepare(
        self,
        context: CanonicalEvaluationContext,
        question: EvaluationQuestion,
        **kwargs: object,
    ) -> PreparedExecution:
        """Semantic resolution only — no runtime binary required.

        Returns the generic ``PreparedExecution`` seam; the native
        ``RamulatorPreparation`` (real artifact retained) rides in
        ``native_prepared`` so ``execute()`` lowers the real trace
        itself.
        """
        native = self._prepare_native(context, question)
        return PreparedExecution(
            backend_id=self.backend_id,
            projection_identity=native.memory_artifact_hash,
            qualification_identity=native.backend_config_hash,
            backend_config=None, backend_input=None, producer=None,
            native_prepared=native)

    def _prepare_native(
        self,
        context: CanonicalEvaluationContext,
        question: EvaluationQuestion,
    ) -> RamulatorPreparation:
        if question is not EvaluationQuestion.DRAM_TIMING:
            raise RamulatorSemanticRefusal(
                "certified Ramulator answers DRAM_TIMING only")
        from veritx_dse.workload.memory_lowering import (
            backend_config_payload, resolve_memory_graph,
        )
        # Semantic preparation: the workload's COMPUTE memory operands
        # resolved against the certified profile. A workload with no
        # resolvable memory demand refuses here — never zero cost.
        try:
            resolved = resolve_memory_graph(
                context.workload, certified_memory_design(),
                policy=certified_mapping_policy())
        except (LoweringError, MemoryArtifactError, InvalidInput) as exc:
            raise RamulatorSemanticRefusal(
                f"no resolvable memory demand: {type(exc).__name__}: "
                f"{exc}") from exc
        artifact = resolved.artifact
        geometry = certified_geometry()
        config_hash = "sha256:" + hashlib.sha256(
            backend_config_payload(geometry, MAPPING_ALGORITHM)).hexdigest()
        return RamulatorPreparation(
            artifact=artifact, geometry=geometry,
            memory_artifact_hash=artifact.artifact_hash,
            access_stream_hash=artifact.access_stream_hash,
            backend_config_hash=config_hash)

    # ── execute ───────────────────────────────────────────────────────

    def execute(
        self,
        prepared: PreparedExecution,
        options: object,
    ) -> Any:
        """Lower the real trace and run it through the vendored backend.

        Writes ``run_dir/ramulator/``: the trace, its manifest, the
        memory artifact and the native evidence document — then runs the
        one audited subprocess path (``simulation.ramulator.execute``).
        No alternative subprocess runner exists. Returns the
        backend-native ``MemoryEvidence`` unchanged.
        """
        from veritx_dse.simulation import ramulator as _sim
        from veritx_dse.workload.memory_lowering import (
            lower_to_ramulator_trace,
        )
        native = prepared.native_prepared
        if not isinstance(native, RamulatorPreparation):
            raise TypeError(
                f"RamulatorAdapter.execute takes a PreparedExecution "
                f"whose native_prepared is a RamulatorPreparation, got "
                f"{type(native).__name__}")
        backend = self._discover()
        if not backend.ready:
            raise RamulatorBackendAbsent(
                f"Ramulator backend not built: no compiled extension at "
                f"{backend.ext_path}; refusing to invent results")
        run_dir = Path(getattr(options, "run_dir"))
        timeout = getattr(options, "timeout_s", 600)
        ram_dir = run_dir / "ramulator"
        ram_dir.mkdir(parents=True, exist_ok=True)
        trace_path = ram_dir / "memory.trace"
        manifest = lower_to_ramulator_trace(
            native.artifact, native.geometry, out_path=trace_path)
        # Tamper-closed: the lowered trace must reproduce the config
        # identity preparation bound — a substituted lowering refuses
        # before spawn.
        if manifest.to_dict()["backend_config_hash"] != \
                native.backend_config_hash:
            raise _sim.RamulatorError(
                "lowered trace backend_config_hash does not match the "
                "prepared config identity — refusing to execute")
        (ram_dir / "memory-artifact.json").write_text(
            json.dumps(native.artifact.serialize(), sort_keys=True,
                       indent=2) + "\n",
            encoding="utf-8")
        (ram_dir / "lowering-manifest.json").write_text(
            json.dumps(manifest.to_dict(), sort_keys=True, indent=2)
            + "\n",
            encoding="utf-8")
        evidence = _sim.execute(
            native.artifact, manifest, trace_path, backend=backend,
            run_dir=ram_dir / "run", timeout=timeout)
        (ram_dir / "memory-evidence.json").write_text(
            json.dumps(evidence.to_dict(), sort_keys=True, indent=2)
            + "\n",
            encoding="utf-8")
        return evidence

    # ── normalize ─────────────────────────────────────────────────────

    def normalize(
        self,
        context: CanonicalEvaluationContext,
        question: EvaluationQuestion,
        prepared: PreparedExecution,
        native_result: object,
    ) -> NormalizedBackendEvidence:
        """Project authenticated native memory evidence into the common
        envelope. Only PASS evidence normalizes: INCONCLUSIVE stays
        INCONCLUSIVE (a refusal here, never a PASS), crashes and
        unsupported geometries never normalize. Only native metrics
        present are projected — absent stays absent, never zero-filled —
        and wall_time_s is never a scientific design objective."""
        from veritx_dse.backend.normalized_evidence import (
            MetricValue, NormalizedBackendEvidence,
        )
        from veritx_dse.simulation.ramulator import (
            MemoryEvidence, RamulatorError,
        )
        if question is not EvaluationQuestion.DRAM_TIMING:
            raise RamulatorSemanticRefusal(
                "certified Ramulator answers DRAM_TIMING only")
        native = prepared.native_prepared
        if not isinstance(native, RamulatorPreparation):
            raise TypeError(
                f"RamulatorAdapter.normalize takes a PreparedExecution "
                f"whose native_prepared is a RamulatorPreparation, got "
                f"{type(native).__name__}")
        if not isinstance(native_result, MemoryEvidence):
            raise TypeError(
                f"RamulatorAdapter.normalize takes a MemoryEvidence, got "
                f"{type(native_result).__name__}")
        evidence = native_result
        # Anti-transplant: the evidence must claim exactly the artifact
        # and config preparation bound.
        if evidence.memory_artifact_hash != native.memory_artifact_hash:
            raise RamulatorError(
                "native evidence memory_artifact_hash does not match the "
                "prepared artifact — refusing a transplanted normalization")
        if evidence.backend_config_hash != native.backend_config_hash:
            raise RamulatorError(
                "native evidence backend_config_hash does not match the "
                "prepared config identity — refusing a transplanted "
                "normalization")
        if evidence.status != "PASS":
            raise RamulatorError(
                f"native memory evidence status {evidence.status!r} is "
                f"not PASS (reason: {evidence.failure_reason}): "
                f"INCONCLUSIVE stays INCONCLUSIVE, never PASS; only "
                f"drained executions normalize")
        metrics: list[MetricValue] = []
        for native_key in _NORMALIZED_METRICS:
            entry = (evidence.metrics or {}).get(native_key)
            if not isinstance(entry, dict):
                continue  # absent stays absent, never zero-filled
            value, unit = entry.get("value"), entry.get("unit")
            if isinstance(value, bool) or \
                    not isinstance(value, (int, float)):
                continue
            metrics.append(MetricValue(
                key=native_key, value=float(value), unit=unit,
                source_metric_key=native_key))
        _resolved = context.bundle.resolved_fabric.resolved_fabric_hash
        resolved_hash = _resolved() if callable(_resolved) else _resolved
        try:
            producer_identity = evidence.producer["binary_sha256"]
        except (TypeError, KeyError) as exc:
            raise RamulatorError(
                f"native evidence carries no producer binary identity: "
                f"{exc}") from exc
        if not isinstance(producer_identity, str) or not producer_identity:
            raise RamulatorError(
                "native evidence carries no producer binary identity")
        return NormalizedBackendEvidence(
            backend_id=self.backend_id, question=question,
            model_fidelity=RAMULATOR_MODEL_FIDELITY,
            canonical_parent_ids=(
                context.design_hash, resolved_hash,
                context.workload_id,
                native.memory_artifact_hash,
                evidence.lowering_manifest_hash),
            native_evidence_id=ramulator_evidence_id(evidence),
            qualification=evidence.status,
            producer_identity=producer_identity,
            backend_config_hash=native.backend_config_hash,
            backend_input_hash=evidence.backend_input_hash,
            metrics=tuple(metrics),
            limitations=RAMULATOR_LIMITATIONS)


#: native metric keys projected into the normalized envelope, in stable
#: order. wall_time_s is deliberately absent: elapsed host time is not a
#: scientific design objective. issued_* counters are covered by the
#: generated/accepted/completed drain counters.
_NORMALIZED_METRICS: tuple[str, ...] = (
    "completion_cycles",
    "average_read_latency_cycles",
    "average_write_latency_cycles",
    "row_hits",
    "row_misses",
    "row_conflicts",
    "read_queue_len_avg",
    "write_queue_len_avg",
    "coalesced_write_requests",
    "completed_read_bytes",
    "completed_write_bytes",
    "generated_requests",
    "accepted_requests",
    "completed_requests",
    "outstanding_requests",
)


from veritx_dse.core.errors import InvalidInput  # noqa: E402
from veritx_dse.core.memory import MemoryArtifactError  # noqa: E402
from veritx_dse.workload.lowering import LoweringError  # noqa: E402
from veritx_dse.workload.memory_lowering import (  # noqa: E402
    MAPPING_ALGORITHM,
)
from veritx_dse.backend.normalized_evidence import (  # noqa: E402
    NormalizedBackendEvidence,
)

#: prepare() failures that are SEMANTIC (UNSUPPORTED/BLOCKED), never
#: runtime. Programming errors (TypeError, AttributeError,
#: AssertionError, KeyError) are deliberately absent: they escape.
_SEMANTIC_REFUSALS = (
    RamulatorSemanticRefusal, LoweringError,
    MemoryArtifactError, InvalidInput,
)


__all__ = [
    "BACKEND_ID", "MODEL_ASSUMPTION", "QUALIFICATION_PROFILE",
    "RAMULATOR_LIMITATIONS", "RAMULATOR_MODEL_FIDELITY",
    "RamulatorAdapter", "RamulatorBackendAbsent", "RamulatorPreparation",
    "RamulatorSemanticRefusal", "certified_geometry",
    "certified_mapping_policy", "certified_memory_design",
    "ramulator_evidence_id",
]
