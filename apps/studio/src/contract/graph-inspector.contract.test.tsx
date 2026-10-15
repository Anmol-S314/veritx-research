/** Unified node and edge inspectors (M2-22/M2-23): stable sections, with
 *  node reset/power domain assignment and edge domain-crossing + physical. */
import { cleanup, fireEvent, render, screen } from '@testing-library/react';
import { afterEach, describe, expect, it } from 'vitest';
import GraphLoom from '../pages/loom/GraphLoom';
import type { LoomProject } from '../graph/project';

const key = (scope: string): string => `loom-graph-autosave-v1:${scope}`;
const seed: LoomProject = {
  schemaVersion: 1,
  compilerSemanticsVersion: 1,
  presetHint: null,
  nodes: [
    { id: 'n1', x: 0, y: 0, role: 'compute_tile', ports: 5, clock: 'clk_1' },
    { id: 'n2', x: 200, y: 0, role: 'hbm_controller', ports: 5, clock: 'clk_1' },
  ],
  edges: [{ id: 'e1', src: 'n1', dst: 'n2', width: 512, pipelineStages: 1, vcClass: 0 }],
  domains: {
    clocks: [{ id: 'clk_1', frequencyHz: null, source: null }],
    resets: [{ id: 'rst_1', polarity: 'active_low', asynchronous: true }],
    powers: [{ id: 'pd_1', nominalVoltageV: 0.8, canPowerOff: false }],
    portAssignments: [],
  },
};

const read = (scope: string): LoomProject => {
  const parsed = JSON.parse(localStorage.getItem(key(scope))!) as { graph?: LoomProject };
  return (parsed.graph ?? parsed) as LoomProject;
};

afterEach(() => { cleanup(); localStorage.clear(); });

describe('M2-22: node inspector sections', () => {
  it('assigns reset and power domains from the inspector', () => {
    localStorage.setItem(key('insp-node'), JSON.stringify(seed));
    render(<GraphLoom projectId="insp-node" draftRequest={null} />);
    fireEvent.click(screen.getByTestId('node-n1'));

    expect(screen.getByLabelText('inspector reset domain')).toBeTruthy();
    fireEvent.change(screen.getByLabelText('inspector reset domain'), { target: { value: 'rst_1' } });
    fireEvent.change(screen.getByLabelText('inspector power domain'), { target: { value: 'pd_1' } });

    const saved = read('insp-node').nodes.find((n) => n.id === 'n1')!;
    expect(saved.resetDomain).toBe('rst_1');
    expect(saved.powerDomain).toBe('pd_1');
  });
});

describe('M2-23: edge inspector sections', () => {
  it('authors a domain-crossing policy and a physical lock', () => {
    localStorage.setItem(key('insp-edge'), JSON.stringify(seed));
    render(<GraphLoom projectId="insp-edge" draftRequest={null} />);
    fireEvent.click(screen.getByTestId('link-e1'));

    fireEvent.change(screen.getByLabelText('inspector clock crossing'), { target: { value: 'synchronizer' } });
    expect(read('insp-edge').edges[0]!.domainCrossing?.clock?.policy).toBe('synchronizer');

    fireEvent.click(screen.getByLabelText('inspector link locked'));
    expect(read('insp-edge').edges[0]!.physical?.locked).toBe(true);

    // Clearing the only policy removes the crossing object entirely.
    fireEvent.change(screen.getByLabelText('inspector clock crossing'), { target: { value: '' } });
    expect(read('insp-edge').edges[0]!.domainCrossing).toBeUndefined();
  });
});
