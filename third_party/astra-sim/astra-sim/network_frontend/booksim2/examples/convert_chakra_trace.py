#!/usr/bin/env python3
"""
Convert LLMServingSim COLOCATED Chakra traces to ASTRA-sim feeder_v3 format.

LLMServingSim uses a different encoding than the Chakra v3 proto ASTRA-sim expects:
  - Node types are off by 1 (type 5 = COMP, type 8 = COMM_COLL)
  - Attributes like comm_type, comm_size, tensor_size are MISSING from field 10
  - Runtime is in field 7 (duration_micros) which ASTRA-sim reads correctly
  - Collective info is encoded in node NAMES, not in protobuf attributes

This converter:
  1. Remaps node types (5->4 COMP, 8->7 COMM_COLL)
  2. Adds missing attributes to each Node's field 10 (repeated AttributeProto):
     - COMP_NODEs:  runtime (from duration_micros), tensor_size, num_ops
     - COMM_COLL:   comm_type (parsed from name), comm_size, involved_dim
     - MEM_LOAD/STORE: tensor_size
  3. Reconstructs the file in the same [varint32 length][protobuf] framing

Usage:
    python3 convert_chakra_trace.py input.et output.et
    python3 convert_chakra_trace.py --in-place file.et
    python3 convert_chakra_trace.py --dry-run file.et
"""

import argparse
import os
import sys

# LLMServingSim type -> ASTRA-sim type
TYPE_MAP = {
    5: 4,   # COMP_NODE
    8: 7,   # COMM_COLL_NODE
}

# Collective name patterns -> ChakraCollectiveCommType enum values
# ORDER MATTERS: longer patterns must come before shorter ones
COLLECTIVE_TYPE_MAP = [
    ("REDUCESCATTER",  7),
    ("REDUCE_SCATTER", 7),
    ("ALLREDUCE",      0),
    ("ALL_TO_ALL",     6),
    ("ALLTOALL",       6),
    ("ALLGATHER",      2),
    ("REDUCE",         1),
    ("GATHER",         3),
    ("SCATTER",        4),
    ("BROADCAST",      5),
    ("BARRIER",        9),
]

# Default sizes (bytes) for different collective types
# These are reasonable defaults for Qwen3-30B-A3B with TP=2
DEFAULT_COMM_SIZES = {
    0:  8192,   # ALLREDUCE: hidden_size(4096) * element_size(2) * TP(2)
    2:  4096,   # ALLGATHER: chunk_size
    6:  8192,   # ALL_TO_ALL: full hidden_size
    7:  4096,   # REDUCE_SCATTER: chunk_size
}

DEFAULT_TENSOR_SIZE = 8192   # bytes
DEFAULT_NUM_OPS = 8388608    # ~8M FLOPs (typical for a projection layer)


def read_varint(data, offset):
    """Read a protobuf varint. Returns (value, new_offset)."""
    result = 0
    shift = 0
    while offset < len(data):
        b = data[offset]
        offset += 1
        result |= (b & 0x7F) << shift
        shift += 7
        if not (b & 0x80):
            break
    return result, offset


def write_varint(value):
    """Encode an integer as a protobuf varint."""
    parts = []
    while value > 0x7F:
        parts.append((value & 0x7F) | 0x80)
        value >>= 7
    parts.append(value & 0x7F)
    return bytes(parts)


def make_attribute_proto_uint64(name, value):
    """Build a serialized AttributeProto with a uint64 value (field 13)."""
    # field 1 (name): wire type 2 (length-delimited)
    name_bytes = name.encode('utf-8')
    tag_name = bytes([0x0a])  # (1 << 3) | 2 = 10 = 0x0a
    # field 13 (uint64_val): wire type 0 (varint)
    tag_val = bytes([0x68])  # (13 << 3) | 0 = 104 = 0x68
    val_bytes = write_varint(value)

    msg = tag_name + write_varint(len(name_bytes)) + name_bytes + tag_val + val_bytes
    return msg


def make_attribute_proto_bool_list(name, bools):
    """Build a serialized AttributeProto with a BoolList value (field 28)."""
    name_bytes = name.encode('utf-8')
    tag_name = bytes([0x0a])

    # BoolList message: field 1 (repeated bool values), wire type 0
    inner = b''
    for b in bools:
        inner += bytes([0x08])  # field 1, wire type 0
        inner += write_varint(1 if b else 0)

    # field 28 (bool_list): wire type 2
    # 28 << 3 | 2 = 226 = 0xe2 0x01 (varint encoded)
    tag_list = bytes([0xe2, 0x01])

    msg = tag_name + write_varint(len(name_bytes)) + name_bytes + tag_list + write_varint(len(inner)) + inner
    return msg


def parse_collective_type(name):
    """Parse collective type from node name like COMM_COLL_NODE_o_proj_6_ALLREDUCE."""
    name_upper = name.upper()
    for pattern, val in COLLECTIVE_TYPE_MAP:
        if pattern in name_upper:
            return val
    return 0  # default ALL_REDUCE


def build_extra_attrs(node_type_original, node_name, duration_micros):
    """Build extra AttributeProto messages to add to a Node's field 10."""
    attrs = []

    if node_type_original == 5:  # COMP_NODE
        # runtime attribute (in microseconds)
        attrs.append(make_attribute_proto_uint64("runtime", duration_micros))
        # tensor_size (synthetic)
        attrs.append(make_attribute_proto_uint64("tensor_size", DEFAULT_TENSOR_SIZE))
        # num_ops (synthetic)
        attrs.append(make_attribute_proto_uint64("num_ops", DEFAULT_NUM_OPS))

    elif node_type_original == 8:  # COMM_COLL_NODE
        # comm_type parsed from name
        ct = parse_collective_type(node_name)
        attrs.append(make_attribute_proto_uint64("comm_type", ct))
        # comm_size (synthetic based on collective type)
        cs = DEFAULT_COMM_SIZES.get(ct, 8192)
        attrs.append(make_attribute_proto_uint64("comm_size", cs))
        # involved_dim (all true for 5-D)
        attrs.append(make_attribute_proto_bool_list("involved_dim", [True, True, True, True]))

    elif node_type_original in (2, 3):  # MEM_LOAD / MEM_STORE
        # tensor_size from duration if available, else default
        ts = duration_micros if duration_micros > 0 else DEFAULT_TENSOR_SIZE
        attrs.append(make_attribute_proto_uint64("tensor_size", ts))

    return attrs


def fix_node(node_bytes, is_metadata=False):
    """
    Fix a Node protobuf message:
      - Remap type field
      - Add missing attributes to field 10
    Returns (fixed_bytes, node_type_original, node_name, duration_micros).
    """
    # First pass: parse all fields to extract type, name, duration_micros
    inner = 0
    fields = {}
    field10_offset = None
    field10_end = None
    field10_replaced = False

    while inner < len(node_bytes):
        tag, tag_end = read_varint(node_bytes, inner)
        fn = tag >> 3
        wt = tag & 7

        if wt == 0:  # varint
            val, val_end = read_varint(node_bytes, tag_end)
            if fn not in fields:
                fields[fn] = val
            inner = val_end
        elif wt == 2:  # length-delimited
            slen, content_end = read_varint(node_bytes, tag_end)
            sdata = node_bytes[content_end:content_end + slen]
            if fn not in fields:
                fields[fn] = sdata
            if fn == 10:
                field10_offset = inner
                field10_end = content_end + slen
            inner = content_end + slen
        elif wt == 1:  # 64-bit
            inner = tag_end + 8
        elif wt == 5:  # 32-bit
            inner = tag_end + 4
        else:
            break

    node_type_original = fields.get(3, 0)
    node_name = ""
    if 2 in fields and isinstance(fields[2], bytes):
        try:
            node_name = fields[2].decode('utf-8')
        except:
            pass
    duration_micros = fields.get(7, 0)

    if is_metadata or node_type_original not in TYPE_MAP:
        return node_bytes, node_type_original, node_name, duration_micros

    # Build extra attributes
    extra_attrs = build_extra_attrs(node_type_original, node_name, duration_micros)
    if not extra_attrs:
        # Still need to fix the type
        pass

    # Reconstruct the message
    result = bytearray()
    inner = 0
    type_fixed = False

    while inner < len(node_bytes):
        tag, tag_end = read_varint(node_bytes, inner)
        fn = tag >> 3
        wt = tag & 7

        if wt == 0:  # varint
            val, val_end = read_varint(node_bytes, tag_end)
            if fn == 3 and node_type_original in TYPE_MAP:
                # Fix type
                new_type = TYPE_MAP[node_type_original]
                result.extend(node_bytes[inner:tag_end])
                result.extend(write_varint(new_type))
                type_fixed = True
                inner = val_end
            else:
                result.extend(node_bytes[inner:val_end])
                inner = val_end
        elif wt == 2:  # length-delimited
            slen, content_end = read_varint(node_bytes, tag_end)
            if fn == 10 and extra_attrs and not field10_replaced:
                # Field 10 (repeated AttributeProto): replace FIRST entry only
                field10_replaced = True
                for attr_msg in extra_attrs:
                    result.extend(bytes([0x52]))  # field 10, wire type 2
                    result.extend(write_varint(len(attr_msg)))
                    result.extend(attr_msg)
                inner = content_end + slen
            elif fn == 10:
                # Skip all other field 10 entries (they're duplicates)
                inner = content_end + slen
            else:
                result.extend(node_bytes[inner:content_end + slen])
                inner = content_end + slen
        elif wt == 1:  # 64-bit
            result.extend(node_bytes[inner:tag_end + 8])
            inner = tag_end + 8
        elif wt == 5:  # 32-bit
            result.extend(node_bytes[inner:tag_end + 4])
            inner = tag_end + 4
        else:
            result.extend(node_bytes[inner:])
            inner = len(node_bytes)

    # If no field 10 existed, add one with extra attributes
    if field10_offset is None and extra_attrs:
        # field 10 tag: (10 << 3) | 2 = 82 = 0x52
        for attr_msg in extra_attrs:
            result.extend(bytes([0x52]))
            result.extend(write_varint(len(attr_msg)))
            result.extend(attr_msg)

    return bytes(result), node_type_original, node_name, duration_micros


def convert_trace(input_path, output_path):
    """Convert a Chakra trace file, fixing types and adding attributes."""
    with open(input_path, "rb") as f:
        data = f.read()

    offset = 0
    messages = []
    node_count = 0
    stats = {"comp": 0, "comm_coll": 0, "mem": 0, "other": 0}

    while offset < len(data):
        size, new_offset = read_varint(data, offset)
        if new_offset + size > len(data):
            messages.append(data[offset:])
            break

        msg_bytes = data[new_offset:new_offset + size]
        offset = new_offset + size
        node_count += 1

        if node_count == 1:
            # GlobalMetadata — pass through unchanged
            messages.append(msg_bytes)
            continue

        # Fix node
        fixed, ntype, nname, dur = fix_node(msg_bytes)
        messages.append(fixed)

        if ntype == 5:
            stats["comp"] += 1
        elif ntype == 8:
            stats["comm_coll"] += 1
        elif ntype in (2, 3):
            stats["mem"] += 1
        else:
            stats["other"] += 1

    # Reconstruct file
    with open(output_path, "wb") as f:
        for msg in messages:
            f.write(write_varint(len(msg)))
            f.write(msg)

    print(f"Converted: {input_path} -> {output_path}")
    print(f"  Nodes: {node_count - 1} "
          f"(COMP={stats['comp']}, COMM_COLL={stats['comm_coll']}, "
          f"MEM={stats['mem']}, other={stats['other']})")
    return stats


def dry_run(input_path):
    """Show what would be changed without writing."""
    with open(input_path, "rb") as f:
        data = f.read()

    offset = 0
    node_count = 0
    stats = {"comp": 0, "comm_coll": 0, "mem": 0, "other": 0}

    while offset < len(data):
        size, new_offset = read_varint(data, offset)
        if new_offset + size > len(data):
            break

        msg_bytes = data[new_offset:new_offset + size]
        offset = new_offset + size
        node_count += 1

        if node_count == 1:
            continue

        # Parse to get type and name
        inner = 0
        fields = {}
        while inner < len(msg_bytes):
            tag, tag_end = read_varint(msg_bytes, inner)
            fn = tag >> 3; wt = tag & 7
            if wt == 0:
                val, val_end = read_varint(msg_bytes, tag_end)
                if fn not in fields:
                    fields[fn] = val
                inner = val_end
            elif wt == 2:
                slen, content_end = read_varint(msg_bytes, tag_end)
                sdata = msg_bytes[content_end:content_end + slen]
                if fn not in fields:
                    fields[fn] = sdata
                inner = content_end + slen
            else:
                inner = len(msg_bytes)

        ntype = fields.get(3, 0)
        name = ""
        if 2 in fields and isinstance(fields[2], bytes):
            try: name = fields[2].decode('utf-8')
            except: pass

        if ntype in TYPE_MAP:
            new_type = TYPE_MAP[ntype]
            type_name = {4: "COMP", 7: "COMM_COLL"}.get(new_type, f"type_{new_type}")
            old_name = {5: "COMP", 8: "COMM_COLL"}.get(ntype, f"type_{ntype}")
            print(f"  Node {node_count}: type {ntype} ({old_name}) -> {new_type} ({type_name})  name={name[:60]}")

            # Show what attributes will be added
            if ntype == 5:
                attrs_added = "runtime, tensor_size, num_ops"
                stats["comp"] += 1
            elif ntype == 8:
                ct = parse_collective_type(name)
                ct_name = {0: "ALLREDUCE", 1: "REDUCE", 2: "ALLGATHER", 6: "ALL_TO_ALL", 7: "REDUCE_SCATTER"}.get(ct, f"TYPE_{ct}")
                cs = DEFAULT_COMM_SIZES.get(ct, 8192)
                attrs_added = f"comm_type={ct}({ct_name}), comm_size={cs}, involved_dim=[T,T,T,T]"
                stats["comm_coll"] += 1
            else:
                attrs_added = ""
                stats["other"] += 1
            if attrs_added:
                print(f"    + attrs: {attrs_added}")
        else:
            stats["other"] += 1

    print(f"\nDry run: {node_count - 1} nodes")
    print(f"  COMP={stats['comp']}, COMM_COLL={stats['comm_coll']}, other={stats['other']}")


def main():
    parser = argparse.ArgumentParser(
        description="Convert LLMServingSim Chakra traces to ASTRA-sim feeder_v3 format"
    )
    parser.add_argument("input", help="Input .et trace file")
    parser.add_argument("output", nargs="?",
                        help="Output .et file (default: <input>.converted.et)")
    parser.add_argument("--in-place", action="store_true",
                        help="Overwrite the input file")
    parser.add_argument("--dry-run", action="store_true",
                        help="Show what would be changed without writing")
    args = parser.parse_args()

    if args.dry_run:
        dry_run(args.input)
        return

    if args.in_place:
        import tempfile
        tmp_fd, tmp_path = tempfile.mkstemp(suffix=".et",
                                             dir=os.path.dirname(args.input))
        os.close(tmp_fd)
        try:
            convert_trace(args.input, tmp_path)
            os.replace(tmp_path, args.input)
        except Exception:
            os.unlink(tmp_path)
            raise
    else:
        output = args.output or args.input.replace(".et", ".converted.et")
        convert_trace(args.input, output)


if __name__ == "__main__":
    main()
