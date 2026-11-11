#!/usr/bin/env python3
"""Build an architecture-derived static trace and bind one pinned G1 observation.

No model weights are loaded and no numerical policy inference is performed.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import subprocess
import sys

import pyarrow.parquet as pq

sys_path = str(Path(__file__).resolve().parents[1] / 'dse')
if sys_path not in sys.path:
    sys.path.insert(0, sys_path)
from veritx_dse.model.presets import SWEEP_TOPOS, topo_size
from gr00t_topology_sweep import rankings as rank_topologies
from gr00t_srota_pair import COMMON as SROTA_PAIR_COMMON, SROTA_CONFIG as SROTA_PAIR_CONFIG

from gr00t_pipeline import DEFAULT_LEDGER, HASHES, REVISION, REPO, SUBSET, checked_hash, read_ledger, sha, write_new, json_bytes, require_timeloop_precision, check_packet_log
from gr00t_full_mapping import matrix_problem

MODEL_DIR = Path(__file__).resolve().parents[3] / 'runs/gr00t-model/staticpick-v1-source'
DATASET_INFO = Path('/tmp/gr00t-g1-dataset-audit/hf-cache/datasets--nvidia--PhysicalAI-Robotics-GR00T-X-Embodiment-Sim/snapshots/ea7ac0b68f87da62f1e726771bba0fe74300802f/unitree_g1.LMPnPAppleToPlateDC/meta/info.json')
DATASET_INFO_SHA256 = '85a5a8bff3957a1638e855d1c878ec82e982c59ea085f924e0f4a94fcf4c9431'
GROUPS = {
    'waist': ['waist_yaw_joint', 'waist_roll_joint', 'waist_pitch_joint'],
    'left_arm': ['left_shoulder_pitch_joint', 'left_shoulder_roll_joint', 'left_shoulder_yaw_joint', 'left_elbow_joint', 'left_wrist_roll_joint', 'left_wrist_pitch_joint', 'left_wrist_yaw_joint'],
    'right_arm': ['right_shoulder_pitch_joint', 'right_shoulder_roll_joint', 'right_shoulder_yaw_joint', 'right_elbow_joint', 'right_wrist_roll_joint', 'right_wrist_pitch_joint', 'right_wrist_yaw_joint'],
    'left_hand': ['left_hand_thumb_0_joint', 'left_hand_thumb_1_joint', 'left_hand_thumb_2_joint', 'left_hand_middle_0_joint', 'left_hand_middle_1_joint', 'left_hand_index_0_joint', 'left_hand_index_1_joint'],
    'right_hand': ['right_hand_thumb_0_joint', 'right_hand_thumb_1_joint', 'right_hand_thumb_2_joint', 'right_hand_index_0_joint', 'right_hand_index_1_joint', 'right_hand_middle_0_joint', 'right_hand_middle_1_joint'],
}


def project_named_state(names, values):
    if len(names) != len(values) or len(set(names)) != len(names):
        raise ValueError('dataset state names/values must have identical length and unique names')
    by_name = dict(zip(names, values))
    expected = [name for group in GROUPS.values() for name in group]
    missing = sorted(set(expected) - by_name.keys())
    if missing:
        raise ValueError(f'dataset state is missing model joints: {missing}')
    projected = {group: [float(by_name[name]) for name in joints]
                 for group, joints in GROUPS.items()}
    if any(len(projected[group]) != len(joints) for group, joints in GROUPS.items()):
        raise ValueError('model input group width mismatch')
    excluded = sorted(set(names) - set(expected))
    return projected, excluded


def _model_ir(model_dir):
    python = Path('/tmp/gr00t-model-venv/bin/python')
    if not python.is_file():
        raise RuntimeError('static model trace requires ONNX; use an isolated Python environment with ONNX 1.19')
    script = Path(__file__).with_name('gr00t_onnx_graph.py')
    completed = subprocess.run([str(python), str(script), str(model_dir)], check=True,
                               capture_output=True, text=True, timeout=120)
    return json.loads(completed.stdout)


def attach_verified_roi(observation, result_path):
    """Attach one graph-bound ROI only after checking actual tool artifacts."""
    result_path = Path(result_path)
    directory = result_path.parent
    roi = json.loads(result_path.read_text())
    graph = observation['model_graphs'].get(roi['source_graph'])
    if not graph or roi['model_onnx_sha256'] != graph['onnx_sha256']:
        raise ValueError('ROI graph digest does not match the observation model')
    index = roi['graph_node_index']
    if type(index) is not int or not 0 <= index < graph['node_count']:
        raise ValueError('ROI graph node index is invalid')
    node = graph['operators'][index]
    if (node['op_type'] != 'MatMul' or roi['operator'] != 'MatMul'
            or [value['shape'] for value in node['inputs'][:2]] != roi['input_shapes']
            or node['outputs'][0]['shape'] != roi['output_shape']):
        raise ValueError('ROI operation/shapes do not match the source graph node')
    mapped = roi['timeloop_single_batch_problem']
    # The canonical mapper filename is authoritative; no stale stats alias.
    stats = directory / 'timeloop-mapper.stats.txt'
    if (mapped.get('stats_filename') != stats.name or sha(stats) != mapped['stats_sha256']
            or sha(directory / 'mapping.yaml') != mapped['config_sha256']):
        raise ValueError('ROI Timeloop artifact digest/filename mismatch')
    require_timeloop_precision(stats.read_text(), roi['precision_bits'])
    trace = directory / 'workload.trace'
    if sha(trace) != roi['traffic']['trace_sha256']:
        raise ValueError('ROI trace digest mismatch')
    variants = roi['booksim_variants']
    if len(variants) != 2 or {v['layout'] for v in variants} != {'mesh-2x2', 'mesh-4x1'}:
        raise ValueError('ROI needs two recorded diagnostic variants')
    for variant in variants:
        label = variant['layout']
        log = directory / f'{label}.packets.csv'
        if (sha(log) != variant['packet_log_sha256']
                or sha(directory / f'{label}.cfg') != variant['config_sha256']):
            raise ValueError('ROI BookSim artifact digest mismatch')
        if check_packet_log(log, trace) != variant['observed']:
            raise ValueError('ROI BookSim metrics do not match retired packet log')
    graph['timeloop_mapped_node_count'] = 1
    graph['timeloop_status'] = 'one_static_MatMul_ROI_mapped_other_nodes_unmapped'
    observation['coverage'].update({
        'timeloop_mapped_nodes': sum(g['timeloop_mapped_node_count'] for g in observation['model_graphs'].values()),
        'qualification': 'architecture-derived graph; one MatMul ROI simulated, not full-model simulation',
        'traffic_trace': 'one source-derived MatMul input/output boundary trace; open-loop timing',
    })
    observation['roi_simulation'] = roi


def attach_verified_full_mapping(observation, result_path):
    """Bind completed static MatMul/Gemm mappings to the exact ONNX node inventory."""
    result_path = Path(result_path)
    directory = result_path.parent
    result = json.loads(result_path.read_text())
    if result.get('schema') != 'veritx/gr00t-full-static-mapping/1':
        raise ValueError('unsupported full mapping result schema')
    import re
    for graph_name, graph in observation['model_graphs'].items():
        mapped_graph = result['model_graphs'].get(graph_name)
        if (not mapped_graph or mapped_graph['onnx_sha256'] != graph['onnx_sha256']
                or mapped_graph['node_count'] != graph['node_count']
                or set(mapped_graph['nodes']) != {node['id'] for node in graph['operators']}):
            raise ValueError(f'full mapping does not match ONNX node inventory for {graph_name}')
        for signature_id, signature in result['signatures'].items():
            if not any(item['graph'] == graph_name for item in signature['nodes']):
                continue
            sig_dir = directory / signature_id
            config, stats = sig_dir / 'mapping.yaml', sig_dir / 'timeloop-mapper.stats.txt'
            if (sha(config) != signature['config_sha256'] or sha(stats) != signature['stats_sha256']):
                raise ValueError(f'full mapping artifact digest mismatch: {signature_id}')
            require_timeloop_precision(stats.read_text(), signature['precision_bits'])
            stats_text = stats.read_text()
            computes = re.search(r'^Actual Computes = (\d+)$', stats_text, re.M)
            cycles = re.search(r'^Cycles: (\d+)$', stats_text, re.M)
            if (not computes or int(computes.group(1)) != signature['M'] * signature['N'] * signature['K']
                    or not cycles or int(cycles.group(1)) != signature['single_matrix_modeled_cycles']):
                raise ValueError(f'full mapping metrics do not reconcile: {signature_id}')
        for node in graph['operators']:
            row = mapped_graph['nodes'][node['id']]
            if row['status'] == 'mapped':
                problem, reason = matrix_problem(node)
                signature = result['signatures'].get(row.get('signature_id'))
                if (problem is None or not signature or not any(item['graph'] == graph_name and item['node_id'] == node['id']
                                             for item in signature['nodes'])
                        or row.get('single_matrix_actual_computes') != signature['M'] * signature['N'] * signature['K']
                        or row.get('single_matrix_modeled_cycles') != signature['single_matrix_modeled_cycles']
                        or type(row.get('batch_count')) is not int or row['batch_count'] != problem['batch_count']
                        or any(signature.get(key) != problem[key] for key in ('M', 'N', 'K', 'precision_bits'))):
                    raise ValueError(f'mapped node does not reconcile to its signature: {node["id"]}')
                row.update({key: signature[key] for key in ('M', 'N', 'K', 'precision_bits')})
            node['timeloop_mapping'] = row
        graph['timeloop_mapped_node_count'] = mapped_graph['mapped_node_count']
        graph['timeloop_status'] = 'static_MatMul_Gemm_nodes_mapped_other_ops_or_dynamic_nodes_unmodeled'
    coverage = result['coverage']
    dynamic = sum(graph['status_counts'].get('unresolved_shape', 0)
                  for graph in result['model_graphs'].values())
    unsupported = sum(sum(count for status, count in graph['status_counts'].items()
                          if status not in ('mapped', 'unresolved_shape'))
                      for graph in result['model_graphs'].values())
    observation['coverage'].update({
        'timeloop_mapped_nodes': coverage['mapped_nodes'],
        'timeloop_matrix_candidates': coverage['matrix_nodes'] + dynamic,
        'timeloop_unresolved_shape_nodes': dynamic,
        'timeloop_unsupported_nodes': unsupported,
        'timeloop_unique_signatures': coverage['unique_static_signatures'],
        'qualification': 'static MatMul/Gemm signatures mapped; dynamic and non-matrix operators remain unmapped',
    })
    observation['full_static_mapping'] = {
        'schema': result['schema'], 'qualification': result['qualification'],
        'unique_signatures': coverage['unique_static_signatures'],
        'mapped_matrix_nodes': coverage['mapped_nodes'],
        'unresolved_shape_matrix_nodes': dynamic,
        'unsupported_operator_nodes': unsupported,
        'source_inventory_sha256': result['source_inventory_sha256'],
        'signatures': [{'signature_id': signature_id,
            **{key: signature[key] for key in ('M', 'N', 'K', 'precision_bits',
                'single_matrix_actual_computes', 'single_matrix_modeled_cycles',
                'config_sha256', 'stats_sha256')},
            'mapped_node_count': len(signature['nodes'])}
            for signature_id, signature in sorted(result['signatures'].items())],
        'limitations': result['limitations'],
    }


def attach_verified_topology_sweep(observation, result_path, roi_result_path):
    result_path, roi_result_path = Path(result_path), Path(roi_result_path)
    directory = result_path.parent
    roi = json.loads(roi_result_path.read_text())
    result = json.loads(result_path.read_text())
    trace = directory / 'workload.trace'
    if (result.get('schema') != 'veritx/gr00t-topology-sweep/1'
            or result.get('source_roi_result_sha256') != sha(roi_result_path)
            or result.get('trace_sha256') != roi['traffic']['trace_sha256']
            or sha(trace) != result['trace_sha256']
            or result.get('trace_packets') != roi['traffic']['packets']
            or result.get('trace_flits') != roi['traffic']['flits']):
        raise ValueError('topology sweep does not match the pinned ROI result and trace')
    expected = {topo.name: (topo, *topo_size(topo)) for topo in SWEEP_TOPOS}
    variants = result.get('variants')
    if not isinstance(variants, list) or {row.get('topology', {}).get('name') for row in variants} != set(expected):
        raise ValueError('topology sweep does not contain exactly the declared preset set')
    for row in variants:
        topology = row['topology']
        topo, endpoints, edges = expected[topology['name']]
        if (topology.get('backend') != topo.backend or topology.get('routing') != topo.routing
                or topology.get('params') != topo.params or topology.get('endpoints') != endpoints
                or topology.get('edges') != edges or row.get('trace_sha256') != result['trace_sha256']
                or sha(directory / topology['name'] / 'booksim.cfg') != row.get('config_sha256')):
            raise ValueError(f'topology sweep metadata/config mismatch for {topology["name"]}')
        if row.get('status') == 'completed':
            packet_log = directory / topology['name'] / 'packets.csv'
            if sha(packet_log) != row.get('packet_log_sha256'):
                raise ValueError(f'topology sweep packet-log digest mismatch for {topology["name"]}')
            if check_packet_log(packet_log, trace) != row.get('observed'):
                raise ValueError(f'topology sweep retirement does not reconcile for {topology["name"]}')
        elif row.get('status') != 'failed' or not isinstance(row.get('error'), str):
            raise ValueError(f'invalid topology sweep status for {topology["name"]}')
    if result.get('rankings_by_endpoint_count') != rank_topologies(variants):
        raise ValueError('topology sweep rankings do not match retired request latency')
    result['limitations'].append(
        'Preset routing and required GEC latency settings remain part of each comparison; this is not an isolated topology-only hardware ablation.')
    observation['topology_sweep'] = result


def attach_verified_srota_pair(observation, result_path, roi_result_path):
    result_path, roi_result_path = Path(result_path), Path(roi_result_path)
    directory = result_path.parent
    roi = json.loads(roi_result_path.read_text())
    result = json.loads(result_path.read_text())
    trace = directory / 'workload.trace'
    if (result.get('schema') != 'veritx/gr00t-srota-paired-comparison/1'
            or result.get('source_roi_result_sha256') != sha(roi_result_path)
            or result.get('trace_sha256') != roi['traffic']['trace_sha256']
            or sha(trace) != result['trace_sha256']
            or result.get('trace_packets') != roi['traffic']['packets']
            or result.get('trace_flits') != roi['traffic']['flits']
            or result.get('shared_router_settings') != SROTA_PAIR_COMMON
            or result.get('reproduction', {}).get('tool_sha256') != sha(Path(__file__).with_name('gr00t_srota_pair.py'))
            or result.get('reproduction', {}).get('srota_template_sha256') != sha(SROTA_PAIR_CONFIG)):
        raise ValueError('SROTA comparison does not match the pinned ROI trace or checked-in config')
    expected = {
        'mesh_8x8_vc4': {'backend': 'mesh', 'routing': 'min_adapt', 'params': {'k': 8, 'n': 2}},
        'srota_8x8': {'backend': 'srota', 'routing': 'o1turn', 'params': {
            'k': 8, 'c': 1, 'srota_mecs': 3, 'srota_path_en': 3,
            'srota_vc_policy': 'rank', 'srota_cong_thresh': 8,
            'srota_epoch_len': 1024, 'srota_cdg_radix': 4}},
    }
    variants = result.get('variants')
    if not isinstance(variants, list) or {row.get('name') for row in variants} != set(expected):
        raise ValueError('SROTA comparison does not contain the exact matched pair')
    for row in variants:
        name = row['name']
        if (row.get('topology') != expected[name] or row.get('endpoints') != 64
                or row.get('trace_sha256') != result['trace_sha256']
                or sha(directory / name / 'booksim.cfg') != row.get('config_sha256')
                or sha(directory / name / 'packets.csv') != row.get('packet_log_sha256')):
            raise ValueError(f'SROTA paired comparison metadata/hash mismatch for {name}')
        if check_packet_log(directory / name / 'packets.csv', trace) != row.get('observed'):
            raise ValueError(f'SROTA paired comparison retirement mismatch for {name}')
    if not isinstance(result.get('limitations'), list):
        raise ValueError('SROTA paired comparison is missing its limitations')
    observation['srota_comparison'] = result


def build_bundle(*, parquet, video, info, ledger, output, model_dir=MODEL_DIR, frame_index=1, roi_result=None, mapping_result=None, topology_sweep_result=None, srota_pair_result=None):
    out = Path(output)
    out.mkdir(parents=True, exist_ok=False)
    rows = read_ledger(ledger)
    checked_hash(parquet, HASHES['parquet_sha256'])
    checked_hash(video, HASHES['mp4_sha256'])
    if not 1 <= frame_index <= 683:
        raise ValueError('frame_index must be in the pinned 1..683 observation range')
    frame = rows[frame_index]
    info_path = Path(info)
    if sha(info_path) != DATASET_INFO_SHA256:
        raise ValueError('dataset info.json hash mismatch')
    meta = json.loads(info_path.read_text())
    names = meta['features']['observation.state']['names']
    if len(names) != 43:
        raise ValueError('unexpected named observation.state width')
    table = pq.read_table(parquet, columns=['frame_index', 'episode_index', 'timestamp', 'observation.state'])
    matched = [row for row in table.to_pylist() if row['frame_index'] == frame_index and row['episode_index'] == 0]
    if len(matched) != 1 or abs(matched[0]['timestamp'] - frame['timestamp_s']) > 0.000002:
        raise ValueError('Parquet row does not match PTS-aligned ledger observation')
    projected, excluded = project_named_state(names, matched[0]['observation.state'])
    video_path = Path(video)
    raw = subprocess.run(['ffmpeg', '-v', 'error', '-i', str(video_path), '-vf', f"select='eq(n,{frame_index-1})",
                          '-vsync', '0', '-frames:v', '1', '-f', 'rawvideo', '-pix_fmt', 'rgb24', '-'],
                         check=True, capture_output=True, timeout=30).stdout
    if len(raw) != 640 * 480 * 3:
        raise ValueError('decoded observation frame is not RGB 640x480')
    write_new(out / 'observation.rgb24', raw)
    graphs = _model_ir(model_dir)
    observation = {
        'schema': 'veritx/gr00t-static-architecture-observation/1',
        'qualification': 'OFFLINE_OBSERVATION_ARCHITECTURE_TRACE_ONLY',
        'source': {'dataset_repo': REPO, 'revision': REVISION, 'subset': SUBSET, 'episode': 0,
                   'frame_index': frame_index, 'timestamp_s': frame['timestamp_s'],
                   'dataset_task': 'pick up the apple, walk left, and place the apple on the plate',
                   'camera_sha256': sha(out / 'observation.rgb24'), 'source_video_sha256': sha(video_path),
                   'state_sha256': hashlib.sha256(json.dumps(matched[0]['observation.state'], separators=(',', ':')).encode()).hexdigest()},
        'model': {'repo': 'nvidia/GN1x-Tuned-Arena-G1-Static-PickNPlace',
                  'revision': '7f78bebf1a90131e7304beacfcd47eb27bad16ab',
                  'export_prompt': 'move the apple to the plate', 'prompt_source': 'frozen in pinned static ONNX export',
                  'staticpredict_horizon': 40, 'simulation_horizon_s': 0.7,
                  'flow_matching_steps': 4, 'flow_matching_source': 'static export README.md'},
        'coverage': {'graph_nodes': sum(graph['node_count'] for graph in graphs.values()),
                     'timeloop_mapped_nodes': sum(graph['timeloop_mapped_node_count'] for graph in graphs.values()),
                     'qualification': 'architecture-derived static graph; no operator mapped to Timeloop',
                     'traffic_trace': 'not produced', 'numeric_inference': 'not performed'},
        'state_binding': {'source_feature': 'observation.state', 'source_names_sha256': hashlib.sha256(json.dumps(names, separators=(',', ':')).encode()).hexdigest(),
                          'source_info_sha256': DATASET_INFO_SHA256,
                          'mapping_authority': ['dataset meta/info.json observation.state.names',
                                                'Isaac OS v0.11.0 operators/gr00t_n1_7/config/control.yaml sim.gr00t_n1_7.state_output_spec',
                                                'static export graph.yaml preprocess_state input element_names'],
                          'mapping': GROUPS, 'projected_groups': projected, 'excluded_source_joints': excluded,
                          'normalization_and_132-wide_padding': 'performed by preprocess_state.onnx; not reimplemented here'},
        'semantics': ['Camera and named-joint state are one actual 50 Hz dataset observation.',
                      'Export is static-pick and frozen-prompt; dataset task differs.',
                      'No same-task or trained-checkpoint compatibility claim.',
                      'No numerical model inference or policy execution performed.',
                      'ONNX shapes/operators are architecture-derived, not measured inference.',
                      'Recorded actions are not model outputs.'],
        'model_graphs': graphs,
    }
    if roi_result is not None:
        attach_verified_roi(observation, roi_result)
    if mapping_result is not None:
        attach_verified_full_mapping(observation, mapping_result)
    if topology_sweep_result is not None:
        if roi_result is None:
            raise ValueError('topology sweep requires its bound ROI result')
        attach_verified_topology_sweep(observation, topology_sweep_result, roi_result)
    if srota_pair_result is not None:
        if roi_result is None:
            raise ValueError('SROTA comparison requires its bound ROI result')
        attach_verified_srota_pair(observation, srota_pair_result, roi_result)
    comparison_path = out / 'comparison.json'
    write_new(comparison_path, json_bytes(observation))
    manifest = {
        'schema': 'veritx/gr00t-static-architecture-bundle/1',
        'qualification': observation['qualification'],
        'files': {name: sha(out / name) for name in ('comparison.json', 'observation.rgb24')},
        'model_graphs': {name: graph['onnx_sha256'] for name, graph in graphs.items()},
        'reproduction': {'tool': 'tracks/t3-topology/tools/gr00t_model_trace.py',
                         'frame_index': frame_index, 'model_revision': observation['model']['revision'],
                         'dataset_revision': REVISION},
        'limitations': observation['semantics'],
    }
    write_new(out / 'manifest.json', json_bytes(manifest))
    return observation


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--parquet', type=Path, required=True)
    p.add_argument('--video', type=Path, required=True)
    p.add_argument('--info', type=Path, default=DATASET_INFO)
    p.add_argument('--ledger', type=Path, default=DEFAULT_LEDGER)
    p.add_argument('--model-dir', type=Path, default=MODEL_DIR)
    p.add_argument('--frame-index', type=int, default=1)
    p.add_argument('--output', type=Path, required=True)
    p.add_argument('--roi-result', type=Path, help='attach a verified source-derived ROI result and its local raw artifacts')
    p.add_argument('--mapping-result', type=Path, help='attach verified static MatMul/Gemm mappings and node coverage')
    p.add_argument('--topology-sweep-result', type=Path, help='attach a verified same-trace sweep over all declared BookSim presets')
    p.add_argument('--srota-pair-result', type=Path, help='attach verified SROTA 8x8 and matched mesh 8x8 results')
    args = p.parse_args()
    result = build_bundle(parquet=args.parquet, video=args.video, info=args.info, ledger=args.ledger,
                          output=args.output, model_dir=args.model_dir, frame_index=args.frame_index,
                          roi_result=args.roi_result, mapping_result=args.mapping_result,
                          topology_sweep_result=args.topology_sweep_result,
                          srota_pair_result=args.srota_pair_result)
    print(json.dumps({'schema': result['schema'], 'qualification': result['qualification'],
                      'frame_index': result['source']['frame_index'], 'graphs': list(result['model_graphs'])}, indent=2))


if __name__ == '__main__':
    main()
