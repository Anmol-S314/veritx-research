#!/usr/bin/env python3
"""Generate a 4-NPU BROADCAST Chakra ET trace: one COMM_COLL_NODE with
comm_type=BROADCAST on every rank (root = rank 0 by convention). The root's
native-collective implementation issues k-1 concurrent sends — the multicast
fold's trigger condition."""

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
    COMM_COLL_NODE,
    BROADCAST,
    AttributeProto as ChakraAttr,
    Node as ChakraNode,
)
from protolib import encodeMessage as encode_message  # noqa: E402


def generate_broadcast(npus_count: int, size: int, path: str) -> None:
    os.makedirs(path, exist_ok=True)
    for npu in range(npus_count):
        fn = os.path.join(path, f"bcast.{npu}.et")
        with open(fn, "wb") as et:
            encode_message(et, GlobalMetadata(version="0.0.4"))
            node = ChakraNode()
            node.id = 0
            node.name = f"bcast_{npus_count}npus"
            node.type = COMM_COLL_NODE
            node.attr.append(ChakraAttr(name="is_cpu_op", bool_val=False))
            node.attr.append(ChakraAttr(name="comm_type", int64_val=BROADCAST))
            node.attr.append(ChakraAttr(name="comm_size", int64_val=size))
            encode_message(et, node)


if __name__ == "__main__":
    generate_broadcast(int(sys.argv[1]), int(sys.argv[2]), sys.argv[3])
    print(f"wrote {sys.argv[3]}")
