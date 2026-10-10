"""Connected remote projection of explicit tensor demand into the existing V5 runner.

Run: python -m veritx_dse.application.tensor_demand examples/tensor_demand_v5.json
Service/control/classes/clock are authored, not generated from tensor sizes.
"""
from dataclasses import dataclass, asdict
import json
from pathlib import Path
import sys

from veritx_dse.core.artifact import FrozenMap, canonical_bytes, content_id, require_fields, thaw
from veritx_dse.core.errors import InvalidInput, EvidenceInvalid, UnsupportedSemantics
from veritx_dse.model.resource_graph import exact_int
from veritx_dse.model.access_policy import AddressSpace
from veritx_dse.model.transaction_intent import TransactionKind
from veritx_dse.model.tensor_demand import TensorDemandWorkload
from veritx_dse.workload.tensor_demand import lower_tensor_demand
from veritx_dse.workload.data_movement import DataMovementOperation, DataMovementWorkload


@dataclass(frozen=True)
class RemoteDemandPolicy:
    network_clock: str
    control_bytes: int
    service_cycles: int
    traffic_class: str
    response_traffic_class: str

    def __post_init__(self):
        for name in ("network_clock", "traffic_class", "response_traffic_class"):
            if not isinstance(getattr(self, name), str) or not getattr(self, name):
                raise InvalidInput(f"{name} must be an explicit nonempty string")
        exact_int("control_bytes", self.control_bytes, 1)
        exact_int("service_cycles", self.service_cycles, 0)

    def to_dict(self):
        return asdict(self)

    @classmethod
    def from_dict(cls, doc):
        require_fields(doc, cls.__dataclass_fields__, "remote demand policy")
        if set(doc) != set(cls.__dataclass_fields__):
            raise InvalidInput("remote demand policy is missing required fields")
        return cls(**doc)


@dataclass(frozen=True)
class RemoteTensorDemand:
    demand_id: str
    policy: RemoteDemandPolicy
    workload: DataMovementWorkload
    completion_groups: FrozenMap

    def identity_dict(self):
        return {"type": "veritx/RemoteTensorDemand", "schema_version": 1,
                "demand_id": self.demand_id, "policy": self.policy.to_dict(),
                "workload": self.workload.to_dict(), "completion_groups": thaw(self.completion_groups),
                "scope": "AUTHORED_SERVICE_ABSTRACT_REMOTE_ONLY_NO_PADDING_TRANSFER"}

    def artifact_id(self):
        return content_id("veritx/RemoteTensorDemand/v1", self.identity_dict())

    def to_dict(self):
        return {**self.identity_dict(), "artifact_id": self.artifact_id()}

    @classmethod
    def from_dict(cls, doc, *, compilation, workload, policy):
        expected = project_remote_tensor_demand(compilation, workload, policy)
        if canonical_bytes(doc) != canonical_bytes(expected.to_dict()):
            raise EvidenceInvalid("remote tensor projection differs from parent-recomputed result")
        return expected


def project_remote_tensor_demand(compilation, workload: TensorDemandWorkload,
                                 policy: RemoteDemandPolicy, *, allow_owner_cache=False) -> RemoteTensorDemand:
    """Preserve access completion dependencies across all fragments and splits.

    Generated requests transfer only payload bytes, not transaction padding.
    Existing initiator ordering/credit/authorization policies remain authoritative.
    """
    if not isinstance(policy, RemoteDemandPolicy):
        raise InvalidInput("explicit RemoteDemandPolicy is required")
    demand = lower_tensor_demand(compilation, workload, allow_owner_cache=allow_owner_cache)
    if not demand.requests:
        raise UnsupportedSemantics("empty demand has no remote data-movement workload")
    if len(demand.requests) > 10000:
        raise UnsupportedSemantics("remote projection exceeds existing runner operation bound")
    if any(r.issuer == r.target for r in demand.requests):
        raise UnsupportedSemantics("local tensor requests require a local execution consumer")
    groups = {a.access_id: tuple(r.request_id for r in demand.requests if r.access_id == a.access_id)
              for a in workload.accesses}
    by_access = {a.access_id: [] for a in workload.accesses}
    for request in demand.requests:
        by_access[request.access_id].append(request)
    operations = []
    for access in workload.topological_accesses():
        deps = tuple(rid for dep in access.deps for rid in groups[dep])
        for request in by_access[access.access_id]:
            operations.append(DataMovementOperation(
                request.request_id, request.issuer, request.target, TransactionKind(request.kind),
                request.payload_address, request.payload_bytes, policy.control_bytes,
                policy.service_cycles, policy.traffic_class, deps,
                AddressSpace(request.address_space), policy.response_traffic_class))
    remote = DataMovementWorkload(workload.design_hash, policy.network_clock, tuple(operations))
    if sum(op.payload_bytes for op in remote.operations) != demand.audit["request_payload_bytes"]:
        raise EvidenceInvalid("remote projection payload conservation failure")
    return RemoteTensorDemand(demand.artifact_id(), policy, remote, FrozenMap(groups))


def run_document(doc):
    """One connected CLI example envelope, not a competing revision/API root."""
    from veritx_dse.application.fabric_compiler import FabricCompiler
    from veritx_dse.application.data_movement import execute_data_movement
    from veritx_dse.model.compile_request_v5 import CompileRequestV5
    from veritx_dse.model.physical_placement import PhysicalPlacement
    require_fields(doc, {"design", "demand", "transport", "placement"}, "tensor experiment")
    if set(doc) != {"design", "demand", "transport", "placement"}:
        raise InvalidInput("tensor experiment is missing required fields")
    compilation = FabricCompiler().compile(CompileRequestV5.from_dict(doc["design"]))
    workload = TensorDemandWorkload.from_dict(doc["demand"])
    policy = RemoteDemandPolicy.from_dict(doc["transport"])
    demand = lower_tensor_demand(compilation, workload)
    remote = project_remote_tensor_demand(compilation, workload, policy)
    placement = PhysicalPlacement.from_dict(doc["placement"])
    evidence = execute_data_movement(compilation, remote.workload, placement)
    return {"demand": demand.to_dict(), "remote_projection": remote.to_dict(),
            "abstract_execution": evidence.to_dict()}


def main(argv=None):
    from veritx_dse.core.errors import Refusal, SemanticError
    argv = sys.argv[1:] if argv is None else argv
    try:
        if len(argv) != 1:
            raise InvalidInput("expected one tensor experiment JSON path")
        result = run_document(json.loads(Path(argv[0]).read_text()))
    except (Refusal, SemanticError, OSError, json.JSONDecodeError) as exc:
        print(json.dumps({"status": "REFUSED", "reason": str(exc)}, sort_keys=True))
        return 2
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
