/** Contract for the copy/paste subgraph path (tracker M1-10/M1-11).
 *
 * A translated copy of a selected subgraph is a NEW component by construction.
 * Connectivity is authoring-legal as a warning (M1-29): paste and duplicate
 * must be accepted with remapped ids, and only compile/run escalate the
 * disconnected document to a refusal. This test pins that policy.
 */
import { describe, expect, it } from 'vitest';
import { graphToDraftRequest } from '../graph/adapter';
import { applyGraphCommand } from '../graph/history';
import { buildPreset } from '../graph/presets';
import { validateProject } from '../graph/project';

describe('paste a translated subgraph', () => {
  const mesh = buildPreset('mesh-4x4');
  const sel = mesh.nodes.slice(0, 2);
  const between = mesh.edges[0];
  const idMap = { [sel[0].id]: 'c-a', [sel[1].id]: 'c-b', [between.id]: 'c-e' };

  it('accepts the copy as a new component with a disconnected warning', () => {
    const out = applyGraphCommand(mesh, {
      type: 'paste',
      nodes: sel.map((n) => ({ ...n, x: n.x + 40, y: n.y + 40 })),
      edges: [between],
      idMap,
    });
    expect(out.refused).toBeNull();
    expect(out.doc.nodes.some((n) => n.id === 'c-a')).toBe(true);
    expect(out.doc.nodes.some((n) => n.id === 'c-b')).toBe(true);
    // Source ids are preserved, so the copy did not overwrite the originals.
    expect(out.doc.nodes.some((n) => n.id === sel[0].id)).toBe(true);
    const issues = validateProject(out.doc);
    const disconnected = issues.find((i) => i.code === 'graph.disconnected');
    expect(disconnected?.severity).toBe('warning');
    expect(disconnected?.components).toHaveLength(2);
    expect(issues.some((i) => i.severity === 'error')).toBe(false);
  });

  it('is accepted and connected when the same command links the copy to the origin', () => {
    const out = applyGraphCommand(mesh, {
      type: 'paste',
      nodes: sel.map((n) => ({ ...n, x: n.x + 40, y: n.y + 40 })),
      edges: [between, { id: 'c-link', src: 'c-a', dst: 'n3', width: 512, pipelineStages: 1, vcClass: 0 }],
      idMap,
    });
    expect(out.refused).toBeNull();
    expect(out.doc.nodes.some((n) => n.id === 'c-a')).toBe(true);
    expect(validateProject(out.doc)).toEqual([]);
  });

  it('compile refuses a held disconnected paste until it is wired in', () => {
    const out = applyGraphCommand(mesh, {
      type: 'paste',
      nodes: sel.map((n) => ({ ...n, x: n.x + 40, y: n.y + 40 })),
      edges: [between],
      idMap,
    });
    expect(out.doc).not.toBeNull();
    expect(graphToDraftRequest(out.doc, { schema_version: 4 }).refused).toMatch(/disconnected/);
  });
});
