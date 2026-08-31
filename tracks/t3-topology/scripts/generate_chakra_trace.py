#!/usr/bin/env python3
"""Chakra Execution Trace (.et) Generator for ASTRA-Sim 2.0.

Generates standardized, dynamic Chakra Execution Traces (.et) representing distributed
AI workloads (LLaMA-7B, LLaMA-13B, LLaMA-70B, GPT-3, ResNet-50, custom models, and collective microbenchmarks)
as Directed Acyclic Graphs (DAGs).

Each node in the Chakra Execution Trace DAG represents:
  - COMP_NODE        (1) : Local NPU/GPU tensor computation (e.g., QKV projection, FFN SwiGLU)
  - COMM_COLL_NODE   (2) : Collective communication (e.g., Ring All-Reduce, Reduce-Scatter)
  - COMM_SEND_NODE   (3) : Point-to-point Send (e.g., Pipeline Parallel activation transfer)
  - COMM_RECV_NODE   (4) : Point-to-point Recv
  - MEM_NODE         (5) : Local host/device memory transfer

Usage
-----
    python3 scripts/generate_chakra_trace.py --model llama7b --out-dir results/chakra_traces
    python3 scripts/generate_chakra_trace.py --model llama70b --tp 8 --pp 8
    python3 scripts/generate_chakra_trace.py --model custom --hidden-size 8192 --num-layers 64
    python3 scripts/generate_chakra_trace.py --selfcheck
"""

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Dict, Any, List, Tuple

HERE = Path(__file__).parent
TRACK = HERE.parent
RESULTS_DIR = TRACK / "results"

# Chakra Node Types (Standard MLCommons Enum)
COMP_NODE = 1
COMM_COLL_NODE = 2
COMM_SEND_NODE = 3
COMM_RECV_NODE = 4
MEM_NODE = 5

# Chakra Collective Types
ALL_REDUCE = 1
ALL_GATHER = 2
REDUCE_SCATTER = 3
ALL_TO_ALL = 4


MODEL_PRESETS: Dict[str, Dict[str, Any]] = {
    "llama7b": {
        "model_name": "LLaMA-7B",
        "hidden_size": 4096,
        "ffn_size": 11008,
        "num_layers": 32,
        "seq_len": 2048,
        "batch_size": 2,
        "tp_degree": 4,
        "pp_degree": 4,
        "bytes_per_elem": 2,
    },
    "llama13b": {
        "model_name": "LLaMA-13B",
        "hidden_size": 5120,
        "ffn_size": 13824,
        "num_layers": 40,
        "seq_len": 2048,
        "batch_size": 2,
        "tp_degree": 4,
        "pp_degree": 4,
        "bytes_per_elem": 2,
    },
    "llama70b": {
        "model_name": "LLaMA-70B",
        "hidden_size": 8192,
        "ffn_size": 28672,
        "num_layers": 80,
        "seq_len": 2048,
        "batch_size": 2,
        "tp_degree": 8,
        "pp_degree": 8,
        "bytes_per_elem": 2,
    },
    "gpt3": {
        "model_name": "GPT-3-175B",
        "hidden_size": 12288,
        "ffn_size": 49152,
        "num_layers": 96,
        "seq_len": 2048,
        "batch_size": 2,
        "tp_degree": 8,
        "pp_degree": 8,
        "bytes_per_elem": 2,
    },
    "resnet50": {
        "model_name": "ResNet-50",
        "hidden_size": 2048,
        "ffn_size": 2048,
        "num_layers": 50,
        "seq_len": 224,
        "batch_size": 32,
        "tp_degree": 1,
        "pp_degree": 1,
        "bytes_per_elem": 4,
    },
}


class ChakraNode:
    """Represents a single node in a Chakra Execution Trace DAG."""
    def __init__(self, node_id: int, name: str, node_type: int, duration_us: int = 10):
        self.id = node_id
        self.name = name
        self.type = node_type
        self.duration_us = duration_us
        self.data_deps: List[int] = []
        self.attr: Dict[str, Any] = {}

    def add_dependency(self, parent_id: int):
        if parent_id not in self.data_deps:
            self.data_deps.append(parent_id)

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "name": self.name,
            "type": self.type,
            "duration_us": self.duration_us,
            "data_deps": self.data_deps,
            "attr": self.attr,
        }


class ChakraTraceGenerator:
    """Generates Chakra Execution Trace DAGs for Distributed AI Workloads."""
    def __init__(self):
        self.nodes: List[ChakraNode] = []
        self.current_id = 0

    def _next_id(self) -> int:
        self.current_id += 1
        return self.current_id

    def resolve_spec(self, model_key: str, **kwargs) -> Dict[str, Any]:
        """Construct full workload specification dictionary from preset and/or overrides."""
        key = model_key.lower()
        if key in MODEL_PRESETS:
            spec = dict(MODEL_PRESETS[key])
        else:
            spec = {
                "model_name": model_key.upper(),
                "hidden_size": 4096,
                "ffn_size": 11008,
                "num_layers": 32,
                "seq_len": 2048,
                "batch_size": 2,
                "tp_degree": 4,
                "pp_degree": 4,
                "bytes_per_elem": 2,
            }

        # Apply CLI overrides if provided
        for field in ("hidden_size", "ffn_size", "num_layers", "seq_len", "batch_size", "tp_degree", "pp_degree", "bytes_per_elem"):
            if kwargs.get(field) is not None:
                spec[field] = kwargs[field]

        # Derived calculations
        hidden_size = spec["hidden_size"]
        ffn_size = spec["ffn_size"]
        seq_len = spec["seq_len"]
        batch_size = spec["batch_size"]
        num_layers = spec["num_layers"]
        bytes_per_elem = spec["bytes_per_elem"]

        msg_size_bytes = batch_size * seq_len * hidden_size * bytes_per_elem
        msg_size_mb = msg_size_bytes / (1024 * 1024)

        attn_flops = 2 * (4 * hidden_size * hidden_size) * seq_len * batch_size
        mlp_flops = 2 * (3 * hidden_size * ffn_size) * seq_len * batch_size
        layer_flops = attn_flops + mlp_flops
        total_flops = layer_flops * num_layers

        spec.update({
            "msg_size_bytes": msg_size_bytes,
            "msg_size_mb": msg_size_mb,
            "attn_flops": attn_flops,
            "mlp_flops": mlp_flops,
            "layer_flops": layer_flops,
            "total_flops": total_flops,
            "num_tp_allreduce_per_layer": 2,
            "total_allreduce_calls": num_layers * 2,
        })
        return spec

    def build_model_trace(self, spec: Dict[str, Any]) -> List[dict]:
        """Build dynamic Chakra ET DAG for any Transformer or Deep Learning Model architecture."""
        self.nodes = []
        self.current_id = 0
        prev_node_id = None

        num_layers = spec["num_layers"]
        msg_size_bytes = spec["msg_size_bytes"]
        pp_degree = spec.get("pp_degree", 1)
        pp_stage_layers = max(1, num_layers // pp_degree) if pp_degree > 1 else num_layers

        for layer_idx in range(num_layers):
            # 1. Attention Compute (COMP_NODE)
            attn_duration = max(5, int(spec["attn_flops"] / 1e10))
            attn_comp = ChakraNode(self._next_id(), f"layer_{layer_idx}_attn_comp", COMP_NODE, duration_us=attn_duration)
            attn_comp.attr = {"flops": spec["attn_flops"], "layer": layer_idx}
            if prev_node_id:
                attn_comp.add_dependency(prev_node_id)
            self.nodes.append(attn_comp)

            # 2. Attention All-Reduce (COMM_COLL_NODE)
            attn_comm = ChakraNode(self._next_id(), f"layer_{layer_idx}_attn_allreduce", COMM_COLL_NODE, duration_us=max(10, int(spec["msg_size_mb"] * 5)))
            attn_comm.attr = {
                "comm_type": "ALL_REDUCE",
                "comm_size_bytes": msg_size_bytes,
                "comm_size_mb": spec["msg_size_mb"],
            }
            attn_comm.add_dependency(attn_comp.id)
            self.nodes.append(attn_comm)

            # 3. MLP / FFN Compute (COMP_NODE)
            mlp_duration = max(5, int(spec["mlp_flops"] / 1e10))
            mlp_comp = ChakraNode(self._next_id(), f"layer_{layer_idx}_mlp_comp", COMP_NODE, duration_us=mlp_duration)
            mlp_comp.attr = {"flops": spec["mlp_flops"], "layer": layer_idx}
            mlp_comp.add_dependency(attn_comm.id)
            self.nodes.append(mlp_comp)

            # 4. MLP All-Reduce (COMM_COLL_NODE)
            mlp_comm = ChakraNode(self._next_id(), f"layer_{layer_idx}_mlp_allreduce", COMM_COLL_NODE, duration_us=max(10, int(spec["msg_size_mb"] * 5)))
            mlp_comm.attr = {
                "comm_type": "ALL_REDUCE",
                "comm_size_bytes": msg_size_bytes,
                "comm_size_mb": spec["msg_size_mb"],
            }
            mlp_comm.add_dependency(mlp_comp.id)
            self.nodes.append(mlp_comm)

            prev_node_id = mlp_comm.id

            # 5. Pipeline Parallel Activation Transfer (COMM_SEND_NODE) at stage boundaries
            if pp_degree > 1 and (layer_idx + 1) % pp_stage_layers == 0 and layer_idx < num_layers - 1:
                pp_send = ChakraNode(self._next_id(), f"layer_{layer_idx}_pp_stage_send", COMM_SEND_NODE, duration_us=max(5, int(spec["msg_size_mb"] * 2)))
                pp_send.attr = {
                    "comm_type": "P2P_SEND",
                    "comm_size_bytes": msg_size_bytes,
                    "stage": (layer_idx + 1) // pp_stage_layers,
                }
                pp_send.add_dependency(mlp_comm.id)
                self.nodes.append(pp_send)
                prev_node_id = pp_send.id

        return [n.to_dict() for n in self.nodes]

    def build_llama7b_trace(self, num_layers: int = 32, msg_size_bytes: int = 33554432) -> List[dict]:
        """Convenience method for LLaMA-7B backward compatibility."""
        spec = self.resolve_spec("llama7b", num_layers=num_layers)
        if msg_size_bytes:
            spec["msg_size_bytes"] = msg_size_bytes
            spec["msg_size_mb"] = msg_size_bytes / (1024 * 1024)
        return self.build_model_trace(spec)

    def build_collective_trace(self, comm_type: str = "ALL_REDUCE", msg_size_bytes: int = 16777216) -> List[dict]:
        """Build Chakra ET DAG for micro-benchmark collective operation."""
        self.nodes = []
        self.current_id = 0
        c1 = ChakraNode(self._next_id(), "comp_pre", COMP_NODE, duration_us=10)
        self.nodes.append(c1)

        comm = ChakraNode(self._next_id(), f"comm_{comm_type.lower()}", COMM_COLL_NODE, duration_us=150)
        comm.attr = {"comm_type": comm_type.upper(), "comm_size_bytes": msg_size_bytes}
        comm.add_dependency(c1.id)
        self.nodes.append(comm)

        c2 = ChakraNode(self._next_id(), "comp_post", COMP_NODE, duration_us=10)
        c2.add_dependency(comm.id)
        self.nodes.append(c2)

        return [n.to_dict() for n in self.nodes]


def _encode_varint(value: int) -> bytes:
    """Encode an unsigned integer into Protobuf varint bytes."""
    res = bytearray()
    while True:
        towrite = value & 0x7F
        value >>= 7
        if value:
            res.append(towrite | 0x80)
        else:
            res.append(towrite)
            break
    return bytes(res)


def encode_chakra_node_protobuf(node_dict: dict) -> bytes:
    """Encode a Chakra Node into binary Protobuf format according to et_def.proto schema."""
    buf = bytearray()
    # Field 1: uint64 id (tag = 1, wire_type = 0 -> 0x08)
    buf.append(0x08)
    buf.extend(_encode_varint(node_dict["id"]))

    # Field 2: string name (tag = 2, wire_type = 2 -> 0x12)
    name_bytes = node_dict["name"].encode("utf-8")
    buf.append(0x12)
    buf.extend(_encode_varint(len(name_bytes)))
    buf.extend(name_bytes)

    # Field 3: enum type (tag = 3, wire_type = 0 -> 0x18)
    buf.append(0x18)
    buf.extend(_encode_varint(node_dict["type"]))

    # Field 4: repeated uint64 data_deps (tag = 4, wire_type = 0 -> 0x20)
    for dep in node_dict.get("data_deps", []):
        buf.append(0x20)
        buf.extend(_encode_varint(dep))

    # Field 5: uint64 duration_us (tag = 5, wire_type = 0 -> 0x28)
    buf.append(0x28)
    buf.extend(_encode_varint(node_dict.get("duration_us", 10)))

    return bytes(buf)


def save_chakra_trace(trace_nodes: List[dict], out_dir: Path, filename_prefix: str = "llama7b", spec: Dict[str, Any] | None = None) -> dict:
    """Save Chakra Execution Trace as .et.json and binary .et Protobuf trace."""
    out_dir.mkdir(parents=True, exist_ok=True)
    json_path = out_dir / f"{filename_prefix}.et.json"
    et_path = out_dir / f"{filename_prefix}.et"

    payload = {
        "chakra_et_version": "0.0.4",
        "workload_spec": spec or {},
        "nodes": trace_nodes,
    }
    json_path.write_text(json.dumps(payload, indent=2))

    # Binary Protobuf length-delimited record serialization
    binary_buf = bytearray()
    for node in trace_nodes:
        pb_node = encode_chakra_node_protobuf(node)
        binary_buf.extend(_encode_varint(len(pb_node)))
        binary_buf.extend(pb_node)

    et_path.write_bytes(bytes(binary_buf))

    return {
        "et_json": str(json_path),
        "et_binary": str(et_path),
        "total_nodes": len(trace_nodes),
        "binary_bytes": len(binary_buf),
    }


def _selfcheck():
    gen = ChakraTraceGenerator()
    spec = gen.resolve_spec("llama7b", num_layers=2)
    nodes = gen.build_model_trace(spec)
    assert len(nodes) >= 8, f"Expected at least 8 nodes for 2 layers, got {len(nodes)}"
    assert nodes[0]["type"] == COMP_NODE
    assert nodes[1]["type"] == COMM_COLL_NODE
    assert nodes[1]["data_deps"] == [nodes[0]["id"]]

    # Test LLaMA-70B preset resolution
    spec70b = gen.resolve_spec("llama70b")
    assert spec70b["hidden_size"] == 8192
    assert spec70b["total_allreduce_calls"] == 160

    print("selfcheck OK")


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--model", default="llama7b", help="Model preset (llama7b, llama13b, llama70b, gpt3, resnet50, all_reduce, all_to_all) or custom")
    ap.add_argument("--hidden-size", type=int, default=None, help="Override hidden size H")
    ap.add_argument("--ffn-size", type=int, default=None, help="Override FFN size H_ffn")
    ap.add_argument("--num-layers", type=int, default=None, help="Override number of layers L")
    ap.add_argument("--seq-len", type=int, default=None, help="Override sequence length S")
    ap.add_argument("--batch-size", type=int, default=None, help="Override batch size B")
    ap.add_argument("--tp", type=int, default=None, help="Tensor parallelism degree")
    ap.add_argument("--pp", type=int, default=None, help="Pipeline parallelism degree")
    ap.add_argument("--out-dir", default=None, help="Output directory for generated Chakra ET files")
    ap.add_argument("--selfcheck", action="store_true", help="Run internal regression selfcheck")
    args = ap.parse_args()

    if args.selfcheck:
        _selfcheck()
        return

    out_dir = Path(args.out_dir) if args.out_dir else RESULTS_DIR / "chakra_traces"
    gen = ChakraTraceGenerator()

    model_key = args.model.lower()
    if model_key in ("all_reduce", "all_to_all", "reduce_scatter", "all_gather"):
        nodes = gen.build_collective_trace(comm_type=model_key.upper())
        res = save_chakra_trace(nodes, out_dir, model_key)
    else:
        spec = gen.resolve_spec(
            model_key,
            hidden_size=args.hidden_size,
            ffn_size=args.ffn_size,
            num_layers=args.num_layers,
            seq_len=args.seq_len,
            batch_size=args.batch_size,
            tp_degree=args.tp,
            pp_degree=args.pp,
        )
        nodes = gen.build_model_trace(spec)
        res = save_chakra_trace(nodes, out_dir, model_key, spec=spec)

    print(f"  ✓ Generated Chakra ET ({res['total_nodes']} DAG nodes for {args.model}) → {res['et_json']}")


if __name__ == "__main__":
    main()

