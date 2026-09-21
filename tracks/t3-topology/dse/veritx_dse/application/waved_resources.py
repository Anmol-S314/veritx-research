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

from veritx_dse.workload.messages import LogicalMessageArtifact
from veritx_dse.workload.operations import OperationGraph
from veritx_dse.model.parallelism import ParallelismArtifact
from veritx_dse.workload.semantics import WaveDWorkloadSemantics
from veritx_dse.workload.traffic import PhysicalTrafficArtifact
from veritx_dse.workload.graph import WaveDWorkload

from .errors import ControlPlaneError, ErrorCode
from .resources import RESOURCE_SCHEMA_VERSION, check_envelope

WAVED_RESOURCE_KINDS = ("wavedworkload", "parallelism", "wavedsemantics",
                        "opgraph", "messages", "traffic")


# ── records (write side) ─────────────────────────────────────────────────

def _record(kind: str, resource_id: str,
            artifact: dict[str, Any]) -> dict[str, Any]:
    return {
        "resource_type": kind,
        "schema_version": RESOURCE_SCHEMA_VERSION,
        "resource_id": resource_id,
        "artifact": artifact,
    }


def parallelism_record(art: ParallelismArtifact) -> dict[str, Any]:
    return _record("parallelism", art.parallelism_id(), art.to_dict())


def waved_semantics_record(art: WaveDWorkloadSemantics) -> dict[str, Any]:
    return _record("wavedsemantics", art.semantics_id(), art.to_dict())


def waved_workload_record(art: WaveDWorkload) -> dict[str, Any]:
    return _record("wavedworkload", art.workload_id(), art.to_dict())


def operation_graph_record(art: OperationGraph) -> dict[str, Any]:
    return _record("opgraph", art.operation_graph_id(), art.to_dict())


def messages_record(art: LogicalMessageArtifact) -> dict[str, Any]:
    return _record("messages", art.message_artifact_id(), art.to_dict())


def traffic_record(art: PhysicalTrafficArtifact, *, design_id: str
                   ) -> dict[str, Any]:
    """Physical traffic + the navigational link to its compiled design.

    ``design_id``/``design_hash``/``mapping_hash`` are links, not
    identity: the identity-bearing parent is ``resolved_fabric_hash``,
    and the loader re-derives the bundle and requires all of them to
    agree.
    """
    doc = dict(art.to_dict())
    doc["design_id"] = design_id
    doc["design_hash"] = art.bundle.resolved_fabric.design_hash
    doc["mapping_hash"] = art.bundle.resolved_fabric.mapping_hash
    return _record("traffic", art.physical_traffic_id(), doc)


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
                                 workload_id: str) -> WaveDWorkload:
    """Verified Wave-D workload: parents resolved by ID and verified."""
    _, doc = _envelope(store, "wavedworkload", workload_id)
    parallelism = load_verified_parallelism(store,
                                            doc.get("parallelism_id"))
    semantics = load_verified_waved_semantics(
        store, doc.get("wave_d_semantics_id"))
    art = _parse("wavedworkload", workload_id, lambda: (
        WaveDWorkload.from_dict(doc, parallelism=parallelism,
                                semantics=semantics, strict=True)))
    _require_equal("workload_id", art.workload_id(), workload_id,
                   workload_id)
    return art


def load_verified_operation_graph(store: Any,
                                  graph_id: str) -> OperationGraph:
    """Verified graph: exactly the graph its declared workload produces."""
    _, doc = _envelope(store, "opgraph", graph_id)
    workload = load_verified_waved_workload(store, doc.get("workload_id"))
    parallelism = load_verified_parallelism(store, doc.get("parallelism_id"))
    semantics = load_verified_waved_semantics(
        store, doc.get("wave_d_semantics_id"))
    _require_equal("workload.parallelism_id",
                   workload.parallelism.parallelism_id(),
                   parallelism.parallelism_id(), graph_id)
    _require_equal("workload.wave_d_semantics_id",
                   workload.semantics.semantics_id(),
                   semantics.semantics_id(), graph_id)
    graph = _parse("opgraph", graph_id, lambda: OperationGraph.from_dict(
        doc, parallelism=parallelism, semantics=semantics, strict=True))
    _require_equal("operation_graph_id", graph.operation_graph_id(),
                   graph_id, graph_id)
    derived = workload.to_graph()
    _require_equal("operation_graph_id", derived.operation_graph_id(),
                   graph.operation_graph_id(), graph_id)
    return graph


def load_verified_messages(store: Any,
                           message_artifact_id: str
                           ) -> LogicalMessageArtifact:
    _, doc = _envelope(store, "messages", message_artifact_id)
    graph = load_verified_operation_graph(store,
                                          doc.get("operation_graph_id"))
    art = _parse("messages", message_artifact_id, lambda: (
        LogicalMessageArtifact.from_dict(doc, graph=graph, strict=True)))
    _require_equal("message_artifact_id", art.message_artifact_id(),
                   message_artifact_id, message_artifact_id)
    art.validate_conservation()
    return art


def rebuild_verified_bundle(store: Any, design_id: str) -> Any:
    """Recompile the Wave-B bundle from a VERIFIED design resource."""
    from veritx_dse.model.compile_model import CompileRequest

    from .compile import compile_bundle
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
        return compile_bundle(request)
    except ControlPlaneError as exc:
        raise ControlPlaneError(
            ErrorCode.EVIDENCE_INVALID,
            f"design {design_id} fails bundle rederivation: {exc.message}",
            operation="verify_resource", resource_id=design_id) from exc


def load_verified_traffic(store: Any, traffic_id: str
                          ) -> tuple[PhysicalTrafficArtifact, dict[str, Any]]:
    """Verified physical traffic: rebuilt from verified parents only."""
    record, doc = _envelope(store, "traffic", traffic_id)
    logical = load_verified_messages(store,
                                     doc.get("message_artifact_id"))
    design_id = doc.get("design_id")
    if not isinstance(design_id, str) or not design_id:
        raise ControlPlaneError(
            ErrorCode.EVIDENCE_INVALID,
            f"persisted traffic {traffic_id} carries no design_id link",
            operation="verify_resource", resource_id=traffic_id)
    bundle = rebuild_verified_bundle(store, design_id)
    art = _parse("traffic", traffic_id, lambda: (
        PhysicalTrafficArtifact.from_dict(
            doc, logical=logical, bundle=bundle, strict=True)))
    _require_equal("physical_traffic_id", art.physical_traffic_id(),
                   traffic_id, traffic_id)
    _require_equal("traffic.design_hash", doc.get("design_hash"),
                   bundle.resolved_fabric.design_hash, traffic_id)
    _require_equal("traffic.mapping_hash", doc.get("mapping_hash"),
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
PLAN_CHAIN_KEYS = (
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
EXECUTION_RESULT_KEYS = (
    "expected_packets",
    "expected_flits",
    "delivered_packets",
    "flits_injected",
    "flits_accepted",
)
RESULT_WAVE_D_KEYS = PLAN_CHAIN_KEYS + EXECUTION_RESULT_KEYS


def waved_chain_ids(workload: WaveDWorkload, graph: OperationGraph,
                    messages: LogicalMessageArtifact,
                    traffic: PhysicalTrafficArtifact,
                    bundle: Any) -> dict[str, Any]:
    """Every ID a Wave-D experiment/result binds, derived from artifacts.

    One implementation: plan identity, workload identity, result
    provenance and the verified re-derivation on load all call this, so
    a stored block can be compared field-by-field against a recomputed
    one.
    """
    block = {
        "workload_kind": "WAVE_D_SEMANTIC",
        "waved_workload_id": workload.workload_id(),
        "parallelism_id": workload.parallelism.parallelism_id(),
        "wave_d_semantics_id": workload.semantics.semantics_id(),
        "operation_graph_id": graph.operation_graph_id(),
        "message_artifact_id": messages.message_artifact_id(),
        "physical_traffic_id": traffic.physical_traffic_id(),
        "resolved_fabric_hash":
            bundle.resolved_fabric.resolved_fabric_hash(),
        "packet_format_hash":
            bundle.packet_format.packet_format_hash(),
    }
    if set(block) != set(PLAN_CHAIN_KEYS):  # pragma: no cover - guard
        raise ControlPlaneError(
            ErrorCode.INTERNAL_ERROR,
            "wave_d chain block does not match PLAN_CHAIN_KEYS: "
            f"{sorted(block)} vs {sorted(PLAN_CHAIN_KEYS)}",
            operation="verify_resource")
    return block


def waved_chain_ids_from_traffic(traffic: PhysicalTrafficArtifact
                                 ) -> dict[str, Any]:
    """Recompute the chain block from a verified traffic artifact."""
    logical = traffic.logical
    return waved_chain_ids(
        workload=_workload_from_graph(logical.graph),
        graph=logical.graph, messages=logical, traffic=traffic,
        bundle=traffic.bundle)


def _workload_from_graph(graph: OperationGraph) -> WaveDWorkload:
    """Reconstruct the declared workload that a graph was lowered from.

    The graph carries only link details, so the workload is rebuilt from
    the graph's own intents; ``workload_id`` then re-derives from the
    same content. This is used ONLY to recompute identity for
    comparison, never to author a graph.
    """
    from veritx_dse.workload.graph import WaveDOperation
    ops: list[WaveDOperation] = []
    by_id = {n.operation_id: n for n in graph.nodes}
    for n in graph.nodes:
        detail: dict[str, Any] = {}
        if n.kind == "COLLECTIVE":
            cid = n.detail.get("collective_id")
            ci = next(c for c in graph.collectives
                      if c.collective_id == cid)
            detail = {"collective_id": ci.collective_id,
                      "collective_kind": ci.kind,
                      "participants": list(ci.participants),
                      "payload_bytes": ci.payload_bytes}
        elif n.kind == "P2P":
            tid = n.detail.get("transfer_id")
            tr = next(t for t in graph.p2p_transfers
                      if t.transfer_id == tid)
            detail = {"transfer_id": tr.transfer_id,
                      "src_rank": tr.src_rank, "dst_rank": tr.dst_rank,
                      "payload_bytes": tr.payload_bytes}
        elif n.kind == "MULTICAST":
            mid = n.detail.get("multicast_id")
            mc = next(m for m in graph.multicasts
                      if m.multicast_id == mid)
            detail = {"multicast_id": mc.multicast_id,
                      "source_rank": mc.source_rank,
                      "destinations": list(mc.destinations),
                      "payload_bytes": mc.payload_bytes,
                      "replication": mc.replication}
        else:  # pragma: no cover - declared workloads have no other kind
            raise ControlPlaneError(
                ErrorCode.EVIDENCE_INVALID,
                f"operation {n.operation_id!r} kind {n.kind!r} is not a "
                "declared Wave-D workload operation",
                operation="verify_resource")
        ops.append(WaveDOperation(
            operation_id=n.operation_id, kind=n.kind, owner=n.owner,
            phase=n.phase, step=n.step, deps=tuple(n.deps), detail=detail))
    return WaveDWorkload(parallelism=graph.parallelism,
                         semantics=graph.semantics,
                         operations=tuple(ops))


def waved_execution_block(chain: dict[str, Any], summary: dict[str, Any],
                          counters: dict[str, Any]) -> dict[str, Any]:
    """Result-level Wave-D provenance + the sealed execution counters."""
    block = dict(chain)
    block.update({
        "expected_packets": summary["num_packets"],
        "expected_flits": summary["flits_total"],
        "delivered_packets": counters.get("delivered_packets"),
        "flits_injected": counters.get("flits_injected"),
        "flits_accepted": counters.get("flits_accepted"),
    })
    if set(block) != set(RESULT_WAVE_D_KEYS):  # pragma: no cover - guard
        raise ControlPlaneError(
            ErrorCode.INTERNAL_ERROR,
            "wave_d result block does not match RESULT_WAVE_D_KEYS: "
            f"{sorted(block)} vs {sorted(RESULT_WAVE_D_KEYS)}",
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
    "RESULT_WAVE_D_KEYS",
    "WAVED_RESOURCE_KINDS",
    "load_verified_messages",
    "load_verified_operation_graph",
    "load_verified_parallelism",
    "load_verified_traffic",
    "load_verified_traffic_record",
    "load_verified_waved_semantics",
    "load_verified_waved_workload",
    "messages_record",
    "operation_graph_record",
    "parallelism_record",
    "rebuild_verified_bundle",
    "traffic_record",
    "waved_chain_ids",
    "waved_chain_ids_from_traffic",
    "waved_execution_block",
    "waved_semantics_record",
    "waved_workload_record",
]
