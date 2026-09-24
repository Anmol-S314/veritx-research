"""veritx_dse.application.waved_resources — persisted Wave-D resources.

Wave-D semantic artifacts are scientific resources: they must survive
persistence and be loadable under the SAME contract Wave C uses for
intents/designs/results:

    requested filename ID == embedded resource_id == recomputed ID

plus verified parents, closed field sets and semantic revalidation.
Raw ``store.get()`` is inspection-only and never scientific trust.

The chain is stored as five content-addressed resources:

    wavedworkload   WaveDWorkload            (declared semantics)
    parallelism     ParallelismArtifact      (rank geometry)
    wavedsemantics  WaveDWorkloadSemantics   (versioned envelope)
    opgraph         OperationGraph           (causal DAG)
    messages        LogicalMessageArtifact   (scheduled messages)
    traffic         PhysicalTrafficArtifact  (packets + flits)

A ``traffic`` record also carries its ``design_id`` so the physical
bundle can be recompiled and re-verified on load; the bundle itself is
never persisted (it is an in-memory proof carrier — same rule as Wave B).
The ConservationLedger is NOT persisted: it is derived from a verified
``PhysicalTrafficArtifact`` and recomputed on demand.
"""
from __future__ import annotations

from typing import Any

from veritx_dse.workload.messages import (
    LogicalMessageArtifactV2,
)
from veritx_dse.workload.operations import OperationGraph
from veritx_dse.model.parallelism import ParallelismArtifact
from veritx_dse.workload.semantics import WaveDWorkloadSemantics
from veritx_dse.workload.traffic import (
    PhysicalTrafficArtifactV2,
)
# Historical v1 authorities (WaveDWorkload, LogicalMessageArtifact v1,
# PhysicalTrafficArtifact v1) were intentionally deleted per §4/§7: the
# canonical WorkloadGraph + V2 artifacts are the sole execution authority.
# v1 persisted resources are therefore explicitly unsupported — the v1
# readers below fail closed rather than resurrecting a second authority.
try:  # pragma: no cover - historical surface, expected absent
    from veritx_dse.workload.messages import (  # type: ignore
        LogicalMessageArtifact as _V1Messages,
    )
except ImportError:  # canonical product has V2 only
    _V1Messages = None  # type: ignore
try:  # pragma: no cover - historical surface, expected absent
    from veritx_dse.workload.traffic import (  # type: ignore
        PhysicalTrafficArtifact as _V1Traffic,
    )
except ImportError:  # canonical product has V2 only
    _V1Traffic = None  # type: ignore
try:  # pragma: no cover - historical surface, expected absent
    from veritx_dse.workload.graph import (  # type: ignore
        WaveDWorkload as _V1Workload,
    )
except ImportError:  # canonical product has WorkloadGraph only
    _V1Workload = None  # type: ignore

from .errors import ControlPlaneError, ErrorCode

# Wave-C resource envelope (local shim — the canonical resources.py now
# owns the 4-kind CompileIntent persistence and must not be overwritten
# with the old generic envelope; waved v1/v2 records carry their own).
RESOURCE_SCHEMA_VERSION = 1


def check_envelope(d: Any, expected_type: str) -> dict[str, Any]:
    """Validate a persisted waved resource envelope (type + version)."""
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

WAVED_RESOURCE_KINDS = ("wavedworkload", "parallelism", "wavedsemantics",
                        "opgraph", "messages", "traffic",
                        # canonical workload authority: the parent the v2
                        # message/chain generations authenticate
                        "workloadgraph")


# ── records (write side) ─────────────────────────────────────────────────
#
# M4: the v1 writers are DELETED (waved_semantics_record,
# waved_workload_record, operation_graph_record, messages_record,
# traffic_record had zero callers after the M1.6 cutover — new runs
# never emit wavedworkload/wavedsemantics/opgraph resources). The v1
# READERS below stay frozen for historical verification; the v2
# records are the only writers.

def _record(kind: str, resource_id: str,
            artifact: dict[str, Any]) -> dict[str, Any]:
    return {
        "resource_type": kind,
        "schema_version": RESOURCE_SCHEMA_VERSION,
        "resource_id": resource_id,
        "artifact": artifact,
    }


def _hash_of(obj: Any, name: str) -> str:
    """Read a child-artifact hash that may be a method (RT v1) or a
    stored attribute (canonical v2). Identity comes from the child;
    this shim only normalizes the accessor."""
    value = getattr(obj, name)
    return value() if callable(value) else value


def parallelism_record(art: ParallelismArtifact) -> dict[str, Any]:
    return _record("parallelism", art.parallelism_id(), art.to_dict())


def workload_graph_record(art: Any) -> dict[str, Any]:
    """The canonical WorkloadGraph resource.

    ``resource_id`` is the graph's content-derived ``workload_id()`` —
    there is no arbitrary second identifier.
    """
    return _record("workloadgraph", art.workload_id(), art.to_dict())


def messages_v2_record(art: LogicalMessageArtifactV2) -> dict[str, Any]:
    """Canonical messages record: the v2 artifact is self-contained."""
    return _record("messages", art.message_artifact_id(), art.to_dict())


def traffic_v2_record(art: PhysicalTrafficArtifactV2, *, design_id: str
                      ) -> dict[str, Any]:
    """Canonical traffic record.

    The v2 artifact's persisted shape is closed (no design keys inside
    it), so the navigational design link rides at the RECORD level,
    never inside the artifact the strict loader authenticates.
    """
    record = _record("traffic", art.physical_traffic_id(), art.to_dict())
    record["design_id"] = design_id
    record["design_hash"] = art.bundle.resolved_fabric.design_hash
    record["mapping_hash"] = art.bundle.resolved_fabric.mapping_hash
    return record


# ── load side (verified) ─────────────────────────────────────────────────

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
            operation="verify_resource", resource_id=resource_id) from exc


def _envelope(store: Any, kind: str, resource_id: str
              ) -> tuple[dict[str, Any], dict[str, Any]]:
    record = _get(store, kind, resource_id)
    try:
        check_envelope(record, kind)
    except ControlPlaneError as exc:
        raise ControlPlaneError(
            ErrorCode.EVIDENCE_INVALID,
            f"persisted {kind} {resource_id} envelope is invalid: "
            f"{exc.message}",
            operation="verify_resource", resource_id=resource_id) from exc
    embedded = record.get("resource_id")
    if embedded != resource_id:
        raise ControlPlaneError(
            ErrorCode.EVIDENCE_INVALID,
            f"{kind} file {resource_id} embeds resource_id {embedded!r}: "
            "refusing transplanted content",
            operation="verify_resource", resource_id=resource_id)
    artifact = record.get("artifact")
    if not isinstance(artifact, dict):
        raise ControlPlaneError(
            ErrorCode.EVIDENCE_INVALID,
            f"persisted {kind} {resource_id} carries no artifact object",
            operation="verify_resource", resource_id=resource_id)
    return record, artifact


def _parse(kind: str, resource_id: str, fn: Any) -> Any:
    try:
        return fn()
    except Exception as exc:
        raise ControlPlaneError(
            ErrorCode.EVIDENCE_INVALID,
            f"persisted {kind} {resource_id} fails verification: {exc}",
            operation="verify_resource", resource_id=resource_id,
            cause_type=type(exc).__name__) from exc


def _require_equal(what: str, actual: Any, expected: Any,
                   resource_id: str) -> None:
    if actual != expected:
        raise ControlPlaneError(
            ErrorCode.EVIDENCE_INVALID,
            f"{what} does not match its authority ({actual!r} != "
            f"{expected!r})",
            operation="verify_resource", resource_id=resource_id)


def load_verified_parallelism(store: Any,
                              parallelism_id: str) -> ParallelismArtifact:
    _, doc = _envelope(store, "parallelism", parallelism_id)
    art = _parse("parallelism", parallelism_id, lambda: (
        ParallelismArtifact.from_dict(doc, strict=True)))
    _require_equal("parallelism_id", art.parallelism_id(), parallelism_id,
                   parallelism_id)
    return art


def load_verified_waved_semantics(store: Any, semantics_id: str
                                  ) -> WaveDWorkloadSemantics:
    _, doc = _envelope(store, "wavedsemantics", semantics_id)
    art = _parse("wavedsemantics", semantics_id, lambda: (
        WaveDWorkloadSemantics.from_dict(doc, strict=True)))
    _require_equal("wave_d_semantics_id", art.semantics_id(), semantics_id,
                   semantics_id)
    return art


def load_verified_waved_workload(store: Any,
                                 workload_id: str) -> Any:
    """Verified Wave-D workload: HISTORICAL v1, explicitly unsupported.

    The v1 WaveDWorkload authority was deleted per §4/§7. Old persisted
    wavedworkload resources fail closed here; canonical runs use the
    workloadgraph path (load_verified_workload_graph).
    """
    raise ControlPlaneError(
        ErrorCode.EVIDENCE_INVALID,
        f"historical v1 wavedworkload {workload_id!r} is not supported "
        "in the canonical product (WorkloadGraph + V2 only)",
        operation="verify_resource", resource_id=workload_id)


def load_verified_operation_graph(store: Any,
                                  graph_id: str) -> OperationGraph:
    """Verified graph: HISTORICAL v1, explicitly unsupported.

    The v1 OperationGraph ancestry (WaveDWorkload parent) was superseded
    by the canonical WorkloadGraph. Old opgraph resources fail closed.
    """
    raise ControlPlaneError(
        ErrorCode.EVIDENCE_INVALID,
        f"historical v1 opgraph {graph_id!r} is not supported in the "
        "canonical product (WorkloadGraph + V2 only)",
        operation="verify_resource", resource_id=graph_id)


def load_verified_workload_graph(store: Any, workload_id: str) -> Any:
    """Verified canonical workload graph.

    Self-contained scientific semantics: it needs NO Wave-D parents. The
    strict parse recomputes the embedded workload_id, so a forged or
    transplanted document cannot pass.
    """
    from veritx_dse.workload.graph import WorkloadGraph
    _, doc = _envelope(store, "workloadgraph", workload_id)
    graph = _parse("workloadgraph", workload_id,
                   lambda: WorkloadGraph.from_dict(doc, strict=True))
    _require_equal("workload_id", graph.workload_id(), workload_id,
                   workload_id)
    return graph


def load_verified_messages(store: Any,
                           message_artifact_id: str
                           ) -> Any:
    """Generation-dispatched verified messages.

    v1 (``srota/WavedLogicalMessages``) authenticates the historical
    OperationGraph parent; v2 (``srota/LogicalMessageArtifactV2``)
    authenticates the canonical WorkloadGraph parent. The dispatch is
    on the persisted type tag — never inferred from which keys happen
    to be present.
    """
    _, doc = _envelope(store, "messages", message_artifact_id)
    if doc.get("type") == "srota/LogicalMessageArtifactV2":
        graph = load_verified_workload_graph(store,
                                             doc.get("workload_id"))
        art = _parse("messages", message_artifact_id, lambda: (
            LogicalMessageArtifactV2.from_dict(doc, graph=graph,
                                               strict=True)))
    else:
        raise ControlPlaneError(
            ErrorCode.EVIDENCE_INVALID,
            f"historical v1 messages {message_artifact_id!r} are not "
            "supported in the canonical product (V2 only)",
            operation="verify_resource",
            resource_id=message_artifact_id)
    _require_equal("message_artifact_id", art.message_artifact_id(),
                   message_artifact_id, message_artifact_id)
    art.validate_conservation()
    return art


def rebuild_verified_bundle(store: Any, design_id: str) -> Any:
    """Recompile the Wave-B bundle from a VERIFIED design resource."""
    from veritx_dse.model.compile_model import CompileRequest

    from veritx_dse.compiler.orchestration import build_resolved_bundle
    from .results import load_verified_design
    record = load_verified_design(store, design_id)
    try:
        request = CompileRequest.from_dict(record.get("compile_request"))
    except Exception as exc:
        raise ControlPlaneError(
            ErrorCode.EVIDENCE_INVALID,
            f"design {design_id} compile_request does not parse: {exc}",
            operation="verify_resource", resource_id=design_id) from exc
    try:
        return build_resolved_bundle(request)
    except ControlPlaneError as exc:
        raise ControlPlaneError(
            ErrorCode.EVIDENCE_INVALID,
            f"design {design_id} fails bundle rederivation: {exc.message}",
            operation="verify_resource", resource_id=design_id) from exc


def load_verified_traffic(store: Any, traffic_id: str
                          ) -> tuple[Any, dict[str, Any]]:
    """Verified physical traffic: rebuilt from verified parents only.

    Generation-dispatched on the persisted type tag. v1 keeps its
    artifact-level design link; v2 carries it at the record level (its
    artifact shape is closed). Both re-derive the bundle and require
    the design/mapping hashes to agree.
    """
    record, doc = _envelope(store, "traffic", traffic_id)
    logical = load_verified_messages(store,
                                     doc.get("message_artifact_id"))
    design_id = record.get("design_id", doc.get("design_id"))
    design_hash = record.get("design_hash", doc.get("design_hash"))
    mapping_hash = record.get("mapping_hash", doc.get("mapping_hash"))
    if not isinstance(design_id, str) or not design_id:
        raise ControlPlaneError(
            ErrorCode.EVIDENCE_INVALID,
            f"persisted traffic {traffic_id} carries no design_id link",
            operation="verify_resource", resource_id=traffic_id)
    bundle = rebuild_verified_bundle(store, design_id)
    if doc.get("type") == "srota/PhysicalTrafficArtifactV2":
        art = _parse("traffic", traffic_id, lambda: (
            PhysicalTrafficArtifactV2.from_dict(
                doc, logical=logical, bundle=bundle, strict=True)))
    else:
        raise ControlPlaneError(
            ErrorCode.EVIDENCE_INVALID,
            f"historical v1 traffic {traffic_id!r} is not supported in "
            "the canonical product (V2 only)",
            operation="verify_resource", resource_id=traffic_id)
    _require_equal("physical_traffic_id", art.physical_traffic_id(),
                   traffic_id, traffic_id)
    _require_equal("traffic.design_hash", design_hash,
                   bundle.resolved_fabric.design_hash, traffic_id)
    _require_equal("traffic.mapping_hash", mapping_hash,
                   bundle.resolved_fabric.mapping_hash, traffic_id)
    art.validate_conservation()
    from veritx_dse.verification.reference_semantics import (
        verify_packetization_reference,
    )
    verify_packetization_reference(art)
    return art, record


# ── chain identity (the product-visible Wave-D provenance block) ─────────

# The ONE authoritative key sets. Plan identity binds the scientific
# chain; the result adds only execution-derived counters. Both
# constructors assert they emit exactly these keys, so a field can never
# be added to a VERIFIED block without this verifier knowing about it.
# ── chain generations ──────────────────────────────────────────────────
# v1 (historical) authenticates the Wave-D runtime ancestry:
# wavedworkload + wavedsemantics + opgraph. It is READ-ONLY science; new
# writers must not emit it.
# v2 (canonical) authenticates the semantic parent by workload_graph_id
# alone. Absence of chain_schema_version means v1, so the boundary is
# unambiguous without guessing from which keys happen to be present.
CHAIN_SCHEMA_VERSION_V2 = 2

PLAN_CHAIN_KEYS_V2 = (
    "chain_schema_version",
    "workload_kind",
    "workload_graph_id",
    "parallelism_id",
    "message_artifact_id",
    "physical_traffic_id",
    "resolved_fabric_hash",
    "packet_format_hash",
)

PLAN_CHAIN_KEYS_V1 = (
    "workload_kind",
    "waved_workload_id",
    "parallelism_id",
    "wave_d_semantics_id",
    "operation_graph_id",
    "message_artifact_id",
    "physical_traffic_id",
    "resolved_fabric_hash",
    "packet_format_hash",
)
def chain_version(block: dict[str, Any]) -> int:
    """Which chain generation a block is.

    v1 documents did not carry a version field, so ABSENCE means v1: the
    boundary is unambiguous without inferring it from which keys happen to
    be present. An unknown version refuses rather than being interpreted.
    """
    if "chain_schema_version" not in block:
        return 1
    version = block["chain_schema_version"]
    if version != CHAIN_SCHEMA_VERSION_V2:
        raise ControlPlaneError(
            ErrorCode.EVIDENCE_INVALID,
            f"unknown chain_schema_version {version!r}",
            operation="verify_resource")
    return version


def plan_chain_keys(version: int) -> tuple[str, ...]:
    if version == 1:
        return PLAN_CHAIN_KEYS_V1
    if version == CHAIN_SCHEMA_VERSION_V2:
        return PLAN_CHAIN_KEYS_V2
    raise ControlPlaneError(ErrorCode.EVIDENCE_INVALID,
                            f"unknown chain version {version!r}",
                            operation="verify_resource")


def validate_plan_chain_shape(block: dict[str, Any]) -> int:
    """Exact per-generation schema closure: no extra or missing keys."""
    version = chain_version(block)
    expected = plan_chain_keys(version)
    if set(block) != set(expected):
        raise ControlPlaneError(
            ErrorCode.EVIDENCE_INVALID,
            f"chain block (v{version}) does not match its field set: "
            f"{sorted(block)} vs {sorted(expected)}",
            operation="verify_resource")
    return version


EXECUTION_RESULT_KEYS = (
    "expected_packets",
    "expected_flits",
    "delivered_packets",
    "flits_injected",
    "flits_accepted",
)
RESULT_WAVE_D_KEYS_V1 = PLAN_CHAIN_KEYS_V1 + EXECUTION_RESULT_KEYS
RESULT_WAVE_D_KEYS_V2 = PLAN_CHAIN_KEYS_V2 + EXECUTION_RESULT_KEYS


def result_wave_d_keys(version: int) -> tuple[str, ...]:
    """The exact result-block field set for a chain generation.

    A v1 result may never verify against a v2 plan or the reverse: the
    generations are different contracts, not different spellings.
    """
    if version == 1:
        return RESULT_WAVE_D_KEYS_V1
    if version == CHAIN_SCHEMA_VERSION_V2:
        return RESULT_WAVE_D_KEYS_V2
    raise ControlPlaneError(ErrorCode.EVIDENCE_INVALID,
                            f"unknown chain version {version!r}",
                            operation="verify_result")


def waved_chain_ids(workload: Any, graph: OperationGraph,
                    messages: Any,
                    traffic: Any,
                    bundle: Any) -> dict[str, Any]:
    """Every ID a Wave-D experiment/result binds, derived from artifacts.

    HISTORICAL v1: explicitly unsupported in the canonical product.
    New runs use semantic_chain_ids_v2.
    """
    raise ControlPlaneError(
        ErrorCode.EVIDENCE_INVALID,
        "historical v1 wave_d chain block is not supported in the "
        "canonical product (v2 canonical chain only)",
        operation="verify_resource")


def semantic_chain_ids_v2(graph: Any, messages: Any, traffic: Any,
                          bundle: Any) -> dict[str, Any]:
    """The CANONICAL chain: the semantic parent is the WorkloadGraph.

    No legacy IDs: not waved_workload_id, not wave_d_semantics_id, not
    operation_graph_id. Old resources prove old ancestry; this proves the
    new one, and it must not need the ghosts of deleted authorities.
    """
    block = {
        "chain_schema_version": CHAIN_SCHEMA_VERSION_V2,
        "workload_kind": "WAVE_D_SEMANTIC",
        "workload_graph_id": graph.workload_id(),
        "parallelism_id": graph.parallelism.parallelism_id(),
        "message_artifact_id": messages.message_artifact_id(),
        "physical_traffic_id": traffic.physical_traffic_id(),
        "resolved_fabric_hash":
            _hash_of(bundle.resolved_fabric, "resolved_fabric_hash"),
        "packet_format_hash":
            _hash_of(bundle.packet_format, "packet_format_hash"),
    }
    if set(block) != set(PLAN_CHAIN_KEYS_V2):  # pragma: no cover - guard
        raise ControlPlaneError(
            ErrorCode.INTERNAL_ERROR,
            "canonical chain block does not match PLAN_CHAIN_KEYS_V2: "
            f"{sorted(block)} vs {sorted(PLAN_CHAIN_KEYS_V2)}",
            operation="verify_resource")
    return block


def semantic_chain_ids_from_traffic_v2(traffic: Any) -> dict[str, Any]:
    """Re-derive the canonical chain from a verified traffic artifact.

    This is the replacement for ``waved_chain_ids_from_traffic``: it reads
    ``traffic.logical.graph`` directly (a WorkloadGraph) and never
    reconstructs a WaveDWorkload from side lists.
    """
    logical = traffic.logical
    return semantic_chain_ids_v2(graph=logical.graph, messages=logical,
                                 traffic=traffic, bundle=traffic.bundle)


def chain_ids_from_traffic(traffic: Any) -> dict[str, Any]:
    """Generation-dispatched re-derivation from a traffic artifact."""
    chain = traffic.logical.identity_dict()
    if "workload_id" in chain and "operation_graph_id" not in chain:
        validate_plan_chain_shape({
            "chain_schema_version": CHAIN_SCHEMA_VERSION_V2,
            "workload_kind": "WAVE_D_SEMANTIC",
            "workload_graph_id": chain["workload_id"],
            "parallelism_id":
                traffic.logical.graph.parallelism.parallelism_id(),
            "message_artifact_id": traffic.logical.message_artifact_id(),
            "physical_traffic_id": traffic.physical_traffic_id(),
            "resolved_fabric_hash":
                _hash_of(traffic.bundle.resolved_fabric,
                         "resolved_fabric_hash"),
            "packet_format_hash":
                _hash_of(traffic.bundle.packet_format,
                         "packet_format_hash"),
        })
        return semantic_chain_ids_from_traffic_v2(traffic)
    return waved_chain_ids_from_traffic(traffic)


def waved_chain_ids_from_traffic(traffic: Any
                                 ) -> dict[str, Any]:
    """Recompute the chain block from a verified traffic artifact.

    HISTORICAL v1: explicitly unsupported in the canonical product.
    """
    raise ControlPlaneError(
        ErrorCode.EVIDENCE_INVALID,
        "historical v1 wave_d chain re-derivation is not supported in "
        "the canonical product (v2 canonical chain only)",
        operation="verify_resource")


def _workload_from_graph(graph: OperationGraph) -> Any:
    """Reconstruct the declared workload that a graph was lowered from.

    HISTORICAL v1 helper: explicitly unsupported (v1 WaveDWorkload
    authority deleted per §4/§7).
    """
    raise ControlPlaneError(
        ErrorCode.EVIDENCE_INVALID,
        "historical v1 workload reconstruction is not supported in the "
        "canonical product",
        operation="verify_resource")


def waved_execution_block(chain: dict[str, Any], summary: dict[str, Any],
                          counters: dict[str, Any]) -> dict[str, Any]:
    """Result-level Wave-D provenance + the sealed execution counters.

    Generation-aware: the chain's own shape declares v1 vs v2, and the
    result block must match that generation's closed key set.
    """
    version = validate_plan_chain_shape(dict(chain))
    expected = result_wave_d_keys(version)
    block = dict(chain)
    block.update({
        "expected_packets": summary["num_packets"],
        "expected_flits": summary["flits_total"],
        "delivered_packets": counters.get("delivered_packets"),
        "flits_injected": counters.get("flits_injected"),
        "flits_accepted": counters.get("flits_accepted"),
    })
    if set(block) != set(expected):  # pragma: no cover - guard
        raise ControlPlaneError(
            ErrorCode.INTERNAL_ERROR,
            f"wave_d result block does not match RESULT_WAVE_D_KEYS_V"
            f"{version}: {sorted(block)} vs {sorted(expected)}",
            operation="verify_resource")
    return block


def load_verified_traffic_record(store: Any, traffic_id: str
                                 ) -> dict[str, Any]:
    """Verified traffic as its stored record (inspection seam)."""
    _, record = load_verified_traffic(store, traffic_id)
    return record


__all__ = [
    "EXECUTION_RESULT_KEYS",
    "PLAN_CHAIN_KEYS",
    "RESULT_WAVE_D_KEYS_V1", "RESULT_WAVE_D_KEYS_V2",
    "result_wave_d_keys",
    "WAVED_RESOURCE_KINDS",
    "load_verified_messages", "load_verified_workload_graph",
    "workload_graph_record",
    "CHAIN_SCHEMA_VERSION_V2", "PLAN_CHAIN_KEYS_V1", "PLAN_CHAIN_KEYS_V2",
    "RESULT_WAVE_D_KEYS_V1", "RESULT_WAVE_D_KEYS_V2", "result_wave_d_keys",
    "chain_ids_from_traffic", "chain_version", "plan_chain_keys",
    "semantic_chain_ids_from_traffic_v2", "semantic_chain_ids_v2",
    "validate_plan_chain_shape",
    "load_verified_operation_graph",
    "load_verified_parallelism",
    "load_verified_traffic",
    "load_verified_traffic_record",
    "load_verified_waved_semantics",
    "load_verified_waved_workload",
    "messages_v2_record",
    "parallelism_record",
    "rebuild_verified_bundle",
    "traffic_v2_record",
    "waved_chain_ids",
    "waved_chain_ids_from_traffic",
    "waved_execution_block",
]
