import { cleanup, render, screen, within } from '@testing-library/react';
import { afterEach, describe, expect, it } from 'vitest';
import { ControlPlaneInspector } from '../components/CompileResult/CompileResult';
import type { ControlPlaneGroup } from '../api/types';

afterEach(cleanup);

const declared: ControlPlaneGroup = {
  available: true,
  declared: true,
  scope: 'DECLARED_STRUCTURE_ONLY',
  claim: 'Plane C is declared.',
  subnet: {
    id: 1, k: 4, c: 2, vcs: ['REQ', 'RSP'], vc_count: 2, routing: 'xy',
    routing_class: 'SROTA_PLANEC_XY', scope: 'DECLARED_STRUCTURE_ONLY',
    artifact: 'srota/ControlPlane', artifact_hash: 'sha256:subnet',
  },
  class_to_subnet: {
    available: true,
    scope: 'DECLARED_STRUCTURE_ONLY',
    artifact: 'srota/MultiPlaneVCAssignment',
    artifact_hash: 'sha256:binding',
    rows: [{ traffic_class: 'SROTA_PLANEC_XY', subnet: 1 }],
  },
  editable: false,
};

describe('compile result control-plane inspector', () => {
  it('renders only declared structure and its artifact-bound class mapping', () => {
    const { container } = render(<ControlPlaneInspector group={declared} />);
    expect(screen.getByText('DECLARED_STRUCTURE_ONLY: declared structure only. This is not traffic or timing, does not visualize actual traffic, and is not editable. Control-plane traffic is not claimed to be simulated.')).toBeTruthy();
    expect(screen.getByText('REQ, RSP')).toBeTruthy();
    expect(screen.getAllByText('SROTA_PLANEC_XY')).toHaveLength(2);
    expect(screen.getByText('sha256:subnet')).toBeTruthy();
    expect(screen.getByText('sha256:binding')).toBeTruthy();
    const table = screen.getByRole('table');
    expect(within(table).getByRole('cell', { name: 'SROTA_PLANEC_XY' })).toBeTruthy();
    expect(within(table).getByRole('cell', { name: '1' })).toBeTruthy();
    expect(container.textContent).not.toMatch(/flits|latency|throughput/i);
  });

  it('shows backend absence reason for a single-plane design', () => {
    render(<ControlPlaneInspector group={{
      available: false, declared: false, scope: 'DECLARED_STRUCTURE_ONLY',
      reason: 'the design declares a single plane: no second subnet',
      subnet: null, class_to_subnet: null, editable: false,
    }} />);
    expect(screen.getByText('the design declares a single plane: no second subnet')).toBeTruthy();
    expect(screen.getByText('Scope: DECLARED_STRUCTURE_ONLY. Not editable.')).toBeTruthy();
  });
});
