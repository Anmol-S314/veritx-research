#!/usr/bin/env python3
"""Finite control-surface witnesses: parse -> compile -> inspect -> execute.

No live drafts are touched. Results keep requested values, derived artifacts,
refusals and measured metrics distinct. Not an exhaustive Cartesian sweep.
"""
from __future__ import annotations

import argparse
from copy import deepcopy
from dataclasses import replace
import json
import os
from pathlib import Path
import resource
import signal
import subprocess
import sys
import time
import traceback

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from veritx_dse.core.paths import REPO, ASTRA_BS_BIN
from veritx_dse.application.presets import build_typed_preset_request, _typed_request
from veritx_dse.model.topology_intent import MeshIntent


def baseline():
    return _typed_request(MeshIntent(4, 1), endpoints=8, tp=8).to_dict()


def specs():
    rows = []
    def add(name, group, doc, execute=False, note=''):
        doc=deepcopy(doc)
        for key in ('design_hash','guardrail_hash'):doc.pop(key,None)
        rows.append({'name':name,'group':group,'request':doc,'execute':execute,'scope_note':note})
    base = baseline()
    add('baseline', 'baseline', base, True)
    # Exact authorable fields, not phantom buffer/VC knobs.
    for field, values in {
        'link_width':[8,16,32,64,128,256,512,0,7],
        'arbitration':[None,'islip','round_robin','rr','unsupported_policy'],
        'rcu_enabled':[False,True], 'mcast_groups':[None,1,4,0],
        'mcast_setup_cycles':[None,0,4,-1],
        'output_formats':[[],['json'],['systemverilog','uvm'],['unknown']],
        'obfuscation_level':[0,1,3,-1],
    }.items():
        for index, value in enumerate(values):
            doc=deepcopy(base);doc['noc_controls'][field]=value
            add(f'noc__{field}_{index}', 'noc_controls',doc,
                execute=(field in ('arbitration','rcu_enabled','mcast_groups','mcast_setup_cycles') or field=='link_width' and value in (32,64,128,256)))
    for field in ('vc_count','input_buffer_depth','credit_return_latency'):
        doc=deepcopy(base);doc['noc_controls'][field]=4
        add('not_authorable__'+field,'schema',doc,note='Derived artifact controls are not v4 request knobs; unknown fields must refuse.')
    # Dependency graph, not an invented direct VC override.
    for cycles in range(0,9):
        doc=deepcopy(base)
        doc['dependencies']=[{'source':f'a{i}','target':f'b{i}','kind':'blocking'} for i in range(cycles)] + [
            {'source':f'b{i}','target':f'a{i}','kind':'blocking'} for i in range(cycles)]
        add(f'vc__dependency_cycles_{cycles}','vc_derivation',doc)
    for policy, shapes in [('none',['row']),('shape',['row','column']),('rank',['row','column','valiant']),('none',['row','column']),('shape',['row','column','valiant'])]:
        doc=build_typed_preset_request('srota32').to_dict()
        doc['topology'].update(vc_policy=policy,path_shapes=shapes)
        add(f'srota__{policy}_'+str(len(shapes)), 'srota_vc',doc,execute=len(shapes)==1 or policy in ('shape','rank'))
    for side,o,d in [(3,1,2),(4,1,3),(5,2,2),(5,1,4),(8,1,7)]:
        doc=build_typed_preset_request('gec_hybrid16').to_dict()
        doc['topology'].update(grid_side_length=side,express_channel_groups_per_dimension=o,destinations_per_express_channel=d,concentration=2)
        add(f'gec__k{side}_o{o}_d{d}','gec_vc',doc,execute=side<=5)
    # SROTA implementation controls and refusal boundaries.
    for field,values in {'drop_latency':[1,2,0], 'tel_period':[1,4,16,0],
        'tel_latency':[1,8,32,0], 'sidebuf_enable':[False,True],
        'sidebuf_watermark':[1,6,16,0], 'mecs_row':[False,True],
        'mecs_col':[False,True], 'island_columns':[[],[1],[0,3],[4],[1,1]],
        'planes':[['d'],['d','t'],['d','t','c'],['t']],
    }.items():
        for i,v in enumerate(values):
            doc=build_typed_preset_request('srota32_islands' if field=='island_columns' else 'srota32').to_dict()
            doc['topology'][field]=v
            if field=='sidebuf_enable':doc['topology']['sidebuf_watermark']=6 if v else None
            add(f'srota_knob__{field}_{i}','srota_knobs',doc,execute=field in ('tel_period','tel_latency','sidebuf_enable','sidebuf_watermark','island_columns'))
    # Workload/class/width and clock interactions.
    for clock in (250,500,1000,2000,0,-1):
        for width in (64,256):
            doc=deepcopy(base);doc['physical']['clock_freq_mhz']=clock;doc['noc_controls']['link_width']=width
            add(f'clock_width__mhz{clock}_w{width}','clock_width',doc,execute=clock>0)
    for payload in (8,64,8192,8193,0):
        doc=deepcopy(base);doc['workload']['collectives'][0]['payload_bytes']=payload
        add(f'workload__payload{payload}','workload',doc,execute=payload>0)
    for field,values in {'protocol':['AXI','CHI','APB','unsupported_protocol'],
                        'data_width':[8,64,256,7], 'addr_width':[8,32,64,7],
                        'clock_domain':[None,'fabric','core'],
                        'power_domain':[None,'always_on','switchable']}.items():
        for i,value in enumerate(values):
            doc=deepcopy(base);doc['agents'][0][field]=value
            add(f'agent__{field}_{i}','agent_interfaces',doc,execute=field in ('clock_domain','power_domain'),
                note='Domain labels alone do not establish heterogeneous timing or power gating.')
    for field,values in {'process_node_nm':[3,7,14,0], 'num_power_domains':[1,2,4,0], 'data_width':[64,256,7]}.items():
        for value in values:
            doc=deepcopy(base);doc['physical'][field]=value
            add(f'physical__{field}_{value}','physical_context',doc)
    # Address regions target singleton HBM groups, not invented interleaving.
    addr=deepcopy(base);addr['agents'].append({'kind':'hbm_controller','count':1,'protocol':'AXI','data_width':256,'addr_width':64,'clock_domain':None,'power_domain':None})
    def region(name, start, size, target=1):return {'name':name,'base':start,'size':size,'target_agent_idx':target}
    regions={
        'one':[region('weights',0x1000,0x1000)],
        'adjacent':[region('a',0,256),region('b',256,256)],
        'disjoint':[region('a',0,256),region('b',4096,256)],
        'overlap':[region('a',0,512),region('b',256,512)],
        'contained_overlap':[region('a',0,4096),region('b',128,128)],
        'top_valid':[region('top',2**64-256,256)],
        'top_overflow':[region('top',2**64-128,256)],
        'zero_size':[region('empty',0,0)],
        'negative_base':[region('negative',-1,256)],
        'bad_target':[region('missing',0,256,99)],
        'non_singleton_target':[region('compute_group',0,256,0)],
        'rename':[region('renamed',0x1000,0x1000)],
        'unaligned':[region('unaligned',3,17)],
    }
    for name,ranges in regions.items():
        doc=deepcopy(addr);doc['address_map']['ranges']=ranges
        add('address__'+name,'address_regions',doc,execute=name in ('one','adjacent','disjoint','rename','unaligned'),
            note='Collective network traffic does not exercise memory addresses; decode boundaries are separately inspected.')
    for bits in (8,32,64):
        doc=deepcopy(addr);doc['agents'][1]['addr_width']=bits
        doc['address_map']['ranges']=[region('fit',2**bits-16,16)]
        add(f'address__width{bits}_fit','address_regions',doc)
        doc=deepcopy(doc);doc['address_map']['ranges'][0]['size']=17
        add(f'address__width{bits}_overflow','address_regions',doc)
    for groups in (1,2):
        doc=deepcopy(addr);doc['agents'][1]['count']=groups
        doc['address_map']['ranges']=[region('memory',0,256)]
        add(f'address__hbm_group_count{groups}','address_regions',doc)
    # Cross knobs: topology/width/allocator. Avoid Cartesian explosion.
    for preset in ('flatfly16','gec_hybrid16','srota32','torus25','explicit16'):
        for width,allocator in ((32,'islip'),(64,'round_robin'),(128,'islip')):
            doc=build_typed_preset_request(preset).to_dict()
            doc['noc_controls'].update(link_width=width,arbitration=allocator)
            add(f'cross__{preset}_w{width}_{allocator}','topology_controls',doc,execute=True)
    return rows


def valid_expansion_specs():
    """Positive interaction witnesses only; no deliberately invalid probes."""
    from veritx_dse.model.topology_intent import ConcentratedMeshIntent
    bases={'mesh':baseline(),
        'cmesh':_typed_request(ConcentratedMeshIntent(2,4),endpoints=16,tp=16).to_dict()}
    for preset in ('flatfly16','torus25','gec_mecs16','gec_hybrid16',
                   'srota32','srota32_rank','srota32_islands'):
        bases[preset]=build_typed_preset_request(preset).to_dict()
    bases['srota_shape']=deepcopy(bases['srota32'])
    bases['srota_shape']['topology'].update(vc_policy='shape',path_shapes=['row','column'])
    bases['srota_no_t']=deepcopy(bases['srota32'])
    bases['srota_no_t']['topology']['planes']=['d']
    bases['srota_no_sidebuffer']=deepcopy(bases['srota32'])
    bases['srota_no_sidebuffer']['topology'].update(sidebuf_enable=False,sidebuf_watermark=None)
    rows=[]
    for family,base in bases.items():
        for width in (16,64,256):
            for tp in (2,4,8):
                for allocator in ('islip','round_robin'):
                    doc=deepcopy(base)
                    for key in ('design_hash','guardrail_hash'):doc.pop(key,None)
                    doc['noc_controls'].update(link_width=width,arbitration=allocator)
                    doc['workload']['tp']=tp
                    doc['workload']['collectives'][0]['payload_bytes']=128*tp
                    rows.append({'name':f'valid__{family}_w{width}_TP{tp}_{allocator}',
                        'group':'valid_interactions','request':doc,'execute':True,
                        'scope_note':'Independent fixture; attached endpoints preserved; '
                            'TP and divisible collective payload explicit. Not hardware signoff.'})
    return rows


def router_control_specs():
    """Finite authored IQ-router witnesses; independent fixtures only."""
    rows = []
    def add(name, doc, values):
        doc = deepcopy(doc)
        for key in ('design_hash', 'guardrail_hash'):
            doc.pop(key, None)
        doc['noc_controls'].update(values)
        rows.append({'name':name, 'group':'router_controls', 'request':doc,
            'execute':True, 'scope_note':'Authored IQ-router simulation; not hardware signoff or exhaustive support.'})
    combined = dict(input_buffer_depth_flits_per_vc=4,
        credit_return_latency_cycles=2, allocator_iterations=2,
        route_compute_cycles=2, vc_alloc_cycles=1,
        switch_alloc_cycles=1, switch_traversal_cycles=2)
    add('router__mesh_combined', baseline(), combined)
    from veritx_dse.model.topology_intent import ConcentratedMeshIntent
    add('router__cmesh_combined', _typed_request(
        ConcentratedMeshIntent(2, 4), endpoints=16, tp=8).to_dict(), combined)
    for preset in ('explicit16', 'torus25', 'flatfly16',
                   'gec_mecs16', 'gec_hybrid16', 'srota32'):
        doc = build_typed_preset_request(preset).to_dict()
        if preset == 'srota32':
            doc['topology'].update(sidebuf_enable=False, sidebuf_watermark=None)
        add(f'router__{preset}_combined', doc, combined)
    from veritx_dse.model.noc_controls import ROUTER_CONTROL_FIELDS
    for field in ROUTER_CONTROL_FIELDS:
        minimum = 0 if field == 'credit_return_latency_cycles' else 1
        maximum = 64 if field == 'input_buffer_depth_flits_per_vc' else 16
        for value in (minimum, maximum):
            add(f'router__mesh_{field}_{value}', baseline(), {field:value})
    return rows


def write(path,data):
    temporary=path.with_suffix('.tmp');temporary.write_text(json.dumps(data,indent=2,default=str));temporary.replace(path)


def run(spec, directory):
    if (directory/'result.json').exists() or (directory/'execution').exists():
        raise FileExistsError(f'fresh witness directory required: {directory}')
    from veritx_dse.model.compile_request_v4 import CompileRequestV4
    from veritx_dse.application.fabric_compiler import FabricCompiler
    from veritx_dse.core.errors import VeritXError
    row={k:v for k,v in spec.items() if k!='request'}
    write(directory/'request.json',spec['request'])
    started=time.monotonic()
    try:
        request=CompileRequestV4.from_dict(spec['request'])
        row['design_hash']=request.design_hash()
        compiled=FabricCompiler().compile(request)
        row.update(status=compiled.status,reason=compiled.error,stage=compiled.stopped_at_stage)
        if compiled.certificate:write(directory/'certificate.json',compiled.certificate.to_dict())
        if compiled.status!='COMPILED':return row
        b=compiled.bundle
        row['artifacts']={'vc_count':b.vc_assignment.vc_count,'class_to_vcs':b.vc_assignment.to_dict()['traffic_class_to_vcs'],
            'topology':b.topology.to_dict(),'address_decode':b.address_decode.to_dict(),
            'router_behavior':b.router_behavior.to_dict(),'packet_format':b.packet_format.to_dict()}
        write(directory/'compiled-artifacts.json',row['artifacts'])
        # Record certified half-open range boundaries, not memory transactions.
        ad=b.address_decode
        row['address_boundaries']=[{'name':e.name,'start':e.base,'last':e.base+e.size-1,
            'one_past':e.base+e.size,'target_endpoint':e.target_endpoint_id} for e in ad.entries]
        from veritx_dse.application.evaluation_context import build_evaluation_context
        from veritx_dse.application.evaluation_plan import EvaluationPlanner
        from veritx_dse.application.evaluation_question import EvaluationQuestion
        from veritx_dse.backend.registry import default_backend_registry
        registry=default_backend_registry(booksim_bin=REPO/'third_party/booksim2/src/booksim',astra_bin=ASTRA_BS_BIN,repo_root=REPO)
        context=build_evaluation_context(compiled)
        qs=tuple(EvaluationQuestion[n] for n in ('NETWORK_COMPLETION','SYSTEM_MAKESPAN','COMMUNICATION_EXPOSURE','PER_RANK_COMPLETION'))
        plan=EvaluationPlanner().plan(context,qs,registry)
        row['plan']=[{'question':a.question.value,'support':a.support.value,'readiness':a.readiness.value,'reason':a.reason} for a in plan.analyses]
        if spec['execute']:
            from veritx_dse.application.federated_evaluator import evaluate_federated,BookSimRunOptions,AstraRunOptions
            clock=int(request.physical.default_clock_freq_mhz*1_000_000)
            result=evaluate_federated(compiled,qs,registry,
                booksim_options=BookSimRunOptions(binary=REPO/'third_party/booksim2/src/booksim',repo_root=REPO,network_clock_hz=clock,timeout_s=30,seed=0),
                astra_options=AstraRunOptions(repo_root=REPO,timeout_s=30),run_dir=str(directory/'execution'))
            row.update(status=result.status,analyses=[a.to_dict() for a in result.analyses])
    except (ValueError,VeritXError) as exc:row.update(status='REFUSED',reason=f'{type(exc).__name__}: {exc}')
    finally:row['seconds']=round(time.monotonic()-started,3)
    return row


def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--filter',default='');parser.add_argument('--worker',help=argparse.SUPPRESS)
    parser.add_argument('--valid-expansion',action='store_true',help='216 valid topology/width/TP/allocator interaction witnesses, excluding invalid probes')
    parser.add_argument('--router-controls',action='store_true',help='22 authored IQ-router family/limit witnesses, with all four analyses')
    parser.add_argument('--owner',type=int,help=argparse.SUPPRESS)
    parser.add_argument('--ready-replay',type=Path,help='Execute compile-only cases whose saved plans mark all four analyses READY')
    parser.add_argument('--force-execute',action='store_true',help=argparse.SUPPRESS)
    args=parser.parse_args();args.output=args.output.resolve();args.output.mkdir(parents=True,exist_ok=True)
    if args.router_controls and args.valid_expansion:
        parser.error('choose one witness suite')
    selected_specs=router_control_specs() if args.router_controls else valid_expansion_specs() if args.valid_expansion else specs()
    if not args.worker and (args.output/'results.json').exists():
        parser.error('output already holds results; choose a fresh directory to preserve evidence')
    if args.worker:
        import ctypes,faulthandler
        def stop(*_):os.killpg(os.getpgrp(),signal.SIGKILL)
        signal.signal(signal.SIGTERM,stop);signal.signal(signal.SIGALRM,stop)
        ctypes.CDLL(None).prctl(1,signal.SIGTERM)
        if args.owner and os.getppid()!=args.owner:stop()
        signal.alarm(150);faulthandler.dump_traceback_later(60,repeat=True)
        resource.setrlimit(resource.RLIMIT_AS,(2*1024**3,2*1024**3))
        spec=next(s for s in selected_specs if s['name']==args.worker)
        if args.force_execute:spec['execute']=True
        try:row=run(spec,args.output)
        except Exception as exc:
            traceback.print_exc();row={'name':spec['name'],'group':spec['group'],'status':'ERROR','reason':f'{type(exc).__name__}: {exc}'}
        write(args.output/'result.json',row);return
    ready_names=None
    if args.ready_replay:
        previous=json.loads(args.ready_replay.read_text())
        ready_names={row['name'] for row in previous if row['status']=='COMPILED'
            and len(row.get('plan',[]))==4 and all(a['readiness']=='READY' for a in row['plan'])}
    rows=[]
    for spec in selected_specs:
        if args.filter not in spec['name']:continue
        if ready_names is not None and spec['name'] not in ready_names:continue
        directory=args.output/spec['name'];directory.mkdir(exist_ok=True)
        cmd=[sys.executable,str(Path(__file__).resolve()),'--output',str(directory),'--worker',spec['name'],'--owner',str(os.getpid())]
        if ready_names is not None or args.force_execute:cmd.append('--force-execute')
        if args.valid_expansion:cmd.append('--valid-expansion')
        if args.router_controls:cmd.append('--router-controls')
        with (directory/'worker.log').open('wb') as log:
            process=subprocess.Popen(cmd,start_new_session=True,stdin=subprocess.DEVNULL,stdout=log,stderr=subprocess.STDOUT)
            try:code=process.wait(timeout=150)
            except subprocess.TimeoutExpired:os.killpg(process.pid,signal.SIGKILL);code=process.wait()
        row=json.loads((directory/'result.json').read_text()) if code==0 else {'name':spec['name'],'group':spec['group'],'status':'TIMEOUT' if code==-9 else 'WORKER_FAILED','reason':f'exit {code}'}
        rows.append(row);write(args.output/'results.json',rows)
        print(row['name'],row['status'],str(row.get('reason') or '')[:130],flush=True)


if __name__=='__main__':main()
