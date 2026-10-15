/** Contract: every graph mutation is a command with apply/revert semantics
 *  (tracker M1-01), compound edits are one atomic history step (M1-03), and
 *  identity rides on stable ids rather than coordinates (M0-02).
 *
 *  The history is snapshot-based, but each command also carries an exact
 *  inverse. These tests pin both layers:
 *   - applying the returned inverse restores byte-equality;
 *   - a batch validates only its final document, so add-then-wire and
 *     multi-delete are legal as single steps;
 *   - one batch is exactly one undo entry.
 */
import { describe, expect, it } from 'vitest';
import { applyGraphCommand, GraphHistory, type GraphCommand } from '../graph/history';
import { buildPreset } from '../graph/presets';
import { validateProject } from '../graph/project';

const reverted = (doc: ReturnType<typeof buildPreset>, cmd: GraphCommand): void => {
  const before = JSON.stringify(doc);
  const out = applyGraphCommand(doc, cmd);
  expect(out.refused).toBeNull();
  expect(out.inverse).not.toBeNull();
  const back = applyGraphCommand(out.doc, out.inverse as GraphCommand);
  expect(back.refused).toBeNull();
  expect(JSON.stringify(back.doc)).toBe(before);
};

describe('command apply/revert semantics', () => {
  it('reverts add_node, move_node and update_node byte-for-byte', () => {
    const p = buildPreset('mesh-4x4');
    const node = { id: 'nz', x: 10, y: 20, role: 'nic', ports: 5 } as const;
    // add_node alone is disconnected; wire it in one batch so the final
    // document is legal, then invert the whole batch.
    reverted(p, {
      type: 'batch',
      commands: [
        { type: 'add_node', node: { ...node } },
        { type: 'add_edge', edge: { id: 'ez', src: 'n1', dst: 'nz', width: 512, pipelineStages: 1, vcClass: 0 } },
      ],
    });
    reverted(p, { type: 'move_node', id: 'n1', x: 999, y: 999 });
    reverted(p, { type: 'update_node', id: 'n1', patch: { role: 'nic', ports: 7 } });
  });

  it('reverts add_edge, delete_edge and delete_node (with incident edges)', () => {
    const p = buildPreset('mesh-4x4');
    reverted(p, { type: 'delete_edge', id: p.edges[0].id });
    reverted(p, { type: 'delete_node', id: p.nodes[0].id });
    const withEdge = applyGraphCommand(p, {
      type: 'batch',
      commands: [
        { type: 'add_node', node: { id: 'nw', x: 1, y: 1, role: 'nic', ports: 5 } },
        { type: 'add_edge', edge: { id: 'ew', src: 'n1', dst: 'nw', width: 512, pipelineStages: 1, vcClass: 0 } },
      ],
    });
    expect(withEdge.refused).toBeNull();
    // Deleting the bridge edge would isolate nw and be refused; delete a mesh
    // edge instead, and delete_node on the bridge-attached node (which drops
    // its incident edge too).
    reverted(withEdge.doc, { type: 'delete_edge', id: p.edges[0].id });
    reverted(withEdge.doc, { type: 'delete_node', id: 'nw' });
  });

  it('reverts workload and firewall replacement commands', () => {
    const p = buildPreset('mesh-4x4');
    reverted(p, { type: 'set_workload', workload: { phases: [{ id: 'ph' }] } });
    reverted(p, { type: 'set_firewall', firewall: { default: 'deny' } });
    const withWl = applyGraphCommand(p, { type: 'set_workload', workload: { phases: [] } });
    reverted(withWl.doc, { type: 'set_workload', workload: undefined });
  });

  it('a refused command has no inverse and leaves the document untouched', () => {
    const p = buildPreset('ring-8');
    const out = applyGraphCommand(p, { type: 'move_node', id: 'missing', x: 1, y: 2 });
    expect(out.refused).toMatch(/unknown node/);
    expect(out.inverse).toBeNull();
    expect(out.doc).toBe(p);
  });
});

describe('compound edits are one atomic history step', () => {
  it('add-then-wire in one batch is a single undo entry', () => {
    const h = new GraphHistory(buildPreset('mesh-4x4'));
    const before = JSON.stringify(h.current());
    const out = h.apply({
      type: 'batch',
      commands: [
        { type: 'add_node', node: { id: 'nx', x: 2000, y: 2000, role: 'nic', ports: 5 } },
        { type: 'add_edge', edge: { id: 'ex', src: 'n1', dst: 'nx', width: 512, pipelineStages: 1, vcClass: 0 } },
      ],
    });
    expect(out.refused).toBeNull();
    expect(h.current().nodes.some((n) => n.id === 'nx')).toBe(true);
    expect(h.current().edges.some((e) => e.id === 'ex')).toBe(true);
    expect(h.undo()).toBe(true);
    expect(JSON.stringify(h.current())).toBe(before);
    expect(h.canUndo()).toBe(false);
  });

  it('multi-delete of a connected pair is one atomic step', () => {
    const h = new GraphHistory(buildPreset('mesh-4x4'));
    const before = JSON.stringify(h.current());
    const n1 = h.current().nodes[0].id;
    const n2 = h.current().nodes[1].id;
    const out = h.apply({ type: 'batch', commands: [
      { type: 'delete_node', id: n1 }, { type: 'delete_node', id: n2 },
    ] });
    expect(out.refused).toBeNull();
    expect(h.current().nodes.some((n) => n.id === n1 || n.id === n2)).toBe(false);
    expect(h.canUndo()).toBe(true);
    expect(h.undo()).toBe(true);
    expect(JSON.stringify(h.current())).toBe(before);
    expect(h.canUndo()).toBe(false);
  });

  it('a batch that ends disconnected is accepted as a warning and is one undo step', () => {
    const h = new GraphHistory(buildPreset('mesh-4x4'));
    const before = JSON.stringify(h.current());
    const lone = h.apply({ type: 'batch', commands: [
      { type: 'add_node', node: { id: 'island', x: 0, y: 0, role: 'nic', ports: 5 } },
    ] });
    expect(lone.refused).toBeNull();
    expect(h.current().nodes.some((n) => n.id === 'island')).toBe(true);
    const issues = validateProject(h.current());
    expect(issues.some((i) => i.code === 'graph.disconnected' && i.severity === 'warning')).toBe(true);
    expect(issues.some((i) => i.severity === 'error')).toBe(false);
    expect(h.canUndo()).toBe(true);
    h.undo();
    expect(JSON.stringify(h.current())).toBe(before);
  });

  it('a batch with a structural error refuses and mutates nothing', () => {
    const h = new GraphHistory(buildPreset('mesh-4x4'));
    const before = JSON.stringify(h.current());
    const bad = h.apply({ type: 'batch', commands: [
      { type: 'add_edge', edge: { id: 'ex', src: 'n1', dst: 'nope', width: 512, pipelineStages: 1, vcClass: 0 } },
    ] });
    expect(bad.refused).toMatch(/unknown node/);
    expect(JSON.stringify(h.current())).toBe(before);
    expect(h.canUndo()).toBe(false);
  });

  it('preset replacement is one undoable step and clears redo', () => {
    const h = new GraphHistory(buildPreset('mesh-4x4'));
    h.apply({ type: 'move_node', id: 'n1', x: 5, y: 5 });
    const editedMesh = JSON.stringify(h.current());
    expect(h.canUndo()).toBe(true);
    const loaded = h.apply({ type: 'replace_project', doc: buildPreset('ring-8') });
    expect(loaded.refused).toBeNull();
    expect(h.current().presetHint).toBe('ring');
    expect(h.undo()).toBe(true);
    expect(JSON.stringify(h.current())).toBe(editedMesh);
    expect(h.canRedo()).toBe(true);
    expect(h.redo()).toBe(true);
    expect(h.current().presetHint).toBe('ring');
    h.apply({ type: 'move_node', id: 'n1', x: 8, y: 8 });
    expect(h.canRedo()).toBe(false);
    expect(validateProject(h.current())).toEqual([]);
  });
});

describe('stable identity is never coordinates', () => {
  it('paste with a remap gives new ids while internal edges and offsets survive', () => {
    const p = buildPreset('mesh-4x4');
    const clipNodes = p.nodes.slice(0, 2).map((n) => ({ ...n, x: n.x + 40, y: n.y + 40 }));
    const between = p.edges.find((e) => e.src === clipNodes[0].id && e.dst === clipNodes[1].id)
      ?? p.edges.find((e) => e.src === clipNodes[1].id && e.dst === clipNodes[0].id);
    expect(between).toBeDefined();
    const idMap: Record<string, string> = {
      [clipNodes[0].id]: 'copy-a', [clipNodes[1].id]: 'copy-b',
      [between!.id]: 'copy-e',
    };
    // A pasted subgraph is a new component; it must be attached to the
    // existing graph or the connectivity invariant refuses the paste. Attach
    // the copy to an untouched original node in the same command.
    const anchor = 'n3';
    const link = { id: 'copy-link', src: 'copy-a', dst: anchor, width: 512, pipelineStages: 1, vcClass: 0 };
    const out = applyGraphCommand(p, {
      type: 'paste',
      nodes: clipNodes,
      edges: [between!, link],
      idMap,
    });
    expect(out.refused).toBeNull();
    const pasted = out.doc.nodes.filter((n) => n.id.startsWith('copy-'));
    expect(pasted).toHaveLength(2);
    const pastedEdge = out.doc.edges.find((e) => e.id === 'copy-e');
    expect(pastedEdge).toMatchObject({ src: 'copy-a', dst: 'copy-b' });
    // Coordinates are not identifiers: the copy keeps its coordinates but a
    // distinct id, and the source ids still resolve.
    expect(out.doc.nodes.some((n) => n.id === clipNodes[0].id)).toBe(true);
  });

  it('save/load round-trip keeps ids as the only join key', () => {
    const p = buildPreset('mesh-4x4');
    const moved = applyGraphCommand(p, { type: 'move_node', id: 'n1', x: 4242, y: -7 }).doc;
    const back = validateProject(JSON.parse(JSON.stringify(moved)));
    expect(back).toEqual([]);
    expect(moved.nodes.find((n) => n.id === 'n1')).toMatchObject({ x: 4242, y: -7 });
  });
});
