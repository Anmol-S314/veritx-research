"""veritx_dse.application.results — verified resource loading (Wave C.2).

Scientific consumers must NEVER use ``store.get()`` directly: every
content-identified resource proves, on load, that its current canonical
contents still produce its claimed ID:

    requested filename ID == embedded resource_id == recomputed ID

plus linkage and Wave-B evidence derivations. Anything else refuses
with EVIDENCE_INVALID (corrupt store links) or NOT_FOUND. Raw
``store.get()`` is inspection/internal storage access only.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from .errors import ControlPlaneError, ErrorCode
from .studies import STUDY_CANDIDATE_STATUSES

# Wave-C resource envelope (local — the canonical resources.py owns the
# 4-kind CompileIntent persistence and must not be overwritten with the
# old generic envelope; evaluation-plane records carry their own).
RESOURCE_SCHEMA_VERSION = 1


def check_envelope(d: Any, expected_type: str) -> dict[str, Any]:
    """Validate a persisted evaluation resource envelope."""
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


def loss_digest_of(loss: list[dict[str, Any]]) -> str:
    """Canonical digest over dimension-sorted semantic loss rows."""
    from veritx_dse.core.spec import canonical_json
    ordered = sorted((dict(r) for r in loss),
                     key=lambda r: r.get("dimension", ""))
    return hashlib.sha256(canonical_json(ordered).encode()).hexdigest()


def _content_id(tag: str, body: dict[str, Any]) -> str:
    from veritx_dse.core.spec import canonical_json
    return hashlib.sha256(
        (tag + "\0" + canonical_json(body)).encode()).hexdigest()


def _get(store: Any, kind: str, resource_id: Any) -> dict[str, Any]:
    if not isinstance(resource_id, str) or not resource_id:
        raise ControlPlaneError(
            ErrorCode.EVIDENCE_INVALID,
            f"invalid {kind} link {resource_id!r}",
            operation="verify_resource")
    try:
        return store.get(kind, resource_id)
    except ControlPlaneError as exc:
        raise ControlPlaneError(
            ErrorCode.EVIDENCE_INVALID,
            f"missing linked {kind} {resource_id!r}: {exc.message}",
            operation="verify_resource",
            resource_id=resource_id) from exc


def _require_id(kind: str, requested_id: str,
                record: dict[str, Any]) -> None:
    embedded = record.get("resource_id")
    if embedded != requested_id:
        raise ControlPlaneError(
            ErrorCode.EVIDENCE_INVALID,
            f"{kind} file {requested_id} embeds resource_id "
            f"{embedded!r}: refusing transplanted content",
            operation="verify_resource", resource_id=requested_id)


def _require_equal(what: str, actual: Any, expected: Any,
                   resource_id: str) -> None:
    if actual != expected:
        raise ControlPlaneError(
            ErrorCode.EVIDENCE_INVALID,
            f"result field {what!r} does not match its authority "
            f"({actual!r} != {expected!r})",
            operation="verify_result", resource_id=resource_id)


def _read_attempt_record(backend_dir: Any, resource_id: str) \
        -> dict[str, Any]:
    """Read the separate execution-attempt record (evidence-v2).

    Host/tool text lives here, not in scientific evidence. A v2 evidence
    document names no ``producer_tool_identity``; the environment record
    does, and the control plane still refuses a store-record tamper by
    re-reading it.
    """
    from veritx_dse.backend.evidence import ATTEMPT_FILE
    if not isinstance(backend_dir, str) or not backend_dir:
        raise ControlPlaneError(
            ErrorCode.EVIDENCE_INVALID,
            f"resource {resource_id} names no backend_dir for its "
            f"execution-attempt record",
            operation="verify_resource", resource_id=resource_id)
    path = Path(backend_dir) / ATTEMPT_FILE
    try:
        data = json.loads(path.read_text())
    except (OSError, ValueError) as exc:
        raise ControlPlaneError(
            ErrorCode.EVIDENCE_INVALID,
            f"execution-attempt record {path} unreadable: {exc}",
            operation="verify_resource", resource_id=resource_id) from exc
    if not isinstance(data, dict):
        raise ControlPlaneError(
            ErrorCode.EVIDENCE_INVALID,
            f"execution-attempt record {path} is not an object",
            operation="verify_resource", resource_id=resource_id)
    return data


def load_verified_intent(store: Any, intent_id: str) -> dict[str, Any]:
    """Intent has no embedded id; requested ID must equal recomputed."""
    from .requests import parse_intent
    record = _get(store, "intent", intent_id)
    try:
        intent = parse_intent({k: v for k, v in record.items()})
    except ControlPlaneError as exc:
        raise ControlPlaneError(
            ErrorCode.EVIDENCE_INVALID,
            f"persisted intent {intent_id} does not parse: {exc.message}",
            operation="verify_resource",
            resource_id=intent_id) from exc
    if intent.intent_id() != intent_id:
        raise ControlPlaneError(
            ErrorCode.EVIDENCE_INVALID,
            f"persisted intent {intent_id} recomputes to "
            f"{intent.intent_id()}: content forged",
            operation="verify_resource", resource_id=intent_id)
    return record


def load_verified_design(store: Any, design_id: str) -> dict[str, Any]:
    """Design ID + recompiled semantic hashes.

    Design identity is content-addressed by its semantic hashes; the
    intent that produced it is NOT part of the record (two intents
    compiling identical fabric share one design resource — only plans
    differ). The design-to-intent link lives on the plan, verified
    there.
    """
    from .compile import compile_bundle
    from veritx_dse.model.compile_model import CompileRequest
    record = _get(store, "design", design_id)
    check_envelope(record, "design")
    _require_id("design", design_id, record)
    recomputed = _content_id("srota-design/v1", {
        "design_hash": record.get("design_hash"),
        "mapping_hash": record.get("mapping_hash"),
        "fabric_hash": record.get("fabric_hash"),
    })
    if recomputed != design_id:
        raise ControlPlaneError(
            ErrorCode.EVIDENCE_INVALID,
            f"design {design_id} recomputes to {recomputed}: forged",
            operation="verify_resource", resource_id=design_id)
    try:
        compile_request = CompileRequest.from_dict(
            record.get("compile_request"))
    except Exception as exc:
        raise ControlPlaneError(
            ErrorCode.EVIDENCE_INVALID,
            f"design {design_id} compile_request does not parse: {exc}",
            operation="verify_resource",
            resource_id=design_id) from exc
    if compile_request.design_hash() != record.get("design_hash"):
        raise ControlPlaneError(
            ErrorCode.EVIDENCE_INVALID,
            f"design {design_id} request hashes to "
            f"{compile_request.design_hash()}, not the recorded "
            f"{record.get('design_hash')}",
            operation="verify_resource", resource_id=design_id)
    try:
        bundle = compile_bundle(compile_request)
    except ControlPlaneError as exc:
        raise ControlPlaneError(
            ErrorCode.EVIDENCE_INVALID,
            f"design {design_id} fails canonical rederivation: "
            f"{exc.message}",
            operation="verify_resource",
            resource_id=design_id) from exc
    for key, actual in (
            ("mapping_hash", bundle.resolved_fabric.mapping_hash),
            ("fabric_hash", bundle.fabric.fabric_hash),
            ("topology_hash", bundle.topology.topology_hash()),
            ("attachment_hash", bundle.attachment.attachment_hash())):
        _require_equal(f"design.{key}", record.get(key), actual, design_id)
    return record


def load_verified_workload(store: Any, workload_id: str) -> dict[str, Any]:
    """Workload content identity.

    The content ID covers trace bytes, byte length and endpoint count
    (plus the verified Wave-D semantic chain for a Wave-D workload).
    ``packets`` and ``source`` are OBSERVATIONAL: they are deliberately
    outside the content hash and must never be read as authenticated
    scientific fields. ``workload_kind`` is the provenance label.

    A Wave-D workload is verified all the way down: the persisted
    semantic chain is re-loaded through its verified loaders, the chain
    block is recomputed, and the derived trace is re-rendered and
    re-hashed against the stored digest.
    """
    record = _get(store, "workload", workload_id)
    check_envelope(record, "workload")
    _require_id("workload", workload_id, record)
    wave_d = record.get("wave_d")
    body: dict[str, Any] = {
        "trace_sha256": record.get("trace_sha256"),
        "trace_bytes": record.get("trace_bytes"),
        "endpoint_count": record.get("endpoint_count"),
    }
    if wave_d is not None:
        body["workload_kind"] = "WAVE_D_SEMANTIC"
        body["wave_d"] = wave_d
    recomputed = _content_id("srota-workload/v1", body)
    if recomputed != workload_id:
        raise ControlPlaneError(
            ErrorCode.EVIDENCE_INVALID,
            f"workload {workload_id} recomputes to {recomputed}: forged",
            operation="verify_resource", resource_id=workload_id)
    if wave_d is not None:
        _verify_waved_workload_chain(store, workload_id, record, wave_d)
    return record


def _verify_waved_workload_chain(store: Any, workload_id: str,
                                 record: dict[str, Any],
                                 wave_d: dict[str, Any]) -> None:
    """Re-derive a Wave-D workload's chain and its derived trace."""
    from veritx_dse.backend.contracts import sha256_bytes
    from veritx_dse.backend.projection import render_waved_trace

    from .waved_resources import (
        chain_ids_from_traffic, load_verified_traffic,
    )
    traffic, _ = load_verified_traffic(
        store, wave_d.get("physical_traffic_id"))
    _require_equal("workload.wave_d", wave_d,
                   chain_ids_from_traffic(traffic), workload_id)
    trace = render_waved_trace(traffic)
    _require_equal("workload.trace_sha256", record.get("trace_sha256"),
                   sha256_bytes(trace), workload_id)
    _require_equal("workload.trace_bytes", record.get("trace_bytes"),
                   len(trace), workload_id)


def _expected_plan_profile(target: str) -> tuple[str, str, str]:
    from veritx_dse.backend.booksim import (
        BOOKSIM_BACKEND_SEMANTICS_VERSION, BOOKSIM_LOWERER_VERSION,
        BOOKSIM_STANDALONE_PROFILE,
    )
    if target == "BOOKSIM_STANDALONE":
        return (BOOKSIM_STANDALONE_PROFILE,
                BOOKSIM_BACKEND_SEMANTICS_VERSION, BOOKSIM_LOWERER_VERSION)
    raise ControlPlaneError(
        ErrorCode.EVIDENCE_INVALID,
        f"plan targets non-executable backend {target!r}",
        operation="verify_resource")


def load_verified_plan(store: Any, plan_id: str) -> dict[str, Any]:
    """Plan ID + links + canonical backend declarations."""
    record = _get(store, "plan", plan_id)
    check_envelope(record, "plan")
    _require_id("plan", plan_id, record)
    body: dict[str, Any] = {
        "design_hash": record.get("design_hash"),
        "mapping_hash": record.get("mapping_hash"),
        "fabric_hash": record.get("fabric_hash"),
        "workload_hash": record.get("workload_hash"),
        "backend_target": record.get("backend_target"),
        "backend_profile": record.get("backend_profile"),
        "backend_semantics_version": record.get(
            "backend_semantics_version"),
        "lowerer_version": record.get("lowerer_version"),
        "execution_mode": record.get("execution_mode"),
        "seed": record.get("seed"),
        "seed_policy": record.get("seed_policy"),
        "metric_ids": record.get("metric_ids"),
        "metric_schema_version": record.get("metric_schema_version"),
    }
    if record.get("wave_d") is not None:
        body["wave_d"] = record.get("wave_d")
    if record.get("wave_e") is not None:
        body["wave_e"] = record.get("wave_e")
    recomputed = _content_id("srota-plan/v1", body)
    if recomputed != plan_id:
        raise ControlPlaneError(
            ErrorCode.EVIDENCE_INVALID,
            f"plan {plan_id} recomputes to {recomputed}: forged",
            operation="verify_resource", resource_id=plan_id)
    design = load_verified_design(store, record.get("design_id"))
    workload = load_verified_workload(store, record.get("workload_id"))
    if record.get("wave_e") is not None:
        _verify_plan_wave_e(store, record, plan_id)
    if record.get("wave_d") is not None:
        from .waved_resources import (
            chain_ids_from_traffic, load_verified_traffic,
        )
        traffic, _ = load_verified_traffic(
            store, record["wave_d"].get("physical_traffic_id"))
        _require_equal("plan.wave_d", record["wave_d"],
                       chain_ids_from_traffic(traffic), plan_id)
        _require_equal("workload.wave_d", workload.get("wave_d"),
                       record["wave_d"], plan_id)
    # The design link is content-addressed; intent binding is on the
    # plan itself (verified via load_verified_intent on the intent_id).
    _require_equal("plan.design_hash", record.get("design_hash"),
                   design.get("design_hash"), plan_id)
    _require_equal("plan.mapping_hash", record.get("mapping_hash"),
                   design.get("mapping_hash"), plan_id)
    _require_equal("plan.fabric_hash", record.get("fabric_hash"),
                   design.get("fabric_hash"), plan_id)
    _require_equal("plan.workload_hash", record.get("workload_hash"),
                   workload.get("trace_sha256"), plan_id)
    profile, semantics, lowerer = _expected_plan_profile(
        record.get("backend_target"))
    _require_equal("plan.backend_profile", record.get("backend_profile"),
                   profile, plan_id)
    _require_equal("plan.backend_semantics_version",
                   record.get("backend_semantics_version"), semantics,
                   plan_id)
    _require_equal("plan.lowerer_version", record.get("lowerer_version"),
                   lowerer, plan_id)
    return record


def _verify_plan_wave_e(store: Any, record: dict[str, Any],
                        plan_id: str) -> None:
    """A plan's Wave-E binding must resolve to a verified overlay.

    Plan identity hashes the block, but that only proves the plan is
    self-consistent: without resolving the parent, a plan could bind a
    temporal workload that does not exist, or whose model is not the
    one it names, or that schedules communication this workload's
    operation graph never performs.
    """
    from .wave_e_resources import (
        PLAN_WAVE_E_KEYS, load_verified_wave_e_workload,
    )
    wave_e = record["wave_e"]
    if not isinstance(wave_e, dict) or \
            set(wave_e) != set(PLAN_WAVE_E_KEYS):
        raise ControlPlaneError(
            ErrorCode.EVIDENCE_INVALID,
            f"plan {plan_id} wave_e binding has the wrong field set",
            operation="verify_resource", resource_id=plan_id)
    if record.get("wave_d") is None:
        raise ControlPlaneError(
            ErrorCode.EVIDENCE_INVALID,
            f"plan {plan_id} binds Wave-E timing without a Wave-D chain: "
            "timing cannot stand without its communication parents",
            operation="verify_resource", resource_id=plan_id)
    overlay = load_verified_wave_e_workload(
        store, wave_e["temporal_workload_id"])
    _require_equal("plan.wave_e.performance_model_id",
                   wave_e["performance_model_id"],
                   overlay.performance_model.performance_model_id(),
                   plan_id)
    # Parent verification is GENERATION-AWARE: a v1 plan authenticates its
    # Wave-D opgraph, a v2 plan authenticates the canonical WorkloadGraph.
    # The scientific gate below is identical either way — only which
    # authority supplies the operation ids changes. A hard-coded
    # operation_graph_id here would have broken the first v2 plan.
    from .waved_resources import (
        CHAIN_SCHEMA_VERSION_V2,
        load_verified_operation_graph, load_verified_workload_graph,
        validate_plan_chain_shape,
    )
    # The SHAPE is validated before anything generation-specific is read.
    # A block carrying chain_schema_version=2, a workload_graph_id AND an
    # illegal operation_graph_id is not "a v2 block we can work with": it
    # is malformed, and it must be refused here rather than after a parent
    # load has already been attempted. This is why the version comes from
    # validate_plan_chain_shape() and not from chain_version() alone.
    wave_d_block = record["wave_d"]
    version = validate_plan_chain_shape(wave_d_block)
    if version == CHAIN_SCHEMA_VERSION_V2:
        canonical = load_verified_workload_graph(
            store, wave_d_block["workload_graph_id"])
        graph_ids = {op.operation_id for op in canonical.operations}
    else:
        graph = load_verified_operation_graph(
            store, wave_d_block["operation_graph_id"])
        graph_ids = {n.operation_id for n in graph.nodes}
    unknown = sorted(set(overlay.declared_wave_d_operation_ids())
                     - graph_ids)
    if unknown:
        raise ControlPlaneError(
            ErrorCode.EVIDENCE_INVALID,
            f"plan {plan_id} temporal overlay schedules Wave-D operations "
            f"{unknown} that are not in the plan's operation graph",
            operation="verify_resource", resource_id=plan_id)


def load_verified_experiment(store: Any,
                             experiment_id: str) -> dict[str, Any]:
    record = _get(store, "experiment", experiment_id)
    check_envelope(record, "experiment")
    _require_id("experiment", experiment_id, record)
    recomputed = _content_id("srota-experiment/v1", {
        "plan_id": record.get("plan_id"),
        "backend_config_hash": record.get("backend_config_hash"),
        "backend_input_hash": record.get("backend_input_hash"),
        "execution_mode": record.get("execution_mode"),
    })
    if recomputed != experiment_id:
        raise ControlPlaneError(
            ErrorCode.EVIDENCE_INVALID,
            f"experiment {experiment_id} recomputes to {recomputed}: "
            f"forged",
            operation="verify_resource", resource_id=experiment_id)
    plan = load_verified_plan(store, record.get("plan_id"))
    _require_equal("experiment.execution_mode",
                   record.get("execution_mode"),
                   plan.get("execution_mode"), experiment_id)
    return record


def load_verified_attempt(store: Any, attempt_id: str) -> dict[str, Any]:
    """UUID attempt: filename==embedded plus linkage and provenance.

    Successful attempts additionally bind producer provenance to the
    authenticated Wave-B evidence (binary/revision/dirt/tool). Failed,
    timed-out and interrupted attempts verify structurally only — their
    integrity is STRUCTURALLY_VALID with evidence NOT_AVAILABLE, never
    cryptographically authenticated success.
    """
    from veritx_dse.backend.evidence import EvidenceRef, \
        read_verified_evidence, validate_evidence_document
    record = _get(store, "attempt", attempt_id)
    check_envelope(record, "attempt")
    _require_id("attempt", attempt_id, record)
    experiment = load_verified_experiment(store,
                                          record.get("experiment_id"))
    status = record.get("status")
    from .service import ATTEMPT_STATUSES
    if status not in ATTEMPT_STATUSES:
        raise ControlPlaneError(
            ErrorCode.EVIDENCE_INVALID,
            f"attempt {attempt_id} has invalid status {status!r}",
            operation="verify_resource", resource_id=attempt_id)
    if status != "SUCCEEDED":
        _verify_attempt_structure(attempt_id, record)
        return record
    # A successful attempt may not simultaneously carry a failure
    # claim: status, evidence and error must tell one story.
    if record.get("error") is not None:
        raise ControlPlaneError(
            ErrorCode.EVIDENCE_INVALID,
            f"attempt {attempt_id} is SUCCEEDED but carries an "
            f"error payload",
            operation="verify_resource", resource_id=attempt_id)
    ref_doc = record.get("evidence_ref") or {}
    try:
        ref = EvidenceRef(path=ref_doc["path"],
                          sha256=ref_doc["sha256"])
        evidence = validate_evidence_document(
            read_verified_evidence(ref))
    except Exception as exc:
        raise ControlPlaneError(
            ErrorCode.EVIDENCE_INVALID,
            f"attempt {attempt_id} evidence fails verification: {exc}",
            operation="verify_resource", resource_id=attempt_id,
            cause_type=type(exc).__name__) from exc
    if not isinstance(evidence, dict):
        raise ControlPlaneError(
            ErrorCode.EVIDENCE_INVALID,
            f"attempt {attempt_id} evidence is not a mapping",
            operation="verify_resource", resource_id=attempt_id)
    for key in ("backend_config_hash", "backend_input_hash"):
        _require_equal(f"attempt.evidence.{key}", evidence.get(key),
                       experiment.get(key), attempt_id)
    producer = record.get("producer") or {}
    attempt_doc = None
    for key, evidence_key in (
            ("binary_sha256", "booksim_binary_sha256"),
            ("source_revision", "producer_source_revision"),
            ("source_dirty", "producer_source_dirty"),
            ("source_dirty_digest", "producer_source_dirty_digest"),
            ("tool_identity", "producer_tool_identity")):
        if evidence_key in evidence:
            # v1 evidence embedded tool identity; v2 does not.
            _require_equal(f"attempt.producer.{key}",
                           producer.get(key),
                           evidence.get(evidence_key), attempt_id)
            continue
        if attempt_doc is None:
            attempt_doc = _read_attempt_record(
                record.get("backend_dir"), attempt_id)
        _require_equal(f"attempt.producer.{key}", producer.get(key),
                       attempt_doc.get(evidence_key), attempt_id)
    return record


def load_verified_result(store: Any, result_id: str, *,
                         expected_experiment_id: str | None = None
                         ) -> dict[str, Any]:
    """Full result validation against verified links + Wave-B evidence.

    Replaces every raw linked ``store.get()`` with verified loaders,
    requires filename == embedded == recomputed result ID, and
    re-derives all scientific fields. Only then is the record trusted.
    """
    from veritx_dse.backend.evidence import (
        EvidenceRef, read_verified_evidence, validate_evidence_document,
    )
    result = store.get("result", result_id)
    check_envelope(result, "result")
    _require_id("result", result_id, result)
    experiment = load_verified_experiment(
        store, result.get("experiment_id"))
    if expected_experiment_id is not None and \
            experiment.get("resource_id") != expected_experiment_id:
        raise ControlPlaneError(
            ErrorCode.EVIDENCE_INVALID,
            f"result {result_id} belongs to experiment "
            f"{experiment.get('resource_id')}, not the requested "
            f"{expected_experiment_id}: refusing transplanted reuse",
            operation="verify_result", resource_id=result_id)
    plan = load_verified_plan(store, experiment.get("plan_id"))
    attempt = load_verified_attempt(store, result.get("attempt_id"))
    _require_equal("attempt.experiment_id",
                   attempt.get("experiment_id"),
                   experiment.get("resource_id"), result_id)
    _require_equal("attempt.status", attempt.get("status"), "SUCCEEDED",
                   result_id)
    _require_equal("attempt.evidence_ref", attempt.get("evidence_ref"),
                   result.get("evidence_ref"), result_id)
    design = load_verified_design(store, plan.get("design_id"))
    workload = load_verified_workload(store, plan.get("workload_id"))
    for key in ("experiment_id", "attempt_id", "plan_id", "design_id",
                "workload_id"):
        _require_equal(key, result.get(key),
                       {"experiment_id": experiment.get("resource_id"),
                        "attempt_id": attempt.get("resource_id"),
                        "plan_id": plan.get("resource_id"),
                        "design_id": design.get("resource_id"),
                        "workload_id": workload.get("resource_id")}[key],
                       result_id)
    for key in ("design_hash", "mapping_hash", "fabric_hash"):
        _require_equal(key, result.get(key), plan.get(key), result_id)
        _require_equal(f"design.{key}", design.get(key), plan.get(key),
                       result_id)
    _require_equal("workload_hash", result.get("workload_hash"),
                   plan.get("workload_hash"), result_id)
    _require_equal("workload.trace_sha256", workload.get("trace_sha256"),
                   plan.get("workload_hash"), result_id)
    for key in ("backend_target", "backend_profile",
                "backend_semantics_version", "execution_mode"):
        _require_equal(key, result.get(key), plan.get(key), result_id)
    for key in ("backend_config_hash", "backend_input_hash"):
        _require_equal(f"result.{key}", result.get(key),
                       experiment.get(key), result_id)
    ref_doc = result.get("evidence_ref") or {}
    try:
        ref = EvidenceRef(path=ref_doc["path"], sha256=ref_doc["sha256"])
    except (KeyError, TypeError, ValueError) as exc:
        raise ControlPlaneError(
            ErrorCode.EVIDENCE_INVALID,
            f"result {result_id} carries a malformed EvidenceRef: {exc}",
            operation="verify_result", resource_id=result_id) from exc
    try:
        evidence = validate_evidence_document(
            read_verified_evidence(ref))
    except Exception as exc:
        raise ControlPlaneError(
            ErrorCode.EVIDENCE_INVALID,
            f"result {result_id} evidence fails verification: {exc}",
            operation="verify_result", resource_id=result_id,
            cause_type=type(exc).__name__) from exc
    if not isinstance(evidence, dict):
        raise ControlPlaneError(
            ErrorCode.EVIDENCE_INVALID,
            f"result {result_id} evidence is not a mapping",
            operation="verify_result", resource_id=result_id)
    for key in ("backend_config_hash", "backend_input_hash"):
        _require_equal(f"evidence.{key}", evidence.get(key),
                       experiment.get(key), result_id)
    recomputed_result = _content_id("srota-result/v1", {
        "experiment_id": experiment.get("resource_id"),
        "attempt_id": attempt.get("resource_id"),
        "evidence_sha256": ref.sha256,
    })
    if recomputed_result != result_id:
        raise ControlPlaneError(
            ErrorCode.EVIDENCE_INVALID,
            f"result {result_id} recomputes to {recomputed_result}: "
            f"forged",
            operation="verify_result", resource_id=result_id)
    _require_equal("status", result.get("status"), "SUCCEEDED", result_id)
    for key in ("qualification", "execution_transport", "seed",
                "seed_policy"):
        _require_equal(key, result.get(key), evidence.get(key), result_id)
    _require_equal("semantic_loss",
                   sorted((dict(r) for r in result.get(
                       "semantic_loss", [])),
                          key=lambda r: r.get("dimension", "")),
                   sorted((dict(r) for r in evidence.get(
                       "semantic_loss", [])),
                          key=lambda r: r.get("dimension", "")),
                   result_id)
    _require_equal("loss_digest", result.get("loss_digest"),
                   loss_digest_of(evidence.get("semantic_loss", [])),
                   result_id)
    _verify_metrics(result, evidence, plan, result_id)
    producer = result.get("producer") or {}
    attempt_doc = None
    for key, evidence_key in (
            ("binary_sha256", "booksim_binary_sha256"),
            ("source_revision", "producer_source_revision"),
            ("source_dirty", "producer_source_dirty"),
            ("source_dirty_digest", "producer_source_dirty_digest"),
            ("tool_identity", "producer_tool_identity")):
        if evidence_key in evidence:
            _require_equal(f"producer.{key}", producer.get(key),
                           evidence.get(evidence_key), result_id)
            continue
        if attempt_doc is None:
            attempt_doc = _read_attempt_record(
                attempt.get("backend_dir"), result_id)
        _require_equal(f"producer.{key}", producer.get(key),
                       attempt_doc.get(evidence_key), result_id)
    if plan.get("wave_d") is not None or result.get("wave_d") is not None:
        _verify_waved_result(store, result, plan, evidence, result_id)
    if plan.get("wave_e") is not None or result.get("wave_e") is not None:
        from .wave_e_resources import verify_wave_e_result_block
        verify_wave_e_result_block(
            store,
            result.get("wave_e") or {},
            plan.get("wave_e"),
            plan.get("wave_d"),
            result.get("wave_d"),
            evidence,
            (result.get("evidence_ref") or {}).get("sha256"),
            result.get("backend_config_hash"),
            result.get("backend_input_hash"),
            result_id)
    return result


def _verify_waved_result(store: Any, result: dict[str, Any],
                         plan: dict[str, Any], evidence: dict[str, Any],
                         result_id: str) -> None:
    """A Wave-D result is only VERIFIED if it IS the plan's experiment.

    The verified plan is the authority for the scientific chain. Proving
    that the result's chain is internally valid is a DIFFERENT question
    from proving that it is THIS experiment's chain: two individually
    valid chains can describe byte-identical BookSim traffic (phase is
    not representable in a five-column trace), so a transplant would
    otherwise pass every local check. The verifier therefore:

      1. closes the result block's schema (no unknown fields),
      2. requires the result's chain to equal the plan's chain exactly,
      3. re-derives the chain from the PLAN's traffic parent,
      4. re-derives the execution counters from that traffic and from
         the authenticated evidence.
    """
    from veritx_dse.backend.projection import verify_trace_projection

    from .waved_resources import (
        chain_ids_from_traffic, plan_chain_keys, result_wave_d_keys,
        validate_plan_chain_shape, load_verified_traffic,
    )
    plan_wave_d = plan.get("wave_d")
    wave_d = result.get("wave_d")
    if plan_wave_d is None or wave_d is None:
        raise ControlPlaneError(
            ErrorCode.EVIDENCE_INVALID,
            f"result {result_id} and its plan disagree on workload kind: "
            "a Wave-D experiment cannot be verified against a legacy "
            "plan (or the reverse)",
            operation="verify_result", resource_id=result_id)
    # 1. Schema closure: a VERIFIED block carries exactly the declared
    #    chain + execution fields, nothing else.
    # 1b. Chain GENERATION: the plan's generation is the contract, and the
    #     result must be the same one. A v1 result never verifies against a
    #     v2 plan, or the reverse: they are different contracts.
    plan_version = validate_plan_chain_shape(plan_wave_d)
    expected_result_keys = result_wave_d_keys(plan_version)
    if set(wave_d) != set(expected_result_keys):
        raise ControlPlaneError(
            ErrorCode.EVIDENCE_INVALID,
            f"result {result_id} wave_d block has the wrong field set for "
            f"chain v{plan_version}: unknown "
            f"{sorted(set(wave_d) - set(expected_result_keys))}, missing "
            f"{sorted(set(expected_result_keys) - set(wave_d))}",
            operation="verify_result", resource_id=result_id)
    # 2. Provenance binding: the result must claim the PLAN's chain.
    for key in plan_chain_keys(plan_version):
        _require_equal(f"result.wave_d.{key}", wave_d.get(key),
                       plan_wave_d.get(key), result_id)
    # 3. Re-derive from the plan's traffic parent (the authority), then
    #    confirm the plan's own chain is what that traffic produces.
    traffic, _ = load_verified_traffic(
        store, plan_wave_d.get("physical_traffic_id"))
    # the generation-dispatched re-derivation: v1 rebuilds the Wave-D
    # ancestry from its historical resources, v2 reads the WorkloadGraph
    # parent directly (no reconstruction, no legacy IDs)
    validate_plan_chain_shape(recomputed := chain_ids_from_traffic(traffic))
    recomputed_chain = recomputed
    for key in plan_chain_keys(plan_version):
        _require_equal(f"plan.wave_d.{key}", plan_wave_d.get(key),
                       recomputed_chain[key], result_id)
    summary = verify_trace_projection(traffic)
    _require_equal("wave_d.expected_packets",
                   wave_d.get("expected_packets"),
                   summary["num_packets"], result_id)
    _require_equal("wave_d.expected_flits", wave_d.get("expected_flits"),
                   summary["flits_total"], result_id)
    stats = evidence.get("stats") or {}
    for key, stats_key in (("delivered_packets", "delivered"),
                           ("flits_injected", "flits_injected"),
                           ("flits_accepted", "flits_accepted")):
        _require_equal(f"wave_d.{key}", wave_d.get(key),
                       stats.get(stats_key), result_id)


def _verify_metrics(result: dict[str, Any], evidence: dict[str, Any],
                    plan: dict[str, Any], resource_id: str) -> None:
    from .presets import METRIC_SCHEMA_VERSION, STATS_TO_METRIC, \
        get_metric_definition
    _require_equal("metric_schema_version",
                   result.get("metric_schema_version"),
                   METRIC_SCHEMA_VERSION, resource_id)
    rows = result.get("metrics")
    if not isinstance(rows, list):
        raise ControlPlaneError(
            ErrorCode.EVIDENCE_INVALID,
            "result metrics must be a list", operation="verify_result",
            resource_id=resource_id)
    stats = evidence.get("stats") or {}
    seen: set[str] = set()
    for row in rows:
        if not isinstance(row, dict):
            raise ControlPlaneError(
                ErrorCode.EVIDENCE_INVALID,
                f"metric row must be an object, got {row!r}",
                operation="verify_result", resource_id=resource_id)
        metric_id = row.get("metric_id")
        try:
            definition = get_metric_definition(metric_id)
        except KeyError as exc:
            raise ControlPlaneError(
                ErrorCode.EVIDENCE_INVALID,
                f"unknown metric {metric_id!r} in persisted result",
                operation="verify_result",
                resource_id=resource_id) from exc
        stats_key = next(
            (k for k, v in STATS_TO_METRIC.items() if v == metric_id), None)
        if stats_key is None or stats_key not in stats:
            raise ControlPlaneError(
                ErrorCode.EVIDENCE_INVALID,
                f"metric {metric_id!r} is not derivable from evidence "
                f"stats",
                operation="verify_result", resource_id=resource_id)
        expected = stats[stats_key]
        if not isinstance(expected, (int, float)) or \
                float(row.get("value")) != float(expected):
            raise ControlPlaneError(
                ErrorCode.EVIDENCE_INVALID,
                f"metric {metric_id!r} value {row.get('value')!r} does "
                f"not match evidence {expected!r}",
                operation="verify_result", resource_id=resource_id)
        _require_equal(f"metric {metric_id} unit", row.get("unit"),
                       definition.unit, resource_id)
        _require_equal(f"metric {metric_id} definition version",
                       row.get("definition_version"),
                       METRIC_SCHEMA_VERSION, resource_id)
        seen.add(metric_id)
    planned = set(plan.get("metric_ids", []))
    if seen != planned:
        raise ControlPlaneError(
            ErrorCode.EVIDENCE_INVALID,
            f"result metrics {sorted(seen)} do not cover the planned "
            f"metrics {sorted(planned)}",
            operation="verify_result", resource_id=resource_id)


def load_verified_comparison(store: Any,
                             comparison_id: str) -> dict[str, Any]:
    """Comparison ID + re-gated candidates + recomputed output."""
    from .comparison import check_compatibility, compare_metrics, \
        parse_contract
    record = store.get("comparison", comparison_id)
    check_envelope(record, "comparison")
    _require_id("comparison", comparison_id, record)
    contract = parse_contract(record.get("contract"))
    candidates = record.get("candidate_ids")
    if not isinstance(candidates, list) or len(candidates) != 2:
        raise ControlPlaneError(
            ErrorCode.EVIDENCE_INVALID,
            "comparison must reference exactly two candidates",
            operation="verify_resource", resource_id=comparison_id)
    recomputed = _content_id("srota-comparison/v1", {
        "candidate_ids": list(candidates),
        "contract": contract.identity_dict(),
        "metric_ids": list(contract.metric_ids),
    })
    if recomputed != comparison_id:
        raise ControlPlaneError(
            ErrorCode.EVIDENCE_INVALID,
            f"comparison {comparison_id} recomputes to {recomputed}: "
            f"forged",
            operation="verify_resource", resource_id=comparison_id)
    results = [load_verified_result(store, candidate)
               for candidate in candidates]
    compatibility = check_compatibility(results[0], results[1], contract)
    metrics = compare_metrics(results[0], results[1],
                              contract.metric_ids)
    _require_equal("compatibility", record.get("compatibility"),
                   compatibility, comparison_id)
    _require_equal("metrics", record.get("metrics"), metrics,
                   comparison_id)
    _require_equal("contract", record.get("contract"),
                   contract.identity_dict(), comparison_id)
    _require_equal("candidate_ids", record.get("candidate_ids"),
                   candidates, comparison_id)
    fidelity = {
        "a_qualification": results[0]["qualification"],
        "b_qualification": results[1]["qualification"],
        "a_loss_digest": results[0]["loss_digest"],
        "b_loss_digest": results[1]["loss_digest"],
        "acknowledged_differences": list(
            contract.acknowledged_differences),
    }
    _require_equal("fidelity_context", record.get("fidelity_context"),
                   fidelity, comparison_id)
    return record


def _verify_attempt_structure(attempt_id: str,
                              record: dict[str, Any]) -> None:
    """Status/error coherence for non-success attempts.

    These records are NOT authenticated scientific evidence — no
    successful EvidenceRef exists to bind. Structural validity still
    requires internal coherence: the terminal state and its error
    classification must agree, and no unsuccessful attempt may carry
    success evidence.
    """
    status = record.get("status")
    if record.get("evidence_ref") is not None:
        raise ControlPlaneError(
            ErrorCode.EVIDENCE_INVALID,
            f"attempt {attempt_id} is {status} but carries an "
            f"evidence_ref",
            operation="verify_resource", resource_id=attempt_id)
    if status in ("PLANNED", "RUNNING"):
        # Live/abandoned states carry no terminal claim at all.
        if record.get("error") is not None:
            raise ControlPlaneError(
                ErrorCode.EVIDENCE_INVALID,
                f"attempt {attempt_id} is {status} but carries a "
                f"terminal error payload",
                operation="verify_resource", resource_id=attempt_id)
        return
    error = record.get("error")
    if not isinstance(error, dict) or not error.get("message"):
        raise ControlPlaneError(
            ErrorCode.EVIDENCE_INVALID,
            f"attempt {attempt_id} ({status}) lacks a well-formed "
            f"error payload",
            operation="verify_resource", resource_id=attempt_id)
    code = error.get("code")
    if status == "TIMED_OUT":
        if code != "EXECUTION_TIMEOUT":
            raise ControlPlaneError(
                ErrorCode.EVIDENCE_INVALID,
                f"attempt {attempt_id} is TIMED_OUT with error "
                f"{code!r}",
                operation="verify_resource", resource_id=attempt_id)
        return
    if status == "FAILED":
        if code != "EXECUTION_FAILED":
            raise ControlPlaneError(
                ErrorCode.EVIDENCE_INVALID,
                f"attempt {attempt_id} is FAILED with non-failure "
                f"error {code!r}",
                operation="verify_resource", resource_id=attempt_id)
        return
    if status == "INTERRUPTED":
        # The interruption marker is its own literal (there is no
        # ErrorCode member for a synchronous cancellation).
        if code != "INTERRUPTED":
            raise ControlPlaneError(
                ErrorCode.EVIDENCE_INVALID,
                f"attempt {attempt_id} is INTERRUPTED with error "
                f"{code!r} (expected the interruption marker)",
                operation="verify_resource", resource_id=attempt_id)
        return
    # Unreachable under the ATTEMPT_STATUSES membership check above,
    # but explicit by design: no status may silently fall through
    # into another state's rule.
    raise ControlPlaneError(
        ErrorCode.EVIDENCE_INVALID,
        f"attempt {attempt_id} has no verification rule for status "
        f"{status!r}",
        operation="verify_resource", resource_id=attempt_id)


def load_verified_study(store: Any, study_id: str) -> dict[str, Any]:
    """StudyDefinition identity (definition kind, deterministic ID)."""
    record = _get(store, "studydef", study_id)
    check_envelope(record, "studydef")
    _require_id("studydef", study_id, record)
    recomputed = _content_id("srota-study/v1", {
        "name": record.get("name"),
        "candidate_intents": list(record.get("candidate_intents", [])),
        "comparison": record.get("comparison_request"),
    })
    if recomputed != study_id:
        raise ControlPlaneError(
            ErrorCode.EVIDENCE_INVALID,
            f"study definition {study_id} recomputes to {recomputed}: "
            f"forged",
            operation="verify_resource", resource_id=study_id)
    intents = record.get("candidate_intents", [])
    if not isinstance(intents, list) or not intents:
        raise ControlPlaneError(
            ErrorCode.EVIDENCE_INVALID,
            f"study definition {study_id} has no candidate identities",
            operation="verify_resource", resource_id=study_id)
    return record


def load_verified_studyrun(store: Any, study_run_id: str) -> dict[str, Any]:
    """StudyRun: definition link + per-entry verification."""
    record = _get(store, "studyrun", study_run_id)
    check_envelope(record, "study")
    _require_id("studyrun", study_run_id, record)
    definition = load_verified_study(store, record.get("study_id"))
    identities = definition.get("candidate_intents", [])
    experiments = record.get("experiments", [])
    if not isinstance(experiments, list) or \
            len(experiments) != len(identities):
        raise ControlPlaneError(
            ErrorCode.EVIDENCE_INVALID,
            f"study run {study_run_id} entries do not match its "
            f"definition ({len(experiments) if isinstance(experiments, list) else '?'} vs "
            f"{len(identities)} candidates)",
            operation="verify_resource", resource_id=study_run_id)
    _require_equal("studyrun.candidate_intents",
                   record.get("candidate_intents"), identities,
                   study_run_id)
    _require_equal("studyrun.name", record.get("name"),
                   definition.get("name"), study_run_id)
    _require_equal("studyrun.comparison_request",
                   record.get("comparison_request"),
                   definition.get("comparison_request"), study_run_id)
    for position, entry in enumerate(experiments):
        _verify_study_entry(store, study_run_id, position, entry,
                            identities)
    _verify_comparison_completeness(study_run_id, definition,
                                    record.get("comparisons"))
    for row in record.get("comparisons", []):
        _verify_study_comparison_row(store, study_run_id, row,
                                     definition, experiments)
    return record


def _verify_comparison_completeness(study_run_id: str,
                                    definition: dict[str, Any],
                                    rows: Any) -> None:
    """Exactly one outcome row per requested comparison pair.

    Validating only the rows that exist would let a requested
    comparison be deleted (or duplicated) while the run still
    verifies; the requested pair multiset is the contract.
    """
    requested = (definition.get("comparison_request") or {})
    pairs = requested.get("pairs", [])
    if not isinstance(rows, list):
        raise ControlPlaneError(
            ErrorCode.EVIDENCE_INVALID,
            f"study run {study_run_id} comparisons must be a list",
            operation="verify_resource", resource_id=study_run_id)
    if len(rows) != len(pairs):
        raise ControlPlaneError(
            ErrorCode.EVIDENCE_INVALID,
            f"study run {study_run_id} has {len(rows)} comparison "
            f"rows for {len(pairs)} requested pairs",
            operation="verify_resource", resource_id=study_run_id)
    observed = []
    for row in rows:
        pair = row.get("pair") if isinstance(row, dict) else None
        if not isinstance(pair, list) or len(pair) != 2 or any(
                not isinstance(i, int) or isinstance(i, bool)
                for i in pair):
            raise ControlPlaneError(
                ErrorCode.EVIDENCE_INVALID,
                f"study run {study_run_id} has a malformed comparison "
                f"pair {pair!r}",
                operation="verify_resource", resource_id=study_run_id)
        observed.append((pair[0], pair[1]))
    expected = [(p[0], p[1]) for p in pairs]
    if sorted(observed) != sorted(expected):
        raise ControlPlaneError(
            ErrorCode.EVIDENCE_INVALID,
            f"study run {study_run_id} comparison pairs {observed} do "
            f"not match the requested pairs {expected}",
            operation="verify_resource", resource_id=study_run_id)


def _verify_study_entry(store: Any, study_run_id: str, position: int,
                        entry: Any, identities: list) -> None:
    if not isinstance(entry, dict):
        raise ControlPlaneError(
            ErrorCode.EVIDENCE_INVALID,
            f"study run {study_run_id} entry {position} is not an object",
            operation="verify_resource", resource_id=study_run_id)
    _require_equal(f"entry[{position}].index", entry.get("index"),
                   position, study_run_id)
    _require_equal(f"entry[{position}].candidate_identity",
                   entry.get("candidate_identity"),
                   identities[position], study_run_id)
    status = entry.get("status")
    if status == "SUCCEEDED":
        result = load_verified_result(store, entry.get("result_id"))
        plan = load_verified_plan(store, result.get("plan_id"))
        _require_equal(f"entry[{position}].experiment_id",
                       entry.get("experiment_id"),
                       result.get("experiment_id"), study_run_id)
        _require_equal(f"entry[{position}].intent_id",
                       entry.get("intent_id"),
                       plan.get("intent_id"), study_run_id)
        _require_equal(f"entry[{position}].backend_target",
                       entry.get("backend_target"),
                       plan.get("backend_target"), study_run_id)
        if entry.get("error") is not None:
            raise ControlPlaneError(
                ErrorCode.EVIDENCE_INVALID,
                f"study run {study_run_id} entry {position} succeeded "
                f"but carries an error payload",
                operation="verify_resource", resource_id=study_run_id)
        return
    if status not in STUDY_CANDIDATE_STATUSES:
        raise ControlPlaneError(
            ErrorCode.EVIDENCE_INVALID,
            f"study run {study_run_id} entry {position} has invalid "
            f"status {status!r}",
            operation="verify_resource", resource_id=study_run_id)
    if entry.get("result_id") is not None:
        raise ControlPlaneError(
            ErrorCode.EVIDENCE_INVALID,
            f"study run {study_run_id} entry {position} is "
            f"{status} but carries a result_id",
            operation="verify_resource", resource_id=study_run_id)
    _verify_study_error(store, study_run_id, position, entry,
                        identities)


def _verify_study_error(store: Any, study_run_id: str, position: int,
                        entry: dict[str, Any],
                        identities: list) -> None:
    """Non-success entries: intent binding + typed error coherence.

    The status must equal the ONE authoritative mapping
    (``study_status_for_code``) for the recorded error code and the
    recorded backend target, so timeout/unsupported/blocked/failure
    cannot be relabelled.
    """
    from .errors import ErrorCode as _Codes
    from .studies import study_status_for_code
    status = entry.get("status")
    error = entry.get("error")
    if not isinstance(error, dict) or not error.get("code") or \
            not error.get("message"):
        raise ControlPlaneError(
            ErrorCode.EVIDENCE_INVALID,
            f"study run {study_run_id} entry {position} ({status}) "
            f"lacks a well-formed error payload",
            operation="verify_resource", resource_id=study_run_id)
    try:
        code = _Codes(error["code"])
    except ValueError:
        raise ControlPlaneError(
            ErrorCode.EVIDENCE_INVALID,
            f"study run {study_run_id} entry {position} has unknown "
            f"error code {error['code']!r}",
            operation="verify_resource",
            resource_id=study_run_id) from None
    if status == "INVALID":
        # Resolution failed: no intent exists; the identity marker is
        # the deterministic hash of the rejected candidate document.
        if entry.get("intent_id") is not None:
            raise ControlPlaneError(
                ErrorCode.EVIDENCE_INVALID,
                f"study run {study_run_id} entry {position} is "
                f"INVALID but carries an intent_id",
                operation="verify_resource", resource_id=study_run_id)
        if entry.get("backend_target") is not None:
            raise ControlPlaneError(
                ErrorCode.EVIDENCE_INVALID,
                f"study run {study_run_id} entry {position} is "
                f"INVALID but carries a backend_target",
                operation="verify_resource", resource_id=study_run_id)
        if not identities[position].startswith("invalid:"):
            raise ControlPlaneError(
                ErrorCode.EVIDENCE_INVALID,
                f"study run {study_run_id} entry {position} is "
                f"INVALID but its candidate resolved",
                operation="verify_resource", resource_id=study_run_id)
        if code not in (_Codes.INVALID_INTENT, _Codes.NOT_FOUND):
            raise ControlPlaneError(
                ErrorCode.EVIDENCE_INVALID,
                f"study run {study_run_id} entry {position} INVALID "
                f"with non-resolution error {code.value}",
                operation="verify_resource", resource_id=study_run_id)
        return
    # Resolution succeeded (otherwise the entry would be INVALID), so
    # the intent is the definition's ordered identity.
    _require_equal(f"entry[{position}].intent_id",
                   entry.get("intent_id"), identities[position],
                   study_run_id)
    experiment_id = entry.get("experiment_id")
    if experiment_id is not None:
        load_verified_experiment(store, experiment_id)
    expected = study_status_for_code(
        code, backend_target=entry.get("backend_target"))
    if status != expected:
        raise ControlPlaneError(
            ErrorCode.EVIDENCE_INVALID,
            f"study run {study_run_id} entry {position} claims "
            f"{status} for error {code.value} (expected {expected})",
            operation="verify_resource", resource_id=study_run_id)


def _verify_study_comparison_row(store: Any, study_run_id: str, row: Any,
                                 definition: dict[str, Any],
                                 experiments: list) -> None:
    from .comparison import parse_contract
    if not isinstance(row, dict):
        raise ControlPlaneError(
            ErrorCode.EVIDENCE_INVALID,
            f"study run {study_run_id} has a malformed comparison row",
            operation="verify_resource", resource_id=study_run_id)
    requested = (definition.get("comparison_request") or {})
    requested_pairs = requested.get("pairs", [])
    pair = row.get("pair")
    if pair not in requested_pairs:
        raise ControlPlaneError(
            ErrorCode.EVIDENCE_INVALID,
            f"study run {study_run_id} comparison pair {pair!r} was "
            f"not requested",
            operation="verify_resource", resource_id=study_run_id)
    status = row.get("status")
    by_index = {e.get("index"): e for e in experiments
                if isinstance(e, dict)}
    if status == "COMPARED":
        comparison = load_verified_comparison(
            store, row.get("comparison_id"))
        expected = [by_index[i].get("result_id") for i in pair]
        _require_equal("comparison.candidate_ids",
                       comparison.get("candidate_ids"), expected,
                       study_run_id)
        contract = parse_contract(requested.get("contract", {}))
        _require_equal("comparison.contract",
                       comparison.get("contract"),
                       contract.identity_dict(), study_run_id)
    elif status == "SKIPPED":
        _require_equal("skipped reason", row.get("reason"),
                       "a side has no successful result", study_run_id)
        sides = [by_index.get(i, {}).get("result_id") for i in pair] \
            if all(isinstance(i, int) for i in (pair or [])) else []
        if all(s is not None for s in sides) and sides:
            raise ControlPlaneError(
                ErrorCode.EVIDENCE_INVALID,
                f"study run {study_run_id} pair {pair!r} skipped "
                f"despite two successful results",
                operation="verify_resource", resource_id=study_run_id)
    elif status == "REFUSED":
        from .comparison import check_compatibility, compare_metrics
        sides = [by_index.get(i, {}).get("result_id") for i in pair] \
            if all(isinstance(i, int) for i in (pair or [])) else []
        if len(sides) != 2 or any(s is None for s in sides):
            raise ControlPlaneError(
                ErrorCode.EVIDENCE_INVALID,
                f"study run {study_run_id} pair {pair!r} refused "
                f"without two successful results",
                operation="verify_resource", resource_id=study_run_id)
        # Re-derive the refusal through the read-only gate (no writes,
        # no execution): the recorded error code must reproduce exactly.
        # Mirrors SrotaControlPlane.compare minus the store put: the
        # evidence policy runs before compatibility, and either source
        # of refusal is legitimate.
        results = [load_verified_result(store, s) for s in sides]
        contract = parse_contract(requested.get("contract", {}))
        refusal: ErrorCode | None = None
        for result in results:
            if result.get("execution_transport") != \
                    "SUPERVISED_PROCESS" or (result.get("producer")
                                             or {}).get("source_dirty") \
                    is not False:
                refusal = ErrorCode.COMPARISON_INCOMPATIBLE
                break
        if refusal is None:
            try:
                check_compatibility(results[0], results[1], contract)
                compare_metrics(results[0], results[1],
                                contract.metric_ids)
            except ControlPlaneError as exc:
                refusal = exc.code
            else:
                raise ControlPlaneError(
                    ErrorCode.EVIDENCE_INVALID,
                    f"study run {study_run_id} pair {pair!r} claims "
                    f"refusal but the gate now compares cleanly",
                    operation="verify_resource",
                    resource_id=study_run_id)
        recorded = (row.get("error") or {})
        _require_equal("refusal error code", recorded.get("code"),
                       refusal.value, study_run_id)
    else:
        raise ControlPlaneError(
            ErrorCode.EVIDENCE_INVALID,
            f"study run {study_run_id} comparison status {status!r} "
            f"invalid",
            operation="verify_resource", resource_id=study_run_id)


__all__ = [
    "load_verified_attempt",
    "load_verified_comparison",
    "load_verified_design",
    "load_verified_experiment",
    "load_verified_intent",
    "load_verified_plan",
    "load_verified_result",
    "load_verified_study",
    "load_verified_studyrun",
    "load_verified_workload",
    "loss_digest_of",
]
