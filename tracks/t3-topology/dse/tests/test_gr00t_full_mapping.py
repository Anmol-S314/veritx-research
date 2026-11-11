import sys
from pathlib import Path

TOOLS = Path(__file__).resolve().parents[2] / 'tools'
sys.path.insert(0, str(TOOLS))
from gr00t_full_mapping import collect_signatures, matrix_problem


def tensor(name, shape, dtype='float'):
    return {'name': name, 'shape': shape, 'dtype': dtype}


def node(op, a, b, y, attrs=None):
    return {'id': op + ':0', 'op_type': op, 'inputs': [a, b], 'outputs': [y],
            'attributes': attrs or {}}


def test_batched_matmul_maps_one_matrix_and_preserves_batch_count():
    op = node('MatMul', tensor('a', [1, 32, 41, 41]), tensor('b', [1, 32, 41, 48]),
              tensor('y', [1, 32, 41, 48]))
    assert matrix_problem(op) == ({'M': 41, 'N': 48, 'K': 41, 'dtype': 'float',
                                   'precision_bits': 32, 'batch_count': 32}, None)


def test_gemm_transposed_weight_shape_is_interpreted_from_onnx_attributes():
    op = node('Gemm', tensor('a', [1, 256]), tensor('b', [1536, 256]),
              tensor('y', [1, 1536]), {'transB': 1})
    problem, reason = matrix_problem(op)
    assert reason is None
    assert problem == {'M': 1, 'N': 1536, 'K': 256, 'dtype': 'float',
                       'precision_bits': 32, 'batch_count': 1}


def test_dynamic_shapes_and_mismatches_fail_closed():
    op = node('Gemm', tensor('a', [None, 256]), tensor('b', [1536, 256]),
              tensor('y', [None, 1536]), {'transB': 1})
    assert matrix_problem(op) == (None, 'unresolved_shape')
    wrong = node('MatMul', tensor('a', [2, 4]), tensor('b', [3, 5]), tensor('y', [2, 5]))
    assert matrix_problem(wrong) == (None, 'matmul_dimensions_do_not_reconcile')


def test_signature_inventory_deduplicates_shapes_but_keeps_each_node():
    a = node('MatMul', tensor('a', [2, 4]), tensor('b', [4, 5]), tensor('y', [2, 5]))
    b = node('Gemm', tensor('x', [2, 4]), tensor('w', [4, 5]), tensor('z', [2, 5]))
    b['id'] = 'Gemm:1'
    graphs = {'g': {'node_count': 3, 'onnx_sha256': 'a' * 64,
                    'operators': [a, b, {'id': 'Add:2', 'op_type': 'Add', 'inputs': [],
                                         'outputs': [], 'attributes': {}}]}}
    signatures, rows = collect_signatures(graphs)
    assert len(signatures) == 1
    assert len(next(iter(signatures.values()))['nodes']) == 2
    assert rows['g']['MatMul:0']['signature_id'] == rows['g']['Gemm:1']['signature_id']
    assert rows['g']['Add:2']['status'] == 'unsupported_operator:Add'
