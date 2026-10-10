import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { api } from '../api';
import type { DraftGeometryView } from '../api/types';
import DesignCanvas from '../components/DesignCanvas';

const doc = {
  schema_version: 4, topology: { kind: 'explicit', graph: { nodes: 3, links: [[0, 1]], link_attrs: { latency_ns: 1, bandwidth_GBs: 8 } } },
  agents: [{ kind: 'compute_tile', count: 1 }], workload: { tp: 1 },
  requirements: [{ binding: true }], noc_controls: { link_width: 64 },
};
const geometry: DraftGeometryView = {
  contract_version: 1, compile_check_status: 'NOT_RUN', design_hash: 'draft-only',
  topology: {
    family: 'custom', routers: [0, 1, 2].map(id => ({ router_id: id, coordinates: [id, 0], seat_capacity: 1 })),
    channels: [{ channel_id: 0, src_router: 0, dst_router: 1, width_bits: 64 }], shared_links: [],
  },
  endpoints: [{ endpoint_id: 0, router_id: 0, group_index: 0, instance_index: 0, kind: 'compute_tile' }],
};
beforeEach(() => { vi.spyOn(api, 'previewDesign').mockResolvedValue(structuredClone(geometry)); });
afterEach(() => { cleanup(); vi.restoreAllMocks(); });
async function ready(): Promise<void> {
  await screen.findByText('3 routers · 1 attached endpoints · 3 seats · compile checks pending');
}

function canvas(onChange = vi.fn(), onInspect = vi.fn()): void {
  render(<DesignCanvas projectId="p" doc={doc} onChange={onChange} onInspect={onInspect} />);
}

describe('one canonical draft canvas', () => {
  it('draws the unsaved canonical request, with no graph-store writes or automatic saves', async () => {
    const changed = vi.fn(); canvas(changed);
    await ready();
    expect(api.previewDesign).toHaveBeenCalledWith('p', doc);
    expect(screen.getByRole('group', { name: 'Draft router diagram' })).toBeTruthy();
    expect(changed).not.toHaveBeenCalled();
  });

  it('selects routers and inventory groups into the appropriate inspector', async () => {
    const inspect = vi.fn(); canvas(vi.fn(), inspect); await ready();
    fireEvent.click(screen.getByRole('button', { name: 'Router 0, 1 attached endpoints, 1 seats' }));
    expect(inspect).toHaveBeenLastCalledWith('fabric');
    expect(screen.getByText(/Individual router overrides are not supported/)).toBeTruthy();
    fireEvent.click(screen.getByRole('button', { name: '1 Compute tile' }));
    expect(inspect).toHaveBeenLastCalledWith('system', 0);
  });

  it('adds routers without turning them into invented compute agents', async () => {
    const changed = vi.fn(); canvas(changed); await ready();
    fireEvent.click(screen.getByRole('button', { name: 'Add router' }));
    expect(changed.mock.calls[0][0].topology.graph.nodes).toBe(4);
    for (const key of ['agents', 'workload', 'requirements', 'noc_controls']) {
      expect(changed.mock.calls[0][0][key]).toEqual(doc[key as keyof typeof doc]);
    }
  });

  it('connects explicit routers through the canonical links list', async () => {
    const changed = vi.fn(); canvas(changed); await ready();
    fireEvent.click(screen.getByRole('button', { name: 'Connect routers' }));
    fireEvent.click(screen.getByRole('button', { name: 'Router 0, 1 attached endpoints, 1 seats' }));
    fireEvent.click(screen.getByRole('button', { name: 'Router 2, 0 attached endpoints, 1 seats' }));
    expect(changed.mock.calls[0][0].topology.graph.links).toEqual([[0, 1], [0, 2]]);
  });

  it('edits supported per-link intent, never a phantom width or VC override', async () => {
    const changed = vi.fn(); canvas(changed); await ready();
    fireEvent.click(screen.getByRole('button', { name: 'Connection 0 to 1' }));
    fireEvent.change(screen.getByLabelText('Latency (ns)'), { target: { value: '2' } });
    expect(changed.mock.calls[0][0].topology.graph.links).toEqual([[0, 1, { latency_ns: 2 }]]);
    expect(screen.queryByLabelText('VC depth')).toBeNull();
    expect(screen.queryByLabelText('Per-link width')).toBeNull();
  });

  it('fails closed instead of drawing a stale local graph when preview refuses', async () => {
    vi.mocked(api.previewDesign).mockRejectedValue(new Error('inventory exceeds seat capacity'));
    canvas();
    await screen.findByText('inventory exceeds seat capacity');
    expect(screen.queryByRole('group', { name: 'Draft router diagram' })).toBeNull();
  });

  it('ignores a late preview for a superseded working copy', async () => {
    let resolveOld!: (value: DraftGeometryView) => void;
    vi.mocked(api.previewDesign).mockImplementationOnce(() => new Promise(resolve => { resolveOld = resolve; }));
    const props = { projectId: 'p', onChange: vi.fn(), onInspect: vi.fn() };
    const rendered = render(<DesignCanvas {...props} doc={doc} />);
    await waitFor(() => expect(api.previewDesign).toHaveBeenCalledTimes(1));
    rendered.rerender(<DesignCanvas {...props} doc={{ ...doc, noc_controls: { link_width: 128 } }} />);
    await ready();
    resolveOld({ ...geometry, topology: { ...geometry.topology, routers: [] } });
    await waitFor(() => expect(screen.getByRole('button', { name: 'Router 2, 0 attached endpoints, 1 seats' })).toBeTruthy());
  });
});
