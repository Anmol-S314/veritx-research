#!/usr/bin/env python3
"""Execute shipped presets and bounded topology/size witnesses, never live drafts.

Each case gets an owned process group, a 240s wall deadline and 2GiB address
space. Inputs, certificate, plan, simulator files and outcomes remain local.
Network numbers are consumption-time reverified; system numbers retain their
own backend/fidelity. This is a finite configuration sweep, not all possible
parameter combinations or a performance/robustness comparison.
"""
from __future__ import annotations

import argparse
from dataclasses import replace
from functools import partial
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
from veritx_dse.core.paths import REPO
from veritx_dse.application.presets import (
    _typed_request, build_versioned_preset_request, build_typed_preset_request,
    preset_catalog,
)
from veritx_dse.model.compile_model import DepKind, Dependency, DependencyGraph
from veritx_dse.model.topology_intent import (
    ConcentratedMeshIntent, ExplicitTopologyIntent, FatTreeIntent, FlatFlyIntent,
    GecMode, GecTopologyIntent, MeshIntent, StructuredTopologyIntent, TorusIntent,
)

QUESTIONS = ('NETWORK_COMPLETION', 'SYSTEM_MAKESPAN',
             'COMMUNICATION_EXPOSURE', 'PER_RANK_COMPLETION')


def srota(side, concentration, mode='row', *, telemetry=True, sidebuf=True, mecs=True):
    base = build_typed_preset_request('srota32_plane_c' if mode == 'plane_c' else 'srota32')
    count = side * side * concentration
    modes = {'row': (('row',), 'none', ()),
             'rowcol': (('row', 'column'), 'shape', ()),
             'rank': (('row', 'column', 'valiant'), 'rank', ()),
             'islands': (('row', 'column'), 'shape', (1,)),
             'plane_c': (('row', 'column'), 'shape', ())}
    shapes, policy, islands = modes[mode]
    from veritx_dse.model.srota_intent import SrotaIntent
    topology = SrotaIntent(side_length=side, concentration=concentration,
        mecs_row=mecs, mecs_col=mecs, drop_latency=1,
        planes=frozenset(('d', 'c', 't') if mode == 'plane_c' else ('d', 't') if telemetry else ('d',)),
        island_columns=islands, path_shapes=frozenset(shapes), vc_policy=policy,
        sidebuf_enable=sidebuf, sidebuf_watermark=6 if sidebuf else None,
        tel_period=4, tel_latency=8)
    workload = replace(base.workload, tp=count,
        collectives=tuple(replace(c, payload_bytes=count * 128) for c in base.workload.collectives))
    return replace(base, workload=workload, agents=(replace(base.agents[0], count=count),),
                   topology=topology)


def torus(side):
    base = build_typed_preset_request('torus25')
    count = side * side
    return replace(base, topology=TorusIntent(side, 1),
        agents=(replace(base.agents[0], count=count),),
        workload=replace(base.workload, tp=count,
            collectives=tuple(replace(c, payload_bytes=count * 128) for c in base.workload.collectives)))


def legacy_carrier(preset):
    # Explicit test workload, NOT an assertion that v2 implied these bytes/TP.
    from veritx_dse.model.compile_model import migrate_v2_to_v3
    from veritx_dse.model.compile_request_v4 import migrate_v3_to_v4
    from veritx_dse.application.presets import _typed_workload
    v3 = migrate_v2_to_v3(build_versioned_preset_request(preset)[0], collective_specs=[])
    return migrate_v3_to_v4(replace(v3, workload=_typed_workload(2)))


def preset_request(name):
    return build_versioned_preset_request(name)[0]


def cases():
    out = {'preset__' + p['preset_id']: partial(preset_request, p['preset_id'])
           for p in preset_catalog()}
    for p in ('mesh4', 'mesh4_hbm', 'mesh4_wide128', 'cmesh16'):
        out['legacy_carrier__' + p] = partial(legacy_carrier, p)
    for side, c in ((2, 4), (4, 2), (4, 4), (5, 2), (6, 2), (8, 2), (8, 4)):
        for mode in ('row', 'rowcol', 'rank', 'islands', 'plane_c'):
            out[f'srota__k{side}_c{c}_e{side*side*c}_{mode}'] = partial(srota, side, c, mode)
    out['srota__k8_c1_invalid'] = partial(srota, 8, 1)
    out['srota__k4_c4_noT'] = partial(srota, 4, 4, telemetry=False)
    out['srota__k4_c4_noSidebuf'] = partial(srota, 4, 4, sidebuf=False)
    out['srota__k4_c4_noMECS'] = partial(srota, 4, 4, mecs=False)
    out.update({
        'mesh__e64': partial(_typed_request, MeshIntent(8, 1), endpoints=64, tp=64),
        'cmesh__e64': partial(_typed_request, ConcentratedMeshIntent(4, 4), endpoints=64, tp=64),
        'torus__k7_e49': partial(torus, 7),
        'torus__k8_e64_even_tie': partial(torus, 8),
        'torus__k9_e81': partial(torus, 9),
        'flatfly__k4_n3_e64': partial(_typed_request, FlatFlyIntent(4, 3, 1), endpoints=64, tp=64),
        'flatfly__k4_n4_e256': partial(_typed_request, FlatFlyIntent(4, 4, 1), endpoints=64, tp=64),
        'flatfly__k2_n6_e64_limit': partial(_typed_request, FlatFlyIntent(2, 6, 1), endpoints=64, tp=64),
        'fattree__k4_l3_e64': partial(_typed_request, FatTreeIntent(4, 3), endpoints=64, tp=64),
        'qtree__k4_t3_e64': partial(_typed_request, StructuredTopologyIntent('qtree', {'radix':4,'tiers':3}), endpoints=64, tp=64),
        'tree4__k4_t3_e64': partial(_typed_request, StructuredTopologyIntent('tree4', {'radix':4,'tiers':3}), endpoints=64, tp=64),
        'dragonfly__k8_g8_e64': partial(_typed_request, StructuredTopologyIntent('dragonfly', {'radix':8,'group_count':8}), endpoints=64, tp=64),
        'fat_tree__k4_t3_e64': partial(_typed_request, StructuredTopologyIntent('fat_tree', {'radix':4,'tiers':3}), endpoints=64, tp=64),
        'flattened_butterfly__k4_n3_e64': partial(_typed_request, StructuredTopologyIntent('flattened_butterfly', {'radix':4,'dimensions':3}), endpoints=64, tp=64),
    })
    for mode, o, d in ((GecMode.MESH, None, None), (GecMode.EXPRESS, 7, 1),
                      (GecMode.MULTIDROP, 1, 7), (GecMode.HYBRID, 1, 7)):
        topo = GecTopologyIntent(mode=mode, grid_side_length=8, concentration=1,
            express_channel_groups_per_dimension=o, destinations_per_express_channel=d)
        out['gec__' + mode.value + '_e64'] = partial(_typed_request, topo, endpoints=64, tp=64)
    from veritx_dse.model import topology_ir
    links = [[r, r+1] for r in range(64) if r % 8 != 7] + [[r,r+8] for r in range(56)]
    graph = topology_ir.from_dict({'name':'explicit64','kind':'custom','nodes':64,
        'links':links,'link_attrs':{'bandwidth_GBs':50.0,'latency_ns':500.0}})
    out['explicit__e64'] = partial(_typed_request, ExplicitTopologyIntent(graph), endpoints=64, tp=64)
    return out


def save(path, data):
    tmp = path.with_suffix('.tmp')
    tmp.write_text(json.dumps(data, indent=2, default=str))
    tmp.replace(path)


def evaluate(name, directory, backend_timeout, *, network_only=False):
    from veritx_dse.application.fabric_compiler import FabricCompiler
    from veritx_dse.application.evaluation_question import EvaluationQuestion
    from veritx_dse.application.federated_evaluator import (
        BookSimRunOptions, AstraRunOptions, evaluate_federated,
    )
    from veritx_dse.backend.registry import default_backend_registry
    from veritx_dse.core.errors import VeritXError
    row = {'name':name, 'analyses':[]}
    started = time.monotonic()
    try:
        request = cases()[name]()
        save(directory / 'request.json', request.to_dict())
        row.update(design_hash=request.design_hash(), agents=sum(a.count for a in request.agents),
                   active_tp=request.workload.tp)
        compiled = FabricCompiler().compile(request)
        row.update(compile=compiled.status, stopped_at=compiled.stopped_at_stage, reason=compiled.error)
        if compiled.certificate:
            save(directory / 'certificate.json', compiled.certificate.to_dict())
            row['certificate'] = compiled.certificate.overall
        if compiled.status != 'COMPILED':
            return row
        row.update(routers=compiled.bundle.topology.router_count,
                   channels=len(compiled.bundle.topology.channels),
                   shared_wires=len(compiled.bundle.topology.shared_links))
        if request.to_dict()['schema_version'] == 2:
            row['status'] = 'LEGACY_COMPILE_ONLY'
            row['reason'] = 'Frozen v2 has no canonical workload execution; explicit carrier copies are separate cases.'
            return row
        result = evaluate_federated(compiled,
            tuple(EvaluationQuestion[q] for q in (QUESTIONS[:1] if network_only else QUESTIONS)),
            default_backend_registry(booksim_bin=REPO/'third_party/booksim2/src/booksim', repo_root=REPO),
            booksim_options=BookSimRunOptions(binary=REPO/'third_party/booksim2/src/booksim',
                repo_root=REPO, network_clock_hz=1_000_000_000, timeout_s=backend_timeout, seed=0),
            astra_options=AstraRunOptions(repo_root=REPO, timeout_s=backend_timeout),
            run_dir=str(directory / 'execution'))
        row.update(status=result.status, analyses=[a.to_dict() for a in result.analyses])
        net = result.network_evaluation
        if net is not None and net.status == 'EVALUATED':
            from veritx_dse.application.authenticated_evaluation import (
                authenticate_backend_evaluation, verify_authenticated_backend_evaluation,
            )
            from veritx_dse.workload.intent_lowering import lower_compile_workload
            from veritx_dse.optimization.metric_registry import CERTIFIED_METRIC_REGISTRY
            proof = authenticate_backend_evaluation(compilation=compiled,
                workload=lower_compile_workload(request).graph, verified_result=net.performance_result,
                evidence_path=net.evidence_path, producer_identity=net.producer_identity)
            claims = verify_authenticated_backend_evaluation(request, proof)
            row['verified_network'] = {'completion_cycles':CERTIFIED_METRIC_REGISTRY.extract_all(claims.verified_result)['completion_cycles'],
                'profile':claims.backend_profile, 'fidelity':claims.execution_fidelity,
                'evidence_path':str(claims.evidence_ref.path), 'evidence_sha256':claims.evidence_ref.sha256}
    except (ValueError, VeritXError) as exc:
        row.update(status='REFUSED', reason=f'{type(exc).__name__}: {exc}')
    finally:
        row['seconds'] = round(time.monotonic()-started, 3)
    return row


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--filter', default='')
    parser.add_argument('--backend-timeout', type=int, default=60)
    parser.add_argument('--network-only', action='store_true', help='Run only standalone network completion; not the system analyses.')
    parser.add_argument('--resume', action='store_true', help='Keep completed cases in this output directory; use a fresh directory after changing code.')
    parser.add_argument('--owner-pid', type=int, help=argparse.SUPPRESS)
    parser.add_argument('--worker', help=argparse.SUPPRESS)
    args = parser.parse_args()
    args.output = args.output.resolve()
    args.output.mkdir(parents=True, exist_ok=True)
    if args.worker:
        import ctypes
        import faulthandler
        def stop_owned_group(*_):
            os.killpg(os.getpgrp(), signal.SIGKILL)
        signal.signal(signal.SIGTERM, stop_owned_group)
        signal.signal(signal.SIGALRM, stop_owned_group)
        ctypes.CDLL(None).prctl(1, signal.SIGTERM)
        if args.owner_pid and os.getppid() != args.owner_pid:
            stop_owned_group()
        signal.alarm(240)
        faulthandler.dump_traceback_later(90, repeat=True)
        resource.setrlimit(resource.RLIMIT_AS, (2*1024**3, 2*1024**3))
        try:
            row = evaluate(args.worker, args.output, args.backend_timeout, network_only=args.network_only)
        except Exception as exc:
            traceback.print_exc()
            row = {'name':args.worker,'status':'ERROR','reason':f'{type(exc).__name__}: {exc}'}
        save(args.output / 'result.json', row)
        return
    rows = []
    for name in cases():
        if args.filter not in name:
            continue
        directory = args.output / name
        directory.mkdir(exist_ok=True)
        if args.resume and (directory / 'result.json').is_file():
            rows.append(json.loads((directory / 'result.json').read_text()))
            save(args.output / 'results.json', rows)
            continue
        command = [sys.executable, str(Path(__file__).resolve()), '--output', str(directory),
                   '--worker', name, '--owner-pid', str(os.getpid()),
                   '--backend-timeout', str(args.backend_timeout)]
        if args.network_only:
            command.append('--network-only')
        with (directory / 'worker.log').open('wb') as logfile:
            process = subprocess.Popen(command, stdout=logfile, stderr=subprocess.STDOUT,
                                       start_new_session=True, stdin=subprocess.DEVNULL)
            try:
                code = process.wait(timeout=240)
                row = json.loads((directory / 'result.json').read_text()) if code == 0 else {
                    'name':name,'status':'TIMEOUT' if code == -signal.SIGKILL else 'WORKER_FAILED',
                    'reason':f'exit {code}; see worker.log for stack samples'}
            except subprocess.TimeoutExpired:
                os.killpg(process.pid, signal.SIGKILL)
                process.wait()
                row = {'name':name,'status':'TIMEOUT','reason':'240s case deadline; no metrics claimed'}
        save(directory / 'result.json', row)
        rows.append(row)
        save(args.output / 'results.json', rows)
        net = row.get('verified_network') or {}
        states = ','.join(a['question'] + ':' + a['status'] for a in row.get('analyses', []))
        print(name, row.get('compile'), row.get('status'), net.get('completion_cycles'), states,
              row.get('reason') or '', flush=True)


if __name__ == '__main__':
    main()
