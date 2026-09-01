#!/usr/bin/env python3
"""Qwen3-30B-A3B serving trace -> 4-rank Chakra ET (scoped network-only slice).

Reads an LLMServingSim per-batch trace (trace_to_matrix.py's documented
format) and emits one Chakra ET file per rank for a 4-NPU model
(2 dies x 2 NPUs, snake mesh). Mapping (documented in the claim-scope
report):
  * ALLREDUCE   -> ALL_REDUCE collective (native ring; no multicast benefit)
  * ALLGATHER   -> BROADCAST (MoE dispatch one-to-k semantics; bcast_root
                   rotates across ranks so every rank dispatches)
  * REDUCESCATTER -> REDUCE_SCATTER (native; no multicast benefit)
  * REMOTE      -> excluded (KV-remote memory traffic, <0.1% of bytes)
The slice is the first `ops` comm ops of the batch (network-only: no comp
nodes; compute-bound serving is out of scope for the bridge-bottleneck
claim, per seed 5de1)."""

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
    ALL_REDUCE,
    REDUCE_SCATTER,
    BROADCAST,
    AttributeProto as ChakraAttr,
    Node as ChakraNode,
)
from protolib import encodeMessage as encode_message  # noqa: E402

import re

LINE_RE = re.compile(
    r"^\s*(?P<name>\S+)\s+(?P<comp>\d+)\s+"
    r"(?P<in_loc>\S+)\s+(?P<in_size>\d+)\s+"
    r"(?P<w_loc>\S+)\s+(?P<w_size>\d+)\s+"
    r"(?P<out_loc>\S+)\s+(?P<out_size>\d+)\s+"
    r"(?P<comm>\S+)\s+(?P<comm_size>\d+)\s+(?P<misc>\S+)")
EXP_RE = re.compile(r"^\s*EXPERT\s+(?P<id>\d+)\s+(?P<comm>\S+)\s+(?P<size>\d+)")


def parse_comm_ops(trace_file):
    ops = []
    for line in open(trace_file):
        m = EXP_RE.match(line)
        if m:
            c, s = m.group("comm"), int(m.group("size"))
            if c != "NONE" and s > 0:
                ops.append((c, s))
            continue
        m = LINE_RE.match(line)
        if m:
            c, s = m.group("comm"), int(m.group("comm_size"))
            if c != "NONE" and s > 0:
                ops.append((c, s))
    return ops


def op_to_collective(comm):
    if comm.startswith("ALLREDUCE"):
        return ALL_REDUCE
    if comm.startswith("ALLGATHER"):
        return BROADCAST  # MoE dispatch one-to-k
    if comm.startswith("REDUCESCATTER"):
        return REDUCE_SCATTER
    return None


def generate(npus_count, trace_file, ops, path):
    seq = parse_comm_ops(trace_file)[:ops]
    os.makedirs(path, exist_ok=True)
    for rank in range(npus_count):
        fn = os.path.join(path, f"qwen_slice.{rank}.et")
        with open(fn, "wb") as et:
            encode_message(et, GlobalMetadata(version="0.0.4"))
            node_id = 0
            prev_id = None
            for i, (comm, size) in enumerate(seq):
                coll = op_to_collective(comm)
                if coll is None:
                    continue
                node = ChakraNode()
                node.id = node_id
                node.name = f"op_{i}_{comm.split(':')[0]}"
                node.type = COMM_COLL_NODE
                if prev_id is not None:
                    node.ctrl_deps.append(prev_id)
                node.attr.append(ChakraAttr(name="is_cpu_op", bool_val=False))
                node.attr.append(ChakraAttr(name="comm_type", int64_val=coll))
                node.attr.append(ChakraAttr(name="comm_size", int64_val=size))
                if coll == BROADCAST:
                    # dispatch sources constrained to the snake HEAD (rank 0):
                    # the mcast stream follows the snake, so a mid-snake source
                    # cannot reach nodes behind it. Honest routing constraint,
                    # documented in the report (on the bridged_2die fabric the
                    # dispatch geometry aligns expert placement with the route).
                    node.attr.append(
                        ChakraAttr(name="bcast_root", uint32_val=0))
                encode_message(et, node)
                prev_id = node_id
                node_id += 1
    return seq


if __name__ == "__main__":
    trace_file = sys.argv[1]
    npus = int(sys.argv[2])
    ops = int(sys.argv[3])
    path = sys.argv[4]
    seq = generate(npus, trace_file, ops, path)
    tot = sum(s for _, s in seq)
    print(f"wrote {path}: {len(seq)} ops, {tot} bytes, "
          f"{sum(1 for c,_ in seq if c.startswith('ALLGATHER'))} broadcasts")
