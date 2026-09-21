from veritx_dse.core.errors import InvalidInput
from .graph import WorkloadGraph,WorkloadSemantics,OperationNode,OperationKind


def graph_from_trace_rows(rows,*,parallelism,participant_count):
    """Direct source ingestion. Historical persisted readers stay out of live runtime."""
    ops=[]; previous=None
    for index,row in enumerate(rows):
        if not row: continue
        head=row[0].strip(); oid=f"op{index}"; deps=() if previous is None else (previous,)
        if head.startswith("PIM "):
            suffix=head.split(maxsplit=1)[1]
            if suffix=="END":
                op=OperationNode.create(oid,OperationKind.PIM_END,deps=deps,detail={})
            else:
                try: channel=int(suffix)
                except ValueError as exc: raise InvalidInput("invalid PIM channel") from exc
                op=OperationNode.create(oid,OperationKind.PIM_CHANNEL,deps=deps,detail={"channel":channel})
        else:
            if len(row)!=9:
                raise InvalidInput("trace row requires 9 columns in this reference parser")
            label,duration,iloc,ibytes,wloc,wbytes,oloc,obytes,batch=row
            op=OperationNode.create(
                oid,OperationKind.COMPUTE,deps=deps,label=label,
                detail={"duration_ns":int(duration),"input_bytes":int(ibytes),
                        "weight_bytes":int(wbytes),"output_bytes":int(obytes),
                        "input_loc":iloc,"weight_loc":wloc,"output_loc":oloc,"batch_tag":batch}
            )
        ops.append(op); previous=oid
    return WorkloadGraph.create(parallelism=parallelism,participant_count=participant_count,
                                semantics=WorkloadSemantics.create(),operations=tuple(ops),
                                provenance={"source":"trace_rows"})
