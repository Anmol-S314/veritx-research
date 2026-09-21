from veritx_dse.model.parallelism import ParallelismArtifact
from veritx_dse.workload.migration import graph_from_trace_rows
from veritx_dse.workload.graph import OperationKind


def test_pim_multichannel_source_survives_ingestion():
    rows=[
        ("PIM 0",),
        ("attn0","10","REMOTE:0.0","8","LOCAL","0","REMOTE:0.0","8","b0"),
        ("PIM 1",),
        ("attn1","11","REMOTE:0.1","8","LOCAL","0","REMOTE:0.1","8","b0"),
        ("PIM END",),
    ]
    graph=graph_from_trace_rows(rows,parallelism=ParallelismArtifact(1,1,1,1),participant_count=1)
    assert [op.kind for op in graph.ordered_operations()]==[
        OperationKind.PIM_CHANNEL,OperationKind.COMPUTE,OperationKind.PIM_CHANNEL,
        OperationKind.COMPUTE,OperationKind.PIM_END
    ]
