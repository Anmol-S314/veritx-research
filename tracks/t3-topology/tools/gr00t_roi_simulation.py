#!/usr/bin/env python3
"""Run one source-derived ONNX MatMul ROI through Timeloop and native BookSim."""
from __future__ import annotations
import argparse, hashlib, json, math, os, subprocess, sys
from pathlib import Path
import onnx
from gr00t_pipeline import require_timeloop_precision

ROOT = Path(__file__).resolve().parents[3]
MODEL = ROOT / 'runs/gr00t-model/staticpick-v1-source/action_head.onnx'
NODE_NAME = 'node_MatMul_916'
FLIT_BYTES, MAX_PACKET_FLITS = 32, 16
DTYPE_BYTES = {onnx.TensorProto.FLOAT: 4, onnx.TensorProto.FLOAT16: 2,
               onnx.TensorProto.DOUBLE: 8, onnx.TensorProto.BFLOAT16: 2}

def digest(path):
    h = hashlib.sha256()
    with Path(path).open('rb') as f:
        for block in iter(lambda: f.read(1 << 20), b''): h.update(block)
    return h.hexdigest()

def write_new(path, data):
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    with Path(path).open('xb') as f: f.write(data if isinstance(data, bytes) else data.encode())

def source_roi(model_path):
    model = onnx.load_model(str(model_path), load_external_data=False)
    model = onnx.shape_inference.infer_shapes(model, strict_mode=False, data_prop=False)
    node = next((n for n in model.graph.node if n.name == NODE_NAME), None)
    if node is None or node.op_type != 'MatMul': raise ValueError(f'pinned graph lacks expected MatMul {NODE_NAME}')
    values = {v.name: v for v in (*model.graph.input, *model.graph.value_info, *model.graph.output)}
    values.update({i.name: i for i in model.graph.initializer})
    def tensor(name):
        value = values.get(name)
        if value is None or not value.type.HasField('tensor_type'): raise ValueError(f'no tensor metadata for {name}')
        typ = value.type.tensor_type
        dims = [d.dim_value if d.dim_value else None for d in typ.shape.dim]
        if not dims or any(type(d) is not int or d < 1 for d in dims): raise ValueError(f'dynamic/unresolved ROI shape for {name}: {dims}')
        return dims, typ.elem_type
    a_shape, a_type = tensor(node.input[0]); b_shape, b_type = tensor(node.input[1]); y_shape, y_type = tensor(node.output[0])
    if a_type != b_type or a_type != y_type or a_type not in DTYPE_BYTES: raise ValueError('ROI tensor dtypes do not match a supported element type')
    if len(a_shape) < 2 or len(b_shape) < 2 or a_shape[:-2] != b_shape[:-2] or a_shape[-1] != b_shape[-2]: raise ValueError('MatMul batch/K dimensions do not reconcile')
    expected = a_shape[:-2] + [a_shape[-2], b_shape[-1]]
    if y_shape != expected: raise ValueError(f'MatMul output shape mismatch: {y_shape} != {expected}')
    batch_count = math.prod(a_shape[:-2]) if a_shape[:-2] else 1
    return node, a_shape, b_shape, y_shape, batch_count, DTYPE_BYTES[a_type], onnx.TensorProto.DataType.Name(a_type).lower(), model

def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--model', type=Path, default=MODEL)
    p.add_argument('--output', type=Path, required=True)
    p.add_argument('--timeloop', type=Path, default=Path('/tmp/srota-timeloop-build.yAXlOe/build/timeloop-mapper'))
    p.add_argument('--timeout', type=int, default=120)
    args = p.parse_args(); out = args.output.resolve()
    if any(c.isspace() for c in str(out)): raise ValueError('output path must not contain whitespace')
    out.mkdir(parents=True, exist_ok=False)
    node, a, b, y, batches, scalar_bytes, dtype_name, model = source_roi(args.model)
    m, k, n = a[-2], a[-1], b[-1]
    transfers = [('activation_left', 0, 1, math.prod(a) * scalar_bytes),
                 ('activation_right', 0, 1, math.prod(b) * scalar_bytes),
                 ('activation_output', 1, 2, math.prod(y) * scalar_bytes)]
    packets, transfer_rows, ready = [], [], {}
    for name, src, dst, byte_count in transfers:
        flits = (byte_count + FLIT_BYTES - 1) // FLIT_BYTES
        cycle, remaining, count = ready.get(src, 0), flits, 0
        while remaining:
            size = min(MAX_PACKET_FLITS, remaining)
            packets.append((cycle, src, 0, dst, size)); remaining -= size; cycle += size; count += 1
        ready[src] = cycle
        transfer_rows.append({'tensor_boundary': name, 'src': src, 'dst': dst, 'payload_bytes': byte_count, 'flits': flits, 'packets': count})
    trace_bytes = ''.join('%d %d %d %d %d\n' % row for row in sorted(packets)).encode()
    write_new(out/'workload.trace', trace_bytes)
    vendor = ROOT/'third_party/timeloop'
    arch = (vendor/'arch.yaml').read_text()
    if arch.count('word-bits: 8') != 4:
        raise ValueError('unexpected base architecture precision fields')
    # Match storage/arithmetic word widths to the graph's actual tensor dtype.
    arch = arch.replace('word-bits: 8', f'word-bits: {scalar_bytes * 8}')
    config = arch + f'''\nproblem:\n  shape:\n    name: gemm\n    dimensions: [ M, N, K ]\n    data-spaces:\n      - name: Inputs\n        projection: [ [[M]], [[K]] ]\n      - name: Weights\n        projection: [ [[K]], [[N]] ]\n      - name: Outputs\n        projection: [ [[M]], [[N]] ]\n        read-write: True\n  instance:\n    M: {m}\n    N: {n}\n    K: {k}\nmapper:\n  algorithm: exhaustive\n  optimization-metrics: [delay]\n  num-threads: 1\n  search-size: 16\n  victory-condition: 4\n  timeout: 16\n'''
    write_new(out/'mapping.yaml', config)
    env = dict(os.environ); env['LD_LIBRARY_PATH'] = str(args.timeloop.resolve().parent.parent/'lib') + os.pathsep + env.get('LD_LIBRARY_PATH','')
    run = subprocess.run([str(args.timeloop.resolve()), str(out/'mapping.yaml')], cwd=out, env=env, timeout=args.timeout, stdin=subprocess.DEVNULL, capture_output=True, text=True)
    write_new(out/'timeloop.stdout', run.stdout); write_new(out/'timeloop.stderr', run.stderr)
    stats = out/'timeloop-mapper.stats.txt'
    if run.returncode or not stats.is_file(): raise RuntimeError('Timeloop ROI mapping failed')
    import re
    stats_text = stats.read_text()
    resolved_widths = require_timeloop_precision(stats_text, scalar_bytes * 8)
    actual_match = re.search(r'^Actual Computes = (\d+)$', stats_text, re.M)
    cycles_match = re.search(r'^Cycles: (\d+)$', stats_text, re.M)
    if not actual_match or not cycles_match: raise ValueError('Timeloop stats lack compute/cycle totals')
    actual = int(actual_match.group(1)); cycles = int(cycles_match.group(1))
    if actual != m*n*k: raise ValueError('Timeloop actual computes do not equal source-derived single-batch GEMM')
    sys.path.insert(0, str(ROOT/'tracks/t3-topology/dse')); sys.path.insert(0, str(ROOT/'tracks/t3-topology/tools'))
    from veritx_dse.simulation.booksim import build_config, run_booksim
    from veritx_dse.model.presets import Topology
    from veritx_dse.core.logging import Ctx
    from gr00t_pipeline import check_packet_log
    variants=[]
    for label, width, height in [('mesh-2x2',2,2),('mesh-4x1',4,1)]:
        packetlog=out/f'{label}.packets.csv'
        cfg=build_config(Topology(name=label,backend='mesh',routing='dim_order',params={'k':width,'n':height}),str(out/'workload.trace'),sim_type='trace',seed=0,overrides={'trace_file':str(out/'workload.trace'),'sample_period':10000,'sim_count':1,'trace_packet_log':str(packetlog)})
        cfgpath=out/f'{label}.cfg'; write_new(cfgpath,cfg)
        def capture(command,cwd,timeout):
            result=subprocess.run(command,cwd=cwd,timeout=timeout,stdin=subprocess.DEVNULL,capture_output=True,text=True)
            write_new(out/f'{label}.stdout',result.stdout);write_new(out/f'{label}.stderr',result.stderr)
            if result.returncode: raise RuntimeError(f'BookSim {label} failed')
            return result
        metrics=run_booksim(Ctx(verbosity=0),cfg,repo_root=ROOT,timeout=args.timeout,label=label,runner=capture)
        observed=check_packet_log(packetlog,out/'workload.trace')
        if observed['packets'] != len(packets) or observed['flits'] != sum(x[4] for x in packets): raise ValueError('BookSim retirement does not conserve source-derived tensor trace')
        variants.append({'layout':label,'config_sha256':digest(cfgpath),'packet_log_sha256':digest(packetlog),'observed':observed,'metrics':metrics})
    result={'qualification':'SOURCE_DERIVED_STATIC_ROI_SIMULATION','model_onnx_sha256':digest(args.model),'source_graph':'action_head','node_name':node.name,'graph_node_index':list(model.graph.node).index(node),'operator':node.op_type,'input_shapes':[a,b],'output_shape':y,'dtype':dtype_name,'precision_bits':scalar_bytes*8,'batch_count':batches,'timeloop_single_batch_problem':{'M':m,'N':n,'K':k,'actual_computes':actual,'modeled_cycles':cycles,'resolved_word_bits':resolved_widths,'stats_filename':stats.name,'stats_sha256':digest(stats),'config_sha256':digest(out/'mapping.yaml')},'traffic':{'semantics':'Two ONNX activation inputs transferred memory->authored compute endpoint; one computed activation output compute->consumer. Full static tensors, all batch instances. Open-loop issue timing: each source starts at cycle 0 and the output is not gated by Timeloop completion.','transfers':transfer_rows,'endpoints':{'memory':0,'compute':1,'consumer':2},'flit_bytes':FLIT_BYTES,'max_packet_flits':MAX_PACKET_FLITS,'payload_bytes':sum(t[3] for t in transfers),'padded_bytes':sum(x[4] for x in packets)*FLIT_BYTES,'packets':len(packets),'flits':sum(x[4] for x in packets),'trace_sha256':hashlib.sha256(trace_bytes).hexdigest()},'booksim_variants':variants,'limitations':['Architecture-derived static tensor shapes, not numeric ONNX inference.','Timeloop maps one matrix instance of this batched MatMul; the 32 source batch instances are identified, no aggregate latency claim is made.','Tensor traffic covers explicit input/output boundaries of one MatMul ROI, not full model movement.','Two authored diagnostic mesh layouts are not calibrated physical hardware.','Timeloop and BookSim cycle counts are separate; not summed.']}
    write_new(out/'result.json',json.dumps(result,sort_keys=True,indent=2,allow_nan=False)+'\n')
    print(json.dumps(result,sort_keys=True,indent=2))
if __name__=='__main__': main()
