from veritx_dse.model.parallelism import ParallelismArtifact
from veritx_dse.model.fabric import FabricSpec
from veritx_dse.model.mapping import MappingArtifact
from veritx_dse.workload.graph import WorkloadGraph,WorkloadSemantics,OperationNode,OperationKind
from veritx_dse.workload.messages import build_logical_messages
from veritx_dse.workload.traffic import build_physical_traffic


def test_nonzero_broadcast_root_reaches_physical_layer():
    p=ParallelismArtifact(1,1,1,4)
    op=OperationNode.create("b",OperationKind.COLLECTIVE,
        detail={"collective_kind":"BROADCAST","participants":[0,1,2,3],
                "payload_bytes":64,"scope":"ALL","source":2})
    g=WorkloadGraph.create(parallelism=p,participant_count=4,
                           semantics=WorkloadSemantics.create(),operations=(op,))
    m=build_logical_messages(g)
    assert [(x.src_rank,x.dst_rank) for x in m.messages]==[(2,0),(2,1),(2,3)]
    f=FabricSpec(4,"MESH",128,64)
    mapping=MappingArtifact(4,(0,1,2,3),f.fabric_id())
    t=build_physical_traffic(g,m,mapping=mapping,fabric=f)
    assert sum(p.payload_bytes for p in t.packets)==192
