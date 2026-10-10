"""Native diagnostic overlay and independently tampered token/credit ledgers."""
from dataclasses import replace
from fractions import Fraction
from pathlib import Path
import json
import os
import shutil
import subprocess
import pytest

from veritx_dse.backend.native_srota_regulator import (
    prepare_native_regulator, replay_native_ledger, run_native_regulator,
    native_source_inventory, load_native_regulator_evidence, parse_native_srota_stats)
from veritx_dse.backend.booksim_projection import prepare_booksim_input

REPO = Path(__file__).resolve().parents[4]


def parents(hotspot=False):
    from veritx_dse.application.presets import build_typed_preset_request, _typed_workload
    from veritx_dse.application.fabric_compiler import FabricCompiler
    from veritx_dse.application.capability_truth import _parents_from_bundle
    request = replace(build_typed_preset_request('srota32_islands'), workload=_typed_workload(32,payload_bytes=32))
    compilation = FabricCompiler().compile(request)
    assert compilation.status == 'COMPILED', compilation.error
    result = _parents_from_bundle(compilation.bundle,request)
    if hotspot:
        # Explicit canonical P2P demand: many sources to ONE island local port,
        # one class. Not inferred memory/collective/reduction semantics.
        from veritx_dse.workload.graph import WorkloadGraph, OperationNode, KIND_P2P, p2p_detail
        from veritx_dse.workload.messages import LogicalMessageArtifactV3
        from veritx_dse.workload.traffic import PhysicalTrafficArtifactV3
        ops=tuple(OperationNode(operation_id=f'p{n}_{src}',kind=KIND_P2P,
                               detail=p2p_detail(src_rank=src,dst_rank=2,payload_bytes=1,
                                                 role='TRANSFER',participant_count=32))
                  for n in range(8) for src in range(32) if src!=2)
        graph=WorkloadGraph(parallelism=compilation.bundle.inventory.parallelism,
                            participant_count=32,operations=ops)
        logical=LogicalMessageArtifactV3(graph=graph,traffic_class_by_operation=tuple(
            (op.operation_id,'DEFAULT') for i,op in enumerate(ops)))
        b=compilation.bundle
        traffic=PhysicalTrafficArtifactV3(logical=logical,resolved_fabric=b.resolved_fabric,
            mapping=b.mapping,attachment=b.attachment,inventory=b.inventory,packet_format=b.packet_format)
        result=replace(result,physical_traffic=traffic)
    return result


def experiment(p, bypass=False, horizon=32768, original=False, depth=8):
    from veritx_dse.backend.booksim_projection import trace_class_map
    base=prepare_booksim_input(p,seed=0)
    schedule=tuple(int(row.split()[0]) for row in base.trace_text.splitlines()) if original else (0,)*base.expected_packets
    return prepare_native_regulator(p,rates={c:Fraction(1,64) if c!='fast' else Fraction(1,4)
                                           for c in trace_class_map(p.physical_traffic)},
                                    burst=64,seed=0,bypass=bypass,arrival_cycles=schedule,horizon=horizon,sidebuf_depth=depth)


def test_overlay_is_separate_retimed_identity_preserving_canonical_packets():
    p=parents();base=prepare_booksim_input(p,seed=0);e=experiment(p)
    assert e.parent_prepared_id==base.prepared_id()
    assert e.prepared.prepared_id()!=base.prepared_id()
    assert prepare_booksim_input(p,seed=0).prepared_id()==base.prepared_id()
    assert [r.split()[1:] for r in e.prepared.trace_text.splitlines()]==[r.split()[1:] for r in base.trace_text.splitlines()]
    assert e.identity()!=experiment(p,bypass=True).identity()
    assert not e.identity_dict()['qualification']


@pytest.mark.parametrize('case',['missing_class','float','nondyadic','zero','bool_burst','bool_seed','bad_horizon','missing_cycle','bool_cycle','unsorted'])
def test_explicit_contract_rejects_unbounded_ambiguous_inputs(case):
    p=parents();base=prepare_booksim_input(p,seed=0)
    kw=dict(rates={'DEFAULT':Fraction(1,64)},burst=4,seed=0,bypass=False,arrival_cycles=(0,)*base.expected_packets,horizon=32768,sidebuf_depth=8)
    if case=='missing_class':kw['rates']={}
    elif case=='float':kw['rates']={'DEFAULT':0.5}
    elif case=='nondyadic':kw['rates']={'DEFAULT':Fraction(1,3)}
    elif case=='zero':kw['rates']={'DEFAULT':Fraction(0)}
    elif case=='bool_burst':kw['burst']=True
    elif case=='bool_seed':kw['seed']=True
    elif case=='bad_horizon':kw['horizon']=0
    elif case=='missing_cycle':kw['arrival_cycles']=(0,)
    elif case=='bool_cycle':kw['arrival_cycles']=(True,)*base.expected_packets
    else:kw['arrival_cycles']=(1,)+(0,)*(base.expected_packets-1)
    with pytest.raises(ValueError):prepare_native_regulator(p,**kw)


def ledger():
    # Hand-derived two-class sequence: two local ports share class 0 tokens;
    # allocation loss refunds at same-step END; captured flit gets one credit.
    events=[(0,'begin',1,-1,-1,2,1,0,0),
            (0,'init',0,-1,-1,.25,2,0,0),(0,'init',1,-1,-1,.5,2,0,0),
            (1,'step_begin',-1,-1,-1,0,0,0,0),
            (1,'refill',0,-1,-1,2,2,1,0),(1,'refill',1,-1,-1,2,2,1,0),
            (1,'arrive',0,10,0,0,0,0,0),(1,'reserve',0,10,0,2,1,0,0),
            (1,'arrive',0,11,1,0,0,0,0),(1,'reserve',0,11,1,1,0,0,0),
            (1,'spend',0,10,0,0,0,0,0),(1,'grant',0,10,0,0,0,0,0),
            (1,'credit',-1,10,0,0,0,0,0),(1,'depart',-1,10,0,0,0,0,0),
            (1,'capture',-1,11,1,0,0,0,1),(1,'credit',-1,11,1,0,0,0,1),
            (1,'refund',0,11,1,0,1,0,1),(1,'step_end',-1,-1,-1,0,0,0,1),
            (2,'step_begin',-1,-1,-1,0,0,0,1),
            (2,'refill',0,-1,-1,1,1.25,1,1),(2,'refill',1,-1,-1,2,2,1,1),
            (2,'reserve',0,11,1,1.25,.25,0,1),(2,'spend',0,11,1,.25,.25,0,1),
            (2,'grant',0,11,1,0,0,0,1),(2,'drain',-1,11,1,0,0,0,0),
            (2,'depart_buffered',-1,11,1,0,0,0,0),(2,'step_end',-1,-1,-1,0,0,0,0),
            (2,'end',-1,-1,-1,0,0,0,0)]
    return '\n'.join('SrotaLedger 0 '+str(i)+' '+' '.join(map(str,row)) for i,row in enumerate(events))


def replay(text):
    return replay_native_ledger(text,rates=(Fraction(1,4),Fraction(1,2)),burst=2,depth=1,router_count=1)


@pytest.mark.parametrize('case', ['duplicate_step', 'within_step_cycle', 'duplicate_refill', 'missing_refill'])
def test_fixed_cycle_steps_require_fresh_complete_refills(case):
    rows = [row.split() for row in ledger().splitlines()]
    if case == 'duplicate_step':
        # Reviewer counterexample: previous cycle's refill markers cannot cover
        # an extra empty same-cycle step, even with contiguous sequence numbers.
        rows[-1:-1] = [['SrotaLedger', '0', '0', '2', event, '-1', '-1', '-1', '0', '0', '0', '0']
                      for event in ('step_begin', 'step_end')]
    elif case == 'within_step_cycle':
        rows[26][3] = '3'  # step_end must retain its step_begin cycle
        rows[27][3] = '3'
    elif case == 'duplicate_refill':
        rows.insert(6, rows[5].copy())
    else:
        rows.pop(20)  # class 1 must refill in this step, not a previous step
    for seq, row in enumerate(rows):
        row[2] = str(seq)
    with pytest.raises(ValueError):
        replay('\n'.join(' '.join(row) for row in rows))


def test_hand_derived_shared_bucket_refund_credit_and_class_isolation():
    counts=replay(ledger())
    assert counts['reserve']==3 and counts['spend']==2 and counts['refund']==1
    assert counts['credit']==2 and counts['capture']==counts['drain']==1
    assert counts['classes'][0]==dict(arrive=2,grant=2,defer_cycles=0)
    assert counts['classes'][1]==dict(arrive=0,grant=0,defer_cycles=0)


@pytest.mark.parametrize('case',['truncated','missing','duplicate','balance','negative','wrong_class','late_refund','credit','occupancy','unknown','nonfinite','cycle','init','missing_refill','second_credit'])
def test_tampered_native_evidence_never_passes(case):
    rows=[r.split() for r in ledger().splitlines()]
    if case=='truncated':rows=rows[:-1]
    elif case=='missing':rows.pop(8)
    elif case=='duplicate':rows.insert(8,rows[8])
    elif case=='balance':rows[7][9]='1.5'
    elif case=='negative':rows[7][9]='-1'
    elif case=='wrong_class':rows[7][5]='1'
    elif case=='late_refund':rows[16][3]='2'
    elif case=='credit':rows[15][6]='10'
    elif case=='occupancy':rows[14][11]='2'
    elif case=='unknown':rows[7][4]='ignored'
    elif case=='nonfinite':rows[7][8]='nan'
    elif case=='cycle':rows[20][3]='1'
    elif case=='init':rows[2][5]='0'
    elif case=='missing_refill':rows[20][4]='step_end'
    else:rows[25][4]='credit'
    with pytest.raises(ValueError):replay('\n'.join(' '.join(row) for row in rows))


@pytest.fixture(scope='module')
def native_binary(tmp_path_factory):
    override=os.environ.get('VERITX_SROTA_DIAGNOSTIC_BINARY')
    if override:
        binary=Path(override);assert binary.is_file();return binary
    # Acceptance must build/run, NEVER skip missing build tools.
    assert all(shutil.which(tool) for tool in ('make','g++','flex','bison'))
    build=tmp_path_factory.mktemp('native-producer');src=REPO/'third_party/booksim2/src'
    for relative,_,_ in native_source_inventory(src)['files']:
        dest=build/relative;dest.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(src/relative,dest)
    outcome=subprocess.run(['make','-j2'],cwd=build,capture_output=True,text=True,timeout=240)
    (build/'build.log').write_text(outcome.stdout+outcome.stderr)
    assert outcome.returncode==0,outcome.stderr[-2000:]
    assert native_source_inventory(src)==native_source_inventory(build)
    return build/'booksim'


def test_live_native_throttle_bypass_refund_sidebuffer_and_conservation(tmp_path,native_binary):
    p=parents(hotspot=True);src=REPO/'third_party/booksim2/src'
    inventory=tmp_path/'source.json';inventory.write_text(json.dumps(native_source_inventory(src)))
    results=[]
    for bypass in (False,True):
        e=experiment(p,bypass=bypass)
        results.append(run_native_regulator(e,parents=p,binary=native_binary,source_root=src,
                       source_inventory=inventory,run_dir=tmp_path/str(bypass)))
    regulated,bypass=results
    assert regulated['stats']['completion_cycles']>bypass['stats']['completion_cycles']
    for result in results:
        assert result['stats']['flits_injected']==result['stats']['flits_accepted']==248
        assert result['counts']['capture']==result['counts']['drain']>0
        assert result['counts']['credit']==result['counts']['depart']+result['counts']['depart_buffered']
        assert result['qualification'] is False
    assert regulated['counts']['refund']>0
    assert regulated['counts']['classes'][0]['defer_cycles']>0
    e=experiment(p)
    reloaded=load_native_regulator_evidence(regulated,e,parents=p,binary=native_binary,
        source_root=src,source_inventory=inventory,run_dir=tmp_path/'False')
    assert reloaded['evidence_id']==regulated['evidence_id']
    for name, expected_bytes in e.prepared.files().items():
        retained = tmp_path / 'False' / name
        for mode in ('tampered', 'missing'):
            if mode == 'tampered':
                retained.write_bytes(b'tampered\n')
            else:
                retained.unlink()
            try:
                with pytest.raises(ValueError, match='retained prepared input'):
                    load_native_regulator_evidence(regulated, e, parents=p, binary=native_binary,
                        source_root=src, source_inventory=inventory, run_dir=tmp_path/'False')
            finally:
                retained.write_bytes(expected_bytes)
        assert load_native_regulator_evidence(regulated, e, parents=p, binary=native_binary,
            source_root=src, source_inventory=inventory, run_dir=tmp_path/'False')['evidence_id'] == regulated['evidence_id']
    for tamper in ('experiment_id','binary_sha256','source_inventory_sha256','stdout_sha256'):
        altered=dict(regulated);altered[tamper]='foreign'
        with pytest.raises(ValueError,match='recomputed'):
            load_native_regulator_evidence(altered,e,parents=p,binary=native_binary,
                source_root=src,source_inventory=inventory,run_dir=tmp_path/'False')
    full=run_native_regulator(experiment(p,depth=1),parents=p,binary=native_binary,
        source_root=src,source_inventory=inventory,run_dir=tmp_path/'full')
    assert full['counts']['full']>0 and full['counts']['capture']==full['counts']['drain']
    baseline=run_native_regulator(experiment(p,original=True),parents=p,binary=native_binary,
        source_root=src,source_inventory=inventory,run_dir=tmp_path/'baseline')
    assert baseline['stats']['flits_injected']==baseline['stats']['flits_accepted']==248
    with pytest.raises(ValueError,match='BOUNDED_INCOMPLETE'):
        run_native_regulator(experiment(p,horizon=2),parents=p,binary=native_binary,source_root=src,
                             source_inventory=inventory,run_dir=tmp_path/'incomplete')
    inventory.write_text('{}')
    with pytest.raises(ValueError,match='inventory'):
        run_native_regulator(experiment(p),parents=p,binary=native_binary,source_root=src,
                             source_inventory=inventory,run_dir=tmp_path/'tamper')


@pytest.mark.parametrize('phase', ['before_execution', 'after_execution'])
@pytest.mark.parametrize('name', ['config.cfg', 'workload.trace'])
@pytest.mark.parametrize('mode', ['tampered', 'missing'])
def test_execution_refuses_retained_input_drift_before_evidence(tmp_path, monkeypatch, phase, name, mode):
    p = parents(); e = experiment(p); src = REPO / 'third_party/booksim2/src'
    inventory = tmp_path / 'source.json'
    inventory.write_text(json.dumps(native_source_inventory(src)))
    binary = tmp_path / 'binary'; binary.write_bytes(b'diagnostic test producer')
    directory = tmp_path / 'run'
    called = []

    def corrupt():
        target = directory / name
        if mode == 'tampered':
            target.write_bytes(b'tampered\n')
        else:
            target.unlink()

    if phase == 'before_execution':
        original = type(e.prepared).prepare_directory
        def altered_prepare(self, path):
            written = original(self, path)
            corrupt()
            return written
        monkeypatch.setattr(type(e.prepared), 'prepare_directory', altered_prepare)

    def execute(*args, **kwargs):
        called.append(True)
        corrupt()
        return subprocess.CompletedProcess(args[0], 0, '', '')

    monkeypatch.setattr('veritx_dse.backend.native_srota_regulator.subprocess.run', execute)
    with pytest.raises(ValueError, match='retained prepared input'):
        run_native_regulator(e, parents=p, binary=binary, source_root=src,
                             source_inventory=inventory, run_dir=directory)
    assert bool(called) == (phase == 'after_execution')
    assert not (directory / 'diagnostic-evidence.json').exists()


def test_synthetic_class_one_spend_does_not_change_class_zero_balance():
    rows=[row.split() for row in ledger().splitlines()]
    # Class 0 has .25 after two departures; class 1 still has its OWN 2.
    injected=[(2,'arrive',1,12,2,0,0,0,0),
              (2,'reserve',1,12,2,2,1,0,0),
              (2,'spend',1,12,2,1,1,0,0),
              (2,'grant',1,12,2,0,0,0,0),
              (2,'credit',-1,12,2,0,0,0,0),
              (2,'depart',-1,12,2,0,0,0,0)]
    rows[-2:-2]=[['SrotaLedger','0','0',*map(str,event)] for event in injected]
    for i,row in enumerate(rows):row[2]=str(i)
    result=replay('\n'.join(' '.join(row) for row in rows))
    assert result['spend']==3
    assert result['classes'][1]==dict(arrive=1,grant=1,defer_cycles=0)


def telemetry():
    return ('SrotaStats: sidebuf routers=1 storage_flits=4 alloc_loss=1 '
            'sb_fill=1 sb_drain=1 sb_full_reject=0 sb_peak=1 '
            'sb_mean_occ_per_router=0.5 sb_full_router_cycles=1 '
            'sb_watermark_router_cycles=1 router_cycles=2  (whole run, incl. warm-up)\n'
            'SrotaStats: island class=0 arrive=2 grant=2 deferred_flits=1 defer_flit_cycles=3')


def test_strict_typed_native_telemetry_parser():
    result=parse_native_srota_stats(telemetry())
    assert result['sidebuf']['sb_fill']==1
    assert result['island_rows']==[(0,2,2,1,3)]


@pytest.mark.parametrize('case',['duplicate_side','duplicate_class','malformed','negative','nonfinite','unknown','missing'])
def test_telemetry_missing_malformed_duplicate_refuses(case):
    text=telemetry()
    if case=='duplicate_side':text+='\n'+text.splitlines()[0]
    elif case=='duplicate_class':text+='\n'+text.splitlines()[1]
    elif case=='malformed':text=text.replace('grant=2','grant=true')
    elif case=='negative':text=text.replace('sb_fill=1','sb_fill=-1')
    elif case=='nonfinite':text=text.replace('router=0.5','router=nan')
    elif case=='unknown':text+='\nSrotaStats: ignored record=1'
    else:text=text.splitlines()[0]
    with pytest.raises(ValueError):parse_native_srota_stats(text)


def test_multiclass_native_canonical_gate_is_retained():
    from veritx_dse.workload.messages import LogicalMessageArtifactV3
    from veritx_dse.workload.traffic import PhysicalTrafficArtifactV3
    p=parents(hotspot=True);old=p.physical_traffic
    logical=LogicalMessageArtifactV3(graph=old.logical.graph,
        traffic_class_by_operation=tuple((op.operation_id,'fast' if i%2 else 'slow')
                                        for i,op in enumerate(old.logical.graph.operations)))
    traffic=PhysicalTrafficArtifactV3(logical=logical,resolved_fabric=p.resolved_fabric,
        mapping=p.mapping,attachment=p.attachment,inventory=old.inventory,packet_format=p.packet_format)
    with pytest.raises(ValueError,match='ONE traffic class'):
        experiment(replace(p,physical_traffic=traffic))
