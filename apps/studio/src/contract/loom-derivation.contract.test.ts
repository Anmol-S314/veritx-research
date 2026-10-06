/** Loom derivation contract tests (fixtures only — no engine, no network).
 *
 *  The Loom workspace draws three derivations that no view carries as an
 *  artifact: per-instance agent rows (certified attachment × authored groups),
 *  clock/power domain crossings (attachment × authored assignment), and
 *  expected per-channel load (measured trace × frozen route table). Each is a
 *  product of two facts, so each can silently overstate what it knows.
 *
 *  These tests pin the discipline: a missing half is reported, never invented;
 *  a derived value never borrows the authority of the artifact it came from.
 */
import { describe, expect, it } from 'vitest';
import {
  agentRows, domainsOf, expectedChannelLoad, problemsOf, sweepPairs,
  type LoomData, type Query,
} from '../pages/loom/data';
import type {
  CanonicalRoute, PreflightView, RunIntegrityView, TrafficMatrixView,
} from '../api/types';
import type { TopologyView } from '../types';

const ready = <T,>(data: T): Query<T> => ({ result: { state: 'ready', data } });
/** "This input does not exist" — resolved, and carrying null. Distinct from
 *  loading and from a failure, exactly as the views render it. */
const absent = <T,>(data: T | null): Query<T> => ({ result: { state: 'ready', data: data as T } });

function loom(over: Partial<LoomData> = {}): LoomData {
  return {
    projectId: 'p-1',
    project: null,
    design: null,
    designHash: null,
    revisionId: 'r-1',
    dirty: false,
    agents: [],
    topology: absent<TopologyView>(null),
    compileResult: absent(null),
    latestRun: null,
    run: absent(null),
    traffic: absent<TrafficMatrixView | null>(null),
    lowering: absent(null),
    ...over,
  };
}

const TOPOLOGY: TopologyView = {
  contract_version: 1,
  revision_id: 'r-1',
  design_hash: 'sha256:d',
  topology_hash: 'sha256:t',
  attachment_hash: 'sha256:a',
  family: 'mesh',
  routers: [
    { router_id: 0, coordinates: [0, 0], seat_capacity: 1 },
    { router_id: 1, coordinates: [0, 1], seat_capacity: 1 },
    { router_id: 2, coordinates: [1, 0], seat_capacity: 1 },
    { router_id: 3, coordinates: [1, 1], seat_capacity: 1 },
  ],
  channels: [
    { channel_id: 0, src_router: 0, src_port: 1, dst_router: 1, dst_port: 1, width_bits: 64, latency_cycles: 1 },
    { channel_id: 1, src_router: 0, src_port: 2, dst_router: 2, dst_port: 1, width_bits: 64, latency_cycles: 1 },
    { channel_id: 2, src_router: 1, src_port: 1, dst_router: 0, dst_port: 2, width_bits: 64, latency_cycles: 1 },
    { channel_id: 3, src_router: 1, src_port: 2, dst_router: 3, dst_port: 1, width_bits: 64, latency_cycles: 1 },
    { channel_id: 4, src_router: 2, src_port: 1, dst_router: 0, dst_port: 2, width_bits: 64, latency_cycles: 1 },
  ],
  physical_links: [],
  endpoints: [
    { endpoint_id: 10, kind: 'compute_tile', group_index: 0, instance_index: 0, router_id: 0, port_id: 0 },
    { endpoint_id: 11, kind: 'compute_tile', group_index: 0, instance_index: 1, router_id: 1, port_id: 0 },
    { endpoint_id: 12, kind: 'hbm_controller', group_index: 1, instance_index: 0, router_id: 2, port_id: 0 },
    { endpoint_id: 13, kind: 'hbm_controller', group_index: 1, instance_index: 1, router_id: 3, port_id: 0 },
  ],
  counts: { routers: 4, channels: 5, seats: 4, endpoints: 4 },
};

const GROUPS = [
  { kind: 'compute_tile', count: 2, data_width: 256, addr_width: 64, protocol: 'AXI', clock_domain: 'clk_a', power_domain: 'pd_0' },
  { kind: 'hbm_controller', count: 2, data_width: 256, addr_width: 64, protocol: 'AXI', clock_domain: 'clk_b', power_domain: 'pd_1' },
];

describe('agentRows', () => {
  it('takes instance identity from the certified attachment, not from the group', () => {
    const rows = agentRows(loom({ agents: GROUPS, topology: ready(TOPOLOGY) }));
    expect(rows).toHaveLength(4);
    expect(rows.map((r) => r.endpointId)).toEqual([10, 11, 12, 13]);
    expect(rows[0].routerId).toBe(0);
    expect(rows[3].routerId).toBe(3);
    expect(rows.every((r) => r.attached)).toBe(true);
  });

  it('joins authored group fields positionally on group_index', () => {
    const rows = agentRows(loom({
      agents: GROUPS,
      topology: ready(TOPOLOGY),
    }));
    expect(rows[0].clockDomain).toBe('clk_a');
    expect(rows[2].clockDomain).toBe('clk_b');
    expect(rows[2].powerDomain).toBe('pd_1');
    expect(rows[0].dataWidth).toBe(256);
  });

  it('marks declared agents unattached when no revision exists', () => {
    const rows = agentRows(loom({ agents: GROUPS }));
    expect(rows).toHaveLength(4);
    expect(rows.every((r) => !r.attached)).toBe(true);
    expect(rows.every((r) => r.endpointId === -1)).toBe(true);
    expect(rows.every((r) => r.routerId === null)).toBe(true);
  });

  it('leaves authored fields null when a group_index has no declared group', () => {
    const rows = agentRows(loom({ agents: [], topology: ready(TOPOLOGY) }));
    expect(rows).toHaveLength(4);
    expect(rows[0].protocol).toBeNull();
    expect(rows[0].dataWidth).toBeNull();
  });
});

describe('domainsOf', () => {
  it('counts agents per domain and separates declared from seated', () => {
    const { rows } = domainsOf(loom({ agents: GROUPS, topology: ready(TOPOLOGY) }));
    const clock = rows.filter((r) => r.kind === 'clock');
    expect(clock.map((r) => r.id)).toEqual(['clk_a', 'clk_b']);
    expect(clock.every((r) => r.agentCount === 2 && r.attachedCount === 2)).toBe(true);
    const power = rows.filter((r) => r.kind === 'power');
    expect(power.map((r) => r.id)).toEqual(['pd_0', 'pd_1']);
  });

  it('derives a crossing only where the two sides name different domains', () => {
    const { crossings } = domainsOf(loom({ agents: GROUPS, topology: ready(TOPOLOGY) }));
    // R0 (clk_a) ↔ R1 (clk_a): same domain, no crossing.
    // R0 (clk_a) ↔ R2 (clk_b): crossing on channels 1 and 4.
    // R1 (clk_a) ↔ R3 (clk_b): crossing on channel 3.
    expect(crossings.map((c) => c.channelId).sort((a, b) => a - b)).toEqual([1, 3, 4]);
    expect(crossings.find((c) => c.channelId === 1)?.srcDomain).toBe('clk_a');
    expect(crossings.find((c) => c.channelId === 1)?.dstDomain).toBe('clk_b');
  });

  it('reports zero crossings when no agent declares a domain', () => {
    const undeclared = GROUPS.map((g) => ({ ...g, clock_domain: null }));
    const { rows, crossings } = domainsOf(loom({
      agents: undeclared,
      topology: ready(TOPOLOGY),
    }));
    // One implicit domain, so there is no boundary to cross — not a
    // fabricated pass and not an invented synchronizer.
    expect(crossings).toHaveLength(0);
    expect(rows.filter((r) => r.kind === 'clock').map((r) => r.id)).toEqual(['undeclared']);
  });

  it('marks a channel against an undeclared side instead of dropping it', () => {
    const half = [
      { ...GROUPS[0], clock_domain: 'clk_a' },
      { ...GROUPS[1], clock_domain: null },
    ];
    const { crossings } = domainsOf(loom({ agents: half, topology: ready(TOPOLOGY) }));
    const toUndeclared = crossings.find((c) => c.channelId === 1);
    expect(toUndeclared?.dstDomain).toBe('undeclared');
  });

  it('reports routers that carry no agent rather than assuming a domain', () => {
    const withIdle: TopologyView = {
      ...TOPOLOGY,
      routers: [...TOPOLOGY.routers, { router_id: 9, coordinates: [2, 2], seat_capacity: 1 }],
    };
    const { routersWithoutAgents } = domainsOf(loom({
      agents: GROUPS, topology: ready(withIdle),
    }));
    expect(routersWithoutAgents).toBe(1);
  });

  it('derives nothing without a certified attachment', () => {
    const { rows, crossings } = domainsOf(loom({ agents: GROUPS }));
    expect(crossings).toHaveLength(0);
    // The census survives: it is authored intent.
    expect(rows.filter((r) => r.kind === 'clock')).toHaveLength(2);
    expect(rows.every((r) => r.attachedCount === 0)).toBe(true);
  });
});

const TRACE: TrafficMatrixView = {
  contract_version: 1,
  run_id: 'run-1',
  revision_id: 'r-1',
  design_hash: 'sha256:d',
  source: {
    trace: 't.trace', backend: 'BOOKSIM', declared_packets: 3, note: 'n',
  },
  nodes: 3,
  packets: 3,
  flits: 30,
  distinct_pairs: 3,
  classes: {},
  matrix: [[0, 10, 0], [0, 0, 20], [0, 0, 0]],
  flit_matrix: [[0, 100, 0], [0, 0, 200], [0, 0, 0]],
  pairs: [
    { src: 0, dst: 1, packets: 1, flits: 10 },
    { src: 1, dst: 2, packets: 2, flits: 20 },
  ],
};

function route(src: number, dst: number, channels: number[]): CanonicalRoute {
  const routers = channels.map((_, i) => src + i);
  routers.push(dst);
  return {
    routing_class: 'DOR_XY',
    src,
    dst,
    routers,
    hops: channels.map((channel_id, i) => ({
      channel_id, src_router: src + i, dst_router: src + i + 1,
      src_port: 1, dst_port: 1,
    })),
    terminates: true,
    terminal: 'LOCAL_EJECTION',
    reason: null,
  };
}

describe('expectedChannelLoad', () => {
  it('attributes measured flits to every channel on the frozen route', () => {
    const routes = new Map([
      ['0->1', route(0, 1, [0])],
      ['1->2', route(1, 2, [3])],
    ]);
    const load = expectedChannelLoad(TRACE, routes, TOPOLOGY);
    expect(load.map((l) => [l.channelId, l.flits])).toEqual([[3, 20], [0, 10]]);
    expect(load[0].pairs).toBe(1);
    expect(load[0].widthBits).toBe(64);
    expect(load[0].latencyCycles).toBe(1);
  });

  it('sums across pairs that share a channel', () => {
    const shared: TrafficMatrixView = {
      ...TRACE,
      pairs: [
        { src: 0, dst: 1, packets: 1, flits: 10 },
        { src: 2, dst: 3, packets: 1, flits: 5 },
      ],
    };
    const routes = new Map([
      ['0->1', route(0, 1, [0])],
      ['2->3', route(2, 3, [0])],
    ]);
    const load = expectedChannelLoad(shared, routes, TOPOLOGY);
    expect(load).toHaveLength(1);
    expect(load[0].flits).toBe(15);
    expect(load[0].pairs).toBe(2);
  });

  it('attributes nothing for a pair with no resolved route', () => {
    const routes = new Map([['0->1', route(0, 1, [0])]]);
    const load = expectedChannelLoad(TRACE, routes, TOPOLOGY);
    expect(load).toHaveLength(1);
    expect(load.some((l) => l.channelId === 3)).toBe(false);
  });

  it('leaves channel geometry at zero when no topology carries it', () => {
    const routes = new Map([['0->1', route(0, 1, [0])]]);
    const load = expectedChannelLoad(TRACE, routes, null);
    expect(load[0].widthBits).toBe(0);
    expect(load[0].latencyCycles).toBe(0);
  });

  it('skips self-traffic, which crosses no channel', () => {
    const selfOnly: TrafficMatrixView = {
      ...TRACE,
      pairs: [{ src: 1, dst: 1, packets: 4, flits: 40 }],
    };
    expect(expectedChannelLoad(selfOnly, new Map(), TOPOLOGY)).toHaveLength(0);
  });
});

describe('sweepPairs', () => {
  it('drops self-traffic and orders by measured load', () => {
    const pairs = sweepPairs({
      ...TRACE,
      pairs: [
        { src: 0, dst: 0, packets: 9, flits: 90 },
        { src: 0, dst: 1, packets: 1, flits: 10 },
        { src: 1, dst: 2, packets: 2, flits: 20 },
        { src: 2, dst: 3, packets: 0, flits: 0 },
      ],
    });
    expect(pairs.map((p) => `${p.src}->${p.dst}`)).toEqual(['1->2', '0->1']);
  });
});

const PREFLIGHT_OK: PreflightView = {
  contract_version: 1,
  revision_id: 'r-1',
  display_name: 'r1',
  backend: 'booksim_standalone',
  backend_profile: 'CERTIFIED_BOOKSIM_MESH_DOR_XY_V1',
  network_clock_hz: 1_000_000_000,
  expected_evidence_tier: 'authenticated backend evidence',
  route_observation_required: true,
  conservation_required: true,
  gates: [
    { gate: 'compilation', state: 'READY', reason: null },
    { gate: 'backend', state: 'READY', reason: null },
  ],
  ready: true,
  reason: null,
};

const INTEGRITY_OK: RunIntegrityView = {
  contract_version: 1,
  run_id: 'run-1',
  packet_conservation: {
    declared: { value: 3, availability: 'MEASURED' },
    loaded: { value: 3, availability: 'MEASURED' },
    injected: { value: 3, availability: 'MEASURED' },
    delivered: { value: 3, availability: 'MEASURED' },
    verdict: 'CONSERVED',
  },
  flit_conservation: null,
  route_realization: null,
} as unknown as RunIntegrityView;

describe('problemsOf', () => {
  const clean = loom({ revisionId: 'r-1' });

  it('reports nothing when every loaded artifact passed', () => {
    const problems = problemsOf(clean, { preflight: PREFLIGHT_OK, integrity: INTEGRITY_OK });
    expect(problems).toHaveLength(0);
  });

  it('surfaces a preflight gate that is not ready, with its reason', () => {
    const blocked: PreflightView = {
      ...PREFLIGHT_OK,
      ready: false,
      gates: [{
        gate: 'backend', state: 'BLOCKED', reason: 'binary absent',
      }],
    };
    const problems = problemsOf(clean, { preflight: blocked, integrity: null });
    expect(problems).toHaveLength(1);
    expect(problems[0].id).toBe('preflight-backend');
    expect(problems[0].severity).toBe('bad');
    expect(problems[0].detail).toContain('binary absent');
    expect(problems[0].source).toBe('preflight.backend');
  });

  it('flags a stale draft as advisory and names both facts', () => {
    const problems = problemsOf(
      { ...clean, dirty: true },
      { preflight: PREFLIGHT_OK, integrity: INTEGRITY_OK },
    );
    expect(problems.map((p) => p.id)).toContain('stale-draft');
    expect(problems.find((p) => p.id === 'stale-draft')?.severity).toBe('warn');
  });

  it('does not call a draft stale when no revision exists to compare it to', () => {
    // Staleness is a comparison. A never-compiled project has nothing to be
    // stale against, so the single finding is "no compiled revision".
    const problems = problemsOf(
      { ...clean, revisionId: null, dirty: true },
      { preflight: null, integrity: null },
    );
    expect(problems.map((p) => p.id)).toEqual(['no-revision']);
    expect(problems[0].severity).toBe('info');
  });

  it('flags a violated conservation check rather than reporting green', () => {
    const broken = {
      ...INTEGRITY_OK,
      packet_conservation: {
        ...INTEGRITY_OK.packet_conservation!,
        verdict: 'VIOLATED' as const,
      },
    };
    const problems = problemsOf(clean, { preflight: PREFLIGHT_OK, integrity: broken });
    expect(problems.map((p) => p.id)).toContain('conservation-VIOLATED');
  });

  it('does not raise a conservation finding for NOT_MEASURED', () => {
    const unmeasured = {
      ...INTEGRITY_OK,
      packet_conservation: {
        ...INTEGRITY_OK.packet_conservation!,
        verdict: 'NOT_MEASURED' as const,
      },
    };
    const problems = problemsOf(clean, { preflight: PREFLIGHT_OK, integrity: unmeasured });
    // NOT_MEASURED is the backend declining to measure, not a failed check.
    // It is not a green light either: the Simulation view says so in place.
    expect(problems.find((p) => p.id.startsWith('conservation-'))).toBeUndefined();
  });

  it('names the missing revision instead of drawing an empty fabric', () => {
    const problems = problemsOf(
      { ...clean, revisionId: null },
      { preflight: null, integrity: null },
    );
    expect(problems.map((p) => p.id)).toContain('no-revision');
  });

  it('flags a trace counted against a different revision', () => {
    const problems = problemsOf(
      { ...clean, traffic: ready({ ...TRACE, revision_id: 'r-99' }) },
      { preflight: PREFLIGHT_OK, integrity: null },
    );
    const stale = problems.find((p) => p.id === 'trace-revision');
    expect(stale?.severity).toBe('warn');
    expect(stale?.detail).toContain('r-99');
  });

  it('orders blocking findings above advisory ones', () => {
    const blocked: PreflightView = {
      ...PREFLIGHT_OK,
      gates: [{ gate: 'backend', state: 'BLOCKED', reason: 'x' }],
    };
    const problems = problemsOf(
      { ...clean, dirty: true },
      { preflight: blocked, integrity: null },
    );
    expect(problems[0].severity).toBe('bad');
    expect(problems[problems.length - 1].severity).toBe('warn');
  });
});