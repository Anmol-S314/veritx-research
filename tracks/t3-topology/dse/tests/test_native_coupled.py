"""Native driver phase tests; actual-engine tests require explicit local pins."""
from copy import deepcopy
from dataclasses import replace
from fractions import Fraction
import json
import os
from pathlib import Path
import subprocess
import sys
from types import SimpleNamespace

import pytest

from veritx_dse.application.fabric_compiler import FabricCompiler
from veritx_dse.application.tensor_demand import RemoteDemandPolicy
from veritx_dse.backend.native_coupled import (_prepare, _drive, _memory, run_document,
                                            NativeCoupledEvidence)
from veritx_dse.core.artifact import FrozenMap, content_id
from veritx_dse.core.errors import InvalidInput, EvidenceInvalid, UnsupportedSemantics
from veritx_dse.application.data_movement import AccessDenied
from veritx_dse.model.compile_request_v5 import CompileRequestV5
from veritx_dse.model.coupled_tensor import CoupledTensorWorkload
from veritx_dse.model.native_coupled import NativeCoupledConfig, PIN_NAMES, verify_pin
from veritx_dse.model.physical_placement import PhysicalPlacement

EXAMPLES = Path(__file__).resolve().parents[1] / 'examples'


@pytest.fixture
def doc():
    return json.loads((EXAMPLES / 'native_coupled_tensor_v5.json').read_text())


def config():
    return NativeCoupledConfig(FrozenMap({k: {'path': '/not-an-executable/' + k,
        'sha256': 'a' * 64} for k in PIN_NAMES}),
        FrozenMap(json.loads((EXAMPLES / 'native_hbm2_config.json').read_text())),
        2000, 1, 1000, 1, 4096, 4160, 32, 2, 4, 64, 100000)


def parents(doc):
    c = FabricCompiler().compile(CompileRequestV5.from_dict(doc['design']))
    assert c.status == 'COMPILED', c.error
    return c, CoupledTensorWorkload.from_dict(doc['workload']), RemoteDemandPolicy.from_dict(doc['transport']), PhysicalPlacement.from_dict(doc['placement'])


def rebind(doc):
    doc['design'].pop('design_hash', None)
    doc['design']['access_policy'].pop('policy_hash', None)
    c = FabricCompiler().compile(CompileRequestV5.from_dict(doc['design']))
    assert c.status == 'COMPILED', c.error
    doc['design'] = c.request.to_dict()
    doc['workload']['demand'].update(design_hash=c.request.design_hash(), system_hash=c.compiled_system.system_hash())
    doc['placement']['resource_graph_id'] = c.compiled_system.resource_graph.artifact_id()


def instant(row):
    return Fraction(row['time_s']['numerator'], row['time_s']['denominator'])


class Net:
    """Synthetic deterministic clock oracle, NOT native execution evidence."""
    def __init__(self):
        self.num_nodes = 4; self.cycle = 0; self.pid = 0; self.rows = {}; self.constructed = 0; self.retired_flits = 0
    def inject(self, src, dst, size):
        pid = self.pid; self.pid += 1; self.constructed += size
        self.rows[pid] = (src, dst, self.cycle, size)
        return pid
    def step(self):
        self.cycle += 1; return self.cycle
    def drain(self, node):
        rows = []
        for pid, (s, d, cycle, size) in list(self.rows.items()):
            if d == node:
                rows.append(SimpleNamespace(pid=pid, src=s, dst=d, cl=0, itime=cycle, atime=self.cycle-1))
                del self.rows[pid]
                self.retired_flits += size  # counted at retirement, not derived
        return rows
    def counts(self):
        live = sum(row[3] for row in self.rows.values())
        return dict(packets=self.pid, flits_constructed=self.constructed, flits_retired=self.retired_flits,
                    tails=self.pid-len(self.rows), flits_live=live, flits_source_queued=live)


class Mem:
    def __init__(self, reject=True, duplicate=False, duplicate_sync=False):
        self.memory_ticks = 0; self.reject = reject; self.pending = []; self.count = [0, 0]
        self.duplicate = duplicate; self.duplicate_sync = duplicate_sync
    def tick(self):
        self.memory_ticks += 1
        pending, self.pending = self.pending, []
        for cb, args in pending:
            cb(*args)
            if self.duplicate: cb(*args)
    def send(self, a, t, s, src, ingress, cb):
        if self.reject:
            self.reject = False; return False
        self.count[t] += 1
        if t:  # synchronous native WRITE ACK seam
            cb(a, t, s)
            if self.duplicate_sync: cb(a, t, s)
        else: self.pending.append((cb, (a, t, s)))
        return True
    def get_stats(self):
        return {'memory_system': {'total_num_read_requests': self.count[0], 'total_num_write_requests': self.count[1]}}


def drive(doc, cfg=None, mem=None, net=None):
    cfg = cfg or config()
    runtime, plan, deps, groups, trackers, auth, _text, _nodes = _prepare(*parents(doc), cfg)
    return _drive(runtime, plan, deps, groups, trackers, auth, cfg, net or Net(), mem or Mem())


def test_phase_oracle_strict_future_edges_send_false_and_sync_write(doc):
    x = drive(doc)
    assert x['status'] == 'COMPLETE'
    assert x['summary']['memory_send_backpressure'] == 1
    assert x['summary']['children_issued'] == x['summary']['children_committed'] == x['summary']['children_responded'] == 7
    assert x['summary']['children_live'] == x['summary']['host_reservations_remaining'] == 0
    assert x['read_results']['readback']['hex'] == 'aa' * 12
    assert x['authorizations'] and all(span['decision']['observed'] for a in x['authorizations'] for span in a['spans'])
    events = {}
    for row in x['ledger']:
        if 'sequence' in row: events.setdefault((row['id'], row['sequence']), {}).setdefault(row['event'], []).append(row)
    for ev in events.values():
        for name, ev_rows in ev.items():
            assert len(ev_rows) == 1, f'duplicate ledger event {name}'
        assert instant(ev['memory_accepted'][0]) > instant(ev['request_tail_retired'][0])
        assert instant(ev['response_injected'][0]) > instant(ev['memory_callback_controller_ack'][0])
        assert instant(ev['response_tail_retired'][0]) > instant(ev['response_injected'][0])
    kernel = x['compute_intervals'][0]
    t = lambda key: Fraction(kernel[key]['numerator'], kernel[key]['denominator'])
    load = next(instant(r) for r in x['ledger'] if r['event'] == 'access_complete' and r['id'] == 'load')
    assert t('start_s') >= load
    assert t('completion_s') - t('start_s') == Fraction(20, 250000000)
    write = next(r for r in x['ledger'] if r['event'] == 'request_injected' and r['access_id'] == 'write')
    assert instant(write) > t('completion_s')


@pytest.mark.parametrize('budget', [1, 2, 3, 4, 5])
def test_engine_budget_never_partially_steps_coincident_edges(doc, budget):
    x = drive(doc, replace(config(), max_engine_steps=budget))
    assert x['status'] == 'INCOMPLETE' and x['stop_reason'] == 'ENGINE_STEP_BOUND'
    assert x['summary']['native_steps'] <= budget
    assert x['summary']['children_declared'] == x['summary']['children_issued'] + x['summary']['children_source_held']
    assert x['summary']['children_issued'] == x['summary']['children_live'] + x['summary']['children_responded']


def test_non_elf_engine_is_refused_before_loading_native_library(tmp_path):
    import hashlib
    import veritx_dse.backend.native_coupled as module
    files = {}
    for name in PIN_NAMES:
        p = tmp_path / name; p.write_bytes(b'x'); files[name] = p
    # A source manifest must itself be a valid, nonempty pin list.
    manifest = tmp_path / 'manifest.json'
    manifest.write_text(json.dumps({'files': [{'path': str(files['booksim_executable']),
        'sha256': hashlib.sha256(b'x').hexdigest()}]}))
    files['booksim_source_manifest'] = files['ramulator_source_manifest'] = manifest
    cfg = replace(config(), files=FrozenMap({name: {'path': str(p),
        'sha256': hashlib.sha256(p.read_bytes()).hexdigest()} for name, p in files.items()}))
    with pytest.raises(UnsupportedSemantics, match='ELF'):
        _memory(cfg)
    assert module._loaded_memory is None


def test_native_coverage_is_not_silently_absent_in_ci():
    if os.environ.get('CI') and not os.environ.get('VERITX_NATIVE_COUPLED_CONFIG'):
        pytest.fail('CI must set VERITX_NATIVE_COUPLED_CONFIG; actual-engine native coverage would silently skip')


def test_historical_native_pid_reuse_fails_closed(doc):
    class ReusedPID(Net):
        def inject(self, src, dst, size):
            super().inject(src, dst, size)
            return 0
    with pytest.raises(EvidenceInvalid, match='PID reused'):
        drive(doc, net=ReusedPID())


def test_duplicate_callback_fails_closed(doc):
    with pytest.raises(EvidenceInvalid, match='callback'):
        drive(doc, mem=Mem(duplicate=True))
    with pytest.raises(EvidenceInvalid, match='callback'):
        drive(doc, mem=Mem(duplicate_sync=True))


def test_incomplete_horizon_has_no_unfinished_mutation(doc):
    doc['workload']['horizon_cycles'] = 1
    x = drive(doc)
    assert x['status'] == 'INCOMPLETE'
    assert x['summary']['children_committed'] == 0
    assert x['final_images'] == doc['workload']['initial_images']
    assert x['summary']['children_issued'] == x['summary']['children_live']
    assert x['authorizations'] and not any(span['decision']['observed'] for a in x['authorizations'] for span in a['spans'])


@pytest.mark.parametrize('change', [dict(tx_bytes=64), dict(host_reservation_slots=True),
    dict(max_engine_steps=1000001), dict(window_start=4099), dict(booksim_period_ps_num=4000, booksim_period_ps_den=2)])
def test_config_refuses_bad_bounds(change):
    with pytest.raises(InvalidInput): replace(config(), **change)


def test_complete_file_pin_tamper_and_symlink_refusal(tmp_path):
    p = tmp_path / 'input'; p.write_bytes(b'input')
    import hashlib
    pin = {'path': str(p), 'sha256': hashlib.sha256(b'input').hexdigest()}
    verify_pin(pin); p.write_bytes(b'changed')
    with pytest.raises(EvidenceInvalid): verify_pin(pin)
    link = tmp_path / 'link'; link.symlink_to(p)
    with pytest.raises(InvalidInput): verify_pin({**pin, 'path': str(link)})
    d = config().to_dict(); d['extra'] = 0
    with pytest.raises(InvalidInput): NativeCoupledConfig.from_dict(d)
    d = config().to_dict(); d['files'] = []
    with pytest.raises(InvalidInput): NativeCoupledConfig.from_dict(d)
    d = config().to_dict(); d['ramulator_config']['nan'] = float('nan')
    with pytest.raises(InvalidInput): NativeCoupledConfig.from_dict(d)


def test_preflight_refuses_ignored_intents_before_opening_engines(doc):
    doc['transport']['service_cycles'] = 1
    with pytest.raises(UnsupportedSemantics, match='service_cycles'): _prepare(*parents(doc), config())
    doc['transport']['service_cycles'] = 0
    with pytest.raises(InvalidInput, match='network clock'): _prepare(*parents(doc), replace(config(), booksim_period_ps_num=1))
    doc['design']['agent_intents'][0]['transaction_clock_domain'] = 'core'; rebind(doc)
    with pytest.raises(UnsupportedSemantics, match='homogeneous'): _prepare(*parents(doc), config())


def test_native_burst_padding_must_be_authorized_before_issue(doc):
    rule = doc['design']['access_policy']['rules'][0]
    rule.update(address_base=4102, address_size=20); rebind(doc)
    with pytest.raises(AccessDenied) as caught: _prepare(*parents(doc), config())
    assert caught.value.authorization['issued_children'] == 0


@pytest.fixture
def native_config():
    path = os.environ.get('VERITX_NATIVE_COUPLED_CONFIG')
    if not path:
        pytest.skip('actual engines require explicit VERITX_NATIVE_COUPLED_CONFIG pins; phase oracles are not native proof')
    return json.loads(Path(path).read_text())


def test_actual_native_synchronous_coalesced_write_callback(native_config):
    # Direct native API seam only: the coupled envelope still refuses aliases
    # and unordered overlapping writes. No coherence/reliability claim here.
    mem = _memory(NativeCoupledConfig.from_dict(native_config))
    callbacks = []
    try:
        assert mem.send(4096, 1, 4, 0, 1, lambda *args: callbacks.append(('first', args)))
        assert callbacks == []
        assert mem.send(4096, 1, 4, 0, 1, lambda *args: callbacks.append(('second', args)))
        assert callbacks == [('second', (4096, 1, 4))]
        assert mem.memory_ticks == 0
        for _ in range(1000):
            mem.tick()
            if len(callbacks) == 2:
                break
        assert callbacks[-1] == ('first', (4096, 1, 4))
        assert mem.get_stats()['memory_system']['total_num_write_requests'] == 2
    finally:
        mem.finalize()


def test_actual_native_dag_read_compute_write_readback_and_reload(doc, native_config):
    a = run_document(doc, native_config)
    x = a.to_dict()
    assert x['status'] == 'COMPLETE' and x['observed'] == {'native_network': True, 'native_memory': True}
    assert not x['scope']['qualified'] and not x['scope']['calibrated']
    assert x['summary']['native_steps'] > 0
    assert x['summary']['children_issued'] == x['summary']['children_committed'] == x['summary']['children_responded'] == 7
    assert x['native_network_counters']['packets'] == x['native_network_counters']['tails'] == 14
    assert x['native_network_counters']['flits_constructed'] == 34
    assert x['native_network_counters']['flits_source_queued'] == 0
    assert x['native_memory_counters'] == {'total_num_read_requests': 5, 'total_num_write_requests': 2}
    assert x['read_results']['readback']['hex'] == 'aa' * 12
    args = dict(zip(('compilation', 'workload', 'policy', 'placement'), parents(doc)))
    args['native_config'] = NativeCoupledConfig.from_dict(native_config)
    assert NativeCoupledEvidence.from_dict(x, **args) == a
    # Rehashing forged evidence is insufficient: fresh native parent replay rejects it.
    bad = deepcopy(x); bad['summary']['children_committed'] = 100
    payload = {k: v for k, v in bad.items() if k != 'artifact_id'}
    bad['artifact_id'] = content_id('veritx/NativeCoupledEvidence/v1', payload)
    with pytest.raises(EvidenceInvalid): NativeCoupledEvidence.from_dict(bad, **args)
    kernel = x['compute_intervals'][0]
    completion = Fraction(kernel['completion_s']['numerator'], kernel['completion_s']['denominator'])
    assert min(instant(r) for r in x['ledger'] if r['event'] == 'request_injected' and r['access_id'] == 'write') > completion
    short = deepcopy(doc); short['workload']['horizon_cycles'] = 1
    partial = run_document(short, native_config).to_dict()
    assert partial['status'] == 'INCOMPLETE' and partial['summary']['children_committed'] == 0
    assert partial['final_images'] == short['workload']['initial_images']


def test_actual_native_backpressure_retries_memory_without_reinjecting(doc, native_config):
    doc['design']['agent_intents'][0]['transaction_policy']['outstanding']['total'] = 8
    next(d for d in doc['design']['clock_domains'] if d['id'] == 'network').update(divider_num=1, divider_den=1, frequency_hz=1000000000)
    rebind(doc)
    doc['workload']['demand']['accesses'][0].update(offset_bytes=0, block_bytes=4, count=16, stride_bytes=4)
    doc['workload']['access_values']['read'] = doc['workload']['initial_images']['activation']
    cfg = deepcopy(native_config); cfg.update(host_reservation_slots=8, max_memory_outstanding=8, booksim_period_ps_num=1000)
    cfg['ramulator_config']['memory_system']['controllers'][0]['read_buffer_size'] = 1
    x = run_document(doc, cfg).to_dict()
    assert x['status'] == 'COMPLETE' and x['summary']['memory_send_backpressure'] > 0
    assert x['summary']['children_issued'] == x['summary']['children_committed'] == x['summary']['children_responded'] == 20
    assert x['native_network_counters']['packets'] == 40
    requests = [r for r in x['ledger'] if r['event'] == 'request_injected']
    assert len(requests) == len({r['pid'] for r in requests}) == 20


def test_actual_fractional_network_clock(doc, native_config):
    next(d for d in doc['design']['clock_domains'] if d['id'] == 'network').update(
        divider_num=4, divider_den=3, frequency_hz=750000000)
    rebind(doc)
    cfg = deepcopy(native_config)
    cfg.update(booksim_period_ps_num=4000, booksim_period_ps_den=3)
    x = run_document(doc, cfg).to_dict()
    assert x['status'] == 'COMPLETE'
    assert x['summary']['children_live'] == 0
    events = {}
    for row in x['ledger']:
        if row['event'] in ('request_tail_retired', 'memory_accepted', 'memory_callback_controller_ack', 'response_injected'):
            events.setdefault((row['id'], row['sequence']), {})[row['event']] = instant(row)
    for row in events.values():
        assert row['memory_accepted'] > row['request_tail_retired']
        assert row['response_injected'] > row['memory_callback_controller_ack']
        assert (row['response_injected'] / Fraction(4000, 3 * 10**12)).denominator == 1


def test_actual_memory_clock_controls_dependent_compute_not_independent_engine(doc, native_config):
    w = doc['workload']
    w['engines'].append({'engine_id': 'independent', 'clock': 'network', 'capacity': 1})
    w['nodes'].append({'node_id': 'unrelated', 'kind': 'COMPUTE', 'engine_id': 'independent',
                       'cycles': 5, 'occupancy': 1, 'deps': []})
    fast = run_document(doc, native_config).to_dict()
    cfg = deepcopy(native_config); cfg['memory_tck_ps'] = 2000
    cfg['ramulator_config']['memory_system']['controllers'][0]['dram']['timing'][-1] = 2000
    slow = run_document(doc, cfg).to_dict()
    times = lambda x: {r['node_id']: r for r in x['compute_intervals']}
    assert times(fast)['unrelated'] == times(slow)['unrelated']
    assert times(fast)['kernel']['start_s'] != times(slow)['kernel']['start_s']
    start = lambda x: Fraction(times(x)['kernel']['start_s']['numerator'], times(x)['kernel']['start_s']['denominator'])
    assert start(slow) > start(fast)
    writes = lambda x: min(instant(r) for r in x['ledger'] if r['event'] == 'request_injected' and r['access_id'] == 'write')
    assert writes(slow) > writes(fast)


def test_native_clock_mismatch_refuses_actual_issue(doc, native_config):
    cfg = deepcopy(native_config); cfg['memory_tck_ps'] += 1
    with pytest.raises(UnsupportedSemantics, match='memory clock'):
        run_document(doc, cfg)


def test_fresh_process_actual_replay_is_byte_identical(doc, native_config, tmp_path):
    a = tmp_path / 'experiment.json'; a.write_text(json.dumps(doc))
    b = tmp_path / 'native.json'; b.write_text(json.dumps(native_config))
    cmd = [sys.executable, '-m', 'veritx_dse.backend.native_coupled', str(a), str(b)]
    outputs = [subprocess.check_output(cmd, timeout=300) for _ in range(2)]
    assert outputs[0] == outputs[1]
    cli = json.loads(outputs[0])
    assert cli == run_document(doc, native_config).to_dict()
