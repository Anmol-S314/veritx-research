import { describe, expect, it } from 'vitest';
import customGraph from '../graph/fixtures/custom-graph.json';
import mesh8x8 from '../graph/fixtures/mesh-8x8.json';
import multiDomain from '../graph/fixtures/multi-domain.json';
import floorplannedGraph from '../graph/fixtures/floorplanned-graph.json';
import workloadGraph from '../graph/fixtures/workload-bound-graph.json';
import { GraphHistory } from '../graph/history';
import { parseProject, serializeProject, validateProject } from '../graph/project';

const FIXTURES = [
  ['custom-graph.json', customGraph],
  ['mesh-8x8.json', mesh8x8],
  ['multi-domain.json', multiDomain],
  ['floorplanned-graph.json', floorplannedGraph],
  ['workload-bound-graph.json', workloadGraph],
] as const;

function loadFixture(source: typeof FIXTURES[number][1]) {
  const raw = JSON.stringify(source);
  return { raw, project: parseProject(raw) };
}

describe('M0 golden project fixtures', () => {
  it('stores and validates all required project variants', () => {
    const projects = FIXTURES.map(([, source]) => loadFixture(source).project);
    expect(projects.map((p) => [p.nodes.length, p.edges.length])).toEqual([
      [4, 3], [64, 112], [8, 8], [8, 8], [8, 8],
    ]);
    expect(projects.map((project) => validateProject(project))).toEqual([[], [], [], [], []]);
    expect(projects[0].access).toBeDefined();
    expect(projects[2].domains).toBeDefined();
    expect(projects[2].firewall).toBeDefined();
    expect(projects[3].floorplan).toBeDefined();
    expect(projects[4].workload).toBeDefined();
    expect(projects[4].vcConfig).toMatchObject({
      virtualChannels: expect.arrayContaining([expect.objectContaining({ id: 'vc-collective', depth: 8, class: 'collective', escape: true })]),
      trafficClassMap: expect.arrayContaining([expect.objectContaining({ trafficClass: 'collective', vcId: 'vc-collective', qos: 3 })]),
      arbitration: { policy: 'weighted_round_robin', weightByTrafficClass: { collective: 4, best_effort: 1 } },
    });
  });

  it.each(FIXTURES)('edit/save/reload preserves semantic state: %s', (_name, source) => {
    const { project } = loadFixture(source);
    const history = new GraphHistory(project);
    const first = history.current().nodes[0];
    const edited = history.apply({ type: 'move_node', id: first.id, x: first.x + 1, y: first.y + 2 });
    expect(edited.refused).toBeNull();
    const saved = serializeProject(history.current());
    const reloaded = parseProject(saved);
    expect(serializeProject(reloaded)).toBe(saved);
    expect(reloaded.nodes[0]).toMatchObject({ id: first.id, x: first.x + 1, y: first.y + 2 });
    expect(reloaded.edges.map((edge) => edge.id)).toEqual(project.edges.map((edge) => edge.id));
    expect(validateProject(reloaded)).toEqual([]);
  });
});
