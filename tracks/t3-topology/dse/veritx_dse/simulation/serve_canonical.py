"""veritx_dse.simulation.serve_canonical — the canonical ``veritx serve`` path.

    cluster/service config (vendored LLMServingSim semantics)
           ↓
    canonical CompileRequest / fabric (canonical compiler ONLY)
           ↓
    canonical serving loop (real Router/Scheduler/MemoryModel)
           ↓
    ASTRA / BookSim (real binaries, qualified evidence)
           ↓
    real request metrics

LLMServingSim remains the service-semantics authority (instances,
parallelism, model, requests); VeritX remains the physical-fabric
authority (the fabric is compiled from a canonical CompileRequest and is
NEVER derived from the cluster config's network section). The legacy
``python -m serving`` path (which lets LLMServingSim own the network)
survives only behind ``veritx serve --legacy`` and its output must never
be mistaken for canonical evidence.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from veritx_dse.simulation.serving_loop import (
    CertifiedServiceProfile, ServingLoopError,
)


@dataclass(frozen=True)
class CanonicalServeResult:
    """Product-visible outcome of one canonical serve run."""

    requests_completed: int
    requests_expected: int
    rounds: int
    machine_id: str
    namespace_id: str
    evidence_ids: tuple[str, ...]
    run_id: str
    mode: str = "CANONICAL"

    def to_dict(self) -> dict[str, Any]:
        return {
            "mode": self.mode,
            "requests_completed": self.requests_completed,
            "requests_expected": self.requests_expected,
            "rounds": self.rounds,
            "machine_id": self.machine_id,
            "namespace_id": self.namespace_id,
            "evidence_ids": list(self.evidence_ids),
            "run_id": self.run_id,
        }


def load_cluster_service_semantics(cluster_path: str | Path
                                   ) -> dict[str, Any]:
    """Service semantics from a cluster config (vendored authority).

    Returns instances (model/hardware/tp/ep/pp ranks), dp groups and the
    model name. Only service-semantics fields are read: no topology, no
    link bandwidth, no BookSim config — those belong to the fabric
    authority and reading them here would leak the legacy network
    authority into the canonical path.
    """
    doc = json.loads(Path(cluster_path).read_text())
    instances: list[dict[str, Any]] = []
    for node in doc.get("nodes", []):
        for inst in node.get("instances", []):
            tp = int(inst.get("tp_size", 1))
            pp = int(inst.get("pp_size", 1))
            ep_raw = inst.get("ep_size")
            ep = int(ep_raw) if ep_raw is not None else (
                tp if _is_moe(inst.get("model_name", "")) else 1)
            instances.append({
                "model_name": inst.get("model_name", ""),
                "hardware": inst.get("hardware", ""),
                "tp_size": tp,
                "pp_size": pp,
                "ep_size": ep,
                "pd_type": inst.get("pd_type"),
                "dp_group": inst.get("dp_group"),
            })
    if not instances:
        raise ServingLoopError(
            f"cluster config {cluster_path} declares no instances")
    if any(i["pd_type"] for i in instances):
        raise ServingLoopError(
            "prefill/decode disaggregation is not supported on the "
            "canonical path (fail closed: historical PD transfer semantics "
            "have no canonical adapter yet)")
    if any(i["pp_size"] != 1 for i in instances):
        raise ServingLoopError(
            "pipeline parallelism is not supported on the canonical path "
            "(fail closed: PP SEND/RECV emission has no canonical adapter "
            "yet)")
    models = {i["model_name"] for i in instances}
    if len(models) != 1:
        raise ServingLoopError(
            f"canonical serve requires one model, got {sorted(models)}")
    return {"instances": instances, "model_name": next(iter(models))}


def _is_moe(model_name: str) -> bool:
    name = (model_name or "").lower()
    return "moe" in name or "a3b" in name or "qwen3-30b" in name


def derive_serve_fabric_request(*, total_ranks: int, model_name: str,
                                ep: int = 1, dp: int = 1) -> Any:
    """Author the canonical CompileRequest for a serving fabric.

    Glue only: the request is built from production model classes and the
    fabric itself is derived by the canonical compiler downstream. Mesh
    DOR, one deterministic VC, sealed settings — the same authority the
    canonical stack compiles through.
    """
    from veritx_dse.model.compile_model import (
        AddressMap, AddressRange, Agent, AgentKind, CompileRequest,
        ModelFamily, NocConfig, TopologyFamily, Workload,
    )
    return CompileRequest(
        workload=Workload(
            model_family=(ModelFamily.MOE if _is_moe(model_name)
                          else ModelFamily.DENSE_TRANSFORMER),
            model_name=model_name,
            tp=total_ranks, pp=1, ep=ep, dp=dp),
        requirements=(),
        agents=(Agent(kind=AgentKind.COMPUTE_TILE, count=total_ranks),
                Agent(kind=AgentKind.HBM_CONTROLLER, count=1)),
        dependencies=[],
        noc_config=NocConfig(topology_family=TopologyFamily.MESH),
        address_map=AddressMap(ranges=(
            AddressRange(name="HBM0", base=0x0, size=0x1000,
                         target_agent_idx=1),)))


def _dor_policy() -> Any:
    from veritx_dse.model.routing_policy import (
        CandidateMode, DeadlockProofObligation, DecisionScope, PathMode,
        RandomnessMode, RoutingPolicyDefinition, RoutingResourceRole,
        RoutingResourceRoleKind, SelectionLocus,
    )
    return RoutingPolicyDefinition(
        id="dor_xy", algorithm="dimension_order", algorithm_version=1,
        path_mode=PathMode.MINIMAL, decision_scope=DecisionScope.STATIC,
        candidate_mode=CandidateMode.SINGLETON,
        selection_locus=SelectionLocus.ROUTE_COMPUTE,
        randomness=RandomnessMode.NONE,
        deadlock_proof_obligation=DeadlockProofObligation.DETERMINISTIC_CDG,
        resource_roles=(RoutingResourceRole(
            id="default", kind=RoutingResourceRoleKind.DEFAULT),),
        allowed_role_transitions=(("default", "default"),))


def _deterministic_vc_spec() -> Any:
    from veritx_dse.compiler.canonical import DeterministicVCSpec
    from veritx_dse.core.route_artifact import DOR_XY
    return DeterministicVCSpec(
        vc_count=1, traffic_class_to_vcs=(("default", (0,)),),
        vc_to_routing_class=((0, DOR_XY),),
        allowed_transitions=((0, 0),), escape_vcs=(), derivation="d")


def _compile_settings() -> Any:
    from veritx_dse.compiler.canonical import FabricCompileSettings
    return FabricCompileSettings(
        max_packet_flits=8, input_buffer_depth_flits_per_vc=8,
        output_stage_depth_flits_per_vc=1)


def run_canonical_serve(*, cluster_config: str | Path,
                        dataset: str | Path, num_reqs: int,
                        run_dir: str | Path,
                        compile_request: str | Path | None = None,
                        astra_binary: str | Path | None = None,
                        profile_overrides: dict[str, Any] | None = None,
                        timeout_s: int = 900,
                        dp_groups: Any = None) -> CanonicalServeResult:
    """Execute the canonical serve path end to end (live, real binaries).

    ``cluster_config`` supplies service semantics (vendored authority);
    ``compile_request`` (optional) supplies an explicit fabric authority —
    otherwise one is derived from the serving geometry through the
    canonical compiler. ``dataset`` is a real JSONL request trace.
    """
    import sys
    from veritx_dse.backend import astra_machine as am
    from veritx_dse.backend import astra_namespace as ans
    from veritx_dse.backend import canonical_serving as cs
    from veritx_dse.backend.astra import AstraWorkloadProjection
    from veritx_dse.backend.booksim_projection import (
        BookSimProjectionParents, prepare_booksim_input,
    )
    from veritx_dse.backend.producer import resolve_producer_identity
    from veritx_dse.compiler.canonical import compile_deterministic_candidate
    from veritx_dse.model.compile_model import (
        CompileRequest, CompileRequestV3,
    )
    from veritx_dse.model.mapping import derive_mapping
    from veritx_dse.model.placement import build_inventory
    from veritx_dse.simulation import serving_loop as sl
    from veritx_dse.workload.graph import (
        KIND_COLLECTIVE, KIND_COMPUTE, OperationNode, WorkloadGraph,
        collective_detail, compute_detail,
    )
    from veritx_dse.workload.messages import LogicalMessageArtifactV2
    from veritx_dse.workload.traffic import (
        ParticipantEndpointMapping, PhysicalTrafficArtifactV2,
    )

    llm_root = Path(__file__).resolve().parents[5] / "third_party" \
        / "llmservingsim"
    if llm_root.is_dir() and str(llm_root) not in sys.path:
        sys.path.insert(0, str(llm_root))

    service = load_cluster_service_semantics(cluster_config)
    instances = service["instances"]
    model_name = service["model_name"]
    # serving ranks: contiguous per-instance spans (TP/EP overlap inside
    # each span; the rank count is the NPU count, never multiplied)
    spans: list[tuple[int, ...]] = []
    cursor = 0
    for inst in instances:
        width = max(inst["tp_size"], 1)
        spans.append(tuple(range(cursor, cursor + width)))
        cursor += width
    total_ranks = cursor
    max_ep = max(inst["ep_size"] for inst in instances)

    if compile_request is not None:
        doc = json.loads(Path(compile_request).read_text())
        try:
            request = CompileRequest.from_dict(doc)
        except Exception:
            request = CompileRequestV3.from_dict(doc)
    else:
        request = derive_serve_fabric_request(
            total_ranks=total_ranks, model_name=model_name,
            ep=1, dp=1)
    inventory = build_inventory(request)
    mapping = derive_mapping(request)
    compiled = compile_deterministic_candidate(
        design=request, inventory=inventory, mapping=mapping,
        routing_policy=_dor_policy(), vc_spec=_deterministic_vc_spec(),
        settings=_compile_settings())

    # machine qualification over a trivial all-rank collective (the live
    # loop re-projects every round over real batches; the machine itself
    # is workload-independent)
    qualifier_ops = (
        OperationNode(operation_id="pre", kind=KIND_COMPUTE,
                      detail=compute_detail(duration_ns=10000,
                                            participant_count=total_ranks)),
        OperationNode(operation_id="ar", kind=KIND_COLLECTIVE,
                      deps=("pre",),
                      detail=collective_detail(
                          collective_kind="ALLREDUCE",
                          participants=tuple(range(total_ranks)),
                          payload_bytes=1024,
                          participant_count=total_ranks)),
    )
    qualifier_graph = WorkloadGraph(
        parallelism=inventory.parallelism, participant_count=total_ranks,
        operations=qualifier_ops)
    qualifier_logical = LogicalMessageArtifactV2(graph=qualifier_graph)
    qualifier_traffic = PhysicalTrafficArtifactV2(
        logical=qualifier_logical, resolved_fabric=compiled.resolved_fabric,
        mapping=compiled.mapping, attachment=compiled.attachment,
        inventory=compiled.inventory, packet_format=compiled.packet_format)
    parents = BookSimProjectionParents(
        resolved_fabric=compiled.resolved_fabric, topology=compiled.topology,
        attachment=compiled.attachment, mapping=compiled.mapping,
        vc_resource=compiled.vc_resource,
        vc_assignment=compiled.routing.vc_assignment,
        packet_format=compiled.packet_format, route=compiled.routing.route,
        physical_traffic=qualifier_traffic)
    prepared = prepare_booksim_input(parents)
    projection = AstraWorkloadProjection.build(
        logical=qualifier_logical, resolved_fabric=compiled.resolved_fabric,
        mapping=compiled.mapping, attachment=compiled.attachment,
        et_granularity="collectives")
    machine = am.qualify_astra_machine(
        parents=parents, prepared=prepared, projection=projection,
        logical=qualifier_logical)

    # serving namespace: rank→endpoint binding over the machine endpoints
    endpoints = list(range(machine.astra_sys_count))[:total_ranks]
    binding = ParticipantEndpointMapping(
        participant_count=total_ranks,
        rank_to_endpoint=tuple((r, e) for r, e in zip(
            range(total_ranks), endpoints)),
        fabric_id=machine.resolved_fabric_hash)
    namespace = ans.build_namespace(
        machine=machine, workload=projection, binding=binding,
        endpoint_count=machine.astra_sys_count,
        router_count=machine.router_count)
    serving_instances = tuple(
        cs.ServingInstance(instance_id=i, ranks=span)
        for i, span in enumerate(spans))
    serving = cs.ServingNamespaceBinding(
        namespace=namespace, instances=serving_instances,
        serving_config_id=f"cfg/{Path(cluster_config).stem}")
    npus = sl.VirtualNpuNamespace(binding=serving)

    binary = Path(astra_binary) if astra_binary is not None \
        else (Path(__file__).resolve().parents[5] / "third_party"
              / "astra-sim" / "astra-sim" / "network_frontend" / "booksim2"
              / "bin" / "AstraSim_BookSim2")
    identity = resolve_producer_identity(binary)
    backend = cs.CanonicalServingNetworkBackend(
        machine=machine, binding=serving, astra_binary=str(binary),
        astra_binary_sha256=identity.binary_sha256,
        astra_binary_size=identity.binary_size,
        astra_source_revision=identity.source_revision,
        execution_mode=cs.MODE_LIVE_CANONICAL)
    lowering = sl.CanonicalLowering(
        resolved_fabric=compiled.resolved_fabric, mapping=compiled.mapping,
        attachment=compiled.attachment,
        parallelism=compiled.inventory.parallelism)

    profile_kwargs: dict[str, Any] = {"model": model_name}
    if max_ep > 1:
        profile_kwargs["ep_size"] = max_ep
    profile_kwargs.update(profile_overrides or {})
    profile = CertifiedServiceProfile(**profile_kwargs)
    schedulers = sl.build_schedulers(profile=profile, npus=npus,
                                     req_num=num_reqs)
    router = sl.build_router(profile=profile, schedulers=schedulers,
                             req_num=num_reqs)
    run_path = Path(run_dir)
    run_path.mkdir(parents=True, exist_ok=True)
    sl.load_request_trace(router=router, dataset=dataset,
                          load_directory=run_path, req_num=num_reqs)
    result = sl.run_request_driven_service(
        backend=backend, machine=machine, profile=profile, npus=npus,
        router=router, schedulers=schedulers, run_dir=run_path,
        workload_id=f"serve-{Path(cluster_config).stem}",
        lowering=lowering, timeout_s=timeout_s,
        session_factory=None, ledger=True,
        expected_requests=num_reqs, dp_groups=dp_groups)
    # Persist the canonical serving evidence beside the run inputs: the
    # product layer reads serving-evidence.json as the served experiment's
    # evidence document and must not reconstruct it.
    (run_path / "serving-evidence.json").write_bytes(
        result.evidence.canonical_bytes())
    return CanonicalServeResult(
        requests_completed=result.evidence.request_count,
        requests_expected=num_reqs,
        rounds=len(result.rounds),
        machine_id=machine.machine_id(),
        namespace_id=namespace.namespace_id(),
        evidence_ids=tuple(
            e.evidence_id() for e in result.round_evidence),
        run_id=result.run_id())
