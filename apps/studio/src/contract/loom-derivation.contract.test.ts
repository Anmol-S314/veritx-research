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
  agentRows, declaredScope, domainsOf, expectedChannelLoad, problemsOf,
  reachabilityLadder, resolveRouterPairs, sweepPairs,
  type LadderStep,
  type LoomData, type Query,
} from '../pages/loom/data';
import { revisionFreshness, sectionFreshness } from '../pages/loom/freshness';
import { SERVED_PROVENANCE } from './servedProvenance.fixture';
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
    basedOnRevisionId: 'r-1',
    dirty: false,
    draftRequest: null,
    reloadDraft: () => {},
    agents: [],
    topology: absent<TopologyView>(null),
    compileResult: absent(null),
    latestRun: null,
    run: absent(null),
    traffic: absent<TrafficMatrixView | null>(null),
    trafficUnavailable: null,
    lowering: absent(null),
    provenance: absent(SERVED_PROVENANCE),
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
    expect(rows.every((r) => r.scope === 'ATTACHED')).toBe(true);
    expect(rows.every((r) => r.integrityNote === null)).toBe(true);
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
    expect(rows.every((r) => r.scope === 'UNATTACHED')).toBe(true);
    expect(rows.every((r) => r.endpointId === -1)).toBe(true);
    expect(rows.every((r) => r.routerId === null)).toBe(true);
  });

  it('marks seats with no declared group as orphan artifacts, not intent', () => {
    const rows = agentRows(loom({ agents: [], topology: ready(TOPOLOGY) }));
    expect(rows).toHaveLength(4);
    expect(rows.every((r) => r.scope === 'ORPHAN_ARTIFACT')).toBe(true);
    expect(rows.every((r) => !r.attached)).toBe(true);
    expect(rows[0].protocol).toBeNull();
    expect(rows[0].dataWidth).toBeNull();
    expect(rows[0].integrityNote).toMatch(/group 0/);
  });

  it('keeps declared-but-unseated agents once a compiled topology exists', () => {
    // Group 1 declares 3 instances; the attachment seats 2. The third must
    // appear as UNATTACHED — the old code returned endpoints only.
    const groups = [
      { ...GROUPS[0] },
      { ...GROUPS[1], count: 3 },
    ];
    const rows = agentRows(loom({ agents: groups, topology: ready(TOPOLOGY) }));
    expect(rows).toHaveLength(5);
    const unattached = rows.filter((r) => r.scope === 'UNATTACHED');
    expect(unattached).toHaveLength(1);
    expect(unattached[0].groupIndex).toBe(1);
    expect(unattached[0].instanceIndex).toBe(2);
    expect(unattached[0].endpointId).toBe(-1);
    // The declared census still equals the draft: 2 + 3.
    const declared = rows.filter((r) => r.scope === 'ATTACHED' || r.scope === 'UNATTACHED');
    expect(declared).toHaveLength(5);
  });

  it('flags a seated instance the draft never declared as an orphan', () => {
    // Group 0 declares 1 instance; the attachment seats 2 of group 0.
    const groups = [{ ...GROUPS[0], count: 1 }, { ...GROUPS[1] }];
    const rows = agentRows(loom({ agents: groups, topology: ready(TOPOLOGY) }));
    const orphans = rows.filter((r) => r.scope === 'ORPHAN_ARTIFACT');
    expect(orphans).toHaveLength(1);
    expect(orphans[0].endpointId).toBe(11);
    expect(orphans[0].integrityNote).toMatch(/instance 1/);
    // Declared census is still exactly the draft: 1 + 2.
    const declared = rows.filter((r) => r.scope === 'ATTACHED' || r.scope === 'UNATTACHED');
    expect(declared).toHaveLength(3);
  });

  it('flags a group_index outside the draft as an orphan, with the draft size named', () => {
    const topo = {
      ...TOPOLOGY,
      endpoints: [
        ...TOPOLOGY.endpoints,
        { endpoint_id: 20, kind: 'nic', group_index: 7, instance_index: 0, router_id: 0, port_id: 1 },
      ],
    };
    const rows = agentRows(loom({ agents: GROUPS, topology: ready(topo) }));
    const orphan = rows.find((r) => r.endpointId === 20);
    expect(orphan?.scope).toBe('ORPHAN_ARTIFACT');
    expect(orphan?.integrityNote).toMatch(/group 7/);
    expect(orphan?.integrityNote).toMatch(/2 group/);
  });

  it('joins mixed groups by position, never by kind', () => {
    // Two groups of the same kind: the seat must follow group_index, so the
    // second group's instance carries the second group's fields.
    const groups = [
      { ...GROUPS[0], count: 1, clock_domain: 'clk_first' },
      { ...GROUPS[0], count: 1, clock_domain: 'clk_second' },
    ];
    const topo = {
      ...TOPOLOGY,
      endpoints: [
        { endpoint_id: 10, kind: 'compute_tile', group_index: 0, instance_index: 0, router_id: 0, port_id: 0 },
        { endpoint_id: 11, kind: 'compute_tile', group_index: 1, instance_index: 0, router_id: 1, port_id: 0 },
      ],
    };
    const rows = agentRows(loom({ agents: groups, topology: ready(topo) }));
    expect(rows).toHaveLength(2);
    expect(rows[0].clockDomain).toBe('clk_first');
    expect(rows[1].clockDomain).toBe('clk_second');
    expect(rows.every((r) => r.scope === 'ATTACHED')).toBe(true);
  });

  it('flags a kind mismatch at the same key as an integrity error', () => {
    const topo = {
      ...TOPOLOGY,
      endpoints: [
        { endpoint_id: 10, kind: 'hbm_controller', group_index: 0, instance_index: 0, router_id: 0, port_id: 0 },
        ...TOPOLOGY.endpoints.slice(1),
      ],
    };
    const rows = agentRows(loom({ agents: GROUPS, topology: ready(topo) }));
    const bad = rows.find((r) => r.endpointId === 10);
    expect(bad?.scope).toBe('INTEGRITY_ERROR');
    expect(bad?.attached).toBe(false);
    expect(bad?.integrityNote).toMatch(/kind mismatch/);
    expect(bad?.integrityNote).toMatch(/compute_tile/);
    expect(bad?.integrityNote).toMatch(/hbm_controller/);
  });

  it('protects against duplicate seats claiming one instance', () => {
    const topo = {
      ...TOPOLOGY,
      endpoints: [
        ...TOPOLOGY.endpoints,
        { endpoint_id: 99, kind: 'compute_tile', group_index: 0, instance_index: 0, router_id: 2, port_id: 1 },
      ],
    };
    const rows = agentRows(loom({ agents: GROUPS, topology: ready(topo) }));
    const dup = rows.find((r) => r.endpointId === 99);
    expect(dup?.scope).toBe('INTEGRITY_ERROR');
    expect(dup?.integrityNote).toMatch(/duplicate seat/);
    expect(dup?.integrityNote).toMatch(/endpoint 10/);
    // The first claim still seats the instance exactly once.
    const first = rows.find((r) => r.endpointId === 10);
    expect(first?.scope).toBe('ATTACHED');
  });

  it('keeps the declared count equal to the draft even with artifacts present', () => {
    const groups = [{ ...GROUPS[0], count: 1 }, { ...GROUPS[1] }];
    const topo = {
      ...TOPOLOGY,
      endpoints: [
        ...TOPOLOGY.endpoints,
        { endpoint_id: 20, kind: 'nic', group_index: 7, instance_index: 0, router_id: 0, port_id: 1 },
      ],
    };
    const rows = agentRows(loom({ agents: groups, topology: ready(topo) }));
    const declared = rows.filter((r) => r.scope === 'ATTACHED' || r.scope === 'UNATTACHED');
    expect(declared).toHaveLength(1 + 2);
  });
});

describe('declaredScope', () => {
  it('reports the draft census and no frozen scope without a loaded project', () => {
    const scope = declaredScope(loom({ agents: GROUPS, dirty: false }));
    expect(scope.draftTotal).toBe(4);
    expect(scope.dirty).toBe(false);
    expect(scope.revisionTotal).toBeNull();
    expect(scope.revisionGroups).toBeNull();
  });

  it('shows both scopes when the draft is dirty', () => {
    const project = {
      active_revision: {
        design: { agents: [{ kind: 'compute_tile', count: 2 }] },
      },
    };
    const scope = declaredScope(loom({
      agents: GROUPS,
      dirty: true,
      revisionId: 'r-9',
      project: project as never,
    }));
    expect(scope.dirty).toBe(true);
    expect(scope.draftTotal).toBe(4);
    expect(scope.revisionId).toBe('r-9');
    expect(scope.revisionTotal).toBe(2);
    expect(scope.revisionGroups).toEqual([{ kind: 'compute_tile', count: 2 }]);
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
  contract_version: 2,
  availability: 'MEASURED',
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

  it('attributes nothing from a route that does not terminate', () => {
    const dead: CanonicalRoute = {
      ...route(0, 1, [0]),
      terminates: false,
      terminal: null,
      reason: 'no entry (DOR_XY,0,1)',
    };
    const routes = new Map([['0->1', dead]]);
    expect(expectedChannelLoad(TRACE, routes, TOPOLOGY)).toHaveLength(0);
  });
});

describe('resolveRouterPairs', () => {
  // Concentration 2: endpoints 0,1 sit on router 0; 2,3 on router 1.
  const C2: TopologyView = {
    ...TOPOLOGY,
    routers: [
      { router_id: 0, coordinates: [0, 0], seat_capacity: 2 },
      { router_id: 1, coordinates: [0, 1], seat_capacity: 2 },
    ],
    endpoints: [
      { endpoint_id: 0, kind: 'compute_tile', group_index: 0, instance_index: 0, router_id: 0, port_id: 0 },
      { endpoint_id: 1, kind: 'compute_tile', group_index: 0, instance_index: 1, router_id: 0, port_id: 1 },
      { endpoint_id: 2, kind: 'compute_tile', group_index: 0, instance_index: 2, router_id: 1, port_id: 0 },
      { endpoint_id: 3, kind: 'compute_tile', group_index: 0, instance_index: 3, router_id: 1, port_id: 1 },
    ],
  };

  it('resolves endpoints to routers through the certified attachment', () => {
    const { routable, unresolvable } = resolveRouterPairs(
      [{ src: 0, dst: 2, packets: 1, flits: 10 }], C2);
    expect(unresolvable).toHaveLength(0);
    expect(routable).toHaveLength(1);
    expect(routable[0].srcRouter).toBe(0);
    expect(routable[0].dstRouter).toBe(1);
    expect(routable[0].local).toBe(false);
  });

  it('marks same-router pairs local instead of routing an endpoint id', () => {
    // Endpoints 0 and 1 share router 0: the route is a trivial local
    // ejection, and the query must carry (0, 0), never (0, 1).
    const { routable } = resolveRouterPairs(
      [{ src: 0, dst: 1, packets: 1, flits: 10 }], C2);
    expect(routable).toHaveLength(1);
    expect(routable[0].srcRouter).toBe(0);
    expect(routable[0].dstRouter).toBe(0);
    expect(routable[0].local).toBe(true);
  });

  it('counts pairs with no certified seat as unresolvable, never queried', () => {
    const { routable, unresolvable } = resolveRouterPairs(
      [
        { src: 0, dst: 2, packets: 1, flits: 10 },
        { src: 0, dst: 99, packets: 1, flits: 10 },
      ], C2);
    expect(routable).toHaveLength(1);
    expect(unresolvable).toHaveLength(1);
    expect(unresolvable[0].dst).toBe(99);
  });

  it('resolves concentration 4 without confusing endpoint and router ids', () => {
    const endpoints = Array.from({ length: 8 }, (_, i) => ({
      endpoint_id: i,
      kind: 'compute_tile',
      group_index: 0,
      instance_index: i,
      router_id: i < 4 ? 0 : 1,
      port_id: i % 4,
    }));
    const c4: TopologyView = { ...C2, endpoints };
    // Endpoint pair (1, 6): routers (0, 1). Naively querying (1, 6) would
    // ask the route table about routers that may not even exist.
    const { routable } = resolveRouterPairs(
      [{ src: 1, dst: 6, packets: 1, flits: 10 }], c4);
    expect(routable[0].srcRouter).toBe(0);
    expect(routable[0].dstRouter).toBe(1);
  });

  it('resolves 1024 endpoints over 256 routers', () => {
    const endpoints = Array.from({ length: 1024 }, (_, i) => ({
      endpoint_id: i,
      kind: 'compute_tile',
      group_index: 0,
      instance_index: i,
      router_id: Math.floor(i / 4),
      port_id: i % 4,
    }));
    const big: TopologyView = {
      ...C2,
      routers: Array.from({ length: 256 }, (_, i) => ({
        router_id: i, coordinates: [i % 16, Math.floor(i / 16)], seat_capacity: 4,
      })),
      endpoints,
    };
    const { routable, unresolvable } = resolveRouterPairs(
      [
        { src: 0, dst: 1023, packets: 1, flits: 10 },
        { src: 511, dst: 512, packets: 1, flits: 10 },
        { src: 7, dst: 2000, packets: 1, flits: 10 },
      ], big);
    expect(routable).toHaveLength(2);
    expect(routable[0].srcRouter).toBe(0);
    expect(routable[0].dstRouter).toBe(255);
    expect(routable[1].srcRouter).toBe(127);
    expect(routable[1].dstRouter).toBe(128);
    expect(unresolvable).toHaveLength(1);
  });

  it('resolves nothing without a certified attachment', () => {
    const pairs = [{ src: 0, dst: 1, packets: 1, flits: 10 }];
    const { routable, unresolvable } = resolveRouterPairs(pairs, null);
    expect(routable).toHaveLength(0);
    expect(unresolvable).toHaveLength(1);
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

  it('turns a failed preflight read into an advisory finding, not silence', () => {
    const problems = problemsOf(clean, {
      preflight: null, integrity: INTEGRITY_OK, preflightError: 'HTTP_500',
    });
    const finding = problems.find((p) => p.id === 'preflight-unreadable');
    expect(finding?.severity).toBe('warn');
    expect(finding?.detail).toMatch(/HTTP_500/);
    expect(finding?.detail).toMatch(/not a clean bill/);
  });

  it('turns a failed integrity read into an advisory finding, not silence', () => {
    const problems = problemsOf(clean, {
      preflight: PREFLIGHT_OK, integrity: null, integrityError: 'gateway unreachable',
    });
    const finding = problems.find((p) => p.id === 'integrity-unreadable');
    expect(finding?.severity).toBe('warn');
    expect(finding?.detail).toMatch(/gateway unreachable/);
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
});describe('reachabilityLadder', () => {
  // TOPOLOGY has routers 0..3, endpoints on 0..3, and channels 0-1-3 plus
  // 0-2. Variants below only rewire the channel list.
  const chan = (pairs: [number, number][]): TopologyView['channels'] =>
    pairs.flatMap(([a, b], i) => ([
      {
        channel_id: 2 * i, src_router: a, src_port: i, dst_router: b,
        dst_port: i, width_bits: 64, latency_cycles: 1,
      },
      {
        channel_id: 2 * i + 1, src_router: b, src_port: i, dst_router: a,
        dst_port: i, width_bits: 64, latency_cycles: 1,
      },
    ]));

  const q = (over: Record<string, unknown> = {}) => ({
    src: 0, dst: 3, route: null, routeAsked: false, measured: null, ...over,
  });

  const stateOf = (steps: LadderStep[], layer: string): string | undefined =>
    steps.find((s) => s.layer === layer)?.state;
  const stepOf = (steps: LadderStep[], layer: string): LadderStep | undefined =>
    steps.find((s) => s.layer === layer);

  it('always answers all five layers, in order', () => {
    const steps = reachabilityLadder(TOPOLOGY, q());
    expect(steps.map((s) => s.layer)).toEqual([
      'PHYSICAL_REACHABILITY', 'ADDRESS_REACHABILITY', 'ACCESS_POLICY',
      'RESOLVED_ROUTE', 'MEASURED',
    ]);
  });

  it('reads connectivity from the certified channels, undirected', () => {
    const t = { ...TOPOLOGY, channels: chan([[3, 2], [2, 1], [1, 0]]) };
    const steps = reachabilityLadder(t, q());
    expect(stateOf(steps, 'PHYSICAL_REACHABILITY')).toBe('CONNECTED');
    // The basis names the channel count so the reader can check the traversal.
    expect(stepOf(steps, 'PHYSICAL_REACHABILITY')?.basis).toMatch(/3 certified channel/);
  });

  it('calls an unjoined pair DISCONNECTED and never a permission denial', () => {
    const t = { ...TOPOLOGY, channels: chan([[0, 1], [2, 3]]) };
    const steps = reachabilityLadder(t, q());
    expect(stateOf(steps, 'PHYSICAL_REACHABILITY')).toBe('DISCONNECTED');
    const basis = stepOf(steps, 'PHYSICAL_REACHABILITY')?.basis ?? '';
    expect(basis).toMatch(/not a permission decision/i);
    // The words a firewall would use must not appear.
    expect(basis).not.toMatch(/denied|blocked|forbidden|deny/i);
  });

  it('has no access policy to report, whatever the pair looks like', () => {
    const t = { ...TOPOLOGY, channels: chan([[0, 1], [2, 3]]) };
    for (const [src, dst] of [[0, 3], [0, 0], [1, 1]]) {
      const steps = reachabilityLadder(t, q({ src, dst }));
      const policy = stepOf(steps, 'ACCESS_POLICY');
      expect(policy?.state).toBe('NO_ARTIFACT');
      // No artifact means no origin. Claiming DERIVED here would invent one.
      expect(policy?.origin).toBeNull();
      expect(policy?.artifact).toBe('');
    }
  });

  it('never derives address reachability from connectivity', () => {
    const joined = { ...TOPOLOGY, channels: chan([[0, 1], [1, 3]]) };
    const steps = reachabilityLadder(joined, q({ src: 0, dst: 2 }));
    // 0 and 2 are joined through 1 in this wiring, but 2 has a seat anyway in
    // TOPOLOGY. Use a truly bare router instead:
    const bare: TopologyView = {
      ...TOPOLOGY,
      channels: chan([[0, 2]]),
      endpoints: TOPOLOGY.endpoints.filter((e) => e.router_id === 0),
    };
    const bare2 = reachabilityLadder(bare, q({ src: 0, dst: 2 }));
    expect(stateOf(bare2, 'PHYSICAL_REACHABILITY')).toBe('CONNECTED');
    expect(stateOf(bare2, 'ADDRESS_REACHABILITY')).toBe('DST_UNSEATED');
    expect(stateOf(steps, 'ADDRESS_REACHABILITY')).toBe('BOTH_SEATED');
  });

  it('reports no topology as no topology, not as a disconnected pair', () => {
    const steps = reachabilityLadder(null, q());
    expect(stateOf(steps, 'PHYSICAL_REACHABILITY')).toBe('NO_TOPOLOGY');
    expect(stateOf(steps, 'ACCESS_POLICY')).toBe('NO_ARTIFACT');
  });

  it('does not borrow the route answer for the physical layer', () => {
    const route = {
      routing_class: 'DOR_XY', src: 0, dst: 3,
      routers: [0, 1, 3],
      hops: [
        {
          channel_id: 0, src_router: 0, dst_router: 1, src_port: 0,
          dst_port: 0,
        },
      ],
      terminates: true, terminal: null, reason: null,
    } as CanonicalRoute;
    const steps = reachabilityLadder(TOPOLOGY, q({ routeAsked: true, route }));
    expect(stateOf(steps, 'RESOLVED_ROUTE')).toBe('RESOLVED');
    expect(stateOf(steps, 'PHYSICAL_REACHABILITY')).toBe('CONNECTED');
    // And an incomplete route is not reported as connected.
    const partial = { ...route, terminates: false, hops: [] } as CanonicalRoute;
    const inc = reachabilityLadder(TOPOLOGY, q({ routeAsked: true, route: partial }));
    expect(stateOf(inc, 'RESOLVED_ROUTE')).toBe('INCOMPLETE');
  });

  it('never calls an unasked route a missing one', () => {
    expect(stateOf(reachabilityLadder(TOPOLOGY, q()), 'RESOLVED_ROUTE'))
      .toBe('NOT_ASKED');
  });

  it('holds measured traffic to MEASURED and a run', () => {
    const none = reachabilityLadder(TOPOLOGY, q());
    expect(stateOf(none, 'MEASURED')).toBe('NO_RUN');
    expect(stepOf(none, 'MEASURED')?.origin).toBeNull();

    const zero = reachabilityLadder(TOPOLOGY, q({ measured: { packets: 0, flits: 0, scope: true } }));
    expect(stateOf(zero, 'MEASURED')).toBe('ZERO');
    expect(stepOf(zero, 'MEASURED')?.origin).toBe('MEASURED');

    const seen = reachabilityLadder(TOPOLOGY, q({ measured: { packets: 12, flits: 96, scope: true } }));
    expect(stateOf(seen, 'MEASURED')).toBe('OBSERVED');
    // A measurement is never a permission.
    expect(stepOf(seen, 'MEASURED')?.basis).toMatch(/not permission/i);
  });

  it('gives every state that claims an artifact one', () => {
    const steps = reachabilityLadder(TOPOLOGY, q({
      routeAsked: true, measured: { packets: 3, flits: 9, scope: true },
    }));
    for (const step of steps) {
      if (step.origin === null) {
        expect(step.artifact).toBe('');
      } else {
        expect(step.artifact).not.toBe('');
        expect(step.basis.length).toBeGreaterThan(0);
      }
    }
  });
});

describe('reachabilityLadder measured scope', () => {
  const two: TopologyView = {
    ...TOPOLOGY,
    routers: [
      { router_id: 0, coordinates: [0, 0], seat_capacity: 1 },
      { router_id: 9, coordinates: [1, 0], seat_capacity: 1 },
    ],
  };
  const step = (measured: { packets: number; flits: number; scope: boolean } | null) =>
    reachabilityLadder(two, {
      src: 0, dst: 9, route: null, routeAsked: false, measured,
    }).find((s) => s.layer === 'MEASURED');

  it('reports an uncounted pair as out of matrix, never as zero', () => {
    const s = step({ packets: 0, flits: 0, scope: false });
    expect(s?.state).toBe('OUT_OF_MATRIX');
    // No run counted it, so it must not claim a measurement either.
    expect(s?.origin).toBeNull();
    expect(s?.artifact).toBe('');
    expect(s?.basis).toMatch(/not a cell of zero/i);
  });

  it('reports a counted zero as zero', () => {
    const s = step({ packets: 0, flits: 0, scope: true });
    expect(s?.state).toBe('ZERO');
    expect(s?.origin).toBe('MEASURED');
  });
});

describe('sectionFreshness', () => {
  const runView = (freshness: unknown) => ({
    run_id: 'run-1',
    freshness,
    // The helper reads run_id and freshness only; the rest is filler so the
    // fixture satisfies the view type without dragging a full run along.
  }) as unknown as import('../api/types').RunView;

  it('quotes the server for run-scoped artifacts, never computing its own', () => {
    const server = {
      state: 'STALE',
      meaning: 'the server sentence for why this run is stale',
    };
    const data = loom({ run: ready(runView(server)) });
    for (const artifact of ['run', 'traffic_matrix', 'evidence']) {
      const fresh = sectionFreshness(data, artifact);
      expect(fresh?.state).toBe('STALE');
      // The basis is the server's meaning verbatim, not a client paraphrase.
      expect(fresh?.basis).toBe('the server sentence for why this run is stale');
    }
  });

  it('shows no badge when the run view carries no freshness', () => {
    const data = loom({ run: ready(runView(null)) });
    expect(sectionFreshness(data, 'run')).toBeNull();
    expect(sectionFreshness(loom(), 'traffic_matrix')).toBeNull();
  });

  it('calls a dirty draft STALE and a clean one CURRENT', () => {
    expect(sectionFreshness(loom({ dirty: true }), 'draft')?.state).toBe('STALE');
    expect(sectionFreshness(loom({ dirty: false }), 'draft')?.state).toBe('CURRENT');
    const basis = sectionFreshness(loom({ dirty: true }), 'draft')?.basis ?? '';
    expect(basis).toMatch(/uncompiled changes/i);
  });

  it('compares revision-scoped artifacts by identity', () => {
    const same = loom({ revisionId: 'r-1', topology: ready(TOPOLOGY) });
    expect(sectionFreshness(same, 'topology')?.state).toBe('CURRENT');
    expect(sectionFreshness(same, 'attachment')?.state).toBe('CURRENT');
    expect(sectionFreshness(same, 'route')?.state).toBe('CURRENT');

    const foreign = loom({
      revisionId: 'r-2',
      topology: ready({ ...TOPOLOGY, revision_id: 'r-1' }),
    });
    const stale = sectionFreshness(foreign, 'topology');
    expect(stale?.state).toBe('FOREIGN_REVISION');
    expect(stale?.basis).toMatch(/r-1/);
    expect(stale?.basis).toMatch(/r-2/);
  });

  it('shows no badge when either revision is missing', () => {
    expect(sectionFreshness(loom({ revisionId: null }), 'topology')).toBeNull();
    const noTopo = loom({ revisionId: 'r-1', topology: absent<TopologyView>(null) });
    expect(sectionFreshness(noTopo, 'topology')).toBeNull();
  });

  it('refuses to badge artifacts that are not revision-scoped', () => {
    // backend profiles are declared, the registry describes the installed
    // system, and the lowering carries no revision. CURRENT for any of them
    // would invent versioning that does not exist.
    const data = loom({ run: ready(runView({ state: 'CURRENT', meaning: 'm' })) });
    for (const artifact of ['backend', 'capability', 'lowering']) {
      expect(sectionFreshness(data, artifact)).toBeNull();
    }
  });

  it('badges each compared run side on its own revision', () => {
    expect(revisionFreshness('r-1', 'r-1', 'run a')?.state).toBe('CURRENT');
    const foreign = revisionFreshness('r-1', 'r-2', 'run b');
    expect(foreign?.state).toBe('FOREIGN_REVISION');
    expect(foreign?.basis).toMatch(/run b/);
    expect(revisionFreshness(null, 'r-1', 'run a')).toBeNull();
  });
});
