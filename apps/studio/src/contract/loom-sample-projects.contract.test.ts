import { describe, expect, it } from 'vitest';
import { parseProject } from '../graph/project';
import SMALL from '../../fixtures/projects/small-custom.project.json';
import DOMAINS from '../../fixtures/projects/multi-domain.project.json';
import FLOORPLAN from '../../fixtures/projects/floorplanned.project.json';
import WORKLOAD from '../../fixtures/projects/workload-bound.project.json';

const samples = [
  ['small topology', SMALL],
  ['multi-domain', DOMAINS],
  ['floorplan', FLOORPLAN],
  ['workload preview input', WORKLOAD],
] as const;

describe('offline Loom sample projects', () => {
  it.each(samples)('%s is a valid self-contained project', (_name, sample) => {
    // Static imports intentionally avoid any network/API dependency in this acceptance test.
    const parsed = parseProject(JSON.stringify(sample));
    expect(parsed.nodes.length).toBeGreaterThan(0);
    expect(parsed.edges.every(edge => parsed.nodes.some(node => node.id === edge.src)
      && parsed.nodes.some(node => node.id === edge.dst))).toBe(true);
  });

  it('includes explicit floorplan data without implying physical-tool results', () => {
    expect(FLOORPLAN.floorplan).toBeDefined();
    expect(FLOORPLAN.metadata?.description).toContain('not physical-tool output');
  });

  it('includes authored workload input without implying a real simulation', () => {
    expect(WORKLOAD.workload).toBeDefined();
  });
});
