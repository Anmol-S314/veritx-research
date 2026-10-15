/** Contract for the topology edit/save/reload flow (tracker M1-34):
 *  start from the 8x8 preset, add a node, wire it, change an edge, save and
 *  reload, and verify semantic equality of the whole project. */
import { describe, expect, it } from 'vitest';
import { GraphHistory } from '../graph/history';
import { buildPreset } from '../graph/presets';
import {
  canonicalizeProject, fingerprintProject, parseProject, serializeProject, validateProject,
} from '../graph/project';

describe('topology edit/save/reload flow (M1-34)', () => {
  it('adds, wires, edits, saves and reloads to the same project', () => {
    const h = new GraphHistory(buildPreset('mesh-8x8'));
    const startNodes = h.current().nodes.length;
    const startEdges = h.current().edges.length;

    // 1. add a node (authoring-legal warning until it is wired).
    expect(h.apply({ type: 'add_node', node: { id: 'extra', x: 2000, y: 2000, role: 'nic', ports: 5 } }).refused).toBeNull();
    // 2. wire it to n1.
    expect(h.apply({ type: 'add_edge', edge: { id: 'e-extra', src: 'n1', dst: 'extra', width: 512, pipelineStages: 1, vcClass: 0 } }).refused).toBeNull();
    // 3. change an existing edge.
    const e0 = h.current().edges[0];
    expect(h.apply({ type: 'update_edge', id: e0.id, patch: { width: 1024 } }).refused).toBeNull();

    // The edited graph is connected and validates clean; editing diverges to custom.
    expect(validateProject(h.current())).toEqual([]);
    expect(h.current().presetHint).toBeNull();
    expect(h.current().nodes).toHaveLength(startNodes + 1);
    expect(h.current().edges).toHaveLength(startEdges + 1);

    // 4. save then reload.
    const saved = serializeProject(h.current());
    const reloaded = parseProject(saved);

    // Semantic equality: identical canonical form, byte-identical re-serialization,
    // identical fingerprint.
    expect(JSON.parse(saved)).toEqual(canonicalizeProject(h.current()));
    expect(serializeProject(reloaded)).toBe(saved);
    expect(fingerprintProject(reloaded)).toBe(fingerprintProject(h.current()));

    // 5. undo/redo across the whole sequence restores exact states.
    const final = JSON.stringify(h.current());
    expect(h.undo()).toBe(true);
    expect(h.redo()).toBe(true);
    expect(JSON.stringify(h.current())).toBe(final);
  });

  it('a hand-built graph is refused until it is wired in', () => {
    const h = new GraphHistory(buildPreset('mesh-4x4'));
    h.apply({ type: 'add_node', node: { id: 'lonely', x: 9, y: 9, role: 'nic', ports: 4 } });
    expect(validateProject(h.current()).some((i) => i.code === 'graph.disconnected')).toBe(true);
    expect(() => serializeProject(h.current())).not.toThrow();
  });
});
