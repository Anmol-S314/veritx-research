from veritx_dse.core.errors import UnsupportedSemantic
from .graph import OperationKind


def lower_to_text_trace(graph):
    lines=[]
    for op in graph.require_total_order():
        d=op.detail_dict()
        if op.kind==OperationKind.COMPUTE:
            lines.append(f"COMPUTE {op.operation_id} {d['duration_ns']} "
                         f"{d['input_loc']}:{d['input_bytes']} "
                         f"{d['weight_loc']}:{d['weight_bytes']} "
                         f"{d['output_loc']}:{d['output_bytes']}")
        elif op.kind==OperationKind.PIM_CHANNEL:
            lines.append(f"PIM {d['channel']}")
        elif op.kind==OperationKind.PIM_END:
            lines.append("PIM END")
        else:
            lines.append(f"{op.kind.value} {op.operation_id}")
    return "\n".join(lines)+("\n" if lines else "")


def lower_to_astra_chakra_et(graph):
    if any(op.kind in {OperationKind.PIM_CHANNEL,OperationKind.PIM_END} for op in graph.operations):
        raise UnsupportedSemantic(
            "PIM is canonical semantics; qualified ASTRA/Chakra PIM execution is not enabled here"
        )
    if any(op.kind==OperationKind.COLLECTIVE and op.detail_dict()["scope"] is None for op in graph.operations):
        raise UnsupportedSemantic("ASTRA lowering refuses undeclared collective scope")
    raise UnsupportedSemantic("ASTRA/Chakra executable lowering belongs to a qualified adapter")
