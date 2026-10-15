import { describe, expect, it } from 'vitest';
import { GraphHistory, type GraphCommand } from '../graph/history';
import { buildPreset } from '../graph/presets';

const link = (id: string, src: string, dst: string) => ({
  id, src, dst, width: 512, pipelineStages: 1, vcClass: 0,
});

const reversibleCommands = {
  move_node: () => ({ type: 'move_node', id: 'n1', x: 123, y: 456 }),
  delete_node: () => ({ type: 'delete_node', id: 'n1' }),
  update_node: () => ({ type: 'update_node', id: 'n1', patch: { role: 'nic', ports: 6 } }),
  add_edge: () => ({ type: 'add_edge', edge: link('undo-edge', 'n1', 'n3') }),
  delete_edge: () => ({ type: 'delete_edge', id: 'e1' }),
  update_edge: () => ({ type: 'update_edge', id: 'e1', patch: { width: 1024, pipelineStages: 2 } }),
  paste: () => ({
    type: 'paste',
    nodes: [{ id: 'undo-node', x: 900, y: 900, role: 'nic', ports: 2 }],
    edges: [link('undo-paste-edge', 'n1', 'undo-node')],
  }),
  set_workload: () => ({ type: 'set_workload', workload: { model: 'unit-test', steps: [1, 2] } }),
  set_firewall: () => ({ type: 'set_firewall', firewall: { default: 'deny', rules: [{ src: 'n1', dst: 'n2', perm: 'RO' }] } }),
} satisfies Record<Exclude<GraphCommand['type'], 'add_node'>, () => GraphCommand>;

describe('graph command undo/redo exact restoration', () => {
  it.each(Object.entries(reversibleCommands))('%s restores exact prior snapshot and replays exactly', (_name, makeCommand) => {
    const history = new GraphHistory(buildPreset('ring-8'));
    const before = JSON.stringify(history.current());
    const applied = history.apply(makeCommand());
    expect(applied.refused).toBeNull();
    const after = JSON.stringify(history.current());
    expect(after).not.toBe(before);
    expect(history.undo()).toBe(true);
    expect(JSON.stringify(history.current())).toBe(before);
    expect(history.redo()).toBe(true);
    expect(JSON.stringify(history.current())).toBe(after);
  });

  it('add_node restores the exact empty-project snapshot and replays exactly', () => {
    const history = new GraphHistory({ schemaVersion: 1, presetHint: null, nodes: [], edges: [] });
    const before = JSON.stringify(history.current());
    const applied = history.apply({
      type: 'add_node', node: { id: 'first', x: 0, y: 0, role: 'nic', ports: 2 },
    });
    expect(applied.refused).toBeNull();
    const after = JSON.stringify(history.current());
    expect(history.undo()).toBe(true);
    expect(JSON.stringify(history.current())).toBe(before);
    expect(history.redo()).toBe(true);
    expect(JSON.stringify(history.current())).toBe(after);
  });

  it('a refused isolated add_node in a nonempty graph changes no state or history', () => {
    const history = new GraphHistory(buildPreset('ring-8'));
    const before = JSON.stringify(history.current());
    expect(history.apply({
      type: 'add_node', node: { id: 'isolated', x: 0, y: 0, role: 'nic', ports: 2 },
    }).refused).toMatch(/disconnected/);
    expect(JSON.stringify(history.current())).toBe(before);
    expect(history.canUndo()).toBe(false);
  });
});
