#!/usr/bin/env python3
"""Map every statically shaped ONNX MatMul/Gemm signature through Timeloop.

Weights are not loaded. Each batched MatMul is mapped as one matrix instance;
its batch count is retained separately, not converted to latency.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
from pathlib import Path
import re
import subprocess
import sys

from gr00t_pipeline import require_timeloop_precision

ROOT = Path(__file__).resolve().parents[3]
MODEL_DIR = ROOT / 'runs/gr00t-model/staticpick-v1-source'
PRECISION_BITS = {'float': 32, 'float16': 16, 'double': 64, 'bfloat16': 16}


def digest(path):
    h = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for block in iter(lambda: stream.read(1 << 20), b''):
            h.update(block)
    return h.hexdigest()


def _static(shape):
    return (isinstance(shape, list) and all(type(d) is int and d > 0 for d in shape))


def _broadcast(a, b):
    width = max(len(a), len(b))
    a = [1] * (width - len(a)) + a
    b = [1] * (width - len(b)) + b
    result = []
    for x, y in zip(a, b):
        if x != y and x != 1 and y != 1:
            raise ValueError(f'Incompatible MatMul batch dimensions: {a} and {b}')
        result.append(max(x, y))
    return result


def matrix_problem(node):
    """Return one Timeloop matrix problem or a precise non-mappable reason."""
    if node.get('op_type') not in ('MatMul', 'Gemm'):
        return None, 'unsupported_operator'
    inputs, outputs = node.get('inputs', []), node.get('outputs', [])
    if len(inputs) < 2 or len(outputs) != 1:
        return None, 'unsupported_tensor_arity'
    a, b, y = inputs[0], inputs[1], outputs[0]
    if not all(_static(t.get('shape')) for t in (a, b, y)):
        return None, 'unresolved_shape'
    dtype = a.get('dtype')
    if dtype not in PRECISION_BITS or b.get('dtype') != dtype or y.get('dtype') != dtype:
        return None, 'unsupported_or_mismatched_dtype'
    ashape, bshape, yshape = a['shape'], b['shape'], y['shape']
    if node['op_type'] == 'Gemm':
        if len(ashape) != 2 or len(bshape) != 2 or len(yshape) != 2:
            return None, 'unsupported_gemm_rank'
        attrs = node.get('attributes', {})
        if attrs.get('transA', 0) not in (0, 1) or attrs.get('transB', 0) not in (0, 1):
            return None, 'unsupported_gemm_transpose'
        m, k = (ashape[1], ashape[0]) if attrs.get('transA', 0) else (ashape[0], ashape[1])
        bk, n = (bshape[1], bshape[0]) if attrs.get('transB', 0) else (bshape[0], bshape[1])
        if k != bk or yshape != [m, n]:
            return None, 'gemm_dimensions_do_not_reconcile'
        batches = 1
    else:
        # ONNX promotes a 1-D left input to [1,K], and a 1-D right
        # input to [K,1], then removes the promoted output dimensions.
        aa = [1, *ashape] if len(ashape) == 1 else ashape
        bb = [*bshape, 1] if len(bshape) == 1 else bshape
        if len(aa) < 2 or len(bb) < 2 or aa[-1] != bb[-2]:
            return None, 'matmul_dimensions_do_not_reconcile'
        batch = _broadcast(aa[:-2], bb[:-2])
        m, k, n = aa[-2], aa[-1], bb[-1]
        expected = [*batch, m, n]
        if len(ashape) == 1:
            expected.pop(-2)
        if len(bshape) == 1:
            expected.pop(-1)
        if yshape != expected:
            return None, 'matmul_output_does_not_reconcile'
        batches = math.prod(batch) if batch else 1
    return {'M': m, 'N': n, 'K': k, 'dtype': dtype,
            'precision_bits': PRECISION_BITS[dtype], 'batch_count': batches}, None


def collect_signatures(graphs):
    signatures, graph_rows = {}, {}
    for graph_name, graph in sorted(graphs.items()):
        node_rows = {}
        for node in graph['operators']:
            problem, reason = matrix_problem(node)
            if problem is None:
                status = reason if reason != 'unsupported_operator' else f"unsupported_operator:{node['op_type']}"
                node_rows[node['id']] = {'status': status}
                continue
            key = (problem['M'], problem['N'], problem['K'], problem['precision_bits'])
            signature = 'gemm-' + hashlib.sha256(','.join(map(str, key)).encode()).hexdigest()[:16]
            entry = signatures.setdefault(signature, {'M': problem['M'], 'N': problem['N'],
                'K': problem['K'], 'precision_bits': problem['precision_bits'],
                'dtype': problem['dtype'], 'nodes': []})
            entry['nodes'].append({'graph': graph_name, 'node_id': node['id'],
                                   'batch_count': problem['batch_count'],
                                   'op_type': node['op_type']})
            node_rows[node['id']] = {'status': 'pending', 'signature_id': signature,
                                     'batch_count': problem['batch_count']}
        graph_rows[graph_name] = node_rows
    return signatures, graph_rows


def _mapping_config(signature, arch_text):
    bits = signature['precision_bits']
    if arch_text.count('word-bits: 8') != 4:
        raise ValueError('unexpected base Timeloop arithmetic/storage precision fields')
    arch = arch_text.replace('word-bits: 8', f'word-bits: {bits}')
    return arch + f'''\nproblem:
  shape:
    name: gemm
    dimensions: [ M, N, K ]
    data-spaces:
      - name: Inputs
        projection: [ [[M]], [[K]] ]
      - name: Weights
        projection: [ [[K]], [[N]] ]
      - name: Outputs
        projection: [ [[M]], [[N]] ]
        read-write: True
  instance:
    M: {signature['M']}
    N: {signature['N']}
    K: {signature['K']}
mapper:
  algorithm: exhaustive
  optimization-metrics: [delay]
  num-threads: 1
  search-size: 16
  victory-condition: 4
  timeout: 16
'''


def run(graphs_path, output, *, timeloop, timeout):
    graph_data = json.loads(Path(graphs_path).read_text())
    out = Path(output).resolve()
    if any(char.isspace() for char in str(out)):
        raise ValueError('output path must not contain whitespace')
    out.mkdir(parents=True, exist_ok=False)
    inventory_path = out / 'source-graph-inventory.json'
    inventory_path.write_text(Path(graphs_path).read_text())
    signatures, graph_rows = collect_signatures(graph_data)
    arch_text = (ROOT / 'third_party/timeloop/arch.yaml').read_text()
    binary = Path(timeloop).resolve()
    env = dict(os.environ)
    env['LD_LIBRARY_PATH'] = str(binary.parent.parent / 'lib') + os.pathsep + env.get('LD_LIBRARY_PATH', '')
    signature_results = {}
    for signature_id, signature in sorted(signatures.items()):
        directory = out / signature_id
        directory.mkdir()
        config_path = directory / 'mapping.yaml'
        config_path.write_text(_mapping_config(signature, arch_text))
        result = subprocess.run([str(binary), str(config_path)], cwd=directory, env=env,
                                timeout=timeout, stdin=subprocess.DEVNULL,
                                capture_output=True, text=True)
        (directory / 'timeloop.stdout').write_text(result.stdout)
        (directory / 'timeloop.stderr').write_text(result.stderr)
        stats = directory / 'timeloop-mapper.stats.txt'
        if result.returncode or not stats.is_file():
            raise RuntimeError(f'Timeloop failed for {signature_id}: {result.stderr[-1000:]}')
        stats_text = stats.read_text()
        widths = require_timeloop_precision(stats_text, signature['precision_bits'])
        computes = re.search(r'^Actual Computes = (\d+)$', stats_text, re.M)
        cycles = re.search(r'^Cycles: (\d+)$', stats_text, re.M)
        expected = signature['M'] * signature['N'] * signature['K']
        if not computes or int(computes.group(1)) != expected or not cycles:
            raise ValueError(f'Timeloop compute count does not match {signature_id}')
        signature_results[signature_id] = {**signature, 'resolved_word_bits': widths,
            'single_matrix_actual_computes': int(computes.group(1)),
            'single_matrix_modeled_cycles': int(cycles.group(1)),
            'config_sha256': digest(config_path), 'stats_sha256': digest(stats),
            'nodes': signature['nodes']}
        for item in signature['nodes']:
            graph_rows[item['graph']][item['node_id']].update({
                'status': 'mapped', 'M': signature['M'], 'N': signature['N'],
                'K': signature['K'], 'precision_bits': signature['precision_bits'],
                'single_matrix_actual_computes': expected,
                'single_matrix_modeled_cycles': int(cycles.group(1))})
    graph_results = {}
    total_nodes = mapped_nodes = 0
    for graph_name, graph in sorted(graph_data.items()):
        rows = graph_rows[graph_name]
        counts = {}
        for row in rows.values():
            counts[row['status']] = counts.get(row['status'], 0) + 1
        total_nodes += graph['node_count']
        mapped_nodes += counts.get('mapped', 0)
        graph_results[graph_name] = {'onnx_sha256': graph['onnx_sha256'],
            'node_count': graph['node_count'], 'mapped_node_count': counts.get('mapped', 0),
            'status_counts': counts, 'nodes': rows}
    result = {'schema': 'veritx/gr00t-full-static-mapping/1',
        'qualification': 'STATIC_SHAPE_MATMUL_GEMM_SIGNATURES_ONLY',
        'source_inventory_sha256': digest(inventory_path),
        'reproduction': {'tool_sha256': digest(__file__), 'timeloop_binary_sha256': digest(binary),
            'architecture_sha256': digest(ROOT / 'third_party/timeloop/arch.yaml'),
            'source_inventory': inventory_path.name,
            'command': 'python3 tracks/t3-topology/tools/gr00t_full_mapping.py --graphs-json <source-graph-inventory.json> --output <new-directory>'},
        'model_graphs': graph_results, 'signatures': signature_results,
        'coverage': {'graph_nodes': total_nodes, 'mapped_nodes': mapped_nodes,
            'unique_static_signatures': len(signatures),
            'matrix_nodes': sum(len(sig['nodes']) for sig in signatures.values()),
            'claim': 'Timeloop maps one matrix instance per unique signature; batch counts and per-node cycles remain separate; no full-model schedule or latency.'},
        'limitations': ['Only statically shaped MatMul/Gemm nodes are mapped.',
            'Dynamic-shape and all non-MatMul/Gemm nodes remain explicitly unmodeled.',
            'Gemm bias epilogues and other elementwise operators are not represented.',
            'Weights are not numerically loaded; work is derived from pinned ONNX shapes.',
            'The authored 16-PE Timeloop template is not calibrated to target hardware.',
            'Timeloop per-matrix cycles are not summed into a model latency.']}
    (out / 'result.json').write_text(json.dumps(result, sort_keys=True, indent=2, allow_nan=False) + '\n')
    print(json.dumps(result['coverage'], sort_keys=True))
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--graphs-json', type=Path, required=True,
                        help='JSON stdout from gr00t_onnx_graph.py')
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--timeloop', type=Path,
                        default=Path('/tmp/srota-timeloop-build.yAXlOe/build/timeloop-mapper'))
    parser.add_argument('--timeout', type=int, default=60)
    args = parser.parse_args()
    run(args.graphs_json, args.output, timeloop=args.timeloop, timeout=args.timeout)


if __name__ == '__main__':
    main()
