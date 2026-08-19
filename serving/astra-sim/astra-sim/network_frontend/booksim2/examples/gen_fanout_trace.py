#!/usr/bin/env python3
"""Generate a 4-NPU fanout broadcast Chakra ET trace with a proper DAG:
node 0 runs a zero-time COMP root, then THREE concurrent COMM_SEND_NODE
children (dst 1,2,3, same size + tag) — the MoE-dispatch geometry. The
multicast fold should collapse the three sends into ONE fabric stream.
Nodes 1,2,3 carry a matching COMM_RECV_NODE."""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../../../..",
                                "extern", "graph_frontend", "chakra",
                                "schema", "protobuf"))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../../../..",
                                "extern", "graph_frontend", "chakra",
                                "src", "third_party", "utils"))

from et_def_pb2 import (  # noqa: E402
    GlobalMetadata,
    COMP_NODE,
    COMM_SEND_NODE,
    COMM_RECV_NODE,
    AttributeProto as ChakraAttr,
    Node as ChakraNode,
)
from protolib import encodeMessage as encode_message  # noqa: E402


def generate_fanout(npus_count: int, size: int, path: str) -> None:
    os.makedirs(path, exist_ok=True)
    for npu in range(npus_count):
        fn = os.path.join(path, f"fanout.{npu}.et")
        with open(fn, "wb") as et:
            encode_message(et, GlobalMetadata(version="0.0.4"))
            node_id = 0
            if npu == 0:
                # zero-time compute root
                root = ChakraNode()
                root.id = node_id
                root.name = "fanout_root"
                root.type = COMP_NODE
                root.attr.append(ChakraAttr(name="is_cpu_op", bool_val=False))
                root.attr.append(ChakraAttr(name="runtime", uint64_val=0))
                encode_message(et, root)
                root_id = node_id
                node_id += 1
                # concurrent sends to 1..N-1 (children of root)
                for dst in range(1, npus_count):
                    node = ChakraNode()
                    node.id = node_id
                    node.name = f"fanout_send_{dst}"
                    node.type = COMM_SEND_NODE
                    node.ctrl_deps.append(root_id)
                    node.attr.append(ChakraAttr(name="is_cpu_op", bool_val=False))
                    node.attr.append(ChakraAttr(name="comm_src", uint32_val=0))
                    node.attr.append(ChakraAttr(name="comm_dst", uint32_val=dst))
                    node.attr.append(ChakraAttr(name="comm_size", uint64_val=size))
                    node.attr.append(ChakraAttr(name="comm_tag", uint32_val=42))
                    encode_message(et, node)
                    node_id += 1
            else:
                node = ChakraNode()
                node.id = node_id
                node.name = "fanout_recv"
                node.type = COMM_RECV_NODE
                node.attr.append(ChakraAttr(name="is_cpu_op", bool_val=False))
                node.attr.append(ChakraAttr(name="comm_src", uint32_val=0))
                node.attr.append(ChakraAttr(name="comm_dst", uint32_val=npu))
                node.attr.append(ChakraAttr(name="comm_size", uint64_val=size))
                node.attr.append(ChakraAttr(name="comm_tag", uint32_val=42))
                encode_message(et, node)
                node_id += 1


if __name__ == "__main__":
    generate_fanout(int(sys.argv[1]), int(sys.argv[2]), sys.argv[3])
    print(f"wrote {sys.argv[3]}")
