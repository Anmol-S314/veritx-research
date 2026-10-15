/** Access-flow panel (M3-27): the verdict updates as the pair changes. */
import { cleanup, fireEvent, render, screen } from '@testing-library/react';
import { afterEach, describe, expect, it } from 'vitest';
import type { ReactElement } from 'react';
import { AccessFlowPanel } from '../pages/loom/AccessFlowPanel';
import { useGraphStore } from '../graph/store';
import type { LoomProject } from '../graph/project';

const key = (scope: string): string => `loom-graph-autosave-v1:${scope}`;
const seed: LoomProject = {
  schemaVersion: 1,
  compilerSemanticsVersion: 1,
  presetHint: null,
  nodes: [
    { id: 'n1', x: 0, y: 0, role: 'compute_tile', ports: 5 },
    { id: 'n2', x: 200, y: 0, role: 'compute_tile', ports: 5 },
    { id: 'n3', x: 400, y: 0, role: 'compute_tile', ports: 5 },
  ],
  edges: [
    { id: 'e1', src: 'n1', dst: 'n2', width: 512, pipelineStages: 1, vcClass: 0 },
    { id: 'e2', src: 'n2', dst: 'n3', width: 512, pipelineStages: 1, vcClass: 0 },
  ],
  routing: { policy: 'custom', rules: [{ src: 'n1', dst: 'n3', nextHop: 'n2' }, { src: 'n2', dst: 'n3', nextHop: 'n3' }] },
  firewall: { default: 'deny', rules: [{ src: 'n1', dst: 'n3', perm: 'RW' }] },
};

function Harness({ scope }: { scope: string }): ReactElement {
  const store = useGraphStore('mesh-8x8', scope);
  return <AccessFlowPanel store={store} />;
}

afterEach(() => { cleanup(); localStorage.clear(); });

describe('M3-27: access flow panel', () => {
  it('traces an authored allowed pair and denies an unlisted one', () => {
    localStorage.setItem(key('flow-ui'), JSON.stringify(seed));
    render(<Harness scope="flow-ui" />);

    // Default pair is n1 -> n2, which has no firewall rule.
    expect(screen.getByTestId('access-flow-verdict').textContent).toContain('DENIED');

    fireEvent.change(screen.getByLabelText('access flow target'), { target: { value: 'n3' } });
    const verdict = screen.getByTestId('access-flow-verdict');
    expect(verdict.textContent).toContain('PERMITTED');
    expect(verdict.textContent).toContain('authored RW');
    expect(screen.getByText('n1 → n2 → n3')).toBeTruthy();
  });
});
