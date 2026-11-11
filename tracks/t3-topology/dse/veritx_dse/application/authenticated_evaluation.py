"""veritx_dse.application.authenticated_evaluation — backend evidence proof.

Rationale: docs/decisions/modules/application.md
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
    EVIDENCE_SCHEMA_VERSION,
    BackendEvidenceError,
    EvidenceArtifact,
    EvidenceRef,
    ScientificBackendEvidence,
    admit_for_certified_product,
    read_verified_evidence,
    validate_evidence_document,
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
from veritx_dse.workload.graph import WorkloadGraph
from veritx_dse.workload.intent_lowering import lower_compile_workload

EVALUATION_AUTHORITY = "certified-backend"

@dataclass(frozen=True)
class AuthenticatedBackendEvaluation:
    """One backend evaluation whose evidence chain was re-proven.

Rationale: docs/decisions/modules/application.md
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
class VerifiedEvaluationClaims:
    """Consumption-time derived claims for one authenticated evaluation.

Rationale: docs/decisions/modules/application.md
    """

    design_hash: str
    workload_id: str
    physical_traffic_id: str
    performance_result_id: str
    requirement_report: dict[str, Any]
    requirement_report_id: str
    producer_identity: str
    backend: str
    backend_profile: str
    execution_fidelity: str
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
        evidence_doc = validate_evidence_document(
            read_verified_evidence(ref))
        if evidence_doc.get("schema_version") != EVIDENCE_SCHEMA_VERSION:
            raise BackendEvidenceError(
                "evidence is not the current schema; it cannot certify")
        admit_for_certified_product(
            ScientificBackendEvidence.from_dict(evidence_doc))
        artifact = EvidenceArtifact.build(
            backend=evidence_doc["profile_id"],
            backend_input_id=evidence_doc["trace_sha256"],
            backend_input_sha256=evidence_doc["trace_sha256"],
            raw_evidence_sha256=ref.sha256,
            stats=evidence_doc["stats"],
            parser_version=evidence_doc["parser_version"])
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
                                        "config_sha256", "evidence")
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
    producer = evidence_doc.get("binary_sha256")
    if not isinstance(producer, str) or not producer:
        raise _refuse(
            "evidence.binary_sha256",
            f"evidence names no producer identity, got {producer!r}")
    return producer


def _bare_digest(value: Any) -> Any:
    return value[7:] if isinstance(value, str) \
        and value.startswith("sha256:") else value


def _check_traffic_class_metrics_binding(
        block: Any, *, evidence_sha256: str, stats_sha256: str) -> None:
    """A per-class block must name exactly the evidence it was read from."""
    from veritx_dse.performance.traffic_class import (
        TrafficClassMetricsError, validate_traffic_class_metrics,
    )
    try:
        validate_traffic_class_metrics(block)
    except TrafficClassMetricsError as exc:
        raise _refuse(
            "verified_result.traffic_class_metrics",
            f"malformed per-class evidence: {exc}") from exc
    if _bare_digest(block["evidence_sha256"]) != \
            _bare_digest(evidence_sha256):
        raise _refuse(
            "verified_result.traffic_class_metrics.evidence_sha256",
            f"{block['evidence_sha256']!r} is not the authenticated "
            f"evidence digest {evidence_sha256!r}")
    if _bare_digest(block["stats_sha256"]) != _bare_digest(stats_sha256):
        raise _refuse(
            "verified_result.traffic_class_metrics.stats_sha256",
            f"{block['stats_sha256']!r} is not the authenticated stats "
            f"digest {stats_sha256!r}")


def _ensure_traffic_class_metrics(
        *, compilation: Any, verified_result: VerifiedPerformanceResult,
        evidence_doc: Mapping[str, Any], evidence_sha256: str,
        stats_sha256: str) -> None:
    """Attach per-class readings derived from the authenticated evidence.

    Optional enrichment: when the canonical traffic or packet format
    cannot be rebuilt, the block stays absent and class-scoped
    requirements stay honestly UNMEASURABLE.  An already-present block is
    validated and digest-bound, never overwritten.
    """
    existing = verified_result.get("traffic_class_metrics")
    if existing is not None:
        _check_traffic_class_metrics_binding(
            existing, evidence_sha256=evidence_sha256,
            stats_sha256=stats_sha256)
        return
    try:
        from veritx_dse.application.evaluation_context import (
            build_evaluation_context,
        )
        from veritx_dse.backend.booksim_adapter import BookSimAdapter
        from veritx_dse.backend.booksim_projection import trace_class_map
        from veritx_dse.performance.traffic_class import (
            build_traffic_class_metrics,
        )
        context = build_evaluation_context(compilation)
        _logical, physical = BookSimAdapter()._canonical_traffic(
            context, traffic_class=context.unified_traffic_class)
        classes = tuple(trace_class_map(physical))
        if len(classes) <= 1:
            return
        block = build_traffic_class_metrics(
            stats=evidence_doc["stats"],
            class_names=classes,
            flit_width_bits=physical.packet_format.flit_width_bits,
            evidence_sha256=evidence_sha256, stats_sha256=stats_sha256)
    except Exception:  # optional enrichment: never fail authentication
        return
    if block is not None:
        verified_result["traffic_class_metrics"] = block


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

Rationale: docs/decisions/modules/application.md
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
    from veritx_dse.model.generation import is_v4_request
    if not isinstance(request, CompileRequestV3) \
            and not is_v4_request(request):
        raise _refuse(
            "compilation",
            f"request is {type(request).__name__}, not a v3 or v4 intent — "
            f"there is no lowering authority to re-derive the workload "
            f"from")

    expected = _re_derive_lowering(request)
    design_hash = request.design_hash()
    workload_id = workload.workload_id()
    if workload_id != expected.graph.workload_id():
        raise _refuse(
            "workload",
            f"{workload_id!r} is not the lowering of design "
            f"{design_hash!r} ({expected.graph.workload_id()!r})")

    binding = _parse_binding(verified_result)
    ref, artifact, evidence_doc = _open_evidence(evidence_path, binding)

    resolved_fabric_hash = \
        compilation.bundle.resolved_fabric.resolved_fabric_hash
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

    _ensure_traffic_class_metrics(
        compilation=compilation, verified_result=verified_result,
        evidence_doc=evidence_doc, evidence_sha256=ref.sha256,
        stats_sha256=artifact.stats_sha256)

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
                f"binary_sha256 {evidence_producer!r}")

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

def verify_authenticated_backend_evaluation(
    candidate_request: Any, proof: Any,
) -> VerifiedEvaluationClaims:
    """Re-check the whole evidence chain and return DERIVED claims.

Rationale: docs/decisions/modules/application.md
    """
    from veritx_dse.model.generation import is_v4_request
    if not isinstance(candidate_request, CompileRequestV3) and not is_v4_request(candidate_request):
        raise InvalidInput(
            f"verify_authenticated_backend_evaluation takes a "
            f"CompileRequestV3 or CompileRequestV4, got {type(candidate_request).__name__}")
    if not isinstance(proof, AuthenticatedBackendEvaluation):
        raise InvalidInput(
            "verify_authenticated_backend_evaluation takes an "
            "AuthenticatedBackendEvaluation proof, got "
            f"{type(proof).__name__}")

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

    class_block = verified_result.get("traffic_class_metrics")
    if class_block is not None:
        _check_traffic_class_metrics_binding(
            class_block, evidence_sha256=reopened_ref.sha256,
            stats_sha256=artifact.stats_sha256)
        from veritx_dse.model.compile_model import (
            derive_v3_traffic_classes,
        )
        from veritx_dse.performance.traffic_class import (
            TrafficClassMetricsError, build_traffic_class_metrics,
        )
        declared = set(derive_v3_traffic_classes(candidate_request))
        names = tuple(class_block["class_names"])
        if list(names) != sorted(names) or not set(names) <= declared:
            raise _refuse(
                "verified_result.traffic_class_metrics.class_names",
                f"{list(names)} is not a sorted subset of the request's "
                f"declared traffic classes {sorted(declared)}")
        declared_width = getattr(
            getattr(candidate_request, "noc_config", None), "link_width", None)
        if declared_width is not None and class_block["flit_width_bits"] \
                != declared_width:
            raise _refuse(
                "verified_result.traffic_class_metrics.flit_width_bits",
                f"{class_block['flit_width_bits']!r} is not the request's "
                f"declared link width {declared_width!r}")
        try:
            recomputed = build_traffic_class_metrics(
                stats=evidence_doc["stats"], class_names=names,
                flit_width_bits=class_block["flit_width_bits"],
                evidence_sha256=class_block["evidence_sha256"],
                stats_sha256=class_block["stats_sha256"])
        except TrafficClassMetricsError as exc:
            raise _refuse(
                "verified_result.traffic_class_metrics",
                f"cannot re-derive per-class readings from the "
                f"authenticated stats: {exc}") from exc
        if recomputed != class_block:
            raise _refuse(
                "verified_result.traffic_class_metrics",
                "per-class readings do not re-derive from the "
                "authenticated evidence stats — refusing transcribed or "
                "tampered class values")

    evidence_producer = _evidence_producer(evidence_doc)
    if proof.producer_identity != evidence_producer:
        raise _refuse(
            "proof.producer_identity",
            f"{proof.producer_identity!r} is not the evidence's "
            f"binary_sha256 {evidence_producer!r}")

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

    # backend_profile carries the PROFILE identity and execution_fidelity
    # carries the fidelity verdict — two different facts in two fields, never
    # overloaded. The fidelity vocabulary itself is enforced where the
    # evidence document is parsed; here both values must simply be present.
    backend = _require_str(
        evidence_doc, "profile_id", "evidence")
    backend_profile = _require_str(
        evidence_doc, "profile_id", "evidence.backend_profile")
    execution_fidelity = _require_str(
        evidence_doc, "execution_fidelity", "evidence.execution_fidelity")
    return VerifiedEvaluationClaims(
        design_hash=design_hash,
        workload_id=workload_id,
        physical_traffic_id=binding.physical_traffic_id,
        performance_result_id=result_id,
        requirement_report=report,
        requirement_report_id=derived_id,
        producer_identity=evidence_producer,
        backend=backend,
        backend_profile=backend_profile,
        execution_fidelity=execution_fidelity,
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
    "VerifiedEvaluationClaims",
    "authenticate_backend_evaluation",
    "verify_authenticated_backend_evaluation",
]
