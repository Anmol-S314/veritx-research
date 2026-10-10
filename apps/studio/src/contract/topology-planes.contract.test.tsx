/** Plane views render only evidence their source artifacts support. */
import { cleanup, render, screen, within } from '@testing-library/react';
import { afterEach, describe, expect, it } from 'vitest';
import {
  aggregateRouterTraffic,
  controlPlaneDeclaration,
  ControlPlanePanel,
  TrafficMatrixHeatmap,
} from '../pages/loom/TopologyPlanes';
import type { CompileResultView } from '../api/types';
import type { LoomData, Query } from '../pages/loom/data';
import type { CompiledSystemArtifact, TopologyView } from '../types';

afterEach(cleanup);

/** A frozen compile-result view that declares Plane C: the control-plane child
 *  is a hash and its binding scope is DECLARED_STRUCTURE_ONLY. */
const MULTI_PLANE_SYSTEM: CompiledSystemArtifact = {
  type: 'veritx/CompiledSystemArtifact',
  schema_version: 1,
  system_semantics_version: 1,
  design_identity: 'sha256:design',
  children: { legacy_control_plane: 'sha256:control' },
  scopes: { control_plane: 'DECLARED_STRUCTURE_ONLY' },
  system_hash: 'sha256:system',
  normalization_refusal: null,
};

/** Only `compileResult` is read by the control-plane panel, so the rest of the
 *  Loom workspace is elided and the shape asserted by the type. */
function loomWith(compiledSystem?: CompiledSystemArtifact): LoomData {
  const compileResult: Query<CompileResultView | null> = {
    result: {
      state: 'ready',
      data: { contract_version: 1, available: true, compiled_system: compiledSystem },
    },
  };
  return { compileResult } as unknown as LoomData;
}

describe('Telemetry heatmap', () => {
  it('renders measured flit counts with endpoint semantics', () => {
    render(<TrafficMatrixHeatmap matrix={[[0, 12], [3, 0]]} />);
    const table = screen.getByRole('table', {
      name: 'Measured flits by source and destination endpoint',
    });
    expect(within(table).getByRole('columnheader', { name: 'E0' })).toBeTruthy();
    expect(within(table).getByRole('rowheader', { name: 'E1' })).toBeTruthy();
    expect(within(table).getByRole('cell', { name: 'Endpoint 0 to endpoint 1: 12 flits' }).textContent)
      .toContain('12');
    expect(within(table).getByRole('cell', { name: 'Endpoint 1 to endpoint 0: 3 flits' }).textContent)
      .toContain('3');
    expect(within(table).getByRole('cell', { name: 'Endpoint 0 to endpoint 0: 0 flits' }).textContent)
      .toContain('0');
  });

  it('renders an all-zero measured matrix without dividing by zero', () => {
    render(<TrafficMatrixHeatmap matrix={[[0, 0], [0, 0]]} />);
    expect(screen.getByRole('cell', { name: 'Endpoint 0 to endpoint 1: 0 flits' })
      .querySelector('.loom-traffic-heat')?.getAttribute('style')).toContain('opacity: 0');
  });
});

describe('Router telemetry aggregation', () => {
  it('joins measured endpoint pairs through the certified attachment', () => {
    const topology = {
      contract_version: 1,
      revision_id: 'rev-1',
      design_hash: 'sha256:design',
      topology_hash: 'topology',
      attachment_hash: 'attachment',
      family: 'mesh',
      routers: [
        { router_id: 0, coordinates: [0, 0], seat_capacity: 1 },
        { router_id: 3, coordinates: [1, 0], seat_capacity: 2 },
      ],
      channels: [],
      physical_links: [],
      endpoints: [
        { endpoint_id: 7, kind: 'compute_tile', group_index: 0, instance_index: 0, router_id: 0, port_id: 0 },
        { endpoint_id: 41, kind: 'compute_tile', group_index: 0, instance_index: 1, router_id: 3, port_id: 0 },
        { endpoint_id: 99, kind: 'hbm_controller', group_index: 1, instance_index: 0, router_id: 3, port_id: 1 },
      ],
      counts: { routers: 2, channels: 0, seats: 3, endpoints: 3 },
    } satisfies TopologyView;
    const result = aggregateRouterTraffic([
      { src: 41, dst: 99, packets: 1, flits: 10 },
      { src: 99, dst: 7, packets: 1, flits: 3 },
      { src: 5, dst: 41, packets: 1, flits: 4 },
    ], topology);
    expect(result.rows).toEqual([
      { routerId: 0, sent: 0, received: 3 },
      { routerId: 3, sent: 13, received: 10 },
    ]);
    expect(result.unresolvedPairs).toHaveLength(1);
    expect(result.unresolvedFlits).toBe(4);
  });
});

describe('Control plane view', () => {
  it('states the artifact needed instead of drawing configuration as a plane', () => {
    render(<ControlPlanePanel />);
    expect(screen.getByText('Control plane — not visualized')).toBeTruthy();
    expect(screen.getByText(/independent, revision-bound control-plane artifact/)).toBeTruthy();
    expect(screen.getByText(/Nothing is estimated or drawn until that artifact exists/)).toBeTruthy();
  });

  it('reflects a declared Plane C structure without drawing or claiming it', () => {
    // The compile-result view carries the control-plane child as a hash when
    // the fabric declared Plane C (multi_plane_vc.py); a single-plane fabric
    // leaves it null. The panel states that declared structure and still
    // refuses the diagram; it makes no Plane C timing or traffic claim.
    const data = loomWith(MULTI_PLANE_SYSTEM);
    expect(controlPlaneDeclaration(data)).toEqual({
      declared: true, scope: 'DECLARED_STRUCTURE_ONLY',
    });
    expect(controlPlaneDeclaration(loomWith(undefined)).declared).toBe(false);

    render(<ControlPlanePanel data={data} />);
    expect(screen.getByText('Control plane — not visualized')).toBeTruthy();
    expect(screen.getByText('DECLARED_STRUCTURE_ONLY')).toBeTruthy();
    expect(screen.getByText(/second subnet/)).toBeTruthy();
    expect(screen.queryByText(/cycles|latency|flits|throughput|bandwidth/i))
      .toBeNull();
  });
});
