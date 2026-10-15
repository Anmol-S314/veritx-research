import { cleanup, fireEvent, render, screen } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';
import DomainsLoom from '../pages/loom/DomainsLoom';
import type { LoomData } from '../pages/loom/data';
import type { LoomSelectionStore } from '../pages/loom/selectionStore';

afterEach(() => cleanup());

describe('power-domain crossing view', () => {
  it('lists derived power crossings as unresolved without power-intent policy', () => {
    const data = {
      projectId: 'p1', project: null, design: null, designHash: null, draftRequest: null,
      reloadDraft: () => undefined,
      agents: [
        { kind: 'compute_tile', count: 1, data_width: 64, addr_width: 32, protocol: 'AXI', clock_domain: 'clk0', power_domain: 'pwr0' },
        { kind: 'compute_tile', count: 1, data_width: 64, addr_width: 32, protocol: 'AXI', clock_domain: 'clk0', power_domain: 'pwr1' },
      ],
      revisionId: 'r1', basedOnRevisionId: 'r1', dirty: false,
      topology: { result: { state: 'ready', data: {
        contract_version: 1, revision_id: 'r1', design_hash: 'd', topology_hash: 't', attachment_hash: 'a',
        family: 'mesh', routers: [
          { router_id: 0, coordinates: [0, 0], seat_capacity: 1 },
          { router_id: 1, coordinates: [0, 1], seat_capacity: 1 },
        ],
        endpoints: [
          { endpoint_id: 10, kind: 'compute_tile', group_index: 0, instance_index: 0, router_id: 0, port_id: 0 },
          { endpoint_id: 11, kind: 'compute_tile', group_index: 1, instance_index: 0, router_id: 1, port_id: 0 },
        ],
        channels: [{ channel_id: 4, src_router: 0, src_port: 1, dst_router: 1, dst_port: 1, width_bits: 64, latency_cycles: 1 }],
        physical_links: [], counts: { routers: 2, channels: 1, seats: 2, endpoints: 2 },
      } } },
    } as unknown as LoomData;
    const sel = {
      selection: { mode: 'empty' }, rejected: [], select: vi.fn(), choose: vi.fn(), drop: vi.fn(),
      clear: vi.fn(), href: vi.fn(), shareUrl: '', copy: vi.fn(), copied: false,
    } as unknown as LoomSelectionStore;

    render(<DomainsLoom data={data} sel={sel} />);
    fireEvent.click(screen.getByRole('tab', { name: 'Power crossings (1)' }));
    expect(screen.getByText('Derived power-domain crossings')).toBeTruthy();
    const crossingTable = screen.getByRole('table').textContent ?? '';
    expect(crossingTable).toContain('pwr0 → pwr1');
    expect(crossingTable).toContain('UNRESOLVED · no power-intent/level-shift policy artifact');
    expect(screen.getByText('authored (base agents[].power_domain)')).toBeTruthy();
    expect(screen.getByText(/Power crossings remain unresolved until explicit power intent/)).toBeTruthy();

    const noAttachment = { ...data, topology: { result: { state: 'ready', data: null } } } as unknown as LoomData;
    cleanup();
    render(<DomainsLoom data={noAttachment} sel={sel} />);
    expect(screen.getByRole('tab', { name: 'Power crossings (—)' })).toBeTruthy();
    fireEvent.click(screen.getByRole('tab', { name: 'Power crossings (—)' }));
    expect(screen.getByText(/certified topology attachment; channel domain boundaries cannot be derived/)).toBeTruthy();
  });
});
