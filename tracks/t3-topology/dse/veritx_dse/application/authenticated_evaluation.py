"""veritx_dse.application.authenticated_evaluation — backend evidence proof.

`VerifiedPerformanceResult` (B's boundary) proves the persisted
PerformanceResult re-derives from a verified ``TemporalWorkload``: event
graph, deterministic schedule, every summary and the result identity.
It does NOT prove the network binding came from authenticated BookSim
execution — ``NetworkWindowBinding.from_dict`` validates digest *shape*
and ``reverify_result`` never reopens the evidence bytes. A synthetic
binding with invented digests can therefore satisfy B's boundary.

This module is the missing half: it dereferences the REAL persisted
evidence bytes and proves the whole chain end to end.

Creation (``authenticate_backend_evaluation``) binds a compilation +
workload + verified result to the evidence bytes at evaluation time and
returns an ``AuthenticatedBackendEvaluation`` proof object.

Consumption (``verify_authenticated_backend_evaluation``) re-checks the
ENTIRE chain from the proof's ``EvidenceRef`` at consumption time and
returns DERIVED ``VerifiedEvaluationClaims`` — never caller-supplied
claims. Worker A calls it directly (real import coupling, no duck
typing).

    exact evidence bytes -> sha256 == EvidenceRef.sha256
      -> read_verified_evidence (digest re-check + parse)
      -> EvidenceArtifact (raw evidence digest, stats digest, backend
         input digest)
      -> NetworkWindowBinding: same evidence digest, same stats digest,
         same backend_input_hash, same physical_traffic_id
      -> VerifiedPerformanceResult (already verified by B's boundary)
      -> request/workload/design identity (re-derived lowering)
      -> RequirementEvaluator re-derivation -> canonical RequirementReport

Every mismatch or unreadable evidence refuses with ``EvidenceInvalid``
naming the mismatch; genuinely unexpected programming errors still
escape. ``evaluation_authority="certified-backend"`` is display metadata
only — the returned proof object IS the proof.
"""
from __future__ import annotations

import hashlib
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from veritx_dse.application.fabric_compiler import Compilation
from veritx_dse.application.requirements import (
    RequirementEvaluator,
    VerifiedPerformanceResult,
    report_identity,
)
from veritx_dse.backend.evidence import (
    BackendEvidenceError,
    EvidenceArtifact,
    EvidenceRef,
    read_verified_evidence,
)
from veritx_dse.core.errors import (
    ArtifactError,
    EvidenceInvalid,
    InvalidInput,
    MappingInvalid,
    UnsupportedSchedule,
    UnsupportedSemantics,
)
from veritx_dse.core.time import TimeError
from veritx_dse.model.compile_model import CompileRequestV3
from veritx_dse.performance.network import NetworkWindowBinding
from veritx_dse.workload.canonical_graph import WorkloadGraph
from veritx_dse.workload.intent_lowering import lower_compile_workload

#: Display metadata only (mirrors optimization.evaluators'
#: ``AUTHORITY_CERTIFIED_BACKEND``). The proof is the returned object.
EVALUATION_AUTHORITY = "certified-backend"


@dataclass(frozen=True)
class AuthenticatedBackendEvaluation:
    """One backend evaluation whose evidence chain was re-proven.

    Carries the dereferenced ``EvidenceRef`` and ``EvidenceArtifact``,
    the binding they authenticate, the producer identity the evidence
    names, B's verified result and the canonical RequirementReport
    re-derived from the triple. A caller may use this object as proof;
    the ``certified-backend`` label alone is never proof.
    """

    design_hash: str
    workload_id: str
    physical_traffic_id: str
    backend_input_hash: str
    evidence_ref: EvidenceRef
    evidence_artifact: EvidenceArtifact
    producer_identity: str
    binding: NetworkWindowBinding
    verified_result: VerifiedPerformanceResult
    requirement_report: dict[str, Any]


@dataclass(frozen=True)
class MetricEvidenceHandle:
    """One authenticated metric value with its evidence provenance.

    ``producer`` is the registered metric-authority name that extracted
    the value; ``evidence_sha256``/``stats_sha256`` name the exact
    authenticated evidence the value derives from, so a consumer can
    display or re-check provenance without trusting a label.
    """

    metric: str
    value: float
    producer: str
    evidence_sha256: str
    stats_sha256: str


@dataclass(frozen=True)
class VerifiedEvaluationClaims:
    """Consumption-time derived claims for one authenticated evaluation.

    Every field is derived by ``verify_authenticated_backend_evaluation``
    from the re-checked evidence chain — none is accepted from the
    caller's proof object. ``metrics`` are the registered metric
    authority's values over the verified result; ``metric_evidence``
    carries the same values with their evidence handles.

    The evidence schema does not persist a backend profile id, so
    ``backend`` is the authenticated producer/transport identity and
    ``backend_profile`` the executed qualification label; the exact
    backend configuration identity is ``backend_config_hash``.
    """

    design_hash: str
    workload_id: str
    physical_traffic_id: str
    performance_result_id: str
    requirement_report: dict[str, Any]
    requirement_report_id: str
    metrics: dict[str, float]
    metric_evidence: tuple[MetricEvidenceHandle, ...]
    producer_identity: str
    backend: str
    backend_profile: str | None
    backend_config_hash: str
    backend_input_hash: str
    resolved_fabric_hash: str
    evidence_ref: EvidenceRef
    evidence_artifact: EvidenceArtifact
    binding: NetworkWindowBinding
    verified_result: VerifiedPerformanceResult


def _refuse(what: str, message: str) -> EvidenceInvalid:
    return EvidenceInvalid(f"{what}: {message}")


def _require_str(mapping: Any, key: str, what: str) -> str:
    if not isinstance(mapping, Mapping):
        raise _refuse(what, f"expected an object, got "
                            f"{type(mapping).__name__}")
    value = mapping.get(key)
    if not isinstance(value, str) or not value:
        raise _refuse(what, f"{key!r} must be a non-empty string, got "
                            f"{value!r}")
    return value


def _parse_binding(verified_result: Any) -> NetworkWindowBinding:
    try:
        return NetworkWindowBinding.from_dict(
            verified_result.get("network_binding"))
    except TimeError as exc:
        raise _refuse(
            "network_binding",
            f"malformed persisted binding: {exc}") from exc


def _open_evidence(evidence_path: Any, binding: NetworkWindowBinding
                   ) -> tuple[EvidenceRef, EvidenceArtifact, dict[str, Any]]:
    """Dereference the REAL bytes and rebuild the evidence artifact."""
    path = Path(evidence_path)
    try:
        raw = path.read_bytes()
    except OSError as exc:
        raise _refuse("evidence", f"{path} unreadable: {exc}") from exc
    digest = hashlib.sha256(raw).hexdigest()
    if digest != binding.evidence_sha256:
        raise _refuse(
            "evidence",
            f"bytes digest {digest} does not match the binding's "
            f"evidence_sha256 {binding.evidence_sha256} — refusing a "
            f"synthetic or forged result; the binding must name the "
            f"exact persisted evidence bytes")
    ref = EvidenceRef(path=str(path), sha256=digest)
    try:
        evidence_doc = read_verified_evidence(ref)
        artifact = EvidenceArtifact.from_verified_evidence(
            evidence_doc, ref)
    except (BackendEvidenceError, ArtifactError) as exc:
        raise _refuse(
            "evidence", f"{type(exc).__name__}: {exc}") from exc
    return ref, artifact, evidence_doc


def _check_artifact_against_binding(
        artifact: EvidenceArtifact, binding: NetworkWindowBinding,
        evidence_doc: Mapping[str, Any],
        expected_resolved_fabric_hash: str | None) -> str:
    """The binding and the authenticated evidence must describe the same
    execution: raw-evidence, stats and backend-input digests agree."""
    if artifact.raw_evidence_sha256 != binding.evidence_sha256:
        raise _refuse(
            "evidence.raw_evidence_sha256",
            f"{artifact.raw_evidence_sha256!r} does not match the "
            f"binding's evidence_sha256 {binding.evidence_sha256!r}")
    if artifact.stats_sha256 != binding.stats_sha256:
        raise _refuse(
            "evidence.stats_sha256",
            f"persisted stats digest {artifact.stats_sha256!r} does not "
            f"match the binding's stats_sha256 {binding.stats_sha256!r} "
            f"— the stats were modified after execution")
    if artifact.backend_input_sha256 != binding.backend_input_hash:
        raise _refuse(
            "evidence.backend_input_hash",
            f"persisted backend input digest "
            f"{artifact.backend_input_sha256!r} does not match the "
            f"binding's backend_input_hash {binding.backend_input_hash!r}")
    if artifact.backend_input_id != binding.backend_input_hash:
        raise _refuse(
            "evidence.backend_input_id",
            f"{artifact.backend_input_id!r} is not the binding's "
            f"backend_input_hash {binding.backend_input_hash!r}")
    evidence_config_hash = _require_str(evidence_doc,
                                        "backend_config_hash", "evidence")
    if evidence_config_hash != binding.backend_config_hash:
        raise _refuse(
            "evidence.backend_config_hash",
            f"{evidence_config_hash!r} does not match the binding's "
            f"backend_config_hash {binding.backend_config_hash!r}")
    evidence_resolved = _require_str(evidence_doc, "resolved_fabric_hash",
                                     "evidence")
    if expected_resolved_fabric_hash is not None and \
            evidence_resolved != expected_resolved_fabric_hash:
        raise _refuse(
            "evidence.resolved_fabric_hash",
            f"{evidence_resolved!r} does not match the compiled fabric "
            f"{expected_resolved_fabric_hash!r}")
    return evidence_resolved


def _check_chain_identity(chain: Any, *, design_hash: str,
                          workload_id: str,
                          resolved_fabric_hash: str | None) -> tuple[str, str]:
    """The result's Wave-D chain must describe this triple."""
    chain_design_hash = _require_str(chain, "design_hash", "wave_d_chain")
    chain_workload_id = _require_str(chain, "workload_graph_id",
                                     "wave_d_chain")
    chain_traffic_id = _require_str(chain, "physical_traffic_id",
                                    "wave_d_chain")
    chain_resolved = _require_str(chain, "resolved_fabric_hash",
                                  "wave_d_chain")
    if chain_design_hash != design_hash:
        raise _refuse(
            "wave_d_chain.design_hash",
            f"{chain_design_hash!r} does not match the design "
            f"{design_hash!r}")
    if chain_workload_id != workload_id:
        raise _refuse(
            "wave_d_chain.workload_graph_id",
            f"{chain_workload_id!r} is not this workload's id "
            f"{workload_id!r}")
    if resolved_fabric_hash is not None and \
            chain_resolved != resolved_fabric_hash:
        raise _refuse(
            "wave_d_chain.resolved_fabric_hash",
            f"{chain_resolved!r} does not match the compiled fabric "
            f"{resolved_fabric_hash!r}")
    return chain_traffic_id, chain_resolved


def _check_binding_identity(binding: NetworkWindowBinding, *, workload_id: str,
                            chain_traffic_id: str) -> None:
    if binding.workload_parent_id != workload_id:
        raise _refuse(
            "network_binding.workload_graph_id",
            f"{binding.workload_parent_id!r} is not this workload's id "
            f"{workload_id!r}")
    if binding.physical_traffic_id != chain_traffic_id:
        raise _refuse(
            "network_binding.physical_traffic_id",
            f"{binding.physical_traffic_id!r} does not match the chain's "
            f"{chain_traffic_id!r}")


def _re_derive_lowering(request: CompileRequestV3) -> Any:
    try:
        return lower_compile_workload(request)
    except (InvalidInput, UnsupportedSemantics, UnsupportedSchedule) as exc:
        raise _refuse(
            "workload",
            f"the request does not lower: {type(exc).__name__}: "
            f"{exc}") from exc


def _evidence_producer(evidence_doc: Mapping[str, Any]) -> str:
    producer = evidence_doc.get("booksim_binary_sha256")
    if not isinstance(producer, str) or not producer:
        raise _refuse(
            "evidence.booksim_binary_sha256",
            f"evidence names no producer identity, got {producer!r}")
    return producer


def _derive_report(request: CompileRequestV3, workload: WorkloadGraph,
                   verified_result: VerifiedPerformanceResult
                   ) -> dict[str, Any]:
    try:
        return RequirementEvaluator.evaluate(request, workload,
                                             verified_result)
    except (InvalidInput, MappingInvalid, EvidenceInvalid) as exc:
        raise _refuse(
            "requirement_report",
            f"re-derivation refused: {type(exc).__name__}: {exc}") from exc


def authenticate_backend_evaluation(
    *, compilation: Any, workload: Any, verified_result: Any,
    evidence_path: Any, producer_identity: str | None = None,
) -> AuthenticatedBackendEvaluation:
    """Prove a backend evaluation from its persisted evidence bytes.

    Refuses (``EvidenceInvalid`` naming the mismatch): a non-COMPILED
    compilation, a workload that is not the compilation request's
    re-derived lowering, a result whose chain/binding does not describe
    this triple, unreadable evidence, an evidence digest that does not
    match the binding, a stats/backend-input/config/fabric mismatch, a
    missing or mismatched producer identity, or a RequirementReport that
    cannot be re-derived. Wrong argument types raise ``InvalidInput``.
    """
    if not isinstance(compilation, Compilation):
        raise InvalidInput(
            f"authenticate_backend_evaluation takes a Compilation, got "
            f"{type(compilation).__name__}")
    if compilation.status != "COMPILED" or compilation.bundle is None:
        raise _refuse(
            "compilation",
            f"must be COMPILED with a bundle, got {compilation.status}")
    certificate = compilation.certificate
    if certificate is None or getattr(certificate, "overall", None) != "PASS":
        raise _refuse(
            "compilation",
            "certificate is not PASS — a failed proof is not a fabric")
    if not isinstance(workload, WorkloadGraph):
        raise InvalidInput(
            f"authenticate_backend_evaluation takes a WorkloadGraph, got "
            f"{type(workload).__name__}")
    if not isinstance(verified_result, VerifiedPerformanceResult):
        raise InvalidInput(
            "authenticate_backend_evaluation takes a "
            "VerifiedPerformanceResult produced by "
            "verify_performance_result(); a naked result dict is not "
            "authenticated content")
    request = compilation.request
    if not isinstance(request, CompileRequestV3):
        raise _refuse(
            "compilation",
            f"request is {type(request).__name__}, not a v3 intent — "
            f"there is no lowering authority to re-derive the workload "
            f"from")

    # ── re-derive the workload (content identity, never provenance) ──
    expected = _re_derive_lowering(request)
    design_hash = request.design_hash()
    workload_id = workload.workload_id()
    if workload_id != expected.graph.workload_id():
        raise _refuse(
            "workload",
            f"{workload_id!r} is not the lowering of design "
            f"{design_hash!r} ({expected.graph.workload_id()!r})")

    # ── the binding this result claims, then the REAL bytes ────────
    binding = _parse_binding(verified_result)
    ref, artifact, evidence_doc = _open_evidence(evidence_path, binding)

    resolved_fabric_hash = \
        compilation.bundle.resolved_fabric.resolved_fabric_hash()
    chain = verified_result.get("wave_d_chain")
    chain_traffic_id, chain_resolved = _check_chain_identity(
        chain, design_hash=design_hash, workload_id=workload_id,
        resolved_fabric_hash=resolved_fabric_hash)
    _check_binding_identity(binding, workload_id=workload_id,
                            chain_traffic_id=chain_traffic_id)
    evidence_resolved = _check_artifact_against_binding(
        artifact, binding, evidence_doc, resolved_fabric_hash)
    if chain_resolved != evidence_resolved:
        raise _refuse(
            "wave_d_chain.resolved_fabric_hash",
            f"{chain_resolved!r} does not match the evidence's "
            f"resolved_fabric_hash {evidence_resolved!r}")

    # ── producer identity from the authenticated evidence ──────────
    evidence_producer = _evidence_producer(evidence_doc)
    if producer_identity is not None:
        if not isinstance(producer_identity, str) or not producer_identity:
            raise InvalidInput(
                "producer_identity must be a non-empty string or None, "
                f"got {producer_identity!r}")
        if evidence_producer != producer_identity:
            raise _refuse(
                "producer_identity",
                f"{producer_identity!r} does not match the evidence's "
                f"booksim_binary_sha256 {evidence_producer!r}")

    # ── canonical requirement report, re-derived (never trusted) ───
    report = _derive_report(request, workload, verified_result)

    return AuthenticatedBackendEvaluation(
        design_hash=design_hash,
        workload_id=workload_id,
        physical_traffic_id=binding.physical_traffic_id,
        backend_input_hash=binding.backend_input_hash,
        evidence_ref=ref,
        evidence_artifact=artifact,
        producer_identity=evidence_producer,
        binding=binding,
        verified_result=verified_result,
        requirement_report=report,
    )


def _metric_handles(verified_result: VerifiedPerformanceResult,
                    ref: EvidenceRef, artifact: EvidenceArtifact
                    ) -> tuple[dict[str, float],
                               tuple[MetricEvidenceHandle, ...]]:
    """Registered metric authority over the verified result (one
    producer registry, imported lazily so ``application`` does not pull
    ``optimization`` at module load)."""
    from veritx_dse.optimization.metric_authority import (
        extract_authoritative_metrics,
    )
    metrics: dict[str, float] = {}
    handles: list[MetricEvidenceHandle] = []
    values = extract_authoritative_metrics(verified_result)
    for metric in sorted(values):
        value = values[metric]
        metrics[metric] = value
        handles.append(MetricEvidenceHandle(
            metric=metric, value=value, producer=metric,
            evidence_sha256=ref.sha256,
            stats_sha256=artifact.stats_sha256))
    return metrics, tuple(handles)


def verify_authenticated_backend_evaluation(
    candidate_request: Any, proof: Any,
) -> VerifiedEvaluationClaims:
    """Re-check the whole evidence chain and return DERIVED claims.

    Consumption-time authority: re-opens the evidence bytes named by the
    proof's ``EvidenceRef``, rebuilds the ``EvidenceArtifact``, re-checks
    the binding digests, the verified result's chain, the candidate
    request's re-derived lowering and the RequirementReport identity. A
    fabricated proof object, a wrong ``EvidenceRef.sha256``, a mismatched
    artifact, or a transplanted request refuses with ``EvidenceInvalid``.
    No claim is ever accepted from the caller.
    """
    if not isinstance(candidate_request, CompileRequestV3):
        raise InvalidInput(
            f"verify_authenticated_backend_evaluation takes a "
            f"CompileRequestV3, got {type(candidate_request).__name__}")
    if not isinstance(proof, AuthenticatedBackendEvaluation):
        raise InvalidInput(
            "verify_authenticated_backend_evaluation takes an "
            "AuthenticatedBackendEvaluation proof, got "
            f"{type(proof).__name__}")

    # ── request/workload/design identity re-derived from the CANDIDATE
    expected = _re_derive_lowering(candidate_request)
    design_hash = candidate_request.design_hash()
    workload_id = expected.graph.workload_id()
    if proof.design_hash != design_hash:
        raise _refuse(
            "proof.design_hash",
            f"{proof.design_hash!r} is not the candidate request's "
            f"design {design_hash!r} — refusing a transplanted proof")
    if proof.workload_id != workload_id:
        raise _refuse(
            "proof.workload_id",
            f"{proof.workload_id!r} is not the candidate request's "
            f"lowering {workload_id!r} — refusing a transplanted proof")

    verified_result = proof.verified_result
    if not isinstance(verified_result, VerifiedPerformanceResult):
        raise _refuse(
            "proof.verified_result",
            "is not a VerifiedPerformanceResult produced by "
            "verify_performance_result()")

    # ── re-open the exact evidence bytes named by the proof ────────
    ref = proof.evidence_ref
    if not isinstance(ref, EvidenceRef):
        raise _refuse(
            "proof.evidence_ref",
            f"must be an EvidenceRef, got {type(ref).__name__}")
    binding = _parse_binding(verified_result)
    if binding != proof.binding:
        raise _refuse(
            "proof.binding",
            "does not equal the binding inside the verified result "
            "document — refusing a fabricated proof field")
    reopened_ref, artifact, evidence_doc = _open_evidence(ref.path, binding)
    if reopened_ref.sha256 != ref.sha256:
        raise _refuse(
            "proof.evidence_ref.sha256",
            f"{ref.sha256!r} does not match the reopened evidence bytes "
            f"{reopened_ref.sha256!r}")
    if artifact != proof.evidence_artifact:
        raise _refuse(
            "proof.evidence_artifact",
            "does not equal the artifact rebuilt from the reopened "
            "evidence bytes — refusing a fabricated proof field")

    # ── the chain must describe the CANDIDATE triple ───────────────
    chain = verified_result.get("wave_d_chain")
    chain_traffic_id, chain_resolved = _check_chain_identity(
        chain, design_hash=design_hash, workload_id=workload_id,
        resolved_fabric_hash=None)
    _check_binding_identity(binding, workload_id=workload_id,
                            chain_traffic_id=chain_traffic_id)
    if proof.physical_traffic_id != binding.physical_traffic_id:
        raise _refuse(
            "proof.physical_traffic_id",
            f"{proof.physical_traffic_id!r} is not the binding's "
            f"{binding.physical_traffic_id!r}")
    if proof.backend_input_hash != binding.backend_input_hash:
        raise _refuse(
            "proof.backend_input_hash",
            f"{proof.backend_input_hash!r} is not the binding's "
            f"backend_input_hash {binding.backend_input_hash!r}")
    evidence_resolved = _check_artifact_against_binding(
        artifact, binding, evidence_doc, None)
    if chain_resolved != evidence_resolved:
        raise _refuse(
            "wave_d_chain.resolved_fabric_hash",
            f"{chain_resolved!r} does not match the evidence's "
            f"resolved_fabric_hash {evidence_resolved!r}")

    # ── producer identity re-derived from the evidence ─────────────
    evidence_producer = _evidence_producer(evidence_doc)
    if proof.producer_identity != evidence_producer:
        raise _refuse(
            "proof.producer_identity",
            f"{proof.producer_identity!r} is not the evidence's "
            f"booksim_binary_sha256 {evidence_producer!r}")

    # ── canonical report re-derived over the CANDIDATE lowering ────
    report = _derive_report(candidate_request, expected.graph,
                            verified_result)
    carried_report = proof.requirement_report
    if not isinstance(carried_report, Mapping):
        raise _refuse(
            "proof.requirement_report",
            f"must be a mapping, got {type(carried_report).__name__}")
    carried_id = report_identity(carried_report)
    derived_id = report_identity(report)
    if carried_id != derived_id:
        raise _refuse(
            "proof.requirement_report",
            f"carried report identity {carried_id!r} does not match the "
            f"re-derived canonical identity {derived_id!r} — refusing a "
            f"fabricated or transplanted report")
    result_id = verified_result.get("resource_id")
    if not isinstance(result_id, str) or not result_id:
        raise _refuse(
            "verified_result.resource_id",
            f"must be a non-empty string, got {result_id!r}")
    if report.get("performance_result_id") != result_id:
        raise _refuse(
            "requirement_report.performance_result_id",
            f"{report.get('performance_result_id')!r} is not the "
            f"verified result's resource_id {result_id!r}")

    metrics, handles = _metric_handles(verified_result, reopened_ref,
                                       artifact)
    execution_transport = evidence_doc.get("execution_transport")
    backend = (execution_transport
               if isinstance(execution_transport, str) and
               execution_transport else artifact.backend)
    qualification = evidence_doc.get("qualification")
    backend_profile = (qualification
                       if isinstance(qualification, str) and qualification
                       else None)
    return VerifiedEvaluationClaims(
        design_hash=design_hash,
        workload_id=workload_id,
        physical_traffic_id=binding.physical_traffic_id,
        performance_result_id=result_id,
        requirement_report=report,
        requirement_report_id=derived_id,
        metrics=metrics,
        metric_evidence=handles,
        producer_identity=evidence_producer,
        backend=backend,
        backend_profile=backend_profile,
        backend_config_hash=binding.backend_config_hash,
        backend_input_hash=binding.backend_input_hash,
        resolved_fabric_hash=evidence_resolved,
        evidence_ref=reopened_ref,
        evidence_artifact=artifact,
        binding=binding,
        verified_result=verified_result,
    )


__all__ = [
    "AuthenticatedBackendEvaluation",
    "EVALUATION_AUTHORITY",
    "MetricEvidenceHandle",
    "VerifiedEvaluationClaims",
    "authenticate_backend_evaluation",
    "verify_authenticated_backend_evaluation",
]
