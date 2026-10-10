import { cleanup, render, screen } from '@testing-library/react';
import { afterEach, describe, expect, it } from 'vitest';
import ExecutionReadiness from '../components/CompileResult/ExecutionReadiness';
import type { PreflightView } from '../api';

afterEach(cleanup);
const preflight: PreflightView = {
  contract_version: 1, revision_id: 'r1', display_name: 'r1', backend: 'booksim_standalone',
  backend_profile: 'profile-from-server', network_clock_hz: 1_000_000_000,
  expected_evidence_tier: 'authenticated', route_observation_required: true,
  conservation_required: true, ready: true, reason: null,
  gates: [{ gate: 'backend', state: 'READY', reason: null }],
};
describe('compact compile readiness', () => {
  it('offers evaluation with technical checks closed by default', () => {
    const { container } = render(<ExecutionReadiness preflight={preflight} projectId="p" />);
    expect(screen.getByText('Ready to evaluate')).toBeTruthy();
    expect(screen.getByRole('link', { name: 'Evaluate revision' }).getAttribute('href')).toBe('/projects/p/simulate');
    expect(container.querySelector('details')!.open).toBe(false);
    expect((screen.getByRole('table').closest('details') as HTMLDetailsElement).open).toBe(false);
    expect(screen.queryByRole('heading', { name: 'Can I run this?' })).toBeNull();
  });
  it('keeps the exact blocker visible and does not claim ready', () => {
    render(<ExecutionReadiness preflight={{ ...preflight, ready: false,
      reason: 'backend binary missing', gates: [{ gate: 'backend', state: 'BLOCKED', reason: 'binary missing' }] }} projectId="p" />);
    expect(screen.getByText('backend binary missing')).toBeTruthy();
    expect(screen.queryByText('Ready to evaluate')).toBeNull();
    expect(screen.getByRole('link', { name: 'Choose analysis' })).toBeTruthy();
  });
});
