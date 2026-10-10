"""Connected native packet -> DRAM -> response -> compute DAG diagnostic.

Native engines determine network and memory completion, never the reference
service_cycles. Byte values and compute cycles remain explicit host reference
semantics. V1 deliberately refuses caches, retry/reset, CDC and multiple owners.
"""
from collections import deque
from dataclasses import dataclass
from fractions import Fraction
import ctypes
import hashlib
import heapq
import importlib.util
import json
from pathlib import Path
import inspect
import sysconfig
import tempfile
from types import SimpleNamespace

from veritx_dse.application.coupled_tensor import _ReferenceRuntime
from veritx_dse.application.data_movement import AccessDenied, ratio
from veritx_dse.application.tensor_demand import project_remote_tensor_demand
from veritx_dse.backend.booksim_projection import MESH_DOR_PROFILE, qualify_native_mesh_dor
from veritx_dse.backend.native_booksim import NativeBookSimProcess
from veritx_dse.backend.router_controls import has_router_controls
from veritx_dse.core.artifact import FrozenMap, canonical_bytes, content_id, thaw
from veritx_dse.core.errors import InvalidInput, EvidenceInvalid, UnsupportedSemantics
from veritx_dse.model.native_coupled import PROFILE, NativeCoupledConfig, verify_pin
from veritx_dse.model.transaction_intent import (TransactionPolicy, OrderingMode,
    OutstandingTracker, ChildTransaction, TransactionKind, split_transactions)
from veritx_dse.model.vc_resource import vc_resources_from_assignment
from veritx_dse.workload.tensor_demand import lower_tensor_demand
from veritx_dse.workload.traffic import packetize_message, flitize_packet

_loaded_memory = None


@dataclass(frozen=True)
class NativeCoupledEvidence:
    data: FrozenMap

    def artifact_id(self):
        return content_id('veritx/NativeCoupledEvidence/v1', self.data)

    def to_dict(self):
        return {**thaw(self.data), 'artifact_id': self.artifact_id()}

    def revalidate(self, *, compilation, workload, policy, placement, native_config):
        if self != execute_native_coupled_tensor(compilation, workload, policy, placement, native_config):
            raise EvidenceInvalid('native evidence differs from actual-engine replay')

    @classmethod
    def from_dict(cls, doc, *, compilation, workload, policy, placement, native_config):
        expected = execute_native_coupled_tensor(compilation, workload, policy, placement, native_config)
        if canonical_bytes(doc) != canonical_bytes(expected.to_dict()):
            raise EvidenceInvalid('native evidence differs from actual-engine replay')
        return expected


def _verify_files(cfg):
    for pin in cfg.files.values():
        verify_pin(pin)
    for name in ('booksim_executable', 'ramulator_extension', 'ramulator_library'):
        with Path(cfg.files[name]['path']).open('rb') as binary:
            if binary.read(4) != b'\x7fELF':
                raise UnsupportedSemantics('native diagnostic requires Linux ELF engines, not script substitutes')
    for name in ('booksim_source_manifest', 'ramulator_source_manifest'):
        path = Path(cfg.files[name]['path'])
        if path.stat().st_size > 2 * 1024 * 1024:
            raise InvalidInput('source manifest exceeds bound')
        doc = json.loads(path.read_text())
        if set(doc) != {'files'} or not isinstance(doc['files'], list) or not 1 <= len(doc['files']) <= 4096:
            raise InvalidInput('source manifest must pin a bounded nonempty file list')
        for pin in doc['files']:
            verify_pin(pin)


def _memory(cfg):
    global _loaded_memory
    # Verify before loading: this function executes pinned native code.
    _verify_files(cfg)
    extension = Path(cfg.files['ramulator_extension']['path'])
    if extension.name != '_ramulator' + sysconfig.get_config_var('EXT_SUFFIX'):
        raise UnsupportedSemantics('native Ramulator extension must match the running Python ABI')
    key = (cfg.files['ramulator_extension']['sha256'], cfg.files['ramulator_library']['sha256'])
    if _loaded_memory is not None and _loaded_memory[0] != key:
        raise UnsupportedSemantics('use a fresh process for a different native Ramulator build')
    if _loaded_memory is None:
        lib = ctypes.CDLL(cfg.files['ramulator_library']['path'], mode=ctypes.RTLD_GLOBAL)
        spec = importlib.util.spec_from_file_location('_ramulator', cfg.files['ramulator_extension']['path'])
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        _loaded_memory = (key, module, lib)
    sim = _loaded_memory[1].Simulation(thaw(cfg.ramulator_config))
    if sim.tCK_ps != cfg.memory_tck_ps or sim.tx_bytes != cfg.tx_bytes:
        sim.finalize()
        raise UnsupportedSemantics('native memory clock/transaction width differs from explicit config')
    return sim


def _prepare(compilation, workload, policy, placement, cfg):
    if not isinstance(cfg, NativeCoupledConfig):
        raise InvalidInput('explicit immutable NativeCoupledConfig required')
    demand = lower_tensor_demand(compilation, workload.demand)
    remote = project_remote_tensor_demand(compilation, workload.demand, policy)
    root, bundle = compilation.compiled_system, compilation.bundle
    placement.validate_against(root.resource_graph)
    if root.access_system is None or root.execution_contract is None:
        raise UnsupportedSemantics('native bytes require compiled authorization and transaction policies')
    if (root.adaptive is not None or root.control_plane is not None or root.request.sideband_interfaces
            or root.request.sideband_connections or root.request.power_domains or root.request.reset_channels
            or root.execution_contract.crossings or workload.cache_profile
            or any(n.retry_of or n.kind == 'DRAIN_RESET' for n in workload.nodes)):
        raise UnsupportedSemantics('native V1 refuses adaptive/multiplane/CDC/cache/retry/reset/power/sideband intent')
    if any(getattr(entry, 'selection_policy', None) == 'STRIPED' for entry in bundle.address_decode.entries):
        raise UnsupportedSemantics('native V1 does not execute striped address selection')
    endpoints = {e.endpoint_id: e for e in bundle.attachment.endpoints}
    contracts = {r['endpoint_id']: r for r in root.execution_contract.endpoints}
    if any(e.interface.clock_domain != policy.network_clock
           or contracts[eid]['transaction_clock_domain'] != policy.network_clock for eid, e in endpoints.items()):
        raise UnsupportedSemantics('native V1 requires homogeneous endpoint transaction/fabric clocks')
    clocks = {d.id: d.frequency_hz for d in root.clock_domains.domains}
    if policy.network_clock not in clocks or cfg.period_ps != Fraction(10**12, clocks[policy.network_clock]):
        raise InvalidInput('native BookSim period must equal the compiled network clock')
    if policy.service_cycles != 0:
        raise UnsupportedSemantics('native memory replaces authored service; service_cycles must explicitly be zero')
    controls = bundle.design.noc_controls
    if (has_router_controls(controls) or controls.arbitration is not None
            or controls.rcu_enabled is True or controls.mcast_groups is not None
            or controls.mcast_setup_cycles is not None):
        raise UnsupportedSemantics('native V1 supports the default mesh IQ router only; authored/advanced controls are not ignored')
    classes = tuple(bundle.vc_assignment.traffic_class_to_vcs)
    if len(classes) != 1 or (policy.traffic_class, policy.response_traffic_class) != (classes[0][0], classes[0][0]):
        raise UnsupportedSemantics('native V1 supports one canonical request/response class')
    # Reuse the canonical native mesh shape, attachment, route and VC gates.
    # Dynamic DAG injection has no static PhysicalTrafficArtifact to fabricate.
    parents = SimpleNamespace(topology=bundle.topology, attachment=bundle.attachment,
        vc_assignment=bundle.vc_assignment, vc_resource=vc_resources_from_assignment(bundle.vc_assignment),
        route=bundle.router_route, physical_traffic=None, source_bundle=bundle)
    qual = qualify_native_mesh_dor(parents)
    if bundle.vc_assignment.vc_count != 1:
        raise UnsupportedSemantics('native V1 requires one identity-transition mesh VC')
    if qual.router_count > 64:
        raise UnsupportedSemantics('native diagnostic supports at most 64 routers')
    values = dict(MESH_DOR_PROFILE.pinned_values())
    values.update(topology='mesh', k=qual.k, n=2, use_noc_latency=1, routing_function='dim_order',
                  num_vcs=bundle.vc_assignment.vc_count, classes=1, subnets=1,
                  traffic='uniform', injection_rate=0.0, seed=0)
    config_bytes = ''.join(f'{k} = {v};\n' for k, v in sorted(values.items())).encode()
    memory = thaw(cfg.ramulator_config)
    try:
        ms = memory['memory_system']; controllers = ms['controllers']; ctrl = controllers[0]; dram = ctrl['dram']
        control_keys = {'impl', 'wr_low_watermark', 'wr_high_watermark', 'read_buffer_size',
                        'write_buffer_size', 'priority_buffer_size', 'scheduler', 'refresh_manager',
                        'row_policy', 'addr_mapper', 'dram'}
        dram_keys = {'impl', 'org', 'timing', 'command_cycles', 'channel_width',
                     'read_latency', 'timing_constraints', 'data_payload_bytes'}
        safe = (set(memory) == {'frontend', 'memory_system'}
            and set(ms) == {'impl', 'clock_ratio', 'channel_mapper', 'controllers'}
            and set(ctrl) in (control_keys, control_keys | {'controller_plugins'})
            and set(dram) == dram_keys
            and ctrl['scheduler'] == {'impl': 'FRFCFS'} and ctrl['row_policy'] == {'impl': 'Open'}
            and ctrl['refresh_manager'] == {'impl': 'AllBank', 'scatter_interval': 0, 'debug': False}
            and all(type(ctrl[k]) is int and 1 <= ctrl[k] <= 65536
                    for k in ('read_buffer_size', 'write_buffer_size', 'priority_buffer_size'))
            and type(dram['read_latency']) is int and 1 <= dram['read_latency'] <= 1000000
            and all(type(v) is int and 0 < v <= 1000000 for v in dram['timing'])
            and len(dram['timing']) == 26
            and all(type(v) is int for v in dram['org']['count'])
            and memory['frontend'] == {'impl': 'External', 'clock_ratio': 1}
            and ms['impl'] == 'GenericDRAM' and ms['clock_ratio'] == 1 and len(controllers) == 1
            and ms['channel_mapper'] == {'impl': 'CacheLineInterleave', 'interleave_bits': 0}
            and ctrl['impl'] == 'HBM12' and ctrl['addr_mapper'] == {'impl': 'RoBaRaCoCh'}
            and dram['impl'] == 'HBM2' and dram['org'] == {'dq': 64, 'count': [1, 2, 1, 4, 2, 16384, 128]}
            and dram['channel_width'] == 128 and dram['data_payload_bytes'] == 32
            and not ctrl.get('controller_plugins'))
    except (KeyError, TypeError, IndexError):
        safe = False
    if not safe:
        raise UnsupportedSemantics('native V1 requires one explicitly configured HBM2_1Gb controller; the native RoBaRaCoCh mapper still scatters the host window across pseudochannels/sids/bankgroups/banks')
    if dram['timing'][-1] != cfg.memory_tck_ps:
        raise UnsupportedSemantics('native memory clock differs from the explicit DRAM configuration')
    if cfg.owner_endpoint not in endpoints or endpoints[cfg.owner_endpoint].agent.kind.value != 'hbm_controller':
        raise UnsupportedSemantics('native HBM must map to an attached hbm_controller endpoint')
    if any(s.target != cfg.owner_endpoint or s.transaction_bytes != cfg.tx_bytes
           or s.base_address < cfg.window_start or s.base_address + s.size_bytes > cfg.window_end
           for t in workload.demand.tensors for s in t.shards):
        raise UnsupportedSemantics('native V1 requires one owner and native-width tensor storage inside its explicit window')
    trackers, policies, plan, deps, groups, authorizations = {}, {}, [], {}, {}, []
    for op in remote.workload.operations:
        if op.kind not in (TransactionKind.READ, TransactionKind.WRITE):
            raise UnsupportedSemantics('native V1 executes only READ and WRITE transactions')
        r = next(r for r in demand.requests if r.request_id == op.operation_id)
        if not cfg.window_start <= r.transaction_address or r.transaction_address + cfg.tx_bytes > cfg.window_end:
            raise InvalidInput('native transaction span escapes the explicit memory window')
        # Authorize the full modeled backing burst as well as requested bytes.
        spans = root.access_system.range_decisions(operation=op.kind.value.lower(),
            initiator=f'group:{endpoints[op.initiator].agent.group_index}',
            target=f'group:{endpoints[op.target].agent.group_index}', address=r.transaction_address,
            byte_length=cfg.tx_bytes, address_space=op.address_space,
            endpoint_exists=True, route_exists=True, observed=False)
        for start, end, decision in spans:
            decoded = [e for e in bundle.address_decode.entries
                       if e.base <= start and end <= e.base + e.size and e.target_endpoint_id == op.target]
            if decision.permitted is not True or not decoded:
                raise AccessDenied('native backing burst is not fully decoded/authorized',
                                   {'operation_id': op.operation_id, 'issued_children': 0})
        authorizations.append({'operation_id': op.operation_id, 'native_burst_address': r.transaction_address,
                               'native_burst_bytes': cfg.tx_bytes,
                               'spans': [{'start': a, 'end': b, 'decision': d.to_dict()} for a, b, d in spans]})
        raw = contracts[op.initiator]['transaction_policy']
        p = TransactionPolicy.from_dict(thaw(raw)) if raw is not None else None
        if (p is None or p.outstanding is None or p.ordering is None
                or p.ordering.mode is not OrderingMode.RELAXED or p.ordering.enforced_hazards
                or p.reordering is not None and p.reordering.enabled):
            raise UnsupportedSemantics('native V1 requires explicit outstanding limits and dependency-ordered RELAXED accesses')
        policies[op.initiator] = p
        trackers.setdefault(op.initiator, OutstandingTracker(p.outstanding))
        deps[op.operation_id] = set(op.deps)
        children = (split_transactions(parent_id=op.operation_id, address_base=op.address,
            payload_bytes=op.payload_bytes, splitting=p.splitting,
            ordering_domain=p.ordering.ordering_domain, traffic_class=op.traffic_class) if p.splitting else
            (ChildTransaction(0, op.address, op.address + op.payload_bytes, op.payload_bytes,
                              op.operation_id, p.ordering.ordering_domain, op.traffic_class, True),))
        groups[op.operation_id] = set(c.sequence for c in children)
        for child in children:
            req = child.byte_length if op.kind is TransactionKind.WRITE else op.control_bytes
            rsp = child.byte_length if op.kind is TransactionKind.READ else op.control_bytes
            counts = []
            for size in (req, rsp):
                packets = packetize_message(size * 8, bundle.packet_format)
                if len(packets) != 1:
                    raise UnsupportedSemantics('native V1 requires one actual packet per child request/response')
                counts.append(flitize_packet(packets[0], bundle.packet_format)[0])
            if max(counts) > cfg.host_flit_limit:
                raise InvalidInput('native packet exceeds host flit limit')
            plan.append((op, child, counts))
    if len(plan) > 4096 or sum(sum(c) for _, _, c in plan) > 100000:
        raise UnsupportedSemantics('native diagnostic exceeds child/flit bounds')
    runtime = _ReferenceRuntime(compilation, workload, policy, placement, demand, remote)
    return runtime, plan, deps, groups, trackers, authorizations, config_bytes, qual.router_count


def _drive(runtime, plan, deps, groups, trackers, authorizations, cfg, net, mem):
    period = cfg.period_ps / 10**12
    mperiod = Fraction(cfg.memory_tck_ps, 10**12)
    horizon = runtime.horizon
    events, serial = [], 0
    def push(time, priority, payload):
        nonlocal serial
        serial += 1
        heapq.heappush(events, (time, priority, serial, payload))
    runtime.bind(deps=deps, push=push, wake=lambda *_: None, trackers=trackers, lane_free={})
    held = list(plan); plan_index = {id(entry): i for i, entry in enumerate(plan)}
    children = []; pids = {}; seen_pids = set()
    memory_queue = deque(); callbacks = deque()
    active_memory = set(); completed_ops = set(); gate_ready = {}
    reservations = peak = accepted = backpressure = steps = 0
    nedge, medge, now = period, mperiod, Fraction(0)
    step_bound_exhausted = False
    def future(time, clock):
        return (time // clock + 1) * clock
    def log(kind, record, **extra):
        if len(runtime.ledger) >= 200000:
            raise UnsupportedSemantics('native event ledger exceeded its finite allocation bound')
        request = runtime.requests[record['child']['parent_id']]
        runtime.log(kind, record['child']['parent_id'], now, sequence=record['child']['sequence'],
                    access_id=request.access_id, **extra)
    def dispatch():
        while events and events[0][0] <= now:
            time, _, _, payload = heapq.heappop(events)
            if time != now or payload[0] != 'runtime':
                raise EvidenceInvalid('native runtime event ordering mismatch')
            runtime.handle(payload[1], now)
        runtime.dispatch(now)
        for gate in sorted(runtime.gates):
            gate_ready.setdefault(gate, Fraction(0) if now == 0 else future(now, period))
    def commit_callbacks():
        while callbacks:
            index, address, typ, size = callbacks.popleft()
            op, _, _ = plan[index]
            rec = by_index[index]
            if (index not in active_memory or rec['state'] != 'MEMORY_ACCEPTED'
                    or (address, typ, size) != (rec['child']['address_start'],
                        int(op.kind is TransactionKind.WRITE), rec['child']['byte_length'])):
                raise EvidenceInvalid('native callback duplicate/unaccepted/identity mismatch')
            active_memory.remove(index)
            runtime.commit(op, rec, now)
            rec['response_ready_s'] = ratio(future(now, period))
            log('memory_callback_controller_ack', rec, memory_tick=mem.memory_ticks)
    by_index = {}
    while now <= horizon:
        if steps + int(now == nedge) + int(now == medge) > cfg.max_engine_steps:
            step_bound_exhausted = True
            break  # before either engine edge runs: no partial coincident step
        # Both engines finish their preceding intervals before any cross-engine
        # admissions. Same-time native completions never feed a current edge.
        if now == nedge:
            cycle = net.step(); steps += 1
            if cycle * period != now:
                raise EvidenceInvalid('native BookSim clock drift')
            for node in range(net.num_nodes):
                for tail in net.drain(node):
                    if tail.pid not in pids:
                        raise EvidenceInvalid('unknown or duplicate native packet retirement')
                    index, direction = pids.pop(tail.pid)
                    op, _, _ = plan[index]; rec = by_index[index]
                    src, dst = (op.initiator, op.target) if direction == 'request' else (op.target, op.initiator)
                    if (tail.src, tail.dst, tail.cl) != (src, dst, 0) or tail.atime + 1 != cycle:
                        raise EvidenceInvalid('native retirement endpoint/class/clock mismatch')
                    log(direction + '_tail_retired', rec, pid=tail.pid,
                        native_itime=tail.itime, native_atime=tail.atime)
                    if direction == 'request':
                        if rec['state'] != 'REQUEST_INFLIGHT':
                            raise EvidenceInvalid('request ownership mismatch')
                        rec['state'] = 'MEMORY_QUEUED'
                        memory_queue.append((index, future(now, mperiod)))
                    else:
                        groups[op.operation_id].remove(rec['child']['sequence'])
                        parent_complete = not groups[op.operation_id]
                        if parent_complete:
                            completed_ops.add(op.operation_id)
                        runtime.responded(op, rec, now, parent_complete)
                        trackers[op.initiator].complete(op.kind)
                        reservations -= 1
            nedge += period
        memory_edge = now == medge
        if memory_edge:
            mem.tick(); steps += 1
            if mem.memory_ticks * mperiod != now:
                raise EvidenceInvalid('native memory clock drift')
            medge += mperiod
        commit_callbacks()
        dispatch()
        if memory_edge:
            # Admission order stays FIFO in request-retirement order: deferred
            # entries keep their relative order and are retried, never rotated.
            deferred = []
            for _ in range(len(memory_queue)):
                index, ready = memory_queue.popleft()
                if ready > now or len(active_memory) >= cfg.max_memory_outstanding:
                    deferred.append((index, ready)); continue
                op, child, _ = plan[index]; rec = by_index[index]
                # Register correlation BEFORE send: WRITE ACK may be synchronous.
                active_memory.add(index)
                ok = mem.send(child.address_start, int(op.kind is TransactionKind.WRITE),
                    child.byte_length, op.initiator, op.target,
                    lambda a, t, s, i=index: callbacks.append((i, a, t, s)))
                if ok:
                    rec['state'] = 'MEMORY_ACCEPTED'
                    accepted += 1
                    log('memory_accepted', rec, memory_tick=mem.memory_ticks)
                else:
                    active_memory.remove(index)
                    backpressure += 1
                    log('memory_send_backpressure', rec)
                    deferred.append((index, now + mperiod))
            memory_queue.extend(deferred)
            commit_callbacks()
        if now % period == 0:
            for rec in children:
                if rec['state'] != 'RESPONSE_INFLIGHT' or 'response_pid' in rec:
                    continue
                ready = rec['response_ready_s']
                if Fraction(ready['numerator'], ready['denominator']) > now:
                    continue
                index = rec['index']; op, _, counts = plan[index]
                pid = net.inject(op.target, op.initiator, counts[1])
                if pid < 0:
                    continue
                if pid in seen_pids:
                    raise EvidenceInvalid('native packet PID reused')
                seen_pids.add(pid)
                rec['response_pid'] = pid; pids[pid] = (index, 'response')
                log('response_injected', rec, pid=pid)
            issued_sources = set()
            for entry in list(held):
                op, child, counts = entry
                gate = runtime.access_nodes[runtime.requests[op.operation_id].access_id]
                if (op.initiator in issued_sources or not runtime.ready(op.operation_id)
                        or gate_ready[gate] > now or not deps[op.operation_id] <= completed_ops
                        or reservations >= cfg.host_reservation_slots):
                    continue
                tracker = trackers[op.initiator]
                if not tracker.try_issue(op.kind):
                    continue
                pid = net.inject(op.initiator, op.target, counts[0])
                if pid < 0:
                    tracker.complete(op.kind); continue
                if pid in seen_pids:
                    raise EvidenceInvalid('native packet PID reused')
                seen_pids.add(pid)
                index = plan_index[id(entry)]
                rec = {'index': index, 'child': child.to_dict(),
                       'demand_request': runtime.requests[op.operation_id].to_dict(), 'epoch': 0,
                       'state': 'REQUEST_INFLIGHT', 'request_pid': pid, 'flits_planned': sum(counts)}
                by_index[index] = rec; children.append(rec); pids[pid] = (index, 'request')
                held.remove(entry); issued_sources.add(op.initiator)
                reservations += 1; peak = max(peak, reservations)
                log('request_injected', rec, pid=pid)
        runtime.now = now
        if runtime.finished:
            if (held or pids or memory_queue or active_memory or reservations
                    or any(runtime.live.values())
                    or reservations != sum(1 for r in children if 'response_pid' not in r)):
                raise EvidenceInvalid('native COMPLETE retains work/credits')
            break
        next_time = min(nedge, medge, events[0][0] if events else horizon + 1)
        if next_time > horizon:
            break
        if steps >= cfg.max_engine_steps:
            step_bound_exhausted = True
            break
        now = next_time
    counts = net.counts()
    retired = len(runtime.responded_keys); committed = len(runtime.committed_keys)
    live = sum(t.live_total for t in trackers.values())
    if (len(children) != retired + live or accepted != committed + len(active_memory)
            or reservations != live or counts['packets'] != len(children) + sum('response_pid' in r for r in children)
            or counts['tails'] != counts['packets'] - len(pids)
            or counts['flits_constructed'] != counts['flits_retired'] + counts['flits_live']):
        raise EvidenceInvalid('native request/callback/packet/credit conservation mismatch')
    for tracker in trackers.values():
        tracker.assert_invariants()
    if runtime.finished and (counts['flits_live'] or counts['flits_source_queued']
            or counts['flits_constructed'] != sum(r['flits_planned'] for r in children)):
        raise EvidenceInvalid('native complete network did not conserve actual flits')
    stats = mem.get_stats()['memory_system']
    if stats['total_num_read_requests'] + stats['total_num_write_requests'] != accepted:
        raise EvidenceInvalid('native memory admission counters differ from host ledger')
    for authorization in authorizations:
        for span in authorization['spans']:
            span['decision']['observed'] = authorization['operation_id'] in completed_ops
    final = {k: bytes(v).hex() for k, v in sorted(runtime.images.items())}
    return {'status': 'COMPLETE' if runtime.finished else 'INCOMPLETE',
        'stop_reason': 'ALL_NODES_RETIRED' if runtime.finished else 'ENGINE_STEP_BOUND' if step_bound_exhausted else 'INCLUSIVE_HORIZON',
        'elapsed_s': ratio(now), 'horizon_s': ratio(horizon), 'children': children,
        'ledger': runtime.ledger, 'compute_intervals': runtime.intervals,
        'pending_nodes': sorted(set(runtime.nodes) - runtime.completed),
        'source_held_children': [{'child': child.to_dict(), 'access_released': runtime.ready(op.operation_id),
                                 'operation_dependencies': sorted(deps[op.operation_id] - completed_ops)}
                                for op, child, _counts in held], 'final_images': final,
        'read_results': {k: {'complete': not runtime.remaining[k], 'returned_bytes': runtime.returned_bytes[k],
                            'hex': bytes(v).hex() if not runtime.remaining[k] else None}
                         for k, v in runtime.reads.items()},
        'summary': {'children_declared': len(plan), 'children_source_held': len(held),
                    'children_issued': len(children), 'children_committed': committed,
                    'children_responded': retired, 'children_live': live, 'memory_accepted': accepted,
                    'memory_send_backpressure': backpressure, 'peak_host_reservations': peak,
                    'host_reservations_remaining': reservations, 'native_steps': steps,
                    'write_bytes_committed': runtime.mutated_bytes,
                    'read_bytes_returned': sum(runtime.returned_bytes.values()),
                    'peak_engine_occupancy': runtime.peak},
        'native_network_counters': counts,
        'native_memory_counters': {k: stats[k] for k in ('total_num_read_requests', 'total_num_write_requests')},
        # Observed, not declared: both engines must have produced native work.
        'observed': {'native_network': bool(counts['flits_constructed']) and bool(steps),
                     'native_memory': accepted > 0 and committed > 0},
        'authorizations': authorizations}


def execute_native_coupled_tensor(compilation, workload, policy, placement, native_config):
    """Run fresh real engines; never substitute the abstract network executor."""
    prepared = _prepare(compilation, workload, policy, placement, native_config)
    runtime, plan, deps, groups, trackers, auth, config_bytes, nodes = prepared
    _verify_files(native_config)
    mem = _memory(native_config)
    try:
        with tempfile.TemporaryDirectory(prefix='veritx-native-connected-') as directory:
            directory = Path(directory)
            path = directory / 'network.config'; path.write_bytes(config_bytes)
            net = NativeBookSimProcess(native_config.files['booksim_executable']['path'], path,
                                       native_config.host_flit_limit, directory)
            try:
                if net.num_nodes != nodes:
                    raise EvidenceInvalid('native terminal universe differs from compiled mesh')
                result = _drive(runtime, plan, deps, groups, trackers, auth, native_config, net, mem)
            finally:
                net.close()
    finally:
        mem.finalize()
    _verify_files(native_config)
    return NativeCoupledEvidence(FrozenMap({
        'type': 'veritx/NativeCoupledEvidence', 'schema_version': 1,
        'profile': PROFILE, 'design_hash': workload.demand.design_hash,
        'system_hash': workload.demand.system_hash, 'workload_id': workload.workload_id(),
        'demand_id': runtime.demand.artifact_id(), 'transport': policy.to_dict(),
        'placement_id': placement.artifact_id(), 'native_config': native_config.to_dict(),
        'native_config_id': native_config.config_id(),
        'booksim_config_sha256': hashlib.sha256(config_bytes).hexdigest(),
        'driver_code_sha256': content_id('veritx/NativeDriverSources/v1', {
            obj.__name__: hashlib.sha256(Path(inspect.getsourcefile(obj)).read_bytes()).hexdigest()
            for obj in (execute_native_coupled_tensor, NativeBookSimProcess, NativeCoupledConfig,
                        _ReferenceRuntime, lower_tensor_demand, project_remote_tensor_demand)}),
        'scope': {'native_engines_declared': True, 'qualified': False, 'calibrated': False,
            'compute': 'AUTHORED_EXACT_CLOCK_CYCLES', 'bytes': 'HOST_REFERENCE_IMAGE_NOT_NATIVE_DRAM_CONTENTS',
            'write_completion': 'CONTROLLER_ACK_NOT_PHYSICAL_PERSISTENCE',
            'admission': 'RESERVATION_ADMISSION_V1_NOT_NATIVE_SINK_CREDITS',
            'clock_bridge': 'STRICTLY_FUTURE_ENGINE_EDGES_NOT_HARDWARE_CDC',
            'protocol': 'NATIVE_PACKET_TIMING_NOT_AXI_CHI_OR_NATIVE_BYTE_ENCODING',
            'network_drain': 'ALL_FLITS_RETIRED_NOT_A_RESET_OR_CREDIT_DRAIN_PROOF',
            'placement': 'PLACEMENT_VALIDATED_NEVER_READ_FOR_TIMING; ATTACHMENT_IDENTITY_ONLY',
            'memory_mapping': 'HOST_WINDOW_SCATTERED_BY_NATIVE_ROBARaCoCh_MAPPER',
            'pin_binding': 'PRE_AND_POST_HASH_CHECKS_NOT_A_BINDING_TO_EXECUTED_BYTES',
            'provenance': 'PINNED_LOCAL_FILES_NOT_RELEASE_QUALIFICATION'}, **result}))


def run_document(doc, native_config):
    from veritx_dse.application.fabric_compiler import FabricCompiler
    from veritx_dse.model.compile_request_v5 import CompileRequestV5
    from veritx_dse.model.coupled_tensor import CoupledTensorWorkload, fields
    from veritx_dse.model.physical_placement import PhysicalPlacement
    from veritx_dse.application.tensor_demand import RemoteDemandPolicy
    fields(doc, {'design', 'workload', 'transport', 'placement'}, 'native experiment')
    compilation = FabricCompiler().compile(CompileRequestV5.from_dict(doc['design']))
    return execute_native_coupled_tensor(compilation, CoupledTensorWorkload.from_dict(doc['workload']),
        RemoteDemandPolicy.from_dict(doc['transport']), PhysicalPlacement.from_dict(doc['placement']),
        NativeCoupledConfig.from_dict(native_config))


def main(argv=None):
    import sys
    from veritx_dse.core.errors import Refusal, SemanticError
    argv = sys.argv[1:] if argv is None else argv
    try:
        if len(argv) != 2:
            raise InvalidInput('expected experiment JSON and pinned native config JSON')
        evidence = run_document(json.loads(Path(argv[0]).read_text()), json.loads(Path(argv[1]).read_text()))
    except (Refusal, SemanticError, OSError, json.JSONDecodeError) as exc:
        print(json.dumps({'status': 'REFUSED', 'profile': PROFILE, 'reason': str(exc)}, sort_keys=True))
        return 2
    print(json.dumps(evidence.to_dict(), sort_keys=True))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
