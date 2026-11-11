import sys
from pathlib import Path

TOOLS = Path(__file__).resolve().parents[2] / 'tools'
sys.path.insert(0, str(TOOLS))

from gr00t_model_trace import (GROUPS, project_named_state, attach_verified_roi,
                               attach_verified_full_mapping, attach_verified_topology_sweep,
                               attach_verified_srota_pair)


def test_full_mapping_binds_verified_stats_to_each_source_node(tmp_path):
    import hashlib
    import json
    signature = 'gemm-test'
    run = tmp_path / signature
    run.mkdir()
    (run / 'mapping.yaml').write_text('config')
    stats = '\n'.join(['Word bits : 32', 'Data word bits : 32',
                       'Data word bits : 32', 'Data word bits : 32',
                       'Actual Computes = 1', 'Cycles: 1']) + '\n'
    (run / 'timeloop-mapper.stats.txt').write_text(stats)
    sha = lambda p: hashlib.sha256(p.read_bytes()).hexdigest()
    node = {'id': 'g:0', 'op_type': 'MatMul',
            'inputs': [{'name': 'a', 'shape': [1, 1], 'dtype': 'float'},
                       {'name': 'b', 'shape': [1, 1], 'dtype': 'float'}],
            'outputs': [{'name': 'y', 'shape': [1, 1], 'dtype': 'float'}], 'attributes': {}}
    result = {'schema': 'veritx/gr00t-full-static-mapping/1',
        'qualification': 'STATIC_SHAPE_MATMUL_GEMM_SIGNATURES_ONLY',
        'source_inventory_sha256': 'b' * 64,
        'model_graphs': {'g': {'onnx_sha256': 'a' * 64, 'node_count': 1,
            'mapped_node_count': 1, 'status_counts': {'mapped': 1},
            'nodes': {'g:0': {'status': 'mapped', 'signature_id': signature,
                'batch_count': 1, 'single_matrix_actual_computes': 1,
                'single_matrix_modeled_cycles': 1}}}},
        'signatures': {signature: {'M': 1, 'N': 1, 'K': 1, 'precision_bits': 32,
            'single_matrix_actual_computes': 1, 'single_matrix_modeled_cycles': 1, 'config_sha256': sha(run / 'mapping.yaml'),
            'stats_sha256': sha(run / 'timeloop-mapper.stats.txt'),
            'nodes': [{'graph': 'g', 'node_id': 'g:0'}]}},
        'coverage': {'mapped_nodes': 1, 'matrix_nodes': 1, 'unique_static_signatures': 1},
        'limitations': ['not a full model run']}
    path = tmp_path / 'result.json'
    path.write_text(json.dumps(result))
    observation = {'model_graphs': {'g': {'onnx_sha256': 'a' * 64,
        'node_count': 1, 'operators': [node]}}, 'coverage': {}}
    attach_verified_full_mapping(observation, path)
    assert observation['model_graphs']['g']['timeloop_mapped_node_count'] == 1
    assert node['timeloop_mapping']['signature_id'] == signature
    assert observation['coverage']['timeloop_unique_signatures'] == 1


def test_topology_sweep_refuses_an_unbound_source_result(tmp_path):
    import json
    import pytest
    sweep = tmp_path / 'topology-sweep'
    sweep.mkdir()
    result = sweep / 'result.json'
    result.write_text(json.dumps({'schema': 'wrong'}))
    roi = tmp_path / 'roi.json'
    roi.write_text('{}')
    observation = {'roi_simulation': {'traffic': {'trace_sha256': 'a' * 64}}}
    with pytest.raises(ValueError, match='pinned ROI'):
        attach_verified_topology_sweep(observation, result, roi)
    assert 'topology_sweep' not in observation


def test_srota_pair_refuses_an_unbound_source_result(tmp_path):
    import json
    import pytest
    directory = tmp_path / 'srota-pair'
    directory.mkdir()
    result = directory / 'result.json'
    result.write_text(json.dumps({'schema': 'wrong'}))
    roi = tmp_path / 'roi.json'
    roi.write_text('{}')
    observation = {'roi_simulation': {'traffic': {'trace_sha256': 'a' * 64}}}
    with pytest.raises(ValueError, match='pinned ROI trace'):
        attach_verified_srota_pair(observation, result, roi)
    assert 'srota_comparison' not in observation


def test_roi_cannot_attach_to_a_different_pinned_graph(tmp_path):
    import json
    import pytest
    path = tmp_path / 'result.json'
    path.write_text(json.dumps({'source_graph': 'action_head', 'model_onnx_sha256': 'wrong'}))
    observation = {'model_graphs': {'action_head': {'onnx_sha256': 'actual'}}}
    with pytest.raises(ValueError, match='graph digest'):
        attach_verified_roi(observation, path)
    assert 'roi_simulation' not in observation


def test_project_named_state_reorders_dataset_hand_names():
    names = [name for joints in GROUPS.values() for name in joints]
    # Dataset metadata uses index/middle/thumb for hands, unlike the model order.
    names = [n for n in names if '_hand_' not in n]
    names += [
        'left_hand_index_0_joint', 'left_hand_index_1_joint',
        'left_hand_middle_0_joint', 'left_hand_middle_1_joint',
        'left_hand_thumb_0_joint', 'left_hand_thumb_1_joint', 'left_hand_thumb_2_joint',
        'right_hand_index_0_joint', 'right_hand_index_1_joint',
        'right_hand_middle_0_joint', 'right_hand_middle_1_joint',
        'right_hand_thumb_0_joint', 'right_hand_thumb_1_joint', 'right_hand_thumb_2_joint',
    ]
    values = list(range(len(names)))
    projected, excluded = project_named_state(names, values)
    source = dict(zip(names, values))
    assert projected['left_hand'] == [source[name] for name in GROUPS['left_hand']]
    assert projected['right_hand'] == [source[name] for name in GROUPS['right_hand']]
    assert excluded == []


def test_project_named_state_reports_excluded_legs():
    names = [name for joints in GROUPS.values() for name in joints]
    names += [f'leg_joint_{i}' for i in range(12)]
    projected, excluded = project_named_state(names, [0.0] * len(names))
    assert sum(map(len, projected.values())) == 31
    assert len(excluded) == 12


def test_project_named_state_rejects_missing_and_duplicate_names():
    names = [name for joints in GROUPS.values() for name in joints]
    with __import__('pytest').raises(ValueError, match='unique'):
        project_named_state(names + [names[0]], [0.0] * (len(names) + 1))
    with __import__('pytest').raises(ValueError, match='missing'):
        project_named_state(names[:-1], [0.0] * (len(names) - 1))
