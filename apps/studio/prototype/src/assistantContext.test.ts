import { describe, expect, test } from 'vitest';
import { answerLocally, buildContextPacket, channelFacts, routerTraffic, suggestedQuestions } from './assistantContext';
import type { SimLoad, Topology } from './gateway';

const topology: Topology = {
  family: 'mesh',
  counts: { routers: 4, channels: 8, endpoints: 2, seats: 2 },
  routers: [
    { router_id: 0, coordinates: [0, 0], seat_capacity: 2 },
    { router_id: 1, coordinates: [1, 0], seat_capacity: 1 },
    { router_id: 2, coordinates: [0, 1], seat_capacity: 1 },
    { router_id: 3, coordinates: [1, 1], seat_capacity: 1 },
  ],
  channels: [
    { channel_id: 0, src_router: 0, dst_router: 1, src_port: 1, dst_port: 1, width_bits: 64, latency_cycles: 1 },
    { channel_id: 1, src_router: 1, dst_router: 0, src_port: 1, dst_port: 1, width_bits: 64, latency_cycles: 1 },
    { channel_id: 2, src_router: 0, dst_router: 2, src_port: 2, dst_port: 1, width_bits: 64, latency_cycles: 1 },
    { channel_id: 3, src_router: 2, dst_router: 0, src_port: 1, dst_port: 2, width_bits: 64, latency_cycles: 1 },
    { channel_id: 4, src_router: 1, dst_router: 3, src_port: 1, dst_port: 1, width_bits: 64, latency_cycles: 1 },
    { channel_id: 5, src_router: 3, dst_router: 1, src_port: 1, dst_port: 1, width_bits: 64, latency_cycles: 1 },
    { channel_id: 6, src_router: 2, dst_router: 3, src_port: 2, dst_port: 1, width_bits: 64, latency_cycles: 1 },
    { channel_id: 7, src_router: 3, dst_router: 2, src_port: 1, dst_port: 2, width_bits: 64, latency_cycles: 1 },
  ],
  endpoints: [
    { endpoint_id: 0, router_id: 0, kind: 'compute_tile', port_id: 0 },
    { endpoint_id: 1, router_id: 1, kind: 'hbm_controller', port_id: 0 },
  ],
};

const channels: NonNullable<SimLoad['channels']> = [
  { logical_channel_id: 0, flits_total: 100, cycles_sampled: 1000, utilization: 0.5, peak_window_utilization: 0.75, queue_cycles_total: 1000, arb_wait_cycles_total: 100, per_hop_latency_mean_cycles: 4, peak_per_hop_latency_cycles: 8 },
  { logical_channel_id: 4, flits_total: 50, cycles_sampled: 1000, utilization: 0.2, peak_window_utilization: 0.3, queue_cycles_total: 100 },
  { logical_channel_id: 10001, flits_total: 20, cycles_sampled: 1000, utilization: 0.1, peak_window_utilization: 0.2, queue_cycles_total: 10 },
  { logical_channel_id: 10004, flits_total: 30, cycles_sampled: 1000, utilization: 0.1, peak_window_utilization: 0.2, queue_cycles_total: 20 },
];

const load: SimLoad = {
  run: 'run-1', source: 'measured', link_capacity_flits_per_cycle: 1,
  sample_period_cycles: 100, num_windows: 10, cycles_sampled: 1000, channels,
};

describe('router traffic', () => {
  test('groups measured source-port counters and keeps local eject separate', () => {
    const traffic = routerTraffic(topology, channels, 0);
    expect(traffic.measured).toBe(true);
    expect(traffic.egress_flits).toBe(150);
    expect(traffic.declared_link_flits).toBe(100);
    expect(traffic.local_flits).toBe(50);
    expect(traffic.active_channels).toBe(2);
    expect(traffic.channels).toBe(2);
    expect(traffic.routes.map(route => route.key)).toEqual(['to:1', 'local']);
    expect(traffic.top_channels[0].id).toBe(0);
    expect(traffic.top_channels[0].queue_per_flit).toBe(10);
  });

  test('absence of a sampled series is not converted to zeros', () => {
    const traffic = routerTraffic(topology, null, 0);
    expect(traffic.measured).toBe(false);
    expect(traffic.gap).toMatch(/no sampled/i);
    const packet = buildContextPacket({ route: 'design/fabric-topology', page: { title: 'Fabric topology', group: 'Design' }, topology, picks: [{ kind: 'router', id: '0', label: 'Router R0' }] });
    const answer = answerLocally('What traffic leaves R0?', packet);
    expect(answer.paragraphs.join(' ')).toMatch(/no sampled channel counters/i);
    expect(answer.paragraphs.join(' ')).toContain('outbound');
    expect(answer.evidence.map(item => item.label)).toContain('Outbound channels');
  });

  test('a recorded zero stays a recorded zero and is not called missing', () => {
    const traffic = routerTraffic(topology, [], 0);
    expect(traffic.measured).toBe(true);
    expect(traffic.egress_flits).toBe(0);
    const packet = buildContextPacket({ route: 'analysis/topology', page: { title: 'Topology', group: 'Analysis' }, topology, load: { ...load, channels: [] }, picks: [{ kind: 'router', id: '0', label: 'Router R0' }] });
    const answer = answerLocally('What traffic leaves R0?', packet);
    expect(answer.paragraphs.join(' ')).toMatch(/no measured egress/i);
    expect(answer.paragraphs.join(' ')).toMatch(/recorded zero/i);
  });
});

describe('channel facts and local answers', () => {
  test('joins a measured id to its declared directed channel', () => {
    const facts = channelFacts(topology, channels, '0');
    expect(facts.measured).toBe(true);
    expect(facts.declared?.src_router).toBe(0);
    expect(facts.declared?.dst_router).toBe(1);
    expect(facts.counters?.flits).toBe(100);
    expect(facts.derived.queue_per_flit).toBe(10);
    expect(facts.derived.tail_ratio).toBe(2);
  });

  test('answers measured channel counters without inventing percentiles', () => {
    const packet = buildContextPacket({ route: 'analysis/topology', page: { title: 'Topology', group: 'Analysis' }, topology, load, picks: [{ kind: 'channel', id: '0', label: 'Measured channel CH-0' }] });
    const answer = answerLocally('What are the counters?', packet);
    expect(answer.paragraphs.join(' ')).toContain('100 measured flits');
    expect(answer.paragraphs.join(' ')).toContain('10.00 queue cycles per delivered flit');
    expect(answer.caveats.join(' ')).toMatch(/packet-latency percentile/i);
  });
});

describe('context packet', () => {
  test('contains scope, selections, measured summary and explicit gaps', () => {
    const packet = buildContextPacket({ route: 'design/fabric-topology', page: { title: 'Fabric topology', group: 'Design' }, project: null, topology, load, picks: [{ kind: 'router', id: '0', label: 'Router R0' }] });
    expect(packet.schema).toBe('srota-studio/assistant-context/v1');
    expect(packet.scope.page).toBe('Fabric topology');
    expect(packet.measured?.active_channels).toBe(4);
    expect(packet.selections[0].resolved).toBeTruthy();
    expect(packet.gaps).toContain('packet-latency percentiles and histograms');
    expect(packet.gaps).toContain('no evaluation run is selected');
    expect(suggestedQuestions(packet)[0]).toBe('What traffic leaves R0?');
  });

  test('the local summary names attached selections and availability', () => {
    const packet = buildContextPacket({ route: 'design/fabric-topology', page: { title: 'Fabric topology', group: 'Design' }, topology, picks: [{ kind: 'section', id: 'section:Fabric summary', label: 'Fabric summary', detail: 'visible text: counts' }] });
    const answer = answerLocally('Summarize this selection', packet);
    expect(answer.paragraphs[0]).toContain('Fabric summary');
    expect(answer.paragraphs.join(' ')).toMatch(/rendered interface context/i);
  });
});
