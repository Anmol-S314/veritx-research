from dataclasses import dataclass
from veritx_dse.model.parallelism import ParallelismArtifact
from veritx_dse.workload.graph import WorkloadGraph,WorkloadSemantics,OperationNode,OperationKind


@dataclass(frozen=True)
class Scenario:
    name:str
    graph:WorkloadGraph


def broadcast_nonzero_root():
    p=ParallelismArtifact(1,1,1,4)
    op=OperationNode.create("broadcast",OperationKind.COLLECTIVE,
        detail={"collective_kind":"BROADCAST","participants":[0,1,2,3],
                "payload_bytes":1024,"scope":"ALL","source":2})
    return Scenario("broadcast_nonzero_root",
        WorkloadGraph.create(parallelism=p,participant_count=4,
            semantics=WorkloadSemantics.create(phase="DECODE"),operations=(op,)))


def multi_instance_namespace():
    p=ParallelismArtifact(4,1,1,2)
    op=OperationNode.create("compute",OperationKind.COMPUTE,owner=0,
        detail={"duration_ns":10,"input_bytes":1,"weight_bytes":1,"output_bytes":1,
                "input_loc":"LOCAL","weight_loc":"LOCAL","output_loc":"LOCAL","batch_tag":"b0"})
    return Scenario("multi_instance_namespace",
        WorkloadGraph.create(parallelism=p,participant_count=4,
            semantics=WorkloadSemantics.create(),operations=(op,)))
