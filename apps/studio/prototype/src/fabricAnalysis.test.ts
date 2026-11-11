import { describe, expect, it } from 'vitest';
import type { CompileResult, Topology } from './gateway';
import {
  buildFabricAnalysis, certificateChecks, controlChecks, islandChecks, portBudgetChecks, reachabilityChecks,
  rtlReachRows, srotaCdg, srotaShapeChecks,
} from './fabricAnalysis';

const srotaRequest = (overrides: Record<string, unknown> = {}) => ({
  topology: {
    kind: 'srota', side_length: 4, concentration: 2, drop_latency: 1,
    mecs_row: true, mecs_col: true, planes: ['d', 't'], island_columns: [],
    path_shapes: ['row', 'column'], vc_policy: 'shape', sidebuf_enable: true,
    sidebuf_watermark: 6, tel_period: 4, tel_latency: 8,
    ...overrides,
  },
  agents: [
    { kind: 'compute_tile', count: 8, data_width: 256, addr_width: 64, protocol: 'AXI' },
    { kind: 'hbm_controller', count: 2, data_width: 512, addr_width: 48, protocol: 'CHI' },
  ],
  address_map: { ranges: [
    { name: 'HBM0', base: 0x1000_0000, size: 0x1000_0000, target_agent_idx: 1, selection_policy: 'FIXED_INSTANCE', target_instance_index: 0 },
    { name: 'HBM1', base: 0x2000_0000, size: 0x1000_0000, target_agent_idx: 1, selection_policy: 'FIXED_INSTANCE', target_instance_index: 1 },
  ] },
  noc_controls: { link_width: 512, input_buffer_depth_flits_per_vc: 8, arbitration: 'islip' },
});

const mesh = (): Topology => {
  const routers = Array.from({ length: 16 }, (_, index) => ({ router_id: index, coordinates: [index % 4, Math.floor(index / 4)], seat_capacity: 2 }));
  const channels = [];
  let channel = 0;
  for (let y = 0; y < 4; y += 1) {
    for (let x = 0; x < 4; x += 1) {
      const id = y * 4 + x;
      if (x < 3) {
        channels.push({ channel_id: channel++, src_router: id, dst_router: id + 1, src_port: 0, dst_port: 1, width_bits: 512, latency_cycles: 1 });
        channels.push({ channel_id: channel++, src_router: id + 1, dst_router: id, src_port: 1, dst_port: 0, width_bits: 512, latency_cycles: 1 });
      }
      if (y < 3) {
        channels.push({ channel_id: channel++, src_router: id, dst_router: id + 4, src_port: 2, dst_port: 3, width_bits: 512, latency_cycles: 1 });
        channels.push({ channel_id: channel++, src_router: id + 4, dst_router: id, src_port: 3, dst_port: 2, width_bits: 512, latency_cycles: 1 });
      }
    }
  }
  return {
    family: 'srota', counts: { routers: 16, channels: channels.length }, routers, channels,
    endpoints: [
      { endpoint_id: 0, router_id: 0, kind: 'hbm_controller', port_id: 0 },
      { endpoint_id: 1, router_id: 4, kind: 'hbm_controller', port_id: 0 },
      ...Array.from({ length: 8 }, (_, index) => ({ endpoint_id: index + 2, router_id: index + 8, kind: 'compute_tile', port_id: 0 })),
    ],
    island_columns: [],
  };
};

const compileResult = (overrides: Record<string, unknown> = {}): CompileResult => ({
  certificate: {
    overall: 'PASS',
    claims: [
      { obligation: 'ATTACHMENT_COMPLETE', status: 'PASS' },
      { obligation: 'DEADLOCK_FREE', status: 'PASS' },
    ],
  },
  groups: {
    resources: {
      vc_count: 2,
      deadlock: {
        status: 'PASS', method: 'shared-resource-cdg/v1',
        evidence: { proof_method: 'CHANNEL_VC_DEPENDENCY_ACYCLIC', nodes: 160, edges: 144, cycle: [], routing_class: 'SROTA_O1TURN_SHAPE_POLICY' },
      },
    },
    address_decode: { available: true, rows: [{ name: 'HBM0', base: 0x1000_0000, size: 0x1000_0000 }], address_transform: 'IDENTITY', unmatched_address_policy: 'ERROR' },
    ...overrides,
  },
});

describe('Srota path-shape CDG abstraction', () => {
  it('finds the RT-R7 two-node cycle when both direct shapes share VCs', () => {
    const result = srotaCdg(srotaRequest({ vc_policy: 'none' }));
    expect(result.acyclic).toBe(false);
    expect(result.cycle).toEqual(['row[0]', 'col[0]', 'row[0]']);
  });

  it('keeps the union acyclic when the shape policy separates VCs', () => {
    const result = srotaCdg(srotaRequest({ vc_policy: 'shape' }));
    expect(result.acyclic).toBe(true);
    expect(result.nodes).toContain('row[0]@vc0');
    expect(result.nodes).toContain('col[0]@vc1');
  });

  it('is acyclic for row-first alone', () => {
    const result = srotaCdg(srotaRequest({ path_shapes: ['row'], vc_policy: 'none' }));
    expect(result.acyclic).toBe(true);
    expect(result.cycle).toBeNull();
  });

  it('defers the rank policy to the compiler proof', () => {
    const result = srotaCdg(srotaRequest({ vc_policy: 'rank' }));
    expect(result.model).toContain('Rank policy');
    expect(result.nodes).toEqual([]);
  });

  it('does not claim a concurrent cycle for one-shape-per-epoch', () => {
    const result = srotaCdg(srotaRequest({ vc_policy: 'oneshape' }));
    expect(result.acyclic).toBe(true);
    expect(result.model).toContain('separated in time');
  });

  it('models Valiant as a second turn outside the rank policy', () => {
    const result = srotaCdg(srotaRequest({ path_shapes: ['valiant'], vc_policy: 'none' }));
    expect(result.acyclic).toBe(false);
    expect(result.model).toContain('turns twice');
  });
});

describe('Srota control checks mirror the compiler rules', () => {
  it('passes row+column under the shape policy', () => {
    const checks = srotaShapeChecks(srotaRequest());
    expect(checks.find(check => check.id === 'srota-direct-separation')?.status).toBe('PASS');
  });

  it('fails row+column when the shapes share VCs', () => {
    const checks = srotaShapeChecks(srotaRequest({ vc_policy: 'none' }));
    expect(checks.find(check => check.id === 'srota-direct-separation')?.status).toBe('FAIL');
  });

  it('fails Valiant under the shape policy and passes under rank with full MECS', () => {
    const refused = srotaShapeChecks(srotaRequest({ path_shapes: ['row', 'column', 'valiant'], vc_policy: 'shape' }));
    expect(refused.find(check => check.id === 'srota-valiant-policy')?.status).toBe('FAIL');
    const accepted = srotaShapeChecks(srotaRequest({ path_shapes: ['row', 'column', 'valiant'], vc_policy: 'rank' }));
    expect(accepted.find(check => check.id === 'srota-valiant-policy')?.status).toBe('PASS');
    expect(accepted.find(check => check.id === 'srota-valiant-mecs')?.status).toBe('PASS');
  });

  it('fails an island design without column-first', () => {
    const checks = srotaShapeChecks(srotaRequest({ path_shapes: ['row'], vc_policy: 'none', island_columns: [1] }));
    expect(checks.find(check => check.id === 'srota-island-shape')?.status).toBe('FAIL');
  });

  it('does not fail Valiant+row under the rank policy', () => {
    const checks = srotaShapeChecks(srotaRequest({ path_shapes: ['row', 'valiant'], vc_policy: 'rank' }));
    expect(checks.some(check => check.id === 'srota-derived-rule')).toBe(false);
    expect(checks.find(check => check.id === 'srota-valiant-policy')?.status).toBe('PASS');
  });

  it('requires both MECS directions for every rank-policy shape set', () => {
    const checks = srotaShapeChecks(srotaRequest({ path_shapes: ['row'], vc_policy: 'rank', mecs_col: false }));
    expect(checks.find(check => check.id === 'srota-rank-express')?.status).toBe('FAIL');
  });

  it('accepts column-only under rank with both MECS directions', () => {
    const checks = srotaShapeChecks(srotaRequest({ path_shapes: ['column'], vc_policy: 'rank' }));
    expect(checks.find(check => check.id === 'srota-column-only')?.status).toBe('PASS');
  });

  it('requires a separating VC policy for an island design', () => {
    const checks = srotaShapeChecks(srotaRequest({ path_shapes: ['row', 'column'], vc_policy: 'none', island_columns: [1] }));
    expect(checks.find(check => check.id === 'srota-island-shape')?.status).toBe('FAIL');
  });

  it('refuses column-only, which the derived route does not cover', () => {
    const checks = srotaShapeChecks(srotaRequest({ path_shapes: ['column'], vc_policy: 'none' }));
    expect(checks.find(check => check.id === 'srota-column-only')?.status).toBe('FAIL');
  });
});

describe('port budget', () => {
  it('reports the VC-R5 disagreement at c=4 with both MECS directions', () => {
    const checks = portBudgetChecks(srotaRequest({ concentration: 4 }));
    const budget = checks.find(check => check.id === 'port-budget');
    expect(budget?.status).toBe('WARN');
    expect(budget?.detail).toContain('P=16');
    expect(budget?.detail).toContain('P=12');
    expect(checks.some(check => check.id === 'port-budget-open')).toBe(true);
  });
});

describe('topology reachability', () => {
  it('passes a connected reciprocal mesh', () => {
    const checks = reachabilityChecks(mesh());
    expect(checks.find(check => check.id === 'topology-strong')?.status).toBe('PASS');
    expect(checks.find(check => check.id === 'topology-reciprocal')?.status).toBe('PASS');
    expect(checks.find(check => check.id === 'topology-endpoints')?.status).toBe('PASS');
  });

  it('fails a router that cannot be reached', () => {
    const broken = mesh();
    broken.channels = broken.channels.filter(channel => channel.dst_router !== 15 && channel.src_router !== 15);
    const checks = reachabilityChecks(broken);
    expect(checks.find(check => check.id === 'topology-strong')?.status).toBe('FAIL');
  });

  it('treats MECS shared-link taps as reachable routers', () => {
    const shared: Topology = {
      family: 'srota', counts: { routers: 4, shared_links: 4 },
      routers: [
        { router_id: 0, coordinates: [0, 0] }, { router_id: 1, coordinates: [1, 0] },
        { router_id: 2, coordinates: [0, 1] }, { router_id: 3, coordinates: [1, 1] },
      ],
      channels: [],
      shared_links: [
        { shared_link_id: 0, src_router: 0, taps: [1, 2, 3], width_bits: 512, latency_cycles: 1 },
        { shared_link_id: 1, src_router: 1, taps: [0, 3], width_bits: 512, latency_cycles: 1 },
        { shared_link_id: 2, src_router: 2, taps: [0, 3], width_bits: 512, latency_cycles: 1 },
        { shared_link_id: 3, src_router: 3, taps: [0, 1, 2], width_bits: 512, latency_cycles: 1 },
      ],
      endpoints: [{ endpoint_id: 0, router_id: 0, kind: 'compute_tile', port_id: 0 }],
    };
    const checks = reachabilityChecks(shared);
    expect(checks.find(check => check.id === 'topology-strong')?.status).toBe('PASS');
    expect(checks.find(check => check.id === 'topology-shared-taps')?.status).toBe('PASS');
    expect(checks.find(check => check.id === 'topology-endpoints')?.status).toBe('PASS');
  });
});

describe('island confinement', () => {
  it('passes when every target is on the declared island column', () => {
    const topology = { ...mesh(), island_columns: [0] };
    const checks = islandChecks(srotaRequest({ island_columns: [0] }), topology);
    expect(checks.find(check => check.id === 'island-placement')?.status).toBe('PASS');
  });

  it('fails when a target is outside the island column', () => {
    const topology = { ...mesh(), island_columns: [1] };
    const checks = islandChecks(srotaRequest({ island_columns: [1] }), topology);
    expect(checks.find(check => check.id === 'island-placement')?.status).toBe('FAIL');
  });
});

describe('executable controls', () => {
  it('passes the compiler default and iSLIP', () => {
    expect(controlChecks(srotaRequest())[0].status).toBe('PASS');
    expect(controlChecks(srotaRequest({ noc_controls: { arbitration: 'islip' } }))[0].status).toBe('PASS');
  });

  it('fails round-robin, which the authored router execution refuses', () => {
    const checks = controlChecks({ ...srotaRequest(), noc_controls: { arbitration: 'round_robin' } });
    expect(checks[0].status).toBe('FAIL');
    expect(checks[0].detail).toContain('iSLIP only');
  });

  it('accepts the compiler canonical iSLIP spellings', () => {
    expect(controlChecks({ ...srotaRequest(), noc_controls: { arbitration: ' iSLIP ' } })[0].status).toBe('PASS');
  });
});

describe('RTL reach', () => {
  it('marks the address map and buffer depth as reaching the preview', () => {
    const rows = rtlReachRows(srotaRequest(), compileResult());
    expect(rows.find(row => row.control === 'Agent address map')?.status).toBe('reaches-preview');
    expect(rows.find(row => row.control === 'Input buffer depth')?.status).toBe('reaches-preview');
  });

  it('marks link width and the routing law as compiled-only', () => {
    const rows = rtlReachRows(srotaRequest(), compileResult());
    expect(rows.find(row => row.control === 'Link width')?.status).toBe('compiled-only');
    expect(rows.find(row => row.control === 'Routing law')?.status).toBe('compiled-only');
  });

  it('reports a missing compile result instead of inventing a certificate', () => {
    const checks = certificateChecks(null);
    expect(checks[0]).toMatchObject({ id: 'certificate-missing', status: 'WARN' });
  });
});

describe('aggregate analysis', () => {
  it('counts every check once and keeps the address coverage', () => {
    const analysis = buildFabricAnalysis(srotaRequest(), mesh(), compileResult());
    expect(analysis.checks.length).toBeGreaterThan(8);
    expect(analysis.counts.PASS + analysis.counts.WARN + analysis.counts.FAIL + analysis.counts['N/A']).toBe(analysis.checks.length);
    expect(analysis.coverage.mappedBytes).toBe(0x2000_0000n);
    expect(analysis.rtlRows.length).toBeGreaterThan(8);
  });
});
