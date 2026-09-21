import pytest
from veritx_dse.core.errors import InvalidInput
from veritx_dse.model.parallelism import ParallelismArtifact
from veritx_dse.workload.graph import WorkloadGraph,WorkloadSemantics,OperationNode,OperationKind


def compute(owner=0):
    return OperationNode.create("c",OperationKind.COMPUTE,owner=owner,
        detail={"duration_ns":10,"input_bytes":1,"weight_bytes":2,"output_bytes":3,
                "input_loc":"LOCAL","weight_loc":"LOCAL","output_loc":"LOCAL","batch_tag":"b"})


def test_participant_namespace_independent_of_world_size():
    p=ParallelismArtifact(4,1,1,2)
    g=WorkloadGraph.create(parallelism=p,participant_count=4,
                           semantics=WorkloadSemantics.create(),operations=(compute(3),))
    assert p.world_size==8 and g.participant_count==4
    with pytest.raises(InvalidInput):
        WorkloadGraph.create(parallelism=p,participant_count=4,
                             semantics=WorkloadSemantics.create(),operations=(compute(4),))


def test_pim_channel_switch_is_not_nested_begin():
    p=ParallelismArtifact(1,1,1,1)
    ops=(
        OperationNode.create("p0",OperationKind.PIM_CHANNEL,detail={"channel":0}),
        OperationNode.create("p1",OperationKind.PIM_CHANNEL,deps=("p0",),detail={"channel":1}),
        OperationNode.create("pe",OperationKind.PIM_END,deps=("p1",),detail={}),
    )
    WorkloadGraph.create(parallelism=p,participant_count=1,
                         semantics=WorkloadSemantics.create(),operations=ops)
