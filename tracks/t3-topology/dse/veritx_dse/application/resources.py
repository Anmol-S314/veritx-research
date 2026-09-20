"""veritx_dse.application.resources — typed control-plane resources.

Every product-visible entity is a frozen, versioned, content-identified
record. Wave-B hashes are REFERENCED, never recomputed into parallel
"control-plane fingerprints" (§96). Content-derived IDs use the Wave-B
canonical JSON encoder.

Resource kinds: intent, design, plan, experiment, attempt, result,
comparison. Attempt IDs are uuid7 (reuse ``core.runs.new_run_id``);
everything else is content-derived.
"""
from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from typing import Any

from .errors import ControlPlaneError, ErrorCode

RESOURCE_SCHEMA_VERSION = 1


def _content_id(tag: str, body: dict[str, Any]) -> str:
    from veritx_dse.core.spec import canonical_json
    return hashlib.sha256(
        (tag + "\0" + canonical_json(body)).encode()).hexdigest()


def _as_id(value: Any, name: str) -> str:
    if not isinstance(value, str) or not value:
        raise ValueError(f"{name} must be a non-empty string")
    return value


@dataclass(frozen=True)
class CompiledDesign:
    intent_id: str
    design_hash: str
    mapping_hash: str
    fabric_hash: str
    topology_hash: str
    attachment_hash: str
    compile_request: dict[str, Any]

    @property
    def resource_type(self) -> str:
        return "design"

    def resource_id(self) -> str:
        return _content_id("srota-design/v1", {
            "intent_id": self.intent_id,
            "design_hash": self.design_hash,
            "mapping_hash": self.mapping_hash,
            "fabric_hash": self.fabric_hash,
        })

    def to_dict(self) -> dict[str, Any]:
        return {
            "resource_type": self.resource_type,
            "schema_version": RESOURCE_SCHEMA_VERSION,
            "resource_id": self.resource_id(),
            "intent_id": self.intent_id,
            "design_hash": self.design_hash,
            "mapping_hash": self.mapping_hash,
            "fabric_hash": self.fabric_hash,
            "topology_hash": self.topology_hash,
            "attachment_hash": self.attachment_hash,
            "compile_request": self.compile_request,
        }


@dataclass(frozen=True)
class WorkloadRecord:
    trace_sha256: str
    trace_bytes: int
    endpoint_count: int
    packets: int
    source: dict[str, Any]

    @property
    def resource_type(self) -> str:
        return "workload"

    def workload_id(self) -> str:
        return _content_id("srota-workload/v1", {
            "trace_sha256": self.trace_sha256,
            "trace_bytes": self.trace_bytes,
            "endpoint_count": self.endpoint_count,
        })

    def to_dict(self) -> dict[str, Any]:
        return {
            "resource_type": self.resource_type,
            "schema_version": RESOURCE_SCHEMA_VERSION,
            "resource_id": self.workload_id(),
            "trace_sha256": self.trace_sha256,
            "trace_bytes": self.trace_bytes,
            "endpoint_count": self.endpoint_count,
            "packets": self.packets,
            "source": dict(self.source),
        }


@dataclass(frozen=True)
class EvaluationPlan:
    plan_id: str
    intent_id: str
    design_id: str
    workload_id: str
    design_hash: str
    mapping_hash: str
    fabric_hash: str
    workload_hash: str
    backend_target: str
    backend_profile: str
    backend_semantics_version: str
    lowerer_version: str
    execution_mode: str
    seed: int | None
    seed_policy: str
    metric_ids: tuple[str, ...]
    metric_schema_version: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "resource_type": "plan",
            "schema_version": RESOURCE_SCHEMA_VERSION,
            "resource_id": self.plan_id,
            "intent_id": self.intent_id,
            "design_id": self.design_id,
            "workload_id": self.workload_id,
            "design_hash": self.design_hash,
            "mapping_hash": self.mapping_hash,
            "fabric_hash": self.fabric_hash,
            "workload_hash": self.workload_hash,
            "backend_target": self.backend_target,
            "backend_profile": self.backend_profile,
            "backend_semantics_version": self.backend_semantics_version,
            "lowerer_version": self.lowerer_version,
            "execution_mode": self.execution_mode,
            "seed": self.seed,
            "seed_policy": self.seed_policy,
            "metric_ids": list(self.metric_ids),
            "metric_schema_version": self.metric_schema_version,
        }


@dataclass(frozen=True)
class ExperimentRecord:
    experiment_id: str
    plan_id: str
    backend_config_hash: str
    backend_input_hash: str
    execution_mode: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "resource_type": "experiment",
            "schema_version": RESOURCE_SCHEMA_VERSION,
            "resource_id": self.experiment_id,
            "plan_id": self.plan_id,
            "backend_config_hash": self.backend_config_hash,
            "backend_input_hash": self.backend_input_hash,
            "execution_mode": self.execution_mode,
        }


@dataclass(frozen=True)
class AttemptRecord:
    attempt_id: str
    experiment_id: str
    status: str
    backend_dir: str
    producer: dict[str, Any]
    error: dict[str, Any] | None = None
    evidence_ref: dict[str, Any] | None = None
    runtime: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "resource_type": "attempt",
            "schema_version": RESOURCE_SCHEMA_VERSION,
            "resource_id": self.attempt_id,
            "experiment_id": self.experiment_id,
            "status": self.status,
            "backend_dir": self.backend_dir,
            "producer": dict(self.producer),
            "error": dict(self.error) if self.error is not None else None,
            "evidence_ref": dict(self.evidence_ref)
            if self.evidence_ref is not None else None,
            "runtime": dict(self.runtime),
        }


@dataclass(frozen=True)
class EvaluationResult:
    result_id: str
    experiment_id: str
    attempt_id: str
    plan_id: str
    design_id: str
    workload_id: str
    design_hash: str
    mapping_hash: str
    fabric_hash: str
    workload_hash: str
    backend_target: str
    backend_profile: str
    backend_semantics_version: str
    backend_config_hash: str
    backend_input_hash: str
    execution_mode: str
    status: str
    qualification: str
    execution_transport: str
    semantic_loss: tuple[dict[str, Any], ...]
    loss_digest: str
    metrics: tuple[dict[str, Any], ...]
    metric_schema_version: str
    evidence_ref: dict[str, Any]
    producer: dict[str, Any]
    seed: int | None
    seed_policy: str
    reused: bool

    def to_dict(self) -> dict[str, Any]:
        return {
            "resource_type": "result",
            "schema_version": RESOURCE_SCHEMA_VERSION,
            "resource_id": self.result_id,
            "experiment_id": self.experiment_id,
            "attempt_id": self.attempt_id,
            "plan_id": self.plan_id,
            "design_id": self.design_id,
            "workload_id": self.workload_id,
            "design_hash": self.design_hash,
            "mapping_hash": self.mapping_hash,
            "fabric_hash": self.fabric_hash,
            "workload_hash": self.workload_hash,
            "backend_target": self.backend_target,
            "backend_profile": self.backend_profile,
            "backend_semantics_version": self.backend_semantics_version,
            "backend_config_hash": self.backend_config_hash,
            "backend_input_hash": self.backend_input_hash,
            "execution_mode": self.execution_mode,
            "status": self.status,
            "qualification": self.qualification,
            "execution_transport": self.execution_transport,
            "semantic_loss": [dict(r) for r in self.semantic_loss],
            "loss_digest": self.loss_digest,
            "metrics": [dict(m) for m in self.metrics],
            "metric_schema_version": self.metric_schema_version,
            "evidence_ref": dict(self.evidence_ref),
            "producer": dict(self.producer),
            "seed": self.seed,
            "seed_policy": self.seed_policy,
            "reused": self.reused,
        }


@dataclass(frozen=True)
class StudyResult:
    study_id: str
    name: str
    candidate_intents: tuple[str, ...]
    experiments: tuple[dict[str, Any], ...]
    comparisons: tuple[dict[str, Any], ...]
    comparison_request: dict[str, Any] | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "resource_type": "study",
            "schema_version": RESOURCE_SCHEMA_VERSION,
            "resource_id": self.study_id,
            "name": self.name,
            "candidate_intents": list(self.candidate_intents),
            "experiments": [dict(e) for e in self.experiments],
            "comparisons": [dict(c) for c in self.comparisons],
            "comparison_request": dict(self.comparison_request)
            if self.comparison_request is not None else None,
        }


@dataclass(frozen=True)
class ComparisonResult:
    comparison_id: str
    candidate_ids: tuple[str, ...]
    contract: dict[str, Any]
    compatibility: dict[str, Any]
    metrics: tuple[dict[str, Any], ...]
    fidelity_context: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return {
            "resource_type": "comparison",
            "schema_version": RESOURCE_SCHEMA_VERSION,
            "resource_id": self.comparison_id,
            "candidate_ids": list(self.candidate_ids),
            "contract": dict(self.contract),
            "compatibility": dict(self.compatibility),
            "metrics": [dict(m) for m in self.metrics],
            "fidelity_context": dict(self.fidelity_context),
        }


def check_envelope(d: Any, expected_type: str) -> dict[str, Any]:
    """Validate a persisted resource envelope (type + schema version)."""
    if not isinstance(d, dict):
        raise ControlPlaneError(
            ErrorCode.INTERNAL_ERROR,
            f"resource must be an object, got {type(d).__name__}",
            operation="inspect")
    if d.get("resource_type") != expected_type:
        raise ControlPlaneError(
            ErrorCode.INTERNAL_ERROR,
            f"expected resource_type {expected_type!r}, got "
            f"{d.get('resource_type')!r}",
            operation="inspect")
    if d.get("schema_version") != RESOURCE_SCHEMA_VERSION:
        raise ControlPlaneError(
            ErrorCode.INTERNAL_ERROR,
            f"unsupported {expected_type} schema_version "
            f"{d.get('schema_version')!r} (this build speaks "
            f"v{RESOURCE_SCHEMA_VERSION})",
            operation="inspect")
    return d


__all__ = [
    "RESOURCE_SCHEMA_VERSION",
    "AttemptRecord",
    "CompiledDesign",
    "ComparisonResult",
    "EvaluationPlan",
    "EvaluationResult",
    "ExperimentRecord",
    "StudyResult",
    "WorkloadRecord",
    "check_envelope",
]
