/** Domain overlay on the topology canvas (tracker M3-15).
 *
 *  Derived from the certified attachment × authored assignment; painted as a
 *  router colour and a legend. Presentation only — no clock tree or power
 *  intent is claimed. */
import { cleanup, render, screen } from '@testing-library/react';
import { afterEach, describe, expect, it } from 'vitest';
import FabricCanvas from '../components/FabricCanvas';
import { routerDomainPaint } from '../pages/loom/data';
import type { LoomData } from '../pages/loom/data';
import type { FabricModel } from '../fabricLayout';

afterEach(cleanup);

/** Four routers; three carry agents, one carries none. */
const data = {
  projectId: 'p1', project: null, design: null, designHash: null, draftRequest: null,
  reloadDraft: () => undefined,
  agents: [
    { kind: 'compute_tile', count: 1, data_width: 64, addr_width: 32, protocol: 'AXI', clock_domain: 'clk0', power_domain: 'pd0' },
    { kind: 'compute_tile', count: 1, data_width: 64, addr_width: 32, protocol: 'AXI', clock_domain: 'clk1', power_domain: 'pd0' },
    { kind: 'compute_tile', count: 1, data_width: 64, addr_width: 32, protocol: 'AXI', clock_domain: null, power_domain: 'pd0' },
  ],
  revisionId: 'r1', basedOnRevisionId: 'r1', dirty: false,
  topology: { result: { state: 'ready', data: {
    contract_version: 1, revision_id: 'r1', design_hash: 'd', topology_hash: 't', attachment_hash: 'a',
    family: 'mesh',
    routers: [0, 1, 2, 3].map((id) => ({ router_id: id, coordinates: [id, 0], seat_capacity: 1 })),
    endpoints: [
      { endpoint_id: 10, kind: 'compute_tile', group_index: 0, instance_index: 0, router_id: 0, port_id: 0 },
      { endpoint_id: 11, kind: 'compute_tile', group_index: 1, instance_index: 0, router_id: 1, port_id: 0 },
      { endpoint_id: 12, kind: 'compute_tile', group_index: 2, instance_index: 0, router_id: 2, port_id: 0 },
    ],
    channels: [],
    physical_links: [],
    counts: { routers: 4, channels: 0, seats: 3, endpoints: 3 },
  } } },
} as unknown as LoomData;

describe('M3-15: router domain paint', () => {
  it('labels each router from its seated agents, muted when undeclared or unseated', () => {
    const clock = routerDomainPaint(data, 'clock');
    expect(clock.byRouter.get(0)).toBe('clk0');
    expect(clock.byRouter.get(1)).toBe('clk1');
    expect(clock.byRouter.get(2)).toBe('undeclared');
    expect(clock.byRouter.get(3)).toBe('no agent');
  });

  it('reads the power overlay independently of the clock overlay', () => {
    const power = routerDomainPaint(data, 'power');
    expect(power.byRouter.get(0)).toBe('pd0');
    expect(power.byRouter.get(1)).toBe('pd0');
    expect(power.byRouter.get(3)).toBe('no agent');
  });

  it('joins the labels of a router whose agents span domains', () => {
    const mixed = {
      ...data,
      agents: [
        { kind: 'compute_tile', count: 1, data_width: 64, addr_width: 32, protocol: 'AXI', clock_domain: 'clk0', power_domain: null },
        { kind: 'compute_tile', count: 1, data_width: 64, addr_width: 32, protocol: 'AXI', clock_domain: 'clk1', power_domain: null },
      ],
      topology: { result: { state: 'ready', data: {
        contract_version: 1, revision_id: 'r1', design_hash: 'd', topology_hash: 't', attachment_hash: 'a',
        family: 'mesh',
        routers: [{ router_id: 0, coordinates: [0, 0], seat_capacity: 2 }],
        endpoints: [
          { endpoint_id: 10, kind: 'compute_tile', group_index: 0, instance_index: 0, router_id: 0, port_id: 0 },
          { endpoint_id: 11, kind: 'compute_tile', group_index: 1, instance_index: 0, router_id: 0, port_id: 0 },
        ],
        channels: [], physical_links: [],
        counts: { routers: 1, channels: 0, seats: 2, endpoints: 2 },
      } } },
    } as unknown as LoomData;
    expect(routerDomainPaint(mixed, 'clock').byRouter.get(0)).toBe('clk0+clk1');
  });
});

const model: FabricModel = {
  source: 'topology', family: 'mesh', shape: 'mesh',
  nodes: [
    { id: 0, row: 0, col: 0, seats: 1, attached: { compute_tile: 1 } },
    { id: 1, row: 0, col: 1, seats: 1, attached: { compute_tile: 1 } },
  ],
  edges: [], cols: 2, rows: 1, concentration: 1, linkWidth: 512,
  totals: { compute: 2, hbm: 0, nic: 0, edge: 0 },
  counts: { routers: 2, channels: 0, endpoints: 2, seats: 2 },
  topologyHash: null, revisionId: 'r1',
};

describe('M3-15: overlay rendering', () => {
  it('paints routers and shows a domain legend when a paint is supplied', () => {
    render(
      <FabricCanvas
        model={model}
        topology={null}
        domainPaint={{ kind: 'clock', byRouter: new Map([[0, 'clk0'], [1, 'clk1']]) }}
      />,
    );
    // Legend entries for each distinct label, with router counts.
    expect(screen.getByText(/clk0 \(1\)/)).toBeTruthy();
    expect(screen.getByText(/clk1 \(1\)/)).toBeTruthy();
    // The router rects carry an inline fill (the palette colour).
    const rects = document.querySelectorAll('.cv-router');
    expect(rects[0]!.getAttribute('style') ?? '').toContain('fill');
    expect(rects[1]!.getAttribute('style') ?? '').toContain('fill');
  });

  it('adds no paint when no overlay is requested', () => {
    render(<FabricCanvas model={model} topology={null} />);
    const rects = document.querySelectorAll('.cv-router');
    expect(rects[0]!.getAttribute('style')).toBeNull();
    expect(screen.queryByText(/clk0/)).toBeNull();
  });
});
