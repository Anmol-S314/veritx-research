#!/usr/bin/env python3
"""Emit ONNX-derived static node/shape metadata without external weights."""
import collections
import hashlib
import json
from pathlib import Path
import re
import sys

import onnx


def sha(path):
    h = hashlib.sha256()
    with open(path, 'rb') as source:
        for block in iter(lambda: source.read(1024 * 1024), b''):
            h.update(block)
    return h.hexdigest()


def tensor_info(values, name):
    value = values.get(name)
    if value is None:
        return {'name': name, 'shape': None, 'dtype': None}
    if hasattr(value, 'dims'):
        dims, elem_type = list(value.dims), value.data_type
    elif value.type.HasField('tensor_type'):
        tensor = value.type.tensor_type
        dims = [int(d.dim_value) if d.dim_value else None for d in tensor.shape.dim]
        elem_type = tensor.elem_type
    else:
        return {'name': name, 'shape': None, 'dtype': None}
    return {'name': name, 'shape': dims,
            'dtype': onnx.TensorProto.DataType.Name(elem_type).lower() if elem_type else None}


def attribute_value(value):
    if isinstance(value, onnx.TensorProto):
        return {'tensor_dtype': onnx.TensorProto.DataType.Name(value.data_type).lower(),
                'tensor_shape': list(value.dims)}
    if isinstance(value, onnx.SparseTensorProto):
        return {'sparse_tensor_dtype': onnx.TensorProto.DataType.Name(value.values.data_type).lower(),
                'sparse_tensor_shape': list(value.dims)}
    if isinstance(value, bytes):
        return value.decode('utf-8', errors='replace')
    if hasattr(value, 'item'):
        return value.item()
    if hasattr(value, 'tolist'):
        return value.tolist()
    if isinstance(value, (list, tuple)):
        return [attribute_value(item) for item in value]
    return value


def main(directory):
    directory = Path(directory)
    graph_config = (directory / 'graph.yaml').read_text()
    declared = dict(re.findall(r'model_path:\s*([\w.-]+)\s+md5sum:.*?sha256sum:\s*([0-9a-f]{64})', graph_config, re.S))
    graphs = {}
    for path in sorted(directory.glob('*.onnx')):
        digest = sha(path)
        if declared.get(path.name) != digest:
            raise ValueError(f'{path.name}: graph.yaml SHA-256 does not match ONNX artifact')
        model = onnx.load_model(str(path), load_external_data=False)
        model = onnx.shape_inference.infer_shapes(model, strict_mode=False, data_prop=False)
        values = {v.name: v for v in (*model.graph.input, *model.graph.value_info, *model.graph.output)}
        values.update({i.name: i for i in model.graph.initializer})
        nodes = []
        for index, node in enumerate(model.graph.node):
            nodes.append({'id': f'{path.stem}:{index}', 'op_type': node.op_type,
                          'inputs': [tensor_info(values, name) for name in node.input if name],
                          'outputs': [tensor_info(values, name) for name in node.output if name],
                          'attributes': {attr.name: attribute_value(onnx.helper.get_attribute_value(attr))
                                         for attr in node.attribute}})
        graphs[path.stem] = {
            'onnx_sha256': digest,
            'external_weight_sidecar_present': path.with_suffix(path.suffix + '.data').is_file(),
            'operator_counts': dict(sorted(collections.Counter(node['op_type'] for node in nodes).items())),
            'timeloop_mapped_node_count': 0,
            'timeloop_status': 'architecture_only_not_mapped',
            'opset': max((op.version for op in model.opset_import), default=None),
            'inputs': [tensor_info(values, v.name) for v in model.graph.input],
            'outputs': [tensor_info(values, v.name) for v in model.graph.output],
            'node_count': len(nodes),
            'external_initializers': sum(i.data_location == onnx.TensorProto.EXTERNAL for i in model.graph.initializer),
            'operators': nodes,
        }
    print(json.dumps(graphs, sort_keys=True, separators=(',', ':')))


if __name__ == '__main__':
    main(sys.argv[1])
