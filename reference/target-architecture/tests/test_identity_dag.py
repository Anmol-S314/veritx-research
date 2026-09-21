from veritx_dse.model.parallelism import ParallelismArtifact
from veritx_dse.model.fabric import FabricSpec
from veritx_dse.model.mapping import MappingArtifact
from veritx_dse.workload.graph import WorkloadGraph,WorkloadSemantics,OperationNode,OperationKind
from veritx_dse.workload.messages import build_logical_messages
from veritx_dse.workload.traffic import build_physical_traffic


def graph(payload):
    p=ParallelismArtifact(1,1,1,2)
    op=OperationNode.create("x",OperationKind.P2P,
        detail={"role":"TRANSFER","src_rank":0,"dst_rank":1,"payload_bytes":payload})
    return WorkloadGraph.create(parallelism=p,participant_count=2,
                                semantics=WorkloadSemantics.create(),operations=(op,))


def test_workload_change_moves_descendants_not_fabric_or_mapping():
    f=FabricSpec(2,"MESH",128,64); mapping=MappingArtifact(2,(0,1),f.fabric_id())
    a,b=graph(64),graph(128)
    am,bm=build_logical_messages(a),build_logical_messages(b)
    at=build_physical_traffic(a,am,mapping=mapping,fabric=f)
    bt=build_physical_traffic(b,bm,mapping=mapping,fabric=f)
    assert a.workload_id()!=b.workload_id()
    assert am.message_artifact_id()!=bm.message_artifact_id()
    assert at.traffic_id()!=bt.traffic_id()
    assert mapping.mapping_id()==mapping.mapping_id()
